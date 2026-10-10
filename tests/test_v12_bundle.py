"""v12 = one LlmAgent with thinking on, sized for the scorer since 2026-10-09 (plan ~/.claude/plans/nifty-sleeping-liskov.md,
Track B): no stages, no setup step, no skills, no graph tools; thinking on with a 4,096 budget and summaries (forum
746250: 48-51/129 vs 23/129 off), temperature 1.0 (the v4 lineage and the forum's best), output room 8,192; 40 tool
calls in 5 minutes (about 34 fit at 8.7 s per call with thinking). The prompt is the harness's partner, not its echo:
the harness's user turn already carries the problem statement, instructions 0-5 and the workspace tree.
Tests: the file set, the compiled tree (one agent, six tools, thinking on), the prompt lint (no call shapes, every tool
it names is declared, the numbers it quotes are the eval_config's), the kernel recipe. Written before the kernel."""
import re, subprocess, sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "tests"))
import swe_compat  # noqa: E402

V12 = ROOT / "submissions" / "v12"
TOOLS = ["run_command", "read_file", "edit_file", "write_file", "get_status", "submit_patch"]
FORBIDDEN = ("run_command(", "run_skill_script(", "submit_patch(", "read_file(", "edit_file(", "write_file(", "get_status(")
KERNEL_DIR, KERNEL_SLUG = "g4-l4-v12-p312", "g4-eval74-v3"
NEW_STACK = not swe_compat.stack()["old_helpers"]


def all_files(d):
    return {str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file() and "__pycache__" not in p.parts}


def test_the_bundle_is_four_files_and_one_prompt():
    assert all_files(V12) == {"agent.yaml", "eval_config.yaml", "configs/sampling.yaml", "prompts/system.md"}
    a = yaml.safe_load(re.sub(r"!include\s+\S+", "INCLUDED", (V12 / "agent.yaml").read_text()))
    assert a["model"] == "gemma-4-31b-it-qat-w4a16-ct" and a["tools"] == TOOLS and "sub_agents" not in a and "skills" not in a
    s = yaml.safe_load((V12 / "configs" / "sampling.yaml").read_text())
    assert s == {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "max_output_tokens": 8192, "seed": 42,
                 "thinking_config": {"include_thoughts": True, "thinking_budget": 4096}}
    ev = yaml.safe_load((V12 / "eval_config.yaml").read_text())
    assert ev == {"evaluation": {"timeout_seconds": 180, "max_tool_calls": 40, "max_time_minutes": 5, "max_turns": 150}}
    assert 32768 - 14336 - 8192 >= 2048                                   # compaction headroom (forum 747791)


@pytest.mark.skipif(not NEW_STACK, reason="needs adk_submission 0.2.13 in the venv")
def test_the_official_compiler_builds_one_agent_with_the_six_tools_thinking_on():
    from test_make_t0 import thinking_of
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(V12)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    agents = re.findall(r"^\s*(\w+Agent) (\w+) model=\S+ tools=(\[.*\])$", r.stdout, re.M)
    assert agents == [("LlmAgent", "swe_single_agent", str(TOOLS))], agents
    assert "'include_thoughts': True, 'thinking_budget': 4096" in r.stdout and "'max_output_tokens': 8192" in r.stdout
    assert thinking_of(V12) == {"swe_single_agent": (True, 4096, None)}


def test_the_prompt_names_only_declared_tools_and_shows_no_call_shape():
    t = (V12 / "prompts" / "system.md").read_text()
    for bad in FORBIDDEN:
        assert bad not in t, bad
    named = {n for n in ("run_command", "read_file", "edit_file", "write_file", "get_status", "submit_patch", "run_skill_script",
                         "get_code_neighbors", "search_similar_code", "get_code_subgraph", "bash", "git_grep") if re.search(r"\b%s\b" % n, t)}
    assert named <= set(TOOLS), named - set(TOOLS)
    assert {"run_command", "read_file", "edit_file", "submit_patch", "get_status"} <= named   # the ones the steps use
    for sp in re.findall(r"`([^`\n]+)`", t):                                # backticks hold shell lines or paths, never tool calls
        assert not any(re.search(r"\b%s\b" % n, sp) for n in TOOLS), sp
    assert "the whole test suite" in t and "tests/" in t and "submit_patch" in t


def test_the_numbers_in_the_prompt_are_the_eval_configs():
    t = (V12 / "prompts" / "system.md").read_text()
    ev = yaml.safe_load((V12 / "eval_config.yaml").read_text())["evaluation"]
    assert f"about {ev['max_time_minutes']} minutes and {ev['max_tool_calls']} tool calls" in t
    assert "plan for 12 tool calls and never more than 25" in t and "after your 10th tool call" in t
    assert 25 < ev["max_tool_calls"]                                        # the hard cap stays above the prompt's own ceiling


def test_the_prompt_is_short_and_free_of_cap_words():
    t = (V12 / "prompts" / "system.md").read_text()
    assert len(t) < 3000, len(t)
    assert not re.search(r"\b(VIEW_CAP|read cap|helper|skill|/tmp/swe)\b", t)


def test_eval_kernel_ships_v12_on_a_free_312_slug(tmp_path):
    import base64, json
    kd = ROOT / "kernels" / KERNEL_DIR
    if not (kd / "kernel-metadata.json").exists():
        pytest.skip("kernels/ is gitignored: generated on the Mac")
    meta = json.loads((kd / "kernel-metadata.json").read_text())
    assert meta["id"] == "carsonrodrigues/" + KERNEL_SLUG and meta["enable_gpu"] is True and meta["docker_image_pinning_type"] == "original"
    nb = json.loads((kd / f"{KERNEL_SLUG}.ipynb").read_text())
    data = next(c["source"] for c in nb["cells"] if c["source"].startswith("FILES = "))
    files = json.loads(data[len("FILES = "):data.index("\nIDS = ")])
    assert {k: base64.b64decode(v) for k, v in files.items()} == {rel: (V12 / rel).read_bytes() for rel in all_files(V12)}
    assert len(json.loads(data[data.index("\nIDS = ") + 7:data.index("\nPATCHES = ")])) == 74
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_eval_kernel.py"), str(V12), KERNEL_DIR, "--ids", str(ROOT / "data" / "kaggle_valid_ids.txt"),
                        "--pin", "original", "--kernel-id", KERNEL_SLUG], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    for f in ("kernel-metadata.json", KERNEL_SLUG + ".ipynb"):
        assert (tmp_path / "kernels" / KERNEL_DIR / f).read_bytes() == (kd / f).read_bytes(), f
