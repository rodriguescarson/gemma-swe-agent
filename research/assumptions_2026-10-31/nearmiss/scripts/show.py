import json,sys,re
N='<scratch>/assume/nearmiss'
tasks={json.loads(l)['instance_id']:json.loads(l) for l in open('<repo>/data/tasks.jsonl')}
ents=json.load(open(N+'/patches_main.json'))
def split(p):
    parts=re.split(r'(?m)^(?=diff --git )',p)
    return [x for x in parts if x.strip()]
def srcdiff(p,maxl=60):
    out=[]
    for s in split(p):
        m=re.match(r'diff --git a/(.*?) b/',s) 
        f=m.group(1) if m else ''
        if re.search(r'(^|/)(tests?)/|^docs/|\.md$',f) or ('new file mode' in s and '/' not in f): 
            out.append(f'   [skipped {f}]'); continue
        out.append(s)
    t='\n'.join(out).split('\n')
    return '\n'.join(t[:maxl])
def show(task,cfg=None,maxl=60,tests=False):
    print('='*30,task,cfg)
    for e in ents:
        if e['task']==task and (cfg is None or cfg in e['cfg'].split('+')):
            print('--- AGENT PATCH',e['cfg']); print(srcdiff(e['patch'],maxl))
            break
    print('--- GOLD'); print(srcdiff(tasks[task]['patch'],maxl))
    if tests:
        tp=tasks[task]['test_patch']; print('--- TEST PATCH'); print('\n'.join(tp.split('\n')[:80]))
if __name__=='__main__':
    show(sys.argv[1], sys.argv[2] if len(sys.argv)>2 and sys.argv[2]!='-' else None, int(sys.argv[3]) if len(sys.argv)>3 else 60, len(sys.argv)>4)
