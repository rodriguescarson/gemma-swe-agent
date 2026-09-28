import json, sys
from render import render
L = json.load(open(sys.argv[1]))
by = {}
for i, e in enumerate(L):
    by.setdefault(e["agent"], []).append(i)
for ag, ids in by.items():
    for a, b in zip(ids, ids[1:]):
        ra, rb = render(L[a]["body"]), render(L[b]["body"])
        if rb.startswith(ra):
            nxt = rb[len(ra):]
            print(f"{ag} {a}->{b}: PREFIX ok; continuation starts {nxt[:90]!r}")
        else:
            k = next(i for i, (x, y) in enumerate(zip(ra, rb)) if x != y) if any(x != y for x, y in zip(ra, rb)) else min(len(ra), len(rb))
            print(f"{ag} {a}->{b}: DIVERGE at char {k}/{len(ra)}: prev {ra[k-40:k+60]!r}\n      next {rb[k-40:k+80]!r}")
    print(f"{ag} first-call tail: {render(L[ids[0]]['body'])[-80:]!r}")
