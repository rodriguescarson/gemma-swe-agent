import sys; sys.path.insert(0,'<scratch>/assume/runtime/scripts')
import extract, load, json, os
from extract import *
B='<repo>/eval/a6000/results'
def box_rows(run):
    out={}
    for l in open(f'{B}/{run}/results.jsonl'):
        if l.strip():
            r=json.loads(l); out[r['id']]=r
    return out
def box_trace(run,i):
    p=f'{B}/{run}/results/traces/trace_{i}.json'
    return json.load(open(p)) if os.path.exists(p) else None
def analyse_box(run,i,rr):
    # reuse analyse() by monkeypatching trace()
    old=extract.trace
    extract.trace=lambda r,i_: box_trace(run,i_)
    try:
        a=extract.analyse(run,i,rr)
    finally:
        extract.trace=old
    a['end']=extract.end_kind(a); a['base']=i in extract.BASEPASS
    return a
def load_box(run):
    rr=box_rows(run)
    ids=[i for i in VALID if i in rr]
    return [analyse_box(run,i,rr) for i in ids]
