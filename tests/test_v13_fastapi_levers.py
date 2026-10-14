"""Single-lever candidates on top of submissions/v13 for the feasible fastapi tasks of the 42 (docs/forty_two/queue/).

Each bundle submissions/v13_<lever> is a byte copy of submissions/v13 plus ONE sentence inserted into prompts/system.md
right after an anchor sentence of v13's prompt. These tests pin that (nothing else differs, file modes included), that the
added text carries no fenced code block and nothing that looks like a tool call (the coordinator's 2026-10-14 warning: a
v13 box row wrote its tool call as text in Gemma's native syntax), that it stays short (Gemma tokens counted when the
tokenizer is on disk), that no public-task specifics leak into it (tests/test_v13_leakage.py's deny list), and that the
organisers' compiler accepts the bundle with v13's tools and sampling.

Levers (evidence: docs/forty_two/queue/*.json and docs/forty_two/evidence/fastapi_levers.md):
- redfirst: before the first edit, run the issue's example with an assert that fails on the current code plus one
  assert on an ordinary input that must keep today's result; rerun it after each edit.
- grepsites: once the fix is in, git grep the package for the changed call or expression and give every other site that
  does the same job the same fix."""
import filecmp, os, re, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V13 = ROOT / "submissions" / "v13"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v13_leakage import leaks  # noqa: E402

LEVERS = {
    "v13_redfirst": (
        "One or two reads are enough.",
        " Before the first edit, run the issue's example as a python3 heredoc that asserts the result the issue asks for"
        " and, for one ordinary input, the result the code gives today. The first assert must fail now (if it passes, the"
        " example misses the bug, so change it); rerun the same check after each edit until both asserts pass.",
    ),
    "v13_grepsites": (
        "Apply the same fix to an obvious sibling (both branches of a condition, load and loads) with one more edit.",
        " Once the fix is in, git grep the package for the call or expression you changed, and give the same fix to every"
        " other site that does the same job.",
    ),
}
MAX_ADDED_TOKENS = 90
TOKENIZER = Path.home() / ".cache/huggingface/hub/models--google--gemma-4-31b-it-qat-w4a16-ct"


def all_files(d):
    return {str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file()}


def expected_prompt(name):
    anchor, added = LEVERS[name]
    base = (V13 / "prompts" / "system.md").read_text()
    assert base.count(anchor) == 1, anchor
    return base.replace(anchor, anchor + added)


@pytest.mark.parametrize("name", sorted(LEVERS))
def test_bundle_is_v13_plus_one_inserted_sentence(name):
    dst = ROOT / "submissions" / name
    assert all_files(dst) == all_files(V13)
    for rel in sorted(all_files(V13)):
        same = filecmp.cmp(V13 / rel, dst / rel, shallow=False)
        assert same == (rel != "prompts/system.md"), rel
        assert os.stat(V13 / rel).st_mode == os.stat(dst / rel).st_mode, rel
    assert (dst / "prompts" / "system.md").read_text() == expected_prompt(name)


@pytest.mark.parametrize("name", sorted(LEVERS))
def test_added_text_has_no_code_fence_or_tool_call_syntax(name):
    added = LEVERS[name][1]
    for bad in ("```", "`", "<|", "|>", "call:", "{", "}", "<<", "tool_call", "edit_file", "write_file"):
        assert bad not in added, (name, bad)
    assert "\n" not in added                      # one sentence group inside an existing step, no new block


@pytest.mark.parametrize("name", sorted(LEVERS))
def test_added_text_is_short(name):
    added = LEVERS[name][1]
    assert len(added) <= 330
    snaps = sorted(TOKENIZER.glob("snapshots/*/tokenizer.json"))
    if not snaps:
        pytest.skip("Gemma tokenizer not on disk")
    from tokenizers import Tokenizer
    n = len(Tokenizer.from_file(str(snaps[0])).encode(added, add_special_tokens=False).ids)
    assert n <= MAX_ADDED_TOKENS, n


@pytest.mark.parametrize("name", sorted(LEVERS))
def test_no_public_task_specifics(name):
    assert not leaks(ROOT / "submissions" / name)


@pytest.mark.parametrize("name", sorted(LEVERS))
def test_validator_passes_with_v13_tools_and_sampling(name):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(ROOT / "submissions" / name)],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "tools=['run_command', 'read_file', 'get_status', 'submit_patch']" in r.stdout
    assert "'thinking_budget': 1024" in r.stdout and "'temperature': 1.0" in r.stdout


def test_check_replay_keeps_only_package_hunks():
    sys.path.insert(0, str(ROOT / "scripts" / "forty_two"))
    from check_replay import package_only
    box = ("diff --git a/pkg/m.py b/pkg/m.py\n--- a/pkg/m.py\n+++ b/pkg/m.py\n@@ -1 +1 @@\n-a\n+b\n"
           "diff --git a/repro.py b/repro.py\nnew file mode 100644\n--- /dev/null\n+++ b/repro.py\n@@ -0,0 +1 @@\n+x\n"
           "diff --git a/pkg/tests/t.py b/pkg/tests/t.py\n--- a/pkg/tests/t.py\n+++ b/pkg/tests/t.py\n@@ -1 +1 @@\n-c\n+d\n")
    kept = package_only(box, "pkg")
    assert kept.count("diff --git") == 1 and "a/pkg/m.py" in kept and "repro.py" not in kept and "tests/t.py" not in kept
    gold = "--- a/pkg/m.py\n+++ b/pkg/m.py\n@@ -1 +1 @@\n-a\n+b\n--- a/docs/x.md\n+++ b/docs/x.md\n@@ -1 +1 @@\n-e\n+f\n"
    kept = package_only(gold, "pkg")
    assert "a/pkg/m.py" in kept and "docs/x.md" not in kept
