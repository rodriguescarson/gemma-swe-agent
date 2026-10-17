"""pub024_6m = pub024 (the public LB-0.24 bundle; sub18 of it ERRORED on Kaggle's 12-hour runtime limit, see GAPS 'sub18
ERRORED on runtime') with its per-task budget cut from 8 to 6 minutes and nothing else: eval_config.yaml max_time_minutes
8 -> 6 (the other three limits unchanged), and the prompt's one budget sentence saying "8 minutes" now says "6 minutes" (the
prompt states its budget, so the number travels with the limit). Pinned before any pub024_6m row exists: every other file
byte-identical to pub024; the two edits are exactly those; validate.py OK with the nine tools, temperature 0.2, thinking 4096."""
import filecmp, os, subprocess, sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "submissions" / "pub024"
B6 = ROOT / "submissions" / "pub024_6m"
OLD_SENTENCE = "- 28 tool calls and 8 minutes in total."
NEW_SENTENCE = "- 28 tool calls and 6 minutes in total."


def all_files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())


def test_only_the_limits_and_the_prompt_differ_from_pub024():
    assert all_files(B6) == all_files(PUB)
    for rel in all_files(PUB):
        same = filecmp.cmp(PUB / rel, B6 / rel, shallow=False)
        assert same == (rel not in ("eval_config.yaml", "prompts/system.md")), rel
        assert os.stat(PUB / rel).st_mode == os.stat(B6 / rel).st_mode, rel


def test_limits_are_pub024s_with_only_max_time_minutes_6():
    old = yaml.safe_load((PUB / "eval_config.yaml").read_text())["evaluation"]
    new = yaml.safe_load((B6 / "eval_config.yaml").read_text())["evaluation"]
    assert old == {"timeout_seconds": 240, "max_tool_calls": 28, "max_time_minutes": 8, "max_turns": 80}
    assert new == {**old, "max_time_minutes": 6}
    assert (B6 / "eval_config.yaml").read_text() == (PUB / "eval_config.yaml").read_text().replace("max_time_minutes: 8", "max_time_minutes: 6")


def test_prompt_is_pub024s_with_only_the_budget_sentence_changed():
    old = (PUB / "prompts" / "system.md").read_text()
    new = (B6 / "prompts" / "system.md").read_text()
    assert old.count(OLD_SENTENCE) == 1 and "8 minutes" not in old.replace(OLD_SENTENCE, "")
    assert new == old.replace(OLD_SENTENCE, NEW_SENTENCE)
    assert "{" not in new and "}" not in new


def test_validator_passes_for_pub024_6m():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(B6)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert ("tools=['run_command', 'read_file', 'edit_file', 'write_file', 'get_status', 'submit_patch', "
            "'get_code_neighbors', 'search_similar_code', 'get_code_subgraph']") in r.stdout
    assert "'thinking_budget': 4096" in r.stdout and "'temperature': 0.2" in r.stdout
