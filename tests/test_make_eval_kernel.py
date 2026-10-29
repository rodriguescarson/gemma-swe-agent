"""scripts/make_eval_kernel.py mirrors the host's Getting Started notebook (2026-09-29).

Regressions this pins:
- The budget came from CLI defaults (6 min / 60 calls / 80 turns / 180 s) that matched no bundle (v10 is 5 / 100 / 200 /
  180), while the host notebook reads the bundle's eval_config.yaml (research/org_update_0928.md 2.1 and 2.2).
- The kernel passed default_chat_template_kwargs={'enable_thinking': True}, which the host removed in its 2026-09-27
  19:50 UTC run (ref/getting_started_20260927 is that run's notebook).
- A build without --ids ran every task in the competition's tasks.jsonl (129, of which 55 are ungradable even with the gold
  patch); a garble run spent 3.8 h on them. Non-oracle builds now default --ids to data/kaggle_valid_ids.txt (74 ids),
  --all-tasks is the only way to run everything, the kernel asserts every requested id was found, and failed grades keep
  the tail of their test output (2026-10-29).
- The notebook serves the 31B weights whatever the bundle declares, so a bundle declaring the 12B, E4B or E2B was graded with
  31B weights under the small model's name; a non-oracle build now refuses it unless --allow-model-mismatch is given.
- Kernel grading uses timeout_seconds as the Phase 2 pytest timeout (swegemma 0.2.11 has no separate field) while the
  scorer fixes it at 300 s: the run cell says so and the build prints a note when timeout_seconds is not 300.
"""
import ast, importlib.util, json, pathlib, subprocess, sys, time, types
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_eval_kernel.py"
HOST_NB = ROOT / "ref" / "getting_started_20260927" / "getting-started-gemma-4-developer-agent.ipynb"
IDS = ROOT / "data" / "kaggle_valid_ids.txt"


def _mod():
    spec = importlib.util.spec_from_file_location("make_eval_kernel", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build(tmp_path, bundle, slug, *flags, check=True):
    r = subprocess.run([sys.executable, str(SCRIPT), str(bundle), slug, *flags], cwd=tmp_path, capture_output=True,
                       text=True, timeout=60)
    if check:
        assert r.returncode == 0, r.stderr[-2000:]
    return r


def cells(tmp_path, slug):
    nb = json.loads((tmp_path / "kernels" / slug / (slug + ".ipynb")).read_text())
    return [c["source"] for c in nb["cells"]]


def ns_value(src, name):
    """The literal assigned to `name` at module level of a cell."""
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


def bundle_dir(tmp_path, eval_config=None, name="b"):
    b = tmp_path / name
    b.mkdir()
    (b / "agent.yaml").write_text("name: a\nmodel: gemma-4-31b-it-qat-w4a16-ct\ninstruction: hi\n")
    if eval_config is not None:
        (b / "eval_config.yaml").write_text(eval_config)
    return b


# ------------------------------------------------------------------------------------------------------------ budget
@pytest.mark.parametrize("bundle,want", [
    ("v10", {"max_time_minutes": 5.0, "max_tool_calls": 100, "max_turns": 200, "timeout_seconds": 180}),
    ("v4", {"max_time_minutes": 5.0, "max_tool_calls": 70, "max_turns": 150, "timeout_seconds": 180}),
    ("v9_eog", {"max_time_minutes": 5.0, "max_tool_calls": 70, "max_turns": 150, "timeout_seconds": 180}),
])
def test_budget_comes_from_eval_config(tmp_path, bundle, want):
    """Base case: no budget flag, so every key is the bundle's own (the old defaults 6/60/80 matched no bundle)."""
    r = build(tmp_path, ROOT / "submissions" / bundle, "t-" + bundle, "--ids", str(IDS))
    src = cells(tmp_path, "t-" + bundle)[1]
    assert ns_value(src, "EXPECTED_BUDGET") == want
    assert ns_value(src, "BUDGET_OVERRIDE") == {}
    assert "from eval_config.yaml" in r.stdout and json.dumps(want, sort_keys=True) in r.stdout


def test_flag_overrides_only_its_key(tmp_path):
    r = build(tmp_path, ROOT / "submissions" / "v10", "t-ovr", "--ids", str(IDS), "--calls", "70", "--min", "6")
    src = cells(tmp_path, "t-ovr")[1]
    assert ns_value(src, "EXPECTED_BUDGET") == {"max_time_minutes": 6.0, "max_tool_calls": 70, "max_turns": 200,
                                                "timeout_seconds": 180}
    assert ns_value(src, "BUDGET_OVERRIDE") == {"max_time_minutes": 6.0, "max_tool_calls": 70}
    assert "flags max_time_minutes,max_tool_calls" in r.stdout


@pytest.mark.parametrize("text,want", [
    ("evaluation:\n  max_tool_calls: 10\n", (60.0, 10, None, 300)),                     # host defaults
    ("max_tool_calls: 12\ntimeout_seconds: 90\n", (60.0, 12, None, 90)),                # top level, no section
    ("evaluation:\n  max_llm_calls: 33\n", (60.0, 100, 33, 300)),                       # turns fallback key
    ("evaluation:\n  max_turns: 7\n  max_llm_calls: 33\n", (60.0, 100, 7, 300)),        # max_turns wins
    ("evaluation:\n  max_turns: null\n  max_time_minutes: 5\n", (5.0, 100, None, 300)),
    ("# budget\nevaluation:   # section\n  max_time_minutes: 4.5  # minutes\n  timeout_seconds: '120'\n",
     (4.5, 100, None, 120)),                                                            # comments, quoted int
])
def test_host_budget_semantics(tmp_path, text, want):
    """Edge cases of the host's reading (cell 10): defaults, top-level keys, the max_llm_calls fallback, null turns,
    comments and a quoted number. The stdlib reader and PyYAML agree on every case."""
    m = _mod()
    b = bundle_dir(tmp_path, text)
    got, _ = m.read_budget(str(b))
    assert (got["max_time_minutes"], got["max_tool_calls"], got["max_turns"], got["timeout_seconds"]) == want
    got2, _ = m.read_budget(str(b), use_yaml=False)
    assert got2 == got
    assert isinstance(got["max_time_minutes"], float) and isinstance(got["timeout_seconds"], int)


def test_mini_yaml_equals_pyyaml_on_every_bundle():
    yaml = pytest.importorskip("yaml")
    m = _mod()
    seen = 0
    for p in sorted((ROOT / "submissions").glob("*/eval_config.yaml")):
        text = p.read_text()
        assert m.mini_yaml(text) == yaml.safe_load(text), p
        seen += 1
    assert seen >= 10


def test_mini_yaml_refuses_what_it_cannot_read():
    m = _mod()
    for bad in ("evaluation:\n  - 5\n", "evaluation: {max_tool_calls: 5}\n", "x:\n    - y\n", "  indented: 1\n",
                "evaluation:\n  max_turns: [1, 2]\n"):
        with pytest.raises(ValueError):
            m.mini_yaml(bad)


def test_missing_eval_config_needs_all_four_flags(tmp_path):
    """The host notebook crashes on a bundle without eval_config.yaml; the builder refuses unless every key is given."""
    b = bundle_dir(tmp_path)
    r = build(tmp_path, b, "t-miss", "--calls", "10", check=False)
    assert r.returncode != 0 and "no eval_config.yaml" in r.stderr
    assert not (tmp_path / "kernels" / "t-miss").exists()
    build(tmp_path, b, "t-miss2", "--min", "5", "--calls", "10", "--turns", "20", "--timeout", "60")
    assert ns_value(cells(tmp_path, "t-miss2")[1], "EXPECTED_BUDGET") == {
        "max_time_minutes": 5.0, "max_tool_calls": 10, "max_turns": 20, "timeout_seconds": 60}


def _run_budget_cell(src, agent_dir):
    """Execute the data cell's budget part (everything from 'import yaml' on, minus the task loading) with the bundle
    already written to agent_dir, as the kernel would."""
    head, _, rest = src.partition("\nimport yaml\n")
    body = "import yaml\n" + rest.split("\nfrom swegemma.models import load_tasks")[0]
    ns = {"AGENT_DIR": agent_dir, "BUDGET_OVERRIDE": ns_value(src, "BUDGET_OVERRIDE"),
          "EXPECTED_BUDGET": ns_value(src, "EXPECTED_BUDGET")}
    exec(compile(body, "cell", "exec"), ns)
    return ns["BUDGET"]


def test_kernel_reads_the_same_budget_and_stops_on_drift(tmp_path):
    """The kernel's own reading (the host's code) equals the builder's; if the bundle's file changed after the build,
    the kernel stops in the data cell, before vLLM starts (no GPU time spent)."""
    pytest.importorskip("yaml")
    b = bundle_dir(tmp_path, "evaluation:\n  max_time_minutes: 5\n  timeout_seconds: 180\n  max_tool_calls: 100\n"
                              "  max_turns: 200\n")
    build(tmp_path, b, "t-exec", "--turns", "150")
    src = cells(tmp_path, "t-exec")[1]
    assert _run_budget_cell(src, b) == {"max_time_minutes": 5.0, "max_tool_calls": 100, "max_turns": 150,
                                        "timeout_seconds": 180}
    (b / "eval_config.yaml").write_text("evaluation:\n  max_time_minutes: 6\n")
    with pytest.raises(AssertionError, match="budget differs"):
        _run_budget_cell(src, b)
    all_src = cells(tmp_path, "t-exec")
    vllm_cell = next(i for i, s in enumerate(all_src) if "VllmConfig(" in s)
    budget_cell = next(i for i, s in enumerate(all_src) if "assert BUDGET == EXPECTED_BUDGET" in s)
    assert budget_cell < vllm_cell


# ------------------------------------------------------------------------------------------------ host parity
def _calls(src_list, names):
    """{call name: {kwarg: source text}} for every call of `names` in the given cell sources."""
    out = {}
    for src in src_list:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
                if fn in names:
                    out[fn] = {k.arg: ast.unparse(k.value) for k in node.keywords}
    return out


def _literal(s):
    try:
        return ast.literal_eval(s)
    except Exception:
        return None


def host_cells():
    nb = json.loads(HOST_NB.read_text())
    return ["".join(c["source"]) if isinstance(c["source"], list) else c["source"] for c in nb["cells"]
            if c["cell_type"] == "code"]


def test_host_reference_is_the_0927_run():
    """The reference copy is the run without the thinking flag and with eval_config budgets (org_update_0928 2.1)."""
    src = "\n".join(host_cells())
    assert "enable_thinking" not in src and "eval_config.yaml" in src and "default_chat_template_kwargs" not in src


def test_kernel_mirrors_host_notebook(tmp_path):
    """VllmConfig, EventsCompactionConfig and ContextCacheConfig take the same keywords with the same literal values as
    the host notebook; the thinking flag is gone; EvalConfig gets the same keywords (the budget via **BUDGET)."""
    build(tmp_path, ROOT / "submissions" / "v10", "t-par", "--ids", str(IDS))
    ours = _calls(cells(tmp_path, "t-par"), {"VllmConfig", "EventsCompactionConfig", "ContextCacheConfig", "EvalConfig"})
    host = _calls(host_cells(), {"VllmConfig", "EventsCompactionConfig", "ContextCacheConfig", "EvalConfig"})
    assert set(ours) == set(host) == {"VllmConfig", "EventsCompactionConfig", "ContextCacheConfig", "EvalConfig"}
    for name in ("VllmConfig", "EventsCompactionConfig", "ContextCacheConfig"):
        assert set(ours[name]) == set(host[name]), (name, set(ours[name]) ^ set(host[name]))
        for k, v in host[name].items():
            if _literal(v) is not None:
                assert _literal(ours[name][k]) == _literal(v), (name, k, ours[name][k], v)
    assert "default_chat_template_kwargs" not in ours["VllmConfig"]
    assert {k: _literal(v) for k, v in ours["EventsCompactionConfig"].items()} == {
        "compaction_interval": 15, "overlap_size": 2, "token_threshold": 14336, "event_retention_size": 5}
    budget = {"timeout_seconds", "max_time_minutes", "max_tool_calls", "max_turns"}
    assert set(host["EvalConfig"]) - budget == set(ours["EvalConfig"]) - {None}, \
        set(host["EvalConfig"]) ^ set(ours["EvalConfig"])
    assert budget <= set(host["EvalConfig"]) and None in ours["EvalConfig"]          # None = the **BUDGET splat
    src = "\n".join(cells(tmp_path, "t-par"))
    assert "enable_thinking" not in src


def test_budget_lines_are_the_hosts(tmp_path):
    """The kernel's budget reading is the host's cell-10 code line for line (after the file read)."""
    host = "\n".join(host_cells())
    want = [ln.strip() for ln in host.splitlines() if ln.strip().startswith((
        "eval_section =", "timeout_seconds =", "max_tool_calls =", "max_time_minutes =", "turns_raw =", "max_turns ="))]
    assert len(want) == 6
    build(tmp_path, ROOT / "submissions" / "v10", "t-lines")
    ours = {ln.strip() for ln in cells(tmp_path, "t-lines")[1].splitlines()}
    for ln in want:
        assert ln in ours, ln


def test_every_cell_compiles_and_builds_fast(tmp_path):
    t0 = time.monotonic()
    build(tmp_path, ROOT / "submissions" / "v10", "t-fast", "--ids", str(IDS))
    assert time.monotonic() - t0 < 10
    for c in cells(tmp_path, "t-fast"):
        compile(c, "cell", "exec")
    meta = json.loads((tmp_path / "kernels" / "t-fast" / "kernel-metadata.json").read_text())
    assert meta["machine_shape"] == "NvidiaL4" and meta["enable_gpu"] is True and meta["enable_internet"] is False
    assert meta["dataset_sources"] == ["metric/gemma-4-developer-agent-wheelhouse"]
    assert meta["model_sources"] == ["google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2"]


def test_kernel_records_the_wheel_set(tmp_path):
    """A/B pairing needs the wheel set by content (vllm and adk_submission were rebuilt in place under unchanged version
    strings on 2026-09-27): the install cell writes wheelhouse_sha256.txt before vLLM starts."""
    build(tmp_path, ROOT / "submissions" / "v10", "t-sha")
    src = cells(tmp_path, "t-sha")
    assert "wheelhouse_sha256.txt" in src[0] and "hashlib.sha256()" in src[0]
    assert not any("VllmConfig(" in c for c in src[:1])


def test_probe_lora_adds_probe_and_routing_cells(tmp_path):
    # docs/v11/GA_PROBE.md: the probe cell runs between vLLM startup and the agent smoke; routing check after it
    sys.path.insert(0, str(ROOT / "scripts")); import make_test_adapters as M
    M.build(str(ROOT / "submissions" / "v4"), str(tmp_path / "pb"), 20261003)
    ids = tmp_path / "ids.txt"; ids.write_text("rich_3006\nrich_3067\n")
    build(tmp_path, tmp_path / "pb", "g4-l4-lora-probe", "--ids", str(ids), "--probe", "lora")
    cs = cells(tmp_path, "g4-l4-lora-probe")
    assert len(cs) == 6 and "ADAPTER_NAMES = [\"loud\", \"loud2\", \"zb\"]" in cs[3] and "lora_probe.json" in cs[3]
    assert "P6_agent_smoke" in cs[5] and "GA_PRE_SMOKE" in cs[3]
    for c in cs:
        compile(c, "<cell>", "exec")
    nb = (tmp_path / "kernels" / "g4-l4-lora-probe" / "g4-l4-lora-probe.ipynb").stat().st_size
    assert nb < 1_000_000, nb
    assert "adapters/zb/adapter_model.safetensors" in cs[1]
    r = build(tmp_path, ROOT / "submissions" / "v4", "nope", "--probe", "lora", check=False)
    assert r.returncode != 0 and "needs a bundle with adapters" in (r.stdout + r.stderr)


def test_pin_original_and_kernel_id_reuse_an_older_slug_environment(tmp_path):
    # E2 (docs/PLAN_TO_FINISH.txt): Kaggle's image moved to Python 3.13 and the wheelhouse has only cp312 wheels; new
    # versions of a slug created under 3.12, pushed with docker_image_pinning_type=original, keep the 3.12 image
    ids = tmp_path / "ids.txt"; ids.write_text("rich_3006\n")
    build(tmp_path, ROOT / "submissions" / "v4", "g4-l4-v4h2", "--ids", str(ids), "--pin", "original", "--kernel-id", "g4-l4-v4")
    meta = json.loads((tmp_path / "kernels" / "g4-l4-v4h2" / "kernel-metadata.json").read_text())
    assert meta["id"] == "carsonrodrigues/g4-l4-v4" and meta["title"] == "g4-l4-v4" and meta["code_file"] == "g4-l4-v4.ipynb"
    assert meta["docker_image_pinning_type"] == "original"
    assert (tmp_path / "kernels" / "g4-l4-v4h2" / "g4-l4-v4.ipynb").exists()
    meta2 = json.loads(json.dumps(meta))
    build(tmp_path, ROOT / "submissions" / "v4", "plain", "--ids", str(ids))
    assert "docker_image_pinning_type" not in json.loads((tmp_path / "kernels" / "plain" / "kernel-metadata.json").read_text())


def test_install_cell_filters_wheels_by_interpreter_tags(tmp_path):
    m = _mod()
    names = ["adk_eval_core-0.1.0-py3-none-any.whl", "cbor2-6.1.4-cp312-cp312-manylinux_2_28_x86_64.whl",
             "vllm-0.19.1-cp38-abi3-manylinux_2_31_x86_64.whl", "xgrammar-0.1.0-cp313-cp313-manylinux_2_28_x86_64.whl"]
    ok, bad = m.split_wheels_by_tags(names, python_tag="cp313")
    assert "cbor2-6.1.4-cp312-cp312-manylinux_2_28_x86_64.whl" in bad and "xgrammar-0.1.0-cp313-cp313-manylinux_2_28_x86_64.whl" in ok
    assert "vllm-0.19.1-cp38-abi3-manylinux_2_31_x86_64.whl" in ok and "adk_eval_core-0.1.0-py3-none-any.whl" in ok
    ok12, bad12 = m.split_wheels_by_tags(names, python_tag="cp312")
    assert not [b for b in bad12 if "cp312" in b] and "xgrammar-0.1.0-cp313-cp313-manylinux_2_28_x86_64.whl" in bad12
    ids = tmp_path / "ids.txt"; ids.write_text("rich_3006\n")
    build(tmp_path, ROOT / "submissions" / "v4", "k", "--ids", str(ids))
    assert "split_wheels_by_tags" in cells(tmp_path, "k")[0] and "incompatible wheels for this interpreter" in cells(tmp_path, "k")[0]


def test_probe_cell_scores_every_loud_adapter_and_maps_its_prefix(tmp_path):
    """G-A2: P1 must consider every adapter named loud*, and the prefix verdict must name the style of the loudest
    adapter that passes (plan_A for loud/loud_all, then loud2, loud3, loud4)."""
    src = SCRIPT.read_text()
    cell = src[src.index("CELL_PROBE = "):]
    assert "startswith('loud')" in cell and "PREFIX_OF" in cell
    for name in ("'loud_all': 'plan_A'", "'loud3': 'loud3'", "'loud4': 'loud4'"):
        assert name in cell


def test_adapters_dataset_option_keeps_weights_out_of_the_notebook(tmp_path):
    """--adapters-dataset owner/slug: adapter weights come from the Kaggle dataset (flat <name>__adapter_model.safetensors),
    the manifest and configs stay embedded, the data cell copies the weights into the bundle and stops on a sha mismatch,
    and the dataset is a kernel dataset source."""
    arm = ROOT / "eval" / "golden" / "arms" / "v4_lora_probe"
    if not (arm / "eval_config.yaml").is_file() or not any(arm.glob("adapters/*/*.safetensors")):
        pytest.skip("eval/golden/arms/v4_lora_probe (with its adapter weights) not present: eval/golden/arms/ is "
                    "gitignored, built locally")
    ids = tmp_path / "ids.txt"; ids.write_text("rich_3006\n")
    build(tmp_path, ROOT / "eval" / "golden" / "arms" / "v4_lora_probe", "k", "--ids", str(ids), "--probe", "lora",
          "--adapters-dataset", "carsonrodrigues/g4-adapters-probe2")
    cs = cells(tmp_path, "k")
    files = ns_value(cs[1], "FILES")
    assert not any(k.endswith(".safetensors") for k in files), [k for k in files if k.endswith(".safetensors")]
    assert "adapters/MANIFEST.json" in files and "adapters/zb/adapter_config.json" in files
    assert ns_value(cs[1], "ADAPTERS_DATASET") == "carsonrodrigues/g4-adapters-probe2" and "sha mismatch" in cs[1] and "__adapter_model.safetensors" in cs[1]
    meta = json.loads((tmp_path / "kernels" / "k" / "kernel-metadata.json").read_text())
    assert "carsonrodrigues/g4-adapters-probe2" in meta["dataset_sources"]
    build(tmp_path, ROOT / "eval" / "golden" / "arms" / "v4_lora_probe", "k2", "--ids", str(ids), "--probe", "lora")
    assert any(k.endswith(".safetensors") for k in ns_value(cells(tmp_path, "k2")[1], "FILES"))   # default: embedded
    # 2026-10-04: json.dumps(None) wrote `ADAPTERS_DATASET = null` -> NameError in the kernel (g4-lora-test v3 ERROR)
    assert "ADAPTERS_DATASET = None" in cells(tmp_path, "k2")[1] and " = null" not in cells(tmp_path, "k2")[1]
    assert ns_value(cells(tmp_path, "k2")[1], "ADAPTERS_DATASET") is None


def test_helper_check_commands_follow_the_helper_set(tmp_path):
    """--helper-check probes the helpers that are actually shipped (v4h2f: edit/locate/test/check), not the Sep-27 set
    (run.py/gate.py); each probe must go through run_command with the literal /tmp/swe path the agent uses."""
    ids = tmp_path / "ids.txt"; ids.write_text("rich_3006\n")
    build(tmp_path, ROOT / "submissions" / "v4h2f", "hc", "--ids", str(ids), "--oracle", "--helper-check",
          str(ROOT / "submissions" / "v4h2f" / "skills" / "swe-tools" / "scripts"))
    cell = cells(tmp_path, "hc")[1]
    assert "HELPERS_B64" in cell and "_helper_check" in cell
    for h in ("locate.py", "test.py", "check.py", "edit.py"):
        assert f"/tmp/swe/{h}" in cell, h
    assert "if h not in HELPERS_B64: continue" in cell       # probes outside the shipped set are skipped at run time
    assert "HELPER_CHECK" in cell


def test_helper_check_probes_view_py_with_a_repeat(tmp_path):
    """v4h6g: view.py must show lines and refuse an exact repeat on the Kaggle sandbox, not only locally."""
    ids = tmp_path / "ids.txt"; ids.write_text("rich_3006\n")
    build(tmp_path, ROOT / "submissions" / "v4h6g", "hc6", "--ids", str(ids), "--oracle", "--helper-check",
          str(ROOT / "submissions" / "v4h6g" / "skills" / "swe-tools" / "scripts"))
    cell = cells(tmp_path, "hc6")[1]
    assert cell.count("python3 /tmp/swe/view.py pkg/mod.py 1 2") >= 2 and "ALREADY SHOWN" in cell


# ------------------------------------------------------------------------------------------------------ task selection
def ids_of(tmp_path, slug):
    return ns_value(cells(tmp_path, slug)[1], "IDS")


def test_default_build_embeds_the_74_valid_ids_from_any_cwd(tmp_path):
    """No --ids: the 74 graded ids, read from the repository's data/ (build() runs with cwd=tmp_path, which has none)."""
    want = IDS.read_text().split()
    assert len(want) == 74
    r = build(tmp_path, ROOT / "submissions" / "v10", "t-default")
    assert ids_of(tmp_path, "t-default") == want
    assert " 74 tasks " in r.stdout


def test_all_tasks_flag_embeds_no_id_filter(tmp_path):
    r = build(tmp_path, ROOT / "submissions" / "v10", "t-all", "--all-tasks")
    assert ids_of(tmp_path, "t-all") == [] and " all tasks " in r.stdout


def test_explicit_ids_win_over_the_default(tmp_path):
    ids = tmp_path / "ids.txt"; ids.write_text("rich_3006\n\nrich_3067\n")
    build(tmp_path, ROOT / "submissions" / "v10", "t-two", "--ids", str(ids))
    assert ids_of(tmp_path, "t-two") == ["rich_3006", "rich_3067"]


def test_oracle_builds_keep_running_every_task_without_ids(tmp_path):
    """oracle_all grades the gold patch of every task in tasks.jsonl; only agent builds default to the 74."""
    build(tmp_path, ROOT / "submissions" / "v10", "t-oracle", "--oracle")
    assert ids_of(tmp_path, "t-oracle") == []
    build(tmp_path, ROOT / "submissions" / "v10", "t-oracle74", "--oracle", "--ids", str(IDS))
    assert len(ids_of(tmp_path, "t-oracle74")) == 74


def test_all_tasks_and_ids_are_exclusive(tmp_path):
    r = build(tmp_path, ROOT / "submissions" / "v10", "t-both", "--all-tasks", "--ids", str(IDS), check=False)
    assert r.returncode != 0 and "--all-tasks and --ids are exclusive" in r.stderr
    assert not (tmp_path / "kernels" / "t-both").exists()


def test_a_missing_or_empty_ids_file_stops_the_build_instead_of_running_everything(tmp_path):
    """An empty IDS list is 'no filter' in the kernel, so an empty file would silently run all 129 tasks."""
    r = build(tmp_path, ROOT / "submissions" / "v10", "t-nofile", "--ids", str(tmp_path / "nope.txt"), check=False)
    assert r.returncode != 0 and "not found" in r.stderr and "--all-tasks" in r.stderr
    empty = tmp_path / "empty.txt"; empty.write_text("\n \n")
    r = build(tmp_path, ROOT / "submissions" / "v10", "t-empty", "--ids", str(empty), check=False)
    assert r.returncode != 0 and "lists no task ids" in r.stderr
    assert not (tmp_path / "kernels" / "t-nofile").exists() and not (tmp_path / "kernels" / "t-empty").exists()


def _run_tasks_cell(src, ids, available, monkeypatch, capsys):
    """Execute the data cell's task-loading tail against a fake swegemma.models.load_tasks returning `available`."""
    fake = types.ModuleType("swegemma.models")
    fake.load_tasks = lambda path: [types.SimpleNamespace(instance_id=i) for i in available]
    monkeypatch.setitem(sys.modules, "swegemma", types.ModuleType("swegemma"))
    monkeypatch.setitem(sys.modules, "swegemma.models", fake)
    body = "from swegemma.models import load_tasks" + src.split("\nfrom swegemma.models import load_tasks", 1)[1]
    ns = {"DATA_DIR": pathlib.Path("/none"), "IDS": ids, "ORACLE": False, "BUDGET": {"max_turns": 1}}
    exec(compile(body, "cell", "exec"), ns)
    return ns["tasks"], capsys.readouterr().out


def test_generated_cell_asserts_every_requested_id_was_found_and_prints_the_count(tmp_path, monkeypatch, capsys):
    build(tmp_path, ROOT / "submissions" / "v10", "t-assert")
    src = cells(tmp_path, "t-assert")[1]
    assert "assert len(tasks) == len(set(IDS))" in src
    available = ["a", "b", "c", "d"]
    tasks, out = _run_tasks_cell(src, ["a", "c"], available, monkeypatch, capsys)
    assert [t.instance_id for t in tasks] == ["a", "c"] and "2 tasks of 2 requested ids" in out
    tasks, out = _run_tasks_cell(src, ["a", "a", "c"], available, monkeypatch, capsys)       # a repeated id is one task
    assert len(tasks) == 2 and "2 tasks of 2 requested ids" in out
    with pytest.raises(AssertionError, match="requested ids missing from tasks.jsonl") as e:
        _run_tasks_cell(src, ["a", "zz_1", "yy_2"], available, monkeypatch, capsys)
    assert "yy_2" in str(e.value) and "zz_1" in str(e.value)
    tasks, out = _run_tasks_cell(src, [], available, monkeypatch, capsys)                    # --all-tasks: no filter
    assert len(tasks) == 4 and "4 tasks (no id filter)" in out


def test_result_rows_keep_the_last_2500_characters_of_the_test_output(tmp_path):
    """Failed grades could not be diagnosed: err is empty in 54 of 55 failing gold rows, and the test output was dropped."""
    build(tmp_path, ROOT / "submissions" / "v10", "t-tail")
    run_cell = next(c for c in cells(tmp_path, "t-tail") if "evaluate_task(" in c)
    exprs = [kw.value for node in ast.walk(ast.parse(run_cell)) if isinstance(node, ast.Call)
             and getattr(node.func, "id", None) == "dict" for kw in node.keywords if kw.arg == "test_tail"]
    assert len(exprs) == 1
    tail = eval(compile(ast.Expression(exprs[0]), "cell", "eval"),
                {"r": types.SimpleNamespace(test_output="x" * 3000 + "FAILED tests/test_a.py::test_b - AssertionError")})
    assert len(tail) == 2500 and tail.endswith("FAILED tests/test_a.py::test_b - AssertionError") and set(tail[:10]) == {"x"}
    assert eval(compile(ast.Expression(exprs[0]), "cell", "eval"), {"r": types.SimpleNamespace(test_output=None)}) == ""
    assert eval(compile(ast.Expression(exprs[0]), "cell", "eval"), {"r": types.SimpleNamespace(test_output="short")}) == "short"


# ------------------------------------------------------------------------------- the test_tail / result row against swegemma
def _row_call(tmp_path, slug):
    """The `dict(cfg=..., test_tail=...)` call that builds a result row in the generated run cell."""
    build(tmp_path, ROOT / "submissions" / "v10", slug)
    run_cell = next(c for c in cells(tmp_path, slug) if "evaluate_task(" in c)
    calls = [node for node in ast.walk(ast.parse(run_cell)) if isinstance(node, ast.Call)
             and getattr(node.func, "id", None) == "dict" and any(kw.arg == "test_tail" for kw in node.keywords)]
    assert len(calls) == 1
    return calls[0]


def test_test_tail_expression_reads_a_real_swegemma_task_result(tmp_path):
    """The row expression runs against swegemma's own TaskResult, not a stand-in namespace: a renamed attribute (the stub
    above would not notice) fails here. TaskResult accepts any keyword (extra='allow'), so the guard is to read every
    attribute off a default-constructed result, which has only the declared fields."""
    task = pytest.importorskip("swegemma.models.task")
    call = _row_call(tmp_path, "t-real")
    row_expr = ast.Expression(call)
    tail_expr = ast.Expression(next(kw.value for kw in call.keywords if kw.arg == "test_tail"))
    for field in ("test_output", "resolved", "test_exit_code", "tool_calls", "agent_patch"):
        assert field in task.TaskResult.model_fields, field
    ev = lambda e, r, **env: eval(compile(e, "cell", "eval"), {"r": r, **env})
    # a default result: every attribute the row reads exists, the tail is empty
    assert ev(tail_expr, task.TaskResult(task_id="t0")) == ""
    env = dict(cfg="c", t=types.SimpleNamespace(instance_id="x_1"), s=time.time(), time=time)
    row = ev(row_expr, task.TaskResult(task_id="x_1"), **env)
    assert row["id"] == "x_1" and row["resolved"] is False and row["exit"] == 0 and row["calls"] == 0
    assert row["err"] is None and row["patch"] == "" and row["test_tail"] == ""
    # a failed grade: the last 2500 characters of the real field
    out = "x" * 3000 + "FAILED tests/test_a.py::test_b - AssertionError"
    r = task.TaskResult(task_id="x_1", test_output=out, resolved=False, test_exit_code=1, tool_calls=7, agent_patch="diff",
                        error="boom")
    row = ev(row_expr, r, **env)
    assert len(row["test_tail"]) == 2500 and row["test_tail"].endswith("AssertionError") and row["test_tail"] == out[-2500:]
    assert (row["exit"], row["calls"], row["patch"], row["err"]) == (1, 7, "diff", "boom")


# ----------------------------------------------------------------------------------- the model the notebook serves
E4B = "gemma-4-e4b-it-qat-w4a16-ct"
ALL_BUDGET = ["--min", "5", "--calls", "10", "--turns", "20", "--timeout", "60"]


def model_bundle(tmp_path, model, name="mb", eval_config="evaluation:\n  timeout_seconds: 180\n"):
    b = bundle_dir(tmp_path, eval_config, name)
    (b / "agent.yaml").write_text("name: a\nmodel: %s\ninstruction: hi\n" % model)
    return b


@pytest.mark.parametrize("model", [E4B, "gemma-4-12b-it-qat-w4a16-ct", "gemma-4-e2b-it-qat-w4a16-ct"])
def test_a_bundle_declaring_a_small_model_is_refused(tmp_path, model):
    """The kernel serves MODEL_PATH = the 31B weights and registers the declared name as an alias of it, so the build
    refuses before writing anything."""
    r = build(tmp_path, model_bundle(tmp_path, model), "t-small", check=False)
    assert r.returncode != 0 and model in r.stderr and "gemma-4-31b-it-qat-w4a16-ct" in r.stderr, r.stderr
    assert "--allow-model-mismatch" in r.stderr and "31B weights" in r.stderr
    assert not (tmp_path / "kernels" / "t-small").exists()


def test_the_repository_e4b_bundles_are_refused_and_the_31b_ones_build(tmp_path):
    """submissions/v12b_e4b and v12b_e4b_card (sub24/sub25) declare the E4B; v12b, the same prompt on the 31B, builds."""
    for name in ("v12b_e4b", "v12b_e4b_card"):
        r = build(tmp_path, ROOT / "submissions" / name, "t-" + name, check=False)
        assert r.returncode != 0 and E4B in r.stderr and not (tmp_path / "kernels" / ("t-" + name)).exists(), name
    build(tmp_path, ROOT / "submissions" / "v12b", "t-v12b")
    m = _mod()
    assert m.declared_models(str(ROOT / "submissions" / "v12b_e4b")) == {E4B}
    assert m.declared_models(str(ROOT / "submissions" / "v12b")) == {m.KERNEL_MODEL}


def test_allow_model_mismatch_builds_with_a_warning_and_still_serves_the_31b(tmp_path):
    r = build(tmp_path, model_bundle(tmp_path, E4B), "t-allow", "--allow-model-mismatch")
    assert "WARNING" in r.stderr and E4B in r.stderr and "31B weights" in r.stderr
    meta = json.loads((tmp_path / "kernels" / "t-allow" / "kernel-metadata.json").read_text())
    assert meta["model_sources"] == ["google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2"]
    vllm = next(c for c in cells(tmp_path, "t-allow") if "VllmConfig(" in c)
    assert "gemma-4-31b-it-qat-w4a16-ct/2" in vllm                     # the weights are still the 31B ones


def test_the_matching_bundle_builds_without_a_warning(tmp_path):
    r = build(tmp_path, bundle_dir(tmp_path, "evaluation:\n  timeout_seconds: 180\n"), "t-match")
    assert "WARNING" not in r.stderr and r.stderr == ""


def test_oracle_builds_are_not_checked_because_no_model_is_served(tmp_path):
    """--oracle (and --helper-check, --patches, which imply it) grade patches with no vLLM and no model_sources."""
    build(tmp_path, model_bundle(tmp_path, E4B), "t-oracle-e4b", "--oracle")
    meta = json.loads((tmp_path / "kernels" / "t-oracle-e4b" / "kernel-metadata.json").read_text())
    assert meta["model_sources"] == [] and meta["enable_gpu"] is False


def test_a_bundle_declaring_no_model_or_several_is_refused_even_with_the_flag(tmp_path):
    """The kernel's own check wants exactly one declared model, so --allow-model-mismatch cannot rescue these."""
    none = bundle_dir(tmp_path, "evaluation:\n  timeout_seconds: 180\n", "none")
    (none / "agent.yaml").write_text("name: a\ninstruction: hi\n")
    two = model_bundle(tmp_path, "gemma-4-31b-it-qat-w4a16-ct", "two")
    (two / "sub.yaml").write_text("name: s\nmodel: %s\n" % E4B)
    for b, what in ((none, "declares no model"), (two, "declares gemma-4-31b-it-qat-w4a16-ct, %s" % E4B)):
        r = build(tmp_path, b, "t-" + b.name, "--allow-model-mismatch", check=False)
        assert r.returncode != 0 and what in r.stderr and "exactly one" in r.stderr, (b.name, r.stderr)
        assert not (tmp_path / "kernels" / ("t-" + b.name)).exists()


def test_declared_models_reads_model_keys_from_every_yaml_file(tmp_path):
    m = _mod()
    b = tmp_path / "bx"
    (b / "agents").mkdir(parents=True); (b / ".hidden").mkdir(); (b / "prompts").mkdir()
    (b / "agent.yaml").write_text("name: a\nmodel: gemma-4-31b-it-qat-w4a16-ct   # the base\nsub_agents:\n  - config_path: agents/x.yaml\n")
    (b / "agents" / "x.yaml").write_text("name: x\nmodel: 'gemma-4-e4b-it-qat-w4a16-ct'\nmodel_name: ignored\nxmodel: ignored\n")
    (b / "agents" / "y.yml").write_text("- model: \"gemma-4-12b-it-qat-w4a16-ct\"\n")
    (b / ".hidden" / "z.yaml").write_text("model: hidden-model\n")
    (b / "prompts" / "system.md").write_text("model: not-a-yaml-file\n")
    assert m.declared_models(str(b)) == {"gemma-4-31b-it-qat-w4a16-ct", "gemma-4-e4b-it-qat-w4a16-ct", "gemma-4-12b-it-qat-w4a16-ct"}


def test_the_served_model_name_is_one_constant_across_the_notebook(tmp_path):
    """KERNEL_MODEL is what the check compares with; the cells and the metadata must name the same weights."""
    m = _mod()
    assert m.KERNEL_MODEL == "gemma-4-31b-it-qat-w4a16-ct"
    assert "/gemma-4-31b-it-qat-w4a16-ct/2" in m.CELL_VLLM and "aliases=[declared, 'gemma-4-31b-it-qat-w4a16-ct']" in m.CELL_VLLM
    build(tmp_path, ROOT / "submissions" / "v10", "t-const")
    assert json.loads((tmp_path / "kernels" / "t-const" / "kernel-metadata.json").read_text())["model_sources"] == [
        "google/gemma-4/Other/%s/2" % m.KERNEL_MODEL]


# --------------------------------------------------------------------------------------- the Phase 2 pytest timeout
def test_the_run_cell_says_verification_shares_the_command_timeout(tmp_path):
    """swegemma 0.2.11 has no separate verification timeout: its Phase 2 pytest uses timeout_seconds (180 for v12b), the
    scorer's is a fixed 300 s, so kernel grades can only err low on tests that take 180-300 s. A comment, no hack."""
    build(tmp_path, ROOT / "submissions" / "v10", "t-vt")
    run_cell = next(c for c in cells(tmp_path, "t-vt") if "evaluate_task(" in c)
    assert "no separate verification timeout" in run_cell and "can only err low" in run_cell and "300 s" in run_cell
    ev_cfg = run_cell[run_cell.index("# Phase 2"):run_cell.index("ec = EvalConfig(")]
    assert "command_timeout_seconds" in ev_cfg and "**BUDGET" in ev_cfg
    compile(run_cell, "cell", "exec")


def test_build_prints_a_note_when_the_kernel_timeout_is_not_the_scorers_300(tmp_path):
    low = build(tmp_path, ROOT / "submissions" / "v12b", "t-vlow")                  # timeout_seconds 180
    assert "timeout_seconds=180" in low.stdout and "takes 180-300 s fails here and passes there" in low.stdout
    assert "kernel grades can only err low" in low.stdout and low.stdout.count("note:") == 1
    exact = build(tmp_path, bundle_dir(tmp_path, "evaluation:\n  timeout_seconds: 300\n", "b300"), "t-v300")
    assert "note:" not in exact.stdout
    high = build(tmp_path, bundle_dir(tmp_path, "evaluation:\n  timeout_seconds: 600\n", "b600"), "t-v600")
    assert "takes 300-600 s passes here and fails there" in high.stdout and "can only err high" in high.stdout
    assert _mod().verification_timeout_note(300) is None


def test_the_installed_swegemma_still_has_no_separate_verification_timeout():
    """The assumption behind the note: swegemma 0.2.11 runs the Phase 2 pytest with harness.command_timeout_seconds. The live
    HARNESS_README (7.1) names config.harness.verification_timeout_seconds for the scorer's newer build. If the wheelhouse
    ever has it, set it to 300 in the run cell (HarnessLimits(verification_timeout_seconds=300)) and drop the note."""
    swegemma = pytest.importorskip("swegemma")
    hits = [str(f) for f in pathlib.Path(swegemma.__file__).parent.rglob("*.py") if "verification_timeout" in f.read_text(errors="replace")]
    assert not hits, "swegemma has a verification timeout now: set it to 300 in CELL_RUN (%s)" % hits
    text = (pathlib.Path(swegemma.__file__).parent / "harness" / "verification.py").read_text()
    assert "timeout=config.harness.command_timeout_seconds" in text
