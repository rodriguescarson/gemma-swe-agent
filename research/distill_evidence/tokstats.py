import json, glob, os, sys, statistics as st
def usage_of(step):
    u=None
    if step.get('source')!='agent': return None
    if step.get('metrics'): return step['metrics']
    for tc in step.get('tool_calls') or []:
        ex=tc.get('extra') or {}
        if ex.get('usage'): return ex['usage']
    return None
def run(d):
    res={}
    tr=os.path.join(d,'task_results.jsonl')
    if os.path.exists(tr):
        for l in open(tr):
            r=json.loads(l); res[r['instance_id']]=r
    rows=[]
    for f in sorted(glob.glob(os.path.join(d,'traces','*.json'))):
        t=json.load(open(f))
        iid=os.path.basename(f)[6:-5]
        P=C=CA=n=0; maxp=0
        seen=set()
        for s in t.get('steps',[]):
            u=usage_of(s)
            if not u: continue
            # tool-call steps with multiple calls share usage; count once per step
            P+=u.get('prompt_tokens',0) or 0; C+=u.get('completion_tokens',0) or 0; CA+=u.get('cached_tokens',0) or 0; n+=1
            maxp=max(maxp,u.get('prompt_tokens',0) or 0)
        r=res.get(iid,{})
        rows.append(dict(iid=iid,P=P,C=C,CA=CA,n=n,maxp=maxp,res=r.get('resolved'),dur=r.get('duration_seconds')))
    return rows
def summ(name,rows):
    rows=[r for r in rows if r['n']>0]
    if not rows: print(name,'none'); return
    def q(xs,p): xs=sorted(xs); return xs[min(len(xs)-1,int(p*len(xs)))]
    P=[r['P'] for r in rows]; C=[r['C'] for r in rows]; N=[r['n'] for r in rows]
    rs=[r for r in rows if r['res']]
    print(f"{name}: tasks={len(rows)} resolved={len(rs)} | calls med {st.median(N)} p90 {q(N,.9)} | input/task mean {st.mean(P):.0f} med {st.median(P):.0f} p90 {q(P,.9)} | output/task mean {st.mean(C):.0f} med {st.median(C):.0f} p90 {q(C,.9)} | maxprompt p90 {q([r['maxp'] for r in rows],.9)}")
    if rs:
        print(f"   resolved only: input mean {st.mean([r['P'] for r in rs]):.0f} output mean {st.mean([r['C'] for r in rs]):.0f} calls mean {st.mean([r['n'] for r in rs]):.1f}")
for d in sys.argv[1:]:
    summ(d.split('eval/',1)[-1], run(d))
