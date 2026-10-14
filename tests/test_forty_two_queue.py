"""scripts/forty_two/queue_plan.py and queue_read.py: the per-task box queue for the forty_two levers (owner, 2026-10-14: "solve
individually until passes and then merge"). One bundle per lever runs its own tasks k=3 times; a task passes when it is solved
in >= 2 of 3 samples; a lever is accepted when at least one of its tasks passes and none of its samples errored. Written before
the scripts."""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "forty_two"))
import queue_plan, queue_read  # noqa: E402


def test_plan_groups_runnable_queue_files_by_bundle_and_interleaves_samples(tmp_path):
    q = tmp_path / "queue"; q.mkdir()
    for i, b in [("t1", "submissions/v13_a"), ("t2", "submissions/v13_a"), ("t3", "submissions/v13_b"), ("t4", None)]:
        (q / f"{i}.json").write_text(json.dumps({"id": i, "bundle": b, "k": 3}))
    p = queue_plan.plan(q, override={"t2": "submissions/v13_b"})
    assert p["groups"] == {"v13_a": ["t1"], "v13_b": ["t2", "t3"]} and p["skipped"] == ["t4"]
    steps = [(s["bundle"], s["sample"]) for s in p["steps"]]
    assert steps == [("v13_a", 1), ("v13_b", 1), ("v13_a", 2), ("v13_b", 2), ("v13_a", 3), ("v13_b", 3)]
    assert all(s["out"] == f"q_{s['bundle']}_s{s['sample']}" for s in p["steps"])


def _res(d, rows):
    d.mkdir(parents=True); (d / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_read_passes_a_task_at_two_of_three_and_accepts_a_lever_with_one_passing_task(tmp_path):
    groups = {"v13_a": ["t1", "t2"], "v13_b": ["t3"]}
    for s, (r1, r2, r3) in enumerate([(True, False, True), (True, False, False), (False, True, False)], 1):
        _res(tmp_path / f"q_v13_a_s{s}", [{"id": "t1", "resolved": r1, "err": ""}, {"id": "t2", "resolved": r2, "err": ""}])
        _res(tmp_path / f"q_v13_b_s{s}", [{"id": "t3", "resolved": r3, "err": ""}])
    r = queue_read.read(tmp_path, groups, k=3)
    assert r["tasks"]["t1"] == {"solved": 2, "samples": 3, "verdict": "PASS"}
    assert r["tasks"]["t2"]["verdict"] == "FAIL" and r["tasks"]["t3"] == {"solved": 1, "samples": 3, "verdict": "FAIL"}
    assert r["levers"] == {"v13_a": "ACCEPT", "v13_b": "REJECT"}


def test_missing_samples_or_an_errored_row_make_it_incomplete_not_a_fail(tmp_path):
    groups = {"v13_a": ["t1"]}
    _res(tmp_path / "q_v13_a_s1", [{"id": "t1", "resolved": False, "err": "Agent completed execution without calling submit_patch."}])
    _res(tmp_path / "q_v13_a_s2", [{"id": "t1", "resolved": False, "err": "Agent exceeded session timeout (5.0 min)"}])
    r = queue_read.read(tmp_path, groups, k=3)
    assert r["tasks"]["t1"]["verdict"] == "INCOMPLETE" and r["levers"]["v13_a"] == "INCOMPLETE"
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "forty_two" / "queue_read.py"), str(tmp_path), "--groups-json",
                          json.dumps(groups)], capture_output=True, text=True).stdout
    assert "t1" in out and "INCOMPLETE" in out and "v13_a" in out


def test_controls_add_base_bundle_samples_and_a_lever_gets_no_credit_where_the_base_also_passes(tmp_path):
    # amendment 2026-10-15 00:15 IST, before any queue row: v13 alone solved fastapi_9753, rich_3718, rich_3777, rich_4075 once
    # in p4_v13, so the queue also runs v13 on them (k=3) and a lever's pass on a task the base also passes is not credited
    q = tmp_path / "queue"; q.mkdir()
    for i, b in [("t1", "submissions/v13_a"), ("t2", "submissions/v13_a")]:
        (q / f"{i}.json").write_text(json.dumps({"id": i, "bundle": b, "k": 3}))
    p = queue_plan.plan(q, controls={"v13": ["t1"]})
    assert p["groups"] == {"v13": ["t1"], "v13_a": ["t1", "t2"]}
    res = tmp_path / "res"
    for s in (1, 2, 3):
        _res(res / f"q_v13_a_s{s}", [{"id": "t1", "resolved": True, "err": ""}, {"id": "t2", "resolved": s > 1, "err": ""}])
        _res(res / f"q_v13_s{s}", [{"id": "t1", "resolved": s != 2, "err": ""}])
    r = queue_read.read(res, p["groups"], k=3, base="v13")
    assert r["credited"]["v13_a"] == ["t2"] and r["levers"]["v13_a"] == "ACCEPT"
    p2 = {"v13": ["t1"], "v13_a": ["t1"]}
    r2 = queue_read.read(res, p2, k=3, base="v13")
    assert r2["credited"]["v13_a"] == [] and r2["levers"]["v13_a"] == "REJECT"
