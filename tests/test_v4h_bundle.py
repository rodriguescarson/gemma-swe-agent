"""v4h is v4 plus one variable: the edit channel. Everything else must be byte-identical to v4."""
import filecmp, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V4, V4H = ROOT / "submissions" / "v4", ROOT / "submissions" / "v4h"
SAME = ["agent.yaml", "eval_config.yaml", "configs/sampling.yaml", "prompts/locator.md", "sub_agents/locator.yaml",
        "skills/swe-tools/scripts/_ws.py", "skills/swe-tools/scripts/check.py", "skills/swe-tools/scripts/locate.py",
        "skills/swe-tools/scripts/test.py"]
CHANGED = {"prompts/fixer.md", "prompts/verifier.md", "skills/swe-tools/SKILL.md", "skills/swe-tools/scripts/install.py",
           "sub_agents/fixer.yaml", "sub_agents/verifier.yaml"}
ADDED = {"skills/swe-tools/scripts/edit.py"}


def files(d):
    return {str(p.relative_to(d)) for p in d.rglob("*")
            if p.is_file() and not p.name.startswith(".") and "__pycache__" not in p.parts}


def test_only_the_edit_channel_differs_from_v4():
    assert files(V4H) == files(V4) | ADDED
    for rel in SAME:
        assert filecmp.cmp(V4 / rel, V4H / rel, shallow=False), rel
    assert {rel for rel in files(V4) if not filecmp.cmp(V4 / rel, V4H / rel, shallow=False)} == CHANGED


def test_fixer_and_verifier_lose_edit_file_and_gain_the_skill():
    for name in ("fixer", "verifier"):
        y = (V4H / "sub_agents" / f"{name}.yaml").read_text()
        assert "edit_file" not in y and "skills: [skills/swe-tools]" in y and "write_file" in y, name
        p = (V4H / "prompts" / f"{name}.md").read_text()
        assert "python3 /tmp/swe/edit.py" in p and "<<<<<<< SEARCH" in p and "There is no edit_file tool" in p
        assert "with `edit_file`" not in p and "run_skill_script" in p
    loc = (V4H / "sub_agents" / "locator.yaml").read_text()
    assert "edit_file" in loc                                   # the locator is untouched v4 (it never called edit_file)


def test_v4h2f_install_puts_every_helper_in_the_sandbox_tmp(tmp_path):
    """2026-10-04: on the scorer (4xL4 traces of g4-l4-v4 v4) v4h2's locate.py failed 145 of 151 calls, check.py 61/62,
    test.py 19/19 with "can't open file": the sandbox rewrites /tmp/swe/<x>.py to <sandbox>/tmp/swe/<x>.py and only
    edit.py had been copied there. Every helper goes into every sandbox tmp dir; the historical v4h/v4h2 bundles are
    left as submitted (sub9) and the fixed bundle is v4h2f."""
    V4H2F = ROOT / "submissions" / "v4h2f"
    env = dict(os.environ, TMPDIR=str(tmp_path), TEST_TMPDIR=str(tmp_path))
    p = subprocess.run([sys.executable, str(V4H2F / "skills/swe-tools/scripts/install.py")], capture_output=True, text=True, env=env)
    assert p.returncode == 0 and "helpers in" in p.stdout, p.stdout + p.stderr
    for h in ("edit.py", "locate.py", "test.py", "check.py", "_ws.py"):
        assert (tmp_path / "swe" / h).exists(), h
    changed = {rel for rel in files(ROOT / "submissions" / "v4h2") if not filecmp.cmp(ROOT / "submissions" / "v4h2" / rel, V4H2F / rel, shallow=False)}
    assert files(V4H2F) == files(ROOT / "submissions" / "v4h2") and changed == {"skills/swe-tools/scripts/install.py"}, changed


def test_bundle_compiles_with_the_official_compiler():
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(V4H)], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    fixer_line = p.stdout.split("LlmAgent fixer")[1].split("\n")[0]
    assert "edit_file" not in fixer_line and "SkillToolset" in fixer_line, fixer_line


def test_v4h2_differs_from_v4h_only_in_the_call_shape_lines():
    V4H2 = ROOT / "submissions" / "v4h2"
    assert files(V4H2) == files(V4H)
    changed = {rel for rel in files(V4H) if not filecmp.cmp(V4H / rel, V4H2 / rel, shallow=False)}
    assert changed == {"prompts/fixer.md", "prompts/verifier.md"}, changed
    for name in ("fixer", "verifier"):
        a, b = (V4H / "prompts" / f"{name}.md").read_text().splitlines(), (V4H2 / "prompts" / f"{name}.md").read_text().splitlines()
        assert len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1
        assert 'run_command(command="python3 /tmp/swe/edit.py ...")' in (V4H2 / "prompts" / f"{name}.md").read_text()


def test_v4h3_differs_from_v4h2_only_in_the_verifier_loop_lines():
    """v4h3 = v4h2 + a bounded fix-and-test loop in the verifier (one variable). Evidence (eval/kaggle/g4-l4-v4/
    failure_taxonomy.json): of 27 right-file-wrong-fix tasks on L4, 10 never ran a test and 7 ended on a failing test
    (4 with >100 s left); v4's verifier re-runs once at most."""
    V4H2, V4H3 = ROOT / "submissions" / "v4h2", ROOT / "submissions" / "v4h3"
    assert files(V4H3) == files(V4H2)
    changed = {rel for rel in files(V4H2) if not filecmp.cmp(V4H2 / rel, V4H3 / rel, shallow=False)}
    assert changed == {"prompts/verifier.md"}, changed
    a, b = (V4H2 / "prompts" / "verifier.md").read_text().splitlines(), (V4H3 / "prompts" / "verifier.md").read_text().splitlines()
    assert len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1
    v3 = (V4H3 / "prompts" / "verifier.md").read_text()
    assert "at most 3 more rounds" in v3 and "budget warning" in v3 and "never the whole suite" in v3
    assert "re-run once" not in v3
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(V4H3)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
