import csv, sys, collections, math
f=sys.argv[1]
rows=list(csv.DictReader(open(f,encoding='utf-8-sig')))
print(len(rows),'teams')
sc=[float(r['Score']) for r in rows]
c=collections.Counter(sc)
# map to k via floor(100k/58)/100
def k_of(s):
    ks=[k for k in range(0,59) if math.floor(100*k/58)/100==round(s,2)]
    return ks
print('score -> k candidates, n teams, cumulative')
cum=0
for s in sorted(c,reverse=True):
    cum+=c[s]
    print(f'{s:.2f} k={k_of(s)} n={c[s]} cum={cum}')
