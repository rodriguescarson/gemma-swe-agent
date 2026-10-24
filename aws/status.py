"""Every EC2 instance tagged Project=gemma4-agent, with uptime and dollars so far. Read-only.

    python aws/status.py [--all] [--json]

$ so far = uptime x the hourly rate (on-demand list price, or the current spot price in the instance's AZ) + gp3 EBS.
It is an estimate; aws/cost.py has the billed numbers (a day late). --all adds terminated instances AWS still lists.
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g4aws  # noqa: E402


def ended_at(inst):
    """The stop/terminate time from StateTransitionReason, e.g. 'User initiated (2026-10-24 10:00:00 GMT)'."""
    m = re.search(r"\((\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) GMT\)", inst.get("StateTransitionReason", ""))
    return dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc) if m else None


def rate(ec2, inst, cache):
    itype, az = inst["InstanceType"], inst.get("Placement", {}).get("AvailabilityZone")
    od = g4aws.ON_DEMAND_USD_H.get(itype)
    if inst.get("InstanceLifecycle") != "spot":
        return od
    key = (itype, az)
    if key not in cache:
        r = ec2.describe_spot_price_history(InstanceTypes=[itype], AvailabilityZone=az, ProductDescriptions=["Linux/UNIX"],
                                            StartTime=dt.datetime.now(dt.timezone.utc), MaxResults=1)
        h = r.get("SpotPriceHistory", [])
        cache[key] = float(h[0]["SpotPrice"]) if h else od
    return cache[key]


def rows(ec2, include_terminated=False, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    states = g4aws.LIVE_STATES + (["terminated"] if include_terminated else [])
    cache, out = {}, []
    for i in g4aws.project_instances(ec2, states):
        state = i["State"]["Name"]
        end = now if state in ("pending", "running", "stopping", "shutting-down") else (ended_at(i) or now)
        up = g4aws.hours_since(i["LaunchTime"], end)
        r = rate(ec2, i, cache)
        disk = g4aws.ROLES.get(g4aws.tag(i, "Role"), {}).get("disk_gb", 0)   # describe_instances gives volume ids, not sizes
        ebs_h = disk * g4aws.GP3_USD_GB_MONTH / 730
        deadline = g4aws.tag(i, "Deadline")
        left = None
        if deadline and state not in ("terminated", "stopped"):
            d = dt.datetime.strptime(deadline, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
            left = round((d - now).total_seconds() / 3600, 2)
        out.append({
            "id": i["InstanceId"], "role": g4aws.tag(i, "Role", "?"), "type": i["InstanceType"],
            "market": "spot" if i.get("InstanceLifecycle") == "spot" else "on-demand", "state": state,
            "az": i.get("Placement", {}).get("AvailabilityZone"), "launched": i["LaunchTime"].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "uptime_h": round(up, 2), "usd_h": round((r or 0) + ebs_h, 4), "usd_so_far": round(up * ((r or 0) + ebs_h), 2),
            "deadline": deadline or None, "hours_left": left, "run": g4aws.tag(i, "Run") or None,
        })
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--all", action="store_true", help="include terminated instances")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    ec2 = g4aws.session().client("ec2")
    rs = rows(ec2, a.all)
    if a.json:
        print(json.dumps(rs, indent=1))
        return 0
    if not rs:
        print(f"no Project={g4aws.PROJECT} instances in {g4aws.REGION} ({'any state' if a.all else ', '.join(g4aws.LIVE_STATES)})")
        return 0
    print(f"{'id':20} {'role':12} {'type':12} {'market':9} {'state':13} {'up h':>6} {'$/h':>7} {'$ so far':>9} {'h left':>7}  run")
    for r in rs:
        left = "" if r["hours_left"] is None else f"{r['hours_left']:.2f}"
        print(f"{r['id']:20} {r['role']:12} {r['type']:12} {r['market']:9} {r['state']:13} {r['uptime_h']:6.2f} "
              f"{r['usd_h']:7.3f} {r['usd_so_far']:9.2f} {left:>7}  {r['run'] or ''}")
    burning = sum(r["usd_h"] for r in rs if r["state"] in ("pending", "running"))
    print(f"total so far ${sum(r['usd_so_far'] for r in rs):.2f}; burning now ${burning:.3f}/h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
