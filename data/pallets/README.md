# SWE-Pallets-X: Verified SWE-Agent Task Dataset (v4)

476 execution-verified software-engineering task instances in the
Gemma 4 Developer Agent competition format, mined from public GitHub history
and validated by fail-to-pass / pass-to-pass test execution.

## Repositories
- `pytest-dev/pytest`: 132 tasks
- `sympy/sympy`: 129 tasks
- `pallets/click`: 109 tasks
- `pallets/werkzeug`: 43 tasks
- `pallets/flask`: 29 tasks
- `pallets/jinja2`: 29 tasks
- `pallets/markupsafe`: 4 tasks
- `pallets/itsdangerous`: 1 tasks

## Layout
- `tasks.jsonl`: instance_id, repo, base_commit, fix_commit,
  problem_statement, patch, test_patch, test_files, provenance fields
- `snapshots.tar.gz`: frozen single-commit repo per instance
- `graphs.tar.gz`: AST call/dependency graphs (NetworkX node-link JSON)
- `embeddings.tar.gz`: 256-dim node embeddings (TF-IDF -> TruncatedSVD)
- `pipeline.tar.gz`: full curation/eval pipeline source

## Verification
Each task: at base_commit + test_patch tests FAIL; + patch tests PASS,
under era-matched Python and era-pinned dependencies.

Integrity audit (pipeline/audit.py): 476/476 unique instance_ids,
476/476 unique (repo, fix_commit) pairs, 476/476 snapshot+graph+embedding
assets present. v4 normalizes all `created_at`/`fix_date` values to ISO 8601.

## Baselines (Qwen2.5-Coder-7B, 20-step harness)
- resolve rate: 4/181 (2.2%) on the pallets subset
- fix localization (all 476): 69% recall@5, +3–4 pt with one-hop graph
  expansion; graph tools are invoked in only 7% of agent episodes

Pipeline + eval harness: https://github.com/taku629/swe-pallets-x
Third-party verification notebook:
https://www.kaggle.com/code/takumuhata/swe-pallets-x-dataset-tour-verification-demo
