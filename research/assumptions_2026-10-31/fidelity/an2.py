import json, statistics as st, collections
valid=set(l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip())
for name,p in (('v12','<repo>/eval/kaggle/g4-l4-v12-p312/results.jsonl'),('garble','<repo>/eval/kaggle/g4-l4-v12b-garble-p312/results.jsonl')):
    rows=[json.loads(l) for l in open(p)]
    r=[x for x in rows if x['id'] in valid]
    errs=collections.Counter((x.get('err') or 'none')[:45] for x in r)
    print(name,len(rows),'valid',len(r),'solved',sum(x['resolved'] for x in r),'mean secs',round(st.mean(x['secs'] for x in r),1),'sum h',round(sum(x['secs'] for x in r)/3600,2))
    print('  errs',dict(errs))
    print('  calls mean',round(st.mean((x.get('calls') or 0) for x in r),1),'empty patch',sum(not x.get('patch') for x in r))
    # phase2 timeouts: test_tail containing 'timeout' or exit 124 etc.
    to=[x['id'] for x in r if 'timed out' in (x.get('test_tail') or '').lower() or 'timeout' in (x.get('test_tail') or '').lower()]
    ex=collections.Counter(x.get('exit') for x in r)
    print('  test exit codes',dict(ex),'timeout-ish tails',len(to),to[:10])
