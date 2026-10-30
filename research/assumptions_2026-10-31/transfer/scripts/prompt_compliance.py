import json, re, glob, os, collections, sys
sys.path.insert(0,'scripts')
from failmodes import runs_from_p10, runs_from_traces
BASE='<repo>'
def first_cmd_shape(cmd):
    c=(cmd or '').strip()
    if re.match(r'git\s+grep', c): return 'git grep (template)'
    if re.match(r'(grep|egrep|rg)\b', c): return 'grep/rg -r'
    if re.match(r'(ls|find|tree)\b', c): return 'ls/find'
    if re.match(r'(cat|head|sed|tail)\b', c): return 'cat/sed/head'
    if re.match(r'(python3?|cd )', c): return 'python/cd'
    return 'other'
def summarize(name, runs):
    n=len(runs); first=collections.Counter(); first_is_cmd=0; pyt=0; unitt=0; inline=0; edits_before_6=0; nocalls=0
    gitgrep_any=0; first_tool=collections.Counter()
    for tid,r in runs.items():
        cs=r['calls']
        if not cs: nocalls+=1; continue
        first_tool[cs[0]['name']]+=1
        rc=[c for c in cs if c['name']=='run_command']
        if cs[0]['name']=='run_command': first[first_cmd_shape((cs[0]['args'] or {}).get('command'))]+=1
        cmds=[(c['args'] or {}).get('command') or '' for c in rc]
        if any(re.search(r'pytest',x) for x in cmds): pyt+=1
        if any(re.search(r'unittest',x) for x in cmds): unitt+=1
        if any(re.search(r"<<\s*['\"]?EOF|python3? -c",x) for x in cmds): inline+=1
        if any(re.match(r'\s*git\s+grep',x) for x in cmds): gitgrep_any+=1
    print(f'--- {name}: runs {n}')
    print('   first tool call:', dict(first_tool.most_common(4)))
    print('   first run_command shape:', dict(first.most_common()))
    print(f'   runs that ever use git grep: {gitgrep_any} ({100*gitgrep_any/n:.0f}%) | ever run pytest: {pyt} ({100*pyt/n:.0f}%) | ever unittest: {unitt} | inline python repro: {inline} ({100*inline/n:.0f}%)')
p10=runs_from_p10(); summarize('P10 v12 non-public', p10)
K=f'{BASE}/eval/kaggle/g4-l4-v12-p312'
summarize('Kaggle L4 v12 public', runs_from_traces(f'{K}/results/traces', f'{K}/results.jsonl'))
