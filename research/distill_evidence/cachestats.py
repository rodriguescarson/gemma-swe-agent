import json, glob, os, sys, statistics as st
def calls(t):
    out=[]
    for s in t.get('steps',[]):
        if s.get('source')!='agent': continue
        u=None; author=None
        if s.get('metrics'): u=s['metrics']; author=(s.get('extra') or {}).get('author')
        else:
            for tc in s.get('tool_calls') or []:
                ex=tc.get('extra') or {}
                if ex.get('usage'): u=ex['usage']; author=ex.get('author'); break
        if u: out.append((author,u.get('prompt_tokens',0) or 0,u.get('completion_tokens',0) or 0))
    return out
for d in sys.argv[1:]:
    res={}
    for l in open(os.path.join(d,'task_results.jsonl')):
        r=json.loads(l); res[r['instance_id']]=r
    U=[];Cc=[];O=[];N=[];R=[]
    for f in sorted(glob.glob(os.path.join(d,'traces','*.json'))):
        iid=os.path.basename(f)[6:-5]
        cs=calls(json.load(open(f)))
        if not cs: continue
        unc=cac=out=0; prev={}
        for a,p,c in cs:
            q=prev.get(a)
            if q is not None and p>=q: cac+=q; unc+=p-q
            else: unc+=p
            prev[a]=p+c  # completion becomes part of next prompt
            out+=c
        U.append(unc);Cc.append(cac);O.append(out);N.append(len(cs));R.append(bool(res.get(iid,{}).get('resolved')))
    tot=[u+c for u,c in zip(U,Cc)]
    print(d, 'tasks',len(U),'uncached mean',round(st.mean(U)),'cached mean',round(st.mean(Cc)),'cache share',round(sum(Cc)/sum(tot),3),'out mean',round(st.mean(O)),'calls mean',round(st.mean(N),1))
    ru=[u for u,r in zip(U,R) if r]; rc=[c for c,r in zip(Cc,R) if r]; ro=[o for o,r in zip(O,R) if r]; rn=[n for n,r in zip(N,R) if r]
    print('  resolved: n',len(ru),'uncached',round(st.mean(ru)),'cached',round(st.mean(rc)),'out',round(st.mean(ro)),'calls',round(st.mean(rn),1))
