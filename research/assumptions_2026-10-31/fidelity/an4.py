import json, glob, os, re, collections, sys
valid=set(l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip())
def cmds(path):
    t=json.load(open(path)); out=[]
    for s in t['steps']:
        for tc in (s.get('tool_calls') or []):
            if tc.get('function_name')=='run_command':
                a=tc.get('arguments') or {}
                out.append(a.get('command') or '')
            elif tc.get('function_name') in ('write_file',):
                a=tc.get('arguments') or {}
                out.append('WRITE '+str(a.get('filepath') or a.get('path') or ''))
    return out
def res_rows(p):
    return {json.loads(l)['id']:json.loads(l) for l in open(p)}
cfgs=(('v12','tr_v12','<repo>/eval/kaggle/g4-l4-v12-p312/results.jsonl'),('garble','tr_garble','<repo>/eval/kaggle/g4-l4-v12b-garble-p312/results.jsonl'))
pat={'pytest':re.compile(r'pytest'),'unittest':re.compile(r'unittest'),'tmp_ref':re.compile(r'(?<![\w.-])/tmp\b'),
     'tmp_script_run':re.compile(r'python3?\s+(-u\s+)?/tmp/\S+\.py'),'pip':re.compile(r'\bpip3?\s+install'),
     'python_dash':re.compile(r'python3?\s+-\s*<<'), 'python_c':re.compile(r'python3?\s+-c\b'),
     'cat_to_tmp':re.compile(r'(>|tee)\s*/tmp/\S+')}
for name,td,rp in cfgs:
    rows=res_rows(rp)
    ids=[i for i in rows if i in valid and os.path.exists(f'{td}/traces/trace_{i}.json')]
    cnt=collections.Counter(); solved=collections.Counter(); n_ids=collections.defaultdict(set)
    for i in ids:
        cs=cmds(f'{td}/traces/trace_{i}.json')
        for k,p in pat.items():
            if any(p.search(c) for c in cs):
                n_ids[k].add(i)
    print(name,'runs',len(ids),'solved(raw)',sum(rows[i]['resolved'] for i in ids))
    for k in pat:
        s=n_ids[k]
        print(f'   {k:15s} runs {len(s):3d}  solved among them {sum(rows[i]["resolved"] for i in s)}')
    json.dump({k:sorted(v) for k,v in n_ids.items()},open(f'exposure_{name}.json','w'))
