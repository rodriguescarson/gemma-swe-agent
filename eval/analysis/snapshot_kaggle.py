"""Save this team's Kaggle submissions (all of them, newest first) as eval/analysis/out/kaggle_submissions_<UTC date>.json, the
input of eval/analysis/calibration.py and paper/make_tables.py. Same fields as the 18 Oct snapshot.

    python eval/analysis/snapshot_kaggle.py [--competition gemma-4-developer-agent]"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
FIELDS = ("ref", "date", "description", "status", "public_score", "private_score", "error_description", "url")


def rows(api, competition: str) -> list[dict]:
    """Every submission: one page of up to 200 (this team has far fewer; a full page is refused rather than truncated)."""
    batch = api.competition_submissions(competition, page_size=200) or []
    if len(batch) >= 200:
        raise SystemExit("200 or more submissions: add page_token paging before trusting this snapshot")
    return [{k: str(getattr(s, k, "") or "") for k in FIELDS} for s in batch if s is not None]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--competition", default="gemma-4-developer-agent")
    a = ap.parse_args(argv)
    from kaggle import api
    now = dt.datetime.now(dt.timezone.utc)
    subs = rows(api, a.competition)
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"kaggle_submissions_{now:%Y-%m-%d}.json"
    p.write_text(json.dumps({"fetched_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "competition": a.competition,
                             "submissions": subs}, indent=1) + "\n")
    print(f"{p}: {len(subs)} submissions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
