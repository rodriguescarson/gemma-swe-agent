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


def _stage(dst):
    """Run the shared staging block (mkdir .. cd) with /g4 -> this repo and /tmp/g4 -> dst, like the container does."""
    t = S.read_text()
    block = t.split("read -r -d '' STAGE_SCRIPT <<'SH' || true\n", 1)[1].split("\nSH\n", 1)[0]
    cmds = block[block.index("mkdir -p /tmp/g4"):block.index("cd /tmp/g4 || exit 1")]
    cmds = cmds.replace("/tmp/g4", "@DST@").replace("/g4", "@SRC@").replace("@DST@", str(dst)).replace("@SRC@", str(S.parents[1]))
    r = subprocess.run(["bash", "-c", "set -e\n" + cmds], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    return dst


def test_staging_keeps_eval_scripts_and_links_the_big_inputs(tmp_path):
    """Regression (2026-10-15, ship run 2): the staged eval/ held only four symlinks, so tests/test_locate_recall_heldout.py
    (imports eval/locate_recall_heldout.py at module level) raised FileNotFoundError at collection and the Linux run tested
    nothing ("1 error in 14 s"). eval/ scripts and small outputs are copied (writable); the big read-only inputs are links."""
    dst = _stage(tmp_path / "g4")
    assert (dst / "eval" / "locate_recall_heldout.py").is_file() and (dst / "eval" / "locate_recall.py").is_file()
    assert (dst / "data").is_symlink()
    for big in ("golden", "kaggle", "race1", "collect"):
        assert (dst / "eval" / big).is_symlink(), big
    assert not list((dst / "tests").glob("__pycache__"))
