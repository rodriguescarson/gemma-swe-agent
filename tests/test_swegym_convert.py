"""train/convert_swegym.py: SWE-Gym OpenHands-SFT-Trajectories (text-action OpenHands) -> one-call SFT rows in our fixer format.

The fixtures imitate OpenHands' own observation formats (cat -n views, the str_replace snippet, the bash echo + PS1 trailer)
from a small in-memory file system, so every mapping is checked against what OpenHands would have shown and what our
harness would return.
"""
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from train import convert_swegym as S  # noqa: E402
from train import validate_rows as V  # noqa: E402
from train.scorer_render import EMPTY_THOUGHT  # noqa: E402

RD = "o__r__1.0"
WS = f"/workspace/{RD}"
SRC = "def foo():\n    return 1\n\n\ndef bar(x):\n    y = x + 1\n    return y\n"


# ---------------------------------------------------------------- a tiny OpenHands imitation over an in-memory FS
def fn(name, **params):
    body = "".join(f"<parameter={k}>\n{v}\n</parameter>\n" if "\n" in str(v) else f"<parameter={k}>{v}</parameter>\n"
                   for k, v in params.items())
    return {"role": "assistant", "content": f"Let me act.\n\n<function={name}>\n{body}</function>"}


def res(tool, text):
    return {"role": "user", "content": f"EXECUTION RESULT of [{tool}]:\n{text}"}


def numbered(lines, first):
    return "\n".join(f"{i + first:6}\t{l}" for i, l in enumerate(lines))


class OH:
    def __init__(self, files):
        self.fs = dict(files)                    # repo-relative path -> text

    def view(self, rel, rng=None):
        lines = self.fs[rel].split("\n")
        if rng:
            a, b = rng
            shown, first = (lines[a - 1:] if b == -1 else lines[a - 1:b]), a
            args = {"command": "view", "path": f"{WS}/{rel}", "view_range": json.dumps(rng)}
        else:
            shown, first = lines, 1
            args = {"command": "view", "path": f"{WS}/{rel}"}
        out = f"Here's the result of running `cat -n` on {WS}/{rel}:\n" + numbered(shown, first) + "\n"
        return [fn("str_replace_editor", **args), res("str_replace_editor", out)]

    def str_replace(self, rel, old, new):
        c = self.fs[rel]
        assert c.count(old) == 1
        rl = c.split(old)[0].count("\n")
        self.fs[rel] = n = c.replace(old, new)
        s, e = max(0, rl - 4), rl + 4 + new.count("\n")
        snip = numbered(n.split("\n")[s:e + 1], s + 1)
        out = (f"The file {WS}/{rel} has been edited. Here's the result of running `cat -n` on a snippet of {WS}/{rel}:\n"
               f"{snip}\nReview the changes and make sure they are as expected. Edit the file again if necessary.")
        return [fn("str_replace_editor", command="str_replace", path=f"{WS}/{rel}", old_str=old, new_str=new),
                res("str_replace_editor", out)]

    def create(self, rel, text):
        self.fs[rel] = text
        return [fn("str_replace_editor", command="create", path=f"{WS}/{rel}", file_text=text),
                res("str_replace_editor", f"File created successfully at: {WS}/{rel}")]

    @staticmethod
    def bash(cmd, out, code=0, cwd=WS):
        echo = cmd.replace("\n", "\n> ")
        body = (echo + "\r\n" + out.replace("\n", "\r\n")) if out else echo
        return [fn("execute_bash", command=cmd),
                res("execute_bash", body + f"[Python Interpreter: /opt/miniconda3/envs/testbed/bin/python]\n"
                                           f"root@openhands-workspace:{cwd} # \n[Command finished with exit code {code}]")]


def header(ps="Fix foo so it returns 2"):
    return [{"role": "system", "content": "You are a helpful assistant ..."},
            {"role": "user", "content": f"<uploaded_files>\n{WS}\n</uploaded_files>\nI've uploaded a python code repository in the "
                                        f"directory {RD}. Consider the following PR description:\n\n<pr_description>\n{ps}\n"
                                        "</pr_description>\n\nCan you help me implement the necessary changes ..."}]


FINISH = {"role": "assistant", "content": "Done.\n\n<function=finish>\n</function>"}
TASK = {"instance_id": "o__r-1", "repo": "o/r", "base_commit": "abc", "problem_statement": "Fix foo so it returns 2",
        "patch": "diff --git a/pkg/a.py b/pkg/a.py\n--- a/pkg/a.py\n+++ b/pkg/a.py\n"}


def files_of(d):
    return lambda rel: d.get(rel)


def happy():
    oh = OH({"pkg/a.py": SRC})
    msgs = header()
    msgs += oh.bash(f"grep -rn 'def foo' {WS}/pkg", f"{WS}/pkg/a.py:1:def foo():")
    msgs += oh.view("pkg/a.py", [1, 3])
    msgs += oh.str_replace("pkg/a.py", "    return 1", "    return 2")
    msgs += oh.create("check_foo.py", "from pkg.a import foo\nprint(foo())\n")
    msgs += oh.bash(f"python {WS}/check_foo.py", "2")
    msgs += [FINISH]
    return msgs


def calls(rows):
    return [r["meta"]["tool"] for r in rows]


def last_call(row):
    """The tool call this row teaches, decoded back from the canonical completion."""
    return row["completion"]


# ---------------------------------------------------------------- parsing
def test_parse_action_decodes_multiline_and_single_line_params():
    m = fn("str_replace_editor", command="str_replace", path="/p.py", old_str="a = 1", new_str="if x:\n    y")
    name, p = S.parse_action(m["content"])
    assert name == "str_replace_editor" and p == {"command": "str_replace", "path": "/p.py", "old_str": "a = 1", "new_str": "if x:\n    y"}
    assert S.parse_action("I think we are done.") is None
    assert S.parse_action(FINISH["content"]) == ("finish", {})


# ---------------------------------------------------------------- mapping of each action type
def test_happy_path_maps_every_action_type():
    conv = S.convert(happy(), TASK, files_of({"pkg/a.py": SRC}))
    assert conv.status == "kept" and conv.cut is None, (conv.reason, conv.cut)
    assert calls(conv.rows) == ["run_command", "read_file", "run_command", "write_file", "run_command", "submit_patch"]
    msgs = conv.messages
    tc = [m["tool_calls"][0]["function"] for m in msgs if m["role"] == "assistant"]
    # the harness's mandatory install call comes first (history only, never a training row)
    assert tc[0]["name"] == "run_skill_script" and json.loads(tc[0]["arguments"]) == {"file_path": "install.py", "skill_name": "swe-tools"}
    # execute_bash -> run_command, repo dir collapsed onto /workspace (our sandbox root)
    assert json.loads(tc[1]["arguments"]) == {"command": "grep -rn 'def foo' /workspace/pkg"}
    # view with range -> read_file with the same range, repo-relative path
    assert json.loads(tc[2]["arguments"]) == {"filepath": "pkg/a.py", "start_line": 1, "end_line": 3}
    # str_replace -> run_command with our edit.py SEARCH/REPLACE heredoc (whole lines)
    edit = json.loads(tc[3]["arguments"])["command"]
    assert edit == "python3 /tmp/swe/edit.py pkg/a.py <<'EOF'\n<<<<<<< SEARCH\n    return 1\n=======\n    return 2\n>>>>>>> REPLACE\nEOF"
    # create -> write_file; finish -> submit_patch()
    assert json.loads(tc[4]["arguments"]) == {"filepath": "check_foo.py", "content": "from pkg.a import foo\nprint(foo())\n"}
    assert tc[6]["name"] == "submit_patch" and json.loads(tc[6]["arguments"]) == {}


def _result(conv, k):
    """Decoded harness payload of the k-th teacher call's tool result (k=0 is the first call after install)."""
    tools = [m for m in conv.messages if m["role"] == "tool"]
    outer = json.loads(tools[k + 1]["content"])
    return json.loads(outer["result"])


def test_tool_results_use_the_harness_shapes():
    conv = S.convert(happy(), TASK, files_of({"pkg/a.py": SRC}))
    assert _result(conv, 0) == {"status": "ok", "stdout": "/workspace/pkg/a.py:1:def foo():\n", "stderr": "", "exit_code": 0}
    assert _result(conv, 1) == {"status": "ok", "filepath": "pkg/a.py", "content": "def foo():\n    return 1\n",
                                "start_line": 1, "end_line": 3, "total_lines": 7, "is_truncated": False}
    ed = _result(conv, 2)
    assert ed["status"] == "ok" and ed["exit_code"] == 0
    assert ed["stdout"].startswith("OK pkg/a.py: lines 2-2 replaced (1 -> 1 lines)\nNow:\n1| def foo():\n2|     return 2\n")   # real edit.py output
    assert _result(conv, 3) == {"status": "ok", "filepath": "check_foo.py", "size": len("from pkg.a import foo\nprint(foo())\n")}
    tools = [m for m in conv.messages if m["role"] == "tool"]
    assert tools[0]["content"] == S.INSTALL["result_content"]            # recorded verbatim from the harness


def test_failed_command_maps_to_command_error():
    oh = OH({"pkg/a.py": SRC})
    msgs = header() + oh.bash(f"python {WS}/x.py", "Traceback (most recent call last):\nValueError: boom", code=1) + [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/a.py": SRC}))
    r = _result(conv, 0)
    out = "Traceback (most recent call last):\nValueError: boom\n"
    assert r == {"status": "error", "error_type": "CommandError", "error_message": out,
                 "details": {"stdout": out, "stderr": "", "exit_code": 1}}


def test_partial_line_old_str_expands_to_whole_lines():
    oh = OH({"pkg/a.py": SRC})
    msgs = header() + oh.str_replace("pkg/a.py", "x + 1", "x + 2") + [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/a.py": SRC}))
    assert conv.cut is None
    cmd = json.loads([m for m in conv.messages if m["role"] == "assistant"][1]["tool_calls"][0]["function"]["arguments"])["command"]
    assert "<<<<<<< SEARCH\n    y = x + 1\n=======\n    y = x + 2\n>>>>>>> REPLACE" in cmd


def test_multiline_edit_and_line_deletion():
    oh = OH({"pkg/a.py": SRC})
    msgs = header() + oh.str_replace("pkg/a.py", "    y = x + 1\n", "") + [FINISH]   # delete a whole line
    conv = S.convert(msgs, TASK, files_of({"pkg/a.py": SRC}))
    assert conv.cut is None, conv.cut
    assert conv.final_files["pkg/a.py"] == SRC.replace("    y = x + 1\n", "")


def test_full_view_and_directory_view():
    oh = OH({"pkg/a.py": SRC})
    msgs = header() + oh.view("pkg/a.py")
    msgs += [fn("str_replace_editor", command="view", path=f"{WS}/pkg"),
             res("str_replace_editor", f"Here's the files and directories up to 2 levels deep in {WS}/pkg, excluding hidden items:\n{WS}/pkg\n{WS}/pkg/a.py\n")]
    msgs += [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/a.py": SRC}))
    tc = [json.loads(m["tool_calls"][0]["function"]["arguments"]) for m in conv.messages if m["role"] == "assistant"]
    assert tc[1] == {"filepath": "pkg/a.py"}
    assert _result(conv, 0)["content"] == SRC.rstrip("\n") and _result(conv, 0)["total_lines"] == 7
    assert tc[2] == {"command": "find /workspace/pkg -maxdepth 2 -not -path '*/\\.*'"}
    assert _result(conv, 1)["stdout"] == "/workspace/pkg\n/workspace/pkg/a.py\n"


# ---------------------------------------------------------------- rows
def test_rows_shape_meta_and_known_tools():
    conv = S.convert(happy(), TASK, files_of({"pkg/a.py": SRC}))
    for r in conv.rows:
        assert r["prompt"].startswith("<bos>") and r["completion"].startswith(EMPTY_THOUGHT)
        assert r["completion"].endswith("<|tool_response>") and "<|tool_call>call:" + r["meta"]["tool"] + "{" in r["completion"]
        assert r["meta"] == {"task": "o__r-1", "traj": "swegym|o__r-1", "stage": "fixer", "continuation": True, "tool": r["meta"]["tool"]}
        assert r["meta"]["tool"] in V.KNOWN_TOOLS
    # each prompt extends the previous one: row k sees exactly the k earlier teacher calls
    for a, b in zip(conv.rows, conv.rows[1:]):
        assert b["prompt"].startswith(a["prompt"][:-200])
    p0 = conv.rows[0]["prompt"]
    assert "Fix foo so it returns 2" in p0 and "install.py" in p0 and 'Your internal name is "fixer"' in p0
    for name in ("run_command", "read_file", "write_file", "submit_patch", "run_skill_script"):
        assert f"declaration:{name}" in p0
    assert "str_replace_editor" not in "".join(r["prompt"] + r["completion"] for r in conv.rows)
    assert "execute_bash" not in "".join(r["prompt"] + r["completion"] for r in conv.rows)
    assert RD not in "".join(r["prompt"] + r["completion"] for r in conv.rows)


def test_repo_dir_is_collapsed_inside_written_content_and_later_reads():
    oh = OH({"pkg/a.py": SRC})
    script = f"import sys\nsys.path.insert(0, '{WS}')\nprint(open('{WS}/pkg/a.py').read())\n"
    msgs = header() + oh.create("rep.py", script) + oh.view("rep.py") + oh.str_replace("rep.py", f"'{WS}/pkg/a.py'", f"'{WS}/pkg/b.py'")
    msgs += [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/a.py": SRC}))
    assert conv.cut is None and calls(conv.rows) == ["write_file", "read_file", "run_command", "submit_patch"]
    assert all(RD not in r["prompt"] + r["completion"] for r in conv.rows)
    assert conv.final_files["rep.py"] == "import sys\nsys.path.insert(0, '/workspace')\nprint(open('/workspace/pkg/b.py').read())\n"


def test_prose_and_continue_nudges_are_removed():
    oh = OH({"pkg/a.py": SRC})
    msgs = header() + [{"role": "assistant", "content": "I will now think about the problem."},
                       {"role": "user", "content": "Please continue working on the task on whatever approach you think is suitable.\n"}]
    msgs += oh.bash("ls", "pkg") + [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/a.py": SRC}))
    assert calls(conv.rows) == ["run_command", "submit_patch"] and conv.removed["text_only"] == 1
    assert "think about the problem" not in conv.rows[-1]["prompt"]


def test_editor_errors_are_removed_with_their_result():
    oh = OH({"pkg/a.py": SRC})
    msgs = header() + [fn("str_replace_editor", command="str_replace", path=f"{WS}/pkg/a.py", old_str="nope", new_str="x"),
                       res("str_replace_editor", f"ERROR:\nNo replacement was performed, old_str `nope` did not appear verbatim in {WS}/pkg/a.py.")]
    msgs += [fn("execute_bash", command="python x.py"),
             res("execute_bash", "[Runtime (ID=x)] Action execution failed: 504 Server Error\n[Error occurred in processing last action]")]
    msgs += oh.str_replace("pkg/a.py", "    return 1", "    return 2") + [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/a.py": SRC}))
    assert calls(conv.rows) == ["run_command", "submit_patch"]
    assert conv.removed == Counter({"editor_error": 1, "runtime_error": 1})


# ---------------------------------------------------------------- unmappable trajectories are dropped
@pytest.mark.parametrize("extra,reason", [
    ([fn("str_replace_editor", command="insert", path=f"{WS}/pkg/a.py", insert_line="1", new_str="x = 1"),
      res("str_replace_editor", "The file has been edited.")], "editor_insert"),
    ([fn("str_replace_editor", command="undo_edit", path=f"{WS}/pkg/a.py"), res("str_replace_editor", "Last edit undone.")], "editor_undo_edit"),
    ([fn("browser", code="goto('https://example.com')"), res("browser", "page")], "tool_browser"),
    ([fn("str_replace_editor", command="view", path="/testbed/pkg/a.py"), res("str_replace_editor", "Here's the result ...")], "path_outside_workspace"),
])
def test_unmappable_trajectories_are_dropped(extra, reason):
    oh = OH({"pkg/a.py": SRC})
    msgs = header() + oh.bash("ls", "pkg") + extra + [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/a.py": SRC}))
    assert conv.status == "dropped" and conv.reason == reason and conv.rows == []


def test_edit_of_a_protected_test_file_is_dropped():
    tsrc = "def test_foo():\n    assert foo() == 1\n"
    oh = OH({"pkg/a.py": SRC, "tests/test_a.py": tsrc})
    msgs = header() + oh.str_replace("tests/test_a.py", "== 1", "== 2") + [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/a.py": SRC, "tests/test_a.py": tsrc}))
    assert conv.status == "dropped" and conv.reason == "edit_protected_path"


def test_no_finish_and_non_python_are_dropped():
    oh = OH({"pkg/a.py": SRC})
    assert S.convert(header() + oh.bash("ls", "pkg"), TASK, files_of({})).reason == "no_finish"
    js = dict(TASK, patch="diff --git a/web/app.js b/web/app.js\n")
    assert S.convert(happy(), js, files_of({"pkg/a.py": SRC})).reason == "non_python"


# ---------------------------------------------------------------- fidelity cuts: later rows would rest on things our harness never shows
def test_output_over_the_harness_cap_strict_cuts_after_that_call():
    oh = OH({"pkg/a.py": SRC})
    msgs = header() + oh.bash("ls", "pkg") + oh.bash("pytest", "x" * 6000) + oh.bash("ls pkg", "a.py") + [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/a.py": SRC}), strict_caps=True)
    assert conv.status == "kept" and conv.cut == "cap_run_command"
    assert calls(conv.rows) == ["run_command", "run_command"]        # the capped call itself is still a valid action


def test_capped_output_is_shown_as_the_harness_truncates_it_and_conversion_goes_on():
    oh = OH({"pkg/a.py": SRC})
    msgs = header() + oh.bash("pytest", "x" * 6000) + oh.bash("ls pkg", "a.py") + [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/a.py": SRC}))
    assert conv.cut is None and calls(conv.rows) == ["run_command", "run_command", "submit_patch"]
    assert _result(conv, 0)["stdout"] == "x" * 5000 and conv.capped_rows == 1   # head only, no marker (harness)


def test_action_that_uses_the_hidden_part_of_a_capped_output_cuts_before_it():
    oh = OH({"pkg/a.py": SRC, "pkg/deep/z.py": "z = 1\n"})
    listing = "\n".join([f"{WS}/pkg/f{i:04d}.py" for i in range(400)] + [f"{WS}/pkg/deep/z.py"])   # z.py lies past 5,000 chars
    msgs = header() + oh.bash(f"find {WS}/pkg", listing) + oh.view("pkg/deep/z.py") + [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/a.py": SRC, "pkg/deep/z.py": "z = 1\n"}))
    assert conv.cut == "depends_on_truncated" and calls(conv.rows) == ["run_command"]


def test_long_file_view_shows_150_lines_and_an_edit_of_unseen_lines_cuts():
    big = "".join(f"x{i} = {i}\n" for i in range(200))
    oh = OH({"pkg/big.py": big})
    msgs = header() + oh.view("pkg/big.py") + oh.bash("ls", "pkg") + oh.str_replace("pkg/big.py", "x180 = 180", "x180 = -1") + [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/big.py": big}))
    assert calls(conv.rows) == ["read_file", "run_command"] and conv.cut == "depends_on_truncated"
    assert _result(conv, 0)["end_line"] == 150 and _result(conv, 0)["is_truncated"] is True
    strict = S.convert(msgs, TASK, files_of({"pkg/big.py": big}), strict_caps=True)
    assert strict.cut == "cap_read_file" and calls(strict.rows) == ["read_file"]


def test_clipped_view_is_not_a_divergence():
    big = "".join(f"value_{i} = {i}\n" for i in range(3000))
    shown = numbered(big.split("\n")[:1200], 1)
    shown = shown[:shown.rindex("\n") + 9] + "<response clipped><NOTE>To save on context only part of this file has been shown to you.</NOTE>"
    msgs = header() + [fn("str_replace_editor", command="view", path=f"{WS}/pkg/big.py"),
                       res("str_replace_editor", f"Here's the result of running `cat -n` on {WS}/pkg/big.py:\n{shown}")]
    msgs += OH.bash("ls", "pkg") + [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/big.py": big}))
    assert conv.cut is None and calls(conv.rows) == ["read_file", "run_command", "submit_patch"] and conv.capped_rows == 1


def test_edit_of_lines_shown_later_by_a_range_read_is_kept():
    big = "".join(f"x{i} = {i}\n" for i in range(200))
    oh = OH({"pkg/big.py": big})
    msgs = header() + oh.view("pkg/big.py") + oh.view("pkg/big.py", [175, 185]) + oh.str_replace("pkg/big.py", "x180 = 180", "x180 = -1") + [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/big.py": big}))
    assert conv.cut is None and calls(conv.rows) == ["read_file", "read_file", "run_command", "submit_patch"]


def test_view_that_disagrees_with_the_real_file_cuts():
    oh = OH({"pkg/a.py": SRC.replace("return 1", "return 7")})     # the environment had other content than base_commit
    msgs = header() + oh.view("pkg/a.py", [1, 3]) + oh.bash("ls", "pkg") + [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/a.py": SRC}))
    assert conv.cut == "fs_divergence" and calls(conv.rows) == ["read_file"]


def test_edit_that_edit_py_would_revert_is_cut_before_it():
    oh = OH({"pkg/a.py": SRC})
    msgs = header() + oh.bash("ls", "pkg") + oh.str_replace("pkg/a.py", "    return 1", "  return (") + [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/a.py": SRC}))
    assert conv.cut == "edit_mismatch" and calls(conv.rows) == ["run_command"]     # never teach the broken edit


def test_command_run_from_another_directory_cuts():
    oh = OH({"pkg/a.py": SRC})
    msgs = header() + oh.bash(f"cd {WS}/pkg", "", cwd=f"{WS}/pkg") + oh.bash("python a.py", "", cwd=f"{WS}/pkg") + [FINISH]
    conv = S.convert(msgs, TASK, files_of({"pkg/a.py": SRC}))
    assert conv.cut == "cwd_state" and calls(conv.rows) == ["run_command"]


# ---------------------------------------------------------------- build: matching, token cap, validation, determinism
def _parquet_rows():
    return [{"messages": happy()}, {"messages": header("Something else") + OH({}).bash("ls", "") + [FINISH]}]


def test_match_tasks_by_problem_statement_and_repo_dir():
    tasks = [TASK, dict(TASK, instance_id="o__r-2", problem_statement="Something else")]
    m = S.match_tasks([t["messages"] for t in _parquet_rows()], tasks)
    assert [t["instance_id"] if t else None for t in m] == ["o__r-1", "o__r-2"]


def test_ambiguous_match_breaks_ties_on_gold_patch_files():
    t1 = dict(TASK, instance_id="o__r-7", patch="diff --git a/pkg/other.py b/pkg/other.py\n")
    t2 = dict(TASK, instance_id="o__r-8")                                                  # its patch touches pkg/a.py
    m = S.match_tasks([happy()], [t1, t2])
    assert m[0]["instance_id"] == "o__r-8"


def test_build_token_cap_validation_and_determinism(tmp_path):
    tasks = [TASK, dict(TASK, instance_id="o__r-2", problem_statement="Something else")]
    trajs = [t["messages"] for t in _parquet_rows()]
    files = lambda task: files_of({"pkg/a.py": SRC})  # noqa: E731

    class CharTok:                         # stand-in for the Gemma tokenizer: 4 chars per token
        def encode(self, s, add_special_tokens=False):
            return type("E", (), {"ids": range(len(s) // 4)})()

    rows, rep = S.build(trajs, tasks, files, tok=CharTok(), max_tokens=10**9)
    assert rep["trajectories_in"] == 2 and rep["rows"] == len(rows) == 8 and rep["tool_mix"]["submit_patch"] == 2
    longest = max(len(r["prompt"]) + len(r["completion"]) for r in rows) // 4
    capped, rep2 = S.build(trajs, tasks, files, tok=CharTok(), max_tokens=longest - 1)
    assert len(capped) < len(rows) and rep2["rows_dropped"]["over_max_tokens"] == len(rows) - len(capped)
    out = tmp_path / "rows.jsonl"
    S.write_rows(rows, out)
    first = out.read_bytes()
    rows_again, _ = S.build(trajs, tasks, files, tok=CharTok(), max_tokens=10**9)
    S.write_rows(rows_again, out)
    assert out.read_bytes() == first                                   # byte-identical on a rerun
    v = V.validate(str(out), exclude=frozenset({"never-used"}), min_rows=1, tok=None)
    assert v["ok"], v["first_problems"]
    assert set(v["tools"]) <= V.KNOWN_TOOLS and set(v["stages"]) == {"fixer"}


def test_build_refuses_excluded_tasks():
    with pytest.raises(SystemExit):
        S.build([happy()], [TASK], lambda t: files_of({"pkg/a.py": SRC}), exclude=frozenset({"o__r-1"}))
