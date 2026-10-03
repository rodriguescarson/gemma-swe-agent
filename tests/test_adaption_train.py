"""train/adaption_train.py: the exact run payload (platform-default LoRA, instruction format, no augmentation) and the
row floor; no network."""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from train import adaption_train as A  # noqa: E402


def test_payload_is_the_pre_registered_recipe():
    p = A.run_payload("ds123", "v11a")
    assert p["model"] == "google/gemma-4-31B-it" and p["training_method"] == "instruction"
    # 2026-10-03 18:28 IST: create() with column_mapping/data_format was refused ("Selected columns 'prompt', 'completion'
    # are not in this dataset"); the proven calls (adaption-leaderboard runs/18, 34) pass neither: the dataset carries
    # the mapping from upload_file(column_mapping=...) on a parquet file
    assert "column_mapping" not in p and "data_format" not in p
    hp = p["hyperparams"]
    assert hp["training_type"] == "lora" and hp["lora_r"] == 8 and hp["lora_alpha"] == 16 and hp["learning_rate"] == 1e-4 and hp["n_epochs"] == 1
    assert hp["lora_trainable_modules"] == "q_proj,k_proj,v_proj,o_proj" and hp["train_on_inputs"] is False
    assert p["augmentation_domain_rows"] == 0 and p["augmentation_general_rows"] == 0 and p["max_iterations"] == 1
    assert p["idempotency_key"].startswith("g4-") and p["idempotency_key"] == A.run_payload("ds123", "v11a")["idempotency_key"]
    assert A.run_payload("ds123", "v11b")["idempotency_key"] != p["idempotency_key"]


def test_row_floor_and_meta_stripping(tmp_path):
    rows = tmp_path / "rows.jsonl"
    rows.write_text("\n".join(json.dumps({"prompt": f"p{i}", "completion": "c", "meta": {"task": "t"}}) for i in range(3)) + "\n")
    assert A.check_rows(str(rows)) == 3
    assert A.strip_meta(str(rows), str(tmp_path / "clean.parquet")) == 3
    import pandas as pd
    df = pd.read_parquet(tmp_path / "clean.parquet")      # parquet, like every upload that trained on Adaption
    assert list(df.columns) == ["prompt", "completion"] and len(df) == 3 and df["prompt"][0] == "p0"
    src = (ROOT / "train" / "adaption_train.py").read_text()
    assert '.upload.parquet' in src and '.upload.jsonl' not in src
    bad = tmp_path / "bad.jsonl"; bad.write_text(json.dumps({"prompt": "p", "completion": ""}) + "\n")
    try:
        A.check_rows(str(bad)); assert False
    except SystemExit as e:
        assert "non-empty" in str(e)


def test_cli_refuses_small_sets_without_flag_and_never_launches_by_default(tmp_path, monkeypatch):
    rows = tmp_path / "rows.jsonl"
    rows.write_text(json.dumps({"prompt": "p", "completion": "c"}) + "\n")
    env = dict(**{k: v for k, v in __import__("os").environ.items()}, ADAPTION_API_KEY="x")
    p = subprocess.run([sys.executable, str(ROOT / "train" / "adaption_train.py"), str(rows), "--name", "probe"], capture_output=True, text=True, env=env)
    assert p.returncode != 0 and "10000" in (p.stdout + p.stderr)
    src = (ROOT / "train" / "adaption_train.py").read_text()
    assert 'if not a.launch:' in src and 'c.autoscientist.create(**payload)' in src.split("if not a.launch:")[1]


def test_download_unpacks_a_zstd_tarball(tmp_path, monkeypatch):
    """2026-10-03: the run artefact is a zstd-compressed tar (magic 28 b5 2f fd), not gzip; tarfile alone fails with
    'invalid header'. download() must detect zstd and unpack it (zstd CLI or the zstandard module)."""
    import tarfile, subprocess, shutil
    src = tmp_path / "src"; src.mkdir(); (src / "adapter_config.json").write_text(json.dumps({"r": 8, "target_modules": ["q_proj"]}))
    (src / "adapter_model.safetensors").write_bytes(b"\x08\x00\x00\x00\x00\x00\x00\x00{}      ")
    tar = tmp_path / "a.tar"
    with tarfile.open(tar, "w") as t:
        for f in src.iterdir(): t.add(f, arcname=f.name)
    assert shutil.which("zstd"), "zstd CLI needed for this test"
    subprocess.run(["zstd", "-q", "-f", str(tar), "-o", str(tmp_path / "a.tar.zst")], check=True)
    blob = (tmp_path / "a.tar.zst").read_bytes()
    assert blob[:4] == b"\x28\xb5\x2f\xfd"
    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def iter_bytes(self): yield blob
    class _AS:
        class with_streaming_response:
            @staticmethod
            def download(run_id): return _Resp()
    class _C: autoscientist = _AS()
    facts = A.download(_C(), "run-1", str(tmp_path / "out"))
    assert "adapter_model.safetensors" in " ".join(facts["files"]) and facts["adapter_config"]["r"] == 8
