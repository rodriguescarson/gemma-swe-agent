"""scripts/a6000/autopilot_lib.py: pure rules of the autonomous P2 -> P4 -> P2b -> P3 run (pre-registered in docs/v4h/GATE.md, P2 addendum 4)."""
import importlib.util, math, pathlib, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "scripts" / "golden"))
spec = importlib.util.spec_from_file_location("autopilot_lib", ROOT / "scripts" / "a6000" / "autopilot_lib.py")
ap = importlib.util.module_from_spec(spec); spec.loader.exec_module(ap)


def test_health_line_has_every_field():
    s = ap.health_line("2026-10-06T22:00:00Z", "stage1a", done=12, total=150, solved=3, empty=2, errors=1, median_s=301.5, cap=7,
                       gpu_util=98, disk_free_gb=860.4, restarts=1)
    for frag in ("2026-10-06T22:00:00Z", "step=stage1a", "done=12/150", "solved=3", "empty=2", "errors=1", "median_s=301.5", "cap=7",
                 "gpu=98%", "disk_free=860GB", "restarts=1"):
        assert frag in s, frag
    assert s.startswith("- ") and "\n" not in s


def test_health_line_handles_missing_numbers():
    s = ap.health_line("t", "p3", done=0, total=10, solved=0, empty=0, errors=0, median_s=None, cap=0, gpu_util=None, disk_free_gb=5, restarts=0)
    assert "median_s=n/a" in s and "gpu=n/a" in s


def test_deadline_is_36_hours_after_launch():
    assert ap.deadline_utc(1000.0) == 1000.0 + 36 * 3600
    assert ap.time_left_s(1000.0, now=1000.0 + 35 * 3600) == 3600 and ap.time_left_s(1000.0, now=1000.0 + 37 * 3600) < 0


def test_stop_rule_needs_enough_items_and_trips_on_errors_or_fast_median():
    assert ap.stop_reason(done=5, errors=5, median_s=200) is None                 # too few items to judge
    assert "error" in ap.stop_reason(done=20, errors=4, median_s=200)             # 20% > 15%
    assert ap.stop_reason(done=20, errors=3, median_s=200) is None                # 15% exactly is allowed
    assert "median" in ap.stop_reason(done=20, errors=0, median_s=59.0)
    assert ap.stop_reason(done=20, errors=0, median_s=None) is None


def test_p4_arm_is_the_arm_that_is_BETTER_under_the_p2_rule_else_v5h2():
    c = lambda w6, l6, w6t, l6t, g6=0.0, g6t=0.0: {"v6p": {"wins": w6, "losses": l6, "cap_gap": g6}, "v6p-think": {"wins": w6t, "losses": l6t, "cap_gap": g6t}}
    assert ap.choose_p4_arm(c(9, 2, 5, 5)) == "v6p"                          # net +7, p = 0.065: BETTER
    assert ap.choose_p4_arm(c(5, 5, 9, 2)) == "v6p-think"
    assert ap.choose_p4_arm(c(10, 1, 9, 2)) == "v6p"                          # both BETTER: the larger net
    assert ap.choose_p4_arm(c(9, 2, 9, 2)) == "v6p"                           # tie -> v6p
    assert ap.choose_p4_arm(c(6, 1, 5, 5)) == "v5h2"                          # net +5 but p = 0.125: not BETTER
    assert ap.choose_p4_arm(c(8, 5, 6, 7)) == "v5h2"                          # positive net is not enough any more
    assert ap.choose_p4_arm(c(2, 9, 2, 9)) == "v5h2" and ap.choose_p4_arm({}) == "v5h2"
    assert ap.choose_p4_arm(c(9, 2, 5, 5, g6=0.3)) == "v6p"                   # a BETTER verdict stands despite more cap hits


def test_p3_arm_is_the_highest_solved_share_among_arms_with_40_valid_tasks():
    st = {"v4h2": {"solved": 20, "valid": 100}, "v6p": {"solved": 25, "valid": 100}, "v6p-b": {"solved": 10, "valid": 50}, "v6p-think": {"solved": 12, "valid": 39}}
    assert ap.choose_p3_arm(st) == "v6p"                                       # v6p-think has 38% but only 39 valid tasks: ineligible; v6p 25% vs v6p-b 20%
    st["v6p-b"] = {"solved": 13, "valid": 50}
    assert ap.choose_p3_arm(st) == "v6p-b"                                     # 26% > 25%
    st["v6p-b"] = {"solved": 25, "valid": 100}
    assert ap.choose_p3_arm(st) == "v6p-b"                                     # tie: v6p-b before v6p
    assert ap.choose_p3_arm({"v4h2": {"solved": 1, "valid": 3}}) == "v6p"      # nothing eligible: the planned bundle


def test_pooling_adds_the_paired_counts_and_flags_heterogeneity():
    a = {"wins": 6, "losses": 2}; b = {"wins": 1, "losses": 7}
    p = ap.pool(a, b)
    assert p["wins"] == 7 and p["losses"] == 9 and p["net"] == -2 and p["heterogeneous"] is True    # nets +4 and -6 differ by >= 5
    assert ap.pool({"wins": 5, "losses": 3}, {"wins": 4, "losses": 3})["heterogeneous"] is False


def test_infra_error_detection():
    f = ap.is_infra_error
    assert f("litellm.APIError: Key limit exceeded") and f("litellm.APIConnectionError: OpenAIException - Connection error.")
    assert f("litellm.InternalServerError: 503 Service Unavailable") and f("Connection refused")
    assert not f(None) and not f("Agent exceeded session timeout (5.0 min)") and not f("Agent exceeded turns budget (150 turns)")
    assert not f("Tool 'python3 /tmp/swe/edit.py' not found")           # a bundle behaviour (the heredoc-as-tool-name crash), not infrastructure


def test_purge_removes_only_infra_error_items(tmp_path):
    spec2 = importlib.util.spec_from_file_location("p2_purge", ROOT / "scripts" / "a6000" / "p2_purge.py")
    pg = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(pg)
    import json
    def put(arm, task, err):
        d = tmp_path / "items" / arm / task; d.mkdir(parents=True)
        (d / "task_results.jsonl").write_text(json.dumps({"instance_id": task, "error": err}) + "\n")
        (tmp_path / "items" / arm / f"{task}.out").write_text("x")
    put("v6p", "a", "litellm.APIConnectionError: Connection error.")
    put("v6p", "b", "Agent exceeded session timeout (5.0 min)")
    put("v4h2", "c", None)
    put("v4h2", "d", "litellm.InternalServerError: 503")
    n = pg.purge(str(tmp_path), "items", rm=lambda p: (__import__("shutil").rmtree(p) if __import__("os").path.isdir(p) else __import__("os").path.exists(p) and __import__("os").remove(p)))
    assert n == 2
    assert not (tmp_path / "items" / "v6p" / "a").exists() and not (tmp_path / "items" / "v6p" / "a.out").exists()
    assert (tmp_path / "items" / "v6p" / "b").exists() and (tmp_path / "items" / "v4h2" / "c").exists() and not (tmp_path / "items" / "v4h2" / "d").exists()


def test_p4_purge_drops_only_infra_error_rows(tmp_path):
    spec4 = importlib.util.spec_from_file_location("p4_purge", ROOT / "scripts" / "a6000" / "p4_purge.py")
    pg = importlib.util.module_from_spec(spec4); spec4.loader.exec_module(pg)
    import json
    f = tmp_path / "results.jsonl"
    rows = [{"id": "a", "err": None}, {"id": "b", "err": "EXC APIConnectionError('Connection error.')"}, {"id": "c", "err": "Agent exceeded session timeout (5.0 min)"},
            {"id": "d", "err": "litellm.InternalServerError: 503"}]
    f.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert pg.purge(str(f)) == 2
    assert [json.loads(l)["id"] for l in f.read_text().splitlines()] == ["a", "c"]
    assert pg.purge(str(tmp_path / "missing.jsonl")) == 0


# ---------------------------------------------------------------- the missing-PID restart bug (21:48 duplicate runner)
import json, os, signal, subprocess, time


def _run_supervisor(tmp_path, plan, state, seconds, log_name="log.md"):
    (tmp_path / "plan.json").write_text(json.dumps(plan)); (tmp_path / "state.json").write_text(json.dumps(state))
    env = dict(os.environ, AUTOPILOT_LOG=str(tmp_path / log_name), AUTOPILOT_NO_PUSH="1", AUTOPILOT_SKIP_SERVICES="1", AUTOPILOT_TICK="1")
    p = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "a6000" / "autopilot.py"), "--plan", str(tmp_path / "plan.json"), "--state", str(tmp_path / "state.json")],
                         env=env, cwd=ROOT, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(seconds)
    os.killpg(p.pid, signal.SIGKILL)
    return (tmp_path / log_name).read_text() if (tmp_path / log_name).exists() else ""


def _plan(marker):
    return {"open": True, "steps": [{"name": "t1", "total": 1, "docker": False, "cmd": ["sleep", marker], "proxy": None,
                                     "stats": {"type": "results_jsonl", "file": "/nonexistent.jsonl"}, "post": []}]}


def _count(marker):
    return len(subprocess.run(["pgrep", "-fx", f"sleep {marker}"], capture_output=True, text=True).stdout.split())


def test_a_fresh_supervisor_records_the_childs_pid_in_the_state_file(tmp_path):
    marker = "31337"
    try:
        _run_supervisor(tmp_path, _plan(marker), {"done": [], "restarts": {}, "launch_epoch": time.time(), "results": {}}, 4)
        st = json.loads((tmp_path / "state.json").read_text())
        assert st.get("child_step") == "t1" and isinstance(st.get("child"), int)         # without this a restarted supervisor cannot adopt
        assert os.path.exists(f"/proc/{st['child']}") and _count(marker) == 1
    finally:
        subprocess.run(["pkill", "-fx", f"sleep {marker}"])


def test_a_restarted_supervisor_adopts_the_running_child_and_starts_no_duplicate(tmp_path):
    marker = "31338"
    child = subprocess.Popen(["sleep", marker], start_new_session=True)
    try:
        log = _run_supervisor(tmp_path, _plan(marker), {"done": [], "restarts": {}, "launch_epoch": time.time(), "results": {}, "child": child.pid, "child_step": "t1"}, 4)
        assert f"adopted running pid {child.pid}" in log and "started pid" not in log
        assert _count(marker) == 1                                                     # still exactly one: no second runner
    finally:
        subprocess.run(["pkill", "-fx", f"sleep {marker}"])
        child.wait()


def test_adopted_poll_follows_the_pid():
    spec5 = importlib.util.spec_from_file_location("autopilot_mod", ROOT / "scripts" / "a6000" / "autopilot.py")
    mod = importlib.util.module_from_spec(spec5); spec5.loader.exec_module(mod)
    p = subprocess.Popen(["sleep", "30"])
    a = mod.Adopted(p.pid)
    assert a.poll() is None
    p.kill(); p.wait()
    assert a.poll() == 0
