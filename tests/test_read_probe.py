"""scripts/read_probe.py: map the G-A probe's lora_probe.json to a verdict and the packager's --key-style, and append
the result block to docs/v11/GA_PROBE.md once. Written before the script."""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "read_probe.py"


def _run(tmp, probe, doc_text="# G-A\n\nResult (appended after the run, never edited above this line):\n"):
    p = tmp / "lora_probe.json"; p.write_text(json.dumps(probe))
    doc = tmp / "GA_PROBE.md"; doc.write_text(doc_text)
    r = subprocess.run([sys.executable, str(SCRIPT), str(p), "--doc", str(doc)], capture_output=True, text=True, timeout=60)
    return r, doc.read_text()


def _probe(prefix, ga="PASS", p6=True):
    return {"checks": {"P1_applied": prefix != "none", "P2_zero_b_harmless": True, "P5_long_ctx_returns": True},
            "prefix": prefix, "GA_pre_smoke": ga, "P6_agent_smoke": p6, "GA": ga,
            "A": {"loud": {"diff_vs_base": 20 if prefix == "plan_A" else 0}, "loud2": {"diff_vs_base": 20 if prefix == "loud2" else 0}}}


def test_pass_plan_a_maps_to_loud(tmp_path):
    r, doc = _run(tmp_path, _probe("plan_A"))
    assert r.returncode == 0 and "KEY_STYLE=loud" in r.stdout and "GA=PASS" in r.stdout
    assert "G-A PASS" in doc and "--key-style loud" in doc


def test_pass_loud2_maps_to_loud2(tmp_path):
    r, doc = _run(tmp_path, _probe("loud2"))
    assert r.returncode == 0 and "KEY_STYLE=loud2" in r.stdout and "--key-style loud2" in doc


def test_fail_closes_the_track_and_exit_2(tmp_path):
    r, doc = _run(tmp_path, _probe("none", ga="FAIL", p6=False))
    assert r.returncode == 2 and "KEY_STYLE=none" in r.stdout and "LoRA track closed" in doc


def test_result_is_appended_once(tmp_path):
    r1, doc1 = _run(tmp_path, _probe("plan_A"))
    p = tmp_path / "lora_probe.json"; doc = tmp_path / "GA_PROBE.md"
    r2 = subprocess.run([sys.executable, str(SCRIPT), str(p), "--doc", str(doc)], capture_output=True, text=True, timeout=60)
    assert r2.returncode == 0 and doc.read_text().count("G-A PASS") == 1 and "already recorded" in r2.stdout
