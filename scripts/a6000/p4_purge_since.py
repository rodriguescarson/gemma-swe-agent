"""Drop rows of a run_eval.py results.jsonl stamped (row['t']) at or after EPOCH, so --resume re-runs them; rows without a stamp are never dropped.

    python scripts/a6000/p4_purge_since.py RESULTS_JSONL EPOCH        prints 'purged N'"""
import json, sys
from pathlib import Path


def purge_since(path, epoch):
    p = Path(path)
    if not p.exists():
        return 0
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    keep = [r for r in rows if not (r.get("t") is not None and r["t"] >= epoch)]
    p.write_text("".join(json.dumps(r) + "\n" for r in keep))
    return len(rows) - len(keep)


if __name__ == "__main__":
    print(f"purged {purge_since(sys.argv[1], float(sys.argv[2]))}")
