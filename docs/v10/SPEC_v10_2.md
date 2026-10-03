# v10.2 SPEC: a budgeted locator, a digest handoff, a one-round fixer loop, and the hidden-repo fixes

Written 2026-09-30 12:05 IST (06:35 UTC). This is a design: nothing under `submissions/` was created or edited, no
Kaggle submission, kernel push, pod or OpenRouter call was made ($0 of this workflow's $4 cap), and the golden HOLDOUT
split was not read. v10.1 (`submissions/v10`, sub6) is frozen; v10.2 is built in `submissions/v10_2` with the same 31-file
structure. Where this file and `docs/v10/SPEC.md` disagree, this file wins for v10.2; everything it does not mention is
v10.1 unchanged. The evaluation that decides whether v10.2 goes to a pod is pre-registered separately in
`docs/eval/V10_2_EVAL.md` and must be read with this file.

Labels: **MEASURED** (read from traces, runs or tests, source given), **ESTIMATE** (a model output; the model is named),
**INFERENCE**, **UNVERIFIED**. Evidence scripts written for this spec, all $0 and re-runnable from the repo root:
`research/v10_2_prereg/` (`cases.py`, `fnoise.py`, `lpower.py`, `chainveto.py`, `firstround.py`, `margins.py`, each
with its `.out`, the drafted prompts in `draft_prompts/`, and the test-model diff `test_v10_prompts_v102.diff`).

---

## 0. One screen

| id | change (v10.1 -> v10.2) | evidence (source) | golden metric it should move | expected (ESTIMATE) |
|---|---|---|---|---|
| L1 | Fixer's first call is `python3 /tmp/swe/status.py`; it ends the locator phase and prints a compact LOCATOR DIGEST (located, viewed, repro) | 5/54 P plans lost at stage end, 8/81 L+P cases (diag M1); fixer recovered only 3/5 | chain `f_hidden_pass` on lost-plan cases; enables L2 | lost-plan cases recovered 3/5 -> 4-5/5 |
| L2 | Locator closed by the helpers after 14 gated calls or at helper t >= 90 s; refusals carry a draft plan | 31/54 P locators > 12 calls; 153/838 P calls after the first stop line; gold definition shown by call 12 in 23/23 L, 39/45 P (diag T3) | `l_calls`, `l_l4_s`, `l_within_time`, `l_within_calls` | `l_calls` mean 15.5 -> 10-12; with L3-L4 `l_l4_s` -10 to -20 s (capsim bound -20.7 P, -23.3 L) |
| L3 | Reproduction budget in the locator: at most 2 attempts, "reply now" after a failing one | repro = 30-35 % of locator time; 28 L / 15 P attempts after a repro had already failed (diag T1) | `l_l4_s`; guard `l_repro_valid` | 44/76 L and 39/90 P attempts removable; `l_repro_valid` -0 to -2 cases of 30 |
| L4 | `run.py`: 3 probes before the plan, SAME RUN refusal, OFFLINE refusal, `python3 -c` literal-`\n` guard, stdin for bare interpreters | run.py 22-32 % of locator time; 30 SyntaxError calls in 10 cases; 7 dropped heredocs; 11 network calls (diag T2, M6) | `l_l4_s`, `l_calls`; X metrics unchanged | 113/135 L, 167/211 P probes beyond 2 removable |
| L5 | `grep.py` suggests the 3 closest real paths for a missing path; `locate.py`/`grep.py` refuse queries with no searchable words or an issue marker; `locate.py` stores its top 3 for the digest | 6 invented `--path` greps (rich_3067), 8 issue-number searches (rich_3105) (diag M3, M6) | `l_calls` | small; neither task is in the evaluation population |
| L6 | Locator prompt: FILES completeness rule, ALSO line, "no reasoning inside it", "never ask for more information", 2-attempt wording, the hard stop stated | M4 3 P, M5 3 P + 2 L, M2 5 P + 2 L, M1 heredoc runaways (diag) | `l_all_gold_files_named`, `l_gold_files_in_files_line`, `l_files_named_n` | headline +5 to +10 points (the +10 gate is not the central expectation, sections 9 and 13) |
| F1 | Fixer prompt: status first, lost-plan rule, ALSO rule, repair **2 -> 1 round** | repair net +1 vs noise +2, +40 % L4 s, +70 % tool calls (ABLATION_REPAIR_RESULTS); 2nd+ fixer round used in 4/87 B2 samples, 1 pass (`fnoise.out`) | `f_hidden_pass` (guard), `f_l4_s`, `f_calls`, `f_verify_rounds` | `f_hidden_pass` within +-0.03; `f_l4_s` -5 to -10 s |
| F2 | `verify.py` RED NEXT lines follow the per-stage repair budget (full verifies since the last `status.py`) | A0 compliance 12 % > 10 %: RED said "Fix the code, then run verify again" whatever the prompt said | edits after the budget (compliance) ~0 | fixer verify runs p90 3 -> 2 |
| F3 | `CONTEXT_TOKENS` 4,700 -> 4,600; the first-round control restated as status + 3 views + 2 edits + 1 verify | a status call first pushed v10.1's modelled first round past 4,700 (SPEC 14); fixer first rounds: edits p50 1, p90 2-3 (`firstround.out`) | `x_compaction_exceedances` = 0 | R95 B margins: fixer 1,037 -> 1,277, verifier 1,101 -> 1,231 (`margins.out`) |
| R1 | T1: slow imports are calibrated, never a false RED or a false "hangs on original" | hidden.md probe E (FAILS today) | none on public tasks (by construction) | insurance for ML-dependency repos |
| R2 | T2: scratch prefixes need a separator; a new root module imported by changed code ships | hidden.md probes F, I (FAIL today) | none on public tasks | insurance |
| R3 | T3: import check covers namespace, `python/`, `lib/`, `packages/*/src` roots; "not checked" is AMBER, never GREEN | hidden.md probe K (FAILS today) | none on public tasks | insurance |
| R4 | T6-lite: base tree skipped above 300 MB tracked or when free space < 3x its size (original side UNKNOWN) | hidden.md 5.2 item 5 (tmpfs, UNVERIFIED) | none on public tasks | insurance |
| R5 | T10: internal-tracker boilerplate stripped from locate queries | 0 of 74 public statements carry it (checked), hidden has Google vocabulary (hidden.md 0.2) | R98 recall identical | insurance |
| R6 | `BUDGET_SCALE` (1.0 in v10.2) and the cap-parity test; the 5.5-minute cap is a separate variant gated by sub6's T6 | speed.md rank 1, 7.3 | none (golden cannot see the cap) | +0.15 to +0.30 hidden tasks if T6 <= 10.70 h |
| R7 | T4: Linux parity job on `python:3.13-slim` | the scorer runs 3.13; CI runs 3.12 (hidden.md 5.2 item 6) | rung 1 | catches 3.13-only breaks |
| E1-E7 | Eval side, not the bundle: router model clock (diag C9), `*_l4_s` metrics, plan metrics, the L-to-F chain tool, scratch-rule parity, 3.13 job, the gate script | golden-L clock ran on OpenRouter retries: proxy/L4 latency ratio median 2.18, max 14.2; all 5 L caps were artefacts (diag T6) | makes `l_t_end`, `l_within_time`, `x_capped` L4 numbers | preconditions of the evaluation |

Unchanged on purpose: `agent.yaml`, every `sub_agents/*.yaml`, every `configs/gen_*.yaml`, `eval_config.yaml`, the setup,
verifier and submitter prompts, `SKILL.md`, `edit.py`, `install.py` (it prints v10.2 through `C.VERSION`). Section 10
lists what was considered and rejected, with the evidence.

---

## 1. Evidence base (what the design rests on)

### 1.1 The locator is the loss, in three parts (diag, `docs/v10/v10_2_locator_diag.md`)

- **Time (MEASURED on the faithful pod pair p1_v10, dev split, 54 tasks):** 50.6 L4 s mean (median 46, p90 83), 15.5
  calls (median 13); 31 of 54 locators make more than 12 calls, 24 more than 14 (`research/locator_diag/rows_all.json`).
  Seconds by kind: reproduction 30-35 %, `run.py` probing 22-32 %, `view.py` 12-19 %, `grep.py` 5-12 %, `locate.py`
  6-7 %. The gold definition is first printed at call 2 (median, 5-8 L4 s); 73 % (P) and 88 % (L) of locator time comes
  after it.
- **The brief's "mean locator end t = 129 s, 18.5 % capped" is a proxy artefact (MEASURED, diag sect. 2).** The golden
  router's retry back-off ran on the helper clock (`--l4-scale 0.934`, proxy/L4 latency ratio median 2.18, max 14.2).
  All 5 capped L cases had L4-projected locator times of 26-88 s. E1 fixes the instrument.
- **Plan quality (P's 19 misses of 54 on `l_all_gold_files_named`):** M1 plan lost 2 (+3 lost plans the metric counts as
  hits: the real hit rate is 32/54), M2 right file seen and another chosen 5, M3 gold never surfaced 2, M4 seen places
  left out 3, M5 the fix needs something the issue does not name 3, M6 no information 1, M7 incidental gold hunks 3.
  M8 (right place, wrong mechanism) is invisible to the headline: on 13 tasks where P named every gold file and the
  golden plan solves, the pipeline still failed 8.
- **Ranking is mostly fine.** The models' own first locate queries put the gold file in the top 3 in 73 % of 56 replays.

### 1.2 The fixer is not the loss, and its repair loop is not paying (MEASURED)

- Suite F with a golden plan: 21-23 of 28 (75-80 %) (`docs/eval/ABLATION_REPAIR_RESULTS.md`).
- Repair ablation: A0 (no fixer repair) 21/28, B2 (v10.1, 2 rounds) 22/28, A0' 23/28; net +1 against a noise net of +2;
  B2 costs 39.4 vs 28.1 L4-projected s (+40 %) and 9.4 vs 5.5 tool calls (+70 %). Verdict INCONCLUSIVE because 12 %
  of A0 samples repaired anyway: verify.py's RED text asks for another round whatever the prompt says.
- How the B2 fixer used its rounds (`research/v10_2_prereg/fnoise.out`): of 87 samples, 60 ran verify once (51 pass),
  15 twice (11 pass), 4 three or more times (1 pass), 8 never (3 pass). The second repair round was used in 4 of 87
  samples and preceded 1 pass.
- The fixer's first round before its first verify (`firstround.out`, A0/B2/A0'): views p50 1-2 (p90 4), edits p50 1
  (p90 2-3); 8-13 % of samples make 3 or more edits.

### 1.3 Hidden-repo defects the public set never exercises (MEASURED, `research/hidden.md` 5-6)

T1 (a 12 s import reads as "RED - import error (HANG)" and "hangs on original"), T2 (a new root module named
`templates_engine.py` or `template.py` is deleted by finalize and hidden by the submit guard), T3 (the import check is
skipped for namespace and `python/` roots and still prints "ok"). T4 (CI on 3.12 only), T13 (cap parity) and T10
(tracker boilerplate) are cheap. T5/T6 (base tree on tmpfs) are unprobed; R4 adds a size guard, not a sparse tree.

---

## 2. Bundle tree

`submissions/v10_2/` has exactly the 31 files of `submissions/v10/` (SPEC 1). Built by copying `submissions/v10` and then
editing only:

| file | change |
|---|---|
| `prompts/locator.md` | full text in 3.2 (L2, L3, L4, L6) |
| `prompts/fixer.md` | full text in 3.3 (L1, F1) |
| `skills/swe-tools/scripts/_swe_common.py` | constants, phase, gate, draft plan, scratch rule, guard patterns, `BUDGET_SCALE`, `sh(input=)` (5.1-5.3, 5.8, 5.11) |
| `skills/swe-tools/scripts/status.py` | phase-start form and LOCATOR DIGEST (5.2) |
| `skills/swe-tools/scripts/locate.py` | gate, `locate_top`, empty-query refusal, T10 cleaning (5.6, 5.10) |
| `skills/swe-tools/scripts/grep.py` | gate, closest paths, issue-marker refusal (5.6) |
| `skills/swe-tools/scripts/view.py` | gate only (5.3) |
| `skills/swe-tools/scripts/run.py` | gate, probe limit, SAME RUN, OFFLINE, `-c` guard, stdin, T1 default (5.5) |
| `skills/swe-tools/scripts/verify.py` | repro budget and texts, repair-budget NEXT lines (5.4, 5.7) |
| `skills/swe-tools/scripts/_swe_gate.py` | T1 calibration, T3 module names, T6-lite (5.8) |
| `skills/swe-tools/scripts/_swe_ckpt.py`, `finalize.py` | T2 separator rule and guard re-include (5.8) |

Every other file is byte-identical to v10.1. `VERSION = "v10.2"`. Stdlib only, Python 3.8 syntax (R01), preamble
unchanged (R02), no new helper flags (so `SKILL.md` and every `USAGE` stay as they are, R92, R93).

---

## 3. Prompts

### 3.1 Rules

All v10.1 prompt rules (SPEC 3, rules 1-11) hold unchanged: only `{problem_description}` and `{plan?}` placeholders (the
fixer has `{problem_description}` only), no backticks, tools named only where declared, helpers only inside
`python3 /tmp/swe/NAME.py` or the exact `run_skill_script(file_path=..., skill_name=...)` call, numbered steps start with a
verb, the shared blocks RECOVER, AMNESIA, TIME, HELPERS and EDITFORM byte-identical to v10.1. Two lints change:

- **R91 sizes:** locator at most 460 words and 2,850 chars; fixer at most 410 words and 2,600 chars; the others keep
  370 / 2,600 (submitter 1,300, setup 600). The limit exists for R94/R95, which section 6 re-derives with these sizes.
- **R96 phrases:** section 7, R144.

Measured on the drafted texts below (`research/v10_2_prereg/draft_prompts/`), placeholders excluded:

| stage | v10.1 words / chars | v10.2 words / chars |
|---|---|---|
| setup | 76 / 452 | unchanged |
| locator | 369 / 2,353 | 448 / 2,794 |
| fixer | 364 / 2,337 | 401 / 2,548 |
| verifier | 368 / 2,255 | unchanged |
| submitter | 185 / 1,198 | unchanged |

Checked on a scratch copy of the bundle with these two prompts (and `CONTEXT_TOKENS = 4600`), with the v10 tests pointed
at it through `G4_BUNDLE`: `tests/test_v10_prompts.py` 57 passed, 1 failed (`test_budget_model_unit`, whose hard-coded
v10.1 fixer mix `{"view": 4, "edit": 4, "verify": 2}` changes by design, R145); the 16 R89b helper-name tests of
`tests/test_v10_1.py` passed; `scripts/validate.py` said `OK model=gemma-4-31b-it-qat-w4a16-ct`. The size, phrase and
mix edits the test module needs are `research/v10_2_prereg/test_v10_prompts_v102.diff`.

### 3.2 `prompts/locator.md` (full text)

```
You are the LOCATOR, stage 2 of 5. Find the code to change in /workspace and write a reproduction; you edit nothing, the next stage does.

Issue:
{problem_description}

Helpers (read code only with these):
python3 /tmp/swe/locate.py "identifiers, error text and key words"
python3 /tmp/swe/grep.py "regex"   (source only; add --tests for tests)
python3 /tmp/swe/view.py FILE START END   or   python3 /tmp/swe/view.py FILE NAME   (NAME: function, Class or Class.method)
python3 /tmp/swe/run.py --timeout 20 "command"   (at most 3 runs before your plan)
Run every python3 /tmp/swe command with run_command; helpers are never tool names.
If a /tmp/swe helper fails with "can't open file" or "No such file", call run_skill_script(file_path="install.py", skill_name="swe-tools") once, then repeat it.
If your earlier tool results are gone (the context was shortened), run python3 /tmp/swe/status.py and continue from it.
Helpers end with the task time [t=...s]; the task stops at t=300s. Obey any LOCATOR, EDIT NOW, CONTEXT, FINISH or TIME line.

Steps (about 8 tool calls; reply by t=90s; the helpers stop answering after 14 calls or at t=90s):
1. Locate the issue's names and error text. If the issue is only a title, turn its words into code names first (proxy gives *Proxy classes, padding width gives *padding_width*). Never search issue numbers; never ask for more information (if nothing matches, reply FILES: none).
2. View the best candidates; grep exact names from the issue. A name the repository does not define comes from a dependency: python3 /tmp/swe/view.py --obj package.module.Name shows its source. Print real objects; never guess library types.
3. If a script can show the bug, write a reproduction that FAILS now: one # CLAIM line per behaviour the issue asks for, with its exact inputs and expected values; at most 25 lines and no other comments (no reasoning inside it):
python3 /tmp/swe/verify.py --repro-only <<'EOF'
from package.module import thing
# CLAIM 1: short description
out = thing("input from the issue")
assert out == "expected from the issue", repr(out)
EOF
It must say fails on original; if a claim passes on original, rewrite it once with another input shape, and if it passes again use REPRO: none. Assert exact text only if the issue states it.
4. Stop and reply with the plan (text only, under 120 words, starting with FILES:):
FILES: path:start-end (function) for every place to change: every use of a name you rename or remove, every function that must change with it, and where the siblings of a new name are listed (styles, options, settings)
ALSO: one other candidate you could not rule out, or none
CAUSE: one sentence
FIX: what to change, with the exact names, messages and signatures the issue gives
REPRO: fails on original, or none
TESTS: an existing test file for it
```

Line by line against v10.1, each with its evidence:

| line | change | evidence (diag) |
|---|---|---|
| Helpers header | "(read code only with these)" | L rich_3278 read_file 3 times; 5 read_file calls bypass the budget |
| run.py line | "(at most 3 runs before your plan)", enforced by L4 | T2: 135 L / 211 P probes |
| Steps header | states the hard stop (L2); the soft target stays "about 8" so the model does not anchor on 14 | T3 |
| step 1 | "never ask for more information (if nothing matches, reply FILES: none)" | M6 rich_3105: an apology plan (L), 28 calls with curl (P) |
| step 3 | "(no reasoning inside it)"; "if it passes again use REPRO: none" (L3) | M1/T5 rich_2725 in both runs; T1 13 attempts on rich_3676 |
| FILES line | every use of a renamed name, every co-changing function, where siblings are listed | M4 fastapi_14077, 14419, 14372, rich_3777; M5 rich_3676 (`default_styles.py`) |
| ALSO line | one runner-up | M2 fastapi_13920, 9425, requests_6644, rich_3935, 3472, L rich_3772 |

`l_plan_format` (FILES first, then CAUSE, FIX, REPRO, TESTS lines) is unaffected; the ALSO line is extra.

### 3.3 `prompts/fixer.md` (full text)

```
You are the FIXER, stage 3 of 5. Make the code change in /workspace now.

Issue:
{problem_description}

The locator's plan is the [locator] message below.

<EDITFORM>
<HELPERS>
View files only with python3 /tmp/swe/view.py FILE START END, search with python3 /tmp/swe/grep.py "regex" and run other code only with python3 /tmp/swe/run.py --timeout 20 "command".
<RECOVER>
<AMNESIA>
<TIME>

Steps (first edit by t=150s, stop editing by t=210s):
1. Run python3 /tmp/swe/status.py first; it prints the LOCATOR DIGEST. If the [locator] message does not start with FILES: or names no file, the plan was lost: use the digest, or if it is empty run python3 /tmp/swe/locate.py "key words". View the plan's FILES.
2. Make the smallest COMPLETE change: every place the plan lists, the exact names, messages and signatures the issue gives, the style of the neighbouring code, unchanged behaviour for other inputs. The current code IS wrong: never conclude that nothing needs changing. Change an ALSO place only if verify still fails.
3. Run python3 /tmp/swe/verify.py and act on it, at most 1 round: a CLAIM that still fails means fix the code (not the reproduction); SIBLINGS means make the same fix where the same defect is; SPEC GAPS means add what is missing; for REGRESSIONS follow its note.
4. Stop and reply (text only, under 60 words):
CHANGED: file function (lines)
VERIFY: the first line verify printed
Never edit tests, conftest.py, pytest.ini, pyproject.toml, setup.cfg or tox.ini: graders replace them.
```

(`<EDITFORM>`, `<HELPERS>`, `<RECOVER>`, `<AMNESIA>`, `<TIME>` are the v10.1 blocks verbatim, SPEC 3.)

| line | change | evidence |
|---|---|---|
| step 1 | status first (phase marker and digest); the lost-plan rule covers text tool calls, empty replies and `FILES: none` | M1: 5/54 P plans lost, fixer recovered 3; T3 needs a phase marker (diag 4) |
| step 2 | ALSO is changed only if verify still fails | M2 fix idea (diag C7); keeps the smallest-change rule |
| step 3 | "at most 1 round" (was 2) | 1.2: the 2nd round was used in 4/87 B2 samples with 1 pass; the verifier keeps its 2 rounds, and finalize its best checkpoint |

### 3.4 Setup, verifier, submitter, SKILL.md

Byte-identical to v10.1. The verifier keeps "at most 2 repair rounds, none after t=240s": its rounds run after the first
attempt exists and checkpoints protect it, so they do not compete with locating or the first attempt (the time this
design wants back), and the verifier loop was never measured (suite F scripts the verifier). The verifier's first step is
already `status.py`, so F2's per-stage count works for it unchanged.

---

## 4. Stage configs, agent tree, eval_config

- `agent.yaml`, `sub_agents/*.yaml`, `configs/gen_*.yaml`: unchanged. Temperature 1.0 stays (T 0.2 is S3's factorial lever,
  PATH_TO_020 C2). The locator's `max_output_tokens` stays 768: 512 would truncate 7-13 reproduction calls per 74 tasks
  (speed.md 8.1), and the plan bound it sets is what R95 B already assumes.
- `eval_config.yaml`: unchanged, `{max_time_minutes: 5, timeout_seconds: 180, max_tool_calls: 100, max_turns: 200}`.
- **The 5.5-minute cap is a variant, not v10.2.** `scripts/make_variant.py submissions/v10_2 OUT --cap 5.5` (a new lever)
  sets `max_time_minutes: 5.5` and `BUDGET_SCALE = 300 / 330` (R6, 5.11). It is built only when sub6's submit-to-COMPLETE
  time T6 is at most 10.70 h (speed.md 7.3) and a candidate's rung-5 mean agent time is at most 159 L4 s/task
  (PATH_TO_020 C11). Golden evals cannot see the cap (the router caps the live stage), so they do not decide it.

---

## 5. Helpers

### 5.0 New constants (`_swe_common.py`)

```
VERSION = "v10.2"
LOC_MAX_CALLS = 14        # gated helper calls the locator phase may run (the 15th is refused)
T_LOC_CLOSE = 90          # helper t at which the locator phase closes (reply by t=90s in the prompt)
LOC_MAX_RUNS = 3          # run.py commands executed in the locator phase
LOC_MAX_REPROS = 2        # new reproductions (--repro-only with text) in the locator phase
STATUS_START_CAP = 800    # chars of the phase-start status output
BUDGET_SCALE = 1.0        # 300/330 only in the --cap 5.5 variant (R6)
BASE_MAX_MB = 300         # tracked baseline size above which no base worktree is made (R4)
CONTEXT_TOKENS = 4600     # was 4700 (F3, section 6)
GATED = ("locate", "grep", "view", "run", "repro")
```

Why 14 and 90 (MEASURED, `research/locator_diag/postfind.json`): the gold definition was first printed after call 14 in
0 of 23 L and 5 of 45 P locators (fastapi_14487, fastapi_14851, rich_3105, rich_3470, rich_3535; 3 of those 5 were
headline hits). Moving the cap to 16 keeps the same 3 at risk and saves less (capsim 19.9 vs 20.7 L4 s in P). On the
scorer the helper clock is real time, so at a hidden stretch k = 1.9 the 90 s close falls at about 47 public-equivalent
seconds, just above P's median locator (46 s); speed.md's 60 s stop was not taken because it would fall at about 32.

### 5.1 Phase marker (L1; `_swe_common.ctx_next`, `status.py`, `edit.py` unchanged)

- The context meter's phase (`state.ctx.phase`) goes `locator -> fixer` at the first `status.py` call (new; v10.1 kept
  `locator`), `fixer -> verifier` at the next (unchanged), and `locator -> fixer` at the first `edit.py` (unchanged, so a
  fixer that skips status still reopens the helpers). Every `status.py` call restarts the meter (unchanged) and resets
  `state.vsince` (F2).
- The locator phase is "open" while `phase == "locator"`. Nothing else stores it.
- A locator that is compacted and follows AMNESIA ends its own phase; the phase-start output then tells it to reply
  (5.2). With the close at 14 calls a locator compaction is near impossible: R95 B leaves the locator 2,693 tokens.

### 5.2 `status.py` phase-start form and LOCATOR DIGEST (L1)

When the call ends the locator phase (phase was `locator`), `status.py` prints this form instead of the v10.1 one, capped
at `STATUS_START_CAP` (800 chars, footer included):

```
STATUS [t=64s] helpers v10.2 | locator closed after 12 helper calls | repro: 2 claims (fails on original) | checkpoints: 0
LOCATOR DIGEST (what the locator's helpers showed; a locator replies with its plan now, the fixer starts from it):
  located: rich/text.py (Text.divide), rich/cells.py (cell_len), rich/segment.py (Segment.split_cells)
  viewed: rich/text.py 1040-1102 (Text.divide); rich/cells.py 20-60 (cell_len)
  repro: fails on original (2 of 2 claims), saved; python3 /tmp/swe/verify.py runs it
DIFF: no source change
[t=64s]
```

- `located`: the last `locate.py` call's top 3 files with their top symbol (`state.locate_top`, written by locate.py).
- `viewed`: at most 3 source files, newest first, each with its latest real view range and the enclosing def of the range
  midpoint from the cached index (`_swe_index`, marshal cache only, 150 ms budget; the def is omitted when the cache is
  absent). Test files never appear.
- `repro`: from `state.repro` (the v10.1 summary) plus "saved; python3 /tmp/swe/verify.py runs it", or `repro: none`.
- Empty state: `LOCATOR DIGEST: no locator activity recorded (no locate, view or reproduction).`
- A non-empty tree (the locator edited, or `edit_file` was used) still gets its diffstat line and the unscored EDITED
  checkpoint (v10.1 R123); the diff body is not printed in this form (the fixer views what it needs).
- Every later `status.py` call prints the v10.1 form (SPEC 4.13) unchanged.
- Budget: 500 ms or less (R27); output within `STATUS_START_CAP`, and the adversarial case (60 views, 200-char paths,
  non-ASCII names) stays within it by dropping `located` first, then `viewed` entries.

### 5.3 Locator close and draft plan (L2; `_swe_common.loc_gate`, called by the gated helpers)

- `loc_gate(kind)` runs in `locate.py`, `grep.py`, `view.py`, `run.py` and `verify.py --repro-only` after argument parsing
  (so USAGE errors still print) and before any subprocess. It returns `None` (and counts the call in `state.loc.calls`)
  or a refusal text. It is a single state read plus, on a pass, one `state_update`.
- It refuses only while `phase == "locator"` and either `state.loc.calls >= LOC_MAX_CALLS` or `clock() >= T_LOC_CLOSE`.
  `install.py`, `status.py`, `edit.py`, plain `verify.py` and `finalize.py` are never gated; no helper is gated in any
  later phase.
- Refusal (first and second consecutive), at most 600 chars, the footer's hint line suppressed (the `[t=Ns]` line kept):

```
LOCATOR CLOSED at t=93s after 14 calls: nothing ran. Locator: reply now with your plan; a draft from your calls:
FILES: rich/text.py:1040-1102 (Text.divide); rich/cells.py:20-60 (cell_len)
REPRO: fails on original
Any later stage: run python3 /tmp/swe/status.py first, then repeat this call.
[t=93s]
```

- Draft FILES: up to 2 files ranked by the number of real views (ties: the latest), each with its latest real view range
  and enclosing def; else the first `locate_top` entry with its symbol span; else `FILES: none seen`. Draft REPRO:
  `fails on original` when a valid claim failed or hung on original, else `none`.
- Third and later consecutive refusals: `LOCATOR CLOSED: nothing ran. Reply with your plan now (the draft is above); a
  later stage runs python3 /tmp/swe/status.py first.` plus `[t=Ns]` (the refusal-loop guard; diag T3 risk (a)).
- A refused call starts no subprocess and writes nothing but `state.loc.refused`. Journal entry `{h: "gate", kind, why}`.
- Bypass: bare `run_command` shell and `read_file` cannot be counted (27 bare and 5 read_file calls in the diag); the
  prompt's "read code only with these" is the only lever, and X metrics watch it.

### 5.4 Reproduction budget (L3; `verify.py --repro-only`)

In the locator phase only:
- A call with new reproduction text (stdin or `--text`) is an attempt; `state.loc.repros` counts them. A third attempt
  does not run: `REPRO LIMIT: 2 reproductions tried; nothing ran. Reply with your plan and REPRO: <fails on original |
  none>.`
- After a result that fails or hangs on original, the body ends with `NEXT: reproduction saved. Locator: reply with
  your plan now; the next stages run it.`
- Passing claim, first attempt: `REPRO: claim n passes on original - it misses the bug; rewrite it once with another
  input shape, and if that passes too, reply with REPRO: none.` Second attempt: `REPRO: claim n passes on original - it
  misses the bug; 2 reproductions tried: reply with your plan and REPRO: none.`
- Claims not finished at `t >= T_LOCATOR`: `REPRO: the claims did not finish in time on original; reply with your plan
  and REPRO: none.` (v10.1 said "pipe the reproduction again" at any time; L rich_3518 retried 4 times at t = 287-299.)
- Outside the locator phase `--repro-only` is unlimited and its texts are v10.1's.
- Measured bound (diag capsim): stopping at the first failing attempt with at most 2 attempts removes 44 of 76 L and 39
  of 90 P attempts, and loses 1 L (rich_3772, invalid on gold anyway) and 5 P late-but-failing reproductions
  (fastapi_13920, 14301, 5077, 9753, rich_4075). Guard G6 in the evaluation watches this.

### 5.5 `run.py` (L4, plus R1's timeout)

Checks run in this order, each before any subprocess; the first that applies prints its line and `[t=Ns]`:
1. `loc_gate("run")` (5.3).
2. **Probe limit**, locator phase only: `state.loc.runs >= LOC_MAX_RUNS` gives `PROBE LIMIT: 3 runs used before the
   plan; nothing ran. Locator: reply with your plan; the fixer can run code after python3 /tmp/swe/status.py.`
3. **OFFLINE**, any phase: a command whose words include `curl`, `wget`, `pip install`/`pip3 install`/`pip download`,
   `python -m pip install`, `uv pip install`, `apt install`/`apt-get install`, `conda install`, `npm install`, or git
   `fetch`/`pull`/`clone`/`push`/`ls-remote`: `OFFLINE: the sandbox has no network; nothing ran. Use the repository and
   its installed packages (python3 /tmp/swe/view.py --obj NAME shows a dependency's source).` Offline git (`log`, `show`,
   `diff`, `status`) runs as before.
4. **SAME RUN**, any phase: the key is `sha1(command | diff_sha)`; when the same key already ran twice with the same output
   sha: `SAME RUN: this command already ran twice on this tree with the same output (t=Ns, t=Ms); nothing ran. Change the
   command or the code.` (v10.1 ran it a third time and then appended "same output 3 times"; L rich_4006 repeated one
   command 20+ times.) `state.runs` keeps the last 50 keys.
5. **`python3 -c` guard**: when the command is `python`/`python3` with `-c CODE`, CODE contains a literal backslash-n and
   `compile(CODE)` raises SyntaxError: `PYTHON -c: the code has literal \n sequences, which Python cannot parse; nothing
   ran. Pipe multi-line code instead: python3 /tmp/swe/run.py python3 <<'EOF' ... EOF`. Code with real newlines, or code
   that compiles, runs as before (30 SyntaxError calls in 10 cases; L rich_3894 made 13 in a row).
6. **stdin for bare interpreters**: when the whole command is `python3`, `python`, `python3 -`, `python -`, `python3 -u`,
   `bash` or `sh`, run.py reads its stdin with `C.read_stdin()` (the 1 s select guard, R15) and passes it to the child
   through `sh(..., input=text)`; with nothing on stdin: `NO INPUT: python3 got no code on stdin; nothing ran. Pipe it:
   python3 /tmp/swe/run.py python3 <<'EOF' ... EOF`. Every other command keeps `stdin=DEVNULL` and never pays the 1 s
   guard (P rich_2943 got "(no output)" 3 times from a dropped heredoc, then lost its plan).
7. Run as v10.1. In the locator phase an executed command increments `state.loc.runs`. The default timeout is
   `max(RUN_DEFAULT, t_import + 15)` when R1 has measured `t_import`, and the TIMEOUT line adds `the package import alone
   takes Ns here` when `t_import >= 5`.

### 5.6 `grep.py` and `locate.py` (L5)

- `grep.py`: an explicit `--path X` that does not exist prints `GREP: 0 hits in 0 files (shown 0)` and `NOTE: --path X does
  not exist; closest: a, b, c (nothing searched)`; a later positional word that looks like a missing path keeps v10.1's
  NOTE and adds `closest: a, b, c`. Closest = `difflib.get_close_matches` over tracked `.py` paths and their directories
  (cutoff 0.5, at most 3). A regex that is only an issue marker (`#123`, `gh-123`, `issue 123`, `issue #123`) is refused:
  `GREP: issue numbers are not in the code; nothing ran. Search the names and words of the issue.` A bare number still
  runs (HTTP codes are legitimate searches) and, with 0 hits, adds `NOTE: issue numbers are not in the code.`
- `locate.py`: when the cleaned query has no terms (only issue numbers, URLs, hashes or stop words):
  `LOCATE: no searchable words (issue numbers, URLs and hashes are not in the code); nothing ran. Search the names and
  words of the issue.` Every successful call writes `state.locate_top = [[path, top symbol, start, end], ...]` (3 files).
- R98 recall is unchanged by construction: no ranking code changes.

### 5.7 Repair-budget NEXT lines (F2; `verify.py`, `_swe_gate.verdict`)

- `state.vsince` counts full `verify.py` calls (not `--repro-only`) since the last `status.py`, including `SAME AS LAST
  RUN` answers (the verifier's first verify of the fixer's tree is usually one, and it is where the verifier's first repair
  starts). The memo stores the verdict; the NEXT line is recomputed from `vsince` at print time.
- RED lines (claims, import, collection, hang-now and regressions alike) by `k = vsince` after this call:
  - `k = 1`: v10.1's line (`NEXT: claim n still fails (sig). Fix the code, then run python3 /tmp/swe/verify.py again.`).
  - `k = 2`: `NEXT: claim n still fails (sig). Fixer: your repair round is used; reply with your notes. Verifier: fix the
    code, then run python3 /tmp/swe/verify.py again.`
  - `k >= 3`: `NEXT: claim n still fails (sig). The repair rounds are used: run python3 /tmp/swe/finalize.py now; it keeps
    the best checked version.`
  - The regression sentence (the old-behaviour rule) is kept on every RED regressions line.
- The same three forms replace `STOP re-running verify; decide now.` on the third identical run.
- GREEN, AMBER and NO SOURCE CHANGE lines are unchanged. `undo` and `must fix` still never appear (R62).
- Result: the fixer's prompt (1 round), the verifier's prompt (2 rounds) and verify.py's text agree. In the ablation the
  RED text alone made 12 % of the no-repair arm repair.

### 5.8 Robustness items (R1-R4)

**R1, T1 slow imports (`_swe_gate`, `verify.py`, `run.py`).** Lazy calibration, so fast repositories pay nothing:
- Claims and the import check first run with the v10.1 budgets.
- When an original-side claim or the import check HANGs, measure `t_import` once per task: one subprocess importing the
  top-level packages involved, under `grader_env(base or ws, "orig")`, budget `real_budget(60)`. Store
  `state.t_import` and the modules.
- When `t_import >= 0.5 x` the budget that hung, re-run only the hung items once with
  `max(v10.1 budget, 2.5 x t_import + 2)`, clamped by `real_budget` and `VERIFY_TOTAL`; the new result replaces the HANG.
  Later calls use the calibrated budgets directly.
- A current-side import HANG is RED only when the original side imported within the same budget; otherwise the line is
  `IMPORT: UNKNOWN - the package import takes Ns on original too (slow dependency); not an error in your change` and the
  verdict is at most AMBER. `REPRO: ... hangs on original` is printed only when the claim still hangs with the calibrated
  budget.
- On the genuine public hang bugs (rich_4006, rich_3772, rich_3480, whose tests hang on the empty patch, R105) a
  reproduction that hangs on original triggers the calibration once; `rich` imports in well under a second
  (INFERENCE, to be measured by R138's fast-repo case), so no budget changes and the HANG stands.

**R2, T2 scratch prefixes (`_swe_common`, `_swe_ckpt`, `finalize.py`, submit guard).**
- `_SCRATCH_ROOT = ^(repro|reproduce|scratch|debug|tmp|temp|try|demo)(?=$|[-_.0-9])` (case-insensitive): `repro.py`,
  `reproduce_issue.py`, `tmp_check.py`, `scratch.py`, `debug_out.log`, `demo2.py` stay scratch; `template.py`,
  `templates_engine.py`, `tmpl.py`, `temperature.py`, `debugger.py`, `trying.py`, `reproducible.py` are not.
- `root_module_kept()`: a new root module that a changed tracked file imports is kept whatever its prefix
  (`demo_data.py` imported by `app.py` ships).
- Guard: `GUARD_ROOT_PREFIXES` become `/<ci(prefix)>`, `/<ci(prefix)>[-_.0-9]*` patterns; every kept new root module or
  new root directory that tracked code references gets a `!/<name>` re-include line in `<gitdir>/swe_exclude` (finalize and
  edit.py re-arm it), so `git add -N . && git diff _swegemma_baseline` carries it.
- 0 of 129 competition and 0 of 476 Pallets gold patches add a root module with a scratch-like prefix (PATH_TO_020 C3):
  this is insurance, and it must not change any public outcome.

**R3, T3 import check roots (`_swe_gate.repo_tops`, `module_name`).** For each changed `.py` file, the candidate roots are
the workspace, `src/`, every workspace directory listed in a `.pth` file the grader env loads, and every `PYTHONPATH`
entry under the workspace. The module name is the dotted path below the deepest root for which
`importlib.util.find_spec(name).origin` (in the import-check child) is the file itself; PEP 420 namespace packages
qualify. When no root gives a name, the line is `IMPORT: not checked for pkg/mod.py (no importable module name)` and a
GREEN verdict becomes `AMBER - import of pkg/mod.py not checked`. Flat and `src/` packages (every public repo) derive
the same names as v10.1.

**R4, T6-lite base tree (`_swe_gate.base_tree`).** Before `git worktree add`, sum the blob sizes of `git ls-tree -r -l
<baseline>`; when the sum exceeds `BASE_MAX_MB` or the free space of `$SWE`'s filesystem (`os.statvfs`) is below 3x the
sum, make no base tree: the original side is `UNKNOWN (base copy skipped: tracked tree N MB, free M MB)`, never a crash.
Original claim results cached from the empty-tree run (the locator's) are still used. Below the limit the base tree is
v10.1's exactly. Public repositories are far below it.

### 5.9 Output caps

| output | cap (chars) | note |
|---|---|---|
| status phase-start form | 800 | new; the v10.1 status form keeps 2,200 |
| LOCATOR CLOSED, PROBE LIMIT, REPRO LIMIT, SAME RUN, OFFLINE, PYTHON -c, NO INPUT, issue-number refusals | 600 | footer `[t=Ns]` included; the hint line is suppressed |
| every other helper output | v10.1 `CAPS` | unchanged |

All new strings go through `emit()` and `CAP_TOKENS`, and name helpers only as full commands (R89b runtime pass).

### 5.10 T10 query cleaning (R5; `locate.clean_query`)

Lines matching `^\s*(BUG|TESTED|RELNOTES|DELTA|PiperOrigin-RevId|Change-Id|Reviewed-by|Reviewed-on|Signed-off-by|
Co-authored-by)\s*[:=]` are dropped, and `b/\d{4,}` and `cl/\d{4,}` tokens are removed. MEASURED: none of the 74 public
statements contains any of these (checked 2026-09-30), so R98 recall on public tasks is identical.

### 5.11 `BUDGET_SCALE` and cap parity (R6)

`clock_scale()` returns `pod_scale x BUDGET_SCALE` (clamped 0.2..5 as before), so every threshold (LOCATOR 75, close 90,
EDIT NOW 150, FINISH 210, TIME 250, finalize and submit 285, cap 300) keeps its meaning in helper time and the prompts
stay unchanged. v10.2 ships `BUDGET_SCALE = 1.0`; the `--cap 5.5` variant sets `300 / 330`. The parity test pins
`BUDGET_SCALE x 60 x max_time_minutes == CAP_S` for every bundle under `submissions/v10*`.

### 5.12 State schema additions (`$SWE/state.json`)

```json
{"loc": {"calls": 0, "runs": 0, "repros": 0, "refused": 0, "close_t": null, "close_why": null},
 "locate_top": [["rich/text.py", "Text.divide", 1040, 1102]],
 "vsince": 0,
 "t_import": null, "t_import_mods": [],
 "runs": {"<sha1(cmd|diff_sha)>": [[12.0, "<out sha1>"], [20.5, "<out sha1>"]]}}
```

Defaults are filled by `_fill()`, so a v10.1 state file (a task restarted mid-run cannot mix versions, but tests may) loads
without error. A `ws` or baseline mismatch still resets everything (R19). A RECOVER install does not reset `loc`.

---

## 6. Context budget (R94, R95 re-derived; MEASURED on the drafted prompts, `research/v10_2_prereg/margins.out`)

The fixer's permitted mix gains the phase-start status call (typical 600 chars, cap 800) and loses a repair round:
`status_start 1, view 3, edit 3, verify 1` (v10.1: view 4, edit 4, verify 2). The status call is metered: it restarts the
meter and its own output counts, so B, C and D keep their meaning. `CONTEXT_TOKENS` drops from 4,700 to 4,600.

| stage | worst stage start (tokens) | B margin v10.1 | B margin v10.2 | C margin v10.1 / v10.2 | D (<= 30,720) v10.1 / v10.2 |
|---|---|---|---|---|---|
| locator | 6,213 -> 6,343 | 2,693 | 2,693 | 2,290 / 2,258 | 16,272 / 16,401 |
| fixer | 6,967 -> 7,029 | 1,037 | **1,277** | 797 / 833 | 20,112 / 17,353 |
| verifier | 7,301 | 1,101 | **1,231** | 866 / 964 | 20,830 / 20,830 |
| setup, submitter | unchanged | 8,400 / 7,217 | same | same | same |

- R94: every stage start stays at or below 8,000 (worst: verifier 7,301).
- R95 B needs at least 1,000: fixer 1,277 and verifier 1,231 pass with more room than v10.1 had.
- **First-round control, restated.** v10.1 modelled a typical first fixer round as 3 views, 3 edits and 1 verify
  (4,597 estimated tokens, under 4,700). A status call first adds about 260-330 estimated tokens, which is why SPEC 14
  declined it. v10.2 models the measured first round: status + 3 views + 2 edits + 1 verify = 4,405 (with status at its
  800-char cap), under 4,600. Evidence: before their first verify, F fixers made edits p50 1, p90 2-3, views p50 1-2,
  p90 4 (`firstround.out`). The trade: a first round with 3 or more edits (8-13 % of samples) now sees CONTEXT at its
  verify and gets one more edit before replying, which is F1's one-round budget anyway.

---

## 7. Requirement registry additions (R131-R148)

Every test module keeps the autouse `no_orphans` fixture (R120). Every change below lists a base case and its edge cases.
The bugs this version fixes each have a named regression test: B1 run.py dropped piped stdin (R134e), B2 `-c` with
literal `\n` looped (R134d), B3/B4 slow import read as a HANG (R138), B5 scratch prefixes deleted real modules (R139),
B6 skipped import check printed "ok" (R140), B7 RED text contradicted the repair budget (R137), B8 golden router clock
ran on retries (E1 tests, section 8).

| ID | requirement | tests (base; edges) | tier |
|---|---|---|---|
| R131 | Phase marker and digest (5.1, 5.2) | TRS::test_status_phase_start_digest (views, locate, failing repro); edges: empty state prints "no locator activity"; second call prints the v10.1 form; adversarial 60 views, 200-char and non-ASCII paths stay within 800 chars; no index cache omits defs within 500 ms; non-empty tree keeps the EDITED checkpoint; ctx phase goes locator -> fixer -> verifier | CI |
| R132 | Locator close (5.3) | T102::test_close_at_call_15 and test_close_at_t90 (`SWE_FAKE_CLOCK`); edges: each gated helper refuses with no child process (instrumented) in under 150 ms; install, status, edit, plain verify, finalize never refused; status and edit reopen; fixer phase never refused; 3rd consecutive refusal is the short form; draft plan names the most-viewed file and its def, falls back to locate_top, then "none seen"; a RECOVER install keeps the counters; refusals within 600 chars and helper-name clean | CI |
| R133 | Reproduction budget (5.4) | TV::test_repro_budget_locator; edges: 3rd attempt refused with the right REPRO word; re-running the saved repro (no text) is not an attempt; the fail-then-reply NEXT line; pass texts for attempts 1 and 2; not-finished text before and after t=75; unlimited and v10.1 texts after the phase marker | CI |
| R134 | run.py checks (5.5) | TRS::test_run_probe_limit, test_run_same_run, test_run_offline, test_run_c_literal_newline, test_run_bare_interpreter_stdin; edges: probe limit only in the locator phase; SAME RUN keyed on the tree (an edit between runs lets the 3rd run); `git log`/`git diff` not refused; `-c` code with real newlines, or that compiles, runs; a bare `python3` with an open silent stdin returns NO INPUT within 1.5 s; a non-interpreter command never reads stdin (0 ms extra, instrumented); R26 killpg still holds with input | CI |
| R135 | grep suggestions and refusals (5.6) | TL::test_grep_missing_path_closest; edges: `--path` and positional forms; no close match prints no list; `#3104`, `gh-3104`, `issue 3104` refused; bare `404` runs; 0-hit number adds the note | CI |
| R136 | locate refusal, locate_top, T10 (5.6, 5.10) | TL::test_locate_empty_query_refused, test_locate_top_state, test_locate_tracker_boilerplate; edges: `#3104 see #3104` refused; T10 fixture ranks the identifier's file first; R98 recall on the 74 tasks identical to v10.1 (same ranks) | CI (R98 part per-task) |
| R137 | Repair-budget NEXT lines (5.7) | TV::test_next_lines_follow_repair_budget; edges: k counted per status call; SAME AS LAST RUN counts; RED import, regressions and hang-now forms; regression sentence kept; GREEN/AMBER unchanged; never `undo`/`must fix`; the third-identical STOP line replaced | CI |
| R138 | T1 slow imports (5.8) | TV::test_slow_import_not_a_hang[12s, 30s] (hidden probe E fixture); edges: a genuine `while True` import still HANG/RED; original also slow gives UNKNOWN not RED; no calibration subprocess on a fast repo (instrumented count 0); calibrated run.py default; all within `real_budget` | CI |
| R139 | T2 scratch rule and guard (5.8) | T102::test_scratch_separator_matrix, test_root_module_imported_ships (probes F, I); edges: `repro.py`, `tmp_check.py`, `scratch.py`, `debug_out.log` still removed and hidden; `demo_data.py` imported by a changed file ships through the harness's exact submit and fallback commands; R126, R127, R130 unchanged | CI |
| R140 | T3 import roots (5.8) | TV::test_import_check_namespace_and_roots (`nspkg/`, `python/pkg/`, `lib/pkg/`, `packages/a/src/a/`; probe K); edges: a raising module the repro does not import is RED or AMBER-not-checked, never GREEN; flat and src names identical to v10.1 | CI |
| R141 | T6-lite (5.8) | TV::test_base_tree_size_guard (sizes and free space injected through env overrides for tests); edges: exactly at the limit; below it the worktree equals v10.1's; skipped base gives UNKNOWN and still uses cached original claims | CI |
| R142 | `BUDGET_SCALE` and cap parity (5.11) | TB::test_cap_parity_every_bundle; edges: the --cap 5.5 variant fires FINISH/TIME/finalize at 231/275/313.5 real s; `real_budget` never exceeds the real time left; pod scale composes (1.7 x 0.909) | CI |
| R143 | Python 3.13 parity | `PY=3.13 V10_ONLY=1 scripts/linux_test.sh` (`python:3.13-slim`, `--cpus 2 --memory 4g`, `TEST_TMPDIR=/tmp`, `TMPDIR` unset) on `G4_BUNDLE=submissions/v10_2` | NIGHTLY |
| R144 | Prompt phrases (R96 update) | TP::test_prompt_rules_present; locator adds "the helpers stop answering after 14 calls or at t=90s", "(at most 3 runs before your plan)", "never ask for more information", "reply FILES: none", "ALSO:", "(no reasoning inside it)", "if it passes again use REPRO: none", "every use of a name you rename or remove"; fixer replaces "at most 2 rounds" by "at most 1 round" and adds "1. Run python3 /tmp/swe/status.py first", "LOCATOR DIGEST", "the plan was lost", "Change an ALSO place only if verify still fails"; sizes per 3.1 | CI |
| R145 | Context model (section 6) | TP::test_worst_case_stage_budget, test_context_meter_does_not_cut_a_normal_first_round (restated), test_budget_model_unit (fixer mix `{"status_start": 1, "view": 3, "edit": 3, "verify": 1}`); `permitted_mix` parses "at most N round(s)" | CI |
| R146 | Constants pinned (5.0) and every timeout still at most 110 s (R86) | TC::test_v102_constants | CI |
| R147 | Mock-LLM flows through the compiled bundle (R113 style) | TFL::test_flow_v102[i-iv]: (i) a locator making 20 calls gets refusals from call 15, replies, the fixer's status reopens, scripted gold resolves; (ii) a locator ending on a text tool call, then the fixer's digest names its viewed file; (iii) a fixer that views before status gets one refusal, runs status, proceeds; (iv) a compacted locator runs status and replies; every last prompt under 14,336 tokens | CI |
| R148 | Frozen trees | TB::test_frozen_unchanged adds `submissions/v10` = `4b8fa33eb41996b29bc81f34290abf8410908600a1a9005e7a300762ec5396fd` (v10.1 as submitted in sub6, computed 2026-09-30 with `tree_sha256`) | CI |

`T102` is a new module, `tests/test_v10_2.py`. The v10 suite runs on the new bundle with `G4_BUNDLE=submissions/v10_2`,
and on v10.1 unchanged; tests that encode v10.1-only values (the fixer mix, R91 sizes, R96 phrases, the SPEC section 3
size table) read the bundle's version and apply that version's values.

---

## 8. Eval-side changes (not in the bundle; preconditions of `docs/eval/V10_2_EVAL.md`)

| id | change | files | tests |
|---|---|---|---|
| E1 | **Router model clock (diag C9).** `run_suite.py --l4-clock {wall,model}` (default `wall`, the behaviour every earlier run had). With `model`, after each live upstream call (and each summariser call during the live stage-run) the router computes `m = 0.102 + 0.02815 c + 0.000921 u` seconds (time_model sect. 2; `u` = prompt tokens for the stage-run's first live call, else `max(0, p - p_prev - c_prev)`, as in `research/locator_diag/l4time.py`), sets `excess = latency - m`, moves the case's `$SWE/t0` forward by `excess` (atomic replace; found under `<case>/sbx/*/tmp/swe/t0`), and adds `excess` to the route. The live cap fires when `(now - t_live0 - excess_total) x scale >= 300 - t0`. The helper clock then reads `scale x (tool wall + sum of m)`: 429 back-off and slow proxy calls stop moving it, and `--l4-scale k` stretches the modelled L4 time by k. `run.json` records `l4_clock`; `--resume`, `compare` and `ablation` refuse mixed values. | `scripts/golden/router.py`, `run_suite.py`, `summary.py` | fake upstream with 20 s latency and c = 100: helper clock advances by m +- 0.5 s, not 20 s; a 45 s 429 storm does not move it; a fast upstream with 700 output tokens advances it by m (negative excess); cap at virtual 300; `wall` reproduces the pre-change router byte for byte on a recorded route; refusals on mixed runs |
| E2 | `l_l4_s`, `f_l4_s`, `v_l4_s` (numeric, lower): sum of m over the live stage-run's live calls plus the tool gaps between them | `eval/golden/golden_metrics.py`, `gen_config.py` output | reproduces `research/locator_diag/l4_L_dev_v101.json` per case within 0.5 s; inapplicable without router calls; `gen_config.py --check` |
| E3 | `l_files_named_n` (count of distinct `*.py`/`*.pyi` path tokens in the reply) and `l_gold_files_in_files_line` (binary: every gold file named on the reply's `FILES:` line, ALSO excluded) | same | ALSO-only hit scores 0 on the second, 1 on the headline; prose before FILES; no reply is inapplicable |
| E4 | **L-to-F chain.** `scripts/golden/chain_plans.py --l-run DIR --sample 0 --out PATH`: an F dev dataset whose `golden.plan` is the L run's sample-0 locator reply verbatim ('' when there is none), whose `golden.repro` is that run's last `--repro-only` heredoc when its result said fails or hangs on original (else null), `plan_source = chain:<run_id>:s0`, `fixture_sha` recomputed; it refuses holdout cases and L runs made on the holdout, and lists dropped tasks. `summary.py compare --pair-by-task` pairs by case id although `fixture_sha` differs, prints both shas, and labels the result CHAIN. | `scripts/golden/chain_plans.py` (new), `summary.py` | round trip on L_dev_v101; lost reply gives an empty plan; a failing repro is carried, a passing one is not; holdout refused; compare without the flag still drops differing fixtures |
| E5 | Scratch-rule parity: `golden_metrics.scratch_files` and `replay_l4.SCRATCH_ROOT` adopt R2's separator rule; `replay_l4.HINTS` gains LOCATOR CLOSED, PROBE LIMIT, REPRO LIMIT and SAME RUN for the obedience counts | `eval/golden/golden_metrics.py`, `scripts/replay_l4.py` | R2 matrix on both; recorded runs' `f_no_scratch` unchanged (no public patch has such a file) |
| E6 | `scripts/linux_test.sh` takes `PY=3.12` (default) or `PY=3.13` | `scripts/linux_test.sh` | `bash -n`, shellcheck, R143 |
| E7 | `scripts/golden/v102_gate.py L101 L102 F101 F102 [CHAIN101 CHAIN102]`: computes V10_2_EVAL.md's gates G1-G6, the chain veto and the spend check from the runs' `compare.json` and `run.json`, and writes the verdict; no judgement by hand | `scripts/golden/v102_gate.py` (new) | one synthetic compare pair per gate edge (exactly +0.10, exactly -0.05, +1 X count, a new crash class, a missing chain, spend over $4, > 5 % infra errors) |

---

## 9. What each golden metric is expected to do (the link between sections 3-5 and the evaluation)

| metric | changes that move it | direction and size (ESTIMATE, over the 30-case population of V10_2_EVAL.md) |
|---|---|---|
| `l_all_gold_files_named` (headline) | L6 FILES rule and ALSO line (up), L1-L3 draft plan and no-heredoc-reasoning (up), L2 close (down for late finds: fastapi_14487 and rich_3470 are in the population) | +5 to +10 points; central +7 |
| `l_gold_files_in_files_line` | L6 FILES rule; not the ALSO line | +0 to +5 points |
| `l_files_named_n` | L6 (ALSO adds about 1) | +0.5 to +1.2 |
| `l_calls`, `l_within_calls` | L2, L3, L4 | calls 15.5 -> 10-12 mean; within 12: about 45 % (L 12/27, P 23/54) -> 75 % |
| `l_l4_s`, `l_t_end`, `l_within_time` | L2-L4 (down), refusal replies (a few seconds up) | -10 to -20 s; within 90 s: about 85 % -> 95 % |
| `x_capped` | E1 (both arms), L2 | about 0 in both |
| `l_repro_fails_on_original`, `l_repro_valid` | L3 | -0 to -2 cases of 30 |
| `l_ended_by_text`, `l_plan_format` | L6 (no reasoning in heredocs), L2 draft | flat or up |
| X metrics | L2 refusals must not create invented tools or bare helper calls | flat |
| `f_hidden_pass` | F1 (1 round), L1 (status first), F2 | -0.03 to +0.03 |
| `f_l4_s`, `f_calls`, `f_verify_rounds` | F1, F2 | -5 to -10 s; calls -1 to -3; verify rounds p90 3 -> 2 |
| chain `f_hidden_pass` (end to end) | everything above plus M8, which no L metric sees | -1 to +2 cases of 30 |

Speed on hidden tasks is not measured by golden at k = 1: the 90 s close binds mostly at k >= 1.9. That is rung 4's job
(pod pair at `G4_L4_SCALE` 3.2, PATH_TO_020 S3(c)).

---

## 10. Considered and not taken (with the evidence)

| idea | decision | why |
|---|---|---|
| Setup runs `locate.py` with the issue's key words and hands the top hits to the locator through `output_key` | rejected | (1) The issue text lives only in session state (`problem_description`, harness_runtime 1), not in the sandbox, so `install.py` cannot read it; the setup model would have to copy words into a tool argument. (2) A title-only query puts the gold file in the top 3 in 20/36 (56 %), the models' own first queries in 41/56 (73 %) (diag 5). (3) The ranking reaches the locator only through setup's final text: about 150 output tokens (about 4 s on L4) for something the locator recomputes at call 1 in 26/27 L and 43/54 P. (4) The index builds and answers in under 0.3 s, so pre-warming saves nothing. (5) Setup's single exact call is what took helper availability to 1.00; a free-text argument reopens the INVALID_ARGUMENTS failure class (e74_v2: 94/107). What survives of the idea is L1: helper state carries the ranking to the fixer at no token cost |
| speed.md rank 2, a 60 s LOCATOR stop | replaced by 14 calls / 90 s | at k = 1.9 a 60 s stop falls at about 32 public s, below P's median locator (46 s); the gold definition was shown by 30 L4 s in 41/45 P, so 90 s keeps first sight and cuts the tail |
| speed.md rank 3, no probes and one attempt (prompt only) | replaced by helper-enforced 3 probes and 2 attempts | 9 of 52 solves got their valid reproduction only on a retry (speed.md 3.3); the prompt budget "about 8 calls" is exceeded in 31/54 P locators, so only helpers enforce |
| speed.md rank 4, an 80-word plan without REPRO and TESTS | deferred | smallest of the four (+0.04 to +0.21 hidden tasks); it breaks `l_plan_format` for the pairing and needs an F run with rewritten golden plans that the $4 cap cannot fund |
| Fixer repair 0 rounds (the A0 arm) | not taken | the pre-registered ablation rule said INCONCLUSIVE (net +1, p 0.5), and CUT needs net <= 0; the one-round trim removes the round with the least evidence (2nd round: 4/87 samples, 1 pass) and the F guard of the evaluation checks it |
| Verifier repair 2 -> 1 | not taken | its time comes after the first attempt exists (checkpoints protect it), so it does not buy locator time; it was never measured (F scripts the verifier) and V dev (about $1.60 for the wrong variant alone) does not fit the cap |
| C8 sibling-consistency diagnosis rule (M8) | deferred to v10.3 | invisible to the L headline; needs the chain (E4) or F-real first (diag) |
| locate.py compound-name boost | rejected | net neutral over 36 snapshots: fixes rich_3935 and rich_2943, breaks rich_3938, 3777, fastapi_14301, 9425 (diag rankexp) |
| locate.py light stemmer | deferred | +1 to +2 top-1 but rich_3180 rank 4 -> 10; hold for a larger check (diag stemexp) |
| `scripts/`, `tools/` down-weighting | rejected | no measurable change on the local snapshots (diag) |
| A larger view cap, or a "view the whole function" NEXT line in locate.py | deferred | T4 paging is real (78 of 298 P views cut) but a larger cap raises context, and the hint cannot be isolated by golden L |
| T11, source under nested `build/`/`vendor/` | deferred | the index lists tracked files only, so artefact dirs are rarely tracked; low value (hidden.md 6) |
| A full sparse base tree (T5/T6) | replaced by R4's size guard | a sparse tree changes the verify base on every task (PATH_TO_020 C9); the guard changes nothing below 300 MB |
| Locator `max_output_tokens` 768 -> 512 | rejected | truncates 7-13 reproduction calls per 74 tasks (speed.md 8.1) |
| Temperature 0.2 | out of scope | S3 factorial lever; the only direct test found no effect (PATH_TO_020 C2) |
| The 5.5-minute cap inside v10.2 | a separate variant | decided by T6 and C11, not by golden (section 4) |

---

## 11. Change list (the return value of this design step)

| id | change | targets | expected |
|---|---|---|---|
| L1 | status.py first in the fixer: phase marker plus 800-char LOCATOR DIGEST | fixer.md step 1; status.py; _swe_common.ctx_next; locate.py writes locate_top | lost plans recovered by the fixer; enables L2 |
| L2 | helper-enforced locator close at 14 gated calls or t >= 90 s with a draft plan | _swe_common.loc_gate; locate/grep/view/run/verify --repro-only; locator.md header | l_calls 15.5 -> 10-12; with L3-L4 l_l4_s -10 to -20 s; headline risk -0 to -2 cases |
| L3 | at most 2 reproduction attempts in the locator, reply after a failing one | verify.py --repro-only; locator.md step 3 | 44/76 L, 39/90 P attempts removable; l_repro_valid -0 to -2 |
| L4 | run.py: 3-probe limit, SAME RUN, OFFLINE, -c literal-\n guard, stdin for bare interpreters | run.py; _swe_common.sh(input=) | 113/135 L, 167/211 P probes beyond 2 removable; defects B1, B2 fixed |
| L5 | grep closest paths and issue-marker refusal; locate empty-query refusal | grep.py; locate.py | M3/M6 calls refused or redirected |
| L6 | locator prompt: FILES completeness, ALSO line, no reasoning in heredocs, never ask for more, FILES: none | locator.md | headline +5 to +10 points; files named +0.5 to +1.2 |
| F1 | fixer prompt: status first, lost-plan rule, ALSO rule, repair 2 -> 1 round | fixer.md | f_hidden_pass within +-0.03; f_l4_s -5 to -10 s |
| F2 | verify.py RED NEXT lines follow the per-stage repair budget | verify.py; _swe_gate.verdict | fixer compliance with its budget ~100 %; defect B7 fixed |
| F3 | CONTEXT_TOKENS 4,700 -> 4,600; first-round control restated | _swe_common; tests/test_v10_prompts.py | fixer B margin 1,037 -> 1,277; verifier 1,101 -> 1,231 |
| R1 | T1 lazy slow-import calibration | _swe_gate; verify.py; run.py | no false RED or false hang on 12-30 s imports; 0 cost on fast repos |
| R2 | T2 separator scratch rule, imported root modules ship, guard re-include | _swe_common; _swe_ckpt; finalize.py | probes F and I pass; public outcomes unchanged |
| R3 | T3 import check for namespace and non-src roots; not-checked is AMBER | _swe_gate | probe K passes |
| R4 | T6-lite base-tree size guard | _swe_gate.base_tree | no OOM path above 300 MB; public unchanged |
| R5 | T10 tracker boilerplate stripped from locate queries | locate.clean_query | R98 recall identical |
| R6 | BUDGET_SCALE (1.0) and cap parity; 5.5 as a make_variant lever | _swe_common.clock_scale; scripts/make_variant.py; tests | 5.5 cap buildable on the T6 rule |
| R7 | Python 3.13 Linux parity job | scripts/linux_test.sh | rung 1 covers the scorer's Python |
| E1 | golden router model clock (--l4-clock model) | scripts/golden/router.py, run_suite.py, summary.py | l_t_end, l_within_time, x_capped become L4 numbers |
| E2 | l_l4_s, f_l4_s, v_l4_s metrics | eval/golden/golden_metrics.py | time gate readable |
| E3 | l_files_named_n, l_gold_files_in_files_line | eval/golden/golden_metrics.py | guards the headline against the ALSO line |
| E4 | chain_plans.py and compare --pair-by-task | scripts/golden/chain_plans.py, summary.py | end-to-end proxy |
| E5 | scratch-rule parity and new hint counters | golden_metrics.py; scripts/replay_l4.py | metrics agree with the bundle |
| E7 | pre-registered gate script | scripts/golden/v102_gate.py | the verdict is computed, not read by eye |

---

## 12. Build order, gates, and a carve-out

1. **Eval side first (E1-E7)**, with tests, then `gen_config.py` and `gen_config.py --check`. Without E1 no paid L run
   is allowed (V10_2_EVAL.md P2): the v10.1 locators are longer than v10.2's, so the retry-driven cap would favour v10.2.
2. **Bundle:** copy `submissions/v10` to `submissions/v10_2`, then core (`_swe_common`, `status.py`, `run.py`), then locate
   (`locate.py`, `grep.py`, `view.py`), then verify (`_swe_gate`, `_swe_ckpt`, `verify.py`, `finalize.py`), then prompts.
   Each component's tests pass on the Mac before the next depends on it.
3. **Rung 1:** `py_compile` of every helper; `scripts/validate.py submissions/v10_2`; the full suite
   `.venv/bin/python -m pytest -q tests` on v10.1 (unchanged, frozen pins) and with `G4_BUNDLE=submissions/v10_2`;
   `G4_NIGHTLY=1`; `V10_ONLY=1 scripts/linux_test.sh` with `PY=3.12` and `PY=3.13`; `bash -n` and shellcheck on changed
   `.sh`; hidden.md's probe scripts (`research/hidden_probes/probe_layouts.py`, `probe_more.py`, `probe_imp.py`) against
   the v10.2 helpers: E, F, I and K pass; `scripts/pack_bundle.py submissions/v10_2 OUT` deterministic (not uploaded).
4. **Rung 2:** the pre-registered evaluation, `docs/eval/V10_2_EVAL.md`.
5. **Carve-out.** R1-R5 and R7 touch only `_swe_gate`, `_swe_ckpt`, `finalize.py`, the scratch/guard part of
   `_swe_common`, and `locate.clean_query`, none of which the locator package (L1-L6) or the fixer package (F1-F3) needs.
   If the evaluation says NOT READY on the locator gates, a `v10.1.1` = v10.1 + R1-R7 can be cut from the same code
   (PATH_TO_020 S2 and C9: hidden-only mechanics, eligible for an LB slot after rung 1, Carson's call).
6. Pods, Kaggle pushes and submissions stay Carson's call.

---

## 13. Risks and open questions

- **The headline gate is ambitious.** The remaining winnable misses in P were 12 of 54 (M1 2, M2 5, M3 2, M4 3); +10 points
  on 30 cases needs +3 net cases, about half of the winnable misses in the population. The central expectation is +7
  (section 9), so a FAIL on G1 is the likelier single outcome; V10_2_EVAL.md states the power.
- **The ALSO line inflates the headline mechanically** (a runner-up on ALSO counts as "named"). E3's metrics and G4 of the
  evaluation bound it; the chain (E4) is the only test of whether ALSO helps or distracts the fixer.
- **Refusal loops.** The model looped on "same output" notes before (T3). The short third refusal and the draft plan are
  the mitigation; X metrics and `l_calls` watch it; R147 (i) tests the flow.
- **Bypass through bare shell or read_file** cannot be blocked by helpers (27 bare, 5 read_file calls in the diag).
- **In-sample design.** The diagnosis read all 54 dev traces, and the population is drawn from that dev split, so the dev
  result is optimistic; the 19-task holdout is kept for one look at a final candidate, outside this workflow.
- **PROXY is not the scorer.** bf16 on OpenRouter with its tool parser; X metrics are indicative; FAITHFUL confirmation is
  rung 4-5.
- **Hidden-clock behaviour is untested here.** At k = 1 the 90 s close rarely binds; the 3.2-scale pod round measures it.
- **R1-R5 are insurance**, valued at 0 to +1 hidden task in total (PATH_TO_020 C3), unmeasurable on public tasks.
- UNVERIFIED: whether the scorer's vLLM caches the system prompt prefix (the locator prompt grew by about 130 tokens:
  about 0.1 s per stage if uncached once, more if every call re-prefills it).
