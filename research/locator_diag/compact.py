import sys
for t in sys.argv[1:]:
    s=open(t).read()
    out=[]; cnt=0
    for ln in s.split("\n"):
        if ln.startswith("    ") and not ln.startswith("    OUT:"):
            cnt+=1
            if cnt>5: continue
        else:
            cnt=0
        if ln.startswith("SCORES:"):
            continue
        out.append(ln[:240])
    print("\n".join(out)); print()
