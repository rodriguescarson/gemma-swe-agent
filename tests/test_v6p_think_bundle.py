"""v6p-think (docs/GAPS_2026-10-06.md S4 REOPENED, Carson 2026-10-06): v6p with thinking ON and no thinking_budget.

How thinking reaches the server (adk_submission/resolvers/generation.py apply_thinking_config_to_model): only
thinking_config.include_thoughts / thinking_level are forwarded, as extra_body.chat_template_kwargs.enable_thinking
(+ reasoning_effort for a low/medium/high level). v5h2/v6p switch it off with `include_thoughts: false`; the twin flips
exactly that line to `true` in every sampling file. No thinking_budget may appear in the bundle (forum 745059: setting
one fails every task). Note: the compiler itself still merges the harness default thinking_budget (4096,
swegemma/config.py) into the compiled config object; generation.py does not forward it and ADK's LiteLlm has no
thinking_budget mapping, so nothing extra reaches vLLM. Written before the bundle."""
import filecmp, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
V6P, THINK = ROOT / "submissions" / "v6p", ROOT / "submissions" / "v6p-think"
KERNEL_DIR, KERNEL_SLUG = "g4-l4-v6p-think-p312", "g4-l4-v9-eog"
TAKEN = {"g4-eval74-v4", "g4-l4-v4", "g4-eval74-v2", "g4-eval74-v3"}   # queued (v5h2, v5h2b, v11b) + v6p


def files(d):
    return {str(p.relative_to(d)) for p in d.rglob("*")
            if p.is_file() and not p.name.startswith(".") and "__pycache__" not in p.parts}


def test_same_files_and_only_the_sampling_configs_differ():
    assert files(THINK) == files(V6P)
    changed = {r for r in files(V6P) if not filecmp.cmp(V6P / r, THINK / r, shallow=False)}
    assert changed == {"configs/sampling.yaml", "configs/sampling_a.yaml", "configs/sampling_b.yaml",
                       "configs/sampling_c.yaml"}, changed


@pytest.mark.parametrize("rel", ["configs/sampling.yaml", "configs/sampling_a.yaml", "configs/sampling_b.yaml",
                                 "configs/sampling_c.yaml"])
def test_the_only_change_is_include_thoughts_true(rel):
    a, b = (V6P / rel).read_text(), (THINK / rel).read_text()
    assert "  include_thoughts: false\n" in a
    assert b == a.replace("  include_thoughts: false\n", "  include_thoughts: true\n")


def test_no_thinking_budget_anywhere():
    for r in files(THINK):
        assert "thinking_budget" not in (THINK / r).read_text(errors="replace"), r


def _enable_thinking(bundle):
    from unittest.mock import MagicMock
    from adk_submission import compile_submission, discover_adapters
    from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS, build_submission_limits
    from swegemma.models import setup_gemma_model_registry
    from swegemma.tools import create_tools
    limits, gen = build_submission_limits()
    root = compile_submission(submission_dir=str(bundle), adapter_manifest=discover_adapters(str(bundle), ALLOWED_ADAPTER_EXTENSIONS),
                              tool_registry=create_tools(MagicMock()), model_registry=setup_gemma_model_registry(),
                              limits=limits, generation_constraints=gen)
    out, stack = {}, [root]
    while stack:
        a = stack.pop()
        stack += list(getattr(a, "sub_agents", []) or [])
        m = getattr(a, "model", None)
        if hasattr(m, "_additional_args"):
            body = (m._additional_args or {}).get("extra_body") or {}
            out[a.name] = ((body.get("chat_template_kwargs") or {}).get("enable_thinking"),
                           (m._additional_args or {}).get("reasoning_effort"))
    return out


def test_compiled_requests_enable_thinking_on_every_llm_stage_and_off_in_v6p():
    on, off = _enable_thinking(THINK), _enable_thinking(V6P)
    stages = {"setup", "locator", "fixer_a", "fixer_b", "fixer_c", "selector", "verifier"}
    assert set(on) == set(off) == stages
    assert all(v == (True, None) for v in on.values()), on                # thinking on, no reasoning_effort level
    assert all(v == (False, None) for v in off.values()), off


def test_validate_py_compiles_the_twin():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(THINK)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0 and "ParallelAgent" in r.stdout, r.stdout[-800:] + r.stderr[-1500:]


def test_eval_kernel_slug_is_free_and_regenerates_identically(tmp_path):
    assert KERNEL_SLUG not in TAKEN
    kd = ROOT / "kernels" / KERNEL_DIR
    if not (kd / "kernel-metadata.json").is_file():
        pytest.skip(f"kernels/{KERNEL_DIR} not present (kernels/*/ is gitignored; generated on the Mac)")
    meta = (kd / "kernel-metadata.json").read_text()
    assert f'"id": "carsonrodrigues/{KERNEL_SLUG}"' in meta and '"docker_image_pinning_type": "original"' in meta
    assert '"machine_shape": "NvidiaL4"' in meta
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_eval_kernel.py"), str(THINK), KERNEL_DIR,
                        "--ids", str(ROOT / "data" / "kaggle_valid_ids.txt"), "--pin", "original",
                        "--kernel-id", KERNEL_SLUG], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    for f in ("kernel-metadata.json", KERNEL_SLUG + ".ipynb"):
        assert (tmp_path / "kernels" / KERNEL_DIR / f).read_bytes() == (kd / f).read_bytes(), f
