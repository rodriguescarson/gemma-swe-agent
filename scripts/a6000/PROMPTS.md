A6000 PROMPTS (paste into Claude Code on the friend's PC, inside WSL Ubuntu)
=========================================================================

Run them in order. Each one is self-contained: Claude on that machine has no memory of our work.
Before P0: the friend has run setup_wsl.sh (FRIEND_SETUP.md), `nvidia-smi` in Ubuntu shows the RTX A6000,
and Claude Code is installed in WSL (`curl -fsSL https://claude.ai/install.sh | bash`, then `claude`).

Credentials you will need ON THAT MACHINE (create short-lived ones, delete them afterwards):
- GitHub: a fine-grained token with read+write on rodriguescarson/gemma-swe-agent only (or `gh auth login`).
- Kaggle: an API token (kaggle.json) to download the competition data, wheelhouse and model.
- Hugging Face (only if Kaggle's model download fails): a read token with the Gemma licence accepted.
Paste them only into the terminal prompts the tools ask for, never into a Claude message.


-------------------------------------------------------------------------
P0. BOOTSTRAP (once, ~1-2 h, mostly downloads)
-------------------------------------------------------------------------
You are on a Windows PC inside WSL2 Ubuntu 24.04 with one NVIDIA RTX A6000 (48 GB), 192 GB RAM and ~1 TB free
disk. It belongs to a friend: work only inside ~/g4 and Docker, never touch anything else, and never store
passwords or tokens in files except where a tool requires it (~/.kaggle/kaggle.json, chmod 600).

Goal: make this box a faithful evaluator for our Kaggle "Google - The Gemma 4 Developer Agent Competition" entry.

1. Check: `nvidia-smi` (A6000 visible), `df -h ~`, `free -g`, `docker run --rm hello-world`. Stop and report if
   any fails.
2. Clone git@github.com:rodriguescarson/gemma-swe-agent.git (or HTTPS with the token I give you) into
   ~/g4/gemma-swe-agent, branch wip/gemma-agent. Never commit to main; never use --no-verify.
3. Read, in this order: docs/GAPS_2026-10-06.md (all current decisions), docs/v4h/GATE.md (last 200 lines),
   scripts/make_eval_kernel.py (how the Kaggle notebook installs the wheelhouse and starts vLLM via
   adk_submission.VllmServer), data/heldout1k/README.md, scripts/pallets/or_race.sh (header).
4. Install the Kaggle CLI (`pipx install kaggle` or a venv), put my kaggle.json in ~/.kaggle (chmod 600), then
   download into ~/g4/data:
   - the competition data: `kaggle competitions download gemma-4-developer-agent` (public tasks, snapshots,
     graphs; about 22 GB), unzipped to where the repo's scripts expect it (find the expected path in
     scripts/ and data/, do not guess);
   - the wheelhouse dataset metric/gemma-4-developer-agent-wheelhouse (exact Kaggle build of vLLM 0.19.1,
     transformers, google-adk, adk_submission, swegemma);
   - the model google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2 from Kaggle Models (int4 W4A16, ~23 GB).
   Verify every download by size and sha256 against what Kaggle reports. A truncated file must fail loudly.
5. Create a Python 3.12 venv ~/g4/venv and install the WHEELHOUSE exactly the way make_eval_kernel.py's install
   cell does (same files, same order). Do not pip-install vllm from PyPI.
6. Write scripts/a6000/serve.sh (test-first: a pytest that checks its DRY_RUN output) that starts vLLM through
   adk_submission's VllmConfig/VllmServer with the kernel's settings, except tensor_parallel_size=1 (one GPU
   instead of Kaggle's 4xL4). Record that deviation in docs/a6000/DEVIATIONS.md. Start it, wait for /v1/models,
   send one chat request with a tool call, print tokens/s for a 1k-token reply.
7. Commit (tests first, small commits) and push the branch. Report: GPU, versions, model sha, tokens/s, and
   anything that differs from the Kaggle notebook.


-------------------------------------------------------------------------
P1. SMOKE + SPEED CALIBRATION (~30 min)
-------------------------------------------------------------------------
Repo ~/g4/gemma-swe-agent, branch wip/gemma-agent; vLLM from scripts/a6000/serve.sh. Read docs/GAPS_2026-10-06.md.

Goal: prove the box runs our agent bundles end to end with the competition harness (swegemma) and measure speed
against Kaggle's 4xL4.

1. Run submissions/v5h2 on 5 public tasks (first 5 ids of data/kaggle_valid_ids.txt) with the harness's
   SUBPROCESS sandbox (the same backend Kaggle scoring uses, so the /tmp-rewrite behaviour matches), budgets from
   the bundle's eval_config.yaml, model at the local vLLM URL. Find the exact eval command in
   scripts/make_eval_kernel.py's run cell and mirror it; do not invent flags.
2. Run scripts/analyze_helper_reachability.py on the results: 0 tasks may hit "can't open file".
3. Compare per-task seconds and tokens/s with the same 5 tasks in eval/kaggle/g4-l4-v4h2g-p312/results.jsonl.
   Write the A6000/L4 speed ratio to docs/a6000/DEVIATIONS.md. If the A6000 is faster, add a pacing option so
   the 5-minute cap means the same amount of model work as on L4 (look at how scripts/or_proxy.py --l4-pace does
   it for OpenRouter) and test it.
4. Commit and push. Report the ratio, solved count, and any harness differences.


-------------------------------------------------------------------------
P2. RANK THE CANDIDATES OFF-REPO (overnight, free)
-------------------------------------------------------------------------
Repo ~/g4/gemma-swe-agent; vLLM running; P1 done. Read docs/GAPS_2026-10-06.md and docs/v4h/GATE.md (end).

Goal: rank v5h2, v6p and v6p-think (and v4h2 as the reference) on the 200-task off-repo sample before they use
scarce Kaggle runs. Discipline: write the pre-registration in docs/v4h/GATE.md BEFORE running (arms, task set,
reading rule), one sample per task per arm unless time allows two, same server and settings for every arm, paired
comparison with a sign test, Wilson 95% CIs.

1. Task set: data/heldout1k/harness_s200 with data/heldout1k/s200_valid_ids.txt (gold-verified; README explains).
2. Arms: v4h2, v5h2, v6p, v6p-think (submissions/<name>). Interleave arms per task so time-of-run effects cancel.
3. Concurrency: whatever keeps the A6000 near full use without starving tasks (measure; start at 4 parallel
   tasks). Faithful budgets (eval_config.yaml) and the P1 pacing.
4. Gates per arm: scripts/analyze_helper_reachability.py (<= 1 task with can't-open), median task secs, cap hits,
   loop counts (identical call >= 5 in a row). For v6p-think check no task fails from thinking settings.
5. Write results to GATE.md against the pre-registered rule, commit, push, and print a table: arm, solved/200,
   CI, paired wins/losses vs v4h2 and vs v5h2, median secs, cap hits.


-------------------------------------------------------------------------
P3. LoRA DATA: SELF-GENERATED SFT + PREFERENCE PAIRS (1-2 nights, free)
-------------------------------------------------------------------------
Repo ~/g4/gemma-swe-agent; vLLM running. Read docs/GAPS_2026-10-06.md decision S2, docs/v11/PLAN.md,
train/build_sft.py, train/rebalance_rows.py, train/validate_rows.py, train/adaption_train.py, and
scripts/or_proxy.py (its --capture mode records the exact request/reply of every model call).

Goal: build training data for the next adapter from Gemma's own verified attempts on the held-out tasks.

1. Use the best bundle from P2. Capture every model call exactly as or_proxy --capture does (write an equivalent
   capturing proxy in front of the local vLLM if needed, test-first).
2. Run it 4 times per task on data/heldout1k/harness_all (1,044 valid tasks: data/heldout1k/all_valid_ids.txt),
   excluding the 200 sample ids (they stay held out for evaluation). Different seeds/temperatures per pass.
3. SFT rows: only test-verified successes, through train/build_sft.py, then rebalance_rows.py with its repeat and
   per-task caps, then validate_rows.py. Report rows, distinct tasks, tool mix.
4. Preference pairs: for tasks with both a solved and a failed attempt, build (chosen, rejected) pairs at the
   first diverging call, in the format Adaption's SDK expects for training_method "alignment" (check the
   installed adaption package for the exact schema; do not guess). Report pair count.
5. Never include data from closed models. Weights and large data stay out of git; commit scripts, tests and a
   data report only. Push.


-------------------------------------------------------------------------
P4. FAITHFUL PUBLIC-74 CHECK OF A CANDIDATE (~4 h per bundle)
-------------------------------------------------------------------------
Repo ~/g4/gemma-swe-agent; vLLM running; P1 pacing on.

Goal: a near-Kaggle run of one bundle on the 74 public tasks, judged by the keep rule before it spends a Kaggle
run. Bundle: <NAME>.

1. Run <NAME> on all ids in data/kaggle_valid_ids.txt exactly as in P1 (subprocess sandbox, eval_config budgets,
   pacing), sequentially like the scorer.
2. Judge with scripts/keep_rule.py against eval/kaggle/g4-l4-v4h2g-p312/results.jsonl (keep = solved >= 37 AND
   paired wins - losses >= +3). Also run analyze_helper_reachability.py.
3. Record in GATE.md as an A6000 screen (not a Kaggle result), commit, push, report.


-------------------------------------------------------------------------
ALWAYS (append to any prompt if needed)
-------------------------------------------------------------------------
- Tests first for every script change; small commits on wip/gemma-agent; push when done.
- Pre-register before any comparison; report numbers with the command that produced them.
- Keep the GPU busy or stop vLLM: never leave it idle for hours. Stop it when a prompt's work ends.
- Watch disk (`df -h ~`): stop at 100 GB free; clean only what you created.
- Nothing outside ~/g4 and Docker. No tokens in git, logs or messages.


-------------------------------------------------------------------------
P5. FAILURE FORENSICS: what is failing and why (CPU only, run while stage 1b continues)
-------------------------------------------------------------------------
Repo ~/g4/gemma-swe-agent, branch wip/gemma-agent. Do not stop, pause or restart any running step, proxy, vLLM
or the supervisor; this is read-only analysis of files on disk plus unit tests. Use no GPU.

Carson suspects that part of the failure rate is OUR bugs (helper scripts erroring, prompts naming tools or flags
that do not exist, outdated SKILL.md, harness rejections) rather than model behaviour. Settle that with evidence
from the stored traces, one mechanism at a time, with counts and task ids. Stage 1a traces are under
~/g4/runs/p2/items/<arm>/<task>/traces/ (arms v4h2, v6p, v6p-think), P4 (v5h2, public 74) under ~/g4/runs/p4/,
probes under ~/g4/runs/p2/probe_*; results.jsonl next to each. Read docs/v4h/GATE.md "P2 addendum 10" first (the
locator budget finding) so you do not redo it.

1. TOOL AND HELPER ERRORS. For every tool call in every trace, classify its observation: ok | helper traceback
   (which helper: install.py, locate.py, view.py, edit.py, test.py, check.py, repro.py, select_best.py,
   repo_map.py) | usage/argument error from a helper ("usage:", "unrecognized arguments", "error: the following
   arguments") | "can't open file" | harness rejection (unknown tool name, schema/argument validation, "Function
   ... not found", file_path given as a list) | command timeout | sandbox execution error | empty output | other.
   Table per arm: mechanism, calls, tasks affected, example task + the exact call and the first 300 chars of the
   reply. Every helper traceback or usage error is a bug of ours: list each distinct one with the helper, the
   line, and the prompt line that led the model to call it that way.
2. PROMPT vs REALITY. For each bundle that ran (v4h2, v5h2, v6p, v6p-think, v6p-b): extract every helper
   invocation shown in prompts/*.md and skills/swe-tools/SKILL.md, and RUN each one (with placeholder args) against
   the bundle's own scripts in a scratch git repo: does it parse, do the flags exist, does the output match what
   the prompt tells the model to expect (e.g. "REPRO PASS", "ALREADY SHOWN", the locate.py result format)?
   List every mismatch. Also: tools named in a prompt that the stage's yaml does not declare, and tools declared
   but never used.
3. LOOPS. For every task with an identical call repeated >= 5 times in a row: the stage, the exact call, what the
   tool returned each time (identical? an error? truncated? our "repeat" message?), and what the model's text said
   between calls if anything. Group by what the tool returned: if a loop follows a helper error or an empty/
   truncated reply, that is ours to fix; if the reply was a normal, useful result repeated, that is model behaviour.
4. EMPTY PATCHES. For every empty-patch task: which stage ended the task (budget exhausted at which stage, cap hit,
   verifier never ran, selector found all candidates empty, fixers never produced a diff, edit.py refused the
   edit, git diff empty because edits went to a test file and were reverted). Counts per cause per arm.
5. v6p PIPELINE CHECK. For each v6p task: did the locator write /tmp/repro.py, did it FAIL on the unedited code as
   required, did each fixer create its /tmp/wK copy, how many of the three diffs were non-empty, what did
   select_best.py print, did it apply a diff to /workspace, did the verifier call submit_patch. Count every step;
   name the first step that is broken most often.
6. THE L4 LOSSES. For the public tasks v4h2g solved on Kaggle L4 (eval/kaggle/g4-l4-v4h2g-p312/results.jsonl) and
   v5h2 did not in P4: per task, where the two trajectories diverge (first differing tool call) and why (view.py
   instead of read_file, temperature, a helper error, a cap). Same for the stage 1a tasks v4h2 solved and v6p did not.
7. ENVIRONMENT. Report the exact versions in play (python in the sandbox, pytest, vllm, transformers, google-adk,
   adk_submission, swegemma) against the Kaggle wheelhouse pins, and every place DEVIATIONS.md says the A6000
   differs from the Kaggle notebook. Then run the FULL repo test suite (PYTHONDONTWRITEBYTECODE=1 venv/bin/python
   -m pytest -q tests) to the end and list every failure with its first assertion line; it was killed earlier to
   launch sooner, so it has not passed on this box.
8. OUTPUT. Write docs/a6000/FAILURE_FORENSICS.md: one ranked table (mechanism, tasks affected per arm, ours vs
   harness vs model, example task, proposed fix, confidence), then the detail per section above. Fix nothing in
   the bundles yet. Commit the doc and any analysis scripts (tests first for scripts), push to wip/gemma-agent,
   and end with the top 5 findings in plain words: what is failing most, why, and whether it is our code.


-------------------------------------------------------------------------
P6. SWITCH TO v7 (Carson 2026-10-07: no more compute on the old bundles)
-------------------------------------------------------------------------
Repo ~/g4/gemma-swe-agent, branch wip/gemma-agent. Carson's decision: stop spending GPU on v4h2 / v6p / v6p-b and
run only the fixed bundle submissions/v7 (v5h2 plus the fixes for every "ours" finding in
docs/a6000/FAILURE_FORENSICS.md; scope and pass rule in docs/GAPS_2026-10-06.md, last section). Keep the supervisor,
the guard, the hourly health lines, the backups and the 36 h hard stop exactly as they are.

1. STOP stage 1b now, cleanly: let in-flight items finish, write the partial stage 1b table to GATE.md (per arm:
   items, solved, empty, budget-exhausted, loops; v6p-b's ledger counts), labelled PARTIAL, then free the GPU.
   Nothing else of v4h2/v6p/v6p-b runs again.
2. WAIT for v7: `git pull --rebase --autostash origin wip/gemma-agent` every 10 minutes until submissions/v7 and
   tests/test_v7_bundle.py exist. Then run ONLY v7's tests plus the sandbox tests
   (PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m pytest -q tests/test_v7_*.py tests/test_setup_stage.py) and the
   compile check (scripts/validate.py submissions/v7). If anything fails, stop and append the failure to
   docs/a6000/P2_LOG.md; do not patch v7 yourself (the Mac side owns it).
3. PRE-REGISTER in GATE.md (same server, same C = 2 and per-arm pacing rule; derive v7's scale from a 4-item probe
   like addendum 4), then run, in this order, each judged by the forensics counters on its traces (view.py
   usage-line calls, literal-wrapper commands, write_file path refusals, forced-install `{}` calls, locate/view cap
   refusals, loops >= 5, budget-exhausted tasks, helper reachability):
   a. v7 on the 50 stage-1a ids, 1 sample, paired against the existing v4h2 stage-1a rows (same ids, same box;
      note the different day as a confound). Reading: wins - losses, sign test, Wilson CI.
   b. v7 on the public 74 (as P4: sequential, pacing on), judged by scripts/keep_rule.py against
      eval/kaggle/g4-l4-v4h2g-p312/results.jsonl (A6000 screen, not a Kaggle result) and by the counters above.
   c. With whatever time remains before the hard stop: P3 (training data) with v7 as the bundle, 4 passes per task,
      excluding the s200 ids, successes only, plus (chosen, rejected) pairs, as written in P3.
4. Report after each of a, b, c: the table, the counters, the verdict against the pre-registered reading, and the
   commit hashes. If a counter that v7 must bring to zero is not zero, say which calls still produce it, with
   three examples (task, call, reply), so the Mac side can fix it.


-------------------------------------------------------------------------
P7. RECOVER AFTER AN INTERRUPTED SESSION (new Claude Code session on the box)
-------------------------------------------------------------------------
You are a new session on the A6000 box (WSL2 Ubuntu, one RTX A6000, a friend's PC: work only inside ~/g4 and
Docker). The previous Claude session was interrupted; its state lives in files, not in memory. Repo
~/g4/gemma-swe-agent, branch wip/gemma-agent (never main, never --no-verify, pull --rebase --autostash before every
push, commit small). Read first, in this order: docs/a6000/P2_LOG.md (last 40 lines: the hourly health lines and
events), docs/v4h/GATE.md from "P2 addendum 11" to the end (the v7 runs, pre-registrations, the P3 plan),
scripts/a6000/PROMPTS.md sections P3 and P6, and the header of scripts/a6000/autopilot.py (the supervisor: plan file,
steps, self-repair, the 36 h hard stop at 2026-10-08 09:44 UTC).

1. STATE, before touching anything: `pgrep -afi "autopilot|vllm|EngineCore|or_proxy|race|swegemma"`, `nvidia-smi`, `tmux ls`,
   `df -h ~`, `git status -sb`, the plan file the supervisor reads, and the newest result dirs under ~/g4/runs.
   Write one block to P2_LOG.md: what is alive, what step the plan is on, the last health line, and whether the
   interruption killed the supervisor, vLLM, or an in-flight P3 pass.
2. If the supervisor is alive and P3 is progressing (new rows since the last health line): leave it alone, keep the
   hourly health lines going, and go to step 4.
3. If anything died: restart in the supervisor's own way (its plan file and resume logic; do not hand-launch steps).
   P3 keeps the bundle it started with (v7 = commit b62a546). Do NOT switch to v7b or any other bundle mid-P3; v7b
   exists on the branch for the Kaggle queue only. Items that were in flight at the interruption are purged and
   re-run by the supervisor's existing rule. Record what was lost in P2_LOG.md.
4. Until the hard stop: hourly health lines; back up results to the branch as before (results, pairs, captures,
   logs); if the other Windows GPU workload returns, the guard pauses and resumes as before.
5. At the hard stop (or when P3 finishes early): run the finalize hooks (the final summary, the P3 data report:
   passes done, rows, distinct tasks, pairs, tool mix), stop vLLM and the proxies, confirm `nvidia-smi` shows no
   compute process, push everything, and end with the P6 step-4 report (the v7_s50 table and verdict, the v7 P4
   table and verdict, the counters, P3 counts, every commit hash). Then stop; do not start new runs.


-------------------------------------------------------------------------
P8. v7c SCREEN + ONE DATA PASS (after the box is restarted; new session)
-------------------------------------------------------------------------
You are a new Claude Code session on the A6000 box (WSL2 Ubuntu, friend's PC; work only in ~/g4 and Docker). Repo
~/g4/gemma-swe-agent, branch wip/gemma-agent (never main, never --no-verify, pull --rebase --autostash before every
push, commit small). Read first: docs/a6000/P2_LOG.md (last 40 lines), docs/v4h/GATE.md from "P2 addendum 11" to
the end, docs/GAPS_2026-10-06.md (last section: the v7c pre-registration), scripts/a6000/PROMPTS.md P3/P6/P7, and the
header of scripts/a6000/autopilot.py. Before any GPU work, confirm with the owner that the Windows session stays
logged in and sleep is off for the next 24 h; WSL died twice when the session ended. Hard stop = launch + 24 h.

1. STATE: `pgrep -afi "autopilot|vllm|EngineCore|or_proxy|race|swegemma"`, `nvidia-smi` (no other compute process), `df -h ~`,
   `git status -sb`, `git pull --rebase --autostash origin wip/gemma-agent`. Confirm submissions/v7c and
   tests/test_v7c_bundle.py exist; run tests/test_v7c_*.py + tests/test_setup_stage.py and scripts/validate.py
   submissions/v7c. If anything fails, log it to P2_LOG.md and stop (the Mac side owns v7c).
2. Start vLLM with scripts/a6000/serve.sh exactly as before (same settings as the v7 runs). Pre-register in GATE.md
   (addendum 12) before the first item: v7c, same C = 2 and pacing rule, scale from a 4-item probe, readings below.
3. Through the supervisor's plan (p6_plan.py mechanism, bundle v7c): probe (4 items) -> v7c on the 50 stage-1a ids,
   paired vs the existing v4h2 and v7 rows on those ids -> v7c on the public 74 (sequential, pacing), judged by
   scripts/keep_rule.py vs eval/kaggle/g4-l4-v4h2g-p312/results.jsonl and by scripts/a6000/v7_counters.py (must be
   zero: view_usage_calls, literal_wrapper_commands, write_file_path_refusals, forced_install_empty_args; report
   cap_refusals, repeat_outlines, loops_ge5, budget_exhausted_tasks) -> if time remains, P3 with v7c: ONE pass over
   the 844 training ids (data/heldout1k/all_valid_ids.txt minus data/heldout1k/sample200_ids.txt), successes only,
   captures kept, rows through build_sft + rebalance + validate, plus (chosen, rejected) pairs where a task has
   both outcomes across this and the v7 P3 attempts.
4. Hourly health lines, hourly results backups to the branch, the GPU guard as before. At the hard stop or when P3
   ends: finalize, stop vLLM and proxies, confirm `nvidia-smi` shows nothing, push, and report after each step:
   tables, counters, verdicts against the pre-registered readings, P3 counts (tasks attempted, solved, rows,
   distinct tasks, pairs), commit hashes. Do not start anything else.

P9. v7d: PULL, VERIFY, PRE-REGISTER, PREPARE THE PLAN; THE OWNER LAUNCHES (new session; paste as is)
--------------------------------------------------------------------------------------------------
You are a new Claude Code session on the A6000 box (WSL2 Ubuntu, friend's PC; work only in ~/g4 and Docker). Repo
~/g4/gemma-swe-agent, branch wip/gemma-agent (never main, never --no-verify, `git pull --rebase --autostash origin
wip/gemma-agent` before every push, commit small). You prepare the v7d screen and STOP before launching it: the owner
runs the launch command himself. Do not start vLLM, the supervisor or any item.

0. PULL FIRST: `cd ~/g4/gemma-swe-agent && git pull --rebase --autostash origin wip/gemma-agent && git log --oneline -3`.
   The head must include "v7d fix 1" (428f3a0 or later). Then read, in chunks: docs/a6000/V7C_FAILURE_ANALYSIS.md
   (all of it; section 7 is the Mac side), docs/GAPS_2026-10-06.md (last section: the v7d pre-registration with its
   decision rule), docs/v4h/GATE.md from "P2 addendum 12" to the end, docs/a6000/P2_LOG.md (last 40 lines),
   scripts/a6000/PROMPTS.md P8, the header of scripts/a6000/autopilot.py and scripts/a6000/p8_plan.py.
1. STATE: `pgrep -afi "autopilot|vllm|EngineCore|or_proxy|race|swegemma"`, `nvidia-smi`, `df -h ~`, `git status -sb`, the last
   lines of P2_LOG.md. Write one block to P2_LOG.md: is the P8 supervisor alive, which step it is on (v7c_p4 / v7c_p3),
   the last health line. P8's hard stop is 2026-10-09 16:26:49 UTC. NEVER write a new plan while P8's supervisor is
   alive: autopilot.py re-reads the plan file at every step start, so a new plan would hijack P8's next step.
2. VERIFY v7d exactly as the Mac shipped it (read-only; the Mac side owns submissions/v7d, do not edit it):
   `~/g4/venv/bin/python -m pytest -q -p no:cacheprovider tests/test_v7d_bundle.py tests/test_v7d_helpers.py
   tests/test_v7d_sandbox.py tests/test_v7d_prompts.py tests/test_v7d_counters.py tests/test_a6000_p8_plan.py
   tests/test_a6000_v7_counters.py` and `~/g4/venv/bin/python scripts/validate.py submissions/v7d`. Then the two
   re-measure scripts on the v7c traces already on this box, as the baseline:
   `python3 -I docs/a6000/v7c_analysis/cross_stage_refusals.py "v7c=$HOME/g4/runs/p2/items/v7c/*/traces/trace_*.json" "v7=$HOME/g4/runs/p2/items/v7/*/traces/trace_*.json"`
   and `python3 -I docs/a6000/v7c_analysis/aggregate_failures.py ~/g4/runs/p2/items/v7c`. Put both outputs in
   P2_LOG.md. If any test or the validator fails: log it, push, and stop; do not fix the bundle here.
3. PRE-REGISTER before any v7d item: GATE.md addendum 13, copied from the v7d pre-registration in GAPS (v7d, C = 2,
   the pacing rule, scale from a 4-item probe at T = 2, (a) the 50 stage-1a ids paired against v4h2, v7 AND v7c with
   the BETTER / WORSE / UNRESOLVED / NO EVIDENCE readings of addendum 12, (b) the public 74 with scripts/keep_rule.py
   against eval/kaggle/g4-l4-v4h2g-p312/results.jsonl and the helper gate, the counters with repeat_reads reported,
   the cross_stage_refusals.py re-measure, the stated decision rule for the Kaggle queue, (c) P3 with v7d only if (a)
   is not WORSE). Name the bundle commit hash and the baseline numbers from step 2. Commit and push.
4. PREPARE THE PLAN, only once P2_LOG.md carries P8's "DONE" line and no autopilot process is alive (if P8 is still
   running, skip this step and say so in the report):
   `~/g4/venv/bin/python scripts/a6000/p8_plan.py --arm v7d --dry-run` (expect ["probe_v7d", "v7d_s50", "v7d_p4", "v7d_p3"]),
   then `~/g4/venv/bin/python scripts/a6000/p8_plan.py --arm v7d` (writes ~/g4/runs/autopilot_plan.json, points the
   choice file at v7d). Check `nvidia-smi` shows no compute process and that the P8 autopilot state file will not
   resume an old step (read scripts/a6000/autopilot.py's --state handling; move the old state file aside the way P8
   did if that is what it does). Do NOT launch.
5. REPORT, then stop: the pull hash, the test counts, the validator line, the baseline numbers, the addendum 13 commit
   hash, whether the plan was written (step 4) or must wait for P8's DONE line, and this exact launch line for the
   owner to paste when he is ready (serve.sh is started by the supervisor's plan the same way P8 did it):
   `cd ~/g4/gemma-swe-agent && git pull --rebase --autostash origin wip/gemma-agent && AUTOPILOT_HARD_STOP_H=24 setsid nohup "$HOME/g4/venv/bin/python" scripts/a6000/autopilot.py >> "$HOME/g4/autopilot.log" 2>&1 < /dev/null & sleep 20; tail -n 2 "$HOME/g4/autopilot.log"`
   If step 4 was skipped, the owner runs `~/g4/venv/bin/python scripts/a6000/p8_plan.py --arm v7d` first, after P8's
   DONE line. After the launch, the plan does the rest: probe -> (a) -> re-measure -> (b) -> (c); hourly health lines
   and backups as before; at the hard stop, finalize, stop vLLM and the proxies, confirm nvidia-smi is empty, push.

P9s. THE SAME, UNDER 4000 CHARACTERS (the goal field's limit; paste this one)
----------------------------------------------------------------------
A6000 box, WSL2, work only in ~/g4 and Docker. Repo ~/g4/gemma-swe-agent, branch wip/gemma-agent (never main, never --no-verify; `git pull --rebase --autostash origin wip/gemma-agent` before every push; commit small). Prepare the v7d screen and STOP before launching: the owner runs the launch line. Never start vLLM, the supervisor or any item.

0. PULL: `cd ~/g4/gemma-swe-agent && git pull --rebase --autostash origin wip/gemma-agent && git log --oneline -3` (head must include "v7d fix 1", 428f3a0 or later). Read in chunks: docs/a6000/V7C_FAILURE_ANALYSIS.md (all; section 7 = Mac side), docs/GAPS_2026-10-06.md last section (v7d pre-registration + decision rule), docs/v4h/GATE.md from "P2 addendum 12" to the end, docs/a6000/P2_LOG.md last 40 lines, scripts/a6000/PROMPTS.md P8 and P9, headers of scripts/a6000/autopilot.py and p8_plan.py.
1. STATE: `pgrep -afi "autopilot|vllm|EngineCore|or_proxy|race|swegemma"`, `nvidia-smi`, `df -h ~`, `git status -sb`. Log one block to P2_LOG.md: is P8's supervisor alive, its step, last health line. P8 hard stop 2026-10-09 16:26:49 UTC. NEVER write a new plan while that supervisor is alive (autopilot.py re-reads the plan file at each step start).
2. VERIFY (read-only; never edit submissions/v7d): `~/g4/venv/bin/python -m pytest -q -p no:cacheprovider tests/test_v7d_bundle.py tests/test_v7d_helpers.py tests/test_v7d_sandbox.py tests/test_v7d_prompts.py tests/test_v7d_counters.py tests/test_a6000_p8_plan.py tests/test_a6000_v7_counters.py` and `~/g4/venv/bin/python scripts/validate.py submissions/v7d`. Baseline on the v7c traces here: `python3 -I docs/a6000/v7c_analysis/cross_stage_refusals.py "v7c=$HOME/g4/runs/p2/items/v7c/*/traces/trace_*.json" "v7=$HOME/g4/runs/p2/items/v7/*/traces/trace_*.json"` and `python3 -I docs/a6000/v7c_analysis/aggregate_failures.py ~/g4/runs/p2/items/v7c`; both outputs into P2_LOG.md. Any failure: log, push, stop.
3. PRE-REGISTER GATE.md addendum 13 from the GAPS v7d pre-registration: v7d, C=2, pacing rule, scale from a 4-item probe at T=2; (a) 50 stage-1a ids paired vs v4h2, v7 AND v7c with addendum 12's BETTER/WORSE/UNRESOLVED/NO EVIDENCE readings; (b) public 74 with scripts/keep_rule.py vs eval/kaggle/g4-l4-v4h2g-p312/results.jsonl + helper gate; counters with repeat_reads reported; the cross_stage_refusals.py re-measure; the Kaggle-queue decision rule; (c) P3 with v7d only if (a) is not WORSE. Name the bundle commit and the step-2 baseline. Commit, push.
4. PLAN, only once P2_LOG.md has P8's DONE line and no autopilot process is alive (else skip and say so): `~/g4/venv/bin/python scripts/a6000/p8_plan.py --arm v7d --dry-run` (expect probe_v7d, v7d_s50, v7d_p4, v7d_p3), then without --dry-run. Check nvidia-smi is empty and that the old autopilot state file cannot resume a P8 step (read autopilot.py's --state handling; move it aside the way P8 did). Do NOT launch.
5. REPORT, then stop: pull hash, test counts, validator line, baseline numbers, addendum 13 commit, whether the plan was written or waits for P8's DONE line, and this launch line for the owner: `cd ~/g4/gemma-swe-agent && git pull --rebase --autostash origin wip/gemma-agent && AUTOPILOT_HARD_STOP_H=24 setsid nohup "$HOME/g4/venv/bin/python" scripts/a6000/autopilot.py >> "$HOME/g4/autopilot.log" 2>&1 < /dev/null & sleep 20; tail -n 2 "$HOME/g4/autopilot.log"` (if step 4 was skipped, he runs the p8_plan.py --arm v7d line first). After launch the plan runs probe -> (a) -> re-measure -> (b) -> (c) with hourly health lines and backups; at the hard stop: finalize, stop vLLM and proxies, confirm nvidia-smi empty, push.

P9b. AFTER THE LAUNCH: APPLY THE P3 CONDITION OF ADDENDUM 13 (under 4000 characters; paste into the box session once the supervisor runs)
----------------------------------------------------------------------
A6000 box, WSL2, work only in ~/g4 and Docker. Repo ~/g4/gemma-swe-agent, branch wip/gemma-agent (never main, never --no-verify; `git pull --rebase --autostash origin wip/gemma-agent` before every push). The owner has launched the v7d supervisor (plan ~/g4/runs/autopilot_plan.json: probe_v7d, v7d_s50, v7d_p4, v7d_p3; log ~/g4/autopilot.log; health lines in docs/a6000/P2_LOG.md). Your job is to apply the one rule the plan cannot: GATE.md addendum 13 says (c) P3 runs only if (a) is not WORSE, but the plan lists v7d_p3 unconditionally. Never start, stop or restart the supervisor, vLLM, a proxy or an item; never edit submissions/v7d.

1. Confirm it is running: `pgrep -af "autopilot|vllm|or_proxy"`, `tail -n 5 ~/g4/autopilot.log`, `nvidia-smi` (vLLM should hold the memory). If the supervisor is not alive, say so and stop.
2. Wait for (a) with a shell loop that sleeps 300 s between checks: `until grep -q "step=v7d_s50 | END" docs/a6000/P2_LOG.md; do git pull -q --rebase --autostash origin wip/gemma-agent; sleep 300; done` (the file is local; the pull only keeps the branch level). Also stop waiting if the log shows a DONE line or the supervisor exited.
3. When the END line is there, wait for its POST p2_results_md.py line (rc=0) and read the v7d table and verdict it appended to docs/v4h/GATE.md (the last section: paired v7d vs v4h2, v7, v7c; BETTER / WORSE / UNRESOLVED / NO EVIDENCE as addendum 13 (a)). Then run the re-measure and put both outputs in P2_LOG.md:
   `python3 -I docs/a6000/v7c_analysis/cross_stage_refusals.py "v7d=$HOME/g4/runs/p2/items/v7d/*/traces/trace_*.json" "v7c=$HOME/g4/runs/p2/items/v7c/*/traces/trace_*.json"`
   `python3 -I docs/a6000/v7c_analysis/aggregate_failures.py ~/g4/runs/p2/items/v7d`
   plus `~/g4/venv/bin/python scripts/a6000/v7_counters.py ~/g4/runs/p2 --arm v7d` (repeat_reads included). State in one block: bare refusals (must be 0), first-fixer-view items solved vs the rest (v7c baseline 11 -> 1 against 39 -> 19), identical-repeat share (v7c 23.9 %), loop items (v7c 11 of 50), the counters, the verdict.
4. If the verdict against v7c is WORSE: edit ~/g4/runs/autopilot_plan.json and remove the step whose name is v7d_p3 (keep the other three; valid JSON; the supervisor re-reads the plan at each step start, so do it before v7d_p4 ends). Log one line in P2_LOG.md ("v7d_p3 removed: (a) WORSE vs v7c, addendum 13 (c)") and push. Otherwise leave the plan alone and log that P3 stays.
5. Commit the P2_LOG.md block, push, report (verdict, re-measure numbers, counters, what you did to the plan, commit hash) and stop. Do not start anything else.

----------------------------------------------------------------------------------------------------------------------
P10. THE SCORER STACK ON THE BOX, THE THINKING-ON PAIR, THE COLLECTION PASS (after P8's DONE line; new session; the owner launches)
----------------------------------------------------------------------------------------------------------------------
You are a new Claude Code session on the A6000 box (WSL2 Ubuntu, friend's PC; work only in ~/g4 and Docker). Repo
~/g4/gemma-swe-agent, branch wip/gemma-agent (never main, never --no-verify, `git pull --rebase --autostash origin
wip/gemma-agent` before every push, commit small). You prepare everything and STOP before launching; the owner runs the
launch line. Never start vLLM, the supervisor or any item yourself; never edit submissions/.

0. PULL FIRST: `cd ~/g4/gemma-swe-agent && git pull --rebase --autostash origin wip/gemma-agent && git log --oneline -5`
   (the head carries "harness/wheels: the 2026-10-09 scorer wheels" and "v12: one LlmAgent with thinking on"). Read in
   chunks: docs/GAPS_2026-10-06.md from "CORRECTION (2026-10-10" to the end (why thinking on, the P10 pre-registration),
   docs/a6000/V7C_FAILURE_ANALYSIS.md section 8, docs/a6000/P2_LOG.md (last 40 lines), scripts/a6000/PROMPTS.md P9,
   the headers of scripts/a6000/p10_plan.py, p10_choose.py, p3_run.py and autopilot.py.
1. STATE: `pgrep -afi "autopilot|vllm|EngineCore|or_proxy|race|swegemma"` (P8's DONE line must be in P2_LOG.md and nothing alive;
   if a supervisor runs, stop here and say so), `nvidia-smi` (if > 1 GB is used with no compute process, the WSL VM
   kept vLLM's memory: tell the owner to run `wsl --shutdown` in Windows PowerShell and reopen with lab.bat linux, then
   start again at step 0), `df -h ~`, `docker ps -a` (remove leftover g4-* containers with `docker rm -f`), `git status -sb`.
   Write one block to P2_LOG.md.
2. THE SCORER STACK (the wheelhouse of 2026-10-09; GAPS CORRECTION): `uv pip install --python ~/g4/venv/bin/python
   --no-deps --reinstall harness/wheels/swegemma-0.2.11-py3-none-any.whl harness/wheels/adk_submission-0.2.13-py3-none-any.whl`
   (uv is on this box; if not, `~/g4/venv/bin/python -m pip install --no-deps --force-reinstall` the same two files). Then
   `~/g4/venv/bin/python scripts/swe_compat.py submissions/v12` must print old_helpers False with swegemma 0.2.11 and
   adk_submission 0.2.13. The race containers install /g4/harness/wheels/*.whl at creation, so the next race gets the same
   stack by itself. VERIFY: `~/g4/venv/bin/python -m pytest -q -p no:cacheprovider tests/test_swe_compat.py tests/test_make_t0.py
   tests/test_v5h2_think_bundle.py tests/test_v12_bundle.py tests/test_a6000_p10.py tests/test_a6000_v7_counters.py` and
   `~/g4/venv/bin/python scripts/validate.py submissions/v12` and `... submissions/v5h2-think`: each stage's gen line must show
   `'include_thoughts': True, 'thinking_budget': 4096`. If anything fails: log it to P2_LOG.md, push, stop.
3. THE THINKING CHECK ON THE SERVER, once, by hand, with vLLM started as the supervisor does (`GPU_UTIL=0.95 scripts/a6000/serve.sh`,
   wait for /v1/models): one chat completion with `{"chat_template_kwargs": {"enable_thinking": true}, "max_tokens": 256}` on a
   short coding question; the reply must carry a non-empty `reasoning_content` (reasoning_parser gemma4). Record the latency.
   Then stop that vLLM (`pkill -fi "vllm|EngineCore"`, twice; confirm nvidia-smi is empty): the supervisor starts its own.
4. PRE-REGISTER GATE.md addendum 14 = the GAPS "P10 pre-registration" text with today's date, the pulled commit, the test counts
   and the step-3 latency. Commit, push.
5. PREPARE THE PLAN (the supervisor must be dead): move ~/g4/runs/autopilot_state.json and autopilot_plan.json aside as
   *_v7d_done.json; `~/g4/venv/bin/python scripts/a6000/p10_plan.py --dry-run` (expect probe_pair, pair_s50, p3_think), then
   without --dry-run. It sets the choice file to v5h2-think; the pair's own post hook (p10_choose.py) replaces it by the rule
   before p3_think starts. Do NOT launch.
6. REPORT, then stop: pull hash, stack line, test counts, validator lines, the step-3 latency and reasoning length, addendum
   commit, and this launch line for the owner:
   `cd ~/g4/gemma-swe-agent && git pull --rebase --autostash origin wip/gemma-agent && AUTOPILOT_HARD_STOP_H=24 setsid nohup "$HOME/g4/venv/bin/python" scripts/a6000/autopilot.py >> "$HOME/g4/autopilot.log" 2>&1 < /dev/null & sleep 20; tail -n 2 "$HOME/g4/autopilot.log"`
   After the launch the plan runs by itself: probe (8 items) -> the 50-id pair (table + choice in GATE.md/P2_LOG.md) -> the
   collection pass with the chosen arm until the hard stop; hourly health lines and backups as before; at the stop it
   finalizes, stops vLLM, pushes. The rows are built on the Mac side (P11); do not train here yet.

P10s. THE SAME, UNDER 4000 CHARACTERS (the goal field's limit; paste this one)
----------------------------------------------------------------------------------------------------------------------
A6000 box, WSL2, work only in ~/g4 and Docker. Repo ~/g4/gemma-swe-agent, branch wip/gemma-agent (never main, never --no-verify; `git pull --rebase --autostash origin wip/gemma-agent` before every push; commit small). Prepare the P10 run and STOP before launching: the owner runs the launch line. Never start the supervisor or any item; never edit submissions/.

0. PULL: `cd ~/g4/gemma-swe-agent && git pull --rebase --autostash origin wip/gemma-agent && git log --oneline -5` (head has "harness/wheels: the 2026-10-09 scorer wheels" and "v12: one LlmAgent"). Read in chunks: docs/GAPS_2026-10-06.md from "CORRECTION (2026-10-10" to the end, docs/a6000/V7C_FAILURE_ANALYSIS.md section 8, P2_LOG.md last 40 lines, PROMPTS.md P9 and P10, headers of scripts/a6000/p10_plan.py, p10_choose.py, p3_run.py, autopilot.py.
1. STATE: `pgrep -afi "autopilot|vllm|EngineCore|or_proxy|race|swegemma"` (P8's DONE line must be in P2_LOG.md and nothing alive; else stop and say so), `nvidia-smi` (>1 GB used with no process = stale WSL memory: tell the owner to run `wsl --shutdown` in Windows PowerShell and reopen with lab.bat linux, then restart at 0), `df -h ~`, `docker ps -a` (rm -f leftover g4-* containers), `git status -sb`. One block to P2_LOG.md.
2. STACK: `uv pip install --python ~/g4/venv/bin/python --no-deps --reinstall harness/wheels/swegemma-0.2.11-py3-none-any.whl harness/wheels/adk_submission-0.2.13-py3-none-any.whl` (no uv: `~/g4/venv/bin/python -m pip install --no-deps --force-reinstall` the same files). `~/g4/venv/bin/python scripts/swe_compat.py submissions/v12` must print old_helpers False. VERIFY: `~/g4/venv/bin/python -m pytest -q -p no:cacheprovider tests/test_swe_compat.py tests/test_make_t0.py tests/test_v5h2_think_bundle.py tests/test_v12_bundle.py tests/test_a6000_p10.py tests/test_a6000_v7_counters.py`; `~/g4/venv/bin/python scripts/validate.py submissions/v12` and `submissions/v5h2-think` must show `'include_thoughts': True, 'thinking_budget': 4096` on every stage. Any failure: log to P2_LOG.md, push, stop.
3. SERVER CHECK, once by hand: start vLLM as the supervisor does (`GPU_UTIL=0.95 scripts/a6000/serve.sh`, wait for /v1/models), send one chat completion with `{"chat_template_kwargs": {"enable_thinking": true}, "max_tokens": 256}` on a short coding question: `reasoning_content` must be non-empty; note the latency. Stop that vLLM (`pkill -fi 'vllm|EngineCore'` twice; nvidia-smi empty).
4. PRE-REGISTER GATE.md addendum 14 = the GAPS "P10 pre-registration" text + date, pulled commit, test counts, step-3 latency. Commit, push.
5. PLAN (supervisor dead): move ~/g4/runs/autopilot_state.json and autopilot_plan.json aside as *_v7d_done.json; `~/g4/venv/bin/python scripts/a6000/p10_plan.py --dry-run` (expect probe_pair, pair_s50, p3_think), then without --dry-run (choice file = v5h2-think until the pair's post hook p10_choose.py applies the rule: v12 unless WORSE). Do NOT launch.
6. REPORT, then stop: pull hash, stack line, test counts, validator lines, step-3 latency, addendum commit, and the launch line: `cd ~/g4/gemma-swe-agent && git pull --rebase --autostash origin wip/gemma-agent && AUTOPILOT_HARD_STOP_H=24 setsid nohup "$HOME/g4/venv/bin/python" scripts/a6000/autopilot.py >> "$HOME/g4/autopilot.log" 2>&1 < /dev/null & sleep 20; tail -n 2 "$HOME/g4/autopilot.log"`. After launch the plan runs alone: probe -> 50-id pair (table + choice) -> collection pass until the hard stop; hourly health lines and backups; finalize, stop vLLM, push. Rows are built on the Mac (P11); do not train here yet.

P11. THE THINKING-ON QLoRA ON THE BOX: ROWS, PROBE, RUN, PACKAGE (after P10's collection pass has ended; new session; GPU idle)
----------------------------------------------------------------------------------------------------------------------
You are a new Claude Code session on the A6000 box (WSL2 Ubuntu, friend's PC; work only in ~/g4 and Docker). Repo
~/g4/gemma-swe-agent, branch wip/gemma-agent (never main, never --no-verify, `git pull --rebase --autostash origin
wip/gemma-agent` before every push, commit small; weights and data never enter git). Training and serving never overlap on
this one GPU: never start vLLM or the supervisor in this session. Each long step runs in the background; you poll its log
and stop when it needs the owner.

0. PULL: `cd ~/g4/gemma-swe-agent && git pull --rebase --autostash origin wip/gemma-agent && git log --oneline -5`. Read in
   chunks: docs/a6000/TRAIN_LOCAL.md (all of it: the thresholds are pre-registered there), the docstrings of
   train/stitch_rows.py, train/qlora_train.py, scripts/a6000/train.sh, and P2_LOG.md's last 30 lines (the P10 pass must have
   its DONE line: "p3_think" finished or hit the hard stop, supervisor finalized).
1. STATE: `pgrep -af "autopilot|vllm|or_proxy|pace_proxy|race|qlora"` (anything alive = stop and say so), `nvidia-smi`
   (> 1 GB used with no process = stale WSL VRAM: owner runs `wsl --shutdown` in Windows PowerShell, reopens with lab.bat
   linux; restart at 0), `df -h ~` (need >= 150 GB free: 63 GB bf16 base + checkpoints), `ls ~/g4/runs/p3_think` (capture*.jsonl,
   items/, results). One block to P2_LOG.md.
2. ROWS: `~/g4/venv/bin/python scripts/a6000/p3_build.py --out ~/g4/runs/p3_think` (build rc must be 0; its GATE/P2_LOG
   paragraph is the data report). `wc -l ~/g4/runs/p3_think/rows.jsonl`. Rows gate (GAPS "gate (a) extended"): the report's
   `thoughts:` line must show share >= 0.80 (rebalanced rows whose completion starts with a non-empty thought channel); below
   it, log to P2_LOG.md, push, stop (the thoughts did not reach the rows; the owner decides).
3. ENV + BASE: `bash scripts/a6000/train.sh env` (must print `cuda ok`), then `bash scripts/a6000/train.sh dequant` (~10 min;
   writes ~/g4/model-bf16/DEQUANT.json with checked_against_library 3).
4. STITCH: `bash scripts/a6000/train.sh stitch ~/g4/runs/p3_think think1`. Gate: validate_stitched.json `ok: true` (it now
   also requires thought_share >= 0.8: model spans starting with a non-empty thought / model spans), `sequences_with_thought ==
   sequences`, >= 40 sequences (one per solved trajectory with v12; the run's schedule scales with the count, `bash
   scripts/a6000/train.sh recipe N`, applied by `train.sh full`); paste stitch_report.json's numbers (sequences, tokens, breaks, healed, compactions, span_*
   counts incl. span_thought_masked, thought_share) into GATE.md addendum 15 with the date and the pulled commit. If the gate
   fails, log why to P2_LOG.md, push, stop.
5. PROBE: `bash scripts/a6000/train.sh probe think1`; poll `bash scripts/a6000/train.sh status think1` every 10 min (about
   1 h). Append probe_report.json's verdict, reasons, tok_s, peak_gb_at_12k, oom_at_16k, forward2k and the repeat losses to
   addendum 15, commit, push. FULL -> step 6. REDUCED -> re-stitch with `bash scripts/a6000/train.sh stitch ~/g4/runs/p3_think
   think1 --max-seqs-per-task-stage 6` then step 6 with `--max-tokens 12288`. FALLBACK -> `gzip -k ~/g4/runs/p3_think/rows.jsonl`,
   note the path, stop (the Mac trains the hosted way).
6. RUN: `bash scripts/a6000/train.sh full think1 [--max-tokens 12288]`; ~13-18 h. Poll hourly: status + the last `eval` line
   (nll_text, nll_tool) to P2_LOG.md; `alarm_tok_s_halved: true` on 3 consecutive steps = report and keep going. If the
   process dies, the same command resumes from the cursor. At `done`: summary.json (best_nll_text, steps, elapsed_h) to
   addendum 15.
7. PACKAGE: the collector bundle is the one named in ~/g4/runs/p3_think/ARM (v12 or v5h2-think). `~/g4/venv/bin/python
   train/package_adapter.py ~/g4/runs/train_think1/run/best --bundle submissions/$ARM --out submissions/${ARM}_think1 --name
   think1 --key-style loud --stages $(v12: agent; v5h2-think: fixer,verifier)`; then `~/g4/venv/bin/python scripts/adapters_dataset.py
   --bundle submissions/${ARM}_think1 --slug g4-adapters-think1 --out ~/g4/ds --push --kaggle ~/g4/venv/bin/kaggle`. Commit
   the bundle WITHOUT adapters/*.safetensors (git status must show no .safetensors), push.
8. REPORT, then stop: pull hash, rows count, stitch numbers, probe verdict + reasons, run summary, the dataset slug, the
   bundle path. Then execute section P11b (the think2 arm) in the same session. The Mac side runs the Kaggle probe kernel, the L4 pair and the slot (TRAIN_LOCAL.md "After training").

P11s. THE SAME, UNDER 4000 CHARACTERS (the goal field's limit; paste this one)
----------------------------------------------------------------------------------------------------------------------
A6000 box, WSL2, work only in ~/g4 and Docker. Repo ~/g4/gemma-swe-agent, branch wip/gemma-agent (never main, never --no-verify; `git pull --rebase --autostash origin wip/gemma-agent` before every push; commit small; weights/data never in git). One GPU: never start vLLM or the supervisor here. Long steps run in the background; poll their logs.

0. PULL: `cd ~/g4/gemma-swe-agent && git pull --rebase --autostash origin wip/gemma-agent && git log --oneline -5`. Read in chunks: docs/a6000/TRAIN_LOCAL.md (thresholds are pre-registered there), docstrings of train/stitch_rows.py, train/qlora_train.py, scripts/a6000/train.sh, last 30 lines of docs/a6000/P2_LOG.md (P10's p3_think must be finished/finalized).
1. STATE: `pgrep -af "autopilot|vllm|or_proxy|pace_proxy|race|qlora"` (anything alive = stop, say so); `nvidia-smi` (>1 GB used, no process = stale WSL VRAM: owner runs `wsl --shutdown`, reopens, restart at 0); `df -h ~` (>=150 GB free); `ls ~/g4/runs/p3_think`. One block to P2_LOG.md.
2. ROWS: `~/g4/venv/bin/python scripts/a6000/p3_build.py --out ~/g4/runs/p3_think` (build rc 0); `wc -l ~/g4/runs/p3_think/rows.jsonl`. Rows gate: the report's `thoughts:` line shows share >= 0.80; below it, log to P2_LOG.md, push, stop.
3. ENV+BASE: `bash scripts/a6000/train.sh env` (must print `cuda ok`); `bash scripts/a6000/train.sh dequant` (~10 min; ~/g4/model-bf16/DEQUANT.json, checked_against_library 3).
4. STITCH: `bash scripts/a6000/train.sh stitch ~/g4/runs/p3_think think1`. Gate: validate_stitched.json ok true (incl. thought_share >= 0.8), sequences_with_thought == sequences, >=40 sequences (one per solved trajectory with v12; `train.sh full` scales epochs by the count). Put stitch_report.json numbers (sequences, tokens, breaks, healed, compactions, span_* incl. span_thought_masked, thought_share) in GATE.md addendum 15 with date + pulled commit. Fail = log to P2_LOG.md, push, stop.
5. PROBE: `bash scripts/a6000/train.sh probe think1`; poll `bash scripts/a6000/train.sh status think1` every 10 min (~1 h). Add probe_report.json verdict, reasons, tok_s, peak_gb_at_12k, oom_at_16k, forward2k, repeat losses to addendum 15; commit, push. FULL -> 6. REDUCED -> re-stitch with `... stitch ~/g4/runs/p3_think think1 --max-seqs-per-task-stage 6`, then 6 with `--max-tokens 12288`. FALLBACK -> `gzip -k ~/g4/runs/p3_think/rows.jsonl`, note the path, stop.
6. RUN: `bash scripts/a6000/train.sh full think1 [--max-tokens 12288]` (~13-18 h). Hourly: status + last `eval` line (nll_text, nll_tool) to P2_LOG.md; alarm_tok_s_halved true on 3 consecutive steps = report, keep going; if the process dies, the same command resumes. At `done`: summary.json (best_nll_text, steps, elapsed_h) to addendum 15.
7. PACKAGE: ARM = content of ~/g4/runs/p3_think/ARM (v12 or v5h2-think). `~/g4/venv/bin/python train/package_adapter.py ~/g4/runs/train_think1/run/best --bundle submissions/$ARM --out submissions/${ARM}_think1 --name think1 --key-style loud --stages <v12: agent | v5h2-think: fixer,verifier>`; `~/g4/venv/bin/python scripts/adapters_dataset.py --bundle submissions/${ARM}_think1 --slug g4-adapters-think1 --out ~/g4/ds --push --kaggle ~/g4/venv/bin/kaggle`. Commit the bundle without any .safetensors, push.
8. REPORT: pull hash, rows, stitch numbers, probe verdict + reasons, run summary, dataset slug, bundle path. Then execute section P11b (think2) from this file. The Mac runs the Kaggle probe kernel, the L4 pair and the slot.

----------------------------------------------------------------------------------------------------------------------
P11b. THE think2 ARM: think1's trajectories + the Invent rows (after P11's think1 run; same session; GPU idle)
----------------------------------------------------------------------------------------------------------------------
Pre-registered in docs/GAPS_2026-10-06.md "Invent rows as an auxiliary arm" (2026-10-11): ONE variable, the Invent rows added to
think1's data; same recipe, same held-out tasks; think2 ships only if it beats think1 on the Kaggle 74 pair AND the generator is
confirmed open-weight (the Mac side decides that; here you train and package). Never start vLLM or the supervisor.

1. ROWS: `mkdir -p ~/g4/invent && ~/g4/venv/bin/kaggle datasets download -d carsonrodrigues/g4-invent-rows -p ~/g4/invent --unzip`
   (two files, bugs*.jsonl and behaviour*.jsonl). Convert with the REAL v12 request as template:
   `~/g4/venv/bin/python train/invent_rows.py ~/g4/invent/*.jsonl --template-capture data/v12/capture_sample.jsonl
    --out ~/g4/runs/p3_think/rows_invent.jsonl --report ~/g4/runs/p3_think/invent_report.json`
   Paste the report (rows_in, kept, rejected by reason, verdicts, repos) into GATE.md addendum 15 under "think2 data". Gate: kept >= 100
   items; below it, log to P2_LOG.md and stop (think2 is not worth a run).
2. COMBINE + STITCH: `mkdir -p ~/g4/runs/p3_think2 && cat ~/g4/runs/p3_think/rows.jsonl ~/g4/runs/p3_think/rows_invent.jsonl >
   ~/g4/runs/p3_think2/rows.jsonl`, then `bash scripts/a6000/train.sh stitch ~/g4/runs/p3_think2 think2 --holdout-tasks
   ~/g4/runs/train_think1/seqs.jsonl.holdout_tasks.txt` (think1's held-out tasks, so the two arms are read on the same 5 tasks; if
   that file does not exist, think1 used data/v11/v11b_holdout_tasks.txt: pass that). Gate as P11 step 4 (ok true incl. thought_share
   >= 0.8, sequences_with_thought == sequences, >= 40 sequences); stitch_report.json numbers to addendum 15.
3. RUN: no second probe (same model, same caps as think1's verdict). `bash scripts/a6000/train.sh full think2 [--max-tokens 12288 if
   think1 was REDUCED]`; the recipe scales by the sequence count (train.sh recipe N). Poll hourly as in P11 step 6; at `done`,
   summary.json (best_nll_text, steps, elapsed_h) to addendum 15 NEXT TO think1's numbers (same held-out tasks: the first comparison).
4. PACKAGE: as P11 step 7 with `--name think2 --out submissions/${ARM}_think2` and the dataset slug `g4-adapters-think2`. Commit the
   bundle without .safetensors, push.
5. REPORT, stop: invent report numbers, stitch numbers, run summary, held-out NLL think1 vs think2, dataset slug, bundle path.

----------------------------------------------------------------------------------------------------------------------
P10c. SIDE CHECKS WHILE THE P10 AUTOPILOT RUNS (read-only; any time after the launch; repeatable)
----------------------------------------------------------------------------------------------------------------------
A6000 box, WSL2, repo ~/g4/gemma-swe-agent on wip/gemma-agent (never main, never --no-verify). The P10 autopilot is running
(launched 2026-10-11T06:05:19Z, hard stop 2026-10-12T06:05:19Z). Everything here is read-only: never write under ~/g4/runs,
never touch autopilot_plan.json / autopilot_state.json / autopilot_choice.json, never start or stop vLLM, Docker or the autopilot.
Only P2_LOG.md may be appended (one block), then commit + push.

0. PULL (the checks below need the current scripts; the run is not touched: the autopilot reads its plan from ~/g4/runs and the
   containers install harness/wheels, which did not change): `cd ~/g4/gemma-swe-agent && git pull --rebase --autostash origin
   wip/gemma-agent && git log --oneline -3` (the head must include "gate (a) extended" or be later).
1. ALIVE: `pgrep -afi "autopilot.py|vllm|EngineCore|pace_proxy"` (the autopilot and, during a step, vLLM + a proxy must be alive),
   `tail -n 5 ~/g4/autopilot.log`, `nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader`, `docker ps --format
   '{{.Names}} {{.Status}}'`, `tail -n 3 docs/a6000/P2_LOG.md`. If the autopilot is NOT alive and P2_LOG.md has no DONE line for
   today: report it as the first line and STOP (the owner decides on a relaunch; the resumable launch line is at the end of P10,
   run detached from an interactive WSL shell: `setsid nohup ... & disown`).
2. THINKING SIGNATURE (as soon as ~/g4/runs/p2/proxy_pair_s50.jsonl exists):
   `~/g4/venv/bin/python scripts/a6000/think_share.py ~/g4/runs/p2/proxy_pair_s50.jsonl --proxy-log`
   Expected with thinking on: completion tokens per call around 250 or more and 8-9 s latency per call (the sub13 traces); around 50
   tokens and 3 s means thinking is OFF through the harness: say so in the first line of the report.
3. GATE (a) + RENDER GATE (once ~/g4/runs/p3_think/capture_s1.jsonl exists; re-run at each check, the shares should hold):
   `~/g4/venv/bin/python scripts/a6000/think_share.py ~/g4/runs/p3_think --min-share 0.8 --render --json ~/g4/think_gate.json`
   Two lines, report both whole. GATE = the captures (PASS/FAIL, the key seen: reasoning or reasoning_content, reasoning chars,
   carried thoughts). RENDER GATE = the training renderer and stitcher on the same captures (GAPS "gate (a) extended"): thinking
   flag on every call with budget 4096, completions with thought >= 0.80, exact chain pairs >= 0.80 (healed = the next prompt did
   NOT carry the thought), breaks <= 0.02, model spans with thought >= 0.80. GATE PASS with RENDER GATE FAIL means the thoughts are
   captured but do not reach the rows or the chain: put the numbers in the first line of the report; P11 must not start on that data.
   Also, once, when capture_s1.jsonl exists: `head -n 1 ~/g4/runs/p3_think/capture_s1.jsonl > data/v12/capture_sample.jsonl` (one real v12
   request + reply, ~100 KB: the Mac's row converter for the Invent arm takes the tool declarations and the fixed task-message parts
   from it; it is a public heldout task, not training data) and commit it with the P2_LOG block.
4. PAIR TABLE (after the pair_s50 step): `cat ~/g4/runs/p2/*.md 2>/dev/null | tail -n 40` and `cat ~/g4/runs/autopilot_choice.json`
   (the P10 rule: v12 unless WORSE). Report the table and the choice as they are.
5. LOG + REPORT: append one block to docs/a6000/P2_LOG.md ("- <UTC> | P10c check: alive=..., signature=..., gate=..., render=..., choice=..."),
   commit, `git pull --rebase --autostash origin wip/gemma-agent && git push origin wip/gemma-agent`. Then report the five items in
   order, numbers verbatim, and stop.
