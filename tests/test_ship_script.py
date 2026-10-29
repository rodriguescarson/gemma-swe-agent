"""scripts/ship.sh must refuse on the Linux gate's own exit status, not only on text in its log, and must keep that log
per run (a shared /tmp/linux_test.out let concurrent ships read each other's result). The success banner is grepped by
the eval/arm_sub*.sh chains and stays byte-identical."""
import os, pathlib, shutil, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _world(tmp, linux_body):
    """A throwaway checkout: the real ship.sh, a stub .venv python (the Mac suite passes), a scripted linux_test.sh and a
    make_kernel.py that only leaves a marker."""
    (tmp / "scripts").mkdir(parents=True); (tmp / ".venv" / "bin").mkdir(parents=True); (tmp / "submissions" / "b").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "ship.sh", tmp / "scripts" / "ship.sh")
    py = tmp / ".venv" / "bin" / "python"; py.write_text("#!/bin/bash\nexit 0\n"); py.chmod(0o755)
    (tmp / "scripts" / "linux_test.sh").write_text("#!/bin/bash\n" + linux_body)
    (tmp / "scripts" / "make_kernel.py").write_text("import pathlib, sys\npathlib.Path('built.txt').write_text(' '.join(sys.argv[1:]))\n")
    (tmp / "tmpdir").mkdir()
    return dict(os.environ, TMPDIR=str(tmp / "tmpdir"))


def _ship(tmp, linux_body):
    env = _world(tmp, linux_body)
    r = subprocess.run(["bash", str(tmp / "scripts" / "ship.sh"), "submissions/b", "slug-x"], cwd=tmp, env=env,
                       capture_output=True, text=True, timeout=60)
    return r, tmp / "built.txt", sorted((tmp / "tmpdir").iterdir())


def test_green_gate_ships_with_the_unchanged_banner_and_leaves_no_log(tmp_path):
    r, built, logs = _ship(tmp_path, 'echo "812 passed in 61.2s"\n')
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.rstrip().endswith("SHIP OK: kernels/slug-x") and "SHIP REFUSED" not in r.stdout
    assert built.read_text() == "submissions/b slug-x" and logs == []


def test_a_failing_linux_gate_is_refused_even_when_its_log_says_passed(tmp_path):
    # the exit status is the gate: a run that printed a pass line and then died (OOM kill, docker exit) must not ship
    r, built, logs = _ship(tmp_path, 'echo "812 passed in 61.2s"\nexit 1\n')
    assert r.returncode == 1 and "SHIP OK" not in r.stdout and not built.exists()
    assert "SHIP REFUSED: Linux tests failed" in r.stdout and "exit 1" in r.stdout
    assert len(logs) == 1 and str(logs[0]) in r.stdout            # the refusal names the log it kept, under TMPDIR
    assert "812 passed" in logs[0].read_text()


def test_a_refusal_names_a_log_that_holds_the_gates_stderr(tmp_path):
    # linux_test.sh reports its own refusals (bad PY, low disk) on stderr with exit 2/3 and no pytest line at all
    r, built, logs = _ship(tmp_path, 'echo "linux_test.sh: only 3 GB free on this disk" >&2\nexit 3\n')
    assert r.returncode == 1 and not built.exists() and "SHIP REFUSED: Linux tests failed" in r.stdout and "exit 3" in r.stdout
    assert "only 3 GB free" in logs[0].read_text()


def test_failed_lines_and_a_missing_pass_line_are_still_refused(tmp_path):
    for i, body in enumerate(('echo "3 failed, 809 passed in 60s"\n', 'echo "no summary here"\n', "true\n")):
        sub = tmp_path / str(i)
        r, built, logs = _ship(sub, body)
        assert r.returncode == 1 and "SHIP REFUSED: Linux tests failed" in r.stdout and "exit 0" in r.stdout and not built.exists(), body


def test_the_log_is_not_the_shared_tmp_file():
    code = "\n".join(l for l in (ROOT / "scripts" / "ship.sh").read_text().splitlines() if not l.lstrip().startswith("#"))
    assert "/tmp/linux_test.out" not in code and "mktemp" in code and "PIPESTATUS" in code
