"""scripts/a6000/p6_plan.py: the supervisor steps of the v7 switch (PROMPTS P6): probe -> 50 stage-1a ids -> public 74 -> P3 with 4 passes. Written before the code."""
import importlib.util, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("p6_plan", ROOT / "scripts" / "a6000" / "p6_plan.py")
p6 = importlib.util.module_from_spec(spec); spec.loader.exec_module(p6)


def test_steps_in_the_p6_order_with_the_right_commands(tmp_path):
    steps = p6.v7_steps(runs=str(tmp_path), py="/py", scale_fallback=1.0)
    names = [s["name"] for s in steps]
    assert names == ["probe_v7", "v7_s50", "v7_p4", "v7_p3"]
    probe, s50, p4, p3 = steps
    assert "--arms" in probe["cmd"] and probe["cmd"][probe["cmd"].index("--arms") + 1] == "v7" and probe["cmd"][probe["cmd"].index("--levels") + 1] == "2"
    assert any("v7_counters.py" in " ".join(h) and "--items-dir probe_v7_T2" in " ".join(h) for h in probe["post"]) and not any("p2_probe_gate" in " ".join(h) for h in probe["post"])
    c = s50["cmd"]
    assert c[c.index("--n") + 1] == "50" and c[c.index("--arms") + 1] == "v7" and c[c.index("--conc") + 1] == "2" and "--require-probe-ok" not in c
    assert "v7=1.0" in c[c.index("--arm-scale-from-probe") + 1] and s50["speed_log"].endswith("proxy_v7_s50.jsonl") and s50["proxy"]["log"] == s50["speed_log"]
    assert s50["stats"]["arms"] == ["v7"] and len(s50["stats"]["ids"]) == 50 and s50["total"] == 50
    posts = [" ".join(h) for h in s50["post"]]
    assert any("p2_results_md.py" in p and "--arms v4h2 v7" in p and "--to 50" in p for p in posts) and any("v7_counters.py" in p and "--arm v7" in p for p in posts)
    c = p4["cmd"]
    assert "p4_run.py" in c[1] and c[c.index("--out") + 1] == str(tmp_path / "p4_v7") and c[c.index("--port") + 1] == "8002" and p4["proxy"]["listen"] == 8002
    assert p4["stats"]["file"] == str(tmp_path / "p4_v7" / "results.jsonl") and p4["purge"][-1] == str(tmp_path / "p4_v7" / "results.jsonl") and p4["speed_log"] == str(tmp_path / "p4_v7_proxy.jsonl")
    assert any("p4_judge.py" in " ".join(h) and str(tmp_path / "p4_v7") in " ".join(h) for h in p4["post"]) and any("v7_counters.py" in " ".join(h) for h in p4["post"])
    c = p3["cmd"]
    assert "p3_run.py" in c[1] and c[c.index("--passes") + 1] == "4" and c[c.index("--out") + 1] == str(tmp_path / "p3") and p3["proxy"] is None
    assert p3["speed_log"] == str(tmp_path / "p3" / "proxy.jsonl") and any("p3_build.py" in " ".join(h) and "--passes 4" in " ".join(h) for h in p3["post"])
    assert p3["total"] == 844 * 4


def test_choice_file_and_finalize_hooks(tmp_path):
    ch = tmp_path / "choice.json"; ch.write_text(json.dumps({"p4_arm": "v5h2", "p3_arm": "v6p"}))
    p6.set_choices(str(ch), "v7")
    assert json.loads(ch.read_text()) == {"p4_arm": "v7", "p3_arm": "v7"}
    fin = p6.finalize_hooks(runs=str(tmp_path), py="/py")
    joined = [" ".join(h) for h in fin]
    assert any("p3_build.py" in j and "--passes 4" in j for j in joined) and any("final_summary.py" in j for j in joined) and any("backup_results.py" in j for j in joined)
