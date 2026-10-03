"""v10.2 R2 / R139 (docs/v10/SPEC_v10_2.md 5.8, hidden.md T2 and probes F, I): a scratch prefix needs a separator, a
new root module that changed tracked code imports ships whatever its prefix, and the submit guard re-includes it.

Regression tests for B5 (scratch prefixes deleted real modules): v10.1's finalize printed "CLEANED: removed
templates_engine.py" and the harness diff held only app.py, which then imported a missing module (probe F); the submit
guard alone kept a new root template.py out of `git add -N .` (probe I). Scratch files (repro.py, tmp_check.py,
scratch.py, debug_out.log) are still removed by finalize and hidden from the harness diff (R126, R127, R130 unchanged).
Every helper runs from a temp copy of submissions/v10_2 (tests/v10_support/v102.py).
"""
import os
import pathlib
import re
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from v10_support.repo import no_orphans  # noqa: F401,E402
from v10_support.v102 import Box, V101_SCRIPTS, V102_SCRIPTS, lines, shim_path  # noqa: E402
from test_v10_1 import submit_patch, patch_paths  # noqa: E402

pytestmark = pytest.mark.skipif(not (V102_SCRIPTS / "_swe_common.py").exists(), reason="v10.2 bundle not built")

SCRATCH = ["repro.py", "reproduce_issue.py", "tmp_check.py", "scratch.py", "debug_out.log", "demo2.py", "Repro.txt",
           "TMP_notes.md", "try-1.py", "temp.py", "debug", "demo_data.py"]
REAL = ["template.py", "templates_engine.py", "tmpl.py", "temperature.py", "debugger.py", "trying.py",
        "reproducible.py", "demographics.py", "templates", "scratchpad_util.py", "tryhard.py"]
FLAT = {"app.py": "def render(x):\n    return str(x)\n", "helpers.py": "X = 1\n",
        "test_app.py": "from app import render\n\n\ndef test_r():\n    assert render(1) == '1'\n"}


def test_scratch_separator_matrix(tmp_path):
    """R139 base: the separator rule in every place that decides scratch (the helpers' scratch_name, the patch rules'
    KPI regex, _swe_ckpt's root-file rule) and in the armed guard (git check-ignore through the repo's own config)."""
    box = Box(tmp_path, FLAT)
    code = ("import _swe_ckpt as K\nimport json\nnames = %r\n"
            "print(json.dumps([[n, C.scratch_name(n), bool(C._KPI_SCRATCH_ROOT.search(n)), K.root_scratch_file(n)] "
            "for n in names]))\n" % (SCRATCH + REAL))
    import json
    rows = json.loads(box.py(code))
    for n, a, b, c in rows:
        want = n in SCRATCH
        assert (a, b, c) == (want, want, want), (n, a, b, c)
    for n in SCRATCH + REAL:
        p = box.ws / n
        if "." in n:
            p.write_text("x = 1\n")
        else:
            (p / "f.txt").parent.mkdir(exist_ok=True)
            (p / "f.txt").write_text("x\n")
    r = subprocess.run(["git", "check-ignore", "--no-index"] + SCRATCH + REAL, cwd=str(box.ws), capture_output=True,
                       text=True, env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1"))
    ignored = set(r.stdout.split())
    assert ignored == set(SCRATCH), (ignored ^ set(SCRATCH))


def test_scratch_rule_control_v101(tmp_path):
    """Control: v10.1's prefix rule called real modules scratch (hidden.md 5.2 item 2)."""
    box = Box(tmp_path, FLAT, src=V101_SCRIPTS, install=False)
    out = box.py("print([n for n in %r if C._SCRATCH_ROOT.match(n)])" % REAL)
    for n in ("template.py", "templates_engine.py", "tmpl.py", "temperature.py", "debugger.py", "trying.py",
              "reproducible.py"):
        assert n in out, (n, out)


def test_probe_f_templates_engine_ships(tmp_path):
    """R139 / probe F: a new root module imported by the changed app.py survives finalize and is in the harness diff."""
    box = Box(tmp_path, FLAT)
    box.h("status", t=5)
    box.write("templates_engine.py", "def fill(t, **kw):\n    return t.format(**kw)\n")
    box.write("app.py", "from templates_engine import fill\n\n\ndef render(x):\n    return fill('{x}', x=x)\n")
    fin = box.h("finalize", t=100)
    assert fin.startswith("READY: 2 files changed") and "CLEANED" not in fin, fin
    assert patch_paths(submit_patch(box.ws)) == ["app.py", "templates_engine.py"]


def test_probe_i_template_ships_without_finalize(tmp_path):
    """R139 / probe I: without finalize, the armed guard no longer hides a new root template.py (the fallback diff at a
    timeout carries it)."""
    box = Box(tmp_path, FLAT)
    box.write("template.py", "T = '{x}'\n")
    box.write("app.py", "from template import T\n\n\ndef render(x):\n    return T.format(x=x)\n")
    assert patch_paths(submit_patch(box.ws)) == ["app.py", "template.py"]


def test_root_module_imported_ships(tmp_path):
    """R139 base: demo_data.py (a scratch-like prefix with a separator) imported by a changed tracked file ships:
    edit.py re-arms the guard's kept entries (through its EDITED checkpoint), finalize keeps it and re-arms fully, and
    both the harness's submit and fallback commands carry it. Without the importer it is scratch."""
    files = dict(FLAT)
    files.pop("helpers.py")                      # no other root module: only the import keeps it
    box = Box(tmp_path, files)
    box.h("status", t=5)
    assert box.h("edit", ["demo_data.py", "--create"], stdin="ROWS = [1, 2]\n", t=20).startswith("OK")
    assert "demo_data.py" not in submit_patch(box.ws)                         # scratch until something imports it
    out = box.h("edit", ["app.py", "--lines", "1-2"],
                stdin="from demo_data import ROWS\n\n\ndef render(x):\n    return str(ROWS + [x])\n", t=30)
    assert out.startswith("OK"), out
    assert patch_paths(submit_patch(box.ws)) == ["app.py", "demo_data.py"]   # before finalize (the fallback diff)
    guard = (box.ws / ".git" / "swe_exclude").read_text()
    assert guard.rstrip("\n").endswith("!/demo_data.py"), guard
    fin = box.h("finalize", t=60)
    assert fin.startswith("READY: 2 files changed") and "demo_data" not in fin.split("\n", 1)[-1], fin
    assert patch_paths(submit_patch(box.ws)) == ["app.py", "demo_data.py"]


def test_unimported_scratch_still_removed_and_hidden(tmp_path):
    """R139 edges (R126, R127, R130 unchanged): repro.py, tmp_check.py, scratch.py, debug_out.log and an unimported
    demo_data.py are hidden from the harness diff and removed by finalize; a real new module in a package ships."""
    box = Box(tmp_path, FLAT)
    box.h("status", t=5)
    for n in ("repro.py", "tmp_check.py", "scratch.py", "debug_out.log", "demo_data.py"):
        box.write(n, "print(1)\n")
    box.write("app.py", FLAT["app.py"].replace("str(x)", "str(x).strip()"))
    assert patch_paths(submit_patch(box.ws)) == ["app.py"]
    fin = box.h("finalize", t=60)
    assert fin.startswith("READY: 1 files changed"), fin
    removed = re.search(r"^CLEANED: removed (.*)$", fin, re.M).group(1)
    for n in ("repro.py", "tmp_check.py", "scratch.py", "debug_out.log", "demo_data.py"):
        assert n in removed and not (box.ws / n).exists(), (n, fin)
    assert patch_paths(submit_patch(box.ws)) == ["app.py"]


def test_new_root_directories(tmp_path):
    """R139 edges: a new root templates/ (no scratch prefix) ships; a new root demo_assets/ that the changed code
    references is kept and re-included; an unreferenced tmp_out/ is removed and hidden."""
    box = Box(tmp_path, FLAT)
    box.h("status", t=5)
    box.write("templates/index.html", "<p>{x}</p>\n")
    box.write("demo_assets/rows.json", "[1, 2]\n")
    box.write("tmp_out/log.txt", "x\n")
    box.write("app.py", "import json\n\n\ndef render(x):\n    rows = json.load(open('demo_assets/rows.json'))\n"
                        "    return open('templates/index.html').read().format(x=x) + str(rows)\n")
    fin = box.h("finalize", t=60)
    assert fin.startswith("READY: 3 files changed"), fin
    assert not (box.ws / "tmp_out").exists() and (box.ws / "demo_assets/rows.json").exists()
    assert patch_paths(submit_patch(box.ws)) == ["app.py", "demo_assets/rows.json", "templates/index.html"]


def test_patch_rules_keep_imported_root_modules(tmp_path):
    """R139 unit: patch_violations keeps a new root module a changed tracked file of the same patch imports; the same
    file without its importer is a scratch violation."""
    box = Box(tmp_path, FLAT)
    box.write("app.py", "import demo_data\n")
    box.write("demo_data.py", "X = 1\n")
    got = box.py("f1 = [('app.py', False), ('demo_data.py', True)]\nf2 = [('helpers.py', False), ('demo_data.py', True)]\n"
                 "print(C.patch_violations(f1, C.kept_root_modules(f1)))\n"
                 "print(C.patch_violations(f2, C.kept_root_modules(f2)))\n"
                 "print(C.patch_violations([('repro.py', True), ('template.py', True), ('tmpl.py', True)]))\n")
    assert got.splitlines() == ["[]", "[('demo_data.py', 'scratch or vendored file')]",
                                "[('repro.py', 'scratch or vendored file')]"], got


def test_guard_text_patterns(tmp_path):
    """R139: the guard has /<prefix> and /<prefix>[-_.0-9]* per prefix (reproduce listed on its own now) and the kept
    section after its marker; baseline root entries with a scratch-like name are re-included as in v10.1."""
    files = dict(FLAT)
    files["demo_utils.py"] = "Y = 2\n"                                     # a tracked root module with such a name
    box = Box(tmp_path, files)
    g = (box.ws / ".git" / "swe_exclude").read_text().splitlines()
    for p in ("repro", "reproduce", "scratch", "debug", "tmp", "temp", "try", "demo"):
        ci = "".join("[%s%s]" % (c.upper(), c.lower()) for c in p)
        assert "/" + ci in g and "/" + ci + "[-_.0-9]*" in g, p
    assert "!/demo_utils.py" in g
    assert g[-1] == "# swe-tools v10.2: kept new root entries (imported or referenced by changed tracked code)"


def _edit_git_calls(tmp_path, src, name, scratch_file=None):
    """git child processes of one edit.py call (a later stage, source already changed), counted by a logging shim."""
    big = "".join("def f%d(x):\n    return x + %d\n\n" % (i, i) for i in range(50))
    box = Box(tmp_path / name, {"pkg/__init__.py": "", "big.py": big}, src=src)
    box.h("status", t=10)
    box.h("status", t=11)
    box.h("edit", ["big.py", "--lines", "5-5"], stdin="    return x + 1  # a\n", t=100)
    if scratch_file:
        box.write(scratch_file, "print(1)\n")
    shim = tmp_path / (name + "_shim")
    shim.mkdir()
    path, log = shim_path(shim, box.env)
    assert box.h("edit", ["big.py", "--lines", "5-5"], stdin="    return x + 2  # b\n", t=101, PATH=path).startswith("OK")
    return sum(1 for c in (log.read_text().splitlines() if log.exists() else []) if c.startswith("git"))


def test_edit_guard_refresh_costs_no_git_call_without_a_scratch_root(tmp_path):
    """Regression (review 2026-09-30, timing budget): save_edited() re-arms the guard's kept entries on every edit.py
    call, and that ran `git ls-files --others` each time: one git call more than v10.1 (5 against 4), about 11 ms of
    edit.py's 150 ms p95 budget (median 95 -> 107 ms measured), enough to fail test_edit_output_and_perf in the 2-CPU
    Linux job. A kept entry is always a root name matching the scratch rule, so a workspace root without one costs a
    listdir and no git call; with one (repro.py) the full check still runs."""
    assert _edit_git_calls(tmp_path, V102_SCRIPTS, "v102") == _edit_git_calls(tmp_path, V101_SCRIPTS, "v101")
    assert _edit_git_calls(tmp_path, V102_SCRIPTS, "v102s", "repro.py") > _edit_git_calls(tmp_path, V101_SCRIPTS,
                                                                                          "v101s", "repro.py")
