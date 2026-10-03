"""scripts/make_eval_kernel.py mirrors the host's Getting Started notebook (2026-09-29).

Regressions this pins:
- The budget came from CLI defaults (6 min / 60 calls / 80 turns / 180 s) that matched no bundle (v10 is 5 / 100 / 200 /
  180), while the host notebook reads the bundle's eval_config.yaml (research/org_update_0928.md 2.1 and 2.2).
- The kernel passed default_chat_template_kwargs={'enable_thinking': True}, which the host removed in its 2026-09-27
  19:50 UTC run (ref/getting_started_20260927 is that run's notebook).
"""
import ast, importlib.util, json, pathlib, subprocess, sys, time
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
