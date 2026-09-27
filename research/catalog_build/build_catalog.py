"""Build research/task_catalog.md and research/task_catalog.json from per-task records.

Inputs: research/tasks/*.json (74 records), research/tasks/_inputs.json (Kaggle-env pass
per config + pod meta), scratchpad mech.json (per-config trace mechanics, from mech.py),
data/tasks.jsonl (statements).
"""
import collections
import glob
import json
import os

ROOT = "/Users/carson/Projects/gemma-swe-agent"
SCR = "/Users/carson/Projects/gemma-swe-agent/research/catalog_build"
CFGS = ["v4", "v6", "v7", "v8"]

recs = {}
for f in sorted(glob.glob(f"{ROOT}/research/tasks/*.json")):
    if os.path.basename(f).startswith("_"):
        continue
    d = json.load(open(f))
    recs[d["task"]] = d
inp = {r["id"]: r for r in json.load(open(f"{ROOT}/research/tasks/_inputs.json"))}
mech = json.load(open(f"{SCR}/mech.json"))
stm = {}
for line in open(f"{ROOT}/data/tasks.jsonl"):
    d = json.loads(line)
    stm[d["instance_id"]] = d["problem_statement"]
assert set(recs) == set(inp), (set(inp) - set(recs), set(recs) - set(inp))
IDS = sorted(recs, key=lambda t: (t.split("_")[0], int(t.split("_")[1])))

def passes(t):
    return [c for c in CFGS if inp[t]["kaggle_env_pass"][c]]

UNSOLVED_V4 = [t for t in IDS if not inp[t]["kaggle_env_pass"]["v4"]]
SOLVED_V4 = [t for t in IDS if inp[t]["kaggle_env_pass"]["v4"]]
assert len(UNSOLVED_V4) == 47 and len(SOLVED_V4) == 27

# ---------------------------------------------------------------- one-line solutions
ONE = {
 "fastapi_11194": "Use each field's own field_info (not the hoisted body_fields[0]) in both File-to-bytes branches of _extract_form_body.",
 "fastapi_13537": "Build the complement-loop skip set from declared field aliases, not from the output dict, so skipped None values are not re-added as raw \"\".",
 "fastapi_13920": "Unwrap TypeAliasType (typing_inspection is_typealiastype) once at the top of analyze_param, before the Annotated metadata scan.",
 "fastapi_14077": "Replace every use of the renamed Starlette 422 constant with the literal 422; grep until no use of the old name remains.",
 "fastapi_14258": "First statement of include_router: `assert self is not router, \"Cannot include the same APIRouter instance into itself. ...\"` (assert, like its neighbours).",
 "fastapi_14301": "Pass scope=depends.scope into get_dependant from get_parameterless_sub_dependant.",
 "fastapi_14306": "Add an endpoint_ctx (TypedDict) kwarg to the ValidationException family, a singular/plural __str__ in the base, and pass the context from routing.",
 "fastapi_14372": "@dataclass(frozen=True) on Depends and Security (and replace the in-place `depends.dependency =` with dataclasses.replace).",
 "fastapi_14419": "Keep scopes in Dependant.cache_key only when the dependant or any sub-dependant (transitive, memoized) uses SecurityScopes.",
 "fastapi_14448": "Classify async/generator at every wrapper layer (partial, __wrapped__, instance, __call__, decorated __call__); prefer the async-gen path in _solve_generator.",
 "fastapi_14458": "`if inspect.isclass(_unwrapped_call(self.call)): return False` in all three is_*_callable properties, before the __call__ fallback.",
 "fastapi_14463": "copy.deepcopy (not dict.copy) the per-route additional response in get_openapi_path.",
 "fastapi_14479": "Message on the bare Query assert: f\"Query parameter {param_name!r} must be one of the supported types\" (the merged wording, not the PR draft).",
 "fastapi_14487": "Docs example returns \"Validation errors:\" plus one \"Field: {loc}, Error: {msg}\" line per exc.errors() entry instead of str(exc).",
 "fastapi_14492": "Replace \"identifier\": \"MIT\" with \"Apache-2.0\" in the one docs_src example.",
 "fastapi_14616": "In _get_multidict_value skip getlist when any field_info.metadata item is a Json() instance (`type(item) is Json`).",
 "fastapi_14786": "`return scheme, param.strip()` in get_authorization_scheme_param.",
 "fastapi_14794": "Add `depends is None and` to analyze_param's special-type branch and delete the assert.",
 "fastapi_14851": "Re-implement on_startup/on_shutdown lists, add_event_handler, _DefaultLifespan and generator-lifespan wrapping in APIRouter instead of inheriting them from Starlette.",
 "fastapi_14873": "Move the on_startup/on_shutdown assignments to after super().__init__() in APIRouter.__init__.",
 "fastapi_14986": "Never mutate self.servers: add root_path per response on a copy of the cached schema; escape swagger params and initOAuth JSON through one helper.",
 "fastapi_15280": "FastAPI.vibe(path, *, prompt='') that raises FastAPIError(\"Are you kidding me? Happy April Fool's\").",
 "fastapi_15588": "AfterValidator on event and id raising ValueError(f\"SSE '{field}' must be a single line\") for \\r or \\n.",
 "fastapi_15589": "Also add get_validation_alias(field) to processed_keys so the raw underscore header is not re-added as an extra.",
 "fastapi_15661": "New scripts/prepare_release.py Typer app (bump version, update release notes) built from pure content->str functions, plus the workflows.",
 "fastapi_15800": "New APIRouter/FastAPI.frontend(path, *, directory, fallback, check_dir) serving an SPA build as low-priority routes, with docs_src examples.",
 "fastapi_5077": "inspect.unwrap(call) before reading __globals__ in BOTH get_typed_signature and get_typed_return_annotation.",
 "fastapi_5624": "Copy the scopes list before extending it (`list(security_scopes or []) + scopes`) in get_dependant.",
 "fastapi_9425": "In get_typed_annotation map an evaluated stringified \"None\" (type(None)) back to None.",
 "fastapi_9555": "Add _unwrapped_call = inspect.unwrap(self.call) and use it in all three Dependant is_*_callable properties.",
 "fastapi_9753": "Strip functools.partial layers in Dependant._unwrapped_call after inspect.unwrap.",
 "requests_6644": "In HTTPAdapter.request_url collapse a leading '//' in path_url to '/' before urlopen.",
 "rich_2725": "Reorder box_segments to (head, mid, foot) to match the `0 if first else (2 if last else 1)` index.",
 "rich_2943": "`style._hash = None` (not a copy) in Style.clear_meta_and_links.",
 "rich_3006": "`param.default is param.empty` (identity, not ==) in auto_rich_repr.",
 "rich_3043": "Move `<html>` to directly after `<!DOCTYPE html>` in CONSOLE_HTML_FORMAT; touch nothing else in the file.",
 "rich_3052": "case_sensitive=True kwarg threaded through PromptBase and every ask overload; lower-case compare in check_choice; return the canonical choice.",
 "rich_3061": "Rewrite Text.expand_tabs to extend the tab's spans over inserted spaces with cell-width tab stops; add Text.extend_style; drop empty-style spans.",
 "rich_3063": "In markup.escape, double a lone trailing backslash.",
 "rich_3067": "Add '~' to ReprHighlighter's URL character class.",
 "rich_3105": "`<code style=\"font-family:inherit\">` in CONSOLE_HTML_FORMAT.",
 "rich_3180": "Make chop_cells iterate left to right (no reversed()) and leave the divide_line call site alone.",
 "rich_3278": "Prepend `(?:\\x1b[0-?])` as a new alternative to re_ansi so Fp private escapes are consumed.",
 "rich_3454": "Add '@' to ReprHighlighter's URL character class (and do not touch tests/test_highlighter.py).",
 "rich_3468": "Catch BrokenPipeError around write+flush, dup2 devnull onto stdout and exit(1) (CPython SIGPIPE recipe) via a Console.on_broken_pipe hook.",
 "rich_3470": "Record only on a real flush: `if self.record and not self._buffer_index:` in Console._write_buffer.",
 "rich_3471": "strip_control_codes(content) inside Text.append_tokens, as __init__ and append already do.",
 "rich_3472": "Skip dataclass fields the instance lacks (`hasattr(obj, field.name)`) in pretty.traverse.",
 "rich_3480": "Iterate a snapshot of text._spans in BOTH Text.append and Text.append_text.",
 "rich_3506": "Make _split_cells' start guess an under-estimate (or start at 0) so the forward scan never starts past the cut.",
 "rich_3518": "Column(_index=index, highlight=self.highlight) for columns auto-created in add_row.",
 "rich_3521": "Make Segment._split_cells search two-way from the proportional guess (or scan from 0).",
 "rich_3535": "Fix _is_single_cell_widths: end ASCII at U+007E, restore the U+00A0-U+02FF range hyphen, add box drawing U+2500-U+25FF.",
 "rich_3675": "TTY_COMPATIBLE tri-state in Console.is_terminal: '1' True, '0' False, anything else falls through to detection.",
 "rich_3676": "Stack.notes = list(getattr(exc_value, '__notes__', [])), rendered after the exception value.",
 "rich_3718": "Revert 7a38204: stylize the panel title/subtitle with the combined border_style.",
 "rich_3772": "Cycle guards in Traceback.extract: stop on an already-seen __cause__/__context__ and keep a visited set for exception-group members.",
 "rich_3777": "TTY_INTERACTIVE tri-state ('0' off, '1' on, else auto) read from self._environ before the is_interactive expression.",
 "rich_3782": "Subtract horizontal padding from the auto code_width in Syntax._get_syntax and clamp it at 0.",
 "rich_3882": "self.console.print(error, markup=True) in PromptBase.on_validate_error.",
 "rich_3894": "Keep `name or __qualname__` and add a type guard falling back to __name__ when qualname is not a str.",
 "rich_3905": "Wrap all of Progress.stop() in `if not self.disable:`.",
 "rich_3930": "Grapheme-aware cell widths: versioned rich._unicode_data tables, CellSpan/split_graphemes API, grapheme-safe chop_cells/set_cell_size.",
 "rich_3934": "Only write the stop() newline when the last render had height > 0 (LiveRender.last_render_height).",
 "rich_3935": "Apply pad_edge in Table._get_padding_width exactly as the render path's get_padding does.",
 "rich_3938": "Add Segment.split_lines_terminator and style each line's text but not its newline in the soft_wrap branch.",
 "rich_3942": "Maintainer restyle of Markdown headings, hr and tables (golden ANSI snapshots).",
 "rich_3944": "Return 1 (not 0) for codepoints beyond the width table in get_character_cell_size.",
 "rich_3953": "Zero width for C0/C1 control characters in get_character_cell_size, and make the ZWJ next() safe at end of string.",
 "rich_4006": "Guarantee every split_graphemes branch advances and emits zero-width spans for leading ZWJ/VS16/zero-width chars; keep the ZWJ `+= 2`.",
 "rich_4075": "`objects = (NewLine(),) if end == \"\\n\" else (\"\",)` when Console.print gets no objects.",
 "rich_4076": "re.split(r\"(?<=\\n)\") instead of splitlines() in AnsiDecoder.decode so a trailing newline survives.",
 "rich_4077": "Add FileProxy.isatty delegating to the wrapped file.",
 "rich_4079": "In TableDataElement.on_text, style only plain str chunks; append pre-styled Text untouched.",
}
assert set(ONE) == set(IDS), set(IDS) ^ set(ONE)

# ---------------------------------------------------------------- solution patterns
TAG = lambda tag: [t for t in IDS if tag in recs[t]["tags"]]
PATTERNS = [
 ("P1", "PR description already contains the fix (names the function and the change)",
  "Transcribe it at the named spot; grep the quoted expression; change nothing else.",
  [t for t in IDS if recs[t]["statement_reveals_fix"] == "full"]),
 ("P2", "Title plus a bare issue link; the spec lives in the linked issue the agent cannot read",
  "Decompose the title into code concepts, grep identifiers (not the issue number), reproduce the most literal reading, probe edge inputs.",
  TAG("title_plus_link_only")),
 ("P3", "Hidden test asserts an exact error message or rendered string",
  "Copy the neighbouring message/format idiom character for character; reuse the statement's own words; never pin a guessed string in your own test.",
  ["fastapi_14258", "fastapi_14479", "fastapi_14487", "fastapi_15588", "fastapi_14306", "fastapi_15280",
   "rich_3043", "rich_3105", "rich_3942", "rich_3934", "rich_3938", "rich_4075", "rich_2725", "rich_3782"]),
 ("P4", "Hidden test imports a new public name the statement never spells out",
  "Rarely derivable. Name helpers after the nearest sibling (split_lines -> split_lines_<variant>) and put them where existing tests import from; cap effort.",
  ["fastapi_15661", "fastapi_15800", "fastapi_14306", "fastapi_15280", "rich_3930", "rich_3938", "rich_3061"]),
 ("P5", "Statement names the new parameter / API / env var explicitly",
  "Implement exactly that name, keyword-only with safe defaults; copy a companion setting's full value semantics; thread it through every overload and factory.",
  ["fastapi_13920", "fastapi_15280", "fastapi_15800", "rich_3052", "rich_3675", "rich_3676", "rich_3777"]),
 ("P6", "Fix belongs at the shared chokepoint every caller goes through",
  "Patch the one normalisation helper/entry point (not each caller, not a downstream helper you grepped first).",
  ["fastapi_14786", "fastapi_9753", "fastapi_9555", "fastapi_14458", "fastapi_14616", "fastapi_13920", "requests_6644", "fastapi_14301"]),
 ("P7", "Same defect at sibling sites (hidden test hits all of them)",
  "After the first fix, grep the package for the same expression/pattern and fix every sibling; treat each 'Fixes #N' as its own bug.",
  ["fastapi_5077", "rich_3480", "fastapi_11194", "fastapi_14986", "fastapi_9555", "fastapi_14458", "rich_3953", "fastapi_14448", "fastapi_14077"]),
 ("P8", "Shared mutable state leaks (aliased list/dict mutated in place, dict used as output and as 'handled' marker)",
  "Copy at the point of sharing (list(x), deepcopy) or track handled keys in a separate set; do not delete the feature.",
  ["fastapi_5624", "fastapi_14463", "fastapi_14986", "rich_3480", "rich_3470", "fastapi_13537", "fastapi_15589", "fastapi_14372"]),
 ("P9", "Ordering / initialisation bug (build order vs index order, parent __init__ overwrites, value hoisted from items[0])",
  "Find where the thing is built and where it is consumed; fix the side that disagrees with the documented meaning.",
  ["fastapi_14873", "fastapi_11194", "rich_2725", "rich_4075"]),
 ("P10", "Wrapped callables and annotations misclassified (partial, @wraps, classes, proxies, type aliases, string annotations)",
  "Normalise every wrapper layer once, at the entry point, before classification; delegate explicitly when a base class shadows __getattr__.",
  ["fastapi_9555", "fastapi_9753", "fastapi_14448", "fastapi_14458", "fastapi_5077", "fastapi_13920", "fastapi_9425", "rich_4077"]),
 ("P11", "Two code paths compute the same quantity and disagree (measure vs render, sibling handler, start vs stop)",
  "Diff the two paths and make the broken one apply every flag/step the working one applies.",
  ["rich_3935", "rich_3782", "rich_3521", "rich_3506", "rich_3180", "rich_4079", "rich_3471", "rich_3905", "rich_3518"]),
 ("P12", "Regex / character-class allow-list is missing characters",
  "Add only the missing range/char, keep existing literals (downstream code may compare the captured group), brute-force check against the slow path.",
  ["rich_3067", "rich_3454", "rich_3278", "rich_3535"]),
 ("P13", "Hang / infinite loop / recursion (loop branch that never advances, missing cycle guard, extend-while-iterating)",
  "Run every repro under `timeout`; find the branch with no progress or the unguarded attribute walk; add the advance or a visited-id set.",
  ["rich_4006", "rich_3772", "rich_3480", "fastapi_14258", "fastapi_14448"]),
 ("P14", "Sentinel / identity / type-guard edge case",
  "Use `is` for sentinels, add a narrow guard after the original expression, invalidate caches rather than copying them.",
  ["rich_3006", "rich_3894", "rich_3472", "fastapi_9425", "rich_2943", "rich_3063"]),
 ("P15", "Byte-exact template or snapshot output",
  "Minimal edit following the neighbouring formatting; never touch other templates' `{{ }}` escapes or the leading `\"\"\"\\`; render once and diff.",
  ["rich_3043", "rich_3105", "rich_3942", "rich_2725", "rich_3718", "rich_3938", "rich_3934", "rich_4079"]),
 ("P16", "Upstream dependency changed; behaviour the repo relies on is inherited from site-packages",
  "When grep finds no definition twice, read the installed base class source (inspect.getsource) and vendor what the repo needs.",
  ["fastapi_14851", "fastapi_14077", "fastapi_14873"]),
 ("P17", "PR looks like docs/tooling but the tested artefact is runnable code",
  "Change the runnable example/module (docs_src/, scripts/) and read its existing test for the output shape; ignore incidental chores.",
  ["fastapi_14487", "fastapi_14492", "fastapi_15661", "rich_4075", "rich_3043"]),
]
for pid, _, _, ts in PATTERNS:
    for t in ts:
        assert t in recs, (pid, t)

# ---------------------------------------------------------------- per-task lever assignment for the 47
# tier: likely = the lever removes the blocker observed in v4 AND another config or v4 itself already
#       had the right fix/location; possible = blocker removed but the remaining step is uncertain;
#       long = only a long shot; none = infeasible in 5 min or no generalisable lever reaches it.
ASSIGN = {
 "fastapi_11194": ("wrong location (routing.py is_body_form)", "possible", ["REPRO", "RETRY"], "Repro with Form declared before File still returns 422 after v4's edit; v6/v7 solved."),
 "fastapi_13920": ("wrong location (type helpers, not analyze_param)", "possible", ["REPRO", "RUNTIME"], "End-to-end repro stays 422; the alias is typing_extensions.TypeAliasType."),
 "fastapi_14258": ("empty patch; 6-min session timeout after 11 calls", "none", ["HANG", "CONVENTION"], "Assert idiom is derivable, the exact merged message is not."),
 "fastapi_14306": ("wrong kwarg name + NameError in closure", "none", [], "Hidden endpoint_ctx name and exact str() rendering."),
 "fastapi_14419": ("partial: own-field check, not transitive", "long", ["REPRO"], "Nested parent->child->grandchild case with a call counter would show the miss."),
 "fastapi_14448": ("own infinite loop over __call__ hung import (558 s)", "long", ["HANG", "SIBLING"], "Hard: seven indirection layers plus a consumer in another file."),
 "fastapi_14479": ("copied the PR draft wording", "long", ["CONVENTION"], "Reviewer-edited string; host says hidden tasks were screened for this kind."),
 "fastapi_14487": ("dropped per-field info", "none", [], "Exact 'Validation errors:' / 'Field:' strings are not in the statement."),
 "fastapi_14616": ("check never true (`Json in metadata`)", "possible", ["RUNTIME", "REPRO"], "v6 was one expression away; printing FieldInfo.metadata shows a Json() instance."),
 "fastapi_14851": ("context overflow in grep loop for an inherited method", "likely", ["CONTEXT", "RUNTIME"], "v7 passed; v4/v6/v8 overflowed re-grepping for a Starlette method."),
 "fastapi_14986": ("deleted the root_path feature; 5/7", "possible", ["GATE", "SIBLING"], "Existing root_path tests flag the deletion; v6/v7 each escaped only one of two sites."),
 "fastapi_15280": ("test-only patch", "none", [], "April Fool's joke; behaviour exists only in the hidden test."),
 "fastapi_15588": ("74 failed edits; rewrote unrelated code -> ImportError", "possible", ["EDIT", "GATE", "CONVENTION"], "Right idea in v4; needs clean edits, a collection check and the neighbour message idiom."),
 "fastapi_15661": ("wrote CI YAML, no module", "none", [], "Hidden scripts.prepare_release API."),
 "fastapi_15800": ("115 edit-parse rejects -> overflow", "none", ["EDIT"], "654-line feature with hidden kwargs and internals."),
 "fastapi_5077": ("context overflow; v6/v7 fixed one of two sites", "likely", ["CONTEXT", "SIBLING"], "Grep for getattr(call, '__globals__') finds the second site."),
 "fastapi_5624": ("context overflow at 35 s / 23 calls", "likely", ["CONTEXT"], "v8 passed with the copy fix; v4 never got to edit."),
 "rich_3043": ("de-escaped SVG `{{ }}`; v7/v8 empty after failed edits", "possible", ["GATE", "EDIT"], "Existing SVG tests catch the collateral damage."),
 "rich_3052": ("125-144 edit-parse rejects in every config", "possible", ["EDIT"], "Right file and spot found; must also return the canonical choice."),
 "rich_3061": ("one-line style tweak; hidden extend_style API", "none", [], "Exact _spans representation plus a new public method."),
 "rich_3105": ("empty patch", "none", [], "'Fix #3104' only; exact inline-style string."),
 "rich_3180": ("broke 9 existing wrap tests", "likely", ["GATE"], "v8 passes 114/114 without its one extra call-site edit (record, verified locally)."),
 "rich_3278": ("93 'old_string not found' edits on a \\x1b regex; 110-call cap", "likely", ["EDIT", "GATE"], "v8 landed the edit once and regressed an existing test the gate would flag."),
 "rich_3454": ("134 edit-parse rejects -> overflow", "likely", ["EDIT", "HYGIENE"], "v6's source edit equals gold but its test-file edit blocked test_patch; v8 passed."),
 "rich_3468": ("wrong exit semantics (120)", "long", ["REPRO"], "Needs the CPython SIGPIPE recipe (exit 1); a real-pipe repro shows 120."),
 "rich_3470": ("repro-only / wrong place", "long", ["REPRO"], "Needs repeated-capture repro and a semantic choice the statement does not give."),
 "rich_3471": ("invented a None input", "long", ["TERSE"], "Comparing append_tokens with append would show the missing strip_control_codes."),
 "rich_3472": ("scratch files only; wrong reading of 'missing field'", "possible", ["REPRO", "NONEMPTY"], "A repro that does not raise means the hypothesis is wrong; init=False field is the case."),
 "rich_3480": ("own repro hung 555 s; v8 fixed one of two siblings", "likely", ["HANG", "SIBLING"], "timeout-wrapped repro plus a grep for `_spans.extend(` finds both methods."),
 "rich_3521": ("kept the overshooting guess", "likely", ["REPRO"], "A sweep over every cut position fails 24 != 23; v6 passed with pos=0."),
 "rich_3535": ("66 failed edits, empty; v8 partial", "long", ["EDIT", "REPRO"], "Box-drawing range is a hidden choice; brute-force check vs slow path might surface it."),
 "rich_3675": ("copied FORCE_COLOR 'any value' semantics", "long", ["CONVENTION"], "Tri-state is conventional but not stated."),
 "rich_3772": ("read 'recursion' as RecursionError; tests hang", "possible", ["HANG", "TERSE"], "Hang heuristic: unguarded `while True` over __cause__ needs a cycle guard."),
 "rich_3777": ("handled '0' only", "possible", ["CONVENTION", "REPRO"], "Copying the companion TTY_COMPATIBLE tri-state fully gives '1'; v7 passed."),
 "rich_3782": ("test-only patch", "possible", ["NONEMPTY", "TERSE", "REPRO"], "v7 made the correct fix in 20 calls; its Kaggle FAIL label is disputed (local rerun passes)."),
 "rich_3930": ("unused new module", "none", [], "12,714-line feature with hidden CellSpan / rich._unicode_data API."),
 "rich_3934": ("changed __enter__, broke 6 byte-exact tests", "long", ["GATE", "REPRO"], "Gate flags the regressions; the zero-height guard is still a guess."),
 "rich_3935": ("wrong location (padding.py)", "possible", ["TERSE", "REPRO"], "grep 'padding_width' -> _get_padding_width; measure path ignores pad_edge."),
 "rich_3938": ("scratch only", "none", [], "Hidden Segment.split_lines_terminator helper."),
 "rich_3942": ("empty patch", "none", [], "Maintainer taste; golden snapshots."),
 "rich_3944": ("78 failed edits, empty; others edited CSS fonts", "long", ["TERSE", "EDIT"], "git log -p on cells.py plus probing private-use codepoints."),
 "rich_3953": ("fixed ZWJ only, missed control chars", "possible", ["SIBLING", "REPRO"], "Two 'Fixes #' links are two bugs; boundary probe chr(1) shows width 1."),
 "rich_4006": ("changed intentional ZWJ step; timed out", "possible", ["GATE", "HANG"], "Existing test_cells.py catches the ZWJ regression in 3 of 4 configs."),
 "rich_4075": ("did the docs chore only", "likely", ["REPRO"], "v6/v8 found the right branch; asserting print(end='!') == '!' flips them."),
 "rich_4076": ("wrong location (pretty.py, markdown.py)", "long", ["REPRO", "TERSE"], "Round-trip from_ansi(x).plain == x over '\\n', 'a\\n' points at decode."),
 "rich_4077": ("hardened Console.is_terminal instead of the proxy", "likely", ["TERSE"], "Title 'proxy isatty' names FileProxy; v8 passed with the gold patch."),
 "rich_4079": ("backticks in a bash -c repro -> context overflow", "likely", ["REPRO", "CONTEXT"], "Repro written to a file works; v6/v7 passed; v8 wrongly concluded 'no bug'."),
}
assert set(ASSIGN) == set(UNSOLVED_V4), set(ASSIGN) ^ set(UNSOLVED_V4)

LEVERS = [
 dict(key="REPRO", name="Repro-must-flip check before submit",
      how=("Write the statement's literal repro to a file (never a bash -c one-liner: backticks, $ and quotes break it) and run it "
           "under `timeout 60` at base and after the edit. It must misbehave at base and produce the exact expected output after "
           "(assert the string, not 'looks fine'). If it already passes at base, re-run it through the other input shapes "
           "(model vs scalar param, wrapped vs plain, empty vs None, both argument orders) before concluding anything; never submit "
           "'no bug' for a bugfix title. For functions with an invariant (split at cut, round-trip decode, width sums), sweep every "
           "position/boundary input instead of one example. Ship as one gate script with the regression gate."),
      pains=["G1", "D4", "I1", "I2", "M (SWE-agent #1302)"]),
 dict(key="EDIT", name="Reliable edit channel plus mechanism-switching loop breaker",
      how=("Forbid edit_file. Edit through run_command calling our helper: exact match, then unescape (\\n \\t \\\" \\\\ \\uXXXX \\x1b) and "
           "retry, then whitespace-flexible match, then line-range replace; preserve trailing newlines; after every edit run "
           "py_compile on the file and print a 3-line diff. Keep a hash of the last commands in $TMPDIR/swe/state and, on the second "
           "identical failure, return an error that names the alternative mechanism (line-range or a python rewrite)."),
      pains=["A1", "A2", "A5", "B1", "B2", "B3", "B4", "C1", "C2", "K2", "L1", "L2", "J2"]),
 dict(key="GATE", name="Regression and collection gate before submit",
      how=("Before submit_patch: `python -m py_compile` every touched file, import the touched modules, then run the nearest existing "
           "test module(s) (tests/test_<module>.py, found by grep for the edited function) with `-q -x` under `timeout`, and compare "
           "against the same run at base so only NEW failures count. On any new failure or collection error, hand the fixer the "
           "failing test ids and the diff in a fresh context; do not submit a patch that regresses."),
      pains=["G1", "G2", "G3", "L1 (compile after every write)", "I1 (regression filter)", "F3"]),
 dict(key="CONTEXT", name="Context budget guard plus dependency-source rule",
      how=("Assume no compaction. Every helper prints bounded output (head/tail, sed line ranges, pytest -q, grep -n with max count), "
           "each stage starts in a fresh context with a short handoff (file:line, plan, diff), and each stage has a call cap. Add the "
           "rule: if a grep for a definition returns nothing twice, it is inherited from a dependency, so read it with "
           "`python -c 'import inspect, m; print(inspect.getsource(m.Base.method))'` instead of paging repo files."),
      pains=["D1", "D2", "E1", "E2", "F2", "F3", "M (history processors)"]),
 dict(key="SIBLING", name="Sibling sweep after the first fix",
      how=("After the first successful edit, grep the package for the exact expression or pattern you changed (the blamed call, the "
           "hoisted variable, `.extend(` over an alias, the unescaped json.dumps) and apply the same fix at every sibling site; treat "
           "each 'Fixes #N' link as a separate bug and write one repro per link."),
      pains=[]),
 dict(key="RETRY", name="Gate-triggered second attempt in a fresh context",
      how=("Only when the gate fails and at least ~2 min of the per-task budget remain: start a new fixer with the problem, the failing "
           "gate output and the reverted diff (FailFast/RestartSmart pattern), and keep whichever candidate passes the gate. Never "
           "run it for tasks that already passed, so the 12 h sequential cap holds."),
      pains=["C2", "I1", "I2", "J1", "J2"]),
 dict(key="TERSE", name="Localisation protocol for title-plus-link statements",
      how=("Split the title into code concepts and grep them as identifiers and class names (proxy -> *Proxy*, padding width -> "
           "_get_padding_width), never the issue number. Run `git log -p -5` on the hot files of the named subsystem to spot a recent "
           "regression. Look for two paths computing the same thing (measure vs render, sibling handler, producer vs consumer) and fix "
           "the producer the title names."),
      pains=[]),
 dict(key="HANG", name="Hang-safe execution plus termination heuristics",
      how=("Wrap every repro and test run in an outer `timeout 60` inside our helpers (pytest-timeout alone cannot stop interpreter "
           "shutdown). For hang/loop/recursion titles, grep the named module for `while True` walks over attributes, self-recursive "
           "calls, `elif` branches with no advance, and list.extend over an alias, and add the advance or a visited-id set."),
      pains=["G2"]),
 dict(key="RUNTIME", name="Runtime ground truth instead of guessing library representations",
      how=("Before matching on a library type or relying on an inherited method, print the real object: "
           "`FieldInfo.from_annotation(...).metadata`, `type(x).__mro__`, `inspect.getsource(Base.method)`, `pkg.__file__`. Match "
           "markers with isinstance/type() on what is actually stored, and import helpers from already-installed dependencies "
           "rather than hand-rolling isinstance checks."),
      pains=["D4"]),
 dict(key="NONEMPTY", name="Never submit an empty, test-only or 'no bug' patch",
      how=("If the fixer is about to end (or 80% of the call/time budget is used) with no change to a non-test source file, force an "
           "edit phase on the best located file:line with the smallest plausible fix. A partial fix can pass; an empty one never "
           "does. Restate the problem statement in every stage's instruction."),
      pains=["F1", "A1", "A2"]),
 dict(key="CONVENTION", name="Copy the repo's own conventions for new checks, messages and settings",
      how=("For a new validation, reuse the enclosing function's idiom (assert vs raise, exception class) and the neighbouring "
           "message template with the field name and the statement's wording. For a new setting, copy the companion setting's full "
           "value semantics (tri-state 1/0/auto). Store captured attributes in their source shape. Extend the existing test module "
           "rather than creating new test files."),
      pains=["Section 1 (host screened hidden tasks for impossible specs)"]),
 dict(key="HYGIENE", name="Pre-submit patch hygiene",
      how=("Before submit: `git checkout -- tests/ conftest.py pytest.ini` for any agent edits there, and delete untracked files "
           "outside the package (repro*.py, test_*.py at the root, anything written to /workspace/tmp)."),
      pains=["H1", "H2"]),
]
EVID = {'REPRO': '23 of the 47 unsolved v4 runs never ran pytest, against 8 of the 27 solved. Reported elsewhere: reproduction-test diagnosis adds 8.0 points in SWE-Doctor, and Agentless uses reproduction tests to rank patches.', 'EDIT': 'Across v4, 49% of edit_file calls were parse-rejected and only 13.6% changed a file (pain_points.md finding 1). 8 of the 47 unsolved v4 runs had 10 or more failed edits, against 2 of the 27 solved. Both misses among the 19 statements that give the fix away are escape-heavy regex edits that looped.', 'GATE': "rich_3180 v8 passes 114/114 once its one extra call-site edit is removed (per the record, verified locally). Three of four rich_4006 configs broke the existing tests/test_cells.py. fastapi_15588's three non-empty patches all failed at collection.", 'CONTEXT': '7 of the 47 unsolved v4 runs ended in ContextWindowExceededError, against 0 of the 27 solved. On the pod, 31 of 74 v4 tasks crossed the 14,336-token threshold and compaction shrank the prompt in 1 (pain_points.md finding 2).', 'SIBLING': 'In five tasks a config fixed one of two sites: fastapi_5077 (v6, v7), rich_3480 (v8), fastapi_14986 (v6, v7), fastapi_11194 (v8) and rich_3953 (v4, v7).', 'RETRY': "The union of the four configs solves 35 tasks against v4's 27. Eight of the 47 were solved by one or two other configs, which is the ceiling for a sampling-variance lever.", 'TERSE': 'v4 solves 3 of the 27 title-plus-link statements and 0 of the 5 wrong_location tasks.', 'HANG': 'No config solved any of the 6 performance_or_hang tasks. v4 hung on its own code in rich_3480 (555 s, on its repro) and fastapi_14448 (558 s, at import).', 'RUNTIME': 'In fastapi_14616 all four configs wrote Json checks that can never be true. `Json in metadata` misses because metadata holds a Json() instance.', 'NONEMPTY': '20 of the 47 unsolved v4 runs changed no source file, against 0 of the 27 solved. Most of those were caused by edit loops, overflow or hangs, so the flips are credited to EDIT, CONTEXT and HANG. This lever is the floor for the rest.', 'CONVENTION': "No config solved any hidden_spec task (0 of 19), and the host says the hidden set was screened for them, so this lever's public count overstates its hidden value.", 'HYGIENE': "15 of the 47 unsolved v4 patches carry scratch files and 5 touch tests/. rich_3454 v6's gold-identical source fix was lost because its test-file edit blocked the test_patch from applying."}
for l in LEVERS:
    l["evidence"] = EVID[l["key"]]
LEVER_BY_KEY = {l["key"]: l for l in LEVERS}
for t, (_, _, ks, _) in ASSIGN.items():
    for k in ks:
        assert k in LEVER_BY_KEY, (t, k)

# lever-specific tiers (a task can be 'likely' overall but only 'possible' for a lever that is not sufficient alone)
LEVER_TASKS = {
 "REPRO":     {"likely": ["rich_4075", "rich_3521", "rich_4079"],
               "possible": ["fastapi_11194", "fastapi_13920", "fastapi_14616", "rich_3472", "rich_3777", "rich_3782", "rich_3935"],
               "long": ["fastapi_14419", "rich_3468", "rich_3470", "rich_3934", "rich_4076", "rich_3535", "rich_3953"]},
 "EDIT":      {"likely": ["rich_3278", "rich_3454"],
               "possible": ["fastapi_15588", "rich_3043", "rich_3052"],
               "long": ["rich_3535", "rich_3944"]},
 "GATE":      {"likely": ["rich_3180", "rich_3278"],
               "possible": ["fastapi_14986", "fastapi_15588", "rich_3043", "rich_4006"],
               "long": ["rich_3934"]},
 "CONTEXT":   {"likely": ["fastapi_14851", "fastapi_5624"],
               "possible": ["fastapi_5077", "rich_4079"],
               "long": []},
 "SIBLING":   {"likely": ["fastapi_5077", "rich_3480"],
               "possible": ["fastapi_14986", "rich_3953"],
               "long": ["fastapi_14448"]},
 "RETRY":     {"likely": [],
               "possible": ["fastapi_11194", "fastapi_14851", "fastapi_5624", "rich_3454", "rich_3521", "rich_3777", "rich_4077", "rich_4079"],
               "long": []},
 "TERSE":     {"likely": ["rich_4077"],
               "possible": ["rich_3935", "rich_3782"],
               "long": ["rich_3944", "rich_4076", "rich_3471", "rich_3772"]},
 "HANG":      {"likely": ["rich_3480"],
               "possible": ["rich_3772", "rich_4006"],
               "long": ["fastapi_14448", "fastapi_14258"]},
 "RUNTIME":   {"likely": ["fastapi_14851"],
               "possible": ["fastapi_14616", "fastapi_13920"],
               "long": []},
 "NONEMPTY":  {"likely": [],
               "possible": ["rich_3782", "rich_3472"],
               "long": ["fastapi_14258", "rich_3105", "rich_3942"]},
 "CONVENTION": {"likely": [],
               "possible": ["fastapi_15588", "rich_3777"],
               "long": ["rich_3675", "fastapi_14479", "fastapi_14258"]},
 "HYGIENE":   {"likely": [],
               "possible": ["rich_3454"],
               "long": []},
}
for k, tiers in LEVER_TASKS.items():
    for tier, ts in tiers.items():
        for t in ts:
            assert t in UNSOLVED_V4, (k, t)

# expected flips: likely ~0.7, possible ~0.35 (rough priors, stated in the doc); RETRY uses measured per-config solve rate
P = {"likely": 0.7, "possible": 0.35}
def expected(k):
    if k == "RETRY":
        return sum(len(passes(t)) / 4 for t in LEVER_TASKS[k]["possible"]) * 0.7  # 0.7 = assumed gate detection rate
    return sum(P[tier] * len(LEVER_TASKS[k][tier]) for tier in ("likely", "possible"))

ORDER = ["REPRO", "EDIT", "GATE", "CONTEXT", "SIBLING", "RETRY", "TERSE", "HANG", "RUNTIME", "NONEMPTY", "CONVENTION", "HYGIENE"]
GEN = {"REPRO": "high", "EDIT": "high (same vLLM 0.19.1 parser on the scorer)", "GATE": "high", "CONTEXT": "high",
       "SIBLING": "high", "RETRY": "high, but costs time", "TERSE": "medium (hidden statements may carry more issue text)",
       "HANG": "high", "RUNTIME": "medium-high", "NONEMPTY": "high (floor, near-free)",
       "CONVENTION": "low-medium (hidden set screened for hidden specs)", "HYGIENE": "high (free insurance)"}

# measured blocker prevalence, v4, unsolved vs solved (control)
def prevalence(ids, cfg="v4"):
    g = [mech[t][cfg] for t in ids]
    return dict(
        n=len(g),
        no_src=sum(1 for x in g if x["no_src"]),
        overflow=sum(1 for x in g if "ContextWindow" in x["err"]),
        timeout=sum(1 for x in g if "timeout" in x["err"] or "turns budget" in x["err"]),
        edit_fail10=sum(1 for x in g if x["edit_rej"] + x["edit_nf"] >= 10),
        no_pytest=sum(1 for x in g if x["pytest"] == 0),
        touches_tests=sum(1 for x in g if x["touches_tests"]),
        scratch=sum(1 for x in g if x["scratch"]),
    )
PREV_U = prevalence(UNSOLVED_V4)
PREV_S = prevalence(SOLVED_V4)

PAIN_MAP = [
 ("0.1 / A5 / B1", "edit_file parse rejects (49-74%) and escaped old_strings (96% fail)", "EDIT (primary), CONTEXT (edit loops are what overflow)"),
 ("A1", "round-bracket / malformed calls fall through as text; 3 nudges end the task", "EDIT (short single-string calls), NONEMPTY"),
 ("A2", "bare openers silently dropped (fixed only in vLLM >= 0.27.1)", "EDIT (never write prose before a call), NONEMPTY"),
 ("A3", "offline-parser quote truncation", "none: not our parser path"),
 ("A4", "parser state shared across concurrent requests", "none for scoring (sequential); eval fidelity for 2-per-GPU pod runs"),
 ("A6", "integer args arriving as strings", "none: measured 3/552, not an issue"),
 ("B2", "whitespace/indent mismatch loops", "EDIT (whitespace tier, line-range primitive, loop breaker)"),
 ("B3", "str_replace editor beats generic edit tools", "EDIT (structured replace via run_command helper)"),
 ("B4", "blank lines left / final newline lost", "EDIT (helper preserves whole-line semantics)"),
 ("C1", "identical call repeated N times (35% exact repeats in v4, 58% of them edit_file)", "EDIT (loop breaker in helpers), RETRY"),
 ("C2", "low temperature -> verbatim retries", "RETRY (fresh sample), EDIT"),
 ("C3", "thought loops on long prompts (12B)", "none while thinking stays off"),
 ("D1", "32k window fills after ~20 full tool outputs", "CONTEXT"),
 ("D2", "orphaned function calls block ADK compaction", "CONTEXT (assume no compaction)"),
 ("D3", "tiny default contexts", "none: we have 32k"),
 ("D4", "partial reads -> hallucinated findings", "REPRO, RUNTIME (verify by running code, print real objects)"),
 ("E1", "thoughts re-sent as history", "CONTEXT (keep include_thoughts false)"),
 ("E2", "unbounded thinking", "CONTEXT (output cap); config"),
 ("E3", "reasoning/tool text leaks", "none: rare with thinking off"),
 ("F1", "model stops without a call / 'please provide the problem'", "NONEMPTY (restate the problem per stage, force an edit phase)"),
 ("F2", "system-prompt non-adherence past ~10k tokens", "CONTEXT (short prompts); put rules in helper error messages"),
 ("F3", "schema discipline drifts after 20-50 calls", "CONTEXT (fresh context per stage), GATE"),
 ("G1", "agent never runs tests (78 of 155 failing runs)", "REPRO, GATE"),
 ("G2", "tests or repros hang", "HANG (outer timeout), GATE"),
 ("G3", "env differences make gold fail", "eval fidelity (pins); also the rich_3782 label recheck"),
 ("H1", "scratch files in the patch (16 of 61 v4 patches)", "HYGIENE"),
 ("H2", "edits to tests break test_patch apply (4 rescored runs)", "HYGIENE"),
 ("I1", "one sample is noisy; selection needs a verifier", "RETRY, GATE (regression filter)"),
 ("I2", "fail fast and restart in a fresh context", "RETRY"),
 ("J1", "per-task caps vs the 12 h sequential cap", "constraint on REPRO/GATE/RETRY cost, not a lever"),
 ("J2", "slow decoding: every saved call buys exploration", "EDIT (810 repeated edit calls in v4), CONTEXT"),
 ("K1 / finding 3", "scorer runs the June template", "eval fidelity; EDIT's 'no prose before a call' also avoids the stray <turn|>"),
 ("K2", "alphabetical parameter order (new_string before old_string)", "EDIT (single-string helper makes order irrelevant)"),
 ("L1", "too many tools; code sandbox beats many small tools; compile check after every write", "EDIT, GATE, CONTEXT (short tool list per stage)"),
 ("L2", "malformed JSON needs repair", "EDIT (helpers tolerate escaped input and sloppy paths)"),
 ("M", "multi-line Python in bash; observation collapsing", "REPRO (write repros to files), CONTEXT (short outputs)"),
 ("Section 1", "hidden set from private repos, screened for impossible/hidden-spec tasks", "down-weights CONVENTION and all hidden-spec tasks; up-weights mechanics levers"),
 ("Finding 2", "pod ran without compaction; scorer config differs", "eval fidelity before trusting a race"),
]

# ---------------------------------------------------------------- counts
def cnt(key):
    return collections.Counter(key(recs[t]) for t in IDS)
BY_KIND = cnt(lambda r: r["kind"])
BY_REVEAL = cnt(lambda r: r["statement_reveals_fix"])
BY_FM = cnt(lambda r: r["failure_mode"])
BY_DIFF = cnt(lambda r: r["difficulty_5min"])
BY_TAG = collections.Counter(tag for t in IDS for tag in recs[t]["tags"])
BY_REPO = collections.Counter(recs[t]["repo"] for t in IDS)

def v4rate(ids):
    s = sum(1 for t in ids if inp[t]["kaggle_env_pass"]["v4"])
    return f"{s}/{len(ids)}"
def anyrate(ids):
    s = sum(1 for t in ids if passes(t))
    return f"{s}/{len(ids)}"

def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")

def outcome(t):
    p = passes(t)
    if len(p) == 4:
        return "all 4"
    if not p:
        return "none"
    return " ".join(p)

def gold(t):
    r = recs[t]
    return f"{len(r['gold_files'])}f/{r['gold_hunks']}h/{r['gold_lines_changed']}l"

# ---------------------------------------------------------------- JSON
pattern_of = collections.defaultdict(list)
for pid, _, _, ts in PATTERNS:
    for t in ts:
        pattern_of[t].append(pid)
lever_of = collections.defaultdict(dict)
for k, tiers in LEVER_TASKS.items():
    for tier, ts in tiers.items():
        for t in ts:
            lever_of[t][k] = tier

out_json = []
for t in IDS:
    r = dict(recs[t])
    r["kaggle_env_pass"] = inp[t]["kaggle_env_pass"]
    r["passing_configs"] = passes(t)
    r["pod_run_meta"] = inp[t]["pod_run_meta"]
    r["trace_mechanics"] = {c: {k: mech[t][c][k] for k in ("secs", "calls", "edit", "edit_rej", "edit_nf", "edit_ok", "pytest",
                                                         "repeats", "max_prompt", "empty", "no_src", "touches_tests")}
                            | {"error": mech[t][c]["err"], "scratch_files": mech[t][c]["scratch"]} for c in CFGS}
    r["one_line_solution"] = ONE[t]
    r["statement_title"] = stm[t].splitlines()[0] if stm[t] else ""
    r["statement_chars"] = len(stm[t])
    r["patterns"] = pattern_of.get(t, [])
    r["infeasible_5min"] = recs[t]["difficulty_5min"] == "infeasible"
    if t in ASSIGN:
        b, tier, ks, note = ASSIGN[t]
        r["v4_blocker"] = b
        r["flip_tier"] = tier
        r["levers"] = lever_of.get(t, {})
        r["flip_note"] = note
    else:
        r["v4_blocker"] = None
        r["flip_tier"] = "solved_by_v4"
        r["levers"] = {}
        r["flip_note"] = None
    out_json.append(r)
json.dump(out_json, open(f"{ROOT}/research/task_catalog.json", "w"), indent=1)

# ---------------------------------------------------------------- Markdown
L = []
w = L.append
w("# Task catalog: the 74 Kaggle-valid public tasks")
w("")
w("Written 2026-09-28. Sources: `research/tasks/*.json` (one record per task; 73 from the parallel workflow, "
  "`rich_3782` written in this step because the workflow stalled on it), `research/tasks/_inputs.json` (Kaggle-env pass per "
  "config), trace mechanics from `eval/eval3/eval/runs/p_v{4,6,7,8}/traces` and `task_results.jsonl`, and the pain-point "
  "sweep in `research/pain_points.md`. Machine-readable version: `research/task_catalog.json` (74 records, every field "
  "below plus per-config trace mechanics).")
w("")
w("**Where we stand.** v4 solves 27/74 in the Kaggle env; the union of v4/v6/v7/v8 solves 35/74. v4 scored **0.12** on the "
  "public leaderboard (about 58 hidden tasks) against 0.36 on these public tasks, so the hidden set is roughly 3x harder "
  "for this agent. The target is 0.30 on the hidden set. The host says the hidden tasks were screened so that a failing "
  "test is 'something it could have gotten correct with the information given'. That makes the mechanics and verification "
  "levers below worth more on the hidden set than levers that guess hidden names.")
w("")
w("**One label is disputed.** `rich_3782` v7 is scored FAIL by the Kaggle rescore (`eval/kaggle/rescore_fair`, exit 1), but "
  "on the task snapshot with Pygments 2.20.0 (the Kaggle kernel's pin) and Python 3.12 its patch passes `tests/test_syntax.py` "
  "25/25 and the full rich suite 853/853, identical to gold. Rerun it in the Kaggle env with test output captured before "
  "trusting the other FAIL labels blindly. Pod-env labels that differ from Kaggle (python-multipart missing, Pygments skew) "
  "are already overridden by the Kaggle result in every record.")
w("")
w("Contents: [1. All tasks](#1-all-tasks) · [2. Counts](#2-counts) · [3. Solution patterns](#3-recurring-solution-patterns) · "
  "[4. Levers](#4-ranked-generalizable-levers) · [5. Infeasible](#5-infeasible-for-a-5-minute-31b-agent)")
w("")
w("## 1. All tasks")
w("")
w("Gold size is files/hunks/lines changed. Outcome lists the configs that pass in the Kaggle env. Failure mode and "
  "difficulty come from the per-task record (`solved_by_*` means no config-wide failure mode).")
w("")
w("| id | PR | kind | reveals fix | gold | passes (Kaggle) | failure mode | difficulty | best solution (one line) |")
w("|---|---|---|---|---|---|---|---|---|")
for t in IDS:
    r = recs[t]
    num = r["pr_url"].rstrip("/").split("/")[-1]
    w(f"| {t} | [#{num}]({r['pr_url']}) | {r['kind']} | {r['statement_reveals_fix']} | {gold(t)} | {outcome(t)} | "
      f"{r['failure_mode']}{' (label disputed)' if r.get('label_disputed') else ''} | {r['difficulty_5min']} | {esc(ONE[t])} |")
w("")
w("## 2. Counts")
w("")
w(f"Repos: " + ", ".join(f"{k} {v}" for k, v in BY_REPO.most_common()) + ".")
w("")
def count_table(title, counter, idsel):
    w(f"**{title}**")
    w("")
    w("| value | tasks | v4 solves | any config solves |")
    w("|---|---|---|---|")
    for k, v in counter.most_common():
        ids = idsel(k)
        w(f"| {k} | {v} | {v4rate(ids)} | {anyrate(ids)} |")
    w("")
count_table("By kind", BY_KIND, lambda k: [t for t in IDS if recs[t]["kind"] == k])
count_table("By statement_reveals_fix", BY_REVEAL, lambda k: [t for t in IDS if recs[t]["statement_reveals_fix"] == k])
count_table("By failure mode", BY_FM, lambda k: [t for t in IDS if recs[t]["failure_mode"] == k])
count_table("By 5-minute difficulty", BY_DIFF, lambda k: [t for t in IDS if recs[t]["difficulty_5min"] == k])
count_table("By tag (a task carries several)", BY_TAG, lambda k: [t for t in IDS if k in recs[t]["tags"]])

REV = ["full", "partial", "none"]
w("**Cross-tab: failure mode x statement_reveals_fix**")
w("")
w("| failure mode | full | partial | none | total |")
w("|---|---|---|---|---|")
for fm, _ in BY_FM.most_common():
    row = [sum(1 for t in IDS if recs[t]["failure_mode"] == fm and recs[t]["statement_reveals_fix"] == rv) for rv in REV]
    w(f"| {fm} | " + " | ".join(str(x) for x in row) + f" | {sum(row)} |")
w("| **total** | " + " | ".join(str(BY_REVEAL[rv]) for rv in REV) + f" | {len(IDS)} |")
w("")
full = [t for t in IDS if recs[t]["statement_reveals_fix"] == "full"]
full_miss = [t for t in full if not inp[t]["kaggle_env_pass"]["v4"]]
none_ = [t for t in IDS if recs[t]["statement_reveals_fix"] == "none"]
none_fm = collections.Counter(recs[t]["failure_mode"] for t in none_)
w(f"What the cross-tab says: when the statement contains the fix, v4 solves {v4rate(full)}, and both misses "
  f"({', '.join(full_miss)}) are regex edits full of escape characters that died in the edit-parse loop, not reasoning "
  f"failures. When the statement reveals nothing, v4 solves {v4rate(none_)} (any config {anyrate(none_)}). Those {len(none_)} "
  f"break down as " + ", ".join(f"{k} {v}" for k, v in none_fm.most_common()) + ". Partial statements sit in between: "
  f"v4 {v4rate([t for t in IDS if recs[t]['statement_reveals_fix']=='partial'])}. No config solved any of the "
  f"{BY_FM['hidden_spec']} hidden_spec tasks, whatever the statement revealed.")
w("")
w("**Measured v4 blockers, unsolved vs solved (control).** From the pod traces. This is an association, not a controlled result.")
w("")
w("| signal (v4 run) | 47 unsolved | 27 solved |")
w("|---|---|---|")
for k, lab in [("no_src", "no change to any non-test source file"), ("overflow", "ended in ContextWindowExceededError"),
               ("timeout", "hit the 6-min session or turn budget"), ("edit_fail10", ">= 10 rejected or not-found edit_file calls"),
               ("no_pytest", "never ran pytest"), ("touches_tests", "patch touches tests/"), ("scratch", "patch includes scratch files")]:
    w(f"| {lab} | {PREV_U[k]} | {PREV_S[k]} |")
w("")
w("## 3. Recurring solution patterns")
w("")
w("A task can match several patterns. 'v4' is how many of the listed tasks v4 solves.")
w("")
for pid, name, move, ts in PATTERNS:
    w(f"**{pid}. {name}** (v4 {v4rate(ts)}, any config {anyrate(ts)})")
    w("")
    w(f"Move: {move}")
    w("")
    w("Tasks: " + ", ".join(f"`{t}`" for t in ts))
    w("")
w("## 4. Ranked generalizable levers")
w("")
w("Each lever is sized on the 47 tasks v4 does not solve. **Likely** means the lever removes the blocker seen in the v4 "
  "trace and another config (or v4 itself) already had the right fix or location. **Possible** means the blocker is removed "
  "but a further step is uncertain. **Long shot** tasks are listed but not counted. The expected-flip column uses rough priors "
  "of 0.7 per likely and 0.35 per possible task; for the retry lever it uses the measured share of configs that solved each "
  "task times an assumed 0.7 gate detection rate. Levers overlap, so the counts do not add up.")
w("")
w("| rank | lever | plausible flips (likely + possible) | expected flips | generalizes to unseen repos |")
w("|---|---|---|---|---|")
for i, k in enumerate(ORDER, 1):
    lt = LEVER_TASKS[k]
    w(f"| {i} | {LEVER_BY_KEY[k]['name']} | {len(lt['likely']) + len(lt['possible'])} ({len(lt['likely'])} + {len(lt['possible'])}) | "
      f"{expected(k):.1f} | {GEN[k]} |")
w("")
w("Ranking is by expected flips, adjusted for how well each lever transfers to unseen repos. One deliberate exception: EDIT "
  "is ranked above GATE although its public count is lower, for three reasons. Its failure rate is measured on the same "
  "vLLM 0.19.1 parser the scorer runs. The gate's feedback is useless if the fixer cannot land the follow-up edit. And it "
  "returns calls on every task: 810 of v4's 1,387 exact-repeat calls were edit_file retries.")
w("")
for i, k in enumerate(ORDER, 1):
    l = LEVER_BY_KEY[k]
    lt = LEVER_TASKS[k]
    w(f"### {i}. {l['name']}")
    w("")
    w(f"How: {l['how']}")
    w("")
    w(f"Evidence: {l['evidence']}")
    w("")
    w(f"- Likely: {', '.join(f'`{t}`' for t in lt['likely']) or 'none'}")
    w(f"- Possible: {', '.join(f'`{t}`' for t in lt['possible']) or 'none'}")
    if lt["long"]:
        w(f"- Long shot: {', '.join(f'`{t}`' for t in lt['long'])}")
    w(f"- Pain points it answers: {', '.join(l['pains']) if l['pains'] else 'none in the sweep; supported by the per-task records only'}")
    w("")
likely_union = sorted({t for k in LEVER_TASKS for t in LEVER_TASKS[k]["likely"]})
possible_union = sorted({t for k in LEVER_TASKS for t in LEVER_TASKS[k]["possible"]} - set(likely_union))
w("### Union and what it buys")
w("")
w(f"- At least one lever is likely to flip {len(likely_union)} tasks: {', '.join(likely_union)}.")
w(f"- A further {len(possible_union)} are possible: {', '.join(possible_union)}.")
w(f"- At the stated priors that is about {0.7*len(likely_union) + 0.35*len(possible_union):.0f} extra public tasks, "
  f"27 -> ~{27 + round(0.7*len(likely_union) + 0.35*len(possible_union))} of 74. The public-to-hidden gap (0.36 -> 0.12) "
  "means this does not translate one-for-one. The mechanics levers (edit, context, gate, hang, non-empty) are the ones "
  "most likely to carry over, because they fire on repo-agnostic failure signatures that are at least as common on the harder "
  "hidden set.")
w("- Ship order: EDIT + NONEMPTY + HYGIENE first (near-free, all mechanics), then one gate script that carries REPRO, GATE "
  "and HANG, then CONTEXT, then RETRY only if the per-task time left allows it. SIBLING, TERSE, RUNTIME and CONVENTION are "
  "prompt/protocol rules and can ride along with any of them.")
w("")
w("### Per-task assignment for the 47 v4-unsolved tasks")
w("")
w("| task | v4 blocker (from the trace) | configs that pass | overall tier | levers | note |")
w("|---|---|---|---|---|---|")
tier_rank = {"likely": 0, "possible": 1, "long": 2, "none": 3}
for t in sorted(UNSOLVED_V4, key=lambda t: (tier_rank[ASSIGN[t][1]], t)):
    b, tier, ks, note = ASSIGN[t]
    lv = ", ".join(f"{k}:{v}" for k, v in lever_of.get(t, {}).items())
    w(f"| {t} | {esc(b)} | {outcome(t)} | {tier} | {esc(lv) or '-'} | {esc(note)} |")
w("")
w("### Which lever each pain point supports")
w("")
w("The sweep (`research/pain_points.md`) was on disk even though the workflow reported it unavailable, so it is mapped in "
  "full here.")
w("")
w("| pain point | problem | lever(s) it supports |")
w("|---|---|---|")
for pid, prob, lev in PAIN_MAP:
    w(f"| {pid} | {esc(prob)} | {esc(lev)} |")
w("")
w("## 5. Infeasible for a 5-minute 31B agent")
w("")
inf = [t for t in IDS if recs[t]["difficulty_5min"] == "infeasible"]
w(f"{len(inf)} tasks are marked infeasible in their records. Every one is a hidden-spec task: the hidden test pins a name, "
  "message or rendering the statement does not give. The host says tasks like these were screened out of the hidden set, so "
  "effort spent on them buys nothing there. The right agent behaviour is to triage early, submit the cheapest plausible "
  "change, and move on.")
w("")
w("| task | why it is infeasible | gold size |")
w("|---|---|---|")
WHY = {
 "fastapi_14258": "Guard is easy; hidden test matches the exact merged AssertionError message.",
 "fastapi_14479": "Hidden test matches the reviewer-edited wording; the statement shows only the pre-review draft.",
 "fastapi_14487": "Exact 'Validation errors:' / 'Field: <loc>' output strings appear nowhere in the statement.",
 "fastapi_15280": "April Fool's PR; the raise and its message exist only in the hidden test.",
 "fastapi_15661": "Empty PR template; tests import scripts.prepare_release and its CLI names.",
 "fastapi_15800": "654-line feature with hidden kwargs (fallback, check_dir), internals and docs_src examples.",
 "rich_3061": "Tests assert exact _spans lists and a new public Text.extend_style.",
 "rich_3105": "'Fix #3104' only; the exact inline-style string is not derivable.",
 "rich_3930": "12,714-line grapheme feature; tests import CellSpan and rich._unicode_data.",
 "rich_3938": "Tests call a new Segment.split_lines_terminator helper by name.",
 "rich_3942": "Maintainer restyle by taste; golden ANSI snapshots are the only spec.",
}
for t in inf:
    w(f"| {t} | {esc(WHY[t])} | {gold(t)} |")
w("")
hard = [t for t in IDS if recs[t]["difficulty_5min"] == "hard" and not passes(t)]
w(f"Near-infeasible in 5 minutes (marked hard, never solved by any config): {', '.join(hard)}. These need multi-layer "
  "reasoning (fastapi_14448's seven wrapper layers), a hidden semantic choice (rich_3470's 'record what was emitted', "
  "rich_3535's box-drawing range, fastapi_14306's endpoint_ctx kwarg) or an issue text the agent cannot read (rich_3944, "
  "rich_4076). Budget them like the infeasible set unless a lever surfaces the fix early.")
w("")
w("## Method and caveats")
w("")
w("- Outcomes are the Kaggle-env labels in `_inputs.json` (rescore of the pod patches). Pod-env failures caused by the "
  "environment were overridden there, not here.")
w("- Trace mechanics: an edit_file call is rejected when its observation says 'mandatory input param', not-found when it says "
  "'not found'; overflow and timeout come from `task_results.jsonl` errors; 'no source change' means the patch touches no "
  "file outside tests/, root-level test_/repro/verify scripts and docs/config. Code: `research/catalog_build/mech.py`; "
  "catalog build: `research/catalog_build/build_catalog.py`.")
w("- Tiers are judgement calls from each task's record and trace, stated per task in section 4. Priors of 0.7 and 0.35 are "
  "assumptions, not measurements. The v9/v10 race arms are the controlled test of these levers.")
w("- Only public tasks are here. The hidden set comes from private repos, so any lever tuned to fastapi/rich specifics "
  "(names, idioms) is excluded from the ranking on purpose.")
open(f"{ROOT}/research/task_catalog.md", "w").write("\n".join(L) + "\n")

# summary to stdout
print("records", len(IDS), "unsolved_v4", len(UNSOLVED_V4))
print("prev unsolved", PREV_U)
print("prev solved", PREV_S)
for i, k in enumerate(ORDER, 1):
    lt = LEVER_TASKS[k]
    print(i, k, len(lt["likely"]), len(lt["possible"]), round(expected(k), 2))
print("likely union", len(likely_union), "possible extra", len(possible_union))
print("reveal full v4", v4rate(full), full_miss, "none v4", v4rate(none_))
