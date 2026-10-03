Test data for component (b) of docs/eval/GOLDEN_EVALS_SPEC.md (tests/test_golden_runner.py, tests/test_golden_trace.py).

- `atif_<tid>.json`: ATIF-v1.7 traces copied from `eval/race2/eval/runs/r2_v10_1/traces/trace_<tid>.json`, every step
  kept, long strings trimmed (observation stdout/stderr to head 120 + tail 50 chars; commands other than --repro-only heredocs to 200 + 60, so `[t=Ns]` footers survive).
  rich_3043: a plain five-stage run; fastapi_14492: two multi-call steps whose second results are `source: system`
  steps; fastapi_14419: a `thinking` step that also carries a tool call; fastapi_13537: an invented tool name
  (`view.py`) with no observation (the harness crashed).
- `golden_calc.py`: synthetic golden dataset cases on the calc task of `tests/test_v10_flow.py`.
