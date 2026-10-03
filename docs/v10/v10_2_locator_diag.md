# v10.2 locator diagnosis: why plans miss and where the locator's seconds go

Written 2026-09-30 10:15 IST. Input to PATH_TO_020 step S2 (v10.2). Read-only analysis: no Kaggle submission, kernel
push, pod or OpenRouter call was made ($0 of the $4 cap), and nothing under `submissions/`, `eval/golden/` or
`scripts/` was changed. Scripts and their outputs are in `research/locator_diag/` (section 9).
Labels: **MEASURED** (read from traces), **ESTIMATE** (a model output; the model is stated), **INFERENCE**.

Population, stated once and used everywhere below:

- **L** = golden run `eval/golden/runs/L_dev_v101`: 27 `ok` cases (all rich; fastapi is not runnable, `requests_6644`
  was skipped), v10.1 bundle, PROXY `google/gemma-4-31b-it` on Crusoe, `--l4-scale 0.934`. The two `infra_error` cases
  (rich_3468, rich_3480, upstream_http) were read but are not in any statistic.
- **P** = locator stages of the pod pair `eval/pair1/eval/runs/p1_v10` (v10.1, faithful compaction, helper clock on the
  L4 scale `G4_L4_SCALE=1.7`) on the **dev split only**: 54 of 55 dev tasks (fastapi_14986 has no trace), 23 fastapi,
  30 rich, 1 requests. The 19 holdout tasks of that run were not opened.
- Gold files and functions come from `eval/golden/datasets/L_dev.json`; hit rules are `golden_metrics._path_named` and
  the whole-word function rule of `l_gold_functions_named`.

## 0. Answers in one screen

| Question | Answer | Evidence |
|---|---|---|
| Is the golden-L clock an L4 clock? | **No.** OpenRouter 429 retries ran on the helper clock. Per-case proxy/L4 latency ratio: median 2.18, mean 4.15, max 14.2, against `--l4-scale 0.934`. All 5 "capped" cases had an L4-projected locator time of 26-88 s at the cap, and 17 of 27 locators saw LOCATOR or EDIT NOW before 75 L4-seconds (6 within their first 3 calls). `l_t_end`, `l_within_time` and `x_capped` of L_dev_v101 are not L4 numbers | sect. 2 (MEASURED) |
| How long does the locator really take? | **P (faithful): 50.6 s mean on the L4 clock, median 46, p90 83, 15.5 calls** (median 13). L projected from tokens: 58.6 s mean, median 44.7. At the brief's hidden stretch k = 1.9: about 96 s mean, p90 about 158 s | `stats.out` |
| Where do the seconds go? | Reproduction (`verify.py --repro-only`) 30-35 %, `run.py` probing 22-32 %, `view.py` 12-19 %, `grep.py` 5-12 %, `locate.py` 6-7 % | `attrib.out` |
| When does the answer appear? | The gold definition is first printed by a helper at **call 2 (median), 5-8 L4 s**. **73 % (P) and 88 % (L) of locator time comes after that** | `postfind.out` |
| Is `locate.py` ranking the problem? | **Mostly no.** Replaying the models' own first queries offline on 36 dev snapshots, the gold file is top-3 in 19/26 (L) and 22/30 (P) and top-1 in 14 of each. A search that never surfaced the gold file explains 2 of P's 19 misses | sect. 5 (MEASURED) |
| Why do P's plans miss gold files (19 of 54)? | Plan lost at stage end 2 (+3 lost plans that the metric still counts as hits), right file seen but another chosen 5, gold never surfaced 2, places it had seen left out 3, fix needs something the issue does not name 3, no information in the issue 1, incidental gold hunks 3 | sect. 3 |
| Is naming the file enough? | **No.** On the 29 dev tasks both P and F cover, 13 had every gold file named by P and a golden plan that F solves; **P still failed 8 of them**, and 7 of those 8 plans state a mechanism that differs from the gold one (the 8th plan was lost). `l_all_gold_files_named` does not see this | `fcompare.out`, M8 |
| What should v10.2 change? | (1) a helper-enforced locator budget with a draft plan, and `status.py` as the fixer's first step; (2) reproduction budget; (3) `run.py` probe budget and three `run.py` bug fixes; (4) plan-loss recovery in the fixer prompt; (5) two plan-content prompt rules. Caps (1)-(3) together remove at most **20.7 L4 s per task in P and 23.3 in L** (42-46 % of locator tool time; about 40 s at k = 1.9) | sect. 6, `capsim.out` |

## 1. Method

- Every L trace (`traces/L_dev.json`, grouped into stage-runs by `golden_metrics._ctx`) and every P locator stage
  (ATIF steps whose author is `locator`) was dumped call by call (`dumps/`, `dumps/p1/`) and read.
- A case counts as a **miss** when the plan does not name every gold file. Misses and all cases with a gold function
  miss were checked against the gold patch (`gold.py`). A gold hunk is **incidental** when it is a docstring, type hint,
  formatting or blank-line change, or a `pragma: no cover` list, and no hidden test node covers it.
- **L4 seconds.** L: per live call `0.102 + 28.15 ms x completion + 0.921 ms x uncached prompt` (research/time_model.md
  sect. 2) plus the proxy's tool gaps. P: deltas of the helper footers, which the pod already writes on the L4 clock.
- "Stop line" = the first helper output carrying `LOCATOR:`, `EDIT NOW:` or `CONTEXT:`.

## 2. The golden-L clock ran on OpenRouter retries (T6, an eval defect)

The helpers' clock is `(now - t0) x clock_scale` of the case sandbox (`_swe_common.clock`), and the router's retry
back-off happens in that wall time. L_dev_v101's mean live-call latency was 10.9 s (Kaggle L4 reference 2.88 s); the
F runs of the same day were worse (14.1-20.3 s). The run used `--l4-scale 0.934`, so a retry-heavy case ran its helper
clock 3-14 times faster than an L4 would.

| case (capped in L) | proxy latency sum | retries | slowest call | L4-projected locator s | what it was doing at the cap |
|---|---|---|---|---|---|
| rich_2725 | 376.6 s | 15 | 118.7 s | 88 | a loop of empty run_command calls (T5); the cap only interrupted it |
| rich_3067 | 410.5 s | 28 | 117.6 s | 68 | a reproduction loop (T1); the cap only interrupted it |
| rich_3470 | 349.4 s | 21 | 116.7 s | 26 | clean progress in rich/console.py (P, same task: plan names console.py and `_write_buffer`) |
| rich_3471 | 328.0 s | 18 | 118.2 s | 32 | gold `Text.append_tokens` found at call 1; probing with bare `python3 -c` |
| rich_3472 | 326.4 s | 22 | 114.0 s | 29 | pretty.py (locate rank 1); first call alone took 69.6 s |

- The cap is a proxy artefact in all five; three of them (3470-3472) were not in a loop. At k = 1 none would have
  reached t = 300; P, the faithful run, has no locator cap in 54 dev tasks (max 117 s).
- The pacing lines were wrong too: 17 of 27 locators got `LOCATOR: 75s used` or `EDIT NOW` while their L4-projected
  time was under 75 s, 6 of them within the first 3 calls (2725, 3105, 3470, 3472, 3518, 3521). The model mostly
  ignored them (T3), but the trajectories are not L4 trajectories.
- So the brief's "mean locator end t = 129 s, 55.6 % within 90 s, 18.5 % capped" describes the proxy. On the L4 model
  the same 27 locators end at 58.6 s mean and 23 of 27 within 90 s; the call counts (15.8 mean, 44 % within 12) are
  real.

**Fix (eval, not bundle).** Before S2's rung-2 gate is read: (a) add an `l_l4_s` metric to `golden_metrics.py` with the
token formula above (the ablation summary already has `l4_projected_s_mean` for F); (b) make the router advance the
sandbox's `/tmp/swe/t0` by `latency - L4-model latency` after each live call, so the helper clock and the t = 300 cap
run on the L4 model instead of on retries; (c) until then, compare arms only on call counts, `l_l4_s` and plan metrics.
S2's gate item "L4-modelled locator seconds down >= 15 s at the hidden clock" is only measurable after (a).

## 3. Plan-quality failure modes

Counts are cases; a case can carry several modes. The full per-case table is the appendix.

| mode | L (27) | P (54) | one-line description |
|---|---|---|---|
| M1 plan lost at the end of the stage | 3 | 5 | the stage ends on a text tool call, empty text, a thinking dump, or never replies |
| M2 right candidate seen, another chosen | 2 | 5 | the gold function was printed or viewed; the plan names a different place |
| M3 gold never surfaced | 0 | 2 | search vocabulary or ranking never showed the gold file |
| M4 places it had seen left out | 0 | 3 | FILES names the primary spot and omits a second place already on screen |
| M5 the fix needs something the issue does not name | 2 | 3 | a registry entry, a new helper tested by name, a new docs file |
| M6 no information in the issue | 1 | 1 | "Fix #3104 / See #3104" |
| M7 incidental gold hunks (metric artefact) | 6 | 3 | the missing file/function changed only cosmetically |
| M8 right place, wrong mechanism | n/a | 7 | FILES right, CAUSE/FIX differ from the gold mechanism (measured only where P has a pipeline outcome) |

L's 12 headline misses decompose as: proxy cap 5 (2 of them genuine loops), M7 3, M5 2, M6 1, M1 1 (rich_3782).
P's 19: M1 2, M2 5, M3 2, M4 3, M5 3, M6 1, M7 3. In P, naming every gold file goes with 15/35 resolved,
missing one with 4/19.

### M1 Plan lost at the end of the stage (L 3, P 5)

- **Evidence.**
  - P fastapi_14448: after 6 calls the stage ended on the text
    `<|tool_call>call:run_command{command:<|"|>python3 /tmp/swe/run_command { "command": "cat <<'EOF' > repro.py ...`
  - P fastapi_14873 (1 call) and P rich_3953 (2 calls) ended on `<|tool_call>call:python3 /tmp/swe/view.py ...`, a
    helper written as a tool name.
  - P rich_2725 ended on a text tool call that carries the reproduction heredoc; the same task in L sent 13
    run_command calls with empty args, the first 3 of them 768-token runaway outputs (`max_output_tokens: 768`).
  - P rich_2943 ended with no text at all.
  - L rich_3782's reply is a 768-token thinking dump ("Wait, if the current code already handles padding...") with
    no FILES line; L rich_3067 never replied.
  - Three of the five P cases (14873, 2725, 3953) contain the gold path inside the garbage, so the metric counts them
    as hits: P's real plan-level hit rate is 32/54, not 35/54. The fixer recovered 3 of the 5 by locating again
    (14873, 2725 and 2943 resolved).
- **Trigger.** Long heredocs with non-ASCII text and reasoning comments inside them (2725 in both runs), and the
  helper-as-tool-name form. INFERENCE: the proxy's tool-call parser turns the same failure into empty-args calls and
  the scorer's vLLM parser into stage-ending text.
- **Fix.**
  1. Fixer prompt, step 1: `python3 /tmp/swe/status.py` for every task (it is also the phase marker of change C1), and
     the rule "If the [locator] message does not start with FILES:, the plan was lost: start from the files and
     reproduction that python3 /tmp/swe/status.py lists."
  2. `status.py` prints a LOCATOR DIGEST from helper state: locate's top 3, each viewed file with its ranges and
     enclosing defs, the last `--repro-only` verdict and where the reproduction is saved. Stdlib only; state already
     records views (`state["views"]`) and the journal records locate and verify.
  3. Locator prompt: "Write no reasoning inside a heredoc; think before the call." (rich_2725, rich_3063, rich_3953,
     rich_3772 all wrote multi-line reasoning as `#` comments in the reproduction.)
- **Tests.** status.py prints the digest when the locator viewed files and ran a repro; prints "no locator activity"
  on an empty state; never exceeds its cap; the prompt test enforces the placeholder and helper-name rules.

### M2 Right candidate seen, another chosen (L 2, P 5)

- **Evidence.**
  - P fastapi_13920: locate rank 2 is the gold `fastapi/dependencies/utils.py`, and `analyze_param` was viewed at
    call 15; the plan picks `WithArgsTypes` in `fastapi/_compat/shared.py`.
  - P fastapi_9425: locate rank 1 is the gold utils.py, `get_typed_return_annotation` viewed at call 2; the plan picks
    the call site in routing.py (resolved anyway).
  - P requests_6644: locate rank 1 is the gold `src/requests/adapters.py` (viewed 369-396); the plan picks
    `models.py path_url`, although the issue names ConnectionPool and the request-uri.
  - P rich_3935 "fix for padding width": locate scored padding.py 41.8 and table.py 41.7; grep `padding_width` at
    call 2 showed `Table._get_padding_width`; the plan picks `Padding.__rich_measure__`. L's locator queried
    `padding_width` directly and named table.py.
  - P rich_3472: pretty.py (rank 1) read in 7 pages, then a third locate on "ConsoleOptions dataclass" moved the plan
    to console.py.
  - L rich_3772 "Fix traceback recursion": blamed `install.excepthook`; gold is the cause/context loop of
    `Traceback.extract` (P named `extract`). L rich_3953 covered the ZWJ half of "Fix ZWJ and edge cases" and never
    considered the second linked issue (`get_character_cell_size`, hidden test `test_non_printable`).
- **Fix.** A locator prompt rule, tested on L before shipping: "Name the function the issue's own words point to: an
  identifier made from the title's words (padding width gives a *padding_width* function), or the component the issue
  names. If a second candidate remains, add it on an ALSO: line." The fixer prompt then reads "ALSO: a second
  candidate; change it only if verify still fails there." Gate: L `l_all_gold_files_named` wins minus losses >= 3,
  and an F run with ALSO lines added to the golden plans is not worse.
- **Tried offline and not recommended:** a locate.py boost for title-word compounds (x2.5 when `padding_width` is in a
  symbol name) fixes rich_3935 and rich_2943 but pushes rich_3938 (`Style.background_style`), rich_3777,
  fastapi_14301 and fastapi_9425 down: top-1 +1, top-3 -1 over 36 snapshots (`rankexp.out`).

### M3 Gold never surfaced (P 2)

- **Evidence.**
  - P fastapi_9753 ("dependables with functools.partial()"): locate's top 3 were `scripts/notify_translations.py`,
    routing.py and a test; the gold `fastapi/dependencies/models.py` (`_unwrapped_call`) never appeared.
  - P rich_3067 ("Allow tilde in URL"): never ran locate; 6 greps with invented `--path` directories
    (`rich/concurrent`, `rich/highlighting`, ... "does not exist"), then `Style.parse`. L found the URL regex in
    `ReprHighlighter` at call 4 by grepping `url` in highlighter.py (locate rank 4).
- **Fix (helper).**
  1. `grep.py --path` on a missing path prints the 3 closest existing paths (difflib over the indexed files and
     their directories) instead of only "does not exist".
  2. `locate.py`: treat `scripts/` and `tools/` like doc dirs (x0.6). Over the 36 dev snapshots this changes nothing
     (the fastapi snapshots with that noise are missing), so it is low priority and rests on the two traces.
  3. A light suffix stemmer (ings/ing/ions/ion/ed/es/s, stem >= 4 chars) on index and query: over 36 snapshots the
     models' own first queries go from 14 to 15 (L) and 14 to 16 (P) top-1 hits, the full issue text from 16 to 20;
     it fixes rich_3063 ("escaping" vs `escape`, rank 99 to 1) and rich_3676 ("notes", 99 to 4) but moves rich_3180
     from 4 to 10 (`stemexp.out`). Hold for a larger check; not in v10.2.

### M4 Places it had seen left out (P 3)

- **Evidence.**
  - P fastapi_14077 (rename every `HTTP_422_UNPROCESSABLE_ENTITY`): grep at call 1 listed 3 files including
    `docs_src/handling_errors/tutorial005.py`; FILES names 2 of them (resolved anyway).
  - P fastapi_14419: viewed `get_dependant` and `solve_dependencies` in utils.py (calls 3-7); FILES names models.py
    only; unresolved.
  - P fastapi_14372: locate rank 3 was utils.py (`analyze_param`); not in FILES (resolved anyway).
  - The M7 miss of rich_3777 (diagnose.py) is the same behaviour: grep `TTY_COMPATIBLE` printed diagnose.py at call
    1-2 in both runs, and FILES left it out.
- **Fix (prompt).** "FILES lists every place the change touches: each grep hit of a name you rename or remove, each
  function you read that must change with the first, and every file where siblings of a new name are registered (a
  new style, option or environment variable goes wherever an existing one is listed)." Only the FILES line grows, so it
  does not fight speed rank 4 (plan <= 80 words) much.

### M5 The fix needs something the issue does not name (L 2, P 3)

- rich_3676 "Add support for Exception.__notes__": the new style `traceback.note` must be registered in
  `rich/default_styles.py` (missed in both runs). The M4 rule's "where siblings are registered" clause covers it: a
  grep for an existing `traceback.` style lands there.
- rich_3938: the gold adds `Segment.split_lines_terminator`, which the hidden tests call by name; fastapi_15280 adds a
  new `docs_src/vibe/tutorial001_py310.py`. Neither is recoverable from the issue text. Treat as unwinnable.

### M6 No information in the issue (L 1, P 1)

- rich_3105 ("Fix #3104 ... See #3104"). L searched `#3104` and `3104` and replied with an apology asking for the
  issue text (a non-plan). P ran `curl` against github.com 9 times, `git log --grep`, and `3104` again (28 calls).
- **Fix (helper).** `locate.py`/`grep.py` answer a pure issue-number query (`#3104`, `3104`, `gh-3104`) with "issue
  numbers are not in the code; search the title's words" without searching; `run.py` answers `curl`, `wget`,
  `pip install` and `git log|show|fetch` with "OFFLINE: nothing ran" (11 such calls: P rich_3105 and fastapi_14077).
  Locator prompt: "Never ask for more information; if the issue gives nothing, reply FILES: none."

### M7 Incidental gold hunks (metric artefact, L 6, P 3)

rich_3535 (segment.py: `assert cut >= 0` and a docstring; hidden test only in test_cells.py), rich_3675 and rich_3777
(diagnose.py env-name list, `pragma: no cover`), and the function misses `words` (rich_3180: type hints and a
docstring), `save_text` (rich_4075: signature reflow) and 4 of 5 functions of rich_3935 (blank lines). Proposed
metric change: `l_gold_files_named_essential`, which drops gold files whose hunks are all docstring, comment, blank,
formatting or type-hint changes (`lines.py` has the blank/comment/docstring part of that rule); the golden dataset
build is the natural place for it.

### M8 Right place, wrong mechanism (P 7 of 8)

- On the 29 dev tasks that both P and F_dev_A0 (golden plan, majority of 3) cover: P named every gold file in 19;
  the golden plan passes in 13 of those 19; **P resolved only 5 of the 13**. The failures are rich_3063, 3180, 3470,
  3471, 3480, 3506, 3718 and 3953 (M1).
- The seven P plans against the golden causes:

| task | P plan's cause | gold cause |
|---|---|---|
| rich_3063 | `_parse` handles a trailing backslash | `escape()` only doubles backslashes before a tag |
| rich_3180 | `chop_cells` alone, "characters may be replaced" | `chop_cells` iterates in reverse, and `divide_line` must change with it |
| rich_3470 | `end_capture` does not record | `_write_buffer` records on every call, not only on flush |
| rich_3471 | the `if style:` check | `append_tokens` does not strip control codes, unlike `append` and `__init__` |
| rich_3480 | self-reference in `append` | `append` and `append_text` extend from a live generator over `_spans` |
| rich_3506 | vague "may be flawed" | the start-index guess overshoots the cut |
| rich_3718 | render the title with `style=` | restyle the title with the combined border style (a revert) |

- Five of the seven are title-only issues. In three gold causes a sibling function is the key: `append_tokens` must
  do what `append` and `__init__` already do (3471), and the sibling needs the same change (`append_text` in 3480,
  `divide_line` in 3180).
- **Fix (prompt, tentative).** "For a bug in function F with no failing reproduction, compare F with its siblings
  (same class, similar name): the fix usually makes F do what they already do." Measure it before shipping: an
  **F-real** variant of suite F that feeds the fixer the p1 plan text instead of the golden plan on the same dev cases
  (about $0.17 per sample-run at F_dev_A0's cost) splits the F-to-pipeline gap into plan content versus the rest.
  Caveat: F's own runs had 14-20 s mean live latency on the same retry-driven clock (sect. 2), so F's 75-80 % was
  measured with the fixer's pacing lines firing early.

## 4. Time and call failure modes

| mode | L | P | measure |
|---|---|---|---|
| T1 reproduction loop | 9 cases with >= 3 attempts | 12 | 76 / 90 attempts; 28 / 15 of them after a reproduction already failed on original; 7.0 / 8.6 L4 s each |
| T2 probing with run.py | 5 cases with >= 5 runs | 15 | 135 / 211 run.py and bare-shell calls; 22.5 % / 31.5 % of locator time |
| T3 stop lines ignored | 169 of 427 calls after the first stop line (inflated by sect. 2) | 153 of 838 (18 %), 14 cases with >= 3 | identical repeats 58 / 83; "same output 3 times" notes shown 30 / 37 times, and the model kept going |
| T4 view paging and re-reads | 110 views: 34 cut short, 24 next-page, 15 re-reads | 298 views: 78 cut short, 62 next-page, 42 re-reads | `view.py`'s 2,800-char cap stops a requested range after about 45-55 lines |
| T5 runaway or unparseable calls | 17 empty-args calls in 3 cases | 4 stage-ending text tool calls | see M1 |

### T1 Reproduction loop

- **Evidence.**
  - First failing reproduction at attempt 1 / 2 / 3+ / never / no attempt: L 12 / 4 / 1 / 7 / 3; P 18 / 3 / 5 / 10 / 18.
  - L rich_3676 made 13 attempts for a feature with no failing assertion; L rich_3067 made 7, asserting the span
    count instead of the span end; L rich_3772 7; L rich_3953 5.
  - L rich_3518 retried 4 times at t = 287-299 after "did not finish in time ... pipe the reproduction again".
  - `verify.py` itself invites the loop: "passes on original - it misses the bug; rewrite it once with another input
    shape" is printed on every passing attempt.
  - 4 of L's 13 reproductions that "fail on original" are invalid on gold: 2725 (TypeError from calling `Box` wrong),
    3180, 3772 (the reproduction's own uncaught `raise Exception("First")`) and 3953. A BROKEN rule for "the innermost
    frame is the reproduction" was considered and rejected: a missing attribute or keyword is also how a legitimate
    feature-request reproduction fails (fastapi_15280: `'FastAPI' object has no attribute 'vibe'`).
- **Fix (helper, `verify.py --repro-only`).**
  1. After a result that fails or hangs on original, the footer carries "LOCATOR: reproduction saved; reply with your
     plan now."
  2. The passing-claim hint becomes "... it misses the bug. Rewrite it at most once; if it passes again, reply with
     REPRO: none."
  3. A third attempt before the phase marker (C1) does not run and prints "REPRO LIMIT: 2 attempts used; nothing ran.
     Reply with the plan and REPRO: none."
  4. The "did not finish in time" hint drops "pipe the reproduction again" once t >= T_LOCATOR.
- **Measured bound.** Stopping at the first failing attempt, with at most 2 attempts, removes 44 of 76 L attempts and
  39 of 90 P attempts. The cost is 1 L case (rich_3772, invalid anyway) and 5 P cases whose first failing
  reproduction came at attempt 3-6 (fastapi_13920, 14301, 5077, 9753, rich_4075).
- **Tension.** This conflicts with diag_5's flip lever, which adds reproduction work; S3's factorial measures the
  interaction.

### T2 Probing with run.py (plus three run.py defects)

- **Evidence.**
  - L rich_3521: 33 run.py probes of `split_cells` (8 identical), all after the stop line.
  - L rich_4006: 36 runs, the same command 20+ times after "same command, same output 3 times; change something".
  - P rich_3480: 25 runs (10 identical); P rich_3506: 21; P rich_4079: 17 (12 identical); P fastapi_14077: 16.
- **Defect 1: python3 -c with multi-line code (30 calls in 10 cases).** Newlines, decorators or `class` inside
  `python3 -c` always raise SyntaxError. L rich_3894 ran 13 such calls in a row after a reproduction had already
  failed at call 3. Fix: `run.py` refuses without running and prints "multi-line code cannot go through python3 -c;
  pipe it: python3 /tmp/swe/verify.py --repro-only <<'EOF' ... EOF".
- **Defect 2: a heredoc piped into run.py is dropped (7 calls in 2 P cases).** `_swe_common.sh` starts the command
  with `stdin=subprocess.DEVNULL`, so `python3 /tmp/swe/run.py "python3" <<EOF ... EOF` prints `exit=0 (no output)`.
  P rich_2943 did this 3 times, got the "same output 3 times" note, and its stage then ended with no plan. Fix: when
  run.py's stdin is not a TTY and not empty, pass it to the command, or refuse loudly; either way, a regression test.
- **Defect 3: unbalanced quotes (12 calls in 5 cases).** The harness's bash fails before run.py starts, so run.py
  cannot fix it; only the prompt's examples can (single-quoted heredocs instead of nested `-c` quoting).
- **Fix (helper).**
  1. Before the phase marker, run.py runs at most 3 commands, then prints "PROBE LIMIT: 3 runs used; nothing ran.
     Reply with your plan."
  2. The 3rd identical command with an identical last output does not run: "identical to call N; nothing ran".
  3. The OFFLINE refusal of M6.

### T3 Stop lines ignored, and the helper-enforced budget

- The prompt budget ("about 8 tool calls; reply by t = 90 s") is far exceeded: 31 of 54 P locators make more than 12
  calls and 12 more than 20, as own_data.md found for v9 (about 80 % over budget). The declarative config has no
  per-stage call cap (own_data.md sect. 6), so the only structural lever is the helpers.
- The obstacle is that helpers cannot tell the locator's 15th view from the fixer's first. The fix gives them a phase
  marker: the fixer's first call is `status.py` (M1's fix), which sets `locator_over` in state.
- Before that marker, the locator is **closed** at 14 helper calls or at helper t >= 90 s, whichever comes first
  (constants in `_swe_common`, scaled like T_LOCATOR). When closed, `locate.py`, `grep.py`, `view.py`, `run.py` and
  `verify.py --repro-only` do not run and print:
  `LOCATOR CLOSED at t=Ns after N calls: nothing ran. Reply now with your plan. Draft from your calls: FILES: <most-viewed file:start-end (def)>; <second> | REPRO: <fails on original, or none>`
- `edit.py`, plain `verify.py`, `finalize.py` and `status.py` are never blocked.
- **Why 14 calls and 90 s.** The gold definition was first printed by call 12 in 23/23 L and 39/45 P cases, and by
  30 L4 s in 23/23 and 41/45. The six late P cases are fastapi_14487 (docs target found at call 37), 14851, 3105,
  3470, 3472 and 3535. On the scorer the helper clock is real time, so on a hidden task at k = 1.9 the 90 s close
  falls at about 47 public-equivalent seconds, above P's median locator (46 s). The call cap does not depend on k.
- **Measured bound (`capsim.out`).** Applying the reproduction rule, a 2-probe limit and the 14-call close together,
  and assuming removed calls are not replaced, the locator's tool time goes from 50.2 to 27.0 L4 s in L (-23.3,
  median -6.8) and from 49.7 to 29.0 in P (-20.7, median -11.0). A 3-probe limit gives -22.3 and -19.6. At k = 1.9
  that is about 40 s more for the fixer on an average hidden task.
- **Risks.** (a) The model may loop on refusals, as it looped on "same output" notes; the draft plan exists to give it
  something to copy, and golden L's X metrics must stay clean. (b) It may switch to bare run_command shell or
  `read_file`, which helpers cannot block: 27 bare calls and 5 `read_file` calls were seen. (c) A locator that
  compacts and calls `status.py` (its prompt allows that) ends its own budget early, which is harmless.
- **Tests.** Closed at call 15 and at t = 90 via `SWE_FAKE_CLOCK`; each blocked helper prints the refusal and starts
  no subprocess; `edit.py`, plain `verify.py`, `finalize.py` and `status.py` still work while closed; `status.py`
  reopens and prints the digest; the draft names the most-viewed file and its enclosing def; the budget counters
  reset on `install.py`; the output stays within `CAPS` and the footer rules.

### T4 View paging

A third of range views are cut by the 2,800-char cap and continued page by page (P rich_3472: 7 pages of pretty.py;
L rich_3518: the `Table` docstring in 5 views; L rich_4075: `Console.print` in 5). Not proposed for v10.2: a larger
cap raises the context, and CONTEXT already fires often in P. Cheaper: `locate.py` prints `view.py FILE NAME` for its
top symbol, so the first read is the whole function.

## 5. Is ranking the problem? (offline replay, $0)

`rankexp.py` rebuilds the v10 index on the 36 dev snapshots that exist locally (31 rich, requests_6644, 4 fastapi)
and ranks the gold files for four queries.

| query | n | gold file top-1 | top-3 | not in top 8 |
|---|---|---|---|---|
| the issue title | 36 | 15 | 20 | 12 |
| the full issue text (`clean_query`) | 36 | 16 | 25 | 6 |
| the L locator's first locate query | 26 | 14 | 19 | 4 |
| the P locator's first locate query | 30 | 14 | 22 | 4 |

- **Auto-running locate.py in setup was considered and rejected.** A title-only query ranks worse than the models' own
  queries (top-3 in 20/36 = 56 %, against 73 % for the models' first queries), and the full issue ranks best but cannot reach a helper without the
  model copying the whole statement (hundreds of output tokens at 28 ms each). The setup's output_key would also have
  to carry the ranking as text (about 150 output tokens), while the locator already calls locate in 26/27 L and
  43/54 P and sees the gold definition by call 2 (median). The index builds and answers a query in under 0.3 s (rich,
  requests, fastapi), so pre-warming it saves nothing either.

## 6. Ranked changes for v10.2 (built in `submissions/v10_2`, v10.1 untouched)

| # | change | kind | modes | measured size | risk | gate on dev |
|---|---|---|---|---|---|---|
| C1 | fixer step 1 `status.py` (phase marker + LOCATOR DIGEST); locator closed at 14 calls or t 90 with a draft plan | helper + prompt | T3, M1 | part of -20.7 (P) / -23.3 (L) L4 s per task | refusal loops; bare-shell bypass | L: `l_l4_s` down >= 15 s at the hidden clock, `l_all_gold_files_named` not worse (<= 1 net loss), X clean |
| C2 | reproduction budget and hint texts in `verify.py --repro-only` | helper | T1 | 44/76 (L), 39/90 (P) attempts | 5 P late-but-failing repros lost | valid-repro rate not down by > 3 cases (speed.md sect. 9.2) |
| C3 | run.py: 3-probe limit, identical-run refusal, OFFLINE refusal, the `python3 -c` multi-line guard, and stdin pass-through or refusal | helper | T2, M6 | 113/135 (L), 167/211 (P) probes beyond 2 | fewer probes on bugs a probe could show | as C1 |
| C4 | fixer rule for a plan that does not start with FILES: | prompt | M1 | 5/54 P plans lost | none measurable | F not worse |
| C5 | FILES completeness rule (every grep hit of a renamed name, co-changing functions, sibling registries) | prompt | M4, M5 (3676) | 3 P + 1 task in both | longer FILES | L headline |
| C6 | "no reasoning inside a heredoc", "never ask for more information" | prompt | M1, M6 | 2725 in both runs, 3105 | none | X metrics |
| C7 | ALSO: line for a second candidate | prompt | M2 | 5 P, 2 L | the fixer edits both | L headline and an F run with ALSO lines |
| C8 | sibling-consistency diagnosis rule | prompt | M8 | a sibling is the key in 3 of the 7 gold causes | untested | F-real first |
| C9 | eval: `l_l4_s` metric and the router clock shift | eval | T6 | 5 fake caps, 17 early stop lines | none | gen_config --check, test_golden_metrics |

- **Order.** C9 first, since without it no rung-2 time gate can be read. Then C1-C4 as one v10.2 locator package: all
  are helpers or one fixer line, and each gets a regression test in `tests/` in the style of test_v10_run_status.py
  and test_v10_verify.py. C5-C8 are single prompt lines, each needing its own dev evidence under the pre-registered
  rule (sign test p <= 0.10, wins - losses >= 3).
- **Spend inside the $4 cap.** One L dev run is $0.43 (L_dev_v101); v10.1 at the hidden clock plus v10.2 at the hidden
  clock is about $0.9. F-real at 3 samples is about $0.5. Use `-j 2` for the Crusoe rate limit; reruns cost the same.

## 7. What this changes in the brief's conclusion

- "The locator is the main loss" holds, but in three parts:
  - **Time:** a real but smaller loss than the proxy showed, about 50 L4 s and 15-16 calls per locator. About 40 % of
    that is removable by C1-C3 without losing the first sight of the gold code.
  - **Lost or garbled plans:** 5 of 54 on the faithful stack.
  - **Diagnosis:** in 8 of the 13 tasks where the right files were named and a golden plan wins, the pipeline still
    lost, and the plans read state another mechanism.
- `l_all_gold_files_named` is blind to this last part and overstates misses through incidental hunks (M7). Read it
  together with the pipeline outcome, or with F-real.

## 8. Limits

- P is one run per task, and L one sample per case: per-case modes are noisy. rich_3772 and rich_3063 were right in
  one run and wrong in the other.
- L4 seconds for L are a token model (R^2 0.97-0.98 on Kaggle calls); P's are the pod clock x 1.7. Neither includes
  the scorer's slower hidden-task tools; k = 1.9 is the brief's figure, and speed.md puts k at 1.4-4.9.
- The cap simulation is an upper bound: it assumes that removed calls are not replaced and that the plans do not change.
- The M8 table compares plan text with gold causes by reading them; it is a judgement on 7 cases, not a metric.

## 9. Reproduce

Each step takes about a minute or less. `rankexp.py` and `stemexp.py` extract the dev-split snapshots (never the
holdout) into `research/locator_diag/ws/`, about 3.8 GB, and copy the v10 helpers to `scripts/`; delete both afterwards.

```bash
cd /Users/carson/Projects/gemma-swe-agent
export PYTHONDONTWRITEBYTECODE=1; PY=.venv/bin/python; D=research/locator_diag
$PY $D/dump.py > /dev/null          # L per-case dumps -> $D/dumps/
$PY $D/dump_p1.py > /dev/null       # P dev-split locator dumps -> $D/dumps/p1/ (holdout never opened)
$PY $D/l4time.py > /dev/null        # L4-projected locator time per L case -> $D/l4_L_dev_v101.json
$PY $D/analyze.py > /dev/null       # per-case rows for L and P -> $D/rows_all.json
$PY $D/stats.py > $D/stats.out      # sections 0 and 4 aggregates
$PY $D/attrib.py > $D/attrib.out    # seconds by call kind
$PY $D/postfind.py 2>/dev/null | grep '^[LP] n' > $D/postfind.out   # time after the gold definition first appears
$PY $D/capsim.py > $D/capsim.out    # combined cap bound
$PY $D/fcompare.py > $D/fcompare.out  # P vs F golden-plan outcome
$PY $D/lines.py > $D/lines.out      # plan line ranges vs gold hunks
$PY $D/rankexp.py > $D/rankexp.out  # offline locate ranking variants (extracts $D/ws/)
$PY $D/stemexp.py > $D/stemexp.out  # offline stemming variant
$PY $D/table.py > $D/table.out      # the appendix -> $D/case_table.md
rm -rf $D/ws $D/scripts             # 3.8 GB of snapshots and the helper copy
```

## Appendix: every case

Modes as in sections 3-4 ("ok" = every gold file named; M7 alone is not a real miss). "end" is how the stage ended:
plan (starts with FILES:), prose+plan, no FILES, text tool call, empty, or capped (the router served "done"). L4 s
for L is the token projection including the final reply; for P it is the last helper footer.

| src | task | gold files named | gold fns named | calls | L4 s | end | modes | evidence |
|---|---|---|---|---|---|---|---|---|
| L | rich_2725 | 0/1 | 0/1 | 18 | 88 | capped | M1 T5 T6 | gold Table._render viewed at call 3; after one repro with box characters and reasoning comments, 13 run_command calls arrived with empty args (the first 3 were 768-token runaway outputs); the router cap served 'done' |
| L | rich_2943 | 1/1 | 1/1 | 5 | 19 | plan | ok | locate rank 3; view Style.clear_meta_and_links at call 2; one repro, fails on original |
| L | rich_3043 | 1/1 | - | 11 | 31 | plan | ok | grep CONSOLE_HTML_FORMAT at call 5; one run.py unbalanced-quote error |
| L | rich_3063 | 1/1 | 1/1 | 8 | 48 | plan | ok T1 | 4 repro attempts, reasoning written as comments inside the heredoc |
| L | rich_3067 | 0/1 | 0/1 | 23 | 68 | capped | M1 T1 T3 T6 | found url regex in highlighter.py at call 4-5; repro asserted span count (not span end) and passed 5 times; drifted to markdown.py; 17 calls after LOCATOR/EDIT NOW; never replied |
| L | rich_3105 | 0/1 | - | 3 | 11 | no FILES | M6 | 'See #3104' only; locate/grep '3104'; replied with an apology asking for the issue text |
| L | rich_3180 | 2/2 | 2/3 | 9 | 37 | plan | ok M7 | missing gold fn words() is type hints and a docstring only |
| L | rich_3278 | 1/1 | - | 13 | 45 | plan | ok T4 | read_file rich/ansi.py 3 times; identical repro run 3 times |
| L | rich_3470 | 0/1 | 0/1 | 11 | 26 | capped | T6 | clean progress on console.py (locate rank 1); two calls took 114.9 s and 116.7 s of 429 retries; L4 26 s |
| L | rich_3471 | 0/1 | 0/1 | 13 | 32 | capped | T6 T2 | gold at call 1-2; run.py with unbalanced quotes 4 times, then bare python3 -c (no footer); 113.8 s and 118.2 s retry calls |
| L | rich_3472 | 0/1 | 0/1 | 10 | 29 | capped | T6 T2 | pretty.py rank 1; python -c with decorators (SyntaxError); guessed Pretty.render and print(pretty=True); first call 69.6 s |
| L | rich_3506 | 1/1 | 1/1 | 8 | 30 | prose+plan | ok | prose before FILES; repro never failed (REPRO: none) |
| L | rich_3518 | 1/1 | 1/1 | 14 | 47 | plan | ok T4 T6 | right plan; 112.8 s and 117.2 s retry calls pushed the proxy clock to 299; Table docstring read in 5 pages |
| L | rich_3521 | 1/1 | 1/1 | 39 | 146 | plan | ok T2 T3 | 33 run.py probes of split_cells (8 identical), all after the stop line; L4 147 s |
| L | rich_3535 | 1/2 | 0/1 | 10 | 30 | plan | M7 | missing rich/segment.py is an assert plus docstring; hidden test only covers cells.py |
| L | rich_3675 | 1/2 | 1/4 | 14 | 43 | plan | M7 | missing diagnose.py is an env-name list (pragma no cover); NO_COLOR change in __init__ is not in the issue |
| L | rich_3676 | 1/2 | 3/5 | 48 | 181 | plan | M5 T1 | __notes__ feature; new style 'traceback.note' needs rich/default_styles.py; 13 repro attempts all pass (feature has no failing assertion); compaction then re-search; L4 181 s |
| L | rich_3718 | 1/1 | 1/1 | 10 | 40 | plan | ok | right plan |
| L | rich_3772 | 1/1 | 0/1 | 16 | 68 | plan | M2 T1 | title-only 'traceback recursion'; blamed install.excepthook, gold is Traceback.extract cause/context loop; 7 repro attempts |
| L | rich_3777 | 1/2 | 1/2 | 13 | 33 | plan | M7 | missing diagnose.py env-name list; grep TTY_COMPATIBLE listed it at call 2 |
| L | rich_3782 | 0/1 | 4/6 | 16 | 88 | no FILES | M1 | final reply is a 768-token thinking dump with a code block and no FILES line; 6 repro attempts |
| L | rich_3894 | 1/1 | 1/1 | 22 | 74 | plan | ok T2 | 15 run.py calls with '\n' inside python -c, SyntaxError every time |
| L | rich_3935 | 1/1 | 1/5 | 21 | 101 | plan | ok M7 T2 | 4 of 5 gold fns are blank-line hunks; 17 run.py probes |
| L | rich_3938 | 1/2 | 1/2 | 11 | 61 | prose+plan | M5 | gold adds Segment.split_lines_terminator in segment.py; hidden tests call it by name |
| L | rich_3953 | 1/1 | 1/2 | 9 | 62 | plan | M2 T1 | second linked issue ('edge cases': non-printable width in get_character_cell_size) never considered; 5 repro attempts with reasoning comments |
| L | rich_4006 | 1/1 | 1/1 | 39 | 105 | plan | ok T2 T3 | 36 run.py calls, the same command 20+ times despite 'same output 3 times'; reply has two FILES blocks and 'Wait,' |
| L | rich_4075 | 1/1 | 1/2 | 13 | 37 | plan | ok M7 | missing save_text is a signature reflow |

| src | task | gold files named | gold fns named | calls | L4 s | end | modes | evidence |
|---|---|---|---|---|---|---|---|---|
| P | fastapi_13537 | 1/1 | 0/1 | 13 | 54 | plan | ok |  |
| P | fastapi_13920 | 0/1 | 0/1 | 28 | 92 | plan | M2 T2 | locate rank 2 = gold utils.py, viewed analyze_param at call 15; plan picks _compat/shared.py WithArgsTypes; 8 bare python -c |
| P | fastapi_14077 | 2/3 | 0/3 | 22 | 59 | plan | M4 T2 | grep at call 1 listed docs_src/handling_errors/tutorial005.py; plan omits it (resolved anyway); 16 run.py incl. pip install and 9 identical deprecation checks |
| P | fastapi_14301 | 1/1 | 1/1 | 13 | 59 | plan | ok T1 | 6 repro attempts, first failing one is the 6th |
| P | fastapi_14306 | 2/2 | 4/9 | 12 | 47 | plan | ok |  |
| P | fastapi_14372 | 1/2 | 0/2 | 7 | 18 | plan | M4 | locate rank 3 dependencies/utils.py (analyze_param) not in plan; resolved anyway |
| P | fastapi_14419 | 1/2 | 3/5 | 13 | 89 | plan | M4 T1 | viewed utils.py get_dependant and solve_dependencies (calls 3-7); plan names models.py only; 5 repro attempts, 4 pass |
| P | fastapi_14448 | 0/2 | 0/5 | 6 | 17 | text tool call | M1 | stage ended on a text tool call: run_command{... /tmp/swe/run_command {cat <<'EOF' > repro.py ...}} |
| P | fastapi_14458 | 1/1 | 3/3 | 9 | 41 | plan | ok |  |
| P | fastapi_14463 | 1/1 | 0/1 | 12 | 52 | plan | ok |  |
| P | fastapi_14479 | 1/1 | 1/1 | 9 | 36 | plan | ok |  |
| P | fastapi_14487 | 1/1 | 0/1 | 37 | 80 | plan | ok T3 | docs-only target found at call 37; 27 greps; 24 calls after CONTEXT |
| P | fastapi_14786 | 1/1 | 1/1 | 8 | - | no FILES | ok | plan written after '//' comment lines |
| P | fastapi_14794 | 1/1 | 1/1 | 13 | 36 | plan | ok |  |
| P | fastapi_14851 | 1/1 | 1/4 | 20 | 32 | prose+plan | ok | prose before FILES |
| P | fastapi_14873 | 1/1 | 1/1 | 1 | 6 | text tool call | M1 | after 1 call the stage ended on text 'call:python3 /tmp/swe/view.py fastapi/routing.py APIRouter.__init__' (helper used as a tool name); counted as a hit by the path in it; resolved anyway |
| P | fastapi_15280 | 1/2 | 0/1 | 11 | 32 | plan | M5 | gold adds a new docs_src/vibe/tutorial001_py310.py |
| P | fastapi_15588 | 1/1 | 1/3 | 18 | 75 | plan | ok T1 T2 | 6 repro attempts, 8 run.py |
| P | fastapi_5077 | 1/1 | 1/2 | 12 | 80 | plan | ok T1 | first failing repro at attempt 6 |
| P | fastapi_9425 | 0/1 | 0/1 | 21 | 83 | plan | M2 T2 | locate rank 1 = gold utils.py, viewed get_typed_return_annotation at call 2; plan picks routing.py call site; resolved anyway; 12 run.py |
| P | fastapi_9555 | 1/1 | 3/4 | 9 | 31 | plan | ok |  |
| P | fastapi_9753 | 0/1 | 0/1 | 11 | 64 | plan | M3 | locate top 3: scripts/notify_translations.py, routing.py, a test; gold dependencies/models.py never shown; plan picks utils.py get_typed_signature |
| P | requests_6644 | 0/1 | 0/1 | 9 | 33 | plan | M2 | locate rank 1 = adapters.py, viewed 369-396; plan picks models.py path_url although the issue names ConnectionPool/request-uri |
| P | rich_2725 | 1/1 | 0/1 | 6 | 34 | text tool call | M1 | stage ended on a text tool call carrying the repro heredoc (box chars); counted as a hit by the path in it; resolved anyway |
| P | rich_2943 | 0/1 | 0/1 | 15 | 40 | empty | M1 T2 | no final text at all; heredoc piped into run.py 3 times gave '(no output)' (stdin is /dev/null); resolved anyway |
| P | rich_3043 | 1/1 | - | 10 | 19 | prose+plan | ok | FILES line spells rich/_export_foramt.py (typo); the prose above it has the right path |
| P | rich_3063 | 1/1 | 1/1 | 15 | 49 | plan | ok M8 T1 | plan blames _parse, gold is escape(); 6 repro attempts |
| P | rich_3067 | 0/1 | 0/1 | 41 | 81 | plan | M3 | never ran locate; grep --path with 6 invented dirs; never saw highlighter.py; plan picks Style.parse; 41 calls |
| P | rich_3105 | 0/1 | - | 28 | 87 | prose+plan | M6 | curl to github.com 9 times, git log --grep, grep/locate '3104'; 28 calls; prose reply |
| P | rich_3180 | 2/2 | 2/3 | 17 | 117 | plan | ok M8 | plan names chop_cells only with a different cause; L4 117 s |
| P | rich_3278 | 1/1 | - | 9 | 26 | plan | ok |  |
| P | rich_3468 | 1/1 | 2/4 | 13 | 31 | plan | ok |  |
| P | rich_3470 | 1/1 | 1/1 | 26 | 53 | prose+plan | ok M8 T4 | plan (prose first) blames end_capture; gold _write_buffer; 15 views |
| P | rich_3471 | 1/1 | 1/1 | 13 | 37 | plan | ok M8 | plan blames 'if style:'; gold strips control codes like append/__init__ |
| P | rich_3472 | 0/1 | 0/1 | 34 | 79 | plan | M2 T3 T4 | pretty.py rank 1 viewed in 7 pages; after the 3rd locate drifted to console.py ConsoleOptions; 22 calls after CONTEXT |
| P | rich_3480 | 1/1 | 1/2 | 31 | 75 | plan | ok M8 T2 | plan fixes append only (self-reference); gold snapshots spans in append and append_text; 25 run.py (10 identical) |
| P | rich_3506 | 1/1 | 1/1 | 25 | 73 | prose+plan | ok M8 T2 | prose plan, vague cause; 21 run.py |
| P | rich_3518 | 1/1 | 1/1 | 10 | 23 | plan | ok |  |
| P | rich_3521 | 1/1 | 1/1 | 22 | 56 | prose+plan | ok T2 | 16 run.py (10 identical) |
| P | rich_3535 | 1/2 | 0/1 | 17 | 34 | plan | M7 | saw segment.py via grep of _is_single_cell_widths users; change there is incidental |
| P | rich_3675 | 1/2 | 1/4 | 7 | 25 | plan | M7 |  |
| P | rich_3676 | 1/2 | 3/5 | 19 | 42 | plan | M5 | default_styles.py not found; 12 views of traceback.py |
| P | rich_3718 | 1/1 | 0/1 | 10 | 23 | plan | ok M8 | plan changes console.render style; gold restyles the title with the combined border_style |
| P | rich_3772 | 1/1 | 1/1 | 12 | 29 | plan | ok | names Traceback.extract (the L run did not) |
| P | rich_3777 | 1/2 | 0/2 | 13 | 26 | plan | M7 |  |
| P | rich_3782 | 1/1 | 4/6 | 20 | 74 | plan | ok T2 | 13 run.py |
| P | rich_3894 | 1/1 | 0/1 | 8 | 25 | plan | ok |  |
| P | rich_3935 | 0/1 | 0/5 | 15 | 46 | prose+plan | M2 | locate: padding.py 41.8 vs table.py 41.7; grep padding_width at call 2 showed Table._get_padding_width; plan picks Padding.__rich_measure__ |
| P | rich_3938 | 1/2 | 2/2 | 16 | 44 | plan | M5 | segment.py new helper (see L) |
| P | rich_3953 | 1/1 | 0/2 | 2 | 7 | text tool call | M1 | after 2 greps the stage ended on text 'call:python3 /tmp/swe/view.py rich/cells.py'; counted as a hit by the path in it |
| P | rich_4006 | 1/1 | 1/1 | 10 | 112 | plan | ok | L4 112 s |
| P | rich_4075 | 1/1 | 1/2 | 22 | 55 | plan | ok T1 | 6 repro attempts |
| P | rich_4077 | 1/1 | 0/1 | 18 | 75 | plan | ok T2 | 13 run.py |
| P | rich_4079 | 1/1 | 0/1 | 20 | 69 | prose+plan | ok T2 | 17 run.py (12 identical); prose plan |
