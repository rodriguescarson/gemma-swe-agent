# Pallets transfer race on OpenRouter: v4 vs v10.1 (2026-10-01)

Question: do unfamiliar repos (SWE-Pallets-X dev40: click/flask/werkzeug/jinja2/markupsafe/sympy, src layouts) reproduce the
HIDDEN ranking (v4 0.12, 0.12 > v10.1 0.08), which our public-task evals did not?

Setup: `scripts/pallets/or_race.sh v4 v10` (commit 38f6d43). The pod's environment is emulated in Docker (g4-pallets-linux:local). Pre-flight
40/40 valid (gold resolves, empty patch does not). Each bundle uses its own eval_config (5 min), with compaction on. The model is
google/gemma-4-31b-it on OpenRouter, pinned to parasail/fp8 (crusoe/bf16 returned 429 on 6 of 6 probes that night), with one proxy
and one USD cap per arm. Both arms ran concurrently. Replies were paced to the modelled L4 time, but the provider was slower than
L4 (median latency 4.8 s against a modelled 1.5-1.9 s), so the tasks ran under about 3x L4 time pressure.

| | v4 | v10.1 |
|---|---|---|
| solved / 40 | **7** | **11** |
| hit 5-min cap | 25 | 21 |
| empty patch | 16 | 15 |
| model calls / cost | 957 / $0.79 | 978 / $0.68 |

Paired: v10.1-only 7, v4-only 3, both 4; two-sided sign p = 0.344.

Defects, all disclosed. The proxies were down twice, at 01:25-01:28 and 03:23-03:38 IST, because a tool time limit killed their
parent. Four tasks overlapped a gap and all four were unsolved: v4 werkzeug_664deb6, click_ecb9983 and werkzeug_019498f, and
v10.1 flask_53b8f08. Even if v4 had solved all three of its affected tasks, v4 would reach at most 10, still below 11.

Reading:
1. Pallets does NOT reproduce the hidden ranking. It ranks like every local eval did (v10.1 >= v4), and the 7-3 split is not
   significant. Pallets is therefore not the hidden-like dev set we hoped for, and the AutoHarness track stays off
   (PLAN.md 2026-09-30 21:40).
2. The "hidden ranking" itself is thin. v10.1 at 0.08 against v4 at 0.12 is one read against two, a gap of about 2.4 of about
   60 public tasks, while a single read's SD is about 1.9 tasks. Every non-hidden measurement we have (Kaggle L4, the pod pair,
   golden evals, Pallets) puts v10.1 at or above v4. The cheapest way to resolve the conflict is a second hidden read of v10.1.
3. Under heavy time pressure v10.1 hits the cap less often than v4 (21 against 25), which is its clock-driven finishing at work.
