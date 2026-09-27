import json,os,re,collections
R='/Users/carson/Projects/gemma-swe-agent/eval/eval3/eval/runs'
labels=json.load(open('/Users/carson/Projects/gemma-swe-agent/data/patch_labels.json'))
patch={(r['task'],r['cfg']):r['patch'] for r in labels}
out={}
for cfg in ['p_v4','p_v6','p_v7','p_v8']:
    tr={}
    for l in open(f'{R}/{cfg}/task_results.jsonl'):
        r=json.loads(l); tr[r['instance_id']]=r
    for t,r in tr.items():
        m=dict(secs=r['duration_seconds'],calls=r['tool_calls'],llm=r['total_llm_calls'],err=(r.get('error') or '')[:120])
        p=patch.get((t,cfg),'')
        files=re.findall(r'^diff --git a/(\S+)',p,re.M)
        src=[f for f in files if not (f.startswith('tests/') or f.startswith('test') or '/test_' in f or f.split('/')[-1].startswith(('test_','repro','reproduce','verify')) or f.endswith(('.md','.txt','.yml','.yaml','.toml','.cfg','.ini')))]
        m['patch_files']=files; m['src_files']=src
        m['touches_tests']=any(f.startswith('tests/') for f in files)
        m['scratch']=[f for f in files if f not in src and not f.startswith('tests/')]
        m['empty']=len(p)==0
        m['no_src']=len(src)==0
        ed=rej=nf=ok=pyt=rep=0; seen=set(); maxp=0
        fp=f'{R}/{cfg}/traces/trace_{t}.json'
        if os.path.exists(fp):
            d=json.load(open(fp))
            for s in d['steps']:
                for tc in s.get('tool_calls') or []:
                    fn=tc['function_name']; a=tc.get('arguments') or {}
                    key=(fn,json.dumps(a,sort_keys=True))
                    if key in seen: rep+=1
                    seen.add(key)
                    u=(tc.get('extra') or {}).get('usage') or {}
                    maxp=max(maxp,u.get('prompt_tokens') or 0)
                    if fn=='run_command' and 'pytest' in str(a.get('command','')): pyt+=1
                obs=json.dumps((s.get('observation') or {}).get('content',''))
                for tc in s.get('tool_calls') or []:
                    if tc['function_name']=='edit_file':
                        ed+=1
                        if 'mandatory input param' in obs: rej+=1
                        elif 'not found' in obs.lower(): nf+=1
                        elif '\\"status\\": \\"ok\\"' in obs or '"status": "ok"' in obs: ok+=1
        m.update(edit=ed,edit_rej=rej,edit_nf=nf,edit_ok=ok,pytest=pyt,repeats=rep,max_prompt=maxp)
        out.setdefault(t,{})[cfg[2:]]=m
json.dump(out,open('/Users/carson/Projects/gemma-swe-agent/research/catalog_build/mech.json','w'),indent=1)
inp={r['id']:r for r in json.load(open('/Users/carson/Projects/gemma-swe-agent/research/tasks/_inputs.json'))}
uns=[t for t in sorted(inp) if not inp[t]['kaggle_env_pass']['v4']]
print(len(uns))
print(f"{'task':14} cfg  secs calls edit rej nf ok pyt rep maxp  empty nosrc tests scratch err")
for t in uns:
    for c in ['v4','v6','v7','v8']:
        m=out[t][c]
        print(f"{t:14} {c} {m['secs']:5.0f} {m['calls']:4} {m['edit']:4} {m['edit_rej']:3} {m['edit_nf']:2} {m['edit_ok']:2} {m['pytest']:3} {m['repeats']:3} {m['max_prompt']:5} {int(m['empty'])} {int(m['no_src'])} {int(m['touches_tests'])} {len(m['scratch'])} {m['err'][:50]}")
