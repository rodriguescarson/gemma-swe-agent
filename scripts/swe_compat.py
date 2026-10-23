"""One face over the two scorer stacks (docs/a6000/V7C_FAILURE_ANALYSIS.md, section 8).

The Kaggle wheelhouse (metric/gemma-4-developer-agent-wheelhouse) moved on 2026-10-09 14:43 UTC from swegemma 0.2.7 +
adk_submission 0.2.12 to swegemma 0.2.11 + adk_submission 0.2.13. swegemma 0.2.11 deleted swegemma/models/discovery.py
(validate_single_declared_model) and swegemma/models/registry.py (setup_gemma_model_registry); the harness now reads the
declared model through adk_submission.discovery.discover_declared_models and builds its model registry from the vLLM
server (VllmServer.create_model_registry). The three Saturday kernels (v7c, v5h2, the v11b probe) died on the first
import two minutes in, and the organisers' own Getting Started notebook (last run 2026-10-01) carries the same import.

Both functions below take the old path when it exists (the A6000 box's venv is still 0.2.7) and the new one otherwise.
scripts/make_eval_kernel.py inlines the same logic into the notebook cells (COMPAT_DECLARED, COMPAT_REGISTRY), since a
kernel cannot import this file; tests/test_swe_compat.py keeps the two copies in step."""
from pathlib import Path

# The models a bundle may declare: the four the organisers list in discussion 748287 (read 2026-10-23; 12B, E4B and E2B
# added beside the 31B). One variant per bundle; the small ones are scored on the same 4xL4, 12 h and per-task budgets.
ALLOWED_MODELS = ("gemma-4-31b-it-qat-w4a16-ct", "gemma-4-12b-it-qat-w4a16-ct",
                  "gemma-4-e4b-it-qat-w4a16-ct", "gemma-4-e2b-it-qat-w4a16-ct")


def declared_model(submission_dir, force_new=False):
    """The one model a bundle declares (its sub_agents' `model:`), e.g. 'gemma-4-31b-it-qat-w4a16-ct'."""
    if not force_new:
        try:
            from swegemma.models.discovery import validate_single_declared_model
            return validate_single_declared_model(str(submission_dir))
        except ImportError:
            pass
    from adk_submission.discovery import discover_declared_models
    found = sorted(discover_declared_models(str(submission_dir)))
    if len(found) != 1:
        raise ValueError("expected exactly one declared model in %s, found %r" % (submission_dir, found))
    return found[0]


def compile_only_model_registry(declared, force_new=False):
    """A ModelRegistry that lets compile_submission resolve the declared model with no server behind it (validate.py,
    the bundle tests, the oracle kernels): the old helper when it exists, else the bare name mapped to its vLLM id."""
    if not force_new:
        try:
            from swegemma.models import setup_gemma_model_registry
            return setup_gemma_model_registry()
        except ImportError:
            pass
    from adk_submission import ModelRegistry
    from google.adk.models.lite_llm import LiteLlm
    base = str(declared).split("/")[-1]
    registry = ModelRegistry()
    for name in dict.fromkeys([str(declared), base, "openai/" + base]):   # LiteLlm clients, as both stacks' registries hold
        registry.register(name, LiteLlm(model="openai/" + base, api_base="http://127.0.0.1:8000/v1", api_key="EMPTY", num_retries=5))
    return registry


def stack():
    """-> {'swegemma': version, 'adk_submission': version, 'old_helpers': bool} for logs and reports."""
    from importlib.metadata import version
    try:
        import swegemma.models.discovery  # noqa: F401
        old = True
    except ImportError:
        old = False
    return {"swegemma": version("swegemma"), "adk_submission": version("adk_submission"), "old_helpers": old}


if __name__ == "__main__":
    import sys
    print(stack())
    for d in sys.argv[1:]:
        print(d, "->", declared_model(Path(d)))
