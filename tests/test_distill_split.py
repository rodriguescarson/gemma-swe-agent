"""scripts/distill/split.py: EVAL and TRAIN are disjoint by repo, exclude the public 74, are deterministic, and the
committed lists in data/distill agree with their report."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "distill"))
import split as S  # noqa: E402


def synthetic():
    repo_of, history = {}, {}
    sizes = {"a/hard": 30, "b/mid": 25, "c/easy": 40, "d/big": 90, "e/tiny": 5, "f/mid2": 22}
    rates = {"a/hard": 0.1, "b/mid": 0.4, "c/easy": 0.8, "d/big": 0.5, "e/tiny": 0.5, "f/mid2": 0.5}
    for repo, n in sizes.items():
        for k in range(n):
            i = f"{repo.split('/')[1]}_{k:03d}"
            repo_of[i] = repo
            history[i] = k < round(n * rates[repo])
    return repo_of, set(repo_of), history


def test_split_rule_is_repo_disjoint_and_deterministic():
    repo_of, pool, hist = synthetic()
    a = S.split(repo_of, pool, hist, repo_min=20, repo_max=60, target=50)
    b = S.split(repo_of, set(sorted(pool, reverse=True)), dict(reversed(list(hist.items()))), repo_min=20, repo_max=60,
                target=50)
    assert a["eval_ids"] == b["eval_ids"] and a["train_ids"] == b["train_ids"]
    assert a["eval_repos"] == ["a/hard", "f/mid2"]          # hardest first, then every other by solve rate
    assert not {repo_of[i] for i in a["eval_ids"]} & {repo_of[i] for i in a["train_ids"]}
    assert set(a["eval_ids"]) | set(a["train_ids"]) == pool
    assert "d/big" not in a["eval_repos"] and "e/tiny" not in a["eval_repos"]


def test_split_refuses_when_eval_too_small():
    repo_of, pool, hist = synthetic()
    with pytest.raises(ValueError, match="only"):
        S.split(repo_of, pool, hist, repo_min=20, repo_max=60, target=500)


OUT = ROOT / "data" / "distill"


@pytest.mark.skipif(not (OUT / "split_report.json").exists(), reason="split not generated")
def test_committed_split_matches_report_and_rules():
    rep = json.loads((OUT / "split_report.json").read_text())
    ev = (OUT / "eval_ids.txt").read_text().split()
    tr = (OUT / "train_ids.txt").read_text().split()
    assert len(ev) == rep["eval_n"] and len(tr) == rep["train_n"] and not set(ev) & set(tr)
    repo_of = rep["repo_of"]
    assert not {repo_of[i] for i in ev} & {repo_of[i] for i in tr}
    assert {repo_of[i] for i in ev} == set(rep["eval_repos"])
    public = set((ROOT / "data" / "kaggle_valid_ids.txt").read_text().split())
    assert not public & (set(ev) | set(tr))
    assert rep["eval_n"] >= rep["rule"]["target"]
