"""v10.2 locator package (docs/v10/SPEC_v10_2.md 5.1-5.6; R131-R136): the phase marker and LOCATOR DIGEST, the
helper-enforced locator close with its draft plan, run.py's checks, grep.py's closest paths and issue-marker refusal,
locate.py's empty-query refusal, locate_top and tracker cleaning.

Every helper runs from a temp copy of submissions/v10_2 (tests/v10_support/v102.py) as a subprocess against a
harness-like repo. Timing budgets are asserted on medians or minima so a loaded machine does not flake them.
Regression tests for the defects this version fixes: B1 run.py dropped piped stdin (test_run_bare_interpreter_stdin),
B2 python3 -c with literal \\n sequences looped (test_run_c_literal_newline), and (review 2026-09-30) a phase-start
status.py that raised left the locator phase open, so the fixer was refused in a loop
(test_failed_phase_start_status_still_ends_the_locator_phase and its two edges).
"""
import json
import os
import pathlib
import re
import statistics
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from v10_support.repo import no_orphans, find_orphans, kill_processes, unique_sleep, copy_helpers, PY  # noqa: F401,E402
from v10_support.v102 import Box, V101_SCRIPTS, V102_SCRIPTS, lines, shim_path, ROOT  # noqa: E402
from test_v10_1 import helper_name_violations  # noqa: E402

pytestmark = pytest.mark.skipif(not (V102_SCRIPTS / "_swe_common.py").exists(), reason="v10.2 bundle not built")

FILES = {
    "pkg/__init__.py": "",
    "pkg/mod.py": "def parse_header(x):\n    return x\n\n\ndef other(y):\n    return y + 1\n",
    "pkg/text.py": ("class Text(object):\n    def divide(self, offsets):\n        out = []\n        for o in offsets:\n"
                    "            out.append(o)\n        return out\n\n\ndef cell_len(s):\n    return len(s)\n"),
    "tests/test_mod.py": "from pkg.mod import parse_header\n\n\ndef test_p():\n    assert parse_header(1) == 1\n",
}
FAILING = "from pkg.mod import parse_header\n# CLAIM 1: doubles\nassert parse_header(2) == 4, parse_header(2)\n"
PASSING = "from pkg.mod import parse_header\n# CLAIM 1: identity\nassert parse_header(2) == 2\n"
CLOSED = "LOCATOR CLOSED at t="
SHORT = ("LOCATOR CLOSED: nothing ran. Reply with your plan now (the draft is above); a later stage runs "
         "python3 /tmp/swe/status.py first.")
LATER = "Any later stage: run python3 /tmp/swe/status.py first, then repeat this call."
HINTS = ("LOCATOR:", "EDIT NOW:", "FINISH:", "TIME:", "CONTEXT:", "FINAL:")


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path, FILES)


def close_by_calls(box, t=20, view_file="pkg/mod.py"):
    """14 gated calls (one locate, 13 views) at task time t: the next gated call is the 15th."""
    box.h("locate", ["parse header"], t=t)
    for i in range(13):
        box.h("view", [view_file, "1", "2"], t=t)
    assert box.state()["loc"]["calls"] == 14


def est_tokens(s):
    a = len(s.encode("ascii", "ignore"))
    return a / 3.0 + (len(s) - a) * 2.7


def assert_refusal(out, t):
    ls = lines(out)
    assert ls[-1] == "[t=%ds]" % t, out
    assert not any(x.startswith(HINTS) for x in ls), out             # the footer's hint line is suppressed
    assert len(out.rstrip("\n")) <= 600, len(out)
    assert helper_name_violations(out) == [], helper_name_violations(out)


# ------------------------------------------------------------------------------------------------------ R132 close
def test_close_at_call_15(box):
    """R132 base: calls 1-14 run, the 15th is refused with the draft plan; nothing else is written but loc.refused."""
    close_by_calls(box, t=80)
    before = box.state()
    out = box.h("view", ["pkg/mod.py", "4", "6"], t=80)
    assert out.startswith("LOCATOR CLOSED at t=80s after 14 calls: nothing ran. Locator: reply now with your plan; a "
                          "draft from your calls:\n"), out
    assert "FILES: pkg/mod.py:1-2 (parse_header)\nREPRO: none\n" + LATER in out, out
    assert "return y + 1" not in out                                   # the view did not run
    assert_refusal(out, 80)
    after = box.state()
    assert after["loc"] == dict(before["loc"], refused=1, close_t=80.0, close_why="calls"), after["loc"]
    assert after["views"] == before["views"]
    assert any(e.get("h") == "gate" and e.get("kind") == "view" and e.get("why") == "calls" for e in box.journal())


def test_close_at_t90(box):
    """R132 base: at t >= 90 the first gated call is refused (after 0 calls); at 89.9 it runs."""
    assert box.h("locate", ["parse header"], t=89.9).startswith("LOCATE:")
    out = box.h("grep", ["parse_header"], t=90)
    assert out.startswith("LOCATOR CLOSED at t=90s after 1 calls:"), out
    assert "FILES: pkg/mod.py:1-2 (parse_header)" in out                 # no view yet: the locate_top fallback
    assert box.state()["loc"]["close_why"] == "time"
    assert_refusal(out, 90)


@pytest.mark.parametrize("helper,args,stdin", [
    ("locate", ["parse header"], None), ("grep", ["parse_header"], None), ("view", ["pkg/mod.py"], None),
    ("run", ["touch MARKER"], None), ("verify", ["--repro-only"], FAILING)])
def test_every_gated_helper_refuses_without_a_child(tmp_path, helper, args, stdin):
    """R132 edge: each gated helper refuses before any subprocess (git and python3 are shimmed and logged) and fast."""
    box = Box(tmp_path, FILES)
    close_by_calls(box)
    path, log = shim_path(tmp_path, box.env)
    walls = []
    for _ in range(3):
        if log.exists():
            log.unlink()
        out, wall = box.timed(helper, args, stdin=stdin, t=30, PATH=path)
        walls.append(wall)
        assert out.startswith("LOCATOR CLOSED"), out
        assert not log.exists() or log.read_text() == "", log.read_text()
    assert not (box.ws / "MARKER").exists()
    assert min(walls) <= 0.15, walls


def test_ungated_helpers_and_recover_install(box):
    """R132 edges: install (the RECOVER call), plain verify and finalize are never refused and keep the counters;
    status.py reopens the helpers for the next stage."""
    close_by_calls(box, t=40)
    assert box.h("install", t=41).startswith("swe-tools v10.2 ready")
    assert box.state()["loc"]["calls"] == 14 and box.state()["loc"]["refused"] == 0
    assert box.h("verify", t=42).startswith("VERIFY: NO SOURCE CHANGE")
    assert box.h("finalize", t=43).startswith("NOT READY: EMPTY")
    assert box.h("view", ["pkg/mod.py", "1", "2"], t=44).startswith(CLOSED)
    assert box.h("status", t=45).startswith("STATUS [t=45s] helpers v10.2 | locator closed after 14 helper calls")
    for _ in range(20):                                                # the fixer phase: never refused
        assert box.h("view", ["pkg/mod.py", "1", "2"], t=200).startswith("pkg/mod.py lines 1-2")


def test_edit_reopens(box):
    """R132 edge: a fixer that edits without status first still reopens the helpers (edit.py ends the phase)."""
    close_by_calls(box)
    out = box.h("edit", ["pkg/mod.py", "--lines", "2-2"], stdin="    return x * 2\n", t=50)
    assert out.startswith("OK ("), out
    assert box.h("view", ["pkg/mod.py", "1", "2"], t=51).startswith("pkg/mod.py lines 1-2")


def test_refusal_loop_guard(box):
    """R132 edge: the first two consecutive refusals carry the draft, the third and later are the short form."""
    close_by_calls(box)
    outs = [box.h("grep", ["x"], t=30 + i) for i in range(4)]
    assert all(o.startswith("LOCATOR CLOSED at t=") and "FILES:" in o for o in outs[:2]), outs[:2]
    assert [lines(o)[0] for o in outs[2:]] == [SHORT, SHORT]
    for i, o in enumerate(outs):
        assert_refusal(o, 30 + i)


def test_draft_plan_ranking_and_fallbacks(tmp_path):
    """R132 edges: the draft names the most-viewed file (then the next) with its latest range and enclosing def from
    the index cache; without views the first locate_top entry; with neither FILES: none seen. REPRO follows the
    saved reproduction."""
    box = Box(tmp_path / "a", FILES)
    box.h("locate", ["divide text offsets"], t=5)
    for _ in range(3):
        box.h("view", ["pkg/text.py", "1", "6"], t=6)
    box.h("view", ["pkg/mod.py", "4", "6"], t=7)
    assert "fails on original" in box.h("verify", ["--repro-only"], stdin=FAILING, t=8)
    box.h("view", ["pkg/text.py", "9", "10"], t=9)                     # the latest range of the most-viewed file
    for _ in range(7):                                                 # gated calls 8-14
        assert box.h("grep", ["zzz_nothing"], t=10).startswith("GREP: 0 hits")
    out = box.h("grep", ["x"], t=10)
    assert "FILES: pkg/text.py:9-10 (cell_len); pkg/mod.py:4-6 (other)\nREPRO: fails on original" in out, out
    box = Box(tmp_path / "b", FILES)
    box.h("locate", ["cell len text"], t=5)
    for _ in range(13):
        box.h("grep", ["zzz_nothing"], t=6)
    out = box.h("grep", ["x"], t=7)
    f, sym, a, b = box.state()["locate_top"][0]
    assert f == "pkg/text.py" and sym and b >= a >= 1
    assert "FILES: %s:%d-%d (%s)\nREPRO: none" % (f, a, b, sym) in out, out
    box = Box(tmp_path / "c", FILES)
    for _ in range(14):
        box.h("grep", ["zzz_nothing"], t=6)
    assert "FILES: none seen\nREPRO: none" in box.h("grep", ["x"], t=7)


def test_draft_plan_skips_test_files(box):
    """R132 edge: a viewed test file never appears in the draft (the graders replace tests)."""
    for _ in range(14):
        box.h("view", ["tests/test_mod.py", "1", "3"], t=5)
    assert "FILES: none seen" in box.h("view", ["pkg/mod.py"], t=6)


# ------------------------------------------------------------------------------------------------------ R131 digest
def test_status_phase_start_digest(box):
    """R131 base: the call that ends the locator phase prints the LOCATOR DIGEST within 800 chars; the context meter
    goes locator -> fixer -> verifier; every status.py restarts vsince."""
    box.h("locate", ["divide text offsets"], t=5)
    box.h("view", ["pkg/text.py", "1", "6"], t=6)
    box.h("view", ["pkg/mod.py", "1", "2"], t=7)
    box.h("verify", ["--repro-only"], stdin=FAILING, t=8)
    box.py("C.state_update(lambda s: s.update(vsince=3))\n")
    assert (box.state().get("ctx") or {}).get("phase", "locator") == "locator"
    top = box.state()["locate_top"]
    located = ", ".join("%s (%s)" % (f, sym) if sym else f for f, sym, _a, _b in top)
    assert top and top[0][0] == "pkg/text.py"
    out, wall = box.timed("status", t=64)
    assert out == (
        "STATUS [t=64s] helpers v10.2 | locator closed after 4 helper calls | repro: 1 claim (fails on original) | "
        "checkpoints: 0\n"
        "LOCATOR DIGEST (what the locator's helpers showed; a locator replies with its plan now, the fixer starts "
        "from it):\n"
        "  located: " + located + "\n"
        "  viewed: pkg/mod.py 1-2 (parse_header); pkg/text.py 1-6 (Text.divide)\n"
        "  repro: fails on original (1 of 1 claims), saved; python3 /tmp/swe/verify.py runs it\n"
        "DIFF: no source change\n[t=64s]\n"), out
    assert len(out.rstrip("\n")) <= 800 and wall <= 0.5 + 0.3
    st = box.state()
    assert st["ctx"]["phase"] == "fixer" and st["vsince"] == 0
    second = box.h("status", t=65)                                   # every later call: the v10.1 form
    assert second.startswith("STATUS [t=65s] helpers v10.2 | repro: 1 claim (fails on original) | checkpoints: 0\n")
    assert "JOURNAL (last" in second and "LOCATOR DIGEST" not in second
    assert box.state()["ctx"]["phase"] == "verifier"
    box.h("status", t=66)
    assert box.state()["ctx"]["phase"] == "verifier"


def test_status_digest_empty_state(box):
    """R131 edge: nothing located, viewed or reproduced."""
    out = box.h("status", t=10)
    assert lines(out)[1:] == ["LOCATOR DIGEST: no locator activity recorded (no locate, view or reproduction).",
                              "DIFF: no source change", "[t=10s]"], out
    assert "locator closed after 0 helper calls" in lines(out)[0]


def test_status_digest_adversarial_sizes(box):
    """R131 edge: 60 views on 200-char and non-ASCII paths, and a long locate_top, stay within 800 chars and the
    token cap (located is dropped first, then viewed entries)."""
    code = ("names = ['pkg/' + ('d\\u00e9j\\u00e0_%02d_' % i) * 12 + 'x' * 100 + '.py' for i in range(60)]\n"
            "def f(s):\n"
            "    s['views'] = {n: [[1, 400, 10.0 + i]] for i, n in enumerate(names)}\n"
            "    s['locate_top'] = [[n, 'Klass.m\\u00e9thode_' + 'y' * 80, 1, 9] for n in names[:3]]\n"
            "C.state_update(f)\n"
            "print(len(names[0]))\n")
    assert int(box.py(code).strip()) >= 200
    box.h("verify", ["--repro-only"], stdin=FAILING, t=8)
    for t in (30, 80, 160):                                           # with and without a hint line in the footer
        box.py("C.state_update(lambda s: s.update(ctx={'phase': 'locator', 'n': 0, 'tail': []}))\n")
        out = box.h("status", t=t)
        assert len(out.rstrip("\n")) <= 800, len(out)
        assert est_tokens(out.rstrip("\n")) <= 800 / 3.0 + 1, est_tokens(out)
        assert "repro: fails on original (1 of 1 claims)" in out and out.rstrip("\n").endswith("[t=%ds]" % t), out
        assert "located:" not in out                                  # dropped first


def test_status_digest_without_index_cache_is_fast(box):
    """R131 edge: with no index cache the defs are omitted and status stays within 500 ms."""
    box.h("view", ["pkg/text.py", "1", "6"], t=6)
    for p in box.swe.glob("index_*.marshal"):
        p.unlink()
    out, wall = box.timed("status", t=20)
    assert "  viewed: pkg/text.py 1-6\n" in out, out
    walls = []
    for _ in range(3):
        box.py("C.state_update(lambda s: s.update(ctx={'phase': 'locator', 'n': 0, 'tail': []}))\n")
        walls.append(box.timed("status", t=20)[1])
    assert statistics.median(walls) <= 0.5, walls


def test_status_digest_nonempty_tree(box):
    """R131 edge: a tree the locator changed (here with the harness's own tools) gets its diffstat and the unscored
    EDITED checkpoint; the diff body is not printed in the phase-start form."""
    box.h("view", ["pkg/mod.py", "1", "2"], t=6)
    (box.ws / "pkg/mod.py").write_text(FILES["pkg/mod.py"].replace("return x\n", "return x * 2\n", 1))
    out = box.h("status", t=30)
    assert "DIFF: pkg/mod.py +1 -1" in out and "@@" not in out and "+    return x * 2" not in out, out
    assert [c["verdict"] for c in box.state()["ckpts"]] == ["EDITED"]


def test_phase_marker_unit(tmp_path):
    """5.1: ctx_next moves locator -> fixer at the first status, fixer -> verifier at the next; edit still ends the
    locator phase (v10.1); install never starts a count."""
    box = Box(tmp_path, FILES, install=False)
    out = box.py("c = C.ctx_next({}, 'install', 5)\n"
                 "a = C.ctx_next(c, 'status', 10)\n"
                 "b = C.ctx_next(a, 'status', 10)\n"
                 "e = C.ctx_next(C.ctx_next({}, 'view', 100), 'edit', 50)\n"
                 "print(c['phase'], a['phase'], b['phase'], C.ctx_next(b, 'status', 1)['phase'], e['phase'], e['n'])\n")
    assert out.split() == ["locator", "fixer", "verifier", "verifier", "fixer", "150.0"]


# status.py run in-process through safe_main with one of its functions replaced (the failure a git error or the helper
# watchdog would cause at that point); the rest of the helper is the bundle's own code.
STATUS_PATCHED = """
import importlib.util, os
spec = importlib.util.spec_from_file_location("status_under_test", os.path.join(%r, "status.py"))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
%s
C.safe_main("status", S.main)
"""


def status_patched(box, patch, t):
    return box.py(STATUS_PATCHED % (str(box.scripts), patch), t=t)


@pytest.mark.parametrize("exc", ["RuntimeError", "C.HelperTimeout"])
def test_failed_phase_start_status_still_ends_the_locator_phase(box, exc):
    """Regression (review 2026-09-30): a phase-start status.py that fails before its output (a git error; the helper
    watchdog's HelperTimeout) still ends the locator phase and restarts vsince. Before the fix safe_main swallowed the
    error with the phase still 'locator', so every later gated call was refused with "run python3 /tmp/swe/status.py
    first", status failed again, and the fixer could loop."""
    close_by_calls(box)
    box.py("C.state_update(lambda s: s.update(vsince=3))\n")
    patch = "def boom(*a, **k):\n    raise %s('injected')\nS.phase_start = boom\n" % exc
    out = status_patched(box, patch, t=60)
    assert out.startswith("HELPER ERROR status: ") and "injected" in out, out
    st = box.state()
    assert st["ctx"]["phase"] == "fixer" and st["ctx"]["tail"][-1][0] == "status" and st["vsince"] == 0, st
    assert box.h("view", ["pkg/mod.py", "1", "2"], t=61).startswith("pkg/mod.py lines 1-2")   # reopened
    later = box.run("status", t=62).stdout                             # its journal shows the injected error
    assert later.startswith("STATUS [t=62s]") and "JOURNAL (last" in later and "LOCATOR DIGEST" not in later, later


def test_failed_later_status_still_starts_the_next_count(box):
    """Regression edge: the v10.1 form failing (the verifier's status) still moves the meter fixer -> verifier and
    restarts vsince, so the verifier's first verify is k = 1 and not the fixer's count plus one."""
    box.h("status", t=50)                                               # the fixer's status ends the locator phase
    box.py("C.state_update(lambda s: s.update(vsince=2))\n")
    out = status_patched(box, "def boom(*a, **k):\n    raise RuntimeError('injected')\nS.later_form = boom\n", t=120)
    assert out.startswith("HELPER ERROR status: "), out
    st = box.state()
    assert st["ctx"]["phase"] == "verifier" and st["vsince"] == 0, st


def test_status_failing_after_its_output_counts_once(box):
    """Regression edge: an error after emit() (which already recorded the call) is not counted a second time: one
    status call moves the meter locator -> fixer, never on to verifier."""
    box.h("view", ["pkg/mod.py", "1", "2"], t=5)
    patch = ("real = C.emit\n"
             "def emit_then_fail(*a, **k):\n    real(*a, **k)\n    raise RuntimeError('after output')\n"
             "C.emit = emit_then_fail\n")
    out = status_patched(box, patch, t=20)
    assert "LOCATOR DIGEST" in out and "HELPER ERROR status: RuntimeError: after output" in out, out
    st = box.state()
    assert st["ctx"]["phase"] == "fixer", st["ctx"]
    assert [h for h, _ in st["ctx"]["tail"]].count("status") == 1, st["ctx"]


# ------------------------------------------------------------------------------------------------------ R134 run.py
def test_run_probe_limit(box):
    """R134 base: 3 executed runs in the locator phase, then PROBE LIMIT (nothing runs); the fixer is unlimited."""
    for i in range(3):
        assert box.h("run", ["echo probe%d" % i], t=10).startswith("exit=0")
    out = box.h("run", ["touch MARKER"], t=11)
    assert lines(out)[0] == ("PROBE LIMIT: 3 runs used before the plan; nothing ran. Locator: reply with your plan; the "
                             "fixer can run code after python3 /tmp/swe/status.py.")
    assert not (box.ws / "MARKER").exists()
    assert_refusal(out, 11)
    assert box.state()["loc"]["runs"] == 3
    box.h("status", t=20)
    for i in range(5):
        assert box.h("run", ["echo fixer%d" % i], t=30).startswith("exit=0")


def test_run_refusals_do_not_use_probes(box):
    """R134 edge: OFFLINE, PYTHON -c and NO INPUT refusals count as locator calls, never as probes."""
    box.h("run", ["curl http://example.com"], t=5)
    box.h("run", ["python3 -c 'import os\\nprint(1)'"], t=5)
    assert box.state()["loc"] == dict(box.state()["loc"], runs=0, calls=2)
    for i in range(3):
        assert box.h("run", ["echo ok%d" % i], t=6).startswith("exit=0")


def test_run_same_run(box):
    """R134 base: a command that ran twice on this tree with the same output is refused; an edit between runs lets
    the third run; a different output never repeats."""
    box.h("status", t=1)                                               # the fixer: no probe limit
    assert box.h("run", ["echo same"], t=10).startswith("exit=0")
    assert box.h("run", ["echo same"], t=12).startswith("exit=0")
    out = box.h("run", ["echo same; touch MARKER"], t=13)
    assert out.startswith("exit=0")                                    # another command
    (box.ws / "MARKER").unlink()
    out = box.h("run", ["echo same"], t=14)
    assert lines(out)[0] == ("SAME RUN: this command already ran twice on this tree with the same output (t=10s, "
                             "t=12s); nothing ran. Change the command or the code.")
    assert_refusal(out, 14)
    (box.ws / "pkg/mod.py").write_text(FILES["pkg/mod.py"] + "\nZ = 1\n")      # an edit between runs
    assert box.h("run", ["echo same"], t=15).startswith("exit=0")
    for i in range(4):                                                 # output differs every time: never refused
        assert box.h("run", ["echo $RANDOM$RANDOM$RANDOM"], t=16).startswith("exit=0")


def test_run_tree_key_only_for_repeats(tmp_path):
    """Regression (review 2026-09-30, timing budget): SAME RUN's tree key (git status) ran on every run.py call, 25-30 ms
    each (min 75 ms against v10.1's 44 ms at load 20), and test_run_overhead_budget_v102 failed at 107 ms over bare
    bash. A first run can never be refused, so it makes no git status call; a repeat makes exactly one."""
    box = Box(tmp_path, FILES)
    box.h("status", t=1)
    path, log = shim_path(tmp_path, box.env)

    def status_calls(cmd):
        if log.exists():
            log.unlink()
        assert box.h("run", [cmd], t=10, PATH=path).startswith("exit=0")
        calls = log.read_text().splitlines() if log.exists() else []
        return sum(1 for c in calls if c.startswith("git ") and " status " in c + " ")
    assert status_calls("echo one") == 0 and status_calls("echo two") == 0          # first runs
    assert status_calls("echo one") == 1                                             # a repeat: its tree is recorded
    runs = box.state()["runs"]
    assert sorted(len(v) for v in runs.values()) == [1, 2] and all(len(e) == 3 for v in runs.values() for e in v)


def test_run_same_run_tree_edges(box):
    """R134 edges of the lazy tree key: after an edit that follows the second run, the next run executes and so does
    the one after it (only one run so far on the new tree), and the next is refused; the first run's tree is never
    recorded, so an edit between runs 1 and 2 that left the output unchanged still refuses a third run on run 2's tree
    (whose output is run 2's)."""
    box.h("status", t=1)
    assert box.h("run", ["echo same"], t=10).startswith("exit=0")
    assert box.h("run", ["echo same"], t=11).startswith("exit=0")
    box.write("pkg/mod.py", FILES["pkg/mod.py"] + "\nZ = 1\n")                      # an edit after run 2
    assert box.h("run", ["echo same"], t=12).startswith("exit=0")
    assert box.h("run", ["echo same"], t=13).startswith("exit=0")                    # run 2 was on the old tree
    assert box.h("run", ["echo same"], t=14).startswith(
        "SAME RUN: this command already ran twice on this tree with the same output (t=12s, t=13s)")
    assert box.h("run", ["echo other"], t=20).startswith("exit=0")
    box.write("pkg/mod.py", FILES["pkg/mod.py"] + "\nZ = 22\n")                     # an edit between runs 1 and 2
    assert box.h("run", ["echo other"], t=21).startswith("exit=0")
    assert box.h("run", ["echo other"], t=22).startswith(
        "SAME RUN: this command already ran twice on this tree with the same output (t=20s, t=21s)")


@pytest.mark.parametrize("cmd", [
    "curl -sL https://example.com/x.tar.gz", "wget http://x/y", "pip install requests", "pip3 install -U rich",
    "pip download six", "python -m pip install httpx", "python3 -m pip install x", "uv pip install x",
    "apt install curl", "apt-get install -y git", "sudo apt-get install -y zlib1g", "conda install numpy",
    "npm install left-pad", "git fetch origin", "git pull", "git clone https://github.com/x/y",
    "git -C . push origin main", "git ls-remote origin", "cd pkg && curl x", "echo a | wget -O- x",
    "timeout 5 pip install x", "FOO=1 curl x"])
def test_run_offline(box, cmd):
    """R134 base: network commands are refused in any phase; nothing runs."""
    box.h("status", t=1)
    out = box.h("run", [cmd + "; touch MARKER"], t=5)
    assert lines(out)[0] == ("OFFLINE: the sandbox has no network; nothing ran. Use the repository and its installed "
                             "packages (python3 /tmp/swe/view.py --obj NAME shows a dependency's source)."), out
    assert not (box.ws / "MARKER").exists()
    assert_refusal(out, 5)


@pytest.mark.parametrize("cmd", ["git log --oneline -1", "git diff", "git status --short", "git show --stat HEAD",
                                 "grep -rn curl pkg || true", "echo 'pip install x'", "python3 -c \"print('curl')\""])
def test_run_offline_allows_local_commands(box, cmd):
    """R134 edge: offline git and commands that merely mention a network tool run as before."""
    assert box.h("run", [cmd], t=5).startswith("exit="), cmd


def test_run_c_literal_newline(box):
    """R134 / B2 regression: python3 -c with literal backslash-n sequences that do not compile is refused (30 such
    SyntaxError calls in 10 golden cases); code with real newlines, or that compiles, runs as before."""
    out = box.h("run", ["python3 -c \"import os\\nprint(os.sep)\""], t=5)
    assert lines(out)[0] == ("PYTHON -c: the code has literal \\n sequences, which Python cannot parse; nothing ran. "
                             "Pipe multi-line code instead: python3 /tmp/swe/run.py python3 <<'EOF' ... EOF"), out
    assert_refusal(out, 5)
    out = box.h("run", ["python3", "-c", "import sys\\nsys.exit(0)"], t=5)         # the argv form, same guard
    assert out.startswith("PYTHON -c:"), out
    assert lines(box.h("run", ["python3 -c \"print('a\\nb')\""], t=6))[:3] == ["exit=0", "a", "b"]
    assert lines(box.h("run", ["python3", "-c", "import os\nprint('real')"], t=6))[:2] == ["exit=0", "real"]


def test_run_bare_interpreter_stdin(box):
    """R134 / B1 regression: a bare interpreter reads the piped heredoc (v10.1 gave it /dev/null: '(no output)' three
    times, then the plan was lost); bash too; without input: NO INPUT."""
    box.h("status", t=1)                                               # the fixer: no probe limit
    assert lines(box.h("run", ["python3"], stdin="import sys\nprint('from stdin')\n", t=5))[:2] == \
        ["exit=0", "from stdin"]
    assert lines(box.h("run", ["python3 -"], stdin="print(6 * 7)\n", t=5))[:2] == ["exit=0", "42"]
    assert lines(box.h("run", ["python3", "-u"], stdin="print('u')\n", t=5))[:2] == ["exit=0", "u"]
    assert lines(box.h("run", ["bash"], stdin="echo from-bash; pwd -P\n", t=5))[:3] == \
        ["exit=0", "from-bash", os.path.realpath(box.ws)]
    out = box.h("run", ["python3"], stdin="", t=6)
    assert lines(out)[0] == ("NO INPUT: python3 got no code on stdin; nothing ran. Pipe it: python3 /tmp/swe/run.py "
                             "python3 <<'EOF' ... EOF"), out
    assert lines(box.h("run", ["sh"], stdin="", t=6))[0].startswith("NO INPUT: sh got no code")


def _open_silent_stdin(box, argv, t):
    """Run a helper with an open pipe on stdin that nobody writes (the harness never redirects stdin)."""
    e = dict(box.env, PWD=str(box.ws), SWE_FAKE_CLOCK=str(t))
    t0 = time.monotonic()
    p = subprocess.Popen([PY, str(box.scripts / "run.py")] + argv, cwd=str(box.ws), env=e, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True)
    out = p.communicate(timeout=20)[0]
    return out, time.monotonic() - t0


def test_run_stdin_guard_costs(box):
    """R134 edges: a bare python3 with an open silent stdin says NO INPUT within 1.5 s; a non-interpreter command never
    reads stdin, so it never pays the 1 s guard."""
    out, wall = _open_silent_stdin(box, ["python3"], 5)
    assert out.startswith("NO INPUT: python3 got no code") and wall <= 1.5 + 0.5, (out, wall)
    walls = []
    for i in range(3):
        out, wall = _open_silent_stdin(box, ["echo quick%d" % i], 6)
        assert out.startswith("exit=0")
        walls.append(wall)
    assert min(walls) < 0.8, walls


def test_run_killpg_with_input(tmp_path, box):
    """R134 edge (R26 with input): a bash script from stdin that leaves background sleeps is killed as a group."""
    box.h("status", t=1)
    S = unique_sleep(tmp_path)
    t0 = time.monotonic()
    out = box.h("run", ["--timeout", "2", "bash"], stdin="%s 30 &\n%s 20\n" % (S, S), t=5)
    assert time.monotonic() - t0 <= 4.5 and lines(out)[0].startswith("TIMEOUT after 2s"), out
    time.sleep(0.5)
    left = find_orphans([S])
    kill_processes(left)
    assert not left, left


def test_run_calibrated_default_timeout(box):
    """R134 / R1: once the package import time is measured the default timeout is max(20, t_import + 15); an explicit
    --timeout is kept; a TIMEOUT line names a slow import (t_import >= 5)."""
    code = ("import json, runpy, sys\ng = runpy.run_path(%r, run_name='probe')\nC = g['C']\n"
            "for argv, ti in (([], None), ([], 3.0), ([], 12.0), (['--timeout', '20'], 12.0), ([], 200.0)):\n"
            "    a = C.parse_args(argv, g['FLAGS'], (), usage=g['USAGE'], interspersed=False)\n"
            "    print(json.dumps(g['effective_timeout'](a, ti)))\n" % str(box.scripts / "run.py"))
    got = [json.loads(x) for x in box.py(code, t=10).splitlines()]
    assert [g[0] for g in got] == [20.0, 20.0, 27.0, 20.0, 90.0], got
    box.h("status", t=1)
    box.py("C.state_update(lambda s: s.update(t_import=6.2))\n")
    out = box.h("run", ["--timeout", "1", "sleep 5"], t=5)
    assert lines(out)[0] == ("TIMEOUT after 1s (partial output below); the package import alone takes 6s here. If the "
                             "issue is about a hang or loop, this may be the bug."), out


def test_run_overhead_budget_v102(box):
    """Speed: v10.2's checks (gate, probe count, OFFLINE, SAME RUN tree key) keep run.py within 100 ms of bare bash,
    run the way the model runs it (python3 /tmp/swe/run.py: the installed copy, libraries precompiled by install),
    with a new command each time (a repeated one is refused by SAME RUN, which is cheaper)."""
    box.h("status", t=1)
    ours, bare = [], []
    env = dict(box.env, SWE_FAKE_CLOCK="5", PWD=str(box.ws))
    for i in range(7):
        t0 = time.monotonic()
        r = subprocess.run([PY, str(box.swe / "run.py"), "true %d" % i], cwd=str(box.ws), env=env, capture_output=True,
                           text=True, stdin=subprocess.DEVNULL)
        ours.append(time.monotonic() - t0)
        assert r.stdout.startswith("exit=0"), r.stdout + r.stderr
        t0 = time.monotonic()
        subprocess.run(["bash", "-c", "true"], env=box.env, cwd=str(box.ws))
        bare.append(time.monotonic() - t0)
    assert min(ours) - min(bare) <= 0.1, (ours, bare)


# ------------------------------------------------------------------------------------------------------ R135 grep
def test_grep_missing_path_closest(box):
    """R135 base: a missing --path gets the closest real paths and searches nothing; the positional form keeps v10.1's
    NOTE and adds them; nothing close prints no list."""
    out = box.h("grep", ["parse", "--path", "pkg/mdo.py"], t=5)
    assert lines(out)[0] == "GREP: 0 hits in 0 files (shown 0)", out
    assert re.match(r"^NOTE: --path pkg/mdo\.py does not exist; closest: pkg/mod\.py(, [\w/.]+){0,2} \(nothing "
                    r"searched\)$", lines(out)[1]), out                      # at most 3, the closest first
    out = box.h("grep", ["parse_header", "pkg/text2.py"], t=5)
    assert "NOTE: pkg/text2.py is not a path in the workspace; searched everywhere. closest: pkg/text.py" in out, out
    assert "GREP: 1 hits" in out
    out = box.h("grep", ["parse", "--path", "zzzz/qqqq_wwww.py"], t=5)
    assert "NOTE: --path zzzz/qqqq_wwww.py does not exist (nothing searched)" in out and "closest" not in out, out
    out = box.h("grep", ["parse", "--path", "lib/mod.py"], t=5)       # the same basename elsewhere
    assert "closest: pkg/mod.py" in out, out


@pytest.mark.parametrize("rx", ["#3104", "gh-3104", "GH-3104", "issue 3104", "issue #3104", "Issue #12", "# 77"])
def test_grep_issue_marker_refused(box, rx):
    """R135 base: a regex that is only an issue marker is refused (rich_3105 searched issue numbers 8 times)."""
    out = box.h("grep", [rx], t=5)
    assert lines(out)[0] == "GREP: issue numbers are not in the code; nothing ran. Search the names and words of the " \
                            "issue.", out
    assert_refusal(out, 5)


def test_grep_bare_number_runs(box):
    """R135 edge: a bare number is a legitimate search (HTTP codes); with 0 hits it adds the issue note."""
    box.write("pkg/codes.py", "NOT_FOUND = 404\n")
    box.git("add", "-A")
    out = box.h("grep", ["404"], t=5)
    assert out.startswith("GREP: 1 hits") and "issue numbers" not in out, out
    out = box.h("grep", ["3104"], t=5)
    assert out.startswith("GREP: 0 hits") and "NOTE: issue numbers are not in the code." in out, out


# ------------------------------------------------------------------------------------------------------ R136 locate
def test_locate_empty_query_refused(box):
    """R136 base: a query with no searchable words (issue numbers, URLs, hashes, stop words) is refused before the
    index is built."""
    for q in ("#3104 see #3104", "https://github.com/x/y/issues/3 #3", "fix the bug", "deadbeef1234 b/12345678"):
        out = box.h("locate", [q], t=5)
        assert lines(out)[0] == ("LOCATE: no searchable words (issue numbers, URLs and hashes are not in the code); "
                                 "nothing ran. Search the names and words of the issue."), (q, out)
        assert_refusal(out, 5)
    assert not list(box.swe.glob("index_*.marshal"))
    assert box.h("locate", ["parse header #3104"], t=6).startswith("LOCATE:")


def test_locate_top_state(box):
    """R136: every successful call stores its top 3 source files (tests left out) with their top symbol."""
    box.h("locate", ["divide text offsets cell len"], t=5)
    top = box.state()["locate_top"]
    assert top[0] == ["pkg/text.py", "Text.divide", 2, 6], top
    assert all(not p.startswith("tests/") for p, _, _, _ in top) and 1 <= len(top) <= 3
    box.h("locate", ["qqqzzz_nothing_matches"], t=6)                   # no match: the last ranking is kept
    assert box.state()["locate_top"] == top


TRACKER_STATEMENT = """frobnicate_widget crashes on empty input

BUG=b/123456789
TESTED=unit
RELNOTES=n/a
PiperOrigin-RevId: 998877
Change-Id: I0123456789abcdef0123456789abcdef01234567
Reviewed-by: Some Reviewer <r@example.com>
Signed-off-by: Someone <s@example.com>
See cl/55555555 and b/44444444 for details.
"""


def test_locate_tracker_boilerplate(tmp_path):
    """R136 / R5 (hidden.md T10): internal-tracker lines and b/NNNN, cl/NNNN references are dropped, so the identifier's
    file ranks first although other files define reviewed/tested/signed names."""
    files = dict(FILES)
    files["pkg/widget.py"] = "def frobnicate_widget(x):\n    return x[0]\n"
    files["pkg/review.py"] = ("def reviewed_by(someone):\n    return someone\n\n\ndef signed_off(someone):\n"
                              "    return someone\n\n\ndef tested_unit(change_id, piper_origin_rev_id, relnotes):\n"
                              "    return change_id\n\n\nclass Reviewer(object):\n    review_history = 998877\n")
    box = Box(tmp_path, files)
    out = box.h("locate", [TRACKER_STATEMENT], t=5)
    assert re.search(r"^1\. pkg/widget\.py ", out, re.M), out
    assert "pkg/review.py" not in out, out                            # nothing of the boilerplate is searched
    old = Box(tmp_path / "v101", files, src=V101_SCRIPTS)            # control: v10.1 searched the boilerplate
    assert re.search(r"^\d\. pkg/review\.py ", old.h("locate", [TRACKER_STATEMENT], t=5), re.M)
    got = box.py("import runpy\ng = runpy.run_path(%r, run_name='probe')\nprint(repr(g['clean_query'](%r)))\n"
                 % (str(box.scripts / "locate.py"), TRACKER_STATEMENT))
    for gone in ("BUG", "TESTED", "PiperOrigin", "Change-Id", "Reviewed-by", "Signed-off-by", "b/123456789",
                 "cl/55555555", "998877"):
        assert gone not in got, (gone, got)
    assert "frobnicate_widget crashes on empty input" in got and "for details." in got


def test_locate_keeps_prose_bug_titles(tmp_path):
    """R5 guard (a deviation from the literal regex, reported): a pandas-style 'BUG: <title>' line is the issue itself,
    so it is kept; only KEY=value lines and tracker-reference values are boilerplate."""
    box = Box(tmp_path, FILES, install=False)
    code = ("import runpy\ng = runpy.run_path(%r, run_name='probe')\ncq = g['clean_query']\n"
            "print(repr(cq('BUG: Text.divide drops the last offset\\nBUG: b/1234\\nBUG=b/99\\nTESTED: none')))\n"
            % str(box.scripts / "locate.py"))
    got = box.py(code)
    assert "Text.divide drops the last offset" in got and "b/1234" not in got and "b/99" not in got, got


def test_locate_clean_query_identical_on_public_statements(tmp_path):
    """R136 / R98 by construction: on every public statement v10.2's clean_query gives v10.1's text, so the ranking
    (unchanged code) and its recall are identical."""
    tasks = ROOT / "data" / "tasks.jsonl"
    if not tasks.exists():
        pytest.skip("data/tasks.jsonl absent")
    rows = [json.loads(x) for x in tasks.read_text().splitlines() if x.strip()]
    stmts = [r["problem_statement"] for r in rows]
    assert len(stmts) >= 74
    box = Box(tmp_path, FILES, install=False)
    old = copy_helpers(tmp_path / "v101", V101_SCRIPTS)
    (tmp_path / "stmts.json").write_text(json.dumps(stmts))
    code = ("import json, runpy\n"
            "a = runpy.run_path(%r, run_name='v101')['clean_query']\n"
            "b = runpy.run_path(%r, run_name='v102')['clean_query']\n"
            "st = json.load(open(%r))\nprint(sum(1 for s in st if a(s) != b(s)), len(st))\n"
            % (str(old / "locate.py"), str(box.scripts / "locate.py"), str(tmp_path / "stmts.json")))
    diff, n = box.py(code).split()
    assert diff == "0" and int(n) == len(stmts)
