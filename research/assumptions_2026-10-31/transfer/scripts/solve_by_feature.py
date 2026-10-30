import json, os, collections, math
BASE='<repo>'
D={r['id']:r for r in json.load(open('out/corpus_features.json'))['heldout1k']}
R=json.load(open('out/p10_runs.json'))
rows=[]
for tid in R:
    tr=f'{BASE}/eval/a6000/results/p3_think/items/v12/{tid}/task_results.jsonl'
    res=json.loads(open(tr).readline()) if os.path.exists(tr) else {}
    f=D[tid]
    rows.append(dict(id=tid, solved=bool(res.get('resolved')), src=f['has_src_dir'], style=tuple(f['style_base']), nonpy=bool(f['nonpy_src']),
                     nfiles=len(f['gold_files']), calls=len(R[tid]['calls']), repo=f['repo'], dur=res.get('duration_seconds')))
def rate(sel, label):
    n=len(sel); k=sum(r['solved'] for r in sel)
    se=math.sqrt(k/n*(1-k/n)/n) if n else 0
    print(f'  {label:42s} n={n:4d} solved={k:3d} = {100*k/n:4.1f}% (+-{100*se:.1f})' if n else f'  {label}: n=0')
print('P10 v12, solve rate by convention feature (repo-confounded)')
rate(rows,'all')
rate([r for r in rows if r['src']],'src/ layout'); rate([r for r in rows if not r['src']],'flat layout')
ut=lambda r: r['style'] and all(s in('unittest','absltest') for s in r['style'])
rate([r for r in rows if ut(r)],'unittest-only test files'); rate([r for r in rows if r['style']==('pytest',)],'pytest-style test files')
rate([r for r in rows if r['nonpy']],'gold touches non-.py source'); rate([r for r in rows if not r['nonpy']],'gold .py only')
rate([r for r in rows if r['nfiles']==1],'gold 1 file'); rate([r for r in rows if r['nfiles']>=2],'gold 2+ files')
# within-repo: src vs flat can't be separated (repo-level). show per-repo rates sorted
import statistics
print('mean calls/run', statistics.mean(r['calls'] for r in rows), ' median dur', statistics.median(r['dur'] for r in rows if r['dur']))
cap=[r for r in rows if r['dur'] and r['dur']>=295]
print('runs at/over 295 s:', len(cap), 'solved among them', sum(r['solved'] for r in cap))
