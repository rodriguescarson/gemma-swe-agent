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


def test_p4_arm_choice_best_non_reference_else_v6p():
    c = lambda net6, net6t: {"v6p": {"wins": 5 + net6, "losses": 5}, "v6p-think": {"wins": 5 + net6t, "losses": 5}}
    assert ap.choose_p4_arm(c(3, 1)) == "v6p"
    assert ap.choose_p4_arm(c(1, 4)) == "v6p-think"
    assert ap.choose_p4_arm(c(-2, -1)) == "v6p"                                    # neither beats the reference: the planned first L4 run
    assert ap.choose_p4_arm(c(2, 2)) == "v6p"                                      # tie -> v6p
    assert ap.choose_p4_arm({}) == "v6p"


def test_pooling_adds_the_paired_counts_and_flags_heterogeneity():
    a = {"wins": 6, "losses": 2}; b = {"wins": 1, "losses": 7}
    p = ap.pool(a, b)
    assert p["wins"] == 7 and p["losses"] == 9 and p["net"] == -2 and p["heterogeneous"] is True    # nets +4 and -6 differ by >= 5
    assert ap.pool({"wins": 5, "losses": 3}, {"wins": 4, "losses": 3})["heterogeneous"] is False


def test_infra_error_detection():
    f = ap.is_infra_error
    assert f("litellm.APIConnectionError: OpenAIException - Connection error.")
    assert f("litellm.InternalServerError: 503 Service Unavailable") and f("Connection refused")
    assert not f(None) and not f("Agent exceeded session timeout (5.0 min)") and not f("Agent exceeded turns budget (150 turns)")
    assert not f("Tool 'python3 /tmp/swe/edit.py' not found")           # a bundle behaviour (the heredoc-as-tool-name crash), not infrastructure
