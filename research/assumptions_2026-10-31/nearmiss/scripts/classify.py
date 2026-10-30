import sys, json, collections, re
sys.path.insert(0,'<scratch>/assume/nearmiss/scripts')
import parse_logs as P
N=P.N
base=P.load_run('nm_empty',N+'/empty_in.json')
gold=P.load_run('nm_gold',N+'/gold_in.json')
main=P.load_run('nm_main',N+'/patches_main.json')
bt={e['task']:(r,p) for e,r,p in base.values()}
gt={e['task']:(r,p) for e,r,p in gold.values()}

def counts(summary):
    d={}
    for k in ('passed','failed','error','errors','skipped'):
        m=re.search(r'(\d+) '+k+r'\b',summary or '')
        if m: d[k.rstrip('s') if k=='errors' else k]=int(m.group(1))
    return d

# consistency: node counts vs summary
def check(name,runs):
    bad=[]
    for e,r,p in runs.values():
        c=counts(r['test_summary']); n=collections.Counter(p['nodes'].values())
        exp=c.get('passed',0)+c.get('failed',0)+c.get('error',0)
        got=n['PASSED']+n['FAILED']+n['ERROR']+n['XPASS']+n['XFAIL']
        if exp!=got: bad.append((e['task'],r['test_summary'],dict(n)))
    return bad
if __name__=='__main__':
    for nm,runs in [('base',base),('gold',gold),('main',main)]:
        b=check(nm,runs); print(nm,len(runs),'count mismatches',len(b))
        for x in b[:8]: print('  ',x)
