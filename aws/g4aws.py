"""Shared constants and the boto3 session for the EC2 kit in aws/ (plan goofy-skipping-hearth, Step 5).

Keys: AWS_ACCESS_KEY / AWS_SECRET_KEY (Carson's names in ~/Projects/.env), or the standard AWS_ACCESS_KEY_ID /
AWS_SECRET_ACCESS_KEY when they are set in the environment. They are read in-process, handed to boto3.Session and never
printed, logged, exported or written anywhere. The machines themselves never see them: they reach S3 through an instance
profile (aws/README.md, "One-time setup").
"""
import datetime as dt
import os
from pathlib import Path

REGION = "us-east-1"
PROJECT = "gemma4-agent"
ENV_FILE = str(Path.home() / "Projects" / ".env")
MAX_HOURS = 24                       # the hard timer may never be set further out than this
LIVE_STATES = ["pending", "running", "stopping", "stopped", "shutting-down"]

# us-east-1 on-demand Linux $/h (AWS price list, 24 Oct 2026). Spot is usually 35-40% of these; status.py reads the live
# spot price where it can and falls back to these as an upper bound.
ON_DEMAND_USD_H = {
    "c7i.xlarge": 0.1785,
    "c7i.8xlarge": 1.428,
    "g6e.2xlarge": 2.24208,
    "g6.12xlarge": 4.6016,
    "g6e.12xlarge": 10.49264,
}
GP3_USD_GB_MONTH = 0.08
GP3_USD_MBPS_MONTH = 0.04            # throughput above the free 125 MB/s
PUBLIC_IPV4_USD_H = 0.005

# The AWS Deep Learning Base OSS NVIDIA driver AMI (Ubuntu 24.04) for GPU roles, plain Ubuntu 24.04 for the CPU role.
SSM_DLAMI = "/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-24.04/latest/ami-id"
SSM_UBUNTU = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"

# One entry per role. setup = the environments aws/bootstrap.sh builds before the job; keep = what it syncs to S3 out/
# besides /opt/g4/out (repo-relative); inputs = run-relative S3 keys a launch refuses without. disk_gb is the root gp3 volume.
ROLES = {
    "cpu-collect": {
        "types": ["c7i.xlarge", "c7i.8xlarge"], "default_type": "c7i.xlarge", "ami": "ubuntu",
        "disk_gb": 120, "throughput": 125, "setup": "docker harness buildenv data", "keep": "eval/collect eval/progress.log",
    },
    "train": {
        "types": ["g6e.2xlarge"], "default_type": "g6e.2xlarge", "ami": "dlami",
        "disk_gb": 250, "throughput": 500, "setup": "trainenv bf16", "keep": "runs",
    },
    "eval": {
        "types": ["g6.12xlarge"], "default_type": "g6.12xlarge", "ami": "dlami",
        "disk_gb": 200, "throughput": 500, "setup": "docker vllm harness buildenv data model", "keep": "eval/runs eval/progress.log",
    },
    # G1 teacher pilot (GAPS "G1 pre-registration"): two open teachers on the latest stable vLLM (NOT the scorer's patched
    # 0.19.1), weights on the 2x 1900 GB NVMe instance store; aws/jobs/g1_teacher.sh builds that side itself.
    "teacher": {
        "types": ["g6e.12xlarge"], "default_type": "g6e.12xlarge", "ami": "dlami",
        "disk_gb": 200, "throughput": 500, "setup": "docker wheels harness", "keep": "eval/g1",
        "inputs": ["in/overlay/data/heldout1k/harness_g1/tasks.jsonl"],
    },
}


def read_env_key(name, env_file=ENV_FILE):
    """$name, else the value of a ``name=...`` (or ``export name=...``) line in env_file; quotes stripped. Never logged."""
    v = (os.environ.get(name) or "").strip()
    if v:
        return v
    if not env_file:
        return None
    try:
        lines = Path(env_file).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        s = line.strip()
        if s.startswith("export "):
            s = s[7:].lstrip()
        k, eq, val = s.partition("=")
        if eq and k.strip() == name:
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            return val or None
    return None


def credentials(env_file=ENV_FILE):
    key = read_env_key("AWS_ACCESS_KEY_ID", None) or read_env_key("AWS_ACCESS_KEY", env_file)
    secret = read_env_key("AWS_SECRET_ACCESS_KEY", None) or read_env_key("AWS_SECRET_KEY", env_file)
    if not key or not secret:
        raise SystemExit(f"AWS_ACCESS_KEY / AWS_SECRET_KEY not in the environment or {env_file}")
    return key, secret


def session(env_file=ENV_FILE):
    import boto3
    key, secret = credentials(env_file)
    return boto3.Session(aws_access_key_id=key, aws_secret_access_key=secret, region_name=REGION)


def tag(inst, key, default=""):
    return next((t["Value"] for t in inst.get("Tags", []) if t["Key"] == key), default)


def project_instances(ec2, states=None):
    """Every instance tagged Project=gemma4-agent in the given states (default: anything not yet terminated)."""
    filters = [{"Name": "tag:Project", "Values": [PROJECT]},
               {"Name": "instance-state-name", "Values": states or LIVE_STATES}]
    out = []
    for page in ec2.get_paginator("describe_instances").paginate(Filters=filters):
        for r in page["Reservations"]:
            out.extend(r["Instances"])
    return out


def hours_since(t, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    return max(0.0, (now - t).total_seconds() / 3600)
