"""scripts/a6000/p12_plan.py and union_bundle.py: the A6000 screen of the think adapters (GAPS "P12 pre-registration",
2026-10-13), written before the box ran it."""
import hashlib, importlib.util, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _mod(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "a6000" / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_steps_probe_then_pair_against_the_p10_reference_with_the_serve_bundle(tmp_path):
    P = _mod("p12_plan")
    arms = ["v12_think1", "v12_think1f", "v12_think2"]
    steps = P.p12_steps("/home/u/g4/runs", "/py", arms)
    assert [s["name"] for s in steps] == ["probe_pair", "pair_s50", "p4_adapter"]
    probe, s50, p4 = steps
    assert probe["cmd"][probe["cmd"].index("--arms") + 1:probe["cmd"].index("--levels")] == arms and probe["total"] == 12
    cmd = s50["cmd"]
    assert cmd[1].endswith("p2_race.py") and cmd[2] == "/home/u/g4/runs/p2"          # the P10 dir: v12's 50 rows are reused, not re-run
    assert cmd[cmd.index("--arms") + 1:cmd.index("--arm-scale-from-probe")] == ["v12", *arms]
    assert "--n" in cmd and cmd[cmd.index("--n") + 1] == "50" and cmd[cmd.index("--conc") + 1] == "2" and s50["total"] == 150
    assert s50["proxy"] == {"listen": 8001, "host": "172.18.0.1", "log": "/home/u/g4/runs/p2/proxy_pair_s50_think.jsonl"}
    md = [h for h in s50["post"] if h[1].endswith("p2_results_md.py")][0]
    assert md[md.index("--arms") + 1:] == ["v12", *arms, "v4h2", "v7c", "v7d", "v5h2-think"] and md[md.index("--base") + 1] == "v12"   # contrasts vs v12
    assert sum(1 for h in s50["post"] if h[1].endswith("v7_counters.py")) == 3 and s50["post"][-1][1].endswith("backup_results.py")
    names = [h[1].rsplit("/", 1)[-1] for h in s50["post"]]
    assert names.index("p2_results_md.py") < names.index("p12_choose.py") < names.index("v7_counters.py")     # the table first, then the choice
    ch = [h for h in s50["post"] if h[1].endswith("p12_choose.py")][0]
    assert ch[ch.index("--arms") + 1:ch.index("--ref")] == arms and ch[ch.index("--ref") + 1] == "v12" and "--log" in ch
    assert p4["cmd"][1].endswith("p4_run.py") and p4["docker"] is False and p4["total"] == 74 and p4["proxy"]["listen"] == 8002
    assert p4["stats"] == {"type": "results_jsonl", "file": "/home/u/g4/runs/p4_adapter/results.jsonl"} and p4["post"][0][1].endswith("p4_judge.py")
    plan = P.write_plan(tmp_path / "plan.json", "/home/u/g4/runs", "/py", arms, "/home/u/g4/serve_bundle")
    saved = json.loads((tmp_path / "plan.json").read_text())
    assert saved["serve_bundle"] == "/home/u/g4/serve_bundle" and saved["open"] is False and [s["name"] for s in saved["steps"]] == ["probe_pair", "pair_s50", "p4_adapter"]
    assert saved["finalize"][0][1].endswith("final_summary.py") and plan == saved


def test_cli_dry_run_lists_adapters_and_refuses_unknown_arms(tmp_path):
    sb = tmp_path / "serve_bundle"; (sb / "adapters" / "think1").mkdir(parents=True)
    r = subprocess.run([sys.executable, str(ROOT / "scripts/a6000/p12_plan.py"), "--serve-bundle", str(sb), "--arms", "v12_think1", "--dry-run"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]
    out = json.loads(r.stdout); assert out["steps"] == ["probe_pair", "pair_s50", "p4_adapter"] and out["adapters"] == ["think1"]
    r = subprocess.run([sys.executable, str(ROOT / "scripts/a6000/p12_plan.py"), "--serve-bundle", str(sb), "--arms", "v12_nope", "--dry-run"], capture_output=True, text=True)
    assert r.returncode != 0 and "v12_nope" in r.stderr


def _bundle(root, name, weight=b"W" * 64, with_manifest=True, bad_sha=False):
    b = root / f"v12_{name}"; (b / "adapters" / name).mkdir(parents=True); (b / "prompts").mkdir()
    (b / "agent.yaml").write_text(f"name: a\nadapter: {name}\n"); (b / "prompts" / "system.md").write_text("S")
    (b / "adapters" / name / "adapter_config.json").write_text(json.dumps({"r": 16, "peft_type": "LORA"}))
    (b / "adapters" / name / "adapter_model.safetensors").write_bytes(weight)
    if with_manifest:
        files = {f"{name}/adapter_model.safetensors": ("0" * 64) if bad_sha else hashlib.sha256(weight).hexdigest(),
                 f"{name}/adapter_config.json": hashlib.sha256((b / "adapters" / name / "adapter_config.json").read_bytes()).hexdigest()}
        (b / "adapters" / "MANIFEST.json").write_text(json.dumps({"files": files}))
    return b


def test_union_bundle_merges_adapters_and_checks_shas(tmp_path):
    U = _mod("union_bundle")
    a, b, c = _bundle(tmp_path, "think1"), _bundle(tmp_path, "think1f", b"F" * 64), _bundle(tmp_path, "think2", b"2" * 64, with_manifest=False)
    rep = U.build(tmp_path / "serve", [a, b, c])
    assert [r["adapter"] for r in rep] == ["think1", "think1f", "think2"]
    out = tmp_path / "serve"
    assert (out / "agent.yaml").read_text().startswith("name: a") and (out / "prompts" / "system.md").is_file()
    assert sorted(p.name for p in (out / "adapters").iterdir()) == ["MANIFEST.json", "think1", "think1f", "think2"]
    man = json.loads((out / "adapters" / "MANIFEST.json").read_text())
    assert man["adapters"] == ["think1", "think1f", "think2"] and set(man["files"]) == {f"{n}/{f}" for n in man["adapters"] for f in ("adapter_config.json", "adapter_model.safetensors")}
    assert man["files"]["think1f/adapter_model.safetensors"] == hashlib.sha256(b"F" * 64).hexdigest()
    assert (out / "adapters" / "think2" / "adapter_model.safetensors").read_bytes() == b"2" * 64
    # a corrupted source refuses; a duplicate name refuses
    bad = _bundle(tmp_path / "x", "think3", b"3" * 64, bad_sha=True)
    try:
        U.build(tmp_path / "serve2", [a, bad]); assert False, "sha mismatch accepted"
    except SystemExit as e:
        assert "sha256 mismatch" in str(e)
    dup = _bundle(tmp_path / "y", "think1")
    try:
        U.build(tmp_path / "serve3", [a, dup]); assert False, "duplicate accepted"
    except SystemExit as e:
        assert "appears in both" in str(e)
    r = subprocess.run([sys.executable, str(ROOT / "scripts/a6000/union_bundle.py"), str(tmp_path / "serve4"), str(a), str(b)], capture_output=True, text=True)
    assert r.returncode == 0 and "2 adapters" in r.stdout, r.stderr[-400:]


def test_choose_picks_the_best_net_that_is_not_worse_and_falls_back_to_the_reference(tmp_path):
    C = _mod("p12_choose")
    arms = ["v12_think1", "v12_think1f", "v12_think2"]
    cs = {"v12_think1": {"n": 50, "wins": 6, "losses": 4, "p": 0.75, "cap_gap": 0.0, "verdict": "NO EVIDENCE"},
          "v12_think1f": {"n": 50, "wins": 9, "losses": 3, "p": 0.15, "cap_gap": -0.1, "verdict": "NO EVIDENCE"},
          "v12_think2": {"n": 50, "wins": 2, "losses": 11, "p": 0.02, "cap_gap": 0.3, "verdict": "WORSE"}}
    arm, got = C.choose("/x", ["a"], arms, "v12", contrast=lambda a: cs[a])
    assert arm == "v12_think1f" and got == cs
    # think2's generator is unconfirmed: it is contrasted and logged but never p4_arm, even with the best net
    top2 = dict(cs); top2["v12_think2"] = {"n": 50, "wins": 15, "losses": 1, "p": 0.001, "cap_gap": 0.0, "verdict": "BETTER"}
    arm2, got2 = C.choose("/x", ["a"], arms, "v12", contrast=lambda a: top2[a])
    assert arm2 == "v12_think1f" and got2["v12_think2"]["verdict"] == "BETTER" and "v12_think2" in C.NOT_SUBMITTABLE
    assert C.choose("/x", ["a"], arms, "v12", contrast=lambda a: top2[a], not_submittable=frozenset())[0] == "v12_think2"
    tie = dict(cs); tie["v12_think1f"] = dict(cs["v12_think1f"], wins=6, losses=4)
    assert C.choose("/x", ["a"], arms, "v12", contrast=lambda a: tie[a])[0] == "v12_think1"          # ties: listed order
    worse = {a: dict(c, verdict="WORSE") for a, c in cs.items()}
    assert C.choose("/x", ["a"], arms, "v12", contrast=lambda a: worse[a])[0] == "v12"                # all WORSE: the control is screened
    f = tmp_path / "choice.json"; f.write_text(json.dumps({"p3_arm": "v12"}))
    C.write_choice(f, "v12_think1f")
    assert json.loads(f.read_text()) == {"p3_arm": "v12", "p4_arm": "v12_think1f"}
