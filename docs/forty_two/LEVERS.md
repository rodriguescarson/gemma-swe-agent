# Levers in submissions/v13 (Phase C)

v13 starts as a byte-identical copy of submissions/v12-b1024 (our current line: one thinking-on agent, budget 1,024, 28/74 on the
box as p4_b1024). Each lever below is one commit, test first (tests/test_v13_bundle.py: written, run red, then implemented and
run green), with offline evidence measured on the Mac without the model. Phase A's evidence is docs/forty_two/TIMING.md.
`python scripts/validate.py submissions/v13` passes after every lever. The leakage test (tests/test_v13_leakage.py) covers the
whole bundle.

Evidence commands (all offline, seconds):

    PY=.venv/bin/python
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
- rich_4075: the cloud dossier (LOG_rich.md) finds b1024 had the right repro and cause by 43 s, then 3 malformed edits and the
  40-call budget ran out (BudgetExceeded). Expected: maybe-to-yes (a 1-line fix; also UNDERSPECIFIED, 1/12 L4).
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

Two corrections to the replay found while running it: (1) the box's edit engine has an "unescaped" tier that the Mac's
adk_eval_core 0.1.0 lacks, so 13 successful box edits per run (over-escaped quotes such as `\"\"\"`) could not be re-applied
offline and their files dropped out of the replay ("state lost"); the template would refuse those as written. Over-escaping is a
habit of the edit_file argument channel: among argument strings that contain a double quote, 25 of 131 (b1024) and 33 of 132
(v0t2) edit_file old/new strings carried `\"`, against 3 of 183 python heredoc commands on b1024. (2) The template must run
under the sandbox's Python 3.12: under macOS's /usr/bin/python3 (3.9) newer syntax fails to compile, so the tests and the replay
put the venv's interpreter first on PATH.

## Lever 2: per-command timeout 180 -> 60 s (eval_config.yaml timeout_seconds)

**What it changes.** `timeout_seconds: 180` -> `60`. The task budget is unchanged: 5 minutes, 40 tool calls, 150 turns
(tests/test_v13_bundle.py checks the file differs in that one value and that the harness's EvalConfig reads 60 as
command_timeout_seconds with budget (5, 40, 150)). This does not touch the 12-hour arithmetic: the cap per task stays 5 minutes.

**Why (MEASURED, TIMING.md sect. 7).** 15,090 run_command calls in 592 traces (six box runs, two Kaggle L4 runs): 15,069
finished, the longest legitimate ones `find /` 58 s and `curl` 32 s (both on L4, both pointless), then `pytest tests/` 7.5 s.
Every command at 60 s or more was a hang. On p4_b1024 four of the 42 lost 749 s to hangs: fastapi_14258 181 s, rich_3480 209 s,
rich_4006 198 s, rich_3052 161 s (the last one still running when the cap fired, so its trace has no observation).

**Offline evidence (docs/forty_two/evidence/hang_replay.txt, `scripts/forty_two/hang_replay.py`).** Each recorded hang re-run on
the Mac in a copy of the task snapshot brought to the agent's state at that moment (its earlier writes and edits), with the
task's offline venv, bounded at 60 s: 7 of 8 were still running at the bound (fastapi_14258 x2 runs, rich_3480 x3, rich_4006 x2);
the v0t2 rich_3480 repro reached 4.7 GB in 28 s (on Kaggle's 4 GB container it would be killed with exit 137, on the box's
subprocess sandbox it ran to the timeout). The 8th, rich_3052, could not be reproduced: two of the agent's edits did not
re-apply offline (see lever 1, correction 1), so its replayed state lacks them and it failed fast instead. So the extra 120 s
the old limit allowed bought nothing in any reproducible case.

**Which of the 42 it should flip, and why.** Time back on the four hang tasks: rich_3480 and rich_4006 (two hangs each, 6 calls
in 300 s on b1024; up to ~240 s back), rich_3052 (~100 s, inferred), fastapi_14258 (~120 s). The hang is the bug's own symptom
(infinite loops); the fix still has to be right. Expected: maybe for rich_3480, rich_4006 and rich_3052 (rich_4006 and rich_3480
touched a gold file in older runs; their cloud dossiers had not landed when this was written); no for fastapi_14258, whose cloud
dossier (LOG_fastapi.md) finds a HIDDEN_SPEC (the test pins an exact 95-character message) and itself recommends this lever for
the time it wastes (553 s of tool time over the six runs).

**Risk to the 32 tasks we solve sometimes.** None seen in the agent phase (no legitimate command over 58 s). The real risk is
verification: in the local harness and on the box, timeout_seconds is also the verification pytest limit
(research/harness_runtime.md sect. 7.4, swegemma verification.py). Gold verification takes at most 12.6 s on Kaggle L4 for the 74
valid public tasks and agent-patch verification at most 6.9 s on the box, so 60 s is 4.7x the slowest; research/harness_runtime.md
item 10 already set >= 60 s as the floor. Whether Kaggle's Stage 2 metric reads this value is UNVERIFIED (research/gap_5.md
sect. 9); a hidden repo whose target tests take over 60 s would fail verification if it does. Fallback if the screen or a later
read shows a verification timeout (exit 124 on a non-hanging patch): 90 s.

## Considered and not built (with the reason)

- **Issue text pinned in the instruction (`{problem_description}`).** Compaction (26 of the 42 tasks) summarises the issue away;
  the system instruction survives it. Not built: no measured effect (re-reads after compaction are of files, not the issue), and it
  adds 134 tokens per call (median; 540 at p90), which moves the compaction threshold earlier. Worth a separate read.
- **Thinking budget 1,024 -> 512.** About 27 s per task back on the 42 (15 s on solved; thinking tokens above 512 per call,
  char-share estimate, TIMING.md sect. 12; 41 s is the upper bound if visible output were cut too); but the long-thinking
  calls are where edits are designed, and the 4,096 -> 1,024 step was neutral on 50 ids (19 vs 19). A single-variable read on
  its own, after v13.
- **Faster search tools, async tool execution, parallel tool calls.** Tools take under 0.02 s per non-hung call; the model
  emitted more than one call per turn in 0 of 1,688 b1024 turns.
- **Narrower reads, lower max_tool_calls, lower temperature.** See TIMING.md sect. 11.
- **Fix-quality rules from the cloud dossiers** (fail-first repro, sibling sweep of the replaced expression, run the module's test
  file once, no identical resend). Not timing levers; the prompt already carries the sibling and no-identical-resend rules. Left for
  the main session once all dossiers have landed.

## Summary

| lever | files | evidence (offline) | the 42 it should flip | expected | risk to the 32 |
|---|---|---|---|---|---|
| 1 edits through run_command | agent.yaml, prompts/system.md | 101 of 478 multi-argument edit/write calls malformed vs 0 of 1,521 run_command (two runs); vLLM parser reproduces the slip; template reproduces 148 of 153 replayable exact edits byte for byte and refuses the other 5 because the file would not compile | rich_3718 yes; rich_4075, fastapi_14616, fastapi_9753 maybe | +1 to +2 | ~3.5 s per edit; 2 solved tasks with intermediate uncompilable edits need a retry |
| 2 per-command timeout 60 s | eval_config.yaml | no finished command >= 60 s in 15,090; 7 of 8 recorded hangs still running at 60 s | rich_3480, rich_4006, rich_3052 maybe; fastapi_14258 no (hidden spec) | +0 to +1 | verification limit on the box (and on Kaggle if Stage 2 reads it): slowest valid verification 12.6 s |
