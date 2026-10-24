"""Terminate gemma4-agent instances by id, role or all, then verify with describe-instances. Lists only, unless --yes.

    python aws/teardown.py i-0abc [i-0def ...] [--yes]
    python aws/teardown.py --role train [--yes]
    python aws/teardown.py --all [--yes]

Only instances tagged Project=gemma4-agent are ever touched; an id without that tag is refused. A terminated machine runs
its stop hook (aws/bootstrap.sh sync) as the OS goes down, but outputs written since its last periodic sync may still be
lost: let a job finish when it can. Carson's rule: never stop a machine that is doing work without his go.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g4aws  # noqa: E402


def targets(ec2, ids=None, role=None, everything=False):
    if ids:
        found = []
        for page in ec2.get_paginator("describe_instances").paginate(InstanceIds=ids):
            for r in page["Reservations"]:
                found.extend(r["Instances"])
        foreign = [i["InstanceId"] for i in found if g4aws.tag(i, "Project") != g4aws.PROJECT]
        if foreign:
            raise SystemExit(f"REFUSED: not tagged Project={g4aws.PROJECT}: {foreign}")
        missing = sorted(set(ids) - {i["InstanceId"] for i in found})
        if missing:
            raise SystemExit(f"REFUSED: not found: {missing}")
        return [i for i in found if i["State"]["Name"] != "terminated"]
    live = g4aws.project_instances(ec2)
    if role:
        return [i for i in live if g4aws.tag(i, "Role") == role]
    if everything:
        return live
    raise SystemExit("give instance ids, --role ROLE or --all")


def wait_terminated(ec2, ids, timeout_s=600, poll_s=10, sleep=time.sleep):
    """Poll describe_instances until every id is terminated; returns {id: state} at the end."""
    deadline = time.monotonic() + timeout_s
    while True:
        states = {}
        for page in ec2.get_paginator("describe_instances").paginate(InstanceIds=ids):
            for r in page["Reservations"]:
                for i in r["Instances"]:
                    states[i["InstanceId"]] = i["State"]["Name"]
        if all(s == "terminated" for s in states.values()) or time.monotonic() >= deadline:
            return states
        sleep(poll_s)


def main(argv=None, sleep=time.sleep):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--role", choices=sorted(g4aws.ROLES)); ap.add_argument("--all", action="store_true")
    ap.add_argument("--yes", action="store_true", help="really terminate")
    ap.add_argument("--timeout", type=int, default=600, help="seconds to wait for terminated")
    a = ap.parse_args(argv)
    ec2 = g4aws.session().client("ec2")
    ts = targets(ec2, a.ids, a.role, a.all)
    if not ts:
        print(f"nothing to terminate (no matching Project={g4aws.PROJECT} instance is live)")
        return 0
    for i in ts:
        print(f"{i['InstanceId']}  {g4aws.tag(i, 'Role', '?'):12} {i['InstanceType']:12} {i['State']['Name']:13} run {g4aws.tag(i, 'Run')}")
    if not a.yes:
        print(f"{len(ts)} instance(s) would be terminated; add --yes. Outputs since each one's last periodic sync may be lost.")
        return 0
    ids = [i["InstanceId"] for i in ts]
    ec2.terminate_instances(InstanceIds=ids)
    print(f"terminate sent for {ids}; waiting for 'terminated' (up to {a.timeout} s)")
    states = wait_terminated(ec2, ids, a.timeout, sleep=sleep)
    for iid, s in states.items():
        print(f"  {iid}: {s}")
    still = [i["InstanceId"] for i in g4aws.project_instances(ec2)]
    print(f"describe-instances: Project={g4aws.PROJECT} instances not yet terminated: {still or 'none'}")
    return 0 if all(s == "terminated" for s in states.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
