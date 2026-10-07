"""GPU-contention guard (docs/a6000/P2_LOG.md, 2026-10-07 09:2x UTC incident): another workload on the lab PC used the A6000 from ~07:30, every model call became
4-100x slower, tasks hit the cap after 0 tool calls, and nothing in the supervisor noticed (rows are cap hits, not errors). Written before the code."""
import importlib.util, json, os, signal, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "scripts" / "golden"))


def _mod(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "a6000" / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


lib = _mod("autopilot_lib")


def _row(t, latency, target=2.0, status=200):
    return {"status": status, "t": t, "latency_s": latency, "l4_target_s": target}


def test_window_slowdown_looks_only_at_the_recent_window_and_needs_enough_calls():
    now = 10_000.0
    old = [_row(now - 3000 + i, 100.0) for i in range(20)]                     # an old bad stretch: outside the window
    recent = [_row(now - 300 + i, 2.5) for i in range(10)]                      # healthy: 2.5 s against a 2.0 s model time
    s = lib.window_slowdown(old + recent, now)
    assert s is not None and abs(s - 1.25) < 1e-9
    assert lib.window_slowdown(old + recent[:5], now) is None                   # fewer than 8 calls in the window: no verdict
    bad = [_row(now - 200 + i, 60.0) for i in range(10)]
    assert lib.window_slowdown(recent + bad, now) > 3.0


def test_contention_threshold_is_three():
    assert lib.contended(3.01) and not lib.contended(3.0) and not lib.contended(1.6) and not lib.contended(None)


def test_gpu_free_means_idle_samples_not_an_average_that_hides_busy_bursts():
    assert lib.gpu_free([0, 5, 10, 0, 3, 8]) is True
    assert lib.gpu_free([96, 96, 0, 96, 96, 96]) is False                       # the pattern seen on 2026-10-07: mostly busy
    assert lib.gpu_free([0, 0, 0, 0, 0, 90]) is False                           # one burst above 60 is enough to say busy
    assert lib.gpu_free([]) is False


def test_contaminated_window_starts_a_quarter_hour_before_detection():
    assert lib.contaminated_since(10_000.0) == 10_000.0 - 900


# ---------------------------------------------------------------------------------------------------- purges
def test_p2_purge_since_removes_items_finished_after_the_epoch_and_partial_dirs(tmp_path):
    pg = _mod("p2_purge_since")
    items = tmp_path / "items"
    for arm, task in (("v6p", "a"), ("v6p", "b"), ("v4h2", "c")):
        d = items / arm / task; d.mkdir(parents=True); (d / "task_results.jsonl").write_text("{}\n"); (items / arm / f"{task}.out").write_text("x")
    (items / "v4h2" / "partial").mkdir(); (items / "v4h2" / "partial.out").write_text("x")      # in flight: no result file
    rows = [{"arm": "v6p", "task": "a", "t0": 100.0, "t1": 200.0, "rc": 0}, {"arm": "v6p", "task": "b", "t0": 900.0, "t1": 1000.0, "rc": 0},
            {"arm": "v4h2", "task": "c", "t0": 950.0, "t1": 1100.0, "rc": 0}]
    (tmp_path / "items.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    n = pg.purge_since(str(tmp_path), "items", 800.0, rm=lambda p: __import__("shutil").rmtree(p, ignore_errors=True) if os.path.isdir(p) else (os.path.exists(p) and os.remove(p)))
    assert n == 3                                                               # b, c (finished after 800) and the partial directory
    assert (items / "v6p" / "a").exists() and not (items / "v6p" / "b").exists() and not (items / "v4h2" / "c").exists() and not (items / "v4h2" / "partial").exists()
    assert [json.loads(l)["task"] for l in (tmp_path / "items.jsonl").read_text().splitlines()] == ["a"]
    assert (tmp_path / "items" / "v6p" / "b.out").exists() is False


def test_p4_purge_since_removes_rows_stamped_after_the_epoch_and_keeps_unstamped_rows(tmp_path):
    pg = _mod("p4_purge_since")
    f = tmp_path / "results.jsonl"
    rows = [{"id": "old", "resolved": True}, {"id": "a", "resolved": False, "t": 500.0}, {"id": "b", "resolved": True, "t": 1200.0}]
    f.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert pg.purge_since(str(f), 1000.0) == 1
    assert [json.loads(l)["id"] for l in f.read_text().splitlines()] == ["old", "a"]
    assert pg.purge_since(str(tmp_path / "missing.jsonl"), 1.0) == 0


def test_run_eval_rows_carry_a_finish_time():
    ev = _mod("run_eval")
    row = ev.result_row(None, "t1", True, 0, 12, 3.14159, None, "diff", t=1234.5)
    assert row["t"] == 1234.5 and list(row)[:8] == ["cfg", "id", "resolved", "exit", "calls", "secs", "err", "patch"]


# ------------------------------------------------------------------ the supervisor pauses a contended step, waits for a free GPU, purges and resumes
def _sup(tmp_path, plan, state, fake_util_file, seconds, extra_env=None):
    (tmp_path / "plan.json").write_text(json.dumps(plan)); (tmp_path / "state.json").write_text(json.dumps(state))
    env = dict(os.environ, AUTOPILOT_LOG=str(tmp_path / "log.md"), AUTOPILOT_NO_PUSH="1", AUTOPILOT_SKIP_SERVICES="1", AUTOPILOT_TICK="1",
               AUTOPILOT_CONT_CHECK_S="2", AUTOPILOT_FREE_POLL_S="1", AUTOPILOT_FREE_SAMPLES="3", AUTOPILOT_FAKE_GPU_UTIL=str(fake_util_file), **(extra_env or {}))
    p = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "a6000" / "autopilot.py"), "--plan", str(tmp_path / "plan.json"), "--state", str(tmp_path / "state.json")],
                         env=env, cwd=ROOT, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p


def _plan(marker, speed_log, purge_marker):
    return {"open": True, "steps": [{"name": "t1", "total": 1, "docker": False, "cmd": ["sleep", marker], "proxy": None, "speed_log": str(speed_log),
                                     "stats": {"type": "results_jsonl", "file": "/nonexistent.jsonl"},
                                     "purge_since": ["bash", "-c", 'touch "$0"', str(purge_marker)], "post": []}]}


def _bad_log(path, n=12):
    now = time.time()
    path.write_text("".join(json.dumps({"status": 200, "t": now - 5 - i, "latency_s": 90.0, "l4_target_s": 2.0}) + "\n" for i in range(n)))


def _wait_for(cond, seconds):
    t = time.time()
    while time.time() - t < seconds:
        if cond():
            return True
        time.sleep(0.5)
    return False


def _count(marker):
    return len(subprocess.run(["pgrep", "-fx", f"sleep {marker}"], capture_output=True, text=True).stdout.split())


def test_contention_confirmed_by_nvidia_smi_pauses_purges_waits_and_resumes(tmp_path):
    marker, util, speed, purged = "31351", tmp_path / "util.txt", tmp_path / "speed.jsonl", tmp_path / "purged"
    util.write_text("0 0 0")                                                     # free at the start: the step runs
    p = _sup(tmp_path, _plan(marker, speed, purged), {"done": [], "restarts": {}, "launch_epoch": time.time(), "results": {}}, util, 0)
    try:
        log = lambda: (tmp_path / "log.md").read_text() if (tmp_path / "log.md").exists() else ""
        assert _wait_for(lambda: _count(marker) == 1, 15), log()
        util.write_text("96 96 96")                                              # another workload arrives: busy while vLLM is idle
        _bad_log(speed)                                                          # and the step's calls become 45x slower
        assert _wait_for(lambda: "EXTERNAL GPU CONTENTION" in log(), 25), log()
        assert _wait_for(lambda: purged.exists(), 10)                              # contaminated items were purged
        assert _wait_for(lambda: _count(marker) == 0, 10)                          # the step was stopped while the GPU is busy
        speed.write_text("")                                                       # old rows would re-trigger: the new run starts clean
        util.write_text("0 1 0")                                                   # the other workload is gone
        assert _wait_for(lambda: "GPU free again" in log(), 25), log()
        assert _wait_for(lambda: _count(marker) == 1, 10)                          # and the step runs again
    finally:
        os.killpg(p.pid, signal.SIGKILL); subprocess.run(["pkill", "-fx", f"sleep {marker}"])


def test_high_slowdown_without_external_load_is_a_false_alarm_nothing_is_purged(tmp_path):
    marker, util, speed, purged = "31352", tmp_path / "util.txt", tmp_path / "speed.jsonl", tmp_path / "purged"
    util.write_text("0 2 1")                                                     # idle GPU while vLLM is idle: the slowness is the workload's own
    p = _sup(tmp_path, _plan(marker, speed, purged), {"done": [], "restarts": {}, "launch_epoch": time.time(), "results": {}}, util, 0)
    try:
        log = lambda: (tmp_path / "log.md").read_text() if (tmp_path / "log.md").exists() else ""
        assert _wait_for(lambda: _count(marker) == 1, 15), log()
        _bad_log(speed)
        assert _wait_for(lambda: "false alarm" in log(), 25), log()
        assert not purged.exists() and _wait_for(lambda: _count(marker) == 1, 10)
    finally:
        os.killpg(p.pid, signal.SIGKILL); subprocess.run(["pkill", "-fx", f"sleep {marker}"])


def test_a_busy_gpu_at_step_start_is_waited_out_before_the_step_runs(tmp_path):
    marker, util, purged = "31353", tmp_path / "util.txt", tmp_path / "purged"
    util.write_text("95 97 96")
    p = _sup(tmp_path, _plan(marker, tmp_path / "nolog.jsonl", purged), {"done": [], "restarts": {}, "launch_epoch": time.time(), "results": {}}, util, 0)
    try:
        log = lambda: (tmp_path / "log.md").read_text() if (tmp_path / "log.md").exists() else ""
        assert _wait_for(lambda: "GPU busy at step start" in log(), 20), log()
        time.sleep(2); assert _count(marker) == 0                                  # not started while busy
        util.write_text("0 0 0")
        assert _wait_for(lambda: _count(marker) == 1, 25), log()
    finally:
        os.killpg(p.pid, signal.SIGKILL); subprocess.run(["pkill", "-fx", f"sleep {marker}"])
