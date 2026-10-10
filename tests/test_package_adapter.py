"""train/package_adapter.py: a downloaded PEFT adapter (Adaption/Together tgz, extracted) -> submission bundle in one command.

Facts the tests pin (read from the vendored wheels 2026-10-03):
  - adk_submission.discover_adapters groups adapters/<dir>/{adapter_config.json, adapter_model.safetensors} into ONE
    adapter named <dir>; swegemma only admits .safetensors as adapter weights.
  - adk_submission.server.VllmConfig.max_lora_rank = 128, so a rank > 128 adapter cannot load on the scorer.
  - an adapter name must match ^[a-zA-Z0-9_.-]+$ (server._VALID_ADAPTER_NAME_RE).
"""
import hashlib, json, struct, subprocess, sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_test_adapters as M  # noqa: E402

V4H2 = ROOT / "submissions" / "v4h2"
SCRIPT = ROOT / "train" / "package_adapter.py"
LOUD = "base_model.model.model.language_model.layers.{n}.self_attn.{m}.lora_{ab}.weight"
LOUD2 = "base_model.model.language_model.layers.{n}.self_attn.{m}.lora_{ab}.weight"
TOGETHER = "base_model.model.model.layers.{n}.self_attn.{m}.lora_{ab}.weight"  # Together's Llama style (PLAN.md 10-02 16:39)


def make_peft(d: Path, key=LOUD, r=4, layers=(0, 1), mods=("q_proj", "v_proj"), dtype=np.float32, cfg_extra=None):
    """A tiny PEFT dir like the Adaption tgz: adapter files plus the extra files the tarball ships."""
    d.mkdir(parents=True)
    rng = np.random.default_rng(7)
    t = {}
    for n in layers:
        for m in mods:
            t[key.format(n=n, m=m, ab="A")] = rng.standard_normal((r, 16)).astype(dtype)
            t[key.format(n=n, m=m, ab="B")] = rng.standard_normal((24, r)).astype(dtype)
    M.write_safetensors(d / "adapter_model.safetensors", t)
    cfg = {"base_model_name_or_path": "google/gemma-4-31B-it", "peft_type": "LORA", "r": r, "lora_alpha": 2 * r,
           "target_modules": list(mods), "task_type": "CAUSAL_LM", "use_dora": False}
    cfg.update(cfg_extra or {})
    (d / "adapter_config.json").write_text(json.dumps(cfg, indent=2))
    (d / "config.json").write_text("{}")             # ships in the tgz, must NOT be copied into the bundle
    (d / "trainer_state.json").write_text("{}")
    return t


def split(path):
    raw = Path(path).read_bytes()
    n = struct.unpack("<Q", raw[:8])[0]
    return json.loads(raw[8:8 + n]), raw[8 + n:]


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


def bundle(tmp_path):
    import shutil
    src = tmp_path / "v4h2"
    shutil.copytree(V4H2, src, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "._*", ".DS_Store"))
    return src


@pytest.mark.parametrize("src_key", [LOUD, LOUD2, TOGETHER])
@pytest.mark.parametrize("style,want", [("loud", LOUD), ("loud2", LOUD2)])
def test_key_style_rewrites_every_key_and_keeps_tensor_bytes(tmp_path, src_key, style, want):
    tensors = make_peft(tmp_path / "ad", key=src_key)
    p = run(tmp_path / "ad", "--bundle", bundle(tmp_path), "--out", tmp_path / "out", "--name", "v11a", "--key-style", style)
    assert p.returncode == 0, p.stdout + p.stderr
    out = tmp_path / "out" / "adapters" / "v11a" / "adapter_model.safetensors"
    h_in, data_in = split(tmp_path / "ad" / "adapter_model.safetensors")
    h_out, data_out = split(out)
    assert data_out == data_in                                         # the whole data section, byte for byte
    rename = {src_key.format(n=n, m=m, ab=ab): want.format(n=n, m=m, ab=ab)
              for n in (0, 1) for m in ("q_proj", "v_proj") for ab in "AB"}
    assert sorted(k for k in h_out if k != "__metadata__") == sorted(rename.values())
    for old, new in rename.items():
        assert h_out[new] == h_in[old]                                 # dtype, shape, offsets untouched
    from safetensors.numpy import load_file                            # the real reader accepts it
    loaded = load_file(str(out))
    for old, new in rename.items():
        assert loaded[new].tobytes() == tensors[old].tobytes()


def test_keys_outside_the_language_model_layers_are_refused(tmp_path):
    make_peft(tmp_path / "ad", key="base_model.model.model.vision_tower.layers.{n}.self_attn.{m}.lora_{ab}.weight")
    p = run(tmp_path / "ad", "--bundle", bundle(tmp_path), "--out", tmp_path / "out", "--key-style", "loud")
    assert p.returncode == 2 and not (tmp_path / "out").exists(), p.stdout + p.stderr


@pytest.mark.parametrize("r,extra", [(256, None), (8, {"rank_pattern": {"q_proj": 192}})])
def test_rank_over_128_is_refused_with_exit_2(tmp_path, r, extra):
    make_peft(tmp_path / "ad", r=r, cfg_extra=extra)
    p = run(tmp_path / "ad", "--bundle", bundle(tmp_path), "--out", tmp_path / "out", "--key-style", "loud")
    assert p.returncode == 2, p.stdout + p.stderr
    assert "128" in p.stdout + p.stderr
    assert not (tmp_path / "out").exists()


def test_rank_128_is_accepted_and_reported(tmp_path):
    make_peft(tmp_path / "ad", r=128, layers=(0,), mods=("q_proj",))
    p = run(tmp_path / "ad", "--bundle", bundle(tmp_path), "--out", tmp_path / "out", "--key-style", "loud")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "r=128" in p.stdout


def test_layout_matches_discover_adapters_and_stages_get_the_adapter_line(tmp_path):
    make_peft(tmp_path / "ad")
    src = bundle(tmp_path)
    p = run(tmp_path / "ad", "--bundle", src, "--out", tmp_path / "out", "--key-style", "loud")  # defaults: v11a, fixer,verifier
    assert p.returncode == 0, p.stdout + p.stderr
    out = tmp_path / "out"
    ad = out / "adapters" / "v11a"
    assert sorted(f.name for f in ad.iterdir()) == ["adapter_config.json", "adapter_model.safetensors"]
    assert (ad / "adapter_config.json").read_bytes() == (tmp_path / "ad" / "adapter_config.json").read_bytes()
    from adk_submission import discover_adapters
    from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS
    man = discover_adapters(out, adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)
    assert list(man.adapters) == ["v11a"]
    assert Path(man.adapters["v11a"].path) == (ad / "adapter_model.safetensors").resolve()
    for stage in ("fixer", "verifier"):
        y = (out / "sub_agents" / f"{stage}.yaml").read_text()
        orig = (src / "sub_agents" / f"{stage}.yaml").read_text()
        assert "\nadapter: v11a\nmodel: " in y and y.replace("adapter: v11a\n", "", 1) == orig
    assert (out / "sub_agents" / "locator.yaml").read_text() == (src / "sub_agents" / "locator.yaml").read_text()
    assert (out / "agent.yaml").read_text() == (src / "agent.yaml").read_text()  # root is a SequentialAgent, no model
    for p_ in src.rglob("*"):                                          # nothing else changed
        rel = p_.relative_to(src)
        if p_.is_file() and rel.parts[0] != "sub_agents":
            assert (out / rel).read_bytes() == p_.read_bytes(), rel


def test_stages_flag_and_existing_adapter_line_is_replaced(tmp_path):
    make_peft(tmp_path / "ad")
    src = bundle(tmp_path)
    f = src / "sub_agents" / "fixer.yaml"
    f.write_text(f.read_text().replace("\nmodel: ", "\nadapter: zb\nmodel: ", 1))
    p = run(tmp_path / "ad", "--bundle", src, "--out", tmp_path / "out", "--name", "v11b", "--key-style", "loud2",
            "--stages", "fixer")
    assert p.returncode == 0, p.stdout + p.stderr
    y = (tmp_path / "out" / "sub_agents" / "fixer.yaml").read_text()
    assert y.count("adapter:") == 1 and "\nadapter: v11b\nmodel: " in y
    assert "adapter:" not in (tmp_path / "out" / "sub_agents" / "verifier.yaml").read_text()


@pytest.mark.parametrize("args", [["--name", "bad name"], ["--name", "gemma4-lora"], ["--stages", "nosuchstage"]])
def test_bad_name_or_stage_is_refused(tmp_path, args):
    make_peft(tmp_path / "ad")
    p = run(tmp_path / "ad", "--bundle", bundle(tmp_path), "--out", tmp_path / "out", "--key-style", "loud", *args)
    assert p.returncode == 2 and not (tmp_path / "out").exists(), p.stdout + p.stderr


def test_existing_out_is_not_overwritten(tmp_path):
    make_peft(tmp_path / "ad")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "keep.txt").write_text("x")
    p = run(tmp_path / "ad", "--bundle", bundle(tmp_path), "--out", tmp_path / "out", "--key-style", "loud")
    assert p.returncode == 2 and (tmp_path / "out" / "keep.txt").read_text() == "x"


def test_nested_tgz_layout_is_found(tmp_path):
    make_peft(tmp_path / "dl" / "checkpoint" / "final")
    p = run(tmp_path / "dl", "--bundle", bundle(tmp_path), "--out", tmp_path / "out", "--key-style", "loud")
    assert p.returncode == 0, p.stdout + p.stderr
    assert (tmp_path / "out" / "adapters" / "v11a" / "adapter_model.safetensors").is_file()


def test_sha256_manifest_is_written(tmp_path):
    make_peft(tmp_path / "ad")
    p = run(tmp_path / "ad", "--bundle", bundle(tmp_path), "--out", tmp_path / "out", "--key-style", "loud")
    assert p.returncode == 0, p.stdout + p.stderr
    man = json.loads((tmp_path / "out" / "adapters" / "MANIFEST.json").read_text())
    sha = lambda f: hashlib.sha256(Path(f).read_bytes()).hexdigest()
    for fn in ("adapter_config.json", "adapter_model.safetensors"):
        assert man["files"][f"v11a/{fn}"] == sha(tmp_path / "out" / "adapters" / "v11a" / fn)
    info = man["packaged"]["v11a"]
    assert info["key_style"] == "loud" and info["stages"] == ["fixer", "verifier"] and info["r"] == 4
    assert info["source_sha256"]["adapter_model.safetensors"] == sha(tmp_path / "ad" / "adapter_model.safetensors")


@pytest.mark.parametrize("style", ["loud", "loud2"])
def test_packaged_bundle_passes_the_official_compiler(tmp_path, style):
    cfg, tensors = M.make_adapter("loud", 20261003)                    # real Gemma 4 q_proj shapes, layer 0, r=4
    d = tmp_path / "ad"
    d.mkdir()
    M.write_safetensors(d / "adapter_model.safetensors", tensors)
    (d / "adapter_config.json").write_text(json.dumps(cfg))
    p = run(d, "--bundle", bundle(tmp_path), "--out", tmp_path / "out", "--key-style", style)
    assert p.returncode == 0, p.stdout + p.stderr
    v = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(tmp_path / "out")],
                       capture_output=True, text=True)
    assert v.returncode == 0, v.stdout[-800:] + v.stderr[-1500:]
    assert "fixer model=openai/gemma-4-31b-it-qat-w4a16-ct:v11a" in v.stdout, v.stdout
    assert "verifier model=openai/gemma-4-31b-it-qat-w4a16-ct:v11a" in v.stdout, v.stdout
    assert "locator model=openai/gemma-4-31b-it-qat-w4a16-ct " in v.stdout, v.stdout


def test_stage_agent_means_the_root_agent_yaml_of_a_single_agent_bundle(tmp_path):
    """submissions/v12 has no sub_agents/: `--stages agent` puts the adapter line into agent.yaml (PROMPTS P11 step 7)."""
    import shutil
    make_peft(tmp_path / "ad")
    src = tmp_path / "v12"
    shutil.copytree(ROOT / "submissions" / "v12", src, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "._*", ".DS_Store"))
    p = run(tmp_path / "ad", "--bundle", src, "--out", tmp_path / "out", "--name", "think1", "--key-style", "loud", "--stages", "agent")
    assert p.returncode == 0, p.stdout + p.stderr
    y = (tmp_path / "out" / "agent.yaml").read_text()
    assert y.count("adapter:") == 1 and "\nadapter: think1\nmodel: " in y
    assert (tmp_path / "out" / "adapters" / "think1" / "adapter_model.safetensors").is_file()
    assert run(tmp_path / "ad", "--bundle", src, "--out", tmp_path / "out2", "--name", "x", "--key-style", "loud", "--stages", "fixer").returncode == 2
