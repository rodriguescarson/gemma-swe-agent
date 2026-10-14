"""Offline evidence for v13_jsonesc on rich_3278: v13's own edit template (prompt step 3) run on the base snapshot with the
regex line written three ways, then the task's tests (test_patch applied) for the score.

(a) old and new copied as the tool reply shows them (JSON escapes kept: one backslash shows as two);
(b) old and new in the file's real characters (what the lever asks for);
(c) old real, new copied from the reply (what p4, p4_v7, p4_v7c and p4_v7d wrote into rich/ansi.py).

Setup as in ev_modtests.py.   python scripts/forty_two/rich_solve/ev_jsonesc.py $WT $VENV/bin/python"""
import json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TID = "rich_3278"


def template():
    prompt = (ROOT / "submissions/v13/prompts/system.md").read_text()
    return [b for b in re.findall(r"```\n(.*?)```", prompt, re.S) if "<<'EDIT'" in b][0]


def fill(t, path, old, new):
    return t.replace("path/to/module.py", path).replace("<old lines, copied exactly>\n", old).replace("<new lines>\n", new)


def json_view(s):
    """The characters of s as they appear inside a JSON string in a tool reply (swegemma 0.2.11: encoded once)."""
    return json.dumps(s, ensure_ascii=False)[1:-1]


def sh(cmd, cwd, env_py=None):
    import os
    env = dict(os.environ)
    if env_py:
        env["PATH"] = str(Path(env_py).parent) + os.pathsep + env["PATH"]
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=110, env=env)


def main():
    wt, py = Path(sys.argv[1]) / TID, sys.argv[2]
    src = (wt / "rich/ansi.py").read_text()
    real_old = "(?:\\x1b([(@-Z\\\\-_]|\\[[0-?]*[ -/]*[@-~]))\n"
    assert src.count(real_old) == 1
    real_new = real_old.replace("[(@-Z", "[(0-?@-Z")          # the class now also takes 0-? (the shape of L4 g4-l4-v4's fix)
    seen_old, seen_new = json_view(real_old[:-1]) + "\n", json_view(real_new[:-1]) + "\n"
    print("the line in the file:          ", real_old.rstrip())
    print("the same line in a tool reply: ", seen_old.rstrip())
    rows = [json.loads(l) for l in open(ROOT / "data/tasks.jsonl") if l.strip()]
    tp = [t for t in rows if t["instance_id"] == TID][0]["test_patch"]
    for label, old, new in (("(a) both copied from the reply", seen_old, seen_new),
                            ("(b) both in the file's real characters", real_old, real_new),
                            ("(c) old real, new copied from the reply", real_old, seen_new)):
        sh("git checkout -q -- . && git clean -fdq", wt)
        r = sh(fill(template(), "rich/ansi.py", old, new), wt, py)
        res = f"template exit {r.returncode}: " + (r.stdout.strip() or r.stderr.strip().splitlines()[-1])
        if r.returncode == 0:
            (wt / "_tp.diff").write_text(tp if tp.endswith("\n") else tp + "\n")
            assert sh("git apply _tp.diff && rm _tp.diff", wt).returncode == 0
            t = sh(f"PYTHONPATH=. {py} -m pytest -q -p no:cacheprovider tests/test_ansi.py", wt)
            res += " | tests/test_ansi.py with the hidden tests: " + t.stdout.strip().splitlines()[-1]
        print(f"{label}: {res}")
        sh("git checkout -q -- . && git clean -fdq", wt)


if __name__ == "__main__":
    main()
