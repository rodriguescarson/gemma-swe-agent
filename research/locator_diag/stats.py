"""Aggregates quoted in docs/v10/v10_2_locator_diag.md (run after analyze.py, attrib.py, postfind.py)."""
import json, os, re, sys, io, contextlib, collections, statistics, glob
SP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SP)
with contextlib.redirect_stdout(io.StringIO()):
    from analyze import cls, case_p1, case_golden_L
rows = json.load(open(SP + "/rows_all.json"))
L = [r for r in rows if r["src"] == "L"]; P = [r for r in rows if r["src"] == "P"]
print("== calls, stop lines, repeats, locate rank, endings")
for src, R in (("L", L), ("P", P)):
    c = [r["calls"] for r in R]
    rk = collections.Counter()
    for r in R:
        lr = r["loc_rank"]
        rk["no locate" if lr is None else ("not in top 8" if not lr else ("1" if min(lr.values()) == 1 else ("2-3" if min(lr.values()) <= 3 else "4-8")))] += 1
    print(src, "n", len(R), "calls mean %.1f median %s, >12: %d, >20: %d" % (statistics.mean(c), statistics.median(c), sum(x > 12 for x in c), sum(x > 20 for x in c)),
          "| after first stop line %d of %d calls, cases >=3: %d" % (sum(r["after_stop"] for r in R), sum(c), sum(r["after_stop"] >= 3 for r in R)),
          "| identical repeats %d, 'same output 3 times' notes %d" % (sum(r["dup"] for r in R), sum(r["same3"] for r in R)),
          "| gold rank in first locate:", dict(rk), "| endings:", dict(collections.Counter(r["reply_kind"] for r in R)))
    t = sorted(r["l4"] for r in R if r["l4"] is not None)
    print("   L4 s mean %.1f median %s p90 %s >60: %d >90: %d" % (statistics.mean(t), statistics.median(t), t[int(0.9 * len(t))], sum(x > 60 for x in t), sum(x > 90 for x in t)))
ct = collections.Counter((r["named"] == r["ngold"], bool(r["resolved"])) for r in P)
print("P all gold files named x resolved:", dict(ct))
print("== reproduction attempts")
for src, cases in (("L", case_golden_L()), ("P", case_p1())):
    b = collections.Counter(); total = saved = lost = runs = runs_saved = 0
    for c in cases:
        seq = ["F" if re.search(r"^REPRO: (fails|hangs) on original|^REPRO: .*hangs", u["out"], re.M) else "P" for u in c["uses"] if cls(u["cmd"], u["name"]) == "repro"]
        nr = sum(1 for u in c["uses"] if cls(u["cmd"], u["name"]) in ("run", "bare_shell"))
        ff = next((i for i, s in enumerate(seq) if s == "F"), None)
        b["none" if not seq else ("never" if ff is None else str(min(ff + 1, 3)).replace("3", "3+"))] += 1
        keep = min(len(seq), 2) if ff is None else min(ff + 1, 2)
        total += len(seq); saved += len(seq) - keep; lost += int(ff is not None and ff >= 2)
        runs += nr; runs_saved += max(0, nr - 2)
    print(src, "first failing repro at attempt:", dict(b), "| attempts %d, removed by (stop at first fail, max 2) %d, cases losing a failing repro %d | run.py+bare %d, removed by max 2 %d" % (total, saved, lost, runs, runs_saved))
print("== helper misuse")
cnt = collections.Counter(); ex = collections.defaultdict(set)
for c in case_golden_L() + case_p1():
    for u in c["uses"]:
        k = cls(u["cmd"], u["name"]); cmd = u["cmd"]; o = u["out"]
        tags = []
        if k == "run":
            if re.search(r'run\.py[^"\']*["\'][^"\']*["\']\s*<<', cmd.split("\n", 1)[0]) and "(no output)" in o: tags.append("stdin heredoc dropped")
            if re.search(r"python3? -c", cmd) and "SyntaxError" in o: tags.append("python -c SyntaxError")
            if "unexpected EOF while looking for matching" in o: tags.append("unbalanced quotes")
            if re.search(r"\b(curl|wget|pip install|git log|git fetch|git show)\b", cmd): tags.append("network or git history")
        if k in ("locate", "grep") and re.search(r'(locate|grep)\.py\s+["\']#?\d{3,6}["\']', cmd): tags.append("issue-number search")
        if k == "grep" and "does not exist" in o: tags.append("grep --path that does not exist")
        for t in tags:
            cnt[t] += 1; ex[t].add("%s:%s" % (c["src"], c["task"]))
for t, n in cnt.most_common():
    print("  %s: %d calls in %d cases %s" % (t, n, len(ex[t]), sorted(ex[t])))
print("== views")
for src, cases in (("L", case_golden_L()), ("P", case_p1())):
    views = trunc = paged = reread = 0
    for c in cases:
        seen = collections.defaultdict(list); prev_end = {}
        for u in c["uses"]:
            if cls(u["cmd"], u["name"]) != "view": continue
            views += 1
            m = re.search(r"^(\S+) lines (\d+)-(\d+) of (\d+)", u["out"], re.M)
            req = re.search(r"view\.py\s+(\S+)\s+(\d+)[\s-]+(\d+)", u["cmd"])
            if not m: continue
            path, a, b = m.group(1), int(m.group(2)), int(m.group(3))
            trunc += int(bool(req) and int(req.group(3)) > b)
            paged += int(path in prev_end and a == prev_end[path] + 1)
            reread += int(any(a >= x and b <= y for x, y in seen[path]))
            seen[path].append((a, b)); prev_end[path] = b
    print(src, "views %d, cut below the requested end %d, next-page continuations %d, re-reads of a shown range %d" % (views, trunc, paged, reread))
