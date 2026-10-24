"""Daily AWS cost by service from Cost Explorer, with credits, tax and the cash left after credits shown separately.

    python aws/cost.py [--days 7] [--project] [--json]

Cost Explorer bills $0.01 per API request: this makes one per result page (one for a week). Data lags about a day.
--project keeps only cost tagged Project=gemma4-agent, which needs that tag activated as a cost allocation tag (Billing ->
Cost allocation tags) first; untagged spend such as Bedrock calls then drops out. The plan's bill check: credits must
cover usage and no GST may be charged in cash, so any day with cash > 0 is flagged.
"""
import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g4aws  # noqa: E402

USAGE_TYPES = {"Usage", "DiscountedUsage", "SavingsPlanCoveredUsage", "RIFee", "SavingsPlanRecurringFee"}


def fetch(ce, start, end, project=False):
    q = {"TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()}, "Granularity": "DAILY",
         "Metrics": ["UnblendedCost"],
         "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}, {"Type": "DIMENSION", "Key": "RECORD_TYPE"}]}
    if project:
        q["Filter"] = {"Tags": {"Key": "Project", "Values": [g4aws.PROJECT]}}
    out, token = [], None
    while True:
        r = ce.get_cost_and_usage(**q, **({"NextPageToken": token} if token else {}))
        out.extend(r["ResultsByTime"])
        token = r.get("NextPageToken")
        if not token:
            return out


def summarise(results):
    days = {}
    for day in results:
        d = days.setdefault(day["TimePeriod"]["Start"], {"services": defaultdict(float), "credits": 0.0, "tax": 0.0, "other": 0.0})
        for g in day.get("Groups", []):
            service, rtype = g["Keys"]
            amt = float(g["Metrics"]["UnblendedCost"]["Amount"])
            if rtype == "Credit":
                d["credits"] += amt
            elif rtype == "Tax":
                d["tax"] += amt
            elif rtype in USAGE_TYPES:
                d["services"][service] += amt
            else:
                d["other"] += amt
    for d in days.values():
        d["usage"] = sum(d["services"].values())
        d["cash"] = d["usage"] + d["credits"] + d["tax"] + d["other"]
        d["services"] = dict(sorted(d["services"].items(), key=lambda kv: -kv[1]))
    return dict(sorted(days.items()))


def main(argv=None, today=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--days", type=int, default=7); ap.add_argument("--project", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    end = (today or dt.date.today()) + dt.timedelta(days=1)
    start = end - dt.timedelta(days=a.days)
    days = summarise(fetch(g4aws.session().client("ce"), start, end, a.project))
    if a.json:
        print(json.dumps(days, indent=1))
        return 0
    tot = defaultdict(float)
    for day, d in days.items():
        print(f"{day}  usage ${d['usage']:9.2f}  credits ${d['credits']:9.2f}  tax ${d['tax']:7.2f}  cash ${d['cash']:8.2f}"
              + ("   <- CASH CHARGED" if d["cash"] > 0.005 else ""))
        for s, v in d["services"].items():
            if abs(v) >= 0.005:
                print(f"            {s:52} ${v:9.2f}")
        for k in ("usage", "credits", "tax", "cash"):
            tot[k] += d[k]
    print(f"{a.days} days{' (Project tag only)' if a.project else ''}: usage ${tot['usage']:.2f}, credits ${tot['credits']:.2f}, "
          f"tax ${tot['tax']:.2f}, cash after credits ${tot['cash']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
