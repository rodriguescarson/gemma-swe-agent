"""v0-think = v0 (our 25 Sep copy of the official starter agent) with include_thoughts true instead of false
(docs/GAPS_2026-10-06.md, "sub16 pre-registration", 2026-10-14). Why: the leaderboard's wall of ~40 teams at 0.18 is the
near-starter agent with thinking on (forum 746250: thoughts carried 48-51/129 public, hidden 35/129); our own thinking-on agent
v12 scored 0.15, and the starter has never been read on our side with thoughts carried. One change: include_thoughts false ->
true in configs/sampling.yaml (shared by the root agent and code_analyzer). The 4,096 budget, temperature 0.2 and every prompt
stay as v0. Written before the bundle was built."""
import filecmp, os, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "tests"))
import swe_compat  # noqa: E402

SRC, DST = ROOT / "submissions" / "v0", ROOT / "submissions" / "v0-think"
NEW_STACK = not swe_compat.stack()["old_helpers"]


def all_files(d):
    return {str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file()}


def test_differs_from_v0_only_in_include_thoughts():
    assert all_files(DST) == all_files(SRC)
    for rel in sorted(all_files(SRC)):
        same = filecmp.cmp(SRC / rel, DST / rel, shallow=False)
        assert same == (rel != "configs/sampling.yaml"), rel
        assert os.stat(SRC / rel).st_mode == os.stat(DST / rel).st_mode, rel
    src, dst = (SRC / "configs" / "sampling.yaml").read_text(), (DST / "configs" / "sampling.yaml").read_text()
    assert dst == src.replace("include_thoughts: false", "include_thoughts: true") and dst != src
    assert "thinking_budget: 4096" in dst and "temperature: 0.2" in dst and "max_output_tokens: 8192" in dst


@pytest.mark.skipif(not NEW_STACK, reason="needs adk_submission 0.2.13 in the venv")
def test_the_agent_is_sent_thinking_on_with_the_starter_budget():
    from test_make_t0 import thinking_of
    assert set(thinking_of(DST).values()) == {(True, 4096, None)}


def test_validator_passes():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(DST)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "'include_thoughts': True" in r.stdout and "'thinking_budget': 4096" in r.stdout and "'temperature': 0.2" in r.stdout
    assert "code_analyzer_agent" in r.stdout
