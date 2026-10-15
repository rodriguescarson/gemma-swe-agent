"""scripts/linux_test.sh must never copy data/ (40 GB) into the container: on 2026-10-15 the whole-suite branch's
`cp -r /g4 /tmp/g4` filled the Docker VM (read-only file system, daemon down) and ship.sh refused v13. The V10_ONLY branch
already stages with tar excludes + symlinks; both branches must. Written before the fix."""
import os, pathlib, re, shutil, subprocess

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
    for big in ("golden", "kaggle", "collect"):          # the only read-only inputs; in Docker they are bind mounts
        assert (dst / "eval" / big).is_symlink(), big
    for writable in ("runs", "a6000", "race1"):          # tests write here (pace_proxy_test.jsonl under eval/runs)
        assert (dst / "eval" / writable).is_dir() and not (dst / "eval" / writable).is_symlink(), writable
    assert not list((dst / "tests").glob("__pycache__"))
    shutil.rmtree(dst)        # ~1.5 GB per copy; pytest keeps the last 3 basetemps, which emptied the disk on 2026-10-15


def test_both_container_commands_mount_the_workspace_cache_but_not_kpar():
    """Regression (2026-10-15, Linux iteration 1): the full suite rebuilt ~/.cache/g4/ws inside the Docker VM (12 GB by 32%
    of the suite; the Mac's copy is 24 GB) and took the Mac to 0 GB free. The workspaces are bind-mounted from the Mac.
    kpar venvs are platform-specific (Mac binaries) and must stay inside the container."""
    t = S.read_text()
    assert 'G4_WS="${G4_WS:-$HOME/.cache/g4/ws}"' in t
    lines = t.splitlines(); cmds = []
    for i, l in enumerate(lines):                 # a command = its line plus the backslash continuations
        if re.match(r"\s*(exec )?docker run ", l):
            c = l
            while c.rstrip().endswith("\\"): i += 1; c += lines[i]
            cmds.append(c)
    assert len(cmds) == 2 and all('-v "$G4_WS":/root/.cache/g4/ws' in c for c in cmds), cmds
    assert "kpar" not in "".join(cmds)


def test_refuses_to_start_when_the_disk_is_low(tmp_path):
    """The Docker VM grew 11 GB in 5 minutes twice on 2026-10-15; the guard runs before any container starts."""
    r = subprocess.run(["bash", str(S)], env=dict(os.environ, MIN_FREE_GB="100000"), capture_output=True, text=True,
                       timeout=60, cwd=str(S.parents[1]))
    assert r.returncode == 3 and "GB free" in r.stderr and "MIN_FREE_GB" in r.stderr, (r.returncode, r.stderr[-500:])


def _container_commands():
    lines = S.read_text().splitlines(); cmds = []
    for i, l in enumerate(lines):
        if re.match(r"\s*(exec )?docker run ", l):
            c = l
            while c.rstrip().endswith("\\"): i += 1; c += lines[i]
            cmds.append(c)
    return cmds


def test_container_has_procps_and_the_full_suite_has_peft():
    """Linux iteration 2 (2026-10-15): 15 tests shell out to pgrep/ps (A6000 autopilot + guard, backup_captures, bounded.py)
    and python:3.12-slim ships without procps; train/qlora_model imports peft, which only the Mac venv had."""
    t = S.read_text()
    block = t.split("read -r -d '' STAGE_SCRIPT <<'SH' || true\n", 1)[1].split("\nSH\n", 1)[0]
    assert re.search(r"apt-get -qq install -y git procps", block), block
    full = t[t.index('bash -c "$V10_SCRIPT"'):]
    assert "pip -q install peft==" in full


def test_read_only_inputs_are_bind_mounted_in_both_container_commands():
    """data/ and the big eval inputs as symlinks broke path relativisation (test_committed_split_equals_recomputation saw
    /tmp/g4/data/... instead of data/...); in Docker they are read-only bind mounts at their real paths, and the staging's
    symlinks are only a fallback for running the block outside Docker (the tests above)."""
    t = S.read_text()
    for c in _container_commands():
        assert '"${RO_MOUNTS[@]}"' in c, c
    assert 'RO_MOUNTS=(-v "$PWD/data:/tmp/g4/data:ro")' in t
    assert 'RO_MOUNTS+=(-v "$PWD/eval/$d:/tmp/g4/eval/$d:ro")' in t and "for d in golden kaggle collect; do" in t
    block = t.split("read -r -d '' STAGE_SCRIPT <<'SH' || true\n", 1)[1].split("\nSH\n", 1)[0]
    assert '[ -e /tmp/g4/data ] || ln -s /g4/data /tmp/g4/data' in block


def test_full_mode_takes_a_tests_subset():
    """TESTS="tests/a.py::x tests/b.py" scripts/linux_test.sh runs only those in the real container environment (the 27
    Linux-only failures of 2026-10-15 took 17 min per full iteration); unset = the whole tests/ tree, as before."""
    t = S.read_text()
    full = t[t.index('bash -c "$V10_SCRIPT"'):]
    assert '-e "TESTS=${TESTS:-}"' in full
    assert "python -m pytest -q -p no:cacheprovider ${TESTS:-tests} -k 'not shellcheck and not official_compiler'" in full
