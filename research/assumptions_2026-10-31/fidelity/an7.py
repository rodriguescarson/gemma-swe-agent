import json, glob, os
valid=set(l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip())
for name,td in (('v12','tr_v12'),('garble','tr_garble')):
    big=[]
    for p in sorted(glob.glob(td+'/traces/trace_*.json')):
        i=os.path.basename(p)[6:-5]
        if i not in valid: continue
        t=json.load(open(p))
        for s in t['steps']:
            m=s.get('metrics')
            if m and m.get('completion_tokens',0)>3500:
                tcs=s.get('tool_calls') or []
                arg_chars=sum(len(json.dumps(tc.get('arguments'))) for tc in tcs)
                big.append((m['completion_tokens'],len(s.get('message') or ''),arg_chars,i,[tc['function_name'] for tc in tcs]))
    big.sort(reverse=True)
    print(name,'calls >3500 tokens:',len(big))
    for b in big[:10]: print('   ',b)
