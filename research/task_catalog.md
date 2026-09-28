# Task catalog: the 74 Kaggle-valid public tasks

Rebuilt 2026-09-28 (afternoon), replacing the 01:04 build. Sources: `research/tasks/*.json` (74 records, several revised after the first build), `research/tasks/_inputs.json` (Kaggle-env pass per config), trace mechanics of the fair pod runs `eval/eval3/eval/runs/p_v{4,6,7,8}`, the other 10 runs we have (race 1 arms in `eval/race1/runs/`, Kaggle 4xL4 runs `eval/kaggle/e74_v{2,3}`), the pain-point sweep `research/pain_points.md` (fourth sweep), and the measured follow-ups in `research/own_data.md`, `research/test_plan.md` and `research/gap_2.md` to `gap_6.md`. Machine-readable version: `research/task_catalog.json` (74 records: every record field plus outcomes, other-run solves, trace mechanics, patterns and lever tiers). Build script: `research/catalog_build/build_catalog.py`.

**Where we stand.** v4 solves 27/74 in the Kaggle env. The union of v4/v6/v7/v8 solves 35/74, and the union of all 14 runs 39/74. v4 (sub3) scored **0.12** on the public leaderboard, which is 7 of about 58 tasks; the hidden set is about 120 tasks split evenly between public and private. So the public-to-hidden transfer ratio is about 0.33 (0.12 / 0.365), and the target of 0.30 is about 18 of 58.

**What that means for the levers.** Every likely and possible flip below together is worth about +13 public tasks (27 -> ~40, 0.54). At a constant 0.33 transfer ratio that is only about 0.18 on the hidden set. Reaching 0.30 therefore needs the transfer ratio itself to rise. That can only come from levers aimed at what is different about the hidden set. The host screened those tasks for specs only the test reveals, and they run about 1.9x longer per task than public ones (roughly 55-75% hit the 5-minute cap, gap_5). So the mechanics and time levers (EDIT, HANG, GATE, TOOLDECL, HYGIENE) should count for more than their public flip counts, and levers that guess hidden names (CONVENTION) for less. The ranking in section 4 applies an explicit transfer weight for this reason. One public-leaderboard score has a run-noise SD of about 0.033 (gap_6), so a single submission cannot confirm any of this.

**Labels to handle with care.**
- `rich_3782` v7 is scored FAIL by the Kaggle rescore, but its patch passes `tests/test_syntax.py` 25/25 locally. With `ipython_pygments_lexers` installed (it is in the Kaggle pip freeze), two syntax tests flake for gold too (3 of 8 reruns). The record's failure mode is `env`.
- `fastapi_14851`: the hidden test passes at base in the Kaggle env. e74_v2 and four race arms resolved it with an empty patch. v4 lost it only because its run overflowed, and an overflow discards the patch and skips verification.
- Pod-env failures caused by the environment (python-multipart missing, Pygments skew) are already overridden by the Kaggle result in every record.

Contents: [1. All tasks](#1-all-tasks) · [2. Counts](#2-counts) · [3. Solution patterns](#3-recurring-solution-patterns) · [4. Levers](#4-ranked-generalizable-levers) · [5. Infeasible](#5-infeasible-for-a-5-minute-31b-agent)

## 1. All tasks

Gold size is files/hunks/lines changed. 'Kaggle env' lists the fair configs that pass (pod patches rescored in the Kaggle env). 'Other runs' counts solves among the other runs that attempted the task: race 1 arms (6 on 51 arena tasks, 2 on the other 23) plus the two Kaggle 4xL4 runs. Failure mode and difficulty come from the per-task record (`solved_by_*` means no config-wide failure mode).

| id | PR | kind | reveals fix | gold | Kaggle env | other runs | failure mode | difficulty | best solution (one line) |
|---|---|---|---|---|---|---|---|---|---|
| fastapi_5077 | [#5077](https://github.com/fastapi/fastapi/pull/5077) | bugfix | partial | 1f/2h/6l | none | 2/8 | partial_fix | easy | inspect.unwrap(call) before reading __globals__ in BOTH get_typed_signature and get_typed_return_annotation. |
| fastapi_5624 | [#5624](https://github.com/fastapi/fastapi/pull/5624) | bugfix | none | 1f/1h/4l | v8 | 1/8 | solved_by_some | medium | Copy the scopes list before extending it (`list(security_scopes or []) + scopes`) in get_dependant. |
| fastapi_9425 | [#9425](https://github.com/fastapi/fastapi/pull/9425) | bugfix | full | 1f/1h/2l | v4 v6 v7 | 7/8 | solved_by_some | easy | In get_typed_annotation map an evaluated stringified "None" (type(None)) back to None. |
| fastapi_9555 | [#9555](https://github.com/fastapi/fastapi/pull/9555) | bugfix | full | 1f/1h/22l | all 4 | 7/8 | solved_by_all | easy | Add _unwrapped_call = inspect.unwrap(self.call) and use it in all three Dependant is_*_callable properties. |
| fastapi_9753 | [#9753](https://github.com/fastapi/fastapi/pull/9753) | feature | partial | 1f/2h/7l | v4 v8 | 3/8 | solved_by_some | easy | Strip functools.partial layers in Dependant._unwrapped_call after inspect.unwrap. |
| fastapi_11194 | [#11194](https://github.com/fastapi/fastapi/pull/11194) | bugfix | partial | 1f/1h/7l | v6 v7 | 4/8 | solved_by_some | easy | Use each field's own field_info (not the hoisted body_fields[0]) in both File-to-bytes branches of _extract_form_body. |
| fastapi_13537 | [#13537](https://github.com/fastapi/fastapi/pull/13537) | bugfix | full | 1f/1h/3l | v4 v6 v8 | 8/8 | solved_by_some | easy | Build the complement-loop skip set from declared field aliases, not from the output dict, so skipped None values are not re-added as raw "". |
| fastapi_13920 | [#13920](https://github.com/fastapi/fastapi/pull/13920) | feature | partial | 1f/2h/4l | none | 0/8 | wrong_location | easy | Unwrap TypeAliasType (typing_inspection is_typealiastype) once at the top of analyze_param, before the Annotated metadata scan. |
| fastapi_14077 | [#14077](https://github.com/fastapi/fastapi/pull/14077) | refactor | full | 3f/6h/11l | v4 v6 v7 | 3/8 | edit_tool_failure | easy | Replace every use of the renamed Starlette 422 constant with the literal 422; grep until no use of the old name remains. |
| fastapi_14258 | [#14258](https://github.com/fastapi/fastapi/pull/14258) | feature | partial | 1f/1h/4l | none | 0/4 | hidden_spec | infeasible | First statement of include_router: `assert self is not router, "Cannot include the same APIRouter instance into itself. ..."` (assert, like its neighbours). |
| fastapi_14301 | [#14301](https://github.com/fastapi/fastapi/pull/14301) | bugfix | full | 1f/1h/5l | all 4 | 3/4 | solved_by_all | easy | Pass scope=depends.scope into get_dependant from get_parameterless_sub_dependant. |
| fastapi_14306 | [#14306](https://github.com/fastapi/fastapi/pull/14306) | feature | partial | 2f/12h/137l | none | 0/4 | hidden_spec | hard | Add an endpoint_ctx (TypedDict) kwarg to the ValidationException family, a singular/plural __str__ in the base, and pass the context from routing. |
| fastapi_14372 | [#14372](https://github.com/fastapi/fastapi/pull/14372) | bugfix | partial | 2f/3h/7l | all 4 | 4/4 | solved_by_all | easy | @dataclass(frozen=True) on Depends and Security (and replace the in-place `depends.dependency =` with dataclasses.replace). |
| fastapi_14419 | [#14419](https://github.com/fastapi/fastapi/pull/14419) | bugfix | partial | 2f/7h/62l | none | 0/8 | partial_fix | medium | Keep scopes in Dependant.cache_key only when the dependant or any sub-dependant (transitive, memoized) uses SecurityScopes. |
| fastapi_14448 | [#14448](https://github.com/fastapi/fastapi/pull/14448) | bugfix | partial | 2f/3h/106l | none | 0/8 | partial_fix | hard | Classify async/generator at every wrapper layer (partial, __wrapped__, instance, __call__, decorated __call__); prefer the async-gen path in _solve_generator. |
| fastapi_14458 | [#14458](https://github.com/fastapi/fastapi/pull/14458) | bugfix | full | 1f/4h/7l | all 4 | 8/8 | solved_by_all | easy | `if inspect.isclass(_unwrapped_call(self.call)): return False` in all three is_*_callable properties, before the __call__ fallback. |
| fastapi_14463 | [#14463](https://github.com/fastapi/fastapi/pull/14463) | bugfix | full | 1f/2h/3l | all 4 | 4/8 | solved_by_all | easy | copy.deepcopy (not dict.copy) the per-route additional response in get_openapi_path. |
| fastapi_14479 | [#14479](https://github.com/fastapi/fastapi/pull/14479) | bugfix | partial | 1f/1h/1l | none | 0/4 | hidden_spec | infeasible | Message on the bare Query assert: f"Query parameter {param_name!r} must be one of the supported types" (the merged wording, not the PR draft). |
| fastapi_14487 | [#14487](https://github.com/fastapi/fastapi/pull/14487) | tooling_or_docs | partial | 1f/1h/7l | none | 0/4 | hidden_spec | infeasible | Docs example returns "Validation errors:" plus one "Field: {loc}, Error: {msg}" line per exc.errors() entry instead of str(exc). |
| fastapi_14492 | [#14492](https://github.com/fastapi/fastapi/pull/14492) | tooling_or_docs | full | 1f/1h/1l | all 4 | 3/4 | solved_by_all | easy | Replace "identifier": "MIT" with "Apache-2.0" in the one docs_src example. |
| fastapi_14616 | [#14616](https://github.com/fastapi/fastapi/pull/14616) | bugfix | partial | 1f/2h/15l | none | 1/8 | wrong_semantics | medium | In _get_multidict_value skip getlist when any field_info.metadata item is a Json() instance (`type(item) is Json`). |
| fastapi_14786 | [#14786](https://github.com/fastapi/fastapi/pull/14786) | bugfix | full | 1f/1h/2l | all 4 | 4/4 | solved_by_all | easy | `return scheme, param.strip()` in get_authorization_scheme_param. |
| fastapi_14794 | [#14794](https://github.com/fastapi/fastapi/pull/14794) | bugfix | full | 1f/2h/5l | all 4 | 4/4 | solved_by_all | easy | Add `depends is None and` to analyze_param's special-type branch and delete the assert. |
| fastapi_14851 | [#14851](https://github.com/fastapi/fastapi/pull/14851) | refactor | partial | 1f/6h/157l | v7 | 6/8 (empty-patch passes) | solved_by_some | hard | Re-implement on_startup/on_shutdown lists, add_event_handler, _DefaultLifespan and generator-lifespan wrapping in APIRouter instead of inheriting them from Starlette. |
| fastapi_14873 | [#14873](https://github.com/fastapi/fastapi/pull/14873) | bugfix | full | 1f/2h/21l | all 4 | 8/8 | solved_by_all | easy | Move the on_startup/on_shutdown assignments to after super().__init__() in APIRouter.__init__. |
| fastapi_14986 | [#14986](https://github.com/fastapi/fastapi/pull/14986) | bugfix | partial | 2f/4h/34l | none | 0/8 | wrong_semantics | medium | Never mutate self.servers: add root_path per response on a copy of the cached schema; escape swagger params and initOAuth JSON through one helper. |
| fastapi_15280 | [#15280](https://github.com/fastapi/fastapi/pull/15280) | feature | none | 2f/3h/72l | none | 0/4 | hidden_spec | infeasible | FastAPI.vibe(path, *, prompt='') that raises FastAPIError("Are you kidding me? Happy April Fool's"). |
| fastapi_15588 | [#15588](https://github.com/fastapi/fastapi/pull/15588) | feature | partial | 1f/2h/23l | none | 0/8 | hidden_spec | medium | AfterValidator on event and id raising ValueError(f"SSE '{field}' must be a single line") for \r or \n. |
| fastapi_15589 | [#15589](https://github.com/fastapi/fastapi/pull/15589) | bugfix | none | 1f/1h/4l | v4 v7 | 4/8 | solved_by_some | medium | Also add get_validation_alias(field) (the unconverted name) to processed_keys so the raw underscore header is not re-added as an extra. |
| fastapi_15661 | [#15661](https://github.com/fastapi/fastapi/pull/15661) | tooling_or_docs | none | 1f/1h/216l | none | 0/4 | hidden_spec | infeasible | New scripts/prepare_release.py Typer app (bump version, update release notes) built from pure content->str functions, plus the workflows. |
| fastapi_15800 | [#15800](https://github.com/fastapi/fastapi/pull/15800) | feature | partial | 8f/20h/654l | none | 0/4 | hidden_spec | infeasible | New APIRouter/FastAPI.frontend(path, *, directory, fallback, check_dir) serving an SPA build as low-priority routes, with docs_src examples. |
| requests_6644 | [#6644](https://github.com/psf/requests/pull/6644) | bugfix | partial | 1f/1h/3l | all 4 | 4/4 | solved_by_all | easy | In HTTPAdapter.request_url collapse a leading '//' in path_url to '/' before urlopen. |
| rich_2725 | [#2725](https://github.com/Textualize/rich/pull/2725) | bugfix | partial | 1f/1h/10l | all 4 | 6/8 | solved_by_all | easy | Reorder box_segments to (head, mid, foot) to match the `0 if first else (2 if last else 1)` index. |
| rich_2943 | [#2943](https://github.com/Textualize/rich/pull/2943) | bugfix | partial | 1f/1h/2l | all 4 | 6/8 | solved_by_all | easy | `style._hash = None` (not a copy) in Style.clear_meta_and_links. |
| rich_3006 | [#3006](https://github.com/Textualize/rich/pull/3006) | bugfix | full | 1f/1h/2l | all 4 | 6/8 | solved_by_all | easy | `param.default is param.empty` (identity, not ==) in auto_rich_repr. |
| rich_3043 | [#3043](https://github.com/Textualize/rich/pull/3043) | bugfix | partial | 1f/2h/2l | none | 0/8 | wrong_semantics | easy | Move `<html>` to directly after `<!DOCTYPE html>` in CONSOLE_HTML_FORMAT; touch nothing else in the file. |
| rich_3052 | [#3052](https://github.com/Textualize/rich/pull/3052) | feature | partial | 1f/12h/34l | none | 0/8 | edit_tool_failure | easy | case_sensitive=True kwarg threaded through PromptBase and every ask overload; lower-case compare in check_choice; return the canonical choice. |
| rich_3061 | [#3061](https://github.com/Textualize/rich/pull/3061) | bugfix | partial | 1f/13h/91l | none | 0/4 | hidden_spec | hard | Rewrite Text.expand_tabs to extend the tab's spans over inserted spaces with cell-width tab stops; add Text.extend_style; drop empty-style spans. |
| rich_3063 | [#3063](https://github.com/Textualize/rich/pull/3063) | bugfix | partial | 1f/2h/4l | v4 | 0/8 | solved_by_some | easy | In markup.escape, double a lone trailing backslash. |
| rich_3067 | [#3067](https://github.com/Textualize/rich/pull/3067) | bugfix | partial | 1f/1h/2l | all 4 | 4/4 | solved_by_all | easy | Add '~' to ReprHighlighter's URL character class. |
| rich_3105 | [#3105](https://github.com/Textualize/rich/pull/3105) | bugfix | none | 1f/1h/2l | none | 0/4 | hidden_spec | infeasible | `<code style="font-family:inherit">` in CONSOLE_HTML_FORMAT. |
| rich_3180 | [#3180](https://github.com/Textualize/rich/pull/3180) | bugfix | partial | 2f/4h/127l | none | 0/4 | broke_tests | medium | Make chop_cells iterate left to right (no reversed()) and leave the divide_line call site alone. |
| rich_3278 | [#3278](https://github.com/Textualize/rich/pull/3278) | bugfix | partial | 1f/1h/1l | none | 1/8 | broke_tests | easy | Prepend `(?:\x1b[0-?])\|` as a new alternative to re_ansi so Fp private escapes are consumed; keep the existing class intact. |
| rich_3454 | [#3454](https://github.com/Textualize/rich/pull/3454) | bugfix | full | 1f/1h/2l | v8 | 5/8 | solved_by_some | easy | Add '@' to ReprHighlighter's URL character class (and do not touch tests/test_highlighter.py). |
| rich_3468 | [#3468](https://github.com/Textualize/rich/pull/3468) | bugfix | none | 1f/4h/42l | none | 0/8 | hidden_spec | medium | Catch BrokenPipeError around write+flush, dup2 devnull onto stdout and exit(1) (CPython SIGPIPE recipe) via a Console.on_broken_pipe hook. |
| rich_3470 | [#3470](https://github.com/Textualize/rich/pull/3470) | bugfix | none | 1f/1h/2l | none | 1/8 | hidden_spec | medium | Record only on a real flush: `if self.record and not self._buffer_index:` in Console._write_buffer. |
| rich_3471 | [#3471](https://github.com/Textualize/rich/pull/3471) | bugfix | none | 1f/1h/1l | none | 0/4 | hidden_spec | medium | strip_control_codes(content) inside Text.append_tokens, as __init__ and append already do. |
| rich_3472 | [#3472](https://github.com/Textualize/rich/pull/3472) | bugfix | none | 1f/1h/4l | none | 0/8 | wrong_semantics | easy | Skip dataclass fields the instance lacks (`hasattr(obj, field.name)`) in pretty.traverse. |
| rich_3480 | [#3480](https://github.com/Textualize/rich/pull/3480) | bugfix | none | 1f/2h/4l | none | 0/8 | partial_fix | easy | Iterate a snapshot of text._spans in BOTH Text.append and Text.append_text. |
| rich_3506 | [#3506](https://github.com/Textualize/rich/pull/3506) | bugfix | partial | 1f/1h/18l | v4 v6 v7 | 3/8 | solved_by_some | easy | Make _split_cells' start guess an under-estimate (or start at 0) so the forward scan never starts past the cut. |
| rich_3518 | [#3518](https://github.com/Textualize/rich/pull/3518) | bugfix | partial | 1f/1h/2l | v4 v6 v7 | 6/8 | solved_by_some | easy | Column(_index=index, highlight=self.highlight) for columns auto-created in add_row. |
| rich_3521 | [#3521](https://github.com/Textualize/rich/pull/3521) | bugfix | none | 1f/1h/34l | v6 | 1/8 | solved_by_some | medium | Make Segment._split_cells search two-way from the proportional guess (or scan from 0). |
| rich_3535 | [#3535](https://github.com/Textualize/rich/pull/3535) | bugfix | partial | 2f/2h/8l | none | 0/8 | edit_tool_failure | medium | Fix _is_single_cell_widths: end ASCII at U+007E, restore the U+00A0-U+02FF range hyphen, add box drawing U+2500-U+25FF. |
| rich_3675 | [#3675](https://github.com/Textualize/rich/pull/3675) | feature | partial | 2f/5h/41l | none | 0/8 | hidden_spec | medium | TTY_COMPATIBLE tri-state in Console.is_terminal: '1' True, '0' False, anything else falls through to detection. |
| rich_3676 | [#3676](https://github.com/Textualize/rich/pull/3676) | feature | partial | 2f/8h/13l | v4 v6 | 4/8 | solved_by_some | easy | Stack.notes = list(getattr(exc_value, '__notes__', [])), rendered after the exception value. |
| rich_3718 | [#3718](https://github.com/Textualize/rich/pull/3718) | bugfix | partial | 1f/3h/7l | v4 v6 v8 | 1/8 | solved_by_some | easy | Revert 7a38204: stylize the panel title/subtitle with the combined border_style. |
| rich_3772 | [#3772](https://github.com/Textualize/rich/pull/3772) | bugfix | none | 1f/6h/45l | none | 0/8 | wrong_semantics | medium | Cycle guards in Traceback.extract: stop on an already-seen __cause__/__context__ and keep a visited set for exception-group members. |
| rich_3777 | [#3777](https://github.com/Textualize/rich/pull/3777) | feature | partial | 2f/3h/13l | v7 | 1/8 | solved_by_some | easy | TTY_INTERACTIVE tri-state ('0' off, '1' on, else auto) read from self._environ before the is_interactive expression. |
| rich_3782 | [#3782](https://github.com/Textualize/rich/pull/3782) | bugfix | none | 1f/7h/29l | none | 0/8 | env (label disputed) | medium | Subtract horizontal padding from the auto code_width in Syntax._get_syntax and clamp it at 0. |
| rich_3882 | [#3882](https://github.com/Textualize/rich/pull/3882) | bugfix | full | 1f/1h/2l | v4 v7 v8 | 6/8 | solved_by_some | easy | self.console.print(error, markup=True) in PromptBase.on_validate_error. |
| rich_3894 | [#3894](https://github.com/Textualize/rich/pull/3894) | bugfix | full | 1f/1h/4l | v4 v7 | 6/8 | broke_tests | easy | Keep `name or __qualname__` and add a type guard falling back to __name__ when qualname is not a str. |
| rich_3905 | [#3905](https://github.com/Textualize/rich/pull/3905) | bugfix | full | 1f/1h/7l | all 4 | 4/4 | solved_by_all | easy | Wrap all of Progress.stop() in `if not self.disable:`. |
| rich_3930 | [#3930](https://github.com/Textualize/rich/pull/3930) | feature | partial | 6f/29h/12714l | none | 0/4 | hidden_spec | infeasible | Grapheme-aware cell widths: versioned rich._unicode_data tables, CellSpan/split_graphemes API, grapheme-safe chop_cells/set_cell_size. |
| rich_3934 | [#3934](https://github.com/Textualize/rich/pull/3934) | bugfix | none | 2f/3h/20l | none | 0/8 | hidden_spec | medium | Only write the stop() newline when the last render had height > 0 (LiveRender.last_render_height). |
| rich_3935 | [#3935](https://github.com/Textualize/rich/pull/3935) | bugfix | none | 1f/5h/16l | none | 0/8 | wrong_location | medium | Apply pad_edge in Table._get_padding_width exactly as the render path's get_padding does. |
| rich_3938 | [#3938](https://github.com/Textualize/rich/pull/3938) | bugfix | none | 2f/2h/45l | none | 0/4 | hidden_spec | infeasible | Add Segment.split_lines_terminator and style each line's text but not its newline in the soft_wrap branch. |
| rich_3942 | [#3942](https://github.com/Textualize/rich/pull/3942) | feature | none | 2f/7h/70l | none | 0/4 | hidden_spec | infeasible | Maintainer restyle of Markdown headings, hr and tables (golden ANSI snapshots). |
| rich_3944 | [#3944](https://github.com/Textualize/rich/pull/3944) | bugfix | none | 1f/1h/2l | none | 0/4 | wrong_location | hard | Return 1 (not 0) for codepoints beyond the width table in get_character_cell_size. |
| rich_3953 | [#3953](https://github.com/Textualize/rich/pull/3953) | bugfix | none | 1f/2h/26l | none | 0/8 | partial_fix | medium | Zero width for C0/C1 control characters in get_character_cell_size, and make the ZWJ next() safe at end of string. |
| rich_4006 | [#4006](https://github.com/Textualize/rich/pull/4006) | bugfix | partial | 1f/2h/45l | none | 0/8 | broke_tests | medium | Guarantee every split_graphemes branch advances and emits zero-width spans for leading ZWJ/VS16/zero-width chars; keep the ZWJ `+= 2`. |
| rich_4075 | [#4075](https://github.com/Textualize/rich/pull/4075) | bugfix | partial | 1f/4h/15l | none | 0/8 | wrong_semantics | medium | `objects = (NewLine(),) if end == "\n" else ("",)` when Console.print gets no objects. |
| rich_4076 | [#4076](https://github.com/Textualize/rich/pull/4076) | bugfix | none | 1f/1h/6l | none | 0/8 | wrong_location | hard | re.split(r"(?<=\n)") instead of splitlines() in AnsiDecoder.decode so a trailing newline survives. |
| rich_4077 | [#4077](https://github.com/Textualize/rich/pull/4077) | bugfix | partial | 1f/1h/3l | v8 | 4/8 | wrong_location | easy | Add FileProxy.isatty delegating to the wrapped file. |
| rich_4079 | [#4079](https://github.com/Textualize/rich/pull/4079) | bugfix | none | 1f/1h/7l | v6 v7 | 0/8 | solved_by_some | easy | In TableDataElement.on_text, style only plain str chunks; append pre-styled Text untouched. |

## 2. Counts

Repos: Textualize/rich 42, fastapi/fastapi 31, psf/requests 1.

**By kind**

| value | tasks | v4 solves | any fair config | any of 14 runs |
|---|---|---|---|---|
| bugfix | 56 | 23/56 | 29/56 | 33/56 |
| feature | 13 | 2/13 | 3/13 | 3/13 |
| tooling_or_docs | 3 | 1/3 | 1/3 | 1/3 |
| refactor | 2 | 1/2 | 2/2 | 2/2 |

**By statement_reveals_fix**

| value | tasks | v4 solves | any fair config | any of 14 runs |
|---|---|---|---|---|
| partial | 37 | 11/37 | 15/37 | 18/37 |
| none | 21 | 1/21 | 4/21 | 5/21 |
| full | 16 | 15/16 | 16/16 | 16/16 |

**By failure mode**

| value | tasks | v4 solves | any fair config | any of 14 runs |
|---|---|---|---|---|
| hidden_spec | 18 | 0/18 | 0/18 | 1/18 |
| solved_by_some | 17 | 10/17 | 17/17 | 17/17 |
| solved_by_all | 15 | 15/15 | 15/15 | 15/15 |
| wrong_semantics | 6 | 0/6 | 0/6 | 1/6 |
| partial_fix | 5 | 0/5 | 0/5 | 1/5 |
| wrong_location | 5 | 0/5 | 1/5 | 1/5 |
| broke_tests | 4 | 1/4 | 1/4 | 2/4 |
| edit_tool_failure | 3 | 1/3 | 1/3 | 1/3 |
| env | 1 | 0/1 | 0/1 | 0/1 |

**By 5-minute difficulty**

| value | tasks | v4 solves | any fair config | any of 14 runs |
|---|---|---|---|---|
| easy | 38 | 26/38 | 31/38 | 33/38 |
| medium | 20 | 1/20 | 3/20 | 5/20 |
| infeasible | 10 | 0/10 | 0/10 | 0/10 |
| hard | 6 | 0/6 | 1/6 | 1/6 |

**By tag (a task carries several)**

| value | tasks | v4 solves | any fair config | any of 14 runs |
|---|---|---|---|---|
| existing_tests_cover_area | 65 | 27/65 | 34/65 | 36/65 |
| statement_is_pr_description | 56 | 26/56 | 30/56 | 33/56 |
| edge_case_logic | 48 | 16/48 | 20/48 | 24/48 |
| single_function_fix | 45 | 21/45 | 27/45 | 30/45 |
| repro_easy_from_statement | 41 | 24/41 | 28/41 | 31/41 |
| test_reveals_hidden_spec | 36 | 4/36 | 6/36 | 9/36 |
| exact_string_or_format_required | 31 | 7/31 | 9/31 | 9/31 |
| needs_linked_issue_text | 28 | 1/28 | 5/28 | 7/28 |
| title_plus_link_only | 27 | 3/27 | 7/27 | 8/27 |
| multi_hunk_same_file | 21 | 5/21 | 6/21 | 8/21 |
| rendering_or_ansi_output | 19 | 6/19 | 7/19 | 7/19 |
| new_function_or_param | 18 | 1/18 | 3/18 | 3/18 |
| statement_names_fix_location | 16 | 12/16 | 13/16 | 15/16 |
| multi_file | 16 | 3/16 | 4/16 | 4/16 |
| env_sensitive_test | 7 | 2/7 | 4/7 | 5/7 |
| typing_or_signature_change | 5 | 1/5 | 1/5 | 1/5 |
| async_code | 5 | 2/5 | 3/5 | 3/5 |
| statement_names_new_api | 5 | 0/5 | 1/5 | 1/5 |
| performance_or_hang | 5 | 0/5 | 0/5 | 0/5 |
| large_feature | 5 | 0/5 | 1/5 | 1/5 |
| regex_change | 4 | 1/4 | 2/4 | 3/4 |
| docs_or_tooling_only | 3 | 1/3 | 1/3 | 1/3 |
| pydantic_or_validation | 2 | 0/2 | 0/2 | 1/2 |
| cli_or_script | 2 | 0/2 | 0/2 | 0/2 |

**Cross-tab: failure mode x statement_reveals_fix**

| failure mode | full | partial | none | total |
|---|---|---|---|---|
| hidden_spec | 0 | 9 | 9 | 18 |
| solved_by_some | 4 | 9 | 4 | 17 |
| solved_by_all | 10 | 5 | 0 | 15 |
| wrong_semantics | 0 | 4 | 2 | 6 |
| partial_fix | 0 | 3 | 2 | 5 |
| wrong_location | 0 | 2 | 3 | 5 |
| broke_tests | 1 | 3 | 0 | 4 |
| edit_tool_failure | 1 | 2 | 0 | 3 |
| env | 0 | 0 | 1 | 1 |
| **total** | 16 | 37 | 21 | 74 |

What the cross-tab says. When the statement contains the fix, v4 solves 15/16. The one miss, rich_3454, is a one-character regex edit that died in the edit-parse loop (134 rejected calls, then overflow), not a reasoning failure. When the statement reveals nothing, v4 solves 1/21 (any fair config 4/21, any run 5/21). Those 21 break down as hidden_spec 9, solved_by_some 4, wrong_location 3, wrong_semantics 2, partial_fix 2, env 1. Partial statements sit in between: v4 11/37. No fair config solved any of the 18 hidden_spec tasks, whatever the statement revealed; across all 14 runs 1 did (rich_3470 by r_v9_c).

**Measured v4 blockers, unsolved vs solved (control).** From the pod traces. This is an association, not a controlled result.

| signal (v4 run) | 47 unsolved | 27 solved |
|---|---|---|
| no change to any non-test source file | 20 | 0 |
| empty patch | 13 | 0 |
| ended in ContextWindowExceededError | 7 | 0 |
| hit the 6-min session or turn budget | 6 | 1 |
| >= 10 rejected or not-found edit_file calls | 8 | 2 |
| never ran pytest | 23 | 8 |
| patch touches tests/ | 5 | 1 |
| patch includes scratch files | 15 | 2 |

## 3. Recurring solution patterns

A task can match several patterns. The rates are how many of the listed tasks v4, any fair config, and any of the 14 runs solve.

**P1. PR description already contains the fix (names the function and the change)** (v4 15/16, any fair config 16/16, any run 16/16)

Move: Transcribe it at the named spot; grep the quoted expression; change nothing else.

Tasks: `fastapi_9425`, `fastapi_9555`, `fastapi_13537`, `fastapi_14077`, `fastapi_14301`, `fastapi_14458`, `fastapi_14463`, `fastapi_14492`, `fastapi_14786`, `fastapi_14794`, `fastapi_14873`, `rich_3006`, `rich_3454`, `rich_3882`, `rich_3894`, `rich_3905`

**P2. Title plus a bare issue link; the spec lives in the linked issue the agent cannot read** (v4 3/27, any fair config 7/27, any run 8/27)

Move: Decompose the title into code concepts, grep identifiers (not the issue number), reproduce the most literal reading, probe edge inputs.

Tasks: `fastapi_5624`, `fastapi_15280`, `fastapi_15661`, `fastapi_15800`, `rich_3063`, `rich_3105`, `rich_3468`, `rich_3470`, `rich_3471`, `rich_3472`, `rich_3480`, `rich_3506`, `rich_3521`, `rich_3675`, `rich_3676`, `rich_3772`, `rich_3782`, `rich_3934`, `rich_3935`, `rich_3938`, `rich_3942`, `rich_3944`, `rich_3953`, `rich_4006`, `rich_4076`, `rich_4077`, `rich_4079`

**P3. Hidden test asserts an exact error message or rendered string** (v4 1/14, any fair config 1/14, any run 1/14)

Move: Copy the neighbouring message/format idiom character for character; reuse the statement's own words; never pin a guessed string in your own test.

Tasks: `fastapi_14258`, `fastapi_14479`, `fastapi_14487`, `fastapi_15588`, `fastapi_14306`, `fastapi_15280`, `rich_3043`, `rich_3105`, `rich_3942`, `rich_3934`, `rich_3938`, `rich_4075`, `rich_2725`, `rich_3782`

**P4. Hidden test imports a new public name the statement never spells out** (v4 0/7, any fair config 0/7, any run 0/7)

Move: Rarely derivable. Name helpers after the nearest sibling (split_lines -> split_lines_<variant>) and put them where existing tests import from; cap effort.

Tasks: `fastapi_15661`, `fastapi_15800`, `fastapi_14306`, `fastapi_15280`, `rich_3930`, `rich_3938`, `rich_3061`

**P5. Statement names the new parameter / API / env var explicitly** (v4 1/7, any fair config 2/7, any run 2/7)

Move: Implement exactly that name, keyword-only with safe defaults; copy a companion setting's full value semantics; thread it through every overload and factory.

Tasks: `fastapi_13920`, `fastapi_15280`, `fastapi_15800`, `rich_3052`, `rich_3675`, `rich_3676`, `rich_3777`

**P6. Fix belongs at the shared chokepoint every caller goes through** (v4 6/8, any fair config 6/8, any run 7/8)

Move: Patch the one normalisation helper/entry point (not each caller, not a downstream helper you grepped first).

Tasks: `fastapi_14786`, `fastapi_9753`, `fastapi_9555`, `fastapi_14458`, `fastapi_14616`, `fastapi_13920`, `requests_6644`, `fastapi_14301`

**P7. Same defect at sibling sites (hidden test hits all of them)** (v4 3/10, any fair config 4/10, any run 5/10)

Move: After the first fix, grep the package for the same expression/pattern and fix every sibling; treat each 'Fixes #N' as its own bug.

Tasks: `fastapi_5077`, `rich_3480`, `fastapi_11194`, `fastapi_14986`, `fastapi_9555`, `fastapi_14458`, `rich_3953`, `fastapi_14448`, `fastapi_14077`, `rich_4006`

**P8. Shared mutable state leaks (aliased list/dict mutated in place, dict used as output and as 'handled' marker)** (v4 4/8, any fair config 5/8, any run 6/8)

Move: Copy at the point of sharing (list(x), deepcopy) or track handled keys in a separate set; do not delete the feature.

Tasks: `fastapi_5624`, `fastapi_14463`, `fastapi_14986`, `rich_3480`, `rich_3470`, `fastapi_13537`, `fastapi_15589`, `fastapi_14372`

**P9. Ordering / initialisation bug (build order vs index order, parent __init__ overwrites, value hoisted from items[0])** (v4 2/4, any fair config 3/4, any run 3/4)

Move: Find where the thing is built and where it is consumed; fix the side that disagrees with the documented meaning.

Tasks: `fastapi_14873`, `fastapi_11194`, `rich_2725`, `rich_4075`

**P10. Wrapped callables and annotations misclassified (partial, @wraps, classes, proxies, type aliases, string annotations)** (v4 4/8, any fair config 5/8, any run 6/8)

Move: Normalise every wrapper layer once, at the entry point, before classification; delegate explicitly when a base class shadows __getattr__.

Tasks: `fastapi_9555`, `fastapi_9753`, `fastapi_14448`, `fastapi_14458`, `fastapi_5077`, `fastapi_13920`, `fastapi_9425`, `rich_4077`

**P11. Two code paths compute the same quantity and disagree (measure vs render, sibling handler, start vs stop)** (v4 3/9, any fair config 5/9, any run 5/9)

Move: Diff the two paths and make the broken one apply every flag/step the working one applies.

Tasks: `rich_3935`, `rich_3782`, `rich_3521`, `rich_3506`, `rich_3180`, `rich_4079`, `rich_3471`, `rich_3905`, `rich_3518`

**P12. Regex / character-class allow-list is missing characters** (v4 1/4, any fair config 2/4, any run 3/4)

Move: Add only the missing range/char, keep existing literals (downstream code may compare the captured group), brute-force check against the slow path.

Tasks: `rich_3067`, `rich_3454`, `rich_3278`, `rich_3535`

**P13. Hang / infinite loop / recursion (loop branch that never advances, missing cycle guard, extend-while-iterating)** (v4 0/5, any fair config 0/5, any run 0/5)

Move: Run every repro under `timeout`; find the branch with no progress or the unguarded attribute walk; add the advance or a visited-id set.

Tasks: `rich_4006`, `rich_3772`, `rich_3480`, `fastapi_14258`, `fastapi_14448`

**P14. Sentinel / identity / type-guard edge case** (v4 5/6, any fair config 5/6, any run 5/6)

Move: Use `is` for sentinels, add a narrow guard after the original expression, invalidate caches rather than copying them.

Tasks: `rich_3006`, `rich_3894`, `rich_3472`, `fastapi_9425`, `rich_2943`, `rich_3063`

**P15. Byte-exact template or snapshot output** (v4 2/8, any fair config 3/8, any run 3/8)

Move: Minimal edit following the neighbouring formatting; never touch other templates' `{{ }}` escapes or the leading `"""\`; render once and diff.

Tasks: `rich_3043`, `rich_3105`, `rich_3942`, `rich_2725`, `rich_3718`, `rich_3938`, `rich_3934`, `rich_4079`

**P16. Upstream dependency changed; behaviour the repo relies on is inherited from site-packages** (v4 2/3, any fair config 3/3, any run 3/3)

Move: When grep finds no definition twice, read the installed base class source (inspect.getsource) and vendor what the repo needs.

Tasks: `fastapi_14851`, `fastapi_14077`, `fastapi_14873`

**P17. PR looks like docs/tooling but the tested artefact is runnable code** (v4 1/5, any fair config 1/5, any run 1/5)

Move: Change the runnable example/module (docs_src/, scripts/) and read its existing test for the output shape; ignore incidental chores.

Tasks: `fastapi_14487`, `fastapi_14492`, `fastapi_15661`, `rich_4075`, `rich_3043`

**P18. The correct fix changes behaviour an existing test pins; the hidden test_patch rewrites that test** (v4 0/6, any fair config 0/6, any run 1/6)

Move: An existing test that fails because it asserts the old behaviour the statement asks to change is expected, not a regression. Keep the fix, do not edit the test (the edit blocks test_patch). Measured with gate.py --target on gold patches (rich only; fastapi has no offline env).

Tasks: `rich_3942`, `rich_3935`, `rich_3470`, `rich_3105`, `rich_3043`, `rich_3061`

## 4. Ranked generalizable levers

Each lever is sized on the 47 tasks v4 does not solve. **Likely** means the lever removes the blocker seen in the v4 trace and some other run (or v4 itself in race 1) already had the right fix or location, or the record verified the patch one step from passing. **Possible** means the blocker is removed but a further step is uncertain. **Long shot** tasks are listed but not counted. Expected public flips use priors of 0.7 per likely and 0.35 per possible task; RETRY uses gap_2's replay instead. The rank uses expected flips x a transfer weight for the hidden set (reason per lever in the table). Levers overlap, so the counts do not add up. No lever tuned to fastapi or rich specifics is included.

| rank | lever | plausible flips (likely + possible) | expected public flips | transfer weight | rank score | why that weight |
|---|---|---|---|---|---|---|
| 1 | Repro-must-flip check before submit | 11 (4 + 7) | 5.25 | 0.8 | 4.20 | hidden statements are PR descriptions that rarely give a repro, so the repro must be derived; slightly harder there |
| 2 | Reliable edit channel plus mechanism-switching loop breaker | 5 (2 + 3) | 2.45 | 1.2 | 2.94 | measured on the scorer's own stack (Kaggle 4xL4: 32-52% parse rejects; for the same v2 bundle 14-16% of edit calls land on either stack); every wasted call is worth more on cap-saturated hidden tasks |
| 3 | Regression and collection gate before submit (return-code based, veto only) | 6 (2 + 4) | 2.80 | 1.0 | 2.80 | repo-agnostic; needs the return-code fix and the P18 exception or it vetoes correct fixes |
| 4 | Completeness sweep: every sibling site, every linked issue, every branch | 5 (2 + 3) | 2.45 | 1.0 | 2.45 | repo-agnostic; partial multi-site fixes are the largest measured loss bucket in every race arm |
| 5 | Hang-safe execution and time discipline | 3 (1 + 2) | 1.40 | 1.2 | 1.68 | repo-agnostic; hidden tasks run ~1.9x longer and 55-75% are estimated to hit the 5-min cap, so time discipline is worth more there |
| 6 | Localisation protocol for title-plus-link statements | 4 (1 + 3) | 1.75 | 0.8 | 1.40 | hidden statements also carry no issue text (0 of 40 linked issues' text reached a public statement) |
| 7 | Runtime ground truth instead of guessing library representations | 3 (1 + 2) | 1.40 | 0.8 | 1.12 | depends on libraries the hidden repos use |
| 8 | Context budget guard (no single huge tool result, fresh context per stage) | 4 (3 + 1) | 2.45 | 0.4 | 0.98 | pod runs had no compaction; on Kaggle compaction fired at 155 of 155 opportunities and 0 of 148 L4 task-runs overflowed |
| 9 | Never submit an empty, test-only or 'no bug' patch | 2 (0 + 2) | 0.70 | 1.0 | 0.70 | repo-agnostic floor; 3-7 no-error empty patches per run |
| 10 | Pre-submit patch hygiene | 1 (0 + 1) | 0.35 | 1.0 | 0.35 | repo-agnostic; 54 of 74 test_patches edit an existing test file, so any test edit risks a certain zero |
| 11 | Conditional second fixer on gate FAIL or empty patch | 12 (0 + 12) | 1.20 | 0.21 | 0.25 | gap_2 replay: +0.17 per 51 hidden-like tasks against +0.67 to +1.0 public-like (ratio ~0.21) |
| 12 | Copy the repo's own conventions for new checks, messages and settings | 2 (0 + 2) | 0.70 | 0.3 | 0.21 | the host screened hidden tasks for specs only the test reveals |
| 13 | Declare every tool name a stage can see; graph tools on stage 1 only | 0 (0 + 0) | 0.00 | 1.0 | 0.00 | repo-agnostic insurance; 3 of 148 Kaggle L4 task-runs crashed this way |

Notes on the ranking. RETRY's 12 plausible tasks are the ceiling (every unsolved task some other run solved); its expected value is the measured replay, about 1 task. TOOLDECL flips none of the 47 but removes a crash seen in 2% of Kaggle task-runs, so it ships with the free items regardless of rank. GATE's value depends on two fixes to gate.py (return code, baseline tag) and on the P18 exception: without the exception it rejects 6 of 39 gold patches, so it can lose rich_3043, rich_3470 and rich_3935 instead of winning them.

### 1. Repro-must-flip check before submit

How: Derive the literal repro from the PR text (hidden statements are PR descriptions that rarely carry a traceback) and write it to a file, never a bash -c one-liner (backticks, $ and quotes break it). Run it under an outer timeout at base and after the edit: it must misbehave at base and print the exact expected value after (assert the string, not 'looks fine'). If it already passes at base, re-run it through the other input shapes (model vs scalar param, wrapped vs plain, empty vs None, both argument orders) before concluding anything; never submit 'no bug' for a bugfix title. For functions with an invariant (split at cut, round-trip decode, width sums) sweep every position and boundary input, including every example value the statement names. Ship it inside the same gate script as GATE.

Evidence: 23 of the 47 unsolved v4 runs never ran pytest, against 8 of the 27 solved. In 3 of the 4 likely tasks another run (for fastapi_11194 and rich_3521 including r_v4, the same bundle) solved it, and in the fourth (rich_4075) two configs found the right branch, so the repro only has to reject the wrong patch. Reported elsewhere: reproduction-test diagnosis adds 8.0 points in SWE-Doctor (pain_points G1), and Agentless's reproduction filter adds 5.0 points (literature.md).

- Likely: `rich_4075`, `rich_3521`, `rich_4079`, `fastapi_11194`
- Possible: `fastapi_13920`, `fastapi_14616`, `rich_3472`, `rich_3777`, `rich_3782`, `rich_3935`, `rich_3470`
- Long shot: `fastapi_14419`, `rich_3468`, `rich_3934`, `rich_4076`, `rich_3535`, `rich_3953`
- Pain points it answers: G1, G6, D4, M (write repros to files), sweep #10 (tests pass on a near-miss fix)

### 2. Reliable edit channel plus mechanism-switching loop breaker

How: Remove edit_file from every stage. Edit only through run_command running our helper with the new text in a quoted heredoc (one code-bearing string argument, which parses cleanly). Helper order: exact anchor match, then unescape (\n \t \" \\ \uXXXX \x1b) and retry only after a failure, then a guarded line-range mode that prints numbered lines and requires the expected first line. Refuse an empty anchor, read and write bytes with newline='' (keeps CRLF), py_compile after every write and print a 3-line diff. Keep a hash of recent commands in the helper's state file and, on the second identical failure, answer with the alternative mechanism. Precondition: the helper must be installed in 100% of tasks (put install in every stage, not a skippable first call).

Evidence: Pod v4: 49% of edit_file calls parse-rejected, 13.6% changed a file. Kaggle 4xL4 (the scorer's stack): 32% (v2) and 52% (v3) rejected by the same mechanism, 14-16% land on either stack for the same bundle. Unescape-on-failure turns 54% of 'old_string not found' failures into a unique match (gap_3). 8 of the 47 unsolved v4 runs had 10 or more failed edits, against 2 of the 27 solved. Across 14 runs, 0 of 123 capped runs solved anything, and malformed-edit spirals are the main cause of turn caps (own_data TL;DR 3). When the statement gives the fix away, v4 misses only rich_3454: an edit-parse loop, not reasoning. Reported elsewhere: content-anchored, lint-gated edits add 3.0 points in SWE-agent, and line-number-addressed edits corrupt 99.1% of files after a one-line shift (literature.md), which is why the line-range mode stays guarded.

- Likely: `rich_3278`, `rich_3454`
- Possible: `fastapi_15588`, `rich_3043`, `rich_3052`
- Long shot: `rich_3535`, `rich_3944`
- Pain points it answers: A1, A2, A5, A7, A11, B1-B10, C1, C3, F8, J2, K1, K2, L1, L2, N1, sweep #1, #2, #3, #11, #12, #14

### 3. Regression and collection gate before submit (return-code based, veto only)

How: Before submit: py_compile every touched file, import the touched modules, then run the nearest existing test module(s) with -q under an outer timeout at base and on the patch, and count only NEW failures. Decide on pytest's return code (2-5, or no summary line, means FAIL) and diff against the _swegemma_baseline tag, not HEAD. On a new failure, show the failing assertion next to the statement: if the test asserts the old behaviour the statement asks to change, keep the fix and leave the test alone (P18); otherwise hand the fixer the failing ids and the diff in a fresh context. Use the verdict as a veto, never as a selector between two passing candidates.

Evidence: rich_3180 v8 passes 114/114 once its one extra call-site edit is removed (record, verified locally). Three of four rich_4006 configs broke the existing tests/test_cells.py; fastapi_15588's three non-empty patches failed at collection. Limits: only 4-7 of 51 unsolved patches per race arm break existing tests (own_data TL;DR 1); a final FAIL resolved 1 of 15 (gap_2) and a FAIL->PASS repair 2 of 3 (own_data 10); Agentless's regression filter is worth +1.3 points (literature.md). gate.py today reports PASS on a conftest import crash and when no test ran, and FAILs 6 of 39 gold patches with --target on the hidden-test file (test_plan F3, F4; pain_points G5).

- Likely: `rich_3180`, `rich_3278`
- Possible: `fastapi_14986`, `fastapi_15588`, `rich_3043`, `rich_4006`
- Long shot: `rich_3934`
- Pain points it answers: G1, G2, G5, F3, H3, I1 (veto), L1 (compile after every write), sweep #5

### 4. Completeness sweep: every sibling site, every linked issue, every branch

How: After the first successful edit, grep the package for the exact expression or pattern you changed (the blamed call, the hoisted variable, `.extend(` over an alias, the unescaped json.dumps, every loop branch that can finish without advancing) and apply the same fix at every sibling site. Treat each 'Fixes #N' link as a separate bug with its own repro. Before submit, list the sites the statement implies (parameter and return path, request and response, append and append_text) and check each is covered by the diff.

Evidence: In six tasks a config fixed one of two sites or branches: fastapi_5077 (v6, v7), rich_3480 (v8), fastapi_14986 (v6, v7), fastapi_11194 (v8), rich_3953 (v4, v7) and rich_4006 (v6, v7). Across race 1, 'right file, wrong or partial fix' is the largest loss bucket: 19 of r_v9_eog's 30 losses, 13 of them with fewer hunks than gold.

- Likely: `fastapi_5077`, `rich_3480`
- Possible: `fastapi_14986`, `rich_3953`, `rich_4006`
- Long shot: `fastapi_14448`, `fastapi_14419`, `rich_3535`
- Pain points it answers: G6, sweep #10

### 5. Hang-safe execution and time discipline

How: Every repro, test and helper command runs under an outer timeout that kills the whole process group (new session + killpg; today run.py's timeout leaves compound or piped commands running). A timeout is reported as 'cut off, still looping', which for a hang/loop/recursion title confirms the bug; never re-run a command that already hung. For such titles grep the named module for `while True` walks over attributes, self-recursive calls, `elif` branches with no advance and list.extend over an alias, and add the advance or a visited-id set. Land a first candidate edit by mid-budget: the harness scores the working-tree diff at the time cap, so the tree should always hold the best candidate so far.

Evidence: No config solved any of the 5 performance_or_hang tasks. v4 hung on its own code in rich_3480 (555 s, on its repro) and fastapi_14448 (558 s, at import). The hidden set: 10.4 h for ~120 tasks is ~308 s per task against 163 s on public tasks on L4, and gap_5 estimates 55-75% of hidden tasks hit the cap. At a time or turn cap the harness scores the working-tree diff, so an early candidate is worth something; at a crash it scores nothing.

- Likely: `rich_3480`
- Possible: `rich_3772`, `rich_4006`
- Long shot: `fastapi_14448`, `fastapi_14258`
- Pain points it answers: G2, J1, J3, sweep #17

### 6. Localisation protocol for title-plus-link statements

How: Split the title into code concepts and grep them as identifiers and class names (proxy -> *Proxy*, padding width -> _get_padding_width, record capture -> record/_buffer), never the issue number. Run `git log -p -5` on the hot files of the named subsystem to spot a recent regression. Look for two paths computing the same thing (measure vs render, sibling handler, producer vs consumer) and fix the producer the title names. Keep graph tools off this path: they save tokens, not accuracy, and their output is unbounded.

Evidence: v4 solves 3/27 title-plus-link statements and 0/5 wrong_location tasks. In race 1, 7 of the 9 tasks v9 arms won over v4 had locate.py put the gold file in the first 3 calls; locate.py's top-3 recall is 28 of 40 local tasks (test_plan section 0).

- Likely: `rich_4077`
- Possible: `rich_3935`, `rich_3782`, `rich_3470`
- Long shot: `rich_3944`, `rich_4076`, `rich_3471`, `rich_3772`
- Pain points it answers: Section 1 (statements are PR text; linked-issue text never reaches them), L1 (graph tools), sweep #13

### 7. Runtime ground truth instead of guessing library representations

How: Before matching on a library type or relying on an inherited method, print the real object: `FieldInfo.from_annotation(...).metadata`, `type(x).__mro__`, `inspect.getsource(Base.method)`, `pkg.__file__`. If a grep for a definition returns nothing twice, it is inherited from a dependency: read it from site-packages instead of paging repo files. Match markers with isinstance/type() on what is actually stored, and import helpers from already-installed dependencies rather than hand-rolling isinstance checks.

Evidence: In fastapi_14616 all four configs wrote Json checks that can never be true: `Json in metadata` misses because metadata holds a Json() instance. In fastapi_14851 three configs overflowed re-grepping the repo for a method that lives in Starlette.

- Likely: `fastapi_14851`
- Possible: `fastapi_14616`, `fastapi_13920`
- Pain points it answers: D4, F5

### 8. Context budget guard (no single huge tool result, fresh context per stage)

How: Cap every tool result at about 4k tokens (compaction cannot stop a one-step jump; search_similar_code returned up to 55,164 chars), bound reads with line ranges, pass located snippets in the handoff so the fixer does not re-read them, keep include_thoughts false and max_output_tokens near 1,536, and start each stage in a fresh context. An overflow raises out of run_async and the harness then submits '' even if a correct fix is on disk.

Evidence: 7 of the 47 unsolved v4 runs ended in ContextWindowExceededError, against 0 of the 27 solved; the overflow path submits '' even with landed edits (11 of 38 overflowed pod runs had landed edits). But the pod ran with no compaction; on Kaggle compaction fired at every one of 155 opportunities and 0 of 148 L4 task-runs overflowed (gap_4), so these flips are mostly a pod artefact.

- Likely: `fastapi_14851`, `fastapi_5624`, `fastapi_5077`
- Possible: `rich_4079`
- Pain points it answers: D1, D2, E1, E2, F2, F3, A9, sweep #6, #8

### 9. Never submit an empty, test-only or 'no bug' patch

How: If a stage is about to end (or 80% of the call/time budget is used) with no change to a non-test source file, force an edit phase on the best located file:line with the smallest plausible fix. A partial fix can pass; an empty one never does. Restate the problem statement in every stage's instruction.

Evidence: 20 of the 47 unsolved v4 runs changed no source file, against 0 of the 27 solved. Most of those came from edit loops, overflow or hangs, so the flips are credited to EDIT, CONTEXT and HANG; this lever is the floor for the rest (3-7 no-error empty patches per run, pain_points G4).

- Likely: none
- Possible: `rich_3782`, `rich_3472`
- Long shot: `fastapi_14258`, `rich_3105`, `rich_3942`
- Pain points it answers: A1, A2, A7, C3, C5, F1, G4, sweep #9

### 10. Pre-submit patch hygiene

How: Before submit, and again on a timer before the per-task cap: `git checkout -- ` every agent change under tests/, conftest.py and pytest.ini, and delete untracked files outside the package (repro*.py, root-level test_*.py). The harness's own reset step is a no-op when any listed path is unknown to git, so a test-file edit survives and the test_patch then fails to apply.

Evidence: 15 of the 47 unsolved v4 patches carry scratch files and 5 touch tests/. rich_3454 v6's gold-identical source fix was lost because its test-file edit blocked test_patch. The harness reset step is a no-op (test_plan F1) and 54 of 74 test_patches edit an existing test file.

- Likely: none
- Possible: `rich_3454`
- Pain points it answers: H1, H2, H3, sweep #9

### 11. Conditional second fixer on gate FAIL or empty patch

How: Only when the final gate says FAIL or the diff is empty, and at least 90 s remain: run one more fixer in a fresh context with the problem, the failing gate output and the reverted diff, and keep whichever candidate the gate does not veto. Never on a passing task, so the 12 h cap holds. Not Parallel k=2 (shared timer, one overflow kills both branches) and not a LoopAgent (no exit tool in the registry).

Evidence: The union of the four fair configs solves 35/74 and the union of all 14 runs 39/74, against v4's 27: 12 of the 47 were solved by some other run, which is the ceiling for a sampling lever. gap_2's replay of a conditional second fixer: +1.0 per 51 when it must fit in the remaining 300 s, +0.67 with a check stage, +0.17 per 51 on hidden-like tasks; Parallel k=2 is negative on hidden-like timing.

- Likely: none
- Possible: `fastapi_11194`, `fastapi_14616`, `fastapi_14851`, `fastapi_5077`, `fastapi_5624`, `rich_3278`, `rich_3454`, `rich_3470`, `rich_3521`, `rich_3777`, `rich_4077`, `rich_4079`
- Pain points it answers: C1, C2, I1, I2, sweep #18

### 12. Copy the repo's own conventions for new checks, messages and settings

How: For a new validation, reuse the enclosing function's idiom (assert vs raise, exception class) and the neighbouring message template with the field name and the statement's wording. For a new setting, copy the companion setting's full value semantics (tri-state 1/0/auto). Store captured attributes in their source shape. Extend the existing test module rather than creating new test files.

Evidence: No fair config solved any of the 18 hidden_spec tasks (one race arm solved rich_3470), and the host says the hidden set was screened for them, so this lever's public count overstates its hidden value.

- Likely: none
- Possible: `fastapi_15588`, `rich_3777`
- Long shot: `rich_3675`, `fastapi_14479`, `fastapi_14258`
- Pain points it answers: Section 1 (host screened hidden tasks for impossible specs)

### 13. Declare every tool name a stage can see; graph tools on stage 1 only

How: A call to an undeclared tool raises ValueError in ADK 1.36.1 and the harness then discards the patch. Every stage must declare every tool name that appears in its instruction, skills or inherited history, or run with include_contents none and name only its own tools. Keep search_similar_code and friends on the stage that sees the harness prompt only. Add a static bundle test that collects tool names from each stage's text and asserts they are in that stage's tools.

Evidence: 3 of 148 Kaggle L4 task-runs were lost to undeclared tool names (e74_v3 rich_4076 and fastapi_14419: a locator calling search_similar_code; e74_v2 rich_3676: a hallucinated git_grep); 0 of the 32 pod runs. None of the 47 flips because of it, since v4 never crashed this way, but each occurrence on the scorer is a certain zero.

- Likely: none
- Possible: none
- Pain points it answers: F6, F7, L3, sweep #4, #13

### Union and what it buys

- Likely overall (12): fastapi_11194, fastapi_14851, fastapi_5077, fastapi_5624, rich_3180, rich_3278, rich_3454, rich_3480, rich_3521, rich_4075, rich_4077, rich_4079.
- Possible overall (14): fastapi_13920, fastapi_14616, fastapi_14986, fastapi_15588, rich_3043, rich_3052, rich_3470, rich_3472, rich_3772, rich_3777, rich_3782, rich_3935, rich_3953, rich_4006.
- Long shot (10): fastapi_14419, fastapi_14448, fastapi_14479, rich_3468, rich_3471, rich_3535, rich_3675, rich_3934, rich_3944, rich_4076. None (11): fastapi_14258, fastapi_14306, fastapi_14487, fastapi_15280, fastapi_15661, fastapi_15800, rich_3061, rich_3105, rich_3930, rich_3938, rich_3942.
- At the stated priors that is about +13.3 public tasks, 27 -> ~40 of 74. For scale, the union of every run we have is 39/74, and 3 of the likely tasks (rich_3180, rich_3480, rich_4075) were never solved by any run; their tier rests on a verified near-miss or a clear trace. Race 1's paired v9_eog vs v4 difference (5 wins, 2 losses on 51, with the edit helper installed in only about half the tasks) is the closest controlled measurement, and it is within noise.
- Ship order: first the free mechanics (EDIT with a guaranteed helper install, NONEMPTY, HYGIENE, TOOLDECL). Then one gate script carrying REPRO, GATE and HANG, with gate.py's return-code and baseline fixes and the P18 exception. Then the CONTEXT per-result cap. RETRY goes last, and only as the conditional second fixer. SIBLING, TERSE, RUNTIME and CONVENTION are prompt/protocol rules that can ride along with any of them. Everything must keep total wall time within +8% of v4 (the 12 h cap leaves at most +15%, own_data 2.4).

### Per-task assignment for the 47 v4-unsolved tasks

| task | v4 blocker (from the trace) | fair configs that pass | other runs | overall tier | levers | note |
|---|---|---|---|---|---|---|
| fastapi_11194 | wrong location (routing.py is_body_form) | v6 v7 | 4/8 | likely | REPRO:likely, RETRY:possible | A Form-before-File repro still returns 422 after v4's edit. v6/v7 and four race arms, including r_v4 (the same v4 bundle), solved it. |
| fastapi_14851 | context overflow in a grep loop for an inherited method | v7 | 6/8 (empty-patch passes) | likely | RUNTIME:likely, CONTEXT:likely, RETRY:possible | The hidden test passes at base in the Kaggle env: e74_v2 and four race arms resolved it with an EMPTY patch. v4 lost it only to the overflow crash, which discards the patch and skips verification. |
| fastapi_5077 | context overflow; v6/v7 fixed one of two sites | none | 2/8 | likely | SIBLING:likely, CONTEXT:likely, RETRY:possible | r_v4 (same bundle) and e74_v3 solved it; grep for getattr(call, '__globals__') finds the second site. |
| fastapi_5624 | context overflow at 35 s / 23 calls | v8 | 1/8 | likely | CONTEXT:likely, RETRY:possible | v8 and r_v9_c passed with the copy fix; v4 never got to edit. |
| rich_3180 | broke 9 existing wrap tests | none | 0/4 | likely | GATE:likely | v8 passes 114/114 without its one extra call-site edit (record, verified locally). |
| rich_3278 | 93 'old_string not found' edits on a \x1b regex; 110-call cap | none | 1/8 | likely | EDIT:likely, GATE:likely, RETRY:possible | v8 landed the edit once and regressed an existing test the gate would flag; r_v9_og solved it (helper not installed; a plain grep found rich/ansi.py and its edits landed). |
| rich_3454 | 134 edit-parse rejects -> overflow | v8 | 5/8 | likely | EDIT:likely, HYGIENE:possible, RETRY:possible | v6's source edit equals gold but its test-file edit blocked test_patch; v8, three race arms and both L4 runs passed. |
| rich_3480 | own repro hung 555 s; v8 fixed one of two siblings | none | 0/8 | likely | SIBLING:likely, HANG:likely | timeout-wrapped repro plus a grep for `_spans.extend(` finds both methods. |
| rich_3521 | kept the overshooting guess | v6 | 1/8 | likely | REPRO:likely, RETRY:possible | A sweep over every cut position fails 24 != 23; v6 and r_v4 passed. |
| rich_4075 | did the docs chore only | none | 0/8 | likely | REPRO:likely | v6/v8 found the right branch; asserting print(end='!') == '!' flips them. |
| rich_4077 | hardened Console.is_terminal instead of the proxy | v8 | 4/8 | likely | TERSE:likely, RETRY:possible | Title 'proxy isatty' names FileProxy; v8 and four race arms passed with the gold patch. |
| rich_4079 | backticks in a bash -c repro -> context overflow | v6 v7 | 0/8 | likely | REPRO:likely, CONTEXT:possible, RETRY:possible | A repro written to a file works; v6/v7 passed; v8 wrongly concluded 'no bug'. |
| fastapi_13920 | wrong location (type helpers, not analyze_param) | none | 0/8 | possible | REPRO:possible, RUNTIME:possible | End-to-end repro stays 422; the alias is typing_extensions.TypeAliasType. No run solved it. |
| fastapi_14616 | check never true (`Json in metadata`) | none | 1/8 | possible | REPRO:possible, RUNTIME:possible, RETRY:possible | v6 was one expression away; printing FieldInfo.metadata shows a Json() instance. e74_v3 (Kaggle L4) solved it. |
| fastapi_14986 | deleted the root_path feature; 5/7 | none | 0/8 | possible | GATE:possible, SIBLING:possible | Existing root_path tests flag the deletion; v6/v7 each escaped only one of two sites. |
| fastapi_15588 | 74 failed edits; rewrote unrelated code -> ImportError | none | 0/8 | possible | EDIT:possible, GATE:possible, CONVENTION:possible | Right idea in v4; needs clean edits, a collection check and the neighbour message idiom. |
| rich_3043 | de-escaped SVG `{{ }}`; v7/v8 empty after failed edits | none | 0/8 | possible | EDIT:possible, GATE:possible | Existing SVG tests catch the collateral damage, but gate.py FAILs even the gold patch here (P18), so the gate must not veto blindly. |
| rich_3052 | 141 edit-parse rejects -> overflow (125-144 in every config) | none | 0/8 | possible | EDIT:possible | Right file and spot found; must also return the canonical choice. |
| rich_3470 | repro-only / wrong place | none | 1/8 | possible | REPRO:possible, TERSE:possible, RETRY:possible | r_v9_c solved it (locate.py 'record capture' -> console.py:334). The gold fix makes an existing test fail (P18). |
| rich_3472 | scratch files only; wrong reading of 'missing field' | none | 0/8 | possible | REPRO:possible, NONEMPTY:possible | A repro that does not raise means the hypothesis is wrong; the init=False field is the case. |
| rich_3772 | read 'recursion' as RecursionError; tests hang | none | 0/8 | possible | HANG:possible, TERSE:long | Hang heuristic: an unguarded `while True` over __cause__ needs a cycle guard. |
| rich_3777 | handled '0' only | v7 | 1/8 | possible | REPRO:possible, RETRY:possible, CONVENTION:possible | Copying the companion TTY_COMPATIBLE tri-state fully gives '1'; v7 and r_v9_c passed. |
| rich_3782 | test-only patch | none | 0/8 | possible | REPRO:possible, TERSE:possible, NONEMPTY:possible | v7 made the correct fix in 20 calls; its Kaggle FAIL is most likely a flaky Pygments test (gold failed 3 of 8 local reruns), so even a correct patch passes only part of the time. |
| rich_3935 | wrong location (padding.py) | none | 0/8 | possible | REPRO:possible, TERSE:possible | grep 'padding_width' -> _get_padding_width; the measure path ignores pad_edge. The gold fix makes an existing test fail (P18). |
| rich_3953 | fixed ZWJ only, missed control chars | none | 0/8 | possible | REPRO:long, SIBLING:possible | Two 'Fixes #' links are two bugs; the boundary probe chr(1) shows width 1. |
| rich_4006 | changed intentional ZWJ step; timed out | none | 0/8 | possible | GATE:possible, SIBLING:possible, HANG:possible | Existing test_cells.py catches the ZWJ regression in 3 of 4 configs; v6/v7 each fixed one of the two non-advancing branches. |
| fastapi_14419 | partial: own-field check, not transitive | none | 0/8 | long | REPRO:long, SIBLING:long | A nested parent->child->grandchild case with a call counter would show the miss. |
| fastapi_14448 | own infinite loop over __call__ hung import (558 s) | none | 0/8 | long | SIBLING:long, HANG:long | Seven indirection layers plus a consumer in another file. |
| fastapi_14479 | copied the PR draft wording | none | 0/4 | long | CONVENTION:long | Reviewer-edited string; the host says hidden tasks were screened for this kind. |
| rich_3468 | wrong exit semantics (120) | none | 0/8 | long | REPRO:long | Needs the CPython SIGPIPE recipe (exit 1); a real-pipe repro shows 120. |
| rich_3471 | invented a None input | none | 0/4 | long | TERSE:long | Comparing append_tokens with append would show the missing strip_control_codes. |
| rich_3535 | 66 failed edits, empty; v8 partial | none | 0/8 | long | REPRO:long, EDIT:long, SIBLING:long | Box-drawing range is a hidden choice; a brute-force check vs the slow path might surface it. |
| rich_3675 | copied FORCE_COLOR 'any value' semantics | none | 0/8 | long | CONVENTION:long | Tri-state is conventional but not stated. |
| rich_3934 | changed __enter__, broke 6 byte-exact tests | none | 0/8 | long | REPRO:long, GATE:long | The gate flags the regressions; the zero-height guard is still a guess. |
| rich_3944 | 78 failed edits, empty; others edited CSS fonts | none | 0/4 | long | EDIT:long, TERSE:long | git log -p on cells.py plus probing private-use codepoints. |
| rich_4076 | wrong location (pretty.py, markdown.py) | none | 0/8 | long | REPRO:long, TERSE:long | Round-trip from_ansi(x).plain == x over '\n', 'a\n' points at decode. |
| fastapi_14258 | empty patch; 6-min session timeout after 11 calls | none | 0/4 | none | HANG:long, NONEMPTY:long, CONVENTION:long | The assert idiom is derivable, the exact merged message is not. |
| fastapi_14306 | wrong kwarg name + NameError in closure | none | 0/4 | none | - | Hidden endpoint_ctx name and exact str() rendering. |
| fastapi_14487 | dropped per-field info | none | 0/4 | none | - | Exact 'Validation errors:' / 'Field:' strings are not in the statement. |
| fastapi_15280 | test-only patch | none | 0/4 | none | - | April Fool's joke; behaviour exists only in the hidden test. |
| fastapi_15661 | wrote CI YAML, no module | none | 0/4 | none | - | Hidden scripts.prepare_release API. |
| fastapi_15800 | 115 edit-parse rejects -> overflow | none | 0/4 | none | - | 654-line feature with hidden kwargs and internals. |
| rich_3061 | one-line style tweak; hidden extend_style API | none | 0/4 | none | - | Exact _spans representation plus a new public method (hard, never solved). |
| rich_3105 | empty patch | none | 0/4 | none | NONEMPTY:long | 'Fix #3104' only; exact inline-style string. |
| rich_3930 | unused new module | none | 0/4 | none | - | 12,714-line feature with hidden CellSpan / rich._unicode_data API. |
| rich_3938 | scratch only | none | 0/4 | none | - | Hidden Segment.split_lines_terminator helper. |
| rich_3942 | empty patch | none | 0/4 | none | NONEMPTY:long | Maintainer taste; golden snapshots. |

### Which lever each pain point supports

The 18 items of the sweep summary:

| # | pain point | lever(s) it supports |
|---|---|---|
| 1 | Gemma 4 drops the closing `<\|"\|>`; vLLM 0.19.1 lets new_string swallow ',old_string:' (32-74% of edit_file calls) | EDIT (primary). Also HANG: the resulting spirals burn the time/turn cap. |
| 2 | Literal \n / \" escapes in old_string -> 'old_string not found' (95-98%) | EDIT: unescape-on-failure tier (rescues 54% in replay), heredoc bodies. |
| 3 | The same failed call repeated many times (31-46% exact repeats) | EDIT: loop breaker inside the helpers plus removing edit_file; RETRY only as a fresh-context fallback. |
| 4 | An undeclared tool name raises ValueError in ADK and ends the task (3/148 Kaggle task-runs) | TOOLDECL. |
| 5 | A test gate that reads failures from output instead of the exit code reports a crash as a pass (our gate.py) | GATE: decide on the return code, add the regression test. |
| 6 | Context overflow; compaction that never fires or cannot fire | CONTEXT (per-result cap, fresh context per stage). Scorer compaction does fire, so the residual risk is one-step jumps. |
| 7 | Chat template vs serving stack: June template turn-tag bug on prose plus a tool call | EDIT's 'no prose before a call' rule; otherwise eval fidelity, not a task lever. |
| 8 | Thinking tokens fill the window | CONTEXT (include_thoughts false, output cap ~1,536). |
| 9 | Success reported with no change, a test-only change, or edits to tests | NONEMPTY and HYGIENE. |
| 10 | Tests pass on a wrong fix one edit away from the right one | REPRO (cover every example and boundary the statement names) and SIBLING. |
| 11 | A required parameter small models omit breaks every call | EDIT: helpers take one required input, default the rest, print usage in every error. |
| 12 | An edit tool normalizes line endings / decodes lossily | EDIT: newline='' and bytes I/O in replace.py. |
| 13 | Code-graph tools save tokens, not accuracy | TERSE (identifier grep, locate.py) over graph tools; TOOLDECL and CONTEXT keep graph tools on stage 1 with bounded output. |
| 14 | Qwen2.5-Coder tool calls come back in a shape the parser cannot read | EDIT: send code through the argument shape the model gets right (one string via run_command). |
| 15 | The serving setup silently changes the score | No task lever. Method: size every lever on Kaggle-L4-faithful paired runs, not the pod. |
| 16 | Devstral tool calling breaks across vLLM versions | No task lever. Pin the environment and run a canary task per batch. |
| 17 | Time limits against the 12 h sequential budget | HANG (time discipline); also the budget that REPRO, GATE and RETRY must fit inside. |
| 18 | Patch selection from several candidates | RETRY (conditional, gate-triggered) with GATE as a veto; not best-of-k. |

Primary lever per sweep item: EDIT 7, CONTEXT 2, TOOLDECL 1, GATE 1, NONEMPTY 1, REPRO 1, TERSE 1, HANG 1, RETRY 1, no task lever 2. Every catalogue item in `research/pain_points.md` section 2:

| id | problem | lever(s) it supports |
|---|---|---|
| A1 | round-bracket calls swallow the rest of the turn | EDIT (short single-string calls), NONEMPTY |
| A2 | bare or malformed openers silently dropped | EDIT (no prose before a call), NONEMPTY |
| A3 | offline-parser quote truncation | none: not our parser path |
| A4 | parser state shared across concurrent requests | none for sequential scoring; eval fidelity for 2-per-GPU pod runs |
| A5 | JSON quoting / wrong or missing delimiter inside <\|"\|> | EDIT (one code-bearing argument, sorted last) |
| A6 | integer args arriving as strings | none: measured 3/552 |
| A7 | no constrained decoding; tool_choice not enforced | EDIT, NONEMPTY |
| A8 | thinking-on parser gaps | none while thinking stays off |
| A9 | tool call cut at the output cap | CONTEXT (output cap ~1,536); at most 9 capped responses per run |
| A10 | several calls in one response | none: 0-18 multi-call steps per run, no duplicates |
| A11 | parser-loss share depends on the stack, landed share does not | EDIT (fix both channels); size levers on L4 |
| B1 | literal escapes in old_string | EDIT (unescape-on-failure) |
| B2 | whitespace/indent mismatch loops | EDIT (harness tiers exist; guarded line-range mode) |
| B3 | hallucinated old_string repeated; line-number tool removes it | EDIT (numbered lines, loop breaker) |
| B4 | empty old_string overwrites the file | EDIT (refuse empty anchor) |
| B5 | str_replace editor beats generic tools | EDIT |
| B6 | blank lines left / final newline lost | EDIT (whole-line semantics) |
| B7 | lossy UTF-8 decode rewrites untouched bytes | EDIT (bytes I/O; 0/9,295 local files affected) |
| B8 | our edit success vs other harnesses | EDIT (context for the size of the gap) |
| B9 | fuzzy matcher chains need guards and honest errors | EDIT (copy opencode's order and guards) |
| B10 | line-ending normalization | EDIT (newline='') |
| C1 | identical call repeated N times | EDIT (loop breaker), RETRY |
| C2 | deterministic sampling -> verbatim retries | RETRY, EDIT (we already run temperature 1.0) |
| C3 | format errors handled badly make loops worse | EDIT (errors name the alternative), NONEMPTY |
| C4 | degenerate thought loops | none while thinking stays off |
| C5 | a prose turn ends the run | NONEMPTY |
| D1 | 32k window fills after ~20 full tool outputs | CONTEXT |
| D2 | orphaned function calls block compaction | CONTEXT |
| D3 | tiny default contexts | none: we have 32k |
| D4 | partial reads -> hallucinated findings | REPRO, RUNTIME |
| E1 | thoughts re-sent as history | CONTEXT (include_thoughts false) |
| E2 | unbounded thinking | CONTEXT (output cap) |
| E3 | reasoning/tool text leaks | none: rare with thinking off |
| E4 | thinking changes near the end of the window | none while thinking stays off |
| F1 | stops without a call / 'please provide the problem' | NONEMPTY |
| F2 | system-prompt non-adherence past ~10k tokens | CONTEXT (short prompts; rules in helper error messages) |
| F3 | schema discipline drifts after 20-50 calls | CONTEXT (fresh context per stage), GATE |
| F4 | model does not believe tool results (wrong role) | none: the June template renders role tool natively |
| F5 | training-time beliefs over evidence | RUNTIME (print the real object; date line in the prompt) |
| F6 | hallucinated tool calls when no schema is attached | TOOLDECL (tool-less stages get include_contents none) |
| F7 | undeclared tool -> ValueError -> task lost | TOOLDECL |
| F8 | required parameter dropped by small models | EDIT (one required input per helper) |
| G1 | agent never runs tests | REPRO, GATE |
| G2 | tests or repros hang | HANG (killpg timeout), GATE |
| G3 | env differences make gold fail | eval fidelity (see rich_3782 flake, fastapi_14851 passing at base) |
| G4 | success after changing nothing or only tests | NONEMPTY |
| G5 | gate reads output, not the exit code | GATE |
| G6 | green suite does not separate the fix from a near-miss | REPRO, SIBLING |
| H1 | scratch files in the patch | HYGIENE |
| H2 | test edits break test_patch | HYGIENE |
| H3 | padded diffs, unrelated files | HYGIENE, GATE (diff --stat tied to the statement) |
| I1 | one sample is noisy; selection needs a verifier | RETRY, GATE (veto only) |
| I2 | fail fast and restart | RETRY |
| J1 | per-task caps vs the 12 h cap | HANG; the budget REPRO/GATE/RETRY must fit |
| J2 | slow decoding: every saved call buys exploration | EDIT (fewer wasted calls) |
| J3 | exploration spends the shared call budget | HANG (land a candidate by mid-budget) |
| K1 | June template tool-calling bugs | EDIT ('no prose before a call'); eval fidelity |
| K2 | alphabetical parameter order | EDIT (single-string helper makes order irrelevant) |
| L1 | too many tools; graph tools save tokens not accuracy | EDIT, CONTEXT, TOOLDECL, TERSE |
| L2 | malformed JSON needs repair | EDIT (helpers tolerate escaped input) |
| L3 | AgentTool returns '' when the sub-agent ends on a call | TOOLDECL (stage design); none unless AgentTool is adopted |
| M | multi-line Python in bash; observation collapsing | REPRO (repros in files), CONTEXT |
| N1 | Qwen2.5-Coder never trained on its advertised tool tokens | EDIT (use the shape the model gets right) |
| N2 | server quantization/context/output caps change scores | eval fidelity (size levers on L4) |
| N3 | Devstral parser breaks across vLLM versions | eval fidelity (pins, canary) |
| N4 | Llama: no new reports | none |
| Section 1 | hidden set from private repos, PR-text statements, screened for hidden specs | down-weights CONVENTION and hidden-spec tasks; REPRO must derive the repro; TERSE transfers |

## 5. Infeasible for a 5-minute 31B agent

10 tasks are marked infeasible in their records. Every one is a hidden-spec task: the hidden test pins a name, message or rendering that the statement does not give, and no run of any config solved one. The host says tasks like these were screened out of the hidden set, so effort spent on them buys nothing there. The right agent behaviour is to triage early, submit the cheapest plausible change and move on.

| task | why it is infeasible | gold size |
|---|---|---|
| fastapi_14258 | Guard is easy; the hidden test matches the exact merged AssertionError message. | 1f/1h/4l |
| fastapi_14479 | The hidden test matches the reviewer-edited wording; the statement shows only the pre-review draft. | 1f/1h/1l |
| fastapi_14487 | Exact 'Validation errors:' / 'Field: <loc>' output strings appear nowhere in the statement. | 1f/1h/7l |
| fastapi_15280 | April Fool's PR; the raise and its message exist only in the hidden test. | 2f/3h/72l |
| fastapi_15661 | Empty PR template; tests import scripts.prepare_release and its CLI names. | 1f/1h/216l |
| fastapi_15800 | 654-line feature with hidden kwargs (fallback, check_dir), internals and docs_src examples. | 8f/20h/654l |
| rich_3105 | 'Fix #3104' only; the exact inline-style string is not derivable. | 1f/1h/2l |
| rich_3930 | 12,714-line grapheme feature; tests import CellSpan and rich._unicode_data. | 6f/29h/12714l |
| rich_3938 | Tests call a new Segment.split_lines_terminator helper by name. | 2f/2h/45l |
| rich_3942 | Maintainer restyle by taste; golden ANSI snapshots are the only spec. | 2f/7h/70l |

Near-infeasible in 5 minutes (marked hard, never solved by any of the 14 runs): fastapi_14306, fastapi_14448, rich_3061, rich_3944, rich_4076. fastapi_14448 needs seven wrapper layers plus a consumer in another file; fastapi_14306 and rich_3061 need a hidden kwarg or public helper plus an exact rendering; rich_3944 and rich_4076 need the text of an issue the agent cannot read. Budget them like the infeasible set unless a lever surfaces the fix early.

## Method and caveats

- Outcomes are the Kaggle-env labels in `_inputs.json` (rescore of the fair pod patches; empty patches were not rescored). 'Other runs' come from `eval/race1/runs/*/task_results.jsonl` (pod with the Kaggle pins, faithful 5 min / 70 calls budget) and `eval/kaggle/e74_v{2,3}/results.jsonl` (bundles v2/v3 on Kaggle 4xL4).
- Trace mechanics: an edit_file call is rejected when its observation says 'mandatory input param', and not-found when it says 'not found'. Overflow and timeout come from the `task_results.jsonl` errors. 'No source change' means the patch touches no file outside tests/, root-level test_/repro/verify scripts and docs/config. Code: `research/catalog_build/mech.py`.
- Tiers are judgement calls from each task's record and trace, stated per task in section 4. The 0.7/0.35 priors and the transfer weights are assumptions, not measurements. The controlled test is the v10 race; gap_6 sizes how many replicates it needs to detect +3 to +5.
- Only public tasks are here. The hidden set comes from private repos, so any lever tuned to fastapi/rich specifics is excluded from the ranking on purpose.
