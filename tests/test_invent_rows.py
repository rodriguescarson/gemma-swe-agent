"""train/invent_rows.py: Invent (Adaption) issue->patch rows become two-call v12-shaped training rows through the real renderer, or are
rejected by the mechanical filter with a counted reason (GAPS 2026-10-06.md "Invent rows as an auxiliary arm", 2026-10-11). Test-first."""
import json, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from train import invent_rows as I  # noqa: E402
from train import scorer_render as R  # noqa: E402

EXCERPT = (
    "def _prepare_import(path: str) -> str:\n"
    "    # Prepare the path for import.\n"
    "    # Current strict regex\n"
    "    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', path):\n"
    "        raise UsageError(\n"
    "            f'Could not import {path}.'\n"
    "        )\n"
    "    return path.replace('/', '.')\n"
    "\n"
    "\n"
    "def find_best_app(module):\n"
    "    return None\n")
PROMPT = ("## Issue: Flask CLI rejects hyphenated module paths\n\n**Description**\n`flask run` fails when FLASK_APP contains hyphens.\n\n"
          "**Error Message**\n```bash\nError: Could not import my-app/app.\n```\n\n**Relevant Source Excerpt**\nFile: `src/flask/cli.py` (lines 210-221)\n"
          "```python\n" + EXCERPT + "```\n\nThe fix should let filesystem paths through.")
DIFF = ("--- a/src/flask/cli.py\n+++ b/src/flask/cli.py\n@@ -210,8 +210,10 @@\n"
        " def _prepare_import(path: str) -> str:\n     # Prepare the path for import.\n-    # Current strict regex\n-    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', path):\n"
        "+    if '/' in path:\n+        return path\n+    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', path):\n         raise UsageError(\n             f'Could not import {path}.'\n         )\n     return path.replace('/', '.')\n")
COMPLETION = ("### Reasoning\n\n1. **Bug**: `_prepare_import` applies the identifier regex to filesystem paths too.\n"
              "2. **Fix**: skip the regex when the path has a separator; minimal and local.\n3. **Test**: tests/test_cli.py covers FLASK_APP resolution.\n\n"
              "### Patch\n```diff\n" + DIFF + "```\n")
TOOLS = [{"type": "function", "function": {"name": n, "description": d, "parameters": {"type": "object", "properties": p, "required": list(p)}}} for n, d, p in (
    ("read_file", "Read a file", {"filepath": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}),
    ("edit_file", "Edit a file", {"filepath": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}))]
TEMPLATE = I.Template(system="You are a software engineer fixing one reported issue.", tools=TOOLS,
                      user_prefix="You are evaluating a software engineering task for repository {repo}.\n\nProblem Statement:\n",
                      user_suffix="\n\n## Task Budget (Session terminates when any budget is exhausted)\n- Time allowance: 5.0 minutes\n")


def test_parse_extracts_the_issue_the_excerpt_and_the_diff():
    item, why = I.parse(PROMPT, COMPLETION)
    assert why is None and item["title"] == "Flask CLI rejects hyphenated module paths"
    assert item["path"] == "src/flask/cli.py" and (item["start"], item["end"]) == (210, 221) and item["excerpt"] == EXCERPT.rstrip("\n")
    assert "**Description**" in item["statement"] and "The fix should let filesystem paths through." in item["statement"]
    assert "Current strict regex" not in item["statement"] and "Relevant Source Excerpt" not in item["statement"]
    assert item["reasoning"].startswith("1. **Bug**") and "### " not in item["reasoning"] and len(item["hunks"]) == 1


def test_hunks_apply_to_the_excerpt_and_the_edit_is_a_minimal_unique_block():
    item, _ = I.parse(PROMPT, COMPLETION)
    patched = I.apply_hunks(item["excerpt"], item["hunks"])
    assert patched and "if '/' in path:" in patched and "# Current strict regex" not in patched and "def find_best_app" in patched
    assert I.python_verdict(item["excerpt"], patched) == "verified"
    old, new = I.edit_region(item["excerpt"], patched)
    assert item["excerpt"].count(old) == 1 and "# Current strict regex" in old and "if '/' in path:" in new
    assert item["excerpt"].replace(old, new) == patched and old.count("\n") <= 6          # 2 lines of context each side
    pre_read, pre_edit = I.split_reasoning(item["reasoning"])
    assert pre_read.startswith("**Bug**") and pre_edit.startswith("**Fix**") and "**Test**" in pre_edit
    assert I.python_verdict("def f(:\n  pass", "x = 1") == "unverifiable"


def test_the_filter_rejects_with_a_named_reason():
    assert I.parse(PROMPT, COMPLETION.replace("src/flask/cli.py", "tests/test_cli.py"))[1] == "test_file"
    two = COMPLETION.replace("```diff\n", "```diff\n--- a/src/flask/other.py\n+++ b/src/flask/other.py\n@@ -1,1 +1,1 @@\n-a\n+b\n")
    assert I.parse(PROMPT, two)[1] == "multi_file"
    assert I.parse(PROMPT, "no diff here")[1] == "no_diff"
    bad_hunk = COMPLETION.replace("-    # Current strict regex\n", "-    # A line that is not in the excerpt\n")
    item, _ = I.parse(PROMPT, bad_hunk)
    assert I.apply_hunks(item["excerpt"], item["hunks"]) is None
    rows, why = I.build_rows(item, TEMPLATE, "probe")
    assert rows is None and why == "hunk_not_in_excerpt"
    broken = COMPLETION.replace("+    if '/' in path:\n", "+    if '/' in path\n")
    item, _ = I.parse(PROMPT, broken)
    assert I.build_rows(item, TEMPLATE, "probe")[1] == "patched_not_python"
    neutral = PROMPT.replace("Flask CLI", "CLI").replace("`flask run`", "the command").replace("FLASK_APP", "APP").replace("src/flask/cli.py", "zzz/cli.py")
    item, _ = I.parse(neutral, COMPLETION.replace("src/flask/cli.py", "zzz/cli.py"))         # no path and no word names a repository
    assert I.build_rows(item, TEMPLATE, "probe")[1] == "unknown_repo"


def test_rows_render_like_the_agents_own_calls_and_chain_exactly(tmp_path):
    from train import stitch_rows as ST
    from train import validate_rows as V
    item, _ = I.parse(PROMPT, COMPLETION)
    rows, why = I.build_rows(item, TEMPLATE, "probe")
    assert why is None and len(rows) == 2
    r1, r2 = rows
    assert r1["prompt"].startswith("<bos>") and "pallets/flask" in r1["prompt"] and "`flask run` fails" in r1["prompt"]
    assert "Current strict regex" not in r1["prompt"]                                    # the excerpt arrives as the tool result
    assert r1["completion"].startswith("<|channel>thought\n**Bug**") and "<|tool_call>call:read_file{" in r1["completion"]
    assert "start_line:210" in r1["completion"] and r1["completion"].endswith("<|tool_response>")
    assert r2["prompt"].startswith(r1["prompt"] + r1["completion"])                     # exact chain: the thought is carried back
    assert "Current strict regex" in r2["prompt"] and '\\"status\\": \\"ok\\"' in r2["prompt"]  # the harness's read_file envelope
    assert r2["completion"].startswith("<|channel>thought\n**Fix**") and "call:edit_file{" in r2["completion"] and "old_string:" in r2["completion"]
    assert r1["meta"]["stage"] is None and r1["meta"]["tool"] == "read_file" and r2["meta"]["continuation"] is True and r2["meta"]["tool"] == "edit_file"
    assert r1["meta"]["task"] == r2["meta"]["task"] and r1["meta"]["traj"] == r2["meta"]["traj"] and r1["meta"]["source"] == "invent"
    f = tmp_path / "rows.jsonl"; f.write_text("".join(json.dumps(r) + "\n" for r in rows))
    v = V.validate(str(f), min_rows=0, require_thought=True)
    assert v["ok"], v["first_problems"]
    seqs, held, rep = ST.stitch(rows, read_share=1.0)
    assert rep["sequences"] == 1 and rep["breaks"] == 0 and rep["healed"] == 0 and rep["span_thought"] == 2 and rep["span_tool"] == 2


def test_template_from_a_real_request_round_trips_the_task_message(tmp_path):
    user = "You are evaluating a software engineering task for repository a/b.\n\nProblem Statement:\nSTMT line 1\n\nline 2\n\n## Task Budget (x)\n- Time allowance: 5.0 minutes\n\n## Execution Environment Rules\n- offline\n"
    cap = {"t": 1, "body": {"messages": [{"role": "system", "content": "SYS"}, {"role": "user", "content": user}], "tools": TOOLS}, "response": {}}
    f = tmp_path / "capture.jsonl"; f.write_text(json.dumps(cap) + "\n")
    t = I.Template.from_capture(str(f))
    assert t.system == "SYS" and t.tools == TOOLS and t.user_prefix.endswith("repository {repo}.\n\nProblem Statement:\n")
    assert t.user_prefix.replace("{repo}", "a/b") + "STMT line 1\n\nline 2" + t.user_suffix == user
    # the per-task directory tree is dropped: no real tree exists for an invented issue
    with_tree = user + "## Workspace Layout\nThe repository is located at `/workspace`. Here is the directory tree (up to 3 levels):\n```\n./a/b.py\n```"
    cap["body"]["messages"][1]["content"] = with_tree
    f.write_text(json.dumps(cap) + "\n")
    t3 = I.Template.from_capture(str(f))
    assert "Workspace Layout" not in t3.user_suffix and "./a/b.py" not in t3.user_suffix and t3.user_suffix.endswith("- offline\n") and t3.user_suffix == t.user_suffix
    trace = {"steps": [{"source": "system", "message": "SYS2"}, {"source": "user", "message": user}]}
    (tmp_path / "trace.json").write_text(json.dumps(trace))
    schemas = {"read_file": TOOLS[0]["function"], "edit_file": TOOLS[1]["function"], "run_command": {"name": "run_command", "parameters": {}}}
    (tmp_path / "schemas.json").write_text(json.dumps(schemas))
    t2 = I.Template.from_trace(str(tmp_path / "trace.json"), str(tmp_path / "schemas.json"), ["read_file", "edit_file"])
    assert t2.system == "SYS2" and t2.tools == TOOLS and t2.user_suffix == t.user_suffix


def test_the_last_python_fence_is_the_excerpt_when_the_file_marker_is_missing():
    bare = PROMPT.replace("**Relevant Source Excerpt**\nFile: `src/flask/cli.py` (lines 210-221)\n", "Here is the code:\n")
    item, why = I.parse(bare, COMPLETION)
    assert why is None and item["path"] == "src/flask/cli.py" and item["excerpt"] == EXCERPT.rstrip("\n") and (item["start"], item["end"]) == (1, 12)
    assert "Here is the code:" in item["statement"] and "Current strict regex" not in item["statement"]


def test_cli_writes_rows_and_a_report(tmp_path):
    rows = [{"enhanced_prompt": PROMPT, "enhanced_completion": COMPLETION},
            {"enhanced_prompt": PROMPT, "enhanced_completion": COMPLETION.replace("src/flask/cli.py", "tests/test_cli.py")},
            {"enhanced_prompt": PROMPT, "enhanced_completion": COMPLETION}]                   # a duplicate title
    (tmp_path / "in.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    user = TEMPLATE.user_prefix.replace("{repo}", "a/b") + "S" + TEMPLATE.user_suffix
    (tmp_path / "trace.json").write_text(json.dumps({"steps": [{"source": "system", "message": TEMPLATE.system}, {"source": "user", "message": user}]}))
    (tmp_path / "schemas.json").write_text(json.dumps({t["function"]["name"]: t["function"] for t in TOOLS}))
    r = subprocess.run([sys.executable, str(ROOT / "train" / "invent_rows.py"), str(tmp_path / "in.jsonl"), "--out", str(tmp_path / "rows.jsonl"),
                        "--report", str(tmp_path / "report.json"), "--template-trace", str(tmp_path / "trace.json"),
                        "--tool-schemas", str(tmp_path / "schemas.json"), "--tools", "read_file,edit_file"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "report.json").read_text())
    assert rep["rows_in"] == 3 and rep["kept"] == 1 and rep["rows_out"] == 2 and rep["rejected"] == {"test_file": 1, "duplicate_title": 1}
    assert rep["verdicts"] == {"verified": 1} and rep["hunks_per_item"] == {"1": 1}
    out = [json.loads(l) for l in (tmp_path / "rows.jsonl").read_text().splitlines()]
    assert len(out) == 2 and out[1]["prompt"].startswith(out[0]["prompt"] + out[0]["completion"])
