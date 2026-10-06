import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
"""scripts/a6000/run_eval.py: the kernel's run cell (scripts/make_eval_kernel.py CELL_RUN) against a local vLLM.
Written before the script. The pure parts are tested here; the Evaluator itself is exercised by P1's real run."""
import importlib.util, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
P = ROOT / "scripts" / "a6000" / "run_eval.py"


def _load():
    spec = importlib.util.spec_from_file_location("a6000_run_eval", P)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_first_ids_keeps_file_order_and_skips_blanks(tmp_path):
    f = tmp_path / "ids.txt"; f.write_text("a\n\nb\n  c  \nd\n")
    assert _load().first_ids(str(f), 3) == ["a", "b", "c"]
    assert _load().first_ids(str(f), None) == ["a", "b", "c", "d"]


def test_budget_comes_from_the_bundle_like_the_kernel(tmp_path):
    (tmp_path / "eval_config.yaml").write_text("evaluation:\n  timeout_seconds: 180\n  max_tool_calls: 70\n  max_time_minutes: 5\n  max_turns: 150\n")
    assert _load().budget_for(str(tmp_path)) == dict(max_time_minutes=5.0, max_tool_calls=70, max_turns=150, timeout_seconds=180)


def test_kernel_settings_are_the_same_constants():
    m = _load()
    import make_eval_kernel as k
    assert m.COMPACTION == k.COMPACTION and m.CONTEXT_CACHE == k.CONTEXT_CACHE


def test_uses_subprocess_sandbox_and_no_docker():
    t = P.read_text()
    assert "sandbox='subprocess'" in t.replace('"', "'") and "docker" not in t.lower()


def test_result_row_has_the_kernels_fields():
    row = _load().result_row(None, "t1", True, 0, 12, 3.14159, None, "diff")
    assert list(row) == ["cfg", "id", "resolved", "exit", "calls", "secs", "err", "patch"] and row["secs"] == 3.1
