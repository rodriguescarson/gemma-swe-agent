"""scripts/run_eval.py --patches: the scorer's own verification on listed patches (the grader behind the label audit).

A synthetic task (a calc package whose add() subtracts) goes through the REAL swegemma Evaluator, subprocess sandbox and
verify_task in a child process; nothing is mocked and no model is involved. A correct patch resolves, a wrong one, an
empty one, one that does not apply and one that only edits the protected hidden test do not; a repeated (task, patch)
is graded once; a "free" task (hidden tests pass on the unpatched base) resolves with an empty patch unless the run also
errored, in which case the scorer never runs the tests; resume, the workspace cache and the parsing helpers are checked."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v10_support import sandbox as S  # noqa: E402

pytest.importorskip("swegemma.evaluate")
ROOT = Path(__file__).resolve().parents[1]
RUN_EVAL = ROOT / "scripts" / "run_eval.py"
TID = "calc_replay_1"
FREE = "calc_replay_free"            # the hidden test passes on the unpatched base
FILES = {
    "calc/__init__.py": "",
    "calc/ops.py": 'def add(a, b):\n    """Add two numbers."""\n    return a - b\n',
    "tests/__init__.py": "",
    "tests/test_ops.py": "from calc.ops import add\n\n\ndef test_zero():\n    assert add(0, 0) == 0\n",
}
TEST_PATCH = ("--- a/tests/test_ops.py\n+++ b/tests/test_ops.py\n@@ -3,3 +3,7 @@ from calc.ops import add\n"
              " \n def test_zero():\n     assert add(0, 0) == 0\n+\n+\n+def test_add():\n+    assert add(2, 3) == 5\n")
TEST_PATCH_FREE = TEST_PATCH.replace("def test_add():\n+    assert add(2, 3) == 5", "def test_zero_again():\n+    assert add(0, 0) == 0")
TIMEOUT = "Agent exceeded session timeout (5.0 min)"
GOLD = ("--- a/calc/ops.py\n+++ b/calc/ops.py\n@@ -1,3 +1,3 @@\n def add(a, b):\n     \"\"\"Add two numbers.\"\"\"\n"
        "-    return a - b\n+    return a + b\n")
WRONG = GOLD.replace("+    return a + b", "+    return a * b")
NOT_APPLYING = GOLD.replace("-    return a - b", "-    return a // b")        # context that is not in the file
EDITS_THE_TEST = ("--- a/tests/test_ops.py\n+++ b/tests/test_ops.py\n@@ -1,5 +1,5 @@\n from calc.ops import add\n \n \n"
                  " def test_zero():\n-    assert add(0, 0) == 0\n+    assert True\n")
ENTRIES = [
    {"task": TID, "cfg": "good", "patch": GOLD},                      # 0
    {"task": TID, "cfg": "wrong", "patch": WRONG},                    # 1
    {"task": TID, "cfg": "empty", "patch": ""},                       # 2
    {"task": TID, "cfg": "good-again", "patch": GOLD},                # 3: same (task, patch) as 0
    {"task": TID, "cfg": "stale", "patch": NOT_APPLYING},             # 4
    {"task": TID, "cfg": "test-edit", "patch": EDITS_THE_TEST},       # 5: the hidden test is protected
    {"task": "no_such_task", "cfg": "ghost", "patch": GOLD},          # 6
    {"task": FREE, "cfg": "free-empty", "patch": ""},                 # 7: resolves with nothing changed
    {"task": FREE, "cfg": "free-empty-timeout", "patch": "", "agent_error": TIMEOUT},     # 8: never tested, unresolved
    {"task": FREE, "cfg": "free-patch-timeout", "patch": WRONG, "agent_error": TIMEOUT},  # 9: a patch is still graded
]


def _load_module():
    spec = importlib.util.spec_from_file_location("run_eval_under_test", RUN_EVAL)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _make_world(root: Path, tarball=True):
    repo = root / "repo"
    repo.mkdir()
    S.write_tree(repo, FILES)
    S.git_init(repo)
    snaps = root / "snapshots"
    snaps.mkdir()
    if tarball:
        with tarfile.open(snaps / f"{TID}.tgz", "w:gz") as tf:
            tf.add(repo, arcname=".")
    rows = [{"instance_id": TID, "repo": "synthetic/calc", "base_commit": "0" * 40, "patch": GOLD, "test_patch": TEST_PATCH,
             "problem_statement": "calc.ops.add subtracts instead of adding", "hints_text": "",
             "created_at": "2026-10-30T00:00:00Z"}]
    rows.append({**rows[0], "instance_id": FREE, "test_patch": TEST_PATCH_FREE})
    (root / "tasks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    if tarball:
        shutil.copy(snaps / f"{TID}.tgz", snaps / f"{FREE}.tgz")
    return repo, snaps


def _run(root: Path, snaps: Path, entries, name="res", env_extra=None, extra_args=(), timeout=600):
    pf = root / f"{name}_patches.json"
    pf.write_text(json.dumps(entries))
    res = root / name
    sbx = root / f"{name}_sbx"
    sbx.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k.startswith(("PATH", "HOME", "LANG", "LC_", "VIRTUAL_ENV"))}
    env.update({"TMPDIR": str(sbx), "PYTHONDONTWRITEBYTECODE": "1", **(env_extra or {})})
    argv = [sys.executable, str(RUN_EVAL), "--patches", str(pf), "eval", "--tasks", str(root / "tasks.jsonl"),
            "--snapshots-dir", str(snaps), "--results-dir", str(res), "--display", "quiet", *extra_args]
    p = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    rows_path = res / "replay_results.jsonl"
    rows = [json.loads(x) for x in rows_path.read_text().splitlines()] if rows_path.is_file() else []
    return p, rows, res


@pytest.fixture(scope="module")
def graded(tmp_path_factory):
    root = tmp_path_factory.mktemp("replay")
    _, snaps = _make_world(root)
    p, rows, res = _run(root, snaps, ENTRIES)
    return root, snaps, p, rows, res


def test_one_row_per_entry_in_entry_order_with_the_labels(graded):
    _, _, p, rows, _ = graded
    assert p.returncode == 0, p.stderr[-2000:]
    assert [r["idx"] for r in rows] == list(range(len(ENTRIES)))
    assert [r["cfg"] for r in rows] == [e["cfg"] for e in ENTRIES]
    assert [r["task"] for r in rows] == [e["task"] for e in ENTRIES]


def test_the_correct_patch_resolves_and_the_wrong_ones_do_not(graded):
    _, _, _, rows, _ = graded
    good, wrong, empty = rows[0], rows[1], rows[2]
    assert good["resolved"] is True and good["test_exit_code"] == 0 and good["phase"] == "tests"
    assert good["test_summary"] == "2 passed" and good["failed"] == [] and good["error"] is None
    assert wrong["resolved"] is False and wrong["test_exit_code"] == 1 and wrong["phase"] == "tests"
    assert wrong["failed"] == ["tests/test_ops.py::test_add"] and "assert" in wrong["test_tail"]
    assert wrong["test_summary"] == "1 failed, 1 passed"
    assert empty["resolved"] is False and empty["phase"] == "tests" and empty["patch_len"] == 0


def test_a_patch_that_does_not_apply_is_an_unresolved_verdict_not_a_missing_one(graded):
    _, _, _, rows, _ = graded
    r = rows[4]
    assert r["resolved"] is False and r["phase"] == "patch_apply" and r["error"].startswith("Failed to apply agent patch")


def test_editing_the_protected_hidden_test_gains_nothing(graded):
    _, _, _, rows, _ = graded
    r = rows[5]
    assert r["resolved"] is False and r["phase"] == "tests" and r["failed"] == ["tests/test_ops.py::test_add"]


def test_an_unknown_task_has_no_verdict(graded):
    _, _, _, rows, _ = graded
    r = rows[6]
    assert r["resolved"] is None and r["phase"] == "infra" and "no_such_task" in r["error"]


def test_a_repeated_task_and_patch_is_graded_once(graded):
    _, _, _, rows, _ = graded
    again = rows[3]
    assert again["dedup_of"] == 0 and again["resolved"] is True and again["cfg"] == "good-again"
    assert again["secs"] == rows[0]["secs"] and again["patch_sha1"] == rows[0]["patch_sha1"]
    assert all("dedup_of" not in rows[i] for i in (0, 1, 2, 4, 5, 6, 7, 8, 9))


def test_a_free_task_resolves_empty_unless_the_run_errored(graded):
    _, _, _, rows, _ = graded
    free, errored, patched = rows[7], rows[8], rows[9]
    assert free["resolved"] is True and free["phase"] == "tests" and free["test_summary"] == "2 passed"
    assert errored["resolved"] is False and errored["phase"] == "agent_error" and errored["test_exit_code"] == -1
    assert errored["error"] == TIMEOUT and errored["agent_error"] == TIMEOUT and errored["patch_len"] == 0
    assert patched["phase"] == "tests" and patched["resolved"] is True and patched["agent_error"] == TIMEOUT   # graded, not penalised


def test_dedupe_off_grades_every_entry(graded):
    root, snaps, *_ = graded
    entries = [ENTRIES[0], {**ENTRIES[0], "cfg": "good-again"}]
    p, rows, _ = _run(root, snaps, entries, name="nodedupe", env_extra={"G4_REPLAY_DEDUPE": "0"})
    assert p.returncode == 0, p.stderr[-2000:]
    assert [r["resolved"] for r in rows] == [True, True] and all("dedup_of" not in r for r in rows)


def test_resume_keeps_finished_rows_and_reruns_only_the_rest(graded):
    root, snaps, _, rows, res = graded
    first = [{**ENTRIES[0]}, {**ENTRIES[1]}]
    p, rows1, res1 = _run(root, snaps, first, name="resume")
    assert p.returncode == 0 and [r["resolved"] for r in rows1] == [True, False]
    p, rows2, _ = _run(root, snaps, first + [ENTRIES[2]], name="resume", env_extra={"G4_REPLAY_RESUME": "1"})
    assert p.returncode == 0, p.stderr[-2000:]
    assert [r.get("resumed") for r in rows2] == [True, True, None]
    assert [r["resolved"] for r in rows2] == [True, False, False]


def test_the_workspace_cache_stands_in_for_the_tarball(tmp_path):
    repo, snaps = _make_world(tmp_path, tarball=False)                 # no <task>.tgz anywhere
    cache = tmp_path / "wscache"
    (cache / TID).mkdir(parents=True)
    subprocess.run(["cp", "-R", str(repo), str(cache / TID / "base")], check=True)
    entries = [ENTRIES[0], ENTRIES[1]]
    p, rows, _ = _run(tmp_path, snaps, entries, env_extra={"G4_WS_CACHE": str(cache)})
    assert p.returncode == 0, p.stderr[-2000:]
    assert [r["resolved"] for r in rows] == [True, False]
    assert (snaps / f"{TID}.tgz").exists()                              # the empty placeholder the harness looks for
    assert not (cache / TID / "base" / "calc" / "__pycache__").exists()    # the cache is never written to
    assert "return a - b" in (cache / TID / "base" / "calc" / "ops.py").read_text()


def test_without_the_cache_or_a_tarball_the_row_says_so(tmp_path):
    _, snaps = _make_world(tmp_path, tarball=False)
    p, rows, _ = _run(tmp_path, snaps, [ENTRIES[0]])
    assert p.returncode == 0 and rows[0]["resolved"] is None and rows[0]["phase"] == "infra"
    assert "Snapshot file not found" in rows[0]["error"]


def test_load_patches_accepts_json_jsonl_and_id(tmp_path):
    m = _load_module()
    f = tmp_path / "a.json"
    f.write_text(json.dumps([{"id": "t1", "cfg": "c", "patch": "p"}, {"task": " t2 ", "patch": None}]))
    assert m.load_patches(f) == [{"task": "t1", "cfg": "c", "patch": "p", "agent_error": None},
                                 {"task": "t2", "cfg": None, "patch": "", "agent_error": None}]
    g = tmp_path / "b.jsonl"
    g.write_text('{"task": "t1", "cfg": 3, "patch": "x"}\n\n{"task": "t2", "patch": "y"}\n')
    assert [e["task"] for e in m.load_patches(g)] == ["t1", "t2"] and m.load_patches(g)[0]["cfg"] == 3


@pytest.mark.parametrize("body", ["[]", "{}", "not json", '[1]', '[{"patch": "x"}]', '[{"task": "t", "patch": 5}]',
                                  '[{"task": "t", "patch": "", "agent_error": 3}]'])
def test_load_patches_rejects_malformed_files(tmp_path, body):
    f = tmp_path / "bad.json"
    f.write_text(body)
    with pytest.raises(SystemExit):
        _load_module().load_patches(f)


def test_pop_option_handles_both_spellings_and_leaves_the_rest():
    m = _load_module()
    a = ["--patches", "x.json", "eval", "--k", "v"]
    assert m.pop_option(a, "--patches") == "x.json" and a == ["eval", "--k", "v"]
    b = ["eval", "--patches=y.json"]
    assert m.pop_option(b, "--patches") == "y.json" and b == ["eval"]
    assert m.pop_option(["eval"], "--patches") is None


def test_patches_and_oracle_are_exclusive():
    with pytest.raises(SystemExit):
        _load_module().main(["--oracle", "--patches", "x.json", "eval"])


def test_replay_row_phases_and_summary_parsing():
    m = _load_module()

    class R:
        resolved, test_exit_code, error = False, 1, None
        test_output = ("STDOUT:\n..F\nFAILED tests/t.py::test_a - assert 1 == 2\nERROR tests/t.py::test_b\n"
                       "1 failed, 1 error, 3 passed in 0.42s\nSTDERR:\n")

    row = m.replay_row(3, {"task": "t", "cfg": "c", "patch": "d"}, R, 1.26)
    assert row["failed"] == ["tests/t.py::test_a", "tests/t.py::test_b"] and row["test_summary"] == "1 failed, 1 error, 3 passed"
    assert row["phase"] == "tests" and row["secs"] == 1.3 and row["timed_out"] is False
    R.test_exit_code = 124
    assert m.replay_row(0, {"task": "t", "cfg": None, "patch": ""}, R, 0)["timed_out"] is True
    R.test_exit_code, R.error = -1, "Evaluation error: boom"
    infra = m.replay_row(0, {"task": "t", "cfg": None, "patch": ""}, R, 0)
    assert infra["phase"] == "infra" and infra["resolved"] is None
    R.test_exit_code, R.error = 1, "Failed to apply agent patch: x"
    assert m.replay_row(0, {"task": "t", "cfg": None, "patch": ""}, R, 0)["phase"] == "patch_apply"
    R.test_exit_code, R.error = -1, "Agent exceeded session timeout"
    stop = m.replay_row(0, {"task": "t", "cfg": None, "patch": "", "agent_error": R.error}, R, 0)
    assert stop["phase"] == "agent_error" and stop["resolved"] is False
