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
