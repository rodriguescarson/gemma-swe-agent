import json, glob, os, collections, statistics as st
def load(d):
    out={}
    for p in sorted(glob.glob(d+'/traces/trace_*.json')):
        out[os.path.basename(p)[6:-5]]=json.load(open(p))
    return out
def ex(s):
    e=s.get('extra')
    return e if isinstance(e,dict) else {}
for name in ('tr_v12','tr_garble'):
    T=load(name)
    ids=data_ids=None
    calls=[];nudges=collections.Counter();tools=collections.Counter()
    ntask=0
    for i,t in T.items():
        if name=='tr_garble':
            pass
        ntask+=1
        for s in t['steps']:
            e=ex(s)
            et=e.get('event_type')
            if et=='continuation_nudge':
                m=s['message']
                k='toolcall_cut' if 'tool call finished closing' in m else ('length' if 'token limit while thinking' in m else 'plain')
                nudges[k]+=1
            m=s.get('metrics')
            if m and isinstance(m,dict) and m.get('completion_tokens') is not None:
                calls.append(m['completion_tokens'])
    calls.sort()
    n=len(calls)
    q=lambda p: calls[int(p*(n-1))]
    print(name,'tasks',ntask,'llm calls',n,'compl tokens mean',round(st.mean(calls)),'p50',q(.5),'p90',q(.9),'p99',q(.99),'max',calls[-1],
          '>4096',sum(c>4096 for c in calls),'>=8000',sum(c>=8000 for c in calls),'nudges',dict(nudges))
