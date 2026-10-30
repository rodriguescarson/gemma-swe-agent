import json, glob, os, re, collections
valid=set(l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip())
for name,td in (('v12','tr_v12'),('garble','tr_garble')):
    sub=collections.Counter(); fails=collections.Counter(); runs=collections.defaultdict(set); ident=0
    for p in sorted(glob.glob(td+'/traces/trace_*.json')):
        i=os.path.basename(p)[6:-5]
        if i not in valid: continue
        t=json.load(open(p))
        for s in t['steps']:
            for tc in (s.get('tool_calls') or []):
                if tc.get('function_name')!='run_command': continue
                cmd=(tc.get('arguments') or {}).get('command') or ''
                for m in re.finditer(r'\bgit\s+(?:-C\s+\S+\s+)?([a-z-]+)',cmd):
                    g=m.group(1); sub[g]+=1; runs[g].add(i)
                obs=s.get('observation'); c=obs.get('content') if isinstance(obs,dict) else str(obs)
                if re.search(r'Please tell me who you are|unable to auto-detect email|empty ident',str(c)): ident+=1
    print(name,'git subcommand counts',dict(sub.most_common(12)),'identity errors',ident)
    print('   runs using stash/checkout/commit/apply/restore/reset:',{g:len(runs[g]) for g in ('stash','checkout','commit','apply','restore','reset','clean','switch') if runs[g]})
