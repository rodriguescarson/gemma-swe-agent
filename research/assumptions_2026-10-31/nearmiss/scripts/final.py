import sys, json, re, collections, os
sys.path.insert(0,'<scratch>/assume/nearmiss/scripts')
import parse_logs as P
N=P.N
tasks={json.loads(l)['instance_id']:json.loads(l) for l in open('<repo>/data/tasks.jsonl')}
ents=json.load(open(N+'/patches_main.json'))
cl={d['idx']:d for d in json.load(open(N+'/classified.json'))}
st=json.load(open(N+'/static_checks.json'))
ti=json.load(open(N+'/test_files.json')); a2=json.load(open(N+'/a2_files.json'))
PASS=('PASSED','XPASS')
def is_test_or_doc(f): return bool(re.search(r'(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|conftest\.py$|^docs/|\.md$',f))
def parse_files(patch):
    fs=[];new=set()
    # handle both "diff --git" patches (agent) and bare ---/+++ patches (gold)
    for blk in re.split(r'(?m)^(?=--- )',patch):
        m=re.search(r'^\+\+\+ b/(.*)$',blk,re.M)
        if not m: continue
        f=m.group(1).strip()
        fs.append(f)
        if re.match(r'--- /dev/null',blk) or 'new file mode' in blk.split('\n@@')[0]: new.add(f)
    if not fs:
        for blk in re.split(r'(?m)^(?=diff --git )',patch):
            m=re.match(r'diff --git a/(.*?) b/(.*)\n',blk)
            if m: fs.append(m.group(2))
    return fs,new
def srcfiles(patch):
    fs,new=parse_files(patch)
    out=[]
    for f in fs:
        if not f.endswith('.py'): continue
        if is_test_or_doc(f): continue
        if f in new and '/' not in f: continue            # top-level new file = scratch (repro.py ...)
        out.append(f)
    return out

# ---- existing-test (A1 U A2) run
def load_exist(run,inp):
    rows=[json.loads(l) for l in open(f'{N}/gr/runs/{run}/replay_results.jsonl')]
    ents_=json.load(open(inp)); out={}
    for r in rows:
        lf=f"{N}/gr/runs/{run}/replay_logs/{r['idx']}_{r['task']}.log"
        txt=open(lf,errors='replace').read() if os.path.exists(lf) else ''
        out[r['idx']]=(ents_[r['idx']],r,P.parse_log(txt))
    return out
ex={}
if os.path.exists(N+'/gr/runs/nm_exist/replay_results.jsonl'):
    ex=load_exist('nm_exist',N+'/exist_in.json')
EXB={};EXG={};EXF={}
for i,(e,r,p) in ex.items():
    if e['cfg']=='empty': EXB[e['task']]=p
    elif e['cfg']=='gold': EXG[e['task']]=p
def exist_catch(i):
    """nodes of the existing test files that pass at base and gold but fail (or vanish) with this patch"""
    e=ents[i]; t=e['task']
    key=[k for k,(ee,r,p) in ex.items() if ee['cfg'].startswith('fail:') and ee['task']==t and ee['patch']==e['patch']]
    if not key: return None
    p=ex[key[0]][2]; r=ex[key[0]][1]
    if t not in EXB or t not in EXG: return None
    good={n for n,s in EXB[t]['nodes'].items() if s in PASS}&{n for n,s in EXG[t]['nodes'].items() if s in PASS}
    pp={n for n,s in p['nodes'].items() if s in PASS}
    bad=sorted(good-pp)
    return dict(n_existing=len(good),n_bad=len(bad),bad=bad[:5],run_resolved=r['resolved'],collection=bool(p['interrupted']) or (not pp and bool(p['collection_errors'])))
rows=[]
for i,e in enumerate(ents):
    d=cl[i]
    if d['resolved']: continue
    t=e['task']
    srcs=srcfiles(e['patch']); gsrc=srcfiles(tasks[t]['patch'])
    s=st[i]
    comp_fail=[c[0] for c in s['py_compile'] if c[1] and c[0] in srcs]
    imp_fail=[c[0] for c in s['import'] if c[1] and not c[0].startswith('repro')]
    if not srcs: fr='no_source_edit'
    elif set(srcs)==set(gsrc): fr='same_files'
    elif set(srcs)&set(gsrc): fr='right_file_plus' if set(srcs)>set(gsrc) else 'right_file_partial'
    else: fr='wrong_file'
    ec=exist_catch(i)
    rows.append(dict(idx=i,task=t,cfg=e['cfg'],cls=d['cls'],file_rel=fr,srcs=srcs,gsrc=gsrc,comp_fail=comp_fail,imp_fail=imp_fail,exist=ec,has_exist_files=bool(ti[t]['existing'] or a2.get(t)),
                     f2p=d['f2p'],f2p_fail=d['f2p_fail'],p2p_fail=d['p2p_fail'],summary=d['summary']))
json.dump(rows,open(N+'/final_rows.json','w'),indent=1)
if __name__=='__main__':
    print(len(rows),'failing distinct patches')
    print('file_rel x cls'); ct=collections.Counter((r['file_rel'],r['cls']) for r in rows)
    for k,v in sorted(ct.items()): print('  ',k,v)
