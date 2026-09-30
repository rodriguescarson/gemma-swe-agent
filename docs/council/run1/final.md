As chairman of the advisory council, I have reviewed the independent assessments and the adversarial critique. The council has correctly identified that a true 0.20 score (12 of 58 public tasks) is a tail event (P ≈ 0.6% to 3%), not a baseline expectation. Our goal for the remaining 9 weeks is to maximize the expected mean of the two selected final submissions, relying strictly on rigorous constraints rather than hope.

The council broadly agrees on the diagnosis and the constraints, though there is a critical disagreement over whether to salvage the heavy `v10` pipeline or revert to the thinner `v4`. Based on the evidence and the 12-hour math, **we must re-anchor on v4.**

Here is the synthesized, ranked plan to maximize our private leaderboard score.

---

### 1. Why v9_eog and v10.1 score below v4 on the hidden set

Local and pod evaluations over-indexed on the 74 public tasks (`fastapi`/`rich`), masking critical failure modes that the hidden set (private repos, different layouts, stretched clocks) exposes. The causes, ranked by probability, are:

1. **Run Noise (Most Likely for the exact 0.04 gap).** The gap between 0.12 (7/58) and 0.08 (5/58) is barely 2 tasks. The standard deviation of a single read is ~1.9 tasks. We cannot rebuild the pipeline over a gap that is highly compatible with noise. v4 is the only score observed twice.
2. **Time Starvation (Most Likely structural cause).** Hidden tasks run ~1.6–1.8× slower than public tasks. The harness only scores a task if a patch exists on disk before the 5-minute cap. v10.1 wastes ~43s/task in its locator and lands its final patch **18–35 seconds later** than v4. While this buys late solves locally, on a stretched clock, those late solves turn into timeouts and score 0. v4 slips under the cap because it edits sooner.
3. **Helper Fragility on Unseen Layouts.** v10.1 relies on `/tmp/swe` helpers that fail on unfamiliar structures. Measured defects include: slow imports (>10s) falsely flagged as hangs (Defect E); `finalize.py` safely deleting valid root modules with prefixes like `temp` (Defect F/I); and blind spots on namespace/non-`src` imports (Defect K). In v9_eog, the gate falsely reported PASS on crashes. Ironically, because of a `/tmp` rewrite bug, v4’s helpers were unreachable, forcing it to use native built-in tools which survived the unseen repos.
4. **Process Overhead.** Checkpoints, repair loops, and 5-stage architectures consume tokens, provoke compaction (at 14,336 tokens), and distract the model into optimizing for workflow compliance rather than fixing the code.

**The Cheapest Resolving Experiments ($0):**
* **$0 Trace Replay (Resolves Time Starvation):** Do not burn GPU. Replay the existing local traces for v4 and v10.1. For each solved task, mathematically scale the timestamps by a stretch factor ($k = 1.6, 1.9, 2.5, 3.2$). Check if a successful non-test edit exists before $300/k$ seconds. If v10's survival ratio drops below v4's, time starvation is confirmed.
* **$0 Container Test (Resolves Helper Fragility):** Run the T1–T15 test suite in `python:3.13-slim --cpus 2 --memory 4g` locally to verify defects E, F/I, K, and cap parity.
* **Pallets CPU Pre-flight:** Look at the current Pallets dev40 run. Read the v10.1 performance against the **size/churn-adjusted expected bar of 27%**, not the 36% local or 12% hidden rates.

---

### 2. The Next 3 Submissions

We must strictly adhere to **one deliberate change per slot** to keep the LB signal interpretable. *(Note: Council Member C suggested combining 6 different speed/diet changes in one slot; I am vetoing this as it violates our evaluation constraints and masks risk.)* Keep thinking off and temperature 1.0 in all three.

* **Bundle 1: `v4_control` (The already armed sub7).** 
  * **What:** Exact v4 baseline. 
  * **Why:** We need a third reading of our only replicated winner to establish true variance. If this returns $\le 0.03$ or ERROR, we stop and diagnose before spending another slot.
* **Bundle 2: `v4_cap55` (Minimal Budget Extension).**
  * **What:** Exact v4 pipeline, but `max_time_minutes: 5.5`. 
  * **Constraint Guard:** You must first verify that v4's faithful L4 mean agent time is $\le 159$ seconds/task. If it exceeds this, do not raise the cap, or the 12-hour limit will kill the run. 
  * **Why:** This directly attacks time starvation without importing v10's heavy logic. (If the $0 trace replay shows v4's patches already exist before 300s even at $k=3$, skip this and go to Bundle 3, as extra cap time doesn't help if the patch isn't written).
* **Bundle 3: Conditional based on Trace/Pallets data.**
  * *Condition A (v10.1 solves die on replay OR Pallets scores < 27%):* Submit **`v4-fixcomplete`**. Add ~100-150 words to v4's fixer prompt demanding multi-site semantic completeness (e.g., checking serializers, error paths) and single-argument file edits. No checkpoints, no new stages.
  * *Condition B (v10.1 solves survive replay AND T1-T3 reproduce locally):* Submit **`v10.1.1`** (mechanical fixes only). Fix T1-T3 unseen-repo bugs and cap parity. No speed diet, no sparse tree. This isolates whether layout bugs alone caused the 0.08 drop.

---

### 3. Pre-Submission Evaluation Strategy

Local public solve rate is actively anti-predicting the hidden score. Realign the ladder:
1. **Rung 1 (Mechanical):** $0 `python:3.13-slim` CI tests. Never ship a helper pipeline without this.
2. **Rung 2 (Proxy L/F):** Golden plans on the OpenRouter bf16 proxy. Screen only. Reject prompts if gold-file recall drops by $\ge 1$ net loss or valid repro drops by $\ge 3$ cases.
3. **Rung 3 (Transfer):** Pallets DEV via `run_eval_pallets.py` (critical to fix the `src/` path trap). Hold out the 103 tasks until final selection.
4. **Rung 4 (Time Stress):** Pods (2x H100) locked at **`G4_L4_SCALE=3.2`**. This is the only valid test for time-to-patch and speed cuts.
5. **Rung 5 (12h Math Guard):** Kaggle 4xL4 faithful pair. Verify mean agent time $\le 159$ s/task before licensing a 5.5 cap.

---

### 4. LoRA Fine-Tuning: Worth Pursuing, But Heavily Gated

LoRA is our only realistic shot at $+3$ to $+5$ tasks, but the estimated probability of it working is just 22%, yielding an expected gain of $+0.3$ tasks. It is a side bet, not the core strategy.

**How to pursue safely:**
1. **Zero-Cost Gates First:** Post the distillation clarification to the Kaggle forum now. Check if the wheelhouse CRC changed.
2. **The Probe (2 GPU-h):** Submit a dummy run with **BOTH** `lora_A` and `lora_B` randomized. If logprobs are identical to baseline, the scorer is ignoring adapters. Kill the LoRA track immediately.
3. **Action Space Mismatch:** If the probe passes, do NOT train on public `OpenHands/SWE-agent` datasets. They map to v10's helper schema. You must run a clean teacher through the **v4 pipeline (native tools)** to generate trajectories, or train on v4's own successful traces.
4. **Licensing & Exclusions:** Use only permissive teachers (Qwen3-Coder/DeepSeek). Pin the OpenRouter provider to read their terms. Exclude all public eval yardsicks (`fastapi`, `rich`, `requests`, `httpx`, `werkzeug`, and the Pallets holdout).
5. **12h Guard:** LoRA imposes an unmeasured decode tax. The adapter bundle must pass the $\le 159$s L4 mean time guard.

---

### 5. What We Must STOP Doing

* **STOP adding process weight.** No new stages, repair loops, regression gates, or checkpoint restores. They scored 0.06/0.08 and failed compliance. 
* **STOP the 8-bundle factorial.** It aliases interactions (e.g., speed diet vs. extra reproduction) and is severely underpowered (+0.7 to +1.6 real levers cannot be resolved by +3 power math).
* **STOP chasing Temperature 0.2 and thinking-on.** The only direct pod sweep proved it had zero effect ($p > 0.45$). 
* **STOP raising the cap blindly.** 6.0 is mathematically unsafe without measuring Validation ($V$) overhead. A slower agent + higher cap = 12-hour timeout = 0.
* **STOP double-counting fix-quality.** The odds model allocates a single $+0.6$ lever for completeness. Adding a "second fixer" on top double-counts gains that won't manifest under a stretched clock. 

### Council Agreements, Disagreements, and Flags
* **Agreement:** v4 is the current baseline champion. Hidden hardware time starvation and unfamiliar layout helper failures are the primary suspects.
* **Disagreement:** Council Member C advocates aggressively fixing and re-deploying the v10 architecture. Members B and D argue v10's architecture is fundamentally flawed for a stretched clock and advocate sticking to thin v4 improvements. I side with B and D: complexity is actively punished by this specific harness. 
* **Constraint Flags:** Member C claimed v10.1 is "constantly hitting the cap"; the math says only 36-66% hit it under realistic stretch factors. Member B advised using "single-argument file edits", which is correct because the context warns the `gemma4` parser corrupts ~20% of multi-argument calls. All other advice complies rigorously with the stated hard constraints.