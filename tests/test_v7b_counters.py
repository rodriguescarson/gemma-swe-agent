"""The forensics counters v7b is judged by live in scripts/a6000/v7_counters.py. That file is on the hard no-touch list
while the GPU box runs v7, so it is used here read-only (its matcher and its CLI unchanged). These tests bind its
cap_refusals counter to what v7b's view.py really prints on the six-call loop (refuse, refuse, outline, refuse, refuse,
outline), produced by running v7b's helpers and stored the way the harness stores replies:

  * the four one-line refusals are still counted: v7b keeps v7's refusal text and the matcher looks for
    "read cap reached" (besides "search cap reached" and v6p-b's "SHARE SPENT");
  * an outline reply never reads as a view.py usage line (view_usage_calls is a must-be-zero counter), and the loop
    counter still sees a model that repeats the identical call, whatever the replies say;
  * the outline replies are NOT counted by today's matcher: they carry none of its three texts. For a v7 vs v7b read
    of refused reads they should be (each one is a refused read; uncounted, v7b's number falls by a third in a looping
    task with no change in behaviour). The matcher change, adding "outline only:" to RULES["cap_refusals"], is
    pre-registered below as a strict xfail: it waits for the no-touch list to lift, and the test turns into a failure
    the day the matcher learns the text, so the marker cannot outlive the fix. Until then a v7b screen adds the
    replies that contain "outline only:" to cap_refusals by hand.
Written before the change (strict test-first)."""
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
    assert c["cap_refusals"] == 4, c


def test_an_outline_is_not_a_usage_line_and_the_loop_is_still_seen(tmp_path):
    _, c = loop_run(tmp_path)
    assert c["view_usage_calls"] == 0 and c["literal_wrapper_commands"] == 0
    assert c["loops_ge5"] == 1                                          # 6 identical calls in a row, any replies


@pytest.mark.xfail(strict=True, reason="pre-registered: RULES['cap_refusals'] in scripts/a6000/v7_counters.py learns "
                   "'outline only:' once the no-touch list lifts (the box is running v7); then this passes and the "
                   "marker goes")
def test_every_refused_read_is_counted_outlines_included(tmp_path):
    _, c = loop_run(tmp_path)
    assert c["cap_refusals"] == 6, c
