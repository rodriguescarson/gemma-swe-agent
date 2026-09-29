# How often does a gold patch create a new file, and a new ROOT-level module with a scratch-like prefix
# (hidden.md T2, defects F/I)? Run from the repo root: python3 research/path020/newfile_rate.py > research/path020/newfile_rate.out
import json, re
PRE = re.compile(r'^(repro|reproduce|scratch|debug|tmp|temp|try|demo)', re.I)  # _swe_common._SCRATCH_ROOT
for name, path in (('competition 129', 'data/tasks.jsonl'), ('pallets 476', 'data/pallets/tasks.jsonl')):
    n = adds = root = hits = 0
    for line in open(path):
        t = json.loads(line); n += 1
        new = re.findall(r'^--- /dev/null\n(?:.*\n)?\+\+\+ b/(\S+)', t['patch'], re.M)
        new += [m for m in re.findall(r'^diff --git a/\S+ b/(\S+)\nnew file mode', t['patch'], re.M) if m not in new]
        adds += bool(new)
        root += sum('/' not in f for f in new)
        hits += sum('/' not in f and bool(PRE.match(f)) for f in new)
    print(f'{name}: gold patches that add any file {adds}/{n}; new root-level files {root}; root files with a scratch-like prefix {hits}')
