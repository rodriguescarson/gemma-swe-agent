"""The forensics counters v7 is judged by (docs/GAPS_2026-10-06.md, last section; scripts/a6000/PROMPTS.md P6) live in
scripts/a6000/v7_counters.py, written on the GPU box: reused here, not duplicated. These tests bind those counters to
what v7's helpers really print, so a v7 run cannot read zero because a message changed shape:

  * a clean v7-shaped task passes the must-be-zero rule (view.py usage-line calls, literal-wrapper commands, write_file
    path refusals, forced-install `{}` calls); a dirty task fails it on each of the four;
  * v7's own refusals, produced by running v7's helpers, are counted: view.py's usage line for non-numeric input, and
    the pre-edit cap refusals of fix 9 ("search cap reached" / "read cap reached", besides v6p-b's "SHARE SPENT");
  * on the 74 committed P4 traces of v5h2 the counters reproduce docs/a6000/FAILURE_FORENSICS.md.
Written before cap_refusals learned v7's texts (test-first)."""
import importlib.util, json, pathlib, subprocess, sys

import pytest

from test_v7_helpers import block, run, task, view

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "a6000"))
spec = importlib.util.spec_from_file_location("a6000_v7_counters", ROOT / "scripts" / "a6000" / "v7_counters.py")
vc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vc)
MUST_ZERO = ("view_usage_calls", "literal_wrapper_commands", "write_file_path_refusals", "forced_install_empty_args")
P4 = ROOT / "eval" / "a6000" / "results" / "p4"


def ok(stdout="", stderr=""):
    return {"status": "ok", "stdout": stdout, "stderr": stderr, "exit_code": 0}


def cmd_err(stdout="", stderr=""):
    return {"status": "error", "error_type": "CommandError", "error_message": stderr or stdout,
            "details": {"stdout": stdout, "stderr": stderr, "exit_code": 1}}


def call(author, fn, args, payload):
    return {"source": "agent", "extra": {"author": author}, "tool_calls": [{"function_name": fn, "arguments": args}],
            "observation": {"content": json.dumps(payload)}}


def rc(author, command, payload):
    return call(author, "run_command", {"command": command}, payload)


def write_run(out, tasks):
    """A p2_race-style run dir (items/v7/<task>/...), the layout the box writes."""
    for name, (steps, resolved) in tasks.items():
        d = out / "items" / "v7" / name
        (d / "traces").mkdir(parents=True)
        (d / "task_results.jsonl").write_text(json.dumps({"instance_id": name, "resolved": resolved}) + "\n")
        (d / "traces" / f"trace_{name}.json").write_text(json.dumps({"steps": steps}))
    return out


INSTALL = {"skill_name": "swe-tools", "file_path": "install.py"}
INSTALLED = {"skill_name": "swe-tools", "file_path": "install.py", "stdout": "installed: ['edit.py'] | helpers in ['/t/swe']"}


def clean_steps():
    """A v7 task as its prompts intend it: setup installs, the locator searches and reads, the fixer reads and edits,
    the verifier diffs, tests, writes and runs the repro through run_command, checks and submits."""
    return [call("setup", "run_skill_script", INSTALL, INSTALLED),
            rc("locator", 'python3 /tmp/swe/locate.py "parse_header"', ok("workspace=/w symbols=10\n1. pkg/mod.py  score=3.0\n")),
            rc("locator", "python3 /tmp/swe/view.py pkg/mod.py 1-40", ok("1| def f(x):\n2|     return x\n")),
            rc("fixer", "python3 /tmp/swe/view.py pkg/mod.py", ok("1| def f(x):\n")),
            rc("fixer", "python3 /tmp/swe/edit.py pkg/mod.py <<'EOF'\n" + block("    return x\n", "    return x * 2\n") + "EOF",
               ok("OK pkg/mod.py: lines 2-2 replaced (1 -> 1 lines)\n")),
            rc("verifier", "git diff", ok("diff --git a/pkg/mod.py b/pkg/mod.py\n")),
            rc("verifier", "python3 /tmp/swe/test.py --target tests/test_mod.py", ok("exit=0 1 passed\nall selected tests passed\n")),
            rc("verifier", "cat > /tmp/repro.py <<'EOF'\nfrom pkg.mod import f\nassert f(3) == 6, f(3)\nEOF", ok()),
            rc("verifier", "python3 /tmp/repro.py; echo EXIT=$?", ok("EXIT=0\n")),
            rc("verifier", "python3 /tmp/swe/check.py --mode preflight", ok("DIFF:\n pkg/mod.py | 2 +-\nPROBLEMS:\nnone\nREADY to submit_patch\n")),
            call("verifier", "submit_patch", {}, {"status": "ok", "patch_size": 120, "files_changed": 1})]


def dirty_steps():
    """Each v5h2 mechanism once or more (forensics findings 1, 3, 4, 6)."""
    return [rc("locator", "python3 /tmp/swe/view.py fastapi/sse.py 42-143", ok("usage: python3 /tmp/swe/view.py FILE START END   (line numbers, at most 120 lines)\n")),
            rc("locator", 'run_command(command="git grep -n x")', cmd_err(stderr="/bin/bash: -c: line 1: syntax error near unexpected token `command=\"git grep -n x\"'")),
            rc("locator", "run_command: git grep -n foo", cmd_err(stderr="/bin/bash: line 1: run_command:: command not found")),
            call("verifier", "write_file", {"filepath": "/tmp/repro.py", "content": "assert 0"},
                 {"status": "error", "error_type": "FileWriteError", "error_message": "Path traversal detected: '/tmp/repro.py' escapes workspace root."}),
            call("fixer", "run_skill_script", {}, {"error": "Argument 'skill_name' is required.", "error_code": "INVALID_ARGUMENTS"})]


def test_a_clean_v7_task_passes_the_must_be_zero_rule(tmp_path):
    c = vc.counters(str(write_run(tmp_path, {"clean": (clean_steps(), True)})), "v7")
    assert c["tasks"] == 1 and c["solved"] == 1
    assert all(c[k] == 0 for k in vc.COUNTERS), {k: c[k] for k in vc.COUNTERS}
    assert vc.verdict(c, MUST_ZERO)["pass"] is True


def test_a_dirty_task_fails_on_each_of_the_four(tmp_path):
    c = vc.counters(str(write_run(tmp_path, {"clean": (clean_steps(), True), "dirty": (dirty_steps(), False)})), "v7")
    assert (c["view_usage_calls"], c["literal_wrapper_commands"], c["write_file_path_refusals"], c["forced_install_empty_args"]) == (1, 2, 1, 1), c
    v = vc.verdict(c, MUST_ZERO)
    assert v["pass"] is False and v["failing"] == list(MUST_ZERO)


def test_v7s_own_refusal_texts_are_counted(tmp_path):
    """Run v7's helpers for real and store their replies the way the harness does."""
    t = task(tmp_path)
    bad_view = view(t, "m.py", "abc")                                   # non-numeric: the one input view.py refuses
    for _ in range(3):
        run(t, "locate.py", "f")
    search_cap = run(t, "locate.py", "f")[1]
    for i in range(14):
        view(t, "m.py", str(10 * i + 101), str(10 * i + 105))
    read_cap = view(t, "m.py", "1", "5")
    good = [view(task(tmp_path, s), *a) for s, a in (("a", ("m.py", "30-40")), ("b", ("m.py",)), ("c", ("m.py", "30:40")), ("d", ("m.py", "30")))]
    steps = [rc("fixer", "python3 /tmp/swe/view.py m.py abc", ok(bad_view)),
             rc("locator", 'python3 /tmp/swe/locate.py "f"', ok(search_cap)),
             rc("locator", "python3 /tmp/swe/view.py m.py 1 5", ok(read_cap))]
    steps += [rc("fixer", f"python3 /tmp/swe/view.py m.py {a}", ok(o)) for a, o in zip(("30-40", "", "30:40", "30"), good)]
    c = vc.counters(str(write_run(tmp_path / "run", {"t": (steps, False)})), "v7")
    assert c["view_usage_calls"] == 1, (c, bad_view)                    # only the non-numeric call; the four shapes are fine
    assert c["cap_refusals"] == 2, (c, search_cap, read_cap)


def test_the_cli_is_unchanged(tmp_path):
    run_dir = write_run(tmp_path / "r", {"clean": (clean_steps(), True), "dirty": (dirty_steps(), False)})
    out = tmp_path / "c.json"
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "a6000" / "v7_counters.py"), str(run_dir), "--arm", "v7", "--json", str(out)],
                       capture_output=True, text=True)
    assert p.returncode == 0 and "must-be-zero verdict: **FAIL" in p.stdout, p.stdout + p.stderr
    d = json.loads(out.read_text())
    assert d["verdict"]["failing"] == list(MUST_ZERO) and d["counters"]["tasks"] == 2


@pytest.mark.skipif(not (P4 / "results.jsonl").exists(), reason="the committed P4 traces are not on this box")
def test_control_reproduces_the_forensics_numbers_on_v5h2_p4():
    """docs/a6000/FAILURE_FORENSICS.md, the same 74 traces: view.py usage 66 calls; literal wrappers 18; write_file
    refusals 33 (29 verifier + 4 fixer; 47 over all arms = 2 + 4 + 8 + 33); 41 `{}` install calls; 26 loops; 13 tasks
    on the budget; no can't-open (the setup stage); 29 solved."""
    c = vc.counters(str(P4), None)
    got = {k: c[k] for k in ("tasks", "solved") + vc.COUNTERS}
    assert got == {"tasks": 74, "solved": 29, "view_usage_calls": 66, "literal_wrapper_commands": 18, "write_file_path_refusals": 33,
                   "forced_install_empty_args": 41, "cap_refusals": 0, "repeat_outlines": 0, "repeat_reads": 0, "loops_ge5": 26, "budget_exhausted_tasks": 13,
                   "helper_unreachable_tasks": 0}, got
