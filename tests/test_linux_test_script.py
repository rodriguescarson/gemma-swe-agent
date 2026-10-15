"""scripts/linux_test.sh must never copy data/ (40 GB) into the container: on 2026-10-15 the whole-suite branch's
`cp -r /g4 /tmp/g4` filled the Docker VM (read-only file system, daemon down) and ship.sh refused v13. The V10_ONLY branch
already stages with tar excludes + symlinks; both branches must. Written before the fix."""
import pathlib, re, shutil, subprocess

S = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "linux_test.sh"


def test_syntax_and_shellcheck():
    assert subprocess.run(["bash", "-n", str(S)]).returncode == 0
    if shutil.which("shellcheck"):
        r = subprocess.run(["shellcheck", "-S", "warning", str(S)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout


def test_no_branch_copies_the_whole_repo_into_the_container():
    t = S.read_text()
    assert "cp -r /g4" not in t and "cp -a /g4" not in t


def test_both_branches_exclude_data_and_symlink_it():
    t = S.read_text()
    assert t.count("--exclude=./data") >= 1 and t.count("ln -s /g4/data /tmp/g4/data") >= 1
    # the staging is shared, so one definition serves both docker runs
    cmds = [l for l in t.splitlines() if re.match(r"\s*(exec )?docker run ", l)]
    assert len(cmds) == 2 and t.count("tar -cf - --exclude=./.venv --exclude=./data") == 1
