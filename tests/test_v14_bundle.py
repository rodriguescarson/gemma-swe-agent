"""v14 = v13 + every lever the per-task queue ACCEPTed (docs/forty_two/QUEUE_PLAN.md "Then merge"): the Mac's read of the synced
results on 2026-10-15 17:40 IST (65/81 task runs) gave ACCEPT = v13_flagvals (rich_3675 3/3) and v13_repro_timeout (rich_3480
2/2); every other lever was already REJECT (0/2 cannot reach 2 of 3) or credited to v13 alone. Pinned here, before the box's END
read and before any v14 run: every file other than prompts/system.md byte-identical to v13; the prompt is v13's with exactly
the two accepted lever texts (as pinned in tests/test_v13_rich_solve.py) after v13's last rule, flagvals first, nothing else;
no public-task specifics; scripts/validate.py passes."""
import filecmp, os, subprocess, sys
from pathlib import Path

from test_v13_rich_solve import LEVERS, RULES_END, _leaks, all_files, gemma_tokens, MAX_TOKENS
from test_v13_repro_timeout import RULE_START, added_text as repro_timeout_added_text

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "submissions" / "v13"
V14 = ROOT / "submissions" / "v14"
ACCEPTED = ("v13_flagvals", "v13_repro_timeout")


def test_only_the_prompt_differs_from_v13():
    assert all_files(V14) == all_files(BASE)
    for rel in sorted(all_files(BASE)):
        assert filecmp.cmp(BASE / rel, V14 / rel, shallow=False) == (rel != "prompts/system.md"), rel
        assert os.stat(BASE / rel).st_mode == os.stat(V14 / rel).st_mode, rel


def accepted_texts():
    """The two lever texts exactly as their own bundles and tests pin them: flagvals from the LEVERS table, repro_timeout as
    the one line its bundle appends to v13's prompt (tests/test_v13_repro_timeout.py)."""
    flagvals = LEVERS["v13_flagvals"][1]
    assert LEVERS["v13_flagvals"][0] == RULES_END
    assert flagvals in (ROOT / "submissions" / "v13_flagvals" / "prompts" / "system.md").read_text()
    repro = repro_timeout_added_text()
    assert repro.count("\n") == 1 and repro.startswith(RULE_START)
    return flagvals, repro


def test_the_prompt_is_v13_plus_the_two_accepted_levers_in_order():
    old = (BASE / "prompts" / "system.md").read_text()
    new = (V14 / "prompts" / "system.md").read_text()
    added = "".join(accepted_texts())
    assert old.count(RULES_END) == 1 and old.endswith(RULES_END)      # v13's last rule is its last line: both levers append
    assert new == old + added
    n = gemma_tokens(added)                              # each lever is capped at MAX_TOKENS by its own test; the join can add a token
    assert (n if n is not None else len(added) / 3.15) <= 2 * MAX_TOKENS + 2, n


def test_no_public_task_specifics_in_v14():
    assert (V14 / "agent.yaml").is_file() and not _leaks(V14)


def test_validator_passes_for_v14():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(V14)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "tools=['run_command', 'read_file', 'get_status', 'submit_patch']" in r.stdout
    assert "'thinking_budget': 1024" in r.stdout and "'temperature': 1.0" in r.stdout
