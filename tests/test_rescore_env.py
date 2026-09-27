"""Regressions from the 2026-09-27 diagnosis: the pod mis-scored tasks because the eval env
lacked python-multipart (fastapi form tests error at collection), and patch rescoring must run
on Kaggle's CPU env with every config's patches."""
import json, pathlib, subprocess, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_buildenv_installs_and_checks_python_multipart():
    s = (ROOT / "pod/buildenv.sh").read_text()
    assert "python-multipart" in s and "import pytest, dirty_equals, inline_snapshot, pytest_httpbin, multipart" in s

def test_rescore_kernel_is_cpu_and_carries_all_patches(tmp_path):
    labels = [{"task": "t1", "cfg": "a", "patch": "diff --git a/x b/x\n"}, {"task": "t1", "cfg": "b", "patch": ""},
              {"task": "t2", "cfg": "b", "patch": "diff --git a/y b/y\n"}]
    lp = tmp_path / "l.json"; lp.write_text(json.dumps(labels))
    ids = tmp_path / "ids.txt"; ids.write_text("t1\nt2\n")
    subprocess.run([sys.executable, str(ROOT / "scripts/make_eval_kernel.py"), str(ROOT / "submissions/v4"), "t-rescore-test",
                    "--ids", str(ids), "--patches", str(lp)], cwd=tmp_path, check=True, capture_output=True)
    kd = tmp_path / "kernels/t-rescore-test"
    meta = json.loads((kd / "kernel-metadata.json").read_text())
    assert meta["enable_gpu"] is False and "machine_shape" not in meta and meta["model_sources"] == []
    nb = json.loads((kd / "t-rescore-test.ipynb").read_text())
    src = "\n".join(c["source"] for c in nb["cells"])
    for c in nb["cells"]: compile(c["source"], "cell", "exec")
    assert 'PATCHES = {"a": {"t1": "diff --git a/x b/x\\n"}, "b": {"t2": "diff --git a/y b/y\\n"}}' in src  # empty patch dropped
    assert "pip freeze" in src

def test_helper_check_cell_is_guarded(tmp_path):
    ids = tmp_path / "ids.txt"; ids.write_text("t1\n")
    subprocess.run([sys.executable, str(ROOT / "scripts/make_eval_kernel.py"), str(ROOT / "submissions/v4"), "t-hc",
                    "--ids", str(ids), "--oracle", "--helper-check", str(ROOT / "submissions/v4/skills/swe-tools/scripts")],
                   cwd=tmp_path, check=True, capture_output=True)
    nb = json.loads((tmp_path / "kernels/t-hc/t-hc.ipynb").read_text())
    cell = nb["cells"][1]["source"]
    compile(cell, "cell", "exec")
    assert "HELPER_CHECK" in cell and "try: _helper_check()" in cell and "except Exception" in cell  # can never abort the rescore
