"""v12b_ctx end to end in the REAL Evaluator (scripts/run_eval.py, compaction at 14,336 tokens) with a scripted model:
a compaction forced after the edit removes the task message from the next request, and the issue pinned in the system
instruction is still there, injected from session state (no literal placeholder). The task resolves."""
import json
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v10_support import sandbox as S  # noqa: E402
from v10_support.mock_llm import MockLLM, cmd, heredoc, submit, text  # noqa: E402

pytest.importorskip("swegemma.evaluate")
ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "submissions" / "v12b_ctx"
TID = "calc_ctx_1"
FILES = {
    "calc/__init__.py": "",
    "calc/ops.py": 'def add(a, b):\n    """Add two numbers."""\n    return a - b\n',
    "tests/__init__.py": "",
    "tests/test_ops.py": "from calc.ops import add\n\n\ndef test_zero():\n    assert add(0, 0) == 0\n",
}
TEST_PATCH = ("--- a/tests/test_ops.py\n+++ b/tests/test_ops.py\n@@ -3,3 +3,7 @@ from calc.ops import add\n"
              " \n def test_zero():\n     assert add(0, 0) == 0\n+\n+\n+def test_add():\n+    assert add(2, 3) == 5\n")
GOLD = ("--- a/calc/ops.py\n+++ b/calc/ops.py\n@@ -1,3 +1,3 @@\n def add(a, b):\n     \"\"\"Add two numbers.\"\"\"\n"
        "-    return a - b\n+    return a + b\n")
STATEMENT = "calc.ops.add subtracts instead of adding: add(2, 3) returns -1 where 5 is expected (marker Q7Z-ctx)."
SCRIPT = {"swe_single_agent": [
    cmd('git grep -n "def add" -- "*.py" | head -n 20'),
    {"tool": "read_file", "args": {"filepath": "calc/ops.py", "start_line": 1, "end_line": 3}},
    {"tool": "edit_file", "args": {"filepath": "calc/ops.py", "old_string": "    return a - b",
                                   "new_string": "    return a + b"}, "ptok": 15000},   # forces the next compaction
    heredoc("python3 -", "from calc.ops import add\nassert add(2, 3) == 5\nprint('ok')\n"),
    submit(),
    text("Fixed add."),
]}


def system_text(body):
    return "".join(m.get("content") if isinstance(m.get("content"), str) else json.dumps(m.get("content"))
                   for m in body.get("messages") or [] if m.get("role") == "system")


def user_texts(body):
    return [m.get("content") if isinstance(m.get("content"), str) else json.dumps(m.get("content"))
            for m in body.get("messages") or [] if m.get("role") == "user"]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    root = tmp_path_factory.mktemp("ctx")
    repo = root / "repo"
    repo.mkdir()
    S.write_tree(repo, FILES)
    S.git_init(repo)
    snaps = root / "snapshots"
    snaps.mkdir()
    with tarfile.open(snaps / f"{TID}.tgz", "w:gz") as tf:
        tf.add(repo, arcname=".")
    row = {"instance_id": TID, "repo": "synthetic/calc", "base_commit": "0" * 40, "patch": GOLD,
           "test_patch": TEST_PATCH, "problem_statement": STATEMENT, "hints_text": "",
           "created_at": "2026-10-29T00:00:00Z"}
    (root / "tasks.jsonl").write_text(json.dumps(row) + "\n")
    bundle = S.copy_bundle(root / "bundle", BUNDLE)
    with MockLLM() as mock:
        api = mock.add_route("ctx", SCRIPT)
        r = S.run_eval_cli(bundle=bundle, tasks=root / "tasks.jsonl", snapshots=snaps, results=root / "res",
                           api_base=api, task_ids=[TID], timeout=420)
        return r, mock.log("ctx")


def test_the_forced_compaction_ran_and_the_task_resolved(run):
    r, log = run
    assert r.rows and r.rows[0].get("resolved") is True, (r.rc, r.rows, r.stderr[-2000:])
    assert sum(e["kind"] == "summarizer" for e in log) >= 1, [e["kind"] for e in log]


def test_the_issue_is_in_every_agent_request_and_injected(run):
    _, log = run
    agent = [e for e in log if e["kind"] == "agent"]
    assert len(agent) >= 5
    for e in agent:
        sy = system_text(e["body"])
        assert STATEMENT in sy, e["step"]
        assert "{problem_description" not in sy


def test_after_the_compaction_only_the_pin_carries_the_issue(run):
    _, log = run
    i = next(n for n, e in enumerate(log) if e["kind"] == "summarizer")
    before = [e for e in log[:i] if e["kind"] == "agent"]
    after = [e for e in log[i + 1:] if e["kind"] == "agent"]
    assert before and after
    assert any(STATEMENT in u for u in user_texts(before[0]["body"]))          # the task message, before
    assert not any("Problem Statement:" in u for u in user_texts(after[0]["body"]))   # compacted away
    assert STATEMENT in system_text(after[0]["body"])                            # the pin survives
