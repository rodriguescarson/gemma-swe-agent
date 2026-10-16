"""v15 = v13 at v12's thinking budget: the two sub17 levers (L1 edits only through a run_command python heredoc, L2 per-command
timeout 60 s) on top of v12 (hidden 0.15, the best so far) instead of on v12-b1024 (hidden 0.10). Pinned here before any v15
run (GAPS 'v15 pre-registration', 2026-10-16): every file byte-identical to v13 except configs/sampling.yaml, which is
byte-identical to v12's (v12-b1024 differs from v12 in the one thinking_budget line, and v13 carries v12-b1024's file); no
public-task specifics; scripts/validate.py passes and reports thinking_budget 4096."""
import filecmp, os, subprocess, sys
from pathlib import Path

from test_v13_rich_solve import _leaks, all_files

ROOT = Path(__file__).resolve().parents[1]
V12 = ROOT / "submissions" / "v12"
B1024 = ROOT / "submissions" / "v12-b1024"
V13 = ROOT / "submissions" / "v13"
V15 = ROOT / "submissions" / "v15"
SAMPLING = "configs/sampling.yaml"


def test_only_the_sampling_config_differs_from_v13():
    assert all_files(V15) == all_files(V13)
    for rel in sorted(all_files(V13)):
        assert filecmp.cmp(V13 / rel, V15 / rel, shallow=False) == (rel != SAMPLING), rel
        assert os.stat(V13 / rel).st_mode == os.stat(V15 / rel).st_mode, rel


def test_sampling_is_v12s_and_the_budget_is_the_only_line_that_moved():
    assert filecmp.cmp(V12 / SAMPLING, V15 / SAMPLING, shallow=False)
    assert filecmp.cmp(B1024 / SAMPLING, V13 / SAMPLING, shallow=False)
    old = (V13 / SAMPLING).read_text().splitlines()
    new = (V15 / SAMPLING).read_text().splitlines()
    assert len(old) == len(new)
    changed = [(a, b) for a, b in zip(old, new) if a != b]
    assert changed == [("  thinking_budget: 1024", "  thinking_budget: 4096")], changed


def test_no_public_task_specifics_in_v15():
    assert (V15 / "agent.yaml").is_file() and not _leaks(V15)


def test_validator_passes_for_v15():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(V15)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "tools=['run_command', 'read_file', 'get_status', 'submit_patch']" in r.stdout
    assert "'thinking_budget': 4096" in r.stdout and "'temperature': 1.0" in r.stdout
