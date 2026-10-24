"""aws/ EC2 kit (plan goofy-skipping-hearth, Step 5) against a stubbed boto3: every launch carries
InstanceInitiatedShutdownBehavior=terminate, a `shutdown -h +N` hard timer as the user-data's first command, the
Project/Role tags, us-east-1, an SSM-resolved AMI and DeleteOnTermination EBS, or it is refused; nothing launches
without --yes. Also status, teardown, cost and the shell scripts. No test here talks to AWS."""
import datetime as dt
import importlib
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AWS = ROOT / "aws"
sys.path.insert(0, str(ROOT / "aws"))

DLAMI = {"ImageId": "ami-0dlami000000001", "Name": "Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04)",
         "RootDeviceName": "/dev/sda1",
         "BlockDeviceMappings": [{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 75, "DeleteOnTermination": True}},
                                 {"DeviceName": "/dev/sdb", "VirtualName": "ephemeral0"}]}
UBUNTU = {"ImageId": "ami-0ubuntu00000001", "Name": "ubuntu-noble-24.04", "RootDeviceName": "/dev/sda1",
          "BlockDeviceMappings": [{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 8, "DeleteOnTermination": True}}]}
NOW = dt.datetime(2026, 10, 24, 12, 0, tzinfo=dt.timezone.utc)
RUN = "s3://g4-test-bucket/runs/r1"


class ClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class Pager:
    def __init__(self, fn):
        self.fn = fn

    def paginate(self, **kw):
        yield self.fn(**kw)


class FakeEC2:
    def __init__(self, world):
        self.w = world
        self.meta = types.SimpleNamespace(region_name=world.region)

    def describe_images(self, ImageIds):
        return {"Images": [i for i in (DLAMI, UBUNTU) if i["ImageId"] in ImageIds]}

    def describe_spot_price_history(self, InstanceTypes, AvailabilityZone=None, **kw):
        h = [{"AvailabilityZone": z, "SpotPrice": str(p)} for z, p in self.w.spot.items() if AvailabilityZone in (None, z)]
        return {"SpotPriceHistory": h}

    def describe_subnets(self, Filters):
        az = next(f["Values"][0] for f in Filters if f["Name"] == "availability-zone")
        return {"Subnets": [{"SubnetId": f"subnet-{az[-1]}", "AvailabilityZone": az}]}

    def _describe(self, Filters=None, InstanceIds=None):
        out = []
        for i in self.w.instances:
            if InstanceIds is not None and i["InstanceId"] not in InstanceIds:
                continue
            ok = True
            for f in Filters or []:
                if f["Name"] == "instance-state-name":
                    ok &= i["State"]["Name"] in f["Values"]
                elif f["Name"].startswith("tag:"):
                    ok &= any(t["Key"] == f["Name"][4:] and t["Value"] in f["Values"] for t in i.get("Tags", []))
            if ok:
                out.append(i)
        self.w.describes += 1
        for i in self.w.instances:   # time passes between polls: shutting-down -> terminated
            if i["State"]["Name"] == "shutting-down":
                i["State"]["Name"] = "terminated"
        return {"Reservations": [{"Instances": out}] if out else []}

    def get_paginator(self, name):
        assert name == "describe_instances"
        return Pager(self._describe)

    def run_instances(self, **kw):
        self.w.run_calls.append(kw)
        if kw.get("DryRun"):
            raise ClientError(self.w.dry_run_code)
        return {"Instances": [{"InstanceId": "i-0new"}]}

    def describe_instance_attribute(self, InstanceId, Attribute):
        assert Attribute == "instanceInitiatedShutdownBehavior"
        return {"InstanceInitiatedShutdownBehavior": {"Value": self.w.live_sdb}}

    def terminate_instances(self, InstanceIds):
        self.w.terminated.append(list(InstanceIds))
        for i in self.w.instances:
            if i["InstanceId"] in InstanceIds:
                i["State"]["Name"] = "shutting-down"


class FakeSSM:
    def __init__(self, world):
        self.w = world

    def get_parameter(self, Name):
        if "deeplearning" in Name:
            return {"Parameter": {"Value": DLAMI["ImageId"]}}
        if "canonical/ubuntu/server/24.04" in Name:
            return {"Parameter": {"Value": UBUNTU["ImageId"]}}
        raise ClientError("ParameterNotFound")


class FakeS3:
    def __init__(self, world):
        self.w = world

    def head_bucket(self, Bucket):
        if Bucket not in self.w.buckets:
            raise ClientError("404")

    def head_object(self, Bucket, Key):
        if f"{Bucket}/{Key}" not in self.w.objects:
            raise ClientError("404")

    def list_objects_v2(self, Bucket, Prefix, MaxKeys=1000):
        n = sum(1 for k in self.w.objects if k.startswith(f"{Bucket}/{Prefix}"))
        return {"KeyCount": min(n, MaxKeys)}


class FakeIAM:
    def __init__(self, world):
        self.w = world

    def get_instance_profile(self, InstanceProfileName):
        if not self.w.profile:
            raise ClientError("NoSuchEntity")
        return {"InstanceProfile": {"Roles": []}}


class FakeQuotas:
    def __init__(self, world):
        self.w = world

    def get_service_quota(self, ServiceCode, QuotaCode):
        return {"Quota": {"Value": self.w.quota.get(QuotaCode, 0.0)}}


class FakeCE:
    def __init__(self, world):
        self.w = world

    def get_cost_and_usage(self, **q):
        self.w.ce_calls.append(q)
        return self.w.ce_pages[len(self.w.ce_calls) - 1]


class World:
    def __init__(self):
        self.region = "us-east-1"
        self.instances, self.run_calls, self.terminated, self.ce_calls, self.ce_pages = [], [], [], [], []
        self.spot = {"us-east-1a": 3.04, "us-east-1f": 1.73}
        self.buckets = {"g4-test-bucket"}
        self.objects = {"g4-test-bucket/runs/r1/in/code.tgz",
                        "g4-test-bucket/shared/wheelhouse/vllm-0.19.1-cp38-abi3-manylinux_2_31_x86_64.whl",
                        "g4-test-bucket/shared/raw/wheels/x.whl"}
        self.profile = True
        self.quota = {"L-DB2E81BA": 52.0, "L-3819A6DF": 52.0, "L-1216C47A": 32.0, "L-34B43A08": 32.0}
        self.dry_run_code = "DryRunOperation"
        self.live_sdb = "terminate"
        self.describes = 0
        self.sessions = 0

    def session(self, *a, **k):
        self.sessions += 1
        clients = {"ec2": FakeEC2, "ssm": FakeSSM, "s3": FakeS3, "iam": FakeIAM, "service-quotas": FakeQuotas, "ce": FakeCE}
        return types.SimpleNamespace(client=lambda name: clients[name](self))


@pytest.fixture
def world(monkeypatch, tmp_path):
    exc = types.ModuleType("botocore.exceptions")
    exc.ClientError = ClientError
    bc = types.ModuleType("botocore")
    bc.exceptions = exc
    monkeypatch.setitem(sys.modules, "botocore", bc)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", exc)
    import g4aws
    import launch
    w = World()
    monkeypatch.setattr(g4aws, "session", w.session)
    monkeypatch.setattr(launch, "LAUNCH_LOG", tmp_path / "launches.jsonl")
    return w


def args(role, *extra, hours="10", job="bash aws/train.sh full d1"):
    a = [role, "--run", RUN, "--job", job]
    if hours is not None:
        a += ["--hours", hours]
    return a + list(extra)


def dry_request(world, role, *extra, **kw):
    import launch
    rc = launch.main(args(role, *extra, **kw))
    calls = [c for c in world.run_calls]
    assert calls and all(c.get("DryRun") is True for c in calls), "only DryRun calls without --yes"
    return rc, calls[-1]


def tagmap(req, kind):
    spec = next(s for s in req["TagSpecifications"] if s["ResourceType"] == kind)
    return {t["Key"]: t["Value"] for t in spec["Tags"]}


# --------------------------------------------------------------------------------------------- the launch request
@pytest.mark.parametrize("role,itype,ami,disk", [
    ("cpu-collect", "c7i.xlarge", UBUNTU["ImageId"], 120),
    ("train", "g6e.2xlarge", DLAMI["ImageId"], 250),
    ("eval", "g6.12xlarge", DLAMI["ImageId"], 200),
])
def test_every_role_request_carries_every_safety_property(world, role, itype, ami, disk, capsys):
    rc, req = dry_request(world, role)
    assert rc == 0, capsys.readouterr()
    assert req["InstanceInitiatedShutdownBehavior"] == "terminate"
    assert req["InstanceType"] == itype and req["ImageId"] == ami
    assert req["MinCount"] == req["MaxCount"] == 1
    first = [ln for ln in req["UserData"].splitlines() if ln and not ln.startswith("#")][0]
    assert first.startswith("shutdown -h +600 ") and first.endswith("|| shutdown -h now")   # no timer -> power off now
    for kind in ("instance", "volume"):
        t = tagmap(req, kind)
        assert t["Project"] == "gemma4-agent" and t["Role"] == role
    ebs = [b["Ebs"] for b in req["BlockDeviceMappings"]]
    assert ebs and all(e["DeleteOnTermination"] for e in ebs)
    assert ebs[0]["VolumeSize"] == disk and ebs[0]["VolumeType"] == "gp3"
    assert req["MetadataOptions"]["HttpTokens"] == "required" and req["MetadataOptions"]["HttpPutResponseHopLimit"] == 1
    assert req["IamInstanceProfile"]["Name"] == "gemma4-agent-ec2"
    assert "InstanceMarketOptions" not in req
    assert len(req["UserData"].encode()) < 16384
    out = capsys.readouterr().out
    assert "DRY RUN (ok)" in out and "nothing was launched" in out


def test_ephemeral_mappings_are_left_to_the_ami(world):
    _, req = dry_request(world, "train")
    assert [b["DeviceName"] for b in req["BlockDeviceMappings"]] == ["/dev/sda1"]


@pytest.mark.parametrize("hours", [None, "0", "-1", "24.5", "48"])
def test_hours_is_required_and_at_most_24(world, hours, capsys):
    import launch
    assert launch.main(args("train", hours=hours)) == 2
    assert "REFUSED" in capsys.readouterr().err
    assert world.sessions == 0 and world.run_calls == []          # refused before any AWS call


def test_24_hours_is_allowed_and_fractional_hours_round_up(world):
    _, req = dry_request(world, "train", hours="24")
    assert "shutdown -h +1440 " in req["UserData"]
    _, req = dry_request(world, "train", hours="0.51")
    assert "shutdown -h +31 " in req["UserData"]


@pytest.mark.parametrize("extra", [["--type", "g6.12xlarge"], ["--type", "p5.48xlarge"]])
def test_wrong_instance_type_for_the_role_is_refused(world, extra, capsys):
    import launch
    assert launch.main(args("train", *extra)) == 2
    assert "not allowed for role train" in capsys.readouterr().err


def test_other_regions_are_refused(world, capsys):
    import launch
    assert launch.main(args("eval", "--region", "eu-west-1")) == 2
    world.region = "us-west-2"                                     # a session that resolved to another region
    assert launch.main(args("eval")) == 2
    assert "us-east-1" in capsys.readouterr().err
    assert world.run_calls == []


@pytest.mark.parametrize("run", ["s3://g4-test-bucket", "s3://g4-test-bucket/", "https://g4-test-bucket/runs/r1", "runs/r1"])
def test_run_must_be_an_s3_prefix(world, run, capsys):
    import launch
    assert launch.main(["eval", "--hours", "2", "--run", run, "--job", "true"]) == 2
    assert "s3://BUCKET/PREFIX" in capsys.readouterr().err


def test_a_root_disk_under_half_the_role_or_under_the_ami_snapshot_is_refused(world, capsys):
    import launch
    assert launch.main(args("train", "--disk-gb", "130")) == 0
    assert launch.main(args("train", "--disk-gb", "70")) == 2
    assert "under half the role's 250 GB" in capsys.readouterr().err
    a = launch.parse(args("train", "--disk-gb", "130"))
    launch.validate_args(a)
    big = {**DLAMI, "BlockDeviceMappings": [{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 200}}]}
    with pytest.raises(launch.Refused, match="root snapshot"):
        launch.build_request(a, big, now=NOW)


def test_spot_is_one_time_terminate_capped_at_on_demand_in_the_cheapest_az(world):
    _, req = dry_request(world, "eval", "--spot")
    so = req["InstanceMarketOptions"]["SpotOptions"]
    assert req["InstanceMarketOptions"]["MarketType"] == "spot"
    assert so == {"SpotInstanceType": "one-time", "InstanceInterruptionBehavior": "terminate", "MaxPrice": "4.6016"}
    assert req["SubnetId"] == "subnet-f"                           # us-east-1f is the cheapest in the stub
    assert tagmap(req, "spot-instances-request")["Project"] == "gemma4-agent"
    assert tagmap(req, "instance")["Market"] == "spot"


def test_job_env_survives_quoting(world, tmp_path):
    job = """bash aws/train.sh full "d 1" --lr '2e-4' && echo $HOME `x`; echo "it's" """
    _, req = dry_request(world, "train", job=job)
    m = re.search(r"<<'G4_JOB_ENV_EOF'\n(.*?)G4_JOB_ENV_EOF\n", req["UserData"], re.S)
    env = tmp_path / "job.env"
    env.write_text(m.group(1))
    out = subprocess.run(["bash", "-c", f'source "{env}"; printf %s "$G4_JOB"'], capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout == job
    assert "G4_RUN=s3://g4-test-bucket/runs/r1\n" in m.group(1) and "G4_SHARED=s3://g4-test-bucket/shared\n" in m.group(1)


def test_user_data_embeds_bootstrap_verbatim_and_runs_it(world):
    _, req = dry_request(world, "eval")
    boot = (AWS / "bootstrap.sh").read_text().rstrip()
    assert f"<<'G4_BOOTSTRAP_EOF'\n{boot}\nG4_BOOTSTRAP_EOF\n" in req["UserData"]
    assert req["UserData"].rstrip().endswith("exec bash /opt/g4/bootstrap.sh")


# ------------------------------------------------------------------------------------------------ check_request
def _good(world):
    import launch
    a = launch.parse(args("eval", "--spot"))
    launch.validate_args(a)
    a.max_spot_usd = 4.6
    return launch.build_request(a, DLAMI, "subnet-f", now=NOW)


def _drop_tag(kind, key):
    def f(p):
        for s in p["TagSpecifications"]:
            if s["ResourceType"] == kind:
                s["Tags"] = [t for t in s["Tags"] if t["Key"] != key]
    return f


MUTATIONS = {
    "no shutdown behaviour": lambda p: p.pop("InstanceInitiatedShutdownBehavior"),
    "shutdown behaviour stop": lambda p: p.update(InstanceInitiatedShutdownBehavior="stop"),
    "no timer": lambda p: p.update(UserData=re.sub(r"(?m)^shutdown -h \+\d+ .*\n", "", p["UserData"])),
    "timer not first": lambda p: p.update(UserData=p["UserData"].replace("#!/bin/bash\n", "#!/bin/bash\nmkdir -p /x\n", 1)),
    "timer mismatch": lambda p: p.update(UserData=p["UserData"].replace("shutdown -h +600 ", "shutdown -h +6000 ", 1)),
    "no Project tag": _drop_tag("instance", "Project"),
    "no Role tag on volumes": _drop_tag("volume", "Role"),
    "no volume tag spec": lambda p: p.update(TagSpecifications=[s for s in p["TagSpecifications"] if s["ResourceType"] != "volume"]),
    "EBS survives termination": lambda p: p["BlockDeviceMappings"][0]["Ebs"].update(DeleteOnTermination=False),
    "no EBS mapping": lambda p: p.update(BlockDeviceMappings=[]),
    "no AMI": lambda p: p.update(ImageId=""),
    "wrong type": lambda p: p.update(InstanceType="p5.48xlarge"),
    "two instances": lambda p: p.update(MaxCount=2),
    "IMDSv1": lambda p: p["MetadataOptions"].update(HttpTokens="optional"),
    "no instance profile": lambda p: p.pop("IamInstanceProfile"),
    "persistent spot": lambda p: p["InstanceMarketOptions"]["SpotOptions"].update(SpotInstanceType="persistent"),
    "spot hibernates": lambda p: p["InstanceMarketOptions"]["SpotOptions"].update(InstanceInterruptionBehavior="stop"),
    "no bootstrap": lambda p: p.update(UserData=p["UserData"].replace("exec bash /opt/g4/bootstrap.sh", "")),
    "DryRun key": lambda p: p.update(DryRun=False),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_check_request_refuses_each_missing_property(world, name):
    import launch
    p = _good(world)
    assert launch.check_request(p, "eval", 10.0)
    MUTATIONS[name](p)
    with pytest.raises(launch.Refused):
        launch.check_request(p, "eval", 10.0)


def test_check_request_refuses_a_role_mismatch(world):
    import launch
    with pytest.raises(launch.Refused):
        launch.check_request(_good(world), "train", 10.0)          # eval's type and tags under the train role


# ------------------------------------------------------------------------------------------- blockers and --yes
def test_yes_launches_exactly_once_and_verifies_the_live_shutdown_behaviour(world, capsys):
    import launch
    assert launch.main(args("train", "--yes")) == 0
    real = [c for c in world.run_calls if "DryRun" not in c]
    assert len(real) == 1 and not [c for c in world.run_calls if c.get("DryRun")]
    assert launch.check_request(real[0], "train", 10.0)
    assert "LAUNCHED i-0new" in capsys.readouterr().out
    rec = launch.LAUNCH_LOG.read_text()
    assert '"instance": "i-0new"' in rec and '"hours": 10.0' in rec


def test_a_capacity_error_is_a_clean_failure_not_a_traceback(world, monkeypatch, capsys):
    import launch
    def no_room(self, **kw):
        self.w.run_calls.append(kw)
        raise ClientError("DryRunOperation" if kw.get("DryRun") else "InsufficientInstanceCapacity")
    monkeypatch.setattr(FakeEC2, "run_instances", no_room)
    assert launch.main(args("train", "--yes")) == 1
    assert "LAUNCH FAILED InsufficientInstanceCapacity" in capsys.readouterr().err
    assert not launch.LAUNCH_LOG.exists()


def test_an_instance_that_comes_up_without_terminate_is_terminated(world, capsys):
    import launch
    world.live_sdb = "stop"
    assert launch.main(args("train", "--yes")) == 2
    assert world.terminated == [["i-0new"]]
    assert "terminated it" in capsys.readouterr().err


@pytest.mark.parametrize("breakage,needle", [
    (lambda w: w.buckets.clear(), "bucket g4-test-bucket"),
    (lambda w: w.objects.discard("g4-test-bucket/runs/r1/in/code.tgz"), "in/code.tgz is missing"),
    (lambda w: setattr(w, "profile", False), "instance profile gemma4-agent-ec2"),
    (lambda w: w.quota.update({"L-DB2E81BA": 0.0}), "vCPU quota L-DB2E81BA is 0"),
])
def test_blockers_stop_a_real_launch_and_fail_the_dry_run(world, breakage, needle, capsys):
    import launch
    breakage(world)
    assert launch.main(args("train")) == 1                         # dry run: reported, exit 1
    assert launch.main(args("train", "--yes")) == 2                # real: refused
    assert not [c for c in world.run_calls if "DryRun" not in c]
    out = capsys.readouterr()
    assert needle in out.out and "REFUSED" in out.err


def test_eval_needs_the_patched_vllm_wheel_in_shared(world, capsys):
    import launch
    world.objects.discard("g4-test-bucket/shared/wheelhouse/vllm-0.19.1-cp38-abi3-manylinux_2_31_x86_64.whl")
    assert launch.main(args("eval", "--yes")) == 2
    assert "organiser-patched vLLM" in capsys.readouterr().out
    assert launch.main(args("train", "--yes")) == 0                 # train does not install vLLM


def _instance(iid, role, state="running", spot=False, hours_ago=2.0, deadline="2026-10-24T20:00:00Z", project="gemma4-agent", itype="g6e.2xlarge"):
    return {"InstanceId": iid, "InstanceType": itype, "State": {"Name": state}, "LaunchTime": NOW - dt.timedelta(hours=hours_ago),
            "Placement": {"AvailabilityZone": "us-east-1f"}, **({"InstanceLifecycle": "spot"} if spot else {}),
            "Tags": [{"Key": "Project", "Value": project}, {"Key": "Role", "Value": role}, {"Key": "Deadline", "Value": deadline},
                     {"Key": "Run", "Value": RUN}]}


def test_a_second_live_instance_of_a_role_is_a_blocker(world, capsys):
    import launch
    world.instances.append(_instance("i-0old", "train"))
    assert launch.main(args("train", "--yes")) == 2
    assert "already live" in capsys.readouterr().out
    assert launch.main(args("train", "--yes", "--allow-concurrent")) == 0


def test_dry_run_failure_is_reported(world, capsys):
    import launch
    world.dry_run_code = "UnauthorizedOperation"
    assert launch.main(args("train")) == 1
    assert "DRY RUN (failed): UnauthorizedOperation" in capsys.readouterr().out


# ----------------------------------------------------------------------------------------------------- credentials
def test_keys_come_from_the_env_file_and_are_never_printed(monkeypatch, tmp_path, capsys):
    import g4aws
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY", "AWS_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nAWS_ACCESS_KEY=AKIATESTKEY000000000\nexport AWS_SECRET_KEY='s3cr3t/value+x'\n")
    seen = {}
    fake = types.ModuleType("boto3")
    fake.Session = lambda **kw: seen.update(kw) or types.SimpleNamespace(**kw)
    monkeypatch.setitem(sys.modules, "boto3", fake)
    g4aws.session(str(env))
    assert seen == {"aws_access_key_id": "AKIATESTKEY000000000", "aws_secret_access_key": "s3cr3t/value+x", "region_name": "us-east-1"}
    with pytest.raises(SystemExit) as e:
        g4aws.session(str(tmp_path / "missing.env"))
    out = capsys.readouterr()
    assert "s3cr3t" not in out.out + out.err + str(e.value)


def test_no_credentials_reach_the_machine():
    src = "".join((AWS / f).read_text() for f in ("bootstrap.sh", "train.sh", "preflight.sh", "health.sh"))
    for needle in ("AWS_ACCESS_KEY", "AWS_SECRET", "aws_secret_access_key", "Projects/.env"):
        assert needle not in src                                   # the box reaches S3 through its instance profile only


# ------------------------------------------------------------------------------------------------------- teardown
def test_teardown_lists_only_without_yes(world, monkeypatch, capsys):
    import teardown
    world.instances.append(_instance("i-0a", "train"))
    assert teardown.main(["--all"]) == 0
    assert world.terminated == [] and "would be terminated" in capsys.readouterr().out


def test_teardown_refuses_instances_without_the_project_tag(world):
    import teardown
    world.instances += [_instance("i-0a", "train"), _instance("i-0x", "train", project="other")]
    with pytest.raises(SystemExit, match="not tagged Project=gemma4-agent"):
        teardown.main(["i-0a", "i-0x", "--yes"])
    assert world.terminated == []


def test_teardown_terminates_then_verifies_with_describe(world, capsys):
    import teardown
    world.instances += [_instance("i-0a", "train"), _instance("i-0b", "eval", itype="g6.12xlarge"), _instance("i-0c", "eval", state="terminated")]
    assert teardown.main(["--role", "eval", "--yes"], sleep=lambda s: None) == 0
    assert world.terminated == [["i-0b"]]
    out = capsys.readouterr().out
    assert "i-0b: terminated" in out and "not yet terminated: ['i-0a']" in out


def test_teardown_reports_failure_when_an_instance_never_terminates(world, monkeypatch):
    import teardown
    world.instances.append(_instance("i-0a", "train"))
    monkeypatch.setattr(FakeEC2, "terminate_instances", lambda self, InstanceIds: self.w.terminated.append(InstanceIds))
    assert teardown.main(["i-0a", "--yes", "--timeout", "0"], sleep=lambda s: None) == 1


# --------------------------------------------------------------------------------------------------------- status
def test_status_rows_price_uptime_and_deadline(world, monkeypatch):
    import g4aws
    import status
    world.instances += [_instance("i-0a", "train", hours_ago=2.0), _instance("i-0b", "eval", spot=True, hours_ago=1.0, itype="g6.12xlarge"),
                        _instance("i-0z", "eval", state="terminated")]
    rs = {r["id"]: r for r in status.rows(FakeEC2(world), now=NOW)}
    assert set(rs) == {"i-0a", "i-0b"}                              # terminated only with --all
    ebs_train = 250 * g4aws.GP3_USD_GB_MONTH / 730
    assert rs["i-0a"]["uptime_h"] == 2.0 and rs["i-0a"]["usd_so_far"] == round(2 * (2.24208 + ebs_train), 2)
    assert rs["i-0b"]["market"] == "spot" and rs["i-0b"]["usd_h"] == round(1.73 + 200 * 0.08 / 730, 4)
    assert rs["i-0a"]["hours_left"] == 8.0


def test_status_says_so_when_nothing_runs(world, capsys):
    import status
    assert status.main([]) == 0
    assert "no Project=gemma4-agent instances" in capsys.readouterr().out


# ----------------------------------------------------------------------------------------------------------- cost
def _ce_group(service, rtype, amt):
    return {"Keys": [service, rtype], "Metrics": {"UnblendedCost": {"Amount": str(amt), "Unit": "USD"}}}


def test_cost_separates_credits_and_tax_and_follows_pages(world, capsys):
    import cost
    world.ce_pages = [
        {"ResultsByTime": [{"TimePeriod": {"Start": "2026-10-23"}, "Groups": [
            _ce_group("Amazon Elastic Compute Cloud - Compute", "Usage", 4.5), _ce_group("Amazon Bedrock", "Usage", 1.25),
            _ce_group("Amazon Elastic Compute Cloud - Compute", "Credit", -4.5), _ce_group("Amazon Bedrock", "Credit", -1.25)]}],
         "NextPageToken": "p2"},
        {"ResultsByTime": [{"TimePeriod": {"Start": "2026-10-24"}, "Groups": [
            _ce_group("Amazon Simple Storage Service", "Usage", 0.10), _ce_group("Tax", "Tax", 0.02)]}]},
    ]
    assert cost.main(["--days", "2", "--project"], today=dt.date(2026, 10, 24)) == 0
    q1, q2 = world.ce_calls
    assert q1["TimePeriod"] == {"Start": "2026-10-23", "End": "2026-10-25"} and q2["NextPageToken"] == "p2"
    assert q1["Filter"] == {"Tags": {"Key": "Project", "Values": ["gemma4-agent"]}}
    assert [g["Key"] for g in q1["GroupBy"]] == ["SERVICE", "RECORD_TYPE"]
    out = capsys.readouterr().out
    day1, day2 = [ln for ln in out.splitlines() if ln.startswith("2026-10-2")]
    assert "usage $     5.75" in day1 and "credits $    -5.75" in day1 and "CASH" not in day1
    assert "tax $   0.02" in day2 and "CASH CHARGED" in day2
    assert "cash after credits $0.12" in out


# --------------------------------------------------------------------------------------------- the shell scripts
SCRIPTS = sorted(AWS.glob("*.sh"))


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_shell_scripts_parse(path):
    r = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not installed")
@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_shellcheck(path):
    r = subprocess.run(["shellcheck", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


@pytest.mark.skipif(Path("/opt/g4/job.env").exists() or os.geteuid() == 0, reason="never execute bootstrap.sh on a job box or as root")
def test_bootstrap_refuses_to_run_outside_a_job_box():
    r = subprocess.run(["bash", str(AWS / "bootstrap.sh")], capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and "refusing" in r.stdout


def test_bootstrap_always_ends_in_sync_then_shutdown():
    s = (AWS / "bootstrap.sh").read_text()
    guard, trap = s.index("not a gemma4-agent EC2 job box"), s.index("trap finish EXIT")
    assert guard < trap < s.index("install_awscli\n") < s.index('setsid bash -c "$G4_JOB"')   # trap before any work
    fin = s[s.index("finish() {"):s.index("\nmain() {")]
    assert fin.index("final_sync") < fin.rindex("shutdown -h now")                       # artifacts leave first
    code = "\n".join(ln for ln in s.replace(fin, "").splitlines() if not ln.lstrip().startswith("#"))
    assert "shutdown -c" not in s and "shutdown -h now" not in code                      # the timer is never cancelled
    assert "trap 'TERMINATED=1; exit 143' TERM INT HUP" in s                               # a signal still runs finish
    assert 'exit 3; fi' in s and s.index("S3_OK=1") < s.index("JOB_START")                # S3 proven writable before the job
    assert "/run/systemd/shutdown/scheduled" in s                                         # re-arms a missing timer
    assert "ExecStop=/bin/bash /opt/g4/bootstrap.sh sync" in s                             # terminate / timer / spot still sync
    assert "FINAL_SYNC_FAILED" in s and "--dryrun" in s                                   # verified, bounded final sync


def test_bootstrap_installs_the_scorers_patched_vllm_like_the_pod():
    s, pod = (AWS / "bootstrap.sh").read_text(), (ROOT / "pod" / "bootstrap.sh").read_text()
    for pin in ('"vllm==0.19.1"', '"transformers==5.13.1"', '"tokenizers==0.22.1"', '"fastapi==0.118.0"', '"starlette==0.48.0"',
                "vllm-0.19.1-cp38-abi3-manylinux_2_31_x86_64.whl", "supports_lora", "google/gemma-4-31B-it-qat-w4a16-ct"):
        assert pin in s and pin in pod, pin
    assert "issubclass(" not in s and "google-adk" not in s


def test_bootstrap_keeps_the_pod_layout_the_reused_pod_scripts_expect():
    s = (AWS / "bootstrap.sh").read_text()
    assert "REPO=/root/g4" in s and "/root/venv" in s and "/root/models/g4" in s and "ln -sfn \"$REPO/data/raw/wheels\" /wheels" in s
    assert 'bash "$REPO/pod/harness_env.sh"' in s and 'bash "$REPO/pod/buildenv.sh"' in s
    assert "/root/hvenv" in (ROOT / "pod" / "harness_env.sh").read_text() and "cd /root/g4" in (ROOT / "pod" / "harness_env.sh").read_text()
    serve = (ROOT / "pod" / "serve.sh").read_text()
    assert "source /root/venv/bin/activate" in serve and "vllm serve /root/models/g4" in serve and "--port 8100" in serve
    assert "nvidia-smi -L | wc -l" in serve                         # TP=4 on the eval role's 4x L4
    for step in ("docker", "data", "vllm", "model", "harness", "buildenv", "trainenv", "bf16"):
        assert f"setup_{step}()" in s, step
    import g4aws
    for role, spec in g4aws.ROLES.items():
        for step in spec["setup"].split():
            assert f"setup_{step}()" in s, (role, step)


def test_the_hard_timer_is_never_more_than_24_hours():
    import g4aws
    import launch
    assert g4aws.MAX_HOURS == 24
    with pytest.raises(launch.Refused):
        launch.timer_minutes(24.01)


def test_aws_train_delegates_the_recipe_and_waits_in_the_foreground():
    a = subprocess.run(["bash", str(AWS / "train.sh"), "recipe", "60"], capture_output=True, text=True)
    b = subprocess.run(["bash", str(ROOT / "scripts" / "a6000" / "train.sh"), "recipe", "60"], capture_output=True, text=True)
    assert a.returncode == 0 and a.stdout == b.stdout != ""
    s = (AWS / "train.sh").read_text()
    assert 'while kill -0 "$PID"' in s and "summary.json" in s and "probe_report.json" in s and "TRAIN_FAILED" in s


def test_health_checks_one_tp4_server_by_default():
    s = (AWS / "health.sh").read_text()
    assert "${SERVE_PORTS:-8100}" in s and "nvidia-smi" not in s


def test_preflight_keeps_every_pod_gate():
    s = (AWS / "preflight.sh").read_text()
    for gate in ("compileall", "pytest", "supports_lora", "validate.py", "aws/health.sh", "--lora-modules", '"model":"main_lora"',
                 "PYTHONPYCACHEPREFIX", "PYTHONDONTWRITEBYTECODE=1"):
        assert gate in s, gate
    assert "hf auth" not in s and "runpodctl" not in s


def test_kit_modules_import_without_boto3(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)                 # boto3 is only imported inside session()
    for name in ("g4aws", "launch", "status", "teardown", "cost", "stage", "account_setup"):
        sys.modules.pop(name, None)
        importlib.import_module(name)
