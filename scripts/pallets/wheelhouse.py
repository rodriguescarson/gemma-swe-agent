"""Download the linux x86_64 / CPython 3.12 wheels a pod needs for the SWE-Pallets-X dev set (research/pallets.md 7).

  python3 scripts/pallets/wheelhouse.py [--out data/pallets/wheels]

Reads the exact pins of every venv named in data/pallets/task_env.json (their .g4_pallets_ok stamps) plus
flit_core==3.12.0 (the competition's build backend for these repos) and downloads each one with --no-deps. The result
is the task set's OWN wheelhouse: pack.py links it as <out>/wheels, which swegemma's resolve_wheels_dir picks before
/wheels (tasks_path.parent/"wheels", container_setup.py:61-86), so run_eval.py's faithful install gets exactly these
versions (with the competition wheels it would take pytest 9.1.1 and click 8.4.2, the newest present).
Public PyPI downloads only; verifies every file it expects exists afterwards.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAL = ROOT / "data" / "pallets"
VENVS = Path(os.environ.get("G4_PALLETS") or Path.home() / ".cache" / "g4" / "pallets")
PLAT = ["--platform", "manylinux2014_x86_64", "--platform", "manylinux_2_17_x86_64", "--platform",
        "manylinux_2_28_x86_64", "--platform", "manylinux_2_34_x86_64", "--platform", "linux_x86_64"]


def pins() -> list:
    env = json.loads((PAL / "task_env.json").read_text())
    out = {"flit_core==3.12.0"}
    for venv in sorted(set(env.values())):
        for ln in (VENVS / venv / ".g4_pallets_ok").read_text().splitlines():
            if ln.strip() and not ln.startswith("#"):
                out.add(ln.strip())
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(PAL / "wheels"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    bad = []
    for p in pins():
        cmd = [sys.executable, "-m", "pip", "download", "-q", "--no-deps", "--only-binary=:all:", "--python-version",
               "3.12", "--implementation", "cp", "--abi", "cp312", "--abi", "abi3", "--abi", "none", *PLAT, "-d",
               str(out), p]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            bad.append((p, (r.stderr or r.stdout).strip().splitlines()[-1:]))
    names = {f.split("-")[0].lower().replace("_", "-") + "==" + f.split("-")[1] for f in os.listdir(out)
             if f.endswith(".whl")}
    missing = [p for p in pins() if p.lower().replace("_", "-") not in names]
    print(f"wheelhouse: {len(names)} wheels in {out}; failed downloads {bad}; missing after download {missing}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
