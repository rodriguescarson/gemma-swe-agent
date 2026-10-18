"""A Harness² substrate for the competition's agent format: an ADK bundle (agent.yaml + prompts + skills) compiled by
adk_submission and served Gemma 4 31B (google-research/harness2 @ 1cfe254, Apache-2.0; its substrate interface is
harness2/substrate/base.py).

The editable surface keeps Harness²'s OpenCode file names, so its editor prompts apply unchanged:
  systemprompt.md, guardrails.md, LongTermMEMORY.md, tool_descriptions/tool_guidance.md   (always on, in that order)
  skills/<name>/SKILL.md and skills/<name>/scripts/*.py                                     (ADK skills, stdlib only)
compose_bundle() turns a tree into a bundle: the non-empty always-on files, in that order, become prompts/system.md; skills
become ADK skills declared on the agent. agent.yaml's model and tools, eval_config.yaml and configs/sampling.yaml are the base
bundle's and are not on the surface: the model is fixed by the rules and the 5-minute cap is the 12-hour gate (GAPS, 18 Oct).
Not supported by the competition's runtime, so rejected by validate_tree(): top-level scripts/ (the bundle is never on the
sandbox's disk), sub_agents/ and plugin/ (no OpenCode plugin layer in ADK)."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Mapping

from harness2.core import tree as HT
from harness2.core.tree import SurfaceSpec
from harness2.substrate.base import Install, RunRequest

ROOT = Path(__file__).resolve().parents[1]
BASE_BUNDLE = ROOT / "submissions" / "v12"
ALWAYS_ON = ("systemprompt.md", "guardrails.md", "LongTermMEMORY.md", "tool_descriptions/tool_guidance.md")
FIXED = ("agent.yaml", "eval_config.yaml", "configs/sampling.yaml")
SKILL_EXTS = (".md", ".py", ".txt", ".json")       # HARNESS_README allowed extensions, minus yaml/safetensors (not skills)
ALWAYS_ON_MAX = 16_000                             # chars: the prompt shares Gemma's 32k context; compaction fires at 14,336 tokens

ADK_SURFACE = SurfaceSpec(
    name="adk",
    always_on=ALWAYS_ON,
    always_on_max=ALWAYS_ON_MAX,
    always_on_cap_reason=(
        "the whole always-on text becomes the agent's system prompt, which shares Gemma 4's 32k-token context with the "
        "trajectory; the scorer compacts at 14,336 prompt tokens"
    ),
    skill_dir="skills",
    skill_name_rule="must_match",
    trigger_hint=(
        "Fix it by adding a trigger line naming `{name}` to systemprompt.md or guardrails.md, e.g. \"When <the situation this "
        "skill handles>, use the `{name}` skill: run_skill_script(skill_name=\\\"{name}\\\", file_path=\\\"<script>.py\\\").\""
    ),
    autotrigger_file="guardrails.md",
    trigger_line="- When {desc}, use the `{name}` skill (load_skill_resource / run_skill_script).\n",
    subagent_requires_mode=False,
    plugin_dir=None,
    hooks_file=None,
    compile_skill_scripts=True,
    reject_empty_always_on=True,
    stubs=(
        (
            "skills/README.md",
            "<!-- skills: ADK skills, loaded with load_skill_resource and run with run_skill_script(skill_name, file_path). "
            "Add one as skills/<name>/SKILL.md (frontmatter `name:` matching the directory and a `description:`) plus "
            "skills/<name>/scripts/<file>.py (Python stdlib only, offline). -->\n",
        ),
    ),
)


def fingerprint(tree: Mapping[str, str]) -> str:
    return hashlib.sha256(json.dumps(sorted(tree.items()), ensure_ascii=False).encode()).hexdigest()


def tree_problems(tree: Mapping[str, str]) -> list[str]:
    """Everything the competition's runtime cannot carry, as actionable lines (fed back to the editor as retry feedback)."""
    errs = []
    for rel in sorted(tree):
        if rel.startswith("scripts/"):
            errs.append(f"{rel}: top-level scripts are not available to the agent in this runtime; move it to "
                        f"skills/<name>/scripts/ and have the agent call run_skill_script(skill_name, file_path)")
        elif rel.startswith("sub_agents/"):
            errs.append(f"{rel}: sub-agents are not allowed in this harness (one agent, one context)")
        elif rel.startswith("plugin/"):
            errs.append(f"{rel}: plugins do not exist in this runtime")
        elif rel.startswith("skills/") and not rel.endswith(SKILL_EXTS):
            errs.append(f"{rel}: skill files must be one of {', '.join(SKILL_EXTS)}")
    body = always_on_text(tree)
    if not body.strip():
        errs.append("the always-on files are all empty; systemprompt.md must hold the agent's instructions")
    if len(body) > ALWAYS_ON_MAX:
        errs.append(f"the always-on text is {len(body)} chars, over the {ALWAYS_ON_MAX}-char cap; cut it")
    if "{" in body or "}" in body:
        errs.append("the always-on text contains a brace; ADK treats {name} as a template variable, so remove every { and }")
    return errs


def always_on_text(tree: Mapping[str, str]) -> str:
    return "\n\n".join(tree[a].strip() for a in ALWAYS_ON if tree.get(a, "").strip()) + "\n"


def skill_names(tree: Mapping[str, str]) -> list[str]:
    return sorted({rel.split("/")[1] for rel in tree if rel.startswith("skills/") and rel.count("/") >= 2
                   and rel.endswith("/SKILL.md")})


def compose_bundle(tree: Mapping[str, str], dest: Path, base: Path = BASE_BUNDLE) -> Path:
    """Write the bundle for `tree` into `dest`: base files + prompts/system.md + skills/. Raises ValueError on tree_problems."""
    errs = tree_problems(tree)
    if errs:
        raise ValueError("; ".join(errs))
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for rel in FIXED:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base / rel, dest / rel)
    (dest / "prompts").mkdir(exist_ok=True)
    (dest / "prompts" / "system.md").write_text(always_on_text(tree), encoding="utf-8")
    names = skill_names(tree)
    for rel, body in tree.items():
        if rel.startswith("skills/") and rel.split("/")[1] in names:
            p = dest / HT.normalize_rel(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
    if names:
        y = (dest / "agent.yaml").read_text(encoding="utf-8")
        if re.search(r"^skills:", y, re.M):
            raise ValueError("the base agent.yaml already declares skills; compose_bundle cannot merge them")
        (dest / "agent.yaml").write_text(y.rstrip("\n") + "\nskills: [" + ", ".join(f"skills/{n}" for n in names) + "]\n",
                                         encoding="utf-8")
    return dest


def validate_bundle(bundle: Path) -> str:
    """scripts/validate.py on the composed bundle (the official compiler); returns its stdout, raises ValueError on failure."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(bundle)], capture_output=True, text=True,
                       timeout=300)
    if r.returncode != 0 or "OK model=" not in r.stdout:
        raise ValueError("the composed bundle does not compile: " + (r.stderr or r.stdout)[-1500:])
    return r.stdout


_TRUNC = "…(+{n} chars — render truncation)"


def _clip(s, n: int) -> str:
    s = "" if s is None else str(s).replace("\x00", "")
    return s if n <= 0 or len(s) <= n else s[:n] + _TRUNC.format(n=len(s) - n)


def _observation(obs) -> tuple[str, str]:
    """(tag, text) for one ATIF observation: the harness wraps each tool result as {"content": "<json>"}."""
    raw = obs.get("content") if isinstance(obs, dict) else obs
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        d = raw
    if isinstance(d, dict):
        if d.get("status") == "error":
            det = d.get("details") or {}
            out = "\n".join(x for x in (d.get("error_message"), det.get("stdout"), det.get("stderr")) if x)
            return "OBSERVATION ERROR", out or json.dumps(d)
        parts = [d.get(k) for k in ("stdout", "stderr", "content", "output", "result") if d.get(k)]
        return "OBSERVATION", "\n".join(str(p) for p in parts) if parts else json.dumps(d, ensure_ascii=False)
    return "OBSERVATION", "" if d is None else str(d)


def render_atif(path: Path, *, obs_trunc: int, max_chars: int, args_trunc: int = 400) -> str:
    """Render the harness's ATIF trace (traces/trace_<id>.json) into Harness²'s shared grammar:
    [THINKING] / [ASSISTANT] text, [ACTION] tool(args), [OBSERVATION] / [OBSERVATION ERROR] result, [ERROR]."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as e:
        return f"(failed to read trajectory: {e})"
    lines = []
    for s in d.get("steps") or []:
        if s.get("source") != "agent":
            continue
        ex = s.get("extra") if isinstance(s.get("extra"), dict) else {}
        msg = s.get("message")
        if isinstance(msg, str) and msg.strip():
            lines.append(f"[{'THINKING' if ex.get('event_type') == 'thinking' else 'ASSISTANT'}] {_clip(msg, obs_trunc)}")
        for c in s.get("tool_calls") or []:
            args = json.dumps(c.get("arguments"), ensure_ascii=False, default=str)
            lines.append(f"[ACTION] {c.get('function_name') or 'tool'}({_clip(args, args_trunc)})")
        if s.get("observation") is not None:
            tag, text = _observation(s["observation"])
            lines.append(f"[{tag}] {_clip(text, obs_trunc)}")
        if ex.get("error"):
            lines.append(f"[ERROR] {_clip(ex['error'], 300)}")
    out = "\n".join(lines).strip() or "(no parseable events in trajectory)"
    return out if len(out) <= max_chars else out[:max_chars] + "\n" + _TRUNC.format(n=len(out) - max_chars)


Launcher = Callable[[RunRequest, Install], list]


class AdkSubstrate:
    """harness2.substrate.base.Substrate for an ADK bundle. The benchmark adapter supplies the launcher (it owns where and how
    rollouts run: on the A6000 box, through the pace proxy, in the faithful Docker sandbox)."""

    name = "adk"

    def __init__(self, launcher: Launcher | None = None, base: Path = BASE_BUNDLE):
        self._launcher = launcher
        self.base = Path(base)

    def surface(self) -> SurfaceSpec:
        return ADK_SURFACE

    def materialise(self, tree_dir: Path, spec, ctx: Mapping[str, str]) -> Install:
        tree = HT.read_tree(ADK_SURFACE, tree_dir)
        staged = Path(tempfile.mkdtemp(prefix="h2g4-bundle-"))
        try:
            compose_bundle(tree, staged, self.base)
        except Exception:
            shutil.rmtree(staged, ignore_errors=True)
            raise
        return Install(staging_dir=staged, fingerprint=fingerprint(tree))

    def execute(self, task_ref: str, install: Install, run_ids: list[str], timeout: int) -> list:
        if self._launcher is None:
            raise RuntimeError("AdkSubstrate was built without a launcher; the benchmark adapter must supply one")
        return self._launcher(RunRequest(task_ref=task_ref, run_ids=tuple(run_ids), timeout=int(timeout)), install)

    def read_trajectory(self, stream_path: Path, *, obs_trunc: int, max_chars: int, args_trunc: int = 400) -> str:
        return render_atif(Path(stream_path), obs_trunc=obs_trunc, max_chars=max_chars, args_trunc=args_trunc)

    def preflight(self) -> None:
        missing = [r for r in FIXED if not (self.base / r).is_file()]
        if missing:
            raise RuntimeError(f"base bundle {self.base} is missing {missing}")


# The improver prompts need a description of this surface (harness2.core.prompts._SURFACE_TEXTS); register it on import, so
# any code that uses ADK_SURFACE also has its prompt text (box B-203, 2026-10-18).
from .prompts_adk import register as _register_prompt_surface  # noqa: E402

_register_prompt_surface()
