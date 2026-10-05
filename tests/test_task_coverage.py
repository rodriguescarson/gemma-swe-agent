"""train/task_coverage.py: tag every task with coverage dimensions read from its patch, test_patch and statement, so
mining can target gaps (Carson 2026-10-05: edge cases, positive/negative routes, zero states, multi-states,
behaviours). Written before the tagger."""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "train"))


def _t(patch="", test_patch="", statement="Fix x", **kw):
    return dict({"instance_id": "t", "repo": "o/r", "patch": patch, "test_patch": test_patch, "problem_statement": statement}, **kw)


def test_negative_route_and_edge_and_zero_state():
    import task_coverage as C
    tp = "+    with pytest.raises(ValueError):\n+        f(None)\n+    assert f([]) == []\n+    assert f(0) == 0\n"
    tags = C.tags(_t(patch="--- a/m.py\n+++ b/m.py\n@@\n-x\n+y\n", test_patch=tp))
    assert {"negative_route", "edge_none", "zero_empty"} <= tags


def test_positive_only_and_multi_file_multi_function_and_new_api():
    import task_coverage as C
    patch = ("--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,4 @@ def f():\n-x\n+y\n+def g():\n+    pass\n"
             "--- a/b.py\n+++ b/b.py\n@@ -5 +5 @@ def h():\n-x\n+y\n")
    tags = C.tags(_t(patch=patch, test_patch="+    assert f(2) == 3\n"))
    assert {"positive_only", "multi_file", "multi_function", "new_api"} <= tags and "negative_route" not in tags


def test_state_async_cli_unicode_and_title_only():
    import task_coverage as C
    tp = "+    obj.reset()\n+    obj.add(1)\n+    assert obj.count == 1\n+async def test_x():\n+    await f()\n+runner.invoke(cli, ['--x'])\n+    assert f('é') == 1\n"
    tags = C.tags(_t(test_patch=tp, statement="Fix it\n\nFixes #12", statement_title_only=True))
    assert {"stateful", "async", "cli", "unicode", "title_only"} <= tags


def test_report_counts_and_gaps(tmp_path):
    rows = [_t(test_patch="+    assert f(1) == 2\n", instance_id=f"t{i}") for i in range(5)]
    rows.append(_t(test_patch="+    with pytest.raises(KeyError):\n+        f()\n", instance_id="t9"))
    p = tmp_path / "tasks.jsonl"; p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = tmp_path / "cov.json"
    r = subprocess.run([sys.executable, str(ROOT / "train" / "task_coverage.py"), str(p), "--out", str(out), "--min-share", "0.3"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    assert rep["n"] == 6 and rep["counts"]["positive_only"] == 5 and rep["counts"]["negative_route"] == 1
    assert "negative_route" in rep["gaps"] and "positive_only" not in rep["gaps"]
