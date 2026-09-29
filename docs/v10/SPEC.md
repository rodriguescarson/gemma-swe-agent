# v10 SPEC: robustness-first pipeline with a claim gate and checkpoints

Synthesizer, 2026-09-28. This file is the single source of truth for the v10 implementers. Where it disagrees with
`docs/v10/design_{A,B,C}.md`, this file wins. **v10.1 (2026-09-29)** applies the robustness fixes of race 2 round 1
(`docs/v10/v10_1_diag_1.md` to `_4.md`) in place; section 0.3 lists them, and the fix-quality levers of `_diag_5.md` are
left for separate variant arms.

Base: design A (judge totals A 55, B 49, C 45.5; A won all three ballots). Grafts come from the judges'
`best_ideas_to_keep`. Every judge-listed fatal flaw of A is fixed, and so is every flaw of a grafted B/C part (section 0.2).
Everything below was checked against the installed harness under `.venv/lib/python3.12/site-packages` (`SP/...`) or the
research reports. The prompt texts, YAML and SKILL.md in sections 2-3 were composed into a scratch bundle and compiled
with `scripts/validate.py`: `OK model=gemma-4-31b-it-qat-w4a16-ct`, 5 LlmAgents, tool lists as specified, 0 backticks,
and only the allowed braces (`scratchpad/synth/make_probe.py`).

Hard rules for implementers:
- **Frozen, never edit:** `submissions/v9_eog/**`, `submissions/v4/**` and `helpers_v9/**` (R84 pins their hashes).
- **Not allowed:** Kaggle pushes, submissions, pods or any spending.
- **Stdlib only** inside `submissions/v10/skills/swe-tools/scripts/`.
- **Tests never run helpers inside `submissions/`.** They copy the scripts to a temp dir first, so no `__pycache__` can
  appear in the bundle (`tests/test_bundles.py` checks this).
- **Test commands:** `.venv/bin/python -m pytest -q tests` runs the full suite (CI tier). Adding `G4_NIGHTLY=1` also runs
  the nightly tier.

---

## 0. What changed from design A, and why

### 0.1 Grafts (source, judge, where it lands)

| # | Graft | From | Lands in |
|---|---|---|---|
| G1 | Every stdin read is guarded by `select`; `locate.py` never reads stdin; `--lines` with empty text is an error, deletion needs `--delete` | B R-B24, C R-C14, judges 1 and 2 | `_swe_common.read_stdin`, `edit.py` |
| G2 | Helpers are immune to stdlib shadowing: `sys.path` preamble plus a `sys.modules` purge | B R-B22, C R-C18, judges 1 and 3 | preamble (4.0) |
| G3 | Every option accepts the `--key value` form, and `--text` replaces stdin, so every helper works through `run_skill_script(args=...)` and self-installs | B, C R-C21 | `parse_args`, `bootstrap` |
| G4 | No backticks anywhere in prompts or SKILL.md; tool-call examples in template (alphabetical) order `run_skill_script(file_path=..., skill_name=...)` | C N1 (e74_v2: 94/107 INVALID_ARGUMENTS) | section 3 |
| G5 | Claim-structured repro: `# CLAIM n:` sections, one process each, BROKEN/INVALID never count as evidence, `k/n claims fixed` | C 4.3, judges 1 and 2 | `_swe_gate.claims` |
| G6 | Automatic SIBLINGS list, plus light SPEC GAPS (new names, a new parameter in every same-named def, exact messages) | B 5.4.6, C 4.4-4.5, judges 2 and 3 | `verify.py` (advisory) |
| G7 | Lexicographic checkpoint score; transactional best-checkpoint restore in `finalize.py`; late auto-restore when the tree is empty at t >= 255 s | B 5.4.7-9, C 5.1, judge 3 | `_swe_ckpt.py`, `finalize.py`, footer hook |
| G8 | ORIGINAL-side test results cached per file set; quick mode near the cap; every helper deadline clamped to the remaining session time | B 5.4, C 5.9, judge 2 | `_swe_gate`, `_swe_common.real_budget` |
| G9 | LOCATOR banner at t >= 75 s (the hand-off was prompt-only in A) | B 5.3 | footer |
| G10 | Dual install target (`/tmp/swe` as well, outside the rewriting sandbox and only when `TEST_TMPDIR` is unset); installed helpers take SWE from `__file__` | C H3 | `swe_dir`, `install` |
| G11 | Trailing `EOF` / backtick junk is stripped from heredoc text | C R-C14 | `read_stdin` |
| G12 | Counterfactual L4 replay as the time ship gate | B R-B69, judge 2 | `scripts/replay_l4.py` |
| G13 | Concurrency is capped at 2 processes (Docker scorer quota: 2 vCPU, `SP/swegemma/sandbox/docker.py:89`) | A, judge 1 on C | `_swe_gate` |

### 0.2 Flaws removed

| Flaw (judge) | Fix in this spec |
|---|---|
| A: `locate.py` reads the inherited stdin, and `edit.py` reads stdin unguarded (a 120 s hang risk) | G1. R15 (1.2 s or less on an open silent pipe) and R111 (2 s or less in the real sandbox) prove it. |
| A: helpers break when the repo root has `json.py`, `types.py` or similar. The skill wrapper imports `json` with `sys.path[0]` = workspace (`SP/google/adk/tools/skill_toolset.py:618-623`), so a shadowed module can already be in `sys.modules` | G2 purges non-stdlib copies of stdlib names from `sys.modules` (R03) |
| A: the setup call was shown with `skill_name` first; backticks in examples | G4 (R88) |
| A: the sibling sweep was only a prompt rule | G6 (R66) |
| A: no best-checkpoint restore | G7 (R70-R76) |
| A: R-A03 required that the harness prompt name only declared tools. It names `submit_patch` (`SP/swegemma/harness/agent_runner.py:139`), and setup does not declare it, so R-A03 could never pass | R89 now scopes the lint to bundle text and helper output. The harness prompt is checked separately: every tool it names except `submit_patch` must be declared on setup. `submit_patch` stays undeclared there on purpose (a confused setup would otherwise submit an empty patch and lose the task anyway). v4/v9 shipped the same way, and the three unknown-tool crashes on record were `git_grep` and `search_similar_code`, never `submit_patch` (test_plan F8). |
| A: the locator hand-off was enforced only by the footer at 150 s | G9 |
| A: `verify.py`'s 60 s deadline was not clamped to the session time, so pytest children in new sessions could outlive a harness kill | G8: every deadline is `real_budget()`, which is at most (300 - clock)/scale - 4 s (R13, R65) |
| A: `edit.py --lines` with empty stdin deleted lines on `/dev/null` (the Docker case) | `--lines` requires text; deletion needs `--delete` (R42) |
| A: verify ran `python3 -s -c "import sys,pytest; sys.exit(pytest.main(...))"`, the mask-bypass form | Replaced by the grader's exact `python3 -s -m pytest` (`SP/swegemma/harness/verification.py:493`). When masked, tests are skipped, never bypassed (R58, R61). |
| A: fixer `max_output_tokens` 3,072 (a runaway costs about 88 s) | 2,048. No legitimate L4 tool call exceeded 2,048 tokens (time_model 3); overflow line 30,720. |
| A: "NOT READY: patch too large" at more than 200 kB or more than 20 new files. **New finding:** the gold patch of rich_3930 is 308 kB with 26 files, and fastapi_15800 has 8 files, so this rule would reject correct patches | Size is advisory only (`NOTE:`). Only vendored trees and untracked files over 1 MB are removed (the largest gold file adds 20.5 kB) (R73, R104) |
| A: a `SWE_EOF` delimiter the model is not used to | `EOF` (v9-measured), with junk stripping (G11) |
| C (grafted part): concurrency of min(8, cpu) | 2 (G13) |
| C (grafted part): a COMMON block that primes the graph tools | Graph tools are never named in bundle text (R89) |
| B/C retry stages (near-worthless on cap-bound hidden tasks: fire rate 0.14-0.29, judge 2) | Not taken. In-context repair (2 rounds or fewer) plus checkpoint restore instead. |

Residual risks accepted: graph tools stay declared (undeclared calls crash, and declared calls returned 11,245 chars
at most in our traces, though a competitor saw 136k); `edit_file` stays declared (malformed loops are bounded by the
cap and discouraged by the prompts).

### 0.3 v10.1: the race-2 round-1 robustness fixes (2026-09-29)

Race 2 round 1 (faithful: compaction 14,336, L4 clock 1.7, 74 tasks): v10 25 against v9_eog 24, paired 6-5, killed on
one unknown-tool crash. The plumbing KPIs held (helpers in 74/74 tasks, 0.05 malformed `edit_file` per task); these fixes
remove the new failure classes the diagnoses found. Each has a regression test (`tests/test_v10_1.py` unless named).

| # | failure (race 2 round 1) | fix | test |
|---|---|---|---|
| 1 | helper names used as tool names: 1 parsed `view.py` call crashed fastapi_13537, 29 more written as `<\|tool_call>call:NAME` text each ended its stage; the verifier's first turn in 9 of 69 | R89b/R89c (section 3 rules 8-10): a helper appears only as `python3 /tmp/swe/NAME.py`, run steps start with "Run", the HELPERS block, the verifier's handoff line; every helper hint and NEXT line names the full command (4.0.10) | R89b, R89c (lint, AST and runtime pass, controls) |
| 2 | an empty tree told "keep the edit you have and end your stage" (FINISH) or "End your stage now" (TIME); LOCATOR "ignore this line" after the locator stage | footer priority FINAL > EDIT NOW > TIME > FINISH > CONTEXT > LOCATOR; EDIT NOW on every empty tree from T_EDIT_NOW, or once the locator stage is over (4.1.7) | R18, R121 |
| 3 | `grep.py "X" path/file.py` folded the path into the regex (65 of 72 such calls missed) | a later positional word that names an existing path is searched (4.5) | R122 |
| 4 | a landed edit undone later left finalize nothing to restore (fastapi_15280) | every landed edit (edit.py) and every non-empty tree status.py sees is an unscored EDITED checkpoint (4.10) | R123 |
| 5 | the last stage submitted an empty patch with 108 s left (fastapi_14873) | EMPTY says the time left and that an empty patch always fails, plus EDIT TARGET (4.12); the submitter sees the issue; submit after READY or at t>=285s (section 3 rule 11) | R124 |
| 6 | a stray EOF inside an edit heredoc | edit.py names the early EOF (4.7); EDITFORM states the EOF rule | R125 |
| 7 | a protected file re-edited after READY (fastapi_14077) and a root repro.py in the timeout fallback diff (fastapi_14258): KPI 7 and 8 | the submit guard (4.1.17): assume-unchanged protected files plus an exclude file, armed by install and finalize; finalize enforces the graders' rules before READY | R126, R127, TFL (g), (h) |
| 8 | `view.py FILE L1191-1433` rejected; plans lost after compaction; long replies at TIME | L-ranges (4.6); status VIEWED line (4.13); TIME/FINISH ask for a short reply (4.1.7) | R128 |
| 9 | locator replies cut at 768 tokens (11 of 73) | prompt: the reproduction has at most 25 lines and no comments but the claim lines; the reply starts with FILES: | R96 |
| 10 | none of this was measured | `scripts/replay_l4.py` reports the v10.1 diagnostic KPIs next to the frozen race-2 rows (race2_checklist Addenda 2) | R129 |

Not applied here, each for a stated reason (section 14): the locator's `max_output_tokens` stays 768 (1,536 breaks the
R95 B margin of the fixer: the p90 plan of 1,087 tokens would enter every fixer call); `LoopAgent` around the
submitter (the tree stays R78's; a stage that ends without a submit is already restarted by the harness nudge); the
context-meter reset at the fixer's start and CONTEXT enforcement in the locator (a status call first breaks the
first-round invariant of `test_context_meter_does_not_cut_a_normal_first_round`); run.py heredoc mode, a per-stage call
budget and "first edit within 5 calls" (behaviour levers that need their own arm).

---

## 1. Bundle file tree (exact)

```
submissions/v10/
  agent.yaml
  eval_config.yaml
  configs/gen_setup.yaml
  configs/gen_locator.yaml
  configs/gen_fixer.yaml
  configs/gen_verifier.yaml
  configs/gen_submitter.yaml
  sub_agents/setup.yaml
  sub_agents/locator.yaml
  sub_agents/fixer.yaml
  sub_agents/verifier.yaml
  sub_agents/submitter.yaml
  prompts/setup.md
  prompts/locator.md
  prompts/fixer.md
  prompts/verifier.md
  prompts/submitter.md
  skills/swe-tools/SKILL.md
  skills/swe-tools/scripts/_swe_common.py   library: paths, clock, args, stdin, subprocess, output, git, hygiene, state
  skills/swe-tools/scripts/_swe_index.py    library: AST symbol index (cached)
  skills/swe-tools/scripts/_swe_gate.py     library: base tree, claims, tests, discovery, siblings, spec gaps, score
  skills/swe-tools/scripts/_swe_ckpt.py     library: checkpoints, transactional restore
  skills/swe-tools/scripts/install.py
  skills/swe-tools/scripts/locate.py
  skills/swe-tools/scripts/grep.py
  skills/swe-tools/scripts/view.py
  skills/swe-tools/scripts/edit.py
  skills/swe-tools/scripts/run.py
  skills/swe-tools/scripts/verify.py
  skills/swe-tools/scripts/finalize.py
  skills/swe-tools/scripts/status.py
```
The tree has 31 files. No `.sh`, dotfiles, `__pycache__`, symlinks or extensionless files. No script stem is in
`sys.stdlib_module_names` (checked under Python 3.12.14: none of the 13 names shadow).

---

## 2. YAML (every file, exact content)

`agent.yaml`
```yaml
name: swe_pipeline
agent_class: SequentialAgent
description: Setup, locate, fix, verify, submit; fresh context per stage.
sub_agents:
  - config_path: sub_agents/setup.yaml
  - config_path: sub_agents/locator.yaml
  - config_path: sub_agents/fixer.yaml
  - config_path: sub_agents/verifier.yaml
  - config_path: sub_agents/submitter.yaml
```

`eval_config.yaml`
```yaml
evaluation:
  max_time_minutes: 5
  timeout_seconds: 180
  max_tool_calls: 100
  max_turns: 200
```

`sub_agents/setup.yaml`
```yaml
name: setup
model: gemma-4-31b-it-qat-w4a16-ct
description: Installs the helper scripts.
include_contents: none
instruction: !include ../prompts/setup.md
tools: [run_command, read_file, edit_file, write_file, get_status, get_code_neighbors, search_similar_code, get_code_subgraph]
skills: [skills/swe-tools]
generate_content_config: !include ../configs/gen_setup.yaml
```

`sub_agents/locator.yaml`
```yaml
name: locator
model: gemma-4-31b-it-qat-w4a16-ct
description: Finds the code to change and writes a reproduction.
include_contents: none
instruction: !include ../prompts/locator.md
tools: [run_command, read_file, edit_file, write_file, get_status, get_code_neighbors, search_similar_code, get_code_subgraph]
skills: [skills/swe-tools]
output_key: plan
generate_content_config: !include ../configs/gen_locator.yaml
```

`sub_agents/fixer.yaml`
```yaml
name: fixer
model: gemma-4-31b-it-qat-w4a16-ct
description: Implements the change.
include_contents: none
instruction: !include ../prompts/fixer.md
tools: [run_command, read_file, edit_file, write_file, get_status, get_code_neighbors, search_similar_code, get_code_subgraph]
skills: [skills/swe-tools]
output_key: fix_notes
generate_content_config: !include ../configs/gen_fixer.yaml
```

`sub_agents/verifier.yaml`
```yaml
name: verifier
model: gemma-4-31b-it-qat-w4a16-ct
description: Checks, repairs and submits the change.
include_contents: none
instruction: !include ../prompts/verifier.md
tools: [run_command, read_file, edit_file, write_file, get_status, get_code_neighbors, search_similar_code, get_code_subgraph, submit_patch]
skills: [skills/swe-tools]
generate_content_config: !include ../configs/gen_verifier.yaml
```

`sub_agents/submitter.yaml`
```yaml
name: submitter
model: gemma-4-31b-it-qat-w4a16-ct
description: Submits the patch if not yet submitted.
include_contents: none
instruction: !include ../prompts/submitter.md
tools: [run_command, read_file, edit_file, write_file, get_status, get_code_neighbors, search_similar_code, get_code_subgraph, submit_patch]
skills: [skills/swe-tools]
generate_content_config: !include ../configs/gen_submitter.yaml
```

`configs/gen_<stage>.yaml`: all five share one shape. Only `temperature` and `max_output_tokens` differ:
```yaml
temperature: <T>
top_p: 0.95
top_k: 64
max_output_tokens: <M>
thinking_config:
  include_thoughts: false
```

| file | T | M | why |
|---|---|---|---|
| gen_setup.yaml | 0.2 | 256 | a one-call stage, near-greedy, so it copies the literal call |
| gen_locator.yaml | 1.0 | 768 | v4/v9 sampling (the only measured one). Review round 2: 768 (from 1,536) bounds the plan at about 2.4x the 120-word target (about 321 tokens). Race-1 locator replies ran median 418-442 and p90 1,020-1,087 tokens. A runaway now costs about 27 s, not 54 s. Race-1 locator tool calls reached 768 in 3 of 5,622 (p99 172-418). |
| gen_fixer.yaml | 1.0 | 2048 | covers every legitimate L4 tool call (time_model 3); runaway about 58 s |
| gen_verifier.yaml | 1.0 | 2048 | same |
| gen_submitter.yaml | 0.2 | 1024 | a one-job stage |

Rules:
- No `seed`, which never reaches vLLM (config_space #1).
- No `thinking_level`, where a typo silently enables thinking (#2).
- `include_thoughts: false` compiles to `chat_template_kwargs.enable_thinking=false` (R80 checks the compiled value).

The tool policy:
- **BASE8** is exactly the v9_eog set, which had 0 unknown-tool crashes in race 1. It is declared on every stage because
  an undeclared name ends the task (`SP/google/adk/flows/llm_flows/functions.py:490-504`).
- **`submit_patch`** is declared only on the verifier and the submitter.
- **`skills: [skills/swe-tools]`** is on every stage, so install and self-install are possible everywhere.

---

## 3. Prompts (full text) and SKILL.md

Prompt rules. Each rule is a lint, R87-R96 plus R89b/R89c (v10.1).
1. Braces: only `{problem_description}`, `{plan?}` and `{fix_notes?}`. No other `{` or `}` characters at all.
2. Backticks: 0 in prompts and in SKILL.md.
3. Tool-call examples are in template order: `run_skill_script(file_path="install.py", skill_name="swe-tools")`.
4. A tool is named only when that stage declares it. `submit_patch` is named only in the verifier and submitter prompts.
   The graph tools are never named.
5. Every helper flag a prompt uses exists in that helper's `FLAGS` (R92).
6. Shared blocks are byte-identical wherever they appear: RECOVER, AMNESIA and TIME in locator, fixer and verifier;
   HELPERS (v10.1) in those three and the submitter; RECOVER also in submitter; EDITFORM in fixer, verifier and
   submitter.
7. Measured sizes, excluding placeholders:

   | stage | words | chars |
   |---|---|---|
   | setup | 76 | 452 |
   | locator | 369 | 2,353 |
   | fixer | 364 | 2,337 |
   | verifier | 368 | 2,255 |
   | submitter | 185 | 1,198 |

   Limits enforced by R91: 370 words and 2,600 chars for each prompt, and 1,300 chars for the submitter.
8. **Helper naming (R89b, v10.1).** In prompts, SKILL.md, YAML and every string a helper prints, a helper file name
   `NAME.py` appears only inside `python3 /tmp/swe/NAME.py ...` or inside the exact skill call
   `run_skill_script(file_path="NAME.py", skill_name="swe-tools")`. Never as a verb ("view.py the candidates"), a noun
   ("with edit.py"), a list item, a usage fragment ("view.py FILE START END"), a `NAME.py` template list, or a
   `/tmp/swe/NAME.py` path without `python3 `. Where the full command would repeat, an English word or a step
   reference is used ("View the plan's FILES", "run step 3 again"). Race 2 round 1: the model turned bare names into
   tool names 30 times in 21 tasks (one parsed `view.py` call crashed fastapi_13537; the other 29 were
   `<|tool_call>call:NAME` texts, and each ended its stage). The v9_eog prompts, which always wrote the full command,
   had 0.
9. **Run instructions (R89c, v10.1).** An instruction to run a helper is a sentence whose verb comes first ("Run
   python3 /tmp/swe/status.py ..."). A numbered step never starts with `python3`: `1. python3 /tmp/swe/status.py`
   opened 9 of 69 race-2 verifier stages as an unparsed call. The tool is named after the command ("with
   run_command"), never as a `run_command: CMD` prefix (v9_eog typed that form into the shell 23 times per 74). The
   HELPERS block says it once per stage.
10. **Handoff (v10.1).** The verifier is told that a tool call written as text in the [fixer] message never ran (5 of
    the 9 verifier turn-1 failures followed a fixer whose last reply was such a text). The locator's reproduction has
    at most 25 lines and no comments but the claim lines, and its reply starts with `FILES:` (race 2: 11 of 73 locator
    replies hit `max_output_tokens` 768, 6 of them repro calls full of commented reasoning).
11. **Submitting (v10.1).** The verifier and the submitter call `submit_patch` after finalize says READY, or at
    t>=285s (T_NO_RESTORE); an empty patch always fails, and a stage that ends without a submit is restarted by the
    harness nudge with the tree intact (harness_runtime 5.3). The submitter sees the issue (`{problem_description}`):
    race 2's fastapi_14873 submitter invented a SEARCH block for code it had never seen.

Shared blocks, verbatim:

RECOVER
```
If a /tmp/swe helper fails with "can't open file" or "No such file", call run_skill_script(file_path="install.py", skill_name="swe-tools") once, then repeat it.
```
AMNESIA
```
If your earlier tool results are gone (the context was shortened), run python3 /tmp/swe/status.py and continue from it.
```
TIME
```
Helpers end with the task time [t=...s]; the task stops at t=300s. Obey any LOCATOR, EDIT NOW, CONTEXT, FINISH or TIME line.
```
HELPERS
```
Run every python3 /tmp/swe command with run_command; helpers are never tool names.
```
EDITFORM
```
Edit only this way, with run_command, as raw code with no escaping (edit_file and write_file corrupt code here):
python3 /tmp/swe/edit.py path/to/file.py <<'EOF'
<<<<<<< SEARCH
exact current lines as viewed (the number column may stay)
=======
new lines
>>>>>>> REPLACE
EOF
Or replace lines by number: python3 /tmp/swe/edit.py path/to/file.py --lines 120-135 <<'EOF'
new lines
EOF
For a new file use --create instead of --lines. EOF appears once, as the last line. A broken edit is undone; a SEARCH that does not match prints the closest numbered lines for --lines. Edit the lowest place first. Never resend a failing edit.
```

### 3.1 `prompts/setup.md`
```
You are SETUP, stage 1 of 5. Your whole job is one tool call. Do not work on the issue; later stages do that.
1. Call exactly this tool, with exactly these arguments:
run_skill_script(file_path="install.py", skill_name="swe-tools")
2. Then reply with the single word READY (text only, no tool call).
If the call returns an error, call it once more exactly as written above (plain values, no extra quotes), then reply READY.
Do not call any other tool.
```

### 3.2 `prompts/locator.md`
```
You are the LOCATOR, stage 2 of 5. Find the code to change in /workspace and write a reproduction; you edit nothing, the next stage does.

Issue:
{problem_description}

Helpers:
python3 /tmp/swe/locate.py "identifiers, error text and key words"
python3 /tmp/swe/grep.py "regex"   (source only; add --tests for tests)
python3 /tmp/swe/view.py FILE START END   or   python3 /tmp/swe/view.py FILE NAME   (NAME: function, Class or Class.method)
python3 /tmp/swe/run.py --timeout 20 "command"   (run other code only this way)
<HELPERS>
<RECOVER>
<AMNESIA>
<TIME>

Steps (about 8 tool calls; reply by t=90s):
1. Locate the issue's names and error text. If the issue is only a title, turn its words into code names first (proxy gives *Proxy classes, padding width gives *padding_width*). Never search issue numbers.
2. View the best candidates; grep exact names from the issue. A name the repository does not define comes from a dependency: python3 /tmp/swe/view.py --obj package.module.Name shows its source. Print real objects; never guess library types.
3. If a script can show the bug, write a reproduction that FAILS now: one # CLAIM line per behaviour the issue asks for, with its exact inputs and expected values; at most 25 lines and no other comments:
python3 /tmp/swe/verify.py --repro-only <<'EOF'
from package.module import thing
# CLAIM 1: short description
out = thing("input from the issue")
assert out == "expected from the issue", repr(out)
EOF
It must say fails on original; if a claim passes on original, rewrite it once with another input shape. Assert exact text only if the issue states it.
4. Stop and reply with the plan (text only, under 120 words, starting with FILES:):
FILES: path:start-end (function) for every place to change
CAUSE: one sentence
FIX: what to change, with the exact names, messages and signatures the issue gives
REPRO: fails on original, or none
TESTS: an existing test file for it
```
(`<RECOVER>`, `<AMNESIA>`, `<TIME>` and `<HELPERS>` stand for the verbatim blocks above, one per line. The same applies
below.)

### 3.3 `prompts/fixer.md`
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
1. If the plan is empty, run python3 /tmp/swe/locate.py "key words" first. View the plan's FILES.
2. Make the smallest COMPLETE change: every place the plan lists, the exact names, messages and signatures the issue gives, the style of the neighbouring code, unchanged behaviour for other inputs. The current code IS wrong: never conclude that nothing needs changing.
3. Run python3 /tmp/swe/verify.py and act on it, at most 2 rounds: a CLAIM that still fails means fix the code (not the reproduction); SIBLINGS means make the same fix where the same defect is; SPEC GAPS means add what is missing; for REGRESSIONS follow its note.
4. Stop and reply (text only, under 60 words):
CHANGED: file function (lines)
VERIFY: the first line verify printed
Never edit tests, conftest.py, pytest.ini, pyproject.toml, setup.cfg or tox.ini: graders replace them.
```

### 3.4 `prompts/verifier.md`
```
You are the VERIFIER, stage 4 of 5: check the change in /workspace, repair it if needed, submit.

Issue:
{problem_description}

Plan:
{plan?}

The fixer's notes are the [fixer] message below; a tool call written there as text never ran.

<EDITFORM>
<HELPERS>
View files only with python3 /tmp/swe/view.py FILE START END and run other code only with python3 /tmp/swe/run.py --timeout 20 "command".
<RECOVER>
<AMNESIA>
<TIME>

1. Run python3 /tmp/swe/status.py (the diff and what earlier stages did).
2. If no source file is changed, make the smallest plausible version of the plan's change now.
3. Run python3 /tmp/swe/verify.py (no flags).
- GREEN or AMBER: go to step 4.
- RED: fix what it names and run step 3 again; at most 2 repair rounds, none after t=240s.
- REGRESSIONS: a test that passed before now fails. If it checks the OLD behaviour the issue asks to change, keep your fix; otherwise fix the regression.
4. Run python3 /tmp/swe/finalize.py; it keeps the best checked version. If it says NOT READY, fix what it names and run it again.
5. Call submit_patch after READY (or at t>=285s), then reply with one short sentence. submit_patch is your last tool call.
If a helper prints TIME, go straight to step 4.
```

### 3.5 `prompts/submitter.md`
```
You are the SUBMITTER, the last stage. The patch has not been submitted yet.

Issue:
{problem_description}

Plan (for reference):
{plan?}

1. Run python3 /tmp/swe/finalize.py
2. Only if it says EMPTY: make the plan's FIX (the smallest version), then run step 1 again.
3. Call submit_patch after READY (or at t>=285s), then reply with the one word submitted.
<EDITFORM>
<HELPERS>
<RECOVER>
```

### 3.6 `skills/swe-tools/SKILL.md`
The usage lines must equal each script's `USAGE` constant (R93).
```
---
name: swe-tools
description: Repository helpers for this task. Install once with run_skill_script(file_path="install.py", skill_name="swe-tools"), then run each helper with run_command as python3 /tmp/swe/NAME.py.
---
# swe-tools
Install: run_skill_script(file_path="install.py", skill_name="swe-tools")
Any helper run through run_skill_script also installs all of them. Options work as args, for example file, start and end.
- python3 /tmp/swe/locate.py "QUERY"
- python3 /tmp/swe/grep.py "REGEX" [PATH ...] [--tests] [--max N]
- python3 /tmp/swe/view.py FILE [START END | NAME] | --obj DOTTED.NAME
- python3 /tmp/swe/edit.py FILE [--lines A-B [--delete] | --insert-after N | --create] <<'EOF' ... EOF
- python3 /tmp/swe/run.py [--timeout N] "COMMAND"
- python3 /tmp/swe/verify.py [--repro-only] [--tests FILE ...] [--list-tests]
- python3 /tmp/swe/finalize.py
- python3 /tmp/swe/status.py
```

### 3.7 Handoffs

| from -> to | channel | format | bound |
|---|---|---|---|
| harness -> setup | harness prompt (stage 1 only) | problem, budgets, rules, 150-line tree | fixed |
| setup -> locator | `For context: [setup] said: READY` | one word | 5 tokens |
| locator -> fixer | the handoff event only (review round 2: `{plan?}` paid for it a second time) | FILES/CAUSE/FIX/REPRO/TESTS | 120 words asked; measured p90 1,087 tokens, cut at 768 by `max_output_tokens` |
| fixer -> verifier | `{plan?}` plus the handoff event (the notes; `{fix_notes?}` removed in review round 2) | CHANGED/VERIFY | 60 words asked; measured p90 244 tokens |
| any -> later | `$SWE/journal.jsonl` via `status.py`, `$SWE/repro.py`, `$SWE/state.json`, checkpoints | files | status 2,200 chars or fewer |
| verifier -> submitter | only when the verifier replied without submitting | handoff plus `{plan?}` | small |

`output_key` is written only on a final text reply, so every downstream placeholder is the optional form (`{plan?}`).
The previous stage's final reply always reaches a stage as the handoff event (`For context:[prev] said: <reply>`,
facts_internal 2.3), so no stage has a placeholder for its previous stage's `output_key`. Such a placeholder would
pay for the same text twice (TP::test_handoff_paid_once). `fix_notes` is still stored but no prompt reads it. After an
in-flow compaction the handoff becomes the summary, so the fixer's instruction no longer carries the plan. The
summary, `status.py` (repro, journal, diff) and the checkpoints are what is left (section 6).

---

## 4. Helpers

### 4.0 Contract shared by every CLI script

1. **Preamble.** Verbatim, the first lines of every CLI script (R02). It captures the original `sys.path[0]` for the
   skill-wrapper case, keeps only the script dir and stdlib paths, drops shadowed stdlib modules and disables `.pyc`
   writes:
   ```python
   import os, sys
   sys.dont_write_bytecode = True
   _HERE = os.path.dirname(os.path.abspath(__file__))
   os.environ.setdefault("SWE_PATH0", sys.path[0] if sys.path else "")
   _STD = tuple({os.path.realpath(p) for p in (sys.base_prefix, sys.base_exec_prefix)})
   sys.path[:] = [_HERE] + [p for p in sys.path if p and os.path.realpath(p).startswith(_STD) and "-packages" not in p]
   for _n in [n for n, m in list(sys.modules.items()) if n.split(".")[0] in getattr(sys, "stdlib_module_names", ())
              and getattr(m, "__file__", None) and not os.path.realpath(m.__file__).startswith(_STD)]:
       del sys.modules[_n]
   import _swe_common as C
   ```
2. **Main.** `C.safe_main(name, main)` runs `main()`. Any exception prints
   `HELPER ERROR <name>: <Type>: <msg>` in 300 chars or fewer. The script always exits 0. A non-zero `SystemExit` becomes
   a skill error, and `run_command` duplicates output on a non-zero exit (harness_runtime 3.2, 4).
3. **Bootstrap.** `C.bootstrap()` is the first call in `main`. When `_HERE` is not an installed dir (it has no `VERSION`
   file starting with `v10`), it silently installs every sibling `.py` (section 4.2), then continues from `_HERE`. So any
   `run_skill_script` of any helper installs all of them.
4. **Arguments.** `C.parse_args(argv, FLAGS, positionals)`.
   - Accepted forms: `--k v`, `--k=v`, bare booleans or booleans followed by `1/0/true/false/yes/no` (case-insensitive;
     the wrapper passes `str(True)` = `True`). A bare `--` is ignored (the wrapper inserts it before `positional_args`).
   - List flags consume values until the next `--x`. `--text` supplies stdin content.
   - An unknown flag prints `USAGE ERROR: unknown option --x. Usage: <USAGE>`.
   - No arguments where some are required prints `USAGE`.
   - Every script exports `USAGE: str` and `FLAGS: dict[str, str]` (kinds: `str`, `int`, `bool`, `range`, `list`) for
     the prompt lint (R28, R92).
5. **stdin.** Only `edit.py` and `verify.py --repro-only` read stdin, through `C.read_stdin()`:
   - `''` when stdin is a TTY, closed or `/dev/null`, or when `select` reports nothing readable within 1.0 s;
   - otherwise everything up to EOF (no size limit; a 64 kB+ heredoc is read completely);
   - then `\r\n` becomes `\n`, and a trailing line matching `^\s*(SWE_)?EOF\W*$` and a trailing lone backtick line are
     stripped.
6. **Output.** `C.emit(name, first_line, body, cap)`:
   - the first line is the status or verdict;
   - the body is capped by `C.cap()`: ANSI/OSC stripped, `\r` normalised, head/tail kept with the marker
     `... [N lines cut; full output: /tmp/swe/last.log] ...`, a single line over 400 chars cut to 200 + ` ... ` + 100, the
     last pytest summary line always kept;
   - then the footer (section 4.1.7);
   - total output, footer included, stays within the helper's cap (4.14). The full text goes to `$SWE/last.log`.
7. **Children.** `C.sh()` always uses `start_new_session=True`, `stdin=DEVNULL`, a deadline and `os.killpg(SIGKILL)`,
   and reaps the session on normal exit too. Children that import repo code get `C.grader_env()`. Helpers never import
   repo code in-process.
8. **Paths.**
   - No `/tmp` or `/workspace` string literal used as a path. Exceptions: `C.DOCKER_TMP = "/tmp"` and the display text
     `/tmp/swe` (R04).
   - Every git call is `git -c core.quotepath=off ...`, with `-z` where it lists paths.
9. **No destructive git.** No `reset --hard`, `checkout .`, `checkout -- .`, pathless `clean -f`, or `stash`. Workspace
   reverts are only path-scoped `git checkout <baseline> -- <path>`, one path per call, because one unknown pathspec aborts
   the whole checkout (the harness no-op bug F1). The only other workspace writers are `edit.py`, hygiene and checkpoint
   restore (R05).
10. **Helper output never names a tool** other than `run_command` and `run_skill_script` (R89). The FINAL/TIME hints say
    "end your stage" or "the stage that can submit should submit now", never the tool name. **v10.1 (R89b):** it names a
    helper only as its full command: "Verifier: run python3 /tmp/swe/finalize.py next.", "then run
    python3 /tmp/swe/verify.py again.", never "run finalize.py" (race 2: a bare name in 531 of 1,859 helper outputs).

### 4.1 `_swe_common.py` (owned by `helpers-core`; pinned API)

1. **Constants.**
   ```
   VERSION = "v10.1";  DOCKER_TMP = os.environ.get("SWE_DOCKER_TMP_FOR_TESTS") or "/tmp";  DISPLAY_SWE = "/tmp/swe"
   CAP_S = 300; T_LOCATOR = 75; T_EDIT_NOW = 150; T_FINISH = 210; T_QUICK = 235; T_TIME = 250; T_SAFE = 255
   T_VERIFY_END = 262; T_EVAL_END = 272; T_NO_EVAL = 275; T_NO_RESTORE = 285
   QUICK_PAD = 15
   RUN_DEFAULT = 20; RUN_MAX = 90; VIEW_OBJ = 15; LOCATE_PARSE = 15; ORIGIN_PROBE = 5; VERIFY_TOTAL = 60
   IMPORT_CHECK = 10; CLAIM_TIMEOUT = 10; CLAIMS_TOTAL = 25; PYTEST_SIDE = 40; FINALIZE_QUICK = 12; MAX_PAR = 2
   CAPS = {"install": 400, "locate": 1800, "grep": 1800, "view": 2800, "edit": 1500, "run": 2500,
           "verify": 2000, "finalize": 1400, "status": 2200}      # finalize 1,000 -> 1,400 in v10.1 (EDIT TARGET)
   CAP_TOKENS = {k: v // 3 for k, v in CAPS.items()}
   CONTEXT_TOKENS = 4700; CTX_CALL = 30
   ```
   Every timeout constant is at most 110 s, which is `timeout_seconds` - 10 (R86).

   **End-game plan (review round 1).** Every `verify.py` run is over by `T_VERIFY_END` (262); `verify --repro-only` and
   finalize's quick evaluation are over by `T_EVAL_END` (`T_NO_EVAL` - 3 = 272). finalize can then evaluate before
   `T_NO_EVAL`, restore before `T_NO_RESTORE`, and the patch is submitted before `CAP_S`. Before this, a full verify
   started anywhere in 225-270 s could run to about 294 s.
2. **`swe_dir()`.** The first match wins:
   1. `_HERE`, if it holds `VERSION` (installed mode: `python3 /tmp/swe/x.py` resolves to this dir in both backends);
   2. `$SWE_DIR` (tests);
   3. `$TEST_TMPDIR/swe` (subprocess: `<root>/tmp`, `SP/swegemma/sandbox/subprocess.py:483-501`; Docker: `/tmp`,
      `docker.py:93`);
   4. `$TMPDIR/swe`;
   5. `tempfile.gettempdir()/swe`.

   `install_targets()` returns the primary (rules 2-5) plus `DOCKER_TMP/swe`. The second target is added only when all of
   these hold: `TEST_TMPDIR` is unset, `in_rewriting_sandbox()` is false, `$SWE_DUAL` is not `0`, the path differs from the
   primary, and the parent is writable. `in_rewriting_sandbox()`: `TEST_TMPDIR` or `TMPDIR` ends in `/tmp`, and the parent
   basename starts with `swegemma_sandbox_`.
3. **`ws()`.** For each candidate in `$SWE_WS`, `os.getcwd()`, `$PWD`, `$SWE_PATH0`, `/workspace`: walk up to the first
   directory containing `.git` (dir or file), skipping anything under `swe_dir()`. `/workspace` is taken only if it has
   `.git`. The fallback is the cwd. The result is cached for the process. (bash exports `PWD` even in the sanitised env,
   harness_runtime 2.4. The skill wrapper keeps `sys.path[0]` = workspace, `skill_toolset.py:571-706`.)
4. **`baseline()`.** `git rev-parse -q --verify refs/tags/_swegemma_baseline^{commit}`, else HEAD recorded at the first
   call. Cached in `state["baseline"]`. `submit_patch` diffs against the same tag (`SP/swegemma/tools/execution.py:83-86`)
   (R11).
5. **`clock()`.**
   - Return `$SWE_FAKE_CLOCK` as a float if it is set.
   - Otherwise take `t0` from the first of these that lies within [0, 900] s of now: the committer time of `baseline()`
     (created just before the agent timer, `container_setup.py:575-582`); the mtime of
     `.git/refs/tags/_swegemma_baseline`; then `$SWE/t0` (written once by any helper).
   - Return `(now - t0) * scale`, where `scale = float($SWE/clock_scale)` clamped to 0.2..5 (the pod L4 hook; the file
     never exists on Kaggle), else 1.0 (R12).
6. **`real_budget(default_s)`.** `min(default_s, max(1.0, (CAP_S - clock()) / scale - 4.0))`. Every subprocess deadline
   and every helper-global deadline goes through it. `run_command` gets `max(5, remaining)` (`execution.py:27-40`), so a
   helper always finishes before the harness kills its process group (R13).
7. **Footer.** `footer()` returns `[t=Ns]` plus at most one hint line, the first that applies (v10.1 priority: FINAL >
   EDIT NOW > TIME > FINISH > CONTEXT > LOCATOR; an empty tree is never told to end its stage):
   - `FINAL: the patch was finalized at t=Ns; nothing more to change. The stage that can submit should submit now; any other stage should reply done.`
     Shown when `state.final_done` is set and the current diff sha equals `state.final_sha`.
   - `EDIT NOW: no source file changed at t=Ns; an empty patch always fails. Locator: reply with your plan now. Other stages: make the smallest plausible version of the plan's change now.`
     Shown when no source change exists and either t >= `T_EDIT_NOW` or `locator_over()`: the journal holds an edit, a
     finalize, a restore or a full verify, or the context meter left the locator phase or saw `status.py`. From `T_TIME`
     on it ends with ` Then run python3 /tmp/swe/finalize.py once.` (race 2: fastapi_14851 read "End your stage now" on an
     empty tree and timed out; fastapi_15280's verifier read "Other stages: ignore this line").
   - `TIME: t>=250s. End your stage now; reply in one line, under 30 words (verifier: run python3 /tmp/swe/finalize.py next).`
     (v10.1: rich_4079's 917-token reply after TIME carried it past the cap.)
   - `FINISH: t>=210s. Stop exploring; keep the edit you have and end your stage with a short reply.`
   - `CONTEXT: this stage's context is nearly full. Locator: reply with your plan now. Fixer: make any missing edit, then reply with your notes. Verifier: run python3 /tmp/swe/finalize.py next.`
     Shown when the context meter (below) reaches `CONTEXT_TOKENS` with this call.
   - `LOCATOR: 75s used. Locator: stop and reply with your plan now. Other stages: ignore this line.` Shown when no source
     change exists and the locator stage is not over.

   `emit()` computes the source-change state for every call at t >= `T_LOCATOR` (EDIT NOW outranks FINISH and TIME).

   **Token caps and the context meter (review round 1).** `emit()` also caps its output by estimated tokens,
   `est_tokens = ASCII chars / 3 + non-ASCII chars x 2.7`, at `CAP_TOKENS[name]` (and `cap / 3`): the body shrinks first,
   then the head and tail, and the footer is always kept. ASCII output never reaches these caps, but a rendered table of
   box drawing (measured at 0.36-0.63 chars/token) can no longer spend 3x a helper's budget. Every call also adds its
   estimated tokens (output, the model-written arguments and heredoc, plus `CTX_CALL`) to `state.ctx`, the meter of the
   current stage. The meter restarts at `status.py` (verifier step 1, and any stage recovering after compaction). The
   first `edit.py` after the locator starts the fixer's count with its trailing view/grep calls (at most 3). The setup
   stage's `install.py` does not count. R95 derives `CONTEXT_TOKENS` (section 6).

   Before building the footer, `emit()` calls `late_guard()`. When `clock() >= T_SAFE`, no source change exists, the
   state is not final, and `$SWE/ckpt` holds a non-empty checkpoint, it imports `_swe_ckpt` lazily (skipped on
   ImportError) and restores the best checkpoint. The output is then prefixed with
   `RESTORED checkpoint #k: the tree had no source change at t=Ns.` (R76).
8. **`sh(argv_or_cmd, timeout, cwd=None, env=None)`** returns `(rc | None, text)`. `sh_many(jobs, deadline)` runs at most
   `MAX_PAR` at a time through threads. Output is merged, capped at 4 MB, and decoded UTF-8 with `errors="replace"`
   (R14).
9. **git helpers.**
   - `git(args, timeout=10)`.
   - `changes(hidden=True)` returns `dict(source, protected, untracked, deleted)` from
     `git diff --name-status -z <baseline>` plus `git ls-files --others --exclude-standard -z`, classified by
     `is_protected`. No write to the real index. v10.1: the untracked listing passes `NO_GUARD`
     (`-c core.excludesFile=/dev/null`), and with `hidden=True` the diff runs on a private copy of the index whose
     assume-unchanged marks are cleared, so the helpers still see what the submit guard (4.1.17) hides from the patch.
     That copy costs about 20 ms, so it is skipped while every guarded file keeps the size and mtime a full check found
     clean (`$SWE/guard_stat.json`; a file found changed is kept as "dirty" until a full check finds it clean, and newly
     armed flags drop the snapshot). `source_changed()` uses `hidden=False` (the guard hides only protected files). An untracked `.py` inside a directory is a new module (source). A root-level one
     is source only when `root_module_kept()` says so (review round 1). Its name must not look like scratch, must not be
     a stdlib module, and must not name a baseline root entry. The baseline must also track root-level modules other
     than `setup.py`, `conftest.py`, `noxfile.py`, `fabfile.py`, `tasks.py`, `manage.py`, `runtests.py` and
     `versioneer.py`, or a changed tracked file must import it. Root check/verify scripts such as `check_fix.py` or
     `verify_box_order.py` are therefore scratch: they are not a source change, and verify says NO SOURCE CHANGE.
   - `diff_bytes()` returns bytes equal to what `submit_patch` would produce, built without touching the real index:
     copy `.git/index` to `$SWE/idx`, then `GIT_INDEX_FILE=$SWE/idx git add -A`, then
     `git diff --cached --binary <baseline>` (R21).
   - `diff_sha()` is the sha1 of `diff_bytes()`.
10. **`is_protected(rel)`** returns a reason string or None:
    - basename `test_*.py`, `*_test.py`, or one of `conftest.py`, `pytest.ini`, `.pytest.ini`, `tox.ini`, `setup.cfg`,
      `pyproject.toml`, `sitecustomize.py`, `usercustomize.py`, `_swegemma_stubs.py`, or a `*.pth` suffix (the
      verification list, `verification.py:60-83`);
    - first path component `tests`, `test` or `testing`, or a path containing `/tests/` or `/test/`;
    - a `.git` component;
    - absolute, or containing `..`, or outside `ws()`.

    Nested `pkg/testing/util.py` is allowed (R20).
11. **`hygiene_revert()`.**
    - Tracked protected paths that were modified or deleted: `git checkout <baseline> -- <p>`, one call per path.
    - Untracked protected paths: removed.
    - Returns the list, and the caller prints one line: `reverted test/config edits: a, b (graders replace test and config files, so a patch never carries them; do not redo this)`
      (v10.1: fastapi_14077's verifier read a bare "reverted pyproject.toml" as a lost edit and made it again).
    - Called by `edit.py` after every successful write, by `verify.py` step 0, and by `finalize.py` (R22).
12. **`unrewrite(text)`.** Only when `in_rewriting_sandbox()`: with `root = dirname(TEST_TMPDIR)`, it maps
    `root/tmp` to `/tmp`, `root/workspace` to `/workspace`, `root/venv/bin` to `/usr/local/bin` and `root/wheels` to
    `/wheels` (the command-text rewrite of `subprocess.py:432-481`). Otherwise it is the identity (R23).
13. **`grader_env(tree, side)`.**
    - Starts from `os.environ`, then sets `PYTHONSAFEPATH=1`, `PYTHONNOUSERSITE=1`, `PYTHONDONTWRITEBYTECODE=1`,
      `NO_COLOR=1` and `TMPDIR=$SWE/rt_<side>` (created).
    - `PYTHONPATH`: every entry equal to or under `ws()` is re-rooted to `tree`. When `PYTHONPATH` is empty (the Docker
      editable install), it is set to `tree`.
    - When the import-origin probe (4.4) found the package under `ws()/D` with `D` non-empty (for example `src`),
      `tree/D` is prepended.
    - `side` is `orig` or `cur` (R59).
14. **State.** `state_load()` and `state_update(fn)` work on `$SWE/state.json` under `fcntl.flock($SWE/state.lock)`,
    written atomically (tmp + `os.replace`). When `ws` or `baseline` in the state differs from the live values, the state,
    caches, repro and checkpoints are reset (R19). Schema: section 4.16.
15. **Journal.** `journal(event)` appends a JSON line to `$SWE/journal.jsonl`; `jtail(n)` renders the last n entries
    (for `status.py`).
16. **Repeat notes.** `repeat_note(helper, key)` counts `sha1(helper, key)` in the state and returns the helper's
    third-repeat note, or `''`.
17. **Submit guard (v10.1, race 2 diagnosis 3).** All hygiene above runs inside a helper call, but the harness takes the
    patch whenever it likes: `submit_patch` after a native `edit_file` (fastapi_14077 re-edited `pyproject.toml` after
    finalize), and the fallback diff `git add -N . && git diff --binary _swegemma_baseline` at a timeout, a tool-budget
    end or a nudge end (fastapi_14258 shipped a root `repro.py`; finalize never ran). `arm_submit_guard()` makes that
    diff blind to such paths from the first tool call on:
    - only in a harness workspace (the `_swegemma_baseline` tag exists), idempotent, a few git calls (under 1 s on a
      3,000-file repository);
    - `git ls-files -v -z`; every tracked path `_protected_git` flags gets `git update-index --assume-unchanged`
      (edits, overwrites and deletions of tracked test/config files then never reach `git add` or `git diff <tag>`;
      `git checkout <baseline> -- p` still restores such a file and keeps its mark);
    - `<gitdir>/swe_exclude` (inside `.git`, so never in a patch), named by `git config core.excludesFile`: root scratch
      prefixes in any case (`/[Rr][Ee][Pp][Rr][Oo]*` and scratch, debug, tmp, temp, try, demo), `*.log`, `*.orig`,
      `*.rej`, `*.bak`, `*.swp`, `.coverage`, vendored `site-packages/`, `_pytest/`, `*.dist-info/`, the protected
      names, `test_*.py`, `*_test.py`, `*.pth`, `tests/`, `test/`, `/testing/`; then `!/<name>` re-includes for
      baseline root entries and tracked vendored-named directories a pattern would hide (a tracked `templates/` or
      `src/_pytest/` keeps shipping new files);
    - called by `install.py` and at the top of `finalize.py` (a failed install, or a `read-tree` that dropped the marks);
    - `patch_violations(files)` applies the graders' rules to `[(path, is_new)]` (the harness's
      `_is_protected_test_or_config_path`, case-insensitive at any depth, plus new scratch or vendored files: KPI 7 and
      8), and `enforce_patch_rules()` undoes whatever the harness-view patch still carries (a staged scratch file, a
      new `.py` under a nested `testing/`).
    `diff_bytes()` keeps no override, so it still equals what `submit_patch` produces (R21).

### 4.2 `install.py`
- **CLI.** `run_skill_script(file_path="install.py", skill_name="swe-tools")`, or `python3 /tmp/swe/install.py`. No flags.
- **Effect.**
  - Copies every `*.py` next to it into each `install_targets()` entry. Each copy is atomic (tmp + `os.replace`, mode
    0644) and skipped when the sha1 is identical.
  - Writes `VERSION` (`v10.1`) and `t0` (only if absent).
  - Arms the submit guard (4.1.17): the setup stage's install is the first tool call, before any agent write.
  - Idempotent. Never touches the workspace files.
- **Output.** 400 chars or fewer, e.g.
  `swe-tools v10.1 ready in /tmp/swe (9 helpers). Next: python3 /tmp/swe/locate.py "key words"` plus the footer. The FINAL
  footer appears on a restart.
- **Budget.** 300 ms or less (v9 measured 25 ms) (R07-R09).

### 4.3 `_swe_index.py` (owned by `helpers-locate`; pinned API)
- **`build(ws, deadline_s=LOCATE_PARSE) -> Index`.**
  - Files come from `git ls-files -z -- '*.py'` (fallback `os.scandir` walk).
  - Skipped: files over 1 MB, vendored dirs (`site-packages`, `node_modules`, `.tox`, `build`, `dist`, `_vendor`,
    `vendor`) and hidden dirs.
  - Each file is `ast.parse`d with errors swallowed. Encoding: UTF-8, else `errors="ignore"`.
  - Cache: `$SWE/index_<baseline12>.marshal`, per file keyed by `(mtime_ns, size)`; only changed files are re-parsed.
  - When the deadline expires, what is parsed is kept, `Index.partial=True`, and the rest is scored by path tokens only.
- **API.**
  - `files`, `symbols(path) -> [Sym]` where `Sym = (qualname, kind in {def, async def, class}, start, end, params)`;
  - `defs_named(name) -> [(path, Sym)]`, `enclosing(path, line) -> Sym | None`, `span(path, qualname)`,
    `outline(path)`, `module_assigns(path) -> set`;
  - `bm25(query_tokens) -> [(score, path, Sym)]`, and `partial`.
- **Determinism.** Ties are broken by path, then line (R29).

### 4.4 `locate.py`
- **CLI.** `python3 /tmp/swe/locate.py "QUERY"` | `--query Q` | `--text Q`. It never reads stdin. `USAGE` =
  `python3 /tmp/swe/locate.py "QUERY"`.
- **Query cleaning** (v9 rules plus more):
  - strip HTML comments, PR checklists and template headings, URLs, `#\d+`, `gh-\d+`, and hex tokens of 7-40 chars;
  - apply the v9 STOP list;
  - tokens are identifiers plus their camel/snake splits.
- **Ranking.** v9 BM25 over AST symbols, unchanged: name tokens ×3, path, the first 3,000 chars of the body, and a module
  pseudo-symbol. Then:
  - symbol name in the query identifiers ×2.5; file stem in the query ×1.8; test files ×0.35;
  - **new:** `docs/`, `docs_src/`, `examples/`, `benchmarks/` ×0.6 (fastapi `docs_src` flooding, catalog P17);
  - **new:** bigram boost ×1.5 when a symbol's split tokens contain two adjacent query words in order ("padding width"
    gives `_get_padding_width`).

  Any further ranking change is allowed only if R98's recall does not drop and no rank-1 hit is lost.
- **Output** (1,800 chars or fewer):
  ```
  LOCATE: 2213 symbols in 118 files
  LAYOUT: packages rich (workspace) | tests tests/ | layout flat
  1. rich/text.py  score=41.2
       def Text.divide  L1040-1102
       def Text.split  L1104-1160
  ...up to 6 files x 3 symbols...
  RELATED TESTS: tests/test_text.py tests/test_segment.py
  [t=14s]
  ```
  - LAYOUT: the top-level packages (dirs with `__init__.py` at the root or under `src/`), test dirs, and `flat` or `src`
    layout.
  - Import origin, one `ORIGIN_PROBE` subprocess under `grader_env(ws, "cur")`:
    `importlib.util.find_spec(pkg).origin` for each package. It prints `(workspace)` or
    `(OUTSIDE WORKSPACE: <path>; tests import that copy, not your edit)`, and caches the package-to-dir map in
    `state.origin` for `grader_env` (R38).
  - RELATED TESTS: at most 3 collectable test files that name the top symbols (one `git grep -l -w`).
  - A third call in one task appends `NOTE: 3rd locate call; stop searching and use what you have.` (R33)
- **Budget.** 3 s or less on the first call for 3k files, 300 ms or less cached (R32).

### 4.5 `grep.py`
- **CLI.** `python3 /tmp/swe/grep.py "REGEX" [PATH ...] [--tests] [--max N]`, with `--max` 40 by default, clamped to
  1..80. Positional or `--regex`; `--path DIR` still works. v10.1 (race 2: 74 of 206 calls wrote `grep.py "X"
  path/file.py`, and the path was folded into the regex): the first positional word is the regex; a later word that
  names an existing file or directory in the workspace (or one absolute path outside it) is searched; a later word that
  looks like a path (a `/` or `.py`) but does not exist gets `NOTE: X is not a path in the workspace; searched
  everywhere.`; any other later word still joins the regex (an unquoted pattern). A path the model names that is a test
  file or test directory is searched without `--tests`.
- **Runs** `git grep -n -I -E --no-color -e REGEX -- <path or .>` with a 5 s deadline. Test paths (the `is_protected` test
  rules) are dropped unless `--tests`.
- **Output.** First line `GREP: N hits in M files (shown K)`. Grouped by file, at most 5 per file, each line cut to
  160 chars, annotated `  (in def Class.meth)` from the index. An invalid regex gives one line,
  `GREP: invalid regex: <git message>`. 1,800 chars or fewer, 1 s or less (R34).
- **Views (review round 1).** Every hit printed is recorded as a derived view `[n, n, t, "d"]` of its file
  (`C.record_views`, one state update). Numbers taken from grep are current, so edit.py's STALE guard no longer
  redirects them. `locate.py` records the two numbers of each symbol span it prints (never the lines between them) the
  same way, and `verify.py` records its SIBLINGS rows
  and the `IMPORT: RED` file:line.

### 4.6 `view.py`
- **CLI.** `python3 /tmp/swe/view.py FILE [START END | NAME] | --obj DOTTED.NAME`. The skill form is
  `--file F --start N --end M --name X --obj D`. v10.1: the `L1191-1433` spans that locate.py and grep.py print are
  ranges too (`FILE L2-3`, `FILE:L2-3`, `FILE L2 L3`; fastapi_14851 and fastapi_5624 got "no def or class named").
- **Modes.**
  - Range. `START` and `END` are 1-based and inclusive, clamped to the file.
  - Symbol. `func`, `Class`, `Class.method`, nested classes and async defs, found through `Index.span`. With several
    matches, the first is shown and the others are listed.
  - Outline, when only FILE is given: at most 60 `kind qualname Lstart-end` entries.
  - `--obj`. A driver in a subprocess (`VIEW_OBJ` s, `grader_env(ws, "cur")`) imports the longest importable prefix,
    walks the attributes, and prints `origin: <path> [installed dependency: read-only]` (or `[workspace]`), the signature,
    for methods which base in the MRO defines the member, and the numbered source through `inspect.getsourcelines` after
    `inspect.unwrap`. An import that hangs gives `HANG importing <mod>` (R37).
- **Format.**
  - Header `<file> lines A-B of N`.
  - Lines formatted `f"{n:>5}| {line}"`, where lines come from `bytes.split(b"\n")`, so the numbers equal git's and
    `edit.py`'s. `str.splitlines` is never used (form feed and other separator chars must not shift numbering, F6).
  - `\r` stripped for display only. Non-UTF-8 is decoded `errors="replace"` with the note
    `[non-UTF-8 bytes shown as U+FFFD]`.
- **Bounds.** At most 100 lines and 4,000 chars. When clamped: `range clamped; next: python3 /tmp/swe/view.py FILE B+1 B+100`.
  A missing file gives one line. Each view is recorded as `state.views[file] += [[a, b, clock]]` for the stale guard.
- **Budget.** 200 ms or less excluding `--obj` (R35, R36).

### 4.7 `edit.py` (the only edit channel)
- **CLI.** `USAGE` = `python3 /tmp/swe/edit.py FILE [--lines A-B [--delete] | --insert-after N | --create] <<'EOF' ... EOF`.
  - The text comes from stdin, or from `--text`.
  - Skill form: `--file F --lines A-B --text "..."`.
  - FILE is relative to `ws()`, or absolute inside it.
- **Modes.**
  - SEARCH/REPLACE blocks (the default). Several blocks per call are applied in order to an in-memory copy; they are
    all-or-nothing.
  - `--lines A-B` replaces lines A..B (inclusive) with the text. Empty text gives
    `ERROR: no text on stdin (to delete lines add --delete)`.
  - `--lines A-B --delete`.
  - `--insert-after N`, where N=0 means the top of the file.
  - `--create`. It refuses an existing file and creates parent dirs.
- **Input normalisation**, before matching:
  1. `unrewrite()`;
  2. marker variants: `^<{5,9} ?SEARCH\s*$`, `^={5,9}\s*$`, `^>{5,9} ?REPLACE\s*$`, case-insensitive;
  3. if every non-blank line of a SEARCH (or REPLACE) body matches `^\s*\d+\| ?`, the prefix is stripped from that body.
- **Matching tiers.** For each block the first unique hit wins, and matching never goes fuzzier than tier 5:
  1. exact substring;
  2. line-wise `rstrip` (this also absorbs CRLF);
  3. unescape: decode `\\\"`, `\"`, `\'`, `\\n`, `\n`, `\t`, `\\` once in SEARCH (the double-JSON artefact,
     harness_runtime 3.1), then decode exactly one JSON level (`json.loads('"' + s + '"')` semantics, for a line with
     real escapes copied one level deep), and retry tiers 1-2. REPLACE is **not** decoded alike (review round 1: the
     prompts ask for raw code, so `"\n".join(parts)` became a real newline and `r"\\s+"` silently became `r"\s+"`).
     `replace_choices()` decodes REPLACE only for artefacts it carries itself. `\n` joins are decoded fully when the
     decoded SEARCH gained lines and REPLACE contains `\n`. Only the quote escapes are decoded when REPLACE has more `\"`
     or `\'` than the matched code. Otherwise REPLACE is kept as written. For `.py` files the first of these forms that
     compiles is used, and the journal records which one (`rdec`: raw, quotes or full);
  4. indentation-relative: compare `strip()`ped lines over windows of equal length, require a unique match, and re-indent
     REPLACE by (window first indent) - (SEARCH first indent). The delta may be negative, so dedent works.

  Tier names are printed: `exact`, `rstrip`, `unescape`, `indent`.
- **Outcomes** (first line):
  - `OK (<tier>): FILE lines A-B replaced (k old, j new). Now lines a-b:` plus the numbered region ±2, at most 30 lines.
  - `NO MATCH: FILE unchanged. Closest lines (similarity 0.82) are 118-121:` plus those numbered lines, plus
    `use: python3 /tmp/swe/edit.py FILE --lines 118-121 <<'EOF' ... EOF`. The closest window is found by a
    stripped-line-set prefilter, then `difflib.SequenceMatcher` on the top 5 same-length windows, in 300 ms or less on
    5k lines.
  - `AMBIGUOUS: SEARCH matches at lines 40, 88; add context lines or use --lines`.
  - `REVERTED: syntax error at line L (line k of your new text): <msg>. FILE unchanged.` The `.py` targets are compiled in
    memory, `compile(src_bytes, path, "exec", dont_inherit=True)`, with no .pyc. A file that did not compile before the
    edit is written with `WARNING: FILE did not compile before this edit either` instead.
  - `REFUSED: <reason from is_protected>` (plus `graders replace test files; this edit would make grading fail; put checks in a reproduction`)
    or `REFUSED: outside the repository`, or `REFUSED: FILE looks binary (NUL bytes); only text files can be edited.`
  - `NO CHANGE: the new text equals the old text.`
  - `ALREADY TRIED: this exact edit failed at t=Ns (<reason>). Do something different: python3 /tmp/swe/view.py FILE A B, then python3 /tmp/swe/edit.py FILE --lines A-B.`
    The key is `sha1(file|mode|range|text)` in the journal.
  - v10.1: `ERROR: the edit ended early: no ======= line and no >>>>>>> REPLACE line arrived, so nothing changed. A line EOF inside the block ends the heredoc and the rest ran as shell commands. Put EOF once, as the last line, and send the whole edit again.`
    when the text holds a SEARCH marker but no divider and no REPLACE marker anywhere (fastapi_14873 steps 36-37). It
    does not count as a failed edit.
  - After the third consecutive failure on one file: the numbered region around the last closest window plus the
    `--lines` recipe.
  - `STALE: lines moved by +d since your last view of this region; the same code is now at A'-B'. Re-run with --lines A'-B' or view it again.`
    This fires for `--lines`/`--insert-after` when the same file had a successful edit with `delta != 0` that ended above
    A and came after the latest view covering A..B. d is the sum of those deltas (R47). Views include the derived views
    that grep, locate and verify record for the numbers they print (section 4.5), so numbers taken from them after the
    edit are current. `--insert-after` has no new text to break a tie, so it is redirected only when the latest view
    covering N is a real view.py range or edit display, never on a derived view alone (review round 1).
- **Fidelity.**
  - Bytes are split on `\n` only and decoded UTF-8 with `surrogateescape`, so untouched bytes round-trip exactly
    (latin-1, invalid UTF-8).
  - The dominant EOL (CRLF or LF) is applied to inserted lines. A BOM is kept and ignored during matching.
  - A missing final newline stays missing unless the last line is edited (R44).
- **Warnings** (one line each):
  - the REPLACE contains `\"` while neither the SEARCH nor the matched region does;
  - the REPLACE starts at column 0 while the replaced first line was indented.
- **Post-edit.**
  - `hygiene_revert()`.
  - Journal `{h: "edit", ok, file, mode, start, end, delta}`, and `state.edits += [...]`.
  - A successful edit prints `NEXT: python3 /tmp/swe/verify.py` when the file is a source `.py` file.
  - v10.1: when the tree then has a source change, it is saved as an unscored `EDITED` checkpoint (`_swe_ckpt.save_edited`,
    4.10), so a landed edit the model undoes later can still be restored (fastapi_15280).
- **Budget.** Output 1,500 chars or fewer. p95 150 ms or less on a 5,000-line file (R50).

### 4.8 `run.py`
- **CLI.** `python3 /tmp/swe/run.py [--timeout N] "COMMAND"`.
  - Default 20. Clamped to 1..RUN_MAX, then by `real_budget`. An invalid value gives `NOTE: --timeout must be an integer; used 20`.
  - The command is the remaining positionals joined, or `--cmd`.
  - Runs `bash -c COMMAND` in `ws()` with `PYTHONDONTWRITEBYTECODE=1 NO_COLOR=1 TERM=dumb COLUMNS=120` added.
- **Output.**
  - Line 1 is `exit=N`, or `TIMEOUT after Ns (partial output below). If the issue is about a hang or loop, this may be the bug.`
  - Then `cap(..., 2500)`, with runs of identical lines collapsed to `line (xN)` and the pytest summary line kept.
  - When the output contains `pytest is disabled in this environment`, the note
    `Test runners are disabled by the harness here: check behaviour with a reproduction (python3 /tmp/swe/verify.py --repro-only) instead.`
    is appended.
  - The third identical (command, output sha) appends `NOTE: same command, same output 3 times; change something.`
- **Budget.** 100 ms or less overhead (R25, R26).

### 4.9 `_swe_gate.py` (owned by `helpers-verify`; pinned semantics)
1. **Base tree** (`base_tree() -> path | None`), made once per task and cached in `state.base`.
   - Remove a stale `$SWE/base` (`git worktree remove --force`, rmtree, `git worktree prune`).
   - Run `git -c core.hooksPath=/dev/null worktree add --detach -f $SWE/base <baseline>` (10 s). Fallback:
     `git archive <baseline> | tar -x -C $SWE/base` (20 s).
   - Copy the workspace's git-ignored files that sit inside a directory holding tracked `.py` files (built extensions
     `*.so`/`*.pyd`, generated `_version.py`, data files), from
     `git ls-files --others --ignored --exclude-standard -z`. Excluded: `__pycache__`, `.pytest_cache`, `*.pyc`,
     `*.egg-info`, `.adk_exec_*`. Limits: 2,000 files and 50 MB.
   - A failure makes the original side `UNKNOWN (base copy unavailable)`, never "fails".
2. **Claims** (`claims.parse(text)`, `claims.run(tree, side, sha)`).
   - Parsing: the prelude is everything before the first line matching `^#\s*CLAIM\s*(\d+)\s*:(.*)$`. Each section runs
     as prelude + section in its own `python3 -s <file>` process. The file is `$SWE/claims/<sha12>_<n>.py`, run with
     `cwd=tree` and `grader_env(tree, side)`, `CLAIM_TIMEOUT` s each.
   - Scheduling: at most `MAX_PAR` concurrent and at most 6 claims. The total is `real_budget(CLAIMS_TOTAL)`; unfinished
     claims are `UNKNOWN`. No header means one claim. Untracked files a run creates in `tree` (porcelain before and
     after) are deleted.
   - Per-side result: `PASS` (rc 0), `FAIL` (last exception line from the traceback tail), or `HANG` (killed).
   - **BROKEN**, decided on the original side only:
     - `SyntaxError`/`IndentationError` located in the claim file;
     - `NameError` whose innermost frame is the claim file (hint when the name is assigned in another section:
       `put shared code before the first # CLAIM line`);
     - `ModuleNotFoundError` for a top-level module that is neither a top-level package or module of the repo nor
       importable under the grader env.
   - Classes: `FIXED` (orig FAIL/HANG, now PASS), `STILL FAILS`, `STILL HANGS`, `BROKE` (orig PASS, now FAIL/HANG),
     `INVALID` (PASS on both), `BROKEN`, `UNKNOWN`. Valid claims are those whose orig is FAIL/HANG and not BROKEN. The
     summary is `k/n claims fixed` over valid claims.
   - Original results are cached in `state.repro.orig` by repro sha. They are run in `ws` when the source diff is empty,
     else in the base tree.
   - Automatic NEW names, parsed from original-side failure lines:
     `cannot import name 'X' from 'm'`, `module 'm' has no attribute 'X'`, `'C' object has no attribute 'x'`,
     `type object 'C' has no attribute 'x'`, `f() got an unexpected keyword argument 'p'`. Explicit headers anywhere in the
     prelude: `# NEW: a, C.b, f(p=)` and `# MESSAGE: "text"`.
3. **Import check.**
   - Each changed source `.py` is compiled in memory.
   - Module names come from the path (`src/` stripped; `__init__` becomes the package). Only files inside an importable
     package chain are included; deleted files are skipped.
   - One subprocess: `python3 -s -c "import importlib,sys;[importlib.import_module(m) for m in sys.argv[1:]]" m1 m2`
     under `grader_env(ws, "cur")`, `IMPORT_CHECK` s.
   - A failure gives `RED IMPORT <module>: <last line> (<ws file>:<line>)`.
   - The origin check (4.4) runs in the same subprocess (R56).
4. **Discovery** (`discover(changed, extra) -> [files]`).
   - Candidates: tracked `test_*.py` / `*_test.py` under 300 kB. Never `conftest.py`, `tests/render.py`,
     `tests/_card_render.py` or `tools/*.py` (v9 picked these 11/40 times).
   - Score:
     - 10 × in `--tests`;
     - 5 × named `test_<stem>.py` or `<stem>_test.py` for a changed module stem;
     - 3 × each changed def/class name of 4 chars or more that appears as a word (one `git grep -c -w -e n1 -e n2 ...`);
     - 2 × imports the changed module (`from pkg.mod import`, `import pkg.mod`, `from pkg import mod`);
     - 1 × mentions the stem.
   - Changed symbols: `-U0` hunk headers, `^[+-]\s*(async\s+)?def|class`, and `Index.enclosing` of every changed new-file
     line.
   - Top 3, ties by path. `--tests` entries go first and may be node ids `f::n` (R57).
5. **Test runs** (`run_tests(files)`).
   - Mask check, once per task via a subprocess:
     `importlib.util.find_spec("pytest")`, then read `<pkgdir>/__main__.py`. If it contains
     `pytest is disabled in this environment` (the harness shim text, `container_setup.py:988`), or pytest is absent, the
     result is `TESTS: unavailable (<why>)`. Pytest is never imported in-process and the mask is never bypassed (R61).
   - Command, per side:
     `python3 -s -m pytest <files> -q -p no:cacheprovider -p no:anyio -o timeout=0 -o python_classes="Test* *Test" --tb=short -rfE --junitxml=$SWE/j_<side>.xml`
     with `cwd=tree` and `grader_env(tree, side)`. The flags are the grader's (`verification.py:493`) plus
     `-p no:cacheprovider`. Never `-o addopts=`.
   - ORIGINAL and CURRENT run concurrently, at most 2 processes. Each gets `real_budget(PYTEST_SIDE)`.
   - ORIGINAL results are cached in `state.orig_tests[sha(files)]`.
   - Outcomes come from JUnit (`xml.etree`), keyed `(classname, name)` and displayed as `path::Class::name`.
     pytest names classnames after node ids relative to ITS rootdir, the directory of the nearest ini file. All 45
     rich snapshots ship `tests/pytest.ini`, so `tests/test_markup.py` reports as `test_markup`. `file_for()` therefore
     tries every dotted suffix of each file, dropping the fewest leading parts first, and needs a dot boundary.
     Module-level collection errors map the same way. Before review round 2, ids on rich tasks could not be re-run,
     and the de-flake rerun silently ran nothing.
   - `UNKNOWN`, never pass, when: exit code 2/3/4/5, no JUnit, 0 tests, the disabled text, or a timeout on both sides.
   - Collection errors (an `<error>` on a module-level testcase) on CURRENT only mean `collects=0`; on both sides they
     mean UNKNOWN for that file.
   - Regressions: passed on ORIGINAL, failed or errored on CURRENT. Each is re-run once, alone, on CURRENT before it is
     reported (de-flake).
   - A CURRENT timeout where ORIGINAL finished means `HANG-NOW` (R58, R60).
6. **SIBLINGS** (advisory).
   - Removed lines of source files from the `-U0` diff are kept when stripped length is 12 or more and they are not a
     comment, docstring quote, bracket, `pass`, `return`, `else:` or `try:`. Call expressions inside them
     (`[\w.]+\([^()]{4,40}`, 16 chars or more) are added.
   - One `git grep -n -F -I -e ...` over non-test `.py`, with at most 10 patterns. Hits inside changed new-file hunks are
     dropped.
   - Plus `Index.defs_named(n)` for each changed def name of 4 chars or more, in other classes or files that are
     unchanged.
   - At most 6 lines: `  path:line  code` (R66).
7. **SPEC GAPS** (advisory, static: index plus `git grep -F`).
   - A NEW name that is not defined anywhere in non-test source.
   - A NEW `C.x` absent from class C's body (def, class var, or a `self.x =` assignment).
   - A NEW `f(p=)`: every `Index.defs_named(f)` in non-test source lacks neither `p` nor `**kwargs`. Each missing def is
     listed.
   - A MESSAGE whose literal, or longest constant fragment of 12 chars or more, is absent from non-test source.
   - At most 4 lines. EXISTS names never count (R67).
8. **Score and key.**
   - `score = (nonempty, imports_ok, collects, no_hang, fixed - broke, -regressions)`, compared lexicographically.
   - Tests UNKNOWN count as 0 regressions and `collects=1`. No valid claims means `fixed - broke = 0`.
   - `key = sha1(repro_sha | sorted test files)`.
   - A quick score uses the first 5 components (R70).

### 4.10 `_swe_ckpt.py` (owned by `helpers-verify`)
- `save(diff_bytes, score, key, verdict, quick, rkey=None, meta=None) -> id`. Stores `$SWE/ckpt/<id>.diff` plus a
  `state.ckpts` entry `{id, sha, score, key, verdict, t, quick, rkey, classes, imp_def, incomplete}`. A diff sha that is
  already stored updates its entry. `meta` is `_swe_gate.evidence()` of the evaluation (review round 1). `classes` maps
  each claim to its class. `imp_def` says whether an import failure is definite: a syntax error, a full-length hang, or
  a failure compared with the original. `incomplete` means the score may understate the tree: a claim UNKNOWN, the
  import check skipped or stopped for time, or an import failure never compared with the original.
- `best(key=None, quick=False)` returns the highest score among non-empty checkpoints with the same key (or any key when
  `key=None`, used for the empty-tree case), preferring the latest on ties.
- `best_against(cur)` returns the checkpoint that strictly beats the current evaluation (same key and both full, else the
  same repro and the quick 5-tuples). UNKNOWN is neutral, never a loss (review round 1). An `incomplete` current
  evaluation loses only to definite evidence (`definitely_worse`): a claim FIXED in the checkpoint that STILL FAILS or
  STILL HANGS now, a claim still passing there (INVALID) that BROKE now, or a definite import failure now where the
  checkpoint imports. finalize's 12 s evaluation leaving slow claims UNKNOWN no longer restores an older checkpoint
  over later edits.
- `restore(rec) -> (ok, msg)` is transactional:
  1. refused when `clock() >= T_NO_RESTORE`;
  2. save the current diff as a checkpoint;
  3. for the tracked changed paths, `git checkout <baseline> -- <p>` per path; untracked changed paths are removed;
  4. `git apply --binary <ckpt>`;
  5. verify that `diff_sha()` equals `rec.sha`;
  6. on any failure, restore the saved current diff the same way and return `RESTORE FAILED: <why>`;
  7. after a success, `tidy()` (review round 2). A checkpoint stores the tree as it was scored: `verify --repro-only`
     saves the raw diff before any hygiene, and a full verify keeps root scratch. So a restore could bring back a
     test/config edit (the hidden test_patch then fails to apply: a 0) and scratch that finalize had already deleted.
     `tidy()` runs `hygiene_revert()` and then `clean_scratch()` on the restored tree. The message is
     `restored checkpoint #k`, plus one line for each thing it undid (`reverted test/config edits: ...`,
     `CLEANED: removed ...`). The sha check in step 5 runs before tidying, so the transaction stays exact.
- `clean_scratch()`, `shadowed()` and `scratch_note()` live here (moved from `finalize.py` in review round 2), so both
  restore paths share them. v10.1: root scratch names match in any letter case (KPI 8 is case-insensitive), and the
  untracked listings of `clean_scratch()` and `reset_to_baseline()` pass `NO_GUARD`.
- `save_edited(diff=None)` (v10.1): an unscored `EDITED` checkpoint of a tree with a source change; `edit.py` calls it
  after every landed edit and `status.py` for every non-empty tree it diffs (which covers `edit_file`). `rank()` puts an
  unscored entry below every scored one, so `best_against()` is unchanged and `best(None)` (finalize's EMPTY branch, the
  late guard) takes the latest EDITED tree only when nothing scored exists.
- `restore()` (v10.1): `reset_to_baseline()` also resets the protected files the submit guard hides, and a restore
  whose diff sha differs from the checkpoint's is still exact when `git apply --reverse --check` of the checkpoint holds
  (a checkpoint saved before the guard was armed can hold a file `diff_bytes()` no longer shows).
- `auto_restore_if_empty()` is used by `late_guard()` and `finalize.py` (R71, R76). Its message stays one line (the
  late guard prefixes a helper's output with it): what `tidy()` undid follows in parentheses,
  `RESTORED checkpoint #k: the tree had no source change at t=Ns. (then reverted test/config edits: ...; CLEANED: removed ...)`.

### 4.11 `verify.py`
- **CLI.** `USAGE` = `python3 /tmp/swe/verify.py [--repro-only] [--tests FILE ...] [--list-tests]`. Flags: `--repro-only`
  (bool), `--tests` (list; one string with spaces or commas is split), `--list-tests` (bool), `--timeout` (int, pytest
  side, 5..60), `--text` (repro text).
- **`--repro-only`.**
  - When stdin or `--text` is non-empty: save it as `$SWE/repro.py`, `compile()` it, and report
    `REPRO INVALID: syntax error line k` when that fails.
  - Run the claims. With no source change, the original is `ws`, and line 1 is exactly one of:
    - `REPRO: fails on original (k of k claims): claim 1 AssertionError: 24 != 23 ...`
    - `REPRO: claim n passes on original - it misses the bug; rewrite it once with another input shape.`
    - `REPRO: claim n hangs on original (expected for hang bugs).`
    - `REPRO: claim n is BROKEN (<error>, in the reproduction itself): fix the reproduction.`
    - `REPRO: none saved. Pipe one in: python3 /tmp/swe/verify.py --repro-only <<'EOF' ... EOF`
  - With a source change, it reports `REPRO: k/n claims fixed` (current against the cached original) and saves a quick
    checkpoint. No tests, siblings or spec gaps run. A failing import is compared with the original even here: the base
    tree is built on demand (review round 1), so an import that already failed at baseline no longer reads as RED with
    every claim `not run (import error)`. When that pre-existing failure stopped the import child, the modules after it
    are imported again (at most 3 rounds).
  - It ends by `T_EVAL_END` (review round 1).
  - 1,200 chars or fewer (R52).
- **`--list-tests`.** Print `TESTS: a.py b.py` (discovery only) and exit. Used offline (R57, R101).
- **Full pipeline.** The global deadline is `span()`: `real_budget(VERIFY_TOTAL)` clamped so the run ends by
  `T_VERIFY_END`, but never below `PHASE_MIN` (3 s) while the helper budget allows it (review round 1). Each phase is
  skipped with `UNKNOWN (no time)` when fewer than 3 s remain.
  0. `hygiene_revert()`, then `changes()`. With no source change: `VERIFY: NO SOURCE CHANGE - make the plan's change with python3 /tmp/swe/edit.py first.`
     in under 1 s, and stop. The HYGIENE line carries the reason (`HYGIENE: reverted p (graders replace test and config
     files, so a patch never carries them; do not redo this)`, v10.1).
  1. Memo. When `sha1(diff_bytes, repro_sha, tests, mode)` equals the last run: print
     `SAME AS LAST RUN (t=Ns): <first line>` plus the last NEXT line. The third identical run adds
     `STOP re-running verify; decide now.` (R63)
  2. Quick mode when `clock() >= T_QUICK` (235) or `clock() + 1.2 × state.last_test_secs + QUICK_PAD > T_VERIFY_END`
     (QUICK_PAD 15 s covers the import check and the claims; the old rule ignored them and had `last` = 0 until a test
     side had run). Tests are skipped (`TESTS: skipped (quick mode)`).
  3. Import check, then claims (current, cached original), then tests (discovery plus runs), then siblings and spec gaps.
     Tests run concurrently with the claims when both are needed. Concurrency stays at `MAX_PAR` or less overall.
  4. Verdict, the first row that matches:

     | condition | line 1 |
     |---|---|
     | import or syntax error in a changed module | `VERIFY: RED - import error` |
     | a valid claim is STILL FAILS, STILL HANGS or BROKE | `VERIFY: RED - k/n claims fixed` |
     | confirmed regressions, collects=0 or HANG-NOW | `VERIFY: RED - regressions` |
     | 1 or more valid claims, all FIXED, and tests OK or no related tests | `VERIFY: GREEN` |
     | otherwise (no or only invalid repro, tests UNKNOWN or skipped, origin outside the workspace) | `VERIFY: AMBER - <reason>` |
     | internal error before any result | `VERIFY: UNKNOWN - <reason>` |

  5. Save a checkpoint (the full score) for a distinct diff sha. Journal the verdict. Set
     `state.last_test_secs`.
- **Output** (2,000 chars or fewer, R69):
  ```
  VERIFY: RED - regressions
  DIFF: rich/text.py +6 -2 | rich/cells.py +1 -1
  HYGIENE: reverted tests/test_text.py            (only when something was done)
  IMPORT: ok (rich from workspace)
  REPRO: 2/2 claims fixed
  TESTS: tests/test_text.py tests/test_cells.py | original 212 passed | now 210 passed, 2 failed (3.1 s)
  REGRESSIONS (passed on original, fail now):
    tests/test_text.py::test_divide  AssertionError: assert [...] == [...]
  If a test asserts the OLD behaviour that the issue asks to change, keep your fix (the graders update such tests). Otherwise your change broke it: fix the code.
  SIBLINGS (same code elsewhere, unchanged; fix them too if they have the same defect):
    rich/text.py:1062  for span in text._spans:
  SPEC GAPS:
    new parameter end= missing in rich/console.py Console.print (L610)
  CHECKPOINT: #3 saved (best: #3)
  NEXT: <verdict-specific line>
  [t=142s]
  ```
  NEXT lines, fixed per verdict (v10.1: helpers named by their full command, R89b):
  - GREEN or AMBER: `NEXT: ready. Fixer: reply with your notes. Verifier: run python3 /tmp/swe/finalize.py.`
  - RED import: `NEXT: fix the error at FILE:LINE with python3 /tmp/swe/edit.py, then run python3 /tmp/swe/verify.py again.`
  - RED claims: `NEXT: claim n still fails (<sig>). Fix the code, then run python3 /tmp/swe/verify.py again.`
  - RED regressions: the sentence above.

  The words `undo` and `must fix` never appear (F4, R62).
- **Budget.** p90 8 s or less on local tasks, and 60 s at most (R64, R65, R102).

### 4.12 `finalize.py`
- **CLI.** `python3 /tmp/swe/finalize.py`, no flags. It always fixes and never only reports.
- **Steps:**
  0. v10.1: `arm_submit_guard()` (4.1.17).
  1. `hygiene_revert()`.
  2. Delete untracked scratch:
     - at the repository root: `repro*`, `reproduce*`, `scratch*`, `debug*`, `tmp*`, `temp*`, `try*`, `demo*`,
       `test_*.py`, `*_test.py`;
     - anywhere untracked: `*.log`, `*.orig`, `*.rej`, `*.bak`, `*.swp`, `.coverage`;
     - untracked files over 1 MB;
     - untracked directories that contain `setup.py`, `site-packages`, `_pytest` or `*.dist-info` (vendoring; the 9.2 MB
       fastapi_14448 patch).

     Untracked `.py` files inside a directory with tracked files are **kept** (new modules). An untracked root-level `.py`
     is kept only when `C.root_module_kept()` says it is a module (section 4.1.9); otherwise it is scratch and deleted
     (review round 1: `check_fix.py`, `simple_repro.py`, `verify_box_order.py`). In all cases an untracked root file
     (`.py`, `.pyi`, `.pyc`, `.so`, `.pyd`) or top-level directory is deleted when its name shadows a stdlib or installed
     module. That is checked in one child of the grader's `python3` with the workspace off `PYTHONPATH` (`shadowed()`),
     because under the grader's `PYTHONPATH=<workspace>` a root `typing_extensions.py` or `py.py` makes every test fail
     to import (the fastapi_14448 patch shape).
  3. When there is no source change and a non-empty checkpoint exists: restore the best one (any key) and print
     `RESTORED: ... (the tree had no source change)`. Steps 1 and 2 ran before the restore, so the restore tidies the
     restored tree itself (section 4.10, step 7). The lines for what it undid follow the RESTORED line (review round 2).
     Before that fix, finalize printed READY for a patch holding a test-file edit and the scratch file it had just deleted.
  4. Otherwise, when the current diff sha has no score and at least `MIN_EVAL` (2 s) remain before `T_EVAL_END`: a quick
     evaluation (import plus claims, current against the cached original) within `FINALIZE_QUICK`, ended by
     `T_EVAL_END` (review round 1). Then, when `best_against()` finds a checkpoint that strictly beats the current score
     (the quick 5-tuple when either side is quick) and, if the current evaluation is incomplete, has definite evidence
     (section 4.10), `restore` it:
     `RESTORED: checkpoint #k (GREEN, t=131s) replaced the current tree (RED, t=205s).` It is tidied the same way.
  5. Compile every changed `.py`. A failure gives
     `NOT READY: SYNTAX ERROR FILE:LINE: <msg>. Fix it with python3 /tmp/swe/edit.py, then run python3 /tmp/swe/finalize.py again.`
  6. When no source change remains (v10.1, fastapi_14873 submitted an empty patch at 72 s of 176):
     `NOT READY: EMPTY at t=Ns (Ms left) - no source change. Do not submit an empty patch: it always fails. Make the plan's FIX (smallest plausible version) now, then run python3 /tmp/swe/finalize.py again.`
     followed by `EDIT TARGET (the code viewed or edited last): FILE lines A-B`, at most 20 numbered lines of the latest
     undone edit's region (2 lines of context) or else the latest real view of a source `.py` file, and
     `use: python3 /tmp/swe/edit.py FILE --lines A-B <<'EOF' ... EOF`; nothing when nothing was viewed or the room is gone.
  7. v10.1: `enforce_patch_rules()` on the harness-view diff (4.1.17); what it undid is one `CLEANED: the patch carried
     ...; undone` line, and a patch that still carries a violation is `NOT READY: the patch still carries ...`.
  8. Otherwise: `READY: n files changed (+a -d): <paths>. Next step: submit the patch.` When the patch is over 200 kB or
     adds more than 20 files, `NOTE: large patch (N files, K kB); fine if the issue needs it.` is added (advisory only:
     rich_3930's gold is 308 kB with 26 files). The final diff must encode and `git apply --check` onto a fresh baseline
     copy; otherwise it prints `NOT READY: patch does not apply cleanly: <why>`. Sets `state.final_done`, `final_sha`
     and `final_t`.
- **Output.** 1,400 chars or fewer (1,000 before v10.1). 1.5 s or less without quick evaluation, 15 s or less with it
  (R72-R77).

### 4.13 `status.py`
- **CLI.** `python3 /tmp/swe/status.py`, no flags.
- **Output** (2,200 chars or fewer, 500 ms or less):
  ```
  STATUS [t=182s] helpers v10.0 | repro: 2 claims (fails on original) | checkpoints: 2 (best GREEN #2)
  JOURNAL (last 8):
    t=12s locate: 6 files (top rich/text.py)
    t=40s verify --repro-only: fails on original (2 of 2)
    t=95s edit rich/text.py OK (exact) lines 40-44 (+3)
    t=101s verify: RED 1/2 claims fixed
  DIFF: rich/text.py +6 -2
  <git diff -U2 of source files, capped at 1,600 chars; hunk headers only beyond that>
  [t=182s]
  ```
  It works with an empty journal (`JOURNAL: empty`) and with a 2 MB diff. When the tree changed after finalize, it adds
  `CHANGED AFTER FINALIZE: run python3 /tmp/swe/finalize.py again.` (R27). Protected edits are listed as
  `PROTECTED (the helpers revert these; graders replace them): ...`. v10.1: a `VIEWED (newest first): FILE A-B, ...`
  line lists the last 4 source ranges viewed (a stage recovering after compaction gets the plan's files back:
  rich_4079 lost the plan three times), and a non-empty source tree is saved as an `EDITED` checkpoint (4.10); the
  repository itself is never changed.

### 4.14 Output and time budgets

| helper | stdout cap (chars) | typical | internal deadline | perf budget (asserted, Mac) |
|---|---|---|---|---|
| install | 400 | 180 | - | 300 ms |
| locate | 1,800 | 1,200 | parse 15 s, origin probe 5 s | first 3 s (3k files) / cached 300 ms |
| grep | 1,800 | 800 | 5 s | 1 s |
| view | 2,800 | 2,500 | `--obj` 15 s | 200 ms (excluding `--obj`) |
| edit | 1,500 | 700 | - | p95 150 ms on 5k lines; NO MATCH 300 ms |
| run | 2,500 | 600 | 20 s default, 90 max | command + 100 ms |
| verify | 2,000 | 900 | 60 s global (ended by T_VERIFY_END; --repro-only by T_EVAL_END), 10 s import, 10 s/claim, 25 s claims, 40 s/pytest side | p90 8 s on local tasks |
| finalize | 1,400 | 250 | quick evaluation 12 s, ended by T_EVAL_END | 1.5 s / 15 s |
| status | 2,200 | 1,200 | - | 500 ms |

All deadlines are clamped by `real_budget`. Output is also capped at `CAP_TOKENS` estimated tokens (section 4.1.7).
The view cap dropped from 4,000 to 2,800 chars in review round 1 (section 6); a class's member list takes whatever the
class head leaves, so a 40-member class still lists fully. Helper start-up (preamble plus import) is 80 ms or less. Every cap stays below
`run_command`'s 5,000-char head cut (`SP/swegemma/tools/execution.py:49-51`). Skill-mode output is not truncated by the
harness at all, which is why the caps apply everywhere.

### 4.15 Edge-case matrix (each cell is tested; the R-ID is in brackets)

| case | locate/grep/view | edit | verify | finalize/status |
|---|---|---|---|---|
| empty diff | n/a | n/a | NO SOURCE CHANGE in under 1 s [R62, R100] | EMPTY; restore when a checkpoint exists [R73, R74] |
| binary / non-UTF-8 file | skipped by the index; view marks U+FFFD [R29, R36] | byte-exact round trip via surrogateescape [R44] | diff via `--binary`; compile of bytes [R56] | `git apply --check` round trip [R75] |
| CRLF | view strips `\r` for display only [R35] | CRLF kept, numstat 1/1 [R44] | n/a | n/a |
| no trailing newline | numbering intact [R35] | preserved unless the last line is edited [R44] | n/a | n/a |
| form feed and other separators | numbers equal git's [R35] | same numbering [R42] | n/a | n/a |
| src/ layout | LAYOUT src plus origin [R38] | n/a | PYTHONPATH maps `tree/src`; OUTSIDE WORKSPACE gives AMBER [R59] | n/a |
| no tests dir | RELATED TESTS none [R30] | n/a | `TESTS: none related`, verdict GREEN possible [R62] | n/a |
| hangs (import-time `while True`, endless repro) | `--obj` HANG [R37]; locate origin probe 5 s [R32] | n/a | killpg, bounded [R68] | quick evaluation bounded [R77] |
| unicode paths | `quotepath=off`, `-z` [R29] | refusal/accept by relative path [R45] | changes, diff [R21] | [R72] |
| new / deleted / renamed files | n/a | `--create` [R42] | import skips deleted; discovery uses new files [R56, R57] | kept new module, deleted scratch [R72] |
| huge output | caps plus last.log [R30, R34, R36] | [R50] | [R69] | [R27] |
| missing pytest plugins | n/a | n/a | collection error on both sides is UNKNOWN, not a regression [R60] | n/a |
| pytest masked | n/a | n/a | TESTS unavailable, repro still runs [R61] | n/a |
| agent `git commit` | baseline tag [R11] | n/a | diff against the tag [R11] | [R75] |
| repo module named like stdlib (`json.py`, `types.py`, `select.py`, `signal.py`) | [R03] | [R03] | [R03] | [R03] |
| inherited open stdin | never read [R30] | 1 s guard [R15, R111] | 1 s guard [R52] | never read |

### 4.16 Files under `$SWE` (all per task)
- `VERSION` and `t0`; optionally `clock_scale` (pod only).
- `state.json`, `state.lock`, `journal.jsonl`, `last.log`.
- `index_<baseline12>.marshal`, `idx` (temp index), `gidx.<pid>` (the unguarded index copy of `changes()`, removed
  after use), `base/` (worktree), `repro.py`, `claims/`, `rt_orig/`, `rt_cur/`, `j_orig.xml`, `j_cur.xml`,
  `ckpt/<id>.diff`, `guard_stat.json` (v10.1, the guarded files' clean snapshot).
- In the workspace's git dir (v10.1): `swe_exclude` (the submit guard's exclude file) and the `core.excludesFile` setting;
  assume-unchanged marks on protected tracked files in the index.

`state.json` schema:
```json
{"version": "v10.0", "ws": "/abs/ws", "baseline": "<sha>", "t0": 0.0,
 "final_done": false, "final_sha": null, "final_t": null,
 "origin": {"rich": ""}, "base": {"sha": "<sha>", "ok": true, "dir": ".../swe/base"},
 "memo": {"verify": {"key": "<sha1>", "n": 1, "t": 101.0, "first": "VERIFY: RED ...", "next": "NEXT: ..."}},
 "repeats": {"<sha1>": 2},
 "repro": {"sha": "<sha1>", "orig": {"1": {"status": "FAIL", "sig": "AssertionError: 24 != 23", "broken": null}},
           "new_names": ["FileProxy.isatty"], "messages": []},
 "orig_tests": {"<sha1(files)>": {"status": "ok", "why": "", "outcomes": {"tests/test_x.py::test_a": "passed"}, "secs": 3.1}},
 "last_test_secs": 3.1, "pytest_mask": "ok|masked|absent",
 "ckpts": [{"id": 1, "sha": "<sha1>", "score": [1, 1, 1, 1, 2, 0], "key": "<sha1>", "verdict": "GREEN", "t": 118.0, "quick": false,
            "rkey": "<sha1>", "classes": {"1": "FIXED"}, "imp_def": true, "incomplete": false}],
 "edits": [{"file": "rich/text.py", "start": 40, "end": 52, "delta": 3, "t": 95.0}],
 "views": {"rich/text.py": [[30, 110, 90.0], [118, 118, 95.0, "d"]]}, "locate_calls": 1,
 "ctx": {"n": 2310.5, "phase": "fixer", "tail": [["view", 903.0], ["edit", 673.0]]}}
```

---

## 5. eval_config and sampling

| knob | value | why |
|---|---|---|
| `max_time_minutes` | 5 | The only knob that bounds the 12 h worst case. 5.25 fails at N=130 (time_model 5). |
| `timeout_seconds` | 120 | Also the hidden-test pytest timeout (`verification.py:498-503`), where a false negative on a correct patch is the most expensive error. The public maximum is 12.6 s, and a private suite on a 2-vCPU scorer is unknown. 120 gives about a 10x margin and is below v4's 180, so the raw-hang tail is shorter. Helper hangs are bounded internally (110 s or less and session-clamped), so the value binds only raw commands the model runs itself (4 of 3,440 L4 commands hung). |
| `max_tool_calls` | 100 | A loop brake. Edits now count (they go through `run_command`). 21 v9 verifiers hit the 70 cap mid-verification (own_data 6). `submit_patch` and `get_status` are free. |
| `max_turns` | 200 | 2x the tool calls or more; never binds before the time cap except in malformed-call spirals. |

The scorer reads only these four keys (R81).

---

## 6. Context budget (tokens; 3.4 chars/token for prose; tool output 3.06 median, 2.3 worst decile)

Fixed part of every call:
- 12 tool declarations, about 7,200 chars (plus about 250 for `submit_patch`);
- the skill boilerplate, 1,333 chars;
- ADK identity, about 150 chars.

That is about 2,560 tokens (2,640 with `submit_patch`) (config_space #14). Instructions are 133 / 684 / 661 / 617 / 326
tokens. The problem is p50 140, p95 720 and max 2,970 tokens. The plan is asked for in 120 words. Measured race-1 plans
ran median 442 and p90 1,087 tokens, so they are now cut at 768 by `max_output_tokens`, and each stage sees a plan only once
(review round 2, below).

| stage | stage start, p50 / worst | dynamic at typical caps | peak p50 / worst | budget line |
|---|---|---|---|---|
| setup | 4.7k / 7.6k (includes the harness prompt) | 2 calls, about 0.3k | 5.0k / 7.9k | 14,336 |
| locator | 3.4k / 6.2k | 10 calls: locate 450, 3 views 3.9k, 2 greps 700, repro in 350 + out 300, plan 250, 30/call: about 5.5k | 8.9k / 11.7k | 14,336 |
| fixer | 3.8k / 6.6k | 2 views, 3 edits of (400 out + 350 in), verify 600, reply 100: about 5.0k | 8.8k / 11.6k | 14,336 |
| verifier | 4.0k / 6.8k | status 700, verify 600, 1 repair (view 1.3k + edit 750 + verify 600), finalize 300: about 3.5k | 7.5k / 10.3k | 14,336 |
| submitter | 3.2k | finalize plus submit: about 0.4k | 3.6k | 14,336 |

The table above is the typical mix. It is not what the prompts permit, and 3.0 chars/token is not the worst case
(review round 1). Tool output measured on the race-1 and e74 traces is 3.06 chars/token at the median and 2.3 at the
worst decile (p10 2.18-2.39). Rendered tables that are 24-35% non-ASCII measured 0.36-0.63, so one 957-char output cost
2,684 prompt tokens. Under the call mix the prompts allowed (fixer 3 verify rounds with repairs; verifier 3 verifies and
2 finalizes), the fixer reached about 15.4k tokens typical and 20.3k at caps, past the compaction line. Compacted tasks
resolved 3/29 against 19/45 (harness_runtime 5.4).

Round-1 changes and the R95 model (tests/test_v10_prompts.py, read from the prompts and `_swe_common`):
- **Permitted mix.** The fixer makes 3 edits after viewing the plan's files, then verifies up to R rounds (R = 2 now, from
  3), with a view and an edit between rounds: 4 views, 4 edits, 2 verifies. The verifier runs status, 1 + K verifies,
  K views, K edits (K = 2 repair rounds), 2 finalizes and the submission. The locator runs locate, 3 views, 2 greps,
  2 repro-only calls (the rewrite-once rule) and 1 run. R and K are parsed from the prompts, so a looser prompt loosens
  the model with it.
- **Caps.** view 2,800 chars (from 4,000). Every output is also capped at `CAP_TOKENS` estimated tokens.
- **Guard.** The context meter shows CONTEXT at `CONTEXT_TOKENS` estimated tokens (5,500 in round 1, 4,700 since
  round 2). After it the locator replies, the fixer makes at most one edit, and the verifier runs finalize and submits.

Round-2 changes (review round 2). The round-1 checks assumed a 120-word plan and 60-word notes. They left the fixer 144
tokens under the line, and the fixer crossed it at the measured median plan (14,434 tokens at 442 tokens of plan).
Three things caused that:
- the prompts' word limits are not what the model writes: race-1 locator replies ran median 418-442 and p90 1,020-1,087
  tokens, with 2-4 runaways of 1,536 or more, and v9's "under 250 words" was overrun 2-4x;
- the plan was paid twice in the fixer, through `{plan?}` and again in the handoff event (and the notes twice in the
  verifier);
- the meter sees only helper output: raw `read_file` (up to 10,000 chars), raw `run_command` (up to 5,000 + 5,000) and
  graph-tool results never reach it.

The fixes:
- **Handoff paid once.** `{plan?}` is gone from the fixer and `{fix_notes?}` from the verifier; the text arrives in the
  handoff event (TP::test_handoff_paid_once). The old fixer prompt misses the B margin below
  (TP::test_double_paid_handoff_breaks_the_margin).
- **The locator's `max_output_tokens` is 768** (from 1,536). This bounds the plan at about 2.4x its 120-word target and
  halves a runaway reply (about 27 s instead of 54 s on L4). Cost: a reply that writes its analysis before `FILES:` is
  cut first. In r_v4 and r_v9_eog, 25 of 105 locator replies were over 768 tokens. The cut would remove `FILES:` in 3 of
  them, 2 of which the old 1,536 cap kept (rich_3935 in r_v9_eog, rich_3472 in r_v4). A fourth, a 4,096-token runaway,
  had no `FILES:` at all. The prose before the cut still names the file and the cause.
- **Sizes measured, not instructed.** Every earlier reply enters the model at its measured race-1 size, bounded by the
  stage's `max_output_tokens`: p50 for A; p90 for B, C and R94 (plan 768, the cap, since the p90 of 1,087 is above it;
  notes 244; verifier reply 188); `max_output_tokens` itself for D.
- **Metered I/O only.** The fixer and verifier prompts say `View files only with view.py and run other code only with
  run.py.` (R96).
- **`CONTEXT_TOKENS` = 4,700** (from 5,500), the highest value that gives B at least 1,000 tokens of margin.

- **Checks** (statement lengths: p95 2,455 chars; the single outlier 10,095 chars, next 2,934), fixer / verifier:
  - A. p95 statement, median handoffs, typical outputs at 3.06 chars/token: 12,000 tokens or fewer (11,051 / 9,283).
  - B. p95 statement, p90 handoffs, outputs at caps and 2.3 chars/token, bounded by the guard: at least 1,000 under
    14,336 (13,304 / 13,046; margins 1,032 / 1,290; the locator 2,699).
  - C. outlier statement, p90 handoffs, 3.06 chars/token, guarded: under 14,336 (13,545 / 13,325; margins 791 / 1,011).
  - D. outlier statement, handoffs at `max_output_tokens`, the whole permitted mix at caps and 2.3, no guard, plus the
    largest generation: 2,048 or more below 32,768 (18,070 + 2,048 / 18,420 + 2,048).
  - A first fixer round at measured sizes (3 views, 3 edits of 256 model-written tokens, the p90 of 5,329 race-1 edit
    calls, 1 verify: 4,598 estimated) stays below the threshold. The hint only fires in later rounds. The trade: a
    first round of 3 edits at the old worst-case 400 tokens each (5,030 estimated) now gets the CONTEXT hint at its
    verify. The fixer then replies, and the verifier repairs in a fresh context.
- **Residual risk.** A runaway fixer reply (notes at the 2,048 cap; the race-1 maximum was 1,139 of 98) still puts
  the verifier past the line in the B scenario. D shows it cannot overflow.

R94 checks the stage start against the real files, handoffs at the measured p90: 8,000 tokens or fewer (verifier
worst 7,287).

If a stage overruns and in-flow compaction still fires:
- The instruction keeps the problem. It keeps the plan only in the verifier and the submitter; the fixer's plan was in
  the handoff, which becomes the compaction summary.
- AMNESIA sends the model to `status.py` (which also restarts the context meter). It shows the repro, the journal tail
  and the diff, and the checkpoints hold the work.
- Overflow needs about 25 or more calls in one stage, and the CONTEXT/FINISH/TIME footers make that rare.

---

## 7. Requirement registry (R01-R120)

Tiers:
- **CI:** on this Mac, no network, the whole suite in 10 min or less.
- **NIGHTLY:** `G4_NIGHTLY=1`.
- **REPLAY:** needs recorded traces.
- **RACE:** GPU, Carson's go.

Every v10 test module imports `no_orphans` (autouse) from `tests/v10_support/repo.py`. It fails a test when any process
whose command line contains the test's `tmp_path` survives 1 s after the test (R120).

Test files and owners:

| owner | test files |
|---|---|
| core | `tests/test_v10_core.py` (TC), `tests/test_v10_run_status.py` (TRS) |
| locate | `tests/test_v10_locate_view.py` (TL) |
| edit | `tests/test_v10_edit.py` (TE) |
| verify | `tests/test_v10_verify.py` (TV), `tests/test_v10_finalize.py` (TF) |
| config | `tests/test_v10_bundle.py` (TB), `tests/test_v10_prompts.py` (TP) |
| tasks | `tests/test_v10_tasks.py` (TT) |
| integration | `tests/test_v10_sandbox.py` (TS), `tests/test_v10_flow.py` (TFL), `tests/test_v10_runner.py` (TR) |

| ID | Requirement | Test | Tier |
|---|---|---|---|
| R01 | Helpers import only the stdlib and each other (AST vs `sys.stdlib_module_names`); no `socket`/`urllib`/`http`/`ssl`/`ftplib`; all scripts parse with `ast.parse(feature_version=(3, 8))`; no script stem shadows a stdlib module, `pytest`, `_pytest` or `py` | TC::test_stdlib_only_py38_no_network | CI |
| R02 | Every CLI script starts with the verbatim 4.0.1 preamble (byte-identical block before the first other statement) and sets `sys.dont_write_bytecode` | TC::test_preamble_identical_and_first | CI |
| R03 | With `json.py`, `types.py`, `select.py`, `signal.py` and `tempfile.py` at the workspace root on `PYTHONPATH`, and also as `sys.path[0]` with `json` pre-imported from the workspace (the skill-wrapper case), every helper runs and exits 0 with its normal first line | TC::test_stdlib_shadow_immunity[helper] | CI |
| R04 | No `/tmp` or `/workspace` string constant is used as a path in helper code (AST Constant scan outside docstrings); whitelist: `DOCKER_TMP`, `DISPLAY_SWE` and strings that contain `/tmp/swe/` as display text | TC::test_no_path_literals | CI |
| R05 | No destructive workspace git (`reset --hard`, `checkout .`, `checkout -- .`, `clean -f` without a path, `stash`) in any helper; every `checkout <baseline> --` names exactly one path | TC::test_no_destructive_git | CI |
| R06 | `swe_dir()` follows the 4.1.2 order for 6 env combinations, including Docker-like (`TEST_TMPDIR=/tmp`-style dir with `TMPDIR` elsewhere) and installed-from-`__file__` | TC::test_swe_dir_resolution[case] | CI |
| R07 | `install.py` copies every `*.py` atomically, is idempotent (a second run rewrites nothing, by mtime), writes `VERSION` and `t0` once, prints 400 chars or fewer naming `/tmp/swe`, and takes 300 ms or less | TC::test_install_contract | CI |
| R08 | Dual target: `DOCKER_TMP/swe` is written only when `TEST_TMPDIR` is unset, not in a rewriting sandbox, and `SWE_DUAL!=0` (the test points `C.DOCKER_TMP` at a temp dir through `SWE_DOCKER_TMP_FOR_TESTS`) | TC::test_install_dual_target | CI |
| R09 | Any helper executed like the skill wrapper (script copied to `<td>/scripts/`, cwd `<td>`, `sys.argv=["scripts/x.py", "--k", "v"]`, `runpy.run_path`, `sys.path[0]`=ws) installs all helpers into `swe_dir()` and then does its own job | TC::test_bootstrap_from_skill_dir[helper] | CI |
| R10 | `ws()` order; a decoy git repo at an injected `/workspace` path is never chosen when cwd, `PWD` or `SWE_PATH0` is inside the real workspace; `cd sub && helper` works; paths under `swe_dir()` (the base worktree) are skipped | TC::test_ws_resolution_with_decoy | CI |
| R11 | `baseline()` prefers `_swegemma_baseline`; after an agent `git commit`, `changes()`, `diff_bytes()`, verify and finalize still see the change | TC::test_baseline_after_agent_commit | CI |
| R12 | `clock()`: committer time of the baseline; over 900 s in the past falls back to the tag mtime, then `t0`; `SWE_FAKE_CLOCK` overrides; `clock_scale` 1.7 multiplies elapsed time; values outside 0.2..5 are clamped | TC::test_clock_sources_and_scale | CI |
| R13 | `real_budget(d)` is `min(d, max(1, (300-clock)/scale-4))`, verified in a matrix | TC::test_real_budget_clamp | CI |
| R14 | `sh()`: new session, stdin `DEVNULL`; the deadline kills `sleep 30 &` and a grandchild `bash -c 'sleep 20'`; returns within timeout + 2 s with partial output; reaps background children on normal exit; output capped at 4 MB | TC::test_sh_killpg_reap_and_cap | CI |
| R15 | `read_stdin()`: TTY gives `''`; an open silent pipe gives `''` within 1.2 s; `/dev/null` gives `''` in under 50 ms; a 1 MB heredoc is read fully; trailing `EOF`, `SWE_EOF`, `EOF.` and lone backtick lines are stripped; CRLF becomes LF | TC::test_read_stdin_never_blocks | CI |
| R16 | `parse_args`: positional and `--key value` forms give equal results; `--k=v`; booleans bare or valued (`True`, `1`, `yes`, `false`); a bare `--` is ignored; list flags; `--text`; unknown flag gives a one-line `USAGE ERROR` with exit 0 | TC::test_parse_args_forms | CI |
| R17 | `cap()`: ANSI/OSC stripped, `\r` normalised, head/tail marker names `/tmp/swe/last.log`, the long-line rule, the pytest summary line kept; the full text lands in `$SWE/last.log` | TC::test_cap_and_last_log | CI |
| R18 | Footer: `[t=Ns]` always; the hint priority FINAL > EDIT NOW > TIME > FINISH > CONTEXT > LOCATOR at the 4.1.7 thresholds and conditions (fake-clock matrix, v10.1: EDIT NOW on an empty tree at 215 and 255 s and once the locator stage is over); no hint names `submit_patch` or any tool | TC::test_footer_hints_matrix | CI |
| R19 | The state is written atomically under flock (20 concurrent writers lose no update); a mismatched `ws` or `baseline` resets state, caches, repro and checkpoints | TC::test_state_atomic_lock_reset | CI |
| R20 | The `is_protected` table (at least 24 cases), including `pkg/testing/util.py` allowed, `pkg/tests/x.py` protected, `a/b/conftest.py`, `*.pth`, `..`, absolute paths outside ws | TC::test_is_protected[case] | CI |
| R21 | `changes()` classifies modified, new, deleted, renamed and unicode-named files with no index change (index mtime and sha unchanged); `diff_bytes()` equals `git add -N . && git diff --binary <baseline>` run on a copy, including binary and mode changes | TC::test_changes_and_diff_bytes_match_submit | CI |
| R22 | `hygiene_revert()` restores tracked protected files that were modified or deleted (per path, even when `sitecustomize.py` is absent), deletes untracked protected files, never touches source, and reports one line | TC::test_hygiene_revert | CI |
| R23 | `unrewrite()` maps the four prefixes only when inside a `swegemma_sandbox_*` tmp; it is the identity otherwise | TC::test_unrewrite_unit | CI |
| R24 | `safe_main`: an injected exception prints `HELPER ERROR ...` in 300 chars or fewer, exit 0, and no traceback on stdout or stderr | TC::test_safe_main_exit0 | CI |
| R25 | `run.py`: default 20 s; `--timeout` clamped to 1..90 with a notice on invalid input; cwd is ws; env additions; `exit=`/`TIMEOUT` first line; partial output kept on timeout; cap 2,500 with the summary kept; `last.log`; the pytest-disabled note; the third-identical note; 100 ms overhead or less | TRS::test_run_contract | CI |
| R26 | `run.py --timeout 2 "sleep 30 & bash -c 'sleep 20'"` returns within 4 s and no process of that session survives 0.5 s later (F7 regression) | TRS::test_run_timeout_kills_group | CI |
| R27 | `status.py`: t, version, repro and checkpoint summary, journal tail of 8, diffstat, diff capped at 1,600; works with an empty journal and a 2 MB diff; CHANGED AFTER FINALIZE; 2,200 chars or fewer; 500 ms or less | TRS::test_status_contract | CI |
| R28 | Every CLI script exports `USAGE` and `FLAGS`, and with no required argument it prints `USAGE` and exits 0 | TC::test_usage_flags_exported[helper] | CI |
| R29 | The index survives SyntaxError, py2 print, non-UTF-8, a 2 MB file, a symlink loop, `site-packages` and unicode paths; the marshal cache re-parses only changed files; a forced 1 s deadline gives `partial` and valid output; output is identical over 3 runs | TL::test_index_hostile_tree_and_cache | CI |
| R30 | `locate.py` output: `LOCATE:` first line, LAYOUT line, at most 6 files × 3 symbols with `L` ranges, RELATED TESTS, 1,800 chars or fewer; the positional, `--query` and `--text` forms are equal; it never reads stdin (returns in under 1 s with an open silent pipe) | TL::test_locate_output_contract | CI |
| R31 | Ranking rules: tests ×0.35, docs dirs ×0.6, bigram boost, `docs_src/` ranked below the package for identical identifiers, deterministic ties; PR boilerplate, URLs, `#123`, `gh-12` and hex tokens produce no terms | TL::test_locate_ranking_rules | CI |
| R32 | `locate.py`: first call 3 s or less on a synthetic 3k-file repo; cached 300 ms or less; a hanging import in the origin probe is bounded by 5 s | TL::test_locate_perf_cache_deadline | CI |
| R33 | The third locate call in a task appends the NOTE | TL::test_locate_third_call_note | CI |
| R34 | `grep.py`: 40 hits or fewer, 5 per file or fewer, 160-char lines, tests excluded unless `--tests`, `--path`, enclosing def annotations, count line, invalid regex in one line, 1 s or less | TL::test_grep_contract | CI |
| R35 | `view.py` range, symbol (func, async def, Class, `Class.method`, nested) and outline modes; the `%5d| ` format; numbering equals `git blame`/`sed -n` numbering on a file containing `\f \x0b \x1c \x1d \x1e \x85 U+2028 U+2029`; views recorded | TL::test_view_modes_and_numbering | CI |
| R36 | `view.py` bounds: 100 lines and 4,000 chars or fewer, the clamp message with the next command, the non-UTF-8 note, CRLF display, a missing file in one line, 200 ms or less | TL::test_view_bounds | CI |
| R37 | `view.py --obj json.JSONEncoder.default` shows origin, signature and numbered source; a repo object shows `[workspace]`; a module that loops at import gives `HANG importing` within 15 + 2 s with no survivors | TL::test_view_obj_dependency_and_hang | CI |
| R38 | Import origin: an src-layout fixture with an installed same-named copy on `PYTHONPATH` makes `locate.py` print `OUTSIDE WORKSPACE`, and `verify.py` reports AMBER with that reason; the flat layout prints `(workspace)` | TL::test_import_origin_warning | CI |
| R39 | `edit.py` applies a unique exact SEARCH/REPLACE; several blocks are all-or-nothing (a failing second block leaves the file byte-identical) | TE::test_search_replace_basic_and_atomic | CI |
| R40 | Tiers `rstrip` (including CRLF), `unescape` (same transform applied to REPLACE), prefix strip (`  12| ` columns) and `indent` (including a dedent) each apply on their fixture and name the tier (12 fixtures) | TE::test_match_tiers[fixture] | CI |
| R41 | NO MATCH prints the closest numbered window and the exact `--lines` recipe; AMBIGUOUS lists every start line; the file stays byte-identical; the closest-window search takes 300 ms or less on 5k lines | TE::test_nomatch_and_ambiguous | CI |
| R42 | `--lines` with text; `--lines` with empty text is an ERROR and changes nothing; `--delete`; `--insert-after 0` and `N`; `--create` (refuses an existing file, creates parents); line numbers equal `view.py`'s on the separator-char fixture | TE::test_line_modes | CI |
| R43 | A syntax error gives REVERTED with a byte-identical file and the error line relative to the new text; no `.pyc` anywhere; a file that was already uncompilable gives WARNING, not REVERTED | TE::test_syntax_revert | CI |
| R44 | Fidelity: CRLF kept (numstat 1/1 on a one-line edit), BOM kept, missing final newline kept, latin-1 and invalid UTF-8 bytes round-trip byte-exact, mixed EOL | TE::test_encoding_fidelity | CI |
| R45 | REFUSED with a reason for every protected class in R20, for paths outside ws, `..`, and a dependency path; `pkg/testing/util.py` is accepted; unicode paths work | TE::test_refusals[case] | CI |
| R46 | Loop breaker: the second identical failing input prints ALREADY TRIED plus the alternative; three consecutive failures on one file print the numbered region and the recipe | TE::test_loop_breaker | CI |
| R47 | Stale guard: `--lines` below an earlier `delta != 0` edit without a newer view gives STALE with the corrected range; after a covering view it is accepted; an edit above is accepted | TE::test_stale_guard | CI |
| R48 | Input normalisation: marker variants, trailing `EOF`/backtick junk, NO CHANGE, the `\"` warning and the column-0 warning | TE::test_input_normalisation_and_warnings | CI |
| R49 | After a raw `sed` edit to `tests/test_x.py`, the next successful `edit.py` of a source file reverts the test file | TE::test_edit_runs_hygiene | CI |
| R50 | Output is 1,500 chars or fewer, status on line 1, region ±2 in 30 lines or fewer; p95 150 ms or less over 20 runs on a 5k-line file | TE::test_edit_output_and_perf | CI |
| R51 | `--file F --lines A-B --text "..."` (skill form) gives the same bytes as the heredoc form | TE::test_skill_arg_form | CI |
| R52 | `verify.py --repro-only` with stdin saves the repro and prints exactly one of the 5 line-1 forms of 4.11 on the matching fixture; returns within 1.2 s on an open silent stdin with no saved repro | TV::test_repro_only_states | CI |
| R53 | Claim parsing (prelude plus `# CLAIM n:`, no header means one claim, at most 6 run); never more than 2 claim processes at once (instrumented fixture); `CLAIM_TIMEOUT` per claim; `CLAIMS_TOTAL` overall gives UNKNOWN for unfinished claims | TV::test_claim_sections_concurrency_budget | CI |
| R54 | Claim classes on fixtures: FIXED, STILL FAILS, STILL HANGS, BROKE, INVALID, BROKEN (syntax, NameError in the claim with the prelude hint, missing module); ModuleNotFoundError for a new submodule of an existing package stays valid; the `k/n` summary counts valid claims only | TV::test_claim_matrix | CI |
| R55 | The base worktree is created once at the baseline, with ignored build artefacts copied (fixture: a module importing an untracked, git-ignored `_speedups.py`); `git status --porcelain` of ws is unchanged; the original claim results are cached per repro sha; files the claim runs create are removed | TV::test_base_tree_and_orig_cache | CI |
| R56 | Import check: in-memory compile plus a subprocess import of changed modules (`src/` stripped); `RED IMPORT` with the last line and `file:line`, including a NameError at import; deleted modules are skipped | TV::test_import_check | CI |
| R57 | Discovery picks only collectable files (never `tests/render.py`, `tests/_card_render.py`, `tools/*.py`, `conftest.py`); the score rule; `--tests` first; 3 or fewer; `--list-tests` | TV::test_discovery_rules | CI |
| R58 | pytest argv and env are captured with a fake `python3` on `PATH`: `-s -m pytest`, `-p no:cacheprovider -p no:anyio -o timeout=0 -o python_classes="Test* *Test"`, `--junitxml`, `PYTHONSAFEPATH=1`, `PYTHONNOUSERSITE=1`; never `-o addopts=`; never `-c ... pytest.main` | TV::test_grader_flags_and_env | CI |
| R59 | `grader_env` re-roots `PYTHONPATH` from ws to base, prepends `tree/src` when the origin map says `src`, and sets `PYTHONPATH=tree` when it was empty | TV::test_pythonpath_mapping | CI |
| R60 | JUnit parsing: exact ids, including params with spaces and unicode; passed-to-failed and passed-to-error are regressions; de-flake by one rerun; a collection error only on current gives RED; on both sides, UNKNOWN; exit 2/4/5, no JUnit, 0 tests or timeouts on both sides give UNKNOWN, never pass (F3 regression); classnames relative to a nested pytest rootdir (`tests/pytest.ini`, every rich task) map to runnable `path::Class::name` ids and the rerun really runs them (review round 2) | TV::test_test_outcomes_and_unknown, TV::test_parse_junit_rootdir_below_workspace, TV::test_rerun_with_nested_pytest_ini | CI |
| R61 | In a throwaway venv with the harness shim applied verbatim (`container_setup.py:968-1043` script), verify prints `TESTS: unavailable (pytest is disabled ...)`, still runs claims, and never imports pytest in-process or through `-c` | TV::test_masked_pytest | CI |
| R62 | The verdict table of 4.11 on fixtures (every row); the regression wording contains the old-behaviour sentence and never `undo` or `must fix` (F4 regression); GREEN is possible without any related test file | TV::test_verdict_table_and_wording | CI |
| R63 | Memo: an identical (diff, repro, tests, mode) gives `SAME AS LAST RUN` plus NEXT in 300 ms or less; the third identical run adds STOP | TV::test_memo | CI |
| R64 | ORIGINAL test results are cached per file set: a second verify after a source change reruns only CURRENT (instrumented count) | TV::test_second_run_cached_speed | CI |
| R65 | Quick mode at `SWE_FAKE_CLOCK` 270, or when clock + 1.2 × last > 285; the global deadline equals `real_budget(60)`; at fake clock 290, verify finishes within `(300-290)-4+2` s | TV::test_quick_mode_and_session_clamp | CI |
| R66 | SIBLINGS: a twin-function fixture lists the untouched twin; hits inside the changed hunks are excluded; same-name defs in another class are listed; 6 lines or fewer | TV::test_siblings | CI |
| R67 | SPEC GAPS: automatic NEW names from original failure signatures (all 5 patterns); `# NEW:` and `# MESSAGE:` headers; a missing parameter in 1 of 3 same-named defs is listed; a message found by its 12-char fragment counts as present; 4 lines or fewer | TV::test_spec_gaps | CI |
| R68 | Hang fixture (a package with `while True: pass` at import, plus an endless claim): verify returns within its deadline + 2 s and no child survives | TV::test_verify_hang_bounded | CI |
| R69 | Verify output is 2,000 chars or fewer on adversarial fixtures (50 regressions, 20 kB assertion lines), with the verdict on line 1 and a NEXT line | TV::test_verify_output_bounds | CI |
| R70 | Score order, table-driven: empty < import error < collection error < hang < claims still failing < regressions < pass; 1 fixed claim with 1 regression beats 0 fixed with 0 regressions; comparisons only within the same key; quick 5-tuples | TF::test_checkpoint_score_order | CI |
| R71 | `restore()`: afterwards the diff sha equals the checkpoint's; an injected `git apply` failure rolls back to the saved current tree byte-exactly; refused at t 285 or later; after the sha check it tidies (protected paths reverted, scratch deleted, new package modules kept) and reports each thing it undid (review round 2) | TF::test_restore_transactional, TF::test_restore_tidy_unit | CI |
| R72 | Finalize hygiene matrix: tracked protected files reverted; scratch patterns, extensions, files over 1 MB and vendored trees deleted; a new module inside a package kept; READY with diffstat | TF::test_finalize_hygiene_matrix | CI |
| R73 | Finalize NOT READY for empty, test-only (after revert) and a syntax error left by raw `sed`; a large patch (26 files, 300 kB) gives READY plus NOTE, never NOT READY | TF::test_finalize_not_ready_and_notes | CI |
| R74 | Restore rules: a strictly better same-key checkpoint replaces a worse current tree; ties keep the current; an empty tree with a checkpoint is restored; an unevaluated current tree gets a quick evaluation below t 275 and is kept as-is at 275 or later; a restored checkpoint holding a test-file edit and a root scratch file ends READY with neither (review round 2) | TF::test_finalize_restore_rules, TF::test_restore_never_brings_back_tests_or_scratch | CI |
| R75 | The final diff encodes and `git apply --check`s onto a fresh baseline copy (including a file with astral characters, F11 class); `final_done`, `final_sha` and `final_t` are set; any later tree change clears the FINAL banner | TF::test_finalize_diff_roundtrip_and_final_flag | CI |
| R76 | Late guard: at fake clock 255 or later, with no source change and a stored checkpoint, the next output of any helper starts with RESTORED and the tree equals the checkpoint (tidied: no test edit, no scratch, what was undone on the same line); below 255, or when final, nothing happens | TF::test_late_auto_restore, TF::test_restore_never_brings_back_tests_or_scratch | CI |
| R77 | Finalize takes 1.5 s or less without quick evaluation and 15 s or less with it | TF::test_finalize_timing | CI |
| R78 | The tree is exactly Sequential[setup, locator, fixer, verifier, submitter], all LlmAgents with `include_contents: none` and the single model id, and compiles via `scripts/validate.py submissions/v10` | TB::test_tree_and_official_compile | CI |
| R79 | Every stage has BASE8 and `skills: [skills/swe-tools]`; `submit_patch` only on verifier and submitter (YAML and compiled tool names) | TB::test_tool_sets_and_skills | CI |
| R80 | The gen-config table of section 2; `include_thoughts: false` everywhere; no `seed` or `thinking_level`; compiled `extra_args` has `enable_thinking: False` | TB::test_generation_configs | CI |
| R81 | `eval_config.yaml` is exactly `{max_time_minutes: 5, timeout_seconds: 180, max_tool_calls: 100, max_turns: 200}` under `evaluation:` | TB::test_eval_config | CI |
| R82 | `output_key`: locator `plan`, fixer `fix_notes`, none elsewhere | TB::test_output_keys | CI |
| R83 | `scripts/pack_bundle.py submissions/v10 out.zip`: only allowed extensions; no `__pycache__`, dotfiles, symlinks or extensionless files; `agent.yaml` at the root; sorted entries, fixed mtime 1980-01-01, mode 0644; the same sha256 twice; under 1 MB | TB::test_pack_deterministic | CI |
| R84 | Frozen trees unchanged. Tree sha256 (walk sorted; skip `__pycache__`, `*.pyc`, `._*`, `.DS_Store`; hash `rel\0content\0`): `submissions/v9_eog` 41db23fcd48cf2b52f21beb691097232eb4a5c5b739e7fb656fdc95fd3c940b1, `submissions/v4` 38eb7a97cdbb6aa91577231dcc1bf33fa256b60c48985445578c603d7ea181ed, `helpers_v9` c40b410b58d0fca3c26708c01032c8716683bc49e5b88b2ef5a877e97bdd4157 (integrator re-pin, 2026-09-28: the first pin ed996c63... predates Carson's committed gate fix 26dd7b9; TB::test_frozen_pins_match_git checks the pin against that commit and that no frozen tree has uncommitted changes) | TB::test_frozen_unchanged | CI |
| R85 | 12 h arithmetic from the shipped values: `600 + N × (60 × max_time_minutes + 3.6 + 5 + 1) <= 0.95 × 43,200` for N=130 | TB::test_fits_12h | CI |
| R86 | Every timeout constant in `_swe_common` is 110 s or less (`timeout_seconds` - 10) | TB::test_deadlines_under_command_timeout | CI |
| R87 | Brace lint: the only `{...}` in any prompt are `{problem_description}`, `{plan?}` and `{fix_notes?}`; no other brace characters; per stage exactly the set it needs (since review round 2: fixer `{problem_description}` only, verifier `{problem_description}` and `{plan?}`) | TP::test_brace_lint | CI |
| R88 | 0 backticks in prompts and SKILL.md; every `run_skill_script(` example lists `file_path=` before `skill_name=` | TP::test_no_backticks_template_order | CI |
| R89 | Named tools: prompts, SKILL.md and every helper string constant (AST) name only tools declared on that stage (registry names plus `run_skill_script`, `load_skill`, `list_skills`, and known hallucinations `git_grep`, `exit_loop`, `bash`); `submit_patch` only in verifier and submitter prompts and in no helper string; graph tools named nowhere in the bundle; the harness prompt rendered by `build_agent_prompt` with graphs on names only tools declared on setup, except `submit_patch` (the documented exception, 0.2) | TP::test_named_tools_declared | CI |
| R89b | v10.1 helper naming: prompts, SKILL.md, YAML, every helper string (AST, f-strings rebuilt) and every helper output over its states (runtime pass) name a helper only as `python3 /tmp/swe/NAME.py` or the exact `run_skill_script` call, and no `/tmp/swe/X.py` names a missing helper; the hint constants rendered; controls from the race-2 triggers | T101::test_helper_names_only_as_commands, test_helper_output_names_only_as_commands, test_helper_hint_constants_clean, test_helper_output_runtime_clean, test_helper_name_lint_controls | CI |
| R89c | v10.1 run instructions: no numbered step starts with `python3`; the HELPERS block once per working stage | T101::test_helper_names_only_as_commands | CI |
| R90 | RECOVER, AMNESIA and TIME are byte-identical in locator, fixer and verifier; RECOVER is also in submitter; EDITFORM is byte-identical in fixer, verifier and submitter; all equal the section 3 text | TP::test_shared_blocks_identical | CI |
| R91 | Sizes: at most 370 words and 2,600 chars per prompt excluding placeholders; submitter at most 1,300 chars; setup at most 600 chars | TP::test_prompt_sizes | CI |
| R92 | Every `python3 /tmp/swe/X.py ...` command in prompts and SKILL.md names an existing script and only flags in its `FLAGS`; each rendered example parses with `parse_args` | TP::test_prompt_commands_match_flags | CI |
| R93 | SKILL.md: `name` equals the directory, description 300 chars or fewer, the install line first, usage lines equal each script's `USAGE` | TP::test_skill_md | CI |
| R94 | Worst-case stage-start prompt (the 10,095-char problem, every earlier reply at its measured race-1 p90 bounded by `max_output_tokens` (plan 768, notes 244, verifier reply 188 tokens), paid once in the handoff and again for any placeholder, compiled declarations, skill boilerplate, and the harness prompt for setup) is 8,000 tokens or fewer; no stage has a placeholder for its previous stage's `output_key` (review round 2) | TP::test_static_stage_start_budget, TP::test_handoff_paid_once, TT::test_static_stage_render | CI |
| R95 | Per stage, the call mix the prompts permit, with handoffs at measured sizes (section 6): A typical at 3.06 chars/token with a p95 statement and median handoffs, 12,000 or fewer; B at caps and 2.3 chars/token with p90 handoffs and the context meter's guard, at least 1,000 under 14,336; C the outlier statement guarded, under 14,336; D unguarded at caps and 2.3 with handoffs at `max_output_tokens`, 2,048 or more below 32,768; the double-paid fixer prompt fails B (control) | TP::test_worst_case_stage_budget, TP::test_double_paid_handoff_breaks_the_margin, TP::test_context_meter_does_not_cut_a_normal_first_round, TC::test_context_meter_* | CI |
| R96 | Protocol rules present: locator (title-to-code-names, `--obj`, runtime truth, CLAIM repro, "fails on original", plan fields); fixer (COMPLETE, never "nothing needs changing", the verify loop with SIBLINGS/SPEC GAPS/REGRESSIONS, the protected-files rule); verifier (status first, the empty rule, 2 repairs and t 240, the old-behaviour rule, finalize, submit last); submitter (finalize, EMPTY, submit); fixer and verifier: view only with view.py and run code only with run.py, so no unmetered output enters the stage (review round 2); v10.1: every helper as its full command, the locator's short reproduction and FILES-first reply, the verifier's text-call handoff line and `(no flags)` verify, the submitter's issue text, and submit after READY or at t>=285s (= `T_NO_RESTORE`) | TP::test_prompt_rules_present | CI |
| R97 | For all 74 tasks: gold and test patch parse and round-trip; gold touches no protected file; every test_patch file is protected; the new-file classification matches; each stage renders with this statement within R94 | TT::test_static_patch_facts[tid] | CI |
| R98 | `locate.py` recall with the problem statement as the query, on local snapshots: gold file at rank 1 in 21/40 or more, top 3 in 28/40 or more, top 8 in 34/40 or more (target 23/30/35); the 6 known misses xfail non-strict; per task 3 s or less and 1,800 chars or fewer | TT::test_locate_recall + TT::test_locate_budget[tid] | CI |
| R99 | Every gold hunk applied by `edit.py` (SEARCH/REPLACE with the hunk's old/new lines, and separately `--lines` bottom-up; new files via `--create`) gives files byte-identical to `git apply` (40 local tasks now; baseline 122/122 hunks) | TT::test_gold_hunks_via_edit[tid] | CI |
| R100 | Empty diff: `verify.py` gives NO SOURCE CHANGE in under 1 s | TT::test_verify_empty[tid] | CI |
| R101 | With gold applied, `verify.py --list-tests` includes a file the test_patch modifies in 25/39 or more (v9: 23; target 30) and never a non-collectable file | TT::test_discovery_recall | CI |
| R102 | Gold applied, no repro: verdict is not RED; confirmed regressions only in KNOWN_BEHAVIOUR_CHANGE {rich_3942, rich_3935, rich_3470, rich_3105, rich_3043, rich_3061}; never `undo`/`must fix`; aggregate p90 wall 8 s or less | TT::test_verify_gold[tid] | NIGHTLY |
| R103 | The test_patch is committed into the baseline, and a claim repro built from the test functions it adds is fed to `verify.py --repro-only`: every claim fails (or hangs) on original; after gold, `verify.py` reports `k/k claims fixed` in 36/39 or more tasks | TT::test_repro_flip_hidden[tid] | NIGHTLY |
| R104 | Gold, plus a raw edit inside the first test_patch hunk, plus root `repro.py`/`reproduce_issue.py`: finalize prints READY; the final diff applies to a fresh baseline; the test_patch applies on top; `mini_verify` resolves in 38/39 or more (known: requests_6644) | TT::test_finalize_saves_tampered_gold[tid] | NIGHTLY |
| R105 | `mini_verify` port: gold resolves in 39/40 (requests_6644 needs installed requests, F10); empty is not resolved (20 s hang cap; rich_4006, rich_3772, rich_3480 hang) | TT::test_mini_verify_gold_empty[tid] | NIGHTLY |
| R106 | Documents F1: an edit inside a test_patch hunk plus the harness-exact reset makes the test_patch fail to apply (`xfail(strict=True)`, so a harness fix alerts us) | TT::test_tamper_lost_under_harness[tid] | NIGHTLY |
| R107 | The parity venv `~/.cache/g4/kpar/rich` matches the Kaggle freeze (`eval/kaggle/rescore_fair/pip_freeze.txt`) for pytest, Pygments, markdown-it-py, mdurl, typing_extensions and attrs (skip with the build command when absent) | TT::test_kpar_matches_freeze | CI |
| R108 | In a real `SubprocessManager` sandbox, `install.py` run through the real ADK wrapper (`SkillToolset._build_wrapper_code`, `skill_toolset.py:571`) makes every helper reachable as `python3 /tmp/swe/<x>.py` from `run_command`, and `cat /tmp/swe/last.log` works | TS::test_install_real_wrapper_reachable | CI |
| R109 | Every helper run through the real wrapper with dict args (`--k v`) self-installs the rest and does its job with cwd = the wrapper temp dir | TS::test_every_helper_as_skill_script[helper] | CI |
| R110 | A heredoc edit through the real sandbox whose text contains `"/tmp/x"` and `/workspace/y` writes those literals to the file (F: harness_runtime 2.3) | TS::test_heredoc_path_roundtrip | CI |
| R111 | In the real sandbox with an inherited open pipe as stdin, `edit.py` without a heredoc and `verify.py --repro-only` return in 2 s or less | TS::test_stdin_inherited_in_sandbox | CI |
| R112 | Docker-like env (`TMPDIR` unset, `TEST_TMPDIR=<dir>/tmp`, no rewrite, `PYTHONPATH` unset with the package pip-installed editable into a throwaway venv): install and all helpers work, and base-tree runs import the base copy | TS::test_docker_like_env | CI |
| R113 | Mock-LLM flow through the compiled bundle in the real `Evaluator` (subprocess sandbox, synthetic task, `EventsCompactionConfig(5, 2, 14336, 5)`): (a) the happy path ends at the verifier's submit + text, and the submitter never runs; (b) the verifier replies without submitting, and the submitter submits; (c) setup replies READY without a call, and the locator's "can't open file" leads to the RECOVER install; (d) compaction forced mid-fixer raises nothing and `status.py` recovers; (e) the last LLM call's prompt is under 14,336 tokens in every scenario; (f) the submitter replies without submitting, the nudge restarts the pipeline, the FINAL banner makes it converge, and the verifier submits | TFL::test_flow[a-f] | CI |
| R114 | Scripted-gold end-to-end on 3 local tasks (rich_3278, rich_3480, rich_4075) through the real Evaluator with the mock model (install, locate, repro from the hidden tests, gold via `edit.py`, verify, finalize, submit) gives resolved=True; a scripted raw `sed` of the hidden test file is reverted and the task still resolves | TFL::test_scripted_gold_e2e[tid] | NIGHTLY |
| R115 | `scripts/run_eval.py` sets `events_compaction_config=EventsCompactionConfig(compaction_interval=5, overlap_size=2, token_threshold=14336, event_retention_size=5)` unless `G4_COMPACTION=0`; `G4_L4_SCALE=s` divides `--max-time-minutes` and `--timeout-seconds` by s and writes `s` to `/tmp/swe/clock_scale` in every agent sandbox; `G4_NO_EDITABLE=1` skips the `-e /workspace` install; defaults are unchanged for other callers (monkeypatched EvalConfig capture) | TR::test_run_eval_compaction_scale_noeditable | CI |
| R116 | `scripts/replay_l4.py --baseline` reproduces v4 as-is at 150.2 ± 0.5 s/task and `--design final` gives 154.0 ± 1.0 on the r_v9_eog base; with `--measured` 163.0 ± 1.0 (0 at the cap), with `--measured --no-cuts` 172.6 ± 1.0 (1 at the cap), and 249.8 ± 1.0 (16 at the cap) on r_v4 ×2, from `eval/race1/runs` (skips when absent) | TR::test_replay_reproduces_baseline | CI |
| R117 | Ship gate (restated in review round 2, section 9.2): `scripts/replay_l4.py --run eval/runs/r2_v10_1` re-times every v10 race-2 call with the L4 model; no task is projected past cap + 10 s and the N=130 hidden-run projection is under 12 h; the mean against r_v4's replay on the same task ids is reported, and above 1.08 × it names the first pre-registered knob; footer obedience is reported | TR::test_replay_gate, TR::test_gate_unit_cases, TR::test_cliff_projection_unit, TR::test_footer_obedience_unit | REPLAY |
| R118 | Race-2 KPIs as pre-registered in section 10.3 | TR::test_race_kpis | RACE |
| R119 | Linux parity: `V10_ONLY=1 scripts/linux_test.sh` runs all `tests/test_v10_*` in `python:3.12-slim` with `--cpus 2 --memory 4g`, `TMPDIR` unset and `TEST_TMPDIR=/tmp`, and they pass | TR::test_linux_parity_script (runs the script when Docker is available) | NIGHTLY |
| R120 | The `no_orphans` fixture detects a deliberately leaked `sleep` (self-test) and is autouse in every v10 test module | TC::test_no_orphans_fixture_detects | CI |
| R121 | v10.1: over t = 0..300 with no source change no hint says "keep the edit you have" or "End your stage"; EDIT NOW from 150 s (with the finalize command from 250 s) even over a full context meter | T101::test_empty_tree_never_told_to_end_its_stage | CI |
| R122 | v10.1 grep.py positional paths: a trailing existing file, `.`, a directory, two paths, `--tests` after a path, an absolute path outside the workspace, a missing path (NOTE), a quoted and an unquoted multi-word regex, a lone `setup.py`, a named test file | T101::test_grep_positional_paths | CI |
| R123 | v10.1 EDITED checkpoints: every landed edit and every non-empty tree status.py sees; finalize's EMPTY branch restores the latest; refused at t >= 285; a scored checkpoint outranks an EDITED one | T101::test_edit_checkpoints_every_landed_edit, test_status_checkpoints_a_native_edit, test_scored_checkpoint_beats_edited | CI |
| R124 | v10.1 finalize EMPTY: the time left, "an empty patch always fails", EDIT TARGET (latest undone edit, else latest source view; never a test file; none without a view); output 1,400 chars or fewer | T101::test_finalize_empty_text_and_edit_target | CI |
| R125 | v10.1 edit.py early EOF: named, nothing changed, not counted; a missing divider alone keeps the old message; EDITFORM states the EOF rule | T101::test_edit_early_eof_message | CI |
| R126 | v10.1 submit guard: protected files overwritten, appended or deleted after READY, and every scratch, vendored and new test/config sample without any finalize, stay out of the harness's exact submit and fallback commands; real changes under matching tracked dirs, a tracked root debug.py, new modules and a unicode path still ship | T101::test_guard_post_finalize_native_edit, test_guard_scratch_without_finalize, test_guard_keeps_real_changes, TFL::test_flow[g], TFL::test_flow[h] | CI |
| R127 | v10.1 guard, helpers' view and upkeep: changes() lists hidden edits, verify reverts them with the reason and the mark survives, finalize still cleans scratch, the base-tree copy ignores guard-matched files; arming is idempotent, under 1 s on 3,000 files, repaired by finalize after a read-tree, never done without the baseline tag; finalize undoes what the graders' rules forbid (the same rules as replay_l4 KPI 7/8) | T101::test_guard_helpers_view_unchanged, test_guard_fast_path_never_hides_a_dirty_file, test_guard_idempotent_fast_and_rearmed, test_guard_only_in_a_harness_workspace, test_finalize_enforces_patch_rules | CI |
| R128 | v10.1 view.py L-ranges (`L2-3`, `FILE:L2-3`, `L2 L3`) and status.py's VIEWED line (newest first, 4 at most, no test files) | T101::test_view_accepts_l_ranges, test_status_lists_viewed_ranges | CI |
| R129 | v10.1 replay_l4 diagnostic KPIs: each counter on a synthetic trace; on race 2 round 1 they reproduce the diagnoses (1 parsed and 29 unparsed invented tool names, 9/69 verifier first turns, 6 helpers and 2 tools typed into the shell, 11 locator replies at 768, 65 grep misses, the KPI 7/8 mechanisms, 3 tasks past cap + 10 s over all ids) and v9_eog's zeros | T101::test_replay_diag_kpis_unit, test_replay_diag_reproduces_race2_round1 | CI (REPLAY data when present) |

### 7.1 v9 bugs and their regression tests

| bug (source) | regression test |
|---|---|
| gate PASS when nothing ran (F3) | R60 |
| gate "must fix/undo" on old-behaviour tests (F4) | R62, R102 |
| HEAD instead of `_swegemma_baseline` (F5) | R11 |
| replace.py CRLF rewrite, form feed shift, latin-1 traceback, test-file edits, outside paths (F6) | R42, R44, R45 |
| run.py leaks process groups (F7) | R26, R14 |
| host `/tmp` literals in check.py:7 and replace.py:28 (test_plan R05) | R04 |
| gate `-o addopts=` and missing grader flags (competitors 5.1) | R58 |
| `_ws.py` picks `/workspace` before `PWD` | R10 |
| locate.py:9 reads inherited stdin | R30, R111 |
| locate.py docstring names `swe_tools` | R93 |
| install skipped in 20/51 tasks, 4 malformed calls (F2); backtick-closed args (e74_v2 N1) | R88, R108, R109, R113c |
| gate re-run loops, 16 times in a row (F12) | R63 |
| heredoc `/tmp` rewrite mutates code (R06) | R110, R23 |
| gate picked `tests/render.py` 11/40 (R38) | R57, R101 |
| helpers shadowed by repo `json.py`/`select.py` (v5 select.py, B R-B22) | R03 |
| rescore kernel astral-char corruption (F11) | R75 (the finalize diff); the kernel generator itself is out of scope |

---

## 8. Per-task offline test design (no GPU)

**Environment choice: per-repo uv venvs.** test_plan section 2 found Docker parity infeasible offline: the local image is
arm64 while the wheels are x86_64 manylinux. A uv venv built offline from `~/.cache/uv` plus `data/raw/wheels` is
feasible for rich (39 tasks) and requests (1). The venvs live **outside the repo**, in `~/.cache/g4/kpar/<repo>`
(override `G4_KPAR`). A `.kpar/` inside the repo would be swept by `tests/test_build.py::test_python_compiles`, which
walks every `.py` outside `data/`, `eval/` and similar dirs.

`scripts/build_kpar.sh [rich|requests|fastapi]`:
- `rich` and `requests` are offline: `uv venv -p 3.12 $KPAR/rich && VIRTUAL_ENV=$KPAR/rich uv pip install --offline --find-links data/raw/wheels pytest==8.4.2 Pygments==2.20.0 markdown-it-py==4.0.0 mdurl==0.1.2 typing_extensions==4.15.0 attrs==26.1.0`,
  and for `requests`, additionally `requests==2.33.0 urllib3 idna charset-normalizer certifi pysocks`.
- `fastapi` needs network once and is Carson's call: the pinned list of test_plan section 2 (pydantic 2.12.3 etc.), with
  no dirty-equals and no inline-snapshot.

**Coverage.** 40 of the 74 Kaggle-valid tasks have snapshots here (rich 39, requests 1). The 34 missing (31 fastapi,
rich_4076, rich_4077, rich_4079) skip with the exact fetch command, which is free but needs network and Carson's go:
`source /Users/carson/Projects/kaggriculture/.venv/bin/activate && python scripts/fetch_data.py snapshots/<tid>.tgz`.
Static tests (R97) run on all 74 today. Once snapshots and the fastapi venv exist, every task test runs on 74 with no code
change.

**`tests/v10_support/tasks.py`** (pinned API):
- `TASK_IDS`; `load_task(tid)`; `parse_patch(text) -> [FilePatch(path, new_file, hunks=[Hunk(old_start, old_len, new_start, new_len, lines)])]`.
  Port it from `scratchpad/tpv10/measure2.py:parse_patch`, which handles `@@ -0,0` new files and blank context lines.
- `has_snapshot(tid)`, `fetch_cmd(tid)`, `kpar_python(repo)` (skips with the build command when absent).
- `base_ws(tid)` (session cache in `$G4_CACHE/<tid>/base`, default `~/.cache/g4/ws`):
  1. extract the tgz (0.38 s);
  2. append the harness exclude lines (`container_setup.py:498-503`);
  3. write the harness `pytest.ini` plus the conftest hook exactly as the harness does, by calling
     `swegemma.harness.container_setup.setup_workspace_test_config` with a local adapter whose `exec(cid, cmd)` runs the
     command with `/workspace` mapped to the path (or port `measure2.py:setup_ws`);
  4. `git add -A && git -c user.email=a@b -c user.name=t commit -qm baseline --allow-empty && git tag -f _swegemma_baseline`.

  Variant `base_ws(tid, with_test_patch=True)` also commits the test_patch into the baseline (for R103).
- `fresh_ws(tid, tmp)`: `cp -c -R` (an APFS clone, 0.14 s), falling back to `cp -R`.
- `sandbox_env(ws, repo)`: `HOME=TMPDIR=TEST_TMPDIR=<ws>_tmp`, `SWE_DIR=<ws>_tmp/swe`, `PYTHONPATH=<ws>`,
  `PYTHONNOUSERSITE=1`, `PYTHONDONTWRITEBYTECODE=1`, `PATH=<kpar>/bin:...`, `LANG=C.UTF-8`, `SWE_DUAL=0`.
- `install_helpers(env)` runs the bundle's `install.py` from a temp copy. `run_helper(name, args, ws, env, stdin=None, timeout=90)`.
- `mini_verify(ws, patch, test_patch, *, tamper=None, timeout=20) -> (resolved, why, secs)` ports
  `verification.py:305-505`:
  - a fresh clone of the base, then the agent patch via `git apply` (with the harness fallbacks);
  - the harness-exact reset list, including `sitecustomize.py` (F1 is reproduced);
  - the test_patch;
  - rewrite `pytest.ini` and the conftest header;
  - the grader pytest line;
  - `swegemma.harness.verification._validate_junit_xml(xml, test_patch=...)` and the stdout checks.
- `hidden_claims_repro(tid)`: one `# CLAIM n: <file>::<test>` section per `+def test_x(` the test_patch adds, each
  `import subprocess, sys; sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "-p", "no:anyio", "<rel file>::<test>"]))`.
  This is test-harness code, not bundle code.
- `results(kind)` is a session fixture that computes per-task results once with `ThreadPoolExecutor(G4_J=4)` and writes
  `eval/offline/v10_<kind>.json`. Parametrised tests read from it, and aggregate tests assert the thresholds (without
  pytest-xdist, which is not installed).

**`tests/test_v10_tasks.py`:**

| test | asserts | tier | measured baseline (v9 helpers) |
|---|---|---|---|
| test_static_patch_facts[tid] | R97 | CI, all 74 | 74/74 |
| test_locate_recall, test_locate_budget[tid] | R98 | CI | 21/28/34; max 1,635 chars, 3.7 s under J=4 |
| test_gold_hunks_via_edit[tid] | R99 | CI | 122/122 hunks by line range |
| test_verify_empty[tid] | R100 | CI | 40/40, 0.3 s |
| test_discovery_recall | R101 | CI | 23/39 |
| test_verify_gold[tid] | R102 | NIGHTLY | FAIL on rich_3942 by default |
| test_repro_flip_hidden[tid] | R103 | NIGHTLY | new |
| test_finalize_saves_tampered_gold[tid] | R104 | NIGHTLY | new (0/39 survive tampering without it) |
| test_mini_verify_gold_empty[tid] | R105 | NIGHTLY | 39/40 gold, 3 hangs |
| test_tamper_lost_under_harness[tid] | R106 | NIGHTLY | 39/39 lost |
| test_kpar_matches_freeze | R107 | CI | - |

Wall time at J=4 (test_plan section 7):
- CI group: about 45-90 s for 40 tasks, about 2-3 min for 74.
- NIGHTLY group: about 5 min for 40 tasks and about 10 min for 74, with the 20 s hang cap.
- Nothing touches a GPU.

---

## 9. Time analysis

### 9.1 Cost model and replay
`t_call = 1.08 × (0.085 s + 28.5 ms × output tokens + 0.65 ms × uncached prompt tokens) + tool seconds`
(time_model 2, own_data 11). The counterfactual replay reuses `docs/v10/design_B_replay.py`: its loader, the collapse
rules (edit streaks to 1 call, post-cap calls dropped, 3rd+ repeats dropped, stage replies capped) and the cost model.
It applies the final v10 rules on top:
- a setup stage;
- the repro write, at 1.3 × one call of (300 out, 500 in, 2 s);
- the claim headers;
- the LOCATOR banner at 75 s, which ends the locator by about 95 s (EDIT NOW at 150 s in the pessimistic case);
- one fixer `verify.py`;
- the FINISH footer at 210 s;
- the verifier at 5 calls plus the v9-derived check load, cut at TIME 250 s;
- the submitter at a 5% fire rate.

Command: `.venv/bin/python docs/v10/final_replay.py` (0.7 s, stdlib). It is ported into `scripts/replay_l4.py --design final`
(R116).

| base trajectories (race 1, 51 tasks) | v4 as-is | **v10 central** | v10, locator banner ignored | v10 pessimistic (banners ignored, v9 verifier calls kept) |
|---|---|---|---|---|
| r_v4 | 150.2 | **139.0 (0.93)** | 139.5 (0.93) | 146.8 (0.98) |
| r_v9_eog | 174.0 | **154.0 (1.03)** | 158.0 (1.05) | 166.4 (1.11) |
| r_v9_c | 152.7 | **129.6 (0.86)** | 131.2 (0.87) | 139.4 (0.93) |
| r_v9_eg | 169.0 | **140.0 (0.93)** | 140.5 (0.94) | 148.4 (0.99) |
| r_v9_eo | 166.4 | **144.6 (0.96)** | 145.9 (0.97) | 149.6 (1.00) |
| r_v9_og | 177.0 | **155.1 (1.03)** | 159.3 (1.06) | 165.7 (1.10) |

Ratios are to v4 as-is (150.2 s/task). For comparison, judge 2's replay of design A gave 1.06 central on v9_eog, B plus
repro 1.07, and C central 1.18 (`scratchpad/judge2/replay_abc.py`). Projected tasks at 295 s or more: 0 for v10 in every
base, against 3 for v4 as-is.

Hidden-like tasks (every stage ×2, then the clock rules): v10 averages 199-221 s against v4's 236-264 s (×2, capped). That
is 0.81-0.93 × v4 central and 0.85-0.94 pessimistic, because the footers end stages that v4 let run to the cap.

**Review round 2: the table above is optimistic by construction.** Every column, including "pessimistic", cuts the
locator at 95 s (150 s), the fixer at 210 s and the verifier at 262 s. It also caps stage replies at 200/100/60 tokens
(`design_B_replay.py` REPLY_CAP), while race-1 locator replies ran median 418-442 and p90 1,020-1,087 tokens. No task can
pass about 275 s under those rules, so "0 at 295 s" is a property of the model, not a result. The rows below keep each
trajectory's measured replies, cut only at v10's `max_output_tokens` (locator 768 since round 2, fixer and verifier
2,048). They are shown with the footers obeyed and with no footer cuts at all, the real pessimistic case, since nothing
makes gemma obey a footer. Command: `.venv/bin/python docs/v10/final_replay.py` (last block), ported as
`scripts/replay_l4.py --design final --measured [--no-cuts] [--stretch 2]` (R116).

| base (51 tasks) | measured replies, footers obeyed | measured replies, no footer cuts | ×2, footers obeyed (vs v4 ×2 capped, 236.8) | ×2, no footer cuts |
|---|---|---|---|---|
| r_v4 | 147.2 (0.98), 0 at cap | 150.5 (1.00), 2 at cap | 210.3 (0.89), 0 | 249.8 (1.05), 16 |
| r_v9_eog | 163.0 (1.09), 0 | 172.6 (1.15), 1 | 223.4 (0.94), 0 | 268.5 (1.13), 31 |
| r_v9_c | 139.4 (0.93), 0 | 144.6 (0.96), 0 | 201.9 (0.85), 0 | 241.1 (1.02), 16 |
| r_v9_eg | 148.6 (0.99), 0 | 151.9 (1.01), 1 | 210.4 (0.89), 0 | 241.3 (1.02), 19 |
| r_v9_eo | 154.8 (1.03), 0 | 160.1 (1.07), 1 | 216.1 (0.91), 0 | 262.8 (1.11), 23 |
| r_v9_og | 163.0 (1.09), 0 | 173.3 (1.15), 2 | 219.8 (0.93), 0 | 263.9 (1.11), 28 |

So on public-like tasks v10 is 0.93-1.09 × v4 if the footers are obeyed and 0.96-1.15 × if they are not; the old 1.08 gate
would fail on the v9_eog and v9_og bases either way. On hidden-like tasks the saving claimed above comes entirely from
obeyed footers. Without them v10 is 1.02-1.13 × v4 ×2 capped, with 16-31 of 51 tasks at the cap (v4's own stages would be
capped there as well). The 12 h cliff is unaffected (9.2): at the cap the per-task wall is the cap.

### 9.2 The 12 h cliff
- **H1 (measured: hidden tasks are cap-saturated; v4 took about 308 s/task and about 10.4 h).** The per-task wall is
  `setup 3.6 + min(agent, 300 + 5 s maximum run_command overshoot) + teardown under 1 s` (`execution.py:27-40`).
  `run_skill_script` runs in a thread and does not delay the deadline (`skill_toolset.py:494`). Every helper finishes
  inside `real_budget`. v10 keeps the same cap, so the worst case is `600 + 120 × 309.6` = **10.49 h** for N=120 and
  11.35 h for N=130, identical to v4. **The whole-run wall is v4's or less: +0% against the +8% allowance.**
- **H2 (public-like hidden tasks).** Central 0.86-1.03 × v4 and pessimistic 0.93-1.11 × v4 on public-like trajectories
  under the footer-cut model. With measured replies it is 0.93-1.09 × with the footers obeyed and 0.96-1.15 × without
  (review round 2, 9.1). In that world, 120 tasks total about 5.3-6.3 h, so even 1.15× leaves more than 5 h of margin.
  The +8% line matters only when tasks approach the cap. That is H1, where v10 cannot exceed v4.
- **H3 (in between, ×2 stretch).** 0.81-0.94 × v4.
- **If verification counts** (UNVERIFIED): the hang tail per task is `timeout_seconds` 120 against v4's 180. Worst case
  10.9 h for N=120.
- **Ship gate R117 (restated in review round 2, before any race-2 run; race2_checklist Addenda 1).** The cliff lives in
  the cap-saturated regime, so the gate is stated there. The race-2 v10 traces, re-timed with the L4 model
  (`scripts/replay_l4.py --run`), must have:
  - no task past cap + 10 s;
  - an N=130 hidden-run projection under 12 h: 600 s, plus per task 3.6 + min(1.9 × re-timed, 305) + 1 s. The
    projection is at most 11.35 h while the cap holds, and it fails for a cap above 5.25 min.

  The replayed mean against r_v4 on the same ids is reported. It no longer blocks: before round 2 it was the blocker,
  and v10 projects 0.93-1.15 × on public-like tasks (9.1), about 6.3 h in total, which says nothing about the cliff.
  Above 1.08 ×, the pre-registered knobs apply in order:
  1. the verifier repair rounds, 2 to 1 (prompt; first);
  2. the LOCATOR banner, 75 to 60 (second).

  Already applied: `T_QUICK` 270 to 250 (review round 1, as 235 with the `T_VERIFY_END` clamp, section 4.1) and the
  locator's `max_output_tokens` 1,536 to 768 (review round 2). Each knob is a one-line change covered by R18 and R65.
- **Footer obedience must be measured in race 2** (review round 2). Every "footers obeyed" figure above assumes gemma
  heeds LOCATOR, EDIT NOW, CONTEXT, FINISH and TIME, and nothing enforces that. `replay_l4.run_kpis` reports, per footer,
  how often the stage's next step did what it asked (race2_checklist row 14, `footer_obedience`, reported only). The
  race-2 report states the rate next to the replayed time, and a low rate means the no-cut rows of 9.1 are the forecast.

---

## 10. Race-2 plan (Carson's go only; GPU spend)

### 10.1 Setup
- **Arms:** `r2_v9_eog` (control = the shipped sub4 bundle) and `r2_v10`, each run **twice** (±3 tasks of noise means a
  +4 median gain needs 2 paired runs). Arms are interleaved across the 2 GPUs as in `pod/chain_race.sh`, 2 tasks per GPU
  (the 1.7 H100-to-L4 ratio was measured at this concurrency, time_model 6).
- **Optional third arm** if budget allows: `r2_v10_t06`, with working-stage temperature 0.6. It is built by the
  `make_variant`-style copy with only `configs/gen_{locator,fixer,verifier}.yaml` changed.
- **Tasks:** all 74 valid ids (`data/arena_ids.txt` + `data/rest_ids.txt`).
- **Faithfulness**, through `scripts/run_eval.py` (R115). These settings apply to both arms:
  - `G4_COMPACTION=1`: `EventsCompactionConfig(compaction_interval=5, overlap_size=2, token_threshold=14336, event_retention_size=5)`.
    This is the organiser README value (`data/HARNESS_README.md:553-561`); our kernels used interval 15, which is the
    same with 1 invocation per task. It fixes config_space finding 6: pod races never compacted, and 49% of race-1 tasks
    crossed 14,336.
  - `G4_L4_SCALE=1.7`: pod cap 300/1.7 = 176 s (`max_time_minutes` 2.94), `timeout_seconds` 120/1.7 = 71 s for v10
    (180/1.7 = 106 s for v9_eog), and `clock_scale` 1.7 written to each agent sandbox's `/tmp/swe`, so the helper footers
    fire at L4-equivalent times.
  - `G4_NO_EDITABLE=1`: Kaggle installs nothing into `/workspace` (F9d).
  - `FAITHFUL=1` (`pod/run_eval.sh`): budgets come from each bundle's `eval_config.yaml`.
- **Chain:** `pod/chain_race2.sh`, modelled on `pod/chain_race.sh`:
  1. boot and health;
  2. the GO flag;
  3. preflight and canary on both bundles;
  4. the 4 arm-runs;
  5. `pod/backup.sh`, copying `eval/runs/r2_*` (traces, `task_results.jsonl`, `run.out`) to the Mac, **then**
     `runpodctl stop pod` as the last step of the chain (Carson's idle-pod rule).

  No checkpoints or weights are produced, so there is nothing else to save.

### 10.2 Before the race (all free, in order)
1. CI green: `.venv/bin/python -m pytest -q tests`.
2. NIGHTLY green: `G4_NIGHTLY=1 ... tests/test_v10_tasks.py tests/test_v10_flow.py`, plus `V10_ONLY=1 scripts/linux_test.sh`.
3. `scripts/validate.py submissions/v10`, `scripts/pack_bundle.py`, and `bash -n`/`shellcheck` on new `.sh` files (the
   existing `tests/test_build.py` covers them).
4. Optional and free: the Kaggle CPU helper-check/rescore kernel (Carson pushes).

### 10.3 Pre-registered pass conditions
These are written into `docs/v10/race2_checklist.md` **before** the run and checked by R118 (`tests/test_v10_runner.py::test_race_kpis`).

| KPI | pass condition | race-1 v9_eog |
|---|---|---|
| resolved, sum of 2 runs | v10 at least v9_eog + 6 on the paired 74 × 2; no run has v10 below v9_eog - 3 | 28/74 single |
| crashes | 0 context overflow, 0 unknown tool, 0 KeyError, 0 post-invocation ValueError | 0 / 0 / 0 |
| helper availability | install or bootstrap succeeded in at least 98% of tasks; `can't open file` calls 1 per 50 tasks or fewer | 27/51 installed, 70 failures |
| malformed `edit_file` | 1 or fewer per task on average | 3.1 (fixer) |
| patches touching protected files | 0 | 10/47 |
| patches with scratch or vendored files | 0 | 11/47 |
| empty patches | 2 or fewer per 74 | 4/51 |
| prompt tokens | every stage-run under 14,336 in at least 95%; max under 26,000 | max 25,352 |
| compaction events | reported (no threshold; used for the pod-to-Kaggle comparison) | never measured |
| time (R117, restated in review round 2, 9.2) | no task projected past cap + 10 s; N=130 hidden-run projection under 12 h; the mean against the r_v4 replay is reported, and above 1.08 × the first pre-registered knob applies | FAIL (5 past the cap; 1.16 ×; 9.79 h) |
| footer obedience | reported, no threshold (9.2): how often the next step of the addressed stage does what LOCATOR, EDIT NOW, CONTEXT, FINISH or TIME asks | no v10 footers |
| verify behaviour | a verdict line in at least 90% of tasks; checkpoint restores reported with outcomes | - |

**Kill rule:** after run 1, if v10 is below v9_eog - 3, or any crash class is above 0, stop the chain (the pod goes down),
diagnose from the traces and do not run 2. **Ship rule:** v10 replaces v9_eog as the next submission only if every row
passes. The push is Carson's.

### 10.4 Analysis
The analysis produces:
- paired per-task wins and losses, with an exact sign test;
- the union of solves;
- per-lever attribution from the verify verdicts: claims flipped, siblings acted on, restores that turned RED into
  GREEN, EMPTY recoveries;
- the replay time.

It goes to `docs/v10/race2_report.md` after the race (not part of this build).

---

## 11. Expected gain (honest)

Anchors:
- v9_eog measured 28/74 locally (±3); v4 measured 26/74, which became 0.12 (7/58) on the leaderboard, a transfer of
  about 0.34.
- The union of 14 runs is 38/74.
- About 15-19 public tasks are out of reach from the statement, and the hidden set was screened for such tasks.

| lever | mechanism | realistic public flips over v9_eog |
|---|---|---|
| helpers in about 100% of tasks, not 55% | setup, bootstrap, RECOVER, skills on every stage | enables the rows below |
| repro-must-flip with claims | locator claims, verify, fixer loop | +1.5 to +2.0 |
| edit channel plus loop breaker | edit.py tiers, ALREADY TRIED, STALE | +1.0 to +1.5 |
| regression/collection gate plus test revert | verify, hygiene everywhere, finalize | +1.0 |
| sibling sweep plus spec gaps (the partial-fix bucket, 19 of 30 losses) | automatic lists in verify | +0.5 to +1.0 |
| context guard plus dependency source plus runtime truth | caps, `view --obj`, status | +0.5 to +1.0 |
| checkpoint restore plus never empty | `_swe_ckpt`, finalize, late guard | +0.3 to +0.5 |
| hang safety | killpg, session clamp | +0.3 |
| title-to-code-names localisation | prompt rule plus bigram boost | +0.2 |

The levers overlap. **Expected local: 31-35/74, median 33.** **Expected leaderboard: 0.14-0.17 (8-10/58), median about
0.155**, with upside to about 0.19-0.21 if hidden losses are mostly mechanical (v4 ran most hidden tasks to the cap,
where v10's graded fallback tree is hygienic, syntax-checked, checkpoint-guarded and non-empty by t=150 s).

**Carson's 0.30 (18/58) is not expected from this or any of the three designs.** It is above our own 14-run union ceiling
after transfer (38/74 × 0.34 is about 0.17-0.18). A step change needs capability, not robustness: a stronger or faster
model path (a working LoRA, or best-of-k if an MoE makes parallel candidates cheap). v10 is the robust base those would
build on.

---

## 12. Build and ship gates (implementers)
1. Build the components (section 13) in dependency order: core, then locate, then edit and verify, then config, then
   tasks and integration. Each component's tests must pass on the Mac before the next depends on it. No helper file is
   generated; they are written by hand into `submissions/v10/skills/swe-tools/scripts/`.
2. After all components: `py_compile` of every helper; `.venv/bin/python scripts/validate.py submissions/v10`;
   `.venv/bin/python -m pytest -q tests` (the existing 370 plus all `test_v10_*`, CI tier in 10 min or less; the existing
   `tests/test_bundles.py` automatically covers v10); `bash -n` and `shellcheck` on new `.sh` files; `G4_NIGHTLY=1` run;
   `V10_ONLY=1 scripts/linux_test.sh`.
3. `scripts/pack_bundle.py submissions/v10 /tmp/...` gives a deterministic zip and sha256. It is not uploaded.
4. The race (section 10) and any Kaggle action are Carson's call.

---

## 13. Components (disjoint file sets)

| key | files | depends on | requirements |
|---|---|---|---|
| helpers-core | `scripts/_swe_common.py`, `install.py`, `run.py`, `status.py` (under `submissions/v10/skills/swe-tools/`); `tests/test_v10_core.py`, `tests/test_v10_run_status.py`, `tests/v10_support/__init__.py`, `tests/v10_support/repo.py` | - | R01-R28, R120 |
| helpers-locate | `scripts/_swe_index.py`, `locate.py`, `grep.py`, `view.py`; `tests/test_v10_locate_view.py` | core | R29-R38 |
| helpers-edit | `scripts/edit.py`; `tests/test_v10_edit.py` | core (view numbering convention) | R39-R51 |
| helpers-verify | `scripts/_swe_gate.py`, `_swe_ckpt.py`, `verify.py`, `finalize.py`; `tests/test_v10_verify.py`, `tests/test_v10_finalize.py` | core, locate (`_swe_index`) | R52-R77 |
| bundle-config-prompts | `submissions/v10/agent.yaml`, `eval_config.yaml`, `configs/*.yaml`, `sub_agents/*.yaml`, `prompts/*.md`, `skills/swe-tools/SKILL.md`; `scripts/pack_bundle.py`; `tests/test_v10_bundle.py`, `tests/test_v10_prompts.py` | helper `USAGE`/`FLAGS` (for R92/R93) | R78-R96 |
| tests-per-task-offline | `tests/test_v10_tasks.py`, `tests/v10_support/tasks.py`, `scripts/build_kpar.sh` | all helpers | R97-R107 |
| integration-runner-race | `scripts/run_eval.py`, `scripts/replay_l4.py`, `scripts/linux_test.sh`, `pod/chain_race2.sh`, `tests/test_v10_sandbox.py`, `tests/test_v10_flow.py`, `tests/test_v10_runner.py`, `tests/v10_support/mock_llm.py`, `tests/v10_support/sandbox.py`, `docs/v10/race2_checklist.md` | everything | R108-R119 |

Shared test support: `tests/v10_support/repo.py` (core) provides:
- `make_repo(tmp, files, *, baseline=True, exclude_lines=HARNESS_EXCLUDES)`: a git repo with the harness `pytest.ini`
  and conftest hook, the baseline commit and the `_swegemma_baseline` tag;
- `copy_helpers(tmp) -> Path`: the bundle scripts copied to a temp dir;
- `helper_env(ws, swe, fake_t=None) -> dict`;
- `run_helper(scripts, name, args, *, ws, env, stdin=None, timeout=30) -> CompletedProcess`;
- the `no_orphans` fixture (autouse when imported).

Other test modules import these; they never edit `repo.py`.

---

## 14. Open questions and UNVERIFIED items
- **Scorer backend:** subprocess (harness_runtime 2.1) or Docker (forum 742882). Every mechanism is specified for both
  (R108, R112, R119).
- **Scorer compaction:** 14,336/5 per the README. Stages stay under it either way.
- **`enable_sandbox_testing` on the scorer:** if False, pytest is masked, verify degrades to claims plus imports (R61),
  and the harness prompt tells setup that tests are disabled.
- **Hidden repos with src layout:** the tests import the host copy for everyone (F10). verify reports AMBER with the
  origin (R38).
- **vLLM prefix caching on the scorer:** it affects only the per-call declaration prefill (about 2.5k tokens), which the
  cost model already charges as uncached.
- **Whether the gemma4 template sorts tool parameters** (C's N1 mechanism) is inferred from traces, not read in the
  template source. R88 is harmless either way.
- **v10.1, not applied (measure first):**
  - The locator's `max_output_tokens` 768 -> 1,536 (diag 2 P2). With the measured p90 plan of 1,087 tokens entering
    every fixer call, R95 B misses its 1,000-token margin, and `CONTEXT_TOKENS` cannot drop far enough without cutting a
    normal first fixer round. The prompt now asks for a short reproduction and a reply that starts with `FILES:`.
  - `LoopAgent(max_iterations: 3)` around the submitter (diag 2 P6): it changes R78's tree; the harness nudge already
    restarts the pipeline with the tree and `/tmp/swe` intact when the last stage ends without a submit.
  - The context-meter reset at the fixer's start and CONTEXT enforcement in the locator (diag 4 5.3): a `status.py`
    first step adds about 460 estimated tokens to a normal first fixer round, past `CONTEXT_TOKENS`.
  - run.py heredoc mode, a per-stage call budget, "first edit within 5 tool calls" (diag 2 P8, diag 4 5.2), the
    `/tmp/swe/run_command.py` alias (diag 4 5.6) and finalize's quick-verdict line (diag 4 5.7): behaviour or
    measurement changes that need their own arm.
