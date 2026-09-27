"""Convert nebius/SWE-rebench-openhands-trajectories (Qwen3-Coder-480B teacher, CC-BY-4.0) into the competition harness's
tool schema, as OpenAI-style chat messages with structured tool_calls (arguments as dicts, as the Gemma template requires).

Mapping: execute_bash -> run_command; str_replace_editor view/str_replace/create -> read_file/edit_file/write_file;
finish -> submit_patch; think -> assistant text; task_tracker and unsupported editor commands (insert, undo_edit) drop the trajectory.
Filters: resolved == 1, <= MAX_TURNS assistant turns, rendered length <= MAX_CHARS, every tool mapped.
Tool results are re-shaped to the harness JSON and truncated to the harness caps (5,000 chars; read_file 150 lines / 10,000 chars).
Usage: python convert_nebius.py <parquet> <out.jsonl> [max_rows]"""
import json, re, sys

MAX_TURNS, MAX_CHARS = 60, 110_000
REASONS = {}
def _rej(r):
    REASONS[r] = REASONS.get(r, 0) + 1
    return None
SYSTEM = open(__file__.rsplit("/", 1)[0] + "/sft_system.md").read()
TOOLS = json.load(open(__file__.rsplit("/", 1)[0] + "/harness_tools.json"))
OPENAI_TOOLS = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                 "parameters": t.get("parameters_json_schema") or t.get("parameters") or {"type": "object", "properties": {}}}} for t in TOOLS]

def rel(p):
    """/workspace/<repo_dir>/a/b.py -> a/b.py ; /workspace or /workspace/<repo_dir> -> '.' ; /testbed/a.py -> a.py"""
    p = (p or "").strip().rstrip("/")
    m = re.match(r"^/(?:testbed|workspace)(?:/([^/]+))?(?:/(.*))?$", p)
    if m:
        first, rest = m.group(1), m.group(2)
        if first is None: return "."
        if "__" in first:            # OpenHands repo dir such as owner__name__version
            return rest or "."
        return f"{first}/{rest}" if rest else first
    return p.lstrip("/") or "."

def scrub(text):
    return re.sub(r"/workspace/[^/\s]*__[^/\s]*", "/workspace", text or "")

def cut(s, n=5000): return s if len(s) <= n else s[:n] + "\n...[truncated]"

def strip_catn(s):
    lines = s.splitlines()
    body = [re.sub(r"^\s*\d+\t", "", l) for l in lines if re.match(r"^\s*\d+\t", l)]
    return "\n".join(body) if body else s

def convert(traj):
    msgs, pending = [], {}
    user_seen = False
    for m in traj:
        role = m["role"]
        if role == "system": continue
        if role == "user":
            content = m["content"] or ""
            if not user_seen:
                user_seen = True
                ps = re.search(r"<issue_description>(.*?)</issue_description>", content, re.S)
                ps = ps.group(1).strip() if ps else content[:6000]
                content = (f"You are evaluating a software engineering task.\n\nProblem Statement:\n{ps}\n\n"
                           "## Execution Environment Rules\n- Command output limit: 5000 characters\n- File view limit: 150 lines per read_file call\n"
                           "- Environment is offline (no network/PyPI access). Do NOT run pip install.")
            msgs.append({"role": "user", "content": content}); continue
        if role == "assistant":
            calls, text = [], (m.get("content") or "").strip()
            for tc in (m.get("tool_calls") or []):
                fn = tc["function"]["name"]
                try: a = json.loads(tc["function"]["arguments"] or "{}")
                except Exception: return _rej("bad_json")
                cid = tc.get("id") or f"c{len(msgs)}"
                if fn == "execute_bash":
                    if a.get("is_input") in ("true", True): return _rej("is_input")
                    calls.append((cid, "run_command", {"command": a.get("command", "")}))
                elif fn == "str_replace_editor":
                    c = a.get("command")
                    if c == "view" and not re.search(r"\.[A-Za-z0-9]+$", a.get("path") or ""):
                        calls.append((cid, "run_command", {"command": f"find {rel(a.get('path')) or '.'} -maxdepth 2 -not -path '*/.git*' | head -80"}))
                    elif c == "view":
                        vr = a.get("view_range")
                        args = {"filepath": rel(a.get("path"))}
                        if isinstance(vr, list) and len(vr) == 2:
                            args["start_line"] = int(vr[0]);  args["end_line"] = int(vr[1]) if int(vr[1]) > 0 else int(vr[0]) + 149
                        calls.append((cid, "read_file", args))
                    elif c == "str_replace":
                        calls.append((cid, "edit_file", {"filepath": rel(a.get("path")), "old_string": a.get("old_str", ""), "new_string": a.get("new_str", "")}))
                    elif c == "create":
                        calls.append((cid, "write_file", {"filepath": rel(a.get("path")), "content": a.get("file_text", "")}))
                    else: return _rej("editor_" + str(c))
                elif fn == "think":
                    text = (text + "\n" + a.get("thought", "")).strip()
                elif fn == "task_tracker":
                    pass
                elif fn == "finish":
                    calls.append((cid, "submit_patch", {}))
                else: return _rej("tool_" + fn)
            if not calls and not text: continue
            out = {"role": "assistant", "content": text or None}
            if calls:
                out["tool_calls"] = [{"id": cid, "type": "function", "function": {"name": n, "arguments": args}} for cid, n, args in calls]
                for cid, n, args in calls:
                    if n != "submit_patch": pending[cid] = (n, args)
            msgs.append(out); continue
        if role == "tool":
            cid = m.get("tool_call_id")
            if cid not in pending: continue       # result of a dropped think call
            n, args = pending.pop(cid); raw = m.get("content") or ""
            if n == "run_command":
                ec = re.search(r"\[The command completed with exit code (\d+)\.\]", raw)
                raw = scrub(raw)
                body = re.sub(r"\[The command completed with exit code \d+\.\]|\[Current working directory:.*?\]|\[Python interpreter:.*?\]", "", raw).strip()
                code = int(ec.group(1)) if ec else 0
                res = {"status": "ok", "stdout": cut(body), "stderr": "", "exit_code": 0} if code == 0 else \
                      {"status": "error", "error_type": "CommandError", "error_message": f"exit code {code}", "details": {"stdout": cut(body), "stderr": "", "exit_code": code}}
            elif n == "read_file":
                body = "\n".join(strip_catn(scrub(raw)).splitlines()[:150])[:10000]
                res = {"status": "ok", "filepath": args["filepath"], "content": body}
            elif n == "edit_file":
                res = {"status": "error", "error_type": "FileEditError", "error_message": raw[:500]} if ("did not appear" in raw or "No replacement" in raw or "Multiple occurrences" in raw) \
                      else {"status": "ok", "filepath": args["filepath"], "occurrences": 1, "strategy": "exact"}
            elif n == "write_file":
                res = {"status": "ok", "filepath": args["filepath"], "size": len(args["content"])}
            else:
                res = {"status": "ok", "patch_size": 1000, "files_changed": 1}
            msgs.append({"role": "tool", "tool_call_id": cid, "name": n, "content": json.dumps(res)})
    if not any(t.get("tool_calls") and t["tool_calls"][-1]["function"]["name"] == "submit_patch" for t in msgs if t["role"] == "assistant"):
        return _rej("no_submit_or_pending")
    if sum(1 for x in msgs if x["role"] == "assistant") > MAX_TURNS: return _rej("too_many_turns")
    if len(json.dumps(msgs)) > MAX_CHARS: return _rej("too_long")
    return [{"role": "system", "content": SYSTEM}] + msgs

if __name__ == "__main__":
    import pyarrow.parquet as pq
    src, dst = sys.argv[1], sys.argv[2]; lim = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9
    pf = pq.ParquetFile(src); n_in = n_ok = 0; reasons = {}
    with open(dst, "w") as f:
        for batch in pf.iter_batches(batch_size=500, columns=["instance_id", "repo", "trajectory", "resolved"]):
            for row in batch.to_pylist():
                if n_in >= lim: break
                n_in += 1
                if row["resolved"] != 1: continue
                conv = convert(row["trajectory"])
                if conv is None: continue
                f.write(json.dumps({"instance_id": row["instance_id"], "repo": row["repo"], "messages": conv, "tools": OPENAI_TOOLS}) + "\n"); n_ok += 1
    print(f"read {n_in}, kept {n_ok}", REASONS)
