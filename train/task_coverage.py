"""Coverage tags for SWE tasks, read from patch / test_patch / problem statement (no execution).

    python train/task_coverage.py tasks.jsonl [more.jsonl ...] --out coverage.json [--min-share 0.05]

Dimensions (Carson 2026-10-05: edge cases, positive/negative routes, zero states, multi-states, behaviours):
  routes      negative_route (tests expect an exception/warning/error exit), positive_only (no failure expectation)
  edge        edge_none (None), zero_empty (0, "", [], {}, empty), boundary (-1, max/min, off-by-one, len-1, large ints)
  inputs      unicode, bytes_encoding, regex, parsing, numeric_float, path_fs, datetime
  state       stateful (object mutated across calls), multi_state (several distinct states/modes asserted), cache
  structure   multi_file, multi_function, new_api (adds a def/class/param), deletion_heavy, one_line_fix
  surface     async, cli, concurrency, typing, deprecation, config_env, logging_output
  statement   title_only, has_traceback, has_example (code block or >>>), long_statement
Each task gets a set of tags; the report gives counts, shares and the dimensions below --min-share ("gaps").
tests/test_task_coverage.py.
"""
import argparse, collections, json, re, sys

def _added(diff):
    return "\n".join(l[1:] for l in (diff or "").splitlines() if l.startswith("+") and not l.startswith("+++"))

def _removed(diff):
    return "\n".join(l[1:] for l in (diff or "").splitlines() if l.startswith("-") and not l.startswith("---"))

RX = {
    "negative_route": r"pytest\.raises|assertRaises|pytest\.warns|assertWarns|exit_code\s*!=\s*0|exit_code\s*==\s*[12]|\bwith raises\(",
    "edge_none": r"\(\s*None\s*[,)]|==\s*None|is None|=None\b",
    "zero_empty": r"\(\s*0\s*[,)]|==\s*0\b|\[\]|\{\}|\(\)|\"\"|''|\bempty\b",
    "boundary": r"\(-1\b|\b-1\)|sys\.maxsize|\bmaxsize\b|2\s*\*\*\s*\d{2}|\binf\b|float\(['\"]inf|len\(\w+\)\s*-\s*1|\bmin\(|\bmax\(",
    "unicode": r"[^\x00-\x7f]|\\u[0-9a-fA-F]{4}|unicode",
    "bytes_encoding": r"\bb['\"]|\.encode\(|\.decode\(|bytes\(",
    "regex": r"\bre\.(compile|match|search|sub|fullmatch)|regex",
    "parsing": r"\bpars(e|er|ing)\b|tokeni[sz]|\bloads?\(",
    "numeric_float": r"\d+\.\d+|approx\(|isclose|Decimal|Fraction",
    "path_fs": r"tmp_path|tmpdir|os\.path|pathlib|\.open\(|Path\(",
    "datetime": (r"datetime|timedelta|tzinfo|timezone|\bdt\b|arrow\.(Arrow|get|now|utcnow)|\.shift\(|\b(de)?humanize"
                 r"|DateTimeParser|\btz(offset|utc|local|file|gettz)\b|\butcnow\b|\bstrftime|\bstrptime|\bisoformat"),
    "stateful": r"\.(reset|clear|add|append|push|pop|update|set_\w+|close|open|start|stop)\(",
    "cache": r"cache|memoi[sz]",
    "async": r"\basync def\b|\bawait\b|asyncio|anyio|trio",
    "cli": r"CliRunner|runner\.invoke|argparse|sys\.argv|\bmain\(\[",
    "concurrency": r"thread|Thread|multiprocess|Lock\(|concurrent",
    "typing": r"\btyping\b|TypeVar|Generic\[|Protocol\b|overload|annotations",
    "deprecation": r"Deprecat",
    "config_env": r"environ|monkeypatch\.setenv|config",
    "logging_output": r"caplog|capsys|capfd|logging|stdout|stderr",
}

def tags(t):
    patch, tp, st = t.get("patch") or "", t.get("test_patch") or "", t.get("problem_statement") or ""
    ta, pa, pr = _added(tp), _added(patch), _removed(patch)
    out = set()
    for k in ("negative_route", "edge_none", "zero_empty", "boundary", "stateful", "async", "cli", "concurrency",
              "logging_output", "config_env", "path_fs", "datetime", "numeric_float", "bytes_encoding", "unicode"):
        if re.search(RX[k], ta):
            out.add(k)
    for k in ("regex", "parsing", "cache", "typing", "deprecation"):
        if re.search(RX[k], ta + "\n" + pa):
            out.add(k)
    if "negative_route" not in out:
        out.add("positive_only")
    if len(re.findall(r"^\s*assert\b", ta, re.M)) >= 3 and "stateful" in out:
        out.add("multi_state")
    files = set(re.findall(r"^\+\+\+ b/(\S+)", patch, re.M))
    if len(files) > 1:
        out.add("multi_file")
    hunks_funcs = set(re.findall(r"^@@[^@]*@@\s*(?:async\s+)?(?:def|class)\s+(\w+)", patch, re.M))
    new_defs = set(re.findall(r"^\s*(?:async\s+)?def\s+(\w+)|^\s*class\s+(\w+)", pa, re.M))
    if len(hunks_funcs | {a or b for a, b in new_defs}) > 1:
        out.add("multi_function")
    if new_defs or re.search(r"^\s*def \w+\([^)]*\w+\s*=", pa, re.M):
        out.add("new_api")
    n_add, n_rem = len(pa.splitlines()), len(pr.splitlines())
    if n_rem > 2 * max(1, n_add):
        out.add("deletion_heavy")
    if n_add + n_rem <= 2:
        out.add("one_line_fix")
    body = re.sub(r"(Fixes|Closes|Resolves)?\s*#\d+|https?://\S+", "", st).strip()
    if t.get("statement_title_only") or len(body) < 120:
        out.add("title_only")
    if "Traceback" in st:
        out.add("has_traceback")
    if "```" in st or ">>>" in st:
        out.add("has_example")
    if len(st) > 1500:
        out.add("long_statement")
    return out

ALL = sorted(set(RX) | {"positive_only", "multi_state", "multi_file", "multi_function", "new_api", "deletion_heavy",
                        "one_line_fix", "title_only", "has_traceback", "has_example", "long_statement"})

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", nargs="+"); ap.add_argument("--out", required=True); ap.add_argument("--min-share", type=float, default=0.05)
    a = ap.parse_args(argv)
    rows = [json.loads(l) for p in a.tasks for l in open(p) if l.strip()]
    counts = collections.Counter(); by_repo = collections.defaultdict(collections.Counter); per_task = {}
    for t in rows:
        tg = tags(t); per_task[t["instance_id"]] = sorted(tg); counts.update(tg); by_repo[t.get("repo")].update(tg)
    n = len(rows)
    share = {k: round(counts[k] / max(1, n), 3) for k in ALL}
    rep = {"n": n, "counts": {k: counts[k] for k in ALL}, "share": share, "gaps": sorted(k for k in ALL if share[k] < a.min_share),
           "repos": dict(collections.Counter(t.get("repo") for t in rows)), "per_task": per_task}
    json.dump(rep, open(a.out, "w"), indent=1)
    for k in sorted(ALL, key=lambda k: share[k]):
        print(f"{k:16} {counts[k]:5d}  {share[k]:.3f}{'  GAP' if k in rep['gaps'] else ''}")
    print("n", n)
    return 0

if __name__ == "__main__":
    sys.exit(main())
