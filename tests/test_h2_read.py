"""eval/analysis/h2_read.py: the pre-registered Phase 1 readings computed from an archive laid out as harness2 and h2g4 write
it (summary.json per task, judged.json, base_judged.json, race/staged records, race/items results, library entries)."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("h2_read", ROOT / "eval" / "analysis" / "h2_read.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
TASKS = ["arrow_06fe693", "arrow_0fe5f06", "arrow_1278a21", "arrow_22acd93",
         "arrow_30d16c1", "arrow_310cef8", "arrow_384fb74", "arrow_3f9837e"]


def write(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj))


def stage(label, kept=False, fell=False, err=""):
    return {"label": label, "kept_base": kept, "fell_back": fell, "error": err}


def archive(tmp: Path, solved=(), sel_fail=(), fell=(), crash=(), base_solved=()) -> Path:
    r = tmp / "h2_gemma" / "root"
    ns = r / "adapt" / "swe-g4-adk-agg1"
    judged, based = [], []
    for i, t in enumerate(TASKS):
        stages = [stage("inv1", fell=t in fell), stage("dom1", kept=True), stage("c1", kept=t in sel_fail)]
        ok = t not in sel_fail
        write(ns / t / "summary.json", {"task_id": t, "status": "ok" if ok else "partial",
                                        "modes": {"seq": {"stages": stages}},
                                        "selections": {"seq": {"ok": ok, "chosen_label": "c1" if ok else "",
                                                               "error": "" if ok else "no candidate produced an artifact"}}})
        judged.append({"task_id": t, "mode": "seq", "all_pass": t in solved and ok,
                       "error": "" if ok else "selection did not complete successfully"})
        based.append({"task": t, "label": "base1", "score": {"all_pass": t in base_solved}})
        for k, lab in enumerate(("base1", "inv1", "dom1", "c1")):
            arm = f"_h2_{'ab' * 6}_{i}{k:05d}"
            write(r / "race" / "staged" / arm / f"{t}.json", {"run_id": f"{t}/{lab}", "arm": arm, "task": t})
            if not (t in crash and lab == "dom1"):
                write(r / "race" / "items" / arm / t / "task_results.jsonl", "{}\n")
        if ok:
            write(r / "library" / "seq" / "arrow" / "harnesses" / t / "harness" / "systemprompt.md", "x")
    write(ns / "judged.json", judged)
    write(ns / "base_judged.json", based)
    return tmp / "h2_gemma"


def test_a_clean_sweep_reads_mechanics_pass_and_counts_adoptions(tmp_path):
    res = R.read(archive(tmp_path, solved=TASKS[:2], sel_fail=(TASKS[0], TASKS[5]), base_solved=TASKS[1:3]))
    assert res["tasks"] == 8 and res["mechanics"] == 8 and res["mechanics_pass"]
    assert res["adoptions"] == 6                                       # two failed selections adopt nothing
    assert res["solved"] == [TASKS[1]]                                 # a failed selection is unsolved even if judged
    assert res["base_solved"] == 2 and not res["signal"]
    text = R.render(res)
    assert "MECHANICS PASS: 8 of 8" in text and "ADOPTIONS: 6 of 8" in text and "SIGNAL NO" in text


def test_fallbacks_and_crashed_rollouts_fail_mechanics(tmp_path):
    res = R.read(archive(tmp_path, fell=TASKS[:2], crash=TASKS[2:3]))
    assert res["mechanics"] == 5 and not res["mechanics_pass"]
    row = next(x for x in res["rows"] if x["task"] == TASKS[2])
    assert len(row["crashed"]) == 1


def test_signal_rules_including_the_never_solved_three(tmp_path):
    assert R.read(archive(tmp_path / "a", solved=TASKS[:4]))["signal"]
    assert not R.read(archive(tmp_path / "b", solved=TASKS[:3]))["signal"]
    assert R.read(archive(tmp_path / "c", solved=(TASKS[0], TASKS[1], "arrow_22acd93")))["signal"]


def test_cli_writes_the_reading(tmp_path, capsys):
    d = archive(tmp_path)
    out = tmp_path / "read.md"
    assert R.main([str(d), "--out", str(out)]) == 0
    assert "MECHANICS PASS" in out.read_text() and "MECHANICS PASS" in capsys.readouterr().out


def test_session_and_replay_audits(tmp_path):
    d = archive(tmp_path)
    audit = d / "root" / "adapt" / "_audit"
    write(audit / "c1.a1.x.response.md", "## Goal\n... exceeded the provider's size limit ...\nShould I begin?")
    write(audit / "inv1.a1.y.response.md", "KEEP_BASE\n")
    ss = R.sessions(d)
    assert ss["c1"] == {"sessions": 1, "overflowed": 1, "bare_keep_base": 0, "ended_with_question": 1}
    assert ss["inv1"]["bare_keep_base"] == 1
    r = d / "root"
    t = "arrow_3f9837e"
    for arm, row in (("_h2_a_1", (True, 15, 1442, 325.4)), ("_h2_a_2", (True, 15, 1442, 325.1)), ("_h2_a_3", (False, 30, 0, 300.0))):
        write(r / "race" / "staged" / arm / f"{t}.json", {"run_id": arm, "arm": arm, "task": t, "fingerprint": "f" * 64})
        write(r / "race" / "items" / arm / t / "task_results.jsonl", json.dumps(
            {"resolved": row[0], "total_llm_calls": row[1], "agent_patch_size": row[2], "duration_seconds": row[3]}) + "\n")
    rp = R.replays(d)
    assert rp["pairs"] == 3 and rp["exact"] == 1 and rp["same_outcome"] == 1
