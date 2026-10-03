"""Per-step and per-task speed extraction over every trace set (speed.md). Stdlib only.

Output: steps.jsonl (one row per agent step) and tasks.jsonl (one row per task) in this directory.

Clock:
  * wall_real  = extra.elapsed_s (seconds since sandbox creation); agent clock = wall_real - task_prompt elapsed.
  * L4 seconds: Kaggle runs are real L4. Pod runs with G4_L4_SCALE=1.7 (pair1, race2) -> x1.7 (the scale the agent's
    own helper clock and cap used). Race 1 (H100, no scale) -> x1.72 (time_model 6 median ratio) for the wall, and the
    cost model for the LLM part.
  * Cost model (research/time_model.md 2, x1.08 as scripts/replay_l4.py): 1.08*(0.085 + 0.0285*ct + 0.00065*unc).
"""
import glob
import json
import os
import re
import sys

G = "/Users/carson/Projects/gemma-swe-agent/eval"
HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = {  # name: (trace dir, results file, scale to L4, kind)
    "p1_v10": (G + "/pair1/eval/runs/p1_v10", None, 1.7, "pod"),
    "p1_v4": (G + "/pair1/eval/runs/p1_v4", None, 1.7, "pod"),
    "r2_v10_1": (G + "/race2/eval/runs/r2_v10_1", None, 1.7, "pod"),
    "r2_v9_eog_1": (G + "/race2/eval/runs/r2_v9_eog_1", None, 1.7, "pod"),
    "k_v4": (HERE + "/l4v4", G + "/kaggle/g4-l4-v4/results.jsonl", 1.0, "kaggle"),
    "k_v9_eog": (HERE + "/l4v9", G + "/kaggle/g4-l4-v9-eog/results.jsonl", 1.0, "kaggle"),
}
for r in ("r_v4", "r_v9_eog", "r_v9_c", "r_v9_eg", "r_v9_eo", "r_v9_og"):
    RUNS[r] = (G + "/race1/runs/" + r, None, 1.72, "race1")
for r in ("p_v4", "p_v6", "p_v7", "p_v8"):     # eval3: fair pod runs, 6 min / 110 calls / 220 turns, H100 unscaled
    RUNS[r] = (G + "/eval3/eval/runs/" + r, None, 1.72, "eval3")

MAXOUT = {  # max_output_tokens per stage per bundle family
    "v10": {"setup": 256, "locator": 768, "fixer": 2048, "verifier": 2048, "submitter": 1024},
}
OVH, DEC, PRE, FUDGE = 0.085, 0.0285, 0.00065, 1.08


def cost(ct, unc):
    return FUDGE * (OVH + DEC * ct + PRE * unc)


def obs_text(s):
    o = s.get("observation")
    if isinstance(o, dict):
        c = o.get("content")
        return c if isinstance(c, str) else json.dumps(c)
    return str(o or "")


def unwrap(o):
    """Tool observations are JSON: run_command -> {status, stdout, stderr}; errors -> {status: error, ...}."""
    try:
        j = json.loads(o)
    except Exception:
        return o, None
    if isinstance(j, dict):
        if "stdout" in j or "stderr" in j:
            return (j.get("stdout") or "") + ("\n" + j["stderr"] if j.get("stderr") else ""), j
        if j.get("status") == "error":
            d = j.get("details") or {}
            return "ERROR " + str(j.get("error_type")) + ": " + str(j.get("error_message")) + " " + \
                str(d.get("stdout") or "") if isinstance(d, dict) else "", j
    return o, j


HELPER = re.compile(r"python3?\s+/tmp/swe/(\w+)\.py")
VIEW = re.compile(r"/tmp/swe/view\.py\s+(\S+)(?:\s+(\d+)\s+(\d+)|\s+([A-Za-z_][\w.]*))?")
TCALL_TEXT = re.compile(r"<\|tool_call>|call:[\w./ ]+\{|^call:", re.M)


def classify(fn, args, out, author):
    """-> (helper, category, ok, source_edit, verify_kind)."""
    cmd = ""
    if isinstance(args, dict):
        cmd = str(args.get("command") or "")
    helper = None
    m = HELPER.search(cmd)
    if fn == "run_command":
        helper = m.group(1) if m else "raw"
        # run.py wrapping another helper: take the first one
    elif fn == "run_skill_script":
        helper = "install"
    else:
        helper = fn
    low = out[:3000]
    ok, src_edit, vk = True, False, None
    if "mandatory input parameters are not present" in low or re.search(r"Tool '[^']+' not found", low):
        return helper, "malformed", False, False, None
    if "can't open file" in low or "No such file or directory" in low and helper not in ("raw",):
        if helper not in ("raw", "read_file"):
            return helper, "cant_open", False, False, None
    if "BudgetExceeded" in low or "budget exhausted" in low.lower():
        return helper, "postcap", False, False, None
    if helper == "edit":
        s = out.lstrip()
        if s.startswith("OK"):
            src_edit = True
        elif "OK (" in s[:400] and "EOF: command not found" in s:
            src_edit = True   # edit landed, stray EOF line errored afterwards
            ok = False
        else:
            ok = False
        cat = "edit_ok" if src_edit else ("edit_repeat" if s.startswith("ALREADY TRIED") else "edit_fail")
        return helper, cat, ok, src_edit, None
    if fn == "edit_file" or fn == "write_file":
        good = '"status": "ok"' in low[:40] or '"status": "success"' in low[:40]
        path = str((args or {}).get("filepath") or (args or {}).get("path") or (args or {}).get("file_path") or "")
        scratch = bool(re.search(r"(^|/)(repro|reproduce|scratch|debug|tmp|temp|try|demo|test_|verify_)[^/]*$", path)) or \
            bool(re.search(r"(^|/)(tests?|testing)/", path)) or path.endswith("conftest.py")
        return helper, ("native_edit_ok" if good else "native_edit_fail"), good, bool(good and not scratch and
                                                                                        path.endswith(".py")), None
    if helper == "verify":
        if "--repro-only" in cmd:
            vk = "repro"
            if low.lstrip().startswith("REPRO: fails on original"):
                return helper, "repro_ok", True, False, vk
            return helper, "repro_retry", True, False, vk
        s = low.lstrip()
        if s.startswith("SAME AS LAST"):
            return helper, "verify_same", False, False, "same"
        mm = re.search(r"VERIFY: (GREEN|AMBER|RED|NO SOURCE CHANGE|UNKNOWN)", low)
        vk = mm.group(1) if mm else "other"
        return helper, "verify", True, False, vk
    if helper == "finalize":
        s = low.lstrip()
        return helper, ("finalize_ready" if s.startswith("READY") else "finalize_not"), True, False, None
    if helper in ("view", "grep", "locate", "status", "run", "install"):
        if low.lstrip().startswith("NOTE: same") or "same command, same output" in low:
            return helper, "repeat_note", False, False, None
        return helper, helper, True, False, None
    if fn == "read_file":
        return helper, "read_file", True, False, None
    if fn == "submit_patch":
        return helper, "submit", True, False, None
    if helper == "raw":
        return helper, "raw", True, False, None
    return helper, fn or "?", True, False, None


def view_key(fn, args):
    """(file, lo, hi) for a line-range read, (file, name) for a symbol view, else None."""
    if fn == "read_file" and isinstance(args, dict):
        f = args.get("filepath") or args.get("path") or args.get("file_path")
        try:
            lo, hi = int(args.get("start_line") or 1), int(args.get("end_line") or (int(args.get("start_line") or 1) + 149))
        except Exception:
            lo, hi = 1, 150
        return (str(f), lo, hi)
    if fn == "run_command" and isinstance(args, dict):
        m = VIEW.search(str(args.get("command") or ""))
        if m:
            if m.group(2):
                return (m.group(1), int(m.group(2)), int(m.group(3)))
            if m.group(4):
                return (m.group(1), m.group(4))
            return (m.group(1), 1, 10 ** 6)
    return None


def load_results(run, d, res_file):
    res = {}
    if res_file:
        for line in open(res_file):
            if line.strip():
                r = json.loads(line)
                res[r["id"]] = dict(resolved=bool(r.get("resolved")), patch=len(r.get("patch") or ""),
                                    secs=r.get("secs"), err=r.get("err"), calls=r.get("calls"))
    else:
        for line in open(os.path.join(d, "task_results.jsonl")):
            if line.strip():
                r = json.loads(line)
                res[r["instance_id"]] = dict(resolved=bool(r.get("resolved")), patch=int(r.get("agent_patch_size") or 0),
                                             secs=r.get("duration_seconds"), err=r.get("error"),
                                             calls=r.get("total_llm_calls"))
    return res


def ensure_l4_traces():
    """Unpack the Kaggle L4 trace tarballs next to this script on first use."""
    import tarfile
    for sub, name in (("l4v4", "g4-l4-v4"), ("l4v9", "g4-l4-v9-eog")):
        if not os.path.isdir(os.path.join(HERE, sub, "traces")):
            os.makedirs(os.path.join(HERE, sub), exist_ok=True)
            with tarfile.open(os.path.join(G, "kaggle", name, "traces.tar.gz")) as tf:
                tf.extractall(os.path.join(HERE, sub))


def main():
    ensure_l4_traces()
    fs = open(os.path.join(HERE, "steps.jsonl"), "w")
    ft = open(os.path.join(HERE, "tasks.jsonl"), "w")
    for run, (d, res_file, scale, kind) in RUNS.items():
        res = load_results(run, d, res_file)
        for fp in sorted(glob.glob(os.path.join(d, "traces", "trace_*.json"))):
            tid = os.path.basename(fp)[6:-5]
            tr = json.load(open(fp))
            steps = tr.get("steps") or []
            t_prompt = None
            for s in steps:
                if s.get("source") == "user" or (s.get("extra") or {}).get("event_type") == "task_prompt":
                    t_prompt = float((s.get("extra") or {}).get("elapsed_s") or 0)
                    break
            t_prompt = t_prompt or 0.0
            prev_end = t_prompt
            prev_tok = {}
            seen_calls, seen_stage_calls, views_stage, views_task = set(), set(), {}, {}
            prev_author = None
            rows = []
            for s in steps:
                if s.get("source") != "agent":
                    continue
                ex = s.get("extra") or {}
                tcs = s.get("tool_calls") or []
                m = s.get("metrics") or {}
                author = ex.get("author") or (tcs and (tcs[0].get("extra") or {}).get("author")) or "?"
                pt = m.get("prompt_tokens")
                ct = m.get("completion_tokens") or 0
                t_llm = ex.get("elapsed_s")
                if t_llm is None and tcs:
                    t_llm = (tcs[0].get("extra") or {}).get("elapsed_s")
                t_llm = float(t_llm) if t_llm is not None else prev_end
                ob = s.get("observation")
                t_obs = None
                if isinstance(ob, dict):
                    t_obs = (ob.get("extra") or {}).get("elapsed_s")
                t_obs = float(t_obs) if (t_obs is not None and tcs) else t_llm
                llm_s = max(0.0, t_llm - prev_end)
                tool_s = max(0.0, t_obs - t_llm) if tcs else 0.0
                prev_end = max(prev_end, t_obs if tcs else t_llm)
                p = prev_tok.get(author)
                unc = max(0, pt - p[0] - p[1]) if (p and pt is not None and pt >= p[0]) else (pt or 0)
                if pt is not None:
                    prev_tok = {author: (pt, ct)}
                if author != prev_author:
                    seen_stage_calls, views_stage = set(), {}
                    prev_author = author
                fn = tcs[0].get("function_name") if tcs else None
                args = tcs[0].get("arguments") if tcs else None
                out_raw = obs_text(s) if tcs else ""
                out, _ = unwrap(out_raw) if tcs else ("", None)
                msg = str(s.get("message") or "")
                row = dict(run=run, tid=tid, sid=s.get("step_id"), author=author, pt=pt, ct=ct, unc=unc,
                           t_llm=round(t_llm - t_prompt, 3), t_end=round((t_obs if tcs else t_llm) - t_prompt, 3),
                           llm_s=round(llm_s, 3), tool_s=round(tool_s, 3), model_s=round(cost(ct, unc), 3),
                           fn=fn, ntc=len(tcs), obs_len=len(out_raw))
                if not tcs:
                    row.update(helper=None, cat=("pseudo_call_text" if TCALL_TEXT.search(msg) else "text"), ok=True,
                               src_edit=False, vk=None, msg_len=len(msg))
                else:
                    helper, cat, ok, src_edit, vk = classify(fn, args, out, author)
                    key = (fn, json.dumps(args, sort_keys=True))
                    row.update(helper=helper, cat=cat, ok=ok, src_edit=src_edit, vk=vk,
                               rep_task=key in seen_calls, rep_stage=key in seen_stage_calls)
                    seen_calls.add(key)
                    seen_stage_calls.add(key)
                    vkey = view_key(fn, args)
                    if vkey:
                        def covered(keys, vk_):
                            for k in keys:
                                if k[0] != vk_[0]:
                                    continue
                                if len(vk_) == 2 or len(k) == 2:
                                    if k == vk_:
                                        return True
                                    continue
                                lo, hi = vk_[1], vk_[2]
                                ov = max(0, min(hi, k[2]) - max(lo, k[1]) + 1)
                                if ov >= 0.8 * (hi - lo + 1):
                                    return True
                            return False
                        row["reread_stage"] = covered(views_stage.keys(), vkey)
                        row["reread_task"] = covered(views_task.keys(), vkey)
                        views_stage[vkey] = 1
                        views_task[vkey] = 1
                    norm = re.sub(r"\[t=\d+s\]|t=\d+s|^(LOCATOR|EDIT NOW|CONTEXT|FINISH|TIME|FINAL):.*$", "", out, flags=re.M)
                    row["oh"] = hash(norm.strip()) & 0xffffffff
                    rst = re.search(r"RESTORED: checkpoint #\d+ \(\w+, t=(\d+)s\)", out)
                    if rst:
                        row["restored_t"] = int(rst.group(1))
                    mt = re.findall(r"\[t=(\d+)s\]", out)
                    if mt:
                        row["helper_t"] = int(mt[-1])
                    hints = [h for h in ("LOCATOR:", "EDIT NOW:", "CONTEXT:", "FINISH:", "TIME:", "FINAL:") if h in out]
                    if hints:
                        row["hints"] = hints
                    if isinstance(args, dict):
                        row["cmd"] = str(args.get("command") or "")[:160]
                rows.append(row)
            for r in rows:
                fs.write(json.dumps(r) + "\n")
            rr = res.get(tid, {})
            ft.write(json.dumps(dict(run=run, tid=tid, kind=kind, scale=scale, resolved=rr.get("resolved", False),
                                     patch=rr.get("patch", 0), secs=rr.get("secs"), err=rr.get("err"),
                                     n_steps=len(rows))) + "\n")
    fs.close()
    ft.close()


if __name__ == "__main__":
    main()
