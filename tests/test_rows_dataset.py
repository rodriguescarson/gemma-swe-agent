"""scripts/rows_dataset.py: stage JSONL row files (the Invent rows for the think2 arm) as a flat private Kaggle dataset the box can pull
with `kaggle datasets download`; the create-vs-version logic is adapters_dataset's. Written before the script (2026-10-11)."""
import importlib.util, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rows_dataset", ROOT / "scripts" / "rows_dataset.py")
rd = importlib.util.module_from_spec(spec); spec.loader.exec_module(rd)


def test_stage_copies_the_files_flat_with_metadata_and_a_manifest(tmp_path):
    a = tmp_path / "in" / "bugs.jsonl"; a.parent.mkdir(); a.write_text('{"enhanced_prompt": "p", "enhanced_completion": "c"}\n' * 3)
    b = tmp_path / "in" / "sub" / "behaviour.jsonl"; b.parent.mkdir(); b.write_text('{"enhanced_prompt": "p"}\n')
    out = tmp_path / "ds"
    files = rd.stage([str(a), str(b)], str(out), "carsonrodrigues", "g4-invent-rows")
    assert files == {"bugs.jsonl": 3, "behaviour.jsonl": 1}
    assert (out / "bugs.jsonl").read_text() == a.read_text() and (out / "behaviour.jsonl").exists()
    meta = json.loads((out / "dataset-metadata.json").read_text())
    assert meta["id"] == "carsonrodrigues/g4-invent-rows" and meta["title"] == "g4-invent-rows"
    man = json.loads((out / "MANIFEST.json").read_text())
    assert man["files"]["bugs.jsonl"]["rows"] == 3 and len(man["files"]["bugs.jsonl"]["sha256"]) == 64
    assert rd.cli_command("kaggle", str(out), False)[:3] == ["kaggle", "datasets", "create"] and rd.cli_command("kaggle", str(out), True)[2] == "version"
