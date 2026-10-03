"""scripts/adapters_dataset.py: stage a bundle's adapter weights as a flat private Kaggle dataset (one file per adapter,
<name>__adapter_model.safetensors, no directories: the 2.x CLI skips directories by default) and compose the create /
version command. Written before the script (2026-10-03: a 2.8 MB notebook with embedded adapters was refused, 400)."""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "adapters_dataset.py"
sys.path.insert(0, str(ROOT / "scripts"))


def _bundle(tmp):
    b = tmp / "bundle"; (b / "adapters" / "zb").mkdir(parents=True); (b / "adapters" / "loud").mkdir()
    (b / "adapters" / "zb" / "adapter_model.safetensors").write_bytes(b"\x00" * 16)
    (b / "adapters" / "zb" / "adapter_config.json").write_text("{}")
    (b / "adapters" / "loud" / "adapter_model.safetensors").write_bytes(b"\x01" * 16)
    (b / "adapters" / "loud" / "adapter_config.json").write_text("{}")
    (b / "adapters" / "MANIFEST.json").write_text(json.dumps({"files": {"zb/adapter_model.safetensors": "a", "loud/adapter_model.safetensors": "b"}}))
    return b


def test_stage_flattens_weights_and_writes_metadata(tmp_path):
    import adapters_dataset as D
    b = _bundle(tmp_path); out = tmp_path / "ds"
    files = D.stage(str(b), str(out), "carsonrodrigues", "g4-adapters-probe2")
    assert sorted(p.name for p in out.iterdir()) == ["dataset-metadata.json", "loud__adapter_model.safetensors", "zb__adapter_model.safetensors"]
    assert (out / "zb__adapter_model.safetensors").read_bytes() == b"\x00" * 16
    meta = json.loads((out / "dataset-metadata.json").read_text())
    assert meta["id"] == "carsonrodrigues/g4-adapters-probe2" and meta["title"] == "g4-adapters-probe2" and meta["licenses"]
    assert files == {"zb/adapter_model.safetensors": "zb__adapter_model.safetensors", "loud/adapter_model.safetensors": "loud__adapter_model.safetensors"}
    assert D.flat_name("loud/adapter_model.safetensors") == "loud__adapter_model.safetensors"


def test_cli_command_create_vs_version():
    import adapters_dataset as D
    assert D.cli_command("kaggle", "/x", exists=False) == ["kaggle", "datasets", "create", "-p", "/x"]
    assert D.cli_command("kaggle", "/x", exists=True)[:4] == ["kaggle", "datasets", "version", "-p"] and "-m" in D.cli_command("kaggle", "/x", exists=True)
