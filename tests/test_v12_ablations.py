"""One-variable ablations from v12 toward the public LB-0.24 bundle (GAPS 'v12 ablations pre-registration', 2026-10-16,
pinned before any ablation row exists): v12a = v12 + pub024's eval_config.yaml (240 s / 28 calls / 8 min / 80 turns);
v12b = v12 + pub024's configs/sampling.yaml (temperature 0.2, top_p 0.95, max_output_tokens 8192, thinking 4096 with thoughts,
no top_k, no seed); v12c = v12 + pub024's eval_config.yaml + pub024's prompts/system.md (the prompt names the 28-call / 8-min
limits, so it travels with them; its marginal effect is read against v12a). Every other file byte-identical to v12; the
replaced files byte-identical to pub024's; scripts/validate.py passes with v12's six tools."""
import filecmp, os, subprocess, sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
V12 = ROOT / "submissions" / "v12"
PUB = ROOT / "submissions" / "pub024"
ABLATIONS = {
    "v12a": ("eval_config.yaml",),
    "v12b": ("configs/sampling.yaml",),
    "v12c": ("eval_config.yaml", "prompts/system.md"),
}
REPLACED = {rel for rels in ABLATIONS.values() for rel in rels}


def all_files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())


def test_each_ablation_is_v12_plus_exactly_its_pub024_files():
    for name, rels in ABLATIONS.items():
        b = ROOT / "submissions" / name
        assert all_files(b) == all_files(V12), name
        for rel in all_files(V12):
            same_as_v12 = filecmp.cmp(V12 / rel, b / rel, shallow=False)
            assert same_as_v12 == (rel not in rels), (name, rel)
            assert os.stat(V12 / rel).st_mode == os.stat(b / rel).st_mode, (name, rel)
        for rel in rels:
            assert filecmp.cmp(PUB / rel, b / rel, shallow=False), (name, rel)


def test_the_replaced_files_really_differ_between_v12_and_pub024():
    for rel in REPLACED:
        assert not filecmp.cmp(V12 / rel, PUB / rel, shallow=False), rel


def test_validator_passes_for_each_ablation():
    for name, rels in ABLATIONS.items():
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(ROOT / "submissions" / name)],
                           capture_output=True, text=True, timeout=180)
        assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, (name, r.stdout[-500:] + r.stderr[-1500:])
        assert "tools=['run_command', 'read_file', 'edit_file', 'write_file', 'get_status', 'submit_patch']" in r.stdout, name
        assert "'thinking_budget': 4096" in r.stdout, name
        assert ("'temperature': 0.2" in r.stdout) == ("configs/sampling.yaml" in rels), name
        ev = yaml.safe_load((ROOT / "submissions" / name / "eval_config.yaml").read_text())["evaluation"]
        pub = {"timeout_seconds": 240, "max_tool_calls": 28, "max_time_minutes": 8, "max_turns": 80}
        v12 = {"timeout_seconds": 180, "max_tool_calls": 40, "max_time_minutes": 5, "max_turns": 150}
        assert ev == (pub if "eval_config.yaml" in rels else v12), (name, ev)
