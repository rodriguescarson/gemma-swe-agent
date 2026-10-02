"""Read an or_race.sh output dir and apply docs/v4h/GATE.md (with its 2026-10-02 addendum).
Usage: python scripts/v4h_gate.py eval/runs/or_smoke_v4h [v4h] [v4]"""
import glob, json, os, sys

BAD = ("NO MATCH", "AMBIGUOUS", "ERROR:", "SYNTAX ERROR", "REFUSED")


def arm_stats(out, bundle):
    rows = {r["instance_id"]: r for r in map(json.loads, filter(str.strip, open(f"{out}/pl_{bundle}/task_results.jsonl")))}
    calls = bad = unreachable_pre = unreachable_post = first_install = 0
    tasks_with_calls, bad_tasks = set(), set()
    for f in glob.glob(f"{out}/pl_{bundle}/traces/trace_*.json"):
        tid = os.path.basename(f)[6:-5]
        installed, fixer_first = False, None
        for s in json.load(open(f)).get("steps", []):
            obs = str((s.get("observation") or {}).get("content", ""))
            for c in s.get("tool_calls") or []:
                fn, a, au = c.get("function_name"), c.get("arguments") or {}, (c.get("extra") or {}).get("author")
                if au == "fixer" and fixer_first is None:
                    fixer_first = fn
                if fn == "run_skill_script" and "install" in str(a.get("file_path", "")) and "SKILL_NOT_FOUND" not in obs:
                    installed = True
                if fn == "run_command" and "/tmp/swe/edit.py" in str(a.get("command", "")):
                    calls += 1; tasks_with_calls.add(tid)
                    if "can't open file" in obs or "No such file" in obs:
                        if installed:
                            unreachable_post += 1; bad_tasks.add(tid)
                        else:
                            unreachable_pre += 1
                    elif any(b in obs for b in BAD):
                        bad += 1
        first_install += fixer_first == "run_skill_script"
    solved = sum(str(r.get("resolved")) == "True" for r in rows.values())
    crashes = [t for t, r in rows.items() if r.get("error") and "timeout" not in str(r.get("error")).lower()]
    return dict(rows=len(rows), solved=solved, edit_calls=calls, tasks_with_edit_calls=len(tasks_with_calls),
                unreachable_before_install=unreachable_pre, unreachable_after_install=unreachable_post,
                unreachable_after_install_tasks=sorted(bad_tasks), fixer_first_call_install=first_install, bad=bad,
                err_rate=round(bad / calls, 3) if calls else None, crashes=crashes)


def main(out, treat="v4h", control="v4"):
    n_ids = len(open(f"{out}/ids.txt").read().split())
    t, c = arm_stats(out, treat), arm_stats(out, control)
    print(f"{treat}: {t}")
    print(f"{control}: solved {c['solved']}/{c['rows']}, crashes {c['crashes']}")
    # smoke (10 tasks) and full-population (74 tasks, docs/v4h/GATE.md 2026-10-02 17:10) rules share this script
    full = n_ids > 10
    checks = {"1a no unreachable after install": t["unreachable_after_install"] == 0 and t["rows"] == n_ids,
              "1b fixer installs first >=90%": t["fixer_first_call_install"] >= (0.9 * n_ids if full else 9),
              "2 err_rate<0.15": t["err_rate"] is not None and t["err_rate"] < 0.15,
              ("3 crashes<=control" if full else "3 zero crashes"): (len(t["crashes"]) <= len(c["crashes"])) if full else (not t["crashes"]),
              ("4 solved>=ctrl-2" if full else "4 sanity solved>=ctrl-1"): t["solved"] >= c["solved"] - (2 if full else 1)}
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    verdict = "PASS" if all(checks.values()) else "FAIL"
    print("GATE", verdict, f"(n={n_ids}, {'full population' if full else 'smoke'})")
    return verdict


if __name__ == "__main__":
    sys.exit(0 if main(*sys.argv[1:4]) == "PASS" else 1)
