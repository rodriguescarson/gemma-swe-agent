# Task catalog: the 74 Kaggle-valid public tasks

Written 2026-09-28. Sources: `research/tasks/*.json` (one record per task; 73 from the parallel workflow, `rich_3782` written in this step because the workflow stalled on it), `research/tasks/_inputs.json` (Kaggle-env pass per config), trace mechanics from `eval/eval3/eval/runs/p_v{4,6,7,8}/traces` and `task_results.jsonl`, and the pain-point sweep in `research/pain_points.md`. Machine-readable version: `research/task_catalog.json` (74 records, every field below plus per-config trace mechanics).

**Where we stand.** v4 solves 27/74 in the Kaggle env; the union of v4/v6/v7/v8 solves 35/74. v4 scored **0.12** on the public leaderboard (about 58 hidden tasks) against 0.36 on these public tasks, so the hidden set is roughly 3x harder for this agent. The target is 0.30 on the hidden set. The host says the hidden tasks were screened so that a failing test is 'something it could have gotten correct with the information given'. That makes the mechanics and verification levers below worth more on the hidden set than levers that guess hidden names.

**One label is disputed.** `rich_3782` v7 is scored FAIL by the Kaggle rescore (`eval/kaggle/rescore_fair`, exit 1), but on the task snapshot with Pygments 2.20.0 (the Kaggle kernel's pin) and Python 3.12 its patch passes `tests/test_syntax.py` 25/25 and the full rich suite 853/853, identical to gold. Rerun it in the Kaggle env with test output captured before trusting the other FAIL labels blindly. Pod-env labels that differ from Kaggle (python-multipart missing, Pygments skew) are already overridden by the Kaggle result in every record.

Contents: [1. All tasks](#1-all-tasks) · [2. Counts](#2-counts) · [3. Solution patterns](#3-recurring-solution-patterns) · [4. Levers](#4-ranked-generalizable-levers) · [5. Infeasible](#5-infeasible-for-a-5-minute-31b-agent)

## 1. All tasks

Gold size is files/hunks/lines changed. Outcome lists the configs that pass in the Kaggle env. Failure mode and difficulty come from the per-task record (`solved_by_*` means no config-wide failure mode).

| id | PR | kind | reveals fix | gold | passes (Kaggle) | failure mode | difficulty | best solution (one line) |
|---|---|---|---|---|---|---|---|---|
| fastapi_5077 | [#5077](https://github.com/fastapi/fastapi/pull/5077) | bugfix | partial | 1f/2h/6l | none | partial_fix | easy | inspect.unwrap(call) before reading __globals__ in BOTH get_typed_signature and get_typed_return_annotation. |
| fastapi_5624 | [#5624](https://github.com/fastapi/fastapi/pull/5624) | bugfix | none | 1f/1h/4l | v8 | solved_by_some | medium | Copy the scopes list before extending it (`list(security_scopes or []) + scopes`) in get_dependant. |
| fastapi_9425 | [#9425](https://github.com/fastapi/fastapi/pull/9425) | bugfix | full | 1f/1h/2l | v4 v6 v7 | solved_by_some | easy | In get_typed_annotation map an evaluated stringified "None" (type(None)) back to None. |
| fastapi_9555 | [#9555](https://github.com/fastapi/fastapi/pull/9555) | bugfix | full | 1f/1h/22l | all 4 | solved_by_all | easy | Add _unwrapped_call = inspect.unwrap(self.call) and use it in all three Dependant is_*_callable properties. |
| fastapi_9753 | [#9753](https://github.com/fastapi/fastapi/pull/9753) | feature | partial | 1f/2h/7l | v4 v8 | solved_by_some | easy | Strip functools.partial layers in Dependant._unwrapped_call after inspect.unwrap. |
| fastapi_11194 | [#11194](https://github.com/fastapi/fastapi/pull/11194) | bugfix | partial | 1f/1h/7l | v6 v7 | solved_by_some | easy | Use each field's own field_info (not the hoisted body_fields[0]) in both File-to-bytes branches of _extract_form_body. |
| fastapi_13537 | [#13537](https://github.com/fastapi/fastapi/pull/13537) | bugfix | full | 1f/1h/3l | v4 v6 v8 | solved_by_some | easy | Build the complement-loop skip set from declared field aliases, not from the output dict, so skipped None values are not re-added as raw "". |
| fastapi_13920 | [#13920](https://github.com/fastapi/fastapi/pull/13920) | feature | partial | 1f/2h/4l | none | wrong_location | easy | Unwrap TypeAliasType (typing_inspection is_typealiastype) once at the top of analyze_param, before the Annotated metadata scan. |
| fastapi_14077 | [#14077](https://github.com/fastapi/fastapi/pull/14077) | refactor | full | 3f/6h/11l | v4 v6 v7 | edit_tool_failure | easy | Replace every use of the renamed Starlette 422 constant with the literal 422; grep until no use of the old name remains. |
| fastapi_14258 | [#14258](https://github.com/fastapi/fastapi/pull/14258) | feature | partial | 1f/1h/4l | none | hidden_spec | infeasible | First statement of include_router: `assert self is not router, "Cannot include the same APIRouter instance into itself. ..."` (assert, like its neighbours). |
| fastapi_14301 | [#14301](https://github.com/fastapi/fastapi/pull/14301) | bugfix | full | 1f/1h/5l | all 4 | solved_by_all | easy | Pass scope=depends.scope into get_dependant from get_parameterless_sub_dependant. |
| fastapi_14306 | [#14306](https://github.com/fastapi/fastapi/pull/14306) | feature | partial | 2f/12h/137l | none | hidden_spec | hard | Add an endpoint_ctx (TypedDict) kwarg to the ValidationException family, a singular/plural __str__ in the base, and pass the context from routing. |
| fastapi_14372 | [#14372](https://github.com/fastapi/fastapi/pull/14372) | bugfix | partial | 2f/3h/7l | all 4 | solved_by_all | easy | @dataclass(frozen=True) on Depends and Security (and replace the in-place `depends.dependency =` with dataclasses.replace). |
| fastapi_14419 | [#14419](https://github.com/fastapi/fastapi/pull/14419) | bugfix | partial | 2f/7h/62l | none | partial_fix | medium | Keep scopes in Dependant.cache_key only when the dependant or any sub-dependant (transitive, memoized) uses SecurityScopes. |
| fastapi_14448 | [#14448](https://github.com/fastapi/fastapi/pull/14448) | bugfix | partial | 2f/3h/106l | none | partial_fix | hard | Classify async/generator at every wrapper layer (partial, __wrapped__, instance, __call__, decorated __call__); prefer the async-gen path in _solve_generator. |
| fastapi_14458 | [#14458](https://github.com/fastapi/fastapi/pull/14458) | bugfix | full | 1f/4h/7l | all 4 | solved_by_all | easy | `if inspect.isclass(_unwrapped_call(self.call)): return False` in all three is_*_callable properties, before the __call__ fallback. |
| fastapi_14463 | [#14463](https://github.com/fastapi/fastapi/pull/14463) | bugfix | full | 1f/2h/3l | all 4 | solved_by_all | easy | copy.deepcopy (not dict.copy) the per-route additional response in get_openapi_path. |
| fastapi_14479 | [#14479](https://github.com/fastapi/fastapi/pull/14479) | bugfix | partial | 1f/1h/1l | none | hidden_spec | infeasible | Message on the bare Query assert: f"Query parameter {param_name!r} must be one of the supported types" (the merged wording, not the PR draft). |
| fastapi_14487 | [#14487](https://github.com/fastapi/fastapi/pull/14487) | tooling_or_docs | partial | 1f/1h/7l | none | hidden_spec | infeasible | Docs example returns "Validation errors:" plus one "Field: {loc}, Error: {msg}" line per exc.errors() entry instead of str(exc). |
| fastapi_14492 | [#14492](https://github.com/fastapi/fastapi/pull/14492) | tooling_or_docs | full | 1f/1h/1l | all 4 | solved_by_all | easy | Replace "identifier": "MIT" with "Apache-2.0" in the one docs_src example. |
| fastapi_14616 | [#14616](https://github.com/fastapi/fastapi/pull/14616) | bugfix | partial | 1f/2h/15l | none | wrong_semantics | medium | In _get_multidict_value skip getlist when any field_info.metadata item is a Json() instance (`type(item) is Json`). |
| fastapi_14786 | [#14786](https://github.com/fastapi/fastapi/pull/14786) | bugfix | full | 1f/1h/2l | all 4 | solved_by_all | easy | `return scheme, param.strip()` in get_authorization_scheme_param. |
| fastapi_14794 | [#14794](https://github.com/fastapi/fastapi/pull/14794) | bugfix | full | 1f/2h/5l | all 4 | solved_by_all | easy | Add `depends is None and` to analyze_param's special-type branch and delete the assert. |
| fastapi_14851 | [#14851](https://github.com/fastapi/fastapi/pull/14851) | refactor | partial | 1f/6h/157l | v7 | solved_by_some | hard | Re-implement on_startup/on_shutdown lists, add_event_handler, _DefaultLifespan and generator-lifespan wrapping in APIRouter instead of inheriting them from Starlette. |
| fastapi_14873 | [#14873](https://github.com/fastapi/fastapi/pull/14873) | bugfix | full | 1f/2h/21l | all 4 | solved_by_all | easy | Move the on_startup/on_shutdown assignments to after super().__init__() in APIRouter.__init__. |
| fastapi_14986 | [#14986](https://github.com/fastapi/fastapi/pull/14986) | bugfix | partial | 2f/4h/34l | none | wrong_semantics | medium | Never mutate self.servers: add root_path per response on a copy of the cached schema; escape swagger params and initOAuth JSON through one helper. |
| fastapi_15280 | [#15280](https://github.com/fastapi/fastapi/pull/15280) | feature | none | 2f/3h/72l | none | hidden_spec | infeasible | FastAPI.vibe(path, *, prompt='') that raises FastAPIError("Are you kidding me? Happy April Fool's"). |
| fastapi_15588 | [#15588](https://github.com/fastapi/fastapi/pull/15588) | feature | partial | 1f/2h/23l | none | hidden_spec | medium | AfterValidator on event and id raising ValueError(f"SSE '{field}' must be a single line") for \r or \n. |
| fastapi_15589 | [#15589](https://github.com/fastapi/fastapi/pull/15589) | bugfix | none | 1f/1h/4l | v4 v7 | solved_by_some | medium | Also add get_validation_alias(field) to processed_keys so the raw underscore header is not re-added as an extra. |
| fastapi_15661 | [#15661](https://github.com/fastapi/fastapi/pull/15661) | tooling_or_docs | none | 1f/1h/216l | none | hidden_spec | infeasible | New scripts/prepare_release.py Typer app (bump version, update release notes) built from pure content->str functions, plus the workflows. |
| fastapi_15800 | [#15800](https://github.com/fastapi/fastapi/pull/15800) | feature | partial | 8f/20h/654l | none | hidden_spec | infeasible | New APIRouter/FastAPI.frontend(path, *, directory, fallback, check_dir) serving an SPA build as low-priority routes, with docs_src examples. |
| requests_6644 | [#6644](https://github.com/psf/requests/pull/6644) | bugfix | partial | 1f/1h/3l | all 4 | solved_by_all | easy | In HTTPAdapter.request_url collapse a leading '//' in path_url to '/' before urlopen. |
| rich_2725 | [#2725](https://github.com/Textualize/rich/pull/2725) | bugfix | partial | 1f/1h/10l | all 4 | solved_by_all | easy | Reorder box_segments to (head, mid, foot) to match the `0 if first else (2 if last else 1)` index. |
| rich_2943 | [#2943](https://github.com/Textualize/rich/pull/2943) | bugfix | partial | 1f/1h/2l | all 4 | solved_by_all | easy | `style._hash = None` (not a copy) in Style.clear_meta_and_links. |
| rich_3006 | [#3006](https://github.com/Textualize/rich/pull/3006) | bugfix | full | 1f/1h/2l | all 4 | solved_by_all | easy | `param.default is param.empty` (identity, not ==) in auto_rich_repr. |
| rich_3043 | [#3043](https://github.com/Textualize/rich/pull/3043) | bugfix | partial | 1f/2h/2l | none | wrong_semantics | easy | Move `<html>` to directly after `<!DOCTYPE html>` in CONSOLE_HTML_FORMAT; touch nothing else in the file. |
| rich_3052 | [#3052](https://github.com/Textualize/rich/pull/3052) | feature | partial | 1f/12h/34l | none | edit_tool_failure | easy | case_sensitive=True kwarg threaded through PromptBase and every ask overload; lower-case compare in check_choice; return the canonical choice. |
| rich_3061 | [#3061](https://github.com/Textualize/rich/pull/3061) | bugfix | partial | 1f/13h/91l | none | hidden_spec | infeasible | Rewrite Text.expand_tabs to extend the tab's spans over inserted spaces with cell-width tab stops; add Text.extend_style; drop empty-style spans. |
| rich_3063 | [#3063](https://github.com/Textualize/rich/pull/3063) | bugfix | partial | 1f/2h/4l | v4 | solved_by_some | easy | In markup.escape, double a lone trailing backslash. |
| rich_3067 | [#3067](https://github.com/Textualize/rich/pull/3067) | bugfix | full | 1f/1h/2l | all 4 | solved_by_all | easy | Add '~' to ReprHighlighter's URL character class. |
| rich_3105 | [#3105](https://github.com/Textualize/rich/pull/3105) | bugfix | none | 1f/1h/2l | none | hidden_spec | infeasible | `<code style="font-family:inherit">` in CONSOLE_HTML_FORMAT. |
| rich_3180 | [#3180](https://github.com/Textualize/rich/pull/3180) | bugfix | partial | 2f/4h/127l | none | broke_tests | medium | Make chop_cells iterate left to right (no reversed()) and leave the divide_line call site alone. |
| rich_3278 | [#3278](https://github.com/Textualize/rich/pull/3278) | bugfix | full | 1f/1h/1l | none | empty_or_timeout | easy | Prepend `(?:\x1b[0-?])` as a new alternative to re_ansi so Fp private escapes are consumed. |
| rich_3454 | [#3454](https://github.com/Textualize/rich/pull/3454) | bugfix | full | 1f/1h/2l | v8 | solved_by_some | easy | Add '@' to ReprHighlighter's URL character class (and do not touch tests/test_highlighter.py). |
| rich_3468 | [#3468](https://github.com/Textualize/rich/pull/3468) | bugfix | none | 1f/4h/42l | none | hidden_spec | medium | Catch BrokenPipeError around write+flush, dup2 devnull onto stdout and exit(1) (CPython SIGPIPE recipe) via a Console.on_broken_pipe hook. |
| rich_3470 | [#3470](https://github.com/Textualize/rich/pull/3470) | bugfix | none | 1f/1h/2l | none | hidden_spec | hard | Record only on a real flush: `if self.record and not self._buffer_index:` in Console._write_buffer. |
| rich_3471 | [#3471](https://github.com/Textualize/rich/pull/3471) | bugfix | none | 1f/1h/1l | none | hidden_spec | medium | strip_control_codes(content) inside Text.append_tokens, as __init__ and append already do. |
| rich_3472 | [#3472](https://github.com/Textualize/rich/pull/3472) | bugfix | none | 1f/1h/4l | none | wrong_semantics | easy | Skip dataclass fields the instance lacks (`hasattr(obj, field.name)`) in pretty.traverse. |
| rich_3480 | [#3480](https://github.com/Textualize/rich/pull/3480) | bugfix | partial | 1f/2h/4l | none | partial_fix | easy | Iterate a snapshot of text._spans in BOTH Text.append and Text.append_text. |
| rich_3506 | [#3506](https://github.com/Textualize/rich/pull/3506) | bugfix | partial | 1f/1h/17l | v4 v6 v7 | solved_by_some | easy | Make _split_cells' start guess an under-estimate (or start at 0) so the forward scan never starts past the cut. |
| rich_3518 | [#3518](https://github.com/Textualize/rich/pull/3518) | bugfix | full | 1f/1h/1l | v4 v6 v7 | solved_by_some | easy | Column(_index=index, highlight=self.highlight) for columns auto-created in add_row. |
| rich_3521 | [#3521](https://github.com/Textualize/rich/pull/3521) | bugfix | none | 1f/1h/35l | v6 | solved_by_some | medium | Make Segment._split_cells search two-way from the proportional guess (or scan from 0). |
| rich_3535 | [#3535](https://github.com/Textualize/rich/pull/3535) | bugfix | partial | 2f/2h/8l | none | hidden_spec | hard | Fix _is_single_cell_widths: end ASCII at U+007E, restore the U+00A0-U+02FF range hyphen, add box drawing U+2500-U+25FF. |
| rich_3675 | [#3675](https://github.com/Textualize/rich/pull/3675) | feature | none | 2f/5h/41l | none | hidden_spec | medium | TTY_COMPATIBLE tri-state in Console.is_terminal: '1' True, '0' False, anything else falls through to detection. |
| rich_3676 | [#3676](https://github.com/Textualize/rich/pull/3676) | feature | partial | 2f/8h/14l | v4 v6 | solved_by_some | easy | Stack.notes = list(getattr(exc_value, '__notes__', [])), rendered after the exception value. |
| rich_3718 | [#3718](https://github.com/Textualize/rich/pull/3718) | bugfix | partial | 1f/3h/7l | v4 v6 v8 | solved_by_some | easy | Revert 7a38204: stylize the panel title/subtitle with the combined border_style. |
| rich_3772 | [#3772](https://github.com/Textualize/rich/pull/3772) | bugfix | none | 1f/6h/47l | none | wrong_semantics | medium | Cycle guards in Traceback.extract: stop on an already-seen __cause__/__context__ and keep a visited set for exception-group members. |
| rich_3777 | [#3777](https://github.com/Textualize/rich/pull/3777) | feature | partial | 2f/3h/13l | v7 | solved_by_some | easy | TTY_INTERACTIVE tri-state ('0' off, '1' on, else auto) read from self._environ before the is_interactive expression. |
| rich_3782 | [#3782](https://github.com/Textualize/rich/pull/3782) | bugfix | none | 1f/7h/29l | none | empty_or_timeout (label disputed) | medium | Subtract horizontal padding from the auto code_width in Syntax._get_syntax and clamp it at 0. |
| rich_3882 | [#3882](https://github.com/Textualize/rich/pull/3882) | bugfix | full | 1f/1h/2l | v4 v7 v8 | solved_by_some | easy | self.console.print(error, markup=True) in PromptBase.on_validate_error. |
| rich_3894 | [#3894](https://github.com/Textualize/rich/pull/3894) | bugfix | full | 1f/1h/4l | v4 v7 | broke_tests | easy | Keep `name or __qualname__` and add a type guard falling back to __name__ when qualname is not a str. |
| rich_3905 | [#3905](https://github.com/Textualize/rich/pull/3905) | bugfix | full | 1f/1h/7l | all 4 | solved_by_all | easy | Wrap all of Progress.stop() in `if not self.disable:`. |
| rich_3930 | [#3930](https://github.com/Textualize/rich/pull/3930) | feature | partial | 6f/29h/12714l | none | hidden_spec | infeasible | Grapheme-aware cell widths: versioned rich._unicode_data tables, CellSpan/split_graphemes API, grapheme-safe chop_cells/set_cell_size. |
| rich_3934 | [#3934](https://github.com/Textualize/rich/pull/3934) | bugfix | none | 2f/3h/20l | none | hidden_spec | medium | Only write the stop() newline when the last render had height > 0 (LiveRender.last_render_height). |
| rich_3935 | [#3935](https://github.com/Textualize/rich/pull/3935) | bugfix | none | 1f/5h/16l | none | wrong_location | medium | Apply pad_edge in Table._get_padding_width exactly as the render path's get_padding does. |
| rich_3938 | [#3938](https://github.com/Textualize/rich/pull/3938) | bugfix | none | 2f/2h/45l | none | hidden_spec | infeasible | Add Segment.split_lines_terminator and style each line's text but not its newline in the soft_wrap branch. |
| rich_3942 | [#3942](https://github.com/Textualize/rich/pull/3942) | feature | none | 2f/7h/70l | none | hidden_spec | infeasible | Maintainer restyle of Markdown headings, hr and tables (golden ANSI snapshots). |
| rich_3944 | [#3944](https://github.com/Textualize/rich/pull/3944) | bugfix | none | 1f/1h/2l | none | wrong_location | hard | Return 1 (not 0) for codepoints beyond the width table in get_character_cell_size. |
| rich_3953 | [#3953](https://github.com/Textualize/rich/pull/3953) | bugfix | none | 1f/2h/26l | none | partial_fix | medium | Zero width for C0/C1 control characters in get_character_cell_size, and make the ZWJ next() safe at end of string. |
| rich_4006 | [#4006](https://github.com/Textualize/rich/pull/4006) | bugfix | partial | 1f/2h/45l | none | broke_tests | medium | Guarantee every split_graphemes branch advances and emits zero-width spans for leading ZWJ/VS16/zero-width chars; keep the ZWJ `+= 2`. |
| rich_4075 | [#4075](https://github.com/Textualize/rich/pull/4075) | bugfix | partial | 1f/4h/15l | none | wrong_semantics | medium | `objects = (NewLine(),) if end == "\n" else ("",)` when Console.print gets no objects. |
| rich_4076 | [#4076](https://github.com/Textualize/rich/pull/4076) | bugfix | none | 1f/1h/6l | none | wrong_location | hard | re.split(r"(?<=\n)") instead of splitlines() in AnsiDecoder.decode so a trailing newline survives. |
| rich_4077 | [#4077](https://github.com/Textualize/rich/pull/4077) | bugfix | partial | 1f/1h/3l | v8 | wrong_location | easy | Add FileProxy.isatty delegating to the wrapped file. |
| rich_4079 | [#4079](https://github.com/Textualize/rich/pull/4079) | bugfix | none | 1f/1h/7l | v6 v7 | solved_by_some | easy | In TableDataElement.on_text, style only plain str chunks; append pre-styled Text untouched. |

## 2. Counts

Repos: Textualize/rich 42, fastapi/fastapi 31, psf/requests 1.

**By kind**

| value | tasks | v4 solves | any config solves |
|---|---|---|---|
| bugfix | 56 | 23/56 | 29/56 |
| feature | 13 | 2/13 | 3/13 |
| tooling_or_docs | 3 | 1/3 | 1/3 |
| refactor | 2 | 1/2 | 2/2 |

**By statement_reveals_fix**

| value | tasks | v4 solves | any config solves |
|---|---|---|---|
| partial | 34 | 9/34 | 13/34 |
| none | 21 | 1/21 | 4/21 |
| full | 19 | 17/19 | 18/19 |

**By failure mode**

| value | tasks | v4 solves | any config solves |
|---|---|---|---|
| hidden_spec | 19 | 0/19 | 0/19 |
| solved_by_some | 17 | 10/17 | 17/17 |
| solved_by_all | 15 | 15/15 | 15/15 |
| wrong_semantics | 6 | 0/6 | 0/6 |
| partial_fix | 5 | 0/5 | 0/5 |
| wrong_location | 5 | 0/5 | 1/5 |
| broke_tests | 3 | 1/3 | 1/3 |
| edit_tool_failure | 2 | 1/2 | 1/2 |
| empty_or_timeout | 2 | 0/2 | 0/2 |

**By 5-minute difficulty**

| value | tasks | v4 solves | any config solves |
|---|---|---|---|
| easy | 38 | 26/38 | 31/38 |
| medium | 18 | 1/18 | 3/18 |
| infeasible | 11 | 0/11 | 0/11 |
| hard | 7 | 0/7 | 1/7 |

**By tag (a task carries several)**

| value | tasks | v4 solves | any config solves |
|---|---|---|---|
| existing_tests_cover_area | 64 | 27/64 | 34/64 |
| statement_is_pr_description | 57 | 26/57 | 30/57 |
| edge_case_logic | 49 | 17/49 | 21/49 |
| single_function_fix | 46 | 21/46 | 27/46 |
| repro_easy_from_statement | 41 | 25/41 | 29/41 |
| test_reveals_hidden_spec | 37 | 5/37 | 7/37 |
| needs_linked_issue_text | 28 | 1/28 | 5/28 |
| exact_string_or_format_required | 28 | 5/28 | 7/28 |
| title_plus_link_only | 27 | 3/27 | 7/27 |
| multi_hunk_same_file | 20 | 5/20 | 6/20 |
| rendering_or_ansi_output | 19 | 5/19 | 6/19 |
| new_function_or_param | 18 | 1/18 | 3/18 |
| statement_names_fix_location | 16 | 12/16 | 13/16 |
| multi_file | 16 | 3/16 | 4/16 |
| statement_names_new_api | 6 | 0/6 | 1/6 |
| performance_or_hang | 6 | 0/6 | 0/6 |
| typing_or_signature_change | 5 | 1/5 | 1/5 |
| async_code | 5 | 2/5 | 3/5 |
| env_sensitive_test | 5 | 1/5 | 3/5 |
| large_feature | 5 | 0/5 | 1/5 |
| regex_change | 4 | 1/4 | 2/4 |
| docs_or_tooling_only | 3 | 1/3 | 1/3 |
| pydantic_or_validation | 2 | 0/2 | 0/2 |
| cli_or_script | 2 | 0/2 | 0/2 |

**Cross-tab: failure mode x statement_reveals_fix**

| failure mode | full | partial | none | total |
|---|---|---|---|---|
| hidden_spec | 0 | 9 | 10 | 19 |
| solved_by_some | 5 | 8 | 4 | 17 |
| solved_by_all | 11 | 4 | 0 | 15 |
| wrong_semantics | 0 | 4 | 2 | 6 |
| partial_fix | 0 | 4 | 1 | 5 |
| wrong_location | 0 | 2 | 3 | 5 |
| broke_tests | 1 | 2 | 0 | 3 |
| edit_tool_failure | 1 | 1 | 0 | 2 |
| empty_or_timeout | 1 | 0 | 1 | 2 |
| **total** | 19 | 34 | 21 | 74 |

What the cross-tab says: when the statement contains the fix, v4 solves 17/19, and both misses (rich_3278, rich_3454) are regex edits full of escape characters that died in the edit-parse loop, not reasoning failures. When the statement reveals nothing, v4 solves 1/21 (any config 4/21). Those 21 break down as hidden_spec 10, solved_by_some 4, wrong_location 3, wrong_semantics 2, empty_or_timeout 1, partial_fix 1. Partial statements sit in between: v4 9/34. No config solved any of the 19 hidden_spec tasks, whatever the statement revealed.

**Measured v4 blockers, unsolved vs solved (control).** From the pod traces. This is an association, not a controlled result.

| signal (v4 run) | 47 unsolved | 27 solved |
|---|---|---|
| no change to any non-test source file | 20 | 0 |
| ended in ContextWindowExceededError | 7 | 0 |
| hit the 6-min session or turn budget | 6 | 1 |
| >= 10 rejected or not-found edit_file calls | 8 | 2 |
| never ran pytest | 23 | 8 |
| patch touches tests/ | 5 | 1 |
| patch includes scratch files | 15 | 2 |

## 3. Recurring solution patterns

A task can match several patterns. 'v4' is how many of the listed tasks v4 solves.

**P1. PR description already contains the fix (names the function and the change)** (v4 17/19, any config 18/19)

Move: Transcribe it at the named spot; grep the quoted expression; change nothing else.

Tasks: `fastapi_9425`, `fastapi_9555`, `fastapi_13537`, `fastapi_14077`, `fastapi_14301`, `fastapi_14458`, `fastapi_14463`, `fastapi_14492`, `fastapi_14786`, `fastapi_14794`, `fastapi_14873`, `rich_3006`, `rich_3067`, `rich_3278`, `rich_3454`, `rich_3518`, `rich_3882`, `rich_3894`, `rich_3905`

**P2. Title plus a bare issue link; the spec lives in the linked issue the agent cannot read** (v4 3/27, any config 7/27)

Move: Decompose the title into code concepts, grep identifiers (not the issue number), reproduce the most literal reading, probe edge inputs.

Tasks: `fastapi_5624`, `fastapi_15280`, `fastapi_15661`, `fastapi_15800`, `rich_3063`, `rich_3067`, `rich_3105`, `rich_3468`, `rich_3470`, `rich_3471`, `rich_3472`, `rich_3480`, `rich_3521`, `rich_3675`, `rich_3676`, `rich_3772`, `rich_3782`, `rich_3934`, `rich_3935`, `rich_3938`, `rich_3942`, `rich_3944`, `rich_3953`, `rich_4006`, `rich_4076`, `rich_4077`, `rich_4079`

**P3. Hidden test asserts an exact error message or rendered string** (v4 1/14, any config 1/14)

Move: Copy the neighbouring message/format idiom character for character; reuse the statement's own words; never pin a guessed string in your own test.

Tasks: `fastapi_14258`, `fastapi_14479`, `fastapi_14487`, `fastapi_15588`, `fastapi_14306`, `fastapi_15280`, `rich_3043`, `rich_3105`, `rich_3942`, `rich_3934`, `rich_3938`, `rich_4075`, `rich_2725`, `rich_3782`

**P4. Hidden test imports a new public name the statement never spells out** (v4 0/7, any config 0/7)

Move: Rarely derivable. Name helpers after the nearest sibling (split_lines -> split_lines_<variant>) and put them where existing tests import from; cap effort.

Tasks: `fastapi_15661`, `fastapi_15800`, `fastapi_14306`, `fastapi_15280`, `rich_3930`, `rich_3938`, `rich_3061`

**P5. Statement names the new parameter / API / env var explicitly** (v4 1/7, any config 2/7)

Move: Implement exactly that name, keyword-only with safe defaults; copy a companion setting's full value semantics; thread it through every overload and factory.

Tasks: `fastapi_13920`, `fastapi_15280`, `fastapi_15800`, `rich_3052`, `rich_3675`, `rich_3676`, `rich_3777`

**P6. Fix belongs at the shared chokepoint every caller goes through** (v4 6/8, any config 6/8)

Move: Patch the one normalisation helper/entry point (not each caller, not a downstream helper you grepped first).

Tasks: `fastapi_14786`, `fastapi_9753`, `fastapi_9555`, `fastapi_14458`, `fastapi_14616`, `fastapi_13920`, `requests_6644`, `fastapi_14301`

**P7. Same defect at sibling sites (hidden test hits all of them)** (v4 3/9, any config 4/9)

Move: After the first fix, grep the package for the same expression/pattern and fix every sibling; treat each 'Fixes #N' as its own bug.

Tasks: `fastapi_5077`, `rich_3480`, `fastapi_11194`, `fastapi_14986`, `fastapi_9555`, `fastapi_14458`, `rich_3953`, `fastapi_14448`, `fastapi_14077`

**P8. Shared mutable state leaks (aliased list/dict mutated in place, dict used as output and as 'handled' marker)** (v4 4/8, any config 5/8)

Move: Copy at the point of sharing (list(x), deepcopy) or track handled keys in a separate set; do not delete the feature.

Tasks: `fastapi_5624`, `fastapi_14463`, `fastapi_14986`, `rich_3480`, `rich_3470`, `fastapi_13537`, `fastapi_15589`, `fastapi_14372`

**P9. Ordering / initialisation bug (build order vs index order, parent __init__ overwrites, value hoisted from items[0])** (v4 2/4, any config 3/4)

Move: Find where the thing is built and where it is consumed; fix the side that disagrees with the documented meaning.

Tasks: `fastapi_14873`, `fastapi_11194`, `rich_2725`, `rich_4075`

**P10. Wrapped callables and annotations misclassified (partial, @wraps, classes, proxies, type aliases, string annotations)** (v4 4/8, any config 5/8)

Move: Normalise every wrapper layer once, at the entry point, before classification; delegate explicitly when a base class shadows __getattr__.

Tasks: `fastapi_9555`, `fastapi_9753`, `fastapi_14448`, `fastapi_14458`, `fastapi_5077`, `fastapi_13920`, `fastapi_9425`, `rich_4077`

**P11. Two code paths compute the same quantity and disagree (measure vs render, sibling handler, start vs stop)** (v4 3/9, any config 5/9)

Move: Diff the two paths and make the broken one apply every flag/step the working one applies.

Tasks: `rich_3935`, `rich_3782`, `rich_3521`, `rich_3506`, `rich_3180`, `rich_4079`, `rich_3471`, `rich_3905`, `rich_3518`

**P12. Regex / character-class allow-list is missing characters** (v4 1/4, any config 2/4)

Move: Add only the missing range/char, keep existing literals (downstream code may compare the captured group), brute-force check against the slow path.

Tasks: `rich_3067`, `rich_3454`, `rich_3278`, `rich_3535`

**P13. Hang / infinite loop / recursion (loop branch that never advances, missing cycle guard, extend-while-iterating)** (v4 0/5, any config 0/5)

Move: Run every repro under `timeout`; find the branch with no progress or the unguarded attribute walk; add the advance or a visited-id set.

Tasks: `rich_4006`, `rich_3772`, `rich_3480`, `fastapi_14258`, `fastapi_14448`

**P14. Sentinel / identity / type-guard edge case** (v4 5/6, any config 5/6)

Move: Use `is` for sentinels, add a narrow guard after the original expression, invalidate caches rather than copying them.

Tasks: `rich_3006`, `rich_3894`, `rich_3472`, `fastapi_9425`, `rich_2943`, `rich_3063`

**P15. Byte-exact template or snapshot output** (v4 2/8, any config 3/8)

Move: Minimal edit following the neighbouring formatting; never touch other templates' `{{ }}` escapes or the leading `"""\`; render once and diff.

Tasks: `rich_3043`, `rich_3105`, `rich_3942`, `rich_2725`, `rich_3718`, `rich_3938`, `rich_3934`, `rich_4079`

**P16. Upstream dependency changed; behaviour the repo relies on is inherited from site-packages** (v4 2/3, any config 3/3)

Move: When grep finds no definition twice, read the installed base class source (inspect.getsource) and vendor what the repo needs.

Tasks: `fastapi_14851`, `fastapi_14077`, `fastapi_14873`

**P17. PR looks like docs/tooling but the tested artefact is runnable code** (v4 1/5, any config 1/5)

Move: Change the runnable example/module (docs_src/, scripts/) and read its existing test for the output shape; ignore incidental chores.

Tasks: `fastapi_14487`, `fastapi_14492`, `fastapi_15661`, `rich_4075`, `rich_3043`

## 4. Ranked generalizable levers

Each lever is sized on the 47 tasks v4 does not solve. **Likely** means the lever removes the blocker seen in the v4 trace and another config (or v4 itself) already had the right fix or location. **Possible** means the blocker is removed but a further step is uncertain. **Long shot** tasks are listed but not counted. The expected-flip column uses rough priors of 0.7 per likely and 0.35 per possible task; for the retry lever it uses the measured share of configs that solved each task times an assumed 0.7 gate detection rate. Levers overlap, so the counts do not add up.

| rank | lever | plausible flips (likely + possible) | expected flips | generalizes to unseen repos |
|---|---|---|---|---|
| 1 | Repro-must-flip check before submit | 10 (3 + 7) | 4.5 | high |
| 2 | Reliable edit channel plus mechanism-switching loop breaker | 5 (2 + 3) | 2.4 | high (same vLLM 0.19.1 parser on the scorer) |
| 3 | Regression and collection gate before submit | 6 (2 + 4) | 2.8 | high |
| 4 | Context budget guard plus dependency-source rule | 4 (2 + 2) | 2.1 | high |
| 5 | Sibling sweep after the first fix | 4 (2 + 2) | 2.1 | high |
| 6 | Gate-triggered second attempt in a fresh context | 8 (0 + 8) | 1.8 | high, but costs time |
| 7 | Localisation protocol for title-plus-link statements | 3 (1 + 2) | 1.4 | medium (hidden statements may carry more issue text) |
| 8 | Hang-safe execution plus termination heuristics | 3 (1 + 2) | 1.4 | high |
| 9 | Runtime ground truth instead of guessing library representations | 3 (1 + 2) | 1.4 | medium-high |
| 10 | Never submit an empty, test-only or 'no bug' patch | 2 (0 + 2) | 0.7 | high (floor, near-free) |
| 11 | Copy the repo's own conventions for new checks, messages and settings | 2 (0 + 2) | 0.7 | low-medium (hidden set screened for hidden specs) |
| 12 | Pre-submit patch hygiene | 1 (0 + 1) | 0.3 | high (free insurance) |

Ranking is by expected flips, adjusted for how well each lever transfers to unseen repos. One deliberate exception: EDIT is ranked above GATE although its public count is lower, for three reasons. Its failure rate is measured on the same vLLM 0.19.1 parser the scorer runs. The gate's feedback is useless if the fixer cannot land the follow-up edit. And it returns calls on every task: 810 of v4's 1,387 exact-repeat calls were edit_file retries.

### 1. Repro-must-flip check before submit

How: Write the statement's literal repro to a file (never a bash -c one-liner: backticks, $ and quotes break it) and run it under `timeout 60` at base and after the edit. It must misbehave at base and produce the exact expected output after (assert the string, not 'looks fine'). If it already passes at base, re-run it through the other input shapes (model vs scalar param, wrapped vs plain, empty vs None, both argument orders) before concluding anything; never submit 'no bug' for a bugfix title. For functions with an invariant (split at cut, round-trip decode, width sums), sweep every position/boundary input instead of one example. Ship as one gate script with the regression gate.

Evidence: 23 of the 47 unsolved v4 runs never ran pytest, against 8 of the 27 solved. Reported elsewhere: reproduction-test diagnosis adds 8.0 points in SWE-Doctor, and Agentless uses reproduction tests to rank patches.

- Likely: `rich_4075`, `rich_3521`, `rich_4079`
- Possible: `fastapi_11194`, `fastapi_13920`, `fastapi_14616`, `rich_3472`, `rich_3777`, `rich_3782`, `rich_3935`
- Long shot: `fastapi_14419`, `rich_3468`, `rich_3470`, `rich_3934`, `rich_4076`, `rich_3535`, `rich_3953`
- Pain points it answers: G1, D4, I1, I2, M (SWE-agent #1302)

### 2. Reliable edit channel plus mechanism-switching loop breaker

How: Forbid edit_file. Edit through run_command calling our helper: exact match, then unescape (\n \t \" \\ \uXXXX \x1b) and retry, then whitespace-flexible match, then line-range replace; preserve trailing newlines; after every edit run py_compile on the file and print a 3-line diff. Keep a hash of the last commands in $TMPDIR/swe/state and, on the second identical failure, return an error that names the alternative mechanism (line-range or a python rewrite).

Evidence: Across v4, 49% of edit_file calls were parse-rejected and only 13.6% changed a file (pain_points.md finding 1). 8 of the 47 unsolved v4 runs had 10 or more failed edits, against 2 of the 27 solved. Both misses among the 19 statements that give the fix away are escape-heavy regex edits that looped.

- Likely: `rich_3278`, `rich_3454`
- Possible: `fastapi_15588`, `rich_3043`, `rich_3052`
- Long shot: `rich_3535`, `rich_3944`
- Pain points it answers: A1, A2, A5, B1, B2, B3, B4, C1, C2, K2, L1, L2, J2

### 3. Regression and collection gate before submit

How: Before submit_patch: `python -m py_compile` every touched file, import the touched modules, then run the nearest existing test module(s) (tests/test_<module>.py, found by grep for the edited function) with `-q -x` under `timeout`, and compare against the same run at base so only NEW failures count. On any new failure or collection error, hand the fixer the failing test ids and the diff in a fresh context; do not submit a patch that regresses.

Evidence: rich_3180 v8 passes 114/114 once its one extra call-site edit is removed (per the record, verified locally). Three of four rich_4006 configs broke the existing tests/test_cells.py. fastapi_15588's three non-empty patches all failed at collection.

- Likely: `rich_3180`, `rich_3278`
- Possible: `fastapi_14986`, `fastapi_15588`, `rich_3043`, `rich_4006`
- Long shot: `rich_3934`
- Pain points it answers: G1, G2, G3, L1 (compile after every write), I1 (regression filter), F3

### 4. Context budget guard plus dependency-source rule

How: Assume no compaction. Every helper prints bounded output (head/tail, sed line ranges, pytest -q, grep -n with max count), each stage starts in a fresh context with a short handoff (file:line, plan, diff), and each stage has a call cap. Add the rule: if a grep for a definition returns nothing twice, it is inherited from a dependency, so read it with `python -c 'import inspect, m; print(inspect.getsource(m.Base.method))'` instead of paging repo files.

Evidence: 7 of the 47 unsolved v4 runs ended in ContextWindowExceededError, against 0 of the 27 solved. On the pod, 31 of 74 v4 tasks crossed the 14,336-token threshold and compaction shrank the prompt in 1 (pain_points.md finding 2).

- Likely: `fastapi_14851`, `fastapi_5624`
- Possible: `fastapi_5077`, `rich_4079`
- Pain points it answers: D1, D2, E1, E2, F2, F3, M (history processors)

### 5. Sibling sweep after the first fix

How: After the first successful edit, grep the package for the exact expression or pattern you changed (the blamed call, the hoisted variable, `.extend(` over an alias, the unescaped json.dumps) and apply the same fix at every sibling site; treat each 'Fixes #N' link as a separate bug and write one repro per link.

Evidence: In five tasks a config fixed one of two sites: fastapi_5077 (v6, v7), rich_3480 (v8), fastapi_14986 (v6, v7), fastapi_11194 (v8) and rich_3953 (v4, v7).

- Likely: `fastapi_5077`, `rich_3480`
- Possible: `fastapi_14986`, `rich_3953`
- Long shot: `fastapi_14448`
- Pain points it answers: none in the sweep; supported by the per-task records only

### 6. Gate-triggered second attempt in a fresh context

How: Only when the gate fails and at least ~2 min of the per-task budget remain: start a new fixer with the problem, the failing gate output and the reverted diff (FailFast/RestartSmart pattern), and keep whichever candidate passes the gate. Never run it for tasks that already passed, so the 12 h sequential cap holds.

Evidence: The union of the four configs solves 35 tasks against v4's 27. Eight of the 47 were solved by one or two other configs, which is the ceiling for a sampling-variance lever.

- Likely: none
- Possible: `fastapi_11194`, `fastapi_14851`, `fastapi_5624`, `rich_3454`, `rich_3521`, `rich_3777`, `rich_4077`, `rich_4079`
- Pain points it answers: C2, I1, I2, J1, J2

### 7. Localisation protocol for title-plus-link statements

How: Split the title into code concepts and grep them as identifiers and class names (proxy -> *Proxy*, padding width -> _get_padding_width), never the issue number. Run `git log -p -5` on the hot files of the named subsystem to spot a recent regression. Look for two paths computing the same thing (measure vs render, sibling handler, producer vs consumer) and fix the producer the title names.

Evidence: v4 solves 3 of the 27 title-plus-link statements and 0 of the 5 wrong_location tasks.

- Likely: `rich_4077`
- Possible: `rich_3935`, `rich_3782`
- Long shot: `rich_3944`, `rich_4076`, `rich_3471`, `rich_3772`
- Pain points it answers: none in the sweep; supported by the per-task records only

### 8. Hang-safe execution plus termination heuristics

How: Wrap every repro and test run in an outer `timeout 60` inside our helpers (pytest-timeout alone cannot stop interpreter shutdown). For hang/loop/recursion titles, grep the named module for `while True` walks over attributes, self-recursive calls, `elif` branches with no advance, and list.extend over an alias, and add the advance or a visited-id set.

Evidence: No config solved any of the 6 performance_or_hang tasks. v4 hung on its own code in rich_3480 (555 s, on its repro) and fastapi_14448 (558 s, at import).

- Likely: `rich_3480`
- Possible: `rich_3772`, `rich_4006`
- Long shot: `fastapi_14448`, `fastapi_14258`
- Pain points it answers: G2

### 9. Runtime ground truth instead of guessing library representations

How: Before matching on a library type or relying on an inherited method, print the real object: `FieldInfo.from_annotation(...).metadata`, `type(x).__mro__`, `inspect.getsource(Base.method)`, `pkg.__file__`. Match markers with isinstance/type() on what is actually stored, and import helpers from already-installed dependencies rather than hand-rolling isinstance checks.

Evidence: In fastapi_14616 all four configs wrote Json checks that can never be true. `Json in metadata` misses because metadata holds a Json() instance.

- Likely: `fastapi_14851`
- Possible: `fastapi_14616`, `fastapi_13920`
- Pain points it answers: D4

### 10. Never submit an empty, test-only or 'no bug' patch

How: If the fixer is about to end (or 80% of the call/time budget is used) with no change to a non-test source file, force an edit phase on the best located file:line with the smallest plausible fix. A partial fix can pass; an empty one never does. Restate the problem statement in every stage's instruction.

Evidence: 20 of the 47 unsolved v4 runs changed no source file, against 0 of the 27 solved. Most of those were caused by edit loops, overflow or hangs, so the flips are credited to EDIT, CONTEXT and HANG. This lever is the floor for the rest.

- Likely: none
- Possible: `rich_3782`, `rich_3472`
- Long shot: `fastapi_14258`, `rich_3105`, `rich_3942`
- Pain points it answers: F1, A1, A2

### 11. Copy the repo's own conventions for new checks, messages and settings

How: For a new validation, reuse the enclosing function's idiom (assert vs raise, exception class) and the neighbouring message template with the field name and the statement's wording. For a new setting, copy the companion setting's full value semantics (tri-state 1/0/auto). Store captured attributes in their source shape. Extend the existing test module rather than creating new test files.

Evidence: No config solved any hidden_spec task (0 of 19), and the host says the hidden set was screened for them, so this lever's public count overstates its hidden value.

- Likely: none
- Possible: `fastapi_15588`, `rich_3777`
- Long shot: `rich_3675`, `fastapi_14479`, `fastapi_14258`
- Pain points it answers: Section 1 (host screened hidden tasks for impossible specs)

### 12. Pre-submit patch hygiene

How: Before submit: `git checkout -- tests/ conftest.py pytest.ini` for any agent edits there, and delete untracked files outside the package (repro*.py, test_*.py at the root, anything written to /workspace/tmp).

Evidence: 15 of the 47 unsolved v4 patches carry scratch files and 5 touch tests/. rich_3454 v6's gold-identical source fix was lost because its test-file edit blocked the test_patch from applying.

- Likely: none
- Possible: `rich_3454`
- Pain points it answers: H1, H2

### Union and what it buys

- At least one lever is likely to flip 11 tasks: fastapi_14851, fastapi_5077, fastapi_5624, rich_3180, rich_3278, rich_3454, rich_3480, rich_3521, rich_4075, rich_4077, rich_4079.
- A further 14 are possible: fastapi_11194, fastapi_13920, fastapi_14616, fastapi_14986, fastapi_15588, rich_3043, rich_3052, rich_3472, rich_3772, rich_3777, rich_3782, rich_3935, rich_3953, rich_4006.
- At the stated priors that is about 13 extra public tasks, 27 -> ~40 of 74. The public-to-hidden gap (0.36 -> 0.12) means this does not translate one-for-one. The mechanics levers (edit, context, gate, hang, non-empty) are the ones most likely to carry over, because they fire on repo-agnostic failure signatures that are at least as common on the harder hidden set.
- Ship order: EDIT + NONEMPTY + HYGIENE first (near-free, all mechanics), then one gate script that carries REPRO, GATE and HANG, then CONTEXT, then RETRY only if the per-task time left allows it. SIBLING, TERSE, RUNTIME and CONVENTION are prompt/protocol rules and can ride along with any of them.

### Per-task assignment for the 47 v4-unsolved tasks

| task | v4 blocker (from the trace) | configs that pass | overall tier | levers | note |
|---|---|---|---|---|---|
| fastapi_14851 | context overflow in grep loop for an inherited method | v7 | likely | CONTEXT:likely, RETRY:possible, RUNTIME:likely | v7 passed; v4/v6/v8 overflowed re-grepping for a Starlette method. |
| fastapi_5077 | context overflow; v6/v7 fixed one of two sites | none | likely | CONTEXT:possible, SIBLING:likely | Grep for getattr(call, '__globals__') finds the second site. |
| fastapi_5624 | context overflow at 35 s / 23 calls | v8 | likely | CONTEXT:likely, RETRY:possible | v8 passed with the copy fix; v4 never got to edit. |
| rich_3180 | broke 9 existing wrap tests | none | likely | GATE:likely | v8 passes 114/114 without its one extra call-site edit (record, verified locally). |
| rich_3278 | 93 'old_string not found' edits on a \x1b regex; 110-call cap | none | likely | EDIT:likely, GATE:likely | v8 landed the edit once and regressed an existing test the gate would flag. |
| rich_3454 | 134 edit-parse rejects -> overflow | v8 | likely | EDIT:likely, RETRY:possible, HYGIENE:possible | v6's source edit equals gold but its test-file edit blocked test_patch; v8 passed. |
| rich_3480 | own repro hung 555 s; v8 fixed one of two siblings | none | likely | SIBLING:likely, HANG:likely | timeout-wrapped repro plus a grep for `_spans.extend(` finds both methods. |
| rich_3521 | kept the overshooting guess | v6 | likely | REPRO:likely, RETRY:possible | A sweep over every cut position fails 24 != 23; v6 passed with pos=0. |
| rich_4075 | did the docs chore only | none | likely | REPRO:likely | v6/v8 found the right branch; asserting print(end='!') == '!' flips them. |
| rich_4077 | hardened Console.is_terminal instead of the proxy | v8 | likely | RETRY:possible, TERSE:likely | Title 'proxy isatty' names FileProxy; v8 passed with the gold patch. |
| rich_4079 | backticks in a bash -c repro -> context overflow | v6 v7 | likely | REPRO:likely, CONTEXT:possible, RETRY:possible | Repro written to a file works; v6/v7 passed; v8 wrongly concluded 'no bug'. |
| fastapi_11194 | wrong location (routing.py is_body_form) | v6 v7 | possible | REPRO:possible, RETRY:possible | Repro with Form declared before File still returns 422 after v4's edit; v6/v7 solved. |
| fastapi_13920 | wrong location (type helpers, not analyze_param) | none | possible | REPRO:possible, RUNTIME:possible | End-to-end repro stays 422; the alias is typing_extensions.TypeAliasType. |
| fastapi_14616 | check never true (`Json in metadata`) | none | possible | REPRO:possible, RUNTIME:possible | v6 was one expression away; printing FieldInfo.metadata shows a Json() instance. |
| fastapi_14986 | deleted the root_path feature; 5/7 | none | possible | GATE:possible, SIBLING:possible | Existing root_path tests flag the deletion; v6/v7 each escaped only one of two sites. |
| fastapi_15588 | 74 failed edits; rewrote unrelated code -> ImportError | none | possible | EDIT:possible, GATE:possible, CONVENTION:possible | Right idea in v4; needs clean edits, a collection check and the neighbour message idiom. |
| rich_3043 | de-escaped SVG `{{ }}`; v7/v8 empty after failed edits | none | possible | EDIT:possible, GATE:possible | Existing SVG tests catch the collateral damage. |
| rich_3052 | 125-144 edit-parse rejects in every config | none | possible | EDIT:possible | Right file and spot found; must also return the canonical choice. |
| rich_3472 | scratch files only; wrong reading of 'missing field' | none | possible | REPRO:possible, NONEMPTY:possible | A repro that does not raise means the hypothesis is wrong; init=False field is the case. |
| rich_3772 | read 'recursion' as RecursionError; tests hang | none | possible | TERSE:long, HANG:possible | Hang heuristic: unguarded `while True` over __cause__ needs a cycle guard. |
| rich_3777 | handled '0' only | v7 | possible | REPRO:possible, RETRY:possible, CONVENTION:possible | Copying the companion TTY_COMPATIBLE tri-state fully gives '1'; v7 passed. |
| rich_3782 | test-only patch | none | possible | REPRO:possible, TERSE:possible, NONEMPTY:possible | v7 made the correct fix in 20 calls; its Kaggle FAIL label is disputed (local rerun passes). |
| rich_3935 | wrong location (padding.py) | none | possible | REPRO:possible, TERSE:possible | grep 'padding_width' -> _get_padding_width; measure path ignores pad_edge. |
| rich_3953 | fixed ZWJ only, missed control chars | none | possible | REPRO:long, SIBLING:possible | Two 'Fixes #' links are two bugs; boundary probe chr(1) shows width 1. |
| rich_4006 | changed intentional ZWJ step; timed out | none | possible | GATE:possible, HANG:possible | Existing test_cells.py catches the ZWJ regression in 3 of 4 configs. |
| fastapi_14419 | partial: own-field check, not transitive | none | long | REPRO:long | Nested parent->child->grandchild case with a call counter would show the miss. |
| fastapi_14448 | own infinite loop over __call__ hung import (558 s) | none | long | SIBLING:long, HANG:long | Hard: seven indirection layers plus a consumer in another file. |
| fastapi_14479 | copied the PR draft wording | none | long | CONVENTION:long | Reviewer-edited string; host says hidden tasks were screened for this kind. |
| rich_3468 | wrong exit semantics (120) | none | long | REPRO:long | Needs the CPython SIGPIPE recipe (exit 1); a real-pipe repro shows 120. |
| rich_3470 | repro-only / wrong place | none | long | REPRO:long | Needs repeated-capture repro and a semantic choice the statement does not give. |
| rich_3471 | invented a None input | none | long | TERSE:long | Comparing append_tokens with append would show the missing strip_control_codes. |
| rich_3535 | 66 failed edits, empty; v8 partial | none | long | REPRO:long, EDIT:long | Box-drawing range is a hidden choice; brute-force check vs slow path might surface it. |
| rich_3675 | copied FORCE_COLOR 'any value' semantics | none | long | CONVENTION:long | Tri-state is conventional but not stated. |
| rich_3934 | changed __enter__, broke 6 byte-exact tests | none | long | REPRO:long, GATE:long | Gate flags the regressions; the zero-height guard is still a guess. |
| rich_3944 | 78 failed edits, empty; others edited CSS fonts | none | long | EDIT:long, TERSE:long | git log -p on cells.py plus probing private-use codepoints. |
| rich_4076 | wrong location (pretty.py, markdown.py) | none | long | REPRO:long, TERSE:long | Round-trip from_ansi(x).plain == x over '\n', 'a\n' points at decode. |
| fastapi_14258 | empty patch; 6-min session timeout after 11 calls | none | none | HANG:long, NONEMPTY:long, CONVENTION:long | Assert idiom is derivable, the exact merged message is not. |
| fastapi_14306 | wrong kwarg name + NameError in closure | none | none | - | Hidden endpoint_ctx name and exact str() rendering. |
| fastapi_14487 | dropped per-field info | none | none | - | Exact 'Validation errors:' / 'Field:' strings are not in the statement. |
| fastapi_15280 | test-only patch | none | none | - | April Fool's joke; behaviour exists only in the hidden test. |
| fastapi_15661 | wrote CI YAML, no module | none | none | - | Hidden scripts.prepare_release API. |
| fastapi_15800 | 115 edit-parse rejects -> overflow | none | none | - | 654-line feature with hidden kwargs and internals. |
| rich_3061 | one-line style tweak; hidden extend_style API | none | none | - | Exact _spans representation plus a new public method. |
| rich_3105 | empty patch | none | none | NONEMPTY:long | 'Fix #3104' only; exact inline-style string. |
| rich_3930 | unused new module | none | none | - | 12,714-line feature with hidden CellSpan / rich._unicode_data API. |
| rich_3938 | scratch only | none | none | - | Hidden Segment.split_lines_terminator helper. |
| rich_3942 | empty patch | none | none | NONEMPTY:long | Maintainer taste; golden snapshots. |

### Which lever each pain point supports

The sweep (`research/pain_points.md`) was on disk even though the workflow reported it unavailable, so it is mapped in full here.

| pain point | problem | lever(s) it supports |
|---|---|---|
| 0.1 / A5 / B1 | edit_file parse rejects (49-74%) and escaped old_strings (96% fail) | EDIT (primary), CONTEXT (edit loops are what overflow) |
| A1 | round-bracket / malformed calls fall through as text; 3 nudges end the task | EDIT (short single-string calls), NONEMPTY |
| A2 | bare openers silently dropped (fixed only in vLLM >= 0.27.1) | EDIT (never write prose before a call), NONEMPTY |
| A3 | offline-parser quote truncation | none: not our parser path |
| A4 | parser state shared across concurrent requests | none for scoring (sequential); eval fidelity for 2-per-GPU pod runs |
| A6 | integer args arriving as strings | none: measured 3/552, not an issue |
| B2 | whitespace/indent mismatch loops | EDIT (whitespace tier, line-range primitive, loop breaker) |
| B3 | str_replace editor beats generic edit tools | EDIT (structured replace via run_command helper) |
| B4 | blank lines left / final newline lost | EDIT (helper preserves whole-line semantics) |
| C1 | identical call repeated N times (35% exact repeats in v4, 58% of them edit_file) | EDIT (loop breaker in helpers), RETRY |
| C2 | low temperature -> verbatim retries | RETRY (fresh sample), EDIT |
| C3 | thought loops on long prompts (12B) | none while thinking stays off |
| D1 | 32k window fills after ~20 full tool outputs | CONTEXT |
| D2 | orphaned function calls block ADK compaction | CONTEXT (assume no compaction) |
| D3 | tiny default contexts | none: we have 32k |
| D4 | partial reads -> hallucinated findings | REPRO, RUNTIME (verify by running code, print real objects) |
| E1 | thoughts re-sent as history | CONTEXT (keep include_thoughts false) |
| E2 | unbounded thinking | CONTEXT (output cap); config |
| E3 | reasoning/tool text leaks | none: rare with thinking off |
| F1 | model stops without a call / 'please provide the problem' | NONEMPTY (restate the problem per stage, force an edit phase) |
| F2 | system-prompt non-adherence past ~10k tokens | CONTEXT (short prompts); put rules in helper error messages |
| F3 | schema discipline drifts after 20-50 calls | CONTEXT (fresh context per stage), GATE |
| G1 | agent never runs tests (78 of 155 failing runs) | REPRO, GATE |
| G2 | tests or repros hang | HANG (outer timeout), GATE |
| G3 | env differences make gold fail | eval fidelity (pins); also the rich_3782 label recheck |
| H1 | scratch files in the patch (16 of 61 v4 patches) | HYGIENE |
| H2 | edits to tests break test_patch apply (4 rescored runs) | HYGIENE |
| I1 | one sample is noisy; selection needs a verifier | RETRY, GATE (regression filter) |
| I2 | fail fast and restart in a fresh context | RETRY |
| J1 | per-task caps vs the 12 h sequential cap | constraint on REPRO/GATE/RETRY cost, not a lever |
| J2 | slow decoding: every saved call buys exploration | EDIT (810 repeated edit calls in v4), CONTEXT |
| K1 / finding 3 | scorer runs the June template | eval fidelity; EDIT's 'no prose before a call' also avoids the stray <turn\|> |
| K2 | alphabetical parameter order (new_string before old_string) | EDIT (single-string helper makes order irrelevant) |
| L1 | too many tools; code sandbox beats many small tools; compile check after every write | EDIT, GATE, CONTEXT (short tool list per stage) |
| L2 | malformed JSON needs repair | EDIT (helpers tolerate escaped input and sloppy paths) |
| M | multi-line Python in bash; observation collapsing | REPRO (write repros to files), CONTEXT (short outputs) |
| Section 1 | hidden set from private repos, screened for impossible/hidden-spec tasks | down-weights CONVENTION and all hidden-spec tasks; up-weights mechanics levers |
| Finding 2 | pod ran without compaction; scorer config differs | eval fidelity before trusting a race |

## 5. Infeasible for a 5-minute 31B agent

11 tasks are marked infeasible in their records. Every one is a hidden-spec task: the hidden test pins a name, message or rendering the statement does not give. The host says tasks like these were screened out of the hidden set, so effort spent on them buys nothing there. The right agent behaviour is to triage early, submit the cheapest plausible change, and move on.

| task | why it is infeasible | gold size |
|---|---|---|
| fastapi_14258 | Guard is easy; hidden test matches the exact merged AssertionError message. | 1f/1h/4l |
| fastapi_14479 | Hidden test matches the reviewer-edited wording; the statement shows only the pre-review draft. | 1f/1h/1l |
| fastapi_14487 | Exact 'Validation errors:' / 'Field: <loc>' output strings appear nowhere in the statement. | 1f/1h/7l |
| fastapi_15280 | April Fool's PR; the raise and its message exist only in the hidden test. | 2f/3h/72l |
| fastapi_15661 | Empty PR template; tests import scripts.prepare_release and its CLI names. | 1f/1h/216l |
| fastapi_15800 | 654-line feature with hidden kwargs (fallback, check_dir), internals and docs_src examples. | 8f/20h/654l |
| rich_3061 | Tests assert exact _spans lists and a new public Text.extend_style. | 1f/13h/91l |
| rich_3105 | 'Fix #3104' only; the exact inline-style string is not derivable. | 1f/1h/2l |
| rich_3930 | 12,714-line grapheme feature; tests import CellSpan and rich._unicode_data. | 6f/29h/12714l |
| rich_3938 | Tests call a new Segment.split_lines_terminator helper by name. | 2f/2h/45l |
| rich_3942 | Maintainer restyle by taste; golden ANSI snapshots are the only spec. | 2f/7h/70l |

Near-infeasible in 5 minutes (marked hard, never solved by any config): fastapi_14306, fastapi_14448, rich_3470, rich_3535, rich_3944, rich_4076. These need multi-layer reasoning (fastapi_14448's seven wrapper layers), a hidden semantic choice (rich_3470's 'record what was emitted', rich_3535's box-drawing range, fastapi_14306's endpoint_ctx kwarg) or an issue text the agent cannot read (rich_3944, rich_4076). Budget them like the infeasible set unless a lever surfaces the fix early.

## Method and caveats

- Outcomes are the Kaggle-env labels in `_inputs.json` (rescore of the pod patches). Pod-env failures caused by the environment were overridden there, not here.
- Trace mechanics: an edit_file call is rejected when its observation says 'mandatory input param', not-found when it says 'not found'; overflow and timeout come from `task_results.jsonl` errors; 'no source change' means the patch touches no file outside tests/, root-level test_/repro/verify scripts and docs/config. Code: `research/catalog_build/mech.py`; catalog build: `research/catalog_build/build_catalog.py`.
- Tiers are judgement calls from each task's record and trace, stated per task in section 4. Priors of 0.7 and 0.35 are assumptions, not measurements. The v9/v10 race arms are the controlled test of these levers.
- Only public tasks are here. The hidden set comes from private repos, so any lever tuned to fastapi/rich specifics (names, idioms) is excluded from the ranking on purpose.
