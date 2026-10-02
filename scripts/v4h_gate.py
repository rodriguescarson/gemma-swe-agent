"""Read an or_race.sh output dir and apply docs/v4h/GATE.md. Usage: python scripts/v4h_gate.py eval/runs/or_smoke_v4h [v4h] [v4]"""
import glob, json, os, sys

BAD = ("NO MATCH", "AMBIGUOUS", "ERROR:", "SYNTAX ERROR", "REFUSED")


def arm_stats(out, bundle):
    rows = {r["instance_id"]: r for r in map(json.loads, filter(str.strip, open(f"{out}/pl_{bundle}/task_results.jsonl")))}
    calls = unreachable = bad = 0
    unreachable_tasks, tasks_with_calls = set(), set()
    for f in glob.glob(f"{out}/pl_{bundle}/traces/trace_*.json"):
        tid = os.path.basename(f)[6:-5]
        for s in json.load(open(f)).get("steps", []):
            obs = str((s.get("observation") or {}).get("content", ""))
            for c in s.get("tool_calls") or []:
                if c.get("function_name") == "run_command" and "/tmp/swe/edit.py" in str((c.get("arguments") or {}).get("command", "")):
                    calls += 1; tasks_with_calls.add(tid)
                    if "can't open file" in obs or "No such file" in obs:
                        unreachable += 1; unreachable_tasks.add(tid)
                    elif any(b in obs for b in BAD):
                        bad += 1
    solved = sum(str(r.get("resolved")) == "True" for r in rows.values())
    crashes = [t for t, r in rows.items() if r.get("error") and "timeout" not in str(r.get("error")).lower()]
    return dict(rows=len(rows), solved=solved, edit_calls=calls, tasks_with_edit_calls=len(tasks_with_calls),
                unreachable=unreachable, unreachable_tasks=sorted(unreachable_tasks), bad=bad,
                err_rate=round(bad / calls, 3) if calls else None, crashes=crashes)


def main(out, treat="v4h", control="v4"):
    t, c = arm_stats(out, treat), arm_stats(out, control)
    print(f"{treat}: {t}")
    print(f"{control}: solved {c['solved']}/{c['rows']}, crashes {c['crashes']}")
    checks = {"1 reachable": t["unreachable"] == 0 and t["rows"] == 10,
              "2 err_rate<0.15": t["err_rate"] is not None and t["err_rate"] < 0.15,
              "3 zero crashes": not t["crashes"],
              "4 sanity solved>=ctrl-1": t["solved"] >= c["solved"] - 1}
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    verdict = "PASS" if all(list(checks.values())[:3]) else "FAIL"
    print("GATE", verdict + ("" if checks["4 sanity solved>=ctrl-1"] else " (sanity flag: v4h solved fewer than v4-1)"))
    return verdict


if __name__ == "__main__":
    sys.exit(0 if main(*sys.argv[1:4]) == "PASS" else 1)
