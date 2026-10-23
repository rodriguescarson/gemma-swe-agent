"""v12b_e4b = v12b (hidden 0.17, our best; v12 + pub024's sampling block, 5-minute cap) with ONE change: the declared model
gemma-4-31b-it-qat-w4a16-ct -> gemma-4-e4b-it-qat-w4a16-ct, for the Small Model Development bonus (discussion 751104: the
best final submission whose base model is Gemma E2B or E4B; it counts only if it is one of the team's two final picks).
The model ids are the four the organisers list in discussion 748287 (read 23 Oct 2026); every agent in a bundle must use the
same variant, and the smaller variants are scored on the same 4xL4, 12-hour limit and per-task budgets as the 31B.
Neither thread gives the small models different thinking or sampling settings, so the prompt, the sampling block (temperature
0.2, thinking budget 4096) and eval_config stay byte-identical to v12b: one variable. Pinned before any v12b_e4b row exists."""
import filecmp, os, shutil, subprocess, sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import swe_compat  # noqa: E402

V12B = ROOT / "submissions" / "v12b"
E4B = ROOT / "submissions" / "v12b_e4b"
OLD, NEW = "gemma-4-31b-it-qat-w4a16-ct", "gemma-4-e4b-it-qat-w4a16-ct"


def all_files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())


def test_the_allowed_models_are_the_organisers_four():
    assert swe_compat.ALLOWED_MODELS == ("gemma-4-31b-it-qat-w4a16-ct", "gemma-4-12b-it-qat-w4a16-ct",
                                         "gemma-4-e4b-it-qat-w4a16-ct", "gemma-4-e2b-it-qat-w4a16-ct")


def test_only_the_model_line_differs_from_v12b():
    assert all_files(E4B) == all_files(V12B)
    for rel in all_files(V12B):
        assert filecmp.cmp(V12B / rel, E4B / rel, shallow=False) == (rel != "agent.yaml"), rel
        assert os.stat(V12B / rel).st_mode == os.stat(E4B / rel).st_mode, rel
    old = (V12B / "agent.yaml").read_text()
    assert old.count(OLD) == 1 and f"model: {OLD}\n" in old
    assert (E4B / "agent.yaml").read_text() == old.replace(f"model: {OLD}\n", f"model: {NEW}\n")
    a, b = yaml.safe_load(old.replace("!include", "")), yaml.safe_load((E4B / "agent.yaml").read_text().replace("!include", ""))
    assert {**a, "model": NEW} == b


def test_the_declared_model_is_e4b_on_both_paths():
    assert swe_compat.declared_model(E4B) == NEW
    assert swe_compat.declared_model(E4B, force_new=True) == NEW


def test_thinking_sampling_and_budgets_are_v12bs():
    s = yaml.safe_load((E4B / "configs" / "sampling.yaml").read_text())
    assert s == {"temperature": 0.2, "top_p": 0.95, "max_output_tokens": 8192,
                 "thinking_config": {"thinking_budget": 4096, "include_thoughts": True}}
    ev = yaml.safe_load((E4B / "eval_config.yaml").read_text())["evaluation"]
    assert ev == {"timeout_seconds": 180, "max_tool_calls": 40, "max_time_minutes": 5, "max_turns": 150}


def test_validator_passes_for_v12b_e4b():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(E4B)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0 and f"OK model={NEW}" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "'temperature': 0.2" in r.stdout and "'thinking_budget': 4096" in r.stdout


def test_the_sub24_chain_refuses_without_the_owners_approval():
    """eval/arm_sub24_e4b.sh is prepared, not run: every Kaggle submission is Carson's call, so the chain exits before it
    touches the checkout, ships or submits unless CARSON_APPROVED_SUB24=yes."""
    chain = ROOT / "eval" / "arm_sub24_e4b.sh"
    assert subprocess.run(["bash", "-n", str(chain)]).returncode == 0
    env = {k: v for k, v in os.environ.items() if k != "CARSON_APPROVED_SUB24"}
    for val in (None, "1", "true", "YES"):
        e = env if val is None else {**env, "CARSON_APPROVED_SUB24": val}
        r = subprocess.run(["bash", str(chain)], capture_output=True, text=True, env=e, cwd=ROOT, timeout=30)
        assert r.returncode == 2 and "not approved" in r.stderr, (val, r.stdout, r.stderr)
    src = chain.read_text()
    first = next(i for i, l in enumerate(src.splitlines()) if l.strip() and not l.startswith("#"))
    assert src.splitlines()[first].startswith('[ "${CARSON_APPROVED_SUB24:-}" = yes ]')   # the guard is the first command
    assert 'B=v12b_e4b; SLUG=g4agent-v12b-e4b; TAG="sub24:"' in src and "scripts/ship.sh" in src and "scripts/submit_at.sh" in src


def test_validator_still_refuses_a_model_the_organisers_do_not_list(tmp_path):
    b = tmp_path / "other"
    shutil.copytree(V12B, b, ignore=shutil.ignore_patterns("__pycache__"))
    y = b / "agent.yaml"
    y.write_text(y.read_text().replace(f"model: {OLD}", "model: gemma-4-27b-it"))
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(b)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode != 0 and "OK model=" not in r.stdout and "gemma-4-27b-it" in r.stderr, r.stdout[-500:] + r.stderr[-800:]
