"""eval/analysis/verify_h2_archive.py: a complete fake sweep archive verifies; each way an archive can be incomplete or
tampered with is caught (paper/EVIDENCE.md: 'the results are saved' must be a checked fact)."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("verify_h2_archive", ROOT / "eval" / "analysis" / "verify_h2_archive.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)


def write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def manifest(d: Path):
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{p.relative_to(d)}" for p in sorted(d.rglob("*"))
             if p.is_file() and p.name != "MANIFEST.sha256"]
    (d / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")


def sweep_archive(tmp: Path) -> Path:
    d = tmp / "h2_argon"
    r = d / "root"
    write(r / "adapt" / "swe-g4-adk-agg1" / "arrow_06fe693" / "summary.json", "{}")
    write(r / "adapt" / "swe-g4-adk-agg1" / "judged.json", "[]")
    write(r / "adapt" / "swe-g4-adk-agg1" / "base_judged.json", "[]")
    write(r / "adapt" / "_audit" / "propose-general.json", '{"mission": "m", "reply": "r"}')
    write(r / "adapt" / "_spend.jsonl", '{"spent_usd": 0.4}\n')
    write(r / "library" / "seq" / "arrow" / "harnesses" / "arrow_06fe693" / "harness" / "systemprompt.md", "x")
    item = r / "rollouts" / "run1" / "items" / "_staging" / "h2_ab" / "arrow_06fe693"
    write(item / "task_results.jsonl", '{"instance_id": "arrow_06fe693", "resolved": false}\n')
    write(item / "traces" / "trace_arrow_06fe693.json", '{"steps": []}')
    write(d / "proxy.jsonl", '{"t": 1, "latency_s": 2.0}\n')
    write(d / "env.txt", "harness2 1cfe254e8d\n" + "".join(f"pkg{i}==1.0\n" for i in range(12)))
    manifest(d)
    return d


def test_a_complete_sweep_archive_verifies(tmp_path, capsys):
    d = sweep_archive(tmp_path)
    assert V.main([str(d)]) == 0
    assert "VERIFIED" in capsys.readouterr().out


def test_missing_library_or_traces_fail(tmp_path):
    d = sweep_archive(tmp_path)
    import shutil
    shutil.rmtree(d / "root" / "library")
    manifest(d)
    assert V.main([str(d)]) == 1
    d2 = sweep_archive(tmp_path / "b")
    next((d2 / "root" / "rollouts").rglob("trace_*.json")).unlink()
    manifest(d2)
    assert V.main([str(d2)]) == 1


def test_a_tampered_or_unlisted_file_fails_the_manifest(tmp_path):
    d = sweep_archive(tmp_path)
    (d / "proxy.jsonl").write_text('{"t": 1, "latency_s": 9.0}\n')            # changed after the manifest
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


def test_transfer_needs_both_base_runs_and_a_frozen_tree_per_candidate(tmp_path):
    d = tmp_path / "h2_transfer"
    write(d / "root" / "eval_base_a.json", json.dumps({"rows": []}))
    write(d / "root" / "eval_fable.json", json.dumps({"rows": []}))
    write(d / "root" / "frozen" / "fable" / "systemprompt.md", "x")
    assert V.check_transfer(d)[0] is False                                    # base_b missing
    write(d / "root" / "eval_base_b.json", json.dumps({"rows": []}))
    write(d / "root" / "eval_argon.json", json.dumps({"rows": []}))
    assert V.check_transfer(d)[0] is False                                    # argon was not frozen
    write(d / "root" / "frozen" / "argon" / "systemprompt.md", "y")
    assert V.check_transfer(d)[0] is True
