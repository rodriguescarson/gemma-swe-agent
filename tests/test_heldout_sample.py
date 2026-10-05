"""scripts/heldout/sample_ids.py: the stratified heldout1k sample (per-repo cap, every repo present, ~20% title-only,
fixed seed) and scripts/heldout/preflight_summary.py: valid / drop reasons from the pod_probe fix_gold + fix_empty runs."""
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "heldout"))
import preflight_summary as PS  # noqa: E402
import sample_ids as S  # noqa: E402


def pop():
    """a skewed population: 3 big repos, 4 small ones, title-only shares from 0% to 70%."""
    rows = []
    spec = {"a/big1": (120, 0.1), "a/big2": (90, 0.0), "a/big3": (60, 0.7), "b/mid": (25, 0.3), "b/s1": (6, 0.5),
            "b/s2": (2, 0.0), "b/s3": (1, 1.0)}
    for repo, (n, share) in spec.items():
        k = round(n * share)
        for i in range(n):
            rows.append({"instance_id": f"{repo.split('/')[1]}_{i:04d}", "repo": repo,
                         "statement_title_only": i < k})
    return rows


def test_cap_every_repo_and_size():
    ids = S.sample(pop(), n=60, cap=15, title_share=0.2, seed=7)
    rows = {r["instance_id"]: r for r in pop()}
    per = Counter(rows[i]["repo"] for i in ids)
    assert len(ids) == len(set(ids)) == 60
    assert max(per.values()) <= 15
    assert set(per) == {r["repo"] for r in pop()}                       # every repo is represented
    assert per["b/s3"] == 1 and per["b/s2"] >= 1


def test_title_only_share_hits_target_even_when_repos_lack_it():
    rows = {r["instance_id"]: r for r in pop()}
    ids = S.sample(pop(), n=60, cap=15, title_share=0.2, seed=7)
    assert sum(rows[i]["statement_title_only"] for i in ids) == 12


def test_deterministic_and_seed_sensitive():
    a = S.sample(pop(), n=60, cap=15, title_share=0.2, seed=7)
    assert a == S.sample(pop(), n=60, cap=15, title_share=0.2, seed=7)
    assert a != S.sample(pop(), n=60, cap=15, title_share=0.2, seed=8)
    assert a == sorted(a)


def test_allocation_is_proportional_below_the_cap():
    alloc = S.allocate(Counter({"x": 100, "y": 50, "z": 10}), n=40, cap=30)
    assert sum(alloc.values()) == 40 and alloc["x"] > alloc["y"] > alloc["z"] >= 1


def test_impossible_request_fails():
    with pytest.raises(ValueError):
        S.sample(pop(), n=500, cap=15, title_share=0.2, seed=1)


REAL = ROOT / "data" / "heldout1k" / "tasks.jsonl"


@pytest.mark.skipif(not REAL.is_file(), reason="heldout1k tasks.jsonl not unpacked")
def test_real_sample200_matches_committed_ids():
    rows = [json.loads(ln) for ln in REAL.read_text().splitlines() if ln.strip()]
    ids = S.sample(rows, n=200, cap=15, title_share=0.2, seed=S.SEED)
    by = {r["instance_id"]: r for r in rows}
    per = Counter(by[i]["repo"] for i in ids)
    assert len(ids) == 200 and max(per.values()) <= 15 and len(per) == len({r["repo"] for r in rows})
    assert sum(by[i]["statement_title_only"] for i in ids) == 40
    committed = ROOT / "data" / "heldout1k" / "sample200_ids.txt"
    if committed.is_file():
        assert committed.read_text().split() == ids


# ------------------------------------------------------------------------------------------- preflight summary
def res(tid, resolved, error=None, code=0):
    return {"instance_id": tid, "repo": "o/r", "resolved": resolved, "error": error, "test_exit_code": code}


def test_classify_valid_and_drop_reasons():
    gold = {"t1": res("t1", True), "t2": res("t2", True), "t3": res("t3", False, "Failed to apply test_patch: x", -1),
            "t4": res("t4", False, None, 1), "t5": res("t5", False, "Failed to apply agent patch: hunk 1 FAILED", 1),
            "t7": res("t7", False, "No passing tests recorded in JUnit XML (total=0, passed=0, skipped=0)", 0),
            "t8": res("t8", False, None, 1)}
    empty = {"t1": res("t1", False, None, 1), "t2": res("t2", True), "t3": res("t3", False), "t4": res("t4", False),
             "t5": res("t5", False), "t7": res("t7", False), "t8": res("t8", False)}
    outs = {"t4": "E   ModuleNotFoundError: No module named 'hypothesis'\n1 failed", "t8": "FAILED t::x - assert 1 == 2"}
    ids = ["t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8"]
    c = {t: PS.classify(t, gold.get(t), empty.get(t), outs.get(t, "")) for t in ids}
    assert c == {"t1": "valid", "t2": "empty_resolves", "t3": "test_patch_no_apply", "t4": "gold_env_error",
                 "t5": "gold_no_apply", "t6": "no_result", "t7": "gold_junit_reject",
                 "t8": "gold_tests_fail"}


def test_summary_counts_by_reason_and_repo(tmp_path):
    for run, rows in (("fix_gold", [res("a_1", True), res("b_1", False, None, 1)]),
                      ("fix_empty", [res("a_1", False, None, 1), res("b_1", False, None, 1)])):
        (tmp_path / run).mkdir()
        (tmp_path / run / "task_results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (tmp_path / "fix_gold" / "test_outputs").mkdir()
    (tmp_path / "fix_gold" / "test_outputs" / "b_1.log").write_text("FAILED tests/test_x.py::test_y - assert 1 == 2\n")
    (tmp_path / "ids.txt").write_text("a_1\nb_1\n")
    s = PS.summarize(tmp_path)
    assert s["n"] == 2 and s["valid"] == 1 and s["reasons"] == {"valid": 1, "gold_tests_fail": 1}
    assert s["valid_ids"] == ["a_1"]
    assert s["by_task"]["b_1"] == "gold_tests_fail"
