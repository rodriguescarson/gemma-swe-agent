"""train/spans.py and train/stitch_rows.py: one sequence per (traj, stage) from build_sft rows, with weighted model spans.
Synthetic rows follow the June template's shapes; the real thinking-on chain property is tested in tests/test_thinking_rows.py.
Written before the code (test-first)."""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from train import spans as S  # noqa: E402
from train import stitch_rows as ST  # noqa: E402

SYS = "<bos><|turn>system\nSYS<turn|>\n<|turn>user\nFIX IT<turn|>\n<|turn>model\n"
TH = lambda t: f"<|channel>thought\n{t}\n<channel|>"  # noqa: E731
CALL = lambda name, arg: f"<|tool_call>call:{name}{{{arg}}}<tool_call|><|tool_response>"  # noqa: E731
RESP = lambda body: f"response:x{{{body}}}<tool_response|>"  # noqa: E731


def chain(task="t1", traj="cap|t1", stage="fixer", thoughts=True, drop_empty_thought=False):
    """A 3-call trajectory: read, edit, text reply; rows as build_sft writes them (prompt_i+1 starts with prompt_i + completion_i,
    except that a thinking-off harness drops the model's empty thought when drop_empty_thought is set)."""
    t = TH if thoughts else (lambda _: S.EMPTY_THOUGHT)
    c1 = t("read first") + CALL("read_file", 'filepath:"a.py"')
    r1 = RESP('"status": "ok", "content": "x"')
    c2 = t("now edit") + CALL("edit_file", 'filepath:"a.py",new_string:"b",old_string:"a"')
    r2 = RESP('"status": "ok"')
    c3 = t("done") + "Changed a.py.<turn|>"
    p1 = SYS if thoughts else SYS + S.EMPTY_THOUGHT
    comp1 = c1 if thoughts else c1[len(S.EMPTY_THOUGHT):]     # thinking off: the first call's empty thought is in the prompt
    heal = lambda c: c.replace(S.EMPTY_THOUGHT, "", 1) if drop_empty_thought else c  # noqa: E731
    p2 = p1 + heal(comp1) + r1
    p3 = p2 + heal(c2) + r2
    meta = lambda cont, tool: {"task": task, "traj": traj, "stage": stage, "continuation": cont, "tool": tool}  # noqa: E731
    return [{"prompt": p1, "completion": comp1, "meta": meta(False, "read_file")},
            {"prompt": p2, "completion": c2, "meta": meta(True, "edit_file")},
            {"prompt": p3, "completion": c3, "meta": meta(True, None)}]


def test_spans_pick_model_bytes_only_and_classify_them():
    rows = chain()
    text = rows[-1]["prompt"] + rows[-1]["completion"]
    sp = S.supervised_char_spans(text)
    picked = "".join(text[a:b] for a, b in sp)
    assert "SYS" not in picked and "FIX IT" not in picked and '"content": "x"' not in picked
    assert "read first" in picked and "call:read_file" in picked and "Changed a.py.<turn|>" in picked
    kinds = [S.describe_span(text, a, b) for a, b in sp]
    assert [k["kind"] for k in kinds] == ["tool", "tool", "text"] and [k["tool"] for k in kinds] == ["read_file", "edit_file", None]
    assert all(k["thought"] for k in kinds)


def test_stitch_is_exact_for_a_thinking_chain_and_heals_the_dropped_empty_thought():
    rows = chain()
    (text, calls, breaks, healed, comp), = ST.stitch_group(rows)
    assert text == rows[-1]["prompt"] + rows[-1]["completion"] and calls == 3 and breaks == 0 and healed == 0 and comp == 0
    off = chain(thoughts=False, drop_empty_thought=True)          # the thinking-off harness: next prompt lacks the empty thought
    (text2, calls2, breaks2, healed2, _), = ST.stitch_group(off)
    assert breaks2 == 0 and calls2 == 3 and healed2 == 1          # only call 2's empty thought was dropped by the harness
    assert text2.count(S.EMPTY_THOUGHT) == 3                       # the model's bytes are kept: first call (in the prompt) + 2 continuations
    assert text2.endswith("Changed a.py.<turn|>") and "call:edit_file" in text2
    assert all(text2.find(r["completion"]) >= 0 for r in off)    # every completion is in the sequence verbatim


def test_a_real_break_splits_the_group_and_is_counted():
    rows = chain()
    rows[2]["prompt"] = rows[2]["prompt"].replace("FIX IT", "FIX THAT")          # the shared prefix itself changed (compaction rewrote history)
    parts = ST.stitch_group(rows)
    assert len(parts) == 2 and parts[1][2] == 1 and parts[0][1] == 2 and parts[1][1] == 1


def test_a_compaction_starts_a_new_sequence_and_file_order_is_kept():
    """ADK compaction replaces the history by a summary user turn: later prompts are SHORTER than earlier ones and share no prefix."""
    rows = chain()
    summary = SYS.replace("FIX IT", "For context:[model] said: **Summary:** the agent read a.py") + TH("resume") + "Changed a.py.<turn|>"
    rows.append({"prompt": summary[:summary.index(TH("resume"))], "completion": TH("resume") + "Changed a.py.<turn|>",
                 "meta": {"task": "t1", "traj": "cap|t1", "stage": "fixer", "continuation": True, "tool": None}})
    parts = ST.stitch_group(rows)
    assert len(parts) == 2 and parts[0][1] == 3 and parts[1] [1] == 1 and parts[1][4] == 1 and parts[1][2] == 0   # a compaction, not a break
    assert parts[0][0].endswith("Changed a.py.<turn|>") and parts[1][0].startswith("<bos><|turn>system") and "For context:[model] said" in parts[1][0]


def test_the_thinking_off_generation_thought_is_tolerated_in_the_prefix():
    """Thinking off: the first prompt ends with the template's empty thought, but the harness renders that turn without it."""
    off = chain(thoughts=False)
    e = S.EMPTY_THOUGHT
    off[1]["prompt"] = off[0]["prompt"][:-len(e)] + off[0]["completion"] + off[1]["prompt"][len(off[0]["prompt"]) + len(off[0]["completion"]):]
    off[2]["prompt"] = off[1]["prompt"] + off[1]["completion"].replace(e, "", 1) + off[2]["prompt"][len(off[1]["prompt"]) + len(off[1]["completion"]) - len(e) + len(e):]
    (text, calls, breaks, healed, comp), = ST.stitch_group(off)
    assert breaks == 0 and calls == 3 and healed >= 1 and text.startswith(off[0]["prompt"] + off[0]["completion"])


def test_the_harness_re_serialising_a_call_is_healed_not_a_break():
    """The harness parses the model's call and renders its own form (escapes, key order) into the next prompt: the model's bytes
    stay in the sequence, the tool response and the rest come from the next prompt."""
    rows = chain()
    rows[1]["prompt"] = rows[1]["prompt"].replace('filepath:"a.py"', 'filepath:"a.py",extra:"1"', 1)       # a different rendering of call 1
    rows[2]["prompt"] = rows[2]["prompt"].replace('filepath:"a.py"', 'filepath:"a.py",extra:"1"', 1)
    (text, calls, breaks, healed, _), = ST.stitch_group(rows)
    assert breaks == 0 and healed == 1 and calls == 3
    assert 'filepath:"a.py"}' in text and "extra" not in text                       # the model's call, not the harness's
    assert '"content": "x"' in text and "call:edit_file" in text and text.endswith("Changed a.py.<turn|>")


def test_weights_mask_repeats_errors_and_excess_reads():
    rows = chain()
    text = rows[-1]["prompt"] + rows[-1]["completion"]
    # add a repeated read and an erroring call before the final reply
    rep = CALL("read_file", 'filepath:"a.py"') + RESP('"status": "ok", "content": "x"')
    err = CALL("run_command", 'command:"ls"') + RESP('"status": "error", "error_type": "CommandError"')
    text = text.replace(TH("done") + "Changed a.py.<turn|>", TH("again") + rep + TH("err") + err + TH("done") + "Changed a.py.<turn|>")
    sp = S.supervised_char_spans(text)
    weighted, r = S.weight_spans(text, sp, read_share=1.0)
    kinds = [S.describe_span(text, a, b) for a, b in sp]
    assert [k["tool"] for k in kinds] == ["read_file", "edit_file", "read_file", "run_command", None]
    assert [w for _, _, w in weighted] == [1.0, 1.0, 0.0, 0.0, 1.0] and r["repeat"] == 1 and r["error"] == 1 and r["text"] == 1
    weighted2, r2 = S.weight_spans(text, sp, read_share=0.0, seed=3)    # no reads allowed: the first read is masked too
    assert [w for _, _, w in weighted2] == [0.0, 1.0, 0.0, 0.0, 1.0] and r2["read_over_share"] == 1


def test_stitch_caps_per_task_stage_holds_out_tasks_and_reports(tmp_path):
    rows = []
    for k in range(12):
        rows += chain(task="t1", traj=f"cap{k}|t1")                 # 12 trajectories of one task/stage
    rows += chain(task="t2", traj="cap|t2")
    rows += chain(task="held", traj="cap|held")
    seqs, held, rep = ST.stitch(rows, max_per_task_stage=10, max_tokens=14336, tok=None, holdout={"held"})
    assert rep["sequences"] == 11 and rep["capped_per_task_stage"] == 2 and rep["holdout_sequences"] == 1 and rep["breaks"] == 0
    assert rep["span_text"] == 12 and rep["span_tool"] == 24 and rep["supervised_chars"] > 0 and rep["tokens"] > 0
    assert all(s["meta"]["task"] != "held" for s in seqs) and held[0]["meta"]["task"] == "held"
    inp = tmp_path / "rows.jsonl"; inp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    (tmp_path / "hold.txt").write_text("held\n")
    r = subprocess.run([sys.executable, str(ROOT / "train" / "stitch_rows.py"), str(inp), "--out", str(tmp_path / "seqs.jsonl"), "--report", str(tmp_path / "rep.json"),
                        "--holdout-tasks", str(tmp_path / "hold.txt"), "--holdout-out", str(tmp_path / "held.jsonl")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    out = [json.loads(l) for l in (tmp_path / "seqs.jsonl").read_text().splitlines()]
    assert len(out) == 11 and set(out[0]) == {"text", "spans", "meta"} and all(len(s) == 3 for s in out[0]["spans"])
    assert len((tmp_path / "held.jsonl").read_text().splitlines()) == 1 and json.loads((tmp_path / "rep.json").read_text())["sequences"] == 11


def test_sequences_over_the_token_cap_are_dropped():
    rows = chain()
    rows[-1]["completion"] = rows[-1]["completion"].replace("Changed a.py.", "x" * 200000)
    seqs, held, rep = ST.stitch(rows, max_tokens=14336)
    assert rep["over_max_tokens"] == 1 and rep["sequences"] == 0


def test_validate_stitched_accepts_the_stitcher_output_and_flags_broken_sequences(tmp_path):
    from train import validate_rows as V
    rows = chain() + [dict(r, prompt=r["prompt"].replace("FIX IT", "FIX THAT")) for r in chain(task="t2", traj="cap|t2")]   # two distinct texts
    seqs, held, rep = ST.stitch(rows)
    good = tmp_path / "seqs.jsonl"; good.write_text("".join(json.dumps(s) + "\n" for s in seqs))
    r = V.validate_stitched(str(good), max_tokens=14336, require_thought=True)
    assert r["ok"] and r["sequences"] == 2 and r["sequences_with_thought"] == 2 and r["trained_chars"] > 0, r["first_problems"]
    bad = dict(seqs[0]); bad["spans"] = [[0, 5, 1.0]]                                    # not the model spans
    dup = dict(seqs[1])
    nothought = dict(seqs[1]); nothought["text"] = nothought["text"].replace("read first", "").replace("now edit", "").replace("done", "")
    (tmp_path / "bad.jsonl").write_text("".join(json.dumps(s) + "\n" for s in [bad, seqs[1], dup]))
    r2 = V.validate_stitched(str(tmp_path / "bad.jsonl"), require_thought=True)
    kinds = {p[1] for p in r2["first_problems"]}
    assert not r2["ok"] and "spans are not the model spans of the text" in kinds and "duplicate sequence" in kinds
    assert V.validate_stitched(str(good), exclude={"t2"})["problems"] == 1
    r3 = subprocess.run([sys.executable, str(ROOT / "train" / "validate_rows.py"), "--stitched", str(good), "--min-rows", "1", "--no-tokenizer", "--require-thought"], capture_output=True, text=True)
    assert r3.returncode == 0 and '"ok": true' in r3.stdout, r3.stdout[-400:] + r3.stderr[-400:]


def test_holdout_auto_draws_tasks_when_the_named_ones_are_absent(tmp_path):
    rows = chain(task="a", traj="x|a") + chain(task="b", traj="x|b") + chain(task="c", traj="x|c")
    assert len(ST.auto_holdout(rows, 2, seed=1)) == 2 and ST.auto_holdout(rows, 2, seed=1) == ST.auto_holdout(rows, 2, seed=1)
    inp = tmp_path / "rows.jsonl"; inp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    (tmp_path / "hold.txt").write_text("zzz\n")
    out = tmp_path / "seqs.jsonl"
    r = subprocess.run([sys.executable, str(ROOT / "train" / "stitch_rows.py"), str(inp), "--out", str(out), "--report", str(tmp_path / "rep.json"),
                        "--holdout-tasks", str(tmp_path / "hold.txt"), "--holdout-out", str(tmp_path / "held.jsonl"), "--holdout-auto", "1"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-600:]
    drawn = (tmp_path / "seqs.jsonl.holdout_tasks.txt").read_text().split()
    assert len(drawn) == 1 and len(out.read_text().splitlines()) == 2 and len((tmp_path / "held.jsonl").read_text().splitlines()) == 1


def test_require_thought_drops_thoughtless_sequences_and_reports_them(tmp_path):
    """2026-10-12: 3 of 159 real sequences carried no non-empty thought (box P2_LOG); such a sequence teaches calling without
    thinking (the v11 failure), so train.sh stitch passes --require-thought and the gate allows <= 5% dropped."""
    rows = chain(task="t1", traj="cap|t1") + chain(task="t2", traj="cap|t2", thoughts=False)
    seqs, held, rep = ST.stitch(rows, tok=None)
    assert rep["sequences"] == 2 and rep["dropped_no_thought"] == 0 and rep["dropped_no_thought_tasks"] == []
    seqs, held, rep = ST.stitch(rows, tok=None, require_thought=True)
    assert rep["sequences"] == 1 and rep["dropped_no_thought"] == 1 and rep["dropped_no_thought_tasks"] == ["t2"]
    assert seqs[0]["meta"]["task"] == "t1" and S.has_thought(seqs[0]["text"])
    inp = tmp_path / "rows.jsonl"; inp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    r = subprocess.run([sys.executable, str(ROOT / "train" / "stitch_rows.py"), str(inp), "--out", str(tmp_path / "seqs.jsonl"),
                        "--report", str(tmp_path / "rep.json"), "--require-thought"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    rep2 = json.loads((tmp_path / "rep.json").read_text())
    assert rep2["sequences"] == 1 and rep2["dropped_no_thought"] == 1 and rep2["dropped_no_thought_tasks"] == ["t2"]
    v = subprocess.run([sys.executable, str(ROOT / "train" / "validate_rows.py"), "--stitched", str(tmp_path / "seqs.jsonl"), "--min-rows", "1",
                        "--no-tokenizer", "--require-thought", "--min-thought-share", "0.8", "--report", str(tmp_path / "val.json")], capture_output=True, text=True)
    val = json.loads((tmp_path / "val.json").read_text())
    assert val["ok"] and val["sequences_with_thought"] == val["sequences"] == 1, v.stdout[-800:]
    assert "--require-thought" in (ROOT / "scripts" / "a6000" / "train.sh").read_text()
