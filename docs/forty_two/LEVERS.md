# Levers in submissions/v13 (Phase C)

v13 starts as a byte-identical copy of submissions/v12-b1024 (our current line: one thinking-on agent, budget 1,024, 28/74 on the
box as p4_b1024). Each lever below is one commit, test first (tests/test_v13_bundle.py: written, run red, then implemented and
run green), with offline evidence measured on the Mac without the model. Phase A's evidence is docs/forty_two/TIMING.md.
`python scripts/validate.py submissions/v13` passes after every lever. The leakage test (tests/test_v13_leakage.py) covers the
whole bundle.

Evidence commands (all offline, seconds):

    PY=/Users/carson/Projects/gemma-swe-agent/.venv/bin/python
    $PY -m pytest -q tests/test_v13_bundle.py tests/test_forty_two_evidence.py tests/test_v13_leakage.py -p no:cacheprovider
    $PY scripts/forty_two/timing_report.py           # Phase A numbers
    $PY scripts/forty_two/edit_replay.py             # lever 1 replay (output in docs/forty_two/evidence/edit_replay.txt)

## Lever 1: edits through run_command only (agent.yaml, prompts/system.md step 3)

**What it changes.** edit_file and write_file leave the agent's tool list (now run_command, read_file, get_status,
submit_patch). Step 3 of the prompt teaches one shell command per change:

    python3 - <<'EDIT'
    from pathlib import Path
    p = Path("path/to/module.py")
    old = r'''
    <old lines, copied exactly>
    '''.lstrip("\n")
    new = r'''
    <new lines>
    '''.lstrip("\n")
    s = p.read_bytes().decode()
    assert s.count(old) == 1, s.count(old)
    s = s.replace(old, new)
    if p.suffix == ".py":
        compile(s, str(p), "exec")
    p.write_bytes(s.encode())
    print("edited", p)
    EDIT

New files: `cat > path <<'EOF'`. The rest of the prompt is v12-b1024's word for word (test: everything before "3. Edit" and
after "4. Check." is identical).

**Why (MEASURED, TIMING.md sect. 6).** On p4_b1024, 84 of 228 edit_file/write_file calls (37 %) came back "mandatory input
parameters are not present": 883 s over 11 tasks, 560 s of it on 5 of the 42. On p4_v0t2 (temperature 0.2), 17 of 250 (7 %).
In both runs 0 of 1,521 run_command calls were malformed, including 177 python heredocs on p4_b1024. Mechanism (vLLM v0.19.1
gemma4 parser, vendored in scripts/forty_two/gemma4_args_vllm.py): when the model closes the first code string with a backtick
or quote instead of `<|"|>`, the parser reads the next argument's name into the string and the following code becomes junk keys,
so old_string (or filepath) is lost; the model then resends the same malformed call (rich_3718: 21 times, 226 s).
tests/test_forty_two_evidence.py reproduces the recorded shape with the real parser and shows that the same slip in a
single-argument call keeps the whole command, and that a slipped template command writes nothing (python parses the whole
script before running it, so the stray character is a SyntaxError).

**Offline evidence for the new path (docs/forty_two/evidence/edit_replay.txt, `scripts/forty_two/edit_replay.py`).** Every
edit_file call of p4_b1024 and p4_v0t2 replayed on the task snapshots, following each agent's own trajectory, through
swegemma's edit engine and through the template run by bash with Python 3.12:
- Successful exact edits: the template wrote a byte-identical file in 68 of 72 (p4_b1024) and 80 of 81 (p4_v0t2). It refused
  the other 5, all because the edited file would not compile: fastapi_15280 (b1024, unsolved) replaced `    def get(` without
  putting it back, a corrupting edit edit_file accepted; fastapi_9555 wrote an unterminated string into a repro script;
  fastapi_14458 (b1024, solved) made two intermediate edits that left a parenthesis open and closed it with a later edit, and
  fastapi_14794 (v0t2, solved) wrote an over-escaped f-string and repaired it next call. Under the template those two solved
  tasks would need to make each edit complete in one command (a retry each, ~15 s), not fail.
- Failed edit_file calls (old_string not found etc.): the template also refuses them (8 of 8 b1024, 11 of 11 v0t2; a 12th
  v0t2 call failed only because the 40-call budget was spent, and the template would have applied it).
- Malformed calls: the new_string the model meant is intact up to the swallowed tail, but the old block is usually destroyed by
  the parser (no colon inside it means nothing is left). Where the old block could be located (rich_3718, 6 calls), the
  intended edit applies and compiles through the template.

**Which of the 42 it should flip, and why.**
- rich_3718: p4_b1024 had the right title change written at 85 s and could not apply it (21 malformed calls, 226 s); p4_v0t2
  solved it with no malformed loop; 9 of 12 L4 runs solved it. The cloud dossier (rich_3718) adds that the subtitle sibling is
  also needed; the prompt's sibling rule is unchanged. Expected: yes (maybe on any one run).
- fastapi_14616 (153 s lost; 4/12 L4) and fastapi_9753 (148 s lost; 2/12 L4): time back, but the cloud dossiers find fix-quality
  causes as well (WRONG_SEMANTICS / WRONG_LOCATION). Expected: maybe.
- Indirectly every task that edits, through the compile check (no uncompilable patch can be written, fastapi_15280 type).

**Risk to the 32 tasks we solve sometimes.** The 5 solved-in-b1024 tasks that hit malformed calls (rich_3454 98 s, rich_3043
80 s, fastapi_14463 70 s, fastapi_11194 17 s, rich_3067 10 s) get that time back. Costs: the template is ~16 lines per edit
(~120 more output tokens, ~3.5 L4-seconds per edit, ~10 s per solved task at 3 edits); multi-step edits that pass through an
uncompilable state must be redone as one edit (2 of 72 successful edits on b1024, one solved task); the r''' strings need the
other quote style when the code contains three single quotes; no whitespace-tolerant matching (edit_file's flexible tier was
used 0 times in the replay, all successes were exact). The model writes python heredocs fluently on this line (177 on
p4_b1024; 3 of 255 python commands hit a SyntaxError). The harness's ToolErrorPlugin (installed swegemma 0.2.11,
agent_runner.py:244) turns a call to a dropped tool into an error reply, not a crash.
