"""scripts/ladder/snapshot_hook.py (budget ladder, 2026-11-07) against the installed swegemma classes: a real
SubprocessManager sandbox, a real git repository tagged _swegemma_baseline, the real SwegemmaContext.check_budget.

It must record the tree at the start of every counted tool call (k = calls completed), skip uncounted calls (get_status),
strip protected test files the way the harness's fallback diff does, mark an unchanged tree as `same`, and never stage
anything in the agent's own git index."""
import importlib.util, json, pathlib, time, types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "ladder" / "snapshot_hook.py"

swegemma = pytest.importorskip("swegemma")


def _hook():
    spec = importlib.util.spec_from_file_location("snapshot_hook_t", HOOK)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_hook_records_each_counted_call_and_leaves_the_agent_index_alone(tmp_path):
    from swegemma.budget import EvaluationBudget
    from swegemma.context import SwegemmaContext
    from swegemma.sandbox.subprocess import SubprocessManager

    out = tmp_path / "snapshots.jsonl"
    m = SubprocessManager(timeout_seconds=60, system_site_packages=True)
    m.initialize({"pkg/mod.py": "def f():\n    return 1\n", "tests/test_mod.py": "def test_f():\n    assert 1\n"})
    sid = m._default_sandbox_id
    r = m.exec(sid, "cd /workspace && git init -q && git add -A && git -c user.email=a@b -c user.name=t commit -qm base"
                    " && git tag -f _swegemma_baseline")
    assert r.exit_code == 0, r.stderr
    task = types.SimpleNamespace(instance_id="t1", repo="x/y", problem_statement="p", hints_text="", test_files=["tests/test_mod.py"])
    ctx = SwegemmaContext(docker_manager=m, container_id=sid, task=task, budget=EvaluationBudget(time_minutes=8, tool_calls=40))
    ctx.agent_start_time = time.perf_counter()
    orig = SwegemmaContext.check_budget
    try:
        _hook().install(str(out))
        assert ctx.check_budget() is None                       # call 1 starts: tree == baseline
        m.exec(sid, "cd /workspace && python3 -c \"import pathlib;p=pathlib.Path('pkg/mod.py');p.write_text(p.read_text().replace('return 1','return 2'))\"")
        assert ctx.check_budget() is None                       # call 2 starts: edit 1
        m.exec(sid, "cd /workspace && echo x > new.py && echo y >> tests/test_mod.py")
        assert ctx.check_budget(count_tool_call=False) is None  # get_status: not counted, no row
        assert ctx.check_budget() is None                       # call 3 starts: edit 1 + new file; the test edit is stripped
        assert ctx.check_budget() is None                       # call 4 starts: unchanged -> same
    finally:
        SwegemmaContext.check_budget = orig
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert [x["k"] for x in rows] == [0, 1, 2, 3]
    assert rows[0]["patch"] == "" and "return 2" in rows[1]["patch"]
    assert "new.py" in rows[2]["patch"] and "test_mod" not in rows[2]["patch"] and rows[3].get("same")
    assert all("dt" in x and x["dt"] >= 0 for x in rows)
    assert not (tmp_path / "snapshots.jsonl.err").exists()
    st = m.exec(sid, "cd /workspace && git status --short").stdout
    assert "?? new.py" in st and "A  new.py" not in st and " A new.py" not in st


def test_a_failing_snapshot_is_logged_and_never_breaks_the_call(tmp_path):
    from swegemma.context import SwegemmaContext
    out = tmp_path / "snapshots.jsonl"
    orig = SwegemmaContext.check_budget
    calls = []
    SwegemmaContext.check_budget = lambda self, *, count_tool_call=True: calls.append(count_tool_call)
    try:
        _hook().install(str(out))
        broken = types.SimpleNamespace(docker=None, container_id=None, task=None, tool_calls_used=0, agent_elapsed_seconds=0.0)
        SwegemmaContext.check_budget(broken)
    finally:
        SwegemmaContext.check_budget = orig
    assert calls == [True]
    assert (tmp_path / "snapshots.jsonl.err").read_text().strip()


def test_a_same_size_edit_in_the_index_second_is_seen(tmp_path):
    """Git trusts a matching stat unless the entry is "racy" (mtime not older than the index file). Pin the file and the index
    to one timestamp (core.checkStat minimal and trustctime off leave only size and mtime seconds), make a same-size edit in place
    and restore the file's mtime: the stat then matches the index entry exactly, so only the racy re-read can see the edit. A plain `cp` of the index (new mtime) missed it; `cp -p` keeps it racy."""
    from swegemma.budget import EvaluationBudget
    from swegemma.context import SwegemmaContext
    from swegemma.sandbox.subprocess import SubprocessManager

    out = tmp_path / "snapshots.jsonl"
    m = SubprocessManager(timeout_seconds=60, system_site_packages=True)
    m.initialize({"pkg/mod.py": "def f():\n    return 1\n"})
    sid = m._default_sandbox_id
    stamp = "202601010000.00"
    r = m.exec(sid, "cd /workspace && git init -q && git add -A && git -c user.email=a@b -c user.name=t commit -qm base"
                    " && git tag -f _swegemma_baseline && git config core.checkStat minimal && git config core.trustctime false"
                    " && touch -t %s pkg/mod.py && git update-index -q --really-refresh"
                    " && touch -t %s .git/index" % (stamp, stamp))
    assert r.exit_code == 0, r.stderr
    # in place (same inode), same size, then the old mtime back: only the racy re-read can see this edit
    r = m.exec(sid, "cd /workspace && python3 -c \"import pathlib;p=pathlib.Path('pkg/mod.py');p.write_text(p.read_text().replace('return 1','return 2'))\""
                    " && touch -t %s pkg/mod.py" % stamp)
    assert r.exit_code == 0, r.stderr
    task = types.SimpleNamespace(instance_id="t2", repo="x/y", problem_statement="p", hints_text="", test_files=[])
    ctx = SwegemmaContext(docker_manager=m, container_id=sid, task=task, budget=EvaluationBudget(time_minutes=8, tool_calls=40))
    ctx.agent_start_time = time.perf_counter()
    orig = SwegemmaContext.check_budget
    try:
        _hook().install(str(out))
        assert ctx.check_budget() is None
    finally:
        SwegemmaContext.check_budget = orig
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(rows) == 1 and "return 2" in rows[0]["patch"], rows
