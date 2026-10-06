# N1 locate recall off-repo + N4 forum scan (2026-10-06)

Both free: CPU only, no model calls, no OpenRouter, no Kaggle submissions or kernel pushes. Gaps doc: `docs/GAPS_2026-10-06.md`.

## N1. Locator file recall on heldout1k (1,044 tasks)

**What was measured.** The rank of a gold-patch `.py` file (best rank over all gold `.py` files) in the shipped locator
`submissions/v5h2/skills/swe-tools/scripts/locate.py`. A temp copy prints 10 files instead of 8 so R@10 exists; the ranking is
byte-for-byte the same. The model only ever sees the top 8. All 1,044 pre-flight-valid tasks (`data/heldout1k/all_valid_ids.txt`)
were run, along with the 74 public tasks through the same script. Each snapshot is extracted to a temp dir and deleted after; the
run left 0 dirs behind and free disk stayed above 50 GB.

**Two query arms, same locator:**
- `query` is a deterministic **approximation** of the query `prompts/locator.md` tells the model to pass ("identifiers, error
  text and keywords from the issue", leaving out URLs, version numbers, environment dumps and doc links). In order: backticked
  code identifiers, traceback file and function names, exception names, other snake/Camel/dotted identifiers, then the words
  from the error message, then keywords that are not stopwords, capped at 300 chars. Several things are removed first: URLs,
  markdown link targets, version numbers, `pkg==x` pins, environment lines (`Python 3.x`, `OS: ...`) and the repo's template
  lines (any line found in at least 15% of that repo's statements, minimum 3). It is not what Gemma actually types. The median
  query is 158 chars (125 on the public set). 5 held-out queries came out empty and count as misses.
- `raw` is the problem statement itself (first 4,000 chars), as `eval/locate_recall.py` did.

| slice (arm = query) | n | R@1 | R@3 | R@5 | R@10 |
|---|---|---|---|---|---|
| heldout1k, all | 1044 | 0.714 | 0.871 | 0.914 | 0.947 |
| heldout1k, title-only statements | 211 | 0.616 | 0.758 | 0.801 | 0.858 |
| heldout1k, full statements | 833 | 0.738 | 0.899 | 0.942 | 0.970 |
| public 74 (same script) | 74 | 0.486 | 0.730 | 0.797 | 0.851 |

| slice (arm = raw statement) | n | R@1 | R@3 | R@5 | R@10 |
|---|---|---|---|---|---|
| heldout1k, all | 1044 | 0.688 | 0.872 | 0.924 | 0.964 |
| heldout1k, title-only | 211 | 0.611 | 0.768 | 0.834 | 0.877 |
| heldout1k, full | 833 | 0.707 | 0.898 | 0.947 | 0.986 |
| public 74 | 74 | 0.446 | 0.649 | 0.703 | 0.838 |

95% Wilson intervals:
- heldout1k query: R@1 0.714 [0.685, 0.740]; R@8, the cut-off the model actually sees, 0.942 [0.926, 0.954].
- public 74 query: R@1 0.486 [0.376, 0.598]; R@8 0.838 [0.738, 0.905].

Paired, query against raw on R@1: on held-out, 67 tasks hit only with the query and 40 only with the raw statement (sign test
p of about 0.01). On public, the split is 5 to 2. The extracted query helps at rank 1, but the raw statement does slightly
better at R@5 and R@10 (0.964 against 0.947 at R@10).

**Runtime** (M-series Mac, 4 parallel jobs): median 0.59 s, p90 2.0 s, max 16.6 s per call. Every call exited with rc 0. The
Kaggle sandbox is slower, so read these as relative numbers.

**By repo** (query arm, R@1 / R@10; the full table, with the raw arm too, is in `research/locate_recall_2026-10-06/summary.md`):

| Weakest | R@1 / R@10 | Strongest | R@1 / R@10 |
|---|---|---|---|
| PyCQA/isort (n=81) | 0.38 / 0.88 | boltons (n=64) | 0.94 / 0.98 |
| python-attrs/cattrs (n=63) | 0.43 / 0.78 | Python-Markdown (n=35) | 0.89 / 1.00 |
| andialbrecht/sqlparse (n=14) | 0.36 / 0.93 | more-itertools (n=88) | 0.85 / 0.98 |
| fastapi/typer (n=9) | 0.44 / 0.78 | pypa/packaging (n=120) | 0.82 / 0.99 |

On the public 74, fastapi (n=31) is at 0.35 / 0.87 and rich (n=42) at 0.57 / 0.83.

**Reading.**
1. Off-repo, the locator is not the bottleneck. In 94% of tasks a gold file is among the 8 files the model sees, and in 71%
   it is at rank 1. Fixing this tool has more headroom on the public set (R@1 0.49) than on held-out repos, mostly because of
   fastapi.
2. The public 74 is the harder set for retrieval, by 23 points at R@1. That is consistent with the B1 trade-off: public gains
   do not have to transfer. Retrieval tuning against the public 74 (for example, docs_src demotion for fastapi) would be fitting
   one repo.
3. Title-only statements cost about 12 points at R@1 and 11 at R@10. That is the gap a repro-first locator (S3) or a second
   query from the first file's symbols could close.
4. Comparison with earlier numbers: the v9 trace-measured recall on real model queries (`research/own_data.md`, 124 tasks) was
   R@1 54% / R@3 73% / R@10 81%. On the public set the approximated query gives 0.49 / 0.73 / 0.85, close enough that the
   approximation is a fair stand-in. `eval/ledger.md` (09-25) recorded R@1 0.40 to 0.62 on rich, requests and httpx with the
   raw statement.
5. Caveats: 102 held-out tasks also change non-`.py` files. 223 have more than one gold `.py` file, and only the best-ranked one
   counts, so a multi-file fix can still be under-located. The held-out statements are PR descriptions from the miner, and they
   often name the file. The hidden tasks come from private repos with unknown statement style.

Reproduce:

```bash
.venv/bin/python eval/locate_recall_heldout.py --ids data/heldout1k/all_valid_ids.txt --out heldout_rows.jsonl --jobs 4
.venv/bin/python eval/locate_recall_heldout.py --tasks data/tasks.jsonl --snapshots data/raw/snapshots \
  --ids data/kaggle_valid_ids.txt --out public74_rows.jsonl
.venv/bin/python eval/locate_recall_heldout.py --summarize heldout_rows.jsonl --public public74_rows.jsonl
```

Rows (one per task, with the extracted query and both ranks) are in `research/locate_recall_2026-10-06/`. Tests:
`tests/test_locate_recall_heldout.py` (8 tests, written before the script).

## N4. Forum scan, activity since 2026-10-05 00:00 UTC

**Method.** `kaggle competitions topics list gemma-4-developer-agent`, pages 1 to 7 (134 topics; page 8 was empty). I ran
`topics show` (table and JSON) on 91 topics: every one created since 10-05, plus every older one with comments. Of those, 32
had a post or comment dated 10-05 or later. Forum text is treated as data. Only comments dated 10-05 or later were mined from
older threads. Fetched 2026-10-06 around 17:40 UTC.

No post in the window claims a leaderboard score of 0.15 or higher alongside a method. The closest are one LB 0.18 team's
local numbers (Wilmer E. Henao, 745855) and a local 129-task sweep (746250). The organiser posts in the window are Elan
Markowitz's 745998 and his reply on 746046. There is nothing from ryanholbrook since 10-05. The open scorer questions
(745805: 12 h overrun, compaction settings, verification timeout, rerun) remain unanswered.

### Findings, most actionable first
1. **746250** (Ayush Thakur, 10-06): a local sweep on gemma-4-31b-it-qat-w4a16-ct over all 129 public tasks, one run per
   setting, with a 60-minute cap on RTX 6000 Pro rather than L4.
   - Thinking disabled scored 23/129, against 48 to 51 with thinking on. Hiding thought summaries scored 35/129.
   - Temperature 0.4 and 1.0 tied at 51, and temperature 0.0 got 47. A thinking budget of 2,048 gave 50 and 6,144 gave 48.
   - Active-time cap: 6 min gave 37, 10 min 46, 15 min 54, 20 min 49, 60 min 51.
   - Cutting tool calls from 50 to 25 took 29% off the median runtime and lost 14 tasks.
   - Graph tools: all 21 semantic searches returned empty, and no graph call surfaced a gold file.
   - A repeat of the same config fell from 55 to 48, so noise is about ±7 tasks.

   For us: v5h2 ships `include_thoughts: false`, which turns thinking off entirely (745059, see
   `research/2026-10-04_kaggle_scan.md`). This is the largest single lever anyone has reported, which supports the S4 thinking
   screen. Our 5-minute cap is far below the 10-minute cap that already cost him 8 tasks.
2. **745059**, comment by Narendar Kumar Ale (10-05): `include_thoughts: true` with `thinking_budget: 2048` failed all 24
   tasks locally with 0 tool calls, because vLLM rejects `thinking_token_budget` unless the server is started with
   `--reasoning-config`. That is a launch flag submissions cannot reach. Quoted: "every one of 24 tasks failed immediately".
   For us: the S4 screen and any v6p thinking variant should first test thinking on with **no** `thinking_budget`, and check
   the scorer's server flags before spending a submission. A budget setting could zero a whole run.
3. **745855** (ayoub diri; comments by Wilmer E. Henao, LB 0.18, and Emilio Dávola, 10-05):
   - 6 of 129 public tasks have hidden tests that import modules or names introduced only by the gold patch: fastapi_15661,
     15030, 14609, 15785, 15745 and rich_3930. Counting loosely, 16 of 129.
   - His local solve rate is 0 of 4 on those, against 41 of 109 on the rest.
   - fastapi_14301 fails at collection on a Starlette mismatch (`on_startup`), independently confirmed in 745980.

   For us: matches our "~22 public tasks unsolvable" note. Mark these as known zeros in the public-74 keep rule's reading, and
   do not tune for them.
4. **745998 and 746046** (organiser Elan Markowitz, 10-05):
   - No private task touches an `async def`, and async functions make up at most 1.8% of functions in the private repos. The
     code graphs will not be updated. So the async gap that broke the shipped graphs on fastapi and httpx does not apply to
     the hidden set, which is relevant to the N2 re-test. Ayush's empty semantic searches (finding 1) are on the public graphs.
   - Organiser ruling: LoRA training data may be trajectories from other open-weight models, or public SWE-style trajectory
     datasets on Hugging Face. Quoted: "Both cases are permitted." This widens the data sources for S2's SFT/DPO.
5. **745774** (Emilio Dávola and Hitarth Jain, 10-05): looping and edit-thrash data.
   - Three of 13 tasks hit the 100-call ceiling.
   - Prompt rules ("never repeat a command", "py_compile before submit") stop binding once the agent loops. A patch that does
     not compile was submitted even though the instruction was in the prompt.
   - Their consensus: a lower call budget contains loops better than prompt wording. Their next idea is to re-read the edited
     region after every edit.

   For us: supports the S6 decision (loops contained by best-of-3) and the deterministic select.py running the repro and test
   rather than trusting the model to.

Also seen:
- 745977 (mugurb, 10-05): when a context overflow ends a task, the scorer drops an already-correct working-tree edit (8,192
  output + 24,577 input > 32,768). No answer yet. Our `max_output_tokens: 4096` leaves more input headroom.
- 746008 and 746169: the 12 hours cover all ~120 hidden tasks, public and private. Some teams had budgeted for 60.
- 745775 and 745850: the public `wheels/` set is missing fastapi test dependencies (inline-snapshot, dirty-equals and others).
  Separately, rich_3296 passes only on Pygments 2.17.2.
- 746235: unused graph tools can be left out of `agent.yaml` (participant answer, not an organiser ruling).
- 746212 and 745980: wheelhouse v28 install semantics are unanswered.
- Nothing on ParallelAgent or best-of-N in the window. The only multi-agent mention is a 3-agent pitch with no numbers
  (743007).

### Public leaderboard, top 10 (fetched 2026-10-06 ~17:40 UTC)

| # | team | score | last submission (UTC) |
|---|---|---|---|
| 1 | Yurnero | 0.24 | 2026-10-06 01:00 |
| 2 | Shan Yang | 0.18 | 2026-10-06 03:13 |
| 3 | Wilmer E. Henao | 0.18 | 2026-10-06 00:03 |
| 4 | Tsunato Nakai | 0.18 | 2026-10-06 01:27 |
| 5 | AGENTS.md | 0.17 | 2026-10-06 00:02 |
| 6 | Anh Nguyen Duong | 0.17 | 2026-10-03 05:17 |
| 7 | Reiji Kobayashi | 0.17 | 2026-10-06 00:06 |
| 8 | Kirill Labzin | 0.17 | 2026-10-06 00:00 |
| 9 | Bardia Bahadori | 0.17 | 2026-10-03 04:05 |
| 10 | youchy | 0.17 | 2026-10-05 14:07 |

The tie at 0.17 runs 12 deep: Haoyu Wang and Sintonizando are also on 0.17. In the first 200 rows there are 63 teams on 0.15
and 120 or more on 0.13. One step of 0.01 is about one task of ~60. The leader (0.24) has posted no method. In the window,
Yurnero only commented on public/private split mechanics (746008).

Sources: topic ids above, with the dates given. Raw fetches are in the session scratchpad and not committed.
