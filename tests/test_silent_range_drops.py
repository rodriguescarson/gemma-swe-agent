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


def raw_step(name, args, observation, n=[0]):
    n[0] += 1
    return {"step_id": str(n[0]), "source": "agent",
            "tool_calls": [{"tool_call_id": f"call_{n[0]}", "function_name": name, "arguments": args}],
            "observation": observation}


def step(name, args, status="ok"):
    return raw_step(name, args, {"content": json.dumps({"status": status, "stdout": "x"}), "extra": {"tool_name": name}})


# what ADK answers when a mandatory argument is missing: a JSON object with an error and no status word
MISSING_FILEPATH = {"content": json.dumps({"error": "Invoking `read_file()` failed as the following mandatory input "
                                                    "parameters are not present:\nfilepath\nYou could retry calling this tool."}),
                    "extra": {"tool_name": "read_file"}}


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


# trace_c: nothing that reads a range (a grep and a read_file without one): the sed share is undefined
TRACE_C = trace(
    step("run_command", {"command": "git grep -n foo | head -n 20"}),
    step("read_file", {"filepath": "c.py"}),
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


OK = {"content": json.dumps({"status": "ok"})}


def one_read(args, observation=OK):
    """scan_trace over a single agent step with one read_file call."""
    return srd.scan_trace({"steps": [raw_step("read_file", args, observation)]})


@pytest.mark.parametrize("key", [
    'start_line"', 'end_line"', '"end_line"', "'start_line'", "`end_line`",
    'start_line\\"',            # the stray quote escaped with a backslash: start_line\"
    '\\"end_line\\"',          # \"end_line\"
    "start_line ",
])
def test_a_range_key_is_recognised_through_any_stray_characters(key):
    r = one_read({"filepath": "a.py", key: 5})
    assert (r["read_file"], r["ranged"], r["garbled"], r["silent"]) == (1, 1, 1, 1), key
    assert r["garbled_keys"] == {key: 1}


@pytest.mark.parametrize("key", ["limit", "encoding", "file_path_x", "Start_Line", "startline"])
def test_a_foreign_extra_key_is_garbled_but_does_not_ask_for_a_range(key):
    r = one_read({"filepath": "a.py", key: 5})
    assert (r["ranged"], r["garbled"], r["silent"]) == (0, 1, 1), key


def test_the_clean_keys_are_neither_garbled_nor_silent():
    r = one_read({"filepath": "a.py", "start_line": 1, "end_line": 9})
    assert (r["ranged"], r["garbled"], r["silent"], r["garbled_keys"]) == (1, 0, 0, {})


def test_a_read_file_call_keyed_file_path_is_garbled_but_ADK_rejects_it_so_it_is_not_silent():
    # `read_file(filepath, ...)`: file_path is an unknown key and filepath is missing, ADK answers {"error": ...} with no status
    r = one_read({"file_path": "a.py", "start_line": 3}, MISSING_FILEPATH)
    assert (r["read_file"], r["ranged"], r["garbled"], r["silent"]) == (1, 1, 1, 0)
    assert r["garbled_keys"] == {"file_path": 1}
    r = one_read({"file_path": "a.py"}, MISSING_FILEPATH)
    assert (r["ranged"], r["garbled"], r["silent"]) == (0, 1, 0)


@pytest.mark.parametrize("observation", [
    None,                                                  # no observation was recorded for the call
    {},                                                    # an observation without content
    {"content": None},
    {"content": "plain text, not JSON"},
    {"content": json.dumps(["ok"])},                      # JSON that is not an object
    {"content": json.dumps({"status": "error"})},
    {"content": json.dumps({"stdout": "no status word"})},
])
def test_a_garbled_call_is_silent_only_when_the_tool_said_status_ok(observation):
    s = raw_step("read_file", {"filepath": "a.py", 'start_line"': 1}, observation)
    r = srd.scan_trace({"steps": [s]})
    assert (r["garbled"], r["silent"]) == (1, 0)


def test_status_of_reads_the_status_word_of_an_ok_observation():
    assert srd.status_of({"content": json.dumps({"status": "ok"})}) == "ok"


def test_only_agent_steps_are_scanned():
    call = [{"function_name": "read_file", "arguments": {"filepath": "a.py", 'start_line"': 1}}]
    d = {"steps": [{"source": "user", "tool_calls": call}, {"source": "system", "tool_calls": call}]}
    assert srd.scan_trace(d)["garbled"] == 0
    d["steps"].append({"source": "agent", "tool_calls": call, "observation": None})
    assert srd.scan_trace(d)["garbled"] == 1


def test_a_trace_without_steps_or_tool_calls_scans_to_zeros():
    for d in ({}, {"steps": None}, {"steps": []}, {"steps": [{"source": "agent"}, {"source": "agent", "tool_calls": None}]}):
        r = srd.scan_trace(d)
        assert (r["read_file"], r["ranged"], r["garbled"], r["silent"], r["sed"], r["garbled_keys"]) == (0, 0, 0, 0, 0, {})


# The rule (is_sed_read's docstring): a read is `sed -n` (quiet, no in-place edit) whose script has a print command `p`
# over a line number, `$`, or a range (`A,B`, line or /pattern/ ends), and that reads a file: directly or through `cat f |`.
# A lone /pattern/p is a search, `sed s///p` is an edit, a pipe from any other program filters program output.
@pytest.mark.parametrize("cmd,is_read", [
    # reads: line ranges, flag spellings, quoting
    ("sed -n '5,10p' f", True),
    ("sed -ne '5,10p' f", True),
    ("sed -n -e '5,10p' f", True),
    ("sed -En '5,10p' f", True),
    ("sed -nE '5,10p' f", True),
    ("sed --quiet '5,10p' f", True),
    ("sed -n '120,175p;175q' f", True),                  # print then quit early
    ("sed -n '120,175{p;q}' f", True),
    ("sed -n '120,175p' path/to/file.py", True),
    ('sed -n "120,175p" file.py', True),
    ("sed -n 120,175p file.py", True),
    ("sed -n '29p;71p' fastapi/_compat/v1.py", True),   # single lines by number
    ("sed -n '$p' f.py", True),
    ("sed -n '/MARKDOWN =/,/\"\"\"/p' tests/test_markdown.py", True),   # a range between two patterns
    ("sed -n '/def f/,/^$/p' a.py | head -n 40", True),                # sed first, its output piped on
    ("cd pkg && sed -n '5,10p' f", True),
    ("git grep -n x | head; sed -n '5,10p' f", True),
    # not reads: in-place edits, in every flag spelling
    ("sed -i '29i ## 0.137.0' docs/release-notes.md", False),
    ("sed -i 's/a/b/' f.py", False),
    ("sed -i '3p' f.py", False),
    ("sed -i -n '3p' f", False),
    ("sed -ni '3p' f", False),
    ("sed -in '3p' f", False),
    ("sed -i.bak -n '5,10p' f", False),
    ("sed --in-place -n '5,10p' f", False),
    # not reads: a search by pattern, a substitution, no -n
    ("sed -n '/a/p' f", False),
    ("sed -n '/def f/p' a.py", False),
    ("sed '120,175p' f.py", False),                      # no -n: prints the whole file, not a range read
    ("sed 's/a/b/p' f.py", False),
    ("sed -n 's/a/b/p' f.py", False),
    # a pipe from cat or nl of a file is still a read of that file
    ("cat fastapi/routing.py | sed -n '330,370p'", True),
    ("cat -n f.py | sed -n '5,9p'", True),
    ("cat -A rich/cells.py | sed -n '10p'", True),
    ("cat f | sed -n '1p'", True),
    ("cd pkg && nl -ba f.py | sed -n '5,9p;9q'", True),
    # not reads: a pipe into sed filters program output, not a file
    ("git log -p x.py | sed -n '1p'", False),
    ("git show HEAD:f.py | sed -n '5,10p'", False),
    ("python3 x.py 2>&1 | sed -n '120,175p;175q'", False),
    ("git grep -n foo | head -n 5 | sed -n '2p'", False),
    ("cat a.py | tee out.txt | sed -n '5,9p'", False),   # tee sits between: program output again
    ("cat | sed -n '1p'", False),                         # cat with no file reads stdin
    ("cat <<EOF | sed -n '1p'", False),
    ("echo x; python3 y.py | sed -n '1,5p'", False),
    # `||` is an or, not a pipe
    ("test -f f || sed -n '5,10p' g", True),
    # not sed at all
    ("git grep -n 'sed -n' -- '*.md'", False),
    ("python3 -m pytest tests/test_x.py -q", False),
    ("", False),
])
def test_sed_read_detection(cmd, is_read):
    assert srd.is_sed_read(cmd) is is_read, cmd


def test_sed_read_detection_tolerates_a_missing_or_non_string_command():
    assert srd.is_sed_read(None) is False and srd.is_sed_read(["sed", "-n", "5p"]) is False


def test_collect_reads_results_traces_and_falls_back_to_traces(tmp_path):
    r1 = make_run(tmp_path, "run1", {"a": TRACE_A, "b": TRACE_B})
    r2 = make_run(tmp_path, "run2", {"b": TRACE_B}, layout="traces")
    runs1, bad1 = srd.collect(r1)
    runs2, bad2 = srd.collect(r2)
    assert [r["run"] for r in runs1] == ["a", "b"] and bad1 == 0
    assert [r["run"] for r in runs2] == ["b"] and bad2 == 0
    assert runs1[0]["garbled"] == 2 and runs1[1]["sed"] == 2


def test_collect_prefers_results_traces_when_both_layouts_exist(tmp_path):
    r = make_run(tmp_path, "run", {"a": TRACE_A})
    make_run(tmp_path, "run", {"x": TRACE_B, "y": TRACE_B}, layout="traces")      # same run dir, second layout
    assert (r / "traces/trace_x.json").exists() and (r / "results/traces/trace_a.json").exists()
    runs, bad = srd.collect(r)
    assert [x["run"] for x in runs] == ["a"] and bad == 0


def test_collect_falls_back_to_traces_only_when_results_traces_has_no_trace_files(tmp_path):
    r = make_run(tmp_path, "run", {"x": TRACE_B}, layout="traces")
    (r / "results/traces").mkdir(parents=True)                                    # exists but holds no trace_*.json
    (r / "results/traces/notes.txt").write_text("not a trace")
    runs, bad = srd.collect(r)
    assert [x["run"] for x in runs] == ["x"] and bad == 0


def test_collect_reports_unreadable_traces_instead_of_skipping_them(tmp_path):
    r = make_run(tmp_path, "run", {"a": TRACE_A})
    (r / "results/traces/trace_broken.json").write_text("{not json")
    runs, bad = srd.collect(r)
    assert [x["run"] for x in runs] == ["a"] and bad == 1


@pytest.mark.parametrize("body", [
    "null", "[]", "[1, 2]", '"a string"', "42", "true",              # valid JSON, not an object
    '{"steps": [null]}', '{"steps": "abc"}', '{"steps": [{"source": "agent", "tool_calls": [null]}]}',   # not step objects
])
def test_a_trace_that_is_valid_json_but_not_a_trace_object_is_unreadable_not_a_crash(tmp_path, body):
    r = make_run(tmp_path, "run", {"a": TRACE_A})
    (r / "results/traces/trace_odd.json").write_text(body)
    runs, bad = srd.collect(r)
    assert [x["run"] for x in runs] == ["a"] and bad == 1, body


def test_an_unreadable_file_is_counted_whatever_is_wrong_with_it(tmp_path):
    r = make_run(tmp_path, "run", {"a": TRACE_A})
    d = r / "results/traces"
    (d / "trace_binary.json").write_bytes(b"\xff\xfe\x00 not utf-8")
    (d / "trace_empty.json").write_text("")
    (d / "trace_dir.json").mkdir()                                          # a directory where a file is expected
    runs, bad = srd.collect(r)
    assert [x["run"] for x in runs] == ["a"] and bad == 3


def test_a_trace_object_without_steps_is_readable_and_counts_zero(tmp_path):
    r = make_run(tmp_path, "run", {"empty": {}, "nosteps": {"steps": None}})
    runs, bad = srd.collect(r)
    assert [(x["run"], x["read_file"], x["sed"]) for x in runs] == [("empty", 0, 0), ("nosteps", 0, 0)] and bad == 0


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


def test_main_prints_the_exact_report_block_per_run_dir_and_writes_json(tmp_path, capsys):
    r1 = make_run(tmp_path, "g4-fix-a", {"a": TRACE_A})                     # garbled + silent, no sed: share 0.0%
    r2 = make_run(tmp_path, "g4-fix-b", {"b": TRACE_B})                     # 2 sed reads + 2 ranged read_file: share 50.0%
    r3 = make_run(tmp_path, "g4-fix-c", {"c": TRACE_C})                     # no range reads at all: share n/a
    (r3 / "results/traces/trace_null.json").write_text("null")             # one unreadable trace
    out = tmp_path / "out.json"
    srd.main([str(r1), str(r2), str(r3), "--json", str(out)])
    assert capsys.readouterr().out == (
        "g4-fix-a: runs=1 unreadable=0\n"
        "  read_file=4 ranged_read_file=3 garbled=2 silent=2 runs_with_garbled=1\n"
        "  sed_reads=0 range_reads=3 sed_share=0.0%\n"
        "  garbled keys: 'start_line\"' x2, '\"end_line\"' x1\n"
        "g4-fix-b: runs=1 unreadable=0\n"
        "  read_file=2 ranged_read_file=2 garbled=1 silent=0 runs_with_garbled=1\n"
        "  sed_reads=2 range_reads=4 sed_share=50.0%\n"
        "  garbled keys: 'filepath\"' x1\n"
        "g4-fix-c: runs=1 unreadable=1\n"
        "  read_file=1 ranged_read_file=0 garbled=0 silent=0 runs_with_garbled=0\n"
        "  sed_reads=0 range_reads=0 sed_share=n/a\n"
        "  garbled keys: none\n")
    data = json.loads(out.read_text())
    assert [d["name"] for d in data] == ["g4-fix-a", "g4-fix-b", "g4-fix-c"]
    assert data[0]["garbled"] == 2 and data[1]["sed_reads"] == 2 and data[0]["rows"][0]["run"] == "a"
    assert [d["sed_share"] for d in data] == [0.0, 0.5, None] and [d["unreadable"] for d in data] == [0, 0, 1]


def test_main_fails_on_a_directory_without_traces(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(SystemExit) as e:
        srd.main([str(tmp_path / "empty")])
    assert "no traces" in str(e.value)
