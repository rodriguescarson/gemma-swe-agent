"""v12b_e4b_card = v12b_e4b (hidden 0.06, sub24) with ONE change, the sampling block: temperature 0.2 -> 1.0 and top_k 64,
the E4B model card's recommended sampling (google/gemma-4-E4B-it-qat-w4a16-ct). The next step pre-registered for a 0.05-0.07
read in GAPS 'v12b_e4b pre-registration'. Every other file is byte-identical to v12b_e4b. Pinned before any row exists."""
import filecmp
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
BASE = ROOT / "submissions" / "v12b_e4b"
CARD = ROOT / "submissions" / "v12b_e4b_card"


def files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def test_same_files_and_only_sampling_differs():
    assert files(BASE) == files(CARD)
    differ = [f for f in files(BASE) if not filecmp.cmp(BASE / f, CARD / f, shallow=False)]
    assert differ == ["configs/sampling.yaml"]


def test_sampling_is_the_card_block_and_nothing_else_moved():
    base = yaml.safe_load((BASE / "configs/sampling.yaml").read_text())
    card = yaml.safe_load((CARD / "configs/sampling.yaml").read_text())
    assert card["temperature"] == 1.0 and card["top_k"] == 64 and card["top_p"] == 0.95
    assert "seed" not in card and "seed" not in base
    for k in ("max_output_tokens", "thinking_config"):
        assert card[k] == base[k]
    assert {k for k in card if card.get(k) != base.get(k)} == {"temperature", "top_k"}


def test_model_is_e4b():
    agent = yaml.safe_load((CARD / "agent.yaml").read_text())
    assert agent["model"] == "gemma-4-e4b-it-qat-w4a16-ct"
