"""Pure classification of stored ATIF traces for the failure forensics (docs/a6000/FAILURE_FORENSICS.md, scripts/a6000/PROMPTS.md P5).
No I/O except load_trace; every function takes parsed trace dicts. tests/test_a6000_forensics.py."""
import collections
import json
import re

Verdict = collections.namedtuple("Verdict", "mechanism owner detail")
Loop = collections.namedtuple("Loop", "author fn args count identical_replies reply_kind owner text_between first_reply")
Call = collections.namedtuple("Call", "step author fn args content payload")

HELPER_RE = re.compile(r"/tmp/swe/(\w+)\.py")
HELPER_FRAME_RE = re.compile(r'swe/(\w+)\.py", line \d+')
ECHO_RE = re.compile(r'^\s*(run_command|run_skill_script|submit_patch|read_file|write_file|edit_file|get_status)\s*(\(|:|"|$)')
SBX_RE = re.compile(r"/tmp/(sbx_[^/\s]+/)?swegemma_sandbox_[^/\s\"']+")
CORRUPT_RE = re.compile(r"[`「」]|,start_line|,end_line|<\|\"\|>|^\":\"$")
LEAK_RE = re.compile(r"<\|tool_call>|\bcall:\w+\{")


def arm_of(path):
    p = path.replace("\\", "/")
    if "/items/" in p:
        return p.split("/items/")[1].split("/")[0]
    if "/p4/" in p:
        return "v5h2"
    m = re.search(r"/probe_[^/]+/([^/]+)/", p)
    return m.group(1) if m else "?"


def load_trace(path):
    with open(path) as f:
        return json.load(f)


def _content(obs):
    if obs is None:
        return None
    return obs.get("content") if isinstance(obs, dict) else obs


def _payload(content):
    if content is None:
        return None
    if isinstance(content, dict):
        return content
    try:
        p = json.loads(content)
    except (ValueError, TypeError):
        return None
    return p if isinstance(p, dict) else None


def iter_calls(trace):
    out = []
    for i, s in enumerate(trace.get("steps", [])):
        author = (s.get("extra") or {}).get("author")
        obs = s.get("observation")
        for tc in s.get("tool_calls") or []:
            c = _content(obs)
            out.append(Call(i, author, tc.get("function_name"), tc.get("arguments") or {}, c if isinstance(c, str) else json.dumps(c), _payload(c)))
    return out


def call_text(fn, args):
    if isinstance(args, dict) and "command" in args and fn == "run_command":
        return str(args["command"])
    return json.dumps(args, sort_keys=True, default=str)


def _helper(cmd):
    m = HELPER_RE.search(cmd or "")
    return m.group(1) if m else None


def _looks_corrupted(args):
    for v in (args or {}).values():
        if isinstance(v, str) and CORRUPT_RE.search(v):
            return True
    return False


def classify(fn, args, payload):
    """-> Verdict(mechanism, owner in {ours, harness, model}, detail) for one tool call and its parsed observation."""
    args = args if isinstance(args, dict) else {}
    cmd = str(args.get("command", "")) if fn == "run_command" else ""
    if payload is None:
        return Verdict("unparseable observation", "harness", "")
    if "error_code" in payload:                                              # run_skill_script's own rejections
        code = payload["error_code"]
        if code in ("SKILL_NOT_FOUND", "SCRIPT_NOT_FOUND") or _looks_corrupted(args):
            return Verdict("parser-corrupted arguments (gemma4 tool parser)", "harness", f"{code}: {json.dumps(args)[:80]}")
        if code == "INVALID_ARGUMENTS":
            return Verdict("harness rejection: INVALID_ARGUMENTS (arguments dropped)", "harness", json.dumps(args)[:80])
        return Verdict("harness rejection: " + code, "harness", json.dumps(args)[:80])
    status = payload.get("status")
    stderr_json = None
    if fn == "run_skill_script" and status == "error":
        stderr_json = _payload(payload.get("stderr"))
    if status == "error":
        et = payload.get("error_type") or (stderr_json or {}).get("error_type")
        msg = str(payload.get("error_message") or (stderr_json or {}).get("error_message") or "")
        if et == "BudgetExceeded":
            return Verdict("budget exhausted (70 tool calls)", "harness", "")
        if et == "TimeoutExceeded":
            return Verdict("command timeout", "model", cmd[:80])
        if "Path traversal" in msg:
            return Verdict("write_file outside the workspace refused", "ours", str(args.get("filepath", ""))[:80])
        if et == "FileReadError":
            if _looks_corrupted(args) or "Invalid integer" in msg:
                return Verdict("parser-corrupted arguments (gemma4 tool parser)", "harness", json.dumps(args)[:100])
            if "cannot be greater" in msg:
                return Verdict("read_file bad range (model)", "model", msg[:80])
            return Verdict("file not found (model path)", "model", str(args.get("filepath", ""))[:80])
        if et == "ValueError" and "cannot be greater" in msg:
            return Verdict("read_file bad range (model)", "model", msg[:80])
        if et == "FileEditError":
            return Verdict("edit_file old_string not found (parser/model)", "model", msg[:80])
        if et == "CommandError":
            d = payload.get("details") or {}
            out = "\n".join(str(x) for x in (d.get("stdout"), d.get("stderr"), msg) if x)
            h = _helper(cmd)
            if ECHO_RE.match(cmd):
                return Verdict("prompt call-shape echoed into the command", "ours", cmd[:80].replace("\n", " "))
            if "can't open file" in out and ("/swe/" in out or h):
                m = re.search(r"can't open file '[^']*/swe/(\w+)\.py'", out)
                return Verdict(f"can't open file: helper not installed ({m.group(1) if m else h})", "ours", cmd[:80])
            m = HELPER_FRAME_RE.search(out)
            if m:
                return Verdict(f"helper traceback ({m.group(1)})", "ours", out.strip().splitlines()[-1][:120])
            if out.lstrip().startswith("usage:") or "unrecognized arguments" in out or "error: the following arguments" in out or "give args=" in out:
                return Verdict(f"helper usage/argument error ({h})", "ours", cmd[:100])
            first = (d.get("stdout") or "").strip().split("\n")[0]
            if h == "edit":
                for key, name in (("NO MATCH", "NO MATCH"), ("AMBIGUOUS", "AMBIGUOUS"), ("SYNTAX ERROR", "SYNTAX ERROR (reverted)"), ("REFUSED --create", "REFUSED (--create exists)"),
                                  ("REFUSED", "REFUSED (test/config file)"), ("NO CHANGE", "NO CHANGE"), ("ERROR: the edit ended early", "edit ended early (heredoc)"), ("ERROR: --lines", "--lines outside the file")):
                    if first.startswith(key):
                        return Verdict("edit.py verdict: " + name, "model", first[:100])
            if "syntax error near unexpected token" in out:
                return Verdict("bash syntax error in the heredoc (model)", "model", cmd[:80].replace("\n", " "))
            if "Traceback" in out:
                return Verdict("model script traceback (repro / python -c)", "model", cmd[:80].replace("\n", " "))
            if "test session starts" in out:
                return Verdict("pytest run red", "model", cmd[:80])
            if "command not found" in out:
                return Verdict("shell: command not found (model)", "model", out.strip().split("\n")[0][:100])
            if h == "edit":
                return Verdict("edit.py verdict: other", "model", first[:100])
            return Verdict("command non-zero exit (grep no match etc.)", "model", cmd[:80].replace("\n", " "))
        return Verdict("error: " + str(et), "harness", msg[:100])
    if fn == "run_command":
        stdout, stderr = str(payload.get("stdout") or ""), str(payload.get("stderr") or "")
        h = _helper(cmd)
        if stdout.lstrip().startswith("usage:") or stdout.lstrip().startswith("give args="):
            return Verdict(f"helper usage/argument error ({h})", "ours", cmd[:100].replace("\n", " "))
        if "ALREADY SHOWN" in stdout:
            return Verdict("view.py repeat refused (ours, by design)", "model", cmd[:80])
        if "REPRO MISSING" in stdout:
            return Verdict("repro.py: no /tmp/repro.py to run", "model", cmd[:80])
        if h == "view" and stdout.startswith("no such file:"):
            return Verdict("view.py no such file (model path)", "model", cmd[:80])
        if h == "locate" and "no matches;" in stdout:
            return Verdict("locate.py: no matches (model query)", "model", cmd[:80])
        if not stdout.strip() and not stderr.strip():
            return Verdict("empty output", "model", cmd[:80].replace("\n", " "))
    return Verdict("ok", "", "")


def leaked_tool_calls(trace):
    """Agent text messages that contain raw Gemma tool-call syntax: the server's parser did not turn the call into a tool call."""
    return sum(1 for s in trace.get("steps", []) if s.get("source") == "agent" and isinstance(s.get("message"), str) and LEAK_RE.search(s["message"]))


def _reply_kind(payload, content):
    c = content or ""
    if payload and payload.get("status") == "error":
        return "error: " + str(payload.get("error_type") or "?")
    if "ALREADY SHOWN" in c:
        return "our repeat refusal (ALREADY SHOWN)"
    if '"stdout": "usage:' in c or (payload and str(payload.get("stdout") or "").lstrip().startswith("usage:")):
        return "helper usage line"
    if payload and not str(payload.get("stdout") or "").strip() and not str(payload.get("stderr") or "").strip() and "stdout" in payload:
        return "empty output"
    if "(output cut)" in c or len(c) > 4800:
        return "truncated reply"
    return "normal result"


def find_loops(trace, n=5):
    steps = trace.get("steps", [])
    seq = []
    for i, s in enumerate(steps):
        author = (s.get("extra") or {}).get("author")
        c = _content(s.get("observation"))
        for tc in s.get("tool_calls") or []:
            seq.append((i, author, tc.get("function_name"), json.dumps(tc.get("arguments") or {}, sort_keys=True, default=str), c if isinstance(c, str) else json.dumps(c)))
    loops, i = [], 0
    while i < len(seq):
        j = i
        while j + 1 < len(seq) and seq[j + 1][1:4] == seq[i][1:4]:
            j += 1
        if j - i + 1 >= n:
            replies = [x[4] for x in seq[i:j + 1]]
            kind = _reply_kind(_payload(replies[0]), replies[0])
            owner = {"our repeat refusal (ALREADY SHOWN)": "model", "helper usage line": "ours", "empty output": "ours", "truncated reply": "ours", "normal result": "model"}.get(kind, "harness" if "Budget" in kind else "model")
            lo, hi = seq[i][0], seq[j][0]
            between = [s["message"] for s in steps[lo:hi + 1] if s.get("source") == "agent" and isinstance(s.get("message"), str)]
            loops.append(Loop(seq[i][1], seq[i][2], seq[i][3], j - i + 1, len(set(replies)) == 1, kind, owner, between, (replies[0] or "")[:200]))
        i = j + 1
    return loops


def _authors(trace):
    return [(s.get("extra") or {}).get("author") for s in trace.get("steps", []) if (s.get("extra") or {}).get("author") and (s.get("tool_calls") or s.get("message"))]


def _select_report(trace):
    for c in iter_calls(trace):
        if c.fn == "run_skill_script" and isinstance(c.args, dict) and c.args.get("file_path") == "select_best.py" and c.payload:
            out = str(c.payload.get("stdout") or "")
            if "select_best:" in out:
                return out
    return None


def empty_patch_cause(trace, row):
    err = str(row.get("error") or "")
    authors = _authors(trace)
    last = authors[-1] if authors else "?"
    calls = iter_calls(trace)
    if "session timeout" in err:
        return f"time cap hit at the {last}"
    budget = [c for c in calls if c.payload and (c.payload.get("error_type") == "BudgetExceeded" or "BudgetExceeded" in str(c.payload.get("stderr") or ""))]
    if budget:
        return f"budget exhausted at the {budget[0].author} ({len(budget)} refused calls after the 70th)"
    if "TaskGroup" in err or "Sandbox execution error" in err:
        return "harness crash: " + err[:70]
    rep = _select_report(trace)
    if rep is not None and re.search(r"^PICK none", rep, re.M):
        return "selector: every candidate empty (fixers produced no diff)"
    if "verifier" not in authors:
        return f"verifier never ran (stopped after the {last}, no error)"
    ok_edits = sum(1 for c in calls if c.fn == "run_command" and "/tmp/swe/edit.py" in str(c.args.get("command", "")) and c.payload and str(c.payload.get("stdout") or "").lstrip().startswith("OK"))
    refused = sum(1 for c in calls if c.fn == "run_command" and "/tmp/swe/edit.py" in str(c.args.get("command", "")) and "REFUSED" in (str((c.payload or {}).get("details", {}).get("stdout") or "") + str((c.payload or {}).get("stdout") or "")))
    submitted = any(c.fn == "submit_patch" for c in calls)
    if ok_edits == 0 and refused > 0:
        return "only test-file edits attempted (refused by edit.py); submitted empty" if submitted else "only test-file edits attempted (refused by edit.py); never submitted"
    if submitted:
        return f"verifier submitted an empty diff after {ok_edits} successful edit(s)"
    return f"verifier ran but never called submit_patch ({ok_edits} successful edits)"


def v6p_pipeline(trace):
    calls = iter_calls(trace)
    ok = lambda c: c.payload is not None and c.payload.get("status") in ("ok", "success")
    cmd = lambda c: str(c.args.get("command", "")) if isinstance(c.args, dict) else ""
    loc = [c for c in calls if c.author == "locator"]
    wrote = any(c.fn == "run_command" and ok(c) and (re.search(r"cat\s*>\s*/tmp/repro\.py", cmd(c)) or ("/tmp/repro.py" in cmd(c) and "--create" in cmd(c))) for c in loc) or \
        any(c.fn == "write_file" and ok(c) and "/tmp/repro.py" in str(c.args.get("filepath", "")) for c in loc)
    how, failed = None, None
    for c in loc:
        if c.fn != "run_command":
            continue
        s = cmd(c)
        if "/tmp/swe/repro.py" in s:
            how = "helper"
            failed = "REPRO FAIL" in str((c.payload or {}).get("stdout") or "")
        elif "python3 /tmp/repro.py" in s and how != "helper":
            how = "direct"
            p = c.payload or {}
            failed = p.get("status") == "error" or "REPRO FAIL" in str(p.get("stdout") or "")
    copies = {k: any(c.author == f"fixer_{k}" and f"cp -a /workspace /tmp/w{k}" in cmd(c) and ok(c) for c in calls) for k in "abc"}
    nonempty = 0
    for k in "abc":
        for c in calls:
            if c.author == f"fixer_{k}" and f"/tmp/w{k} diff --stat" in cmd(c) and ok(c) and str(c.payload.get("stdout") or "").strip():
                nonempty += 1
                break
    rep = _select_report(trace)
    select_ran = rep is not None
    m = re.search(r"repro=([^|\n]+)", rep or "")
    select_repro = re.sub(r"\s*\([^)]*\)\s*$", "", m.group(1).strip()) if m else None
    pm = re.search(r"^PICK (\w+)", rep or "", re.M)
    pick = pm.group(1) if pm else None
    applied = bool(rep) and "applied to the workspace" in rep
    submitted = any(c.author == "verifier" and c.fn == "submit_patch" and ok(c) for c in calls)
    checks = [("locator wrote /tmp/repro.py", wrote), ("locator repro fails before the fix", bool(failed))] + [(f"fixer_{k} copy", copies[k]) for k in "abc"] + \
        [("at least one non-empty diff", nonempty > 0), ("selector ran select_best", select_ran), ("a candidate was picked and applied", applied), ("verifier submit_patch", submitted)]
    first = next((name for name, v in checks if not v), None)
    return {"locator_wrote_repro": wrote, "repro_run_how": how, "repro_failed_before_fix": failed, "copies": copies, "nonempty_diffs": nonempty, "select_ran": select_ran,
            "select_repro": select_repro, "pick": pick, "applied": applied, "verifier_submitted": submitted, "first_broken": first, "checks": checks}


def _norm(call):
    return SBX_RE.sub("<sbx>", call)


def first_divergence(ta, tb, skip=("setup",)):
    A = [(c.author, c.fn, _norm(call_text(c.fn, c.args))) for c in iter_calls(ta) if c.author not in skip]
    B = [(c.author, c.fn, _norm(call_text(c.fn, c.args))) for c in iter_calls(tb) if c.author not in skip]
    i = 0
    while i < min(len(A), len(B)) and (A[i][1], A[i][2][:60]) == (B[i][1], B[i][2][:60]):
        i += 1
    if i >= len(A) and i >= len(B):
        return {"index": None, "a": None, "b": None, "len_a": len(A), "len_b": len(B)}
    mk = lambda x: {"author": x[0], "fn": x[1], "call": x[2][:160]} if x else None
    return {"index": i, "a": mk(A[i]) if i < len(A) else None, "b": mk(B[i]) if i < len(B) else None, "len_a": len(A), "len_b": len(B)}


def mechanism_table(traces):
    """traces: {arm: {task: trace}} -> {arm: {mechanism: {calls, tasks: set, owner, example: {task, call, reply}}}}"""
    tab = {}
    for arm, by_task in traces.items():
        t = tab.setdefault(arm, {})
        for tid, tr in by_task.items():
            for c in iter_calls(tr):
                v = classify(c.fn, c.args, c.payload)
                row = t.setdefault(v.mechanism, {"calls": 0, "tasks": set(), "owner": v.owner, "example": None})
                row["calls"] += 1
                row["tasks"].add(tid)
                if row["example"] is None:
                    row["example"] = {"task": tid, "call": call_text(c.fn, c.args)[:300], "reply": (c.content or "")[:300], "detail": v.detail}
    return tab
