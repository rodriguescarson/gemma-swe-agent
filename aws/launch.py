"""Launch ONE EC2 machine for a gemma4-agent role (plan goofy-skipping-hearth, Step 5). Dry run unless --yes.

    python aws/launch.py ROLE --hours H --run s3://BUCKET/runs/ID --job 'CMD' [--spot] [--type T] [--az AZ|auto]
        [--disk-gb N] [--shared s3://BUCKET/shared] [--setup '...'] [--keep '...'] [--yes]

Roles: cpu-collect (c7i.xlarge | c7i.8xlarge, Ubuntu 24.04), train (g6e.2xlarge, L40S 48 GB), eval (g6.12xlarge, 4x L4 =
the Kaggle scorer, vLLM TP=4), teacher (g6e.12xlarge, 4x L40S, aws/jobs/g1_teacher.sh); GPU roles boot the AWS Deep
Learning Base AMI (Ubuntu 24.04), resolved from SSM. --max-usd refuses a launch whose worst case (timer x the highest
hourly price it can be billed) is above the cap.

Every launch, or it is refused (check_request runs on the exact dict sent to RunInstances):
  - InstanceInitiatedShutdownBehavior=terminate, so any OS shutdown ends the instance and its EBS;
  - user-data whose first command is `shutdown -h +N` (the hard timer: --hours is required, at most 24);
  - tags Project=gemma4-agent and Role=<role> on the instance and its volumes;
  - region us-east-1, an AMI resolved from SSM, gp3 EBS sized per role with DeleteOnTermination=true;
  - IMDSv2 only (hop limit 1, so a sandboxed test container cannot read the instance role's credentials).
Then aws/bootstrap.sh (embedded in the user-data) builds the role's envs, pulls in/ from the run prefix, runs --job, syncs
out/ to S3 and shuts the machine down itself. Without --yes nothing is created: the request is checked, read-only
preflights run, and RunInstances is called with DryRun=True (free).
"""
import argparse
import datetime as dt
import json
import math
import re
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import g4aws  # noqa: E402

VCPUS = {"c7i.xlarge": 4, "c7i.8xlarge": 32, "g6e.2xlarge": 8, "g6.12xlarge": 48, "g6e.12xlarge": 48}
QUOTA_CODES = {   # (on-demand, spot) vCPU quota codes per family class
    "g": ("L-DB2E81BA", "L-3819A6DF"),   # Running On-Demand / All Spot: G and VT instances
    "std": ("L-1216C47A", "L-34B43A08"),  # Running On-Demand / All Spot: Standard (A, C, D, H, I, M, R, T, Z)
}
PROFILE = "gemma4-agent-ec2"
VLLM_WHEEL = "vllm-0.19.1-cp38-abi3-manylinux_2_31_x86_64.whl"
S3_RE = re.compile(r"^s3://([a-z0-9][a-z0-9.-]{1,61}[a-z0-9])/([A-Za-z0-9._=/-]+?)/?$")
ENV_EOF, BOOT_EOF = "G4_JOB_ENV_EOF", "G4_BOOTSTRAP_EOF"
USER_DATA_MAX = 16384
LAUNCH_LOG = HERE / "launches.jsonl"   # one line per real launch (no secrets): instance, role, run, hours


class Refused(Exception):
    pass


def parse_s3(uri, what):
    m = S3_RE.match(uri or "")
    if not m:
        raise Refused(f"{what} must be s3://BUCKET/PREFIX (not the bucket root), got {uri!r}")
    return m.group(1), m.group(2).rstrip("/")


def timer_minutes(hours):
    if hours is None:
        raise Refused("--hours is required: the hard shutdown timer has no default")
    if not (0 < hours <= g4aws.MAX_HOURS):
        raise Refused(f"--hours must be in (0, {g4aws.MAX_HOURS}], got {hours}")
    return max(1, math.ceil(hours * 60))


def validate_args(a):
    if a.role not in g4aws.ROLES:
        raise Refused(f"unknown role {a.role!r}; one of {sorted(g4aws.ROLES)}")
    spec = g4aws.ROLES[a.role]
    a.type = a.type or spec["default_type"]
    if a.type not in spec["types"]:
        raise Refused(f"{a.type} is not allowed for role {a.role} (allowed: {spec['types']})")
    timer_minutes(a.hours)
    bucket, prefix = parse_s3(a.run, "--run")
    a.shared = (a.shared or f"s3://{bucket}/shared").rstrip("/")
    parse_s3(a.shared, "--shared")
    if not (a.job or "").strip():
        raise Refused("--job is required (the command bootstrap.sh runs in /root/g4)")
    a.disk_gb = a.disk_gb or spec["disk_gb"]
    if a.disk_gb < spec["disk_gb"] // 2:
        raise Refused(f"--disk-gb {a.disk_gb} is under half the role's {spec['disk_gb']} GB")
    if a.region != g4aws.REGION:
        raise Refused(f"region must be {g4aws.REGION}, got {a.region}")
    a.setup = spec["setup"] if a.setup is None else a.setup
    a.keep = spec["keep"] if a.keep is None else a.keep
    return bucket, prefix


def run_id(run_uri):
    return run_uri.rstrip("/").rsplit("/", 1)[-1]


def user_data(a, minutes, deadline):
    env = {
        "G4_ROLE": a.role, "G4_RUN": a.run.rstrip("/"), "G4_SHARED": a.shared, "G4_JOB": a.job, "G4_SETUP": a.setup,
        "G4_KEEP": a.keep, "G4_HOURS": str(a.hours), "G4_DEADLINE": deadline.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "G4_DEADLINE_EPOCH": str(int(deadline.timestamp())), "G4_SYNC_MIN": str(a.sync_min),
        "G4_STALL_MIN": str(a.stall_min), "G4_FINAL_SYNC_MIN": str(a.final_sync_min),
    }
    env_text = "".join(f"{k}={shlex.quote(v)}\n" for k, v in env.items())
    boot = (HERE / "bootstrap.sh").read_text()
    for delim in (ENV_EOF, BOOT_EOF):
        if delim in env_text or delim in boot:
            raise Refused(f"heredoc delimiter {delim} appears in the payload")
    return (
        "#!/bin/bash\n"
        f"shutdown -h +{minutes} 'gemma4-agent hard timer ({a.hours} h)' || shutdown -h now\n"
        f"# gemma4-agent role={a.role} run={a.run}: generated by aws/launch.py. The line above is the hard timer and must stay first.\n"
        "mkdir -p /opt/g4\n"
        f"cat > /opt/g4/job.env <<'{ENV_EOF}'\n{env_text}{ENV_EOF}\n"
        f"cat > /opt/g4/bootstrap.sh <<'{BOOT_EOF}'\n{boot.rstrip()}\n{BOOT_EOF}\n"
        "exec bash /opt/g4/bootstrap.sh\n"
    )


def tags(a, deadline, market):
    t = {"Project": g4aws.PROJECT, "Role": a.role, "Name": f"g4-{a.role}-{run_id(a.run)}", "Run": a.run.rstrip("/"),
         "Deadline": deadline.strftime("%Y-%m-%dT%H:%M:%SZ"), "HardStopHours": str(a.hours), "Market": market,
         "LaunchedBy": "aws/launch.py"}
    return [{"Key": k, "Value": v} for k, v in t.items()]


def build_request(a, image, subnet=None, now=None):
    """The exact RunInstances kwargs (no AWS calls). image = describe_images()["Images"][0] of the resolved AMI."""
    now = now or dt.datetime.now(dt.timezone.utc)
    minutes = timer_minutes(a.hours)
    deadline = now + dt.timedelta(minutes=minutes)
    spec = g4aws.ROLES[a.role]
    bdm = []
    for m in image.get("BlockDeviceMappings", []):
        if "Ebs" not in m:
            continue
        ebs = {"DeleteOnTermination": True, "VolumeType": "gp3", "Encrypted": True}
        if m["DeviceName"] == image["RootDeviceName"]:
            snap = int(m["Ebs"].get("VolumeSize") or 0)
            if a.disk_gb < snap:
                raise Refused(f"--disk-gb {a.disk_gb} is smaller than the AMI's {snap} GB root snapshot")
            ebs.update(VolumeSize=a.disk_gb, Iops=3000, Throughput=spec["throughput"])
        bdm.append({"DeviceName": m["DeviceName"], "Ebs": ebs})
    market = "spot" if a.spot else "on-demand"
    tag_list = tags(a, deadline, market)
    kinds = ["instance", "volume"] + (["spot-instances-request"] if a.spot else [])
    p = {
        "ImageId": image["ImageId"], "InstanceType": a.type, "MinCount": 1, "MaxCount": 1,
        "InstanceInitiatedShutdownBehavior": "terminate",
        "UserData": user_data(a, minutes, deadline),
        "BlockDeviceMappings": bdm,
        "IamInstanceProfile": {"Name": a.profile},
        "MetadataOptions": {"HttpTokens": "required", "HttpEndpoint": "enabled", "HttpPutResponseHopLimit": 1},
        "TagSpecifications": [{"ResourceType": k, "Tags": tag_list} for k in kinds],
    }
    if a.spot:
        so = {"SpotInstanceType": "one-time", "InstanceInterruptionBehavior": "terminate"}
        if a.max_spot_usd:
            so["MaxPrice"] = f"{a.max_spot_usd:.4f}"
        p["InstanceMarketOptions"] = {"MarketType": "spot", "SpotOptions": so}
    if subnet:
        p["SubnetId"] = subnet
    return p


def check_request(p, role, hours):
    """The last gate before RunInstances: every mandatory safety property, read back from the request itself."""
    miss = []
    if p.get("InstanceInitiatedShutdownBehavior") != "terminate":
        miss.append("InstanceInitiatedShutdownBehavior=terminate")
    minutes = timer_minutes(hours)
    lines = [ln for ln in (p.get("UserData") or "").splitlines() if ln.strip() and not ln.startswith("#")]
    m = re.match(r"^shutdown -h \+(\d+) ", lines[0]) if lines else None
    if not m or int(m.group(1)) != minutes or int(m.group(1)) > g4aws.MAX_HOURS * 60:
        miss.append(f"user-data whose first command is `shutdown -h +{minutes}`")
    if "exec bash /opt/g4/bootstrap.sh" not in (p.get("UserData") or ""):
        miss.append("bootstrap.sh in the user-data")
    if len((p.get("UserData") or "").encode()) > USER_DATA_MAX:
        miss.append(f"user-data under {USER_DATA_MAX} bytes")
    specs = {s.get("ResourceType"): {t["Key"]: t["Value"] for t in s.get("Tags", [])} for s in p.get("TagSpecifications", [])}
    for kind in ("instance", "volume"):
        t = specs.get(kind, {})
        if t.get("Project") != g4aws.PROJECT or t.get("Role") != role:
            miss.append(f"tags Project={g4aws.PROJECT} and Role={role} on the {kind}")
    if not str(p.get("ImageId", "")).startswith("ami-"):
        miss.append("an AMI resolved from SSM")
    if role not in g4aws.ROLES or p.get("InstanceType") not in g4aws.ROLES[role]["types"]:
        miss.append(f"an instance type allowed for {role}")
    bdm = p.get("BlockDeviceMappings") or []
    if not bdm or any(not b.get("Ebs", {}).get("DeleteOnTermination") for b in bdm):
        miss.append("EBS with DeleteOnTermination=true on every volume")
    if not any(b.get("Ebs", {}).get("VolumeSize") for b in bdm):
        miss.append("an explicitly sized root volume")
    if p.get("MinCount") != 1 or p.get("MaxCount") != 1:
        miss.append("exactly one instance")
    if (p.get("MetadataOptions") or {}).get("HttpTokens") != "required":
        miss.append("IMDSv2 (HttpTokens=required)")
    if not (p.get("IamInstanceProfile") or {}).get("Name"):
        miss.append("an instance profile (the box reaches S3 through it, never through keys)")
    mo = p.get("InstanceMarketOptions")
    if mo and (mo.get("SpotOptions", {}).get("InstanceInterruptionBehavior") != "terminate"
               or mo.get("SpotOptions", {}).get("SpotInstanceType") != "one-time"):
        miss.append("spot: one-time with InstanceInterruptionBehavior=terminate")
    if p.get("DryRun") is not None:
        miss.append("no DryRun key in the request (it is added only for the dry run)")
    if miss:
        raise Refused("missing: " + "; ".join(miss))
    return True


# ---------------------------------------------------------------------------------------------------- AWS (read-only)
def resolve_ami(sess, role):
    from botocore.exceptions import ClientError
    name = g4aws.SSM_DLAMI if g4aws.ROLES[role]["ami"] == "dlami" else g4aws.SSM_UBUNTU
    try:
        ami = sess.client("ssm").get_parameter(Name=name)["Parameter"]["Value"]
        images = sess.client("ec2").describe_images(ImageIds=[ami])["Images"]
    except ClientError as e:
        raise Refused(f"cannot resolve the AMI from {name}: {e.response['Error']['Code']}")
    if not images:
        raise Refused(f"{name} -> {ami}, which describe_images does not return")
    return images[0]


def spot_prices(ec2, itype):
    r = ec2.describe_spot_price_history(InstanceTypes=[itype], ProductDescriptions=["Linux/UNIX"],
                                        StartTime=dt.datetime.now(dt.timezone.utc))
    return {p["AvailabilityZone"]: float(p["SpotPrice"]) for p in r.get("SpotPriceHistory", [])}


def resolve_subnet(ec2, az):
    if not az:
        return None
    subs = ec2.describe_subnets(Filters=[{"Name": "availability-zone", "Values": [az]},
                                         {"Name": "default-for-az", "Values": ["true"]}])["Subnets"]
    if not subs:
        raise Refused(f"no default subnet in {az}")
    return subs[0]["SubnetId"]


def preflight(sess, a, bucket):
    """Read-only checks; returns a list of blockers (a real launch refuses on any)."""
    from botocore.exceptions import ClientError
    s3, ec2, blockers = sess.client("s3"), sess.client("ec2"), []

    def exists(b, key):
        try:
            s3.head_object(Bucket=b, Key=key)
            return True
        except ClientError:
            return False

    try:
        s3.head_bucket(Bucket=bucket)
        _, prefix = parse_s3(a.run, "--run")
        if not exists(bucket, f"{prefix}/in/code.tgz"):
            blockers.append(f"{a.run}/in/code.tgz is missing (python aws/stage.py code {a.run})")
        sb, sp = parse_s3(a.shared, "--shared")
        if "vllm" in a.setup.split() and not exists(sb, f"{sp}/wheelhouse/{VLLM_WHEEL}"):
            blockers.append(f"{a.shared}/wheelhouse/{VLLM_WHEEL} is missing (the organiser-patched vLLM; aws/README.md)")
        if "data" in a.setup.split() and not s3.list_objects_v2(Bucket=sb, Prefix=f"{sp}/raw/", MaxKeys=1).get("KeyCount"):
            blockers.append(f"{a.shared}/raw/ is empty (python aws/stage.py shared {a.shared} data/raw raw)")
        if "wheels" in a.setup.split() and not s3.list_objects_v2(Bucket=sb, Prefix=f"{sp}/raw/wheels/", MaxKeys=1).get("KeyCount"):
            blockers.append(f"{a.shared}/raw/wheels/ is empty (python aws/stage.py shared {a.shared} data/raw/wheels raw/wheels)")
        for key in g4aws.ROLES[a.role].get("inputs", []):
            if not exists(bucket, f"{prefix}/{key}"):
                blockers.append(f"{a.run}/{key} is missing (the role's job input; aws/README.md)")
    except ClientError as e:
        blockers.append(f"bucket {bucket}: {e.response['Error']['Code']} (create it: python aws/account_setup.py --bucket {bucket})")
    try:
        sess.client("iam").get_instance_profile(InstanceProfileName=a.profile)
    except ClientError as e:
        blockers.append(f"instance profile {a.profile}: {e.response['Error']['Code']} (python aws/account_setup.py)")
    fam = "g" if a.type.startswith("g") else "std"
    code = QUOTA_CODES[fam][1 if a.spot else 0]
    try:
        quota = sess.client("service-quotas").get_service_quota(ServiceCode="ec2", QuotaCode=code)["Quota"]["Value"]
    except ClientError as e:
        quota = None
        blockers.append(f"quota {code}: {e.response['Error']['Code']}")
    live = g4aws.project_instances(ec2, ["pending", "running"])
    used = sum(VCPUS.get(i["InstanceType"], 0) for i in live
               if (i["InstanceType"].startswith("g")) == (fam == "g") and (i.get("InstanceLifecycle") == "spot") == bool(a.spot))
    if quota is not None and used + VCPUS[a.type] > quota:
        blockers.append(f"vCPU quota {code} is {quota:g}; {a.type} needs {VCPUS[a.type]} on top of {used} in use")
    same = [i["InstanceId"] for i in g4aws.project_instances(ec2) if g4aws.tag(i, "Role") == a.role]
    if same and not a.allow_concurrent:
        blockers.append(f"a {a.role} instance is already live: {same} (--allow-concurrent to launch another)")
    return blockers


def dry_run(ec2, params):
    from botocore.exceptions import ClientError
    try:
        ec2.run_instances(DryRun=True, **params)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        return (True, "DryRunOperation: the request would have succeeded") if code == "DryRunOperation" else (False, f"{code}: {e.response['Error'].get('Message', '')}")
    return False, "DryRun returned without DryRunOperation (unexpected)"


def hourly(a, prices, worst=False):
    """-> (instance $/h, EBS $/h, total $/h). worst: the most this launch can be billed per hour (spot at its MaxPrice)."""
    od = g4aws.ON_DEMAND_USD_H[a.type]
    if a.spot:
        rate = (a.max_spot_usd or od) if worst else prices.get(a.az, od)
    else:
        rate = od
    ebs = a.disk_gb * g4aws.GP3_USD_GB_MONTH / 730 + max(0, g4aws.ROLES[a.role]["throughput"] - 125) * g4aws.GP3_USD_MBPS_MONTH / 730
    return rate, ebs, rate + ebs + g4aws.PUBLIC_IPV4_USD_H


def check_cap(a, prices):
    """--max-usd: the hard timer is the spend cap, so the worst case of timer x hourly price must fit under it."""
    if a.max_usd is None:
        return None
    worst = hourly(a, prices, worst=True)[2] * timer_minutes(a.hours) / 60
    if worst > a.max_usd:
        fit = int(a.max_usd / hourly(a, prices, worst=True)[2] * 4) / 4
        raise Refused(f"worst case ${worst:.2f} ({a.hours} h at up to ${hourly(a, prices, worst=True)[2]:.3f}/h) is over --max-usd "
                      f"{a.max_usd:g}; at most --hours {fit:g} fits")
    return worst


def summary(a, params, image, prices):
    az = a.az or "AWS's choice"
    rate, ebs, per_h = hourly(a, prices)
    return "\n".join([
        f"role {a.role}: {a.type} ({'spot' if a.spot else 'on-demand'}) in {az}, AMI {image['ImageId']} ({image.get('Name', '?')})",
        f"hard timer: shutdown -h +{timer_minutes(a.hours)} ({a.hours} h), then terminate (InstanceInitiatedShutdownBehavior=terminate)",
        f"disk: {a.disk_gb} GB gp3, DeleteOnTermination=true; run {a.run}; shared {a.shared}",
        f"setup: {a.setup or '-'} | keep: {a.keep or '-'} | job: {a.job}",
        f"cost: about ${per_h:.3f}/h (instance ${rate:.4f} + EBS ${ebs:.3f} + IPv4 ${g4aws.PUBLIC_IPV4_USD_H}); ceiling ${per_h * a.hours:.2f} for {a.hours} h",
        f"user-data: {len(params['UserData'].encode())} bytes",
    ])


def parse(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("role", choices=sorted(g4aws.ROLES))
    ap.add_argument("--hours", type=float, help=f"hard timer, required, at most {g4aws.MAX_HOURS}")
    ap.add_argument("--run", required=True, help="s3://BUCKET/runs/ID: in/ (code.tgz, overlay/) and out/")
    ap.add_argument("--job", required=True, help="shell command run in /root/g4 after setup")
    ap.add_argument("--type"); ap.add_argument("--spot", action="store_true")
    ap.add_argument("--max-spot-usd", type=float, help="spot price cap per hour (default: the on-demand price)")
    ap.add_argument("--az", default="auto", help="us-east-1x, or auto (spot: cheapest AZ now; on-demand: AWS's choice)")
    ap.add_argument("--disk-gb", type=int); ap.add_argument("--shared")
    ap.add_argument("--setup", help="override the role's setup steps (aws/g4aws.py ROLES)")
    ap.add_argument("--keep", help="override the role's repo paths synced to out/keep/")
    ap.add_argument("--sync-min", type=int, default=10, help="periodic sync of outputs to S3, minutes")
    ap.add_argument("--stall-min", type=int, default=30, help="no output change (and idle GPUs) for this long ends the job; 0 = off")
    ap.add_argument("--final-sync-min", type=int, default=20, help="how long the last sync may retry before the machine stops anyway")
    ap.add_argument("--max-usd", type=float, help="refuse unless timer x the worst hourly price fits under this cap (G1: 40)")
    ap.add_argument("--profile", default=PROFILE, help="IAM instance profile (S3 access for the box)")
    ap.add_argument("--region", default=g4aws.REGION)
    ap.add_argument("--allow-concurrent", action="store_true")
    ap.add_argument("--yes", action="store_true", help="really launch (spends money); without it: dry run only")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse(argv)
    try:
        bucket, _ = validate_args(a)
        sess = g4aws.session()
        ec2 = sess.client("ec2")
        if ec2.meta.region_name != g4aws.REGION:
            raise Refused(f"client region {ec2.meta.region_name} != {g4aws.REGION}")
        image = resolve_ami(sess, a.role)
        prices = spot_prices(ec2, a.type) if a.spot else {}
        if a.az == "auto":
            a.az = min(prices, key=prices.get) if prices else None
        if a.spot and a.max_spot_usd is None:
            a.max_spot_usd = g4aws.ON_DEMAND_USD_H[a.type]
        params = build_request(a, image, resolve_subnet(ec2, a.az))
        check_request(params, a.role, a.hours)
        worst = check_cap(a, prices)
        print(summary(a, params, image, prices))
        if worst is not None:
            print(f"cap: worst case ${worst:.2f} <= --max-usd {a.max_usd:g}")
        if prices:
            print("spot now:", ", ".join(f"{z} ${p:.4f}" for z, p in sorted(prices.items())))
        blockers = preflight(sess, a, bucket)
        for b in blockers:
            print("BLOCKER:", b)
        if not a.yes:
            ok, msg = dry_run(ec2, params)
            print(f"DRY RUN ({'ok' if ok else 'failed'}): {msg}")
            print("nothing was launched; add --yes to launch" + (" once the blockers are cleared" if blockers else ""))
            return 0 if ok and not blockers else 1
        if blockers:
            raise Refused(f"{len(blockers)} blocker(s) above")
        resp = ec2.run_instances(**params)
        iid = resp["Instances"][0]["InstanceId"]
        got = ec2.describe_instance_attribute(InstanceId=iid, Attribute="instanceInitiatedShutdownBehavior")
        if got.get("InstanceInitiatedShutdownBehavior", {}).get("Value") != "terminate":
            ec2.terminate_instances(InstanceIds=[iid])
            raise Refused(f"{iid} came up without shutdown behaviour terminate; terminated it")
        rec = {"time": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "instance": iid, "role": a.role,
               "type": a.type, "market": "spot" if a.spot else "on-demand", "az": a.az, "hours": a.hours, "run": a.run, "job": a.job}
        with open(LAUNCH_LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"LAUNCHED {iid}; watch: python aws/status.py; outputs: {a.run}/out/; stop early: python aws/teardown.py {iid} --yes")
        return 0
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
