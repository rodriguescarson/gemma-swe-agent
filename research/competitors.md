# Competitor map: Gemma 4 Developer Agent (snapshot 2026-09-27 16:11 UTC / 21:41 IST)

Read-only research. No kernels pushed, nothing submitted, no pods started. Every number below carries
the file, command or URL it came from. `NB2` = `/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/nb2`.
Anything not checked against source or data is marked **UNVERIFIED**.

## 0. Bottom line

1. **Nobody public is doing anything we have not already matched.** No team at 0.13 or above has a
   public notebook or dataset for this competition (checked `kaggle kernels list --user` and
   `kaggle datasets list --user` for all 8 of them: `NB2/_lists/top8_users.txt`). The public
   frontier is one design, Roman Rozen's coder plus a read-only `code_analyzer`, and every public
   0.12 is that design or a fork of it.
2. **The public board has exactly 58 tasks, and Kaggle truncates the score.** Leader 0.15 = 9/58,
   0.13 = 8/58, our 0.12 = 7/58. The 0.30 target is **18/58**. One team's score has a binomial SD of
   about 2.5 tasks, and the same Rozen bundle scored 0.12 for its author and 0.08 for a fork
   (forum 743140). The leader is within noise of us. On the LB the gap is 2 tasks; to reach the
   target we need +11.
3. **The biggest lever turned up while checking competitor claims against our own traces, not in
   any competitor notebook:** **about half of all `edit_file` calls never reach the tool.** The
   gemma4 tool-call parser splits the `old_string`/`new_string` code arguments into junk keys. In
   race1, 3,535 of 5,278 `edit_file` calls (67%) came back "mandatory input parameters are not
   present". 606 (11.5%) succeeded. On the real Kaggle L4 stack (e74_v3) the numbers are 360/698
   malformed and 136 ok. `run_command` (one string argument, heredoc bodies) is malformed only
   2.5% of the time, and `write_file` about 0 to 1%. This matches the competitors' symptom:
   "agent reaches the file and then does not edit it" (busyaprime: 42/68 runs with zero
   successful edits). §7.1.
4. **Several harness facts the competitors found change how we measure** (§5): the scorer
   compacts context at 14,336 tokens but our pod runner does not; the scorer uses a private
   **Docker** sandbox, so the `/tmp` rewrite bug may never have hit sub3; an uncaught context
   overflow throws away the patch; patch validation (~2 h) is not counted in the 12 h; the scorer
   reads only 4 `eval_config` keys, defaults to unlimited, and a fix is planned that scores
   unfinished tasks as 0.
5. **Tricks from competitors we have not tried** (§6), ranked: route every edit through
   `run_command` heredocs; cut `max_output_tokens` to about 2048; mirror the grader's exact pytest
   line in our helpers; add an import-path self-check; forbid `search_similar_code` in the prompt;
   set a longer per-task cap once our timing supports it. LoRA stays blocked (adapters are
   silently wiped: forum 743508).

## 1. Sources and method

| What | Command / path | Count |
|---|---|---|
| Public leaderboard | `kaggle competitions leaderboard gemma-4-developer-agent --download` → `NB2/_lists/lb_now2/gemma-4-developer-agent-publicleaderboard-2026-09-27T16:11:39.csv` | 607 teams |
| Notebooks by date | `kaggle kernels list --competition gemma-4-developer-agent --sort-by dateRun --page-size 100 --csv` → `NB2/_lists/date2141_p1.csv` | 57 (page 2 empty) |
| Notebooks by votes | same, `--sort-by voteCount` → `NB2/_lists/votes2141_p1.csv` | 57 |
| Notebook sources | `kaggle kernels pull <ref> -p NB2/pull/<slug>`; flattened text in `NB2/txt/<slug>.txt` | 57 of 57 pulled; the 5 updated after 11:24 UTC today were re-pulled at 15:45 UTC |
| Notebook outputs (bundles) | `kaggle kernels output <ref> -p NB2/out/<slug>` | 19 with files; the rest hit HTTP 429 (retry script `NB2/fetch_out2.sh`) |
| Discussion forum | `kaggle competitions topics list gemma-4-developer-agent` and `topics show <id>` → `NB2/disc/t_<id>.txt` (table, comments cut at ~200 chars) and `NB2/disc/j_<id>.json` (full comment text) | 40 topics, all bodies fetched; full JSON for 13 (429-limited, `NB2/disc/fetch_json.sh`) |
| Top-8 teams' public work | `kaggle kernels list --user`, `kaggle datasets list --user`, `kaggle competitions team-submissions 16953627` | none for this competition |
| Harness source | `.venv/lib/python3.12/site-packages/{swegemma,adk_submission,adk_eval_core,google/adk}` | claims below checked against it |

## 2. Leaderboard

### 2.1 Score = floor(100·k/58)/100
Among N = 40..79, only N = 58 with truncation reproduces the observed set of distinct scores
{0.01, 0.03, 0.05, 0.06, 0.08, 0.10, 0.12, 0.13, 0.15} (my check; the same result was posted in forum
743506 by Geremie Yeo). So 0.15 = 9, 0.13 = 8, 0.12 = 7, 0.10 = 6, 0.08 = 5, 0.06 = 4. **0.30 needs 18/58.**
The hidden set is about 120 tasks, split evenly public/private (data page, quoted in 743506).

Distribution (607 teams): 0.15 ×1, 0.13 ×7, 0.12 ×45, 0.10 ×67, 0.08 ×104, 0.06 ×106, 0.05 ×86,
0.03 ×32, 0.01 ×39, 0.00 ×119. We (Carson Rodrigues, team 16949775) are rank 50: 0.12, 3 submissions
(`kaggle competitions submissions`: sub1 v0 = 0.10, sub2 v2 = platform resource error, sub3 v4 = 0.12).

### 2.2 Top 30

| # | team | users | score | tasks/58 | subs | last sub (UTC) |
|---|---|---|---|---|---|---|
| 1 | Makus | alexmartinez75 | 0.15 | 9 | 2 | 2026-09-26 13:58 |
| 2 | Chandan Ranjan | chandanranjan | 0.13 | 8 | 2 | 2026-09-26 14:51 |
| 3 | 暗黑AGI | boristown | 0.13 | 8 | 4 | 2026-09-27 00:42 |
| 4 | Alperen ÖZ | alperenzfddg | 0.13 | 8 | 3 | 2026-09-26 00:08 |
| 5 | Daniel Olajide | danielolajide | 0.13 | 8 | 3 | 2026-09-27 00:25 |
| 6 | Jeki Wan Taufik | jek1wantaufik | 0.13 | 8 | 1 | 2026-09-26 03:36 |
| 7 | Daniel Du | nghongnhn | 0.13 | 8 | 4 | 2026-09-27 01:05 |
| 8 | I Zaznov | izaznov | 0.13 | 8 | 1 | 2026-09-27 01:14 |
| 9 | Roman Rozen | romanrozen | 0.12 | 7 | 1 | 2026-09-23 18:49 |
| 10 | daoviet | daoviet | 0.12 | 7 | 4 | 2026-09-27 02:02 |
| 11 | Kawchar Husain | kawchar85 | 0.12 | 7 | 2 | 2026-09-25 14:59 |
| 12 | Rahul Rathnavel K | rahulrathnavel | 0.12 | 7 | 3 | 2026-09-26 19:55 |
| 13 | mahmoud al-ghraibeh | mahmoudalghraibeh | 0.12 | 7 | 4 | 2026-09-27 00:06 |
| 14 | Mubin Shaikh | shaikhmubin | 0.12 | 7 | 4 | 2026-09-27 00:13 |
| 15 | kwon yong deuk | kwonyongdeuk | 0.12 | 7 | 3 | 2026-09-26 04:12 |
| 16 | Yuchen20 | yuchen2066 | 0.12 | 7 | 1 | 2026-09-24 22:10 |
| 17 | Radek | rathko | 0.12 | 7 | 4 | 2026-09-27 07:52 |
| 18 | Adarsh Varshney | adarshvarshney | 0.12 | 7 | 2 | 2026-09-26 11:00 |
| 19 | Brian msw | brianmsw | 0.12 | 7 | 3 | 2026-09-27 00:05 |
| 20 | Whisper Last | whisperlast | 0.12 | 7 | 3 | 2026-09-26 00:53 |
| 21 | BokingChen | chenbaoying | 0.12 | 7 | 1 | 2026-09-25 05:16 |
| 22 | Thomas | tommurakami | 0.12 | 7 | 3 | 2026-09-27 01:30 |
| 23 | Chandram Dutta | chandramdutta | 0.12 | 7 | 2 | 2026-09-25 08:26 |
| 24 | Leander Antony | leanderantony30 | 0.12 | 7 | 2 | 2026-09-26 11:23 |
| 25 | Rapha | raphaabels | 0.12 | 7 | 2 | 2026-09-26 18:46 |
| 26 | Gronk | jianyicai | 0.12 | 7 | 3 | 2026-09-27 03:37 |
| 27 | Mohamed Samir | mosam002 | 0.12 | 7 | 2 | 2026-09-26 13:25 |
| 28 | Lucas Hudson | lucashudson | 0.12 | 7 | 1 | 2026-09-25 14:01 |
| 29 | vogts wu | vogtswu | 0.12 | 7 | 2 | 2026-09-26 04:04 |
| 30 | Alan Karl | alankarl | 0.12 | 7 | 1 | 2026-09-25 15:32 |

### 2.3 What the top 8 have in public: nothing for this competition
- `alexmartinez75` (Makus, 0.15), `chandanranjan`, `alperenzfddg`, `danielolajide`: "Not found" / "No datasets
  found". `boristown`, `jek1wantaufik`, `nghongnhn`, `izaznov`: only kernels and datasets from other
  competitions (`NB2/_lists/top8_users.txt`). `team-submissions 16953627` returns only
  `{id 56581026, 2026-09-26 13:58, 0.15}`, not the file.
- Two of the 0.13 teams got there with **one** submission (Jeki Wan Taufik, I Zaznov). That fits a
  standard baseline plus luck.
- The only first-hand hint from a 0.13 team is Alperen ÖZ (#4) in forum 743213 (2026-09-26 09:23):
  their 0.13 came from "a plain YAML bundle, no adapters". A later bundle "from the same pipeline (differing
  only in the thinking settings in sampling.yaml and timeout_seconds in eval_config.yaml)" hit the platform
  resource error. So: no LoRA, an eval_config with a command timeout, and thinking settings still being varied
  (`NB2/disc/j_743213.json`).
- Luck is enough to explain the leader. Under independent tasks, a p = 0.10 agent reaches ≥9/58 with
  probability 0.12. Across ~50 teams running near-identical agents, someone reaches 9 with probability
  ≈0.998 (my binomial arithmetic). The fact that nobody reached 10 suggests outcomes are correlated
  across teams, because everyone solves the same easy tasks.
- **Measured run-to-run noise on the real scorer:** Geremie Yeo's direct fork of Rozen's notebook
  scored **0.08** (scoring time 14.5 h), against Rozen's **0.12** (forum 743140, comment 2026-09-25
  21:21). That is 5 vs 7 tasks from the same bundle.

Implication: the LB cannot rank designs whose difference is under about 3 to 4 tasks. Only paired,
Kaggle-faithful local runs can.

## 3. What the scoring public notebooks actually ship

### 3.1 The 0.12 family (Rozen's design)
`NB2/out/romanrozen/submission_bundle/` (the scored zip, sha256 `f353…a7aa4`, experiment card
2026-09-23T19:18Z):
- **Root `swe_coder`**: tools `run_command, read_file, edit_file, write_file, get_status, submit_patch` plus
  `agent_tool: {config_path: sub_agents/code_analyzer.yaml, skip_summarization: true}`. No graph tools on the coder.
- **`code_analyzer`**: read-only, tools `run_command, read_file, search_similar_code, get_code_neighbors,
  get_code_subgraph`; fixed answer format `LOCATION / ROOT CAUSE / FIX PLAN / RELATED / TESTS / CONFIDENCE`, ≤250 words.
- **Sampling** (both agents): `temperature 0.2, top_p 0.95, top_k 40, max_output_tokens 8192,
  thinking_config {thinking_budget 4096, include_thoughts false}`. `include_thoughts: false` sends
  `enable_thinking: false` (verified: `adk_submission/resolvers/generation.py:92-107`), so thinking is
  **off**. `thinking_budget` is never forwarded.
- **No `eval_config.yaml`** at all, so the scorer's default is no limit (Ryan Holbrook, forum 743063:
  "The scorer reads those, and only those, four fields. The default is no limit.").
- Prompt rules (`prompts/system.md`): never edit tests/conftest/pytest.ini/CI/packaging; scratch in /tmp;
  call analyzer first with the full issue; grep every identifier; `/tmp/repro.py`; `edit_file` with verbatim
  `old_string` incl. indentation, no line-number prefixes; `py_compile` after every edit; closest tests with
  `-x -q`; `git status`/`git diff` before `submit_patch`; `get_status` every ~8 calls, and below 25% budget go
  straight to fix, verify, submit.

Same design, other scores:
- mizeroluckygall's **Pathfinder v2** (team at 0.12, rank 35): same prompt and time policy, the analyzer gets
  the full issue, no eval_config. Its **v1** had a hard 4-minute self-limit and an 8-call analyzer and scored
  **0.08** ("cutting hard tasks short cost more than it saved": `NB2/pull/pathfinder-gemma-4-agent-eda-baseline`,
  MD cells 25 and 34).
- msama01 (0.10, rank 75): byte-for-byte Rozen clone (`NB2/out/gemma-4-developer-agent-eda/submission.zip`).
- Geremie Yeo's fork: 0.08 (above).
- anatomy-of-a-fix (proamari, no LB entry): Rozen plus data-derived rules (below).

### 3.2 The other scored designs

| author (LB) | architecture | budget | sampling / thinking | result and notes |
|---|---|---|---|---|
| zhukovoleksiy (0.10, #63) | coder (all 9 tools) plus read-only analyzer via agent_tool | v2: none; v3: `max_time_minutes 4, max_turns 80, timeout_seconds 120` | T 0.2, top_k 40, out 8192 (v3: 4096), thinking off | Starter with fixes at 5 min/50 calls: **0.00** (run took 80 min). v2 uncapped: **0.10**. First v3 at 12 min/task: **Notebook Exceeded Allowed Compute**. v3 adds `{problem_description}` at the end of both instructions, tail-first logs, "write findings as text", `skip_summarization: false`, bans `search_similar_code` |
| nihilisticneuralnet (0.10, #54) | coder plus optional localizer and verifier agent_tools (lean variant = coder only) | 4.5 min / 40 calls / 100 turns / 60 s | T 0.15, top_p 0.95, out 8192, thinking off | 0.10 was a previous version (`previous_user_reported_score: 0.10`, `NB2/out/0-10-…/experiment_card_detailed.json`). One combined `py_compile && git diff --check && pytest … -p no:anyio -o timeout=0` command. A developer-side multi-candidate selector (sample N search/replace proposals, test each, pick by fail-to-pass) that **cannot be shipped** |
| lucifer19 / Black Cat (team best 0.10, #93) | v1 single agent → **0.06**; v2 single agent, 16k output, thinking HIGH → **Exceeded allowed compute**; v3 "Compact" single agent → **0.08**; v4 "Analyzer challenger" coder plus analyzer → probably the team's 0.10 (**UNVERIFIED** which version scored) | v1 default (no cap); v3 4 min / 24 calls / 40 turns / 60 s; v4 5 min / 40 calls / 100 turns / 120 s | T 0.2, analyzer T 0.1 and out 2048; coder out 4096, thinking off | Rules: `git grep` (no `rg`/`tree`), heredoc scratch files, `> /tmp/t1.log 2>&1; tail -n 25`, one-shot `py_compile && pytest -q -x -p no:anyio -o timeout=0`, never call `search_similar_code`, `{problem_description?}` in the analyzer |
| TwangyGarlic449 gemma-super-basic (0.08) | single agent, 5 tools, 20-line prompt | none | T 0.2, out 8192, thinking off | **0.08**, a useful floor: a minimal agent lands within 2 tasks of the frontier |
| prvsiyan "Shape of Doubt" (0.08, #126) | engineer (keeps history) plus one read-only reviewer via agent_tool, a `repo_lens` search skill run with `run_skill_script` | 5 min / 45 calls / 80 turns / 60 s | T **1.0** (Google's recommendation), out 2048 engineer / 1024 reviewer, thinking off | Local development: 2/4 + 3/12. The V14 candidate (3/4 + 4/12) was **not** shipped for lack of evidence. Very careful receipts |
| busyaprime (0.06, #262) | coder loop, 120 calls / 5 min | | | Predicted 17/58 from its own 34/119 locally and got **4/58**. "The error is in the scale": every team is at least 14.8 pp below a well-built local grader |
| nursrijan starter kit (0.05) | coder plus analyzer | | T 0.2, out 16384 | 0.05 (forum 743140) |

The rest, with no LB evidence: tharunkumar369's "Top 1 Master Baseline" claims "LB 0.12–0.13+" for a flat
agent, but the author is not on the LB and ships 30 min/task with thinking on (`NB2/out/gemma-4-developer-agent-top-1-master-baseline`).
That is **UNVERIFIED** and probably over the 12 h. haideptry (0.00 LB) ships skills at the wrong path
`/workspace/skills/...`. GemmaForge, chaitanyajamble and koushikkumardinda are all at 0.00. The graph and paper-track
notebooks (woldywei 0.05, zzgtylors, norikazuhaji 0.03, avikdas567, sayandeepghosh 0.08, yuki16, nursrijan) are
localization studies, covered in §6.8. Three notebooks are unrelated (Vietnamese NLP, Kaggle template).

### 3.3 Our own calibration points
v0 (sample prompt, coder plus analyzer, uncapped, T 0.2, thinking off) = **0.10**. v4 (3-stage Sequential, T 1.0,
5 min / 70 calls / 150 turns / 180 s) = **0.12**. So we already sit at the public frontier with a different
architecture. The frontier holds whether the agent is a single agent (0.08), coder plus analyzer (0.08 to 0.12)
or staged (0.12). **Architecture choice has not shown up on the LB for anybody.**

## 4. Settings the field agrees on (and whether we match)

| Setting | Field consensus | Evidence | Ours (v9_eog) |
|---|---|---|---|
| Thinking | off (`include_thoughts: false`) | every scoring notebook; thinking-on runs blew the 12 h (Black Cat v3, zhukov v3 at 12 min) | off ✓ |
| `thinking_level` | never set: it becomes `reasoning_effort`, which LiteLLM rejects for this model | host notebook cell 3 comment; Shape of Doubt MD 6 | not set ✓ |
| `seed` | useless: never forwarded to vLLM | Shape of Doubt MD 6; zhukov 743365 | set to 42 (harmless no-op) |
| Temperature | 0.1 to 0.2 in all 0.10 to 0.12 entries; 1.0 in Shape of Doubt (0.08) and ours | §3 | 1.0; not isolated anywhere |
| `max_output_tokens` | trending down: 8192 → 4096 (zhukov v3, Black Cat), 2048/1024 (Shape of Doubt) | vLLM rejects prompt + max_tokens > 32768 | 4096 |
| `{problem_description}` in the instruction | zhukov v3, Black Cat, Shape of Doubt, zero-to-first-valid | ADK state injection; survives compaction | ✓ (v6, v8, v9) |
| `search_similar_code` | banned in the prompt but kept registered | uncapped class bodies (136k chars for "FastAPI"): zhukov MD 23 | registered and allowed |
| Budget | none (Rozen) or 4 to 5 min | §5.4 | 5 min / 70 / 150 / 180 s |
| Search | `git grep -n` (no `rg`, no `tree` in the sandbox) | zhukov, Black Cat | ✓ |

## 5. Harness facts competitors discovered (with our verification)

1. **Scoring rule since 2026-09-25**: pytest exit 0 **and** a JUnit XML with `passed_tests > 0`, `failures == 0`,
   `errors == 0`, and every required node explicitly passed; **a skip is not a pass**. Required nodes come from
   `FAIL_TO_PASS`/`PASS_TO_PASS` or are extracted from `test_patch` (busyaprime §3.1). ✓ Verified in
   `data/HARNESS_README.md:598-610`. Grader command:
   `cd /workspace && PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1 python3 -s -m pytest <targets> --junitxml=… -p no:anyio -o timeout=0 -o python_classes="Test* *Test" -q`.
   Our `helpers_v9/gate.py:30` runs `pytest -q -p no:cacheprovider -o addopts= --tb=line -rfE`. That is **not**
   the grader's line: no `PYTHONSAFEPATH`, no `-p no:anyio`, no `python_classes`, and it wipes `addopts`.
2. **Uncaught exceptions discard the patch.** ✓ Verified: `swegemma/harness/agent_runner.py:209`
   (`agent_patch = ''`), the working-tree fallback exists only on the normal path (`:758-795`), and the outer
   `except Exception` (`:797-801`) keeps `''`. Race1: **13/352 runs** ended in `ContextWindowExceededError`
   ("you requested 4096 output tokens and your prompt contains at least 28673 input tokens"), each with patch 0.
   By our trace parse, **5** of them had already made at least one successful edit (c_v9_eog rich_3930: 9 edits; r_v9_eg fastapi_14419: 11;
   r_v9_og rich_3043: 5; r_v9_c fastapi_14448: 2; r_v9_eg fastapi_14616: 1). LiteLLM also "Retried: 5 times" on a
   deterministic 400. Most of the overflows are repeat-read loops (§7.1), not single huge outputs.
3. **Scorer-side compaction.** README §7.2 (`data/HARNESS_README.md:553-563`): `EventsCompactionConfig(compaction_interval=5,
   overlap_size=2, token_threshold=14,336, event_retention_size=5)` plus `ContextCacheConfig(2048, 1800 s, 10)`.
   The host notebook uses `compaction_interval=15` with the same threshold. Compacted history keeps model text
   and drops tool outputs (zhukov MD 28; **UNVERIFIED** by us in ADK source). **Our pod runner does not compact**: `scripts/run_eval.py` wraps
   `swegemma eval`, and `swegemma/cli.py`/`evaluate.py` never set `events_compaction_config` (EvalConfig default
   `None`, `swegemma/config.py:117`; applied only when set, `agent_runner.py:410`). Our Kaggle eval kernel does set it
   (`scripts/make_eval_kernel.py:95`). **The race1 pod results therefore come from a non-compacting harness.**
4. **The private scorer uses a Docker sandbox.** Ryan Holbrook, forum 742882 (2026-09-27 11:12): "This may be a problem with
   the subprocess sandbox. I don't recall seeing these failures using the Docker sandbox. The private Docker sandbox
   uses the same base image but installs a different set of dependencies". The `/tmp`-in-command-text rewrite is
   subprocess-only (✓ `swegemma/sandbox/subprocess.py:436-442`; `swegemma/sandbox/docker.py` has no rewrite).
   So in Docker `python3 /tmp/swe/locate.py` resolves to the container's /tmp, where v4's `install.py` (hard-coded
   `dst = "/tmp/swe"`) also wrote through `run_skill_script`. Both run inside the same container
   (`adk_eval_core/sandbox/base.py:164-223`).
   **UNVERIFIED but likely: sub3's helpers worked on the scorer, so the 0.12 was measured with working helpers.**
   Docker also means 4 GiB RAM, 2 vCPU, `network_mode=none` (busyaprime divergence 4, README).
5. **Budget semantics.** Tasks run sequentially. Only `timeout_seconds / max_tool_calls / max_time_minutes /
   max_turns` are read; the default is no limit. Hitting 12 h currently errors the whole run, and Ryan is "planning on
   a fix that will score unfinished tasks as 0" (743063, full text in `NB2/disc/j_743063.json`). **Patch validation
   (~2 h when every task has a patch; ~10 min for a no-patch run) is excluded from the 12 h** (743663). Container
   setup is excluded from the per-task time (README tip, `agent_start_time`). `timeout_seconds` also caps the
   Phase-2 verification pytest (zhukov 743365, from `verification.py`), so a 60 s cap can fail a correct patch.
6. **Tools**: `run_command` keeps the **first** 5,000 chars of stdout and of stderr, and a timeout returns **no**
   output (✓ `swegemma/tools/execution.py:42-53`). `read_file` ≤150 lines / 10,000 chars. File tools reject
   paths outside /workspace. `get_code_neighbors` matches `edge_type` exactly and the graph has only lowercase
   `calls`. Graphs contain **0 of 305 async defs** (forum 742911; 302,689 function nodes, 0 async, in
   nitish5236goel's reissue audit). `search_similar_code` resolves the query against node **names** only (no
   text encoder: woldywei RQ4), so a sentence returns nothing. Every task has graphs since the 2026-09-25 re-issue.
7. **Skills**: custom tools must be skill scripts (Ryan, 743573). `run_skill_script` materializes **all** skill files
   into a fresh `tempfile.TemporaryDirectory()` on every call, `chdir`s there (so cwd is **not** /workspace), runs
   `runpy`, and executes inside the sandbox via a `.adk_exec_<hex>.py` written into /workspace and then deleted
   (✓ `google/adk/tools/skill_toolset.py:571-712`, `adk_eval_core/sandbox/base.py:201-210`). GraphLoc's skill
   is invoked this way on every call and needs no install step.
8. **Nudges**: 3 consecutive replies without a tool call end the session (`max_nudges = 3`,
   `agent_runner.py:499`). `skip_summarization: true` ends the coder's turn after each analyzer call and so costs a
   nudge (zhukov MD 28; plausible from the loop code).
9. **LoRA**: only LoRA adapters are accepted (743383). The patched vLLM 0.19.1 loads them and then **wipes every
   `lora_B`**, because Gemma4 decoder layers are registered twice (743508, Whisper Last, with repro). Ryan: "I will
   address" (2026-09-26 11:19). No public submission has scored with an adapter. Ruling on distillation from
   proprietary LLMs: "conferring" since 09-24 (742807).
10. **Hidden tasks are cleaner than public ones.** Ryan, 743817 (2026-09-27 10:58): "We did much more extensive reviewing
    and editing of the test tasks than the training tasks. 'Impossible' tasks … are one of the things we checked for.
    We also checked that a failing test case for the frontier model's patch was something it could have gotten correct
    with the information given." Our never-solved buckets "hidden spec 9, underspecified 6"
    (`eval/diagnosis_never_solved.json`) are therefore probably over-represented in public relative to hidden.
11. **Environment shadowing**: in the subprocess sandbox the repo's own released package can shadow /workspace
    (requests, httpx), and some FastAPI test deps are missing (typing-inspection, inline-snapshot, dirty-equals,
    pytest-httpbin) (742882, rdeschamps; Shape of Doubt). anatomy-of-a-fix adds
    `python -c "import <pkg>; print(<pkg>.__file__)"` to the prompt to catch it.
12. **Serving numbers** (busyaprime §6, measured on 4×L4): startup 562 s; KV cache 87,985 tokens (2.69× at 32k);
    prompt/completion throughput at concurrency 1 = 210.6 / 34.1 tok/s; 9,211 prompt tokens per turn on average.
    Shape of Doubt: 12.2 tok/s with eager single-sequence serving vs 31.4 with compile + 2048 prefill (scorer
    settings unknown).
13. ADK 2.x is not supported; "almost any kind of ADK 1.x configuration is allowed … We block anything that
    allows arbitrary code execution" (Ryan, 743800). Support for e2b/e4b/12b/26b-MoE Gemma variants is planned
    "early next week" (743316), which could reopen the model choice. **UNVERIFIED** timing.

## 6. Tricks we have NOT tried (ranked by expected value)

Our v9 prompts and bundles were checked for each (`submissions/v9_eog/**`).

1. **Make `run_command` the edit channel and stop depending on `edit_file`.** No competitor does this
   deliberately; they all tell the model to retry `edit_file` with a smaller snippet. Our traces (§7.1) show the
   failure is in argument parsing, not snippet choice. We have `replace.py`, but only as a fallback after a failed
   `edit_file`. It succeeded 98/129 times, with 53 reverts on syntax error (race1 e-arms).
2. **Cap `max_output_tokens` at ~2048** (Shape of Doubt 2048/1024, Black Cat analyzer 2048). Our completion
   tokens per turn: median 41, p90 195, p99 688 (r_v9_eog, 2,667 turns). 5 to 6 turns per full evaluation hit
   the 4096 cap (r_v9_eog 5 of 51 tasks, e74_v3 6 of 74). The
   ~0.5% of turns at ≥1024 tokens consume 12% of all completion tokens (31,315 of 252,393 in r_v9_eog). A 4096-token
   runaway costs ~2 min at 34 tok/s, and each reserved token is one less prompt token before the overflow in §5.2.
3. **Use the grader's exact pytest line** in gate/test helpers (§5.1), including `PYTHONSAFEPATH=1 PYTHONNOUSERSITE=1
   -p no:anyio -o timeout=0 -o python_classes="Test* *Test"`, and without `-o addopts=`. nihilisticneuralnet and Black
   Cat copy the harness flags for this reason.
4. **Import-path self-check** before trusting a reproduction (anatomy-of-a-fix step 3): catches installed-package shadowing.
5. **Forbid `search_similar_code` in the prompt** (zhukov v3, Black Cat, walkthrough) but keep it registered: our v3
   crashed twice calling an unregistered tool (ledger 2026-09-26 04:40). It is rarely called in race1 (42 calls, max
   11,845 chars), so this is cheap insurance for hidden repos with big classes.
6. **Longer per-task cap, sized from our own timing.** Evidence for caps hurting: Pathfinder 0.08 at 4 min vs 0.12
   uncapped; zhukov 0.00 at 5 min vs 0.10 uncapped (confounded by other changes). Evidence for caps protecting the
   run: three teams hit "Exceeded Allowed Compute" at 12 min or with thinking on. If sub3's 10.4 h wall included the
   ~2 h validation, generation used ~8.4 h, leaving ~3.5 h ≈ +1.7 min/task of headroom. **UNVERIFIED accounting:
   check the sub3 kernel log before raising the cap.** Once Ryan's "unfinished = 0" fix lands, overshooting stops
   being fatal.
7. **Notes-as-text for compaction** (zhukov v3: "after each important finding write one or two sentences"). Our
   stages pass `output_key` notes between stages, but inside a stage nothing survives a compaction at 14,336 tokens.
8. **Localization**: already ahead of the field. busyaprime's best BM25-over-file-tree with code-shaped queries:
   recall@1 29.5%, @20 64%. woldy's TF-IDF file R@10 0.605 vs `search_similar_code` 0.271. GraphLoc (zzgtylors)
   ships a stdlib BM25 + personalized-PageRank skill (async-aware, ~2 s/1,000 files) run through `run_skill_script`.
   **Its end-to-end ablation is the only paired resolution experiment any competitor published**
   (`NB2/out/graphloc-e2e-json/e2e/e2e_summary.json`). On the 106 public tasks whose gold passes in the Kaggle
   subprocess sandbox, running the sample prompt with all 9 tools, T 0.2, thinking **on** (budget 4096, out 16384),
   and 40 calls / 25 min / 60 turns / 120 s: **base 31/106 = 29.2%, +skill 30/106 = 28.3%, McNemar p = 1.0**
   (base-only 8, skill-only 7). The skill ran first in 77/106 tasks and raised function-hit by nothing
   (0.434 → 0.425). Resolution was 0.587 when the agent touched a gold function vs 0.037 when it did not. So
   **better localization tooling did not move resolution**, which agrees with our §7.1 story (the file is found;
   the edit fails). Our `locate.py` measured R@1 0.53 / R@10 0.85 (ledger 2026-09-26 12:10). No gain from copying.
9. **Untried by the whole field**: best-of-N or test-selected candidates (`ParallelAgent`, `LoopAgent`). Nobody
   ships them; nihilisticneuralnet built the selector developer-side only. That leaves an opening, but it is
   budget-bound at ~5 min/task.
10. **LoRA** (only if the 743508 fix lands): our SFT data exists (ledger 2026-09-26 08:30, 314 rows). Nobody on the
    board can use adapters today, so a working adapter after the fix would be a real differentiator.

## 7. Cross-checks on our own traces triggered by competitor claims

### 7.1 Malformed tool arguments (the largest measurable loss)
Script: `/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/edit_rate.py`.
"Malformed" = observation contains `mandatory input parameters are not present`.

| run | edit_file calls | ok | malformed | other error | write_file malformed |
|---|---|---|---|---|---|
| sw1_v1 (T 0.5) | 184 | 28 | 98 (53%) | 58 | 0/21 |
| sw1_v1_t10 (T 1.0) | 359 | 41 | 192 (53%) | 126 | 0/32 |
| p_v4 (fair pod) | 1030 | 140 | 502 (49%) | 388 | 1/109 |
| p_v7 | 983 | 131 | 328 (33%) | 524 | 0/99 |
| p_v8 | 1328 | 118 | 987 (74%) | 223 | 0/133 |
| race1 r_v4 (18/51 solved) | 665 | 84 | 336 (51%) | 245 | 1/70 |
| race1 r_v9_c (15/51) | 933 | 79 | 660 (71%) | 194 | 1/67 |
| race1 r_v9_eo (14/51) | 878 | 86 | 605 (69%) | 187 | 0/55 |
| race1 r_v9_eg (16/51) | 1106 | 81 | 870 (79%) | 155 | 0/56 |
| race1 r_v9_og (14/51) | 864 | 104 | 609 (70%) | 151 | 1/87 |
| race1 r_v9_eog (21/51) | 411 | 98 | 161 (39%) | 152 | 0/78 |
| race1 total (all 8 dirs + canaries) | 5278 | 606 | 3535 (67%) | 1134 | |
| **Kaggle L4 e74_v3** | 698 | 136 | **360 (52%)** | 202 | 0/35 |

- Corrupted keys are fragments of code, for example `'def __enter__(self) -> Self'`, `'.?/;'`,
  `'r"(?P<url>(file|https|http|ws|wss)'`, `'<|"|>,show_default (bool, optional)'`, or the whole `old_string`
  folded into `new_string` as `…`,old_string:`. That points at the gemma4 tool parser's string delimiters
  (`<|"|>`) breaking on code content. **UNVERIFIED root cause**: the raw completions are not in the traces. Temperature
  is not the driver (53% at both T 0.5 and T 1.0).
- `read_file` gets `start_line\"` / `end_line\"` keys in 155/3,557 race1 calls. The range is silently dropped,
  lines 1-150 come back every time, and the model re-reads the same range until the context overflows (r_v9_eg
  rich_3782: 13 identical reads; r_v9_c fastapi_5077: 13). This causes most of the 13 overflows in §5.2.
- Across the six race1 arms, the two with the lowest malformed-edit share (eog 39%, v4 51%) are the two best
  scorers (21 and 18 of 51). Spearman ρ ≈ 0.47 over 6 arms, so this is suggestive, not significant.
- `run_command` is malformed in 125/4,977 calls (2.5%) in the e-arms, mostly `description`/`parameters` wrappers.
  **One-string-argument tools survive; two-long-string-argument tools do not.**

### 7.2 Helper install reached only ~half the race1 runs
Across 352 race1 task-runs, `run_skill_script(install.py)` was attempted in 194 and succeeded in 159 (45%). 40/204
calls had corrupted arguments (`'"swe-tools"'`, `{"\"install.py\"": …}`, `'":"'`, missing `skill_name`).
v9_eog: 27/51 installed. Helper calls failing with "can't open file": 72/389 (v9_eog), 86/93 (v4). So the race arms
were only half-treated. A task-stratified permutation test (20 tasks with mixed install outcome) shows **no
detectable effect of a successful install on resolution**: +1.33 tasks vs expectation, P(harm) = 0.92. The pooled
19% vs 32% is a Simpson's-paradox artifact: easy tasks skip the install. Helpers are unproven either way.
Corollary of §5.4: race1's `r_v4` arm (helper calls failing 86/93 on the subprocess sandbox) does **not**
reproduce v4 as the Docker scorer ran it. Comparisons of v9 against "v4" on the pod are against a crippled v4.

## 8. Negative results the field already paid for (do not repeat)
- Starter kit as-is: FAILED (unhandled error) because of the zero LoRA adapters and a 1 min/10 call eval_config
  (743140, 743213, zhukov).
- Thinking on (HIGH, or `include_thoughts: true` with 16k output): exceeds the 12 h (Black Cat v3, zhukov).
- 12 min/task cap: exceeds the 12 h (zhukov v3 first attempt). The many "requested more CPU, GPU or TPU
  resources" failures on 2026-09-26 (743213, 743661) were platform-side, not budget-side; Ryan: "I think I've
  resolved this one".
- Hard 4-min self-limit in the prompt: 0.08 vs 0.12 uncapped (Pathfinder).
- Graph-centric entries: none above 0.08 (sayandeepghosh 0.08, nursrijan 0.05, woldy 0.05, norikazuhaji 0.03;
  avikdas and zzgtylors have no LB entry).
- A single 16-task development subset predicted nothing: busyaprime's 34/119 locally became 4/58 on the board.

## 9. Open questions
1. Does the scorer really use the Docker sandbox? This decides whether the `/tmp` bug affected sub3 (§5.4).
2. Does the 12 h include vLLM startup (~9.4 min)? Did sub3's 10.4 h include the ~2 h validation?
3. Scorer compaction interval: 5 (README) or 15 (host notebook)? Forum 743456 claims token_threshold = 32,768.
4. When do the "unfinished = 0" and LoRA-wipe fixes land? The distillation ruling (742807) is still pending.
5. Will the small Gemma variants be allowed? A faster model would change the whole time budget.
6. What did the leader change? No trace exists; the score is compatible with noise (§2.3).
