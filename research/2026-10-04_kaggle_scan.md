# Kaggle scan, 2026-10-04 (read-only)

Sources: `kaggle competitions leaderboard`, `kernels list/pull` (16 notebooks), `competitions topics show --format json` (35 threads). Raw files: `SP/nb/`, `SP/forum1004/` (SP = session scratchpad). Paper-track writeups are not readable by CLI or WebFetch (JS only), so none were read. Nothing was submitted or posted.

## 1. Verified facts

**The board moved after the 09-30 wheelhouse fixes.** The public split has 58 tasks, so 1 task ≈ 0.017. In the top 200, all 0.15+ scores and 93 of 130 scores at 0.13 were submitted 10-02 to 10-03. Before that, the cluster sat at 0.12. In tasks: 0.24 = 14, 0.17 = 10, 0.15 = 9, 0.13 = 8, 0.12 = 7, 0.10 = 6. The leader ("ТониСтарк собрал реактор в яме", 10-03) has no public notebook or post. Five teams are at 0.17, all from 10-03. **Any of our scores from before 10-01 are not comparable with today's board.**

**Host-confirmed fixes in the 09-30 wheelhouse** (Holbrook, 744794 / 744354 / 744272 / 744566):
- Thoughts are now kept between tool calls.
- Tool output is JSON-encoded once, and `edit_file` has an unescape fallback.
- `thinking_budget` and `seed` are now forwarded.
- vLLM sizes LoRA to the adapters you actually ship.
- **Still open:** a 12 h overrun can error the whole run, and the compaction threshold is not confirmed.

**Best public bundle with a claimed score: hsiaosuan, 0.13 on 10-03** (`kaggle.com/code/hsiaosuan/gemma-developer-agent-0-13-submission`, zip decoded):
- `agent_class: SequentialAgent`. An explore stage (`output_key: repair_plan`) feeds a coder that has no AgentTool.
- **eval_config:** `timeout_seconds: 60`, `max_tool_calls: 60`, `max_time_minutes: 5`, `max_turns: 100`.
- **Explore:** T 0.1, `max_output_tokens: 4096`, `thinking_budget: 1024`. **Coder:** T 0.2, `max_output_tokens: 8192`, `thinking_budget: 2048`. Both use `include_thoughts: false`.
- **Explore prompt:**
  - one bounded `rg` search, then a source read;
  - at most one `get_code_neighbors(max_neighbors=8)` on a *qualified method name*, plus one `get_code_subgraph`;
  - `search_similar_code` is explicitly banned;
  - output is a plan of at most 100 words that quotes the source lines.
- **Coder prompt:** edit before any reproduction; `git diff --check`; one assertion of at most 6 lines that must exit nonzero on failure and checks both the new and an old behavior; then submit immediately.
- **Skills:** `swe-workflow` and `verify-before-submit`.

**Roman Rozen's bundle** (verified by SHA, also inside Black Cat and SuperAgent) scored 0.12 and 0.15 byte-identical (0.15 was kozykappa's copy). Black Cat's v10 is the same bundle and scored 0.12.
- Root `swe_coder` with an `agent_tool` analyzer (`skip_summarization: true`).
- T 0.2, top_k 40, `max_output_tokens: 8192`, `thinking_budget: 4096`, `include_thoughts: false`.
- **No eval_config, so there is no per-task limit.** A fork took 14.5 h to score (Geremie Yeo, 743140).

**Black Cat:**
- v12 "state-card" protocol: **0.05**. v10: 0.12 (checked 10-03).
- v13 challenger (unscored): `timeout_seconds: 300`, `max_tool_calls: 100`, `max_time_minutes: 5`, `max_turns: 250`.

## 2. Harness traps with evidence (code-read and local traces by participants)

1. **`include_thoughts: false` turns thinking OFF in adk_submission 0.2.12.** It maps to `enable_thinking: false`, so any `thinking_budget` is ignored (Anthony Chiu 745059, confirmed by Syurolh).
   - So the 0.13 and 0.12/0.15 bundles all run **without thinking**.
   - Our v4h2f and v4h2g also set `include_thoughts: false`, so they run without thinking too. v4h_think runs with thinking on (LOW).
2. **Undeclared or hallucinated tool calls end the task with an empty patch** (745028, Zhukov). The task message always advertises the graph tools. Whisper Last saw Gemma call `search_similar_code` 142 times across 91 of 129 tasks, and 140 of those calls returned nothing.
3. **Graph tools only match exact names** (745220, 745731):
   - Ids must be full dotted names.
   - `edge_type` must be lowercase `calls` or left out.
   - `search_similar_code` cannot embed free text.
   - Neighbors are cut alphabetically at 50 and have no direction.
   - The graphs cover 14–21% of real call pairs.
   - Plain TF-IDF over def names and source puts a changed def in the top 10 for 52% of tasks; the embeddings manage 9%.
4. **The "Workspace Layout" tree misses the source package in 115 of 129 tasks** (`find | sort | head -150` fills up on `.github`/`docs`/`docs_src`). Agents then wander into the docs tutorials.
5. **Context overflow throws away the patch.** About 12% of sessions overflow at the 14,336 compaction trigger, and 44 of 44 overflowed sessions had an empty patch, 14 of them after successful edits (744692).
   - With `max_output_tokens: 16384`, any prompt above 16,384 tokens is refused (dariushafshar notebook, 1 of 7 tasks).
   - Keeping thoughts now makes context grow faster (MrMadsheep, 744354).
6. **Editing an existing test file makes test_patch fail to apply.** The reset step does nothing (744825).
7. **Skill `file_path` passed as a list crashes the task** in about 3% of skill runs (745028, Koo).

## 3. Ranked actions for us

1. **Re-baseline on the post-10-01 harness first.** Our 0.10–0.12 may be from before the fixes; the comparable field is now about 0.13–0.15. One slot on the decoded 0.13 bundle, or our best bundle unchanged, tells us the real gap.
2. **Decide on thinking explicitly.** Every public scorer at 0.12–0.15 effectively runs thinking off. Test thinking off against `include_thoughts: true` with a small budget. Keep a 5-minute cap, because kept thoughts grow the context.
3. **Lower the temperature.** Every scored public bundle uses 0.1–0.2. We use 1.0. Black Cat's T 1.0 variant scored 0.06 against 0.10 for the same design (from our 09-28 research notes).
4. **Prevent zero-patch endings:**
   - declare every advertised tool, or tell the agent which tools it has;
   - ban test edits;
   - keep `max_output_tokens` ≤ 8192 (ours is 4096, which is fine);
   - write the prompt to keep reads small so the context stays under the 14k compaction trigger.
5. **Fix localization in the prompt.** Tell the agent the layout listing is truncated: first `git ls-files '*.py' | grep -v -e tests -e docs | head`, then `rg` the issue's identifiers. Use graph tools only with full ids; never use `search_similar_code` for text.
6. **Copy the planner-to-coder handoff:** a short plan with quoted source lines, edit first, one assertion of at most 6 lines that must exit nonzero, then submit.
7. **Budget for the full run.** Holbrook says unfinished tasks will eventually score 0, but an overrun still errors today. 5 min × 120 ≈ 10 h plus setup is what the public leaders use.

## 4. Speculation and weak evidence (not verified)

- **LoRA:** no scored run anywhere shows an adapter taking effect (745364, open).
  - dmitriigluzdov: a LoRA cut action loss by 40.7%, yet resolved tasks fell from 4/32 to 2/32 (NO-GO).
  - whoami's r64 adapter (980 MB) ended in an error.
  - Distilling from DeepSeek gave +5 local tasks (htn 745274). Using other models' outputs is still not ruled on.
  - **Conclusion: low expected value.**
- **Local scores don't predict the LB:** ISAKA and 508shuto both saw their highest local score get the lowest LB score. Treat local wins of 1–2 tasks as noise.
- **Noise:** one submission has SD ≈ 2.3 tasks; Rozen's identical bundle scored 0.12 and 0.15.
- **The leader's 0.24 is unexplained.** It is 4 tasks above the next five teams, about 1.7 SD, so it could be partly a lucky draw.
- **Final picks:** dariushafshar's model says to pick two *different* agents rather than near-copies.
