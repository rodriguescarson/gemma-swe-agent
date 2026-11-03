"""Print the create-pod request body for the Linux-gate pod (2026-11-03), for the RunPod MCP tool create-pod.

The pod runs linux_test.sh's own image (python:3.12-slim; --py 3.13 for PY=3.13) as an x86_64 CPU pod, the
architecture Kaggle runs; Docker on the Mac ran arm64. Its start command:
  1. starts scripts/runpod/pod_watchdog.py first, so a pod whose setup fails still removes itself;
  2. installs openssh-server, rsync and git (what the shim needs beyond the image: sshd, the uploads, and the clone it
     seeds the repo from; the suite's own staging installs git and procps as well, as in Docker);
  3. writes the account keys RunPod injects as PUBLIC_KEY (startSsh) and starts sshd on 22/tcp (direct SSH, so rsync works).
cpu3g with 8 vCPU is 32 GB of RAM and at most 80 GB of container disk at $0.04 per vCPU-hour ($0.32/h, listed
2026-11-03). Usage: python3 scripts/runpod/pod_body.py [--py 3.12] [--name NAME] > body.json"""
import argparse
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
FLAVOR, VCPU, DISK_GB = "cpu3g", 8, 80
DATA_CENTERS = ["EU-RO-1", "EUR-IS-1"]        # CPU stock HIGH on 3 Nov; Europe is the shortest path from the Mac
MAX_HOURS, IDLE_MIN = 4, 40


def start_script() -> str:
    wd = (HERE / "pod_watchdog.py").read_text()
    assert "G4WD" not in wd
    return "\n".join([
        "set -u",
        "mkdir -p /root/g4m",
        "cat > /root/g4m/watchdog.py <<'G4WD'",
        wd.rstrip("\n"),
        "G4WD",
        "nohup python3 -u /root/g4m/watchdog.py > /root/g4m/watchdog.out 2>&1 &",
        "export DEBIAN_FRONTEND=noninteractive",
        "for _ in 1 2 3; do apt-get update -qq > /root/g4m/apt.log 2>&1 && "
        "apt-get install -y -qq --no-install-recommends openssh-server rsync git ca-certificates >> /root/g4m/apt.log 2>&1 && break; sleep 20; done",
        "mkdir -p /root/.ssh /run/sshd && chmod 700 /root/.ssh",
        "printf '%s\\n' \"${PUBLIC_KEY:-}\" > /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys",
        "ssh-keygen -A > /dev/null 2>&1",
        "/usr/sbin/sshd -e 2>> /root/g4m/sshd.log || echo 'sshd did not start' >> /root/g4m/sshd.log",
        "touch /root/g4m/ready",
        "sleep infinity",
    ]) + "\n"


def body(py: str = "3.12", name: str = "g4-linux-gate") -> dict:
    image = f"python:{py}-slim"
    return {
        "name": name,
        "image": image,
        "cpu": {"id": FLAVOR, "vcpuCount": VCPU},
        "cloud": "SECURE",
        "dataCenterIds": DATA_CENTERS,
        "disk": DISK_GB,
        "ports": ["22/tcp"],
        "startSsh": True,
        "env": {"G4_POD_IMAGE": image, "G4_POD_MAX_HOURS": str(MAX_HOURS), "G4_POD_IDLE_MIN": str(IDLE_MIN)},
        "args": json.dumps({"entrypoint": ["/bin/bash", "-c"], "cmd": [start_script()]}),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--py", default="3.12", choices=["3.12", "3.13"])
    ap.add_argument("--name", default="g4-linux-gate")
    a = ap.parse_args()
    print(json.dumps(body(a.py, a.name), indent=1))
