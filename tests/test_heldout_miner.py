"""heldout_miner: metadata-only schema, dedupe vs existing ids + public set, exclusions, disk floor, batch cleanup,
diff splitting, junit parsing and the FAIL_TO_PASS / PASS_TO_PASS verdict (fake git / gh / pytest throughout)."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "pallets"))
import heldout_miner as m  # noqa: E402

SRC_DIFF = """diff --git a/src/pkg/core.py b/src/pkg/core.py
index 111..222 100644
--- a/src/pkg/core.py
+++ b/src/pkg/core.py
@@ -1,2 +1,2 @@
 def f():
-    return 1
+    return 2
"""
TEST_DIFF = """diff --git a/tests/test_core.py b/tests/test_core.py
index 333..444 100644
--- a/tests/test_core.py
+++ b/tests/test_core.py
@@ -1,2 +1,4 @@
 from pkg.core import f
+def test_f():
+    assert f() == 2
"""
DOC_DIFF = """diff --git a/CHANGES.rst b/CHANGES.rst
index 555..666 100644
--- a/CHANGES.rst
+++ b/CHANGES.rst
@@ -1 +1,2 @@
 Changes
+- fixed f
"""
BIN_DIFF = """diff --git a/src/pkg/logo.png b/src/pkg/logo.png
index 777..888 100644
Binary files a/src/pkg/logo.png and b/src/pkg/logo.png differ
"""


def _cand(**kw):
    c = dict(repo="python-attrs/attrs", base_commit="b" * 40, fix_commit="abcdef1" + "0" * 33, pr_number=7,
             created_at="2024-01-01T00:00:00Z", merged_at="2024-01-02T00:00:00Z", title="Fix f",
             body="f returned 1 instead of 2 when called without arguments.", patch=SRC_DIFF, test_patch=TEST_DIFF,
             test_files=["tests/test_core.py"])
    c.update(kw)
    return c


# ------------------------------------------------------------------ path classes and diff split
@pytest.mark.parametrize("path,kind", [
    ("tests/test_core.py", "test"), ("src/pkg/tests/test_x.py", "test"), ("testing/test_y.py", "test"),
    ("pkg/test_z.py", "test"), ("pkg/z_test.py", "test"), ("tests/conftest.py", "test"),
    ("tests/data/fixture.json", "test"), ("src/pkg/testing.py", "src"), ("src/pkg/core.py", "src"),
    ("pyproject.toml", "src"), ("setup.py", "src"), ("docs/index.rst", "doc"), ("CHANGES.rst", "doc"),
    ("README.md", "doc"), ("changelog.d/123.change.md", "doc"), (".github/workflows/ci.yml", "doc"),
    ("tox.ini", "doc"), ("src/blib2to3/Grammar.txt", "src"),
])
def test_classify_path(path, kind):
    assert m.classify_path(path) == kind


def test_split_diff_drops_docs_and_separates_tests():
    s = m.split_diff(SRC_DIFF + DOC_DIFF + TEST_DIFF)
    assert s["patch"] == SRC_DIFF and s["test_patch"] == TEST_DIFF
    assert s["src_files"] == ["src/pkg/core.py"] and s["test_files"] == ["tests/test_core.py"]
    assert s["dropped"] == ["CHANGES.rst"] and not s["binary"]


def test_split_diff_flags_binary():
    assert m.split_diff(SRC_DIFF + BIN_DIFF + TEST_DIFF)["binary"]


def test_candidate_filter_reasons():
    ok = m.split_diff(SRC_DIFF + TEST_DIFF)
    assert m.reject_reason(ok, pr_files={"src/pkg/core.py", "tests/test_core.py"}) is None
    assert m.reject_reason(m.split_diff(SRC_DIFF), pr_files={"src/pkg/core.py"}) == "no_test_change"
    assert m.reject_reason(m.split_diff(TEST_DIFF), pr_files={"tests/test_core.py"}) == "no_src_change"
    assert m.reject_reason(m.split_diff(SRC_DIFF + BIN_DIFF + TEST_DIFF), pr_files=None) == "binary"
    # the merge commit's diff does not match the PR's file list: a rebase-merge whose last commit is only part of it
    assert m.reject_reason(ok, pr_files={"src/pkg/core.py", "tests/test_core.py", "src/pkg/other.py"}) == "files_mismatch"
    big = m.split_diff(SRC_DIFF.replace("+    return 2\n", "".join(f"+    x{i} = {i}\n" for i in range(500))) + TEST_DIFF)
    assert m.reject_reason(big, pr_files=None) == "src_too_big"


# ------------------------------------------------------------------ dedupe, exclusions, ids
def _known(tmp_path):
    pal = tmp_path / "pallets.jsonl"
    pal.write_text(json.dumps({"instance_id": "click_abc1234", "repo": "pallets/click", "fix_commit": "abc1234" + "0" * 33}) + "\n")
    pub = tmp_path / "public.jsonl"
    pub.write_text(json.dumps({"instance_id": "rich_3063", "repo": "Textualize/rich"}) + "\n"
                   + json.dumps({"instance_id": "starlette_1", "repo": "encode/starlette-public-test"}) + "\n")
    out = tmp_path / "out.jsonl"
    out.write_text(json.dumps({"instance_id": "attrs_1111111", "repo": "python-attrs/attrs",
                               "fix_commit": "1111111" + "0" * 33}) + "\n")
    return m.load_known(pallets=pal, public=pub, out=out)


def test_known_index_merges_all_sources(tmp_path):
    k = _known(tmp_path)
    assert {"click_abc1234", "rich_3063", "attrs_1111111"} <= k.ids
    assert ("pallets/click", "abc1234" + "0" * 33) in k.fixes
    # every repo of the public set is excluded, plus the fixed list (fastapi, rich, requests, httpx)
    assert {"fastapi/fastapi", "textualize/rich", "psf/requests", "encode/httpx",
            "encode/starlette-public-test"} <= k.excluded_repos


@pytest.mark.parametrize("repo", ["fastapi/fastapi", "Textualize/rich", "psf/requests", "encode/httpx",
                                  "TEXTUALIZE/RICH"])
def test_excluded_repo_refused(tmp_path, repo):
    with pytest.raises(m.ExcludedRepo):
        m.check_repo_allowed(repo, _known(tmp_path))


def test_dedupe(tmp_path):
    k = _known(tmp_path)
    assert m.is_duplicate(_cand(repo="pallets/click", fix_commit="abc1234" + "0" * 33), k)
    assert m.is_duplicate(_cand(fix_commit="1111111" + "f" * 33), k)        # same instance_id as an existing row
    assert not m.is_duplicate(_cand(), k)
    assert m.instance_id("python-attrs/attrs", "abcdef1" + "0" * 33) == "attrs_abcdef1"


# ------------------------------------------------------------------ statements
def test_statement_title_only_flag():
    text, title_only = m.statement("Fix f", "")
    assert text == "Fix f\n\n" and title_only
    text, title_only = m.statement("Fix f", "Fixes #12")
    assert title_only                                   # body is only an issue reference
    text, title_only = m.statement("Fix f", "f returned 1 instead of 2 when called without arguments.")
    assert not title_only and text.startswith("Fix f\n\nf returned")


# ------------------------------------------------------------------ junit + verdict
JUNIT = """<?xml version="1.0"?><testsuites><testsuite>
<testcase classname="tests.test_core" name="test_f" />
<testcase classname="tests.test_core.TestG" name="test_g[a b]"><failure message="x"/></testcase>
<testcase classname="tests.test_core" name="test_h"><skipped/></testcase>
<testcase classname="tests.test_core" name="test_e"><error message="boom"/></testcase>
</testsuite></testsuites>"""


def test_parse_junit_nodeids():
    out = m.parse_junit(JUNIT, ["tests/test_core.py"])
    assert out == {"tests/test_core.py::test_f": "passed", "tests/test_core.py::TestG::test_g[a b]": "failed",
                   "tests/test_core.py::test_h": "skipped", "tests/test_core.py::test_e": "error"}


def _run(outcomes, rc=None, timed_out=False, secs=1.0):
    if rc is None:
        rc = 0 if all(v in ("passed", "skipped") for v in outcomes.values()) and outcomes else 1
    return {"rc": rc, "outcomes": outcomes, "timed_out": timed_out, "secs": secs, "harness_junit_ok": rc == 0}


def test_judge_valid_and_lists():
    base = _run({"t::a": "passed", "t::b": "failed", "t::c": "error"})
    gold = _run({"t::a": "passed", "t::b": "passed", "t::c": "passed", "t::d": "skipped"})
    v = m.judge(base, gold, gold)
    assert v["valid"] and v["reason"] == "valid"
    assert v["FAIL_TO_PASS"] == ["t::b", "t::c"] and v["PASS_TO_PASS"] == ["t::a"]


def test_judge_collection_error_at_base_counts_as_fail():
    base = _run({"tests/test_core.py": "error"}, rc=2)        # module failed to import: no per-test rows
    gold = _run({"t::a": "passed", "t::b": "passed"})
    v = m.judge(base, gold, gold)
    assert v["valid"] and v["FAIL_TO_PASS"] == ["t::a", "t::b"] and v["PASS_TO_PASS"] == []


@pytest.mark.parametrize("base,g1,g2,reason", [
    (_run({"t::a": "passed"}), _run({"t::a": "passed"}), _run({"t::a": "passed"}), "no_fail_to_pass"),
    (_run({"t::a": "failed"}), _run({"t::a": "failed"}), _run({"t::a": "failed"}), "gold_fails"),
    (_run({"t::a": "failed"}), _run({"t::a": "passed"}), _run({"t::a": "failed"}), "gold_flaky"),
    (_run({"t::a": "failed"}), _run({"t::a": "passed"}, timed_out=True, rc=-9), None, "gold_timeout"),
    (_run({"t::a": "failed"}), _run({}, rc=5), None, "gold_no_tests"),
    (_run({"t::a": "failed"}), _run({"t::a": "passed"}, secs=200), _run({"t::a": "passed"}), "gold_slow"),
    (_run({"t::a": "failed", "t::p": "passed"}), _run({"t::a": "passed", "t::p": "passed"}),
     _run({"t::a": "passed", "t::p": "passed"}) | {"harness_junit_ok": False}, "harness_junit_reject"),
])
def test_judge_rejections(base, g1, g2, reason):
    v = m.judge(base, g1, g2)
    assert not v["valid"] and v["reason"] == reason


# ------------------------------------------------------------------ metadata-only row
def test_make_row_schema_is_metadata_only():
    verdict = {"valid": True, "reason": "valid", "FAIL_TO_PASS": ["t::b"], "PASS_TO_PASS": ["t::a"],
               "base": _run({"t::b": "failed"}), "gold": [_run({"t::b": "passed"})] * 2}
    env = {"python": "3.12.11", "deps": ["pytest==8.4.2"], "env_id": "attrs-0"}
    row = m.make_row(_cand(), verdict, env)
    assert tuple(row) == m.SCHEMA_KEYS
    assert row["instance_id"] == "attrs_abcdef1" and row["statement_title_only"] is False
    assert row["problem_statement"].startswith("Fix f\n\n") and row["FAIL_TO_PASS"] == ["t::b"]
    assert row["env"]["python"] == "3.12.11"
    # nothing big or local: no paths into the scratch dir, no snapshot/venv blobs
    blob = json.dumps(row)
    assert "scratch" not in blob and "snapshot" not in blob and len(blob) < 20000


def test_append_rows_dedupes_again(tmp_path):
    out = tmp_path / "tasks.jsonl"
    k = m.Known(ids=set(), fixes=set(), excluded_repos=set(m.EXCLUDED_REPOS))
    row = {"instance_id": "attrs_abcdef1", "repo": "python-attrs/attrs", "fix_commit": "f" * 40}
    assert m.append_rows(out, [row, dict(row)], k) == 1
    assert m.append_rows(out, [row], k) == 0
    assert len(out.read_text().splitlines()) == 1


# ------------------------------------------------------------------ disk floor + batch cleanup
def test_disk_floor_stops(tmp_path):
    with pytest.raises(m.DiskFloor):
        m.require_disk(tmp_path, floor_gb=8, free_fn=lambda p: 7.9)
    assert m.require_disk(tmp_path, floor_gb=8, free_fn=lambda p: 12.0) == 12.0


def test_batch_dir_cleaned_on_success_and_error(tmp_path):
    with m.batch_dir(tmp_path, "b0") as d:
        (d / "venv").mkdir()
        (d / "venv" / "big").write_bytes(b"x" * 1000)
    assert not (tmp_path / "b0").exists()
    with pytest.raises(RuntimeError):
        with m.batch_dir(tmp_path, "b1") as d:
            (d / "wt").mkdir()
            raise RuntimeError("boom")
    assert not (tmp_path / "b1").exists()


def test_run_batches_stops_cleanly_at_disk_floor_and_cleans(tmp_path):
    cands = [_cand(fix_commit=f"{i:07x}" + "0" * 33) for i in range(1, 7)]
    out = tmp_path / "tasks.jsonl"
    k = m.Known(ids=set(), fixes=set(), excluded_repos=set(m.EXCLUDED_REPOS))
    free = iter([20.0, 20.0, 5.0])                # third batch check is under the floor
    seen_dirs = []

    def validate_batch(batch, bdir):
        seen_dirs.append(bdir)
        (bdir / "venv").mkdir()
        assert bdir.exists()
        good = {"valid": True, "reason": "valid", "FAIL_TO_PASS": ["t::a"], "PASS_TO_PASS": [],
                "base": _run({"t::a": "failed"}), "gold": [_run({"t::a": "passed"})] * 2}
        env = {"python": "3.12", "deps": [], "env_id": "x"}
        return [(c, good if i % 2 == 0 else dict(good, valid=False, reason="gold_fails"), env)
                for i, c in enumerate(batch)]

    stats = m.run_batches(cands, validate_batch, out_path=out, scratch=tmp_path / "scratch", known=k,
                          batch_size=2, floor_gb=8, free_fn=lambda p: next(free))
    assert stats["stopped"] == "disk_floor" and stats["batches"] == 2
    assert stats["validated"] == 2 and stats["reasons"] == {"valid": 2, "gold_fails": 2}
    assert all(not d.exists() for d in seen_dirs)
    rows = [json.loads(ln) for ln in out.read_text().splitlines()]
    assert [r["instance_id"] for r in rows] == ["attrs_0000001", "attrs_0000003"]
    assert all(tuple(r) == m.SCHEMA_KEYS for r in rows)


def test_run_batches_skips_duplicates_and_respects_target(tmp_path):
    cands = [_cand(fix_commit=f"{i:07x}" + "0" * 33) for i in range(1, 6)]
    k = m.Known(ids={"attrs_0000001"}, fixes=set(), excluded_repos=set(m.EXCLUDED_REPOS))
    got = []

    def validate_batch(batch, bdir):
        got.extend(c["fix_commit"][:7] for c in batch)
        ok = {"valid": True, "reason": "valid", "FAIL_TO_PASS": ["t::a"], "PASS_TO_PASS": [],
              "base": _run({"t::a": "failed"}), "gold": [_run({"t::a": "passed"})] * 2}
        return [(c, ok, {"python": "3.12", "deps": [], "env_id": "x"}) for c in batch]

    stats = m.run_batches(cands, validate_batch, out_path=tmp_path / "t.jsonl", scratch=tmp_path / "s", known=k,
                          batch_size=2, floor_gb=8, free_fn=lambda p: 50.0, target=2)
    assert "0000001" not in got and stats["validated"] == 2 and stats["stopped"] == "target"


# ------------------------------------------------------------------ gh: modest pagination, rate limit
def test_gh_rate_limit_raises():
    def fake(cmd, **kw):
        return SimpleNamespace(returncode=1, stdout="", stderr="HTTP 403: API rate limit exceeded for user")
    with pytest.raises(m.RateLimited):
        m.gh_json(["pr", "list"], runner=fake)


def test_list_merged_prs_args_and_since_filter():
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        rows = [{"number": 2, "title": "b", "body": "", "mergedAt": "2024-05-01T00:00:00Z", "createdAt": "2024-04-01T00:00:00Z",
                 "mergeCommit": {"oid": "c" * 40}, "baseRefName": "main", "files": [{"path": "a.py"}]},
                {"number": 1, "title": "a", "body": "", "mergedAt": "2019-01-01T00:00:00Z", "createdAt": "2019-01-01T00:00:00Z",
                 "mergeCommit": {"oid": "d" * 40}, "baseRefName": "main", "files": []}]
        return SimpleNamespace(returncode=0, stdout=json.dumps(rows), stderr="")
    prs = m.list_merged_prs("python-attrs/attrs", limit=300, since="2021-01-01", runner=fake)
    assert [p["number"] for p in prs] == [2] and prs[0]["files"] == {"a.py"}
    cmd = calls[0]
    assert cmd[:3] == ["gh", "pr", "list"] and "--limit" in cmd and int(cmd[cmd.index("--limit") + 1]) <= 1000
    assert "merged" in cmd


# ------------------------------------------------------------------ harness fidelity
def test_harness_pytest_ini_matches_swegemma():
    from swegemma.harness import container_setup as cs
    import inspect
    src = inspect.getsource(cs.setup_workspace_test_config)
    assert m.HARNESS_PYTEST_INI in src.replace('content = """', "").replace('"""\n    try:', "")


def test_pytest_cmd_is_grader_line(tmp_path):
    cmd = m.pytest_cmd(tmp_path / "venv", ["tests/test_core.py"], tmp_path / "j.xml")
    assert "-m pytest tests/test_core.py" in cmd and "-p no:anyio" in cmd and "-o timeout=0" in cmd
    assert 'python_classes="Test* *Test"' in cmd and "PYTHONSAFEPATH=1" in cmd and " -s -m pytest" in cmd


def test_real_git_validate_one_end_to_end(tmp_path):
    """A tiny real git repo through validate_one with the real pytest of this venv (no network)."""
    repo = tmp_path / "r"
    (repo / "src" / "pkg").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "pkg" / "__init__.py").write_text("")
    (repo / "src" / "pkg" / "core.py").write_text("def f():\n    return 1\n")
    (repo / "tests" / "test_core.py").write_text("from pkg.core import f\n\n\ndef test_keep():\n    assert f() in (1, 2)\n")
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(repo)]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(g + ["add", "-A"], check=True)
    subprocess.run(g + ["commit", "-qm", "base"], check=True)
    base = subprocess.run(g + ["rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (repo / "src" / "pkg" / "core.py").write_text("def f():\n    return 2\n")
    (repo / "tests" / "test_core.py").write_text((repo / "tests" / "test_core.py").read_text()
                                                 + "\n\ndef test_f():\n    assert f() == 2\n")
    subprocess.run(g + ["commit", "-qam", "fix"], check=True)
    fix = subprocess.run(g + ["rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    diff = subprocess.run(g + ["diff", base, fix], capture_output=True, text=True).stdout
    s = m.split_diff(diff)
    cand = _cand(base_commit=base, fix_commit=fix, patch=s["patch"], test_patch=s["test_patch"],
                 test_files=s["test_files"])
    venv = Path(sys.executable).parent.parent
    v = m.validate_one(cand, clone=repo, venv=venv, work=tmp_path / "wt", timeout=60)
    assert v["valid"], v
    assert v["FAIL_TO_PASS"] == ["tests/test_core.py::test_f"]
    assert v["PASS_TO_PASS"] == ["tests/test_core.py::test_keep"]
    assert not (tmp_path / "wt" / m.instance_id(cand["repo"], fix)).exists()      # worktree removed after the task


def test_parse_junit_masks_memory_addresses():
    """parametrize ids that embed object reprs differ per process; they must not make a stable test look flaky."""
    xml1 = '<testsuite><testcase classname="tests.test_a" name="test_x[&lt;object at 0x10a2b3c4&gt;]"/></testsuite>'
    xml2 = '<testsuite><testcase classname="tests.test_a" name="test_x[&lt;object at 0x7f00aa11&gt;]"/></testsuite>'
    a, b = m.parse_junit(xml1, ["tests/test_a.py"]), m.parse_junit(xml2, ["tests/test_a.py"])
    assert a == b == {"tests/test_a.py::test_x[<object at 0x?>]": "passed"}
    g = _run(a)
    assert m.judge(_run({}, rc=2), g, _run(b))["valid"]


def test_worktree_submodules_are_initialised(tmp_path):
    """tomlkit keeps its conformance suite in a git submodule (tests/toml-test): a worktree must get it from the clone."""
    sub = tmp_path / "sub"
    sub.mkdir()
    g = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "protocol.file.allow=always"]
    subprocess.run(["git", "init", "-q", str(sub)], check=True)
    (sub / "case.toml").write_text("a = 1\n")
    subprocess.run(g + ["-C", str(sub), "add", "-A"], check=True)
    subprocess.run(g + ["-C", str(sub), "commit", "-qm", "s"], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    subprocess.run(g + ["-C", str(clone), "submodule", "add", "-q", str(sub), "tests/suite"], check=True)
    subprocess.run(g + ["-C", str(clone), "commit", "-qm", "base"], check=True)
    m.init_submodules(clone)                                        # once per clone (network in real runs)
    head = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    ws = tmp_path / "wt"
    m.git(clone, "worktree", "add", "--detach", "-f", str(ws), head)
    assert not (ws / "tests" / "suite" / "case.toml").exists()
    m.init_submodules(ws, reference=clone)
    assert (ws / "tests" / "suite" / "case.toml").read_text() == "a = 1\n"


def test_repo_cfg_era_deps_present():
    assert "mock" in m.REPO_CFG["httpie/cli"]["deps"]
    assert "pyrsistent" in m.REPO_CFG["python-jsonschema/jsonschema"]["deps"]
    assert "msgspec" in m.REPO_CFG["python-attrs/cattrs"]["deps"]
    assert "pylama" not in m.REPO_CFG["PyCQA/isort"]["deps"]       # its pytest plugin needs pkg_resources


def test_progress_keeps_rounds_and_repo_totals(tmp_path):
    out = tmp_path / "tasks.jsonl"
    out.write_text("".join(json.dumps({"repo": r, "statement_title_only": t}) + "\n"
                           for r, t in [("a/x", True), ("a/x", False), ("b/y", False)]))
    recs = [{"repo": "a/x", "round": 1, "prs": 10, "candidates": 5, "validated": 1, "reasons": {"gold_fails": 4}},
            {"repo": "a/x", "round": 2, "prs": 10, "candidates": 5, "validated": 1, "reasons": {"valid": 1}}]
    p = tmp_path / "PROGRESS.md"
    m.write_progress(p, recs, out)
    text = p.read_text()
    assert "| a/x | 2 | 1/2 |" in text and "| b/y | 1 | 0/1 |" in text     # per-repo totals from tasks.jsonl
    assert text.count("| a/x | 1 |") == 1 and "| a/x | 2 | 10 |" in text    # both rounds kept
    assert "**3**" in text


def test_instance_id_uses_package_name_for_generic_repo_names():
    assert m.instance_id("httpie/cli", "abcdef1" + "0" * 33) == "httpie_abcdef1"


def test_gh_retries_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    seq = iter([SimpleNamespace(returncode=1, stdout="", stderr="HTTP 502: 502 Bad Gateway"),
                SimpleNamespace(returncode=0, stdout="[1]", stderr="")])
    assert m.gh_json(["pr", "list"], runner=lambda cmd, **kw: next(seq)) == [1]


def test_gh_5xx_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    calls = []

    def fake(cmd, **kw):
        calls.append(1)
        return SimpleNamespace(returncode=1, stdout="", stderr="HTTP 502: 502 Bad Gateway")
    with pytest.raises(RuntimeError):
        m.gh_json(["pr", "list"], runner=fake)
    assert len(calls) == 3


def test_judge_drops_wall_clock_node_ids():
    """marshmallow parametrizes with dt.datetime.now(): the id changes every second, so base and gold never share it
    and it would be a fake FAIL_TO_PASS. Ids that embed the run's date are volatile and kept out of both lists."""
    base = _run({"t::x[07:10:11 2026-10-05]": "passed", "t::real": "failed", "t::keep[2020-01-01]": "passed"})
    gold = _run({"t::x[07:10:12 2026-10-05]": "passed", "t::real": "passed", "t::keep[2020-01-01]": "passed"})
    v = m.judge(base, gold, gold, today="2026-10-05")
    assert v["valid"] and v["FAIL_TO_PASS"] == ["t::real"] and v["PASS_TO_PASS"] == ["t::keep[2020-01-01]"]
    only_clock = _run({"t::x[07:10:12 10-05-2026]": "passed"})
    v = m.judge(_run({"t::x[07:10:11 10-05-2026]": "passed"}), only_clock, only_clock, today="2026-10-05")
    assert not v["valid"] and v["reason"] == "no_fail_to_pass"


def test_judge_wall_clock_ids_do_not_make_gold_flaky():
    g1 = _run({"t::x[07:10:12 2026-10-05]": "passed", "t::real": "passed"})
    g2 = _run({"t::x[07:10:13 2026-10-05]": "passed", "t::real": "passed"})
    v = m.judge(_run({"t::real": "failed"}), g1, g2, today="2026-10-05")
    assert v["valid"] and v["FAIL_TO_PASS"] == ["t::real"]


# ------------------------------------------------------------------ coverage steering (train/task_coverage.py)
def test_gap_score_counts_gap_tags_hit():
    c = _cand(test_patch=TEST_DIFF.replace("+    assert f() == 2\n",
                                           "+    with pytest.raises(ValueError):\n+        f(datetime.now())\n"))
    tg = m.candidate_tags(c)
    assert "datetime" in tg and "negative_route" in tg
    assert m.gap_score(tg, gaps={"datetime", "regex"}) == 1 + m.NEG_ROUTE_BONUS
    assert m.gap_score({"zero_empty"}, gaps={"datetime"}) == 0


def test_prioritize_puts_gap_hitting_candidates_first():
    plain = _cand(fix_commit="1" * 40)
    dt = _cand(fix_commit="2" * 40, test_patch=TEST_DIFF + "+from datetime import timedelta\n")
    out = m.prioritize([plain, dt], gaps={"datetime"})
    assert [c["fix_commit"][0] for c in out] == ["2", "1"]
    assert out[0]["gap_score"] >= 1 and out[1]["gap_score"] == 0


def test_repo_cap_limits_the_repo_target(tmp_path):
    out = tmp_path / "t.jsonl"
    out.write_text("".join(json.dumps({"repo": "a/x", "instance_id": f"x_{i}"}) + "\n" for i in range(115)))
    assert m.repo_budget("a/x", out, global_left=400, cap=120) == 5
    assert m.repo_budget("b/y", out, global_left=7, cap=120) == 7
    assert m.repo_budget("a/x", out, global_left=400, cap=100) == 0


def test_progress_reports_tags_added(tmp_path):
    out = tmp_path / "tasks.jsonl"
    out.write_text(json.dumps({"repo": "a/x", "statement_title_only": False}) + "\n")
    recs = [{"repo": "a/x", "round": 4, "prs": 1, "candidates": 1, "validated": 1, "reasons": {},
             "tags_added": {"datetime": 3, "regex": 1}}]
    m.write_progress(tmp_path / "P.md", recs, out)
    assert "datetime 3, regex 1" in (tmp_path / "P.md").read_text()


def test_auto_deps_reads_pyproject_groups_and_requirement_files(tmp_path):
    (tmp_path / "pyproject.toml").write_text('''
[project]
name = "pkg"
dependencies = ["six>=1"]
[project.optional-dependencies]
tests = ["pytest==7.0", "freezegun>=1.0", "pkg[extra]"]
docs = ["sphinx"]
[dependency-groups]
test = ["hypothesis", {include-group = "lint"}]
dev = ["pytest-mock"]
lint = ["ruff"]
''')
    (tmp_path / "requirements").mkdir()
    (tmp_path / "requirements" / "tests.txt").write_text("-r base.txt\n-e .\n# c\npytz==2024.1  # tz\npluggy<1\n")
    deps = m.auto_deps(tmp_path, own="pkg")
    assert {"six>=1", "freezegun>=1.0", "hypothesis", "pytest-mock", "pytz==2024.1"} <= set(deps)
    assert not any(d.split("[")[0].split("=")[0].split("<")[0].strip().lower() in ("pytest", "pluggy", "pkg", "sphinx", "ruff")
                   for d in deps)


def test_auto_deps_without_metadata_is_empty(tmp_path):
    assert m.auto_deps(tmp_path, own="x") == []


def test_new_coverage_repos_have_package_names():
    assert m.instance_id("cpburnz/python-pathspec", "a" * 40) == "pathspec_aaaaaaa"
    assert m.instance_id("rspeer/python-ftfy", "a" * 40) == "ftfy_aaaaaaa"
    assert m.own_package("jpadilla/pyjwt") == "PyJWT"
    assert m.own_package("pytoolz/toolz") == "toolz"


def test_tags_added_counts_only_new_rows(tmp_path):
    out = tmp_path / "t.jsonl"
    old = {"instance_id": "a_1", "repo": "a/x", "patch": "", "test_patch": "+from datetime import date\n",
           "problem_statement": "x", "statement_title_only": True}
    new = dict(old, instance_id="a_2", test_patch="+import re\n+re.compile('x')\n")
    out.write_text(json.dumps(old) + "\n" + json.dumps(new) + "\n")
    got = m.tags_added(out, before_ids={"a_1"})
    assert got.get("regex") == 1 and "datetime" not in got


def test_auto_deps_reads_tox_testenv_deps_and_common_test_libs(tmp_path):
    (tmp_path / "tox.ini").write_text("""[tox]
envlist = py3
[testenv]
deps =
    -rrequirements.txt
    parameterized
    mock>=4
    pytest-cov
    {py37}: oldthing
commands = pytest
[testenv:docs]
deps = sphinx
""")
    deps = m.auto_deps(tmp_path, own="dateparser")
    assert "parameterized" in deps and "mock>=4" in deps and "pytest-cov" in deps
    assert "sphinx" not in deps and not any("oldthing" in d or d.startswith("-r") for d in deps)
    assert set(m.COMMON_TEST_DEPS) <= set(m.auto_deps(tmp_path / "missing", own="x", common=True))


def test_venv_deps_merges_auto_and_repo_extras(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "tenacity"\ndependencies = []\n'
                                             '[project.optional-dependencies]\ntest = ["tornado>=6"]\n')
    own, deps = m.venv_deps("jd/tenacity", tmp_path)
    assert own == "tenacity" and "tornado>=6" in deps and {"six", "typeguard"} <= set(deps)
    own, deps = m.venv_deps("python-attrs/attrs", tmp_path)          # hand-written config wins, no auto deps
    assert own == "attrs" and deps == m.REPO_CFG["python-attrs/attrs"]["deps"]


@pytest.mark.parametrize("toml,path", [
    ('[tool.hatch.build.hooks.vcs]\nversion-file = "src/pkg/version.py"\n', "src/pkg/version.py"),
    ('[tool.setuptools_scm]\nwrite_to = "src/pkg/_version.py"\n', "src/pkg/_version.py"),
    ('[tool.setuptools_scm]\nversion_file = "pkg/_version.py"\n', "pkg/_version.py"),
])
def test_scm_version_file_written_like_pip_install_e(tmp_path, toml, path):
    """hatch-vcs / setuptools-scm generate a gitignored version module at install time; the grader's
    `pip install -e` creates it, a bare checkout does not."""
    (tmp_path / "pyproject.toml").write_text(toml)
    (tmp_path / path).parent.mkdir(parents=True)
    assert m.write_scm_version_file(tmp_path) == [path]
    ns = {}
    exec((tmp_path / path).read_text(), ns)
    assert ns["__version__"] == ns["version"] and ns["__version_tuple__"][0] == 0
    assert m.write_scm_version_file(tmp_path) == []          # never overwrites an existing file


def test_scm_version_file_noop_without_config(tmp_path):
    assert m.write_scm_version_file(tmp_path) == []
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert m.write_scm_version_file(tmp_path) == []


def test_make_row_records_prep():
    verdict = {"valid": True, "reason": "valid", "FAIL_TO_PASS": ["t::b"], "PASS_TO_PASS": [], "prep": ["src/p/version.py"],
               "base": _run({"t::b": "failed"}), "gold": [_run({"t::b": "passed"})] * 2}
    row = m.make_row(_cand(), verdict, {"python": "3.12", "deps": [], "env_id": "x"})
    assert row["validation"]["prep"] == ["src/p/version.py"]
