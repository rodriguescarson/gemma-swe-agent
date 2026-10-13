"""v12-b1024 = v12 with a thinking budget of 1,024 instead of 4,096 (docs/GAPS_2026-10-06.md, "sub15b pre-registration",
2026-10-13). Why: v12 hit the 5-minute cap on 21 of 50 box tasks, 251 of 468 in the collection pass and 55 of 150 adapter items
in P12; every call spends up to 4,096 reasoning tokens. One change: thinking_budget 4096 -> 1024 in configs/sampling.yaml.
max_output_tokens stays 8192 (one variable). Everything else is byte-identical to v12, the 0.15 submission.
Written before the bundle was built."""
import filecmp, os, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "tests"))
import swe_compat  # noqa: E402

SRC, DST = ROOT / "submissions" / "v12", ROOT / "submissions" / "v12-b1024"
NEW_STACK = not swe_compat.stack()["old_helpers"]


def all_files(d):
    return {str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file()}


def test_differs_from_v12_only_in_the_thinking_budget():
    assert all_files(DST) == all_files(SRC)
    for rel in sorted(all_files(SRC)):
        same = filecmp.cmp(SRC / rel, DST / rel, shallow=False)
        assert same == (rel != "configs/sampling.yaml"), rel
        assert os.stat(SRC / rel).st_mode == os.stat(DST / rel).st_mode, rel
    src, dst = (SRC / "configs" / "sampling.yaml").read_text(), (DST / "configs" / "sampling.yaml").read_text()
    assert dst == src.replace("thinking_budget: 4096", "thinking_budget: 1024") and dst != src
    assert "max_output_tokens: 8192" in dst and "include_thoughts: true" in dst and "temperature: 1.0" in dst


@pytest.mark.skipif(not NEW_STACK, reason="needs adk_submission 0.2.13 in the venv")
def test_the_agent_is_sent_thinking_on_with_the_smaller_budget():
    from test_make_t0 import thinking_of
    assert set(thinking_of(DST).values()) == {(True, 1024, None)}
    assert set(thinking_of(SRC).values()) == {(True, 4096, None)}


def test_validator_passes():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(DST)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "'thinking_budget': 1024" in r.stdout and "'max_output_tokens': 8192" in r.stdout and "'include_thoughts': True" in r.stdout
