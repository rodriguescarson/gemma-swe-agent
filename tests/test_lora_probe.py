"""P0.6: the test adapters are byte-reproducible, correctly shaped, and the probe bundle differs from v4 by adapters only."""
import filecmp, json, subprocess, sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_test_adapters as M  # noqa: E402

V4 = ROOT / "submissions" / "v4"


def test_adapters_are_byte_reproducible_and_sha_recorded(tmp_path):
    m1 = M.build(str(V4), str(tmp_path / "a"), 20261003)
    m2 = M.build(str(V4), str(tmp_path / "b"), 20261003)
    assert m1["files"] == m2["files"]
    for rel, sha in m1["files"].items():
        assert M.sha256(tmp_path / "a" / "adapters" / rel) == sha
    m3 = M.build(str(V4), str(tmp_path / "c"), 1)
    assert m3["files"]["loud/adapter_model.safetensors"] != m1["files"]["loud/adapter_model.safetensors"]


def test_shapes_keys_and_zero_b(tmp_path):
    M.build(str(V4), str(tmp_path / "a"), 20261003)
    h = M.read_safetensors_header(tmp_path / "a" / "adapters" / "zb" / "adapter_model.safetensors")
    keys = sorted(k for k in h if k != "__metadata__")
    assert keys == sorted(M.KEY_A.format(n=0, m="q_proj", ab=ab) for ab in "AB")
    assert h[M.KEY_A.format(n=0, m="q_proj", ab="A")]["shape"] == [4, M.HIDDEN] and h[M.KEY_A.format(n=0, m="q_proj", ab="B")]["shape"] == [M.Q_OUT, 4]
    assert all(v["dtype"] == "F16" for k, v in h.items() if k != "__metadata__")
    cfg, tensors = M.make_adapter("zb", 20261003)
    assert not np.any(tensors[M.KEY_A.format(n=0, m="q_proj", ab="B")]) and np.any(tensors[M.KEY_A.format(n=0, m="q_proj", ab="A")])
    _, loud = M.make_adapter("loud", 20261003)
    assert np.any(loud[M.KEY_A.format(n=0, m="q_proj", ab="B")])
    h2 = M.read_safetensors_header(tmp_path / "a" / "adapters" / "loud2" / "adapter_model.safetensors")
    assert all(k.startswith("base_model.model.language_model.") for k in h2 if k != "__metadata__")
    assert cfg["r"] == 4 and cfg["target_modules"] == ["q_proj"] and cfg["layers_to_transform"] == [0]


def test_safetensors_roundtrip(tmp_path):
    t = {"x": np.arange(6, dtype=np.float16).reshape(2, 3), "a": np.ones((1, 1), np.float32)}
    M.write_safetensors(tmp_path / "t.safetensors", t)
    h = M.read_safetensors_header(tmp_path / "t.safetensors")
    raw = (tmp_path / "t.safetensors").read_bytes()
    n = int.from_bytes(raw[:8], "little"); data = raw[8 + n:]
    s, e = h["x"]["data_offsets"]
    assert np.frombuffer(data[s:e], np.float16).reshape(2, 3).tolist() == t["x"].tolist()
    assert (8 + n) % 8 == 0


def test_probe_bundle_is_v4_plus_adapters_and_one_line(tmp_path):
    M.build(str(V4), str(tmp_path / "a"), 20261003)
    out = tmp_path / "a"
    for p in V4.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            rel = p.relative_to(V4)
            if str(rel) == "sub_agents/fixer.yaml":
                y = (out / rel).read_text()
                assert "adapter: zb\nmodel: " in y and y.replace("adapter: zb\n", "") == p.read_text()
            else:
                assert filecmp.cmp(p, out / rel, shallow=False), rel
    total = sum(f.stat().st_size for f in (out / "adapters").rglob("*") if f.is_file())
    assert total < 500_000, total
    assert json.load(open(out / "adapters" / "MANIFEST.json"))["seed"] == 20261003


def test_probe_bundle_compiles_with_the_official_compiler(tmp_path):
    M.build(str(V4), str(tmp_path / "a"), 20261003)
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(tmp_path / "a")], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout[-800:] + p.stderr[-1500:]
    # adk_submission 0.2.x names the adapter-backed model <base>:<adapter>, not openai/<adapter> (plan_A.md assumed the latter)
    assert "fixer model=openai/gemma-4-31b-it-qat-w4a16-ct:zb" in p.stdout, p.stdout
    assert "locator model=openai/gemma-4-31b-it-qat-w4a16-ct " in p.stdout


def test_ga2_adapters_loud_all_and_two_more_prefixes(tmp_path):
    """G-A2 (docs/v11/GA_PROBE.md addendum 2026-10-03): loud_all touches q_proj of ALL 60 layers (r=1, N(0,1) A and B)
    under the plan_A prefix; loud3/loud4 are the Gemma-3 HF style and the plain Llama/Together style, layer 0 only.
    The default build (zb, loud, loud2) is unchanged so the first probe stays reproducible."""
    m = M.build(str(ROOT / "submissions" / "v4"), str(tmp_path / "p2"), 20261003, names=("zb", "loud", "loud_all", "loud3", "loud4"))
    assert sorted(n.split("/")[0] for n in m["files"]) == sorted(["zb", "zb", "loud", "loud", "loud_all", "loud_all", "loud3", "loud3", "loud4", "loud4"])
    h = M.read_safetensors_header(tmp_path / "p2" / "adapters" / "loud_all" / "adapter_model.safetensors")
    keys = [k for k in h if k != "__metadata__"]
    assert len(keys) == 120 and all(".self_attn.q_proj.lora_" in k and k.startswith("base_model.model.model.language_model.layers.") for k in keys)
    assert {tuple(h[k]["shape"]) for k in keys if k.endswith("lora_A.weight")} == {(1, M.HIDDEN)}
    assert {tuple(h[k]["shape"]) for k in keys if k.endswith("lora_B.weight")} == {(M.Q_OUT, 1)}
    cfg = json.load(open(tmp_path / "p2" / "adapters" / "loud_all" / "adapter_config.json"))
    assert cfg["r"] == 1 and cfg["layers_to_transform"] == list(range(60)) and cfg["target_modules"] == ["q_proj"]
    h3 = M.read_safetensors_header(tmp_path / "p2" / "adapters" / "loud3" / "adapter_model.safetensors")
    assert all(k.startswith("base_model.model.language_model.model.layers.0.self_attn.q_proj.") for k in h3 if k != "__metadata__")
    h4 = M.read_safetensors_header(tmp_path / "p2" / "adapters" / "loud4" / "adapter_model.safetensors")
    assert all(k.startswith("base_model.model.model.layers.0.self_attn.q_proj.") for k in h4 if k != "__metadata__")
    assert np.any(M.make_adapter("loud_all", 1)[1][M.KEY_A.format(n=59, m="q_proj", ab="B")])
    m_default = M.build(str(ROOT / "submissions" / "v4"), str(tmp_path / "p1"), 20261003)
    assert sorted({n.split("/")[0] for n in m_default["files"]}) == ["loud", "loud2", "zb"]
