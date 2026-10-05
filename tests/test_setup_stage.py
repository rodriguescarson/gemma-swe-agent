"""Root-cause fix for the recurring "can't open file /tmp/swe/<helper>.py" on Kaggle (Carson 2026-10-05: fix asap).
Measured on L4 traces (scripts/analyze_helper_reachability.py): v4h2f 54/74 and v4h2g 44/74 tasks had a first
helper failure, and in EVERY one the locator called locate.py before it had ever run install.py (it skipped step 1);
once installed, no helper ever failed again in that task. Fix: a dedicated first stage whose only tools are the skill
tools, so the only action available is the install; the locator no longer carries the install step.
Written before the change. Applies to every bundle that ships /tmp/swe helpers going forward (v5h2, v5h2b)."""
import pathlib, re, yaml
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUNDLES = ["v5h2", "v5h2b"]


def _yaml(p):
    return yaml.safe_load(re.sub(r"!include\s+\S+", "INCLUDED", p.read_text()))


@pytest.mark.parametrize("b", BUNDLES)
def test_setup_is_the_first_stage(b):
    root = _yaml(ROOT / "submissions" / b / "agent.yaml")
    assert root["agent_class"] == "SequentialAgent"
    assert root["sub_agents"][0]["config_path"] == "sub_agents/setup.yaml"
    assert [s["config_path"] for s in root["sub_agents"][1:]] == [
        "sub_agents/locator.yaml", "sub_agents/fixer.yaml", "sub_agents/verifier.yaml"]


@pytest.mark.parametrize("b", BUNDLES)
def test_setup_stage_can_only_install(b):
    d = ROOT / "submissions" / b
    s = _yaml(d / "sub_agents" / "setup.yaml")
    assert s.get("tools", []) == [], "no shell/read/edit tools: the only possible action is the skill install"
    assert s["skills"] == ["skills/swe-tools"]
    assert s.get("include_contents") == "none"
    prompt = (d / "prompts" / "setup.md").read_text()
    assert 'run_skill_script(skill_name="swe-tools", file_path="install.py")' in prompt
    assert "{problem_description}" not in prompt  # no reason to spend tokens on the issue here
    assert len(prompt.split()) < 80


@pytest.mark.parametrize("b", BUNDLES)
def test_locator_no_longer_carries_the_install_step_but_keeps_one_recovery_line(b):
    loc = (ROOT / "submissions" / b / "prompts" / "locator.md").read_text()
    steps = re.findall(r"^\d+\. .*$", loc, re.M)
    assert steps and "install.py" not in steps[0], "step 1 must be the search, not the install"
    assert loc.count("install.py") == 1 and "can't open file" in loc  # the single recovery instruction


@pytest.mark.parametrize("b", BUNDLES)
def test_install_is_idempotent_so_a_recovery_call_is_harmless(b):
    src = (ROOT / "submissions" / b / "skills" / "swe-tools" / "scripts" / "install.py").read_text()
    assert "exist_ok=True" in src or "os.path.exists" in src
