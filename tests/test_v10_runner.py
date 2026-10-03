"""v10 integration: the pod runner, the L4 replay ship gate, the race-2 KPIs and the Linux parity script (SPEC R115-R119).

Tiers: CI by default; R116 skips without eval/race1/runs; R117 (REPLAY) and R118 (RACE) run only when race-2 results
exist (eval/runs/r2_* or $G4_RACE_DIR); R119 is NIGHTLY (G4_NIGHTLY=1) and needs Docker. Nothing here touches a GPU,
a pod or Kaggle: chain_race2.sh is only read.
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from v10_support.compat import VERSION  # noqa: E402  (G4_BUNDLE may be v10.2)
try:
    from v10_support.repo import no_orphans  # noqa: F401  (autouse, R120)
except ImportError:  # core's support module not present: same contract, minimal form
    @pytest.fixture(autouse=True)
    def no_orphans(tmp_path):
        yield
        deadline, left = time.monotonic() + 1.0, []
        while True:   # a process of this test may take up to 1 s to die; none may survive longer
            ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
            left = [line for line in ps.splitlines() if str(tmp_path) in line and "ps -axo" not in line]
            if not left or time.monotonic() > deadline:
                break
            time.sleep(0.1)
        assert not left, f"orphan processes survived the test: {left[:3]}"

RACE1 = ROOT / "eval" / "race1" / "runs"
RACE_DIR = Path(os.environ.get("G4_RACE_DIR") or ROOT / "eval" / "runs")
NIGHTLY = os.environ.get("G4_NIGHTLY") == "1"
OLD_SETUP_SHA1 = "83e9feb7215a71d86ce70792dc4c6bd1026d22b3"   # scripts/run_eval.py SETUP as shipped for race 1


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RE = _load("run_eval")
RP = _load("replay_l4")


# ---------------------------------------------------------------------------------------------------------------------
# R115 scripts/run_eval.py
# ---------------------------------------------------------------------------------------------------------------------
class FakeRes:
    exit_code, stdout, stderr = 0, "ENV_OK\n", ""


class FakeDocker:
    def __init__(self):
        self.cmds = []

    def exec(self, cid, cmd, timeout=None):
        self.cmds.append(cmd)
        return FakeRes()


@pytest.fixture
def harness_restored(monkeypatch):
    """monkeypatch records the originals, so whatever run_eval.main patches is undone after the test."""
    import swegemma.cli as cli
    import swegemma.harness.agent_runner as ar
    import swegemma.harness.container_setup as cs
    import swegemma.harness.verification as vf
    for m in (ar, vf, cs):
        monkeypatch.setattr(m, "install_test_dependencies", m.install_test_dependencies)
    for k in ("G4_COMPACTION", "G4_L4_SCALE", "G4_NO_EDITABLE", "G4_FAITHFUL_ENV"):
        monkeypatch.delenv(k, raising=False)
    captured = {}

    def capture(*a, **kw):
        captured.clear()
        captured.update(kw)
        return kw

    class FakeEvaluator:
        def __init__(self, config):
            self.config = config

        async def run(self):
            return type("R", (), {"resolved": 0, "total": 0, "resolution_rate": 0.0})()

    monkeypatch.setattr(cli, "EvalConfig", capture)
    monkeypatch.setattr(cli, "Evaluator", FakeEvaluator)
    return captured, (ar, vf, cs)


def _argv(tmp_path, *extra):
    return ["eval", "--tasks", str(tmp_path / "t.jsonl"), "--snapshots-dir", str(tmp_path), "--results-dir",
            str(tmp_path / "res"), "--submission-dir", str(tmp_path), "--sandbox", "subprocess", "--display", "quiet", *extra]


def test_run_eval_compaction_scale_noeditable(tmp_path, monkeypatch, harness_restored):
    captured, (ar, vf, cs) = harness_restored
    import swegemma.cli as cli
    import swegemma.evaluate as ev
    orig = {m: m.install_test_dependencies for m in (ar, vf, cs)}

    # importing the runner changes nothing (defaults unchanged for other callers)
    _load("run_eval")
    assert {m: m.install_test_dependencies for m in (ar, vf, cs)} == orig
    assert ev.EvalConfig.__dataclass_fields__["events_compaction_config"].default is None

    # default: compaction on with the README values; budgets untouched
    assert RE.main(_argv(tmp_path, "--max-time-minutes", "5", "--timeout-seconds", "120")) == 0
    c = captured["events_compaction_config"]
    assert (c.compaction_interval, c.overlap_size, c.token_threshold, c.event_retention_size) == (5, 2, 14336, 5)
    assert captured["max_time_minutes"] == 5.0 and captured["timeout_seconds"] == 120
    assert ar.install_test_dependencies is RE.faithful_install          # the pod environment stays the default
    assert vf.install_test_dependencies is RE.faithful_install

    # G4_COMPACTION=0 disables it
    monkeypatch.setenv("G4_COMPACTION", "0")
    RE.main(_argv(tmp_path, "--max-time-minutes", "5"))
    assert captured.get("events_compaction_config") is None
    monkeypatch.delenv("G4_COMPACTION")

    # G4_L4_SCALE divides both caps; --k=v form too; timeout rounded, >= 1
    monkeypatch.setenv("G4_L4_SCALE", "1.7")
    RE.main(_argv(tmp_path, "--max-time-minutes", "5", "--timeout-seconds=120"))
    assert abs(captured["max_time_minutes"] - 5 / 1.7) < 1e-4 and captured["timeout_seconds"] == 71
    RE.main(_argv(tmp_path, "--max-time-minutes=6", "--timeout-seconds", "180"))
    assert abs(captured["max_time_minutes"] - 6 / 1.7) < 1e-4 and captured["timeout_seconds"] == 106
    assert captured["events_compaction_config"] is not None

    # the agent-phase install writes clock_scale; the verification phase does not
    d = FakeDocker()
    ar.install_test_dependencies(d, "cid", "Textualize/rich")
    assert any("/tmp/swe/clock_scale" in x and "1.7" in x for x in d.cmds), d.cmds
    d2 = FakeDocker()
    vf.install_test_dependencies(d2, "cid", "Textualize/rich")
    assert not any("clock_scale" in x for x in d2.cmds)

    # G4_FAITHFUL_ENV=0 keeps the stock harness install (the Mac flow tests), clock_scale still written
    monkeypatch.setenv("G4_FAITHFUL_ENV", "0")
    for m in (ar, vf, cs):
        monkeypatch.setattr(m, "install_test_dependencies", orig[m])
    RE.main(_argv(tmp_path))
    assert vf.install_test_dependencies is orig[vf] and cs.install_test_dependencies is orig[cs]
    assert ar.install_test_dependencies is not orig[ar]


def test_run_eval_no_editable_and_setup_compat(monkeypatch):
    # the historical script is unchanged byte for byte (existing pod behaviour)
    assert hashlib.sha1(RE.SETUP.encode()).hexdigest() == OLD_SETUP_SHA1
    assert RE.setup_script(False) == RE.SETUP and "-e /workspace" in RE.SETUP
    assert "-e /workspace" not in RE.setup_script(True) and "ENV_OK" in RE.setup_script(True)
    for flag, has_e in (("1", False), ("0", True), ("", True), ("true", False)):
        monkeypatch.setenv("G4_NO_EDITABLE", flag)
        d = FakeDocker()
        RE.faithful_install(d, "cid", "fastapi/fastapi")
        assert len(d.cmds) == 1 and d.cmds[0].startswith("REPO_PKG=fastapi bash -c ")
        assert ("-e /workspace" in d.cmds[0]) is has_e, flag


@pytest.mark.parametrize("argv,s,want", [
    (["--max-time-minutes", "5", "--timeout-seconds", "120"], 1.7, ["--max-time-minutes", "2.941176", "--timeout-seconds", "71"]),
    (["--timeout-seconds=1"], 1.7, ["--timeout-seconds=1"]),                      # never below 1 s
    (["--max-time-minutes"], 1.7, ["--max-time-minutes"]),                        # dangling flag left to argparse
    (["--task-ids", "a", "--timeout-seconds", "60", "b"], 2.0, ["--task-ids", "a", "--timeout-seconds", "30", "b"]),
    (["--max-tool-calls", "100"], 1.7, ["--max-tool-calls", "100"]),              # other budgets untouched
])
def test_scale_argv_edges(argv, s, want):
    assert RE.scale_argv(argv, s) == want


@pytest.mark.parametrize("raw,ok", [("1.7", 1.7), ("", None), (" ", None), ("abc", "exit"), ("0", "exit"), ("9", "exit")])
def test_l4_scale_parsing(monkeypatch, raw, ok):
    monkeypatch.setenv("G4_L4_SCALE", raw)
    if ok == "exit":
        with pytest.raises(SystemExit):
            RE.l4_scale()
    else:
        assert RE.l4_scale() == ok


def test_clock_scale_lands_in_real_sandbox_tmp(tmp_path, harness_restored, monkeypatch):
    """Real SubprocessManager: /tmp in the command text is rewritten, so the file lands in <sandbox>/tmp/swe."""
    sub = pytest.importorskip("swegemma.sandbox.subprocess")
    _, (ar, vf, cs) = harness_restored
    monkeypatch.setenv("G4_FAITHFUL_ENV", "0")
    monkeypatch.setenv("G4_L4_SCALE", "1.7")
    RE.main(_argv(tmp_path))
    m = sub.SubprocessManager(timeout_seconds=30, base_dir=tmp_path)
    try:
        sid = m.start()
        ar.install_test_dependencies(m, sid, "synthetic/calc")
        f = Path(m.sandboxes[sid]["tmp"]) / "swe" / "clock_scale"
        assert f.read_text() == "1.7\n"
        assert not Path("/tmp/swe/clock_scale").exists() or Path("/tmp/swe/clock_scale").stat().st_mtime < time.time() - 60
        scripts = ROOT / (os.environ.get("G4_BUNDLE") or "submissions/v10") / "skills" / "swe-tools" / "scripts"
        if (scripts / "install.py").is_file():   # install.py keeps it, and installed helpers scale their clock by it
            # under the sandbox root: the harness shields its own root from the /tmp rewrite, while a tmp_path under
            # /tmp (Linux) would be rewritten in the command text (found by the Linux parity run)
            wrap = Path(m.sandboxes[sid]["root"]) / "wrap"
            shutil.copytree(scripts, wrap / "scripts", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            r = m.exec(sid, "git init -q && git -c user.email=a@b -c user.name=t commit -q --allow-empty -m b && "
                            f"git tag _swegemma_baseline && cd {wrap} && python3 scripts/install.py")
            assert r.stdout.startswith("swe-tools %s ready in /tmp/swe" % VERSION), r.stdout + r.stderr
            assert f.read_text() == "1.7\n"
            code = ("import sys,time; sys.path.insert(0, '/tmp/swe'); import _swe_common as C; a = C.clock(); "
                    "time.sleep(1.0); print(C.clock() - a)")
            r = m.exec(sid, f'python3 -c "{code}"')
            assert r.exit_code == 0, r.stderr
            assert 1.5 < float(r.stdout.strip().splitlines()[-1]) < 2.2, r.stdout
    finally:
        m.cleanup_all()


def test_runner_scripts_start_fast():
    t = time.perf_counter()
    r = subprocess.run([sys.executable, "-X", "importtime", "-c",
                        f"import sys; sys.path.insert(0, {str(ROOT / 'scripts')!r}); import run_eval, replay_l4"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert time.perf_counter() - t < 2.0
    heavy = [line for line in r.stderr.splitlines() if re.search(r"\b(swegemma|google|litellm|adk_)", line)]
    assert not heavy, heavy[:3]          # both import only the stdlib at module level


# ---------------------------------------------------------------------------------------------------------------------
# R116 / R117 replay
# ---------------------------------------------------------------------------------------------------------------------
def _replay(*args):
    t = time.perf_counter()
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "replay_l4.py"), *args, "--json"], capture_output=True, text=True)
    return r.returncode, json.loads(r.stdout.strip().splitlines()[-1]), time.perf_counter() - t


@pytest.mark.skipif(not (RACE1 / "r_v4").is_dir() or not (RACE1 / "r_v9_eog").is_dir(), reason="eval/race1/runs absent")
def test_replay_reproduces_baseline():
    rc, out, secs = _replay("--baseline")
    assert rc == 0 and out["n"] == 51 and abs(out["mean"] - 150.2) <= 0.5, out
    assert secs < 5.0
    rc, out, _ = _replay("--design", "final")
    assert rc == 0 and out["base"] == "r_v9_eog" and abs(out["mean"] - 154.0) <= 1.0, out
    assert abs(out["ratio_to_v4"] - 1.03) < 0.01
    _, pess, _ = _replay("--design", "final", "--pessimistic")
    assert abs(pess["mean"] - 166.4) <= 1.0, pess                       # SPEC 9.1 table, pessimistic column
    _, x2, _ = _replay("--design", "final", "--base", "r_v4", "--stretch", "2")
    assert abs(x2["mean"] - 207.0) <= 1.0, x2                           # "final x2: v4:207"
    # review round 2: the rows above cut every stage at its footer time and cap replies at 200/100/60 tokens, so "0 at
    # the cap" is built in. Measured replies (cut at max_output_tokens 768/2048/2048), then no footer cuts at all:
    _, m, _ = _replay("--design", "final", "--measured")
    assert abs(m["mean"] - 163.0) <= 1.0 and m["at_cap"] == 0, m          # SPEC 9.1, footers obeyed (1.09 x v4)
    _, nc, _ = _replay("--design", "final", "--measured", "--no-cuts")
    assert abs(nc["mean"] - 172.6) <= 1.0 and nc["at_cap"] == 1, nc      # SPEC 9.1, the real pessimistic row (1.15)
    assert nc["mean"] > m["mean"] > 154.0
    _, nc2, _ = _replay("--design", "final", "--measured", "--no-cuts", "--base", "r_v4", "--stretch", "2")
    assert abs(nc2["mean"] - 249.8) <= 1.0 and nc2["at_cap"] == 16, nc2  # hidden-like: near the cap, like v4 x2
    # the gate is not trivially green: v9_eog as-is (1.16 x v4) projects 5 tasks past the cap
    rc, g, _ = _replay("--run", str(RACE1 / "r_v9_eog"))
    assert rc == 1 and not g["pass"] and g["ratio"] > 1.08 and len(g["over_cap"]) == 5
    assert g["knob"] == RP.KNOBS[0] and g["proj_h"] < RP.CLIFF_H


def _step(author, pt, ct, t, tool=None, args=None, obs="", tool_s=0.0):
    extra = {"author": author, "timestamp": t}
    st = {"source": "agent", "metrics": {"prompt_tokens": pt, "completion_tokens": ct}, "extra": extra}
    if tool:
        st["tool_calls"] = [{"function_name": tool, "arguments": args or {}, "extra": dict(extra)}]
        st["observation"] = {"content": obs, "extra": {"tool_name": tool, "timestamp": t + tool_s, "author": author}}
    return st


def _write_run(d, tasks):
    """tasks: {iid: dict(steps=[...], resolved=bool, patch=str, error=str|None)} -> an eval/runs-like directory."""
    (d / "traces").mkdir(parents=True)
    (d / "patches").mkdir()
    rows = []
    for iid, t in tasks.items():
        (d / "traces" / f"trace_{iid}.json").write_text(json.dumps({"schema_version": "ATIF-v1.7", "steps": t["steps"]}))
        patch = t.get("patch", "diff --git a/pkg/m.py b/pkg/m.py\n--- a/pkg/m.py\n+++ b/pkg/m.py\n@@ -1 +1 @@\n-a\n+b\n")
        if patch:
            (d / "patches" / f"{iid}.patch").write_text(patch)
        rows.append({"instance_id": iid, "resolved": t.get("resolved", False), "agent_patch_size": len(patch),
                     "error": t.get("error")})
    (d / "task_results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return d


def _good_task(resolved=True, secs_scale=1.0, **kw):
    steps = [_step("setup", 5000, 30, 0.0, "run_skill_script", {"file_path": "install.py"},
                   '{"status": "success", "stdout": "swe-tools v10.1 ready"}', 0.1),
             _step("locator", 4000, 40 * secs_scale, 2.0, "run_command", {"command": 'python3 /tmp/swe/locate.py "x"'},
                   '{"status": "ok", "stdout": "LOCATE: 3 symbols [t=5s]"}', 0.3),
             _step("verifier", 6000, 40, 9.0, "run_command", {"command": "python3 /tmp/swe/verify.py"},
                   '{"status": "ok", "stdout": "VERIFY: GREEN"}', 2.0),
             _step("verifier", 6500, 20, 12.0, "submit_patch", {}, '{"status": "ok"}', 0.0),
             _step("verifier", 6600, 10, 13.0)]
    return dict(steps=steps, resolved=resolved, **kw)


def test_cliff_projection_unit():
    """SPEC 9.2 H1: every task cap-saturated gives (600 + N x 309.6) / 3600 h: 10.49 h at 120 and 11.35 h at 130, under
    12 h. A cap above 5.25 min fails at N=130 (time_model 8: never above 5.25), so the projection guards the knob that
    actually moves the cliff. Tasks below the cap are stretched 1.9x (hidden are about 1.9x public)."""
    assert abs(RP.cliff_hours([1000.0] * 5, n=120) - 10.49) < 0.01
    assert abs(RP.cliff_hours([1000.0] * 5) - 11.35) < 0.01 and RP.cliff_hours([1000.0]) < RP.CLIFF_H
    assert RP.cliff_hours([1000.0], cap=5.25 * 60) < RP.CLIFF_H < RP.cliff_hours([1000.0], cap=5.5 * 60)
    assert abs(RP.cliff_hours([100.0]) - (600 + 130 * (3.6 + 190.0 + 1.0)) / 3600) < 1e-9
    assert RP.cliff_hours([]) == 0.0


def test_footer_obedience_unit(tmp_path):
    """Review round 2: the time projection assumed the stages obey the footers; race 2 measures it. The first time a
    hint reaches a stage counts once; obeyed = the prescribed next step (locator: reply; fixer: EDIT NOW -> edit.py,
    CONTEXT -> reply within 2 steps, FINISH/TIME -> reply; verifier: finalize.py or submit_patch); a hint after which
    the stage makes no further step is not counted; v9 traces (no v10 footers) give nothing."""
    loc = 'LOCATE: 3 symbols\nLOCATOR: 75s used. Locator: stop and reply with your plan now.\n[t=76s]'
    fin = 'VIEW pkg/m.py\nFINISH: t>=210s. Stop exploring; keep the edit you have and end your stage.\n[t=211s]'
    tim = 'VERIFY: RED\nTIME: t>=250s. End your stage now (verifier: run finalize.py next).\n[t=251s]'
    cmd = lambda c: {"command": c}
    t = dict(steps=[
        _step("locator", 4000, 40, 1.0, "run_command", cmd('python3 /tmp/swe/locate.py "x"'), loc),
        _step("locator", 4100, 40, 2.0, "run_command", cmd("python3 /tmp/swe/view.py a.py 1 9"), loc),   # one more call:
        _step("locator", 4200, 200, 3.0),                                                               # not obeyed
        _step("fixer", 5000, 40, 4.0, "run_command", cmd("python3 /tmp/swe/view.py a.py 1 9"), fin),
        _step("fixer", 5100, 40, 5.0, "run_command", cmd("python3 /tmp/swe/view.py a.py 9 19"), ""),     # ignored FINISH
        _step("fixer", 5200, 80, 6.0),
        _step("verifier", 6000, 40, 7.0, "run_command", cmd("python3 /tmp/swe/verify.py"), tim),
        _step("verifier", 6100, 40, 8.0, "run_command", cmd("python3 /tmp/swe/finalize.py"), "READY"),
        _step("verifier", 6200, 20, 9.0, "submit_patch", {}, "ok"),
        _step("submitter", 3000, 40, 10.0, "run_command", cmd("python3 /tmp/swe/status.py"), tim)],   # no next step
        resolved=True)
    d = _write_run(tmp_path / "r", {"a": t, "b": _good_task()})
    data = RP.load(str(d), keep_obs=True)
    assert RP.footer_obedience(data["a"]["steps"]) == {"LOCATOR": [0, 1], "FINISH": [0, 1], "TIME": [1, 1]}
    assert RP.footer_obedience(data["b"]["steps"]) == {}
    k = RP.run_kpis(str(d), "r")
    assert k["footer_obedience"] == {"LOCATOR": [0, 1], "FINISH": [0, 1], "TIME": [1, 1]}   # the repeat counted once
    assert RP._obeyed("LOCATOR", "locator", [{"kind": "text", "args": "", "fn": None}]) is True
    assert RP._obeyed("EDIT NOW", "fixer", [{"kind": "ok", "args": "view.py", "fn": "run_command"},
                                           {"kind": "ok", "args": "edit.py x", "fn": "run_command"}]) is True
    assert RP._obeyed("CONTEXT", "verifier", [{"kind": "ok", "args": "verify.py", "fn": "run_command"}]) is False
    assert RP._obeyed("LOCATOR", "fixer", [{"kind": "text", "args": "", "fn": None}]) is None


def test_gate_unit_cases(tmp_path):
    base = RP.load(str(_write_run(tmp_path / "base", {f"t{i}": _good_task() for i in range(4)})))
    same = RP.gate(RP.load(str(_write_run(tmp_path / "same", {f"t{i}": _good_task() for i in range(4)}))), base)
    assert same["pass"] and same["ratio"] == 1.0 and same["n"] == 4
    assert same["ratio_ok"] and same["knob"] is None
    # R117 restated (review round 2): a slower mean with every task inside the cap is not a cliff risk. It passes, and
    # the ratio above 1.08 names the first pre-registered knob instead of blocking the ship.
    slow = RP.gate(RP.load(str(_write_run(tmp_path / "slow", {f"t{i}": _good_task(secs_scale=4) for i in range(4)}))), base)
    assert slow["pass"] and slow["ratio"] > 1.08 and not slow["ratio_ok"], slow
    assert slow["knob"] == RP.KNOBS[0] == "verifier repair rounds 2 -> 1 (prompts/verifier.md)"
    assert slow["proj_h"] < RP.CLIFF_H
    # one task projected past cap + 10 s fails the gate even when the mean is fine
    tasks = {f"t{i}": _good_task() for i in range(4)}
    tasks["t0"]["steps"].append(_step("fixer", 9000, 12000, 20.0, "run_command", {"command": "x"}, "ok", 0.0))
    over = RP.gate(RP.load(str(_write_run(tmp_path / "over", tasks))), base, ratio=99)
    assert not over["pass"] and over["over_cap"] == ["t0"]
    assert over["proj_h"] < RP.CLIFF_H                                  # the cap, not the projection, failed it
    # disjoint ids -> FAIL, never a vacuous PASS
    other = RP.gate(RP.load(str(_write_run(tmp_path / "other", {"zz": _good_task()}))), base)
    assert not other["pass"] and other["n"] == 0
    # compaction: a same-author drop from >= 14,336 to < 70 % counts once and costs 5.6 s
    t = _good_task()
    t["steps"] = [_step("fixer", 15000, 10, 0.0, "run_command", {"command": "a"}, "ok"),
                  _step("fixer", 3000, 10, 1.0, "run_command", {"command": "b"}, "ok"),
                  _step("fixer", 14000, 10, 2.0, "run_command", {"command": "c"}, "ok"),
                  _step("fixer", 13000, 10, 3.0, "run_command", {"command": "d"}, "ok")]
    loaded = RP.load(str(_write_run(tmp_path / "comp", {"c": t})))["c"]
    assert RP.compactions(loaded) == 1
    assert abs(RP.retime(loaded) - sum(RP.cost(s) for s in loaded["steps"]) - RP.COMPACTION_EXTRA_S) < 1e-9


@pytest.mark.skipif(not (RACE_DIR / "r2_v10_1").is_dir(), reason="REPLAY tier: no race-2 v10 run yet (eval/runs/r2_v10_1)")
@pytest.mark.skipif(not (RACE1 / "r_v4").is_dir(), reason="eval/race1/runs/r_v4 absent")
def test_replay_gate():
    for k in (1, 2):
        run = RACE_DIR / f"r2_v10_{k}"
        if not run.is_dir():
            continue
        rc, g, _ = _replay("--run", str(run), "--against", str(RACE1 / "r_v4"))
        assert rc == 0 and g["pass"], g


# ---------------------------------------------------------------------------------------------------------------------
# R118 race-2 KPIs
# ---------------------------------------------------------------------------------------------------------------------
def _race(tmp_path, v10_resolved=(40, 40), ctl_resolved=(30, 30), n=20, mutate=None):
    d = tmp_path / "runs"
    for arm, res in (("r2_v9_eog", ctl_resolved), ("r2_v10", v10_resolved)):
        for k, nres in enumerate(res, 1):
            tasks = {f"t{i}": _good_task(resolved=i < nres * n // 100) for i in range(n)}
            if mutate and arm == "r2_v10":
                mutate(k, tasks)
            _write_run(d / f"{arm}_{k}", tasks)
    base = _write_run(tmp_path / "base_r_v4", {f"t{i}": _good_task() for i in range(n)})
    return d, base


def test_race2_kpis_pass_on_a_clean_synthetic_race(tmp_path):
    d, base = _race(tmp_path, v10_resolved=(60, 60), ctl_resolved=(40, 40))
    ok, rows, per = RP.race2(str(d), against=str(base))
    assert ok, [r for r in rows if not r["pass"]]
    assert len(rows) == 26 and {r["kpi"] for r in rows} >= {"resolved sum", "crashes", "time (R117 replay)",
                                                             "footer obedience", "invented tool names (v10.1)"}
    # the 11 v10.1 diagnostic rows are reported with their targets and never fail a race (Addenda 2)
    assert all(r["pass"] for r in rows if "(v10.1)" in r["kpi"]) and sum("(v10.1)" in r["kpi"] for r in rows) == 11


@pytest.mark.parametrize("case,kpi", [
    ("margin", "resolved sum"),
    ("run_floor", "resolved per run"),
    ("overflow", "crashes"), ("unknown_tool", "crashes"), ("keyerror", "crashes"), ("postinv", "crashes"),
    ("no_helpers", "helper availability"),
    ("cant_open", "can't open file per task"),
    ("malformed", "malformed edit_file per task"),
    ("protected", "protected-file patches"),
    ("scratch", "scratch/vendored patches"), ("vendored", "scratch/vendored patches"),
    ("empty", "empty patches per 74"),
    ("prompt_max", "max prompt tokens"),
    ("no_verdict", "verify verdict line"),
])
def test_race2_each_kpi_can_fail(tmp_path, case, kpi):
    errs = {"overflow": "Sandbox execution error: litellm.ContextWindowExceededError: ...",
            "unknown_tool": "Sandbox execution error: Tool 'git_grep' not found",
            "keyerror": "Sandbox execution error: KeyError: 'Context variable not found: `x`.'",
            "postinv": "Sandbox execution error: No LlmAgent model available for event compaction summarizer."}

    def mutate(k, tasks):
        t0 = tasks["t0"]
        if case in errs:
            t0["error"] = errs[case]
        elif case == "no_helpers":
            for t in tasks.values():
                t["steps"] = [s for s in t["steps"] if "tool_calls" not in s or s["tool_calls"][0]["function_name"] == "submit_patch"]
        elif case == "cant_open":
            t0["steps"].append(_step("fixer", 4000, 10, 20.0, "run_command", {"command": "python3 /tmp/swe/edit.py x"},
                                     "python3: can't open file '/x/tmp/swe/edit.py'"))
        elif case == "malformed":
            for t in tasks.values():
                t["steps"] += [_step("fixer", 4000, 10, 20.0 + j, "edit_file", {"filepath": "x"},
                                     "Invoking edit_file() failed as the following mandatory input parameters are not present")
                               for j in range(3)]
        elif case == "protected":
            t0["patch"] = "diff --git a/tests/test_x.py b/tests/test_x.py\n--- a/tests/test_x.py\n+++ b/tests/test_x.py\n"
        elif case == "scratch":
            t0["patch"] = "diff --git a/reproduce_bug.py b/reproduce_bug.py\nnew file mode 100644\n--- /dev/null\n+++ b/reproduce_bug.py\n"
        elif case == "vendored":
            t0["patch"] = "diff --git a/lib/site-packages/x/a.py b/lib/site-packages/x/a.py\nnew file mode 100644\n"
        elif case == "empty":
            for i in range(3):
                tasks[f"t{i}"]["patch"] = ""
        elif case == "prompt_max":
            t0["steps"].append(_step("fixer", 27000, 10, 20.0, "run_command", {"command": "x"}, "ok"))
        elif case == "no_verdict":
            for i in range(3):
                for s in tasks[f"t{i}"]["steps"]:
                    if "observation" in s:
                        s["observation"]["content"] = s["observation"]["content"].replace("VERIFY: GREEN", "ok")

    v10 = {"margin": (45, 45), "run_floor": (70, 20)}.get(case, (60, 60))
    ctl = {"margin": (40, 40), "run_floor": (40, 40)}.get(case, (40, 40))
    d, base = _race(tmp_path, v10_resolved=v10, ctl_resolved=ctl, mutate=mutate)
    ok, rows, _ = RP.race2(str(d), against=str(base))
    failed = {r["kpi"] for r in rows if not r["pass"]}
    assert not ok and kpi in failed, rows


def test_race2_missing_runs_and_kill_rule(tmp_path):
    ok, rows, _ = RP.race2(str(tmp_path))
    assert not ok and rows[0]["kpi"] == "runs present"
    cont, info = RP.kill_check(str(tmp_path))                       # no results at all: fail closed, never CONTINUE
    assert not cont and any("no task results" in r for r in info["reasons"])
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "replay_l4.py"), "--kill-check", str(tmp_path / "none")],
                       capture_output=True, text=True)
    assert r.returncode == 3 and r.stdout.startswith("KILL")
    d, _ = _race(tmp_path, v10_resolved=(40, 40), ctl_resolved=(60, 60))            # 8 vs 12 -> -4 < -3: kill
    cont, info = RP.kill_check(str(d))
    assert not cont and info["reasons"]
    d2, _ = _race(tmp_path / "b", v10_resolved=(50, 50), ctl_resolved=(60, 60))      # -2: continue
    assert RP.kill_check(str(d2))[0]
    d3, _ = _race(tmp_path / "c", mutate=lambda k, t: t["t1"].update(error="Tool 'git_grep' not found"))
    cont, info = RP.kill_check(str(d3))
    assert not cont and "unknown_tool=1" in info["reasons"]
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "replay_l4.py"), "--kill-check", str(d3)], capture_output=True, text=True)
    assert r.returncode == 3 and r.stdout.startswith("KILL")


@pytest.mark.skipif(not (RACE1 / "r_v9_eog").is_dir(), reason="eval/race1/runs absent")
def test_kpis_reproduce_race1_column():
    """The checklist's comparison column is what this code computes on race-1 v9_eog (and matches research/own_data:
    70 missing-helper calls, 3.1 malformed edit_file per task, 10 protected-file patches, 4 empty, 0 crashes)."""
    t = time.perf_counter()
    k = RP.run_kpis(str(RACE1 / "r_v9_eog"), "r_v9_eog")
    assert time.perf_counter() - t < 5.0
    assert (k["n"], k["resolved"]) == (51, 21)
    assert k["crashes"] == {"context_overflow": 0, "unknown_tool": 0, "key_error": 0, "post_invocation": 0}
    assert round(k["cant_open_per_task"] * 51) == 70 and round(k["helper_ok"] * 51) == 30
    assert abs(k["malformed_edit_per_task"] - 3.16) < 0.01
    assert (len(k["protected_patches"]), len(k["scratch_patches"]), len(k["empty_patches"])) == (10, 12, 4)
    assert k["prompt_max"] == 25657 and abs(k["stage_under_line"] - 0.81) < 0.01 and k["compactions"] == 0
    doc = (ROOT / "docs" / "v10" / "race2_checklist.md").read_text()
    for cell in ("0.59 (30/51)", "1.37 per task (70 calls)", "| 3.16 |", "| 10/51 |", "| 12/51 |", "| 4/51 |",
                 "81% under; max 25,657"):
        assert cell in doc, cell


def test_checklist_thresholds_match_code():
    doc = (ROOT / "docs" / "v10" / "race2_checklist.md").read_text()
    block = re.search(r"```\n((?:\w+ = [-0-9.]+\n)+)```", doc).group(1)
    pre = {k: float(v) for k, v in re.findall(r"^(\w+) = ([-0-9.]+)$", block, re.M)}
    assert set(pre) == set(RP.KPI), set(pre) ^ set(RP.KPI)
    for k, v in pre.items():
        assert abs(RP.KPI[k] - v) < 1e-9, (k, v, RP.KPI[k])
    assert "Written 2026-09-28, before any race-2 run exists" in doc
    for needle in ("Kill rule", "Ship rule", "G4_COMPACTION", "G4_L4_SCALE", "G4_NO_EDITABLE", "FAITHFUL"):
        assert needle in doc, needle


@pytest.mark.skipif(not ((RACE_DIR / "r2_v10_1").is_dir() and (RACE_DIR / "r2_v9_eog_1").is_dir()),
                    reason="RACE tier: race-2 results not present (eval/runs/r2_* or $G4_RACE_DIR)")
def test_race_kpis():
    against = RACE_DIR / "r_v4" if (RACE_DIR / "r_v4").is_dir() else RACE1 / "r_v4"
    ok, rows, _ = RP.race2(str(RACE_DIR), against=str(against))
    assert ok, "\n".join(f"{'PASS' if r['pass'] else 'FAIL'} {r['kpi']}: {r['value']} {r['note']}" for r in rows)


# ---------------------------------------------------------------------------------------------------------------------
# R119 Linux parity + the race-2 chain (static: it is never run from here)
# ---------------------------------------------------------------------------------------------------------------------
def test_linux_test_script_v10_mode_static():
    s = (ROOT / "scripts" / "linux_test.sh").read_text()
    assert subprocess.run(["bash", "-n", str(ROOT / "scripts" / "linux_test.sh")]).returncode == 0
    v10 = s[s.index('if [ "${V10_ONLY:-0}" = 1 ]'):s.index('bash -c "$V10_SCRIPT"')]
    for needle in ("--cpus 2", "--memory 4g", "-e TEST_TMPDIR=/tmp", "unset TMPDIR", "tests/test_v10_*.py",
                   '"python:${PY}-slim"', "G4_NIGHTLY", "harness/wheels"):
        assert needle in v10, needle
    assert 'PY="${PY:-3.12}"' in s             # 3.12 by default; PY=3.13 is the scorer's Python (SPEC_v10_2 E6)
    assert "exit $rc" in v10                      # pytest's status is the script's status


def _docker_ok():
    return bool(shutil.which("docker")) and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


@pytest.mark.skipif(not NIGHTLY, reason="NIGHTLY tier (G4_NIGHTLY=1)")
@pytest.mark.skipif(not _docker_ok() or Path("/.dockerenv").exists(), reason="Docker not available (or already inside it)")
def test_linux_parity_script():
    env = {**os.environ, "V10_ONLY": "1"}
    r = subprocess.run(["bash", str(ROOT / "scripts" / "linux_test.sh")], capture_output=True, text=True, timeout=3600, env=env)
    out = r.stdout + r.stderr
    assert "LINUX_V10 TMPDIR=unset TEST_TMPDIR=/tmp" in out, out[-3000:]
    assert r.returncode == 0 and re.search(r"\d+ passed", out), out[-3000:]


def test_chain_race2_static():
    s = (ROOT / "pod" / "chain_race2.sh").read_text()
    assert subprocess.run(["bash", "-n", str(ROOT / "pod" / "chain_race2.sh")]).returncode == 0
    assert "export G4_COMPACTION=1 G4_L4_SCALE=1.7 G4_NO_EDITABLE=1 FAITHFUL=1" in s
    assert "CONTROL=v9_eog; TREAT=v10" in s and "data/arena_ids.txt data/rest_ids.txt" in s
    runs = re.findall(r'run_arm (8100|8101) "\$(CONTROL|TREAT)" "r2_\$\{(CONTROL|TREAT)\}_(\d)"', s)
    assert sorted((p, a, k) for p, a, _, k in runs) == [("8100", "CONTROL", "1"), ("8100", "TREAT", "2"),
                                                       ("8101", "CONTROL", "2"), ("8101", "TREAT", "1")]
    assert " 2 $IDS" in s                                                        # 2 tasks per GPU
    kill, round2 = s.index("--kill-check"), s.index('run_arm 8100 "$TREAT"')
    assert kill < round2 and "stop_pod race2kill" in s[kill:round2]             # kill rule before run 2
    assert "GO_RACE2" in s and "pod/preflight.sh" in s and "pod/canary.sh" in s
    body = s.split("\n")
    assert body[-2].strip() == "stop_pod race2" or s.rstrip().endswith("stop_pod race2")   # the last step stops the pod
    assert all("stop_pod" in line for line in body if "ABORT" in line and "exit 1" in line)
    ids = (ROOT / "data" / "arena_ids.txt").read_text().split() + (ROOT / "data" / "rest_ids.txt").read_text().split()
    assert len(ids) == len(set(ids)) == 74


# ---------------------------------------------------------------------------------------------------------------------
# Support: the scripted mock model used by R113/R114 (stdlib; no harness needed)
# ---------------------------------------------------------------------------------------------------------------------
def _post(url, body):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _req(agent, *extra, tools=None):
    sys_msg = {"role": "system", "content": f'You are an agent. Your internal name is "{agent}".'} if agent else None
    msgs = ([sys_msg] if sys_msg else []) + list(extra)
    return {"model": "gemma-4-31b-it-qat-w4a16-ct", "messages": msgs, "tools": tools or []}


def test_mock_llm_contract():
    from concurrent.futures import ThreadPoolExecutor
    from v10_support.mock_llm import MockLLM, cmd, estimate_prompt_tokens, last_result_has, text, when
    with MockLLM() as m:
        a = m.add_route("a", {"fixer": [cmd("ls"), when(last_result_has("can't open file"), text("recover"), text("fine")),
                                        {**text("big"), "ptok": 15000}]})
        b = m.add_route("b", {"fixer": [text("route b")]})
        code, r = _post(a, _req("fixer", {"role": "user", "content": "go"}))
        call = r["choices"][0]["message"]["tool_calls"][0]
        assert code == 200 and call["function"]["name"] == "run_command" and json.loads(call["function"]["arguments"]) == {"command": "ls"}
        assert r["choices"][0]["finish_reason"] == "tool_calls" and r["usage"]["prompt_tokens"] > 0
        assert _post(b, _req("fixer"))[1]["choices"][0]["message"]["content"] == "route b"      # routes are isolated
        tool_msg = {"role": "tool", "tool_call_id": "x", "content": "python3: can't open file '/x/tmp/swe/a.py'"}
        assert _post(a, _req("fixer", tool_msg))[1]["choices"][0]["message"]["content"] == "recover"   # reactive step
        code, r = _post(a, _req("fixer"))
        assert r["usage"]["prompt_tokens"] == 15000                                            # forced usage
        code, r = _post(a, _req("fixer"))                                                       # exhausted -> default
        assert r["choices"][0]["message"]["content"] == "done" and m.log("a")[-1]["exhausted"]
        summ = {"role": "user", "content": "The following is a conversation history between a user and an AI agent. x"}
        code, r = _post(a, _req(None, summ))
        assert code == 200 and m.summarizer_calls("a") == 1 and m.log("a")[-1]["agent"] == "_summarizer"
        code, r = _post(m.url("nope"), _req("fixer"))
        assert code == 500 and "no route" in r["error"]["message"] and m.errors                # never hangs the client
        m.errors.clear()
        c = m.add_route("c", {"x": [text(str(i)) for i in range(40)]})
        with ThreadPoolExecutor(8) as ex:                                                       # server-side counters
            got = list(ex.map(lambda _: _post(c, _req("x"))[1]["choices"][0]["message"]["content"], range(40)))
        assert sorted(got, key=int) == [str(i) for i in range(40)]
    small = estimate_prompt_tokens(_req("fixer", {"role": "user", "content": "x" * 340}))
    big = estimate_prompt_tokens(_req("fixer", {"role": "tool", "content": "x" * 3000}))
    assert 100 <= small <= 150 and 1000 <= big <= 1050                                          # 3.4 / 3.0 chars per token
