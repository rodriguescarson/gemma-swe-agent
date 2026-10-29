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
    # make_eval_kernel.py stand-in: records its argv, writes kernels/<slug>/kernel-metadata.json, and prints the real builder's summary line
    # ("<dir> <n> files <ids or 'all'> tasks budget ..."); STUB_IDS = the ids count it reports ("all" = no --ids), STUB_RC = its exit status
    (tmp / "scripts" / "make_eval_kernel.py").write_text(
        "import os, pathlib, sys\npathlib.Path('built_eval.txt').write_text(' '.join(sys.argv[1:]))\n"
        "d = pathlib.Path('kernels') / sys.argv[2]; d.mkdir(parents=True, exist_ok=True); (d / 'kernel-metadata.json').write_text('{}')\n"
        "print('kernels/%s 12 files %s tasks budget {} from x' % (sys.argv[2], os.environ.get('STUB_IDS', '74')))\n"
        "sys.exit(int(os.environ.get('STUB_RC', '0')))\n")
    (tmp / "tmpdir").mkdir()
    return dict(os.environ, TMPDIR=str(tmp / "tmpdir"))


def _ship(tmp, linux_body, args=("submissions/b", "slug-x"), **env_extra):
    env = {**_world(tmp, linux_body), **env_extra}
    r = subprocess.run(["bash", str(tmp / "scripts" / "ship.sh"), *args], cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
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


GREEN = 'echo "812 passed in 61.2s"\n'
EVAL = ("submissions/b", "slug-x", "eval", "--ids", "data/ids.txt", "--min", "5")


def test_eval_mode_with_ids_builds_and_passes_the_arguments_through(tmp_path):
    r, _, _ = _ship(tmp_path, GREEN, EVAL, STUB_IDS="74")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.rstrip().endswith("SHIP OK: kernels/slug-x") and "kernels/slug-x 12 files 74 tasks" in r.stdout
    assert (tmp_path / "built_eval.txt").read_text() == "submissions/b slug-x --ids data/ids.txt --min 5"
    assert (tmp_path / "kernels" / "slug-x" / "kernel-metadata.json").exists()


def test_eval_mode_refuses_a_kernel_for_all_tasks(tmp_path):
    # no --ids (or an empty ids file): the builder says "all tasks" and the kernel would run every task in tasks.jsonl
    r, _, _ = _ship(tmp_path, GREEN, ("submissions/b", "slug-x", "eval"), STUB_IDS="all")
    assert r.returncode == 1 and "SHIP OK" not in r.stdout and "SHIP REFUSED: the eval kernel covers ALL tasks" in r.stdout
    assert "kernels/slug-x 12 files all tasks" in r.stdout                                  # the builder's own line is still shown
    assert not (tmp_path / "kernels" / "slug-x" / "kernel-metadata.json").exists()       # and the build cannot be pushed


def test_eval_mode_allows_all_tasks_when_asked(tmp_path):
    r, _, _ = _ship(tmp_path, GREEN, ("submissions/b", "slug-x", "eval"), STUB_IDS="all", ALLOW_ALL_TASKS="1")
    assert r.returncode == 0 and r.stdout.rstrip().endswith("SHIP OK: kernels/slug-x") and "SHIP REFUSED" not in r.stdout
    assert (tmp_path / "kernels" / "slug-x" / "kernel-metadata.json").exists()


def test_a_failing_eval_builder_still_fails_the_ship(tmp_path):
    r, _, _ = _ship(tmp_path, GREEN, EVAL, STUB_RC="3")
    assert r.returncode == 3 and "SHIP OK" not in r.stdout


def test_submit_mode_is_not_subject_to_the_all_tasks_rule(tmp_path):
    r, built, _ = _ship(tmp_path, GREEN, STUB_IDS="all")
    assert r.returncode == 0 and built.read_text() == "submissions/b slug-x" and not (tmp_path / "built_eval.txt").exists()
