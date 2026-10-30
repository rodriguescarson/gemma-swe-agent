import json, glob, os, collections
R='<repo>'
S='<scratch>/assume/runtime'
VALID=[l.strip() for l in open(f'{R}/data/kaggle_valid_ids.txt') if l.strip()]
def rows(run):
    p={'v12':f'{R}/eval/kaggle/g4-l4-v12-p312/results.jsonl','garble':f'{R}/eval/kaggle/g4-l4-v12b-garble-p312/results.jsonl'}[run]
    out={}
    for l in open(p):
        if l.strip():
            r=json.loads(l); out[r['id']]=r
    return out
def trace(run,i):
    p=f'{S}/{run}/traces/trace_{i}.json'
    return json.load(open(p)) if os.path.exists(p) else None
