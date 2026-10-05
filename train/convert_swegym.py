"""Turn SWE-Gym/OpenHands-SFT-Trajectories (491 successful OpenHands CodeAct runs, text-action format) into one-call SFT
rows in our fixer format: {"prompt": scorer-rendered prefix, "completion": canonical reply, "meta": {task, traj, stage,
continuation, tool}}, the same shape as train/build_sft.py, so they can be merged with our own rows.

    python train/convert_swegym.py fetch   [--data-dir data/swegym]          # parquet + task metadata + touched source files
    python train/convert_swegym.py convert [--data-dir data/swegym] [--out data/v11/rows_swegym.jsonl]
        [--report data/v11/rows_swegym_report.json] [--max-tokens 30000] [--exclude-ids data/pallets/dev40_ids.txt ...]

SOURCE AND LICENCE (checked 2026-10-05): dataset card licence MIT (revision pinned below). The trajectories were sampled
from gpt-4o-2024-08-06 and claude-3-5-sonnet-20241022 (arXiv 2412.21139, App. B.4: "These trajectories are sampled from
gpt-4o-2024-08-06 and claude-3-5-sonnet-20241022"): closed API teachers, NOT open-weight. research/distill.md 2.3 rates
this class "Doubtful (Q3)" under the competition rules; settle that before these rows enter a submitted adapter.

MAPPING (OpenHands -> our harness tools). The harness's mandatory first call, run_skill_script(install.py), is put in
front of every trajectory with its recorded result (history only, never a training row):
  execute_bash               -> run_command(command); /workspace/<repo_dir> collapsed onto /workspace (our repo root)
  str_replace_editor view    -> read_file(filepath[, start_line, end_line]) for a file; for a directory, run_command with
                                the same `find <dir> -maxdepth 2 -not -path '*/\\.*'` OpenHands ran
  str_replace_editor str_replace -> run_command("python3 /tmp/swe/edit.py FILE <<'EOF' SEARCH/REPLACE EOF"), the SEARCH
                                block widened to the whole lines old_str spans
  str_replace_editor create  -> write_file(filepath, content)
  finish                     -> submit_patch()
Tool results are what the harness would return (swegemma 0.2.7 shapes, JSON-encoded twice), computed from the real files:
read_file from the file at the instance's base_commit (fetched from GitHub, then replayed through the trajectory's own
edits), edit output by running the bundle's real edit.py on that file.

POLICY. Drop the whole trajectory when an action cannot be expressed in our tools: insert / undo_edit / other editor
commands, any other tool (browsing), a path outside /workspace, a str_replace on a path edit.py refuses (tests, config),
no finish, a gold patch with no .py file (non-Python), or no SWE-Gym instance. Remove a step (call + result) that carries
no usable information or whose error our tools would word differently: prose-only turns and OpenHands' "Please continue"
nudges, editor calls that returned ERROR, runtime failures (504). Cut the trajectory (keep the rows before) where our
harness would show the model something different from what the teacher saw, because later actions may rest on it:
after a result over our caps (run_command 5,000 chars; read_file 150 lines / 10,000 chars) or a read that disagrees with
the replayed file; before an edit that edit.py would not reproduce (no unique match, reverted for a syntax error,
different result), a command run from another directory of OpenHands' stateful shell, or a file state we cannot know.
Rows longer than --max-tokens (prompt + completion, Gemma tokenizer) are dropped.
Known approximations: OpenHands' pty merges stderr into stdout, so all output is put in stdout (and in error_message on a
non-zero exit); a trailing newline the pty observation lost is restored; no budget_warning fields (no budget is set).
tests/test_swegym_convert.py.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from train.scorer_render import canonical_completion, render  # noqa: E402

DATASET, DATASET_REV = "SWE-Gym/OpenHands-SFT-Trajectories", "4aaa5a4a4b5861f4799d2336908760c190ac3b17"
DATASET_FILE = "data/train.success.oss-00000-of-00001.parquet"
TASKS, TASKS_REV = "SWE-Gym/SWE-Gym", "bb94ed9e39bbeb96a7fcbfb533b80f25a7fd59cb"
TASKS_FILE = "data/train-00000-of-00001.parquet"
SOURCE = {"dataset": DATASET, "revision": DATASET_REV, "licence": "MIT (dataset card `license: mit`)",
          "task_metadata": f"{TASKS}@{TASKS_REV} (MIT)",
          "teacher_models": ["gpt-4o-2024-08-06", "claude-3-5-sonnet-20241022"],
          "teacher_source": "arXiv 2412.21139 App. B.4 / Table 10",
          "teacher_note": "closed API teachers, not open-weight; research/distill.md 2.3 rates this class Doubtful (Q3)"}

EDIT_PY = ROOT / "submissions" / "v4h2g" / "skills" / "swe-tools" / "scripts" / "edit.py"
_SIDE = json.loads((Path(__file__).resolve().parent / "swegym_tools.json").read_text())
TOOLS, INSTALL = _SIDE["tools"], _SIDE["install"]
CMD_CAP, READ_LINES, READ_CHARS = 5000, 150, 10000
STAGE = "fixer"


def _load_edit_py():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_swegym_edit_py", EDIT_PY)
    mod = importlib.util.module_from_spec(spec)
    old, sys.dont_write_bytecode = sys.dont_write_bytecode, True      # never write a .pyc into submissions/
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    return mod


_PROTECTED = _load_edit_py().PROTECTED                                  # edit.py's own refuse list

SYSTEM_PROMPT = """You are the FIXER working in /workspace. Implement the change now.

Your first tool call is always `run_skill_script(skill_name="swe-tools", file_path="install.py")` (instant, safe to repeat; without it the edit helper does not exist). Helpers are never tool names. The ONLY correct call shape is run_command(command="python3 /tmp/swe/edit.py ...").
Rules: read code with `read_file(filepath, start_line, end_line)` and run shell commands such as `git grep` through `run_command`. Edit an existing file ONLY with `run_command`, as raw code with no escaping:
python3 /tmp/swe/edit.py path/to/file.py <<'EOF'
<<<<<<< SEARCH
exact current lines (copied as read, unique)
=======
new lines
>>>>>>> REPLACE
EOF
EOF appears once, as the last line. A broken edit is undone. Create a new file with `write_file(filepath, content)`.
Make the smallest complete source change. Never edit existing tests, conftest.py, pytest.ini, pyproject.toml, setup.cfg or tox.ini. The current code IS wrong: do not conclude that nothing needs changing.
When the change is done and verified, call `submit_patch()`.

Tools you can call: run_command, read_file, write_file, submit_patch, run_skill_script. There is no edit_file tool and no bash tool.


You are an agent. Your internal name is "fixer". The description about you is "Implements the fix.\""""

USER_TEMPLATE = """You are evaluating a software engineering task for repository {repo}.

Problem Statement:
{problem}

## Execution Environment Rules
- Command output limit: 5000 characters
- File view limit: 150 lines per read_file call
- File character limit: 10000 characters per read_file call
- Environment is offline (no network/PyPI access). All repository and test dependencies are ALREADY pre-installed. Do NOT attempt to run pip install or download packages.

## Instructions:
0. All source code is under `/workspace`. Do NOT search outside `/workspace` (e.g. `/usr/`, `/wheels/`, system site-packages). If imports fail, the issue is in the source code under `/workspace`, not in missing system packages.
1. Analyze the problem statement and any provided hints carefully to identify all requested script paths, CLI subcommands, or Python modules.
2. Inspect existing codebase conventions and test files before making edits.
3. Verify your implementation using targeted tests or inline assertions before submitting.
4. Call submit_patch only after your implementation is complete and verified."""

RESULT_HEAD = "EXECUTION RESULT of ["
BASH_TRAILER = re.compile(r"\[Python Interpreter: [^\]\n]*\]\nroot@[^\n:]*:(\S*) # ?\n\[Command finished with exit code (-?\d+)\]\s*$")
VIEW_HEAD = re.compile(r"^Here's the result of running `cat -n` on [^\n]*:\n")
DIR_HEAD = re.compile(r"^Here's the files and directories up to 2 levels deep in [^\n]*, excluding hidden items:\n?")
EDIT_HEAD = re.compile(r"^The file [^\n]* has been edited\. Here's the result of running `cat -n` on a snippet of [^\n]*:\n")
EDIT_TAIL = "\nReview the changes and make sure they are as expected. Edit the file again if necessary."
NUMLINE = re.compile(r"^\s*(\d+)(?:\t(.*))?$")
EDITOR_OK = {"view", "create", "str_replace"}


# ------------------------------------------------------------------------------------------------ parsing helpers
def decode_param(v: str) -> str:
    """OpenHands' text format wraps a multi-line value in one newline on each side."""
    if "\n" in v and len(v) >= 2 and v.startswith("\n") and v.endswith("\n"):
        return v[1:-1]
    return v


def parse_action(content):
    m = re.search(r"<function=([^>\s]+)>(.*?)</function>", content or "", re.S)
    if not m:
        return None
    params = {k: decode_param(v) for k, v in re.findall(r"<parameter=([^>\s]+)>(.*?)</parameter>", m.group(2), re.S)}
    return m.group(1), params


def header_info(messages):
    u = messages[1]["content"] if len(messages) > 1 else ""
    up = re.search(r"<uploaded_files>\s*(\S+)\s*</uploaded_files>", u)
    pr = re.search(r"<pr_description>\n?(.*?)\n?</pr_description>", u, re.S)
    if not up or not pr or not up.group(1).startswith("/workspace/"):
        return None, None
    return up.group(1).rstrip("/").split("/")[-1], pr.group(1)


def map_path(p, rd):
    """OpenHands absolute path -> repo-relative path in our sandbox (/workspace is the repo root), or None if outside."""
    p = (p or "").strip().rstrip("/")
    base = f"/workspace/{rd}"
    if p in (base, "/workspace"):
        return "."
    if p.startswith(base + "/"):
        return p[len(base) + 1:]
    if p.startswith("/workspace/"):          # OpenHands wrote next to the repo dir; in our sandbox that is the repo root
        return p[len("/workspace/"):]
    return None


def scrub(text, rd):
    return (text or "").replace(f"/workspace/{rd}", "/workspace")


def patch_files(patch):
    return re.findall(r"^diff --git a/(\S+) b/", patch or "", re.M)


def view_agrees(text, first, shown, clipped=False):
    """Do the cat -n lines OpenHands showed match `text`? The observation was right-stripped as a whole (the last line
    may lose trailing whitespace) and a clipped view ends mid-line."""
    have = text.expandtabs().split("\n")[first - 1:first - 1 + len(shown)]
    if len(have) != len(shown) or have[:-1] != shown[:-1]:
        return False
    if not shown:
        return True
    return have[-1].startswith(shown[-1]) if clipped else have[-1].rstrip() == shown[-1].rstrip()


def first_difference(text, first, shown):
    have = text.expandtabs().split("\n")[first - 1:first - 1 + len(shown)]
    for j, (a, b) in enumerate(zip(have, shown)):
        if a != b:
            return {"line": first + j, "file_text": a[:160], "shown_text": b[:160]}
    return {"line": None, "file_lines": len(have), "shown_lines": len(shown)}


def parse_numbered(body):
    """cat -n lines -> (first line number, [text...]); None if a line does not parse. Lines are as OpenHands showed
    them (tabs expanded)."""
    out, first = [], None
    for ln in body.split("\n"):
        m = NUMLINE.match(ln)
        if not m:
            return None
        n = int(m.group(1))
        if first is None:
            first = n
        elif n != first + len(out):
            return None
        out.append(m.group(2) or "")
    return first, out


# ------------------------------------------------------------------------------------------------ harness replicas
def harness_read_file(text, filepath, start_line=None, end_line=None):
    """swegemma/tools/workspace.py read_file on a file whose content is `text` (decoded with surrogateescape)."""
    content = text.encode("utf-8", "surrogateescape").decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    lines = content.splitlines()
    total = len(lines)
    if total == 0:
        return {"status": "ok", "filepath": filepath, "content": "", "start_line": 1, "end_line": 0, "total_lines": 0, "is_truncated": False}
    start = max(start_line if start_line is not None else 1, 1)
    end = min(end_line if end_line is not None else total, total)
    if start > end:
        return {"status": "error", "error_type": "ValueError", "error_message": f"start_line ({start}) cannot be greater than end_line ({end})", "details": {}}
    trunc = False
    if end - start + 1 > READ_LINES:
        end, trunc = start + READ_LINES - 1, True
    snippet = "\n".join(lines[start - 1:end])
    if len(snippet) > READ_CHARS:
        snippet, trunc = snippet[:READ_CHARS], True
    return {"status": "ok", "filepath": filepath, "content": snippet, "start_line": start, "end_line": end,
            "total_lines": total, "is_truncated": trunc}


def command_result(output, code):
    if code == 0:
        return {"status": "ok", "stdout": output[:CMD_CAP], "stderr": "", "exit_code": 0}
    return {"status": "error", "error_type": "CommandError", "error_message": output[:CMD_CAP],
            "details": {"stdout": output[:CMD_CAP], "stderr": "", "exit_code": code}}


def run_edit_py(rel, text, heredoc_lines):
    """Run the bundle's edit.py exactly as the harness would (cwd = repo root, stdin = the heredoc body) on a scratch copy
    holding `text`. -> (stdout, exit_code, new_text or None)."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(text.encode("utf-8", "surrogateescape"))
        p = subprocess.run([sys.executable, "-B", str(EDIT_PY), rel], cwd=d, input="\n".join(heredoc_lines).encode("utf-8", "surrogateescape") + b"\n",
                           capture_output=True, timeout=60, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        new = f.read_bytes().decode("utf-8", "surrogateescape") if f.exists() else None
        return p.stdout.decode("utf-8", "replace"), p.returncode, new


def edit_blocks(F, old, new):
    """OpenHands str_replace(old -> new) on F as whole-line SEARCH/REPLACE text, or None when old is not unique."""
    if not old or F.count(old) != 1:
        return None
    pos = F.index(old)
    end_excl = pos + len(old)
    N = F[:pos] + new + F[end_excl:]
    delta = len(new) - len(old)
    start = F.rfind("\n", 0, pos) + 1
    if F[end_excl - 1] == "\n" and new.endswith("\n"):
        span = end_excl - 1                          # old_str ends at a line break and so does new_str
    else:
        span = F.find("\n", end_excl)
        span = len(F) if span < 0 else span
    search, replace = F[start:span], N[start:span + delta]
    if F[:start] + search + F[span:] != F or N[:start] + replace + N[span + delta:] != N:
        return None
    return search, replace, N, F[:start].count("\n")


# ------------------------------------------------------------------------------------------------ conversion
@dataclass
class Conversion:
    status: str
    reason: str | None = None
    rows: list = field(default_factory=list)
    cut: str | None = None
    removed: Counter = field(default_factory=Counter)
    messages: list = field(default_factory=list)
    final_files: dict = field(default_factory=dict)
    capped_rows: int = 0                      # calls whose result our harness truncated (the teacher saw more)
    cut_detail: dict | None = None


def _drop(reason):
    return Conversion(status="dropped", reason=reason)


def precheck(messages, task, rd):
    """The whole-trajectory drop rules (actions our tools cannot express). -> reason or None."""
    if not any(f.endswith(".py") for f in patch_files(task.get("patch"))):
        return "non_python"
    finished = False
    for m in messages[2:]:
        if m["role"] != "assistant":
            continue
        act = parse_action(m["content"])
        if act is None:
            continue
        name, p = act
        if name == "finish":
            finished = True
            break
        if name == "execute_bash":
            cmd = p.get("command", "")
            if cmd.strip() in ("", "ctrl+c", "C-c") or str(p.get("is_input", "")).lower() == "true":
                return "bash_interactive"
            if "/testbed" in cmd:
                return "path_outside_workspace"
        elif name == "str_replace_editor":
            c = p.get("command")
            if c not in EDITOR_OK:
                return f"editor_{c}"
            rel = map_path(p.get("path"), rd)
            if rel is None:
                return "path_outside_workspace"
            if c == "str_replace" and _PROTECTED.search(rel):
                return "edit_protected_path"
        else:
            return f"tool_{name}"
    return None if finished else "no_finish"


PATH_TOKEN = re.compile(r"[\w.-]*/[\w./-]+|[\w-]+\.py\b")


def refs_of(name, args, search=None):
    """What a call points at that it could only know from earlier output: paths, and the lines an edit replaces."""
    if name == "read_file":
        return [args["filepath"]]
    if name == "run_command":
        r = [t.rstrip(".,:;)") for t in PATH_TOKEN.findall(args["command"])]
        return [t for t in r if len(t) > 3 and t not in ("/workspace", "/tmp/swe/edit.py")] + \
               [ln.strip() for ln in (search or []) if len(ln.strip()) > 3]
    return []


def convert(messages, task, files, strict_caps=False):
    """One OpenHands trajectory -> Conversion. `files(rel)` returns the file's text at base_commit, or None.

    strict_caps: cut right after any result our harness truncates. Default: show the truncated result, as the harness
    would, and cut only before a later call that refers to something (a path, a line it edits) that appeared solely in
    the truncated-away part."""
    rd, problem = header_info(messages)
    if rd is None:
        return _drop("bad_header")
    why = precheck(messages, task, rd)
    if why:
        return _drop(why)
    # our sandbox root IS the repo: collapse /workspace/<repo_dir> everywhere (commands, written content, observations)
    messages = messages[:2] + [dict(m, content=scrub(m["content"], rd)) for m in messages[2:]]

    hist = [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(repo=task["repo"], problem=problem)},
            {"role": "assistant", "tool_calls": [{"type": "function", "id": "swegym_c0",
                                                  "function": {"name": "run_skill_script", "arguments": INSTALL["arguments"]}}]},
            {"role": "tool", "tool_call_id": "swegym_c0", "content": INSTALL["result_content"]}]
    conv = Conversion(status="kept")
    vfs, cwd, k = {}, None, 0
    traj_id = f"swegym|{task['instance_id']}"
    seen, hidden = [problem], []              # text the model is shown / text only the teacher saw

    def depends(name, args, search=None):
        if not hidden:
            return False
        s, h = "\n".join(seen), "\n".join(hidden)
        return any(r in h and r not in s for r in refs_of(name, args, search))

    def text_of(rel):
        if rel not in vfs:
            vfs[rel] = files(rel)
        return vfs[rel]

    def emit(name, args, search=None):
        nonlocal k
        if depends(name, args, search):
            conv.cut = "depends_on_truncated"
            return None
        seen.extend(str(v) for v in args.values())
        k += 1
        call = {"type": "function", "id": f"swegym_c{k}", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
        body = {"messages": hist, "tools": TOOLS, "chat_template_kwargs": {"enable_thinking": False}}
        conv.rows.append({"prompt": render(body), "completion": canonical_completion({"tool_calls": [call]}, True),
                          "meta": {"task": task["instance_id"], "traj": traj_id, "stage": STAGE, "continuation": True, "tool": name}})
        hist.append({"role": "assistant", "tool_calls": [call]})
        return call["id"]

    def result(cid, payload, teacher_saw=None):
        content = json.dumps({"result": json.dumps(payload)}, ensure_ascii=False)
        hist.append({"role": "tool", "tool_call_id": cid, "content": content})
        shown = payload.get("stdout") or payload.get("content") or payload.get("error_message") or ""
        seen.append(shown)
        if teacher_saw is not None and teacher_saw != shown:
            hidden.append(teacher_saw)
            conv.capped_rows += 1
            if strict_caps:
                return True
        return False

    def stop(reason):
        conv.cut = reason

    i = 2
    while i < len(messages) and conv.cut is None:
        m = messages[i]
        if m["role"] != "assistant":
            if not m["content"].startswith(RESULT_HEAD):
                conv.removed["continue_nudge"] += 1
            i += 1
            continue
        act = parse_action(m["content"])
        obs_msg = messages[i + 1] if i + 1 < len(messages) and messages[i + 1]["role"] == "user" else None
        obs = obs_msg["content"] if obs_msg and obs_msg["content"].startswith(RESULT_HEAD) else None
        i += 1 + (obs is not None)
        if act is None:
            conv.removed["text_only"] += 1
            continue
        name, p = act
        if name == "finish":
            emit("submit_patch", {})
            break
        body = obs.split("\n", 1)[1] if obs and "\n" in obs else ""
        if obs is None or "[Error occurred in processing last action]" in body:
            conv.removed["runtime_error"] += 1
            continue

        if name == "execute_bash":
            cmd = p["command"]
            tm = BASH_TRAILER.search(body)
            if not tm:
                conv.removed["runtime_error"] += 1
                continue
            rest = body[:tm.start()].replace("\r\n", "\n")
            out = None
            for echo in (cmd.replace("\n", "\n> "), cmd):
                if rest == echo:
                    out = ""
                elif rest.startswith(echo + "\n"):
                    out = rest[len(echo) + 1:]
                if out is not None:
                    break
            if out is None:
                stop("bash_echo")
                break
            if cwd not in (None, "/workspace", f"/workspace/{rd}") and not cmd.lstrip().startswith("cd /"):
                stop("cwd_state")
                break
            out = scrub(out, rd)
            if out and not out.endswith("\n"):
                out += "\n"
            mapped = scrub(cmd, rd)
            if rd in mapped or rd in out:
                stop("repo_dir_leak")
                break
            cid = emit("run_command", {"command": mapped})
            if cid is None:
                break
            if result(cid, command_result(out, int(tm.group(2))), teacher_saw=out):
                stop("cap_run_command")
            cwd = tm.group(1)
            continue

        # str_replace_editor
        c, rel = p.get("command"), map_path(p.get("path"), rd)
        if body.startswith("ERROR:"):
            conv.removed["editor_error"] += 1
            continue
        if c == "create":
            text = p.get("file_text", "")
            cid = emit("write_file", {"filepath": rel, "content": text})
            if cid is None:
                break
            result(cid, {"status": "ok", "filepath": rel, "size": len(text)})
            vfs[rel] = text
            continue

        if c == "view" and DIR_HEAD.match(body):
            listing = [ln for ln in DIR_HEAD.sub("", body, 1).split("\n") if ln.strip()]
            if len(listing) <= 1:                        # OpenHands listed only the directory itself (symlinked root)
                conv.removed["empty_listing"] += 1
                continue
            target = "/workspace" if rel == "." else f"/workspace/{rel}"
            out = scrub("\n".join(listing), rd) + "\n"
            if rd in out:
                stop("repo_dir_leak")
                break
            cid = emit("run_command", {"command": f"find {target} -maxdepth 2 -not -path '*/\\.*'"})
            if cid is None:
                break
            if result(cid, command_result(out, 0), teacher_saw=out):
                stop("cap_run_command")
            continue

        if c == "view":
            vm = VIEW_HEAD.match(body)
            raw = body[vm.end():] if vm else None
            clipped = raw is not None and "<response clipped>" in raw
            if clipped:
                raw = raw[:raw.index("<response clipped>")]
            parsed = parse_numbered(raw.rstrip("\n")) if raw else None
            if parsed is None:
                stop("view_unparsed")
                break
            first, shown = parsed
            rng = json.loads(p["view_range"]) if p.get("view_range") else None
            args = {"filepath": rel}
            if rng:
                args["start_line"] = int(rng[0])
                if int(rng[1]) != -1:
                    args["end_line"] = int(rng[1])
            cur = text_of(rel)
            if not rng and not clipped and (cur is None or not view_agrees(cur, first, shown)):
                cur = vfs[rel] = "\n".join(shown)          # a complete full view is the ground truth (e.g. bash changed the file)
            cid = emit("read_file", args)
            if cid is None:
                break
            if cur is None:
                stop("unknown_file_state")
                break
            res = harness_read_file(cur, rel, args.get("start_line"), args.get("end_line"))
            if not view_agrees(cur, first, shown, clipped):
                result(cid, res)
                conv.cut_detail = {"file": rel, **first_difference(cur, first, shown)}
                stop("fs_divergence")
                break
            core = shown[:-1] if shown and shown[-1] == "" and first - 1 + len(shown) > res.get("total_lines", 0) else shown
            got = res.get("content", "").expandtabs().split("\n") if res["status"] == "ok" else []
            complete = not clipped and res["status"] == "ok" and len(got) >= len(core) and view_agrees("\n".join(got), 1, core)
            if result(cid, res, teacher_saw=None if complete else "\n".join(core)):
                stop("cap_read_file")
            continue

        # str_replace
        cur = text_of(rel)
        if cur is None:
            stop("unknown_file_state")
            break
        eb = edit_blocks(cur, p.get("old_str", ""), p.get("new_str", ""))
        if eb is None:
            conv.cut_detail = {"file": rel, "why": f"old_str occurs {cur.count(p.get('old_str', '')) if p.get('old_str') else 0} times"}
            stop("edit_mismatch")
            break
        search, replace, N, _ = eb
        em = EDIT_HEAD.match(body)
        snip = parse_numbered(body[em.end():].split(EDIT_TAIL)[0].rstrip("\n")) if em else None
        if snip is None or not view_agrees(N, snip[0], snip[1]):
            conv.cut_detail = {"file": rel, "edit_snippet": True, **(first_difference(N, *snip) if snip else {})}
            stop("fs_divergence")
            break
        lines = ["<<<<<<< SEARCH", *search.split("\n"), "=======", *replace.split("\n"), ">>>>>>> REPLACE"]
        if "EOF" in lines:
            conv.cut_detail = {"file": rel, "why": "a line EOF would end the heredoc"}
            stop("edit_mismatch")
            break
        out, code, new_text = run_edit_py(rel, cur, lines)
        if code != 0 or new_text != N:
            conv.cut_detail = {"file": rel, "why": f"edit.py exit {code}" if code else "edit.py result differs", "edit_py": out[:300]}
            stop("edit_mismatch")
            break
        cmd = f"python3 /tmp/swe/edit.py {rel} <<'EOF'\n" + "\n".join(lines) + "\nEOF"
        cid = emit("run_command", {"command": cmd}, search=search.split("\n"))
        if cid is None:
            break
        result(cid, command_result(out, 0))
        vfs[rel] = N

    conv.messages = hist
    conv.final_files = {k_: v for k_, v in vfs.items() if v is not None}
    if not conv.rows:
        conv.status, conv.reason = "dropped", "no_rows_before_cut"
    return conv


# ------------------------------------------------------------------------------------------------ dataset level
def edited_paths(messages, rd):
    out = set()
    for m in messages:
        if m["role"] == "assistant":
            a = parse_action(m["content"])
            if a and a[0] == "str_replace_editor" and a[1].get("command") in ("str_replace", "create"):
                r = map_path(a[1].get("path"), rd)
                if r:
                    out.add(r)
    return out


def match_tasks(trajs, tasks):
    """Each trajectory -> its SWE-Gym task (problem statement + repo dir), ties broken on the gold patch's files."""
    by_ps = {}
    for t in tasks:
        by_ps.setdefault(t["problem_statement"].strip(), []).append(t)
    out = []
    for msgs in trajs:
        rd, ps = header_info(msgs)
        cands = [t for t in by_ps.get((ps or "").strip(), [])
                 if rd and (rd == f"{t['repo'].replace('/', '__')}__{t['version']}" if t.get("version") else rd.startswith(t["repo"].replace("/", "__") + "__"))]
        if len(cands) > 1:
            ed = edited_paths(msgs, rd)
            cands.sort(key=lambda t: (-len(ed & set(patch_files(t.get("patch")))), t["instance_id"]))
        out.append(cands[0] if cands else None)
    return out


def build(trajs, tasks, files_for, tok=None, max_tokens=30000, exclude=frozenset(), strict_caps=False):
    matched = match_tasks(trajs, tasks)
    leaks = sorted({t["instance_id"] for t in matched if t and t["instance_id"] in exclude})
    if leaks:
        print(f"LEAK GUARD: SWE-Gym trajectories for excluded tasks {leaks[:5]}; refusing to build (exit 2)", file=sys.stderr)
        raise SystemExit(2)
    dropped, cut, removed, rows_dropped = Counter(), Counter(), Counter(), Counter()
    rows, seen, kept, per_traj, used_traj, capped = [], set(), 0, [], Counter(), 0
    for msgs, task in zip(trajs, matched):
        if task is None:
            dropped["no_task"] += 1
            continue
        conv = convert(msgs, task, files_for(task), strict_caps=strict_caps)
        removed.update(conv.removed)
        capped += conv.capped_rows
        if conv.status != "kept":
            dropped[conv.reason] += 1
            continue
        cut[conv.cut or "none (finished)"] += 1
        used_traj[task["instance_id"]] += 1
        suffix = "" if used_traj[task["instance_id"]] == 1 else f"#{used_traj[task['instance_id']]}"
        n = 0
        for r in conv.rows:
            r["meta"]["traj"] += suffix
            if tok is not None:
                ntok = len(tok.encode(r["prompt"], add_special_tokens=False).ids) + len(tok.encode(r["completion"], add_special_tokens=False).ids)
                if ntok > max_tokens:
                    rows_dropped["over_max_tokens"] += 1
                    continue
            h = hashlib.sha1((r["prompt"] + "\x00" + r["completion"]).encode("utf-8", "replace")).hexdigest()
            if h in seen:
                rows_dropped["duplicate"] += 1
                continue
            seen.add(h)
            rows.append(r)
            n += 1
        kept += n > 0
        per_traj.append(n)
    tool_mix = Counter(r["meta"]["tool"] for r in rows)
    report = {"source": SOURCE, "trajectories_in": len(trajs), "trajectories_with_rows": kept,
              "trajectories_dropped": dict(dropped.most_common()), "trajectories_converted_cut_reason": dict(cut.most_common()),
              "steps_removed": dict(removed.most_common()), "rows": len(rows), "rows_dropped": dict(rows_dropped),
              "max_tokens": max_tokens if tok is not None else None, "strict_caps": strict_caps,
              "results_truncated_by_harness_caps": capped,
              "rows_per_trajectory_p50_max": [sorted(per_traj)[len(per_traj) // 2] if per_traj else 0, max(per_traj or [0])],
              "tool_mix": dict(tool_mix.most_common()),
              "tool_share": {k: round(v / max(1, len(rows)), 3) for k, v in tool_mix.most_common()},
              "edit_py_sha256": hashlib.sha256(EDIT_PY.read_bytes()).hexdigest()}
    return rows, report


def write_rows(rows, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------------------------------------ I/O
def load_inputs(data_dir):
    import pyarrow.parquet as pq
    d = Path(data_dir)
    trajs = [r["messages"] for r in pq.read_table(d / "sft" / DATASET_FILE).to_pylist()]
    tasks = pq.read_table(d / "tasks" / TASKS_FILE, columns=["instance_id", "repo", "base_commit", "problem_statement", "patch", "version"]).to_pylist()
    return trajs, tasks


def src_path(data_dir, task, rel):
    return Path(data_dir) / "src" / task["repo"].replace("/", "__") / task["base_commit"] / rel


def files_reader(data_dir):
    def for_task(task):
        def read(rel):
            p = src_path(data_dir, task, rel)
            return p.read_bytes().decode("utf-8", "surrogateescape") if p.is_file() else None
        return read
    return for_task


def needed_files(trajs, tasks):
    need = set()
    for msgs, task in zip(trajs, match_tasks(trajs, tasks)):
        if task is None:
            continue
        rd, _ = header_info(msgs)
        for m in msgs:
            if m["role"] == "assistant":
                a = parse_action(m["content"])
                if a and a[0] == "str_replace_editor" and (a[1].get("path") or "").startswith(f"/workspace/{rd}/"):
                    need.add((task["repo"], task["base_commit"], map_path(a[1]["path"], rd)))
    return sorted(need)


def fetch(data_dir, min_free_gb=8):
    from huggingface_hub import hf_hub_download
    d = Path(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    probe = "/System/Volumes/Data" if os.path.exists("/System/Volumes/Data") else str(d)
    free = shutil.disk_usage(probe).free / 2**30
    if free < min_free_gb:
        print(f"only {free:.1f} GB free on {probe} (< {min_free_gb}); not downloading", file=sys.stderr)
        raise SystemExit(3)
    hf_hub_download(DATASET, DATASET_FILE, repo_type="dataset", revision=DATASET_REV, local_dir=d / "sft")
    hf_hub_download(TASKS, TASKS_FILE, repo_type="dataset", revision=TASKS_REV, local_dir=d / "tasks")
    trajs, tasks = load_inputs(d)
    need = needed_files(trajs, tasks)
    miss_path = d / "src" / "missing.json"
    missing = set(json.loads(miss_path.read_text())) if miss_path.exists() else set()

    def get(item):
        repo, commit, rel = item
        task = {"repo": repo, "base_commit": commit}
        dst, key = src_path(d, task, rel), f"{repo}@{commit}:{rel}"
        if dst.is_file() or key in missing:
            return "cached"
        url = f"https://raw.githubusercontent.com/{repo}/{commit}/{urllib.request.quote(rel)}"
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    data = r.read()
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
                return "fetched"
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return "missing:" + key
                if attempt == 3:
                    return "error:" + key
            except Exception:  # noqa: BLE001
                if attempt == 3:
                    return "error:" + key
        return "error:" + key

    stats = Counter()
    with cf.ThreadPoolExecutor(8) as ex:
        for r in ex.map(get, need):
            stats[r.split(":", 1)[0]] += 1
            if r.startswith("missing:"):
                missing.add(r.split(":", 1)[1])
    miss_path.parent.mkdir(parents=True, exist_ok=True)
    miss_path.write_text(json.dumps(sorted(missing), indent=0))
    print(json.dumps({"files_needed": len(need), **stats, "free_gb_before": round(free, 1)}))
    return 0 if not stats.get("error") else 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--data-dir", default=str(ROOT / "data" / "swegym"))
    c = sub.add_parser("convert")
    c.add_argument("--data-dir", default=str(ROOT / "data" / "swegym"))
    c.add_argument("--out", default=str(ROOT / "data" / "v11" / "rows_swegym.jsonl"))
    c.add_argument("--report", default=str(ROOT / "data" / "v11" / "rows_swegym_report.json"))
    c.add_argument("--max-tokens", type=int, default=30000)
    c.add_argument("--exclude-ids", action="append", default=[])
    c.add_argument("--strict-caps", action="store_true", help="cut right after any result the harness truncates")
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        return fetch(a.data_dir)
    from train.validate_rows import tokenizer, validate
    excl = set()
    for p in a.exclude_ids:
        excl |= {ln.strip() for ln in open(p) if ln.strip()}
    tok = tokenizer()
    if tok is None:
        print("Gemma tokenizer unavailable; refusing to guess token lengths", file=sys.stderr)
        return 1
    trajs, tasks = load_inputs(a.data_dir)
    rows, rep = build(trajs, tasks, files_reader(a.data_dir), tok=tok, max_tokens=a.max_tokens, exclude=frozenset(excl), strict_caps=a.strict_caps)
    write_rows(rows, a.out)
    v = validate(a.out, frozenset(excl), min_rows=1, max_tokens=a.max_tokens, tok=tok)
    rep["validate_rows"] = {k: v[k] for k in ("ok", "problems", "first_problems", "rows", "tasks", "rows_per_task", "stages", "tools",
                                             "continuation_rows", "prompt_tokens_p50_p90_max", "completion_tokens_p50_p90_max")}
    rep["token_length_check"] = "Gemma tokenizer (validate_rows.tokenizer, google/gemma-4-31b-it-qat-w4a16-ct)"
    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: rep[k] for k in ("trajectories_in", "trajectories_with_rows", "trajectories_dropped", "trajectories_converted_cut_reason",
                                          "steps_removed", "rows", "rows_dropped", "tool_mix")}, indent=1))
    print("validate_rows ok:", v["ok"], "problems:", v["problems"])
    return 0 if v["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
