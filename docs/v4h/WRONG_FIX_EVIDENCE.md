# Right file, wrong fix: what information was missing (v4, Kaggle 4xL4, 27 tasks)

Source run: `eval/kaggle/g4-l4-v4/` (bundle v4, 74 public tasks, 29 solved). The 27 rows below are every task that
`failure_taxonomy.json` classes `right_file_wrong_fix`. For each one I read the problem statement, gold `patch` and
`test_patch` from `data/tasks.jsonl`, the agent's final `patch` from `results.jsonl`, and the trace (tool calls,
test/repro runs and their output, stage messages). Read-only. Nothing was executed against a repo; no Docker, no model.

## Definitions used

Class (exactly one per row; where two apply, the row gets the one that binds, meaning the one that would still fail
the hidden test if the other were fixed, and the other is named in the sentence):

- **A**: the issue text states the expected behaviour and the agent's fix contradicts it.
- **B**: partial fix. A second function, file or branch in the gold patch is missing.
- **C**: the hidden test checks an edge case or API detail that the issue text does not state.
- **D**: title-only, or a link to an issue that is not in the text. No spec offline.
- **E**: semantically right, breaks on an implementation detail (symbol, type check, error-message wording).
- **F**: other (named in the row).

Repro-would-catch: would a repro built only from the issue text (its stated input, compared with its stated expected
outcome) FAIL on the agent's final patch?

- `yes (obs)`: observed in the trace. The agent ran such a repro after its last edit and the output already shows the
  failure.
- `yes (inf)`: inferred by reading the code. Not run.
- `no`: a repro of what the issue states passes on the agent's patch. The hidden test checks something else.
- `unknowable`: the issue gives no input or no expected outcome to build the repro from.

Lines are added + removed lines in the diff. The agent figure is the whole submitted patch. Where the agent's patch
also contains scratch or test files, the source-only count is in brackets.

## 1. Table

| id | class | repro-would-catch | gold lines | agent lines | what was missing |
|---|---|---|---|---|---|
| fastapi_15588 | E | no | 23 | 8 | Newline validation on `event`/`id` was right, but the test matches the message `SSE 'event' must be a single line`; the agent wrote `SSE field must not contain newline characters`, and the issue gives no wording. |
| fastapi_14986 | A | no | 34 | 6 | The issue says do not *store* root_path in servers; the agent deleted the per-request root_path entry entirely (the test `test_legitimate_root_path_still_appears` needs it), and escaped `swagger_ui_parameters` but not `init_oauth` (also B). |
| fastapi_13920 | E | yes (obs) | 4 | 60 [16] | The issue names the vendored `is_typealiastype` from typing-inspection; the agent wrote an `isinstance(typing.TypeAliasType)` check and an unwrap via `get_args(...)[0]`. Its own `test_pep695.py` raised a Traceback after the last edit, and it submitted anyway. |
| fastapi_14479 | E | no | 2 | 2 | The agent copied the issue's message verbatim (`Query param 'data' must be of one of...`); the gold and the test use `Query parameter 'q' must be one of...`. The issue text contradicts the test, so this was unknowable. |
| fastapi_14487 | C | no | 7 | 4 | The issue only says "do not include string as is". The test asserts the exact format `Validation errors:` / `Field: ('path', 'item_id')`; the agent returned a constant string. |
| fastapi_14306 | B | yes (inf) | 137 | 24 | The agent added an `endpoint_context` kwarg and `__str__` to the exceptions, but nothing in `routing.py` ever passes it, so the issue's exact "After" output (File/line/function + `GET /users/{user_id}`) never appears. |
| fastapi_14448 | B | unknowable | 106 | 21 | The agent added checks on `self.call` plus the fully unwrapped call. The gold also checks `__call__` at the partial-stripped and the unwrapped level (wrapped class-instance deps). The agent's own 5-test file passed. |
| fastapi_9753 | F: over-edit regression | yes (inf) | 7 | 10 | The `_unwrapped_call` change matches the gold. The extra partial-stripping in `get_typed_signature` exposes partial-bound args as request params, which breaks the case the issue says already works. Its self-written test used keyword partials over defaulted params, which masks this. |
| fastapi_5077 | B | unknowable | 6 | 2 | The agent fixed `get_typed_signature` but not `get_typed_return_annotation`, which holds the identical `getattr(call, "__globals__", {})` line. The test's function has a forward-ref return annotation. |
| fastapi_14419 | A | yes (inf) | 62 | 48 [5] | The title and body state the rule: scopes enter the cache key only if the dep or a sub-dep declares scopes or uses SecurityScopes. The agent unions sub-dep scopes, so a scope-less dep under `Security(...)` still gets a different key and is called twice. |
| rich_3934 | D | unknowable | 20 | 2 | "empty live" plus a link. The test wants no newline written when nothing was rendered (`last_render_height`); the agent changed `start(refresh=True)`. |
| rich_3953 | D | unknowable | 26 | 4 | "Fix ZWJ and edge cases" plus 2 links. The agent fixed the ZWJ-at-end StopIteration; `test_non_printable` (C0 controls have width 0) is not stated anywhere. Its own guessed-expectation script failed after the edit. |
| rich_3938 | D | unknowable | 45 | 2 | Title plus a link. The test needs the background reset before `\n` under soft_wrap and a new `Segment.split_lines_terminator` API (also C); the agent changed the width option. |
| rich_3894 | F: over-edit regression | no | 4 | 20 | The `__qualname__` type check matches the issue. The agent also dropped `name or`, which changes attribute qualnames. `pytest tests/test_inspect.py` FAILED after the edit (observed) and it submitted. |
| rich_3930 | C | unknowable | 12714 | 68 | A large feature. The tests assert new APIs (`split_text`, `split_graphemes -> (spans, cell_length)`, `CellSpan`, `get_character_cell_size` on chr(918000) = 0) that the issue describes only as a capability. |
| fastapi_15800 | D | unknowable | 654 | 71 [26] | The spec is the title only. The test (858 lines) asserts `fallback`, `check_dir`, `_frontend_routes`, error-code mapping; the agent mounted a plain `StaticFiles`. |
| fastapi_14616 | E | yes (obs) | 12 | 39 [9] | The right condition at the right line, but checked `isinstance(m, params.Json)`; the gold uses `pydantic.Json`. Its own `repro_test.py` failed after the edit, the fixer ran out of its 70 calls, and the verifier submitted. |
| rich_3468 | D | unknowable | 42 | 15 | "handle broken pipe" plus a link. The test asserts that `python -m rich \| head -1` exits with code 1 (gold: dup2 devnull + `SystemExit(1)` in `_check_buffer`); the agent's bare `raise SystemExit` exits 0. |
| rich_3782 | D | unknowable | 29 | 2 | "Syntax padding" plus a link. The gold adds a padding descriptor and subtracts horizontal padding from code_width; the agent removed a `+ 1`. `tests/test_syntax.py` had 3 failures after the edit (whether they predate it cannot be told from the trace). |
| rich_3772 | D | unknowable | 45 | 36 [8] | Title plus 2 links. The real bug is `raise e from e` (self-cause loop) and exception-group revisits; the agent guessed recursion inside the excepthook. |
| rich_3676 | C | yes (obs) | 13 | 28 [6] | The test asserts `Traceback().trace.stacks[0].notes == [...]`, an unstated `Stack.notes` field. Separately, the agent read `__notes__` from `stack.exc_value` (a str), so no note is rendered. Its own `test_notes.py` output shows the exception line with no note after it. |
| rich_3535 | C | no | 8 | 2 | The agent fixed `o` to `\u007f` (printable ASCII passes). The test also requires the box-drawing range U+2500-25FF as single-cell, which the issue does not state. The missing `-` in ` ˿` was left in place. |
| rich_3480 | D | unknowable | 4 | 3 | "fix infinite loop in append" plus a link. The test expects `a.append(a)` to give "oneone" (and `append_text` too); the agent raises ValueError on self-append. |
| rich_3472 | D | unknowable | 4 | 1 | "fix for missing field in dataclass" plus a link. The gold skips fields with no attribute; the agent added an unrelated `last_child` field to `Node`. |
| rich_3471 | D | unknowable | 1 | 58 [2] | "Fixed exception in append_tokens" plus a link. The gold strips control codes from token content; the agent changed `if style:` to `if style is not None:`. |
| rich_3043 | F: existing test pins old output | yes (obs) | 2 | 37 [27] | The agent did reach the right `<html>` move (fixer step 32), but the existing `test_export_html` asserts the old layout. It reverted, thrashed through 13 edits, and timed out with `{{`/`}}` unescaped; the final run shows `KeyError: '\n    color'`. |
| rich_3061 | C | yes (inf) | 91 | 2 | The test asserts a new `Text.extend_style` API and exact span splits. Separately, the agent's `part.style` is the part's base style, not its spans, so tab spaces stay unstyled, which contradicts the issue (also A). |

## 2. Counts

By class (27):

| class | n | ids |
|---|---|---|
| A, issue states it, fix contradicts | 2 | fastapi_14986, fastapi_14419 |
| B, partial (second function/file missing) | 3 | fastapi_14306, fastapi_14448, fastapi_5077 |
| C, test checks unstated edge case / API | 5 | fastapi_14487, rich_3930, rich_3676, rich_3535, rich_3061 |
| D, title-only / link-out | 10 | rich_3934, rich_3953, rich_3938, fastapi_15800, rich_3468, rich_3782, rich_3772, rich_3480, rich_3472, rich_3471 |
| E, implementation detail | 4 | fastapi_15588, fastapi_13920, fastapi_14479, fastapi_14616 |
| F, other | 3 | fastapi_9753, rich_3894 (over-edit regression); rich_3043 (existing test pins old output) |

By repro-would-catch (27):

| value | n | ids |
|---|---|---|
| yes (obs) | 4 | fastapi_13920, fastapi_14616, rich_3676, rich_3043 |
| yes (inf) | 4 | fastapi_14306, fastapi_9753, fastapi_14419, rich_3061 |
| no | 6 | fastapi_15588, fastapi_14986, fastapi_14479, fastapi_14487, rich_3894, rich_3535 |
| unknowable | 13 | the 10 D rows, plus fastapi_14448, fastapi_5077, rich_3930 |

Cross-tab against the taxonomy's `test_runs` (pytest runs):

- `test_runs == 0` (10): E 2 (15588, 13920), C 3 (14487, 3930, 3676), B 1 (14306), D 4 (3953, 15800, 3468, 3480).
- `test_runs > 0` (17): A 2, B 2, C 2, D 6, E 2, F 3.

What the counts say:

- **17 of 27 are out of reach of anything built from the issue text.** That is D 10, C 5, and the two E rows where
  the failing detail is message wording that the issue omits (15588) or contradicts (14479).
- **10 of 27 are reachable**: A 2, B 3, E 2 (13920, 14616), F 3.
- **The signal was often already there.** In 4 tasks the agent's own post-edit run already showed the failure:
  13920, 14616 and 3043 exited non-zero, and in 3676 the output lacks the note. In a fifth, rich_3894, an existing
  test failed after the edit. All five were submitted anyway. v4's verifier prompt says "fix it and re-run once.
  Failures unrelated to the change can be ignored"; v4h3 replaces that with a 3-round fix loop. So the
  "act on the failing signal" variable is already the one being tested in v4h3.
- **Self-written checks were weak.** 9753 used keyword partials over defaulted params, which masks the regression.
  14448 wrote 5 tests that pass on a partial fix. 14419's test checks a different property from the one the title
  states. 5077's repro was never shown failing on the base code.
- **The v4 helpers were missing (context, not a class).** In these 74 traces, 153 of 168 `python3 /tmp/swe/*.py`
  invocations returned "can't open file". So v4's verifier `test.py`/`check.py` steps almost never ran, and the
  agent fell back to raw pytest. v4h fixes this; see GATE.md.

## 3. Recommendation for v4h4 (one variable, pre-registered)

**Variable: a fail-before / pass-after issue repro in the verifier.** v4h4 = v4h3 plus one verifier step, nothing else
changed. Before any test run, the verifier writes `/tmp/repro.py` using only the input and expected outcome stated in
the issue: the code snippet, the "Before/After" output, or the behaviour rule in the title. It then:

1. runs it with the patch stashed (`git stash; python3 /tmp/repro.py; git stash pop`), and the run must FAIL. If the
   repro passes on the base, the repro is wrong: rewrite it once.
2. runs it on the patch, and the run must PASS. A failure here enters v4h3's existing fix loop.

If the issue states no input or no expected outcome (the D/C rows), the step is skipped.

Why this and not something else. Of the 10 reachable rows, the repro column is `yes` for 6 non-C/D rows (13920, 14306,
9753, 14419, 14616, 3043). Three of those six (13920, 14616, 3043) already had an observed failing post-edit signal,
which is v4h3's loop territory. **The incremental upper bound of v4h4 over v4h3 is therefore 3 tasks: fastapi_14306,
fastapi_9753, fastapi_14419.** All three are `yes (inf)`, so the bound is itself unverified. The fail-before
requirement targets the weak self-tests seen in 9753, 14448 and 5077. The rival single variable was a "pattern sweep"
(after editing a line, grep the repo for the same expression and the new parameter's producers). It applies to
fastapi_5077 (identical `__globals__` line in the sibling function) and fastapi_14306 (new kwarg with no caller):
bound 2, so it ranks second.

Pre-registration (written before any v4h4 run):

- Population: the same 74 public tasks, the same faithful Kaggle 4xL4 harness, paired per task against v4h3's run.
- Target set T = {fastapi_14306, fastapi_9753, fastapi_14419}.
- **PASS** requires all three of the following:
  - net flips (v4h3-fail to v4h4-pass, minus v4h3-pass to v4h4-fail) >= +2 over the 74;
  - at least 1 of those flips is in T;
  - zero new non-timeout crash rows.
- **FAIL**: anything else. If a v4h3 A/A rerun exists by then, the net-flip threshold becomes max(2, A/A flips + 1),
  fixed before reading v4h4.
- Ceiling stated up front: even a perfect v4h4 cannot exceed +3 on this population through this mechanism. The 17
  unreachable rows (D 10, C 5, E-wording 2) need information that is not in the issue text.
- Secondary measurements, which do not gate:
  - the fraction of tasks where the repro failed on base (repro validity);
  - the fraction where repro-pass coincided with hidden-test pass.

## 4. Commands used

All scratch output went to `$S=/private/tmp/claude-501/-Users-carson-Projects/654244a3-b38c-45a0-96af-d7e5f0aac6ce/scratchpad/wf`.
The working directory was `/Users/carson/Projects/gemma-swe-agent`.

```bash
# extract traces outside the repo
mkdir -p $S/traces && tar -xzf eval/kaggle/g4-l4-v4/traces.tar.gz -C $S/traces

# the 27 ids and their taxonomy fields
python3 -c "
import json
t=json.load(open('eval/kaggle/g4-l4-v4/failure_taxonomy.json'))
for x in t['tasks']:
  if x['class']=='right_file_wrong_fix': print(x['id'],x['stage'],x['edit_calls'],x['test_runs'],x.get('timed_out'),x['gold_files'],x['patch_files'])"

# per-task review files: problem, gold, test_patch, agent patch, trace (runs + messages)
mkdir -p $S/c && python3 $S/compact.py $S        # script reproduced below
sed '/^## TRACE/q' $S/c/<id>.txt                  # read problem/gold/test/agent
sed -n '/^## TRACE/,$p' $S/c/<id>.txt | cut -c1-900  # read trace

# runs after the agent's last source edit, with exit code and pytest summary
python3 $S/lastrun.py $S

# changed-line counts (gold vs agent; agent source-only excludes tests/, test_*.py, repro*.py, dotfiles, docs/)
python3 - <<'EOF'   # see cnt() below
EOF

# helper reachability across all 74 traces (unquoted heredoc so $S expands)
python3 - <<EOF
import json,glob,re
ok=bad=0
for f in glob.glob('$S/traces/traces/*.json'):
    for s in json.load(open(f))['steps']:
        for tc in s.get('tool_calls') or []:
            a=json.dumps(tc['arguments'])
            if tc['function_name']=='run_command' and re.search(r'tmp/swe/\w+\.py',a):
                c=str((s.get('observation') or {}).get('content'))
                bad+= "can't open file" in c; ok+= "can't open file" not in c
print(ok,bad)   # -> 15 153
EOF

# targeted trace checks
#   fastapi_9753 step 38 verifier-written test content; fastapi_5077 write_file/rm calls;
#   rich_3676 'Note 1' in test_notes.py output; rich_3953 test_zwj_fix.py output;
#   rich_3782 step 24/31 pytest output; fastapi_14616 verifier calls (BudgetExceeded then submit_patch)
```

`compact.py`:

```python
import json,sys,re
S=sys.argv[1]
tax=json.load(open('eval/kaggle/g4-l4-v4/failure_taxonomy.json'))
ids=[x['id'] for x in tax['tasks'] if x['class']=='right_file_wrong_fix']
res={json.loads(l)['id']:json.loads(l) for l in open('eval/kaggle/g4-l4-v4/results.jsonl')}
tasks={json.loads(l)['instance_id']:json.loads(l) for l in open('data/tasks.jsonl')}
def cap(s,n): s=s or ''; return s if len(s)<=n else s[:n]+f'\n...[{len(s)-n} more chars]'
for i in ids:
    t=tasks[i]; r=res[i]
    with open(f'{S}/c/{i}.txt','w') as f:
        f.write(f"#### {i}  resolved={r['resolved']} err={r.get('err')}\n## PROBLEM\n{cap(t['problem_statement'],3500)}\n## GOLD\n{cap(t['patch'],5000)}\n## TEST_PATCH\n{cap(t['test_patch'],4500)}\n## AGENT\n{cap(r.get('patch'),4000)}\n## TRACE (tests + messages)\n")
        tr=json.load(open(f'{S}/traces/traces/trace_{i}.json'))
        for s in tr['steps']:
            if s['source']=='user': continue
            au=s.get('extra',{}).get('author')
            if s.get('message'): f.write(f"[{s['step_id']} {au} MSG] {cap(s['message'],800)}\n")
            for tc in s.get('tool_calls') or []:
                a=json.dumps(tc['arguments'])
                if tc['function_name']=='run_command' and re.search(r'pytest|python',a):
                    f.write(f"[{s['step_id']} {au} RUN] {cap(a,600)}\n")
                    ob=s.get('observation') or {}
                    c=str(ob.get('content') if isinstance(ob,dict) else ob)
                    f.write(f"   -> ...{c[-700:]}\n")
                elif tc['function_name'] not in ('read_file','run_command'):
                    f.write(f"[{s['step_id']} {au} {tc['function_name']}] {cap(a,300)}\n")
```

Line counting (`cnt`): count `+`/`-` lines that are not `+++`/`---` headers. With `src_only=True`, skip files that match
`(^|/)(tests?/|test_*.py|repro*.py|reproduce*.py)` or start with `.` or `docs/`.

`lastrun.py` walks every tool call. It records the index of the last `edit_file`/`write_file` call, excluding writes to
`test_*`/`repro*`/`reproduce*` files. For every later `run_command` matching `pytest|python3? ` (and not a `/tmp/swe`
helper), it prints the exit code and the pytest summary line, or `Traceback` if one appears.

Caveats on reading:

- Gold patches longer than 5,000 characters (rich_3930, fastapi_15800, fastapi_14306, fastapi_14448, fastapi_14419)
  and test patches longer than 4,500 characters were read only up to those caps. The classification of those rows
  rests on the part that was read.
- Every `yes (inf)` and the rich_3782 test-failure attribution are code-reading inferences, not runs.
