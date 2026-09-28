import glob, json, sys, collections
sys.argv = [sys.argv[0]] + sys.argv[1:]
exec(open(__file__.rsplit("/", 1)[0] + "/recon.py").read().split("res = {")[0])
ct_by = collections.Counter(); dl_by = collections.Counter()
for d in sys.argv[1:]:
    for f in sorted(glob.glob(d + "/trace_*.json")):
        st = steps_of(json.load(open(f)))
        for i, s in enumerate(st):
            if s["kind"] != "call" or s["obs"] is None or len(s["calls"]) > 1:
                continue
            prev = st[i - 1] if i else None
            first = not (prev and prev["kind"] == "call" and prev["author"] == s["author"])
            if s["ct"] is not None:
                diff = s["ct"] - (ntok(call_text(s["calls"])) + 1)
                ct_by[(("first" if first else "cont"), diff if diff in (0, 4) else "other")] += 1
            if i + 1 < len(st):
                n = st[i + 1]
                if n["kind"] == "call" and n["author"] == s["author"] and n["pt"] and s["pt"]:
                    mv = model_visible(s["obs_tool"] or s["calls"][0][0], s["obs"])
                    got = ntok(increment(([("_", {})], ["_"]), (s["calls"], [mv])))
                    dl = n["pt"] - s["pt"] - got
                    dl_by[(("first" if first else "cont"), dl if dl in (0, -4) else ("<-1000" if dl < -1000 else "other"))] += 1
print("completion_tokens - (canonical+1):", sorted(ct_by.items(), key=str))
print("delta_prompt - rendered increment:", sorted(dl_by.items(), key=str))
