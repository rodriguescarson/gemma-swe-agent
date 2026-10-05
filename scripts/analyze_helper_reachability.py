"""Helper reachability on real Kaggle traces: which tasks hit "can't open file" on a /tmp/swe helper, and why.

    python scripts/analyze_helper_reachability.py [--json] [--max-tasks-with-failure N] RUN_DIR [RUN_DIR ...]

RUN_DIR holds results/traces/trace_*.json (ATIF steps, as eval/kaggle/<slug>/). First failure per task is classed as
helper_before_install (the model skipped the install), install_same_response, or after_helper_worked. With
--max-tasks-with-failure the exit code is 1 when a run exceeds it (a gate for l4_result_summary). 2026-10-05 finding:
v4h2f 54/74 and v4h2g 44/74 tasks failed, every first failure helper_before_install. tests/test_analyze_helper_reachability.py.
"""
import argparse, collections, glob, json, os, re, sys

HELPER = re.compile(r"/tmp/swe/(\w+)\.py")


def _names(tool_calls):
    out = []
    for tc in tool_calls or []:
        a = tc.get("arguments") or {}
        a = a if isinstance(a, dict) else {}
        if a.get("file_path") in ("install.py", "scripts/install.py"):
            out.append("install")
        else:
            m = HELPER.search(a.get("command", "") or "")
            out.append(m.group(1) if m else None)
    return out


def analyse(run):
    rep = {"tasks": 0, "tasks_with_failure": 0, "helpers": {},
           "first_failure": {"helper_before_install": 0, "install_same_response": 0, "after_helper_worked": 0}}
    helpers = collections.defaultdict(lambda: {"ok": 0, "fail": 0})
    for f in sorted(glob.glob(os.path.join(run, "results", "traces", "trace_*.json"))):
        steps = json.load(open(f)).get("steps", [])
        rep["tasks"] += 1
        installed, worked, failed = False, set(), False
        for s in steps:
            names = _names(s.get("tool_calls"))
            if not any(names):
                continue
            obs = s.get("observation"); obs = obs if isinstance(obs, str) else json.dumps(obs)
            cant = "can't open file" in obs
            for n in names:
                if n in (None, "install"):
                    continue
                helpers[n]["fail" if cant else "ok"] += 1
                if cant and not failed:
                    failed = True
                    k = ("install_same_response" if "install" in names else
                         "after_helper_worked" if worked else "helper_before_install")
                    rep["first_failure"][k] += 1
                if not cant:
                    worked.add(n)
            if "install" in names:
                installed = True
        rep["tasks_with_failure"] += failed
    rep["helpers"] = dict(helpers)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+"); ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-tasks-with-failure", type=int)
    a = ap.parse_args(argv)
    reps = {r: analyse(r) for r in a.runs}
    bad = False
    if a.json:
        print(json.dumps(reps, indent=1))
    for r, rep in reps.items():
        over = a.max_tasks_with_failure is not None and rep["tasks_with_failure"] > a.max_tasks_with_failure
        bad |= over
        if not a.json:
            print(f"{'FAIL' if over else 'ok  '} {r}: {rep['tasks_with_failure']}/{rep['tasks']} tasks with a can't-open; "
                  f"first failure {rep['first_failure']}; helpers {rep['helpers']}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
