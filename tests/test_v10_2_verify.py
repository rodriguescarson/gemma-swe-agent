"""v10.2 verify side (docs/v10/SPEC_v10_2.md 5.4, 5.7, 5.8; R133, R137, R138, R140, R141): the locator's reproduction
budget, the repair-budget NEXT lines, slow-import calibration, the import check's namespace and non-src roots, and the
base-tree size guard.

Regression tests for the defects this version fixes: B3/B4 a slow import read as a HANG (test_slow_import_not_a_hang,
hidden.md probe E), B6 a skipped import check printed "ok" (test_import_check_namespace_and_roots, probe K), B7 the
RED text contradicted the repair budget (test_next_lines_follow_repair_budget: 12 % of the no-repair ablation arm
repaired because verify.py said "Fix the code, then run verify again").
Every helper runs from a temp copy of submissions/v10_2 as a subprocess (tests/v10_support/v102.py).
"""
import json
import os
import pathlib
import re
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from v10_support.repo import no_orphans, git  # noqa: F401,E402
from v10_support.v102 import Box, V102_SCRIPTS, lines  # noqa: E402

pytestmark = pytest.mark.skipif(not (V102_SCRIPTS / "_swe_common.py").exists(), reason="v10.2 bundle not built")
NIGHTLY = os.environ.get("G4_NIGHTLY") == "1"

BUGGY = "def area(w, h):\n    return w + h\n"
FIXED = "def area(w, h):\n    return w * h\n"
KEEP = "\n\ndef keep():\n    return 1\n"
TEST = "from {mod} import area, keep\n\n\ndef test_keep():\n    assert keep() == 1\n"
REPRO = "from {mod} import area\n# CLAIM 1: area of a 2x3 rectangle is 6\nassert area(2, 3) == 6, repr(area(2, 3))\n"
GEO = {"pkg/__init__.py": "", "pkg/geo.py": BUGGY + KEEP, "tests/test_geo.py": TEST.format(mod="pkg.geo")}
PASSING = "from pkg.geo import area\n# CLAIM 1: 2+2\nassert area(2, 2) == 4\n"
SAVED = "NEXT: reproduction saved. Locator: reply with your plan now; the next stages run it."
FIXER_USED = ("Fixer: your repair round is used; reply with your notes. Verifier: fix the code, then run "
              "python3 /tmp/swe/verify.py again.")
ROUNDS_USED = "The repair rounds are used: run python3 /tmp/swe/finalize.py now; it keeps the best checked version."


def repro(box, text, t=10):
    return box.h("verify", ["--repro-only"], stdin=text, t=t)


# ------------------------------------------------------------------------------------------------ R133 repro budget
def test_repro_budget_locator(tmp_path):
    """R133 base: in the locator phase two new reproductions run, the third is refused with the right REPRO word."""
    box = Box(tmp_path, GEO)
    out = repro(box, PASSING)
    assert lines(out)[0] == ("REPRO: claim 1 passes on original - it misses the bug; rewrite it once with another input "
                             "shape, and if that passes too, reply with REPRO: none."), out
    out = repro(box, PASSING.replace("2, 2", "0, 0").replace("== 4", "== 0"))
    assert lines(out)[0] == ("REPRO: claim 1 passes on original - it misses the bug; 2 reproductions tried: reply with "
                             "your plan and REPRO: none."), out
    out = repro(box, REPRO.format(mod="pkg.geo"))
    assert lines(out)[0] == ("REPRO LIMIT: 2 reproductions tried; nothing ran. Reply with your plan and REPRO: none."), out
    assert lines(out)[-1] == "[t=10s]" and len(out) <= 600
    assert box.state()["loc"]["repros"] == 2
    assert "== 6" not in (box.swe / "repro.py").read_text()          # the refused text was not saved


def test_repro_fail_then_reply(tmp_path):
    """R133 edges: a reproduction that fails on original ends with the reply NEXT line; the third attempt names the
    saved reproduction's state ('fails on original'); re-running the saved reproduction (no text) is not an attempt."""
    box = Box(tmp_path, GEO)
    assert "misses the bug" in repro(box, PASSING)
    out = repro(box, REPRO.format(mod="pkg.geo"))
    assert lines(out)[0].startswith("REPRO: fails on original (1 of 1 claims): claim 1 AssertionError") and \
        lines(out)[-2] == SAVED, out
    out = repro(box, PASSING)
    assert lines(out)[0] == ("REPRO LIMIT: 2 reproductions tried; nothing ran. Reply with your plan and REPRO: fails on "
                             "original."), out
    for _ in range(2):                                                # the saved one re-runs: no attempt counted
        out = box.h("verify", ["--repro-only"], t=12)
        assert out.startswith("REPRO: fails on original") and SAVED in out, out
    assert box.state()["loc"]["repros"] == 2


def test_repro_invalid_second_attempt(tmp_path):
    """R133 edge: a second attempt that does not compile tells the locator to reply (no third attempt is left)."""
    box = Box(tmp_path, GEO)
    assert "misses the bug" in repro(box, PASSING)
    out = repro(box, "from pkg.geo import area\n# CLAIM 1: x\nassert area(2, 3) == 6 +\n")
    assert lines(out)[0].startswith("REPRO INVALID: syntax error line 3:") and \
        lines(out)[0].endswith("2 reproductions tried: reply with your plan and REPRO: none."), out
    assert (box.swe / "repro.py").read_text() == PASSING                 # an uncompilable text is never saved here


def test_repro_invalid_keeps_the_failing_reproduction(tmp_path):
    """R133 edge (v10.2 robustness): after a reproduction that fails on original, an uncompilable second attempt does
    not replace it, and the reply line names 'fails on original'; outside the locator phase v10.1 saves it as before."""
    box = Box(tmp_path, GEO)
    good = REPRO.format(mod="pkg.geo")
    assert SAVED in repro(box, good)
    out = repro(box, "from pkg.geo import area\n# CLAIM 1: x\nassert area(\n")
    assert lines(out)[0].startswith("REPRO INVALID:") and lines(out)[0].endswith(
        "2 reproductions tried: reply with your plan and REPRO: fails on original."), out
    assert (box.swe / "repro.py").read_text() == good
    assert box.h("verify", ["--repro-only"], t=12).startswith("REPRO: fails on original")
    box.h("status", t=60)
    out = repro(box, "x = (\n", t=70)
    assert lines(out)[0] == "REPRO INVALID: syntax error line 1: '(' was never closed. Fix the reproduction and pipe it " \
                            "again." or lines(out)[0].endswith("Fix the reproduction and pipe it again."), out
    assert (box.swe / "repro.py").read_text() == "x = (\n"


def test_repro_not_finished_texts(tmp_path):
    """R133 edge: claims that did not finish on original: v10.1's text before T_LOCATOR and outside the locator phase,
    the reply text from t=75 in the locator phase."""
    box = Box(tmp_path, GEO, install=False)
    code = ("import runpy\ng = runpy.run_path(%r, run_name='probe')\nimport _swe_gate as G\n"
            "_, cl, _, _ = G._parse('# CLAIM 1: a\\nx = 1\\n')\n"
            "for a in (1, 2, None):\n    print(g['_orig_line'](cl, {1: {'status': 'UNKNOWN'}}, a))\n"
            % str(box.scripts / "verify.py"))
    early = box.py(code, t=60).splitlines()
    late = box.py(code, t=80).splitlines()
    v101 = "REPRO: the claims did not finish in time on original; shorten them and pipe the reproduction again."
    reply = "REPRO: the claims did not finish in time on original; reply with your plan and REPRO: none."
    assert early == [v101, v101, v101] and late == [reply, reply, v101], (early, late)


def test_repro_unlimited_after_the_phase_marker(tmp_path):
    """R133 edge: once status.py ended the locator phase, --repro-only is unlimited and its texts are v10.1's."""
    box = Box(tmp_path, GEO)
    box.h("status", t=5)
    for i in range(4):
        out = repro(box, PASSING.replace("== 4", "== 4  # %d" % i), t=20 + i)
        assert lines(out)[0] == ("REPRO: claim 1 passes on original - it misses the bug; rewrite it once with another "
                                 "input shape."), out
        assert SAVED not in out
    out = repro(box, REPRO.format(mod="pkg.geo"), t=30)
    assert lines(out)[0].startswith("REPRO: fails on original") and SAVED not in out, out


def test_repro_hang_bug_keeps_its_hang_and_calibrates_once(tmp_path):
    """R133 + R138 edge (the public hang bugs, R105): a reproduction that hangs on original triggers the import-time
    measurement once; the package imports fast, so no budget changes and the HANG stands."""
    files = dict(GEO)
    files["pkg/geo.py"] = "def spin():\n    while True:\n        pass\n" + KEEP
    box = Box(tmp_path, files)
    t0 = time.monotonic()
    out = repro(box, "from pkg.geo import spin\n# CLAIM 1: spin returns\nspin()\n")
    assert time.monotonic() - t0 < 25
    assert lines(out)[0] == "REPRO: claim 1 hangs on original (expected for hang bugs)." and SAVED in out, out
    st = box.state()
    assert st["t_import"] is not None and st["t_import"] < 2.0 and st["t_import_mods"] == ["pkg"]
    assert box.py("import _swe_gate as G\nprint(G.cal(C.CLAIM_TIMEOUT), G.cal(C.IMPORT_CHECK))").split() == \
        ["10.0", "10.0"]


# ------------------------------------------------------------------------------------------------ R137 NEXT lines
UNIT = r'''
import _swe_gate as G
def R(**kw):
    base = {"nonempty": True, "import": {"ok": True}, "repro": {}, "tests": {"status": "none"}}
    base.update(kw)
    return base
claims = {"summary": {"valid": [1], "fixed": 0, "broke": 0, "classes": {1: "STILL FAILS"}, "text": "0/1 claims fixed"},
          "cur": {1: {"status": "FAIL", "sig": "AssertionError: 5"}}}
green = {"summary": {"valid": [1], "fixed": 1, "broke": 0, "classes": {1: "FIXED"}, "text": "1/1 claims fixed"}, "cur": {}}
cases = {
    "claim": R(repro=claims),
    "import": R(**{"import": {"ok": False, "where": "pkg/geo.py:3", "module": "pkg.geo"}}),
    "regress": R(repro=green, tests={"status": "ok", "regressions": ["tests/t.py::test_a"], "collects": 1}),
    "hang": R(repro=green, tests={"status": "ok", "hang_now": True, "regressions": [], "collects": 1}),
    "coll": R(repro=green, tests={"status": "ok", "regressions": [], "collects": 0,
                                  "coll_now": {"tests/t.py": "ImportError: x"}}),
    "green": R(repro=green),
    "amber": R(repro={"summary": {"valid": [], "fixed": 0, "broke": 0, "classes": {1: "INVALID"}, "text": "0/0"},
                      "cur": {}}),
    "empty": R(nonempty=False),
    "notchecked": R(repro=green, **{"import": {"ok": True, "not_checked": ["my-lib/geo.py"],
                                               "amber": "import of my-lib/geo.py not checked"}}),
}
import json
out = {}
for name, r in cases.items():
    out[name] = [G.verdict(r, k) for k in (1, 2, 3, 4)]
print(json.dumps(out))
'''


def test_next_lines_follow_repair_budget_unit(tmp_path):
    """R137 base (unit): each RED kind (claims, import, regressions, hang-now, collection) gets v10.1's line at k=1,
    the fixer-reply form at k=2 and the finalize form from k=3; the regression sentence stays on every RED
    regressions line; GREEN, AMBER and NO SOURCE CHANGE never change; no NEXT line says undo or must fix."""
    box = Box(tmp_path, GEO, install=False)
    got = json.loads(box.py(UNIT))
    v1 = {"claim": "NEXT: claim 1 still fails (AssertionError: 5). Fix the code, then run python3 /tmp/swe/verify.py "
                   "again.",
          "import": "NEXT: fix the error at pkg/geo.py:3 with python3 /tmp/swe/edit.py, then run "
                    "python3 /tmp/swe/verify.py again."}
    reason = {"claim": "claim 1 still fails (AssertionError: 5).", "import": "the import fails at pkg/geo.py:3.",
              "hang": "the tests finished on original but time out now (look for an endless loop in your change).",
              "coll": "tests/t.py no longer collects (ImportError: x).",
              "regress": "If a test asserts the OLD behaviour that the issue asks to change, keep your fix (the graders "
                         "update such tests)."}
    for kind in ("claim", "import", "regress", "hang", "coll"):
        rows = got[kind]
        assert all(r[2] == "RED" for r in rows), kind
        if kind in v1:
            assert rows[0][1] == v1[kind], rows[0]
        assert rows[1][1] == "NEXT: %s %s" % (reason[kind], FIXER_USED), rows[1]
        assert rows[2][1] == rows[3][1] == "NEXT: %s %s" % (reason[kind], ROUNDS_USED), rows[2]
    assert got["regress"][0][1].startswith(reason["regress"]) and got["regress"][0][1].endswith(
        "Otherwise your change broke it: fix the code.")
    for kind in ("green", "amber", "empty"):
        assert len({r[1] for r in got[kind]}) == 1 and got[kind][0][2] in ("GREEN", "AMBER", "EMPTY"), got[kind]
    assert got["green"][3] == ["VERIFY: GREEN", "NEXT: ready. Fixer: reply with your notes. Verifier: run "
                               "python3 /tmp/swe/finalize.py.", "GREEN"]
    assert got["notchecked"][0][:1] == ["VERIFY: AMBER - import of my-lib/geo.py not checked"]
    text = json.dumps(got)
    assert "undo" not in text.lower() and "must fix" not in text.lower()


def test_next_lines_follow_repair_budget(tmp_path):
    """R137 / B7 regression: the RED NEXT line of verify.py follows the per-stage budget. k counts full verify runs
    since the last status.py, SAME AS LAST RUN included; the repair-budget form replaces v10.1's STOP line."""
    box = Box(tmp_path, GEO)
    repro(box, REPRO.format(mod="pkg.geo"))
    box.h("status", t=60)                                              # the fixer starts
    box.write("pkg/geo.py", "def area(w, h):\n    return w - h\n" + KEEP)   # a wrong fix: the claim still fails
    outs = [box.h("verify", t=70 + i) for i in range(3)]
    assert lines(outs[0])[0] == "VERIFY: RED - 0/1 claims fixed", outs[0]
    nx = [next(x for x in lines(o) if x.startswith("NEXT:")) for o in outs]
    assert nx[0] == "NEXT: claim 1 still fails (AssertionError: -1). Fix the code, then run python3 /tmp/swe/verify.py " \
                    "again.", nx[0]
    assert outs[1].startswith("SAME AS LAST RUN") and nx[1] == "NEXT: claim 1 still fails (AssertionError: -1). " + \
        FIXER_USED, nx[1]
    assert nx[2] == "NEXT: claim 1 still fails (AssertionError: -1). " + ROUNDS_USED, nx[2]
    assert "STOP re-running verify" not in outs[2]
    assert box.state()["vsince"] == 3
    box.h("status", t=90)                                              # the verifier starts: k restarts
    assert box.state()["vsince"] == 0
    out = box.h("verify", t=91)
    assert out.startswith("SAME AS LAST RUN") and "Fix the code, then run python3 /tmp/swe/verify.py again." in out
    assert "your repair round is used" not in out


def test_amber_third_identical_run_unchanged(tmp_path):
    """R137 edge: AMBER keeps v10.1's READY line and, on the third identical run, its STOP line."""
    box = Box(tmp_path, GEO)
    box.h("status", t=5)
    box.write("pkg/geo.py", FIXED + KEEP)
    outs = [box.h("verify", t=20 + i) for i in range(3)]
    assert lines(outs[0])[0] == "VERIFY: AMBER - no reproduction saved", outs[0]
    for o in outs:
        assert "NEXT: ready. Fixer: reply with your notes. Verifier: run python3 /tmp/swe/finalize.py." in o
    assert "STOP re-running verify; decide now." in outs[2] and "STOP" not in outs[1]


def test_regression_red_keeps_the_old_behaviour_rule(tmp_path):
    """R137 edge: a RED regressions verdict at k=2 keeps the old-behaviour sentence and the REGRESSIONS section does not
    add 'fix the code' after the fixer was told to reply."""
    box = Box(tmp_path, GEO)
    repro(box, REPRO.format(mod="pkg.geo"))
    box.h("status", t=60)
    box.write("pkg/geo.py", FIXED + KEEP.replace("return 1", "return 2"))
    first = box.h("verify", t=70)
    assert lines(first)[0] == "VERIFY: RED - regressions", first
    assert "NEXT: If a test asserts the OLD behaviour that the issue asks to change, keep your fix (the graders update " \
           "such tests). Otherwise your change broke it: fix the code." in first
    second = box.h("verify", t=75)
    assert "NEXT: If a test asserts the OLD behaviour that the issue asks to change, keep your fix (the graders update " \
           "such tests). " + FIXER_USED in second, second


# ------------------------------------------------------------------------------------------------ R138 slow imports
def slow_files(secs):
    return {"pkg/__init__.py": "import time\ntime.sleep(%s)\n" % secs, "pkg/geo.py": BUGGY + KEEP,
            "tests/test_geo.py": TEST.format(mod="pkg.geo")}


def _slow_flow(tmp_path, secs):
    """hidden.md probe E: the locator's reproduction, then the fix, then verify and finalize on a package whose
    import takes `secs` seconds."""
    box = Box(tmp_path, slow_files(secs))
    t0 = time.monotonic()
    o1 = repro(box, REPRO.format(mod="pkg.geo"), t=10)
    w1 = time.monotonic() - t0
    box.write("pkg/geo.py", FIXED + KEEP)
    box.h("status", t=60)
    t0 = time.monotonic()
    o2 = box.h("verify", t=70, timeout=150)
    w2 = time.monotonic() - t0
    o3 = box.h("finalize", t=100, timeout=150)
    return box, o1, w1, o2, w2, o3


def _assert_not_a_hang(box, o1, w1, o2, w2, o3, secs):
    assert "hangs on original" not in o1 and "RED - import error" not in o2 and "HANG" not in o2, (o1, o2)
    st = box.state()
    assert st["t_import"] is not None and abs(st["t_import"] - secs) < 4 and st["t_import_mods"] == ["pkg"], st
    assert not st.get("t_import_timeout")
    assert w1 <= 110 and w2 <= 60 + 10, (w1, w2)                       # within the helper watchdog and VERIFY_TOTAL
    assert o3.startswith("READY:"), o3


def test_slow_import_not_a_hang(tmp_path):
    """R138 / B3-B4 regression (hidden.md probe E, 12 s import): v10.1 printed 'claim 1 hangs on original' and
    'VERIFY: RED - import error ... HANG'. v10.2 measures the import once, re-runs the hung claim with the calibrated
    budget (it fails on original: a valid reproduction), and verify imports with that budget."""
    box, o1, w1, o2, w2, o3 = _slow_flow(tmp_path, 12)
    assert lines(o1)[0].startswith("REPRO: fails on original (1 of 1 claims)"), o1
    _assert_not_a_hang(box, o1, w1, o2, w2, o3, 12)
    assert re.match(r"VERIFY: (GREEN|AMBER)", lines(o2)[0]), o2
    assert "claim 1 FIXED" in o2 or "1/1 claims fixed" in o2, o2
    got = [float(x) for x in box.py("import _swe_gate as G\nprint(G.cal(C.CLAIM_TIMEOUT), G.cal(C.IMPORT_CHECK))").split()]
    assert all(abs(g - (2.5 * box.state()["t_import"] + 2)) < 1e-6 for g in got), got


@pytest.mark.skipif(not NIGHTLY, reason="NIGHTLY tier (G4_NIGHTLY=1): about 3 minutes")
def test_slow_import_not_a_hang_30s(tmp_path):
    """R138 (hidden.md probe E at 30 s): no false HANG or RED; claims that cannot finish in time are UNKNOWN."""
    box, o1, w1, o2, w2, o3 = _slow_flow(tmp_path, 30)
    _assert_not_a_hang(box, o1, w1, o2, w2, o3, 30)


def test_genuine_import_hang_stays_red(tmp_path):
    """R138 edge: a change whose import never finishes (while True at module level) while the original imports fast
    is still RED - import error (HANG); the measurement shows the original is fast."""
    box = Box(tmp_path, GEO)
    box.h("status", t=5)
    box.write("pkg/geo.py", FIXED + KEEP + "\nwhile True:\n    pass\n")
    t0 = time.monotonic()
    out = box.h("verify", t=20)
    assert time.monotonic() - t0 < 30
    assert lines(out)[0] == "VERIFY: RED - import error" and "HANG (the import did not finish in 10s)" in out, out
    assert box.state()["t_import"] < 2.0


def test_original_also_slow_is_unknown(tmp_path):
    """R138 edge: when the original does not import within the measurement either, the current side's HANG is not an
    error in the change: IMPORT UNKNOWN, never RED (the verdict is at most AMBER)."""
    box = Box(tmp_path, slow_files(100))
    box.h("status", t=5)
    box.write("pkg/geo.py", FIXED + KEEP)
    t0 = time.monotonic()
    out = box.h("verify", t=240, timeout=90)                            # late: verify's span is about 22 s
    assert time.monotonic() - t0 < 40
    assert "RED" not in lines(out)[0] and lines(out)[0].startswith("VERIFY: AMBER"), out
    assert re.search(r"IMPORT: UNKNOWN - the package import takes \d+s on original too \(slow dependency\); not an "
                     r"error in your change", out), out
    assert box.state().get("t_import_timeout") is True


def test_no_calibration_on_a_fast_repo(tmp_path):
    """R138 edge: nothing hangs, so no import-time measurement runs (state.t_import stays None) and budgets are v10.1's."""
    box = Box(tmp_path, GEO)
    repro(box, REPRO.format(mod="pkg.geo"))
    box.h("status", t=60)
    box.write("pkg/geo.py", FIXED + KEEP)
    assert lines(box.h("verify", t=70))[0] == "VERIFY: GREEN"
    assert box.h("finalize", t=90).startswith("READY:")
    st = box.state()
    assert st["t_import"] is None and st["t_import_mods"] == []
    assert box.py("import _swe_gate as G\nprint(G.cal(C.CLAIM_TIMEOUT), G.cal(C.IMPORT_CHECK), G.claims_total())")\
        .split() == ["10.0", "10.0", "25.0"]


def test_calibrated_budgets_unit(tmp_path):
    """R138 unit: cal() = max(base, 2.5 t + 2) from t >= base/2, capped at VERIFY_TOTAL; claims_total leaves room for
    one calibrated claim; imported_tops lists the reproduction's non-stdlib imports."""
    box = Box(tmp_path, GEO, install=False)
    code = ("import _swe_gate as G\n"
            "for ti in (None, 3.0, 4.9, 5.0, 12.0, 40.0):\n"
            "    C.state_update(lambda s: s.update(t_import=ti))\n"
            "    print(ti, G.cal(10), G.claims_total())\n"
            "print(G.imported_tops('import os, json\\nfrom pkg.geo import area\\nimport numpy as np\\nfrom . import x\\n'))\n")
    got = box.py(code).splitlines()
    assert got[:6] == ["None 10.0 25.0", "3.0 10.0 25.0", "4.9 10.0 25.0", "5.0 14.5 25.0", "12.0 32.0 35.0",
                       "40.0 60.0 60.0"], got
    assert got[6] == "['pkg', 'numpy']", got[6]


# ------------------------------------------------------------------------------------------------ R140 import roots
NS_REPRO = "from {mod} import area\n# CLAIM 1: area of a 2x3 rectangle is 6\nassert area(2, 3) == 6, repr(area(2, 3))\n"
RAISES = "def helper():\n    return 1\n\nundefined_name_at_import\n"


@pytest.mark.parametrize("layout,files,changed,extra,mod,pp", [
    ("namespace", {"nspkg/geo.py": BUGGY + KEEP, "nspkg/extra.py": "def helper():\n    return 1\n"},
     "nspkg/geo.py", "nspkg/extra.py", "nspkg.geo", ""),
    ("python", {"python/pkg/__init__.py": "", "python/pkg/geo.py": BUGGY + KEEP,
                "python/pkg/extra.py": "def helper():\n    return 1\n"}, "python/pkg/geo.py", "python/pkg/extra.py",
     "pkg.geo", "python"),
    ("lib", {"lib/pkg/__init__.py": "", "lib/pkg/geo.py": BUGGY + KEEP, "lib/pkg/extra.py": "def helper():\n    return 1\n"},
     "lib/pkg/geo.py", "lib/pkg/extra.py", "pkg.geo", "lib"),
    ("packages", {"packages/a/src/a/__init__.py": "", "packages/a/src/a/geo.py": BUGGY + KEEP,
                  "packages/a/src/a/extra.py": "def helper():\n    return 1\n"},
     "packages/a/src/a/geo.py", "packages/a/src/a/extra.py", "a.geo", "packages/a/src"),
])
def test_import_check_namespace_and_roots(tmp_path, layout, files, changed, extra, mod, pp):
    """R140 / B6 regression (hidden.md probe K): a changed module that raises at import, which the reproduction does not
    import, is RED - import error under namespace, python/, lib/ and packages/*/src roots (v10.1 skipped the check
    there and printed 'IMPORT: ok (no changed module inside a package)', so the verdict could be GREEN)."""
    box = Box(tmp_path, files)
    if pp:
        box.env["PYTHONPATH"] = os.pathsep.join([str(box.ws), str(box.ws / pp)])
    assert repro(box, NS_REPRO.format(mod=mod)).startswith("REPRO: fails on original"), layout
    box.h("status", t=60)
    box.write(changed, FIXED + KEEP)
    box.write(extra, RAISES)
    out = box.h("verify", t=70)
    assert lines(out)[0] == "VERIFY: RED - import error", (layout, out)
    assert "NameError" in out and "undefined_name_at_import" in out, out
    box.write(extra, "def helper():\n    return 2\n")                    # the same layout imports cleanly: GREEN
    out = box.h("verify", t=80)
    assert lines(out)[0] == "VERIFY: GREEN", (layout, out)
    assert "not checked" not in out


def test_import_not_checked_is_amber(tmp_path):
    """R140 edge: a changed library file with no importable module name is 'IMPORT: not checked for ...' and a verdict
    that would be GREEN is AMBER - import of <file> not checked; the score and evidence are unchanged."""
    files = {"my-lib/geo.py": BUGGY + KEEP}
    box = Box(tmp_path, files)
    claim = ("# CLAIM 1: area of a 2x3 rectangle is 6\nns = {}\nexec(open('my-lib/geo.py').read(), ns)\n"
             "assert ns['area'](2, 3) == 6\n")
    assert repro(box, claim).startswith("REPRO: fails on original")
    box.h("status", t=60)
    box.write("my-lib/geo.py", FIXED + KEEP)
    out = box.h("verify", t=70)
    assert lines(out)[0] == "VERIFY: AMBER - import of my-lib/geo.py not checked", out
    assert "IMPORT: not checked for my-lib/geo.py (no importable module name)" in out, out
    ck = box.state()["ckpts"][-1]
    assert ck["score"][:5] == [1, 1, 1, 1, 1] and ck["incomplete"] is False


def test_import_check_scripts_and_flat_names(tmp_path):
    """R140 edges: flat and src package names are v10.1's; scripts (docs/, scripts/, setup.py) are not import-checked
    and never make a verdict AMBER."""
    files = dict(GEO)
    files.update({"src/other/__init__.py": "", "src/other/mod.py": "X = 1\n", "scripts/release.py": "import sys\n",
                  "docs/conf.py": "project = 'x'\n"})
    box = Box(tmp_path, files)
    got = box.py("import _swe_gate as G\nprint([G.module_name(p) for p in ('pkg/geo.py', 'pkg/__init__.py', "
                 "'src/other/mod.py', 'scripts/release.py', 'docs/conf.py', 'setup.py')])\n"
                 "print([G.script_like(p) for p in ('scripts/release.py', 'docs/conf.py', 'setup.py', 'pkg/geo.py', "
                 "'pkg/__main__.py', 'repro.py', 'app.py')])\n").splitlines()
    assert got == ["['pkg.geo', 'pkg', 'other.mod', None, None, None]",
                   "[True, True, True, False, True, True, False]"], got
    assert repro(box, REPRO.format(mod="pkg.geo")).startswith("REPRO: fails on original")
    box.h("status", t=60)
    box.write("pkg/geo.py", FIXED + KEEP)
    box.write("scripts/release.py", "import sys\nraise SystemExit(sys.argv)\n")   # a script that exits at import
    box.write("docs/conf.py", "project = 'y'\n")
    out = box.h("verify", t=70)
    assert lines(out)[0] == "VERIFY: GREEN", out


# ------------------------------------------------------------------------------------------------ R141 T6-lite
MB = 1 << 20


def _skip_flow(box, **env):
    repro(box, REPRO.format(mod="pkg.geo"))                            # the original claims, cached on the empty tree
    box.h("status", t=60)
    box.write("pkg/geo.py", FIXED + KEEP)
    return box.h("verify", t=70, **env)


def test_base_tree_size_guard(tmp_path):
    """R141 base: a tracked tree over BASE_MAX_MB makes no base worktree; the original side is UNKNOWN with the reason,
    and the original claims cached from the locator's run still count (the claim is FIXED)."""
    box = Box(tmp_path, GEO)
    out = _skip_flow(box, SWE_BASE_TREE_BYTES_FOR_TESTS=301 * MB, SWE_FREE_BYTES_FOR_TESTS=100000 * MB)
    assert lines(out)[0] == "VERIFY: AMBER - tests unknown (original side: base copy skipped: tracked tree 301 MB, " \
                            "free 100000 MB)", out
    assert "claim 1" in out and "FIXED" in out, out
    st = box.state()["base"]
    assert st["ok"] is False and st["why"] == "base copy skipped: tracked tree 301 MB, free 100000 MB"
    assert not (box.swe / "base").exists()


def test_base_tree_at_the_limit_and_free_space(tmp_path):
    """R141 edges: exactly BASE_MAX_MB is allowed (the worktree is v10.1's: every tracked file); free space under 3x
    the tree skips it."""
    box = Box(tmp_path / "at", GEO)
    out = _skip_flow(box, SWE_BASE_TREE_BYTES_FOR_TESTS=300 * MB, SWE_FREE_BYTES_FOR_TESTS=900 * MB)
    assert lines(out)[0] == "VERIFY: GREEN", out
    base = box.swe / "base"
    assert box.state()["base"]["ok"] is True and "why" not in box.state()["base"]
    tracked = box.git("ls-files").split()
    assert tracked and all((base / p).read_bytes() == git(box.ws, "show", "_swegemma_baseline:" + p, text=False)
                           for p in tracked)
    box = Box(tmp_path / "free", GEO)
    out = _skip_flow(box, SWE_BASE_TREE_BYTES_FOR_TESTS=300 * MB, SWE_FREE_BYTES_FOR_TESTS=899 * MB)
    assert "base copy skipped: tracked tree 300 MB, free 899 MB" in out, out


def test_base_size_guard_measures_the_tracked_tree(tmp_path):
    """R141 unit: without the test overrides the guard sums the baseline's blob sizes (git ls-tree -l)."""
    files = dict(GEO)
    files["data/blob.bin"] = "x" * 50000
    box = Box(tmp_path, files)
    got = box.py("import _swe_gate as G\nimport subprocess\n"
                 "print(G.base_size_guard(C.ws(), C.baseline()))\n"
                 "C.BASE_MAX_MB = 0\nprint(G.base_size_guard(C.ws(), C.baseline()))\n").splitlines()
    assert got[0] == "None" and re.match(r"base copy skipped: tracked tree 0 MB, free \d+ MB", got[1]), got
