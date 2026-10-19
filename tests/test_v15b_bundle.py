"""v15b = v15 (v12 + L1 + L2: edits only through a run_command heredoc with edit_file and write_file dropped, and a 60 s
per-command timeout; box 29/74, never submitted) with v12b's sampling block (temperature 0.2, top_p 0.95, no top_k, no seed;
the change that took v12 from 0.15 to 0.17 hidden). Equivalently v12b + L1 + L2. Why: v12b still loses edit calls to
tool-call parse failures (11 tasks in p4_v12b; GAPS observation 19 Oct), which L1 removes, and the owner asked on 19 Oct to
carry the sampling change to the other shippable bundles. Five-minute cap, so the 10-hour worst-case gate holds.
Pinned before any v15b row exists."""
import filecmp, os, subprocess, sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
V15 = ROOT / "submissions" / "v15"
V12B = ROOT / "submissions" / "v12b"
V15B = ROOT / "submissions" / "v15b"
SAMPLING = "configs/sampling.yaml"


def all_files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())


def test_v15_with_v12bs_sampling_and_nothing_else():
    assert all_files(V15B) == all_files(V15)
    for rel in all_files(V15):
        assert filecmp.cmp(V15 / rel, V15B / rel, shallow=False) == (rel != SAMPLING), rel
        assert os.stat(V15 / rel).st_mode == os.stat(V15B / rel).st_mode, rel
    assert filecmp.cmp(V12B / SAMPLING, V15B / SAMPLING, shallow=False)


def test_equivalently_v12b_plus_l1_and_l2():
    differ = {rel for rel in all_files(V12B) if not filecmp.cmp(V12B / rel, V15B / rel, shallow=False)}
    assert differ == {"agent.yaml", "eval_config.yaml", "prompts/system.md"}, differ
    ev = yaml.safe_load((V15B / "eval_config.yaml").read_text())["evaluation"]
    assert ev == {"timeout_seconds": 60, "max_tool_calls": 40, "max_time_minutes": 5, "max_turns": 150}, ev
    assert 120 * ev["max_time_minutes"] <= 600


def test_validator_passes_for_v15b():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(V15B)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "'temperature': 0.2" in r.stdout and "edit_file" not in r.stdout.split("tools=")[1].split("]")[0]
