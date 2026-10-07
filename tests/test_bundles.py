"""Every bundle that could be submitted must compile with the organisers' compiler and contain only allowed files.
Guards: .pyc/__pycache__ (sweep v2 died on this), AppleDouble ._ files (smoke run died), non-kebab skill names, unknown tools."""
import os, re, subprocess, sys, pathlib, pytest
ROOT = pathlib.Path(__file__).parent.parent
BUNDLES = sorted(p for p in (ROOT / "submissions").iterdir() if (p / "agent.yaml").exists())
REAL_TOOLS = {"run_command", "read_file", "edit_file", "write_file", "get_status", "submit_patch", "get_code_neighbors", "search_similar_code", "get_code_subgraph"}
ALLOWED_EXT = {".yaml", ".yml", ".md", ".txt", ".py", ".json", ".safetensors"}

@pytest.mark.parametrize("b", BUNDLES, ids=lambda p: p.name)
def test_bundle_files_are_clean(b):
    for dp, dns, fns in os.walk(b):
        assert "__pycache__" not in dns, f"{dp} has __pycache__"
        for f in fns:
            assert not f.startswith("._") and f != ".DS_Store", os.path.join(dp, f)
            assert pathlib.Path(f).suffix in ALLOWED_EXT, os.path.join(dp, f)

@pytest.mark.parametrize("b", BUNDLES, ids=lambda p: p.name)
def test_skill_names_are_kebab_case(b):
    for skill in (b / "skills").glob("*/SKILL.md") if (b / "skills").exists() else []:
        m = re.search(r"^name:\s*(\S+)", skill.read_text(), re.M)
        assert m and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", m.group(1)), skill

@pytest.mark.parametrize("b", BUNDLES, ids=lambda p: p.name)
def test_agents_only_use_real_tools(b):
    for y in list(b.glob("*.yaml")) + list(b.glob("sub_agents/*.yaml")):
        m = re.search(r"^tools:\s*\[(.*)\]", y.read_text(), re.M)
        if m:
            tools = {t.strip() for t in m.group(1).split(",") if t.strip()}
            assert tools <= REAL_TOOLS, (y, tools - REAL_TOOLS)

def adapter_weights_missing(b):
    """True for a bundle that names an `adapter:` while its adapters/ dir holds no weight file (*.safetensors, what
    discover_adapters counts): the weights are gitignored and ship as a Kaggle dataset, so a clone cannot compile it."""
    yamls = list(b.glob("*.yaml")) + list(b.glob("sub_agents/*.yaml"))
    named = any(re.search(r"^adapter:\s*\S", y.read_text(), re.M) for y in yamls)
    return named and not any(p.suffix == ".safetensors" for p in (b / "adapters").rglob("*") if p.is_file())

@pytest.mark.parametrize("b", BUNDLES, ids=lambda p: p.name)
def test_bundle_compiles_with_official_compiler(b):
    if adapter_weights_missing(b):
        pytest.skip(f"adapter weights not present (gitignored): {b.name}/adapters has no *.safetensors")
    r = subprocess.run([sys.executable, str(ROOT / "scripts/validate.py"), str(b)], capture_output=True, text=True)
    assert "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-800:] + r.stderr[-2000:]

def test_adapter_weights_guard(tmp_path):
    b = tmp_path / "b"; (b / "sub_agents").mkdir(parents=True); (b / "agent.yaml").write_text("name: a\n")
    assert not adapter_weights_missing(b)                                  # no adapter named: compiles without weights
    (b / "sub_agents" / "fixer.yaml").write_text("name: fixer\nadapter: v11a\n")
    assert adapter_weights_missing(b)                                      # named, no adapters/ dir (a fresh clone)
    (b / "adapters" / "v11a").mkdir(parents=True); (b / "adapters" / "v11a" / "adapter_config.json").write_text("{}")
    assert adapter_weights_missing(b)                                      # config only (v4_lora_test's tracked file)
    (b / "adapters" / "v11a" / "adapter_model.safetensors").write_bytes(b"x")
    assert not adapter_weights_missing(b)                                  # weights present: the compile test runs

def test_make_kernel_skips_caches(tmp_path):
    b = tmp_path / "bundle"; (b / "skills/x/scripts/__pycache__").mkdir(parents=True)
    (b / "agent.yaml").write_text("name: a\nmodel: gemma-4-31b-it-qat-w4a16-ct\ninstruction: hi\n")
    (b / "skills/x/scripts/__pycache__/m.cpython-312.pyc").write_bytes(b"x"); (b / "._agent.yaml").write_text("x")
    subprocess.run([sys.executable, str(ROOT / "scripts/make_kernel.py"), str(b), "t-kernel-test"], cwd=tmp_path, check=True, capture_output=True)
    nb = (tmp_path / "kernels/t-kernel-test/t-kernel-test.ipynb").read_text()
    assert ".pyc" not in nb and "._agent" not in nb and "agent.yaml" in nb

@pytest.mark.parametrize("b", BUNDLES, ids=lambda p: p.name)
def test_skill_scripts_do_not_shadow_stdlib(b):
    # a script named select.py shadowed the stdlib `select` that subprocess imports on Linux, breaking every helper
    # in v5's sandbox (passed on macOS, failed on the pod)
    import sys
    stdlib = set(sys.stdlib_module_names)
    for p in b.glob("skills/*/scripts/*.py"):
        assert p.stem not in stdlib, f"{p} shadows stdlib module '{p.stem}'"
