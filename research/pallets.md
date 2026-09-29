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
| licence | **CC0-1.0** (Kaggle metadata `licenses: [{"name": "CC0-1.0"}]`, re-read live 2026-09-30 03:10 and 03:42 IST). The code inside the snapshots keeps its upstream licence: BSD-3-Clause (pallets `LICENSE.txt`), BSD (sympy `LICENSE`), MIT (pytest `LICENSE`) | same; snapshot LICENSE files |
| size | 1,453 files, 23.5 GB: snapshots 3.0 GB, graphs 12.1 GB, embeddings 8.4 GB, tasks.jsonl 3.7 MB, pipeline code | `dataset_list_files` |
| fetched | tasks.jsonl, README.md, pipeline/ (23 files), all 476 snapshots (size-verified), 1 graph + 1 embedding (format check) | `scripts/pallets/fetch.py` |
| not fetched | graphs + embeddings (20.5 GB): only needed for a faithful pod run, per packed subset (section 7) | |
| repos | pytest 132, sympy 129, click 109, werkzeug 43, flask 29, jinja2 29, markupsafe 4, itsdangerous 1 | tasks.jsonl |
| dates | click 2022-01..2026-09, flask 2022-02..2026-07, werkzeug 2024-11..2026-09, jinja2 2021-05..2025-03, pytest 2016..2026, sympy 2019..2026 | tasks.jsonl `created_at` |

`scripts/pallets/fetch.py` downloads file by file and checks each file's size against the listing (Kaggle throttled a
few sympy files mid-run and left them final-named but truncated; the size check caught 5 such files and the retries
fixed them; the final check is 476/476).

The dataset's own "verified" flag does not transfer: its `pipeline/pipeline/verify.py` runs `pytest -x` in a per-instance
venv with an era-matched Python (3.10 to 3.13) and dependencies pinned to the last release before the commit, with no
harness `pytest.ini`/`conftest.py`, no `PYTHONSAFEPATH`, and no JUnit required-node check. Hence this oracle.

## 2. Schema check against `data/tasks.jsonl`

- Competition keys (8): `instance_id, repo, base_commit, patch, test_patch, problem_statement, hints_text, created_at`.
  Pallets has all 8 with the same types, plus `fix_commit, fix_date, pr_number, test_files, n_src_files, n_patch_lines,
  n_test_files`. `swegemma.models.task.load_tasks` loads all 476 (it filters unknown keys).
- `test_files` equals swegemma's `extract_test_files_from_patch(test_patch)` for 476/476, so the grader targets the same
  files the dataset intended (the harness ignores the field and re-derives it).
- Patches: pallets uses `diff --git` headers, the competition plain `--- a/`; the harness apply pipeline takes both (the
  oracle applies every gold patch through it). Gold patches touch .py files only and never a protected test/config path
  (0/476, same as the competition's 0/129).
- `hints_text` is empty in both. IDs are `<repo>_<7-char fix sha>` (competition: `<repo>_<PR number>`); no collisions.
- **Snapshots:** same tar layout (`./` + `.git/`), but a single commit `baseline` with no `[user]` in `.git/config`, while
  competition snapshots carry the full history and `user.name=Agent, user.email=agent@eval`. Without an identity the
  harness's `git commit -m baseline && git tag -f _swegemma_baseline` fails on Linux ("fatal: unable to auto-detect
  email address (got 'root@f2aafc43d549.(none)')", reproduced in python:3.12-slim with HOME unset; it succeeds on macOS,
  so a Mac-only test hides it). `scripts/pallets/pack.py` adds the competition's identity; nothing else changes (member
  lists identical, checked).
- **Graphs/embeddings:** same node-link JSON keys (`directed, multigraph, graph, nodes[id,name,text], edges[source,target,
  type,key]`) and 256-dim float32 node vectors as the competition's; similarity is node-to-node
  (`swegemma/graph/retrieval_utils.get_similar_nodes`), so the dataset's TF-IDF embedding space is usable as-is. They
  must be renamed from `<tid>` to `<repo>_<base_commit>` (the harness key, `swegemma/context.py graph_repo_key`);
  `pack.py` does it. v10 declares the three graph tools, and the harness only advertises them when both files exist
  (`agent_runner.py:170-176`), so a run without them sees a different prompt than the public Kaggle tasks.

## 3. Test environments

`scripts/pallets/build_envs.sh` builds one uv venv per repo in `~/.cache/g4/pallets/<name>` (network once), stamped with
`.g4_pallets_ok` (= `uv pip freeze` + the rule that produced it):

- Python 3.12, pytest 8.4.2 (both Kaggle's), every package Kaggle's image has at Kaggle's version
  (`eval/kaggle/rescore_fair/pip_freeze.txt`: Werkzeug 3.1.8, Jinja2 3.1.6, click 8.3.3, MarkupSafe 3.0.3, itsdangerous 2.2.0,
  blinker 1.9.0, ...), plus the test-only deps Kaggle lacks, pinned: flask `asgiref`, werkzeug `ephemeral-port-reserve`,
  jinja2 `trio`, itsdangerous `freezegun`, pytest `argcomplete hypothesis mock xmlschema py toml`, sympy `hypothesis`
  (sympy also gets Kaggle's setuptools 81.0.0, whose shim supplies the `distutils` that sympy of 2019-2021 imports).
- Code under test comes from the workspace: `PYTHONPATH=<ws>:<ws>/src` (PYTHONPATH precedes site-packages). The repo's
  own package is ALSO installed at Kaggle's version, only for its metadata: without it 4 tasks fail on
  `importlib.metadata.PackageNotFoundError` (flask `--version`, click `__version__`), and werkzeug's dev-server helper,
  which starts a child with `PYTHONPATH` replaced, cannot import werkzeug at all (pass 1 vs pass 2 in section 4.1).
- Era venv `flask-wz2` (Werkzeug 2.3.8, Flask 2.3.3; both versions ship in the competition wheels): 13 flask base commits
  of 2022-2023 import `werkzeug.urls.url_quote` or `werkzeug.__version__`, removed in Werkzeug 3. It recovers 9. A second
  era venv `flask-2022` (Werkzeug 2.2.3, click 8.1.8; not in the competition wheels) recovered 1 more of the remaining 8
  and is NOT used (the rest need exact 2022 behaviour: warning counts, route order, `FlaskClient._cookies`).

## 4. Gold-patch oracle

**Method** (`scripts/pallets/oracle.py`, via `scripts/pallets/source.py`): the project's harness-exact port
`tests/v10_support/tasks.py` is reused unmodified. `source.activate()` only rebinds its path globals and its
`sandbox_env`, so the golden build's caches are untouched. Per task: build the harness base workspace (snapshot,
`.git/info/exclude`, swegemma's own `setup_workspace_test_config` for `pytest.ini` + the conftest hook, baseline commit),
then `mini_verify` (port of `verify_task`: 4-pass harness apply, protected-file reset, test_patch, config overwrite,
the grader's exact pytest line with `PYTHONSAFEPATH=1 ... -p no:anyio -o timeout=0 -o python_classes=...`,
`_validate_junit_xml` incl. required nodes, stdout checks) with the gold patch twice and the empty patch once, 180 s per
pytest run (the grader's command timeout). **valid = gold resolves both times AND the empty patch does not** (the
"gradable" rule of GOLDEN_EVALS_SPEC 4.5). Rows: `data/pallets/oracle/*.jsonl`; full pytest output of every run in
`data/pallets/oracle/logs*/` (gitignored).

### 4.1 Results

| repo | tasks | pass 1 (no own pkg) | pass 2 (Mac) | + flask-wz2 (Mac) | Linux (python:3.12-slim) | final |
|---|---|---|---|---|---|---|
| click | 109 | 100 | 102 | 102 | 103 | **103** |
| flask | 29 | 10 | 12 | 21 | 21 (12 + 9 flask-wz2) | **21** |
| werkzeug | 43 | 41 | 41 | 41 | 41 | **41** |
| jinja2 | 29 | 29 | 29 | 29 | 29 | **29** |
| markupsafe | 4 | 2 | 2 | 2 | 2 | **2** |
| itsdangerous | 1 | 1 | 1 | 1 | 1 | **1** |
| **pallets-org** | **215** | 183 | 187 | 196 | 197 | **197** |
| pytest | 132 | 0 | | | | **0** |
| sympy | 129 | 99 (venv without setuptools) | 115 (30 re-run) | | 116 | **110** (6 slow dropped) |
| **all** | **476** | | | | 313 | **307** |

- Linux vs macOS, default venvs: identical class on 214/215; the one difference is `click_43c2e7f`, whose required test
  `test_path_surrogates` skips when the filesystem rejects non-UTF-8 names (APFS) and runs on Linux. Linux is the
  scoring OS, so it is valid; `split.json` marks it `mac_valid: false` (the golden runner executes on the Mac).
- The Linux run (`scripts/pallets/linux_oracle.sh`) rebuilds the venvs inside the container from the same script; its rows
  are `data/pallets/oracle/linux/results_linux*.jsonl`.
- Grader cost (Linux rows, slower of the two gold runs, `oracle/summary.json`): median gold pytest time click 0.10 s,
  flask 0.15 s, werkzeug 0.19 s, jinja2 0.07 s, max 2.2 s (click_bc32a92); sympy median 2.2 s, p90 14.9 s, max 59.5 s
  (sympy_29f686c). Median tests per grader run 71 (p90 300) for pallets-org, 27 (p90 167) for sympy. Only 5 of 197
  pallets-org and 8 of 110 sympy empty runs fail at collection (`ERROR collecting` / `ImportError while` in the empty
  log); the rest fail on assertions, so the hidden tests mostly exercise behaviour of existing names rather than
  importing new ones.
- Reproducibility (2026-09-30 03:45 IST, after the split was written): `oracle.py` on a `random.Random(20260930)` sample
  of 12 valid tasks (click 3, flask 1, flask-wz2 1, werkzeug 2, jinja2 2, sympy 3) plus 4 invalid ones (click_8ee83dd,
  click_0f71fe7, click_ad39d74, markupsafe_0b6bee0) gave the recorded class for 16/16.

### 4.2 Why the other 18 pallets-org tasks are invalid (each with its evidence)

| class | tasks | cause | valid on Kaggle? |
|---|---|---|---|
| harness drops repo pytest config | click_0f71fe7, click_7d05a59, click_82f377c | the test expects exit code 1 from a duplicate-option `UserWarning`, which the repo's `filterwarnings = error` turns into an error; the harness `pytest.ini` replaces that config and ignores UserWarning (log: `assert 0 == 1`, `tests/test_options.py::test_flag_group_competition_duplicate_option_name`) | no (same ini there) |
| Windows-only required test | click_ad39d74, click_b96c260 | required node `@pytest.mark.skipif(sys.platform != "win32")`; a skipped required node fails `_validate_junit_xml` | no |
| skipped parametrization | markupsafe_0b6bee0, markupsafe_e49d257 | `test_escaping` is parametrized over the C speedups, which a source checkout lacks; the skipped variant fails the required-node check | no on Kaggle (not built); maybe on a pod if the editable install compiles the extension |
| grader `PYTHONSAFEPATH=1` | werkzeug_60ea32c, werkzeug_fa0f4f2 | `tests/test_debug.py::test_basic` starts `tests/live_apps/run.py`, which imports its sibling module; `PYTHONSAFEPATH=1` (inherited) removes the script dir from `sys.path`, the child dies, and the fixture's `wait_ready` loops until the 180 s timeout. Without it the file passes 22/22 in 0.28 s | no |
| empty patch resolves | click_8ee83dd | the new tests pass on the base commit | no |
| era dependencies | 8 flask tasks of 2022-2023 | need Werkzeug < 2.3 / click < 8.2 behaviour (section 3) | no (Kaggle has Werkzeug 3.1.8) |

### 4.3 The stock sandbox (Kaggle semantics) grades none of them

`scripts/run_eval.py --oracle` with `G4_FAITHFUL_ENV=0` (the unmodified subprocess sandbox: nothing installed,
`PYTHONPATH` = workspace root, host site-packages visible) on 8 tasks valid above (2 click, 2 jinja2, 2 werkzeug,
itsdangerous, markupsafe): gold resolved click_4f9086b, jinja2_56a7246, jinja2_7232b82 and failed the other 5.
`--skip-agent-patch` then resolved the same 3 with NO patch: the tests ran against the harness venv's click 8.5.0 and
Jinja2 3.1.6, which already contain those fixes (the markupsafe log shows `markupsafe._native` loaded from
`.venv/lib/python3.12/site-packages`). **0/8 gradable.** Re-run 2026-09-30 03:54 IST with the same 8 verdicts
(`data/pallets/oracle/stock_mac/{gold,empty}/`, command in `stock_mac/run.sh`). This is the requests F10 effect again:
in a subprocess backend a src-layout repo is not importable, so its gold patch cannot matter. The same would hold for any hidden repo with a
`src/` layout if Kaggle scores in the subprocess backend (inference; which backend Kaggle uses is still unverified,
research/harness_runtime.md section 12). The competition's Docker image (`swebench-sandbox:latest`, python 3.13 +
flit-core) would install these repos editable and add `/workspace/src` through `workspace_paths.pth`.

### 4.4 pytest repo: structurally ungradable under the harness (0/132)

1. `src/_pytest/_version.py` is generated by setuptools_scm at install time; the snapshot lacks it and every pytest run
   dies with `ModuleNotFoundError: No module named '_pytest._version'` (132/132; older ones also needed the `py` library,
   added). setuptools_scm is not in the competition wheels, so a pod editable install would not produce it either.
2. With the file written by hand (a probe on the 8 newest tasks), all 8 still fail: `recursive dependency involving
   fixture 'pytester' detected`, because pytest's own `addopts = "-rfEX -p pytester --strict-markers"` lives in its
   pyproject, and the harness `pytest.ini` replaces it.
Excluded. It is also a clean example of a repo the harness cannot grade at all.

### 4.5 sympy

sympy is a different kind of repo from the pallets ones: flat layout, 880 source modules / 525k lines, PR statements from
a template, tests that mostly add asserts to existing functions (section 5), and slow tests (gold pytest median 2.2 s,
p90 14.9 s, max 59.5 s over the 110 kept; pallets-org max 2.2 s).

| run | venv | valid | evidence |
|---|---|---|---|
| Mac pass 1 | `sympy` built without setuptools | 99/129 | `oracle/results_sympy.jsonl`; 18 of its 19 env errors are `ModuleNotFoundError: No module named 'distutils'` (all 18 are sympy of 2019-2021, which imports distutils; Python 3.12 removed it; setuptools' shim restores it) |
| Mac pass 2 | rebuilt with setuptools 81.0.0 (Kaggle's version), the 30 non-valid re-run | 115/129 | `oracle/results_sympy_mac2.jsonl`; sympy_37bde31 flaky (gold1 passed, gold2 hit 180 s on the loaded Mac) |
| Linux, python:3.12-slim | same pins, all 129 | **116/129** | `oracle/linux/results_linux_sympy.jsonl` (the verdict of record) |
| dev set | Linux verdict minus gold pytest > 90 s | **110** | `slow_ids.txt`: sympy_0dcb63d 146.5 s, 37bde31 160.8, 7497556 135.8, 7907fec 104.5, b5eb853 94.6, de58c0e 107.8 |

Why the 13 are invalid on Linux (same class on both OSes for all 13):
- 5 `gold_junit_reject` (6467b28, 7b00305, 88336b5, a22a276, cb458c0): the grader's required-node list includes a test
  that does not pass even with the gold patch, e.g. `@XFAIL def test_continuous_domain_acot` in sympy_88336b5, which the
  test_patch only touches as diff context. Unwinnable for everyone.
- 4 `gold_tests_fail` (403dd53, 8381f0c, b860164, ba448a2): one test still fails with gold + test_patch. Three fail the
  same one, `test_polytools.py::test_Poly_rootof_extension_primitive_element` (`IsomorphismFailed`); b860164 fails
  `test_numbers.py::test_numpy_to_float` on NumPy 2's scalar repr (`could not convert string to float:
  'np.float16(0.6665)'`).
- 2 `gold_env_error`: 8e687b8 needs scipy for `test_lambdify::test_integral` (with Kaggle's scipy 1.16.3 it still fails:
  `np.PINF` was removed in NumPy 2.0); 942bbe7 fails to parse `Symbol ('x' )!` in every environment.
- 2 `gold_timeout` (01987e2, 4623f8f): hang past 180 s in all three runs.

Two environment sensitivities, both measured:
- **Optional packages change verdicts.** sympy's tests switch on optional packages (`import_module`). The `sympy-kx` venv
  adds the ones Kaggle's image has at Kaggle's versions (scipy 1.16.3, matplotlib 3.10.0, numexpr, Cython, lxml,
  antlr4 4.9.3, numba 0.60.0, networkx; `build_envs.sh sympy-kx`). On 23 tasks (`oracle/results_sympy_kx.jsonl`) 22
  verdicts are unchanged and **sympy_dc25d66 flips from valid to invalid**: with scipy importable,
  `test_simplex.py::test_lp` takes a branch that imports `sympy.solvers.inequalities._np`, which the gold patch does not
  add (`oracle/logs_sympy_kx/sympy_dc25d66.gold1.log`). The dev set keeps the verdicts of the plain `sympy` venv, and a
  pod run ships exactly that venv (pack.py `_extra-sympy.txt`), so the verdicts hold there.
- **hypothesis is required but not shipped.** In 54 of the 110 kept tasks (all but 2 created 2023-08-17 or later),
  `sympy/conftest.py` raises `ImportError: hypothesis is a required dependency to run the SymPy test suite`. hypothesis
  is in neither Kaggle's image (`eval/kaggle/rescore_fair/pip_freeze.txt`) nor the competition wheels
  (`data/raw/wheels`). The first pod probe hit exactly this (section 7.2). The same holds for werkzeug: `tests/conftest.py`
  imports `ephemeral_port_reserve` unconditionally (line 18 in the newest snapshot) in all 41 kept werkzeug tasks, and it
  is also absent from both. With Kaggle's packages alone these 95 tasks would stop at conftest import (measured for sympy
  in probe 1, read from the source for werkzeug); they are gradable here only because the venvs and the pod pack add
  the packages. Whether hidden tasks have such needs, and whether the organisers' private wheel set covers them, is
  unknown.

Why keep sympy: it is the only non-pallets organisation in the set, it has the flat layout that the public repos have,
and its size and slow tests are plausible causes of the one measured way the hidden set differs (hidden tasks ran about
1.9x slower than public ones on Kaggle). That sympy resembles the hidden repos is an inference. It is a separate stratum, so a
pallets-only run is one `grep -v '^sympy_'` away.

## 5. How these tasks differ from fastapi/rich

All numbers from `python3 scripts/pallets/profile.py --valid data/pallets/valid_ids.txt` (`data/pallets/profile.json`),
comparing the 74 Kaggle-valid competition tasks with the 197 valid pallets-org tasks (sympy in its own column).

### 5.1 Problem statements

| metric | comp 74 | fastapi 31 | rich 42 | pallets-org 197 (dataset) | pallets-org 197 (PR-style) | sympy 110 (dataset) | sympy 110 (PR-style) |
|---|---|---|---|---|---|---|---|
| median chars | 466 | 816 | 138 | 865 | 607 | 1,618 | 1,687 |
| title-only (body < 40 chars of prose) | 31% | 6% | 50% | 8% | 14% | 1% | 1% |
| PR voice ("this PR", "fixes #", ...) | 61% | 55% | 67% | 16% | **60%** | 74% | 89% |
| PR checklist | 26% | 16% | 33% | 8% | 24% | 4% | 4% |
| issue link | 70% | 58% | 79% | 40% | 75% | 76% | 89% |
| code block | 16% | 29% | 7% | 45% | 7% | 24% | 14% |
| traceback | 0% | 0% | 0% | 9% | 0% | 6% | 2% |
| names a .py path | 12% | 26% | 2% | 28% | 6% | 12% | 10% |

sympy's statements are PR descriptions already for most tasks (74% PR voice in the dataset form) because sympy PRs
follow a fixed template (in the 110 PR-style statements: "References to other Issues or PRs" 93, "Brief description of
what is fixed or changed" 97, a `BEGIN RELEASE NOTES` block 110); at the median they are 3.6x the competition's 466
chars and 2.1x fastapi's 816, the longest competition repo.

The competition statement is the PR, byte for byte: `gh api repos/<repo>/pulls/<n>` title + `"\n\n"` + body equals
`problem_statement` for rich_3063, rich_4075, fastapi_14479, fastapi_15661 and requests_6644 (5/5), and again for 8
tasks drawn with `random.seed(7)` from all 129 (fastapi_14605, fastapi_14512, fastapi_14258, rich_3468, rich_4070,
requests_7433, requests_6757, requests_7315: 8/8, re-checked 2026-09-30 03:12 IST), so **13 of 13 distinct tasks**.
The dataset's `enrich.py` prefers the linked issue ("prefer the original linked issue as problem statement"), giving symptom reports
with code and tracebacks instead of PR descriptions. `scripts/pallets/pr_statements.py` rebuilt the PR form from the
dataset's `pr_number` for 466/476 (10 have no PR number; 90 were already identical). Spot check 2026-09-30 04:05 IST:
the rebuilt statements of click_a3321c9, sympy_fd82eac and werkzeug_795f4ea equal `gh api` title + "\n\n" + body byte for
byte, `\r\n` included (the competition's statements keep GitHub's CRs too: 91 of 129 contain `\r`). The PR-style
profile matches the competition closely, so **agent runs should use `data/pallets/tasks_prstyle.jsonl`** (pack.py's default). The hidden set
presumably follows the same PR-based pipeline (inference: same organisers and format).

### 5.2 Gold patches and tests

| metric | comp 74 | pallets-org 197 | click | flask | werkzeug | jinja2 | sympy 110 |
|---|---|---|---|---|---|---|---|
| single-file gold | 77% | 77% | 82% | 67% | 56% | 93% | 69% |
| changed lines, median / p90 | 7 / 91 | 19 / 94 | 20 / 76 | 37 / 99 | 24 / 154 | 8 / 36 | 16 / 125 |
| hunks, median | 2 | 2 | 2 | 3 | 3 | 2 | 2.5 |
| added test functions, median | 1 | 2 | 2 | 2 | 1 | 1 | 0 |
| test_patch adds no `def test_` | 15% | 20% | 13% | 10% | 46% | 17% | 52% |
| uses `pytest.mark.parametrize` | 20% | 43% | 59% | 10% | 34% | 21% | 1% |
| class-based tests | 0% | 5% | 1% | 14% | 0% | 17% | 0% |
| new test file | 0% | 3% | 2% | 5% | 0% | 10% | 1% |

- Gold patches are about 2.7x larger at the median (19 vs 7 changed lines); the tail is similar. werkzeug and flask more
  often span several files.
- Tests lean on parametrize (click 59%): one gold behaviour is checked over many inputs, so a partial fix fails more
  often than on rich's snapshot-style tests. werkzeug's test_patches often only edit existing tests (46%): the grader
  then takes the required nodes from the hunk headers.
- Codebase size (package source, newest snapshot): click 17 files / 12.7k lines, flask 24 / 9.5k, werkzeug 54 / 23.4k,
  jinja2 25 / 14.4k, vs rich 100 / 38.5k and fastapi ~16.5k lines in its graph's `fastapi.*` nodes. Pallets repos are
  smaller than rich, so locating should be no harder. sympy is the opposite: 880 source files / 525k lines in `sympy/`
  (plus 689 test files / 276k lines; newest snapshot, sympy_253f564), 14x rich. It is the stratum that tests locating in a
  large codebase, and half its test_patches (52%) only add asserts to existing test functions.
- Era: 58% of valid pallets-org tasks were created 2025 or later (click 73 of 103 are 2024-2026), sympy 27%; a
  `created_at >= 2024` filter keeps the most hidden-like part.

## 6. Split

`scripts/pallets/finalize.py` -> `data/pallets/split.json` (schema `pallets-split-v1`), `dev_ids.txt`, `holdout_ids.txt`,
`valid_ids.txt`, `task_env.json` (tid -> venv), `oracle/summary.json`.

- Strata = repo (as asked). Inside a repo, tasks are sorted by gold changed lines (ties: `sha256("pallets-v1:<tid>")`)
  and every third one is holdout from a sha-seeded offset. Systematic sampling was needed: the golden spec's plain
  "first k in sha order" rule gave this pool a holdout at median 27 changed lines vs dev 16.
- Result (`split.json` `strata`, `counts`):

| stratum | valid | dev | holdout | in the first 40 of `dev_order` |
|---|---|---|---|---|
| click | 103 | 68 | 35 | 8 |
| flask | 21 (9 need `flask-wz2`) | 14 | 7 | 8 |
| itsdangerous | 1 | 1 | 0 | 1 |
| jinja2 | 29 | 19 | 10 | 8 |
| markupsafe | 2 | 1 | 1 | 1 |
| sympy | 110 | 73 | 37 | 7 |
| werkzeug | 41 | 28 | 13 | 7 |
| **total** | **307** | **204** | **103** | 40 |

- Balance, dev vs holdout (PR-style statements): all 307: median gold changed lines 17.5 vs 19, mean 36.0 vs 36.0,
  multi-file 26% vs 24%, created 2025 or later 47% vs 48%, statement median 828 vs 843 chars. Pallets-org: 19 vs 20.5
  lines, multi-file 24% vs 20%, 2025+ 58% vs 59%, statement 615 vs 592. sympy: 16 vs 16 lines, multi-file 30% vs 32%,
  gold pytest median 3.2 s vs 1.3 s.
- `dev_order` / `holdout_order` interleave the repos round-robin (each repo in sha order): any prefix is spread across
  repos instead of being mostly click. Per task: `split, repo, venv, era_env, created_at, core181, mac_valid,
  linux_valid, pr_statement, gold_pytest_s, slow`. `pack.py --venv default` drops the flask-wz2 tasks, so
  `pack.py --ids dev_ids.txt --limit 40` packs click 8, jinja2 8, sympy 8, werkzeug 8, flask 6, itsdangerous 1,
  markupsafe 1 (the pod probe's set, section 7.2).
- Optional stricter filter: `data/pallets/kaggle_pkg_gaps.json` lists the 95 tasks that need a test package Kaggle
  lacks (section 4.5). Without them: 136 dev / 76 holdout; also requiring `created_at >= 2024`: 67 / 35. (flask's
  asgiref and jinja2's trio appear in some test files and were not checked per task.)
- Holdout protocol as in the golden spec: tune on dev only, look at holdout once per final candidate.

## 7. Plugging it into a faithful pod / L4 run

### 7.1 Layout (`scripts/pallets/pack.py`)

```
python3 scripts/pallets/wheelhouse.py                                   # once: linux cp312 wheels of every pin (8.3 MB)
python3 scripts/pallets/pack.py --ids data/pallets/dev_ids.txt --limit 40 --out data/pallets/harness
# for the graph tools (dev40 measured: 1.1 GB for 40 tasks, 645 MB graphs + 471 MB embeddings):
python scripts/pallets/fetch.py --ids data/pallets/harness/ids.txt graphs/graphs/ embeddings/embeddings/ && re-run pack
```

`data/pallets/harness/` then has the competition layout: `tasks.jsonl` (the 8 competition keys, PR-style statements),
`snapshots/<tid>.tgz` (identity added), `graphs/` + `embeddings/` renamed to `<repo>_<base_commit>`, `wheels/` (only
the pinned versions: swegemma resolves `tasks_path.parent/wheels` before `/wheels`, `container_setup.py:61-86`, so the
faithful install gets pytest 8.4.2 and click 8.3.3, not the newest competition wheels 9.1.1 / 8.4.2), `env.json`,
`ids.txt`. `--venv default` (the default) packs the Kaggle-version tasks; the 9 flask-wz2 tasks need their own pack
(`--venv flask-wz2 --out data/pallets/harness_wz2`), because pack refuses to mix venvs that pin different versions.

**Built and checked 2026-09-30 04:15 IST (local, gitignored, ready to rsync):** `data/pallets/harness/` = the 40 tasks of
`dev40_ids.txt` (= the dev40 probe's set) with graphs + embeddings for 40/40 (fetched with `fetch.py --ids
data/pallets/dev40_ids.txt`, `DONE bad=0`), 34 pinned wheels plus the 7 `_extra-<repo>.txt` files, 39 PR-style
statements (1 task has no PR number), 1.3 GB; `swegemma.models.task.load_tasks` reads its `tasks.jsonl` (40 rows) and
every row's graph exists under the harness key. `data/pallets/harness_wz2/` = the 5 dev flask-wz2 tasks (no graphs yet,
10 MB).

### 7.2 The pod environment problem and the fix

What the pod does today (`pod/run_eval.sh` -> `scripts/run_eval.py`, `G4_FAITHFUL_ENV=1`): every sandbox venv gets
`_host_env.pth` -> `/root/buildenv` (`pod/buildenv.sh`: the public tasks' test dependencies, which bring click via typer
and Flask, Werkzeug, Jinja2, MarkupSafe, itsdangerous via pytest-httpbin -> httpbin), then `pip install -e /workspace`
from `/wheels`. flit_core's editable install writes `<module>.pth` (flit_core/wheel.py:168 in the competition's
flit_core 3.12.0 wheel), which sorts after `_host_env.pth`, so `import click` in a pallets task finds buildenv's click
8.5.0, not the task's code.

Measured with `scripts/pallets/pod_probe.sh` (free and local: python:3.12-slim, `pod/buildenv.sh` run inside, the newest
competition wheels of click/flask/werkzeug/jinja2/itsdangerous in the harness python as `pod/harness_env.sh` does, the
tasks packed by `pack.py`, the real harness in the subprocess sandbox; gold = `--oracle`, empty = `--skip-agent-patch`;
valid = gold resolved and empty not; no model, no GPU). Caveat: the container is arm64, so compiled x86_64 pins fall
back to buildenv's copies.

| probe | tasks | stock `run_eval.py` valid | `run_eval_pallets.py` valid | evidence (`data/pallets/oracle/`) |
|---|---|---|---|---|
| 1 | 14: click, jinja2, werkzeug, flask 2 each, itsdangerous, markupsafe, sympy 4 | 3 (4 resolve with NO patch) | 12 | `pod_probe/probe.log` |
| 2 (after fix 2) | 4 sympy | 1 | 4 | `pod_probe_sympy/probe.log` |
| dev40 (fixes 1-3) | the first 40 default-venv tasks of `dev_order` (`pack.py --limit 40`) | not run | **39** | `pod_probe_dev40/probe.log` |
| wz2 (fixes 1-4) | the 9 flask-wz2 tasks, own pack (`PROBE_VENV=flask-wz2`) | not run | **9** | `pod_probe_wz2/probe.log` |
| stub (fixes 1-4) | dev40 + the other 7 werkzeug tasks graded on `tests/test_routing.py` | not run | **47** | `pod_probe_stub/probe.log` |

The fixes, all in `scripts/pallets/run_eval_pallets.py` (`scripts/run_eval.py` is not edited; for flat-layout repos the
wrapper changes only the wheelhouse and the extras, fixes 2 and 3):
1. **`__g4_src.pth`** = `/workspace/src` in the sandbox venv, when the repo has `src/`. It sorts before `_host_env.pth`,
   like pip's own `__editable__.*.pth` finders. Probe 1: stock 3/14 -> 12/14.
2. **Per-repo extras.** Probe 1's two misses were sympy: `ImportError: hypothesis is a required dependency to run the
   SymPy test suite` (`pod_probe/fix_gold/test_outputs/sympy_0105c46.log`). `pack.py` writes `wheels/_extra-<repo>.txt`
   (the oracle venv's freeze minus the repo's own package) and the wrapper installs it `--no-deps` after the faithful
   install. Probe 2: 4/4.
3. **`G4_WHEELHOUSE`** (absolute, outside the four rewritten prefixes): the faithful install reads the pack's own pinned
   wheels. Without it the sandbox copies a wheels dir one level too deep and falls back to the pod's `/wheels`
   (`swegemma/sandbox/subprocess.py:197-198, 458-479`), so pallets' pins (pytest 8.4.2, trio, asgiref,
   ephemeral-port-reserve, hypothesis ...) are never seen.
4. **httpbin stub (found today).** dev40's one miss, werkzeug_23142a3: gold fails
   `tests/test_routing.py::test_no_memory_leak_from_Rule_builder` with `assert 57 == 0`
   (`pod_probe_dev40/fix_gold/test_outputs/werkzeug_23142a3.log`; stderr shows httpbin's "flasgger is not installed"
   warning). buildenv's pytest-httpbin plugin is auto-loaded, imports httpbin, and httpbin builds a Flask app at import;
   through fix 1 that app's werkzeug is the task's own, so 57 `Rule` objects stay alive. The oracle venv and Kaggle's
   image (`eval/kaggle/rescore_fair/pip_freeze.txt`) have no pytest-httpbin, so this is a pod-only false negative, and it
   hits every werkzeug task whose graded files include `tests/test_routing.py` (8 of the 41 kept: 6 dev, 2 holdout). The
   wrapper now writes an empty `pytest_httpbin/plugin.py` into the sandbox venv of src-layout tasks
   (`G4_PALLETS_HTTPBIN_STUB=0` turns it off). Flat-layout repos keep the plugin: the public requests tasks need it, and
   sympy passed 8/8 in dev40 with it loaded. Mechanism check: httpbin's warning appears in the test output of 40/40
   dev40 gold runs (no stub) and 0/9 wz2 gold runs (stub; flask has `src/`).
   Stub probe: 47/47 valid, werkzeug_23142a3 included and all 8 `test_routing.py` tasks resolved by gold; httpbin's
   warning is left only in the 8 sympy runs (flat layout, stub not applied).

So on a pod, run pallets only through `run_eval_pallets.py` with `G4_WHEELHOUSE`, and keep the pre-flight (7.3 step 1):
the probes cover 70 of the 307 tasks, not all of them.

### 7.3 Run

On the pod, the same as `pod/run_eval.sh` with four changes: `--tasks data/pallets/harness/tasks.jsonl
--snapshots-dir data/pallets/harness/snapshots`, `python scripts/pallets/run_eval_pallets.py` in place of
`python scripts/run_eval.py` (identical for flat-layout repos), and `G4_WHEELHOUSE=/root/g4/data/pallets/harness/wheels`
(absolute, not under /tmp, /workspace, /usr/local/bin or /wheels; the wrapper asserts it). Order of operations:

1. **Pre-flight, CPU only, before vLLM starts:** `python scripts/pallets/run_eval_pallets.py --oracle eval ...` and the
   same with `--skip-agent-patch`; the valid set is gold resolved AND empty unresolved. Compare with `valid_ids.txt`;
   drop any task that differs. `scripts/pallets/pod_probe.sh` with `PROBE_RUNS=fix` is exactly this step; for 40 tasks
   it took 4.5 min (gold) + 4 min (empty) on 3 Docker CPUs at `--concurrency 2`. No GPU.
2. The agent run on the first 40 or 60 of `dev_order`.
   Estimate (sequential, L4 clock): 40 tasks take 1.8 h at the public-task pace (163 s/task, Kaggle 4x L4,
   research/harness_runtime.md section 10) and 3.5 h at the hidden-set pace (10.4 h / ~120 tasks = 312 s/task); 60 tasks
   2.7 to 5.2 h. Where pallets lands is informative too (inference): a hidden-like pace on unseen public repos would
   point at repo unfamiliarity rather than the hidden set's infrastructure as the cause of the 1.9x slowdown.
3. What it can show (Wilson 95% CIs): at 60 tasks, 12% -> [6%, 22%], 20% -> [12%, 32%], 36% -> [26%, 49%]. So one 60-task
   run separates "our public rate carries over to unseen repos" (~36%) from "it collapses to the hidden 12%", which is the
   question behind the 0.12 vs 27/74 gap. It is too small for paired A/B deltas under about 10 points; use all 204 dev
   tasks (or the 131 pallets-org ones) and both arms for those.

## 8. Plugging it into the golden evals later (GOLDEN_EVALS_SPEC, not built here)

Nothing in `eval/golden/`, `scripts/golden*` or `tests/test_golden_*` was touched. What a pallets source needs:

| spec input / step | pallets status | what to do |
|---|---|---|
| tasks, snapshots, per-task venv | ready | `source.activate()`; call `source.venv_ok(tid)`, never `tasks.kpar_ok/kpar_dir/repo_key` (they raise `KeyError: 'pallets/click'`, checked); always pass `repo=tid` to `mini_verify` so era venvs apply |
| split (spec 2) | ready | read `data/pallets/split.json`; stratum label `<repo>/unrun` (no race-2 outcomes exist); never reshuffle once a run exists |
| gradability (4.5) | ready | gradable = `valid` here (gold x2, empty fails, 180 s); `runnable` = snapshot present and `source.venv_ok(tid)` |
| golden plan FILES / TESTS, `gold_functions`, `title_words` (4.1) | **computed** | `data/pallets/golden_preview.json` (`scripts/pallets/golden_preview.py`, which imports the builder's pure functions from `scripts/golden/fixture_lib.py` read-only): 307/307 `plan_basis: ast`, 298 with a gold function, 35 FILES lines over 6 entries (truncated as for rich), 4 `TESTS: none` |
| `hidden_nodes` (4.5) | **computed** | same file: non-empty for 296/307; empty for 11 (click_b5464b7, itsdangerous_7f4dcf8, jinja2_d5f49f5, sympy_0dbc71a, 3f7094e, 5c4174c, b3c9da8, e25df9e, werkzeug_051fd66, 580fa61, 8e9105f), which only matters for V's `pre_hidden_nodes_pass` |
| golden plan CAUSE / FIX (4.1) | missing | needs `root_cause` and `one_line_solution`, i.e. a pallets `task_catalog.json` (research/catalog_build method; a labelling job, no OpenRouter needed) |
| golden repro (4.2) | missing | comes from v10 locator traces; none until a first pallets run exists -> `REPRO: none` |
| V `wrong` variant (4.3) | missing | needs unresolved patches from a real run |
| agent env in the stage child (5.5) | **needs one change** | `_g4_kpar.pth` alone would let the sandbox import the venv's installed copy (the metadata install) instead of `/workspace/src`: add `_g4_0src.pth` = `<ws>/src` (sorts first) for repos with `src/`. Same trap as 4.3 |
| exec checks (6.3) | ready | `mini_verify` through `source.activate()`; Mac verdicts differ from Linux on `click_43c2e7f` only among the 307 (`mac_valid` in split.json) |
| schema | **one extension** | golden-case-v1 has no per-task environment; pallets needs `venv` (9 flask tasks use `flask-wz2`), and `plan_source` needs a value for "no catalog yet" |

A pallets F case in the spec's inference-input form, with every key of a real `eval/golden/datasets/F_dev.json` case
(32 keys, checked against `F__fastapi_13537`) plus `venv`; values from `golden_preview.json` and `split.json`, `t0` and
`pre_s` as the spec's F values, `plan` null until a catalog exists:

```json
{"eval_case_id": "F__click_a3321c9",
 "prompt": {"role": "user", "parts": [{"text": "<PR-style problem_statement, data/pallets/tasks_prstyle.jsonl>"}]},
 "reference": {"response": {"role": "model", "parts": [{"text": "<gold patch>"}]}},
 "golden": {"schema": "golden-case-v1", "suite": "F", "task": "click_a3321c9", "variant": "-", "split": "dev",
  "repo": "click", "stratum": "click/unrun", "runnable": true, "runnable_why": "", "gradable": true, "gradable_why": "",
  "fixture_sha": "<sha256 of this block without fixture_sha>", "t0": 47, "pre_s": 150,
  "plan": null, "plan_source": "catalog-missing", "plan_basis": "ast",
  "title_words": "apply Unix line endings for shell completion output for windows compat",
  "repro": null, "reproducible": false,
  "tree_patch": "", "tree_source": "", "replay": "", "replay_steps": [], "notes_changed": "",
  "gold_files": ["src/click/shell_completion.py"], "gold_new_files": [],
  "gold_functions": [{"file": "src/click/shell_completion.py", "name": "shell_complete", "qualname": "shell_complete"}],
  "test_files": ["tests/test_shell_completion.py"],
  "hidden_nodes": ["tests/test_shell_completion.py::test_source_uses_lf_line_endings"],
  "pre_hidden_nodes_pass": null, "known": [], "venv": "click"}}
```

The FILES line the golden plan would open with is already in the preview:
`FILES: src/click/shell_completion.py:45-51 (shell_complete)`.

Order of work when it is wanted: (1) catalog labels for dev tasks, (2) the `_g4_0src.pth` agent-env change plus a
parity test on one click task (the sandbox must import `/workspace/src/click`), (3) L and F suites on dev, (4) V after
the first pod run supplies wrong patches and repros.

## 9. Limits and open questions

- The venv versions are Kaggle's, so the verdicts describe a Kaggle-like environment with the repo importable. A pod
  run uses the pinned wheelhouse and `/root/buildenv`, and the pre-flight (7.3 step 1) is the check that it agrees.
- macOS vs Linux: every task that entered the set was run on Linux (344 tasks: 215 pallets-org + 129 sympy; the 17
  flask-wz2 rows re-run flask tasks) and the verdicts agree with the Mac on 342; the two differences are click_43c2e7f (valid on Linux only,
  kept) and sympy_37bde31 (flaky on the Mac, dropped as slow).
- Test flakiness: gold ran twice per task on each OS. One task flipped between its two gold runs (sympy_37bde31, gold2
  hit 180 s on the loaded Mac); none among the 307.
- sympy verdicts depend on which optional packages the grader exposes (sympy_dc25d66, section 4.5), and 54 sympy + 41
  werkzeug tasks need a test package that Kaggle's image lacks. A pod run ships the oracle's packages, so this does not
  affect pod measurements; it does mean those 95 tasks are less certain to resemble what the organisers could grade.
- Hidden-set representativeness is an inference, not a measurement: different repos, PR-style statements, recent PRs.
  Whether pallets tasks behave like the hidden ones is what the first pod run will tell (7.3).
- Not done: graphs/embeddings beyond dev40 (about 8 GB more for all 307 at dev40's 28 MB per task, estimate; per
  subset on demand), a pallets task catalog, the golden-eval wiring of section 8, any agent run.

## 10. Files

| path | what |
|---|---|
| `data/pallets/{tasks.jsonl,README.md}` | the dataset (CC0-1.0) |
| `data/pallets/tasks_prstyle.jsonl`, `pr_statements.json` | PR title + body statements (competition format) |
| `data/pallets/valid_ids.txt`, `task_env.json`, `split.json`, `dev_ids.txt`, `holdout_ids.txt` | the dev set |
| `data/pallets/oracle/results.jsonl` (Mac pass 2), `results_pass1.jsonl`, `results_era.jsonl` (flask-wz2), `results_era2.jsonl` (flask-2022, unused), `results_pytest.jsonl`, `results_sympy.jsonl` (Mac pass 1), `results_sympy_mac2.jsonl`, `results_sympy_kx.jsonl` (Kaggle optional packages), `results_sympy_rerun.jsonl` / `results_sympy_v2.jsonl` (single-task diagnostics), `linux/results_linux*.jsonl`, `summary.json` | oracle evidence |
| `data/pallets/oracle/stock_mac/` | the stock-sandbox check of 4.3 (8 tasks, gold + empty, `run.sh`) |
| `data/pallets/oracle/pod_probe{,_sympy,_dev40,_wz2,_stub}/` | pod emulation probes (section 7.2): `probe.log` table, `fix_*/task_results.jsonl`, test outputs |
| `data/pallets/profile.json` | section 5 statistics (regenerated 2026-09-30 with sympy) |
| `data/pallets/golden_preview.json` | computable golden-fixture fields for the 307 (section 8) |
| `data/pallets/kaggle_pkg_gaps.json` | the 95 tasks needing a test package Kaggle lacks (section 4.5) |
| `data/pallets/dev40_ids.txt` | the 40 tasks `pack.py --ids dev_ids.txt --limit 40` selects (dev40 probe, graph fetch) |
| `data/pallets/{snapshots,graphs,embeddings,wheels,pipeline,harness,harness_wz2}/`, `oracle/logs*/` | local only (`data/pallets/.gitignore`) |
| `scripts/pallets/fetch.py` | size-verified download (`--ids FILE` for subsets) |
| `scripts/pallets/build_envs.sh` | venvs in `~/.cache/g4/pallets/` |
| `scripts/pallets/source.py` | pallets as a source for `tests/v10_support/tasks.py` |
| `scripts/pallets/oracle.py` | gold x2 + empty oracle (`--venv`, `--logs`, `--out`) |
| `scripts/pallets/linux_oracle.sh` | the oracle in python:3.12-slim |
| `scripts/pallets/finalize.py` | valid ids, split, summary |
| `scripts/pallets/profile.py`, `pr_statements.py` | section 5 |
| `scripts/pallets/wheelhouse.py`, `pack.py` | pod/L4 layout |
| `scripts/pallets/run_eval_pallets.py`, `pod_probe.sh` | the pod fixes (src path, extras, wheelhouse, httpbin stub) and their free pod emulation (`PROBE_VENV`, `PROBE_RUNS`) |
| `scripts/pallets/golden_preview.py` | section 8 preview (reads `scripts/golden/fixture_lib.py`, writes only `data/pallets/golden_preview.json`) |

Reproduce (O=data/pallets/oracle):

```
scripts/pallets/build_envs.sh                                                   # venvs, network once
.venv/bin/python scripts/pallets/oracle.py --repos click flask werkzeug jinja2 markupsafe itsdangerous -j 4
.venv/bin/python scripts/pallets/oracle.py --ids <the 17 non-valid flask ids> --venv flask-wz2 --out $O/results_era.jsonl
.venv/bin/python scripts/pallets/oracle.py --repos pytest --out $O/results_pytest.jsonl
.venv/bin/python scripts/pallets/oracle.py --repos sympy --out $O/results_sympy.jsonl -j 4
.venv/bin/python scripts/pallets/oracle.py --ids <its 30 non-valid ids> --out $O/results_sympy_mac2.jsonl --logs $O/logs_sympy_mac2
scripts/pallets/linux_oracle.sh --repos click flask werkzeug jinja2 markupsafe itsdangerous -j 4   # + era and sympy runs
python3 scripts/pallets/finalize.py --results $O/results.jsonl $O/results_era.jsonl $O/results_pytest.jsonl \
  $O/results_sympy_mac2.jsonl $O/results_sympy.jsonl \
  --linux $O/linux/results_linux.jsonl $O/linux/results_linux_era.jsonl $O/linux/results_linux_sympy.jsonl
```

The last command, re-run 2026-09-30 03:58 IST on the recorded rows, rewrote `valid_ids.txt`, `slow_ids.txt`,
`task_env.json`, `split.json`, `dev_ids.txt`, `holdout_ids.txt` and `oracle/summary.json` byte for byte (the Mac file
order matters for one line of `summary.json`: `results_sympy_mac2.jsonl` before `results_sympy.jsonl`). Cost: about 10
min on the Mac at -j 4 for the 215 pallets-org tasks plus two 6-minute werkzeug hangs; sympy is the slow part (sum of
per-task wall time 116 min on Linux, about half an hour elapsed at -j 4, estimate).
