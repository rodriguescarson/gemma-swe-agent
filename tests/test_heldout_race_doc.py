"""The heldout1k README one-liner (race bundles on harness_s200 with or_race.sh) runs as written under DRY_RUN=1, and
pod_probe.sh accepts a prepacked harness dir (PROBE_HARNESS) for the gold pre-flight, also checked with DRY_RUN=1."""
import os
import re
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "data" / "heldout1k" / "README.md"


def readme_race_line():
    m = re.search(r"^\s*(HARNESS=data/heldout1k/harness_s200 .*scripts/pallets/or_race\.sh .*)$", README.read_text(),
                  re.M)
    assert m, "README.md must hold the or_race.sh one-liner for harness_s200"
    return m.group(1).strip()


def test_readme_race_one_liner_plans_the_s200_harness(tmp_path):
    line = readme_race_line()
    words = shlex.split(line)
    env = {**os.environ, "DRY_RUN": "1", "RACE_OUT": str(tmp_path / "out")}
    i = 0
    while "=" in words[i] and not words[i].startswith(("scripts/", "./")):
        k, _, v = words[i].partition("=")
        env[k] = v
        i += 1
    r = subprocess.run(["bash", *words[i:]], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "harness=data/heldout1k/harness_s200\n" in r.stdout
    assert "ids=data/heldout1k/harness_s200/ids.txt\n" in r.stdout
    arms = [w for w in words[i + 1:]]
    assert arms and all(f"arm {a} port" in r.stdout for a in arms)
    assert not (tmp_path / "out").exists()                              # a dry run starts nothing


def probe_plan(tmp_path, **env):
    e = {**os.environ, "DRY_RUN": "1", "PROBE_OUT": str(tmp_path / "probe"), **env}
    ids = tmp_path / "ids.txt"
    ids.write_text("a_1\nb_2\n")
    r = subprocess.run(["bash", str(ROOT / "scripts" / "pallets" / "pod_probe.sh"), str(ids)], cwd=ROOT, env=e,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_pod_probe_default_still_packs_pallets(tmp_path):
    out = probe_plan(tmp_path)
    assert "harness=pack.py --venv default\n" in out and "runs=stock fix\n" in out and "conc=2\n" in out
    assert "no_editable=0\n" in out
    assert not (tmp_path / "probe").exists()


def test_pod_probe_prepacked_harness(tmp_path):
    out = probe_plan(tmp_path, PROBE_HARNESS="data/heldout1k/harness_s200", PROBE_RUNS="fix", PROBE_CONC="4",
                     PROBE_NO_EDITABLE="1")
    assert "harness=data/heldout1k/harness_s200\n" in out and "runs=fix\n" in out and "conc=4\n" in out
    assert "no_editable=1\n" in out
