"""eval/analysis/verify_h2_archive.py: a complete archive verifies; every omission at task and rollout level is caught, not
only tampering (paper/EVIDENCE.md: 'saved' must be a checked fact). The expected tasks come from eval/analysis/h2_expected.json,
committed before any Harness² rollout existed."""
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_h2_archive", ROOT / "eval" / "analysis" / "verify_h2_archive.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)
EXP = json.loads((ROOT / "eval" / "analysis" / "h2_expected.json").read_text())


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def manifest(d: Path):
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.relative_to(d)}" for p in sorted(d.rglob("*"))
             if p.is_file() and p.name != "MANIFEST.sha256"]
    (d / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")


def item(r: Path, run_id: str, task: str) -> Path:
    """Where h2g4's launcher puts a rollout since B-208: race/items/_h2_<fp12>_<sha1(run_id)[:6]>/<task>."""
    return r / "race" / "items" / f"_h2_{'ab' * 6}_{hashlib.sha1(run_id.encode()).hexdigest()[:6]}" / task


def rollout(r: Path, run_id: str, task: str, traced=True, legacy=False):
    it = r / "rollouts" / run_id / "items" / "_staging" / "h2_ab" / task if legacy else item(r, run_id, task)
    write(it / "task_results.jsonl", json.dumps({"instance_id": task, "resolved": False}) + "\n")
    if not legacy:
        write(r / "race" / "staged" / it.parent.name / f"{task}.json",
              json.dumps({"run_id": run_id, "arm": it.parent.name, "task": task, "fingerprint": "ab" * 32}))
    if traced:
        write(it / "traces" / f"trace_{task}.json", '{"steps": []}')


def sweep_archive(tmp: Path, name="h2_argon", tasks=None, legacy=False) -> Path:
    d = tmp / name
    r = d / "root"
    tasks = tasks or EXP["pilot"]["tasks"]
    for t in tasks:
        write(r / "adapt" / "swe-g4-adk-agg1" / t / "summary.json", "{}")
        for k in range(EXP["pilot"]["min_rollouts_per_task"]):
            rollout(r, f"{t}-r{k}", t, legacy=legacy)
    write(r / "adapt" / "swe-g4-adk-agg1" / "judged.json", json.dumps([{"task_id": t} for t in tasks]))
    write(r / "adapt" / "swe-g4-adk-agg1" / "base_judged.json", "[]")
    write(r / "adapt" / "_audit" / "propose-general.json", '{"mission": "m", "reply": "r"}')
    write(r / "library" / "seq" / "arrow" / "harnesses" / tasks[0] / "harness" / "systemprompt.md", "x")
    write(d / "proxy.jsonl", '{"t": 1, "latency_s": 2.0}\n')
    write(d / "env.txt", "harness2 1cfe254e8d\n" + "".join(f"pkg{i}==1.0\n" for i in range(12)))
    manifest(d)
    return d


def test_a_complete_sweep_archive_verifies(tmp_path, capsys):
    d = sweep_archive(tmp_path)
    assert V.main([str(d)]) == 0
    out = capsys.readouterr().out
    assert "VERIFIED" in out and "8 tasks checked, 32 rollouts" in out


def test_each_task_level_omission_fails(tmp_path):
    tasks = EXP["pilot"]["tasks"]
    d = sweep_archive(tmp_path / "a")                                  # a whole task missing (summary, rollouts, judged row)
    shutil.rmtree(d / "root" / "adapt" / "swe-g4-adk-agg1" / tasks[3])
    for k in range(EXP["pilot"]["min_rollouts_per_task"]):
        shutil.rmtree(item(d / "root", f"{tasks[3]}-r{k}", tasks[3]))
    ok, msg = V.check_sweep(d)
    assert not ok and tasks[3] in msg
    d = sweep_archive(tmp_path / "b")                                  # one rollout short
    shutil.rmtree(item(d / "root", f"{tasks[0]}-r3", tasks[0]))
    ok, msg = V.check_sweep(d)
    assert not ok and "3 rollouts < 4" in msg
    d = sweep_archive(tmp_path / "c")                                  # a rollout without its trace
    shutil.rmtree(item(d / "root", f"{tasks[1]}-r0", tasks[1]) / "traces")
    ok, msg = V.check_sweep(d)
    assert not ok and "without a trace" in msg
    d = sweep_archive(tmp_path / "d")                                  # judged.json lacks a task
    write(d / "root" / "adapt" / "swe-g4-adk-agg1" / "judged.json", json.dumps([{"task_id": t} for t in tasks[:-1]]))
    ok, msg = V.check_sweep(d)
    assert not ok and "no judged row" in msg
    d = sweep_archive(tmp_path / "e")                                  # library or transcripts missing
    shutil.rmtree(d / "root" / "library")
    assert not V.check_sweep(d)[0]
    d = sweep_archive(tmp_path / "f")                                  # a result with no record of what ran
    it = item(d / "root", f"{tasks[2]}-r1", tasks[2])
    (d / "root" / "race" / "staged" / it.parent.name / f"{tasks[2]}.json").unlink()
    ok, msg = V.check_sweep(d)
    assert not ok and "without a staged record" in msg


def test_a_pre_b208_archive_still_verifies(tmp_path):
    d = sweep_archive(tmp_path, legacy=True)
    ok, msg = V.check_sweep(d)
    assert ok and "32 rollouts" in msg, msg


def test_a_budget_stop_limits_the_expected_tasks_to_the_finished_ones(tmp_path):
    tasks = EXP["pilot"]["tasks"]
    d = sweep_archive(tmp_path, tasks=tasks[:3])
    ok, _ = V.check_sweep(d)
    assert not ok                                                      # without a stop record, 5 tasks are missing
    write(d / "root" / "adapt" / "_sweeps" / "budget-stop-20261019T030000Z.json",
          json.dumps({"budget_stop": "cap", "finished_task_summaries": tasks[:3]}))
    ok, msg = V.check_sweep(d)
    assert ok and "BUDGET STOP after 3 of 8" in msg


def test_a_tampered_or_unlisted_file_fails_the_manifest(tmp_path):
    d = sweep_archive(tmp_path)
    (d / "proxy.jsonl").write_text('{"t": 1, "latency_s": 9.0}\n')
    assert V.check_manifest(d)[0] is False
    d2 = sweep_archive(tmp_path / "b")
    write(d2 / "late.txt", "added after")
    assert V.check_manifest(d2)[0] is False


def test_key_material_fails_and_is_named_not_printed(tmp_path, capsys):
    d = sweep_archive(tmp_path)
    write(d / "root" / "adapt" / "_audit" / "leak.json", '{"k": "sk-or-v1-abcdef"}')
    manifest(d)
    assert V.main([str(d)]) == 1
    out = capsys.readouterr().out
    assert "KEY MATERIAL" in out and "leak.json" in out and "abcdef" not in out


def transfer_archive(tmp: Path, labels=("base_a", "base_b", "fable")) -> Path:
    d = tmp / "h2_transfer"
    r = d / "root"
    for lbl in labels:
        write(r / f"eval_{lbl}.json", json.dumps({"rows": [{"task": t} for t in EXP["transfer"]["tasks"]]}))
        for t in EXP["transfer"]["tasks"]:
            rollout(r, f"eval-{lbl}-{t}", t)
        if not lbl.startswith("base"):
            write(r / "frozen" / lbl / "systemprompt.md", "x")
    return d


def test_transfer_checks_every_label_task_pair(tmp_path):
    d = transfer_archive(tmp_path)
    ok, msg = V.check_transfer(d)
    assert ok, msg
    t = EXP["transfer"]["tasks"][5]
    shutil.rmtree(item(d / "root", f"eval-fable-{t}", t))
    ok, msg = V.check_transfer(d)
    assert not ok and f"fable/{t}" in msg
    d = transfer_archive(tmp_path / "b", labels=("base_a", "fable"))
    ok, msg = V.check_transfer(d)
    assert not ok and "eval_base_b.json" in msg
    d = transfer_archive(tmp_path / "c")
    shutil.rmtree(d / "root" / "frozen" / "fable")
    assert not V.check_transfer(d)[0]
