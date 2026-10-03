import json, os, re, sys, io, contextlib
SP = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
import prep; prep.helpers(SP); prep.workspaces(SP)
sys.path.insert(0, SP + "/scripts")
os.environ["SWE_DIR"] = SP + "/swe_state"
import _swe_index as I
import locate as L
with contextlib.redirect_stdout(io.StringIO()):
    sys.path.insert(0, SP)
    from analyze import cls, case_p1, case_golden_L
gold = {c["eval_case_id"].split("__")[1]: c["golden"] for c in json.load(open("/Users/carson/Projects/gemma-swe-agent/eval/golden/datasets/L_dev.json"))["eval_cases"]}
issues = {}
for l in open("/Users/carson/Projects/gemma-swe-agent/data/tasks.jsonl"):
    r = json.loads(l)
    if r["instance_id"] in gold:
        issues[r["instance_id"]] = r["problem_statement"]
first_q = {}
for c in case_golden_L() + case_p1():
    for u in c["uses"]:
        if cls(u["cmd"], u["name"]) == "locate":
            m = re.search(r'locate\.py\s+"([^"]*)"', u["cmd"]) or re.search(r"locate\.py\s+'([^']*)'", u["cmd"])
            if m:
                first_q[(c["src"], c["task"])] = m.group(1)
            break
EXTRA_DOC = frozenset(("scripts", "tools"))

def rank_v(idx, q, compound=False, scripts_down=False):
    qt, qids, bigrams = L.query_terms(q)
    if not qt:
        return []
    qc = set(qt)
    # compounds: adjacent word pairs of the title line and of the whole query (lower), joined with _ and concatenated
    comps = set()
    for line in [l for l in q.splitlines() if l.strip()][:1] + [q]:
        ws = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9]+", line) if w.lower() not in L.STOP]
        for a, b in zip(ws, ws[1:]):
            comps.add(a + "_" + b)
    by = {}
    for s, path, sym in idx.bm25(qt):
        name = sym[0].rsplit(".", 1)[-1]
        if name in qids:
            s *= 2.5
        stem = os.path.splitext(os.path.basename(path))[0].lstrip("_").lower()
        s *= 1.8 if (stem in qc or stem.replace("_", "") in qc) else 1.0
        s *= 0.35 if L.is_test_path(path) else 1.0
        dirs = set(path.split("/")[:-1])
        s *= 0.6 if (L.DOC_DIRS.intersection(dirs) or (scripts_down and EXTRA_DOC.intersection(dirs))) else 1.0
        if bigrams and sym[1] != "module":
            sp = I.split_word(name)
            if bigrams.intersection(zip(sp, sp[1:])):
                s *= 1.5
        if compound and sym[1] != "module":
            nl = name.lower()
            if any(cmp in nl or cmp.replace("_", "") == nl.replace("_", "") for cmp in comps):
                s *= 2.5
        if s > 0:
            by.setdefault(path, []).append((s, sym))
    out = []
    for path, lst in by.items():
        lst.sort(key=lambda x: (-x[0], x[1][2], x[1][0]))
        fs = lst[0][0] + 0.3 * (lst[1][0] if len(lst) > 1 else 0)
        out.append((fs, path, lst))
    out.sort(key=lambda x: (-x[0], x[1]))
    return out

def gold_rank(ranked, g):
    files = [p for _, p, _ in ranked]
    rs = [files.index(f) + 1 for f in g["gold_files"] if f in files]
    return min(rs) if rs else 99

def fn_rank(ranked, g):
    """rank of the first gold function among all shown symbols (3 per file, 6 files) else 99"""
    names = {x["name"] for x in g.get("gold_functions", [])}
    k = 0
    for fs, p, lst in ranked[:6]:
        shown = [sym for _s, sym in lst if sym[1] != "module"][:3]
        for sym in shown:
            k += 1
            if p in g["gold_files"] and sym[0].rsplit(".", 1)[-1] in names:
                return k
    return 99

rows = []
WS = SP + "/ws"
for tid in sorted(os.listdir(WS)):
    ws = os.path.join(WS, tid)
    g = gold[tid]
    idx = I.build(ws, use_cache=False)
    iss = issues[tid]
    title = iss.strip().splitlines()[0]
    qs = {"title": title, "issue": iss}
    for src in ("L", "P"):
        if (src, tid) in first_q:
            qs["model_" + src] = first_q[(src, tid)]
    for qn, q in qs.items():
        cq = L.clean_query(q)
        r = {}
        for vn, kw in (("base", {}), ("compound", {"compound": True}), ("scripts", {"scripts_down": True}), ("both", {"compound": True, "scripts_down": True})):
            rk = rank_v(idx, cq, **kw)
            r[vn] = (gold_rank(rk, g), fn_rank(rk, g))
        # sanity: base equals locate.rank
        br = L.rank(idx, cq)
        assert gold_rank(br, g) == r["base"][0], (tid, qn)
        rows.append(dict(task=tid, q=qn, text=q[:80], **{k: v for k, v in r.items()}))
json.dump(rows, open(SP + "/rankexp.json", "w"), indent=1)
import collections
for qn in ("title", "issue", "model_L", "model_P"):
    R = [r for r in rows if r["q"] == qn]
    if not R:
        continue
    line = [qn, "n=%d" % len(R)]
    for vn in ("base", "compound", "scripts", "both"):
        top1 = sum(r[vn][0] == 1 for r in R); top3 = sum(r[vn][0] <= 3 for r in R); miss = sum(r[vn][0] > 8 for r in R)
        f3 = sum(r[vn][1] <= 3 for r in R)
        line.append("%s: file@1 %d, file@3 %d, not@8 %d, goldfn in first 3 syms %d" % (vn, top1, top3, miss, f3))
    print(" | ".join(line))
for r in rows:
    if r["base"] != r["both"]:
        print("CHANGED", r["task"], r["q"], r["text"][:60].replace("\n", " "), r["base"], "->", r["compound"], r["scripts"], r["both"])
