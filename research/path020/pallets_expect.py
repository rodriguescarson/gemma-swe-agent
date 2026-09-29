# Expected v4-level solve rate on Pallets subsets if ONLY gold churn (or only statement length) mattered,
# Run from the repo root: .venv/bin/python research/path020/pallets_expect.py > research/path020/pallets_expect.out
# using the public pooled per-stratum rates from research/hidden_probes/strata.out.
import json, sys, statistics
sys.path.insert(0, '.venv/lib/python3.12/site-packages')
from swegemma.difficulty import extract_task_metrics as analyze_task
CH = {'<=10': 0.48, '<=40': 0.26, '>40': 0.05}
WD = {'<25': 0.09, '<60': 0.33, '<150': 0.65, '>=150': 0.38}
def cb(c): return '<=10' if c <= 10 else '<=40' if c <= 40 else '>40'
def wb(w): return '<25' if w < 25 else '<60' if w < 60 else '<150' if w < 150 else '>=150'
tasks = {json.loads(l)["instance_id"]: json.loads(l) for l in open("data/pallets/tasks_prstyle.jsonl")}
comp = {json.loads(l)["instance_id"]: json.loads(l) for l in open("data/tasks.jsonl")}
def ids(p): return [l.strip() for l in open(p) if l.strip()]
kv = ids('data/kaggle_valid_ids.txt')
for name, src, sel in (('public74', comp, kv), ('pallets dev40', tasks, ids('data/pallets/dev40_ids.txt')),
                       ('pallets dev204', tasks, ids('data/pallets/dev_ids.txt')),
                       ('pallets-org dev131', tasks, [i for i in ids('data/pallets/dev_ids.txt') if not i.startswith('sympy_')])):
    ms = [analyze_task(src[i]) for i in sel]
    ec = statistics.mean(CH[cb(m.total_churn)] for m in ms)
    ew = statistics.mean(WD[wb(m.prompt_words)] for m in ms)
    dist = {k: sum(1 for m in ms if cb(m.total_churn) == k) for k in CH}
    print(f'{name:20s} n={len(ms):3d} churn strata {dist}  expected rate from churn {ec:.2f}, from words {ew:.2f}')
