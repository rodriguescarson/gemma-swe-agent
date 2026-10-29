"""eval/analysis/labels.py (2026-10-30): the cleaned run labels, the comparable reach bands and the cleaned 32-task screen.

Small fixture repositories pin each rule (the band edges, what a regrade may change, the flags and exclusions, the step by
step counts, the screen), and the committed outputs are pinned from tracked files: the raw band of step one reproduces
task_reach.json, the corrected label differs from the raw one in exactly one row, and the clean outputs equal what the script
writes from results.jsonl today.
"""
import hashlib, importlib.util, json, pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "eval" / "analysis" / "labels.py"
OUT = ROOT / "eval" / "analysis" / "out"
INPUTS = OUT / "label_inputs"


def _mod():
    spec = importlib.util.spec_from_file_location("labels", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def sha(patch):
    return hashlib.sha1(patch.encode()).hexdigest()


# ---------------------------------------------------------------------------------------------------- fixture repository
IDS = ["t1", "t2", "t3", "t4", "t5"]
SOLVED = {                       # config -> the tasks its raw label resolves
    "k1": {"t1", "t5"},          # Kaggle kernel at 5 min / 40 calls
    "b1": {"t1", "t3", "t5"},    # box, at spec
    "bn": {"t1", "t2", "t5"},    # box, at spec; t2 is solved after a live pip install
    "b1r": {"t1", "t3", "t4", "t5"},   # box, a rerun of b1's bundle (the same draw)
    "bl": set(IDS),              # box at 8 min / 28 calls
}
SIDE = {"k1": "L4", "b1": "box", "bn": "box", "b1r": "box", "bl": "box"}
BUDGET = {"k1": (5, 40), "b1": (5, 40), "bn": (5, 40), "b1r": (5, 40), "bl": (8, 28)}


def patch_of(cfg, tid):
    return "" if tid in ("t4", "t5") else f"--- a/x.py\n+++ b/x.py\n+{cfg}{tid}\n"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if isinstance(text, str) else json.dumps(text))


def make_repo(tmp_path, monkeypatch, regraded=None, extra_flags=None):
    lb = _mod()
    monkeypatch.setattr(lb, "ROOT", str(tmp_path))
    monkeypatch.setattr(lb, "IDS", set(IDS))
    out = tmp_path / "eval" / "analysis" / "out"
    write(out / "run_audit.json", {"table": [{"cfg": f"{SIDE[c]} {c}"} for c in SOLVED]})
    for c, won in SOLVED.items():
        base = "eval/kaggle" if SIDE[c] == "L4" else "eval/a6000/results"
        rows = [{"id": t, "resolved": t in won, "patch": patch_of(c, t)} for t in IDS]
        rows.append({"id": "not_a_public_task", "resolved": True, "patch": ""})
        rows.append({"cfg": c, "note": "a row without an id"})
        write(tmp_path / base / c / "results.jsonl", "".join(json.dumps(r) + "\n" for r in rows))
    hyg = {"budget": {c: {"max_time_minutes": m, "max_tool_calls": n} for c, (m, n) in BUDGET.items()},
           "network": [["bn", "t2", "step 9: pip install"]],
           "duplicate_detail": {"pairs": [
               {"a": "b1", "b": "b1r", "first_msg_and_call_identical": "4/5", "same_bundle": True},
               {"a": "b1", "b": "bn", "first_msg_and_call_identical": "3/5", "same_bundle": False}]},
           "stack": {c: {"run_date": f"2026-10-{10 + i}"} for i, c in enumerate(SOLVED)}}
    hyg.update(extra_flags or {})
    row_flags = {"bn|t2": ["NETWORK_SUCCESS"], "k1|t4": ["HARNESS_KILLED_ROW", "BUDGET_NOT_5MIN_40CALLS"],
                 "b1|t2": ["BOX_PYGMENTS_2_21_EXPOSED"]}
    tasks = {t: {"base_resolved": t == "t5"} for t in IDS}
    if regraded is None:           # b1's t2 was unresolved under the box's Pygments and resolves under the scorer's
        regraded = [dict(cfg="b1", id="t2", old_resolved=False, new_resolved=True, exit=0, old_exit=1, phase="tests",
                         patch_sha1=sha(patch_of("b1", "t2"))),
                    dict(cfg="b1", id="t3", old_resolved=True, new_resolved=True, exit=0, old_exit=0, phase="tests",
                         patch_sha1=sha(patch_of("b1", "t3"))),
                    dict(cfg="bl", id="t4", old_resolved=True, new_resolved=None, exit=-1, old_exit=0, phase="infra",
                         patch_sha1=sha(patch_of("bl", "t4"))),
                    dict(cfg="outside_the_audit", id="t2", old_resolved=False, new_resolved=True, exit=0, old_exit=1,
                         phase="tests", patch_sha1=sha(""))]
    inp = out / "label_inputs"
    write(inp / "grader_tasks.json", tasks)
    write(inp / "hygiene_flags.json", hyg)
    write(inp / "hygiene_row_flags.json", row_flags)
    write(inp / "regraded.json", regraded)
    write(inp / "regraded_p4.json", [])
    return lb


# ------------------------------------------------------------------------------------------------------------ the bands
@pytest.mark.parametrize("solved,n,want", [
    (0, 0, "nodata"), (0, 20, "never"), (1, 20, "rare_lt10"), (1, 11, "rare_lt10"), (1, 10, "contested_10_90"),
    (2, 20, "contested_10_90"), (9, 10, "contested_10_90"), (18, 20, "contested_10_90"), (19, 20, "always_gt90"),
    (10, 11, "always_gt90"), (10, 10, "always_gt90"), (1, 1, "always_gt90"), (1, 2, "contested_10_90"),
])
def test_band_edges_are_exact_at_10_and_90_percent(solved, n, want):
    assert _mod().band(solved, n) == want


# ----------------------------------------------------------------------------------------------------- reading and regrade
def test_read_rows_keeps_one_row_per_public_task_and_rejects_a_repeated_id(tmp_path, monkeypatch):
    lb = make_repo(tmp_path, monkeypatch)
    rows = lb.read_rows(lb.agent_configs())
    assert len(rows) == 5 * 5 and {(r["cfg"], r["id"]) for r in rows} == {(c, t) for c in SOLVED for t in IDS}
    r = next(r for r in rows if r["cfg"] == "k1" and r["id"] == "t1")
    assert (r["side"], r["raw_resolved"], r["resolved"], r["patch_sha1"]) == ("L4", True, True, sha(patch_of("k1", "t1")))
    path = tmp_path / "eval" / "a6000" / "results" / "b1" / "results.jsonl"
    path.write_text(path.read_text() + json.dumps({"id": "t1", "resolved": False}) + "\n")
    with pytest.raises(ValueError, match="two rows for t1"):
        lb.read_rows(lb.agent_configs())


def test_a_regrade_changes_a_label_only_where_a_test_verdict_differs(tmp_path, monkeypatch):
    lb = make_repo(tmp_path, monkeypatch)
    rows = lb.read_rows(lb.agent_configs())
    changed = lb.apply_regrades(rows, json.loads((tmp_path / "eval/analysis/out/label_inputs/regraded.json").read_text()))
    assert [(c["cfg"], c["id"], c["raw"], c["resolved"]) for c in changed] == [("b1", "t2", False, True)]
    by = {(r["cfg"], r["id"]): r for r in rows}
    assert (by["b1", "t2"]["raw_resolved"], by["b1", "t2"]["resolved"]) == (False, True)
    assert by["b1", "t3"]["resolved"] is True and by["b1", "t3"].get("env_regraded")        # replayed, same verdict
    assert by["bl", "t4"]["resolved"] is True and by["bl", "t4"].get("env_regraded")        # no test ran (infra): the label stands
    assert sum(1 for r in rows if r["raw_resolved"] != r["resolved"]) == 1
    assert sum(1 for r in rows if r.get("env_regraded")) == 3            # the config outside the audit was skipped


@pytest.mark.parametrize("mutate", [dict(old_resolved=True), dict(patch_sha1="0" * 40)])
def test_a_regrade_made_on_another_row_raises(tmp_path, monkeypatch, mutate):
    lb = make_repo(tmp_path, monkeypatch)
    rows = lb.read_rows(lb.agent_configs())
    g = dict(cfg="b1", id="t2", old_resolved=False, new_resolved=True, exit=0, old_exit=1, phase="tests",
             patch_sha1=sha(patch_of("b1", "t2")))
    g.update(mutate)
    with pytest.raises(ValueError, match="different row"):
        lb.apply_regrades(rows, [g])


# ------------------------------------------------------------------------------------------------------ flags, exclusions
def test_flags_notes_and_the_reasons_a_row_is_not_comparable(tmp_path, monkeypatch):
    lb = make_repo(tmp_path, monkeypatch)
    labels, _ = lb.build()
    by = {(r["cfg"], r["id"]): r for r in labels["rows"]}
    assert by["b1", "t2"]["flags"] == dict(env_regraded=True, base_passes=False, network=False, duplicate_of=None, budget=None)
    assert by["b1", "t2"]["notes"] == ["BOX_PYGMENTS_2_21_EXPOSED"] and by["b1", "t2"]["excluded"] == []
    assert by["bn", "t2"]["flags"]["network"] is True and by["bn", "t2"]["excluded"] == ["network"]
    assert by["bn", "t2"]["notes"] == []                  # NETWORK_SUCCESS is the network flag, not a note
    assert by["k1", "t4"]["excluded"] == ["harness_killed"] and by["k1", "t4"]["notes"] == ["HARNESS_KILLED_ROW"]
    assert by["b1r", "t3"]["flags"]["duplicate_of"] == "b1" and by["b1r", "t3"]["excluded"] == ["duplicate_config"]
    assert by["bn", "t3"]["flags"]["duplicate_of"] is None            # shares a draw with b1 but not the same bundle
    assert by["bl", "t1"]["flags"]["budget"] == "8min/28calls" and by["bl", "t1"]["excluded"] == ["budget"]
    assert by["b1", "t1"]["flags"]["budget"] is None
    assert by["b1", "t5"]["flags"]["base_passes"] is True and by["b1", "t5"]["excluded"] == []
    assert {c["cfg"]: (c["budget"], c["at_spec"], c["duplicate_of"], c["comparable_rows"]) for c in labels["configs"]} == {
        "k1": ("5min/40calls", True, None, 4), "b1": ("5min/40calls", True, None, 5), "bn": ("5min/40calls", True, None, 4),
        "b1r": ("5min/40calls", True, "b1", 0), "bl": ("8min/28calls", False, None, 0)}
    assert labels["meta"]["excluded"] == dict(network=1, harness_killed=1, duplicate_config=5, budget=5)
    assert labels["meta"]["comparable_rows"] == 13 and labels["meta"]["comparable_configs"] == ["k1", "b1", "bn"]
    assert labels["meta"]["base_passes"] == ["t5"] and (labels["meta"]["raw_solved"], labels["meta"]["solved"]) == (17, 18)


def test_a_config_without_a_budget_stops_the_run(tmp_path, monkeypatch):
    lb = make_repo(tmp_path, monkeypatch)
    path = tmp_path / "eval/analysis/out/label_inputs/hygiene_flags.json"
    h = json.loads(path.read_text())
    del h["budget"]["b1r"]
    path.write_text(json.dumps(h))
    with pytest.raises(KeyError, match="b1r has no budget"):
        lb.build()


# ------------------------------------------------------------------------------------------------------ the reach bands
def test_the_reach_steps_drop_one_kind_of_row_at_a_time(tmp_path, monkeypatch):
    """Raw: t1 and t5 are solved by all five configs, t2 2/5, t3 3/5, t4 2/5. Each step removes one kind of row."""
    lb = make_repo(tmp_path, monkeypatch)
    _, reach = lb.build()
    cut = lambda s: [s[k] for k in ("configs", "runs", "tasks", "never", "rare_lt10", "contested_10_90", "always_gt90", "every_run")]
    got = {s["step"]: cut(s) for s in reach["steps"]}
    assert list(got.values()) == [
        [5, 25, 5, 0, 0, 3, 2, 2],          # raw labels, every run
        [5, 25, 5, 0, 0, 3, 2, 2],          # b1's t2 corrected: t2 is 3/5 instead of 2/5, still contested
        [5, 23, 5, 0, 0, 3, 2, 2],          # without bn's network row and k1's harness-killed row
        [4, 18, 5, 0, 0, 3, 2, 2],          # b1r counted once: it was the only other config to solve t4
        [3, 13, 5, 1, 0, 2, 2, 2],          # only the three configs at 5 min / 40 calls: t4 is now never solved
        [3, 10, 4, 1, 0, 2, 1, 1]]          # t5 (the base passes) reported apart: its 3 runs leave the count
    assert reach["never"] == ["t4"] and reach["contested_10_90"] == ["t2", "t3"] and reach["always_gt90"] == ["t1"]
    assert reach["rare_lt10"] == [] and reach["nodata"] == []
    assert [(b["id"], b["solved"], b["n"], b["raw"]["solved"], b["raw"]["n"]) for b in reach["base_passing"]] == [("t5", 3, 3, 5, 5)]
    assert reach["moved"] == {"t4": ["contested_10_90", "never"]}
    assert reach["tasks"]["t2"] == dict(raw=dict(n=5, solved=2, band="contested_10_90"),
                                        clean=dict(n=2, solved=1, band="contested_10_90"), base_passes=False)
    assert reach["comparable_configs"] == ["k1", "b1", "bn"]
    assert reach["dropped_configs"] == dict(duplicate={"b1r": "b1"}, budget={"bl": "8min/28calls"})
    assert reach["screen"] == ["t2", "t3"]


def test_a_duplicate_config_counts_once(tmp_path, monkeypatch):
    lb = make_repo(tmp_path, monkeypatch)
    rows = lb.build()[0]["rows"]
    once = lb.reach(rows, "resolved", drop=("duplicate_config",))
    twice = lb.reach(rows, "resolved")
    assert (once["t3"]["n"], once["t3"]["solved"]) == (4, 2) and (twice["t3"]["n"], twice["t3"]["solved"]) == (5, 3)
    assert once["t4"]["solved"] == 1 and twice["t4"]["solved"] == 2           # b1r was the second config to solve t4


def test_clusters_join_pairs_at_or_above_the_share_and_nothing_below():
    pairs = [dict(a="v13", b="v13r", first_msg_and_call_identical="55/74"),
             dict(a="v13", b="v15", first_msg_and_call_identical="53/74"),
             dict(a="b1024", b="v12", first_msg_and_call_identical="41/74"),
             dict(a="b1024", b="v12r", first_msg_and_call_identical="35/74"),
             dict(a="x", b="y", first_msg_and_call_identical="37/74")]
    got = sorted(sorted(c) for c in _mod().clusters(pairs, 0.5))
    assert got == [["b1024", "v12"], ["v13", "v13r", "v15"], ["x", "y"]]


def test_sensitivity_variants_follow_their_own_reading_of_comparable(tmp_path, monkeypatch):
    lb = make_repo(tmp_path, monkeypatch)
    _, reach = lb.build()
    s = reach["sensitivity"]
    assert s["time_only_budget"]["configs"] == 3 and s["time_only_budget"]["runs"] == 13 - 3        # bl (8 min) out, t5 apart
    assert s["kaggle_only"]["configs"] == 1 and s["kaggle_only"]["runs"] == 3                    # k1 only; its t4 row is harness-killed
    assert s["loose_duplicates"]["configs"] == 2 and s["loose_duplicates"]["screen"] == reach["screen"]    # bn and b1r join b1's cluster


# ------------------------------------------------------------------------------------------------------------ the files
def test_main_writes_the_three_outputs_and_reports_the_screen_change(tmp_path, monkeypatch, capsys):
    lb = make_repo(tmp_path, monkeypatch)
    (tmp_path / "old_screen.txt").write_text("t1\nt2\nt4\n")
    paths = {k: tmp_path / f"{k}.out" for k in ("labels", "reach", "screen")}
    lb.main(["--labels", str(paths["labels"]), "--reach", str(paths["reach"]), "--screen", str(paths["screen"]),
             "--old-screen", str(tmp_path / "old_screen.txt")])
    assert paths["screen"].read_text() == "t2\nt3\n"
    labels = json.loads(paths["labels"].read_text())
    assert [len(labels[k]) for k in ("configs", "rows")] == [5, 25] and labels["meta"]["labels_changed"][0]["cfg"] == "b1"
    assert json.loads(paths["reach"].read_text())["never"] == ["t4"]
    text = capsys.readouterr().out
    assert "5 configs, 25 rows: 17 raw solves, 18 corrected (1 labels changed" in text
    assert "screen: 3 before, 2 now; added ['t3']; removed ['t1', 't4']" in text
    assert "base-passing, apart: t5 3/3" in text


def test_the_rows_file_has_one_row_per_line(tmp_path, monkeypatch):
    lb = make_repo(tmp_path, monkeypatch)
    labels, _ = lb.build()
    p = tmp_path / "labels.json"
    lb.write_json(str(p), labels, per_line=("configs", "rows"))
    lines = p.read_text().splitlines()
    assert sum(1 for ln in lines if ln.startswith('  {"cfg"')) == 5 + 25
    assert json.loads(p.read_text()) == json.loads(json.dumps(labels))


# ------------------------------------------------------------------------ the committed outputs and inputs (tracked files)
def j(path):
    return json.loads(path.read_text())


def test_the_committed_inputs_agree_with_each_other():
    hyg, tasks = j(INPUTS / "hygiene_flags.json"), j(INPUTS / "grader_tasks.json")
    rowf = j(INPUTS / "hygiene_row_flags.json")
    valid = set((ROOT / "data" / "kaggle_valid_ids.txt").read_text().split())
    assert set(tasks) == valid and all(t["gold_resolved"] for t in tasks.values())        # the gold patch resolves all 74
    assert sorted(t for t, v in tasks.items() if v["base_resolved"]) == ["fastapi_14077", "fastapi_14851", "requests_6644"]
    assert sorted(t for t, v in tasks.items() if v["pyg221_changed"]) == ["rich_3782", "rich_4079"]
    for cfg, b in hyg["budget"].items():                  # the stage's own at-spec flag is the 5 min / 40 call rule
        assert b["at_spec_5min_40calls"] == (float(b["max_time_minutes"]) == 5 and b["max_tool_calls"] == 40), cfg
    net = {(c, i) for c, i, _ in hyg["network"]}
    assert len(net) == 8 and net == {tuple(k.split("|")) for k, v in rowf.items() if "NETWORK_SUCCESS" in v}
    assert sorted(k for k, v in rowf.items() if "HARNESS_KILLED_ROW" in v) == [
        "e74_v2|rich_3676", "e74_v3|fastapi_14419", "e74_v3|rich_4076", "g4-l4-v9-eog|rich_2725"]
    same = [(p["a"], p["b"]) for p in hyg["duplicate_detail"]["pairs"] if p["same_bundle"]]
    assert same == [("p4_v13", "p4_v13r"), ("p4_v12", "p4_v12r")]
    rg = j(INPUTS / "regraded.json") + j(INPUTS / "regraded_p4.json")
    assert len(rg) == 43 and sorted(g["id"] for g in rg if g["cfg"] == "p4") == ["rich_3782", "rich_4079"]
    flips = [(g["cfg"], g["id"]) for g in rg if g["phase"] == "tests" and g["new_resolved"] != g["old_resolved"]]
    assert flips == [("p4_pub024", "rich_3782")]


def test_the_committed_labels_pin_one_changed_label_and_the_exclusion_counts():
    labels, audit = j(OUT / "labels_clean.json"), j(OUT / "run_audit.json")
    valid = set((ROOT / "data" / "kaggle_valid_ids.txt").read_text().split())
    rows = labels["rows"]
    assert (labels["meta"]["configs"], labels["meta"]["rows"], len(rows), len(labels["configs"])) == (33, 2442, 2442, 33)
    assert [c["cfg"] for c in labels["configs"]] == [t["cfg"].split(" ", 1)[1] for t in audit["table"]]
    assert {(r["cfg"], r["id"]) for r in rows} == {(c["cfg"], t) for c in labels["configs"] for t in valid}
    solved = {(x["cfg"].split(" ", 1)[1], x["id"]): x["solved"] for x in audit["rows"]}
    assert all(r["raw_resolved"] == solved[r["cfg"], r["id"]] for r in rows)         # the raw label is run_audit's label
    diff = [(r["cfg"], r["id"]) for r in rows if r["resolved"] != r["raw_resolved"]]
    assert diff == [("p4_pub024", "rich_3782")]
    assert [(c["raw"], c["resolved"]) for c in labels["meta"]["labels_changed"]] == [(False, True)]
    assert (labels["meta"]["raw_solved"], labels["meta"]["solved"]) == (911, 912)
    assert labels["meta"]["excluded"] == dict(network=8, harness_killed=4, duplicate_config=148, budget=1480)
    assert (labels["meta"]["comparable_rows"], labels["meta"]["env_regraded_rows"]) == (812, 40)
    assert labels["meta"]["comparable_configs"] == [
        "g4-l4-v12-p312", "g4-l4-v12b-garble-p312", "p4_b1024", "p4_v0t2", "p4_v12", "p4_v12b", "p4_v13", "p4_v14", "p4_v15",
        "p4_v15b", "p4_v16"]
    assert sum(1 for r in rows if not r["excluded"]) == 812
    assert {r["id"] for r in rows if r["flags"]["base_passes"]} == {"fastapi_14077", "fastapi_14851", "requests_6644"}
    assert {r["cfg"] for r in rows if r["flags"]["duplicate_of"]} == {"p4_v12r", "p4_v13r"}


def test_the_committed_reach_pins_the_before_and_after_counts():
    reach, old = j(OUT / "task_reach_clean.json"), j(OUT / "task_reach.json")
    steps = reach["steps"]
    keys = ("never", "rare_lt10", "contested_10_90", "always_gt90", "every_run")
    assert [tuple(s[k] for k in keys) for s in steps] == [
        (27, 10, 22, 15, 5), (26, 11, 22, 15, 5), (26, 11, 21, 16, 5), (26, 10, 23, 15, 5), (32, 8, 13, 21, 11),
        (32, 8, 11, 20, 10)]
    assert [(s["configs"], s["runs"], s["tasks"]) for s in steps] == [
        (33, 2442, 74), (33, 2442, 74), (33, 2430, 74), (31, 2282, 74), (11, 812, 74), (11, 781, 71)]
    # step one is the old task_reach.json: the same tasks per band
    raw = {b: sorted(t for t, v in reach["tasks"].items() if v["raw"]["band"] == b)
           for b in ("never", "rare_lt10", "contested_10_90", "always_gt90")}
    assert raw["never"] == old["never"] and raw["rare_lt10"] == old["rare_lt10"] and raw["contested_10_90"] == old["contested_10_90"]
    assert len(raw["always_gt90"]) == 15 and sum(len(v) for v in raw.values()) == 74
    final = [len(reach[k]) for k in ("never", "rare_lt10", "contested_10_90", "always_gt90", "base_passing", "nodata")]
    assert final == [32, 8, 11, 20, 3, 0] and sum(final) == 74
    assert [b["id"] for b in reach["base_passing"]] == ["fastapi_14077", "fastapi_14851", "requests_6644"]
    assert sorted(reach["never"] + reach["rare_lt10"] + reach["contested_10_90"] + reach["always_gt90"] +
                  [b["id"] for b in reach["base_passing"]]) == sorted(reach["tasks"])
    # the 27 never-solved tasks stay never solved; five rare ones join them once only configs at spec count
    assert set(old["never"]) <= set(reach["never"])
    assert set(reach["never"]) - set(old["never"]) == {"fastapi_14419", "rich_3063", "rich_3180", "rich_3470", "rich_3471"}
    assert reach["tasks"]["rich_3782"]["raw"]["band"] == "never"        # p4_pub024's regraded solve is not at spec


def test_the_committed_screen_is_rare_plus_contested_and_the_old_one_is_untouched():
    reach = j(OUT / "task_reach_clean.json")
    new = (ROOT / "data" / "screen32_clean_ids.txt").read_text().split()
    old = (ROOT / "data" / "screen32_ids.txt").read_text().split()
    task_reach = j(OUT / "task_reach.json")
    assert old == sorted(task_reach["contested_10_90"] + task_reach["rare_lt10"]) and len(old) == 32       # as it was built
    assert new == sorted(reach["rare_lt10"] + reach["contested_10_90"]) == reach["screen"] and len(new) == 19
    assert (ROOT / "data" / "screen32_clean_ids.txt").read_text().endswith("\n")
    assert sorted(set(new) - set(old)) == []
    assert sorted(set(old) - set(new)) == [
        "fastapi_14419", "fastapi_14463", "fastapi_14851", "fastapi_5077", "requests_6644", "rich_2725", "rich_3063", "rich_3067",
        "rich_3180", "rich_3470", "rich_3471", "rich_3894", "rich_4077"]


def test_the_committed_outputs_are_what_the_script_writes_from_the_raw_results(tmp_path):
    if not (ROOT / "eval" / "a6000" / "results" / "p4_v13" / "results.jsonl").exists():
        pytest.skip("raw results.jsonl not checked out")
    lb = _mod()
    labels, reach = lb.build()
    lb.write_json(str(tmp_path / "labels.json"), labels, per_line=("configs", "rows"))
    lb.write_json(str(tmp_path / "reach.json"), reach)
    assert (tmp_path / "labels.json").read_text() == (OUT / "labels_clean.json").read_text()
    assert (tmp_path / "reach.json").read_text() == (OUT / "task_reach_clean.json").read_text()
    assert "".join(t + "\n" for t in reach["screen"]) == (ROOT / "data" / "screen32_clean_ids.txt").read_text()
