"""v10.2 eval-side parity (docs/v10/SPEC_v10_2.md section 8, E5): the golden metrics and replay_l4 decide scratch the
way the v10.2 bundle does (the R2 separator rule), and replay_l4 counts obedience to the v10.2 refusals (LOCATOR
CLOSED, PROBE LIMIT, REPRO LIMIT, SAME RUN). The recorded public runs are unaffected: no public patch adds a root file
the two rules disagree on.
"""
import importlib.util
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[0]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "eval" / "golden"))
from v10_support.repo import no_orphans  # noqa: F401,E402
from v10_support.v102 import Box, V102_SCRIPTS  # noqa: E402

# A partial copy of the repo without eval/golden (linux_test.sh V10_ONLY before 2026-09-30 linked only eval/race1 and
# eval/kaggle) must skip this module, not abort the whole collection (that run tested nothing).
if not (ROOT / "eval" / "golden" / "golden_metrics.py").is_file():
    pytest.skip("eval/golden/golden_metrics.py absent (partial repo copy)", allow_module_level=True)

import replay_l4 as R  # noqa: E402
import golden_metrics as GM  # noqa: E402

MATRIX = {"repro.py": True, "reproduce_issue.py": True, "tmp_check.py": True, "scratch.py": True,
          "debug_out.log": True, "demo2.py": True, "Repro.txt": True, "test_x.py": True, "x_test.py": True,
          "template.py": False, "templates_engine.py": False, "tmpl.py": False, "temperature.py": False,
          "debugger.py": False, "trying.py": False, "reproducible.py": False, "demographics.py": False,
          "pkg/repro.py": False, "rich/text.py": False}


def test_scratch_rule_parity_with_the_bundle(tmp_path):
    """E5: golden_metrics.SCRATCH_ROOT, replay_l4.SCRATCH_ROOT and the bundle's _KPI_SCRATCH_ROOT are one rule."""
    assert (GM.SCRATCH_ROOT.pattern, GM.SCRATCH_ROOT.flags) == (R.SCRATCH_ROOT.pattern, R.SCRATCH_ROOT.flags)
    box = Box(tmp_path, install=False)
    bundle = box.py("print(C._KPI_SCRATCH_ROOT.pattern)").rstrip("\n")
    assert bundle == R.SCRATCH_ROOT.pattern
    for p, want in MATRIX.items():
        got = bool(R.scratch_files([(p, True)]))
        assert got == want == bool(GM.scratch_files([(p, True)])), (p, got)
        assert not R.scratch_files([(p, False)])                         # a tracked file is never scratch


def _step(author, kind="call", fn="run_command", args="", obs=""):
    return {"author": author, "kind": kind, "fn": fn, "args": args, "obs": obs}


def test_obedience_counts_the_v102_refusals():
    """E5: the locator replies after LOCATOR CLOSED, PROBE LIMIT and REPRO LIMIT; a later stage runs status.py after
    LOCATOR CLOSED; after SAME RUN the next step is not the same command. v10.1's hints are counted as before."""
    closed = "LOCATOR CLOSED at t=93s after 14 calls: nothing ran. ..."
    steps = [
        _step("locator", args="python3 /tmp/swe/view.py a.py 1 9", obs=closed),
        _step("locator", kind="text", fn=None),
        _step("fixer", args="python3 /tmp/swe/view.py a.py 1 9", obs=closed),
        _step("fixer", args="python3 /tmp/swe/status.py", obs="STATUS"),
        _step("fixer", args='python3 /tmp/swe/run.py "echo x"', obs="SAME RUN: this command already ran twice on this"),
        _step("fixer", args='python3 /tmp/swe/run.py "echo x"', obs="SAME RUN: this command already ran twice on this"),
        _step("verifier", args='python3 /tmp/swe/run.py "echo y"', obs="SAME RUN: this command already ran twice on this"),
        _step("verifier", args='python3 /tmp/swe/run.py "echo z"', obs="exit=0"),
    ]
    got = R.footer_obedience(steps)
    assert got["LOCATOR CLOSED"] == [2, 2] and got["SAME RUN"] == [1, 2], got
    probe = [_step("locator", args='python3 /tmp/swe/run.py "x"', obs="PROBE LIMIT: 3 runs used before the plan"),
             _step("locator", args='python3 /tmp/swe/run.py "y"'),
             _step("locator", args="python3 /tmp/swe/verify.py --repro-only", obs="REPRO LIMIT: 2 reproductions tried"),
             _step("locator", kind="text", fn=None)]
    assert R.footer_obedience(probe) == {"PROBE LIMIT": [0, 1], "REPRO LIMIT": [1, 1]}
    assert R._obeyed("PROBE LIMIT", "fixer", [_step("fixer")]) is None
    assert R._obeyed("LOCATOR", "locator", [_step("locator", kind="text", fn=None)]) is True   # v10.1 unchanged


def test_recorded_public_patches_unaffected():
    """E5: the separator rule changes no scratch verdict on the recorded public gold patches (0 of the public gold
    patches add a root file with a scratch-like prefix, PATH_TO_020 C3)."""
    import json
    tasks = ROOT / "data" / "tasks.jsonl"
    if not tasks.exists():
        pytest.skip("data/tasks.jsonl absent")
    import re
    old = re.compile(r"^(repro|reproduce|scratch|debug|tmp|temp|try|demo)[^/]*$|^test_[^/]*\.py$|^[^/]*_test\.py$",
                     re.I)
    n = 0
    for line in tasks.read_text().splitlines():
        row = json.loads(line)
        for part in ("patch", "test_patch"):      # the data keeps unified diffs without diff --git headers
            for p in re.findall(r"^\+\+\+ b/(\S+)", row.get(part) or "", re.M):
                n += 1
                assert bool(old.search(p) and "/" not in p) == bool(R.SCRATCH_ROOT.search(p) and "/" not in p), p
    assert n > 100
