"""train/adaption_train.py: the exact run payload (platform-default LoRA, instruction format, no augmentation) and the
row floor; no network."""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from train import adaption_train as A  # noqa: E402


def test_payload_is_the_pre_registered_recipe():
    p = A.run_payload("ds123", "v11a")
    assert p["model"] == "google/gemma-4-31B-it" and p["training_method"] == "instruction" and p["data_format"] == "instruction"
    assert p["column_mapping"] == {"prompt": "prompt", "completion": "completion"}
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
    assert A.strip_meta(str(rows), str(tmp_path / "clean.jsonl")) == 3
    first = json.loads((tmp_path / "clean.jsonl").read_text().splitlines()[0])
    assert set(first) == {"prompt", "completion"}
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
