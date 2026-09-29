"""scripts/ab_l4_decide.py: the pre-registered rule of docs/v10/AB_L4.md, on synthetic runs (base and edge cases) and on
the two real Kaggle-L4 runs (v4 and v9_eog, 29/74 each)."""
import importlib.util, json, pathlib, subprocess, sys
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ab_l4_decide.py"
IDS = ["t%02d" % i for i in range(74)]


def _mod(path=SCRIPT, name="ab_l4_decide"):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_dir(tmp_path, name, solved, secs=150.0, errs=None, ids=IDS, wheels="abc  vllm.whl\n"):
    d = tmp_path / name
    d.mkdir()
    rows = []
    for i in ids:
        rows.append({"id": i, "resolved": i in solved, "secs": secs, "err": (errs or {}).get(i), "calls": 10})
    (d / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    if wheels is not None:
        (d / "wheelhouse_sha256.txt").write_text(wheels)
    return d


def decide(tmp_path, control, arm):
    m = _mod()
    return m.decide(m.load(control), m.load(arm), IDS)


BASE = set(IDS[:25])


@pytest.mark.parametrize("gain,verdict", [(4, "SHIP-ELIGIBLE"), (3, "NO"), (6, "SHIP-ELIGIBLE"), (0, "NO")])
def test_delta_threshold(tmp_path, gain, verdict):
    c = run_dir(tmp_path, "c", BASE)
    a = run_dir(tmp_path, "a", BASE | set(IDS[25:25 + gain]))
    r = decide(tmp_path, c, a)
    assert r["verdict"] == verdict and r["delta"] == gain and r["wins"] == gain and r["losses"] == 0, r


def test_paired_not_totals(tmp_path):
    """Wins and losses are paired per id: +6 wins and -2 losses is a delta of +4 (eligible), sign test reported."""
    c = run_dir(tmp_path, "c", BASE)
    a = run_dir(tmp_path, "a", (BASE - set(IDS[:2])) | set(IDS[30:36]))
    r = decide(tmp_path, c, a)
    assert (r["wins"], r["losses"], r["delta"], r["verdict"]) == (6, 2, 4, "SHIP-ELIGIBLE"), r
    assert r["sign_p"] == pytest.approx(37 / 256, abs=1e-4)


@pytest.mark.parametrize("secs,verdict", [(165.0, "SHIP-ELIGIBLE"), (165.2, "NO"), (120.0, "SHIP-ELIGIBLE")])
def test_wall_ratio_edge(tmp_path, secs, verdict):
    """1.1 x control passes exactly at the line (150 s -> 165 s), not above it."""
    c = run_dir(tmp_path, "c", BASE, secs=150.0)
    a = run_dir(tmp_path, "a", BASE | set(IDS[40:45]), secs=secs)
    r = decide(tmp_path, c, a)
    assert r["verdict"] == verdict, r


def test_new_crash_class_blocks(tmp_path):
    """A class the control never showed blocks the arm (the fastapi_13537 unknown-tool crash); timeouts are not a crash;
    a class both runs show is not new; an unmatched error is its own class."""
    c = run_dir(tmp_path, "c", BASE, errs={"t60": "Sandbox execution error: litellm.ContextWindowExceededError: x",
                                           "t61": "Agent exceeded session timeout (5.0 min)"})
    gain = BASE | set(IDS[40:46])
    a = run_dir(tmp_path, "a1", gain, errs={"t60": "maximum context length is 32768",
                                            "t62": "Agent exceeded session timeout (5.0 min)"})
    assert decide(tmp_path, c, a)["verdict"] == "SHIP-ELIGIBLE"
    a = run_dir(tmp_path, "a2", gain, errs={"t63": "Tool 'view.py' not found"})
    r = decide(tmp_path, c, a)
    assert r["verdict"] == "NO" and r["new_crash_classes"] == ["unknown_tool"], r
    a = run_dir(tmp_path, "a3", gain, errs={"t63": "EXC RuntimeError('boom')", "t64": "something new"})
    assert decide(tmp_path, c, a)["new_crash_classes"] == ["kernel_exception", "other_error"]


def test_invalid_pairs_are_never_decided(tmp_path):
    c = run_dir(tmp_path, "c", BASE)
    a = run_dir(tmp_path, "a", BASE | set(IDS[40:50]), ids=IDS[:-1])
    r = decide(tmp_path, c, a)
    assert r["verdict"] == "INVALID" and r["n_missing"] == 1, r
    a = run_dir(tmp_path, "a2", BASE | set(IDS[40:50]), wheels="def  vllm.whl\n")
    r = decide(tmp_path, c, a)
    assert r["verdict"] == "INVALID" and "wheel" in r["why"], r
    a = run_dir(tmp_path, "a3", BASE | set(IDS[40:50]), wheels=None)       # unrecorded: decided, flagged
    r = decide(tmp_path, c, a)
    assert r["verdict"] == "SHIP-ELIGIBLE" and r["wheels"] == "unrecorded", r


def test_crash_classes_match_replay_l4():
    """The four race-2 crash classes are replay_l4's own patterns (no drift between the race KPI and this rule)."""
    m = _mod()
    r = _mod(ROOT / "scripts" / "replay_l4.py", "replay_l4_for_ab")
    for k, rx in r.CRASH.items():
        assert m.CRASH[k].pattern == rx.pattern and m.CRASH[k].flags == rx.flags, k


def test_cli_on_real_kaggle_l4_runs(tmp_path):
    """The real paired runs (v4 and v9_eog, 29/74 each, pre-hash kernels): delta 0, so NO, and the PICK line says keep
    the control; v9_eog's context overflow is a new crash class against v4."""
    k = ROOT / "eval" / "kaggle"
    if not (k / "g4-l4-v4" / "results.jsonl").exists():
        pytest.skip("Kaggle-L4 outputs not present")
    r = subprocess.run([sys.executable, str(SCRIPT), str(k / "g4-l4-v4"), str(k / "g4-l4-v9-eog"), "--ids",
                        str(ROOT / "data" / "kaggle_valid_ids.txt")], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    line = r.stdout.splitlines()[0]
    verdict, name, blob = line.split("\t")
    got = json.loads(blob)
    assert (verdict, name) == ("NO", "g4-l4-v9-eog") and got["delta"] == 0 and got["resolved_control"] == got["resolved_arm"] == 29
    assert got["new_crash_classes"] == ["context_overflow"] and got["wheels"] == "unrecorded"
    assert r.stdout.strip().endswith("PICK none (keep the control)")


def test_pick_among_eligible_arms(tmp_path):
    """Two eligible arms: the larger delta wins; on equal deltas the lower wall ratio wins; none eligible keeps the
    control. INVALID arms are never picked."""
    c = run_dir(tmp_path, "c", BASE, secs=150.0)
    a = run_dir(tmp_path, "a", BASE | set(IDS[40:45]), secs=160.0)          # +5, 1.067
    b = run_dir(tmp_path, "b", BASE | set(IDS[40:46]), secs=164.0)          # +6, 1.093
    e = run_dir(tmp_path, "e", BASE | set(IDS[40:46]), secs=155.0)          # +6, 1.033
    bad = run_dir(tmp_path, "bad", BASE | set(IDS[40:60]), wheels="zzz  vllm.whl\n")

    def pick(*dirs):
        r = subprocess.run([sys.executable, str(SCRIPT), str(c), *map(str, dirs)], capture_output=True, text=True,
                           timeout=30)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip().splitlines()[-1]
    assert pick(a, b) == "PICK b"
    assert pick(a, b, e) == "PICK e"
    assert pick(bad, a) == "PICK a"
    assert pick(bad) == "PICK none (keep the control)"
