# Analysis scripts for the IATMSI-2027 version of the paper

These scripts make every number in the six-page conference version of *A 74-Task Local Screen Did Not Rank Seven
Gemma 4 31B Agent Configurations, and Hidden-Read Noise Is Only Bracketed* (Carson Rodrigues, Celabe Research).
The longer version is the Zenodo preprint, doi:10.5281/zenodo.23592037.

They read this repository and write nothing outside this folder.

## Run

```bash
pip install -r paper/iatmsi-2027/analysis/requirements.txt    # numpy, scipy
python3 paper/iatmsi-2027/analysis/calibration_robustness.py
python3 paper/iatmsi-2027/analysis/run_inventory.py --repo .
python3 paper/iatmsi-2027/analysis/decision_checks.py --repo .
python3 paper/iatmsi-2027/analysis/test_scoring.py
python3 paper/iatmsi-2027/make_later_macros.py .
git diff --stat paper/iatmsi-2027
```

| Script | Writes | What it covers |
|---|---|---|
| `analysis/calibration_robustness.py` | `analysis/results/robust_macros.tex`, `calibration_robustness.*` | Rank correlation, exact p, bootstrap interval, critical value, power, leave-one-out, the 58-task denominator check |
| `analysis/run_inventory.py` | `analysis/results/inventory_macros.tex`, `run_inventory.*` | Every complete run, the exclusions and their reasons, submission counts |
| `analysis/decision_checks.py` | `analysis/results/decision_macros.tex`, `decision_checks.*`, `checksums.sha256` | Outcome categories, the trace search, the checksum manifest of every input file |
| `analysis/test_scoring.py` | nothing (tests) | Hand-checked tests of the outcome categories, rank correlation, exact p and critical value |
| `make_later_macros.py` | `later_macros.tex`, `table_power.tex` | The read-noise bracket, reads per arm, drop probabilities, the 15-repository transfer counts, the time ladder |

## What you should see

On a fresh clone the outputs match the committed ones except:

- the lines that record the repository HEAD and tags, which change with every commit;
- `nChecksums` in `decision_macros.tex` and the matching lines of `checksums.sha256`: 49 input files on the author's
  machine, 37 on a clone. The other 12 are the trace archives of the Kaggle L4 runs (`eval/kaggle/*/traces.tar.gz`),
  which are not in the repository, so the trace search (`tracesRead`) cannot be rerun from a clone.

The upper end of the read-noise bracket (about 1.56 tasks, 23 degrees of freedom) comes from repeated public-notebook
reads in a third-party dataset. Those draws were not kept; `make_later_macros.py` holds the summary values it used.

## Data

`data/tasks.jsonl`, the harness wheels and the sample submission come from the Kaggle competition's data page
(Google, "The Gemma 4 Developer Agent Competition"), which lists the data licence as Apache 2.0. Everything else here is
the author's own work under this repository's Apache-2.0 licence.
