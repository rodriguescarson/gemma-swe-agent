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
    assert keys == sorted(M.KEY_A.format(n=0, ab=ab) for ab in "AB")
    assert h[M.KEY_A.format(n=0, ab="A")]["shape"] == [4, M.HIDDEN] and h[M.KEY_A.format(n=0, ab="B")]["shape"] == [M.Q_OUT, 4]
    assert all(v["dtype"] == "F16" for k, v in h.items() if k != "__metadata__")
    cfg, tensors = M.make_adapter("zb", 20261003)
    assert not np.any(tensors[M.KEY_A.format(n=0, ab="B")]) and np.any(tensors[M.KEY_A.format(n=0, ab="A")])
    _, loud = M.make_adapter("loud", 20261003)
    assert np.any(loud[M.KEY_A.format(n=0, ab="B")])
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
