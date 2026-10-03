import json, os
SP = os.path.dirname(os.path.abspath(__file__))
rows = {(r["src"], r["task"]): r for r in json.load(open(SP + "/rows_all.json"))}
A = {
("L","rich_2725"): ("M1 T5 T6", "gold Table._render viewed at call 3; after one repro with box characters and reasoning comments, 13 run_command calls arrived with empty args (the first 3 were 768-token runaway outputs); the router cap served 'done'"),
("L","rich_2943"): ("ok", "locate rank 3; view Style.clear_meta_and_links at call 2; one repro, fails on original"),
("L","rich_3043"): ("ok", "grep CONSOLE_HTML_FORMAT at call 5; one run.py unbalanced-quote error"),
("L","rich_3063"): ("ok T1", "4 repro attempts, reasoning written as comments inside the heredoc"),
("L","rich_3067"): ("M1 T1 T3 T6", "found url regex in highlighter.py at call 4-5; repro asserted span count (not span end) and passed 5 times; drifted to markdown.py; 17 calls after LOCATOR/EDIT NOW; never replied"),
("L","rich_3105"): ("M6", "'See #3104' only; locate/grep '3104'; replied with an apology asking for the issue text"),
("L","rich_3180"): ("ok M7", "missing gold fn words() is type hints and a docstring only"),
("L","rich_3278"): ("ok T4", "read_file rich/ansi.py 3 times; identical repro run 3 times"),
("L","rich_3470"): ("T6", "clean progress on console.py (locate rank 1); two calls took 114.9 s and 116.7 s of 429 retries; L4 26 s"),
("L","rich_3471"): ("T6 T2", "gold at call 1-2; run.py with unbalanced quotes 4 times, then bare python3 -c (no footer); 113.8 s and 118.2 s retry calls"),
("L","rich_3472"): ("T6 T2", "pretty.py rank 1; python -c with decorators (SyntaxError); guessed Pretty.render and print(pretty=True); first call 69.6 s"),
("L","rich_3506"): ("ok", "prose before FILES; repro never failed (REPRO: none)"),
("L","rich_3518"): ("ok T4 T6", "right plan; 112.8 s and 117.2 s retry calls pushed the proxy clock to 299; Table docstring read in 5 pages"),
("L","rich_3521"): ("ok T2 T3", "33 run.py probes of split_cells (8 identical), all after the stop line; L4 147 s"),
("L","rich_3535"): ("M7", "missing rich/segment.py is an assert plus docstring; hidden test only covers cells.py"),
("L","rich_3675"): ("M7", "missing diagnose.py is an env-name list (pragma no cover); NO_COLOR change in __init__ is not in the issue"),
("L","rich_3676"): ("M5 T1", "__notes__ feature; new style 'traceback.note' needs rich/default_styles.py; 13 repro attempts all pass (feature has no failing assertion); compaction then re-search; L4 181 s"),
("L","rich_3718"): ("ok", "right plan"),
("L","rich_3772"): ("M2 T1", "title-only 'traceback recursion'; blamed install.excepthook, gold is Traceback.extract cause/context loop; 7 repro attempts"),
("L","rich_3777"): ("M7", "missing diagnose.py env-name list; grep TTY_COMPATIBLE listed it at call 2"),
("L","rich_3782"): ("M1", "final reply is a 768-token thinking dump with a code block and no FILES line; 6 repro attempts"),
("L","rich_3894"): ("ok T2", "15 run.py calls with '\\n' inside python -c, SyntaxError every time"),
("L","rich_3935"): ("ok M7 T2", "4 of 5 gold fns are blank-line hunks; 17 run.py probes"),
("L","rich_3938"): ("M5", "gold adds Segment.split_lines_terminator in segment.py; hidden tests call it by name"),
("L","rich_3953"): ("M2 T1", "second linked issue ('edge cases': non-printable width in get_character_cell_size) never considered; 5 repro attempts with reasoning comments"),
("L","rich_4006"): ("ok T2 T3", "36 run.py calls, the same command 20+ times despite 'same output 3 times'; reply has two FILES blocks and 'Wait,'"),
("L","rich_4075"): ("ok M7", "missing save_text is a signature reflow"),
("P","fastapi_13537"): ("ok", ""),
("P","fastapi_13920"): ("M2 T2", "locate rank 2 = gold utils.py, viewed analyze_param at call 15; plan picks _compat/shared.py WithArgsTypes; 8 bare python -c"),
("P","fastapi_14077"): ("M4 T2", "grep at call 1 listed docs_src/handling_errors/tutorial005.py; plan omits it (resolved anyway); 16 run.py incl. pip install and 9 identical deprecation checks"),
("P","fastapi_14301"): ("ok T1", "6 repro attempts, first failing one is the 6th"),
("P","fastapi_14306"): ("ok", ""),
("P","fastapi_14372"): ("M4", "locate rank 3 dependencies/utils.py (analyze_param) not in plan; resolved anyway"),
("P","fastapi_14419"): ("M4 T1", "viewed utils.py get_dependant and solve_dependencies (calls 3-7); plan names models.py only; 5 repro attempts, 4 pass"),
("P","fastapi_14448"): ("M1", "stage ended on a text tool call: run_command{... /tmp/swe/run_command {cat <<'EOF' > repro.py ...}}"),
("P","fastapi_14458"): ("ok", ""),
("P","fastapi_14463"): ("ok", ""),
("P","fastapi_14479"): ("ok", ""),
("P","fastapi_14487"): ("ok T3", "docs-only target found at call 37; 27 greps; 24 calls after CONTEXT"),
("P","fastapi_14786"): ("ok", "plan written after '//' comment lines"),
("P","fastapi_14794"): ("ok", ""),
("P","fastapi_14851"): ("ok", "prose before FILES"),
("P","fastapi_14873"): ("M1", "after 1 call the stage ended on text 'call:python3 /tmp/swe/view.py fastapi/routing.py APIRouter.__init__' (helper used as a tool name); counted as a hit by the path in it; resolved anyway"),
("P","fastapi_15280"): ("M5", "gold adds a new docs_src/vibe/tutorial001_py310.py"),
("P","fastapi_15588"): ("ok T1 T2", "6 repro attempts, 8 run.py"),
("P","fastapi_5077"): ("ok T1", "first failing repro at attempt 6"),
("P","fastapi_9425"): ("M2 T2", "locate rank 1 = gold utils.py, viewed get_typed_return_annotation at call 2; plan picks routing.py call site; resolved anyway; 12 run.py"),
("P","fastapi_9555"): ("ok", ""),
("P","fastapi_9753"): ("M3", "locate top 3: scripts/notify_translations.py, routing.py, a test; gold dependencies/models.py never shown; plan picks utils.py get_typed_signature"),
("P","requests_6644"): ("M2", "locate rank 1 = adapters.py, viewed 369-396; plan picks models.py path_url although the issue names ConnectionPool/request-uri"),
("P","rich_2725"): ("M1", "stage ended on a text tool call carrying the repro heredoc (box chars); counted as a hit by the path in it; resolved anyway"),
("P","rich_2943"): ("M1 T2", "no final text at all; heredoc piped into run.py 3 times gave '(no output)' (stdin is /dev/null); resolved anyway"),
("P","rich_3043"): ("ok", "FILES line spells rich/_export_foramt.py (typo); the prose above it has the right path"),
("P","rich_3063"): ("ok M8 T1", "plan blames _parse, gold is escape(); 6 repro attempts"),
("P","rich_3067"): ("M3", "never ran locate; grep --path with 6 invented dirs; never saw highlighter.py; plan picks Style.parse; 41 calls"),
("P","rich_3105"): ("M6", "curl to github.com 9 times, git log --grep, grep/locate '3104'; 28 calls; prose reply"),
("P","rich_3180"): ("ok M8", "plan names chop_cells only with a different cause; L4 117 s"),
("P","rich_3278"): ("ok", ""),
("P","rich_3468"): ("ok", ""),
("P","rich_3470"): ("ok M8 T4", "plan (prose first) blames end_capture; gold _write_buffer; 15 views"),
("P","rich_3471"): ("ok M8", "plan blames 'if style:'; gold strips control codes like append/__init__"),
("P","rich_3472"): ("M2 T3 T4", "pretty.py rank 1 viewed in 7 pages; after the 3rd locate drifted to console.py ConsoleOptions; 22 calls after CONTEXT"),
("P","rich_3480"): ("ok M8 T2", "plan fixes append only (self-reference); gold snapshots spans in append and append_text; 25 run.py (10 identical)"),
("P","rich_3506"): ("ok M8 T2", "prose plan, vague cause; 21 run.py"),
("P","rich_3518"): ("ok", ""),
("P","rich_3521"): ("ok T2", "16 run.py (10 identical)"),
("P","rich_3535"): ("M7", "saw segment.py via grep of _is_single_cell_widths users; change there is incidental"),
("P","rich_3675"): ("M7", ""),
("P","rich_3676"): ("M5", "default_styles.py not found; 12 views of traceback.py"),
("P","rich_3718"): ("ok M8", "plan changes console.render style; gold restyles the title with the combined border_style"),
("P","rich_3772"): ("ok", "names Traceback.extract (the L run did not)"),
("P","rich_3777"): ("M7", ""),
("P","rich_3782"): ("ok T2", "13 run.py"),
("P","rich_3894"): ("ok", ""),
("P","rich_3935"): ("M2", "locate: padding.py 41.8 vs table.py 41.7; grep padding_width at call 2 showed Table._get_padding_width; plan picks Padding.__rich_measure__"),
("P","rich_3938"): ("M5", "segment.py new helper (see L)"),
("P","rich_3953"): ("M1", "after 2 greps the stage ended on text 'call:python3 /tmp/swe/view.py rich/cells.py'; counted as a hit by the path in it"),
("P","rich_4006"): ("ok", "L4 112 s"),
("P","rich_4075"): ("ok T1", "6 repro attempts"),
("P","rich_4077"): ("ok T2", "13 run.py"),
("P","rich_4079"): ("ok T2", "17 run.py (12 identical); prose plan"),
}
missing = [k for k in rows if k not in A]
assert not missing, missing
out = []
for src in ("L", "P"):
    out.append("| src | task | gold files named | gold fns named | calls | L4 s | end | modes | evidence |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for k in sorted(k for k in rows if k[0] == src):
        r = rows[k]; m, ev = A[k]
        l4 = r["l4"]
        end = {"plan": "plan", "prose_then_plan": "prose+plan", "prose_no_plan": "no FILES", "text_tool_call": "text tool call", "empty": "empty", "capped_no_plan": "capped"}[r["reply_kind"]]
        out.append("| %s | %s | %d/%d | %s | %d | %s | %s | %s | %s |" % (src, k[1], r["named"], r["ngold"], ("%d/%d" % (r["fnamed"], r["nfn"])) if r["nfn"] else "-", r["calls"],
                   ("%.0f" % l4) if l4 is not None else "-", end, m, ev))
    out.append("")
open(SP + "/case_table.md", "w").write("\n".join(out))
import collections
for src in ("L", "P"):
    c = collections.Counter()
    for k, (m, _) in A.items():
        if k[0] == src:
            for t in m.split():
                c[t] += 1
    print(src, dict(sorted(c.items())))
