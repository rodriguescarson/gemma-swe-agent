import json, re, glob, os, collections, hashlib
BASE='<repo>'
def text(u): return u if isinstance(u,str) else ''.join(x.get('text','') if isinstance(x,dict) else str(x) for x in u)
RECALL=re.compile(r"\b(I recall|I remember|as I know|in my knowledge|known (issue|behavio|pattern)|typically|usually|standard (way|practice|implementation)|commonly|in (the )?(original|upstream|actual) (code|implementation)|in recent versions|(newer|later) versions? of)\b", re.I)
def stats(name, firsts):
    n=len(firsts); m=sum(1 for repo,t in firsts if repo.lower() in t.lower()); rc=sum(1 for repo,t in firsts if RECALL.search(t))
    print(f'{name:38s} runs {n:4d} | first reasoning names the library: {m} ({100*m/n:.0f}%) | uses recall/prior wording: {rc} ({100*rc/n:.0f}%)')
# P10: first response of each task (by first_user key)
cap=[]
tasks={}
for l in open('<repo>/data/heldout1k/tasks.jsonl'):
    r=json.loads(l); tasks[r['instance_id']]=r
firsts=[]; seen=set()
for l in open('p3/capture.jsonl'):
    d=json.loads(l); ms=d['body']['messages']
    if len(ms)!=2 or ms[0]['role']!='system': continue
    u=text(ms[1]['content'])
    if not u.startswith('You are evaluating'): continue
    k=hashlib.md5(u.encode()).hexdigest()
    if k in seen: continue
    seen.add(k)
    repo=u.split('repository ',1)[1].split('.\n',1)[0].split('/')[-1]
    reas=d['response']['choices'][0]['message'].get('reasoning') or d['response']['choices'][0]['message'].get('reasoning_content') or ''
    firsts.append((repo.replace('-','_'), reas.replace('-','_')))
stats('P10 non-public (first reasoning)', firsts)
pf=[]
for f in glob.glob(f'{BASE}/eval/kaggle/g4-l4-v12-p312/results/traces/trace_*.json'):
    t=json.load(open(f)); u=t['steps'][1]['message']; repo=u.split('repository ',1)[1].split('.\n',1)[0].split('/')[-1]
    reas=''
    for s in t['steps'][2:]:
        if s.get('source')=='agent': reas=s.get('message') or ''; break
    pf.append((repo, reas))
stats('PUBLIC 74 Kaggle v12 (first agent msg)', pf)
