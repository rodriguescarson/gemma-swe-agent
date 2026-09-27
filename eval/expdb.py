"""Experiment database + stage-level failure attribution.
Every (config, task) outcome goes into eval/experiments.sqlite; failures are labelled from traces:
  EMPTY_TIMEOUT      no patch, hit the time cap
  EMPTY_NO_EDIT      no patch, finished without editing
  LOCATE_MISS        patch exists but the agent never read or edited any gold file
  WRONG_FILE_EDIT    read a gold file but edited only other files
  GOLD_EDIT_FAILED   edited a gold file, tests still failed (wrong or incomplete fix)
Usage: python eval/expdb.py ingest <config_name> <run_dir> ; python eval/expdb.py report [task_list_file]"""
import glob, json, os, re, sqlite3, sys, collections
DB = os.path.join(os.path.dirname(__file__), "experiments.sqlite")
T = {json.loads(l)["instance_id"]: json.loads(l) for l in open(os.path.join(os.path.dirname(__file__), "..", "data/tasks.jsonl"))}
is_test = lambda p: bool(re.search(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|conftest\.py$", p))
def gold(iid): return {g for g in re.findall(r"^\+\+\+ b/(\S+)", T[iid]["patch"], re.M) if not is_test(g)}
def norm(p): return re.sub(r"^(/workspace/|\./)", "", (p or "").strip())
def touched(trace_path):
    reads, edits, stages = set(), set(), collections.Counter()
    if not os.path.exists(trace_path): return reads, edits, stages
    for s in json.load(open(trace_path)).get("steps", []):
        for tc in (s.get("tool_calls") or []):
            a = tc.get("arguments") or {}; fn = tc.get("function_name"); stages[(tc.get("extra") or {}).get("author", "?")] += 1
            if fn == "read_file": reads.add(norm(a.get("filepath")))
            elif fn in ("edit_file", "write_file"): edits.add(norm(a.get("filepath")))
            elif fn == "run_command":
                cmd = a.get("command", "")
                reads |= {norm(m) for m in re.findall(r"[\w./-]+\.py", cmd)}
    return reads, edits, stages
def label(r, g, reads, edits):
    if r["resolved"]: return "SOLVED"
    if not r.get("agent_patch_size"):
        return "EMPTY_TIMEOUT" if "timeout" in (r.get("error") or "").lower() else "EMPTY_NO_EDIT"
    strip = lambda s: {re.sub(r"^\.cand_[a-z]/", "", x) for x in s}
    reads, edits = strip(reads), strip(edits)
    if edits & g: return "GOLD_EDIT_FAILED"
    if (reads | edits) & g: return "WRONG_FILE_EDIT"
    return "LOCATE_MISS"
con = sqlite3.connect(DB)
con.execute("""create table if not exists runs(config text, task text, repo text, resolved int, empty int, timeout int, secs real, calls int,
  label text, read_gold int, edited_gold int, stage_calls text, primary key(config, task))""")
if sys.argv[1] == "ingest":
    cfg, d = sys.argv[2], sys.argv[3]; n = 0
    for f in glob.glob(os.path.join(d, "task_results.jsonl")):
        for l in open(f):
            r = json.loads(l); iid = r["instance_id"]; g = gold(iid)
            reads, edits, stages = touched(os.path.join(d, "traces", f"trace_{iid}.json"))
            lab = label(r, g, reads, edits)
            con.execute("insert or replace into runs values(?,?,?,?,?,?,?,?,?,?,?,?)", (cfg, iid, iid.split("_")[0], int(bool(r["resolved"])),
                int(not r.get("agent_patch_size")), int("timeout" in (r.get("error") or "").lower()), r.get("duration_seconds") or 0,
                r.get("tool_calls") or 0, lab, int(bool((reads | edits) & g)), int(bool(edits & g)), json.dumps(dict(stages))))
            n += 1
    con.commit(); print("ingested", n, "rows for", cfg)
elif sys.argv[1] == "report":
    ids = set(l.strip() for l in open(sys.argv[2])) if len(sys.argv) > 2 else None
    for cfg, in con.execute("select distinct config from runs order by config"):
        rows = [r for r in con.execute("select task, label from runs where config=?", (cfg,)) if ids is None or r[0] in ids]
        c = collections.Counter(l for _, l in rows)
        print(f"{cfg:14} n={len(rows):3} " + "  ".join(f"{k}={v}" for k, v in c.most_common()))
