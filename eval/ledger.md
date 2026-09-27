# Run ledger (every paid run and every Kaggle submission)

| when (UTC) | what | cost | result | notes |
|---|---|---|---|---|
| 2026-09-25 17:55 | Kaggle sub 56557072: v0 = sample minus adapters, no eval_config, include_thoughts false, out 8192, seed 42 | free | pending | calibration: packaging + run duration |
| 2026-09-25 17:59 | Pod 1fs5qx44uhc3m7 (A40 48GB, secure CA-MTL-1) created | $0.49/h | running | bootstrap: env + model + data |
| 2026-09-25 18:40 | smoke v1 (3 tasks) after env fixes | pod | rich_3006 resolved in 122 s | harness loop validated end to end |
| 2026-09-25 19:20 | env oracle, all 129: gold pass 47, no-patch pass 0 | pod | dev set = 47 (rich 40, requests 5, httpx 1, fastapi 1) | fastapi blocked by pydantic 1.x on py3.12; limitation recorded |
| 2026-09-25 19:45 | locate.py recall (issue text as query), rich+requests+httpx n=53 | free | R@1 0.40 to 0.62, R@3 0.55 to 0.77, R@8 0.70 to 0.91 after boilerplate stripping + stopwords + stem boost | held-out fastapi n=67 old: R@1 0.19, R@3 0.46 |
| 2026-09-25 20:20 | sweep1 launched: v2, v1_t10, v1_t10_low, v1 on dev47, 6 min cap | ~$1.7 | pending | first 6 v2 tasks: heavy exact-repeat loops persist |
| 2026-09-25 22:10 | Kaggle-env oracle (official Getting Started recipe, CPU kernel g4-oracle-all), all 129 | free | gold pass 74/129: fastapi 31, rich 42, requests 1, httpx 0; median 8.2 s/task setup+verify | faithful dev set = data/kaggle_valid_ids.txt (74) |
| 2026-09-25 23:27 | sweep1 done (pod dev47, 6 min cap, conc 4) | ~$2.7 pod total | v1 9, v1_t10 8, v1_t10_low 12, v2 11 of 47; all paired p>0.45 | exact-repeat calls 17-25 of ~45 per task = the dominant failure; sampling alone does not fix it |
| 2026-09-25 23:00 | Kaggle L4x4 smoke (v2, 3 tasks) | free quota | 1/3; vLLM TP4 up in 348 s; ~2.2 s per tool call | wall clock is not binding at 5 min; loops and patch quality are |
| 2026-09-25 23:29 | pod 1fs5qx44uhc3m7 STOPPED (idle) | | | disk wiped on stop; bootstrap + data fetch needed on restart |
| 2026-09-26 00:01 | Kaggle sub2 queued: v2 + eval_config 5 min/60 calls/180 s | free | pending | |
| 2026-09-26 03:30 | Kaggle L4 eval, 74 valid tasks, 5 min/60 calls/80 turns: v2 vs v3 (staged fresh-context pipeline) | free quota (~7.5 GPU-h) | v2 19/74 (136 s/task), v3 22/74 (163 s/task); v3-only 8, v2-only 5, p=0.58 | empty patches v2 23 vs v3 14; v3 hit 80-turn cap 6x -> raise turns |
| 2026-09-26 04:30 | Kaggle sub1 v0 scored | free | public 0.10 (about 6/60) | leaders 0.13; packaging path proven |
| 2026-09-26 04:30 | Kaggle sub2 (v2) FAILED | free | error_description: "requested more CPU, GPU or TPU resources than are available" | cause: two L4 eval kernels launched while it scored. Rule: no GPU kernels during scoring |
| 2026-09-26 04:40 | v3 empty-patch analysis (14/74) | free | 2 unknown-tool crashes (search_similar_code), fixer loops to 80-turn cap 6x, "already fixed" 3x | v4 = all real tools on every stage + no-empty-diff rule + 150 turns |
| 2026-09-26 04:45 | Kaggle L4 eval v4, 74 tasks, 5 min/70 calls/150 turns | free quota | pending | |
| 2026-09-26 07:20 | RunPod 2x H100 SXM pod 87kqp9osz3gn6o (ssh alias h100) | $6.98/h | booting | eval lanes + parity oracle + SFT data; self-stops 45 min after chain |
| 2026-09-26 08:30 | tests/ added (64 pass) + scripts/ship.sh gate | free | caught a live __pycache__ in v5 on first run | converter: nebius 3k rows -> 314 kept after fixing finish/task_tracker/path bugs |
| 2026-09-26 09:58 | H100 pod chain: v5 at 2 tasks/GPU; LoRA gate; SFT smoke | ~$20 pod | v5 17/74 (worse than v4 21/74); vLLM 0.19.1: "Gemma4ForConditionalGeneration does not support LoRA yet" -> adapter route blocked on the scorer; smoke run failed (empty selection bug, fixed + tested) | pod self-stopped after verified backup train1 (HF private repo) |
| 2026-09-26 11:00 | CORRECTION | | sub2 resource error is platform-side (other teams hit it); our LoRA "not supported" came from PyPI vllm, the scorer's patched wheel loads LoRA but wipes it (743508) | posted comment #3528695 on 743213 (slot restore + local-testing note) |
| 2026-09-26 12:00 | preflight gate added (pod/preflight.sh): compileall, tests, patched-vllm/env check, bundle validation, inference smoke, exact-args LoRA request | free | 216 tests pass | mandatory before any future benchmark chain (test enforces) |
| 2026-09-26 12:10 | shipped graph tools vs locate.py, file recall with issue text (eval/graph_recall.py, CPU) | free | graph tools n=74: R@1 0.04, R@10 0.19; paired n=40: graph R@1 0.05 / R@3 0.05 / R@10 0.17 vs locate.py 0.53 / 0.70 / 0.85 | "graph-first localization" rejected with data; paper-track result |
| 2026-09-26 12:33-14:27 | v7/v8 chain | ~$14 wasted | preflight failed (compileall wrote __pycache__ into bundles); abort path did not stop the pod -> 2 h idle | fixed + tested; then 1 Linux-only failure: skill script select.py shadowed stdlib select (v5 helpers broken on Linux -> v5 result invalid) |
| 2026-09-26 14:50 | new pod 2wyl66nmji13p1 (2x H100, AP-IN-1) with supervisor + canary + Linux-test gate | $6.98/h | running | v7 vs v8, 74 tasks each |
| 2026-09-26 16:40 | v7 vs v8 (74 tasks each, fair, preflight+canary gated) | ~$14 | v4 26/13E, v7 24/13E (2W/4L), v6 22/13E, v8 21/16E (3W/8L) | v4 stays for sub 00:01 UTC; fix quality is the frontier (GOLD_EDIT_FAILED 23-31 across configs); pod self-stopped after verified backup |
