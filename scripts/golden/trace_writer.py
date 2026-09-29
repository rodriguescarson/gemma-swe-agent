"""ATIF-v1.7 harness traces -> agents-cli GRADING-INPUT trace cases (docs/eval/GOLDEN_EVALS_SPEC.md v1.1, 6.2).

One trace case per case sample:

    {"eval_case_id", "responses": [{"response": <the live stage's final text>}], "reference": <from the dataset>,
     "agent_data": {"agents": {...}, "turns": [{"turn_index", "events": [{"author", "content"}]}]},
     "golden": {<dataset golden block> + case_id, sample, live_agents, status, final_patch, run, llm_calls,
                exec_checks, writer_warnings}}

Mapping (ATIF step -> events):
- source user (the harness task prompt): the first opens turn 0 as a ``user`` text event; a later one, or a harness
  ``continuation_nudge`` record, opens a new turn;
- source agent with tool_calls: one ``model`` event with one function_call part per call (author = the call's
  extra.author), then one ``user``-role event by the same author with the function_response of the step's
  observation (the observation JSON parsed to a dict, else ``{"result": text}``). A later ``source: system`` step
  with an observation answers the next pending call of that step (multi-call steps, fastapi_14492);
- source agent text (final / text / no event_type): a ``model`` text event; ``thinking`` text is dropped (ADK never
  shows thoughts to later calls) and counted in writer_warnings, while its tool calls are kept;
- ``compaction`` records are dropped (counted): a summary event inside the live stage would split its stage-run;
- anything else: a ``user`` text event prefixed ``[<source>] `` plus a writer warning.
There is NO ``prompt`` field (the skill: never mix prompt with agent_data) and ``responses[0]`` is always present:
agents-cli fails every local metric of a case without it (gotcha 1).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(HERE), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SKILL_TOOLS = ("list_skills", "load_skill", "load_skill_resource", "run_skill_script")


# ------------------------------------------------------------------------------------------------------ the bundle
def _yaml_load(path: Path) -> dict:
    """yaml with the bundle's ``!include`` tag resolved to the included file's text (or a path marker)."""
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    def include(loader, node):
        rel = loader.construct_scalar(node)
        return {"__include__": str((path.parent / rel).resolve())}
    Loader.add_constructor("!include", include)
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=Loader) or {}


def bundle_agents(bundle: Path) -> list:
    """[(name, sub-agent dict with instruction text and gen config)] in pipeline order."""
    bundle = Path(bundle)
    root = _yaml_load(bundle / "agent.yaml")
    out = []
    for sa in root.get("sub_agents") or []:
        p = bundle / sa["config_path"]
        d = _yaml_load(p)
        ins = d.get("instruction")
        if isinstance(ins, dict) and "__include__" in ins:
            d["instruction"] = Path(ins["__include__"]).read_text(encoding="utf-8")
        gen = d.get("generate_content_config")
        if isinstance(gen, dict) and "__include__" in gen:
            import yaml
            d["generate_content_config"] = yaml.safe_load(Path(gen["__include__"]).read_text(encoding="utf-8")) or {}
        out.append((d.get("name"), d))
    return out


def max_output_tokens(bundle: Path) -> dict:
    return {n: int((d.get("generate_content_config") or {}).get("max_output_tokens") or 0)
            for n, d in bundle_agents(bundle)}


def agents_map(bundle: Path, tools_seen: dict | None = None) -> dict:
    """agent_data.agents: id, type, instruction (the raw prompt file), tool declarations (names). ``tools_seen``
    ({agent: [names]} from the router log's first request per agent) wins over the yaml list."""
    out = {}
    for name, d in bundle_agents(bundle):
        names = list((tools_seen or {}).get(name) or [])
        if not names:
            names = list(d.get("tools") or []) + (list(SKILL_TOOLS) if d.get("skills") else [])
        out[name] = {"agent_id": name, "agent_type": "LlmAgent", "instruction": d.get("instruction") or "",
                     "tools": [{"function_declarations": [{"name": n} for n in names if n]}]}
    return out


# ----------------------------------------------------------------------------------------------------- the mapping
def _content_text(obs: Any) -> str:
    if isinstance(obs, dict):
        return str(obs.get("content") if obs.get("content") is not None else "")
    return "" if obs is None else str(obs)


def parse_response(text: str) -> dict:
    try:
        v = json.loads(text)
    except (ValueError, TypeError):
        return {"result": text}
    return v if isinstance(v, dict) else {"result": text}


def _author(step: dict, tc: dict | None = None) -> str | None:
    if tc is not None:
        a = (tc.get("extra") or {}).get("author")
        if a:
            return a
    a = (step.get("extra") or {}).get("author")
    if a:
        return a
    tcs = step.get("tool_calls") or []
    return ((tcs[0].get("extra") or {}).get("author")) if tcs else None


def atif_to_agent_data(atif: dict, agents: dict) -> tuple:
    """(agent_data, writer_warnings)."""
    agents = {k: dict(v) for k, v in agents.items()}
    turns: list = []
    warnings: list = []
    pending: list = []            # [(author, call name)] of calls still waiting for a response
    counts: dict = {}

    def warn(kind: str) -> None:
        counts[kind] = counts.get(kind, 0) + 1

    def author_ok(a: str | None) -> str:
        if a in agents:
            return a
        a = a or "unknown_agent"
        agents[a] = {"agent_id": a, "agent_type": "LlmAgent", "instruction": "",
                     "tools": [{"function_declarations": []}]}
        warn(f"unknown_author:{a}")
        return a

    def new_turn() -> list:
        turns.append({"turn_index": len(turns), "events": []})
        return turns[-1]["events"]

    def cur() -> list:
        return turns[-1]["events"] if turns else new_turn()

    seen_user = False
    for s in atif.get("steps") or []:
        src = s.get("source")
        ex = s.get("extra") or {}
        et = ex.get("event_type")
        msg = s.get("message")
        if src == "user" or et == "continuation_nudge":
            ev = new_turn() if (seen_user or (turns and turns[-1]["events"])) else cur()
            seen_user = True
            ev.append({"author": "user", "content": {"role": "user", "parts": [{"text": str(msg or "")}]}})
            continue
        if et == "compaction":
            warn("compaction_dropped")
            continue
        if src == "agent":
            tcs = s.get("tool_calls") or []
            if msg is not None and str(msg) != "":
                if et == "thinking":
                    warn("thinking_dropped")
                else:
                    a = author_ok(_author(s))
                    cur().append({"author": a, "content": {"role": "model", "parts": [{"text": str(msg)}]}})
            if tcs:
                a = author_ok(_author(s, tcs[0]))
                parts = []
                for tc in tcs:
                    args = tc.get("arguments")
                    parts.append({"function_call": {"name": tc.get("function_name") or "",
                                                    "args": args if isinstance(args, dict) else {"_raw": args}}})
                cur().append({"author": a, "content": {"role": "model", "parts": parts}})
                pending = [(author_ok(_author(s, tc)), tc.get("function_name") or "") for tc in tcs]
                obs = s.get("observation")
                if obs is not None:
                    pa, name = pending.pop(0)
                    cur().append({"author": pa, "content": {"role": "user", "parts": [
                        {"function_response": {"name": name, "response": parse_response(_content_text(obs))}}]}})
            elif msg is None or str(msg) == "":
                warn("empty_agent_step")
            continue
        if src == "system" and s.get("observation") is not None:
            obs = s["observation"]
            if pending:
                pa, name = pending.pop(0)
            else:
                name = (obs.get("extra") or {}).get("tool_name", "") if isinstance(obs, dict) else ""
                pa = author_ok((obs.get("extra") or {}).get("author") if isinstance(obs, dict) else None)
                warn("unpaired_observation")
            cur().append({"author": pa, "content": {"role": "user", "parts": [
                {"function_response": {"name": name, "response": parse_response(_content_text(obs))}}]}})
            continue
        cur().append({"author": "user", "content": {"role": "user", "parts": [{"text": f"[{src}] {msg or ''}"}]}})
        warn(f"other_step:{src}:{et}")
    for k in sorted(counts):
        warnings.append(f"{k}={counts[k]}")
    return {"agents": agents, "turns": turns}, warnings


def events(agent_data: dict) -> list:
    return [e for t in agent_data.get("turns") or [] for e in t.get("events") or []]


def first_stage_run(agent_data: dict, agent: str) -> list:
    """The events of the agent's first stage-run (a maximal run of consecutive events by that author)."""
    out, started = [], False
    for e in events(agent_data):
        if e.get("author") == agent:
            out.append(e)
            started = True
        elif started:
            break
    return out


def is_text_event(e: dict) -> bool:
    c = e.get("content") or {}
    return c.get("role") == "model" and any("text" in p for p in c.get("parts") or [])


def event_text(e: dict) -> str:
    return "".join(p.get("text", "") for p in (e.get("content") or {}).get("parts") or [] if "text" in p)


def live_final_text(agent_data: dict, live: str) -> str:
    texts = [event_text(e) for e in first_stage_run(agent_data, live) if is_text_event(e)]
    return texts[-1] if texts else ""


def repro_text_of(agent_data: dict, live: str) -> str | None:
    """The body of the live agent's last `verify.py --repro-only` heredoc in its first stage-run (L, 6.3)."""
    from checks import repro_body
    body = None
    for e in first_stage_run(agent_data, live):
        for p in (e.get("content") or {}).get("parts") or []:
            fc = p.get("function_call")
            if fc and fc.get("name") == "run_command":
                b = repro_body(str((fc.get("args") or {}).get("command") or ""))
                if b is not None:
                    body = b
    return body


def live_tool_calls(agent_data: dict, live: str) -> int:
    return sum(1 for e in first_stage_run(agent_data, live) for p in (e.get("content") or {}).get("parts") or []
               if "function_call" in p)


def placeholder_agent_data(agents: dict, statement: str) -> dict:
    """For a case without a harness trace (skipped, not launched): the issue as the only event."""
    return {"agents": agents, "turns": [{"turn_index": 0, "events": [
        {"author": "user", "content": {"role": "user", "parts": [{"text": statement or ""}]}}]}]}


def build_case(*, case: dict, sample: int, case_id: str, agents: dict, atif: dict | None, extra_golden: dict) -> dict:
    """One grading-input trace case."""
    g = dict(case.get("golden") or {})
    live = extra_golden.get("live_agents") or []
    statement = "".join(p.get("text", "") for p in ((case.get("prompt") or {}).get("parts") or []))
    if atif:
        agent_data, warnings = atif_to_agent_data(atif, agents)
    else:
        agent_data, warnings = placeholder_agent_data(agents, statement), ["no_atif_trace"]
    reply = live_final_text(agent_data, live[0]) if live else ""
    g.update(extra_golden)
    g["case_id"], g["dataset_case_id"], g["sample"] = case_id, case.get("eval_case_id"), sample
    g["writer_warnings"] = list(extra_golden.get("writer_warnings") or []) + warnings
    out = {"eval_case_id": case_id,
           "responses": [{"response": {"role": "model", "parts": [{"text": reply}]}}],
           "reference": case.get("reference") or {"response": {"role": "model", "parts": [{"text": ""}]}},
           "agent_data": agent_data,
           "golden": g}
    return out


def write_dataset(path: Path, cases: list) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"eval_cases": sorted(cases, key=lambda c: c["eval_case_id"])}
    path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def validate_case(c: dict) -> list:
    """Structural problems of one trace case (empty list = valid)."""
    bad = []
    if "prompt" in c:
        bad.append("prompt present")
    r = c.get("responses")
    if not (isinstance(r, list) and r and isinstance((r[0].get("response") or {}).get("parts"), list)):
        bad.append("responses[0] missing")
    ad = c.get("agent_data") or {}
    agents = ad.get("agents") or {}
    for i, t in enumerate(ad.get("turns") or []):
        if t.get("turn_index") != i:
            bad.append(f"turn_index {t.get('turn_index')} != {i}")
        for e in t.get("events") or []:
            if e.get("author") != "user" and e.get("author") not in agents:
                bad.append(f"author {e.get('author')!r} not in agents")
            parts = (e.get("content") or {}).get("parts")
            if not isinstance(parts, list) or not parts:
                bad.append("event without parts")
    return bad
