"""train/probe_reverdict.py: the probe's verdict re-derived from its report under the current rules (2026-10-12: the box's
probe ran on the old tok/s average while the thrash rule was pre-registered; its raw numbers stand, its verdict does not)."""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from train.probe_reverdict import reverdict  # noqa: E402


def box_report(losses=None):
    """The shape of ~/g4/runs/train_think1/probe/probe_report.json with the box's 2026-10-12 readings."""
    step = lambda tok, s, peak: {"tokens": tok, "s": s, "tok_s": round(tok / s), "loss": 0.3, "grad_norm": 2.0, "peak_reserved_gb": peak}  # noqa: E731
    buckets = [{"range": [0, 5000], "oom": False, "steps": [step(4500, 30.0, 28.0)] * 5},
               {"range": [5000, 9000], "oom": False, "steps": [step(8500, 65.4, 34.38)] * 5},
               {"range": [9000, 13000], "oom": False, "steps": [step(12500, 122.5, 41.37)] * 5},
               {"range": [13000, 10 ** 9], "oom": False, "steps": [step(15844, 194.82, 46.53), step(15844, 2459.65, 47.8), step(15844, 2508.48, 47.8),
                                                                    step(15844, 2487.16, 47.8), step(15844, 2493.75, 47.8)]}]
    losses = losses if losses is not None else [0.47, 0.45] + [0.4] * 20 + [0.3, 0.28]
    return {"verdict": "FALLBACK", "reasons": ["21 tok/s < 100"], "tok_s": 21.0, "buckets": buckets, "repeat_losses": losses,
            "grad_norms": [3.27, 2.0, 1.5] + [1.0] * 21, "forward2k": {"tokens": 2600, "supervised": 64, "max_abs_logit": 29.9, "base_nll": 0.81},
            "peak_gb_at_12k": 41.37, "oom_at_16k": False, "max_tokens": 16384}


def test_old_fallback_becomes_reduced_once_the_thrashing_bucket_is_excluded():
    out = reverdict(box_report())
    assert out["old_verdict"] == "FALLBACK" and out["verdict"] == "REDUCED"
    assert out["excluded_buckets"] == [[13000, 10 ** 9]] and out["thrash_at_16k"] is True and out["cap_tokens"] == 12288
    assert 100 <= out["tok_s"] < 150 and out["peak_gb_at_12k"] == 41.37
    assert any("thrashed" in r for r in out["reasons"]) and any("cap 12,288" in r for r in out["reasons"])
    assert out["loss_first"] == 0.46 and out["loss_last"] == 0.29


def test_other_checks_still_fail_it():
    out = reverdict(box_report(losses=[0.4] * 24))                       # the loss did not fall
    assert out["verdict"] == "FALLBACK" and any("loss fell" in r for r in out["reasons"])
    rep = box_report(); rep["forward2k"]["base_nll"] = 2.4
    assert reverdict(rep)["verdict"] == "FALLBACK"
    rep = box_report(); rep["buckets"][2]["steps"][0]["peak_reserved_gb"] = 45.0
    assert reverdict(rep)["verdict"] == "FALLBACK"


def test_cli_writes_next_to_the_report_and_exits_by_verdict(tmp_path):
    r = tmp_path / "probe_report.json"; r.write_text(json.dumps(box_report()))
    p = subprocess.run([sys.executable, str(ROOT / "train" / "probe_reverdict.py"), str(r), "--write"], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-500:]
    out = json.loads((tmp_path / "probe_reverdict.json").read_text()); assert out["verdict"] == "REDUCED" and out["old_verdict"] == "FALLBACK"
    r.write_text(json.dumps(box_report(losses=[0.4] * 24)))
    assert subprocess.run([sys.executable, str(ROOT / "train" / "probe_reverdict.py"), str(r)], capture_output=True, text=True).returncode == 3
