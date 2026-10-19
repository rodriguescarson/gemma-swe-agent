"""v12b6 = v12b (hidden 0.17, our best; v12 + pub024's sampling block) with ONE change: max_time_minutes 5 -> 6. The prompt
still says "about 5 minutes and 40 tool calls", on purpose: the agent keeps pacing itself for five minutes, and the extra
minute only lets the runs still working at the five-minute mark finish (the deadline curve: solves arrive late; v12 had 7 of
27 solves in the last 30 s and 4 still running at the cap). One variable, aimed at that mechanism.
The 10-hour worst-case gate (120 x cap <= 10 h) is deliberately NOT met (120 x 6 min = 12 h): the owner chose on 19 Oct to
replace it, for this bundle, with a mean-based gate read on the box, mean seconds per task <= 280 (120 x 280 s = 9.3 h; pub024
failed the 12-hour limit twice at a box mean of 346 s = 11.5 h). Pinned before any v12b6 row exists."""
import filecmp, os, subprocess, sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
V12B = ROOT / "submissions" / "v12b"
V12B6 = ROOT / "submissions" / "v12b6"
MEAN_GATE_S = 280


def all_files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())


def test_only_the_time_cap_differs_from_v12b():
    assert all_files(V12B6) == all_files(V12B)
    for rel in all_files(V12B):
        assert filecmp.cmp(V12B / rel, V12B6 / rel, shallow=False) == (rel != "eval_config.yaml"), rel
        assert os.stat(V12B / rel).st_mode == os.stat(V12B6 / rel).st_mode, rel
    old = yaml.safe_load((V12B / "eval_config.yaml").read_text())["evaluation"]
    new = yaml.safe_load((V12B6 / "eval_config.yaml").read_text())["evaluation"]
    assert new == {**old, "max_time_minutes": 6}, new
    assert (V12B6 / "eval_config.yaml").read_text() == (V12B / "eval_config.yaml").read_text().replace(
        "max_time_minutes: 5", "max_time_minutes: 6")


def test_the_prompt_still_paces_for_five_minutes():
    p = (V12B6 / "prompts" / "system.md").read_text()
    assert "about 5 minutes and 40 tool calls" in p and "6 minutes" not in p


def test_the_runtime_gate_is_the_mean_based_one():
    ev = yaml.safe_load((V12B6 / "eval_config.yaml").read_text())["evaluation"]
    assert 120 * ev["max_time_minutes"] > 600                      # the worst-case gate is knowingly not met
    assert 120 * MEAN_GATE_S / 3600 < 9.4                          # the gate it ships under (box mean, GAPS)


def test_validator_passes_for_v12b6():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(V12B6)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "'temperature': 0.2" in r.stdout and "'thinking_budget': 4096" in r.stdout
