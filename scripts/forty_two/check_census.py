"""Where a "red first" rule would fire in recorded box runs: for every task, the python/pytest checks the agent ran before
and after its first source edit, whether any check before the edit failed (exit != 0 or a traceback/assert/FAILED in the
output), and what the last check before the end was. Reads only committed traces.

    python scripts/forty_two/check_census.py eval/a6000/results/p4_b1024 [more run dirs] [--ids a,b,c]

Heuristics (labelled as such in the report): a source edit is a successful edit_file/write_file, or a `cat > file <<`
command, on a .py path that is not a test or scratch file (repro*, reproduce*, test*, debug*, check*, /tmp, tests/); a
python check is a run_command that runs python3/python (script or heredoc) and is not the v13 edit template (`<<'EDIT'`)."""
import argparse, json, os, re

SCRATCH = re.compile(r"(^|/)(repro\w*|reproduce\w*|test_?\w*|debug\w*|check\w*|scratch\w*)\.py$|^/?tmp/|(^|/)tests?/")


def is_src(path):
    return bool(path) and path.endswith(".py") and not SCRATCH.search(path.lstrip("/").replace("workspace/", ""))


def kind(cmd):
    c = cmd.strip()
    if "<<'EDIT'" in c:
        return "edit"
    if "pytest" in c:
        return "pytest"
    if re.match(r"(cd \S+ && )?(PYTHONPATH=\S+ )?python3?\b", c):
        return "python"
    return None


def failed(obs):
    try:
        o = json.loads(obs)
    except Exception:
        return None
    if o.get("status") == "error":
        return True
    out = (o.get("stdout") or "") + (o.get("stderr") or "")
    return bool(re.search(r"Traceback|AssertionError|FAILED|Error:", out))


def events(trace):
    d = json.load(open(trace))
    ev = []
    for s in d["steps"]:
        if s["source"] != "agent":
            continue
        obs = (s.get("observation") or {}).get("content", "") or ""
        for tc in s.get("tool_calls") or []:
            fn, a = tc.get("function_name"), tc.get("arguments") or {}
            t = (tc.get("extra") or {}).get("elapsed_s") or 0.0
            if fn in ("edit_file", "write_file"):
                ev.append(("edit", t, a.get("filepath"), '"status": "ok"' in obs))
            elif fn == "run_command":
                c = a.get("command", "")
                k = kind(c)
                m = re.search(r"cat\s*<<\s*'?\w+'?\s*>\s*(\S+)|cat\s*>\s*(\S+)\s*<<", c)
                if k == "edit":
                    p = re.search(r'Path\("([^"]+)"\)', c)
                    ev.append(("edit", t, p.group(1) if p else "", not failed(obs)))
                elif m and not k:
                    ev.append(("edit", t, m.group(1) or m.group(2), True))
                elif k:
                    ev.append((k, t, c[:90].replace("\n", " "), failed(obs)))
    return ev


def summarise(ev):
    first = next((e for e in ev if e[0] == "edit" and e[3] and is_src(e[2])), None)
    t_src = first[1] if first else None
    checks = [e for e in ev if e[0] in ("python", "pytest")]
    pre = [e for e in checks if t_src is None or e[1] < t_src]
    post = [e for e in checks if t_src is not None and e[1] > t_src]
    return {"edited": first is not None, "t_first_edit": t_src, "pre": len(pre), "red_pre": sum(1 for e in pre if e[3]),
            "post": len(post), "last": checks[-1] if checks else None}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("runs", nargs="+"); ap.add_argument("--ids", default="")
    a = ap.parse_args()
    never = set(open("data/never_solved_box5_ids.txt").read().split())
    ids = set(filter(None, a.ids.split(",")))
    for run in a.runs:
        rows = {}
        for l in open(os.path.join(run, "results.jsonl")):
            if l.strip():
                r = json.loads(l); rows[r["id"]] = r
        groups = {"the 42": [], "solved": []}
        detail = []
        for i, r in sorted(rows.items()):
            tr = os.path.join(run, "results", "traces", f"trace_{i}.json")
            if not os.path.exists(tr):
                continue
            s = summarise(events(tr))
            g = "the 42" if i in never else ("solved" if r["resolved"] else None)
            if g:
                groups[g].append(s)
            if i in ids:
                last = s["last"]
                detail.append(f"  {i}: resolved={r['resolved']} edited={s['edited']} first_edit_t={s['t_first_edit'] and round(s['t_first_edit'])}"
                              f" checks_before={s['pre']} (red {s['red_pre']}) after={s['post']}"
                              f" last_check={'none' if not last else (('RED ' if last[3] else 'green ') + last[2])}")
        print(f"== {run}  (heuristic classification, see docstring)")
        for g, v in groups.items():
            ed = [x for x in v if x["edited"]]
            print(f"  {g}: tasks={len(v)} with a source edit={len(ed)}; of those: a failing check before the first edit={sum(1 for x in ed if x['red_pre'])},"
                  f" no check before it={sum(1 for x in ed if not x['pre'])}, a check after it={sum(1 for x in ed if x['post'])}")
        print("\n".join(detail))


if __name__ == "__main__":
    main()
