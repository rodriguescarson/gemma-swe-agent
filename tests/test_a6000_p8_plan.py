"""scripts/a6000/p8_plan.py: the supervisor steps of PROMPTS P8 (v7c screen + one data pass): probe -> 50 stage-1a ids -> public 74 -> P3 with ONE pass. Written before the code."""
import importlib.util, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("p8_plan", ROOT / "scripts" / "a6000" / "p8_plan.py")
p8 = importlib.util.module_from_spec(spec); spec.loader.exec_module(p8)


def test_steps_in_the_p8_order_with_the_right_commands(tmp_path):
    steps = p8.v7c_steps(runs=str(tmp_path), py="/py", scale_fallback=1.0)
    assert [s["name"] for s in steps] == ["probe_v7c", "v7c_s50", "v7c_p4", "v7c_p3"]
    probe, s50, p4, p3 = steps
    assert probe["cmd"][probe["cmd"].index("--arms") + 1] == "v7c" and probe["cmd"][probe["cmd"].index("--levels") + 1] == "2" and probe["total"] == 4
    assert any("v7_counters.py" in " ".join(h) and "--arm v7c" in " ".join(h) and "--items-dir probe_v7c_T2" in " ".join(h) for h in probe["post"])
    c = s50["cmd"]
    assert c[c.index("--n") + 1] == "50" and c[c.index("--arms") + 1] == "v7c" and c[c.index("--conc") + 1] == "2"
    assert c[c.index("--arm-scale-from-probe") + 1] == "v7c=1.0" and s50["speed_log"].endswith("proxy_v7c_s50.jsonl") and s50["proxy"]["log"] == s50["speed_log"]
    assert s50["stats"]["arms"] == ["v7c"] and len(s50["stats"]["ids"]) == 50
    posts = [" ".join(h) for h in s50["post"]]
    assert any("p2_results_md.py" in p and "--arms v4h2 v7 v7c" in p and "--to 50" in p for p in posts)
    assert any("v7_counters.py" in p and "--arm v7c" in p and "v7c_s50_counters.json" in p for p in posts) and any("backup_results.py" in p for p in posts)
    c = p4["cmd"]
    assert "p4_run.py" in c[1] and c[c.index("--out") + 1] == str(tmp_path / "p4_v7c") and c[c.index("--port") + 1] == "8002"
    assert p4["stats"]["file"] == str(tmp_path / "p4_v7c" / "results.jsonl") and p4["speed_log"] == str(tmp_path / "p4_v7c_proxy.jsonl")
    assert any("p4_judge.py" in " ".join(h) and str(tmp_path / "p4_v7c") in " ".join(h) for h in p4["post"])
    assert any("v7_counters.py" in " ".join(h) and "v7c_p4_counters.json" in " ".join(h) for h in p4["post"])
    c = p3["cmd"]
    assert "p3_run.py" in c[1] and c[c.index("--passes") + 1] == "1" and c[c.index("--out") + 1] == str(tmp_path / "p3_v7c") and p3["proxy"] is None
    assert p3["total"] == 844 and p3["stats"]["arms"] == ["v7c"] and len(p3["stats"]["ids"]) == 844
    assert any("p3_build.py" in " ".join(h) and "--passes 1" in " ".join(h) and str(tmp_path / "p3_v7c") in " ".join(h) for h in p3["post"])


def test_p3_scale_is_passed_when_given(tmp_path):
    p3 = p8.v7c_steps(runs=str(tmp_path), py="/py", scale_fallback=1.0, p3_scale=0.73)[3]
    assert p3["cmd"][p3["cmd"].index("--scale") + 1] == "0.73"


def test_choice_file_and_finalize_hooks(tmp_path):
    ch = tmp_path / "choice.json"; ch.write_text(json.dumps({"p4_arm": "v7", "p3_arm": "v7"}))
    p8.set_choices(str(ch), "v7c")
    assert json.loads(ch.read_text()) == {"p4_arm": "v7c", "p3_arm": "v7c"}
    joined = [" ".join(h) for h in p8.finalize_hooks(runs=str(tmp_path), py="/py")]
    assert any("p3_build.py" in j and "--passes 1" in j and "p3_v7c" in j for j in joined) and any("final_summary.py" in j for j in joined) and any("backup_results.py" in j for j in joined)


def test_a_fresh_plan_replaces_the_old_steps_and_is_closed(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"steps": [{"name": "old"}], "open": True, "finalize": []}))
    p8.write_plan(str(plan), runs=str(tmp_path), py="/py")
    got = json.loads(plan.read_text())
    assert [s["name"] for s in got["steps"]] == ["probe_v7c", "v7c_s50", "v7c_p4", "v7c_p3"] and got["open"] is False and got["finalize"]


def test_the_arm_option_builds_the_same_four_steps_for_v7d_paired_against_v7c_too(tmp_path):
    """PROMPTS P9 (docs/a6000/V7C_FAILURE_ANALYSIS.md, step 1): the v7d screen is P8's plan with the arm swapped; its
    50-id table is paired against v4h2, v7 AND v7c; the default stays v7c, byte for byte."""
    steps = p8.v7c_steps(runs=str(tmp_path), py="/py", scale_fallback=1.0, arm="v7d")
    assert [s["name"] for s in steps] == ["probe_v7d", "v7d_s50", "v7d_p4", "v7d_p3"]
    probe, s50, p4, p3 = steps
    assert probe["cmd"][probe["cmd"].index("--arms") + 1] == "v7d" and "--items-dir probe_v7d_T2" in " ".join(probe["post"][0])
    c = s50["cmd"]
    assert c[c.index("--arms") + 1] == "v7d" and c[c.index("--arm-scale-from-probe") + 1] == "v7d=1.0" and s50["stats"]["arms"] == ["v7d"]
    posts = [" ".join(h) for h in s50["post"]]
    assert any("p2_results_md.py" in p and "--arms v4h2 v7 v7c v7d" in p and "vs v4h2, v7, v7c stage 1a" in p for p in posts)
    assert any("v7_counters.py" in p and "--arm v7d" in p and "v7d_s50_counters.json" in p for p in posts)
    assert p4["cmd"][p4["cmd"].index("--out") + 1] == str(tmp_path / "p4_v7d") and p4["stats"]["file"] == str(tmp_path / "p4_v7d" / "results.jsonl")
    assert p3["cmd"][p3["cmd"].index("--out") + 1] == str(tmp_path / "p3_v7d") and p3["stats"]["arms"] == ["v7d"]
    assert "v7c" not in json.dumps([probe, p4, p3]) and "v7c" not in json.dumps(s50["cmd"])   # only the comparator list names it
    joined = [" ".join(h) for h in p8.finalize_hooks(runs=str(tmp_path), py="/py", arm="v7d")]
    assert any("p3_build.py" in j and "p3_v7d" in j for j in joined)
    plan = tmp_path / "plan.json"
    p8.write_plan(str(plan), runs=str(tmp_path), py="/py", arm="v7d")
    assert [s["name"] for s in json.loads(plan.read_text())["steps"]] == ["probe_v7d", "v7d_s50", "v7d_p4", "v7d_p3"]
    assert p8.v7c_steps(runs=str(tmp_path), py="/py", scale_fallback=1.0) == p8.v7c_steps(runs=str(tmp_path), py="/py", scale_fallback=1.0, arm="v7c")
    assert (ROOT / "submissions" / "v7d" / "agent.yaml").exists()


def test_the_cli_takes_the_arm(tmp_path):
    import subprocess, sys
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "a6000" / "p8_plan.py"), "--dry-run", "--arm", "v7d"], capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout) == ["probe_v7d", "v7d_s50", "v7d_p4", "v7d_p3"], r.stdout + r.stderr
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "a6000" / "p8_plan.py"), "--dry-run"], capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout) == ["probe_v7c", "v7c_s50", "v7c_p4", "v7c_p3"], r.stdout + r.stderr
