"""The forensics tooling learns v7d's reply (docs/a6000/V7C_FAILURE_ANALYSIS.md, step 1): view.py's SHOWN AGAIN line.

  * scripts/a6000/forensics_lib.py classifies a run_command whose stdout carries "SHOWN AGAIN" as ours by design (like
    the ALREADY SHOWN refusal before it), and a loop of such calls as the model's (the note is not a refusal);
  * scripts/a6000/v7_counters.py gets one more reported counter, repeat_reads (the SHOWN AGAIN replies), right after
    repeat_outlines; it is never gated (the default must-be-zero list is unchanged) and the CLI prints it;
  * the committed v5h2 P4 traces and v7's clean task read 0 (tests/test_v7_counters.py's control dict carries the key).
The box runs v7_counters.py after every step and pulls this branch between tasks, so the change must be additive.
Written before the code (strict test-first)."""
import json, subprocess, sys
from pathlib import Path

from test_a6000_forensics import _step, _trace, fx, ok
from test_v7_counters import MUST_ZERO, clean_steps, rc, vc, write_run
from test_v7_helpers import task, view
import test_v7_helpers as v7h

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "submissions" / "v7d" / "skills" / "swe-tools" / "scripts"
AGAIN = ("SHOWN AGAIN: a.py lines 1-120 are unchanged since they were shown earlier in this task, so use them now instead "
         "of viewing them again\n1| import os\n2| x = 1\n")


def test_forensics_classifies_the_shown_again_reply_as_ours_by_design():
    v = fx.classify("run_command", {"command": "python3 /tmp/swe/view.py a.py 1 120"}, ok(AGAIN))
    assert v.mechanism == "view.py repeat shown again (ours, by design)" and v.owner == "model", v
    old = fx.classify("run_command", {"command": "python3 /tmp/swe/view.py a.py 1 120"}, ok("ALREADY SHOWN: a.py lines 1-120, unchanged since."))
    assert old.mechanism == "view.py repeat refused (ours, by design)"                # unchanged for v4h6g..v7c traces
    plain = fx.classify("run_command", {"command": "python3 /tmp/swe/view.py a.py 1 120"}, ok("1| import os\n2| x = 1\n"))
    assert plain.mechanism == "ok"


def test_forensics_names_a_loop_of_shown_again_replies_and_charges_it_to_the_model():
    steps = [_step("fixer", "run_command", {"command": "python3 /tmp/swe/view.py a.py 1 120"}, ok(AGAIN), i) for i in range(5)]
    loops = fx.find_loops(_trace(steps))
    assert len(loops) == 1 and loops[0].reply_kind == "our repeat note (SHOWN AGAIN)" and loops[0].owner == "model", loops
    steps = [_step("fixer", "run_command", {"command": "python3 /tmp/swe/view.py a.py 1 120"}, ok("ALREADY SHOWN: a.py lines 1-120"), i) for i in range(5)]
    assert fx.find_loops(_trace(steps))[0].reply_kind == "our repeat refusal (ALREADY SHOWN)"   # unchanged


def test_repeat_reads_is_its_own_counter_after_repeat_outlines_and_is_not_gated(tmp_path, monkeypatch):
    monkeypatch.setattr(v7h, "SCRIPTS", SCRIPTS)
    t = task(tmp_path)
    first = view(t, "pkg/e.py", "4", "8")
    reps = [view(t, "pkg/e.py", "4", "8") for _ in range(6)]                        # again, again, outline, again, again, outline
    steps = clean_steps() + [rc("fixer", "python3 /tmp/swe/view.py pkg/e.py 4 8", ok(o)) for o in [first] + reps]
    c = vc.counters(str(write_run(tmp_path / "run", {"t": (steps, True)})), "v7")
    assert vc.COUNTERS.index("repeat_reads") == vc.COUNTERS.index("repeat_outlines") + 1
    assert (c["repeat_reads"], c["repeat_outlines"], c["cap_refusals"]) == (4, 2, 0), {k: c[k] for k in vc.COUNTERS}
    assert all(c[k] == 0 for k in MUST_ZERO) and vc.verdict(c, MUST_ZERO)["pass"] is True
    assert [e["task"] for e in c["examples"]["repeat_reads"]] == ["t", "t", "t"]       # three examples, as for every counter
    assert "SHOWN AGAIN" in c["examples"]["repeat_reads"][0]["reply"]


def test_a_clean_task_reads_zero_and_the_cli_prints_the_column(tmp_path):
    run_dir = write_run(tmp_path / "r", {"clean": (clean_steps(), True)})
    c = vc.counters(str(run_dir), "v7")
    assert c["repeat_reads"] == 0 and all(c[k] == 0 for k in vc.COUNTERS)
    out = tmp_path / "c.json"
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "a6000" / "v7_counters.py"), str(run_dir), "--arm", "v7", "--json", str(out)],
                       capture_output=True, text=True)
    assert p.returncode == 0 and "must-be-zero verdict: **PASS" in p.stdout, p.stdout + p.stderr
    header = p.stdout.splitlines()[0]
    cols = [x.strip() for x in header.strip("|").split("|")]
    assert cols == ["tasks", "solved"] + list(vc.COUNTERS) and "repeat_reads" in cols
    d = json.loads(out.read_text())
    assert d["counters"]["repeat_reads"] == 0 and d["verdict"]["must_zero"] == list(MUST_ZERO)
