"""Drop rows of a run_eval.py results.jsonl whose error came from the model server or the network, so --resume re-runs them. Prints 'purged N'.

    python scripts/a6000/p4_purge.py [RESULTS_JSONL]"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from autopilot_lib import is_infra_error  # noqa: E402


def purge(path):
    p = Path(path)
    if not p.exists():
        return 0
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    keep = [r for r in rows if not is_infra_error(r.get("err"))]
    p.write_text("".join(json.dumps(r) + "\n" for r in keep))
    return len(rows) - len(keep)


if __name__ == "__main__":
    print(f"purged {purge(sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / 'g4' / 'runs' / 'p4' / 'results.jsonl'))}")
