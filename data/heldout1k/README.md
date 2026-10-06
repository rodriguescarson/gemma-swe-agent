# heldout1k: runnable harness packs

`tasks.jsonl` (metadata only, mined by `scripts/pallets/heldout_miner.py`, see `PROGRESS.md`) is packed into the
SWE-Pallets-X harness layout by `scripts/heldout/pack_heldout.py`, so the existing Pallets tooling runs it unchanged.
Pack dirs (`harness_*/`) and pre-flight outputs (`preflight_*/`) are gitignored and re-derivable.

```bash
# 1. stratified 200-task sample (per-repo cap 15, every repo present, 20% title-only, seed 20261006) -> sample200_ids.txt
.venv/bin/python scripts/heldout/sample_ids.py
# 2. pack: tasks.jsonl (8 competition keys), single-commit snapshots at base_commit, graphs + embeddings (Pallets
#    pipeline), wheels for every pin (x86_64 + aarch64) and wheels/_extra-<repo>.txt (the miner's validation venv).
#    Needs the repo clones in ~/.cache/g4/heldout1k/clones/<owner>_<name> (git clone --no-checkout) and a tool python
#    with pip + scikit-learn at ~/.cache/g4/heldout1k/toolenv.
.venv/bin/python scripts/heldout/pack_heldout.py --ids data/heldout1k/sample200_ids.txt --out data/heldout1k/harness_s200 --min-free-gb 15
# 3. gold pre-flight in Docker (fix_gold resolves, fix_empty = test_patch only does not), race settings (no editable install)
PROBE_HARNESS=data/heldout1k/harness_s200 PROBE_RUNS=fix PROBE_CONC=4 PROBE_NO_EDITABLE=1 PROBE_OUT=$PWD/data/heldout1k/preflight_s200 scripts/pallets/pod_probe.sh data/heldout1k/harness_s200/ids.txt
.venv/bin/python scripts/heldout/preflight_summary.py data/heldout1k/preflight_s200 --valid-ids data/heldout1k/s200_valid_ids.txt
```

Race bundles on harness_s200 (OpenRouter spend; `DRY_RUN=1` in front prints the plan only; add
`IDS_FILE=data/heldout1k/s200_valid_ids.txt` to race only the pre-flight-valid tasks):

    HARNESS=data/heldout1k/harness_s200 scripts/pallets/or_race.sh v4h2 v5h2

(tested by `tests/test_heldout_race_doc.py` under `DRY_RUN=1`).

## Results (2026-10-06, Docker python:3.12-slim arm64, `pod_probe.sh` fix runs, race settings)

| pack | tasks | gold resolves, empty does not | dropped |
|---|---|---|---|
| harness_s200 (sample200_ids.txt) | 200 | 200 (`s200_valid_ids.txt`) | 0 |
| harness_all | 1046 | 1044 (`all_valid_ids.txt`) | 2 empty_resolves: isort_d75b093 (miner base_rc 0, F2P from parametrize-id drift), trio_50b9825 |

Per-task classes: `preflight_all_summary.json`. Earlier s200 runs that found packer bugs (kept in gitignored
`preflight_s200_run*`): run 1 (stopped at 79 gold runs), isort without its own distribution's metadata (12 gold collection
errors); run 2 162/200, the real own wheel shadowed /workspace/src (38 drops); run 3 197/200, real wheels of black and
mistune missing for isort/httpie. Each fixed in the packer, never in the tasks.

Env recipe: each repo's `wheels/_extra-<repo>.txt` is the miner's validation freeze; the repo's own distribution is a
metadata-only wheel `X+g4meta` (importlib.metadata works, code comes from the workspace), every other pin is `===X`.
Snapshots are single-commit `baseline` repos at base_commit (tomlkit's toml-test submodule vendored), byte-deterministic.
