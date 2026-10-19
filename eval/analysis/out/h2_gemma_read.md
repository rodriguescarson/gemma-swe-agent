<!-- eval/analysis/h2_read.py eval/a6000/results/h2_gemma --mode seq -->
| task | INV | DOM | COMPOSE | rollouts | crashed | selection | chosen solved | base solved | library |
|---|---|---|---|---|---|---|---|---|---|
| arrow_06fe693 | new tree | kept base | kept base | 4 | 0 | failed: no candidate produced an artifact (finals-only poo | False | False | False |
| arrow_0fe5f06 | kept base | new tree | kept base | 4 | 0 | ok (c1) | True | False | False |
| arrow_1278a21 | kept base | kept base | kept base | 4 | 0 | ok (c1) | False | False | False |
| arrow_22acd93 | kept base | kept base | kept base | 4 | 0 | ok (c1) | False | False | False |
| arrow_30d16c1 | kept base | kept base | kept base | 4 | 0 | ok (c1) | False | False | False |
| arrow_310cef8 | kept base | kept base | kept base | 4 | 0 | failed: no candidate produced an artifact (finals-only poo | False | False | False |
| arrow_384fb74 | kept base | kept base | kept base | 4 | 0 | ok (c1) | False | False | False |
| arrow_3f9837e | kept base | kept base | kept base | 4 | 0 | ok (c1) | True | True | False |

MECHANICS PASS: 8 of 8 tasks with three valid stages and no crashed rollout (pass >= 6).
ADOPTIONS: 0 of 8 (successful selection and a library entry).
SIGNAL NO: chosen runs solved 2 of 8 (arrow_0fe5f06, arrow_3f9837e); base runs solved 1; pre-registered base expectation 1.8 of 8. n = 8 is descriptive.

Improver sessions (post hoc audit of the replies):
  c1: 8 sessions, 8 overflowed the context, 0 bare KEEP_BASE, 1 ended with a question
  dom1: 8 sessions, 5 overflowed the context, 1 bare KEEP_BASE, 0 ended with a question
  experience: 6 sessions, 6 overflowed the context, 0 bare KEEP_BASE, 0 ended with a question
  inv1: 8 sessions, 4 overflowed the context, 3 bare KEEP_BASE, 0 ended with a question
  all: 30 sessions, 23 overflowed

Same-tree replays (post hoc): 42 pairs of rollouts of one tree on one task; 17 repeat exactly (outcome, calls, patch size, seconds within 2 s); 40 have the same outcome.
