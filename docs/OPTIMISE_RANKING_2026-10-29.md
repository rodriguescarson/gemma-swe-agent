# Optimisation ranking, 29 Oct 2026 (workflow gemma-diagnose-optimise, run wf_0efc6ce6-a76)

Raw synthesis of 75 findings (49 kept after an evidence check, 26 dropped) from 7 finders: pipeline defects, tool-call
failures, solved-vs-failed contrast on the 32 screen tasks (3 finders), model options and techniques online.

**Correction (Mac, 29 Oct):** the synthesis says screening runs on the A6000 box. That box was closed on 20 Oct
(GAPS 'The A6000 box is closed'). Screening options today are Kaggle 4x L4 (about 15 h a week, counted double),
hidden reads (one a day) and, for mechanism counts only, the OpenRouter proxy.

---

# Synthesis: ranked backlog, top-3 specs and model options for the Gemma 4 agent (v12b)

I edited nothing. I only read `submissions/v12b` and `submissions/v12b_ctx` (`prompts/system.md`, `eval_config.yaml`) and the header of `tests/test_v13_leakage.py`, to get exact wording. `agent.yaml` is identical in the two bundles. v12b_ctx differs from v12b only in prompt step 2 (ranges of at most 80 lines), a rule to keep outputs short, a note rule, and a repeat of `{problem_description?}`.

**What the evidence supports.** No survivor is resolvable by one hidden read. A task is worth 0.0172 on the 58-task board, and identical files already differ by 2 to 3 tasks. Summing every submission candidate below at its corrected gain gives about +0.9 tasks per 74, roughly +0.013, even if all of it is real. Gains are in tasks per 74, and 0.1 task is about +0.0014 on the board. The task-specific gains come from fitting the 74 public tasks. The hidden pool is a different set, so transfer is unmeasured. History also says stacked rules lose: v13, v14 and v16 all read at or below v12 and v12c. Each added rule costs about 4% of the 2.7k-token first prompt. So: one change per slot, a veto threshold decided before the run, and a verdict on mechanism counts rather than solve counts.

Public-task numbers below are fitted to the 74, so the realistic hidden gain is lower. Where two verifiers disagreed (the "first check passes" family: surviving contrast1 vs dropped contrast0), I used the cautious one.

## 1. Ranked backlog

### A. Pipeline defects (no score effect; they block or mislead)

Items marked "wait" edit the checkout and must wait until the running gate is done.

| # | Fix | Why it ranks here | Cost |
|---|---|---|---|
| A0 | Give each workflow subagent its own scratch subdirectory and filename prefix. Confirmed: `wf/` now holds 750 entries and generic names (`feat.py`, `lib.py`) collide. | Free, and stops silent analysis mix-ups. Do it in the next task text. | One line |
| A1 | `eval/analysis/run_audit.py`: skip `oracle_all` and `rescore_fair` (`calls == 0`). Add a `src_diff` column and set `first_edit_s` only for a non-test, non-scratch source path. Regenerate the md and json. Corrected figures: 33 configs, 2,442 runs, 27 never solved, 5 always, 42 contested. This agrees with `task_reach.json` and `docs/TASKS.md`. The current md says "0 never solved". Corrected first-edit figures: scratch-only first edits are about 24 of 175 no-source-edit runs (not 44 of 194), the no-source-edit rate is 29.6% (not 33%), and median first edit is about 40 s too early. (wait) | It misleads target selection today. | 5 lines plus a test pinning 27/5/42 |
| A2 | `scripts/make_eval_kernel.py`: non-oracle builds default `--ids` to `data/kaggle_valid_ids.txt`, with `--all-tasks` as the explicit opt-out. After the filter, assert `len(tasks) == len(set(IDS))` and print N, and refuse to push unless N is 74. Also store `test_tail=(r.test_output or '')[-2500:]` in each row (the err field is empty in 54 of 55 failing gold rows). Drop the redundant `junit_err` key. (wait) | The garble run cost 3.8 h (44%) on 55 ungradable tasks. That is 0.7 h per 10 avoided tasks, not 1 h, and a one-off since the next run already passes `--ids`. Worst-case 12 h breach is an estimate. | About 25 lines, 2 tests |
| A3 | Gate and ship hygiene (wait). Items:<br>- `ship.sh`: capture `PIPESTATUS`, print the "SHIP REFUSED" banner, use `mktemp` instead of `/tmp/linux_test.out`, and write timestamped logs (`arm_sub27_ctx.sh:27` truncates).<br>- Add `--basetemp` with cleanup.<br>- Add a `G1_FAKE_FREE_GB` test hook.<br>- Set `G1_SPORT=free_port()` in `make_world()`.<br>- Fix the time-of-day test with a fake `date` in PATH or an env override of `DAY_END`. `day start + 3600` does not work. The failing window is 23:50-00:00 UTC.<br>- After the gate finishes, delete `pytest-35` (3.1 GiB). Free disk is 15.68 GiB against a 12 GiB guard, so one more full Mac suite leaves about 12.5 GiB.<br>- Relaxing the speed asserts is optional, since they have 60 to 1,000x headroom. Only `dt <= 1.2` is thin. | Corrected savings are small: about 28 min from a disk pre-check, not 2 h 20 min. Attempt 2 failed on a CPU-load bound, and the G1 14 GB cause is already fixed (7546bb2e). | About 40 lines |
| A4 | `scripts/submit_at.sh` (wait). Two fixes in one file:<br>- Use `base=max(TARGET, now)` for `DAY_END`, as `decide_or_skip.sh:20-21` already does. With `TARGET=0` the overlap guard is dead and submits at once.<br>- Exit 1 with "GAVE UP" when the tag is not on Kaggle. Set `ok=1` when `already` returns 0 and when the tag appears in the final listing, otherwise it gives a false "GAVE UP".<br>In `arm_sub2x.sh`, keep `rc=$?` and `exit $rc` before `say`, and use the wrapper `…; rc=$?; …; exit $rc`. | A missed slot is one hidden read. It happened once (sub16, 14 Oct) and its cause is fixed. `arm_box_submit`, `decide_sub9` and `arm_sub21_aa` read give-ups as success. Do the guard first. | About 12 lines, 2 tests |
| A5 | `kaggle_push_wait.sh`: add a deadline (`PUSH_MAX_S`) and exit 1 after 10 consecutive empty status reads. Skip the stale-skip and submission.zip parts, because the skip is intentional and tested. | Robustness only. I found no run that it would have saved. | 8 lines |
| A6 | Refresh `data/HARNESS_README.md` (local copy 49,356 B, live 55.94 kB) and diff it. Confirm replica flags: `gpu_memory_utilization` 0.90 (the box deliberately uses 0.88), no server-default `enable_thinking`, LoRA only with an adapter, no `--generation-config` override. Every new bundle must set `thinking_config` explicitly. Replica flags already match. (wait) | Hygiene. | 15 min |
| A7 | `decide_or_skip.sh`: filter rows by the 74 ids and require all of them, and retry the output download 3 times. | Latent. It matters only if the script is re-armed. `box_p4_gate.py` already filters. | 10 lines |
| A8 | Wording fix in `docs/GAPS_2026-10-06.md`: change "grading is not trusted" to "gold also fails". Correct counts: 0 of 55 extras pass with the gold patch. 36 of 55 are explained (21 import `inline_snapshot` or `dirty_equals`, 8 use the `httpbin` fixture, 1 is a `skipif`, and the rest are an inferred remainder). At least 17 are unexplained. The 0.57 ceiling is unmeasured. 74/74 is definitional. A free CPU oracle kernel on the 55 ids, with A2's `test_tail`, would settle the rest. | Decision quality. | Docs only, plus one CPU kernel |

Dropped pipeline items (the gate's silent skips, the `success` grep in `submit_at`, the arm-script wait, and tested-vs-shipped tree) need no action.

### B. Submission candidates (each a single change)

Each is built on v12b_ctx if its hidden read is ≥0.15, otherwise on v12b. Rules are ordered by reward = gain × confidence ÷ cost.

| # | Change | Evidence and corrected gain | Confidence, cost, risk |
|---|---|---|---|
| B1 | Range reads through `sed -n` in `run_command`, with no ranged `read_file` | 2.5% of ranged reads drop the range silently (key written `start_line"`): 17 calls in 7 runs on Kaggle v12, 5 in 3 runs on garble. The tool returns lines 1-150 with status ok. The matched shortfall of -0.53 per 74 shrinks to about -0.2 [-0.6, +0.2] over all 19 thinking-on configs. **+0.05 to +0.15** (about +0.001 to +0.002). v12b_ctx's mandatory ranges raise exposure from 85% to 100% of reads, about +2 to 3 dropped calls per 74. | Mechanism high, effect low-medium. Cost is one rewritten sentence at no added tokens. Risk: sed prints no line numbers, output is cut at 5,000 chars (4% of today's sed reads), and the model may stop reading before editing. Unverified on L4. |
| B2 | Literal-change rule, plus keep an old-behaviour test red | 19 failing patches over 4 tasks coerce or invent behaviour (rich_3676, 4077, 3777, 3470). No solved run did. The rule only touches 3676 (6/19 × 50% ≈ 0.16) and 4077 (3/19 × 50% ≈ 0.08), so about **+0.25 public**. 3777 is 0 and 3470 about 0.02. Adding the 5077 revert-own-edit loss (2 clean losses in 19 configs, about +0.1) gives about +0.3 public. The hidden gain for these four named tasks is about 0, and transfer is unmeasured, so I plan on **about +0.1**. | Mechanism high, effect medium-low. About 140 tokens. Risk: a task whose gold really needs a conversion or second behaviour gets under-built. Run the 32-id screen. |
| B3 | "If your first check passes on the unmodified code, derive the failing variant from the function's branch conditions" | 9425 (11/13 solved runs wrote the `-> "None"` repro, 0/6 failed runs did), 11194 (12/13 vs 1/6), 15589 (6/6 vs 6/13). Corrected **+0.1** (upper bound about +0.2), not +0.3, and +0.8 is unsupported. | Mechanism high, effect low. About 120 tokens, plus 15-25 s only when it fires. Risk: v13_redfirst was the same idea and was rejected on 0/2 to 0/3 samples, the dropped contrast0 version was refuted, and it could push 14851 (solved only by ending before the cap) into a timeout. Make 14851 a harm control. |
| B4 | `eval_config.timeout_seconds` 180 → 60 (a config change, not a prompt rule) | 51 timed-out `run_command` calls in 39 runs, 46 on rich_4006, 3480, 14258 and 3052. Only 3480 is ever solved. Corrected **+0.1** (range 0 to +0.3). It saves about 360 s on the two Kaggle runs. | Low confidence, zero tokens. Confounded: v13 used 60 and read 0.13, and the v14 prompt rule read 24/74. Pre-check before building: scan the Kaggle traces for successful `run_command` calls lasting 60-180 s. |
| B5 | "Probe before assuming": bare-word `git grep -n name`, never `def name`, to prove absence; print `type(x)` before a class check and use `isinstance`; stub probe | 14616 (class vs instance, 0/8 vs 4/4, Fisher about 0.002): **+0.05 to +0.15**. 3777: **+0.08** at 40% compliance. The two overlap with B2's 3777 share. Hidden is about 0 unless the habit generalises. | Low. About 150 tokens. Do not name `Json` or `is_interactive`. |
| B6 | Two independent read-only calls per turn | 0 of about 12,000 steps ever merged, but 53% of calls directly follow another read-only call. Corrected **+0.0 to +0.5** (central about +0.2). The harness supports it (ADK `gather`, serialised by `tool_lock`). | Low. Needs a 10-task probe, about 1.4 quota hours of the 2.5 left this week. Risk: text-leak rows (v13 lost about 4 per 74). Hold until quota returns. |
| B7 | Sweep a number-to-position function over its inputs instead of tracing it by hand | rich_3506 only: 14 of 18 failed runs have a 4,096-token step of about 137 s. **+0.2 public**, hidden about 0. Not rich_3535 or rich_3278, which are regex tasks. | Low generality. 130 tokens. Last in line. |

**Not recommended** (corrected gain about 0 or negative):
- Deleting "Think briefly" (saves about 40 s per 74).
- Any rule for call-as-text, test-file edits or `/tmp` writes. Note: if a pub024-style prompt is reused, say "write_file only takes /workspace paths".
- A syntax or lint guard (0 to +0.1).
- A repetition guard.
- A plan step, "read tests first", graph tools or localization prompts.
- A call-30 empty-patch submit on 14851. It loses an expected 1.2 to 1.4 solves per run against a gain of 0.3.
- Thinking budget 2048 with a 4096 output cap (-0.3 to +0.1).
- A "LOW thinking" line. Its ceiling is +1 and its expected value is about +0.3, so it is not worth a slot.
- The "consumers of the option" rule, which overlaps the refuted sibling-path finding.

### C. Evaluation and model decisions

1. **Evaluation protocol (adopt now).**
   - Judge by mechanism counts (garble, drop, truncation, revert counts) and by within-task pairs, never by one 74-run's solve total. The noise floor is 2 to 3 tasks.
   - Use a swing set of about 11-12 tasks (the 0.2-0.7 band plus rich_4077) at k≥3, not 6 tasks.
   - Exclude 14851 from deltas, but use it as a harm control for rules that lengthen runs. A thinking-on vs thinking-off gap moves by about 0.35 solves per 74 from it, not 2.
   - Count `p4_v13` and `p4_v13r` once (same seed). Drop the 8- and 6-minute configs from 5-minute evidence (`p4_v12a`, `v12c`, `pub024`, `pub024_6m`). Use `secs >= 299` for cap analysis.
   - Box solves are veto-only (≤24 vetoes). The box has already failed to predict hidden order.
   - The within-task proxy screen only drops candidates. It is underpowered (CI half-widths 0.08-0.25 against one task = 0.017).
2. **Hidden read policy.** v12b's repeats are 0.17, 0.15, 0.17. Use the sub27 rule: ≥0.19 promote, 0.15-0.18 neutral, ≤0.14 drop. Nothing between is a verdict.
3. **Finals and calendar.** Best-of-two counts the better final, so keep v12b plus one other. The second should be as good in expectation as possible and as different from v12b as possible. Submit the last new bundle by 28-29 Nov UTC. A 24 h queue plus a rerun must fit before 2 Dec 23:59 UTC. Do not edit files after a successful scoring. A 12 h overrun scores nothing, and vLLM start has run 514-1,677 s against a 1,200 s limit. If v12b_ctx runs slower per task, lower `max_time_minutes` so the worst case stays under 10 h.
4. **Quota.** L4 quota is the scarce resource: about 2.5 h left this week against about 10 per 74-task run. All screening goes on the A6000 box. L4 gets at most one 10-task probe.
5. **Small-model bonus (R2).** The E4B line is still open, which the model finding wrongly treats as closed. The free step is an A6000 E4B comparison with and without the rank-128 adapter, thinking on, counting `old_string not found`. Do not download the adapter without Carson's OK, and spend no slot until that step shows a clear drop. Expected gain is 0 to +1 public task. Reaching a leading 0.12 needs +2 to 3 over sub25's 0.08, so the chance is low.
6. **Sampling.** Compaction summary calls carry no sampling (T 1.0, top_k 64), and both replica servers use the default `--generation-config auto`. No bundle change.

## 2. Implementation specs for the top 3 candidates

Shared conventions:
- Each bundle is a copy of the base with only `prompts/system.md` changed. `agent.yaml`, `eval_config.yaml` and `configs/` stay byte-identical, with no new files.
- Each gets a bundle test modelled on `tests/test_v12b_ctx_bundle.py` that pins four things:
  - an exact one-file diff against the base;
  - the `{problem_description?}` placeholder appears exactly once;
  - the added characters stay under the stated budget;
  - the leakage test passes. Parametrise `BUNDLE` in `tests/test_v13_leakage.py`'s `deny_list()` and `leaks()`, which currently point at `submissions/v13`. If a plain English word is flagged, reword it rather than extend `GENERIC`.
- Build and ship only when the checkout is idle, via the A3-fixed `scripts/ship.sh`.

### Spec 1: B1, `submissions/v12b_ctx_sed` (`v12b_sed` if the base falls back)

Edit only `prompts/system.md` step 2.

Current (v12b_ctx):
`2. Read only the function that must change, with the read_file tool and always a start_line and end_line (at most 80 lines); never read a whole file. One or two reads are enough.`

Replace with:
`2. Read only the function that must change: run_command with `sed -n '120,175p' path/to/file.py` (take the line numbers from the grep -n hit, at most 60 lines per read, because a longer output is cut at 5000 characters). Do not give read_file a start_line or end_line: it sometimes drops them and returns lines 1-150. One or two reads are enough.`

The v12b fallback replaces "at most 150 lines" the same way.

Tests: the shared set, plus these.
- `sed -n` is present and the old "always a start_line and end_line" is absent.
- The `read_file` tool is still in `agent.yaml`'s tool list.
- Added text is under 200 characters net.
- Unit test for the counter in `eval/analysis/` (`silent_range_drops()`) on a fixture trace that carries the key `start_line"`. This counter also feeds the A1 audit.

Pre-registration:
- **Box gate (A6000, 74 tasks paced to L4). All must hold:**
  - sed share of range reads is at least 90%;
  - silent drops (keys `start_line"`, `end_line"`, `"end_line"`) are at most 3 per 74, against a baseline of 11.7 pooled;
  - sed outputs cut at 5,000 chars are at most 8 per 74;
  - mean calls per run are at most v12b_ctx plus 1;
  - `old_string not found` calls are at most 9 per 74;
  - solved is at least 25 (drop at ≤24).
- **L4 probe (optional, 10 tasks):** compliance, plus `nl` availability if `nl -ba` is needed instead.
- **Hidden:** one slot. Drop at ≤0.14 or any failed mechanism gate. Promote at ≥0.19. Between 0.15 and 0.18, keep the base as final and do not swap.
- **Fallback:** if the model stops writing line numbers before editing, switch the command to `nl -ba path | sed -n '120,175p'`. That is a new candidate with its own gate.

### Spec 2: B2, `submissions/v12b_ctx_literal`

Add one bullet to Rules, after the "never refactor or reformat" bullet:

`- Do what the issue says and nothing more. Give a new field, option or method exactly the name the issue uses. When a value comes from another object (a list, a dict, a number), store and pass on that value as it is; convert it to text only in the code that prints it. When the issue says to forward or delegate something, make the same call on the same underlying object that the nearest sibling method makes; do not answer from another object's state. Do not add a second behaviour the issue does not state. If an existing test fails only because it asserts the old behaviour the issue asks to change, that failure is expected: leave it, and never undo your edit or bend it to make that test pass.`

The wording leaves out `wrap`, `proxy`, `isatty`, `fileno`, `notes` and `safe_str`, per the verifier.

Tests: the shared set, plus a character-budget cap of about +700 characters. Add `tests/test_literal_patch_check.py` for a small script that counts patches storing a newly added attribute through `str()`, `safe_str()` or `join()`. Run it on the 19 known rich_3676 patches: 8 coerce and 10 do not.

Pre-registration:
- **Box swing screen, 4 runs per task:**
  - targets: rich_3676, 4077, 3777, 3470, 3718, 3043 and fastapi_5077;
  - controls: fastapi_11194, rich_2725, rich_3067, fastapi_9425.
- Keep going if:
  - coercing patches on 3676 are at most 1 of 4;
  - the controls score at least 14 of 16 (v12-family expectation is 15.5);
  - revert-own-edit events are 0 in the targets' 28 runs;
  - whole-74 box solved is at least 25.
- Drop if any control loses 2 or more of 4, or box solved is ≤24.
- Hidden thresholds are as in Spec 1.
- **Honest limit:** target solve gains are not resolvable at k=4 (binomial SD about 1.4 per 8 runs). The keep decision rests on the mechanism count and the controls.

### Spec 3: B3, `submissions/v12b_ctx_variant`

Add one bullet to Rules, after the empty-patch bullet:

`- If your check of the issue's example passes on the unmodified code, that example does not reach the bug: do not conclude that it already works and do not start reading other files. Take each `if` or `isinstance(...)` condition in the function you are about to change and write the input that makes it true, copying any value the issue puts in quotes or backticks exactly, quotes included ("3" is a str, not an int). Put the variants in one script so one run prints them all; the variant that fails is your reproduction.`

I dropped the task-shaped examples (bytes vs file, str vs type) so it stays generic.

Tests: the shared set, plus a budget cap of about +620 characters. Add a trace-analysis helper `first_variant_repro_time()` (the first script after a passing exit-0 repro that differs by a literal or argument), unit-tested on two fixtures.

Pre-registration:
- **Box screen, 4 runs per task** on fastapi_9425, 11194 and 15589 (12 runs).
  - Keep going if at least 8 of 12 write the branch-derived variant by 150 s. The baseline is about 40-50%, so this is measurable.
  - Controls: fastapi_14851 must score at least 3 of 4 (it is solved only by ending before the cap), and fastapi_5077 and rich_2725 must not lose 2 or more of 4.
  - Whole-74 box solved must be at least 25.
- Drop if the variant rate is under 65% (the rule is ignored) or any control fails.
- Hidden thresholds are as in Spec 1.
- Not worth a slot unless Spec 1 or 2 is already decided. B3's cost is mainly the compaction hit from the extra tokens. Verify with `compaction_l4.py` that compacted runs do not rise by more than 5 per 74.

## 3. Model options

Only four W4A16 QAT variants are allowed (31B, 12B, E4B, E2B). The validator rejects any other id, so the 26B-A4B MoE, the 27B and the bf16 builds are CLI-only, and no bigger or pruned model can be submitted. A bundle cannot reach the vLLM launch, so speculative decoding, an MTP drafter, KV dtype, layer skipping and early exit are all unreachable. A LoRA adapter only adds latency and would switch the LoRA path on. The only speed lever is fewer tokens or calls: decode is the binding resource (27.6 completion tok/s, 28 of 74 tasks capped at 5 min, 9.5 s per call). The 12B decodes about 1.9x faster (67 vs 35 tok/s, a forum figure I could not re-verify), but it solved 4 vs 9-11 of 31 public tasks, so 31B with T 0.2, budget 4096 and top_p 0.95 stays. The small-model bonus (E4B, R2) is separate and still undecided.