"""scripts/a6000/p3_run.py and p3_build.py: the P3 pass (one pass, capturing every call, resumable) and the SFT build from what finished.
Written before the code (docs/v4h/GATE.md, P2 addendum 4, step 4)."""
import importlib.util, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "scripts" / "golden"))


def _mod(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "a6000" / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_p3_arm_comes_from_the_choice_file_default_v6p(tmp_path):
    run = _mod("p3_run")
    assert run.chosen_arm(str(tmp_path / "none.json")) == "v6p"
    f = tmp_path / "c.json"; f.write_text(json.dumps({"p3_arm": "v4h2"}))
    assert run.chosen_arm(str(f)) == "v4h2"


def test_p3_race_args_use_one_arm_its_scale_the_capture_proxy_port_and_the_p3_pack():
    run = _mod("p3_run")
    a = run.race_args("/o", "v6p", 8003)
    assert a[a.index("--arms") + 1] == "v6p" and "v6p=0.6156688916658797" in a and a[a.index("--port") + 1] == "8003"
    assert a[a.index("--harness") + 1] == "data/heldout1k/harness_p3" and a[a.index("--ids") + 1].endswith("p3_ids.txt") and a[a.index("--conc") + 1] == "2"
    assert "--keep" in a and a[a.index("--label") + 1] == "p3"


def test_merge_results_concatenates_item_rows_of_one_arm(tmp_path):
    b = _mod("p3_build")
    for t in ("a", "b"):
        d = tmp_path / "items" / "v6p" / t; d.mkdir(parents=True)
        (d / "task_results.jsonl").write_text(json.dumps({"instance_id": t, "resolved": t == "a"}) + "\n")
    out = tmp_path / "all.jsonl"
    assert b.merge_results(str(tmp_path), str(out)) == 2
    assert sorted(json.loads(l)["instance_id"] for l in out.read_text().splitlines()) == ["a", "b"]


def test_build_commands_exclude_the_sample_ids_and_do_not_use_the_tokenizer_download(tmp_path):
    b = _mod("p3_build")
    cmds = b.commands("/p3", "/h/tasks.jsonl")
    sft = " ".join(cmds["sft"]); reb = " ".join(cmds["rebalance"]); val = " ".join(cmds["validate"])
    assert "build_sft.py" in sft and "--exclude-ids" in sft and "sample200_ids.txt" in sft and "s200_valid_ids.txt" in sft and "--capture /p3/capture.jsonl" in sft
    assert "--drop-repeats" in reb and "read_file=0.15" in reb and "--max-per-task 200" in reb and "--drop-unknown-tools" in reb
    assert "validate_rows.py" in val and "--no-tokenizer" in val and "--min-rows 0" in val


def test_pairs_need_two_attempts_of_one_task():
    b = _mod("p3_build")
    assert b.pair_count({"a": [True], "b": [False]}) == 0                     # one pass: no task has both a solved and a failed attempt
    assert b.pair_count({"a": [True, False], "b": [False, False], "c": [True, True]}) == 1


def test_final_summary_survives_steps_that_never_ran(tmp_path):
    fs = _mod("final_summary")
    d = tmp_path / "p2" / "items" / "v4h2" / "t0"; d.mkdir(parents=True)
    (d / "task_results.jsonl").write_text(json.dumps({"instance_id": "t0", "resolved": True, "duration_seconds": 100.0, "error": None, "agent_patch_size": 5}) + "\n")
    text = fs.summary_text(str(tmp_path / "p2"), str(tmp_path / "no_p4"), str(tmp_path / "no_p3"), ids=["t0"])
    assert "FINAL SUMMARY" in text and "stage 1a" in text and "P4" in text and "not run" in text and "P3" in text


def test_build_reports_cleanly_when_p3_never_ran(tmp_path, capsys):
    b = _mod("p3_build")
    if not pathlib.Path(b.PY).exists():         # off the box (no ~/g4/venv): the build steps run under this interpreter
        b.PY = sys.executable
    assert b.main(["--out", str(tmp_path / "never_created"), "--no-append"]) == 0
    out = capsys.readouterr().out
    assert "P3 did not run" in out and "0" in out
    (tmp_path / "empty").mkdir()
    assert b.main(["--out", str(tmp_path / "empty"), "--no-append"]) == 0                  # a directory with no items and no capture
    assert "tasks finished 0" in capsys.readouterr().out


def test_p4_judge_reports_slowdown_over_clean_windows_and_says_how_much_was_contended(tmp_path):
    j = _mod("p4_judge")
    now = 1_000_000.0
    rows = [{"status": 200, "t": now - 3600 * 5 + i * 20, "latency_s": 2.2, "l4_target_s": 2.0} for i in range(90)]            # healthy hour
    rows += [{"status": 200, "t": now - 3600 * 3 + i * 20, "latency_s": 120.0, "l4_target_s": 2.0} for i in range(90)]         # contended hour
    rows += [{"status": 200, "t": now - 1800 + i * 20, "latency_s": 2.4, "l4_target_s": 2.0} for i in range(90)]               # healthy again
    s = j.slowdown_summary(rows)
    assert abs(s["clean"] - 1.15) < 0.05 and s["all"] > 20 and s["contended_windows"] == 3 and s["windows"] == 9
    assert "clean windows" in j.slowdown_text(s) and "contended" in j.slowdown_text(s)


# ------------------------------------------------------------------ P3 with v7: 4 passes per task (PROMPTS P6 / P3)
def test_p3_race_args_with_passes_use_one_port_per_pass():
    run = _mod("p3_run")
    a = run.race_args("/o", "v7", 8003, passes=4)
    assert a[a.index("--passes") + 1] == "4" and a[a.index("--pass-ports") + 1:a.index("--pass-ports") + 5] == ["8003", "8004", "8005", "8006"]
    assert "--arms" in a and a[a.index("--arms") + 1] == "v7"
    assert run.pass_seed(42, 1) == 42 and run.pass_seed(42, 4) == 45                     # pass 1 keeps the bundle's seed, later passes shift it


def test_merge_results_per_pass_and_pair_arguments(tmp_path):
    b = _mod("p3_build")
    for t, k, solved in (("a", 1, True), ("a", 2, False), ("b", 1, False), ("b", 2, False)):
        d = tmp_path / "items" / "v7" / f"{t}__s{k}"; d.mkdir(parents=True)
        (d / "task_results.jsonl").write_text(json.dumps({"instance_id": t, "resolved": solved}) + "\n")
    for k in (1, 2):
        (tmp_path / f"capture_s{k}.jsonl").write_text('{"t": 1}\n')
    per = b.merge_results_per_pass(str(tmp_path), passes=2)
    assert per == {1: 2, 2: 2} and (tmp_path / "s1" / "task_results.jsonl").exists() and (tmp_path / "s2" / "task_results.jsonl").exists()
    cmds = b.commands(str(tmp_path), "/h/tasks.jsonl", passes=2)
    sft = cmds["sft"]
    assert sft.count("--pair") == 2 and f"{tmp_path}/capture_s1.jsonl={tmp_path}/s1/task_results.jsonl" in sft and "--capture" not in sft
    attempts = b.attempts_from(str(tmp_path / "results_all.jsonl"))
    assert attempts == {"a": [True, False], "b": [False, False]} and b.pair_count(attempts) == 1
    raw = b.pairs_raw(attempts)
    assert raw == [{"task": "a", "solved_passes": [1], "failed_passes": [2]}]


def test_single_pass_build_still_uses_capture_and_results(tmp_path):
    b = _mod("p3_build")
    cmds = b.commands("/p3", "/h/tasks.jsonl", passes=1)
    assert "--capture /p3/capture.jsonl" in " ".join(cmds["sft"]) and "--pair" not in " ".join(cmds["sft"])


def test_final_summary_lists_every_p4_run_dir(tmp_path):
    fs = _mod("final_summary")
    for name in ("p4", "p4_v7"):
        d = tmp_path / name; (d / "results").mkdir(parents=True)
        (d / "ARM").write_text("v5h2" if name == "p4" else "v7")
        (d / "results.jsonl").write_text((ROOT / "eval" / "kaggle" / "g4-l4-v4h2g-p312" / "results.jsonl").read_text())
    text = fs.summary_text(str(tmp_path / "p2"), str(tmp_path / "p4"), str(tmp_path / "no_p3"), ids=["t0"], runs_root=str(tmp_path))
    assert text.count("P4 A6000 screen RESULT") == 2 and "v7 on the public 74" in text and "v5h2 on the public 74" in text


def test_data_report_carries_the_thought_share_from_the_validator(tmp_path):
    """P11 step 2 (2026-10-11): the rows gate reads rows_with_thought / rows from validate_report.json, printed in the data report."""
    (tmp_path / "validate_report.json").write_text(json.dumps({"rows": 200, "rows_with_thought": 180, "ok": True}))
    P = _mod("p3_build")
    line = P.thought_line(str(tmp_path))
    assert "180 of 200" in line and "share 0.90" in line and ">= 0.80" in line
    assert "missing" in P.thought_line(str(tmp_path / "nowhere"))
    (tmp_path / "validate_report.json").write_text(json.dumps({"rows": 0, "rows_with_thought": 0}))
    assert "0 of 0" in P.thought_line(str(tmp_path))
