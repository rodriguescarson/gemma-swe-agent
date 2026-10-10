"""scripts/a6000/p10_plan.py and p10_choose.py: the thinking-on collector pair (PROMPTS P10, GAPS "P10 pre-registration"): probe_pair ->
pair_s50 -> p3_think, and the mechanical collector rule (v12 unless WORSE than v5h2-think). Written before the code."""
import importlib.util, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "a6000" / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


p10 = load("p10_plan")
choose = load("p10_choose")


def test_steps_in_the_p10_order_with_both_arms_and_the_choice_hook(tmp_path):
    steps = p10.p10_steps(runs=str(tmp_path), py="/py", scale_fallback=1.0)
    assert [s["name"] for s in steps] == ["probe_pair", "pair_s50", "p3_think"]
    probe, s50, p3 = steps
    c = probe["cmd"]
    assert c[c.index("--arms") + 1:c.index("--levels")] == ["v5h2-think", "v12"] and c[c.index("--levels") + 1] == "2" and probe["total"] == 8
    assert [h[h.index("--arm") + 1] for h in probe["post"]] == ["v5h2-think", "v12"]
    c = s50["cmd"]
    assert c[c.index("--n") + 1] == "50" and c[c.index("--conc") + 1] == "2" and c[c.index("--arms") + 1:c.index("--arm-scale-from-probe")] == ["v5h2-think", "v12"]
    assert c[c.index("--arm-scale-from-probe") + 1:c.index("--port")] == ["v5h2-think=1.0", "v12=1.0"]
    assert s50["stats"]["arms"] == ["v5h2-think", "v12"] and len(s50["stats"]["ids"]) == 50 and s50["total"] == 100
    posts = [" ".join(h) for h in s50["post"]]
    assert posts[0].startswith("/py scripts/a6000/p2_results_md.py") and "--arms v4h2 v7c v7d v5h2-think v12" in posts[0]
    assert posts[1].startswith("/py scripts/a6000/p10_choose.py") and "--cand v12 --ref v5h2-think" in posts[1] and "--log docs/a6000/P2_LOG.md" in posts[1]
    assert any("v7_counters.py" in p and "--arm v12" in p for p in posts) and any("--arm v5h2-think" in p for p in posts) and "backup_results.py" in posts[-1]
    c = p3["cmd"]
    assert "p3_run.py" in c[1] and c[c.index("--out") + 1] == str(tmp_path / "p3_think") and c[c.index("--passes") + 1] == "1" and p3["proxy"] is None
    assert p3["total"] == 844 and p3["stats"]["arms"] == ["v5h2-think", "v12"]
    assert any("p3_build.py" in " ".join(h) and str(tmp_path / "p3_think") in " ".join(h) for h in p3["post"])
    joined = [" ".join(h) for h in p10.finalize_hooks(runs=str(tmp_path), py="/py")]
    assert any("p3_build.py" in j and "p3_think" in j for j in joined) and any("final_summary.py" in j for j in joined)


def test_a_fresh_plan_is_closed_and_the_choice_starts_at_the_reference(tmp_path):
    plan = tmp_path / "plan.json"; plan.write_text(json.dumps({"steps": [{"name": "old"}], "open": True, "finalize": []}))
    p10.write_plan(str(plan), runs=str(tmp_path), py="/py")
    got = json.loads(plan.read_text())
    assert [s["name"] for s in got["steps"]] == ["probe_pair", "pair_s50", "p3_think"] and got["open"] is False and got["finalize"]
    ch = tmp_path / "choice.json"; ch.write_text(json.dumps({"p4_arm": "v7d", "p3_arm": "v7d"}))
    p10.set_choices(str(ch), "v5h2-think")
    assert json.loads(ch.read_text()) == {"p4_arm": "v5h2-think", "p3_arm": "v5h2-think"}


def items(out, arm, results):
    """A p2_race items layout: items/<arm>/<task>/task_results.jsonl with resolved flags."""
    for t, ok in results.items():
        d = out / "items" / arm / t; d.mkdir(parents=True, exist_ok=True)
        (d / "task_results.jsonl").write_text(json.dumps({"instance_id": t, "resolved": ok, "duration_seconds": 100, "tool_calls": 10, "agent_patch_size": 5}) + "\n")


def test_the_candidate_is_chosen_unless_worse(tmp_path):
    ids = [f"t{i}" for i in range(50)]
    out = tmp_path / "p2"
    # candidate wins 3, loses 2 -> NO EVIDENCE -> candidate
    items(out, "v12", {t: i < 20 or i in (40, 41, 42) for i, t in enumerate(ids)})
    items(out, "v5h2-think", {t: i < 20 or i in (45, 46) for i, t in enumerate(ids)})
    arm, c = choose.choose(out, ids, "v12", "v5h2-think")
    assert arm == "v12" and c["verdict"] == "NO EVIDENCE" and (c["wins"], c["losses"]) == (3, 2)
    # candidate loses 8, wins 1 -> WORSE -> reference
    out2 = tmp_path / "p2b"
    items(out2, "v12", {t: i < 10 or i == 49 for i, t in enumerate(ids)})
    items(out2, "v5h2-think", {t: i < 18 for i, t in enumerate(ids)})
    arm2, c2 = choose.choose(out2, ids, "v12", "v5h2-think")
    assert c2["verdict"] == "WORSE" and arm2 == "v5h2-think", c2


def test_the_cli_writes_the_choice_file_and_the_log_line(tmp_path):
    import subprocess, sys
    ids = [f"t{i}" for i in range(50)]
    (tmp_path / "ids.txt").write_text("\n".join(ids) + "\n")
    out = tmp_path / "p2"
    items(out, "v12", {t: i < 25 for i, t in enumerate(ids)}); items(out, "v5h2-think", {t: i < 24 for i, t in enumerate(ids)})
    ch = tmp_path / "choice.json"; ch.write_text(json.dumps({"p4_arm": "v5h2-think", "p3_arm": "v5h2-think"}))
    log = tmp_path / "log.md"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "a6000" / "p10_choose.py"), str(out), "--ids", str(tmp_path / "ids.txt"), "--choice", str(ch), "--log", str(log)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "p3_arm=v12" in r.stdout and "NO EVIDENCE" in r.stdout, r.stdout + r.stderr
    assert json.loads(ch.read_text()) == {"p4_arm": "v5h2-think", "p3_arm": "v12"}
    assert "P10 collector choice: p3_arm=v12" in log.read_text()
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "a6000" / "p10_plan.py"), "--dry-run"], capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout) == ["probe_pair", "pair_s50", "p3_think"], r.stdout + r.stderr
