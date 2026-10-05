"""or_race.sh plan (DRY_RUN=1): harness dir is selectable (holdout pack), arms are 1..N with one proxy port each."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "pallets" / "or_race.sh"


def plan(tmp_path, *arms, **env):
    e = {**os.environ, "DRY_RUN": "1", "RACE_OUT": str(tmp_path / "out"), **env}
    r = subprocess.run(["bash", str(SCRIPT), *arms], cwd=ROOT, env=e, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_default_harness_and_two_arms(tmp_path):
    out = plan(tmp_path, "v4h2", "v4h2g")
    assert "harness=data/pallets/harness\n" in out
    assert "arm v4h2 port 8790" in out and "arm v4h2g port 8791" in out


def test_harness_override(tmp_path):
    out = plan(tmp_path, "v4h2", "v4h2g", HARNESS="data/pallets/harness_holdout")
    assert "harness=data/pallets/harness_holdout\n" in out


def test_single_arm(tmp_path):
    out = plan(tmp_path, "v4")
    assert "arm v4 port 8790" in out and "8791" not in out


def test_three_arms(tmp_path):
    out = plan(tmp_path, "v4", "v4h2", "v4h2g")
    assert "arm v4h2g port 8792" in out


def test_dry_run_starts_nothing(tmp_path):
    plan(tmp_path, "v4h2", "v4h2g")
    assert not list((tmp_path / "out").glob("proxy_*"))
