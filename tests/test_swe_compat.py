"""scripts/swe_compat.py: the declared model and a compile-only registry on both scorer stacks (swegemma 0.2.7, where
the old helpers exist, and 0.2.11 + adk_submission 0.2.13, where they are gone and the declared model comes from
adk_submission.discovery.discover_declared_models). The new path is forced here, so it is tested whichever stack the
venv carries; the kernel template inlines the same code and must agree with it. Written before the code (test-first,
2026-10-10, after the three Saturday kernels died on `No module named 'swegemma.models.discovery'`)."""
import importlib.util, re, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import swe_compat  # noqa: E402

BUNDLES = ["v7d", "v7c", "v5h2", "v4h2g_v11b_probe"]
DECLARED = "gemma-4-31b-it-qat-w4a16-ct"


@pytest.mark.parametrize("b", BUNDLES)
def test_the_declared_model_is_the_same_on_both_paths(b):
    d = ROOT / "submissions" / b
    assert swe_compat.declared_model(d) == DECLARED
    assert swe_compat.declared_model(d, force_new=True) == DECLARED


def test_a_bundle_with_two_models_is_refused_on_the_new_path(tmp_path):
    import shutil
    b = tmp_path / "two"
    shutil.copytree(ROOT / "submissions" / "v7d", b, ignore=shutil.ignore_patterns("__pycache__"))
    y = b / "sub_agents" / "fixer.yaml"
    y.write_text(y.read_text().replace("model: gemma-4-31b-it-qat-w4a16-ct", "model: gemma-4-other"))
    with pytest.raises(ValueError, match="exactly one declared model"):
        swe_compat.declared_model(b, force_new=True)


def test_the_compile_only_registry_holds_litellm_clients_on_both_paths():
    from google.adk.models.lite_llm import LiteLlm
    for force in (False, True):
        r = swe_compat.compile_only_model_registry(DECLARED, force_new=force)
        m = r.get(DECLARED)
        assert isinstance(m, LiteLlm) and m.model.endswith(DECLARED), (force, m)
    new = swe_compat.compile_only_model_registry("openai/" + DECLARED, force_new=True)
    assert new.get(DECLARED).model == new.get("openai/" + DECLARED).model == "openai/" + DECLARED


@pytest.mark.parametrize("b", BUNDLES)
def test_the_official_compiler_builds_every_queued_bundle_with_the_new_path_registry(b):
    from unittest.mock import MagicMock
    from adk_submission import compile_submission, discover_adapters
    from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS, build_submission_limits
    from swegemma.tools import create_tools
    d = ROOT / "submissions" / b
    limits, gen = build_submission_limits()
    declared = swe_compat.declared_model(d, force_new=True)
    agent = compile_submission(submission_dir=str(d), adapter_manifest=discover_adapters(str(d), adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS),
                               tool_registry=create_tools(MagicMock()), model_registry=swe_compat.compile_only_model_registry(declared, force_new=True),
                               limits=limits, generation_constraints=gen)
    names = [a.name for a in getattr(agent, "sub_agents", [])]
    expected = {"v7d": ["setup", "locator", "fixer", "verifier"], "v7c": ["setup", "locator", "fixer", "verifier"],
                "v5h2": ["setup", "locator", "fixer", "verifier"], "v4h2g_v11b_probe": ["locator", "fixer", "verifier"]}
    assert names == expected[b], names


def test_validate_py_runs_on_the_current_stack():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(ROOT / "submissions" / "v7d")], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]


def test_the_kernel_template_inlines_the_same_fallbacks():
    """The notebook cannot import scripts/: make_eval_kernel.py carries the two fallbacks as text, and they must name the
    same new-stack functions as swe_compat and never the deleted modules outside a try."""
    spec = importlib.util.spec_from_file_location("mk", ROOT / "scripts" / "make_eval_kernel.py")
    mk = importlib.util.module_from_spec(spec); spec.loader.exec_module(mk)
    for cell in (mk.CELL_VLLM, mk.CELL_RUN):
        for line in cell.splitlines():
            if "swegemma.models.discovery" in line or "setup_gemma_model_registry" in line:
                assert line.lstrip().startswith("from ") and line.startswith("    "), line   # only inside a try block
    assert "discover_declared_models" in mk.CELL_VLLM and "except ImportError" in mk.CELL_VLLM
    assert "ModelRegistry()" in mk.CELL_RUN and "except ImportError" in mk.CELL_RUN
    src = (ROOT / "scripts" / "make_eval_kernel.py").read_text()
    assert "validate_single_declared_model(AGENT_DIR)" not in src and "models or setup_gemma_model_registry()" not in src


def test_the_inlined_fallback_runs_as_the_kernel_would(monkeypatch):
    """Execute the declared-model and registry parts of the two cells with the old modules hidden (None in sys.modules
    makes their import raise ImportError; monkeypatch restores sys.modules so later tests see the real stack)."""
    from google.adk.models.lite_llm import LiteLlm
    spec = importlib.util.spec_from_file_location("mk2", ROOT / "scripts" / "make_eval_kernel.py")
    mk = importlib.util.module_from_spec(spec); spec.loader.exec_module(mk)
    monkeypatch.setitem(sys.modules, "swegemma.models.discovery", None)
    head = mk.CELL_VLLM.split("adapters = discover_adapters(")[0]
    ns = {"AGENT_DIR": ROOT / "submissions" / "v7d"}
    exec(compile(head, "CELL_VLLM-head", "exec"), ns)
    assert ns["declared"] == DECLARED
    reg_src = mk.CELL_RUN.split("def run_sync(")[0]
    monkeypatch.setitem(sys.modules, "swegemma.models", None)
    ns2 = {"declared": DECLARED}
    exec(compile(reg_src, "CELL_RUN-head", "exec"), ns2)
    m = ns2["_fallback_registry"]().get(DECLARED)
    assert isinstance(m, LiteLlm) and m.model == "openai/" + DECLARED
