"""Remove p2_race items whose error came from the model server or the network (autopilot_lib.is_infra_error), so the queue re-runs them.

    python scripts/a6000/p2_purge.py OUT [ITEMS_DIR]      prints 'purged N'
Item directories are written by root inside the container, so removal goes through `sudo -n rm -rf`."""
import glob, json, os, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from autopilot_lib import is_infra_error  # noqa: E402


def _sudo_rm(p):
    subprocess.run(["sudo", "-n", "rm", "-rf", p], check=False)


def purge(out, items_dir="items", rm=_sudo_rm):
    n = 0
    for f in sorted(glob.glob(os.path.join(out, items_dir, "*", "*", "task_results.jsonl"))):
        d = os.path.dirname(f)
        try:
            rows = [json.loads(l) for l in open(f) if l.strip()]
        except Exception:
            rows = []
        if any(is_infra_error(r.get("error")) for r in rows):
            rm(d); rm(d + ".out"); n += 1
    return n


if __name__ == "__main__":
    print(f"purged {purge(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'items')}")
