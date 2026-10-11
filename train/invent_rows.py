#!/usr/bin/env python3
"""Invent (Adaption) issue->patch rows -> training rows shaped like the v12 agent's own calls (docs/GAPS_2026-10-06.md, "Invent rows as
an auxiliary arm", 2026-10-11). Input rows {enhanced_prompt, enhanced_completion}: an issue (title, description, traceback) with a source
excerpt ('File: `path` (lines a-b)' followed by a ```python fence; the last python fence when the marker is missing), then numbered
reasoning and ONE ```diff fenced unified diff. Nothing here is test-verified, so the filter is mechanical and strict, and every
rejection is counted:
  - exactly one file in the diff, not a test file, a repository we know (owner/repo from the path, else from the issue text);
  - every hunk's context and removed lines occur exactly once in the excerpt (applied in sequence -> the patched excerpt);
  - when the excerpt parses as Python (after dedent) the patched excerpt must parse too ("verified"); otherwise "unverifiable".
Each kept item is a two-call trajectory rendered through train/scorer_render.py as a v12 request would be: the real system instruction,
the task message (prefix/suffix from a real request or trace, the issue as the problem statement), call 1 = thought (the reasoning's
first step) + read_file(filepath, start_line, end_line) over the excerpt's lines, tool result = the harness's read_file envelope with the
excerpt as content, call 2 = thought (the remaining steps) + edit_file(filepath, old_string, new_string) with the minimal changed block
plus 2 lines of context, unique in the excerpt. The task message keeps the harness's fixed sections (Task Budget, Execution Environment
Rules, Instructions) and DROPS the per-task '## Workspace Layout' directory tree: there is no real tree for an invented issue and a
borrowed one would be wrong (recorded in GAPS; the rows differ from serving by that section). Rows carry meta {task, traj, stage None, continuation, tool, thinking, reasoning_chars,
source "invent"}, so train/stitch_rows.py chains them byte-exactly and train/validate_rows.py --require-thought accepts them.

    python train/invent_rows.py IN.jsonl [IN2 ...] --out rows.jsonl --report report.json \\
        (--template-capture CAPTURE.jsonl | --template-trace TRACE.json --tool-schemas docs/v11/evidence/tool_schemas_v10.json
         [--tools run_command,read_file,edit_file,write_file,get_status,submit_patch] [--system submissions/v12/prompts/system.md])
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import textwrap
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from train.scorer_render import canonical_completion, render  # noqa: E402

MODEL = "gemma-4-31b-it-qat-w4a16-ct"
V12_TOOLS = ["run_command", "read_file", "edit_file", "write_file", "get_status", "submit_patch"]
REPOS = {"fastapi": "fastapi/fastapi", "starlette": "encode/starlette", "pydantic": "pydantic/pydantic", "rich": "Textualize/rich",
         "textual": "Textualize/textual", "requests": "psf/requests", "urllib3": "urllib3/urllib3", "httpx": "encode/httpx",
         "flask": "pallets/flask", "werkzeug": "pallets/werkzeug", "click": "pallets/click", "jinja2": "pallets/jinja", "jinja": "pallets/jinja",
         "itsdangerous": "pallets/itsdangerous", "markupsafe": "pallets/markupsafe", "sqlalchemy": "sqlalchemy/sqlalchemy",
         "attr": "python-attrs/attrs", "attrs": "python-attrs/attrs", "pytest": "pytest-dev/pytest", "_pytest": "pytest-dev/pytest",
         "tornado": "tornadoweb/tornado"}
TEST_PATH = re.compile(r"(^|/)tests?(/|$)|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$")
FILE_MARK = re.compile(r"^\**File\**:\s*`([^`]+)`(?:\s*\(lines?\s*(\d+)\s*[-–]\s*(\d+)\))?[^\n]*$", re.M)
FENCE = re.compile(r"```([A-Za-z0-9_+-]*)[^\n]*\n(.*?)```", re.S)
TITLE = re.compile(r"^(?:#+\s*)?(?:\*\*)?(?:Issue|Title)(?:\*\*)?\s*:\s*(.+?)\s*$", re.M)
HUNK = re.compile(r"^@@[^\n]*\n", re.M)
STEP = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+", re.M)
HEADER = re.compile(r"^#+\s*[^\n]*$", re.M)


class Template:
    """The fixed parts of a v12 request: system instruction, tool declarations, the task message around the problem statement."""

    def __init__(self, system, tools, user_prefix, user_suffix):
        self.system, self.tools, self.user_prefix, self.user_suffix = system, tools, user_prefix, user_suffix

    @staticmethod
    def split_user(user):
        m = re.search(r"for repository (\S+)\.\n\nProblem Statement:\n", user)
        if not m:
            raise SystemExit("template: the task message has no 'for repository X.\\n\\nProblem Statement:\\n' head")
        prefix = user[:m.end()].replace(m.group(1), "{repo}", 1)
        k = re.search(r"\n+## Task Budget", user) or re.search(r"\n+## ", user[m.end():])
        suffix = user[k.start():] if k else ""
        w = re.search(r"\n+## Workspace Layout", suffix)          # the per-task directory tree: no real tree exists for an invented issue
        if w:
            suffix = suffix[:w.start()] + "\n"
        return prefix, suffix

    @classmethod
    def from_capture(cls, path):
        row = json.loads(next(l for l in open(path) if l.strip()))
        body = row["body"]
        text = lambda c: c if isinstance(c, str) else " ".join(p.get("text", "") for p in (c or []) if isinstance(p, dict))  # noqa: E731
        system = next(text(m.get("content")) for m in body["messages"] if m.get("role") == "system")
        user = next(text(m.get("content")) for m in body["messages"] if m.get("role") == "user")
        prefix, suffix = cls.split_user(user)
        return cls(system, body.get("tools") or [], prefix, suffix)

    @classmethod
    def from_trace(cls, trace_path, schemas_path, tool_names, system_path=None):
        t = json.load(open(trace_path))
        steps = t.get("steps") or []
        system = next((s["message"] for s in steps if s.get("source") == "system"), None)
        if system_path:
            system = Path(system_path).read_text()
        user = next(s["message"] for s in steps if s.get("source") == "user")
        schemas = json.load(open(schemas_path))
        tools = []
        for n in tool_names:
            v = schemas[n]
            tools.append(v if isinstance(v, dict) and v.get("type") == "function" else {"type": "function", "function": v})
        prefix, suffix = cls.split_user(user)
        return cls(system, tools, prefix, suffix)


def repo_of(path, text):
    parts = path.split("/")
    for key in (parts[0], parts[0].replace("-", "_"), parts[1] if parts[0] == "src" and len(parts) > 1 else ""):
        if key in REPOS:
            return REPOS[key]
    low = text.lower()
    for key, repo in REPOS.items():
        if re.search(rf"\b{re.escape(key)}\b", low):
            return repo
    return None


def parse_hunks(diff):
    out = []
    for body in HUNK.split(diff)[1:]:
        old, new = [], []
        for line in body.split("\n"):
            if line.startswith(("\\", "diff --git", "index ", "--- a/", "+++ b/")):
                continue
            tag, text = (line[0], line[1:]) if line[:1] in (" ", "-", "+") else (" ", line)
            if tag in " -":
                old.append(text)
            if tag in " +":
                new.append(text)
        while old and new and old[-1] == "" and new[-1] == "":        # the fence's trailing newline
            old.pop(); new.pop()
        out.append(("\n".join(old), "\n".join(new)))
    return out


def parse(prompt, completion):
    """-> (item, None) or (None, reason). item: title, statement, path, start, end, excerpt, reasoning, diff, hunks."""
    tm = TITLE.search(prompt)
    title = (tm.group(1) if tm else next((l.strip("# ").strip() for l in prompt.splitlines() if l.strip()), "")).strip()
    dm = next((m for m in FENCE.finditer(completion) if m.group(1).lower() == "diff" or m.group(2).lstrip().startswith(("--- ", "diff --git"))), None)
    if dm is None:
        return None, "no_diff"
    diff = dm.group(2)
    files = sorted(set(re.findall(r"^\+\+\+ (?:b/)?(\S+)", diff, re.M)))
    if len(files) != 1:
        return None, "multi_file" if files else "no_file_in_diff"
    path = files[0]
    if TEST_PATH.search(path):
        return None, "test_file"
    reasoning = HEADER.sub("", completion[:dm.start()]).strip()
    if not reasoning:
        return None, "no_reasoning"
    excerpt = cut = tail = None
    start = end = None
    marks = list(FILE_MARK.finditer(prompt))
    for m in marks:
        fm = FENCE.search(prompt, m.end())
        if fm and (len(marks) == 1 or m.group(1).endswith(path) or path.endswith(m.group(1))):
            excerpt, cut, tail = fm.group(2), m.start(), fm.end()
            if m.group(2):
                start, end = int(m.group(2)), int(m.group(3))
            break
    if excerpt is None:
        fences = [m for m in FENCE.finditer(prompt) if m.group(1).lower() in ("python", "py", "")]
        if not fences:
            return None, "no_excerpt"
        fm = fences[-1]
        excerpt, cut, tail = fm.group(2), fm.start(), fm.end()
    excerpt = excerpt.rstrip("\n")
    if excerpt.count("\n") + 1 < 5:
        return None, "excerpt_too_short"
    head = re.sub(r"\**Relevant Source Excerpt\**:?\s*$", "", prompt[:cut].strip()).strip()
    rest = prompt[tail:].strip()
    statement = head + ("\n\n" + rest if rest else "")
    if start is None:
        start, end = 1, excerpt.count("\n") + 1
    hunks = parse_hunks(diff)
    if not hunks or any(old == "" for old, _ in hunks):
        return None, "no_hunks"
    return {"title": title, "statement": statement, "path": path, "start": start, "end": end, "excerpt": excerpt,
            "reasoning": reasoning, "diff": diff, "hunks": hunks}, None


def apply_hunks(excerpt, hunks):
    """The patched excerpt, or None when a hunk's old block is not found exactly once (exact, then trailing-whitespace-insensitive)."""
    text = excerpt
    for old, new in hunks:
        if text.count(old) == 1:
            text = text.replace(old, new)
            continue
        tl, ol = text.split("\n"), old.split("\n")
        hits = [i for i in range(len(tl) - len(ol) + 1) if [x.rstrip() for x in tl[i:i + len(ol)]] == [x.rstrip() for x in ol]]
        if len(hits) != 1:
            return None
        i = hits[0]
        tl[i:i + len(ol)] = new.split("\n")
        text = "\n".join(tl)
    return text


def python_verdict(excerpt, patched):
    def ok(t):
        try:
            ast.parse(textwrap.dedent(t))
            return True
        except SyntaxError:
            return False
    if not ok(excerpt):
        return "unverifiable"
    return "verified" if ok(patched) else "patched_not_python"


def edit_region(excerpt, patched, context=2):
    """(old_string, new_string): the changed lines with `context` lines around them, grown until old_string is unique in the excerpt."""
    a, b = excerpt.split("\n"), patched.split("\n")
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    j = 0
    while j < min(len(a), len(b)) - i and a[-1 - j] == b[-1 - j]:
        j += 1
    lo, hi = max(0, i - context), min(len(a), len(a) - j + context)
    while True:
        old = "\n".join(a[lo:hi])
        new = "\n".join(b[lo:len(b) - (len(a) - hi)])
        if excerpt.count(old) == 1 or (lo == 0 and hi == len(a)):
            return old, new
        lo, hi = max(0, lo - 1), min(len(a), hi + 1)


def split_reasoning(text):
    """(thought before the read, thought before the edit): the first numbered step, then the rest; paragraphs when unnumbered."""
    steps = [s.strip() for s in STEP.split(text) if s.strip()]
    if len(steps) < 2:
        steps = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(steps) < 2:
        return "", text.strip()
    return steps[0], "\n".join(steps[1:])


def build_rows(item, template: Template, dataset):
    """-> ([row_read, row_edit], None) or (None, reason)."""
    repo = repo_of(item["path"], item["title"] + " " + item["statement"])
    if not repo:
        return None, "unknown_repo"
    patched = apply_hunks(item["excerpt"], item["hunks"])
    if patched is None:
        return None, "hunk_not_in_excerpt"
    verdict = python_verdict(item["excerpt"], patched)
    if verdict == "patched_not_python":
        return None, verdict
    old, new = edit_region(item["excerpt"], patched)
    pre_read, pre_edit = split_reasoning(item["reasoning"])
    lines = item["statement"].splitlines()
    if lines and TITLE.match(lines[0]):
        lines[0] = item["title"]
    statement = "\n".join(lines).strip()
    user = template.user_prefix.replace("{repo}", repo) + statement + template.user_suffix
    task = "invent_" + hashlib.sha1(item["title"].encode("utf-8", "replace")).hexdigest()[:12]
    msgs = [{"role": "system", "content": template.system}, {"role": "user", "content": user}]
    body1 = {"model": MODEL, "messages": msgs, "tools": template.tools, "chat_template_kwargs": {"enable_thinking": True}, "thinking_token_budget": 4096}
    call1 = {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": json.dumps(
        {"filepath": item["path"], "start_line": item["start"], "end_line": item["end"]})}}
    msg1 = {"role": "assistant", "content": "", "reasoning": pre_read, "tool_calls": [call1]}
    result1 = json.dumps({"status": "ok", "filepath": item["path"], "content": item["excerpt"], "start_line": item["start"], "end_line": item["end"],
                          "total_lines": item["end"], "is_truncated": False}, ensure_ascii=False)
    tool1 = {"role": "tool", "tool_call_id": "call_1", "content": json.dumps({"result": result1})}
    carried = {"role": "assistant", "content": "", "tool_calls": [call1]}
    if pre_read:
        carried["reasoning_content"] = pre_read
        carried["reasoning"] = pre_read
    body2 = dict(body1, messages=msgs + [carried, tool1])
    call2 = {"id": "call_2", "type": "function", "function": {"name": "edit_file", "arguments": json.dumps(
        {"filepath": item["path"], "old_string": old, "new_string": new})}}
    msg2 = {"role": "assistant", "content": "", "reasoning": pre_edit, "tool_calls": [call2]}
    meta = {"task": task, "traj": f"invent|{dataset}|{task}", "stage": None, "thinking": True, "source": "invent", "dataset": dataset,
            "repo": repo, "verdict": verdict, "hunks": len(item["hunks"])}
    rows = [{"prompt": render(body1), "completion": canonical_completion(msg1, False, True),
             "meta": dict(meta, continuation=False, tool="read_file", reasoning_chars=len(pre_read))},
            {"prompt": render(body2), "completion": canonical_completion(msg2, True, True),
             "meta": dict(meta, continuation=True, tool="edit_file", reasoning_chars=len(pre_edit))}]
    return rows, None


def convert(paths, template: Template):
    rows, rep, seen = [], Counter(), set()
    verdicts, hunks = Counter(), Counter()
    for p in paths:
        name = Path(p).stem
        for line in open(p):
            if not line.strip():
                continue
            e = json.loads(line)
            rep["rows_in"] += 1
            item, why = parse(e.get("enhanced_prompt") or e.get("prompt") or "", e.get("enhanced_completion") or e.get("completion") or "")
            if why:
                rep["rejected:" + why] += 1
                continue
            key = item["title"].strip().lower()
            if key in seen:
                rep["rejected:duplicate_title"] += 1
                continue
            built, why = build_rows(item, template, name)
            if why:
                rep["rejected:" + why] += 1
                continue
            seen.add(key)
            rep["kept"] += 1
            verdicts[built[0]["meta"]["verdict"]] += 1
            hunks[str(len(item["hunks"]))] += 1
            rows += built
    report = {"rows_in": rep["rows_in"], "kept": rep["kept"], "rows_out": len(rows),
              "rejected": {k.split(":", 1)[1]: v for k, v in rep.items() if k.startswith("rejected:")},
              "verdicts": dict(verdicts), "hunks_per_item": dict(hunks),
              "thought_chars": sum(r["meta"]["reasoning_chars"] for r in rows), "rows_with_thought": sum(1 for r in rows if r["meta"]["reasoning_chars"]),
              "repos": dict(Counter(r["meta"]["repo"] for r in rows[::2]))}
    return rows, report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inputs", nargs="+"); ap.add_argument("--out", required=True); ap.add_argument("--report", required=True)
    ap.add_argument("--template-capture", help="a pace-proxy capture row of a real v12 request (preferred: byte-exact system, tools, task message)")
    ap.add_argument("--template-trace", help="an ATIF trace of a real v12 run (steps: system_instruction + task_prompt)")
    ap.add_argument("--tool-schemas", help="JSON {tool name: schema} (docs/v11/evidence/tool_schemas_v10.json) for --template-trace")
    ap.add_argument("--tools", default=",".join(V12_TOOLS), help="tool names, in the bundle's YAML order")
    ap.add_argument("--system", help="override the system instruction with this file's text")
    a = ap.parse_args(argv)
    if a.template_capture:
        template = Template.from_capture(a.template_capture)
    elif a.template_trace and a.tool_schemas:
        template = Template.from_trace(a.template_trace, a.tool_schemas, a.tools.split(","), a.system)
    else:
        ap.error("--template-capture or --template-trace with --tool-schemas is required")
    rows, report = convert(a.inputs, template)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    Path(a.report).write_text(json.dumps(report, indent=1, sort_keys=True))
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
