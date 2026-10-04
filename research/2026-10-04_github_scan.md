# GitHub scan: rival entries and reusable SWE-agent tricks (2026-10-04)

Method: `gh search repos`/`gh search code` (competition slug, model id, "swegemma") plus web search; ~25 entrant repos, commits/configs/prompts read for the relevant ones. Literature is in `literature.md` and `2026-10-04_web_papers_scan.md`. (Our own repo appears in searches but is **private**.)

**Bottom line:** no public entry is ahead of us. The best public LB numbers are AMonFer 0.12 and happyc0der 0.10. ns-0437 and LogosTopos are at 0.06 and rlawoals0529 at 0.05. Nobody near the 0.24 leader publishes code. What is worth taking from the rivals is a few concrete prompt rules and one verification defect, not an architecture.

## Ranked by expected impact for us

**1. happyc0der/gemma-swe-agent: prompt v5.0n rules (medium, cheap)**
https://github.com/happyc0der/gemma-swe-agent (last commit 2026-10-04 00:17 UTC). This is the most rigorous rival. They run a "faithful eval" (official Evaluator, real 31B on llama.cpp, 16 holdout tasks). Results: v4.5 7/16, v4.6 8/16, v4.7 8/16, v5.0n **9/16**. n=16, so most of those steps are within noise. Their LB best is 0.10. Rules they kept that we could A/B on all 74 tasks:
- **No paging.** A third consecutive `sed -n` region of the same file means stop paging and `grep -n` for the specific name instead.
- **Fix siblings.** After a fix, grep the changed expression across the package, because siblings such as `load`/`loads` and `add`/`add_many` "usually need the same fix".
- **Behaviour before docs.** Make the issue's example work end to end, `submit_patch`, and only then touch docstrings and overloads.
- **Malformed calls.** On "mandatory parameters are not present", never resend. Instead, write `/tmp/fix.py` doing `assert s.count(OLD)==1; s.replace(OLD,NEW)`. This matches our own finding that edits fail as multi-argument calls and succeed as heredocs.
- **Ports from stdlib.** If the issue ports stdlib behaviour, read it in the sandbox with `inspect.getsource(...)`.
- Edit by call 10, wrap every script in `timeout 30`, keep repro scripts under 20 lines.

Negative results, worth not repeating:
- "One-line note before every call" with thinking off produced empty thought markers and no tool call (7/16); "empty grep means not found" raised repeats 77 to 130; temperature 0.2 vs 0.7 tied on the LB.
- `scripts/submission_errors.py` reads `errorDescription`, which the Kaggle CLI hides. Their blank scores were a capacity error and an unhandled error, not the 12 h cap. **We should run this on our own failed submissions.**

**2. ns-0437/gemma4-developer-agent: repro scripts that cannot fail (medium, cheap)**
https://github.com/ns-0437/gemma4-developer-agent, `experiments/verification_v1/PLAN.md`. In a trace (rich_3675), the agent's repro first commented out the key assertion, then caught `AssertionError` and exited 0. The agent "verified" a wrong patch against it. The proposed fix is a rule: bare `assert`, no try/except around the check, nonzero exit on failure, and fixed before/after expectations. Stdlib skill option: lint `/tmp/repro.py` with `ast` for a `try` wrapping an `assert` or an `except AssertionError`, and refuse it. It targets our "right file, wrong fix" bucket. They have 0.06 on the LB and no solves in their 8-run A/Bs, so the rule itself is unmeasured.

**3. Gosling-dude/gemma4-developer-agent: harness checks and a deterministic locator benchmark (low to medium)**
https://github.com/Gosling-dude/gemma4-developer-agent, `docs/experiments.md`. They have no real-model runs.
- **E005, a bug we should test for.** In the official subprocess sandbox, skill scripts saw an **empty directory** because ADK chdirs to a temp dir. They fixed it with a `$PWD` fallback. We should confirm our skills resolve `/workspace` explicitly.
- **O002.** The harness sends only `enable_thinking`; `thinking_budget` is never sent.
- **O003.** `timeout_seconds` also caps the hidden-test pytest run. We already know this.
- **Localization ablation** (n=12, rich only, no LLM). Dropping env-dump, URL and doc-link terms from the issue raised file@1 from 0.25 to 0.50. Following `calls` 1-2 hops from symbols named in the issue gave callees@3 0.67. A dotted module term should map to its module file. All three are cheap filters to port into our locator skill.

**4. AMonFer/Gemma4-Developer-Agent-Competition: 0.12 with a plain bundle (low; mainly a data point)**
https://github.com/AMonFer/Gemma4-Developer-Agent-Competition. Their 0.12 came from a short TDD prompt with 6 min / 30 calls / `timeout_seconds 120`, temperature 0.2, and thinking on with `include_thoughts: true`. They also bundle the **sample dummy LoRA** (r=4, layer 0, q/o_proj), which is effectively a no-op. Adding a `semantic_scout` sub-agent (v2) scored 0.12 again. The v3 `graph_inspector` result is pending. So sub-agent localization has not moved anyone's public score.

**5. sagarml4949/gemma4-swe-agent: LoRA data pipeline (conditional)**
https://github.com/sagarml4949/gemma4-swe-agent. It has a mining script plus split SFT sets (`localization_*`, `edit_*`, `verification_*` traces, `main_lora`/`tool_lora` jsonl) and axolotl/unsloth/PEFT recipes. It only matters if adapter loading on the scorer is confirmed. That is still unverified per `docs/council/brief.md`.

**6. msingatullin v9 (low)** (https://github.com/msingatullin/gemma-4-developer-agent): a coder plus a `code_analyzer`, temperature 0.15, `py_compile` after every edit, `git checkout --` to revert. No LB score.

**Skip:** emiliodavola (60-min/task budget would blow the 12 h cap; skills are instructions only), belemcrizan (paired A/B tooling only), LogosTopos (0.06), and JGM-droid, biswalprince, ennydev-2026, magician-k2, rlawoals0529 (0.05), elamurg, hemantadil (starters or no scores).

## Reference SWE-agent repos: what still transfers

- **AutoCodeRover** (https://github.com/nus-apr/auto-code-rover). Its AST search APIs (`search_class`, `search_method_in_class`, `search_code_in_file`) can be built as one stdlib `ast` skill with **bounded** output. That makes it a safer replacement for `search_similar_code`, whose output is uncapped (136k chars, `competitors.md`). This is the most directly reusable code idea in this section.
- **mini-swe-agent** `config/benchmarks/swebench.yaml` (https://github.com/SWE-agent/mini-swe-agent, v2.4.6). It frames the task as `<pr_description>`, which matches our finding that the statements are PR bodies. It also asks for changes "general and consistent with the codebase" and limits the patch to the source files the agent changed. The framing is cheap to copy. Do not copy its bash-only action space (-15 pts at 30B) or its parallel tool calls, which our harness does not support.
- **Agentless**: only the single-sample repro-test + regression filter fits (already #1 in the papers scan).
- **SWE-smith / SWE-Gym** are data sources only if LoRA becomes viable. **Moatless, SWE-Search, OpenHands, Kimi-Dev, DeepSWE, SWE-RL** add nothing beyond `literature.md` §5.

## Suggested actions (in order)

1. Run `submission_errors.py`-style `errorDescription` retrieval on our blank submissions.
2. Test the skill-cwd bug (E005) against our skills.
3. Add the repro-must-fail rule, or the `ast` repro lint.
4. A/B happyc0der's paging, sibling-fix and behaviour-first rules on all 74 tasks.
5. Add Gosling's term filters to the locator.
6. Build an AutoCodeRover-style bounded AST search skill.

