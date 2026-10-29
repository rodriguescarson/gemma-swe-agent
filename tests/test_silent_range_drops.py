"""eval/analysis/silent_range_drops.py on two small fixture traces: read_file calls whose argument keys are not a subset of
{filepath, start_line, end_line} (vLLM's gemma4 parser writes `start_line"`; the tool drops the range and answers status ok),
and the share of range reads done through `sed -n` in run_command."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("silent_range_drops", ROOT / "eval/analysis/silent_range_drops.py")
srd = importlib.util.module_from_spec(spec)
sys.modules["silent_range_drops"] = srd
spec.loader.exec_module(srd)


def step(name, args, status="ok", n=[0]):
    n[0] += 1
    obs = {"content": json.dumps({"status": status, "stdout": "x"}), "extra": {"tool_name": name}}
    return {"step_id": str(n[0]), "source": "agent",
            "tool_calls": [{"tool_call_id": f"call_{n[0]}", "function_name": name, "arguments": args}], "observation": obs}


def trace(*steps):
    head = [{"step_id": "1", "source": "system", "message": "s"}, {"step_id": "2", "source": "user", "message": "u"},
            {"step_id": "3", "source": "agent", "message": "thinking only", "observation": None}]
    return {"schema_version": "x", "steps": head + list(steps)}


# trace_a: 4 read_file calls, 2 garbled (both answered ok: silent), 1 clean range, 1 without a range; one grep
TRACE_A = trace(
    step("run_command", {"command": 'git grep -n "foo" -- "*.py" | head -n 20'}),
    step("read_file", {"filepath": "a.py", "start_line": 10, "end_line": 50}),
    step("read_file", {"filepath": "a.py", 'start_line"': 10, "end_line": 50}),
    step("read_file", {"filepath": "a.py", '"end_line"': 90, 'start_line"': 60}),
    step("read_file", {"filepath": "a.py"}),
)
# trace_b: 2 sed reads (one by pattern range), an in-place sed edit that is not a read, a clean range, one garbled call
# the tool rejected (no silent drop)
TRACE_B = trace(
    step("run_command", {"command": "sed -n '120,175p' a.py"}),
    step("run_command", {"command": "sed -n '/def f/,/^$/p' a.py | head -n 40"}),
    step("run_command", {"command": "sed -i 's/a/b/' a.py"}),
    step("read_file", {"filepath": "b.py", "start_line": 1, "end_line": 30}),
    step("read_file", {'filepath"': "b.py", "start_line": 1}, status="error"),
)


def make_run(root, name, traces, layout="results/traces"):
    d = root / name / layout
    d.mkdir(parents=True)
    for k, t in traces.items():
        (d / f"trace_{k}.json").write_text(json.dumps(t))
    return root / name


def test_scan_trace_counts_garbled_silent_and_ranged_reads():
    a = srd.scan_trace(TRACE_A)
    assert (a["read_file"], a["ranged"], a["garbled"], a["silent"], a["sed"]) == (4, 3, 2, 2, 0)
    assert a["garbled_keys"] == {'start_line"': 2, '"end_line"': 1}


def test_scan_trace_counts_sed_reads_and_a_rejected_garble_is_not_silent():
    b = srd.scan_trace(TRACE_B)
    assert (b["read_file"], b["ranged"], b["garbled"], b["silent"], b["sed"]) == (2, 2, 1, 0, 2)
    assert b["garbled_keys"] == {'filepath"': 1}


@pytest.mark.parametrize("cmd,is_read", [
    ("sed -n '120,175p' path/to/file.py", True),
    ('sed -n "120,175p" file.py', True),
    ("sed -n 120,175p file.py", True),
    ("sed -n '29p;71p' fastapi/_compat/v1.py", True),
    ("sed -n '/MARKDOWN =/,/\"\"\"/p' tests/test_markdown.py", True),
    ("cat -n f.py | sed -n '5,9p'", True),
    ("sed -n '$p' f.py", True),
    ("sed -i '29i ## 0.137.0' docs/release-notes.md", False),
    ("sed -i 's/a/b/' f.py", False),
    ("sed '120,175p' f.py", False),                      # no -n: prints the whole file, not a range read
    ("sed -i '3p' f.py", False),
    ("sed 's/a/b/p' f.py", False),
    ("sed -n 's/a/b/p' f.py", False),
    ("git grep -n 'sed -n' -- '*.md'", False),
    ("python3 -m pytest tests/test_x.py -q", False),
])
def test_sed_read_detection(cmd, is_read):
    assert srd.is_sed_read(cmd) is is_read, cmd


def test_collect_reads_results_traces_and_falls_back_to_traces(tmp_path):
    r1 = make_run(tmp_path, "run1", {"a": TRACE_A, "b": TRACE_B})
    r2 = make_run(tmp_path, "run2", {"b": TRACE_B}, layout="traces")
    runs1, bad1 = srd.collect(r1)
    runs2, bad2 = srd.collect(r2)
    assert [r["run"] for r in runs1] == ["a", "b"] and bad1 == 0
    assert [r["run"] for r in runs2] == ["b"] and bad2 == 0
    assert runs1[0]["garbled"] == 2 and runs1[1]["sed"] == 2


def test_collect_reports_unreadable_traces_instead_of_skipping_them(tmp_path):
    r = make_run(tmp_path, "run", {"a": TRACE_A})
    (r / "results/traces/trace_broken.json").write_text("{not json")
    runs, bad = srd.collect(r)
    assert [x["run"] for x in runs] == ["a"] and bad == 1


def test_summarise_totals_and_sed_share(tmp_path):
    runs, _ = srd.collect(make_run(tmp_path, "run", {"a": TRACE_A, "b": TRACE_B}))
    s = srd.summarise(runs)
    assert (s["runs"], s["runs_with_garbled"], s["garbled"], s["silent"]) == (2, 2, 3, 2)
    assert (s["read_file"], s["ranged_read_file"], s["sed_reads"]) == (6, 5, 2)
    # range reads = 5 ranged read_file calls (garbled ones included: the model asked for a range) + 2 sed reads
    assert s["range_reads"] == 7 and s["sed_share"] == pytest.approx(2 / 7)
    assert s["garbled_keys"] == {'start_line"': 2, '"end_line"': 1, 'filepath"': 1}


def test_summarise_with_no_range_reads_has_no_share():
    assert srd.summarise([])["sed_share"] is None


def test_main_prints_one_block_per_run_dir_and_writes_json(tmp_path, capsys):
    r1 = make_run(tmp_path, "g4-fix-a", {"a": TRACE_A})
    r2 = make_run(tmp_path, "g4-fix-b", {"b": TRACE_B})
    out = tmp_path / "out.json"
    srd.main([str(r1), str(r2), "--json", str(out)])
    text = capsys.readouterr().out
    assert "g4-fix-a" in text and "g4-fix-b" in text
    assert "garbled=2" in text and "silent=2" in text      # run a
    assert "sed_reads=2" in text                             # run b
    data = json.loads(out.read_text())
    assert [d["name"] for d in data] == ["g4-fix-a", "g4-fix-b"]
    assert data[0]["garbled"] == 2 and data[1]["sed_reads"] == 2 and data[0]["rows"][0]["run"] == "a"


def test_main_fails_on_a_directory_without_traces(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(SystemExit) as e:
        srd.main([str(tmp_path / "empty")])
    assert "no traces" in str(e.value)
