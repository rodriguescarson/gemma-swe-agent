"""Parse -rA pytest logs from the grader into per-node outcomes."""
import re, json, os, glob
N='<scratch>/assume/nearmiss'
ST=('PASSED','FAILED','ERROR','XFAIL','XPASS','SKIPPED')
LINE=re.compile(r'^(PASSED|FAILED|ERROR|XFAIL|XPASS)\s+(.*)$')

def parse_log(text):
    """-> dict(nodes={id:status}, collection_errors=[file], interrupted=bool, summary=str, syntax=bool, err_kinds=set)"""
    nodes={}; coll=[]
    # only the section after "short test summary info" carries the -rA lines; but -rA PASSED lines come before it
    for line in text.split('\n'):
        m=LINE.match(line)
        if not m: continue
        st,rest=m.group(1),m.group(2).strip()
        if st in('FAILED','ERROR'):
            nid=rest.split(' - ',1)[0].strip()
        else:
            nid=rest.split(' - ',1)[0].strip() if st!='PASSED' else rest
        if st=='ERROR' and '::' not in nid:
            coll.append(nid)
        nodes[nid]=st if nid not in nodes or st in('FAILED','ERROR') else nodes[nid]
    interrupted='Interrupted:' in text and 'error' in text.split('Interrupted:')[1][:80]
    # error kinds in collection
    kinds=set()
    for k in ('SyntaxError','IndentationError','ModuleNotFoundError','ImportError','NameError','AttributeError','TypeError','TabError'):
        if re.search(r'^E\s+.*'+k,text,re.M): kinds.add(k)
    summ=''
    for line in reversed(text.split('\n')):
        if re.search(r'\b(passed|failed|error|errors)\b.*\bin [\d.]+s',line) or re.match(r'^=+ .* in [\d.]+s',line):
            summ=line.strip('= ').strip(); break
    return dict(nodes=nodes,collection_errors=coll,interrupted=interrupted,summary=summ,kinds=sorted(kinds))

def load_run(run, inputs):
    """returns {idx: (entry,row,parsed)}"""
    rows=[json.loads(l) for l in open(f'{N}/gr/runs/{run}/replay_results.jsonl')]
    ents=json.load(open(inputs))
    out={}
    for r in rows:
        i=r['idx']; lf=f"{N}/gr/runs/{run}/replay_logs/{i}_{r['task']}.log"
        txt=open(lf,encoding='utf-8',errors='replace').read() if os.path.exists(lf) else ''
        out[i]=(ents[i],r,parse_log(txt))
    return out
