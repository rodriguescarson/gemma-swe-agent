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
