# Gap 1: the scorer's Docker sandbox, measured locally

Written 2026-09-28 (IST). Read-only. Nothing was submitted, pushed or started on Kaggle or RunPod, and no money was spent.
Everything ran in Docker Desktop on this Mac (server 29.1.3, 10-CPU VM, runc). An earlier attempt at this gap had
already built `swebench-sandbox` for amd64 and arm64. I re-ran a cached `docker build --platform linux/amd64` of
`data/raw/docker/Dockerfile.sandbox` with its two shims. It produced the same five layer digests and the same creation
time as `swebench-sandbox:latest`, so the image under test is exactly that Dockerfile. I pulled no new image.

Scripts, raw JSONL and logs are in
`/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/gap1_v3/` (below: `G1/`):
- `oracle.py`: harness Phase 2, with the agent replaced.
- `agent_probe.py`: the harness's Phase 1 setup, then probes through the real tools.
- Supporting scripts: `repro_demo.py`, `testdeps_probe.py`, `tool_latency.py`, `tmp_contrast.py`, `helper_calls2.py`,
  `tool_durations.py`, `analyze.py`, `probe_summary.py`.

Earlier partial attempts left data in `scratchpad/gap1/` and `scratchpad/gap1_opus/`. I used them only as a cross-check.
Every number below comes from a fresh run.

**Load caveat.** Other sessions shared this Mac.
- Host 1-minute load was about 8-11 during the gold oracle.
- It was 8-37 across the arm64 runs (agent probe, oracle, latency). The probe and the latency run also shared the
  Docker VM with the empty-oracle lane.
- It was 36-68 during the amd64 agent probe and the amd64 latency run.

Timing claims therefore use the gold pass and the arm64 runs. The amd64 probe is used for function only.

## 0. Answers

| Question | Answer | Evidence |
|---|---|---|
| Does the scorer run the Docker sandbox? | **Very likely, but not proven.** The host says so, the harness defaults to it, and the README describes container limits as part of scoring. Nothing points to subprocess. | Section 1 |
| Did sub3's `/tmp/swe` helpers work on the scorer? | **Yes, provided install ran in that task.** In Docker, `run_skill_script(install.py)` and `run_command("python3 /tmp/swe/...")` share the container's `/tmp`. v4's hard-coded `/tmp/swe` works in 11/11 tasks on both architectures. | Section 4 |
| Is race 1's `r_v4` the v4 that scored 0.12? | **No.** In r_v4, 21/51 tasks installed the helpers, and 35 of the 38 helper calls made after a successful install failed with "can't open file". Under Docker those calls would have run. `r_v9_c` differs from v4 only in the install path, so it is the pod's best stand-in for v4-as-scored: 15 vs 18, inside the ±3 noise. **The v9 path fix is worth about 0 on the LB.** | Section 4.3 |
| Pass 1: gold resolves the same set as on the pod | **FAIL.** Docker gold 40/59 against the pod's 44/59: 4 pass only on the pod, none only in Docker. On the 40 Kaggle-valid tasks: Docker 37, pod 39, Kaggle-env 40. All 4 differences are public-environment artefacts, explained in Section 3. | Section 3 |
| Pass 2: the empty patch fails on requests_6644 | **PASS, but gold fails too.** In the public Docker environment requests_6644 cannot be solved. Docker instead has free passes elsewhere: rich_3468 (Kaggle-valid), requests_7309, requests_7315 and requests_7427 resolve with an empty patch. | Section 3 |
| Pass 3: `/tmp/swe` is reachable from both run_command and run_skill_script | **PASS.** 11/11 tasks, amd64 and arm64, v4 and v9_eog, through the harness's own executor and tools. A toy repo gives the same result. | Section 4.1 |

The most important new finding was not in the brief. It is **the /tmp-repro trap** (Section 5):
- In Docker, the repo's own package is also installed in site-packages. The image bakes in rich 15.0.0 through typer,
  and the harness injects the public wheels, which include fastapi, requests, rich and httpx.
- Any Python started with a script outside `/workspace` imports that copy, not the agent's edit. This includes
  `python3 /tmp/repro.py`, which v9_eog's verifier prompt prescribes.
- For rich_3043 this makes a `/tmp` repro report FIXED before any edit.
- For requests_6644 the repro reports BUG after the gold patch. There, only `PYTHONPATH=/workspace/src` shows the truth.
- Pod runs cannot show this, because the subprocess sandbox exports `PYTHONPATH=<workspace>`.
- 13/51 r_v9_eog tasks ran `/tmp` repros, including 7 of its 21 solves.

## 1. Is the scorer Docker? The evidence

- **Host statement.** Forum 742882 [3529110], 2026-09-27 11:12 UTC: "The private Docker sandbox uses the same base image
  but installs a different set of dependencies" (`research/forum.md:46`). He also says gold validates at 100% on the
  scorer (742882 [3528750], `research/forum.md:47`).
- **Harness defaults.**
  - `swegemma/cli.py:55-58`: `--sandbox` defaults to `docker`.
  - `swegemma/config.py:98`: `sandbox: str = 'docker'  # 'docker' (default) or 'subprocess' (Kaggle/notebooks)`.
  - `HARNESS_README.md:247` calls Docker the default and `:254` says subprocess is "used in environments without a
    Docker daemon".
- **The README describes container limits as part of scoring.** `HARNESS_README.md:180`, in the 4xL4 scoring-hardware
  section: "Host Container Sandboxing (4 GiB RAM / 2 vCPUs per container)".
- **The Docker backend is engineered for a hosted scorer.**
  - `docker.py:25-28` falls back to pre-seeded images `gcr.io/kaggle-playground-170215/swebench-sandbox:v1|latest`.
  - `docker.py:67` handles a "dockerproxy".
  - `docker.py:387-388, 445, 491` work around gVisor (`runsc`) dentry caching and "/tmp tmpfs shadowing".
  - `container_setup.py:41-49` looks for `.../competition-data/secret/sandbox/setup.py`.
  - A local notebook needs none of this.
- **Dockerfile.public** (`data/raw/docker/Dockerfile.public:2,24`) says it "Extends Dockerfile.sandbox with offline
  public wheels cache ... (zero private wheels or internal code artifacts)". That implies a private twin
  (inference, UNVERIFIED).
- **Nothing contradicts it.** Forum 743752 asked Docker/gVisor vs subprocess and is still unanswered
  (`research/forum.md:96`).
- **UNVERIFIED consequences.**
  - The scorer probably runs gVisor, so per-exec overhead could exceed the runc numbers in Section 6.
  - `/tmp` may be a tmpfs there (`docker.py:387`), which would count against the 4 GiB limit.
  - I could not test either: this Mac has only `runc` (`docker info`: "Runtimes: io.containerd.runc.v2 runc").
- **Pods.** Our pods run `--sandbox subprocess` (`pod/run_eval.sh:24`). No report here shows a pod with a Docker daemon.
  The "pods have Docker" idea stays UNVERIFIED, and I did not touch a pod.

## 2. What differs between the two sandboxes (verified)

| | Docker (scorer, probably) | Subprocess (all our pod and Kaggle-notebook runs) | Evidence |
|---|---|---|---|
| Python / pytest | 3.13.15 / pytest 9.1.1 (unpinned, so it depends on build date), pytest-timeout 2.1.0 | pod 3.12.14 / pytest 9.1.1; Kaggle host pytest 8.4.2 | `docker run ... pip list`; `.venv`; `eval/kaggle/rescore_fair/pip_freeze.txt` |
| Command text | not rewritten; `/tmp` and `/workspace` are real | `/tmp`, `/workspace`, `/usr/local/bin`, `/wheels` rewritten in command text only | `subprocess.py:436-481`; `docker.py` has no rewrite |
| `TMPDIR` / `TEST_TMPDIR` / `PYTHONPATH` | unset / `/tmp` / **unset** | sandbox tmp / sandbox tmp / **`<workspace>`** | probe `env` (11/11 tasks); `docker.py:93`; `subprocess_sandbox.py:49-50`; `subprocess.py:488` |
| Repo install | `pip install -e /workspace`, then `workspace_paths.pth` listing `/workspace` and every top-level dir (incl. `src/`) | none (the harness returns early); our pods substitute `scripts/run_eval.py` | `container_setup.py:512-530`; `sandbox/setup.py:290-320` |
| Site-packages | image packages (typer, **rich 15.0.0**, **Pygments 2.21.0**, markdown-it-py, ...) plus **every public wheel under 20 MB**, deduped to the highest version, injected with no `RECORD` files: fastapi 0.141.1, requests 2.34.2, rich 15.0.0, httpx 0.28.1, starlette 1.6.0, ... | host site-packages via `_host_env.pth` (Kaggle: requests 2.32.4, rich 13.9.4, Pygments 2.20.0) | `container_setup.py:155-227, 318-343`; probe `site_pkgs` |
| CPUs seen / quota | `os.cpu_count()` = 10, `sched_getaffinity` = 10, but `cpu.max` = 200000/100000, i.e. 2 CPUs | host | probe `env` |
| Memory / network | 4 GiB / none; `pip install x` fails after 8.5 s (no hang) | host / host | `docker.py:86-89`; timed run |
| pytest in Container A | available by default; masked if `enable_sandbox_testing=False`, which the scorer may set (UNVERIFIED; default True) | never masked | `agent_runner.py:302-309`; `config.py:122`; `container_setup.py:968-1043`; `HARNESS_README.md:332` |
| Per-task containers | two (A agent, B verify), each stopped with `stop(timeout=2)` on a `sleep infinity` PID 1 that ignores SIGTERM, so 2.2 s each | none | `docker.py:673, 812`; `docker stop -t 2` timed at 2.17-2.19 s, `docker kill` 0.08 s |

## 3. Oracle over the full local population (59 snapshots, gold and empty)

**Method.**
- `G1/oracle.py` replaces `Evaluator._run_agent_sandbox` with a stub that returns the gold patch or `''`, as in
  `scripts/oracle.py`.
- It then runs the harness's own `evaluate_task`, which calls the real `verify_task`, in `--sandbox docker` with the
  image `swebench-sandbox:latest` (amd64 under emulation).
- Budgets were 180 s / 70 / 150 / 5 min. Runs were sequential, one lane.
- Outputs: `G1/oracle_gold_amd64.jsonl` and `G1/oracle_empty_amd64.jsonl`.
- References: the pod oracle `eval/runs/oracle_all/task_results.jsonl` (subprocess plus the editable install in
  `scripts/run_eval.py`) and the Kaggle-env oracle `eval/kaggle/oracle_all/results.jsonl` (official subprocess recipe on
  a Kaggle CPU kernel).

| Set | Docker gold | Pod gold | Kaggle-env gold | Docker empty resolved |
|---|---|---|---|---|
| 40 Kaggle-valid tasks with local snapshots | **37** | 39 | 40 | 1 (rich_3468) |
| All 59 local snapshots | **40** | 44 | 40 | 4 (rich_3468, requests_7309, requests_7315, requests_7427) |

The empty patch hangs to the 180 s pytest timeout on rich_3480, rich_3772 and rich_4006, the same three as
`research/test_plan.md:497`. The arm64 image gives exactly the same outcomes on the 11 probe tasks
(`G1/oracle_gold_arm64.jsonl`), so architecture does not change pass or fail.

Every difference has a mechanism, and every one is specific to the public environment:

| Task | Docker gold | Why | Check |
|---|---|---|---|
| requests_6644 (valid) | fail | src-layout package shadowed. Site-packages holds requests 2.34.2, which returns `'//v:h'`. pytest imports it, not `/workspace/src` (the import-origin probe shows S in all 7 entry points). The empty patch also fails, so the task **cannot be solved** here. On Kaggle it is a free pass, because the host's requests 2.32.4 is imported instead (`test_plan.md:102-107`). | `G1/repro_demo.out`; probe import origins |
| httpx_3672, requests_7205 (not valid) | fail | same shadowing: `module 'httpx' has no attribute 'Stream'` (site-packages 0.28.1, workspace 1.0.dev3); requests_7205 fails 4 parse tests | oracle `test_tail` |
| requests_7309 / 7315 / 7427 (not valid) | **pass, and empty passes too** | same shadowing in reverse: requests 2.34.2 already contains these fixes, so any patch "solves" them | empty oracle |
| rich_3468 (valid, in `data/arena_ids.txt` as never-solved) | pass, **empty passes too** | the hidden test spawns `python -m rich` as a subprocess. That child imports site-packages rich 15.0.0, which has the BrokenPipe fix, not `/workspace`. All 6 race-1 arms ended rich_3468 with an empty patch (5 of them without an agent error), so under Docker those 5 would have scored it (`evaluate.py:324` only skips verification when an error accompanies the empty patch). | empty oracle; `eval/race1/runs/*/task_results.jsonl` |
| rich_3472 (valid, arena) | fail (exit 2) | `ModuleNotFoundError: No module named 'attr'`. attrs is not in `data/raw/wheels`. | oracle `test_tail` |
| rich_3782 (valid, arena) | fail (6 test_syntax failures) | Pygments drift: the image bakes in unpinned Pygments 2.21.0. With 2.20.0 the same gold patch passes 25/25. The pod fails the same 6 tests (`eval/runs/oracle_all/test_outputs/rich_3782.log`; I did not check its Pygments version). Kaggle (2.20.0) passes. | `G1/p3782/run.sh`: "Pygments 2.21.0: 6 failed, 19 passed; Pygments 2.20.0: 25 passed" |

So the "free pass" of test_plan F10 is not specific to subprocess. It comes from whichever copy of the package shadows
the workspace, and each sandbox has its own free and impossible tasks. The host's "gold = 100%" on the private scorer
says the private environment avoids the impossible kind for hidden tasks. It says nothing about free passes.

**Consequence for evaluation.**
- Arena labels are sandbox-dependent for rich_3468, rich_3472 and rich_3782 (all in `data/arena_ids.txt`) and for
  requests_6644 (contested). Keep them out of paired comparisons, or report them separately.
- rich_3480, rich_3772 and rich_4006 each cost 180 s of verification for an empty or hanging patch in both sandboxes.

## 4. Helpers under Docker

### 4.1 Reachability (pass condition 3)

**Method.**
- `G1/agent_probe.py` replays `agent_runner.py:268-317` step by step: wheels, snapshot, git exclude, editable install,
  test deps, test config, baseline, tree.
- It then builds the harness's `SwegemmaContext.create_tools()` and runs skills through
  `_SkillScriptCodeExecutor(AdkSandboxCodeExecutor(context.sandbox))`. That is the path `run_skill_script` takes: the
  skill is written to `/workspace/.adk_exec_*.py`, runs as `python3`, and materialises into `tempfile.TemporaryDirectory()`
  (`adk_eval_core/sandbox/base.py:201-207`, `google/adk/tools/skill_toolset.py:627-658`).
- 11 tasks (`G1/ids_probe.txt`) × {arm64 `G1/probe_arm64.jsonl`, amd64 `G1/probe_amd64.jsonl`}.

| Probe | Result, both architectures |
|---|---|
| `python3 /tmp/swe/locate.py` before install | 0/11: "can't open file '/tmp/swe/locate.py'". Install is still required per task, because each task gets a fresh container. |
| v4 (= sub3) `install.py` via run_skill_script | 11/11 success; `/tmp/swe` holds `_ws.py check.py locate.py test.py` |
| v4 `locate.py` / `check.py --mode preflight` / `test.py --target` via run_command | 11/11 / 11/11 / 10/10 (requests_6644 has no pre-existing test file) |
| v9_eog `install.py`; `_ws.SWE`, `_ws.ws()` | 11/11; `/tmp/swe /workspace` (TMPDIR unset, so `TMPDIR or /tmp` resolves to `/tmp`) |
| v9_eog `locate` / `run` / `gate` | 11/11 each |

`G1/tmp_contrast_docker.out` repeats this on a toy repo with `ContainerManager.initialize()`: v4 and v9_eog both
install and run `locate.py` (exit 0). The subprocess contrast is already a repo test (`tests/test_sandbox_tmp_paths.py`),
and the traces in 4.3 confirm it at scale.

### 4.2 Python 3.13 and 2 vCPU

- `tests/test_helpers_v9.py` passes **6/6 in 7.3 s** under Python 3.13.15 / pytest 9.1.1. The run used the amd64 image
  with `--network none --cpus 2 --memory 4g` and read-only mounts (`docker run ... python3 -m pytest -p no:cacheprovider`).
- Every script in `submissions/v4`, `submissions/v9_eog` and `helpers_v9` compiles under `python3 -W error` with no
  warning.
- The helpers import only `os re sys subprocess shutil py_compile ast math collections`. None of these is removed in
  3.13, and none reads `os.cpu_count()`.

Helper time per call on the arm64 image (native, 2-CPU quota), against the pod's `r_v9_eog` trace medians
(`G1/tool_durations.py`):

| | Docker arm64, 2 vCPU (median) | pod r_v9_eog (median, p90) |
|---|---|---|
| install via run_skill_script | 0.38 s | 0.05 s |
| locate.py | 0.80 s | 1.09 / 1.42 s |
| run.py (echo) | 0.09 s | 0.07 / 0.12 s |
| gate.py on the gold patch | 1.53 s (max 31.4 s, httpx) | 1.50 / 2.80 s |
| test.py / `python -m pytest` on the target file | 0.40 / 0.39 s | pytest 0.52 / 0.81 s |

At 2 native vCPUs the helpers cost what they cost on the pod: these suites are single-threaded pytest. Timeouts sized on
the pod hold. The emulated amd64 run was 3-4× slower, and under load 36-68 up to 56 s for the httpx gate. Emulation and
host load explain that; it is not a property of the scorer.

### 4.3 How much sub3 differs from r_v4

Counted with `G1/helper_calls2.py` over the traces. A call counts as "after install" when a successful
`run_skill_script(install.py)` came earlier in the same task.

| Run (sandbox) | tasks with install OK | helper calls after install / of which "can't open file" | calls with no prior install / failing |
|---|---|---|---|
| race1 `r_v4` (pod, subprocess) | 21/51 | 38 / **35** | 57 / 50 (the other 7 were malformed commands) |
| `eval3 p_v4` (pod) | 29/74 | 77 / 67 | 84 / 73 |
| Kaggle L4 `e74_v3` (notebook, subprocess) | 36/74 | 94 / 87 | 49 / 46 |
| race1 `r_v9_c` (pod) | 22/51 | 59 / **0** | 47 / 42 |
| race1 `r_v9_eog` (pod) | 27/51 | 309 / 0 | 81 / 70 |

- Under Docker, 35 of r_v4's 38 "after install" calls would have run; the other 3 were malformed
  (`run_command: python3 ...`). The "no prior install" calls would still fail.
- So sub3 on the scorer behaved like r_v9_c, not like r_v4. The model's habit of skipping or botching the install (for
  example `skill_name: "\"swe-tools\""`) is sandbox-independent: about half the tasks never had working helpers in
  either sandbox. That is the bigger lever (see `research/competitors.md` §7.2).

## 5. The /tmp-repro trap (new; Docker only)

**Mechanism.** In Docker, `PYTHONPATH` is unset. The `.pth` entries that add `/workspace` and `/workspace/src` come
after site-packages on `sys.path`. Site-packages already holds a copy of the repo's package, from the image or from the
injected wheels. So the workspace wins only when something puts it first:
- `python3 -c` with cwd `/workspace` (sys.path[0] = '');
- a script located in `/workspace`;
- pytest's rootdir-conftest insertion, where the harness's `conftest.py` sits at the repo root.

For a src-layout repo, nothing puts `/workspace/src` first.

Import origin of the repo package from 7 entry points, 11 tasks, both architectures (`G1/probe_*.jsonl`,
`probe_summary.py`). W = /workspace, S = site-packages:

| Repo layout | `python3 -c` in /workspace | `python3 -c` in / | `python3 /tmp/x.py` | `python3 x.py` in /workspace | `python3 -m pytest` / `pytest` / verifier command |
|---|---|---|---|---|---|
| flat (9 rich tasks) | W | **S** | **S** | W | W / W / W |
| src (requests_6644, httpx_3672) | **S** | **S** | **S** | **S** | **S / S / S** |

Behavioural demo (`G1/repro_demo.py`, `G1/repro_demo.out`), with the issue's own check as `/tmp/repro.py`:

| Task | State | `python3 /tmp/repro.py` | `python3 -c` (cwd /workspace) | with `PYTHONPATH` = workspace |
|---|---|---|---|---|
| rich_3043 (flat) | baseline, bug present | **FIXED** (imports site-packages rich 15.0.0) | BUG | BUG |
| rich_3043 | gold applied | FIXED | FIXED | FIXED |
| requests_6644 (src) | baseline | BUG | BUG | BUG |
| requests_6644 | gold applied | **BUG** (imports site-packages requests 2.34.2) | **BUG** | FIXED (`PYTHONPATH=/workspace/src:/workspace`) |

**Who walks into it.**
- `submissions/v9_eog/prompts/verifier.md:14` says "`cat > /tmp/repro.py <<'EOF'` ... `python3 /tmp/repro.py`; if it
  still shows the bug, fix it".
- v4 and v9's `fixer.md:9` says "Scratch files go in /tmp".
- `check.py` says "move it to /tmp".
- `gate.py` prints "Write a repro in /tmp instead", and on rich_3043 in Docker it said exactly that
  (`G1/probe_arm64.jsonl`).

**How often it would have mattered** (race 1 traces, run_command with `python3 /tmp/<not swe>/*.py`):
- r_v9_eog: 13/51 tasks, 7 of its 21 solves.
- r_v9_eg: 14/51 tasks, 6 of its 16 solves.
- r_v4: 3/51; r_v9_c: 0/51.

All of these are rich or fastapi tasks, and both packages are installed in site-packages in public Docker. On the pod
every such repro imported the workspace. **Part of v9_eog's pod lead rests on repros that the scorer would have answered
from the wrong copy.** Whether that biases up or down cannot be measured without a Docker lane, but the pod ranking of
repro-heavy arms is not trustworthy.

A second symptom is **gate.py's asymmetric environment**. The tested bundle copy is
`submissions/v9_eog/skills/swe-tools/scripts/gate.py:38-43`.
- ORIGINAL runs with `PYTHONPATH=<base>/src:<base>`; YOUR VERSION inherits the harness environment.
- `helpers_v9/gate.py` was edited at 13:21 IST today by another session. It still has the same asymmetry (`:43-48`) and
  the "/tmp" advice (`:28`). How its new BROKEN status labels the httpx case is UNVERIFIED.
- On httpx_3672 (src layout) with the correct gold patch, gate reported "YOUR VERSION: 1 error / ORIGINAL: 35 passed /
  GATE: FAIL". A gate-following agent would have undone a correct fix.
- For flat layouts, both sides import their own tree, and the gate matched on 10/10.

For hidden repos this is UNVERIFIED but likely. The public wheelhouse contains the public repos' own packages (fastapi,
requests, rich, httpx, starlette), so the private "different set of dependencies" probably contains hidden repos'
packages too.

## 6. Timing under Docker

Per-task harness overhead outside the agent cap, measured with the harness's own functions. The arm64 figures are
native (host load 8-37, see the caveat at the top); the amd64 figures run under emulation.

| Component | arm64 native | amd64 emulated (gold pass) | Subprocess, as assumed so far |
|---|---|---|---|
| Container A setup (start to tree) | median 9.6 s (3.6-16.4) | not usable (probe ran at load 36-68) | 3.6 s mean (`research/time_model.md:18,54`, TM2) |
| Container A stop | 2.5 s | 2.4 s | ~0 |
| Container B, all-in (start, setup, 2 × test deps, patches, pytest, stop) | median 15.6 s: fast tasks 13-15.5, slow 29-33 | median 25.6: fast 16.8 (n=35), slow 35.9 (n=24) | verification 3.7 s median (`time_model.md:18`); pod oracle 9.2 s mean |
| of which pytest | 0.71 s median | 1.06 s median (max 10.8) | |
| **Total per task, outside the cap** | **~28 s median (fast ~21 s, slow ~46 s)** | | ~7.3 s |

Notes on the table:
- **The slow mode is a harness bug and costs wall clock, not CPU.** On 24 of 59 tasks, `sandbox/setup.py` re-runs
  `pip install -e` (`setup.py:193-213, 352-353`).
  - pip then meets the injected copy of the repo's own package, which was written with no `RECORD`
    (`container_setup.py:266`), and fails with "Cannot uninstall rich 15.0.0 ... no RECORD file".
  - The fallback `pip install --no-deps -e` then builds in isolation and retries PyPI under `network_mode=none`. That
    takes about 8.5-9 s per call.
  - Confirmed on rich_3052, requests_6589 and rich_3953 (`G1/testdeps_probe_3052.json`, `G1/testdeps_probe_more.json`).
  - `setup.py` runs once in Container A and twice in B (`verification.py:287, 466`), so affected tasks lose about 27 s.
  - Which tasks are affected is deterministic: the same 5 of 11 on both architectures.
  - It will hit any hidden repo whose own package is also a private wheel (UNVERIFIED).
- **Stops cost 2.2-2.5 s each by construction.** Two per task, about 9 min per 120 tasks. This does not apply if the
  scorer pools containers (`reuse_containers`, `docker.py:776-802`), which is UNVERIFIED.
- **Tool latency is paid inside the agent cap** (`G1/tool_latency.jsonl`, toy repo, real tools, arm64 native):

  | | Docker | Subprocess |
  |---|---|---|
  | run_command | 0.087 s | 0.010 s |
  | run_command (python -c) | 0.139 s | 0.028 s |
  | read_file | 0.076 s | 0.001 s |
  | edit_file | 0.332 s | 0.002 s |
  | submit_patch | 0.137 s | 0.052 s |

  - At r_v9_eog's mix (28 run_command, 9.9 read_file, 9.3 edit or write, 1 submit per task) that is **about 6 s per
    task** of the 300 s.
  - amd64 under load was about 2× these numbers (run_command 0.17 s, edit_file 0.67 s).
  - gVisor would add more (UNVERIFIED).
- **Relation to the 12 h.** sub3's observed 10.4 h already contains this overhead, whatever the scorer's value is. What
  changes is the model:
  - TM2's 3.6 s setup plus 3.7 s verify understates Docker by about 3-6×.
  - `research/gap_5.md:94-95` quotes this gap's earlier attempt as "Mac arm64 Docker, 9 gold tasks, ~10 s per task".
    That attempt ran the **amd64 image under emulation** (`swebench-sandbox:arm64` was built at 22:14:53 UTC, after its
    22:08 UTC gold run) and timed **Container B only**. The per-task figure is about 28 s once Container A and both
    stops are counted.
  - Hidden-repo figures on the scorer's x86 plus gVisor remain UNVERIFIED.

## 7. The brief's points (a)-(e), checked

- **(a) Confirmed.** Mechanism in 4.1 and counts in 4.3. r_v4 is not sub3; r_v9_c is the closest pod proxy for sub3.
  The path fix alone should move the LB by about 0.
- **(b) Partly right.**
  - "Repo not pip-installed" is a subprocess artefact: Docker editable-installs it (`container_setup.py:514-517`,
    probe `site_pkgs`).
  - "src-layout not importable" is wrong in the other direction. In Docker it is importable but **shadowed** whenever
    site-packages has a copy, and the verifier sees the shadow too (Section 5).
  - test_plan F10's free pass is not subprocess-only. Docker has its own free passes (Section 3), and requests_6644 is
    unsolvable there instead.
- **(c) Confirmed, and it matters less than feared.** Native 2 vCPU with Python 3.13 matches the pod for helper and
  pytest timings (4.2). The real Docker-only costs are fixed overhead and tool latency (Section 6).
- **(d) Confirmed and quantified:** ~28 s median per task outside the cap, against the 7.3 s assumed. There is a 24/59
  pip-retry tail of +27 s.
- **(e) Confirmed.**
  - The verifier's exact reset command (`verification.py:392-415`) returns `rc=1` with "pathspec 'sitecustomize.py' did
    not match", and a tampered test file survives on **10/10** tasks with an existing test file, on both architectures.
  - Checking out the single file alone works.
  - The stubs live in site-packages (`docker.py:784-789`), never in HEAD.

## 8. Consequences for v10 (concrete)

1. **Put the workspace first for every run of repo code that we control.**
   - What to set: `PYTHONPATH=<ws>/src:<ws>`, where `src/` exists, prepended to any existing value.
   - Where: `run.py`, the repro helper, and the "current" side of `gate.py`/`verify.py`, the same way `gate.py` already
     treats ORIGINAL.
   - Why: this makes both sandboxes agree, and it removes the false GATE FAIL (httpx_3672) and the FIXED-before-edit
     repro (rich_3043).
   - `docs/v10/design_A.md:603` currently says "the current uses cwd=ws() and the inherited PYTHONPATH". In Docker that
     inherited value is empty, so the design must change there. `docs/v10/design_B.md:52,506` already does the right
     thing.
2. **Print the import origin** in the repro and gate output (`design_A` R-A50). When the origin is site-packages, say
   so: "the grader will also test that copy". For src-layout, a shadowed package means the grader tests the wheel, so
   no edit can change the result.
3. **Rewrite the prompt lines that point repros at `/tmp`.**
   - Affected: `verifier.md:14`, `fixer.md:9` "Scratch files go in /tmp", and gate's "Write a repro in /tmp instead".
   - Replacement: a helper call, or `cd /workspace && PYTHONPATH=... python3 /tmp/repro.py`.
   - Scratch files can stay in `/tmp`; only the interpreter's path must change.
4. **Keep `$TEST_TMPDIR > $TMPDIR > /tmp` for the helper dir** (design_A 4.1). In Docker, `TEST_TMPDIR=/tmp` and
   `TMPDIR` is unset (probe `env`), so it gives `/tmp/swe` in both sandboxes. v9's `TMPDIR or /tmp` is also correct on
   today's image.
5. **Never size parallelism from `os.cpu_count()`.** It reports 10 inside a 2-CPU quota. Read
   `/sys/fs/cgroup/cpu.max` or hard-cap at 2, as design_A's "at most 2 processes" already does.
6. **Budget tool calls with Docker latency:** roughly 0.09 s per run_command and 0.33 s per edit_file natively. A
   helper that folds 3 calls into 1 saves about 0.2-0.7 s per fold. This is small; do not trade correctness for it.
7. **Assume pytest may be masked** (`enable_sandbox_testing=False`; `container_setup.py:968-1043`).
   - Masking overwrites `/usr/local/bin/pytest` and `pytest/__main__.py`. `python3 -c "import pytest; pytest.main()"`
     would bypass it; design_A rightly refuses to (R-A46).
   - The repro path must still work when pytest is masked.
8. **Evaluation lane.**
   - Pod subprocess runs cannot see Sections 3 and 5. For any arm whose prompts use repros or gate, add a
     Docker-faithful check before trusting its pod rank.
   - Cheapest option: the pod serves vLLM, and `swegemma eval --sandbox docker` runs on this Mac against it through an
     SSH tunnel.
     - Use arm64-native `swebench-sandbox:arm64` for rich and requests.
     - fastapi needs x86 `pydantic_core` from `data/raw/wheels`, so run it on the amd64 image under emulation.
     - Feasibility is UNVERIFIED: I did not open a tunnel or start a pod.
   - At minimum, rerun `G1/oracle.py` whenever the image or wheels change, and drop env-dependent tasks from paired
     tests: rich_3468, rich_3472, rich_3782, requests_6644.
9. **Do not let the model run `pip install`.** It fails in about 8.5 s under Docker (no hang), and nothing it installs
   reaches Container B.

## 9. Open questions (UNVERIFIED)

- Whether the scorer uses gVisor, a tmpfs `/tmp` or container pooling. Each would change the Section 6 overheads.
  Needs the host's answer on 743752.
- The scorer image's build date. Unpinned pytest and typer (hence rich and Pygments) change with it; rich_3782 shows
  one Pygments minor version flipping a gold patch.
- Which hidden-repo packages are in the private wheel set. That decides how often the /tmp-repro trap, the gate
  asymmetry and the pip-retry tail fire on the scorer.
- The scorer's `enable_sandbox_testing` value.
- The sign of Section 5's effect on v9_eog's LB score relative to its pod score.

## 10. Reproduce

All commands run from `G1/` with `PY=/Users/carson/Projects/gemma-swe-agent/.venv/bin/python`.
- Full oracle (about 60 min at load 10): `./run_oracle_all.sh`. It runs `oracle.py gold|empty` over the 40 valid tasks,
  then the 19 others.
- Analysis: `python3 analyze.py oracle_gold_amd64.jsonl oracle_empty_amd64.jsonl`.
- Agent phase: `GAP1_IMAGE=swebench-sandbox:arm64 $PY agent_probe.py probe_arm64.jsonl $(cat ids_probe.txt)`, then
  `python3 probe_summary.py probe_arm64.jsonl`.
- Trap demo: `$PY repro_demo.py`. Pip tail: `$PY testdeps_probe.py rich_3052`. Latency: `$PY tool_latency.py docker|subprocess`.
- Pygments check: `docker run --rm --platform linux/arm64 --network none -v .../rich_3782.tgz:/s.tgz:ro -v $PWD/p3782:/p:ro -v .../data/raw/wheels:/w:ro swebench-sandbox:arm64 bash /p/run.sh`.
- Trace counts: `python3 helper_calls2.py <run_dir>...` and `python3 tool_durations.py <run_dir>...` from `eval/`.
- Housekeeping:
  - Every container my scripts started was removed (`docker ps -a` shows none).
  - The temporary tag `swebench-sandbox:gap1v3-amd64` was deleted.
  - Six idle containers from the earlier attempts at this gap are still up: `sleep infinity`, created 2026-09-27
    22:15-22:44 UTC, about 20 MiB each. I left them because I did not start them. Remove them with
    `docker rm -f 253633af3725 71c0e9745378 b83b6183841d c35042beb4d1 011777e8dce7 80db26518349`.
