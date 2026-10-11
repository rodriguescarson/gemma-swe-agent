"""scripts/a6000/backup_captures.py: the interval backup of a collection run (captures + per-item results) to a private Kaggle
dataset, written before the code (2026-10-11, while p3_think ran with nothing but P2_LOG leaving the box)."""
import gzip, importlib.util, json, os, pathlib, stat, subprocess, sys, tarfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _mod(name="backup_captures"):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "a6000" / f"{name}.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def _run(tmp_path, partial=True, n=3):
    run = tmp_path / "p3_x"; run.mkdir()
    lines = [json.dumps({"t": i, "body": {"messages": [{"role": "user", "content": "x" * 50}]}, "response": {"id": i}}) for i in range(n)]
    data = "".join(l + "\n" for l in lines) + ('{"t": 99, "body": {"partial' if partial else "")
    (run / "capture.jsonl").write_text(data)
    (run / "proxy.jsonl").write_text('{"call": 1}\n{"call": 2}\n')
    (run / "ARM").write_text("v12"); (run / "ids.txt").write_text("a\nb\n"); (run / "items.jsonl").write_text('{"task": "a"}\n')
    it = run / "items" / "v12" / "task_a"; it.mkdir(parents=True)
    (it / "task_results.jsonl").write_text('{"task_id": "a", "solved": true}\n')
    (it / "patches").mkdir(); (it / "patches" / "a.patch").write_text("--- a\n+++ b\n")
    (it / "logs").mkdir(); (it / "logs" / "container.log").write_text("noise\n")
    (it / "traces").mkdir(); (it / "traces" / "a.json").write_text("{}")
    big = it / "big.bin"; big.write_bytes(b"\0" * (9 * 1024 * 1024))
    (run / "items" / "v12" / "task_a.out").write_text("ok\n")
    return run, lines


def test_snapshot_keeps_only_complete_lines(tmp_path):
    B = _mod(); run, lines = _run(tmp_path, partial=True)
    n, nbytes = B.snapshot_gz(run / "capture.jsonl", tmp_path / "capture.jsonl.gz")
    assert n == 3
    got = gzip.open(tmp_path / "capture.jsonl.gz", "rt").read()
    assert got == "".join(l + "\n" for l in lines)              # the partial last line is left out: json.loads works on every line
    assert nbytes == len(got.encode())
    assert all(json.loads(l) for l in got.splitlines())
    # no newline at all -> nothing (the whole file is one partial line)
    (tmp_path / "half.jsonl").write_text('{"x": 1')
    assert B.snapshot_gz(tmp_path / "half.jsonl", tmp_path / "half.gz") == (0, 0)


def test_item_files_follow_the_backup_results_rules(tmp_path):
    B = _mod(); run, _ = _run(tmp_path)
    rel = B.item_files(run)
    assert "items/v12/task_a/task_results.jsonl" in rel and "items/v12/task_a/patches/a.patch" in rel and "items/v12/task_a.out" in rel
    assert not any("/logs/" in r or "/traces/" in r for r in rel)           # container logs and P3 traces stay on the box
    assert "items/v12/task_a/big.bin" not in rel                            # > 8 MB


def test_stage_writes_the_dataset_directory_and_manifest(tmp_path):
    B = _mod(); run, lines = _run(tmp_path)
    out = tmp_path / "ds"
    man = B.stage(run, out, "owner", "g4-x")
    names = sorted(os.listdir(out))
    assert names == sorted(["ARM", "MANIFEST.json", "capture.jsonl.gz", "dataset-metadata.json", "ids.txt", "items.jsonl", "items.tar.gz", "proxy.jsonl.gz"])
    meta = json.load(open(out / "dataset-metadata.json"))
    assert meta["id"] == "owner/g4-x" and meta["title"] == "g4-x"
    assert man["captures"] == {"capture.jsonl.gz": {"lines": 3, "bytes": len("".join(l + "\n" for l in lines).encode())}}
    assert man["capture_lines"] == 3 and man["items"] == 3 and man["run"] == str(run)
    assert set(man["files"]) == set(names) - {"MANIFEST.json", "dataset-metadata.json"}
    assert all(set(v) == {"bytes", "sha256"} for v in man["files"].values())
    with tarfile.open(out / "items.tar.gz") as t:
        assert sorted(t.getnames()) == ["items/v12/task_a.out", "items/v12/task_a/patches/a.patch", "items/v12/task_a/task_results.jsonl"]
    # multi-pass layout: every capture_s<k>.jsonl is snapshotted
    (run / "capture_s2.jsonl").write_text('{"t": 1}\n')
    man2 = B.stage(run, tmp_path / "ds2", "owner", "g4-x")
    assert set(man2["captures"]) == {"capture.jsonl.gz", "capture_s2.jsonl.gz"} and man2["capture_lines"] == 4


def test_changed_compares_lines_and_items():
    B = _mod()
    man = {"capture_lines": 10, "items": 4}
    assert B.changed(None, man)
    assert not B.changed({"capture_lines": 10, "items": 4}, man)
    assert B.changed({"capture_lines": 9, "items": 4}, man) and B.changed({"capture_lines": 10, "items": 3}, man)


def test_alive_uses_the_pgrep_result():
    B = _mod()
    assert B.autopilot_alive(lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "10 python autopilot.py\n", ""))
    assert not B.autopilot_alive(lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", ""))


def _fake_kaggle(tmp_path):
    k = tmp_path / "kaggle"
    k.write_text("#!/bin/sh\n"
                 f"echo \"$@\" >> {tmp_path}/calls.log\n"
                 "if [ \"$1 $2\" = \"datasets status\" ]; then\n"
                 f"  if [ -f {tmp_path}/created ]; then echo ready; exit 0; else echo '404 - Not Found'; exit 1; fi\n"
                 "fi\n"
                 f"if [ \"$2\" = create ]; then touch {tmp_path}/created; echo 'Your private Dataset is being created.'; exit 0; fi\n"
                 "if [ \"$2\" = version ]; then echo 'Dataset version is being created.'; exit 0; fi\n"
                 "exit 2\n")
    k.chmod(k.stat().st_mode | stat.S_IEXEC)
    return k


def test_cli_once_creates_then_versions_then_skips_unchanged(tmp_path):
    B = _mod(); run, _ = _run(tmp_path); k = _fake_kaggle(tmp_path); out = tmp_path / "ds"; ds = out / "dataset"
    args = ["--run", str(run), "--out", str(out), "--slug", "g4-x", "--owner", "owner", "--kaggle", str(k), "--once"]
    assert B.main(args) == 0
    calls = (tmp_path / "calls.log").read_text().splitlines()
    assert calls == ["datasets status owner/g4-x", f"datasets create -p {ds}"]
    assert not (ds / "state.json").exists() and not (ds / "backup.log").exists()      # the dataset dir holds only what is uploaded
    state = json.load(open(out / "state.json")); assert state["capture_lines"] == 3 and state["items"] == 3 and state["pushes"] == 1
    log = (out / "backup.log").read_text(); assert "pushed" in log and "create" in log and "lines 3" in log
    # nothing changed -> no upload
    assert B.main(args) == 0
    calls = (tmp_path / "calls.log").read_text().splitlines()
    assert calls[2:] == [] and "skip" in (out / "backup.log").read_text().splitlines()[-1]
    # one more complete line + the partial one finished -> a new version
    with open(run / "capture.jsonl", "a") as f:
        f.write('": 1}}\n{"t": 100, "body": {}, "response": {}}\n')
    assert B.main(args) == 0
    calls = (tmp_path / "calls.log").read_text().splitlines()
    assert calls[2:] == [f"datasets version -p {ds} -m " + " ".join(calls[2].split()[5:])]   # known state: no status call, straight to version
    assert calls[2].startswith("datasets version -p") and "update" in calls[2]
    assert json.load(open(out / "state.json"))["capture_lines"] == 5
    assert gzip.open(ds / "capture.jsonl.gz", "rt").read().count("\n") == 5


def test_cli_push_failure_is_reported_and_state_kept(tmp_path):
    B = _mod(); run, _ = _run(tmp_path); out = tmp_path / "ds"
    k = tmp_path / "kaggle"; k.write_text("#!/bin/sh\necho 'boom'; exit 3\n"); k.chmod(k.stat().st_mode | stat.S_IEXEC)
    assert B.main(["--run", str(run), "--out", str(out), "--slug", "g4-x", "--owner", "owner", "--kaggle", str(k), "--once"]) == 1
    assert not (out / "state.json").exists() and "FAILED" in (out / "backup.log").read_text()


def test_force_pushes_even_when_unchanged(tmp_path):
    B = _mod(); run, _ = _run(tmp_path); k = _fake_kaggle(tmp_path); out = tmp_path / "ds"
    base = ["--run", str(run), "--out", str(out), "--slug", "g4-x", "--owner", "owner", "--kaggle", str(k), "--once"]
    assert B.main(base) == 0 and B.main(base + ["--force"]) == 0
    assert (tmp_path / "calls.log").read_text().count("datasets version") == 1


def test_script_mentions_no_owner_name_but_the_kaggle_handle():
    src = (ROOT / "scripts" / "a6000" / "backup_captures.py").read_text()
    assert "Carson" not in src           # the box is a shared lab machine


def _fake_kaggle_403(tmp_path, create_conflict=False):
    """status always 403 (the box's token, 2026-10-11); create optionally answers 'already exists'."""
    k = tmp_path / "kaggle"
    k.write_text("#!/bin/sh\n"
                 f"echo \"$@\" >> {tmp_path}/calls.log\n"
                 "if [ \"$1 $2\" = \"datasets status\" ]; then echo '403 - Forbidden'; exit 1; fi\n"
                 + (f"if [ \"$2\" = create ]; then echo 'Dataset owner/g4-x already exists'; exit 1; fi\n" if create_conflict
                    else "if [ \"$2\" = create ]; then echo 'Your private Dataset is being created.'; exit 0; fi\n")
                 + "if [ \"$2\" = version ]; then echo 'Dataset version is being created.'; exit 0; fi\n"
                 "exit 2\n")
    k.chmod(k.stat().st_mode | stat.S_IEXEC)
    return k


def test_status_403_then_known_state_versions_without_asking(tmp_path):
    B = _mod(); run, _ = _run(tmp_path); k = _fake_kaggle_403(tmp_path); out = tmp_path / "ds"; ds = out / "dataset"
    args = ["--run", str(run), "--out", str(out), "--slug", "g4-x", "--owner", "owner", "--kaggle", str(k), "--once"]
    assert B.main(args) == 0                                   # unknown existence -> create (it did not exist)
    with open(run / "capture.jsonl", "a") as f:
        f.write('": 1}}\n{"t": 100, "body": {}, "response": {}}\n')
    assert B.main(args) == 0                                   # state says pushed once -> version, no status call
    calls = (tmp_path / "calls.log").read_text().splitlines()
    assert calls == ["datasets status owner/g4-x", f"datasets create -p {ds}", f"datasets version -p {ds} -m " + " ".join(calls[2].split()[5:])]
    assert json.load(open(out / "state.json"))["pushes"] == 2 and "pushed version #2" in (out / "backup.log").read_text()


def test_create_conflict_falls_back_to_version(tmp_path):
    B = _mod(); run, _ = _run(tmp_path); k = _fake_kaggle_403(tmp_path, create_conflict=True); out = tmp_path / "ds"; ds = out / "dataset"
    args = ["--run", str(run), "--out", str(out), "--slug", "g4-x", "--owner", "owner", "--kaggle", str(k), "--once"]
    assert B.main(args) == 0                                   # a fresh --out but the dataset exists (a restart): create -> exists -> version
    calls = (tmp_path / "calls.log").read_text().splitlines()
    assert [c.split()[1] for c in calls] == ["status", "create", "version"]
    assert json.load(open(out / "state.json"))["pushes"] == 1 and "pushed version #1" in (out / "backup.log").read_text()


def test_pid_file_is_written(tmp_path):
    B = _mod(); run, _ = _run(tmp_path); k = _fake_kaggle(tmp_path); out = tmp_path / "ds"
    assert B.main(["--run", str(run), "--out", str(out), "--slug", "g4-x", "--owner", "owner", "--kaggle", str(k), "--once"]) == 0
    assert int((out / "pid").read_text()) == os.getpid()
