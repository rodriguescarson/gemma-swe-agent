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

1. STATE, before touching anything: `pgrep -af "autopilot|vllm|or_proxy|race|swegemma"`, `nvidia-smi`, `tmux ls`,
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
