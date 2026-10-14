"""Candidate bundles for the never-solved rich tasks (docs/forty_two/tasks/<id>.md, queue entries in docs/forty_two/queue/).

Each bundle is submissions/v13 plus ONE change: one piece of text inserted into prompts/system.md at a fixed anchor. Tasks that
share a lever share a bundle. The levers are general rules for any Python repository; none names a task, a gold file, a gold
function or class, or a test (the deny list of tests/test_v13_leakage.py).

Pinned for every bundle:
- every file other than prompts/system.md is byte-identical to submissions/v13 (same modes);
- prompts/system.md is v13's with exactly the lever text inserted after its anchor, and nothing else changed;
- the inserted text has no fenced block, no backtick, no brace and nothing shaped like a tool call (coordinator, 2026-10-14: on
  the v13 box screen one task put its first tool call in the message text, suspected to follow v13's fenced heredoc block), and
  names no tool;
- the inserted text costs at most MAX_TOKENS Gemma tokens (the model's own tokenizer.json when it is cached on this machine);
- no public-task specifics, and scripts/validate.py passes."""
import filecmp, glob, importlib.util, os, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "submissions" / "v13"
RULES_END = "if less than 90 seconds remain, submit what you have.\n"     # last line of v13's Rules list
MAX_TOKENS = 90

# bundle -> (anchor in v13's prompt, text inserted right after it)
LEVERS = {
    # rich_3777, rich_3675: a new on/off option copies the value handling of the option it extends; otherwise explicit
    # 1/0 and every other value (unset, empty, unknown) keeps today's behaviour.
    "v13_flagvals": (RULES_END,
                     "- A new on/off option or environment variable: if the issue says it adds to or mirrors an existing one,"
                     " git grep that one in the source and tests/ and treat its values the same way; otherwise \"1\" turns"
                     " it on, \"0\" turns it off, and any other value (unset, empty, unknown) keeps today's behaviour, unless"
                     " the issue defines the values.\n"),
    # rich_3777 (p4_b1024 broke 96 tests of the edited module and never ran them), rich_3278 (p4_v0t2), rich_3180 (p4_v7d):
    # the module's own test file, run once after the first edit, shows a regression the issue's example cannot.
    "v13_modtests": (RULES_END,
                     "- After your first edit to a module, run its test file once (tests/test_<module>.py, or the file git"
                     " grep -l finds for the module name under tests/), even if the issue's example already passes; a"
                     " failure there in code you changed is yours to fix before you submit.\n"),
    # rich_3278: tool replies are JSON (encoded once on swegemma 0.2.11), so a file's backslash shows as two; four runs wrote
    # the reply's form into a raw regex, and v13 has no unescape fallback (it dropped edit_file, which has one).
    "v13_jsonesc": (RULES_END,
                    "- Tool replies are JSON, so file text inside them is escaped: one backslash shows as \\\\, a double"
                    " quote as \\\" and a line break as \\n. In edits and scripts write the file's real characters (one"
                    " backslash for each \\\\ you see, a plain quote for each \\\"); if an old block is not found, check"
                    " this first.\n"),
}


def all_files(d):
    return {str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file()}


def gemma_tokens(text):
    paths = glob.glob(os.path.expanduser(
        "~/.cache/huggingface/hub/models--google--gemma-4-31b-it-qat-w4a16-ct/snapshots/*/tokenizer.json"))
    if not paths:
        return None
    from tokenizers import Tokenizer
    return len(Tokenizer.from_file(paths[0]).encode(text).ids)


def _leaks(bundle):
    spec = importlib.util.spec_from_file_location("v13_leakage", ROOT / "tests" / "test_v13_leakage.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.leaks(bundle)


@pytest.mark.parametrize("name", sorted(LEVERS))
def test_only_the_prompt_differs_from_v13(name):
    dst = ROOT / "submissions" / name
    assert all_files(dst) == all_files(BASE)
    for rel in sorted(all_files(BASE)):
        assert filecmp.cmp(BASE / rel, dst / rel, shallow=False) == (rel != "prompts/system.md"), rel
        assert os.stat(BASE / rel).st_mode == os.stat(dst / rel).st_mode, rel


@pytest.mark.parametrize("name", sorted(LEVERS))
def test_the_prompt_is_v13_plus_the_lever_text_at_its_anchor(name):
    anchor, added = LEVERS[name]
    old = (BASE / "prompts" / "system.md").read_text()
    new = (ROOT / "submissions" / name / "prompts" / "system.md").read_text()
    assert old.count(anchor) == 1
    assert new == old.replace(anchor, anchor + added)


@pytest.mark.parametrize("name", sorted(LEVERS))
def test_the_lever_text_is_short_and_has_no_code_block_or_tool_call_shape(name):
    added = LEVERS[name][1]
    for bad in ("```", "`", "{", "}", "<|", "|>", "call:", "tool_call", "<<", "run_command", "read_file", "submit_patch",
                "get_status", "edit_file", "write_file"):
        assert bad not in added, bad
    n = gemma_tokens(added)
    assert (n if n is not None else len(added) / 3.15) <= MAX_TOKENS, n


@pytest.mark.parametrize("name", sorted(LEVERS))
def test_no_public_task_specifics_in_the_bundle(name):
    dst = ROOT / "submissions" / name
    assert (dst / "agent.yaml").is_file()
    assert not _leaks(dst)


def test_jsonesc_states_the_escapes_the_installed_stack_really_shows():
    """The model reads tool results as ADK serialises them: swegemma returns a dict (parse_tool_response), ADK's LiteLLM
    adapter json.dumps it once (ensure_ascii=False). So a file's backslash, double quote and newline appear as the two-character
    forms the lever names (host-confirmed since the 09-30 wheelhouse: 'tool output is JSON-encoded once')."""
    from swegemma.tools.base import ok_response, parse_tool_response
    from google.adk.models.lite_llm import _safe_json_serialize
    file_text = 'a\\b "q"\nz'                                         # a backslash, two quotes, a newline
    shown = _safe_json_serialize(parse_tool_response(ok_response(stdout=file_text)))
    assert '"a\\\\b \\"q\\"\\nz"' in shown                              # i.e. a\\b \"q\"\nz : encoded exactly once
    added = LEVERS["v13_jsonesc"][1]
    for real, seen in (("\\", "\\\\"), ('"', '\\"'), ("\n", "\\n")):
        assert _safe_json_serialize(real)[1:-1] == seen and seen in added, (real, seen)


@pytest.mark.parametrize("name", sorted(LEVERS))
def test_validator_passes(name):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(ROOT / "submissions" / name)],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "tools=['run_command', 'read_file', 'get_status', 'submit_patch']" in r.stdout
    assert "'thinking_budget': 1024" in r.stdout and "'temperature': 1.0" in r.stdout
