"""v16 = v12 (hidden 0.15, our best scored bundle; 5-minute cap, 40 calls, 180 s per command, 150 turns; temperature 1.0) with
ONE change: pub024's system prompt (the public LB-0.24 lineage's procedural prompt: call plan, protected test files, parallel
sync/async fixes, git status + diff before submit_patch), with its single budget sentence restated to v12's own limits ("40 tool
calls and 5 minutes in total" instead of "28 tool calls and 8 minutes"). Why (GAPS 'Deadline curve and the worst-case gate',
2026-10-18): pub024 itself cannot ship (its 8-minute cap errored on Kaggle's 12-hour limit twice), but its prompt can, under a
5-minute cap whose worst case (120 x 5 min = 10 h) is provably inside the limit. Pinned before any v16 row exists: every file
other than prompts/system.md byte-identical to v12; the prompt equals pub024's with exactly that sentence replaced; no braces;
validate.py OK with v12's six tools, temperature 1.0, thinking 4096, limits 5 min / 40 calls."""
import filecmp, os, subprocess, sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
V12 = ROOT / "submissions" / "v12"
PUB = ROOT / "submissions" / "pub024"
V16 = ROOT / "submissions" / "v16"
OLD_SENTENCE = "- 28 tool calls and 8 minutes in total."
NEW_SENTENCE = "- 40 tool calls and 5 minutes in total."


def all_files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())


def test_only_the_prompt_differs_from_v12():
    assert all_files(V16) == all_files(V12)
    for rel in all_files(V12):
        assert filecmp.cmp(V12 / rel, V16 / rel, shallow=False) == (rel != "prompts/system.md"), rel
        assert os.stat(V12 / rel).st_mode == os.stat(V16 / rel).st_mode, rel


def test_prompt_is_pub024s_restated_to_v12s_limits():
    pub = (PUB / "prompts" / "system.md").read_text()
    new = (V16 / "prompts" / "system.md").read_text()
    assert pub.count(OLD_SENTENCE) == 1
    assert new == pub.replace(OLD_SENTENCE, NEW_SENTENCE)
    assert "{" not in new and "}" not in new and "8 minutes" not in new and "28 tool calls" not in new
    ev = yaml.safe_load((V16 / "eval_config.yaml").read_text())["evaluation"]
    assert ev == {"timeout_seconds": 180, "max_tool_calls": 40, "max_time_minutes": 5, "max_turns": 150}, ev


def test_worst_case_runtime_fits_the_12_hour_limit():
    ev = yaml.safe_load((V16 / "eval_config.yaml").read_text())["evaluation"]
    assert 120 * ev["max_time_minutes"] <= 600          # 120 hidden tasks all at the cap: 10 h, 2 h for sandbox setup


def test_validator_passes_for_v16():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(V16)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "tools=['run_command', 'read_file', 'edit_file', 'write_file', 'get_status', 'submit_patch']" in r.stdout
    assert "'thinking_budget': 4096" in r.stdout and "'temperature': 1.0" in r.stdout
