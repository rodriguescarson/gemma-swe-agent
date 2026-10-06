"""eval/locate_recall_heldout.py: file recall@k of the shipped locator (submissions/v5h2/.../locate.py) on heldout1k.

The query is a deterministic approximation of what prompts/locator.md tells the model to pass: identifiers, error text
and keywords from the issue, leaving out URLs, version numbers, environment dumps and doc links. Written before the
script (GAPS N1, 2026-10-06)."""
import importlib.util, io, json, subprocess, sys, tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "eval" / "locate_recall_heldout.py"
spec = importlib.util.spec_from_file_location("lrh", SCRIPT)
lrh = importlib.util.module_from_spec(spec); spec.loader.exec_module(lrh)

PATCH = """diff --git a/pkg/core.py b/pkg/core.py
--- a/pkg/core.py
+++ b/pkg/core.py
@@ -1 +1 @@
-x
+y
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-a
+b
diff --git a/pkg/new.py b/pkg/new.py
new file mode 100644
--- /dev/null
+++ b/pkg/new.py
@@ -0,0 +1 @@
+z
"""


def test_gold_files_all_and_py():
    assert lrh.gold_files(PATCH) == ["pkg/core.py", "README.md", "pkg/new.py"]
    assert lrh.gold_files(PATCH, py_only=True) == ["pkg/core.py", "pkg/new.py"]


def test_query_drops_urls_versions_env_and_doc_links():
    s = ("`Session.merge_environment_settings` raises KeyError\n\n"
         "See https://docs.example.org/en/latest/api.html and [docs](https://x.y/z).\n"
         "Python 3.11.4, requests==2.31.0, urllib3 2.0.7\n"
         "OS: Ubuntu 22.04\n"
         "```\nTraceback (most recent call last):\n  File \"/src/requests/sessions.py\", line 12, in merge_environment_settings\n"
         "KeyError: 'proxies'\n```\n")
    q = lrh.extract_query(s)
    for gone in ("http", "docs.example", "3.11", "2.31", "2.0.7", "22.04", "Ubuntu"):
        assert gone not in q, (gone, q)
    for kept in ("Session.merge_environment_settings", "KeyError", "merge_environment_settings", "sessions.py", "proxies"):
        assert kept in q, (kept, q)


def test_query_is_deterministic_bounded_and_identifiers_first():
    s = "Fix `iter_suppress` in more.py when StopIteration bubbles " + "lorem ipsum dolor " * 200
    q1, q2 = lrh.extract_query(s), lrh.extract_query(s)
    assert q1 == q2 and len(q1) <= lrh.MAX_QUERY_CHARS
    assert q1.split()[0] == "iter_suppress"
    assert len(set(q1.split())) == len(q1.split())  # no duplicate terms


def test_query_title_only_still_yields_keywords():
    q = lrh.extract_query("fix: adding persian names of months and month-abbreviations")
    assert "persian" in q and "months" in q and "fix" not in q.split()


def test_ranked_files_parses_locator_output():
    out = "workspace=/w symbols=9\n1. a/b.py  score=3.0\n     def f  L1-2\n2. tests/t.py [test]  score=1.0\n"
    assert lrh.ranked_files(out) == ["a/b.py", "tests/t.py"]


def test_recall_table_counts_misses():
    ranks = [1, 2, 4, 11, None]  # None = no .py gold file / not ranked
    r = lrh.recall(ranks, ks=(1, 3, 5, 10))
    assert r == {1: 0.2, 3: 0.4, 5: 0.6, 10: 0.6}


def _snapshot(tmp_path):
    src = tmp_path / "src"; (src / "repo" / ".git").mkdir(parents=True); (src / "repo" / "pkg").mkdir()
    (src / "repo" / "pkg" / "sessions.py").write_text("def merge_environment_settings(proxies):\n    return proxies['x']\n")
    (src / "repo" / "pkg" / "other.py").write_text("def unrelated():\n    return 1\n")
    tgz = tmp_path / "snaps" / "t1.tgz"; tgz.parent.mkdir()
    with tarfile.open(tgz, "w:gz") as tf:
        tf.add(src / "repo", arcname=".")
    return tgz.parent


def test_end_to_end_on_tiny_snapshot(tmp_path):
    snaps = _snapshot(tmp_path)
    patch = "--- a/pkg/sessions.py\n+++ b/pkg/sessions.py\n@@ -1 +1 @@\n-a\n+b\n"
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(json.dumps(dict(instance_id="t1", repo="o/r", patch=patch, statement_title_only=False,
                                     problem_statement="KeyError in merge_environment_settings with proxies")) + "\n")
    out = tmp_path / "rows.jsonl"
    r = subprocess.run([sys.executable, str(SCRIPT), "--tasks", str(tasks), "--snapshots", str(snaps), "--out", str(out),
                        "--tmp", str(tmp_path / "work"), "--jobs", "1"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    row = json.loads(out.read_text().splitlines()[0])
    assert row["id"] == "t1" and row["rank_query"] == 1 and row["secs_query"] >= 0
    assert "rank_raw" in row and row["n_gold_py"] == 1
    assert not any((tmp_path / "work").iterdir())  # extraction dirs cleaned up


def test_repo_template_lines_are_dropped():
    tmpl = "Thank you for taking the time to improve Arrow!\nBefore submitting, check the appropriate boxes"
    tasks = [dict(repo="o/r", problem_statement=f"Issue {i}: widget_{i} breaks\n{tmpl}") for i in range(6)]
    boiler = lrh.boilerplate_lines(tasks)
    q = lrh.extract_query(tasks[0]["problem_statement"], boiler.get("o/r"))
    assert "widget_0" in q and "Arrow" not in q and "submitting" not in q
    # a line that is not repeated across the repo's statements survives
    assert "breaks" in q
