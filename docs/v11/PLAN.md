# v11 plan (living document)

v11 is the frozen v10 bundle plus one LoRA adapter, trained only on Gemma-4-31B's own v10 trajectories from repos
outside the public set. This file replaces `plan_A.md`, `plan_B.md` and `plan_C.md`, which stay on disk as inputs.
Nothing here starts a pod, pushes a kernel or submits. Every one of those is Carson's call.

Source keys used below:
- FI = `docs/v11/facts_internal.md`, FE = `docs/v11/facts_external.md`.
- PA, PB, PC = plans A, B and C.
- J = the judges' review in the 09-28 workflow (not saved to disk).
- LED = `eval/ledger.md`. R2 = `docs/v10/RACE2.md` and `docs/v10/race2_checklist.md`.

Thresholds in §1 and §6 are copied into `docs/v11/checklist.md` before the first paid v11 run. After that they change
only through dated addenda.

---

## 0. Status (2026-09-28, evening IST)

| item | state | source |
|---|---|---|
| Phase | **P0**: Mac tooling. Free, not started | this plan |
| Next gate | **G-A** Kaggle 4×L4 LoRA probe. It is blocked until `g4-l4-v4` and `g4-l4-v9-eog` leave the queue (both QUEUED at 17:45 IST), and it cannot run while any submission is scoring | PA §1 |
| v10 | Bundle built and gates green: CI `1234 passed`, `validate.py` OK, pack sha `98920550…c482`. **It has never been run with the model in the loop.** Race 2 is written but not started (Carson's go) | R2 §2, §5 |
| Pods | No Gemma pod is running (`list-pods` this pass: `2wyl66nmji13p1` and `1fs5qx44uhc3m7` are EXITED). `kaggri-watch` is RUNNING but belongs to Kaggriculture | RunPod MCP |
| Spend | $96.09 billed through 09-28, against a ledger that shows about $51 (it stops at 09-26 22:10 IST). About $404 of the $500 cap is left. Race 2 needs about $30-35, which is v10's money | FI §6, PA §7 |
| v11 spend | **$0 of the $250 cap** | — |
| LB | sub3 (v4) 0.12, sub4 (v9_eog) 0.06 (within noise), leader 0.15, target 0.30 | task |
| Kaggle API | Unreachable from the Mac during this pass (DNS error), so kernel states were not re-read | this pass |

---

## 1. Goal and ship rule

**Goal.** Build an adapter that makes v10 better at format and efficiency: fewer malformed calls, fewer exact repeats,
fewer seconds per task. The own-data audit puts those losses at about 3.5 tasks per 51, plus 18-41% of agent time
wasted (FE §3). The paper track also gets the first verified adapter path on the scorer. v11 is **not** expected to
take the score from 0.12 to 0.30: published self-RFT at about 32B is flat (19.0 → 19.7) or negative (15.3 → 8.7)
(FE §3).

**Honest odds.** These are guesses, and they multiply:

| step | P |
|---|---|
| LoRA is alive on the scorer (G-A and G-B pass) | 0.6 |
| enough data (≥ 120 trajectories) | 0.7 |
| the adapter learns something and it survives serving | 0.7 |
| the pod screen advances it | 0.5 |
| it passes the faithful gate | 0.3 |
| **P(ship)** | **≈ 0.04-0.10** |

Plan B's "20%" is about 3x too high, because its own factors multiply to 0.07 (J). If v11 ships, expect about +1
hidden task of 58 (+0.015 LB, 80% range −1 to +4) (PC §12).

Why it is still worth running:
- The kills come first and are cheap: $0 if G-A fails, at most $10.5 if G-B fails.
- The data and findings go to the paper track whatever happens (§8).
- A verified adapter pipeline is the only way to use teacher data if the host allows other models' outputs. Teacher
  data is the lever with large published gains: 7.0 → 20.6 and 7.0 → 40.2 (FE §3).

**Ship rule (pre-registered; PB §8 margin, PC §5.3 validity checks).**

- Arms: CTL = `V10_FREEZE` (no `adapters/`, so LoRA is off). TRT = the same bytes plus `adapters/v11_a/` and
  `adapter: v11_a` on locator, fixer and verifier; `tests/test_v11_bundle.py` pins that diff.
- Setup: the 74 ids in `data/kaggle_valid_ids.txt`; Kaggle 4×L4 with the host's notebook recipe; compaction
  `(15, 2, 14336, 5)`; budgets from `eval_config.yaml` (5 min, 120 s, 100 calls, 200 turns). Order C1, T1, kill check,
  T2, C2.
- d_k = TRT − CTL resolved in round k; D = d_1 + d_2 over 148 paired task-runs.

| # | gate | pass |
|---|---|---|
| 1 | pooled resolved | **D ≥ +6** (SD(D) ≈ 4.2, so +6 ≈ 1.4 SD; PC §5.4) |
| 2 | per round | every d_k ≥ −2 |
| 3 | crashes | 0 in every race-2 KPI-3 class |
| 4 | empty patches | TRT ≤ CTL + 2 per round |
| 5 | malformed calls per task | TRT ≤ CTL |
| 6 | time | TRT mean s/task ≤ 1.05 × CTL; measured startup + 130 × 309.6 s ≤ 11.5 h, i.e. startup ≤ 1,150 s (v4's full run took 10.4 h; PA §5) |
| 7 | validity (a failed round is rerun, not analysed) | same vLLM `gemma4.py` CRC and `pip freeze` in every kernel; TRT has `--enable-lora` and `/metrics` shows `v11_a` on every task; CTL has no `--enable-lora` |

- **Inconclusive.** If D is +3 to +5 and gates 2-7 pass, run one more pair. Ship if the three-round D is at least +8.
- **Stop after R1** if d_1 ≤ −4, any crash appears, or the time gate fails.
- **The LB never decides.** A submission is only a check for catastrophe (a score of 0.03 or less, or an ERROR).

---

## 2. Phases

Owner: **C** = Claude (Mac, free). **K** = Carson, who approves pod starts, pushes, uploads, network downloads,
submissions and forum posts.

| step | what | pass gate | $ | wall | owner | depends on |
|---|---|---|---|---|---|---|
| P0.1 | Catch the ledger up to billing, using FI §6's attribution: race 1 = `2wyl66nmji13p1` on 09-27, $33.19; `r02i1c2nbk4v6p` $28.18, attributed by timing. PB mislabels these (J). Add a v11 spend column | ledger within $2 of $96.09 | 0 | 0.5 h | C | — |
| P0.2 | `train/scorer_render.py` (from `evidence/render.py`), the June template (16,934 B, sha `94899c0f`), tests | `bodies_a/d/adapter` render byte-exact; 2,391/2,391 e74_v3 continuation increments; 53/53 post-compaction first calls at −4 (FI §3.3) | 0 | 3 h | C | — |
| P0.3 | `train/build_sft.py` with the §4 recipe, and ≥ 12 tests | a planted public id makes the builder exit 2; the June template's stray end-of-turn token case passes; the thought-channel policy test passes | 0 | 8 h | C | P0.2 |
| P0.4 | `train/sft_v11.py` with the §5 recipe | on a tiny `Gemma4ForCausalLM` on CPU: chunked CE = full CE to 1e-5, softcap applied, only LoRA params get gradients (PA S0) | 0 | 6 h | C | — |
| P0.5 | `train/export_adapter.py` (bf16, PEFT prefix, `--kv-mode dup\|none\|exclude`) and `scripts/make_v11_bundle.py` | tests on key prefix, dtype, shapes, size < 3 GiB, r/alpha, `v_proj` duplicated on exactly 10 layers, diff vs v10 = adapter only, `validate.py` OK, name regex (no `gemma4`, `o<digit>` or `gpt-5`) | 0 | 4 h | C | — |
| P0.6 | `make_test_adapters.py` (numpy, byte-reproducible, sha recorded); `pod/lora_gate.py`; `make_eval_kernel.py --probe lora`, `--adapters-dataset`, sha assert | notebooks valid; the sha assert fails on a flipped byte | 0 | 5 h | C | — |
| P0.7 | Pod: bootstrap installs the v25 wheel (CRC asserts `c8cefd56` / `e16a1908`) plus the June template and Kaggle v2 tokenizer config; `serve.sh` gets LoRA flags; stdlib `capture_proxy.py` records bodies and token ids; chains always back up and then run `runpodctl stop`, with an outer timeout equal to their cap | `bash -n`, shellcheck, `test_pod_scripts`, `linux_test.sh` all green | 0 | 6 h | C | — |
| P0.8 | SWE-Pallets-X env adapter: per-instance uv venvs following the dataset's `era_pin` / `verify.py` (not a fixed Python 3.12; J); a `G4_ENV_MAP` hook; resolved label = tests FAIL at base+test_patch and PASS with the patch | Mac smoke on 10 tasks: gold passes ≥ 8/10, empty patch fails 10/10. Otherwise switch to SWE-rebench (+1 day) | 0 | 6 h | C (download: K) | — |
| P0.9 | `docs/v11/checklist.md` (§1 and §6 verbatim) and `scripts/v11_kpis.py` constants, pinned by a test | the test fails if the constants drift | 0 | 2 h | C | — |
| **G-A** | Kaggle 4×L4 probe, §6 row 1 | §6 | 0 (≈ 2 GPU-h) | 1 queue window | K push | P0.6; both queued kernels done; nothing scoring |
| **G-B** | Pod parity probe, §6 row 2. It can be chained onto race 2's boot (≈ $7) | §6 | 7-10.5 | 1.5 h | K start | P0.6, P0.7 |
| P2 | Pod session 1: Pallets oracle, then a 40-task v10 probe, then one sample on every valid non-werkzeug task, then a second sample on tasks with at most 1 success | oracle: ≥ 150 valid tasks over ≥ 5 repos. Probe: solve rate ≥ 10% and proxy/render parity ≥ 99%. Round: ≥ 120 clean, L4-feasible trajectories over ≥ 60 tasks and ≥ 5 repos (PC K5) | 45-60, cap 75 | 8-10 h | K start | G-B pass; `V10_FREEZE` (does not wait past Wed 7 Oct; later prompt-only changes are re-rendered: PC §2, §6.3) |
| P3 | Pod session 2: 10-min smoke, train `v11_a`, export, served NLL, pod screen of 74 tasks (CTL LoRA-off on GPU0 vs TRT on GPU1) | §6 rows 3-5 | 45-60, cap 75 | 9 h | K start | P2 |
| Z | One LB slot: v10 plus a tiny zero-B adapter (LoRA mode on, behaviour identical to v10) | completes and scores ≥ 0.05 | 0 (1 slot) | 12 h | K | G-A pass |
| M1 | Private Kaggle dataset holding the adapter. A CPU kernel reproduces its sha. A `prompt_logprobs` cell re-checks served NLL at TP4 (J) | sha equal; the TP4 NLL drop is ≥ 0.5 × the HF drop | 0 | 1 h | K upload | P3 pass |
| P4 | Faithful paired run under the §1 rule, inside a 36-60 h window made by skipping 1-2 submission slots (PC §1.3) | §1 | 0 (≈ 15 GPU-h) | 36-60 h | K pushes | M1, Z |
| P5 | Ship. Adapter dataset version = the exact P4 bytes; build the submission kernel; validate; submit at 05:31 IST (00:01 UTC) via `submit_at.sh`, with nothing else scoring | `validate.py` OK; unpacked < 3,221,225,472 B; adapter sha = the P4 sha; diff = adapter only | 0 | 14 h | K | P4 PASS |
| P6 | Conditional iteration 2 (§5) | same ladder | cap 90 | 1-2 weeks | K | P4 PASS or inconclusive; ≥ $100 left; on or before 2026-11-10 IST |

**Target calendar (IST, PC §2).**
- P0: Mon 28 Sep to Sat 3 Oct. Carson is mostly away 30 Sep to 4 Oct for Kaggriculture, Shipaton, the Adaption talk
  and Fatima.
- One batched approval, A1, on Sat 3 Oct. It covers the G-B / P2 session (cap $75 + $10.5), the downloads, the G-A
  push and Z.
- P2: Sun 4 to Mon 5 Oct. Z: Tue 6 Oct at 05:31. P3: Wed 7 to Thu 8 Oct. A2 on Thu 8 Oct covers the P3 results, the
  upload and the P4 window.
- P4 window: Fri 9 Oct 17:30 to Mon 12 Oct 05:31. **Decision: Mon 12 Oct.**
- No v11 approvals during the Italy trip, 16-20 Oct.

**Budget.**

| line | expected | cap |
|---|---|---|
| v11-a (G-B + P2 + P3) | ≈ $105 | $160 |
| P6 | — | $90 |
| **v11 total** | | **$250** |
| left for v10.x after race 2 | about $119 | |

---

## 3. Kill criteria

Any one of these ends LoRA work for the main track. The negative result is written up for the paper.

| id | condition | where |
|---|---|---|
| K1 | Adapter not applied: random-B changes top-1 on < 18/20 prompts, or zero-B differs beyond the base-vs-base noise floor, or any `No LoRA weights found … self_decoder` line appears. Action: stop LoRA spend and draft a 743508 repro. Reopen only when the wheelhouse CRCs change | G-A, G-B |
| K2 | Fewer than 3 module families reach Δlogprob parity r ≥ 0.9 (both k_eq_v options tried), or neither r16 nor r8 is as deterministic as base | G-B |
| K3 | On 4×L4: any LoRA-mode decode tax (base-name or adapter requests) > 25%, or startup > 1,150 s (§1 gate 6), or Z errors or scores ≤ 0.03 | G-A, Z |
| K4 | Nothing learned survives serving: held-out NLL drop < 3%, or the served drop is < 0.5 × the HF drop, after one retry | P3 |
| K5 | < 60 valid tasks, or < 40 clean trajectories after P2. At 40-119, one extra pass (≤ $30) is allowed, then train only if the count reaches 120 | P2 |
| K6 | Pod screen: TRT < CTL − 3, or a crash or summariser breakage survives one fix, or the break-even rule in §6 row 5 fails | P3 |
| K7 | §1 FAIL outside the inconclusive band, and one recipe change (lr, epochs or attachment) also fails | P4 |
| K8 | v11 pod spend reaches $160 with no adapter past P3, or $250 at any point. No adapter past P3 by Thu 15 Oct. No faithful PASS by **Sun 8 Nov (LoRA kill date)**. Main deadline: Thu 3 Dec 05:29 IST (Wed 2 Dec 23:59 UTC) | ledger, calendar |
| K9 | The host restricts adapters or self-training, or changes the model or wheel so that G-A/G-B must be redone, and they fail | forum 743964, wheelhouse |
| K10 | v10 has already recovered the format loss: race 2 / v10 L4 shows malformed `edit_file` ≤ 0.3 per task, exact repeats ≤ 15%, and ≤ 1 of 74 tasks lost to cap spirals. Cancel P3 onward; data and paper work continue (PC K10) | race 2 |

---

## 4. Data plan

**Sources.**
- Train on SWE-Pallets-X v4: 476 tasks over 8 repos, CC0 (FE §4). The public set's 4 repos are not among them.
- **werkzeug (43 tasks) is held out**, and 10% of the remaining tasks go to `pal_val`, split by task.
- `val_pub` holds race-2 `r2_v10` trajectories on public tasks. It is used only for NLL checks and exactness tests,
  never for gradients or selection.
- Fallback: SWE-rebench (CC-BY-4.0).

**Never used for training:**
- the 129 public tasks and their 4 repos: 39 of the 43 old resolved tasks are in the 74-task gate set (J);
- the 349 old unique trajectories: pre-v10 action space, 35-54% raw `run_command` (FI §4.6);
- the nebius/Qwen3-Coder set: other-model ruling pending, and off-format (FI §5.2);
- any non-Gemma output.

**Filters** (PB §6.4): resolved; no protected or scratch files in the patch; no crash class; re-timed on the L4 model
(0.99 s/call + 26.5 ms/token) at ≤ 290 s; no parallel-call step; ≤ 20% of calls masked; every call joined to a proxy
record.

**Caps and ordering.** At most 3 trajectories per task, fewest calls first; no repo above 30%; near-duplicates collapse
to the shortest. Epoch 1 runs shortest first (turn-count curriculum, +2.2, FE §3). Problem statements that describe
the fix (a gold added line appears verbatim; J) are tagged and capped at 30% of trajectories.

**Loss masks** (the call stays in context, only its loss is zeroed): schema-invalid or ADK-rejected calls (16% of all
calls are malformed; FI §4.5), helper usage errors, exact repeats of one of the stage's last 5 calls, and
`finish_reason=length`. Test and repro failures inside a correct reproduction stay **supervised**, because v10's
locator is meant to show the bug failing (J, against PC's mask). Stop tokens 1, 106 and 50 are supervised.

**Format parity with inference** (FI §2-3): June template, OpenAI content parts, tool results double-encoded with
`ensure_ascii=False`, and the thought-channel generation prompt on first calls. Two samples per stage segment: (a) the
first call alone; (b) the final prompt, with loss on completions 2..n.

**Thought-channel policy (J).** The June template drops empty thoughts from history, so in sample (b) the middle
completions are canonical re-renders without the `+4` empty channel; only the first and last completions of a segment
are raw. A test pins this, and the P3 screen reports how often the model emits an empty channel.

**Compaction.** Summaries are captured by the proxy and make up ≤ 5% of the mix. A post-compaction segment is used
only when its summary was captured.

**Expected counts.** 120-250 trajectories at about 2.4k supervised tokens each (PB funnel: 107 trajectories =
256,546 completion tokens). That is 0.3-0.6 M supervised tokens, or 4-9 M total tokens per epoch (PB §6.6).

---

## 5. Training recipe

- **Base.** dequant(served w4a16) via `CompressedTensorsConfig(dequantize=True)` in a separate env on transformers
  5.17.0 (the train env pins 5.13.1; bump it). It is a 23.3 GB download instead of 62.5 GB and matches serving
  numerics; the served int4 is an RTN of the QAT bf16 with 6.7% elementwise error (FE §2.1).
- **LoRA.** r16, alpha 32, all 7 projections of the 60 language layers: 122.4 M params, 245 MB bf16 (FI §1.6).
  Families that fail G-B are dropped. On full layers 5, 11, …, 59, `k_proj` is duplicated as `v_proj` at export
  unless the no-duplication variant already reaches r ≥ 0.9 (FE §1.3). Rank stays 16 unless higher ranks pass
  determinism (vLLM #50059).
- **Optimisation.** lr 1e-4, cosine, 1-2 epochs; one retry at 5e-5 or 2e-4. Sequences ≤ 16,384 tokens (the scorer
  compacts at 14,336).
- **Implementation (FE §2.3).** sdpa (FA2 rejects head_dim 512); chunked CE on supervised positions only, softcap 30;
  zero `mm_token_type_ids`; no ZeRO-3, tensor shapes checked after every save; grad norm, max abs logit and tok/s
  logged.
- **Cost.** Throughput is unmeasured. The published anchor is 486 tok/s at r64 on 2×H100 (FE §2.5). The P3 smoke
  measures it and re-prices training. Training is cut to 1 epoch or a 50% subset if the projection exceeds $45.
- **Export.** bf16, keys `base_model.model.model.language_model.layers.N.<mod>.lora_{A,B}.weight`, name `v11_a`.
  Weights go to the private HF artifacts repo and the Mac, named with their size, before any pod stop.
- **Attachment.** One shared adapter on locator, fixer and verifier. Setup and submitter stay on the base
  model (PA §2.1). The compaction summariser in an adapted stage also runs through the adapter (FI §1.4).
- **Per-stage adapters.** Only in P6, and only if each stage has ≥ 300 segments. In P6, keep a stage's adapter only if
  one per-stage KPI improves by ≥ 10% and none worsens by more than 5% (PA §2.3).
- **P6 data.** A second Pallets sample, plus a privileged self-teacher: the same Gemma with thinking on, used on
  unsolved tasks, with thoughts stripped and results re-timed on L4. Teacher data from other models only if the host
  rules it allowed.

---

## 6. Evaluation protocol

Pod runs screen for harm and format problems. **Only the Kaggle L4 faithful run decides shipping.**

| # | check | measures | pass |
|---|---|---|---|
| 1 | **G-A** Kaggle 4×L4, TP4. Adapters come from numpy with their sha asserted | top-1 with a random-B N(0,1) adapter on 20 prompts; zero-B vs base, with a base-vs-base repeat as the noise floor; `konly_full` vs `dupv` outputs; determinism (5 repeats + restart); decode ms/token at 4k and 12k tokens for LoRA off, base name in LoRA mode, tiny adapter and r16 adapter; startup; KV capacity; Δlogprobs with a calibrated adapter (RMS 0.1-0.5 nats) saved for the TP1 comparison; 5-task v10 + zero-B agent smoke | top-1 changes on ≥ 18/20; zero-B within the noise floor; `dupv` ≠ `konly`; r16 mismatches ≤ base + 2 of 15; base-in-LoRA-mode tax ≤ 10% (10-25%: continue, and the §6 row 5 break-even absorbs it); tiny-adapter tax within 3 points of r16 (so Z is representative); startup ≤ 1,150 s; KV fits ≥ one 32k sequence; smoke has 0 crashes and routing is confirmed |
| 2 | **G-B** pod, 2×H100 | dequant exactness (bf16, same op order, ≤ 1 ulp; J); random-B plus a DEBUG grep; per-family Δlogprob parity for q, k_sliding, k_full with and without dup, v, o, gate_up and down, over ≥ 2,000 tokens; HF references saved and GPU0 freed before TP2 (J); determinism at r16/32/64/128 vs base; `return_token_ids`; TP1 reference for G-A | r ≥ 0.9 for every kept family; ≥ 3 families; r16 mismatches ≤ base; after G-A, TP4-vs-TP1 r ≥ 0.95 |
| 3 | **Train** (P3) | 8-sample overfit, peak memory, loss | loss < 30% of its start in 30 steps; no NaN; max abs logit ≤ 30; ≤ 78 GB/GPU at 16,384; held-out werkzeug NLL and `val_pub` NLL each ≤ 0.97 × base |
| 4 | **Served** (P3) | vLLM prompt-logprob NLL on the trained adapter | served drop ≥ 0.5 × HF drop; per-token Δ correlation ≥ 0.8; determinism ≤ base (PA T3; J rejects PB's absolute 3% rule because it passes when the adapter is not applied) |
| 5 | **Pod screen** (P3), 74 tasks, faithful switches, June template | resolved; crashes; routing; summaries; format | TRT ≥ CTL − 3; 0 crash classes; ≥ 99% of work-stage requests and 0% of setup/submitter requests go to the adapter; ≥ 95% of summaries non-empty, ≤ 1,024 tokens, with no tool-call tokens; malformed/task or exact-repeat share ≤ 0.7 × CTL; **break-even**: completion tokens per task × (1 + G-A adapter tax) ≤ CTL's (J) |
| 6 | **Z**, **M1**, **P4** | as in §2 and §1 | as in §2 and §1 |

**P4 report** (`docs/v11/p4_report.md`): paired wins/losses with an exact sign test, bootstrap CI for D/148, per repo,
s/task, ms/token, per-stage format KPIs, summary validity, startup delta, LB transfer estimate 0.34 × local (PA §5).

---

## 7. Risks and mitigations

| risk | mitigation |
|---|---|
| The wheel fix exists in code, but nobody has shown adapter ≠ base on a GPU (FE §1.1). The 743508 bug was *partial* zeroing, which a top-1 test cannot see (J) | G-A first; G-B per-family parity catches partial application |
| k_eq_v: vLLM gives V no delta on 10 of the 60 layers (FE §1.3) | `--kv-mode dup` plus the parity test |
| LoRA mode is global. The rank-128 slots may cost adapter stages 15-19% decode (J's estimate, UNVERIFIED), and a lower rank does not reduce that | G-A measures it; the break-even rule; K3 |
| Train/serve numerics gap | Train on dequant(w4a16); served-NLL transfer gate |
| Self-RFT gives about 0 | Framed as a format lever; K6, K7 and K10 stop spend early |
| Pallets yield or env validity is low; Pallets repos sit in pretraining and are easier | Oracle and 40-task probe gates; SWE-rebench fallback; the public 74 are the out-of-org test |
| v10 changes after data collection | Record `V10_FREEZE` sha; `--require-sha`; re-render prompt-only changes; regenerate after helper or tool changes (PC §6.3) |
| Kaggle queues of 4-9 h, the 2-session limit, no kernels during scoring, unknown quota | 36-60 h windows made by skipping slots; read the quota in P0 |
| A 245 MB adapter cannot be base64-inlined in a notebook | Private dataset with a sha assert (M1) |
| Pod idle spend | Every chain backs up, then runs `runpodctl stop` itself; the outer timeout equals its cap |

---

## 8. Paper-track tie-in

- **Deadline:** Fri 13 Nov 05:29 IST (Thu 12 Nov 23:59 UTC). First submission Fri 6 Nov; final Wed 11 Nov (PC §8).
- **Entry: Best New Resource.** Every P2 task-run on Pallets-X (successes and failures) with exact June-template
  prompts, raw completions, captured summaries, labels and predicted L4 time; the tools `scorer_render`, `build_sft`,
  `export_adapter` and `lora_gate`, with the exactness statistic recomputed over the full population. Public-task
  traces only if 743255 Q4 allows redistribution.
- **Findings:** the LoRA fix's status at TP1, TP2 and TP4; the k_eq_v V-slot mismatch; the LoRA-mode tax; the
  pre-registered self-RFT result on unseen repos, negative or not.
- **Disclosure:** bug reports (743508) as soon as verified, posted by Carson; dataset and tools with the paper; weights
  and exact recipe held until Thu 3 Dec.
- **Prose** goes through ai-writing-detection and voice-dna. Carson tests a draft save by Sun 25 Oct (743094).

---

## 9. Open questions

1. What is the weekly 4×L4 quota, when does it reset, and is queue time charged (743683)? This sets the P4 window.
2. What are the scorer's compaction interval (5 or 15) and `gpu_memory_utilization` (0.80 or 0.90) (743752)?
3. How will the host rule on other models' outputs (742807, 743964)? If they are allowed, P6 becomes teacher data. A
   different Gemma checkpoint as teacher also needs to be confirmed with the host.
4. Does the patched vLLM 0.19.1 honour `return_token_ids`? If not, fall back to the render path at ≥ 99% parity.
5. Does the vLLM gemma4 parser accept completions both with and without the empty thought channel (§4 policy)?
6. Should an efficiency ship route be allowed (0 ≤ D < 6 with s/task ≤ 0.85 × and malformed ≤ 0.5 ×; PA §5)? It is not
   in the rule. Carson's call.
7. Are Kaggle v2 and HF `model.safetensors` byte-identical? Sizes match at 23,265,352,448 B (FE §2.2); G-B checks
   the sha.

---

## 10. Update triggers and CHANGELOG

Revise this file (add a row below, and update §0) when any of these happens:
- race 2 finishes: set `V10_FREEZE` and apply K10;
- a v10 bundle edit (§7 rule);
- a gate result;
- someone posts a LoRA re-test or a scored adapter;
- the wheelhouse CRCs change: re-run G-A;
- a ruling on 742807 or 743255;
- new facts about quota or queues;
- LB movement, for example an adapter team reaching 0.20 or more.

| date (IST) | change |
|---|---|
| 2026-09-28 | Plan created from `facts_internal.md`, `facts_external.md`, plans A/B/C and the judges' review. Decisions taken: A's probe-first order and delta-based gates; B's ship margin, data filters and proxy; C's leak guard, TP4 check, Z slot, validity checks and calendar. The judges' fixes are applied: canonical middle completions, no masking of repro failures, a noise floor for zero-B, the break-even rule for the decode tax, per-instance venvs, and honest multiplied odds. `list-pods`: no Gemma pod running. |
- 2026-09-28 18:35 IST: Carson approved race 2 (v10 vs v9_eog, 2 rounds x 74 tasks, faithful compaction + L4 clock). Old pod host had no free GPUs; new pod `cl440ut808797d` (2x H100, AP-IN-1, $6.98/h) created 18:29 IST, repo cloned, `pod/chain_boot.sh` + `pod/chain_race2.sh` running; race waits for GO_RACE2, written after the v10 review rounds finish and the sweep's timeout_seconds 180 change lands. L4 kernels g4-l4-v4 / g4-l4-v9-eog still QUEUED on Kaggle (2 h+). v11 gate G-A stays blocked until they leave the queue.
- 2026-09-28 19:10 IST: CLM-8B (Contrastive-LM, Stanford x NVIDIA) kept as OPTIONAL developer-side items only (it cannot run in the scored bundle: Gemma-only, stdlib skills <= 50 MiB, no parallel calls). (O1) trajectory filter for the v11 SFT set via the DeepSWE head `Contrastive-LM/deepswe-clm-heads-8k`, tried only if a cheaper Jev filter proves too weak (~$1 pod); (O2) paper-track section "can external verifiers predict which Gemma patches pass?" combining the Jev probe (AUROC 0.742, within-task 0.61, eval/judge_jev-1.13.jsonl) with a CLM run on the same 239 labelled patches. Neither blocks any gate.
- 2026-09-28 22:05 IST: v10 final = 2 review/fix rounds (round-3 reviewers stalled) + timeout_seconds 180 (sweep); 1,272 tests pass; notebook g4agent-v10 pushed, zip byte-identical to submissions/v10. First race-2 pod (cl440ut808797d) timed out waiting for GO while the build reviewed, backed up and stopped itself (~$14). Race 2 relaunched on pod 7clewitgz8132x with GO pre-set. VPS armed with the fallback (sub5 = v4 resubmit) for 2026-09-29 00:01 UTC; swapped to v10 only if race 2 passes the pre-registered KPIs.
- 2026-09-29 00:50 IST: Race 2 round 1 on pod qhvrwk3ma3tkug (US-MO-1): v10 25 vs v9_eog 24 of 74 (paired 6-5, sign p=1, union 30). Killed by the pre-registered rule on 1 unknown-tool crash (fastapi_13537: the model called `view.py` as a tool because prompts use helper names as verbs). v10 KPIs: helper availability 1.00 (v9 0.59), malformed edit_file 0.05/task (v9 3.16), max prompt 17,388; FAIL on crash 1, empty patches 6 (max 2), protected 1, scratch 1, stage-runs under 14,336 91% (min 95%), verdict line 78% (min 90%), 1 task past cap. Conclusion: plumbing fixed, solve rate unchanged; the binding constraint is fix quality. Tonight's slot stays v4 (fallback). v11 relevance: SFT targets fix quality, so it is now the main lever rather than a long shot on top.
- 2026-09-30 01:05 IST: sub5 (v4 resubmit) = 0.12 (sub3 also 0.12; sub4 v9_eog 0.06). Kaggle weekly GPU quota exhausted (no L4 evals until reset; G-A probe waits). v10.1 + review fix (one protection rule) vs v4, one faithful pod round (pod oq3hhhrwmlgrvg, compaction + L4 scale): v10.1 27 vs v4 24 /74, paired 10-7 (p=0.63), 0 crashes both, empty 2 vs 12, time 0.98x -> pre-registered rule PASS -> VPS armed with g4agent-v10 version 2 as sub6 for 2026-09-30 00:01 UTC. Golden-eval build resumed with the pre-registered repair ablation appended.
- 2026-09-30 21:40 IST: AutoHarness (huyxdang.com/autoharness, github.com/huyxdang/AutoHarness) reviewed. It has a frontier LLM read failed trajectories, edit the system prompt and agent-loop code, and keep an edit only if the dev-set score rises within an efficiency budget (AppWorld: Qwen3.5-9B 19.6% -> 49.4%, 27B 35.1% -> 72.0%). NOT adopted now: our local dev sets have ranked bundles opposite to the hidden set (v10.1 and v9_eog beat v4 locally, lose on hidden), so an automated optimiser would overfit faster; loop-code edits are illegal here (declarative bundle), leaving prompts and stdlib helpers. CONDITIONAL track: if the Pallets transfer race reproduces the hidden ranking (v4 > v10.1), Pallets becomes the first hidden-like dev set, and an AutoHarness-style loop over prompts and helpers, scored with L4-scaled time, gated on Pallets dev and confirmed on a Pallets holdout, becomes worth running.
- 2026-10-01 04:45 IST: Pallets transfer race done on OpenRouter (no pod; docs/eval/PALLETS_OR_RACE.md): v10.1 11/40 vs v4 7/40, paired 7-3, p=0.34, $1.47. Pallets does NOT reproduce the hidden v4 > v10.1 ranking, so it is not a hidden-like dev set; AutoHarness track stays off. The hidden v4>v10.1 gap (2 reads vs 1, ~2.4 tasks, SD ~1.9) is within noise; a second hidden read of v10.1 is the cheapest resolver. Pods retired by Carson 2026-09-30 (all deleted); screening races run via scripts/pallets/or_race.sh.
- 2026-10-02 10:00 IST: Grilling settled the operating rules (see memory): the LB is the experiment, one bold variable per slot, two reads per arm; queue = sub8 v10.1 (submitted by hand 09:41 IST after the VPS job died on a missing `kaggle` binary; submit_at.sh now resolves it at arm time) → v4h Oct 3-4 (v4 + the edit helper only; gate in docs/v4h/GATE.md; smoke running) → Z slot after G-A → thinking LOW after a timing check. Pods retired. P0.6 DONE (commit de51064): `scripts/make_test_adapters.py` (zb/loud/loud2, r=4 on layer 0, sha manifest; the adapter-backed model is named `<base>:<adapter>` by adk_submission, not `openai/<adapter>` as plan_A assumed) and `make_eval_kernel.py --probe lora` (notebook g4-l4-lora-probe, 473 KB, 5-task smoke on v4+zb). G-A thresholds pre-registered in docs/v11/GA_PROBE.md. Run it on Saturday's quota AFTER sub9's scoring window (no GPU kernels while a submission scores): push after ~17:30 IST Sat 4 Oct. Forum (10-01/02): sub7's crash was a platform-wide v25 regression (744807), rerun request drafted; LoRA fixed in v23/v25 per staff, no post-fix adapter score on the board; thinking was silently broken until v25 (744354), so every thinking-off verdict predates a working feature; public LB = 58 tasks.
- 2026-10-02 10:40 IST: v4h smoke 1 FAILED the gate (no-install "can't open file" + heredoc-as-tool-name crash), prompts fixed (install first; helpers are never tool names), smoke 2 PASSED (10/10 install first, 0 unreachable, 0 helper errors, 0 crashes; docs/v4h/GATE.md). sub9 = g4agent-v4h v2 armed on the VPS for 2026-10-03 00:01 UTC (05:31 IST), PID 4114087, "armed" line confirmed. sub8 (v10.1) scoring since 09:41 IST.
- 2026-10-02 11:10 IST: Saturday kernels built, not pushed (no GPU kernels while a submission scores): `kernels/g4-l4-lora-probe` (G-A, docs/v11/GA_PROBE.md) and `kernels/g4-l4-v4h-think` (thinking LOW timing, docs/v4h/THINK_TIMING.md, 10 ids = kaggle_valid_ids 6-15). Push both after sub9's scoring window closes (~17:30 IST Sat 4 Oct), G-A first. validate.py now prints every agent's gen config.
- 2026-10-02 17:00 IST: LEADER 0.24 (14/58) = Kaggle user samson8 "Yurnero", Competitions Grandmaster (rank 31), solo, 2 submissions, no public method; golds include the Nemotron reasoning challenge (LoRA r32 via Unsloth + Tinker on synthetic traces) and AI Agent Security. Ryan's replies (via reader): hidden set is from PRIVATE repos (744951); the Sep 30 wheelhouse (0.2.12, "v28") fixed KV-cache-with-LoRA (sized per submission), double-encoded tool output, dropped thoughts, thinking_budget/seed not sent (744794); the Sep 30/Oct 1 failures were a GPU outage, NOT rerun (0 score changes without a new submission; Lasme's failed one too); 12 h cap still errors the run. Since the rebuild 100 teams moved up via new submissions (0.13 band 32→49, 0.15 7→11): every read before Oct 1 (incl. v4's 0.12 x2) is on the OLD scorer; sub8 is our first on the new one. Consequences: the double-encoding fix removes part of v4h's rationale (the parser-corruption part remains); LoRA is the likeliest edge of the leader → G-A Saturday is the key run and the v11 pipeline should be built before, not after, it; sub10 = v4h_think (thinking LOW, 4-min cap; docs/v4h/THINK_SLOT.md) on Oct 4.
