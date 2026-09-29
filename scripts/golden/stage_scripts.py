"""Scripted neighbours of a single-stage golden run (docs/eval/GOLDEN_EVALS_SPEC.md v1.1, 5.3, 5.4 step 2, 5.9).

Every function here is pure: it turns a dataset case (its ``golden`` block, section 4.6) into the per-agent step lists the
router (router.py) answers with. Steps use the ``tests/v10_support/mock_llm.py`` syntax: ``{"tool": name, "args": {...}}``,
``{"text": "..."}`` or a reactive ``callable(Request) -> step``.

    L          setup: install, CLOCK(t0), READY | locator LIVE | fixer CHANGED: nothing | verifier submit | submitter submit
    F          setup: install, READY | locator LOCATE, REPRO?, CLOCK(t0), PLAN | fixer LIVE | verifier submit | submitter submit
    V gold/wrong  ... | locator LOCATE, REPRO?, PLAN | fixer replay..., VERIFY, CLOCK(t0), NOTES | verifier LIVE | submitter submit
    V empty    ... | fixer VERIFY, CLOCK(t0), NOTES | ...

PLAN and NOTES scan EVERY tool result of the request (newest first): CLOCK is the pre-stage's last tool call, so the last
result is always the clock write (v1 defect, gotcha 15).

scripts/golden is not a package: this file puts its own directory and ROOT/tests on sys.path.
"""
from __future__ import annotations

import base64
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(HERE), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from v10_support.mock_llm import Request, cmd, heredoc, skill, submit, text  # noqa: E402

STAGES = ("setup", "locator", "fixer", "verifier", "submitter")
LIVE_AGENT = {"L": "locator", "F": "fixer", "V": "verifier"}
T0_DEFAULT = {"L": 2, "F": 47, "V": 91}            # section 4.5, measured 2026-09-29; the dataset carries the real value
CAP_S = 300                                          # the task stops at helper t=300
PRE_S_DEFAULT = 150                                  # section 5.4 step 4

SWE = "/tmp/swe"
VERIFY_CMD = f"python3 {SWE}/verify.py"
REPRO_CMD = f"python3 {SWE}/verify.py --repro-only"
VERIFY = cmd(VERIFY_CMD)
STATUS = cmd(f"python3 {SWE}/status.py")
FINALIZE = cmd(f"python3 {SWE}/finalize.py")
INSTALL = skill("install.py")
REWRITTEN = ("/tmp", "/workspace", "/wheels", "/usr/local/bin")   # rewritten by the subprocess sandbox in command text
MARKER = re.compile(r"^\s*(<{5,9} ?SEARCH|={5,9}|>{5,9} ?REPLACE)\s*$", re.I)   # tasks._MARKER (edit.py SEARCH/REPLACE)


# ------------------------------------------------------------------------------------------------------------ helpers
def live_agent(suite: str) -> str:
    try:
        return LIVE_AGENT[suite]
    except KeyError:
        raise ValueError(f"unknown suite {suite!r} (L, F or V)") from None


def clock_cmd(t: float, scale: float = 1.0) -> str:
    """CLOCK(t): write $SWE/t0 so the helper clock reads t now (5.4 step 2). /tmp is rewritten to <sandbox>/tmp."""
    if not scale or scale <= 0:
        raise ValueError(f"scale must be > 0, got {scale!r}")
    return "python3 -c \"import time;open('/tmp/swe/t0','w').write(repr(time.time()-%r))\"" % (t / scale)


def clock_step(t: float, scale: float = 1.0) -> dict:
    return cmd(clock_cmd(t, scale))


def safe_title(title_words: str) -> str:
    """Title words for a double-quoted shell argument: quotes, backticks, $ and backslashes removed (they would be
    shell syntax inside "..."), whitespace collapsed."""
    s = re.sub(r"[\"`$\\]", "", title_words or "")
    return " ".join(s.split())[:80] or "issue"


def locate_step(title_words: str) -> dict:
    return cmd(f'python3 {SWE}/locate.py "{safe_title(title_words)}"')


def repro_step(repro: str | None) -> dict | None:
    return heredoc(REPRO_CMD, repro) if repro else None


def tool_text(raw: str) -> str:
    """The human text of one tool result as the model receives it: run_command / run_skill_script replies are JSON
    (sometimes JSON inside a JSON string); stdout and stderr are joined. Falls back to the raw text."""
    obj: Any = raw
    for _ in range(6):          # ADK/LiteLLM send '{"result": "<the tool's JSON reply as a string>"}'
        if isinstance(obj, str):
            s = obj.strip()
            if not s.startswith(("{", "[", '"')):
                break
            try:
                obj = json.loads(s)
            except (ValueError, TypeError):
                break
        elif isinstance(obj, dict) and "stdout" not in obj and isinstance(obj.get("result"), (str, dict)):
            obj = obj["result"]
        else:
            break
    if isinstance(obj, dict):
        parts = [str(obj.get(k) or "") for k in ("stdout", "stderr", "output", "result", "content") if obj.get(k)]
        return "\n".join(parts) if parts else json.dumps(obj)
    if isinstance(obj, str):
        return obj
    return str(raw)


def _call_commands(req: Request) -> dict:
    """tool_call_id -> the run_command command (or '' for other tools) over every assistant message of the request."""
    out = {}
    for m in req.messages:
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments") or ""
            try:
                a = json.loads(args) if isinstance(args, str) else dict(args)
            except (ValueError, TypeError):
                a = {}
            out[tc.get("id")] = str(a.get("command") or "") if isinstance(a, dict) else ""
    return out


def _tool_messages(req: Request) -> list:
    return [m for m in req.messages if m.get("role") == "tool"]


def repro_status(req: Request) -> str:
    """'fails on original' when the --repro-only result (found by scanning ALL tool results, newest first) says fails or
    hangs on original, else 'none'. The result is identified by its call's command; without call ids (a compacted
    request), by the first result that carries a 'REPRO:' line."""
    calls = _call_commands(req)
    msgs = _tool_messages(req)
    for m in reversed(msgs):
        if "--repro-only" in calls.get(m.get("tool_call_id"), ""):
            body = tool_text(m.get("content") if isinstance(m.get("content"), str) else json.dumps(m.get("content")))
            return "fails on original" if ("fails on original" in body or "hangs on original" in body) else "none"
    for raw in reversed(req.tool_results()):
        body = tool_text(raw)
        if re.search(r"^REPRO:", body, re.M):
            return "fails on original" if ("fails on original" in body or "hangs on original" in body) else "none"
    return "none"


def verify_line(req: Request) -> str:
    """The first line starting with 'VERIFY:' in the newest tool result that has one, else 'not run'."""
    for raw in reversed(req.tool_results()):
        for line in tool_text(raw).splitlines():
            if line.startswith("VERIFY:"):
                return line.strip()
    return "not run"


def set_repro_line(plan: str, status: str) -> str:
    line = f"REPRO: {status}"
    if re.search(r"^REPRO:.*$", plan, re.M):
        return re.sub(r"^REPRO:.*$", line, plan, count=1, flags=re.M)
    if re.search(r"^TESTS:", plan, re.M):
        return re.sub(r"^(TESTS:)", line + "\n\\1", plan, count=1, flags=re.M)
    return plan.rstrip("\n") + "\n" + line


def plan_step(plan: str) -> Callable[[Request], dict]:
    """PLAN: the golden plan with its REPRO line set from the real --repro-only result of this request."""
    def step(req: Request) -> dict:
        return text(set_repro_line(plan, repro_status(req)))
    step.__name__ = "PLAN"
    return step


def notes_step(notes_changed: str) -> Callable[[Request], dict]:
    """NOTES: notes_changed + '\\nVERIFY: ' + the newest VERIFY line (or 'not run')."""
    def step(req: Request) -> dict:
        return text((notes_changed or "CHANGED: nothing") + "\nVERIFY: " + verify_line(req))
    step.__name__ = "NOTES"
    return step


# ---------------------------------------------------------------------------------------------------- patch replays
def _parse(patch: str) -> list:
    from v10_support import tasks as T   # lazy: tasks imports pytest
    return T.parse_patch(patch)


def git_apply_step(patch: str) -> dict:
    """One run_command that pipes the base64-encoded patch into git apply (the sandbox rewrites /tmp, /workspace, ...
    in command text; base64 keeps the rewrite away from the patch)."""
    body = patch if patch.endswith("\n") else patch + "\n"
    b64 = base64.b64encode(body.encode("utf-8", "surrogateescape")).decode()
    return cmd("python3 -c \"import base64,subprocess,sys;sys.exit(subprocess.run(['git','apply','--whitespace=nowarn',"
               f"'-'],input=base64.b64decode('{b64}')).returncode)\"")


def edit_fallback_reason(patch: str) -> str | None:
    """Why edit.py cannot replay this patch (section 4.4), or None."""
    if not patch.strip():
        return "empty patch"
    if "GIT binary patch" in patch or re.search(r"^Binary files ", patch, re.M):
        return "binary"
    files = _parse(patch)
    if not files or not any(fp.path for fp in files):
        return "no file sections"
    for fp in files:
        if fp.deleted:
            return f"deletes {fp.old_path or fp.path}"
        if fp.old_path and not fp.new_file and fp.old_path not in ("/dev/null", fp.path):
            return f"renames {fp.old_path}"
        if not fp.hunks:
            return f"mode-only or empty section {fp.path}"
        for h in fp.hunks:
            raw = "".join(h.lines)
            for s in REWRITTEN:
                if s in raw:
                    return f"hunk text contains {s} (rewritten by the sandbox)"
            for line in h.new_lines:
                if line.rstrip("\r\n") == "EOF":
                    return "a new-side line is EOF (ends the heredoc)"
                if MARKER.match(line.rstrip("\r\n")):
                    return "a new-side line matches the SEARCH/REPLACE marker"
    return None


def edit_steps(patch: str) -> list:
    """One edit.py run_command per hunk, bottom-up per file: --create, --insert-after N, --lines A-B [--delete]."""
    steps = []
    for fp in _parse(patch):
        path = shlex.quote(fp.path)
        if fp.new_file:
            body = "".join(fp.hunks[0].new_lines) if fp.hunks else ""
            steps.append(heredoc(f"python3 {SWE}/edit.py {path} --create", body))
            continue
        for h in sorted(fp.hunks, key=lambda x: -x.old_start):
            new = h.new_lines
            if h.old_len == 0:
                steps.append(heredoc(f"python3 {SWE}/edit.py {path} --insert-after {h.old_start}", "".join(new)))
            elif not new:
                steps.append(cmd(f"python3 {SWE}/edit.py {path} --lines {h.old_start}-{h.old_start + h.old_len - 1} "
                                 "--delete"))
            else:
                steps.append(heredoc(f"python3 {SWE}/edit.py {path} --lines {h.old_start}-{h.old_start + h.old_len - 1}",
                                     "".join(new)))
    return steps


def replay_steps(patch: str, mode: str = "edit") -> tuple:
    """(steps, mode used, fallback reason) that rebuild `patch` through the real tools."""
    if not (patch or "").strip():
        return [], "none", "empty patch"
    why = None if mode == "git_apply" else edit_fallback_reason(patch)
    if mode == "git_apply" or why:
        return [git_apply_step(patch)], "git_apply", why or "requested"
    return edit_steps(patch), "edit", None


def patch_paths(patch: str) -> tuple:
    """(paths that exist at the baseline, paths the patch creates)."""
    existing, created = [], []
    for fp in _parse(patch or ""):
        if not fp.path:
            continue
        (created if fp.new_file else existing).append(fp.path)
    return existing, created


def revert_cmd(patch: str) -> str | None:
    """The oracle's revert of a recorded tree patch (5.9): checkout the baseline copies, remove created files."""
    existing, created = patch_paths(patch)
    parts = ["cd /workspace"]
    if existing:
        parts.append("git checkout -q _swegemma_baseline -- " + " ".join(shlex.quote(p) for p in existing))
    if created:
        parts.append("rm -f -- " + " ".join(shlex.quote(p) for p in created))
    return " && ".join(parts) if len(parts) > 1 else None


def changed_line(patch: str) -> str:
    files = [fp.path for fp in _parse(patch or "") if fp.path]
    return "CHANGED: " + ("; ".join(files) if files else "nothing")


# ------------------------------------------------------------------------------------------------------ the scripts
def _g(case: dict) -> dict:
    return case.get("golden") or case


def case_t0(case: dict) -> float:
    g = _g(case)
    t0 = g.get("t0")
    return float(T0_DEFAULT[g["suite"]] if t0 is None else t0)


def case_pre_s(case: dict) -> float:
    v = _g(case).get("pre_s")
    return float(PRE_S_DEFAULT if v is None else v)


def gold_patch(case: dict) -> str:
    """The gold patch: the F/V reference text, else golden.gold_patch (tests), else ''."""
    g = _g(case)
    if g.get("gold_patch"):
        return g["gold_patch"]
    if g.get("suite") in ("F", "V"):
        ref = ((case.get("reference") or {}).get("response") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in ref if isinstance(p, dict))
    return ""


def neighbour_scripts(case: dict, scale: float = 1.0) -> dict:
    """{agent: [steps]} for the scripted stages of one case (the live agent is absent)."""
    g = _g(case)
    suite = g["suite"]
    live = live_agent(suite)
    t0 = case_t0(case)
    clock = clock_step(t0, scale)
    rep = repro_step(g.get("repro"))
    loc_pre = [locate_step(g.get("title_words") or "")] + ([rep] if rep else [])
    tail_verifier = [submit(), text("Submitted.")]
    tail_submitter = [submit(), text("submitted")]
    s: dict = {"setup": [INSTALL, text("READY")]}
    if suite == "L":
        s["setup"] = [INSTALL, clock, text("READY")]
        s["fixer"] = [text("CHANGED: nothing")]
        s["verifier"] = tail_verifier
    elif suite == "F":
        s["locator"] = loc_pre + [clock, plan_step(g.get("plan") or "")]
        s["verifier"] = tail_verifier
    else:
        variant = g.get("variant") or "gold"
        s["locator"] = loc_pre + [plan_step(g.get("plan") or "")]
        steps = [] if variant == "empty" else [dict(x) for x in (g.get("replay_steps") or [])]
        s["fixer"] = steps + [VERIFY, clock, notes_step(g.get("notes_changed") or "CHANGED: nothing")]
    s["submitter"] = tail_submitter
    s.pop(live, None)
    return s


def gold_replay(case: dict) -> list:
    """The GOLD patch replayed through the tools (the V gold tree's validated steps when the case carries them)."""
    g = _g(case)
    if g.get("suite") == "V" and g.get("tree_source") == "gold" and g.get("replay_steps"):
        return [dict(x) for x in g["replay_steps"]]
    steps, _, _ = replay_steps(gold_patch(case), g.get("oracle_replay") or "edit")
    return steps


def oracle_script(case: dict) -> list:
    """The live stage's oracle answers (5.9)."""
    g = _g(case)
    suite = g["suite"]
    if suite == "L":
        rep = repro_step(g.get("repro"))
        return ([rep] if rep else []) + [plan_step(g.get("plan") or "")]
    if suite == "F":
        return gold_replay(case) + [VERIFY, notes_step(changed_line(gold_patch(case)))]
    variant = g.get("variant") or "gold"
    end = [VERIFY, FINALIZE, submit(), text("Submitted.")]
    if variant == "gold":
        return [STATUS] + end
    if variant == "wrong":
        rv = revert_cmd(g.get("tree_patch") or "")
        return ([cmd(rv)] if rv else []) + gold_replay(case) + end
    return gold_replay(case) + end


def null_script(case: dict) -> list:
    return []          # every live request -> text("done")


def describe(step: Any) -> str:
    """A short label for logs and tests: the tool and command head, 'text', or the reactive step's name."""
    if callable(step):
        return getattr(step, "__name__", "reactive")
    if "text" in step:
        return "text"
    a = step.get("args") or {}
    return f"{step.get('tool')}:{str(a.get('command') or a.get('file_path') or '')[:60]}"
