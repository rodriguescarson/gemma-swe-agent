"""Every bundle that could be submitted must compile with the organisers' compiler and contain only allowed files.
Guards: .pyc/__pycache__ (sweep v2 died on this), AppleDouble ._ files (smoke run died), non-kebab skill names, unknown tools."""
import os, re, subprocess, sys, pathlib, pytest
ROOT = pathlib.Path(__file__).parent.parent
# _h2_<id>: Harness² candidates the box stages for its race runner (h2g4/swe.py RaceLauncher; git-ignored, never shipped)
BUNDLES = sorted(p for p in (ROOT / "submissions").iterdir() if (p / "agent.yaml").exists() and not p.name.startswith("_h2_"))
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
    # 31B everywhere except the small-model entries (v12b_e4b 23 Oct, v12b_e4b_card 24 Oct), which pin their own model in
    # their own tests
    want = "gemma-4-e4b-it-qat-w4a16-ct" if "_e4b" in b.name else "gemma-4-31b-it-qat-w4a16-ct"
    assert f"OK model={want}" in r.stdout, r.stdout[-800:] + r.stderr[-2000:]

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

def test_make_kernel_takes_adapter_weights_from_a_dataset(tmp_path):
    """sub15 (2026-10-13): a 242 MB adapter cannot ride base64 inside a notebook; with --adapters-dataset the kernel copies
    <name>__adapter_model.safetensors from the private dataset, checks its sha256 against adapters/MANIFEST.json and zips it."""
    import base64, hashlib, json
    b = tmp_path / "v12_t"; (b / "adapters" / "t").mkdir(parents=True)
    (b / "agent.yaml").write_text("name: a\nmodel: gemma-4-31b-it-qat-w4a16-ct\nadapter: t\ninstruction: hi\n")
    w = b"W" * 100; (b / "adapters" / "t" / "adapter_model.safetensors").write_bytes(w)
    (b / "adapters" / "t" / "adapter_config.json").write_text("{}")
    (b / "adapters" / "MANIFEST.json").write_text(json.dumps({"files": {"t/adapter_model.safetensors": hashlib.sha256(w).hexdigest(), "t/adapter_config.json": "0" * 64}}))
    r = subprocess.run([sys.executable, str(ROOT / "scripts/make_kernel.py"), str(b), "t-kernel-ds", "--adapters-dataset", "owner/g4-adapters-t"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]
    nb = json.loads((tmp_path / "kernels/t-kernel-ds/t-kernel-ds.ipynb").read_text())["cells"][0]["source"]
    assert base64.b64encode(w).decode() not in nb and "DATASET = 'owner/g4-adapters-t'" in nb
    assert "adapters/MANIFEST.json" in nb and "sha mismatch" in nb and "t__adapter_model.safetensors" not in nb      # the name is built from the manifest at run time
    meta = json.loads((tmp_path / "kernels/t-kernel-ds/kernel-metadata.json").read_text())
    assert meta["dataset_sources"] == ["owner/g4-adapters-t"] and meta["enable_gpu"] is False
    # the embedded files still carry the config and the manifest; without the flag the weights are embedded (the old behaviour)
    assert "adapters/t/adapter_config.json" in nb
    subprocess.run([sys.executable, str(ROOT / "scripts/make_kernel.py"), str(b), "t-kernel-embed"], cwd=tmp_path, check=True, capture_output=True)
    assert base64.b64encode(w).decode() in json.loads((tmp_path / "kernels/t-kernel-embed/t-kernel-embed.ipynb").read_text())["cells"][0]["source"]
    # a weight the manifest does not name refuses
    (b / "adapters" / "MANIFEST.json").write_text(json.dumps({"files": {}}))
    r = subprocess.run([sys.executable, str(ROOT / "scripts/make_kernel.py"), str(b), "t-kernel-bad", "--adapters-dataset", "owner/x"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode != 0 and "names no sha256" in r.stderr

def test_make_kernel_cell_is_valid_python_with_and_without_a_dataset(tmp_path):
    """2026-10-13: the g4agent-v12-b1024 kernel died on `DATASET = null` (json.dumps(None) written into Python); the adapter
    kernels passed only because their dataset was a string. Both modes must compile."""
    import json
    b = tmp_path / "b"; b.mkdir(); (b / "agent.yaml").write_text("name: a\nmodel: gemma-4-31b-it-qat-w4a16-ct\ninstruction: hi\n")
    subprocess.run([sys.executable, str(ROOT / "scripts/make_kernel.py"), str(b), "k-plain"], cwd=tmp_path, check=True, capture_output=True)
    src = json.loads((tmp_path / "kernels/k-plain/k-plain.ipynb").read_text())["cells"][0]["source"]
    compile(src, "k-plain", "exec")
    assert "DATASET = None" in src
    ns = {}
    exec(src.split("\nout = ")[0], ns)                     # the header runs: FILES, DATASET, WEIGHTS defined, no dataset cell
    assert ns["DATASET"] is None and ns["WEIGHTS"] == {} and "agent.yaml" in ns["FILES"]
