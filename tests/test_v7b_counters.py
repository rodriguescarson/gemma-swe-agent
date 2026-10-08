"""The forensics counters v7b is judged by live in scripts/a6000/v7_counters.py. These tests bind them to what v7b's
view.py really prints on the six-call loop past the read cap (refuse, refuse, outline, refuse, refuse, outline),
produced by running v7b's helpers and stored the way the harness stores replies:

  * the four one-line refusals are counted under cap_refusals: v7b keeps v7's refusal text and the matcher looks for
    "read cap reached" (besides "search cap reached" and v6p-b's "SHARE SPENT");
  * the two outline replies are counted under repeat_outlines (2026-10-08, v7c pre-registration in
    docs/GAPS_2026-10-06.md: the counters split; "outline only:" moved out of cap_refusals into its own counter, so a
    v7c run, where the outline answers identical re-reads and no cap exists, does not read as cap refusals). A v7b
    screen's refused reads are cap_refusals + repeat_outlines (4 + 2 here); before the split they were cap_refusals 6;
  * an outline reply never reads as a view.py usage line (view_usage_calls is a must-be-zero counter), and the loop
    counter still sees a model that repeats the identical call, whatever the replies say.
Updated before the matcher changed (strict test-first)."""
import pytest

import test_v7_helpers as v7h
from test_v7_counters import ok, rc, vc, write_run
from test_v7_helpers import run, task, view
from test_v7b_helpers import READ_CAP, SCRIPTS


@pytest.fixture(autouse=True)
def _v7b_scripts(monkeypatch):
    monkeypatch.setattr(v7h, "SCRIPTS", SCRIPTS)


def loop_run(tmp_path):
    """v7b's real replies to the identical refused read, six times in a row, as a stored one-task run."""
    t = task(tmp_path)
    for i in range(14):
        view(t, "m.py", str(10 * i + 101), str(10 * i + 105))
    outs = [run(t, "view.py", "pkg/e.py", "4", "8")[1] for _ in range(6)]
    steps = [rc("fixer", "python3 /tmp/swe/view.py pkg/e.py 4 8", ok(o)) for o in outs]
    return outs, vc.counters(str(write_run(tmp_path / "run", {"t": (steps, False)})), "v7")


def test_the_one_line_refusals_are_still_counted(tmp_path):
    outs, c = loop_run(tmp_path)
    assert [o.strip() == READ_CAP for o in outs] == [True, True, False, True, True, False], outs
    assert sum("outline only:" in o for o in outs) == 2
    assert c["cap_refusals"] == 4, c                                   # the one-line refusals only, not the outlines


def test_an_outline_is_not_a_usage_line_and_the_loop_is_still_seen(tmp_path):
    _, c = loop_run(tmp_path)
    assert c["view_usage_calls"] == 0 and c["literal_wrapper_commands"] == 0
    assert c["loops_ge5"] == 1                                          # 6 identical calls in a row, any replies


def test_the_outline_replies_count_under_repeat_outlines(tmp_path):
    _, c = loop_run(tmp_path)
    assert c["repeat_outlines"] == 2 and c["cap_refusals"] == 4, c
    assert c["cap_refusals"] + c["repeat_outlines"] == 6                # every refused read is still counted once
