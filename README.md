# Gemma 4 Developer Agent: a measured entry

Our entry to the Kaggle [Gemma 4 Developer Agent](https://www.kaggle.com/competitions/gemma-4-developer-agent) competition and
its [paper track](https://www.kaggle.com/competitions/gemma-4-developer-agent-paper). The model, tools and scorer are fixed;
an entry is an agent configuration (prompt, limits, sampling). This repository holds every configuration we built, every
local run, every hidden score, and the log of rules we wrote down before each run.

The paper: [What a local screen could not tell us about a small offline coding agent](https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/writeups/what-a-local-screen-could-not-tell-us-about-a-smal).
Its main finding is that a 74-task local screen, on the scorer's own hardware or on a GPU paced to it, did not rank our
configurations' hidden scores.

## Where things are

| Path | What it holds |
|---|---|
| `submissions/` | Every agent bundle (agent.yaml, prompt, limits, sampling). Each shipped one is pinned by `tests/test_<name>_bundle.py`. |
| `eval/a6000/results/` | Per-task results of every full 74-task local run, with traces. |
| `eval/kaggle/` | Runs on Kaggle's own 4xL4 notebooks. |
| `eval/analysis/` | Calibration of local runs against hidden scores, the claim chronology checker, the Harness² archive verifier and reader. |
| `paper/` | The writeup, its evidence index, and `make_tables.py`, which regenerates every table from saved results. |
| `docs/GAPS_2026-10-06.md` | The append-only log: what we expected and how we would read each run, written before the run. |
| `docs/a6000/channel/` | The full message log between this machine and the lab GPU that ran the local screens. |
| `h2g4/` | The adapter that runs Google's [Harness²](https://github.com/google-research/harness2) on this competition's agent format. |

## Checking the numbers

```bash
python paper/make_tables.py                  # every table, from the saved per-task results
python eval/analysis/check_claims.py         # each claim's rule commit against its first result commit
python eval/analysis/verify_h2_archive.py eval/a6000/results/h2_gemma --prereg "Harness² pilot pre-registration"
```

## A note on the history

On 23 Oct 2026 the commit author emails were rewritten (one personal address replaced) before the repository went public.
Commit dates and contents are unchanged, but every commit hash changed. `docs/commit-map-2026-10-23.txt` maps each old hash
(as quoted in older GAPS entries and channel messages) to its new one; `check_claims.py` reads dates and contents, so it gives
the same answers before and after.

## Licence and third-party material

Code in this repository is released under the Apache License 2.0 (`LICENSE`), as the competition rules require for shared
competition code. `submissions/pub024` is a byte-identical copy of the public Kaggle notebook "Gemma 4 Baseline | LB 0.24"
by honghanhhh, kept as a control and credited here. Task data and patches come from the competition and from open-source
repositories, under their own licences.
