"""scripts/a6000/backup_results.py: copy the run's result files into the repo and push them, so a crash loses at most one interval. Written before the code."""
import importlib.util, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("backup_results", ROOT / "scripts" / "a6000" / "backup_results.py")
bk = importlib.util.module_from_spec(spec); spec.loader.exec_module(bk)


def mk(p, text="x"):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text); return p


def test_p2_items_copy_rows_patches_tests_and_traces_but_not_logs(tmp_path):
    src, dst = tmp_path / "runs", tmp_path / "repo"
    base = src / "p2" / "items" / "v6p" / "t1"
    for rel in ("task_results.jsonl", "summary.json", "patches/t1.diff", "test_outputs/t1.txt", "traces/trace_t1.json", "logs/x.log"):
        mk(base / rel)
    mk(src / "p2" / "items.jsonl"); mk(src / "p2" / "proxy_stage1a.jsonl"); mk(src / "p2" / "probe_summary.json")
    rels = {str(d.relative_to(dst)) for s, d in bk.plan(str(src), str(dst))}
    assert "p2/items/v6p/t1/task_results.jsonl" in rels and "p2/items/v6p/t1/patches/t1.diff" in rels and "p2/items/v6p/t1/traces/trace_t1.json" in rels
    assert "p2/items/v6p/t1/test_outputs/t1.txt" in rels and "p2/items.jsonl" in rels and "p2/proxy_stage1a.jsonl" in rels and "p2/probe_summary.json" in rels
    assert not any("/logs/" in r for r in rels)


def test_p3_keeps_rows_and_patches_but_never_traces_capture_or_sft_rows(tmp_path):
    src, dst = tmp_path / "runs", tmp_path / "repo"
    base = src / "p3" / "items" / "v6p" / "t1"
    for rel in ("task_results.jsonl", "patches/t1.diff", "traces/trace_t1.json"):
        mk(base / rel)
    for big in ("capture.jsonl", "rows.jsonl", "rows_rebalanced.jsonl", "results_all.jsonl"):
        mk(src / "p3" / big)
    mk(src / "p3" / "rebalance_report.json"); mk(src / "p3" / "validate_report.json"); mk(src / "p3" / "ARM")
    rels = {str(d.relative_to(dst)) for s, d in bk.plan(str(src), str(dst))}
    assert "p3/items/v6p/t1/task_results.jsonl" in rels and "p3/rebalance_report.json" in rels and "p3/validate_report.json" in rels and "p3/ARM" in rels
    assert not any(r.endswith(("capture.jsonl", "rows.jsonl", "rows_rebalanced.jsonl")) or "/traces/" in r for r in rels)


def test_p4_results_and_traces(tmp_path):
    src, dst = tmp_path / "runs", tmp_path / "repo"
    mk(src / "p4" / "results.jsonl"); mk(src / "p4" / "ARM"); mk(src / "p4" / "results" / "traces" / "trace_a.json"); mk(src / "p4_proxy.jsonl")
    rels = {str(d.relative_to(dst)) for s, d in bk.plan(str(src), str(dst))}
    assert {"p4/results.jsonl", "p4/ARM", "p4/results/traces/trace_a.json", "p4_proxy.jsonl"} <= rels


def test_only_new_or_changed_files_are_planned_and_huge_files_skipped(tmp_path):
    src, dst = tmp_path / "runs", tmp_path / "repo"
    f = mk(src / "p2" / "items.jsonl", "a")
    assert len(bk.plan(str(src), str(dst))) == 1
    bk.copy(bk.plan(str(src), str(dst)))
    assert bk.plan(str(src), str(dst)) == []
    f.write_text("ab")                                     # changed size
    assert len(bk.plan(str(src), str(dst))) == 1
    mk(src / "p2" / "proxy_big.jsonl", "x" * 200)
    assert all("proxy_big" not in str(d) for s, d in bk.plan(str(src), str(dst), max_bytes=100))


def test_probe_gate_result_is_backed_up(tmp_path):
    src, dst = tmp_path / "runs", tmp_path / "repo"
    mk(src / "p2" / "probe_gate.json")
    assert "p2/probe_gate.json" in {str(d.relative_to(dst)) for s, d in bk.plan(str(src), str(dst))}
