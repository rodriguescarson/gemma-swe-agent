import json, re, os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    from analyze import cls, case_p1, case_golden_L
gold = {c["eval_case_id"].split("__")[1]: c["golden"] for c in json.load(open("/Users/carson/Projects/gemma-swe-agent/eval/golden/datasets/L_dev.json"))["eval_cases"]}
res = collections.defaultdict(collections.Counter)
detail = []
for c in case_golden_L() + case_p1():
    seq = []
    for u in c["uses"]:
        if cls(u["cmd"], u["name"]) == "repro":
            o = u["out"]
            if re.search(r"^REPRO: fails on original", o, re.M) or re.search(r"^REPRO: .*hangs", o, re.M):
                seq.append("F")
            elif "passes on original" in o:
                seq.append("P")
            else:
                seq.append("X")
    first_f = next((i + 1 for i, s in enumerate(seq) if s == "F"), None)
    key = "none" if not seq else ("never" if first_f is None else ("1" if first_f == 1 else ("2" if first_f == 2 else "3+")))
    res[c["src"]][key] += 1
    extra_after_f = (len(seq) - first_f) if first_f else 0
    detail.append((c["src"], c["task"], "".join(seq), key, extra_after_f, c.get("repro_valid")))
for src in ("L", "P"):
    print(src, dict(res[src]))
    D = [d for d in detail if d[0] == src]
    print("  attempts total", sum(len(d[2]) for d in D), " attempts after the first F", sum(d[4] for d in D),
          " attempts in never-F cases", sum(len(d[2]) for d in D if d[3] == "never"))
print([d for d in detail if d[3] == "3+"])
print("L repro_valid by first-F bucket:", collections.Counter((d[3], bool(d[5])) for d in detail if d[0] == "L"))
