Ad-hoc analysis scripts behind ../V7C_FAILURE_ANALYSIS.md. Read-only, untested; the default paths are the A6000 box's (~/g4/runs/p2/...).
Run as: python3 -I <script> [args]. classify_failures.py and compare_patches.py read gold patches: diagnosis only, never feed them to prompts or training.
cross_stage_refusals.py takes LABEL=GLOB arguments (trace globs) and counts both re-read markers (v4h6g..v7c ALREADY SHOWN, v7d SHOWN AGAIN);
aggregate_failures.py takes an items directory. Both run on the Mac copies under eval/a6000/results/p2 (section 7 of the analysis).
