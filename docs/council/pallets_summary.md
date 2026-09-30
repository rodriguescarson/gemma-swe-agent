# SWE-Pallets-X as a hidden-like dev set (2026-09-30)

Why: the hidden set (~120 tasks, public LB slice ~60) comes from private repos other than fastapi/rich, and our 74-task
tuning set may flatter or mislead us (v10.1 solves 27/74 on the pod; v4 scored 0.12 on the hidden LB). This builds a
dev set from repos the agent has never been tuned on, verified under the competition harness's own verification
semantics, and wires it for the golden evals and for a faithful pod/L4 run. No Kaggle submissions, no pods, no
OpenRouter; every number below has the file or command that produced it. Estimates are labelled.

## 0. Bottom line

- **Downloaded and verified:** `takumuhata/swe-pallets-x` is now **v4: 476 tasks over 8 repos, licence CC0-1.0** (not 181
  tasks / CC-BY-SA-4.0 as briefed; the 181 are its v1 core, click 109 + werkzeug 43 + flask 29). All 476 snapshots are local
  and size-checked against the Kaggle listing (476/476, 3.0 GB, `data/pallets/snapshots/`). Schema is a superset of
  `data/tasks.jsonl`; swegemma's own `load_tasks` reads it unchanged (extra keys dropped).
- **Valid under harness semantics (gold passes twice, empty patch fails):** **197 of the 215 pallets-org tasks**
  (Linux verdict; 196 on macOS), of which **165 of the 181-task core**: click 103/109, flask 21/29, werkzeug 41/43, jinja2
  29/29, markupsafe 2/4, itsdangerous 1/1. The pytest repo is **0/132** (structurally ungradable under the harness,
  section 4.4). sympy: **116 of 129** valid on Linux, **110** kept after dropping 6 whose gold pytest run takes 95 to 161 s
  (more than half the grader's 180 s timeout; section 4.5). **The dev set is 307 tasks** (197 pallets-org + 110 sympy,
  `data/pallets/valid_ids.txt`). A re-run of the oracle today on a seeded sample of 16 (12 valid, 4 invalid, every repo
  but itsdangerous) reproduced 16/16 verdicts.
- **Split:** DEV 204 / HOLDOUT 103 (pallets-org 131 / 66, sympy 73 / 37), stratified by repo, balanced on gold-patch size
  (section 6). `dev_order` interleaves repos, so any prefix is a balanced subset (the first 40: click, flask, jinja2 8 each,
  sympy and werkzeug 7 each, itsdangerous and markupsafe 1 each). Pallets-only runs: `grep -v '^sympy_' dev_ids.txt`.
- **Three findings that change how this set must be run** (all measured):
  1. **The competition's `problem_statement` is exactly `PR title + "\n\n" + PR body`** (13/13 byte-identical against
     GitHub, section 5.1). The dataset uses the linked ISSUE instead when one exists, which reads very differently
     (pallets-org: 16% PR voice vs 61%, 45% code blocks vs 16%). Rebuilt PR-style statements for 466/476
     (`data/pallets/tasks_prstyle.jsonl`); they match the competition's statement profile (section 5.1). Use them for
     agent runs.
  2. **All pallets repos use a `src/` layout.** In the stock subprocess sandbox (Kaggle-like: nothing installed, only
     `PYTHONPATH=<workspace>`) **0 of 8** gold-valid tasks were gradable: the tests import the host's installed click/jinja2/...,
     and 3 of 8 even pass with NO patch (section 4.3). The oracle therefore puts `<ws>/src` on the path (the pod's
     `pip install -e /workspace`).
  3. **On the pod as configured today the same trap reappears:** `pod/buildenv.sh` installs click (via typer) and Flask,
     Werkzeug, Jinja2, MarkupSafe and itsdangerous (via pytest-httpbin -> httpbin), and flit_core's editable install writes
     `<module>.pth`, which sorts AFTER the sandbox's `_host_env.pth`. A free local emulation of the pod
     (`scripts/pallets/pod_probe.sh`, section 7.2) measured it: the stock pod runner grades 3 of 14 valid tasks (4 of the
     14 resolve with NO patch). `scripts/pallets/run_eval_pallets.py` is the fix (src path first, per-repo test extras,
     the pack's own wheelhouse, and, added today, a stub for buildenv's pytest-httpbin plugin, which made werkzeug's
     memory-leak test fail on 8 werkzeug tasks): 39 of the first 40 dev tasks before the stub, 47 of 47 after it (the
     40 plus the other 7 werkzeug tasks graded on `tests/test_routing.py`), and 9 of the 9 flask-wz2 tasks.
- **Harness-semantics lessons that also apply to the hidden set** (section 4.2): the harness `pytest.ini` replaces the
  repo's own pytest config (drops `filterwarnings = error` and `-p pytester`), a skipped parametrization of a required
  test fails the JUnit check (so does an `@XFAIL` test that the test_patch only shows as diff context, sympy), and the
  grader's `PYTHONSAFEPATH=1` breaks tests that spawn `python script.py` helpers. A hidden task hit by any of these is
  unwinnable for everyone. Rate here: 9 of 215 pallets-org tasks (config 3, Windows-only 2, skipped parametrization 2,
  `PYTHONSAFEPATH` 2) and 5 of 129 sympy tasks fail on these harness semantics alone, 4.1% of the 344 that were not
  structurally ungradable (sections 4.2, 4.5; the pytest repo, 132, fails for other reasons first).
- **Ready for a pod:** `data/pallets/harness/` holds the first 40 default-venv dev tasks in the competition layout with graphs and
  embeddings (1.3 GB), and the pod pre-flight on exactly those tasks passed 40/40 locally (section 7). Recipe in 7.3.
- **Caveat on hidden-likeness:** 95 of the 307 (all 41 werkzeug, 54 sympy) need a test package that neither Kaggle's image
  nor the competition wheels have (`ephemeral-port-reserve`, `hypothesis`); they are gradable here because the venvs and
  the pod pack add it. One sympy verdict (sympy_dc25d66) flips when Kaggle's optional scipy is importable (section 4.5).

## 1. What was downloaded

| item | value | evidence |
|---|---|---|
| dataset | `takumuhata/swe-pallets-x`, "SWE-Pallets-X: Verified SWE-Agent Tasks", v4 (README: "v4 normalizes all created_at/fix_date values to ISO 8601") | `kaggle datasets metadata`; `data/pallets/README.md` |
