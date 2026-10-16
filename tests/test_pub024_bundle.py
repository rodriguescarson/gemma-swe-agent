"""pub024 = the public Kaggle notebook honghanhhh/gemma-4-baseline-lb-0-24 ("Gemma 4 Baseline | LB 0.24", 0.24 public on
16 Oct 2026), byte-identical to the FILES literal in that notebook (extracted on 2026-10-16 without running it), kept as a
CONTROL bundle: it calibrates the box's 74-task read against a known hidden score and is the lineage matterhorn3838 SuperAgent
(0.18) -> flexonafft budget-aware v2 (0.22) -> this (prompt edits only). Nothing in it is ours; it is never edited in place
(a derived bundle gets its own directory and test). Pinned: exactly four files with these digests; the notebook's own
assertion (no braces in the prompt); scripts/validate.py OK with the nine tools, thinking_budget 4096, temperature 0.2; the
evaluation limits 240 s / 28 calls / 8 min / 80 turns."""
import hashlib, subprocess, sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "submissions" / "pub024"
DIGESTS = {
    "agent.yaml": "680799291cc7d156d06fb7bfb5577f683ccc0d555b00e8ddb662d577f9bfa5e4",
    "configs/sampling.yaml": "571a934e89911734927533f1d36cbcc7b8d493592febe63b217e911cf7ed4926",
    "eval_config.yaml": "916cf6cb34a6cc3de39837fa72cac681599b9ac2a3ee0b893adadfd36474c531",
    "prompts/system.md": "ff7609068a7a301a4294e0e78fedf35a0163778cace266f33ac6815c4914d25d",
}


def test_exactly_the_notebooks_four_files_byte_identical():
    files = sorted(str(p.relative_to(PUB)) for p in PUB.rglob("*") if p.is_file())
    assert files == sorted(DIGESTS), files
    for rel, want in DIGESTS.items():
        assert hashlib.sha256((PUB / rel).read_bytes()).hexdigest() == want, rel


def test_the_notebooks_own_assertion_and_the_limits():
    prompt = (PUB / "prompts" / "system.md").read_text()
    assert "{" not in prompt and "}" not in prompt
    ev = yaml.safe_load((PUB / "eval_config.yaml").read_text())["evaluation"]
    assert ev == {"timeout_seconds": 240, "max_tool_calls": 28, "max_time_minutes": 8, "max_turns": 80}, ev
    s = yaml.safe_load((PUB / "configs" / "sampling.yaml").read_text())
    assert s["temperature"] == 0.2 and s["top_p"] == 0.95 and s["max_output_tokens"] == 8192
    assert s["thinking_config"] == {"thinking_budget": 4096, "include_thoughts": True}


def test_validator_passes_for_pub024():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(PUB)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert ("tools=['run_command', 'read_file', 'edit_file', 'write_file', 'get_status', 'submit_patch', "
            "'get_code_neighbors', 'search_similar_code', 'get_code_subgraph']") in r.stdout, r.stdout[-800:]
    assert "'thinking_budget': 4096" in r.stdout and "'temperature': 0.2" in r.stdout
