"""v10.1 regression tests: one or more per root cause of race 2 round 1 (docs/v10/v10_1_diag_1.md to _4.md).

Owner: v10.1. Every helper runs from a temp copy of the bundle scripts (no __pycache__ in submissions/), against throwaway
git repos tagged _swegemma_baseline, as subprocesses.

- R89b/R89c, helper naming (diag 1, 2, 4): a helper file name appears only as its full command, in the bundle text and in
  everything a helper prints (static AST scan plus a runtime pass over every output state); numbered steps start with a
  verb. The lint has controls built from the exact race-2 triggers.
- Footers (diag 2 P4): an empty tree is never told to end its stage; LOCATOR gives way to EDIT NOW once the locator
  stage is over.
- grep.py trailing paths (diag 2 P3), view.py L-ranges (diag 1 N6), status VIEWED (diag 4 5.4).
- EDITED checkpoints (diag 2 P5), finalize EMPTY text and EDIT TARGET (diag 2 P6), early-EOF message (diag 2 P7).
- The submit guard (diag 3): protected tracked files and untracked scratch never reach submit_patch or the fallback diff,
  while the helpers keep their own view.
- replay_l4's v10.1 diagnostic KPIs on synthetic traces and, when present, on the race-2 run itself.
"""
import ast
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from v10_support.repo import (no_orphans, make_repo, copy_helpers, helper_env, run_helper, run_py, git,  # noqa: F401,E402
                              cli_scripts, SCRIPTS_SRC, ROOT, TAG)
from test_v10_bundle import BUNDLE, LIB_SCRIPTS, CLI_SCRIPTS, prompts  # noqa: E402
from v10_support.compat import V102, later_stage  # noqa: E402  (G4_BUNDLE may be v10.2)

pytestmark = pytest.mark.skipif(not (SCRIPTS_SRC / "_swe_common.py").exists(), reason="helpers not built")

VBIN = str(pathlib.Path(sys.executable).parent)
RUNS2 = ROOT / "eval" / "race2" / "eval" / "runs"

# ---------------------------------------------------------------------------------------------------------------------
# R89b / R89c: the helper-naming lint (diag 1 section 8). HELPERS is derived from the scripts directory.
# ---------------------------------------------------------------------------------------------------------------------
HELPERS = cli_scripts()
_NAMES = "|".join(map(re.escape, HELPERS))
_PH = r"(?:/tmp/swe|%(?:\([a-z_]+\))?s|\{[^{}]*\})"          # /tmp/swe, or a format placeholder standing for it
ALLOWED = re.compile(r"python3 %s/(?:%s|NAME)\.py(?!\w)" % (_PH, _NAMES)
                     + r'|run_skill_script\(file_path="(?:%s|NAME)\.py", skill_name="swe-tools"[,)]' % _NAMES)
BARE = re.compile(r"(?<![\w.\-/])(?:%s)\.py(?!\w)|/tmp/swe/(?:%s)\.py(?!\w)" % (_NAMES, _NAMES))
SWE_PATH = re.compile(r"/tmp/swe/(\w+)\.py")
STEP_CMD = re.compile(r"^\s*(?:\d+\.|-)\s*python3\s", re.M)


def helper_name_violations(text):
    """Every helper name used other than as `python3 /tmp/swe/NAME.py` or the exact run_skill_script call, plus any
    /tmp/swe/X.py path whose X is no helper (an invented one)."""
    rest = ALLOWED.sub(lambda m: " " * len(m.group(0)), text)
    out = [m.group(0) for m in BARE.finditer(rest)]
    out += [m.group(0) for m in SWE_PATH.finditer(text) if m.group(1) not in HELPERS and m.group(1) != "NAME"]
    return out


def bundle_texts():
    """Prompts, SKILL.md and every YAML file of the bundle."""
    t = {"prompts/%s.md" % s: v for s, v in prompts().items()}
    t["SKILL.md"] = (BUNDLE / "skills" / "swe-tools" / "SKILL.md").read_text(encoding="utf-8")
    for p in sorted(BUNDLE.rglob("*.yaml")):
        t[p.relative_to(BUNDLE).as_posix()] = p.read_text(encoding="utf-8")
    return t


def output_strings(path):
    """Every string a helper can print, from its AST: string constants other than docstrings, and each f-string
    rebuilt with {} for its formatted parts (as one text, so a name split across parts is still seen)."""
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    docs, inner = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            f = node.body[0]
            if isinstance(f, ast.Expr) and isinstance(f.value, ast.Constant) and isinstance(f.value.value, str):
                docs.add(id(f.value))
        if isinstance(node, ast.JoinedStr):
            inner.update(id(v) for v in node.values)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            out.append("".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs | inner:
            out.append(node.value)
    return out


def test_helper_names_only_as_commands():
    """R89b/R89c (bundle text): prompts, SKILL.md and the YAML name a helper only as its full command; no numbered
    step of a prompt starts with python3 (race 2: '1. python3 /tmp/swe/status.py' opened 9 of 69 verifier stages as
    an unparsed call; '2. view.py the best candidates' became the parsed call that crashed fastapi_13537)."""
    for name, text in bundle_texts().items():
        assert helper_name_violations(text) == [], (name, helper_name_violations(text))
        if name.startswith("prompts/"):
            assert not STEP_CMD.findall(text), (name, STEP_CMD.findall(text))
    for s in ("locator", "fixer", "verifier", "submitter"):   # the HELPERS block: once per working stage
        assert prompts()[s].count("Run every python3 /tmp/swe command with run_command; helpers are never tool "
                                  "names.") == 1, s


@pytest.mark.parametrize("script", LIB_SCRIPTS + CLI_SCRIPTS)
def test_helper_output_names_only_as_commands(script):
    """R89b (helper strings, AST): no string a helper can print uses a bare helper name (race 2: a bare name in 531 of
    1,859 helper outputs, in 72 of 74 tasks; the CONTEXT hint alone 339 times)."""
    for text in output_strings(SCRIPTS_SRC / ("%s.py" % script)):
        assert helper_name_violations(text) == [], (script, text[:160])


def _common(tmp_path):
    import importlib.util
    d = copy_helpers(tmp_path)
    spec = importlib.util.spec_from_file_location("swe_common_v101", str(d / "_swe_common.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, d


def test_helper_hint_constants_clean(tmp_path):
    """R89b: the footers every helper prints, the verify/gate READY line and finalize's EMPTY line, as rendered."""
    from test_v10_bundle import module_constants
    C, d = _common(tmp_path)
    empty = module_constants(d / "finalize.py")["EMPTY_LINE"]
    texts = [C.TIME_HINT, C.FINISH_HINT, C.EDIT_NOW_HINT % 160, C.EDIT_NOW_LATE, C.CONTEXT_HINT, C.LOCATOR_HINT,
             C.FINAL_HINT % 5, C.HYGIENE_WHY, *C.REPEAT_NOTES.values(), empty % (100, 200)]
    for text in texts:
        assert helper_name_violations(text) == [], text
    for text in (C.TIME_HINT, C.CONTEXT_HINT, C.EDIT_NOW_LATE, empty):
        assert "python3 /tmp/swe/finalize.py" in text, text


def test_helper_name_lint_controls():
    """R89b control: the exact race-2 triggers are caught and correct texts pass."""
    bad = ["2. view.py the best candidates", "each as python3 /tmp/swe/NAME.py: view.py FILE START END",
           "Edit only with edit.py through run_command", "Verifier: run finalize.py.", "cat /tmp/swe/view.py",
           'run_skill_script(file_path="view.py")', "then edit.py %s --lines %d-%d.", "(status.py)",
           "python3 /tmp/swe/verify_tabs.py", "the first line verify.py printed", "python3 /tmp/swe/run_command.py x",
           "VIEW: read the file with view.py FILE instead"]
    for text in bad:
        assert helper_name_violations(text), text
    good = ["python3 /tmp/swe/view.py FILE START END", 'run_skill_script(file_path="install.py", skill_name="swe-tools")',
            'Next: python3 %s/locate.py "key words"', "python3 {}/view.py", "NEXT: python3 /tmp/swe/verify.py",
            "fastapi/routing/run.py", "preview.py and view.pyc", "Run python3 /tmp/swe/edit.py.", "the verify helper",
            'run_skill_script(file_path="NAME.py", skill_name="swe-tools")', "python3 /tmp/swe/NAME.py"]
    for text in good:
        assert not helper_name_violations(text), text
    assert STEP_CMD.findall("1. python3 /tmp/swe/status.py (x)\n3. Run python3 /tmp/swe/verify.py") == ["1. python3 "]
    assert STEP_CMD.findall("- python3 /tmp/swe/finalize.py") and not STEP_CMD.findall("x python3 y")


# ---------------------------------------------------------------------------------------------------------------------
# A small task used by the runtime tests
# ---------------------------------------------------------------------------------------------------------------------
FILES = {
    "pkg/__init__.py": "",
    "pkg/mod.py": "def double(x):\n    return x + 1\n\n\ndef other(y):\n    return y + 1\n",
    "pkg/routing.py": "def on_startup():\n    return 1\n\n\ndef add(app):\n    app.on_startup = on_startup\n",
    "tests/__init__.py": "",
    "tests/test_mod.py": "from pkg.mod import other\n\n\ndef test_other():\n    assert other(1) == 2\n",
    "pyproject.toml": "[project]\nname = 'pkg'\n",
    "setup.cfg": "[metadata]\nname = pkg\n",
}
REPRO = "from pkg.mod import double\n# CLAIM 1: doubles\nassert double(3) == 6, double(3)\n"


def task(tmp_path, files=None, name="ws"):
    ws = make_repo(tmp_path, FILES if files is None else files, name=name)
    swe = tmp_path / ("sbx_" + name) / "swe"
    scripts = copy_helpers(tmp_path)
    return ws, swe, scripts


def env_at(ws, swe, t=100):
    e = helper_env(ws, swe, fake_t=t)
    e["PATH"] = VBIN + os.pathsep + e.get("PATH", "")
    return e


def helper(scripts, name, args=(), *, ws, swe, t=100, stdin=None, timeout=90):
    r = run_helper(scripts, name, list(args), ws=ws, env=env_at(ws, swe, t), stdin=stdin, timeout=timeout)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "HELPER ERROR" not in r.stdout and "Traceback (most recent" not in r.stdout, r.stdout
    return r.stdout


def submit_patch(ws):
    """The harness's submit_patch and timeout fallback, verbatim (execution.py:81-86, agent_runner.py:760-776)."""
    sh = lambda c: subprocess.run(["bash", "-c", c], cwd=str(ws), capture_output=True, text=True,
                                  env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1"))
    sh("cd %s && git add -N ." % ws)
    return sh("cd %s && (git diff --binary _swegemma_baseline 2>/dev/null || git diff --binary HEAD)" % ws).stdout


def patch_paths(diff):
    return sorted(re.findall(r"^diff --git a/(.*?) b/", diff, re.M))


def state(swe):
    return json.loads((swe / "state.json").read_text())


# ---------------------------------------------------------------------------------------------------------------------
# R89b runtime pass: every helper in every output state, stdout linted
# ---------------------------------------------------------------------------------------------------------------------
def test_helper_output_runtime_clean(tmp_path):
    """R89b (runtime): the text every helper actually prints, over its output states (install banner, locate, grep
    hits / no match / invalid regex / not-a-path note, view range / missing / past EOF, edit OK / NO MATCH / ALREADY
    TRIED / REFUSED / early EOF, run and its repeat note, verify NONE SAVED / NO SOURCE CHANGE / RED / GREEN or AMBER,
    finalize EMPTY with EDIT TARGET / SYNTAX / READY, status with protected edits and CHANGED AFTER FINALIZE, and the
    footers LOCATOR, EDIT NOW (early and late), FINISH, TIME and FINAL). No fixture file is named after a helper."""
    ws, swe, sc = task(tmp_path)
    outs = []

    def h(name, args=(), t=100, stdin=None):
        o = helper(sc, name, args, ws=ws, swe=swe, t=t, stdin=stdin)
        outs.append((name, t, o))
        return o
    assert "ready in /tmp/swe" in h("install", t=2)
    h("locate", ["double other"], t=10)
    h("grep", ["on_startup"], t=20)
    assert "NOTE: no match" in h("grep", ["zz_never_zz"], t=20)
    assert "invalid regex" in h("grep", ["on_startup("], t=20)
    assert "is not a path in the workspace" in h("grep", ["on_startup", "pkg/nope.py"], t=20)
    h("view", ["pkg/mod.py", "1", "3"], t=30)
    assert "no such file" in h("view", ["pkg/nope.py"], t=30)
    h("view", ["pkg/mod.py", "900", "950"], t=30)
    assert "LOCATOR: 75s used." in h("view", ["pkg/mod.py", "1", "2"], t=80)
    assert h("verify", ["--repro-only"], t=40).startswith("REPRO: none saved")
    assert "fails on original" in h("verify", ["--repro-only"], t=40, stdin=REPRO)
    assert "VERIFY: NO SOURCE CHANGE" in h("verify", t=160)
    miss = "<<<<<<< SEARCH\n    return x + 99\n=======\n    return x * 2\n>>>>>>> REPLACE\n"
    assert h("edit", ["pkg/mod.py"], t=165, stdin=miss).startswith("NO MATCH")
    assert h("edit", ["pkg/mod.py"], t=166, stdin=miss).startswith("ALREADY TRIED")
    assert h("edit", ["tests/test_mod.py", "--lines", "1-1"], t=167, stdin="x = 1\n").startswith("REFUSED")
    assert h("edit", ["pkg/mod.py"], t=168, stdin="<<<<<<< SEARCH\n    return x + 1\n").startswith("ERROR: the edit ended early")
    fin = h("finalize", t=170)
    assert fin.startswith("NOT READY: EMPTY at t=170s") and "EDIT TARGET" in fin, fin
    (ws / "data.bin").write_bytes(b"\0\1\2")
    assert h("edit", ["data.bin", "--lines", "1-1"], t=171, stdin="x\n").startswith("REFUSED")
    (ws / "data.bin").unlink()
    still = "<<<<<<< SEARCH\n    return x + 1\n=======\n    return x + 2\n>>>>>>> REPLACE\n"
    assert h("edit", ["pkg/mod.py"], t=172, stdin=still).startswith("OK")
    assert "VERIFY: RED" in h("verify", t=175)
    good = "<<<<<<< SEARCH\n    return x + 2\n=======\n    return x * 2\n>>>>>>> REPLACE\n"
    assert h("edit", ["pkg/mod.py"], t=176, stdin=good).startswith("OK")
    assert re.search(r"VERIFY: (GREEN|AMBER)", h("verify", t=180))
    for _ in range(3):
        h("run", ["echo same"], t=181)
    if V102:        # v10.2 (SPEC_v10_2 5.5): the third identical run on the same tree is refused (SAME RUN)
        assert outs[-1][2].startswith("SAME RUN: this command already ran twice on this tree")
    else:
        assert "NOTE: same command, same output 3 times" in outs[-1][2]
    assert "FINISH: t>=210s" in h("view", ["pkg/mod.py", "1", "2"], t=215)
    (ws / "tests/test_mod.py").write_text("def test_other():\n    pass\n")
    assert "PROTECTED" in h("status", t=220)
    assert h("finalize", t=230).startswith("READY:")
    assert "FINAL:" in h("status", t=231)
    (ws / "pkg/mod.py").write_text((ws / "pkg/mod.py").read_text() + "\n\nZ = 1\n")
    assert "CHANGED AFTER FINALIZE" in h("status", t=255)
    assert "TIME: t>=250s" in h("view", ["pkg/mod.py", "1", "2"], t=256)
    (ws / "pkg/mod.py").write_text((ws / "pkg/mod.py").read_text() + "def broken(:\n    pass\n")
    assert "SYNTAX ERROR" in h("finalize", t=286)                       # past T_NO_RESTORE: no better tree comes back
    git(ws, "checkout", TAG, "--", "pkg/mod.py")
    late = h("view", ["pkg/mod.py", "1", "2"], t=286)                        # empty tree, too late to restore
    assert "EDIT NOW: no source file changed at t=286s" in late and "Then run python3 /tmp/swe/finalize.py once." in late
    for name, t, o in outs:
        assert helper_name_violations(o) == [], (name, t, helper_name_violations(o), o)
        assert "call:" not in o
    assert not any(p.stem in HELPERS for p in ws.rglob("*.py")), "a fixture file named after a helper"


# ---------------------------------------------------------------------------------------------------------------------
# Footers (diag 2 P4)
# ---------------------------------------------------------------------------------------------------------------------
def test_empty_tree_never_told_to_end_its_stage(tmp_path):
    """P4: over t = 0..300 (step 5) with no source change, no hint says 'keep the edit you have' or 'End your stage'
    (race 2: fastapi_14851 step 38 read 'TIME: ... End your stage now' on an empty tree and timed out with no edit).
    From T_EDIT_NOW it is EDIT NOW, even with a full context meter, and from T_TIME it adds the finalize command. A tree
    with a source change still gets FINISH and TIME; FINAL still wins over everything."""
    ws, swe, sc = task(tmp_path)
    code = ("import json\nout = []\nfor t in range(0, 305, 5):\n"
            "    for ctx in (None, 99999):\n        out.append([t, ctx, C.hint(t, False, None, ctx)])\n"
            "out.append([255, None, C.hint(255, True, None, None)])\nout.append([215, None, C.hint(215, True, None, None)])\n"
            "print(json.dumps(out))\n")
    r = run_py(sc, code, env=env_at(ws, swe), cwd=ws)
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout.strip().splitlines()[-1])
    for t, ctx, h in rows[:-2]:
        assert "keep the edit you have" not in h and "End your stage" not in h, (t, ctx, h)
        if t >= 150:
            assert h.startswith("EDIT NOW: no source file changed at t=%ds;" % t), (t, ctx, h)
            assert ("python3 /tmp/swe/finalize.py" in h) == (t >= 250), (t, h)
    assert rows[-2][2].startswith("TIME: t>=250s") and rows[-1][2].startswith("FINISH: t>=210s")


# ---------------------------------------------------------------------------------------------------------------------
# grep.py trailing paths (diag 2 P3), view.py L-ranges (diag 1 N6), status VIEWED (diag 4 5.4)
# ---------------------------------------------------------------------------------------------------------------------
def _hits(out):
    m = re.match(r"GREP: (\d+) hits in (\d+) files", out)
    assert m, out
    return int(m.group(1)), int(m.group(2))


def test_grep_positional_paths(tmp_path):
    """P3 (race 2: 74 of 206 grep.py calls wrote a trailing path, which the helper folded into the regex; 65 found
    nothing or 'invalid regex'). The first word is the regex; a later existing path is searched; a later word that
    looks like a path but does not exist gets a NOTE and everything is searched; other words still join the regex."""
    files = dict(FILES)
    files["pkg/other.py"] = "def on_startup_hook():\n    return 2\n"
    files["tests/test_routing.py"] = "def test_on_startup():\n    assert True\n"
    files["README.md"] = "on_startup\n"
    ws, swe, sc = task(tmp_path, files)
    g = lambda *a: helper(sc, "grep", list(a), ws=ws, swe=swe, t=20)
    assert _hits(g("on_startup", "pkg/routing.py")) == (2, 1)                     # the race-2 shape, now right
    assert _hits(g("on_startup", "."))[0] >= 3
    assert _hits(g("on_startup", "pkg")) == (3, 2)
    assert _hits(g("on_startup", "pkg/routing.py", "pkg/other.py")) == (3, 2)
    assert _hits(g("on_startup", "pkg/routing.py", "--tests")) == (2, 1)
    out = g("on_startup", "pkg/nope.py")
    assert "NOTE: pkg/nope.py is not a path in the workspace; searched everywhere." in out and _hits(out)[0] >= 3
    assert _hits(g("def on_startup")) == (2, 2)                                  # one argv word with a space
    assert _hits(g("def", "on_startup")) == (2, 2)                               # an unquoted pattern still joins
    assert "GREP:" in g("setup.py")                                              # a lone word is always the regex
    assert _hits(g("on_startup", "tests/test_routing.py")) == (1, 1)             # a named test file is searched
    outside = tmp_path / "outside.py"
    outside.write_text("def on_startup():\n    pass\n")
    assert _hits(g("on_startup", str(outside))) == (1, 1)
    assert "invalid regex" in g("on_startup(", "pkg/routing.py")                 # the regex itself is still checked


def test_view_accepts_l_ranges(tmp_path):
    """diag 1 N6 (fastapi_14851 step 10, fastapi_5624 step 6): the L1191-1433 spans locate.py and grep.py print are
    accepted as ranges, also as FILE:L2-3 and as two words; a NAME still works."""
    ws, swe, sc = task(tmp_path)
    later_stage(swe)                                   # v10.2: t=100 is past the locator's close
    for args in (["pkg/mod.py", "L2-3"], ["pkg/mod.py:L2-3"], ["pkg/mod.py", "L2", "L3"], ["pkg/mod.py", "l2..3"]):
        out = helper(sc, "view", args, ws=ws, swe=swe)
        assert out.startswith("pkg/mod.py lines 2-3 of"), (args, out)
    assert "def double" in helper(sc, "view", ["pkg/mod.py", "double"], ws=ws, swe=swe)


def test_status_lists_viewed_ranges(tmp_path):
    """diag 4 5.4 (rich_4079: three compactions, each losing the locator's plan): status prints the source ranges
    viewed last, newest first, at most 4, test files left out."""
    ws, swe, sc = task(tmp_path)
    later_stage(swe)                                   # v10.2: the v10.1 form is the status of a later stage
    for i, (a, b) in enumerate(((1, 2), (4, 6), (1, 3), (2, 5), (1, 6))):
        helper(sc, "view", ["pkg/mod.py", str(a), str(b)], ws=ws, swe=swe, t=10 + i)
    helper(sc, "view", ["tests/test_mod.py", "1", "2"], ws=ws, swe=swe, t=40)
    out = helper(sc, "status", ws=ws, swe=swe, t=50)
    line = next(x for x in out.splitlines() if x.startswith("VIEWED"))
    assert line == "VIEWED (newest first): pkg/mod.py 1-6, pkg/mod.py 2-5, pkg/mod.py 1-3, pkg/mod.py 4-6", out


# ---------------------------------------------------------------------------------------------------------------------
# EDITED checkpoints (diag 2 P5), finalize EMPTY + EDIT TARGET (P6), early EOF (P7)
# ---------------------------------------------------------------------------------------------------------------------
FIX = "<<<<<<< SEARCH\n    return x + 1\n=======\n    return x * 2\n>>>>>>> REPLACE\n"


def test_edit_checkpoints_every_landed_edit(tmp_path):
    """P5 (fastapi_15280: two OK edits undone by the model, then finalize said EMPTY with checkpoints: 0 and an empty
    patch was submitted). Every landed edit is an unscored EDITED checkpoint; finalize's EMPTY branch restores the latest
    one; restores are still refused at t >= 285."""
    ws, swe, sc = task(tmp_path)
    assert helper(sc, "edit", ["pkg/mod.py"], ws=ws, swe=swe, t=170, stdin=FIX).startswith("OK")
    ck = state(swe)["ckpts"]
    assert [(c["verdict"], c["score"]) for c in ck] == [("EDITED", None)], ck
    fixed = submit_patch(ws)
    git(ws, "checkout", TAG, "--", "pkg/mod.py")                   # the model undid it (a raw write, edit_file, ...)
    out = helper(sc, "finalize", ws=ws, swe=swe, t=200)
    assert re.search(r"^RESTORED: checkpoint #1 \(EDITED, t=170s\) \(the tree had no source change\)$", out, re.M), out
    assert out.startswith("READY: 1 files changed") and submit_patch(ws) == fixed, out
    # too late to restore: EMPTY stays EMPTY, with the refusal said
    ws2, swe2, sc2 = task(tmp_path, name="late")
    helper(sc2, "edit", ["pkg/mod.py"], ws=ws2, swe=swe2, t=170, stdin=FIX)
    git(ws2, "checkout", TAG, "--", "pkg/mod.py")
    out = helper(sc2, "finalize", ws=ws2, swe=swe2, t=290)
    assert out.startswith("NOT READY: EMPTY at t=290s (10s left)") and "RESTORE REFUSED" in out, out


def test_status_checkpoints_a_native_edit(tmp_path):
    """P5: a tree changed with the harness's own tools (no edit.py call) is saved by status.py as EDITED too."""
    ws, swe, sc = task(tmp_path)
    (ws / "pkg/mod.py").write_text(FILES["pkg/mod.py"].replace("x + 1", "x * 2"))
    helper(sc, "status", ws=ws, swe=swe, t=120)
    assert [c["verdict"] for c in state(swe)["ckpts"]] == ["EDITED"]
    helper(sc, "status", ws=ws, swe=swe, t=121)                      # the same tree is not stored twice
    assert len(state(swe)["ckpts"]) == 1


def test_scored_checkpoint_beats_edited(tmp_path):
    """P5: rank() puts an unscored EDITED entry below every scored one, so best() and best_against() are unchanged,
    and among EDITED entries the latest wins."""
    ws, swe, sc = task(tmp_path)
    code = ("import json, _swe_ckpt as K\n"
            "a = K.save(b'diff --git a/x b/x\\n+1\\n', [1, 1, 1, 1, 0, 0], 'k', 'AMBER', False)\n"
            "b = K.save(b'diff --git a/x b/x\\n+2\\n', None, None, 'EDITED', False)\n"
            "best = K.best(None)\n"
            "cur = dict(K.entry_for_sha(K._sha(b'diff --git a/x b/x\\n+2\\n')))\n"
            "print(json.dumps([a, b, best['id'], K.rank(cur) < K.rank(best)]))\n")
    r = run_py(sc, code, env=env_at(ws, swe, 100), cwd=ws)
    assert r.returncode == 0, r.stderr
    a, b, best, lower = json.loads(r.stdout.strip().splitlines()[-1])
    assert best == a and lower, r.stdout


def test_finalize_empty_text_and_edit_target(tmp_path):
    """P6 (fastapi_14873: the submitter invented a SEARCH block and submitted an empty patch at 72 s of 176). EMPTY says
    the time left and that an empty patch always fails, and shows the code last viewed (or the region of an undone
    edit) as numbered lines with the --lines recipe; nothing viewed means no EDIT TARGET; test files are never offered."""
    ws, swe, sc = task(tmp_path)
    later_stage(swe)                                   # v10.2: t=160 is past the locator's close
    out = helper(sc, "finalize", ws=ws, swe=swe, t=160)
    assert out.startswith("NOT READY: EMPTY at t=160s (140s left) - no source change. Do not submit an empty patch: "
                          "it always fails.") and "EDIT TARGET" not in out, out
    helper(sc, "view", ["tests/test_mod.py", "1", "4"], ws=ws, swe=swe, t=161)
    assert "EDIT TARGET" not in helper(sc, "finalize", ws=ws, swe=swe, t=162)
    helper(sc, "view", ["pkg/mod.py", "1", "5"], ws=ws, swe=swe, t=163)
    out = helper(sc, "finalize", ws=ws, swe=swe, t=164)
    lines = out.splitlines()
    i = lines.index("EDIT TARGET (the code viewed or edited last): pkg/mod.py lines 1-5")
    assert lines[i + 1] == "    1| def double(x):" and lines[i + 5] == "    5| def other(y):", out
    assert lines[i + 6] == "use: python3 /tmp/swe/edit.py pkg/mod.py --lines 1-5 <<'EOF' ... EOF", out
    assert len(out.rstrip("\n")) <= 1400
    # a landed edit that was undone is the better target than an older view
    helper(sc, "edit", ["pkg/mod.py", "--lines", "5-6"], ws=ws, swe=swe, t=170, stdin="def other(y):\n    return y + 3\n")
    git(ws, "checkout", TAG, "--", "pkg/mod.py")
    shutil.rmtree(swe / "ckpt")                                     # no checkpoint to restore: EMPTY stays
    st = state(swe)
    st["ckpts"] = []
    (swe / "state.json").write_text(json.dumps(st))
    out = helper(sc, "finalize", ws=ws, swe=swe, t=180)
    assert "EDIT TARGET (the code viewed or edited last): pkg/mod.py lines 3-6" in out, out


def test_edit_early_eof_message(tmp_path):
    """P7 (fastapi_14873 steps 36-37): a stray EOF line inside the heredoc ended it early, so only the SEARCH half
    arrived and the rest ran as shell commands. edit.py says so, changes nothing and does not count it as a failed
    edit; a block that has REPLACE but no divider still gets the old message. EDITFORM states the EOF rule."""
    ws, swe, sc = task(tmp_path)
    before = (ws / "pkg/mod.py").read_bytes()
    out = helper(sc, "edit", ["pkg/mod.py"], ws=ws, swe=swe, stdin="<<<<<<< SEARCH\n    return x + 1\n")
    assert out.startswith("ERROR: the edit ended early: no ======= line and no >>>>>>> REPLACE line arrived, so nothing "
                          "changed. A line EOF inside the block ends the heredoc and the rest ran as shell commands. "
                          "Put EOF once, as the last line, and send the whole edit again."), out
    assert (ws / "pkg/mod.py").read_bytes() == before
    j = [json.loads(x) for x in (swe / "journal.jsonl").read_text().splitlines()]
    assert j[-1]["why"] == "EARLY EOF" and j[-1]["counts"] is False
    out = helper(sc, "edit", ["pkg/mod.py"], ws=ws, swe=swe,
                 stdin="<<<<<<< SEARCH\n    return x + 1\n    return x * 2\n>>>>>>> REPLACE\n")
    assert out.startswith("ERROR: block 1 has no ======= line"), out
    for s in ("fixer", "verifier", "submitter"):
        assert "EOF appears once, as the last line." in prompts()[s], s


# ---------------------------------------------------------------------------------------------------------------------
# The submit guard (diag 3)
# ---------------------------------------------------------------------------------------------------------------------
def test_guard_post_finalize_native_edit(tmp_path):
    """fastapi_14077: after finalize printed READY, the verifier re-edited pyproject.toml with the harness's edit_file
    and submitted it. Now protected tracked files are invisible to submit_patch from install on: overwritten the way
    write_file writes (shutil.copy2 of a temp file), appended, or deleted, only the source edit is submitted."""
    ws, swe, sc = task(tmp_path)
    helper(sc, "install", ws=ws, swe=swe, t=2)
    helper(sc, "edit", ["pkg/mod.py"], ws=ws, swe=swe, t=90, stdin=FIX)
    assert helper(sc, "finalize", ws=ws, swe=swe, t=98).startswith("READY: 1 files changed")
    with tempfile.TemporaryDirectory() as td:
        for rel, text in (("pyproject.toml", "[project]\nname = 'pkg'\nversion = '2'\n"),
                          ("tests/test_mod.py", "def test_other():\n    assert False\n")):
            p = pathlib.Path(td) / "f"
            p.write_text(text)
            shutil.copy2(p, ws / rel)
    (ws / "setup.cfg").unlink()
    with open(ws / "conftest.py", "a") as f:
        f.write("import sys\n")
    assert patch_paths(submit_patch(ws)) == ["pkg/mod.py"]


def test_guard_scratch_without_finalize(tmp_path):
    """fastapi_14258: the fixer wrote a root repro.py, the session timed out before any helper ran again, and the
    fallback diff shipped it. Untracked scratch, vendored trees and new test/config files never enter that diff now,
    with no finalize at all (every sample of the finalize hygiene matrix, in any letter case)."""
    ws, swe, sc = task(tmp_path)
    (ws / "repro.py").write_text("x = 1\n")                        # control: without the guard it ships (race 2)
    assert patch_paths(submit_patch(ws)) == ["repro.py"]
    git(ws, "rm", "-q", "--cached", "--ignore-unmatch", "repro.py")  # undo the intent-to-add of that submit
    helper(sc, "install", ws=ws, swe=swe, t=2)
    junk = ["repro.py", "Repro.txt", "REPRODUCE_issue.py", "scratch_check.py", "debug_out.txt", "tmp1.py", "Temp.py",
            "try_it.py", "demo.py", "run.log", "pkg/a.orig", "pkg/b.rej", "c.bak", ".d.swp", ".coverage",
            "site-packages/x/a.py", "lib/site-packages/y.py", "foo-1.0.dist-info/METADATA", "_pytest/z.py",
            "tests/new/test_q.py", "tests/data.json", "pkg/sub/conftest.py", "test_root.py", "root_test.py",
            "sitecustomize.py", "usercustomize.py", "x.pth", "pkg/tests/helper.py", "pkg/test/h.py", "testing/t.py",
            "tox.ini", "pkg/pytest.ini", "scratch_dir/notes.py", "debug/x.py",
            "pkg/testing/new_mod.py", "pkg/Tests/n.py", "a/TEST/b/c.py", "Testing/r.py"]   # graders' git clean deletes
    for rel in junk:
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x = 1\n")
    assert submit_patch(ws) == "", patch_paths(submit_patch(ws))


def test_guard_keeps_real_changes(tmp_path):
    """The guard's patterns never hide a real change: tracked dirs that a pattern matches (templates/, src/_pytest/,
    tmp_data/) keep shipping new files through the re-includes, a tracked root debug.py still ships its edit, and new
    modules such as pkg/tmp_utils.py or a unicode path ship."""
    files = dict(FILES)
    files.update({"templates/a.html": "a\n", "src/_pytest/x.py": "y = 1\n", "debug.py": "D = 1\n",
                  "tmp_data/d.txt": "d\n", "pkg/testing/util.py": "U = 1\n", "pkg/Tests/h.py": "H = 1\n"})
    ws, swe, sc = task(tmp_path, files)
    helper(sc, "install", ws=ws, swe=swe, t=2)
    for rel in ("templates/new.html", "src/_pytest/new.py", "tmp_data/e.txt", "pkg/tmp_utils.py", "pkg/ünï.py",
                "pkg/testing/data.txt", "pkg/testing.py", "pkg/mytesting/m.py"):
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_text("n = 1\n")
    for rel in ("debug.py", "pkg/testing/util.py", "pkg/Tests/h.py"):      # tracked: the graders keep these edits
        (ws / rel).write_text("D = 2\n")
    got = submit_patch(ws)
    for rel in ("templates/new.html", "src/_pytest/new.py", "tmp_data/e.txt", "pkg/tmp_utils.py", "debug.py",
                "pkg/testing/data.txt", "pkg/testing.py", "pkg/mytesting/m.py", "pkg/testing/util.py", "pkg/Tests/h.py"):
        assert "b/" + rel in got, (rel, patch_paths(got))
    assert "\\303\\274n\\303\\257.py" in got or "ünï.py" in got


def test_guard_helpers_view_unchanged(tmp_path):
    """The helpers still see what the guard hides: changes() lists a hidden test edit as protected, verify prints
    HYGIENE and reverts it (with the reason), the reverted file keeps its flag so a re-edit stays hidden, finalize still
    deletes root scratch, and the base tree copy of ignored files never picks up guard-matched files."""
    ws, swe, sc = task(tmp_path)
    helper(sc, "install", ws=ws, swe=swe, t=2)
    helper(sc, "edit", ["pkg/mod.py"], ws=ws, swe=swe, t=90, stdin=FIX)
    (ws / "tests/test_mod.py").write_text("def test_other():\n    assert 0\n")
    (ws / "repro.py").write_text("print(1)\n")
    r = run_py(sc, "import json\nch = C.changes()\nprint(json.dumps([ch['protected'], ch['untracked']]))\n",
               env=env_at(ws, swe), cwd=ws)
    prot, untracked = json.loads(r.stdout.strip().splitlines()[-1])
    assert prot == ["tests/test_mod.py"] and untracked == ["repro.py"], r.stdout
    out = helper(sc, "verify", ws=ws, swe=swe, t=100)
    assert "HYGIENE: reverted tests/test_mod.py (graders replace test and config files, so a patch never carries them; "\
           "do not redo this)" in out, out
    assert (ws / "tests/test_mod.py").read_text() == FILES["tests/test_mod.py"]
    assert git(ws, "ls-files", "-v", "tests/test_mod.py").startswith("h "), "the revert dropped the guard flag"
    (ws / "tests/test_mod.py").write_text("def test_other():\n    assert 0\n")
    assert patch_paths(submit_patch(ws)) == ["pkg/mod.py"]
    code = ("import json, tempfile, _swe_gate as G\nd = tempfile.mkdtemp()\nG._copy_ignored(C.ws(), d)\n"
            "import os\nprint(json.dumps(sorted(os.path.relpath(os.path.join(a, f), d) for a, _, fs in os.walk(d) "
            "for f in fs)))\n")
    r = run_py(sc, code, env=env_at(ws, swe), cwd=ws)
    assert "repro.py" not in r.stdout and "test_mod" not in r.stdout, r.stdout + r.stderr
    out = helper(sc, "finalize", ws=ws, swe=swe, t=120)
    assert "CLEANED: removed repro.py" in out and out.startswith("READY:"), out
    assert not (ws / "repro.py").exists()


def test_guard_fast_path_never_hides_a_dirty_file(tmp_path):
    """Speed (v10.1): changes() skips the unguarded index copy while every guarded file keeps the size and mtime a full
    check found clean. A file found dirty stays dirty for every later call until a full check finds it clean again, an
    edit that keeps the size is still seen, and a newly armed flag invalidates the snapshot."""
    ws, swe, sc = task(tmp_path)
    helper(sc, "install", ws=ws, swe=swe, t=2)
    code = ("import json\nprint(json.dumps(C.changes()['protected']))\n")
    prot = lambda: json.loads(run_py(sc, code, env=env_at(ws, swe), cwd=ws).stdout.strip().splitlines()[-1])
    assert prot() == [] and (swe / "guard_stat.json").exists()           # full check, all clean: snapshot written
    assert prot() == []                                                  # fast path
    (ws / "tests/test_mod.py").write_text("def test_other():\n    assert 0\n")
    assert prot() == ["tests/test_mod.py"] and prot() == ["tests/test_mod.py"]   # dirty stays dirty
    before = (ws / "setup.cfg").read_text()
    (ws / "setup.cfg").write_text(before.replace("pkg", "pkq"))             # same size, new mtime
    assert prot() == ["setup.cfg", "tests/test_mod.py"]
    git(ws, "checkout", TAG, "--", "setup.cfg", "tests/test_mod.py")
    assert prot() == [] and prot() == []
    snap = json.loads((swe / "guard_stat.json").read_text())
    assert "dirty" not in snap.values() and "tests/test_mod.py" in snap
    git(ws, "update-index", "--no-assume-unchanged", "pyproject.toml")    # a flag lost, then re-armed
    run_py(sc, "C.arm_submit_guard()\n", env=env_at(ws, swe), cwd=ws)
    assert not (swe / "guard_stat.json").exists()


def test_guard_idempotent_fast_and_rearmed(tmp_path):
    """Arming twice (install, install, finalize) leaves one exclude file, one core.excludesFile value and the same flag
    count; arming a 3,000-file repository takes well under a second; a read-tree that drops the flags is repaired by
    the next finalize."""
    files = dict(FILES)
    for i in range(1000):
        files["pkg/gen/m%04d.py" % i] = "X = %d\n" % i
        files["tests/gen/test_%04d.py" % i] = "def test_%d():\n    pass\n" % i
        files["docs/p%04d.md" % i] = "p\n"
    ws, swe, sc = task(tmp_path, files)
    helper(sc, "install", ws=ws, swe=swe, t=2)
    flags = lambda: sum(1 for x in git(ws, "ls-files", "-v").splitlines() if x[:1].islower())
    n1, ex1 = flags(), (ws / ".git" / "swe_exclude").read_text()
    assert n1 >= 1000 + 5
    helper(sc, "install", ws=ws, swe=swe, t=3)
    helper(sc, "finalize", ws=ws, swe=swe, t=4)
    assert flags() == n1 and (ws / ".git" / "swe_exclude").read_text() == ex1
    got = git(ws, "config", "--get-all", "core.excludesFile").splitlines()
    assert [os.path.realpath(x) for x in got] == [os.path.realpath(ws / ".git" / "swe_exclude")], got
    git(ws, "read-tree", TAG)                          # a reset that drops the flags
    assert flags() == 0
    r = run_py(sc, "import time\nt = time.perf_counter()\nC.arm_submit_guard()\nprint(time.perf_counter() - t)\n",
               env=env_at(ws, swe), cwd=ws)
    assert float(r.stdout.strip().splitlines()[-1]) < 1.0, r.stdout      # a full arm of 3,000 files
    assert flags() == n1
    git(ws, "read-tree", TAG)
    helper(sc, "finalize", ws=ws, swe=swe, t=5)       # finalize re-arms
    assert flags() == n1


def test_guard_only_in_a_harness_workspace(tmp_path):
    """A repository without the _swegemma_baseline tag (a developer checkout) is never armed: no exclude file, no
    core.excludesFile, no flags."""
    ws = make_repo(tmp_path, FILES, baseline=False)
    git(ws, "add", "-A")
    git(ws, "commit", "-qm", "dev")
    sc = copy_helpers(tmp_path)
    swe = tmp_path / "sbx" / "swe"
    r = run_py(sc, "print(repr(C.arm_submit_guard()))\n", env=env_at(ws, swe), cwd=ws)
    assert r.stdout.strip().splitlines()[-1] == "None", r.stdout + r.stderr
    assert not (ws / ".git" / "swe_exclude").exists()
    assert git(ws, "config", "--get", "core.excludesFile", check=False) == ""


def test_finalize_enforces_patch_rules(tmp_path):
    """finalize never prints READY while the graders' view of the patch carries a test/config or scratch file: a root
    scratch file the model staged with git add and a new .py under a nested testing/ dir (the graders' git clean deletes
    it; their rule is case-insensitive and covers nested dirs) are undone. For NEW files the rules match replay_l4's
    KPI 7/8 exactly; for tracked files they are the helpers' own rule (_protected_git), because the graders' checkout of
    tracked files always aborts on a missing pathspec (harness_runtime 7.2), so a tracked pkg/testing/u.py edit ships
    (review 2026-09-29: see test_protection_one_rule_nested_testing)."""
    files = dict(FILES)
    files["pkg/testing/util.py"] = "U = 1\n"
    ws, swe, sc = task(tmp_path, files)
    helper(sc, "install", ws=ws, swe=swe, t=2)
    helper(sc, "edit", ["pkg/mod.py"], ws=ws, swe=swe, t=90, stdin=FIX)
    (ws / "repro_steps.txt").write_text("x\n")
    git(ws, "add", "-f", "repro_steps.txt")               # the guard makes a plain git add refuse it
    (ws / "pkg/testing/new_helper.py").write_text("H = 1\n")
    git(ws, "add", "-f", "pkg/testing/new_helper.py")     # staged too: status A, not only untracked
    out = helper(sc, "finalize", ws=ws, swe=swe, t=100)
    assert out.startswith("READY: 1 files changed"), out
    assert "CLEANED: the patch carried" in out and "repro_steps.txt (scratch or vendored file)" in out, out
    assert "reverted test/config edits: pkg/testing/new_helper.py" in out, out
    assert not (ws / "pkg/testing/new_helper.py").exists()
    assert patch_paths(submit_patch(ws)) == ["pkg/mod.py"]
    sys.path.insert(0, str(ROOT / "scripts"))
    import replay_l4 as R
    C, _ = _common(tmp_path / "lib")
    table = [("tests/test_x.py", False), ("pkg/testing/u.py", False), ("Tests/x.py", True), ("pkg/conftest.py", True),
             ("pyproject.toml", False), ("x.pth", True), ("repro.py", True), ("Repro.txt", True), ("pkg/repro.py", True),
             ("a.log", True), ("lib/site-packages/a.py", True), ("x.dist-info/M", True), ("pkg/mod.py", False),
             ("pkg/new.py", True), ("docs/tmp.md", True), ("debug.py", False), ("test_root.py", True),
             ("pkg/testing/u.py", True), ("pkg/Tests/h.py", True), ("pkg/Tests/h.py", False), ("TESTING/x.py", False),
             ("tests/data.json", False), ("pkg/testing/data.json", True)]
    for p, new in table:
        kpi = R.is_protected(p) or bool(R.scratch_files([(p, new)]))
        got = bool(C.patch_violations([(p, new)]))
        if new:
            assert got == kpi, (p, new)
        else:
            assert got == bool(C._protected_git(p)), (p, new)


# The graders' reset of test/config files, verbatim (swegemma/harness/verification.py:392-415, with the path list the
# agent patch produces): the checkout aborts on the first unknown pathspec, the clean still runs.
def _grader_reset(ws, paths):
    lst = " ".join(list(paths) + ["conftest.py", "pytest.ini", "sitecustomize.py", "usercustomize.py",
                                  "_swegemma_stubs.py"])
    for cmd in ("git checkout HEAD -- %s 2>/dev/null || true" % lst, "git clean -f -- %s 2>/dev/null || true" % lst):
        subprocess.run(["bash", "-c", "cd %s && %s" % (ws, cmd)], capture_output=True, text=True,
                       env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1"))


def test_protection_one_rule_nested_testing(tmp_path):
    """Review finding 2026-09-29 (major): finalize's patch rule (the graders' _is_protected_test_or_config_path: .py
    under tests/test/testing at any depth, any case) and edit.py's refusal (is_protected: root testing/, nested
    lower-case tests/ and test/) disagreed. edit.py accepted pkg/testing/util.py; finalize undid it (NOT READY: EMPTY with
    an EDIT TARGET pointing back at the same file), the next finalize restored the EDITED checkpoint and undid it again,
    and from t>=255 the late guard restored it on any helper call. Now one rule, per file kind:
    - a TRACKED file there is editable and ships (the graders' checkout aborts on a missing pathspec, so they keep the
      edit): edit OK, finalize READY with it, a second finalize and status at t=260 restore nothing, submit_patch carries
      it, and the verbatim graders' reset leaves it in place; the same for a case variant (pkg/Tests/helper.py);
    - a NEW .py there (the graders' git clean deletes it) is REFUSED by edit.py up front, both --create and an untracked
      file written natively, and a native one is reverted by the helpers and never reaches the fallback diff; a new
      non-.py file there (the graders keep it) is accepted and ships;
    - for every sample, edit.py refuses a path exactly when patch_violations would undo it."""
    files = dict(FILES)
    files.update({"pkg/testing/__init__.py": "", "pkg/testing/util.py": "def u():\n    return 1\n",
                  "pkg/Tests/helper.py": "H = 1\n"})
    ws, swe, sc = task(tmp_path, files)
    helper(sc, "install", ws=ws, swe=swe, t=2)
    out = helper(sc, "edit", ["pkg/testing/util.py", "--lines", "2-2"], ws=ws, swe=swe, t=140, stdin="    return 2\n")
    assert out.startswith("OK (lines): pkg/testing/util.py"), out
    out = helper(sc, "finalize", ws=ws, swe=swe, t=150)
    assert out.startswith("READY: 1 files changed"), out
    assert "CLEANED" not in out and "EDIT TARGET" not in out and "RESTORED" not in out, out
    assert patch_paths(submit_patch(ws)) == ["pkg/testing/util.py"]
    out = helper(sc, "finalize", ws=ws, swe=swe, t=160)
    assert out.startswith("READY: 1 files changed") and "RESTORED" not in out, out
    out = helper(sc, "status", ws=ws, swe=swe, t=260)
    assert "RESTORED" not in out, out
    assert (ws / "pkg/testing/util.py").read_text() == "def u():\n    return 2\n"
    # the case variant of the harness rule (Tests/): same behaviour
    out = helper(sc, "edit", ["pkg/Tests/helper.py", "--lines", "1-1"], ws=ws, swe=swe, t=170, stdin="H = 2\n")
    assert out.startswith("OK (lines): pkg/Tests/helper.py"), out
    out = helper(sc, "finalize", ws=ws, swe=swe, t=180)
    assert out.startswith("READY: 2 files changed") and "CLEANED" not in out, out
    assert patch_paths(submit_patch(ws)) == ["pkg/Tests/helper.py", "pkg/testing/util.py"]
    # new files: a .py is refused up front (the graders delete it), a data file is not (the graders keep it)
    for rel in ("pkg/testing/new_helper.py", "pkg/Tests/new_mod.py", "pkg/sub/TESTING/n.py"):
        out = helper(sc, "edit", [rel, "--create"], ws=ws, swe=swe, t=190, stdin="N = 1\n")
        assert out.startswith("REFUSED: new file in a test directory (%s)" % rel), out
        assert not (ws / rel).exists()
    (ws / "pkg/testing/native.py").write_text("N = 1\n")         # written by a native tool or the shell
    out = helper(sc, "edit", ["pkg/testing/native.py", "--lines", "1-1"], ws=ws, swe=swe, t=195, stdin="N = 2\n")
    assert out.startswith("REFUSED: new file in a test directory (pkg/testing/native.py)"), out
    assert patch_paths(submit_patch(ws)) == ["pkg/Tests/helper.py", "pkg/testing/util.py"]   # the guard hides it
    out = helper(sc, "edit", ["pkg/testing/notes.txt", "--create"], ws=ws, swe=swe, t=200, stdin="n\n")
    assert out.startswith("OK (create"), out
    assert "reverted test/config edits: pkg/testing/native.py" in out, out   # hygiene after every landed write
    assert not (ws / "pkg/testing/native.py").exists()
    (ws / "pkg/Tests/native2.py").write_text("N = 1\n")         # again, then straight to finalize
    out = helper(sc, "finalize", ws=ws, swe=swe, t=210)
    assert out.startswith("READY: 3 files changed") and "CLEANED: the patch carried" not in out, out
    assert "reverted test/config edits: pkg/Tests/native2.py" in out, out
    assert not (ws / "pkg/Tests/native2.py").exists()
    got = submit_patch(ws)
    assert patch_paths(got) == ["pkg/Tests/helper.py", "pkg/testing/notes.txt", "pkg/testing/util.py"], got
    # the graders' own reset keeps every tracked edit and the new data file: nothing the helpers kept is lost
    _grader_reset(ws, patch_paths(got))
    assert (ws / "pkg/testing/util.py").read_text() == "def u():\n    return 2\n"
    assert (ws / "pkg/Tests/helper.py").read_text() == "H = 2\n" and (ws / "pkg/testing/notes.txt").exists()
    # one rule: edit.py's refusal == patch_violations' test/config verdict, tracked and new, over a table
    tracked = ["pkg/testing/util.py", "pkg/Tests/helper.py", "tests/test_mod.py", "tests/__init__.py", "setup.cfg",
               "pkg/mod.py", "pyproject.toml"]
    new = ["pkg/testing/x.py", "pkg/Tests/x.py", "a/b/testing/c/d.py", "Test/x.py", "tests/data.json",
           "pkg/testing/d.json", "pkg/new.py", "pkg/tests/h.py", "testing/t.py", "pkg/conftest.py", "x.pth",
           "pkg/test_new.py", "pkg/ünï.py"]
    code = ("import json\nrows = json.loads(%r)\nout = []\nfor p, n in rows:\n"
            "    v = [w for q, w in C.patch_violations([(p, n)]) if w == 'test/config file']\n"
            "    out.append([p, n, bool(C.write_protected(p)), bool(v)])\nprint(json.dumps(out))\n"
            % json.dumps([[p, False] for p in tracked] + [[p, True] for p in new]))
    r = run_py(sc, code, env=env_at(ws, swe), cwd=ws)
    rows = json.loads(r.stdout.strip().splitlines()[-1])
    assert [x for x in rows if x[2] != x[3]] == [], rows
    assert {p for p, _, refused, _ in rows if refused} == {
        "tests/test_mod.py", "tests/__init__.py", "setup.cfg", "pyproject.toml", "pkg/testing/x.py", "pkg/Tests/x.py",
        "a/b/testing/c/d.py", "Test/x.py", "tests/data.json", "pkg/tests/h.py", "testing/t.py", "pkg/conftest.py",
        "x.pth", "pkg/test_new.py"}, rows


# ---------------------------------------------------------------------------------------------------------------------
# replay_l4: the v10.1 diagnostic KPIs
# ---------------------------------------------------------------------------------------------------------------------
def _rp():
    sys.path.insert(0, str(ROOT / "scripts"))
    import replay_l4 as R
    return R


def test_replay_diag_kpis_unit(tmp_path):
    """Each diagnostic counter on a synthetic trace: a parsed call to 'view.py' (the crash), text calls to an invented
    name and to a real tool, a verifier whose first turn is such a text, a cascade, helpers and tools typed into the
    shell, a locator reply at 768 tokens, grep.py with a trailing path that missed, an empty submit at t=115, and the
    can't-open-file split."""
    import test_v10_runner as TR
    R = _rp()

    def text(author, pt, ct, t, msg):
        s = TR._step(author, pt, ct, t)
        s["message"] = msg
        return s
    cmd = lambda c: {"command": c}
    steps = [
        TR._step("setup", 4000, 30, 0.0, "run_skill_script", {"file_path": "install.py"}, '{"status": "success"}'),
        TR._step("locator", 4100, 40, 1.0, "view.py", {"filepath": "a.py", "start_line": 1}, ""),
        TR._step("locator", 4200, 40, 2.0, "run_command", cmd('python3 /tmp/swe/grep.py "on_startup" pkg/routing.py'),
                 "GREP: 0 hits in 0 files (shown 0)\n[t=20s]"),
        TR._step("locator", 4300, 40, 3.0, "run_command", cmd("view.py pkg/a.py 1 9"), "bash: view.py: command not found"),
        TR._step("locator", 4400, 40, 4.0, "run_command", cmd("run_command python3 x"), "command not found"),
        TR._step("locator", 4500, 40, 5.0, "run_command", cmd("python3 /tmp/swe/verify_tabs.py"),
                 "python3: can't open file '/tmp/swe/verify_tabs.py'"),
        text("locator", 4600, 768, 6.0, "<|tool_call>call:run_command{command:<|\"|>python3 /tmp/swe/verify.py"),
        text("fixer", 3000, 40, 7.0, '<|tool_call>call:grep.py "class APIRouter" fastapi/routing.py<tool_call|>'),
        text("verifier", 3100, 30, 8.0, "<|tool_call>call:python3 /tmp/swe/status.py<tool_call|>"),
        TR._step("submitter", 3200, 20, 9.0, "run_command", cmd("python3 /tmp/swe/finalize.py"),
                 "NOT READY: EMPTY\n[t=115s]"),
        TR._step("submitter", 3300, 20, 10.0, "submit_patch", {}, '{"status": "ok", "patch_size": 0}'),
        text("submitter", 3400, 5, 11.0, "submitted"),
    ]
    d = TR._write_run(tmp_path / "r", {"a": dict(steps=steps, patch="")})
    t = R.load(str(d), keep_obs=True)["a"]
    c, ex = R.pipeline_diag(t)
    assert (c["parsed_invented"], c["unparsed_invented"], c["unparsed_real"]) == (1, 2, 1), c
    assert (c["stage_text_calls"], c["verifier_first_text"], c["verifier_runs"], c["cascades"]) == (3, 1, 1, 1), c
    assert (c["helper_shell"], c["tool_shell"], c["locator_capped"]) == (1, 1, 1), c
    assert (c["grep_trailing"], c["grep_trailing_bad"], c["empty_submit_early"]) == (1, 1, 1), c
    assert (c["cant_open_helper"], c["cant_open_invented"]) == (0, 1), c
    assert ex["parsed_invented"] == ["None:view.py"] or ex["parsed_invented"][0].endswith(":view.py")
    # a clean task counts nothing
    good = R.load(str(TR._write_run(tmp_path / "g", {"b": TR._good_task()})), keep_obs=True)["b"]
    c2, _ = R.pipeline_diag(good)
    assert not any(v for k, v in c2.items() if k != "verifier_runs"), c2
    # the KPI 7/8 mechanism
    fin = [TR._step("verifier", 5000, 20, 1.0, "run_command", cmd("python3 /tmp/swe/finalize.py"), "READY: 2 files"),
           TR._step("verifier", 5100, 20, 2.0, "edit_file", {"filepath": "pyproject.toml"}, "ok")]
    d2 = TR._write_run(tmp_path / "m", {"c": dict(steps=fin)})
    assert R.patch_mechanism(R.load(str(d2), keep_obs=True)["c"]).startswith("write after READY finalize")
    assert R.patch_mechanism(good) == "no READY finalize (end state)"


@pytest.mark.skipif(not (RUNS2 / "r2_v10_1").is_dir(), reason="race-2 round-1 traces absent (eval/race2/eval/runs)")
def test_replay_diag_reproduces_race2_round1():
    """The diagnostic KPIs reproduce the diagnoses' counts on r2_v10_1 (and v9_eog's zeros), so the next measurement is
    compared with numbers produced by the same code."""
    R = _rp()
    k = R.run_kpis(str(RUNS2 / "r2_v10_1"), "r2_v10_1")["diag"]
    assert (k["parsed_invented"], k["unparsed_invented"]) == (1, 29), k
    assert (k["verifier_first_text"], k["verifier_runs"]) == (9, 69)
    assert (k["helper_shell"], k["tool_shell"], k["locator_capped"]) == (6, 2, 11)
    assert k["grep_trailing_bad"] == 65 and k["cant_open_invented"] == 2 and k["cant_open_helper"] == 0
    assert k["patch_mechanism"] == {"fastapi_14077": "write after READY finalize (step 44)",
                                    "fastapi_14258": "no READY finalize (end state)"}
    assert k["over_cap_all"] == ["fastapi_14306", "rich_3061", "rich_4079"]
    v9 = R.run_kpis(str(RUNS2 / "r2_v9_eog_1"), "r2_v9_eog_1")["diag"]
    assert (v9["parsed_invented"], v9["unparsed_invented"], v9["verifier_first_text"]) == (0, 0, 0), v9
