import json, re, sys, os, collections
sys.path.insert(0, "/Users/carson/Projects/gemma-swe-agent/eval/golden")
import golden_metrics as GM
SP = os.path.dirname(os.path.abspath(__file__))
FOOT = re.compile(r"\[t=(\d+)s\]")
gold = {}
for c in json.load(open("/Users/carson/Projects/gemma-swe-agent/eval/golden/datasets/L_dev.json"))["eval_cases"]:
    gold[c["eval_case_id"].split("__")[1]] = c["golden"]
split = json.load(open("/Users/carson/Projects/gemma-swe-agent/eval/golden/split.json"))["tasks"]

def cls(cmd, name):
    if name != "run_command":
        return name  # read_file etc
    if not cmd:
        return "malformed"
    m = re.search(r"/tmp/swe/(\w+)\.py", cmd)
    if m and cmd.strip().startswith("python3 /tmp/swe/"):
        h = m.group(1)
        if h == "verify" and "--repro-only" in cmd:
            return "repro"
        return h
    return "bare_shell"

def case_golden_L():
    RUN = "/Users/carson/Projects/gemma-swe-agent/eval/golden/runs/L_dev_v101"
    l4 = json.load(open(SP + "/l4_L_dev_v101.json"))
    out = []
    for case in json.load(open(RUN + "/traces/L_dev.json"))["eval_cases"]:
        inst = GM.make_instance(case); c = GM._ctx(inst)
        if c["status"] != "ok":
            continue
        uses = []
        for u in GM._uses(GM._stage(c)):
            o = GM._stdout(u["resp"]) if u["resp"] is not None else ""
            uses.append(dict(name=u["name"], cmd=u["cmd"] or (json.dumps(u["args"]) if u["args"] else ""), out=o if isinstance(o, str) else json.dumps(o)))
        tid = c["g"]["task"]
        capped = bool(GM._score("x_capped", inst)["score"])
        out.append(dict(src="L", task=tid, uses=uses, reply=GM._reply(c), capped=capped,
                        l4=l4[c["inst"]["eval_case_id"]]["l4_total"], repro_valid=c["g"]["exec_checks"].get("repro_fails_orig") and c["g"]["exec_checks"].get("repro_passes_gold")))
    return out

def case_p1():
    P = "/Users/carson/Projects/gemma-swe-agent/eval/pair1/eval/runs/p1_v10"
    res = {json.loads(l)["instance_id"]: json.loads(l) for l in open(P + "/task_results.jsonl")}
    out = []
    for tid in sorted(gold):
        f = f"{P}/traces/trace_{tid}.json"
        if not os.path.exists(f):
            continue
        steps = json.load(open(f))["steps"]
        loc, started = [], False
        for s in steps:
            tcs = s.get("tool_calls") or []
            a = tcs[0].get("extra", {}).get("author") if tcs else (s.get("extra") or {}).get("author")
            if a == "locator":
                started = True; loc.append(s)
            elif started and a not in (None, "locator"):
                break
        uses, reply = [], ""
        for s in loc:
            for tc in (s.get("tool_calls") or []):
                obs = s.get("observation", {}); content = obs.get("content") if isinstance(obs, dict) else ""
                try:
                    cj = json.loads(content); o = cj.get("stdout") or cj.get("result") or content
                except Exception:
                    o = content or ""
                args = tc.get("arguments", {}) or {}
                cmd = args.get("command") if isinstance(args.get("command"), str) else (json.dumps(args) if args else "")
                uses.append(dict(name=tc["function_name"], cmd=cmd, out=o if isinstance(o, str) else json.dumps(o),
                                 out_tok=tc.get("extra", {}).get("usage", {}).get("completion_tokens")))
            if not s.get("tool_calls") and s.get("message") and s.get("source") == "agent":
                reply = s["message"]
        ts = [int(x) for u in uses for x in FOOT.findall(u["out"])]
        out.append(dict(src="P", task=tid, uses=uses, reply=reply, capped=False, l4=ts[-1] if ts else None,
                        resolved=res.get(tid, {}).get("resolved")))
    return out

def locate_rank(uses, gf):
    for u in uses:
        if cls(u["cmd"], u["name"]) == "locate":
            files = re.findall(r"^\s*(\d+)\. (\S+)", u["out"], re.M)
            ranks = {}
            for r, p in files:
                if p in gf and p not in ranks:
                    ranks[p] = int(r)
            return ranks, [p for _, p in files[:8]]
    return None, None

def reply_kind(reply, capped):
    r = reply.strip()
    if capped and r in ("done", ""):
        return "capped_no_plan"
    if not r:
        return "empty"
    if r.startswith("<|tool_call>") or "<|tool_call>" in r[:200]:
        return "text_tool_call"
    if r.startswith("FILES:"):
        return "plan"
    if re.search(r"(?m)^\s*`?FILES:", r):
        return "prose_then_plan"
    return "prose_no_plan"

rows = []
for c in case_golden_L() + case_p1():
    g = gold[c["task"]]
    gf = g.get("gold_files", [])
    fn = [x["name"] for x in g.get("gold_functions", []) if x.get("name") and x["name"].lower() not in GM.VACUOUS_FUNCTIONS]
    reply = c["reply"]
    named = [f for f in gf if GM._path_named(reply, f)]
    fnamed = [n for n in fn if re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", reply)]
    kinds = collections.Counter(cls(u["cmd"], u["name"]) for u in c["uses"])
    cmds = [u["cmd"] for u in c["uses"]]
    dup = sum(1 for i, x in enumerate(cmds) if x and x in cmds[:i])
    seen = {f: any(f in (u["out"] + u["cmd"]) for u in c["uses"]) for f in gf}
    viewed = {f: any(cls(u["cmd"], u["name"]) in ("view", "read_file") and f in u["cmd"] for u in c["uses"]) for f in gf}
    ranks, top = locate_rank(c["uses"], gf)
    # first stop-line index
    stop_idx = None
    for i, u in enumerate(c["uses"]):
        if re.search(r"^(LOCATOR:|EDIT NOW:|CONTEXT:)", u["out"], re.M):
            stop_idx = i; break
    after_stop = (len(c["uses"]) - stop_idx - 1) if stop_idx is not None else 0
    same3 = sum(1 for u in c["uses"] if "same command, same output 3 times" in u["out"])
    passes_notes = sum(1 for u in c["uses"] if "passes on original - it misses the bug" in u["out"])
    runaway = sum(1 for u in c["uses"] if (u.get("out_tok") or 0) >= 730)
    rows.append(dict(src=c["src"], task=c["task"], ngold=len(gf), named=len(named), missing=[f for f in gf if f not in named],
                     nfn=len(fn), fnamed=len(fnamed), fmissing=[n for n in fn if n not in fnamed], calls=len(c["uses"]),
                     kinds=dict(kinds), dup=dup, seen=seen, viewed=viewed, loc_rank=ranks, loc_top=top, after_stop=after_stop,
                     same3=same3, passes_notes=passes_notes, reply_kind=reply_kind(reply, c["capped"]), capped=c["capped"],
                     l4=c["l4"], resolved=c.get("resolved"), issue_len=None, reply_words=len(reply.split())))
json.dump(rows, open(SP + "/rows_all.json", "w"), indent=1, default=str)
for r in rows:
    print(r["src"], r["task"], f"{r['named']}/{r['ngold']}", f"f{r['fnamed']}/{r['nfn']}", "calls", r["calls"], "l4", r["l4"], r["reply_kind"],
          "rank", r["loc_rank"], "seen", sum(r["seen"].values()), "viewed", sum(r["viewed"].values()), "dup", r["dup"], "afterstop", r["after_stop"],
          "k", r["kinds"])
