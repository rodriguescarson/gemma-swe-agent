"""scripts/a6000/p2_lib.py: the pure logic of the P2 race (pre-registered in docs/v4h/GATE.md, 'P2 pre-registration').
Written before the code."""
import importlib.util, json, math, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "scripts" / "golden"))
spec = importlib.util.spec_from_file_location("p2_lib", ROOT / "scripts" / "a6000" / "p2_lib.py")
p2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(p2)

ARMS = ["v4h2", "v6p", "v6p-think"]


def test_items_keep_task_order_and_rotate_arm_order():
    items = p2.build_items(["a", "b", "c", "d"], ARMS)
    assert [t for t, _ in items] == ["a"] * 3 + ["b"] * 3 + ["c"] * 3 + ["d"] * 3
    firsts = [items[i][1] for i in range(0, 12, 3)]
    assert firsts == ["v4h2", "v6p", "v6p-think", "v4h2"]
    for k in range(4):
        assert sorted(a for _, a in items[3 * k:3 * k + 3]) == sorted(ARMS)


def _row(latency, target, status=200):
    return {"status": status, "latency_s": latency, "l4_target_s": target}


def test_slowdown_uses_max_of_latency_and_model_time():
    rows = [_row(2.0, 4.0), _row(6.0, 3.0), _row(1.0, 1.0), {"status": 500, "latency_s": 9, "l4_target_s": 99}]
    s = p2.slowdown(rows)
    assert math.isclose(s["effective"], (4 + 6 + 1) / (4 + 3 + 1)) and math.isclose(s["raw"], (2 + 6 + 1) / (4 + 3 + 1)) and s["calls"] == 3


def test_choose_concurrency_takes_the_highest_level_within_1_15():
    assert p2.choose_concurrency({1: 1.02, 2: 1.08, 3: 1.14, 4: 1.30}) == (3, 1.0)
    assert p2.choose_concurrency({1: 1.02, 2: 1.10, 3: 1.40, 4: 1.12}) == (4, 1.0)   # highest level that passes, as registered
    assert p2.choose_concurrency({1: 1.0, 2: 1.15, 3: 1.2, 4: 1.3}) == (2, 1.0)      # 1.15 is allowed


def test_choose_concurrency_when_two_is_too_slow_maximises_work_per_second_and_scales_the_cap():
    c, scale = p2.choose_concurrency({1: 1.05, 2: 1.32, 3: 1.6, 4: 1.9})        # T/S: 2/1.32=1.52  3/1.6=1.88  4/1.9=2.11 -> 4
    assert c == 4 and math.isclose(scale, 1 / 1.9)
    c, scale = p2.choose_concurrency({1: 1.3, 2: 1.4, 3: 2.4, 4: 3.4})          # 2/1.4=1.43  3/2.4=1.25  4/3.4=1.18 -> 2
    assert c == 2 and math.isclose(scale, 1 / 1.4)
    assert p2.choose_concurrency({1: 1.0, 2: 1.4, 3: 2.1, 4: 2.8})[0] == 2        # all equal 1.43: tie -> the smaller T


def test_choose_concurrency_with_missing_or_nan_levels_does_not_crash():
    assert p2.choose_concurrency({1: 1.4}) == (1, 1.0)               # smoke case: only one level measured, none within 1.15 -> the lowest level
    assert p2.choose_concurrency({1: float("nan"), 2: float("nan")})[0] == 2


def test_scale_is_clamped_to_the_helpers_range():
    assert p2.choose_concurrency({1: 1.0, 2: 9.0, 3: 9.0, 4: 9.0})[1] == 0.2


def test_projection_hours():
    h = p2.project_hours(m_seconds=200, c=2, scale=1.0, n_tasks=200)
    assert math.isclose(h, 200 * (2 * 200 + 360) / 2 / 3600)
    assert math.isclose(p2.project_hours(200, 2, 1 / 1.5, 200), 200 * (2 * 200 + 360) * 1.5 / 2 / 3600)   # addendum 1: every item x S


def test_plan_stage():
    assert p2.plan_stage(11.9) == 200 and p2.plan_stage(12.01) == 100


def test_wilson_and_sign_test():
    lo, hi = p2.wilson(17, 57)
    assert abs(lo - 0.195) < 0.005 and abs(hi - 0.427) < 0.005          # the GATE.md table for v4h2 on holdout57
    assert math.isclose(p2.sign_p(5, 0), 0.0625) and p2.sign_p(0, 0) == 1.0 and math.isclose(p2.sign_p(10, 1), 0.01171875)


def test_verdicts():
    assert p2.verdict(wins=9, losses=2, cap_gap=0.0) == "BETTER"             # net +7, p = 0.065
    assert p2.verdict(wins=2, losses=9, cap_gap=0.0) == "WORSE"
    assert p2.verdict(wins=2, losses=9, cap_gap=0.12) == "UNRESOLVED"        # more cap hits: not "worse"
    assert p2.verdict(wins=7, losses=1, cap_gap=0.2) == "BETTER"             # a BETTER verdict stands (net +6, p = 0.07)
    assert p2.verdict(wins=5, losses=3, cap_gap=0.0) == "NO EVIDENCE"
    assert p2.verdict(wins=6, losses=1, cap_gap=0.0) == "NO EVIDENCE"        # net +5 but p = 0.125
    assert p2.verdict(wins=8, losses=2, cap_gap=0.0) == "NO EVIDENCE"        # net +6 but p = 0.109
    assert p2.verdict(wins=3, losses=3, cap_gap=0.15) == "UNRESOLVED"
    assert p2.verdict(wins=1, losses=2, cap_gap=0.09) == "NO EVIDENCE"       # under 10 points


# ---------------------------------------------------------------------------------------------------- p2_race
spec2 = importlib.util.spec_from_file_location("p2_race", ROOT / "scripts" / "a6000" / "p2_race.py")
race = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(race)


def test_budget_flags_come_from_the_bundles_eval_config():
    f = race.budget_flags(str(ROOT / "submissions" / "v6p"))
    assert f == "--max-time-minutes 5.0 --max-tool-calls 70 --max-turns 150 --timeout-seconds 180"


def test_item_script_is_the_race_command_for_one_task():
    s = race.item_script("v6p", "arrow_0fe5f06", port=8001, scale=1.0)
    for frag in ("run_eval_pallets.py eval", "--tasks /root/h/tasks.jsonl", "--snapshots-dir /root/h/snapshots",
                 "--sandbox subprocess", "--concurrency 1", "--task-ids arrow_0fe5f06", "--results-dir /out/items/v6p/arrow_0fe5f06",
                 "--submission-dir /tmp/bundle_v6p", "OPENAI_BASE_URL=http://host.docker.internal:8001/v1", "G4_L4_SCALE=1.0",
                 "G4_WHEELHOUSE=/root/h/wheels", "G4_COMPACTION=1", "G4_NO_EDITABLE=1", "--max-time-minutes 5.0"):
        assert frag in s, frag


def test_item_script_passes_the_scale_as_the_harness_env_not_in_the_flags():
    s = race.item_script("v6p", "t1", port=8001, scale=0.75)
    assert "G4_L4_SCALE=0.75" in s and "--max-time-minutes 5.0" in s


def test_pending_skips_items_with_results(tmp_path):
    (tmp_path / "items" / "v6p" / "a").mkdir(parents=True)
    (tmp_path / "items" / "v6p" / "a" / "task_results.jsonl").write_text('{"instance_id": "a"}\n')
    items = [("a", "v6p"), ("a", "v4h2"), ("b", "v6p")]
    assert race.pending(items, str(tmp_path)) == [("a", "v4h2"), ("b", "v6p")]


def test_items_dir_is_configurable_for_the_probe_levels(tmp_path):
    s = race.item_script("v6p", "t1", port=8001, scale=1.0, items="probe_T2")
    assert "--results-dir /out/probe_T2/v6p/t1" in s and "/out/items/" not in s
    (tmp_path / "probe_T2" / "v6p" / "t1").mkdir(parents=True)
    (tmp_path / "probe_T2" / "v6p" / "t1" / "task_results.jsonl").write_text("{}\n")
    assert race.pending([("t1", "v6p"), ("t2", "v6p")], str(tmp_path), items_dir="probe_T2") == [("t2", "v6p")]
    assert race.pending([("t1", "v6p")], str(tmp_path)) == [("t1", "v6p")]          # default dir untouched


# ------------------------------------------------------------------------------- addendum 2 (per-arm scale, stage 1a)
def test_arm_scale_parsing_and_use():
    assert race.parse_arm_scales(["v6p=0.6", "v4h2=1.0"]) == {"v6p": 0.6, "v4h2": 1.0}
    assert race.parse_arm_scales([]) == {}
    s = race.item_script("v6p", "t1", port=8001, scale=race.scale_for("v6p", {"v6p": 0.6}, 1.0))
    assert "G4_L4_SCALE=0.6" in s
    assert race.scale_for("v4h2", {"v6p": 0.6}, 1.0) == 1.0


def test_arm_scale_from_s():
    assert p2.arm_scale(1.05) == 1.0 and p2.arm_scale(1.15) == 1.0
    assert math.isclose(p2.arm_scale(1.6), 1 / 1.6) and p2.arm_scale(9.0) == 0.2 and p2.arm_scale(float("nan")) == 1.0


def test_decide_picks_the_level_with_the_smaller_projected_hours():
    # m = mean item wall s at that level, S = effective slowdown, per arm; the think arm is assumed (v6p-like, m 360)
    per = {1: {"v4h2": {"S": 1.03, "m": 150}, "v6p": {"S": 1.40, "m": 250}},
           2: {"v4h2": {"S": 1.10, "m": 160}, "v6p": {"S": 1.57, "m": 285}}}
    d = p2.decide(per, n_tasks=100)
    f1 = 100 * (150 * 1.0 + 250 * 1.40 + 360 * 1.40) / 1 / 3600
    f2 = 100 * (160 * 1.0 + 285 * 1.57 + 360 * 1.57) / 2 / 3600
    assert d["C"] == 2 and math.isclose(d["H"][1], f1) and math.isclose(d["H"][2], f2)
    assert d["scales"] == {"v4h2": 1.0, "v6p": 1 / 1.57, "v6p-think": 1 / 1.57}


def test_decide_tie_goes_to_the_smaller_c():
    per = {1: {"v4h2": {"S": 1.0, "m": 100}, "v6p": {"S": 1.0, "m": 100}}, 2: {"v4h2": {"S": 1.0, "m": 250}, "v6p": {"S": 1.0, "m": 250}}}
    assert p2.decide(per, n_tasks=10, think_m=100)["C"] == 1


def test_plan_stage_ladder():
    assert p2.plan_stage_ladder({200: 11.0, 100: 5.5, 50: 2.7}) == 200
    assert p2.plan_stage_ladder({200: 20.0, 100: 10.0, 50: 5.0}) == 100
    assert p2.plan_stage_ladder({200: 40.0, 100: 20.0, 50: 10.0}) == 50
    assert p2.plan_stage_ladder({200: 90.0, 100: 45.0, 50: 22.0}) == 50          # even 50 over 12 h: stage 1a anyway
