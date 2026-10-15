"""v10 integration checks (integrator, 2026-09-28).

1. Channel parity (CI): every helper gives the same answer through both channels the prompts and SKILL.md teach, inside
   the REAL harness subprocess sandbox: ``run_command("python3 /tmp/swe/<x>.py ...")`` (literal /tmp path, rewritten
   by the sandbox, heredoc stdin) after a ``run_skill_script(install.py)``, and ``run_skill_script(<x>.py, args={...})``
   through the real ADK wrapper on a tree where nothing is installed yet (so the helper must bootstrap itself).
   test_v10_sandbox covers each channel on its own (R108/R109); this pins that they agree, output and workspace effect.
2. make_variant on a v10 bundle (CI, regression): the v9 $TMPDIR fix used to overwrite v10's install.py with
   helpers_v9/install.py and add _ws.py; the race-2 arm r2_v10_t06 is built by ``--work-temp`` alone.
3. Real snapshots (NIGHTLY, needs data/raw/snapshots and the kpar venvs): every helper on real repositories with an
   empty diff and with the gold patch applied: bounded output and time, no helper error.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v10_support import sandbox as S  # noqa: E402
from v10_support.compat import VERSION  # noqa: E402  (G4_BUNDLE may be v10.2)
from v10_support.repo import no_orphans  # noqa: F401,E402  (autouse, R120)

ROOT = Path(__file__).resolve().parents[1]
NIGHTLY = os.environ.get("G4_NIGHTLY") == "1"
SCRIPTS = ROOT / (os.environ.get("G4_BUNDLE") or "submissions/v10") / "skills" / "swe-tools" / "scripts"
CAPS = {"install": 400, "locate": 1800, "grep": 1800, "view": 4000, "edit": 1500, "run": 2500, "verify": 2000,
        "finalize": 1000, "status": 2200}                       # SPEC 4.14 (stdout cap, footer included)

OPS = '''def add(a, b):
    """Add two numbers."""
    return a - b


def mul(a, b):
    return a * b
'''
FIXED = OPS.replace("return a - b", "return a + b")
FILES = {
    "calc/__init__.py": "",
    "calc/ops.py": OPS,
    "tests/__init__.py": "",
    "tests/test_ops.py": "from calc.ops import mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n",
}
CLAIM = "from calc.ops import add\n# CLAIM 1: add sums\nassert add(2, 3) == 5, add(2, 3)\n"
EDIT_BLOCK = "<<<<<<< SEARCH\n    return a - b\n=======\n    return a + b\n>>>>>>> REPLACE\n"
_TIME = re.compile(r"t=\d+(?:\.\d+)?s|\d+(?:\.\d+)? ?(?:ms|s)\b")


_INSTALL_JOURNAL = re.compile(r"JOURNAL: empty|JOURNAL \(last 1\):\n\s+<T> install: [^\n]*")


def norm(text):
    """Output with the only legitimate differences between the channels masked: clock readings and durations, and
    the journal line of the explicit install call (the run_command channel made one; the skill channel's bootstrap
    install is silent by design, SPEC 4.0.3)."""
    return _INSTALL_JOURNAL.sub("JOURNAL", _TIME.sub("<T>", text.strip()))


def out(r):
    return (r.get("stdout") or "") + (r.get("stderr") or "") + (r.get("error_message") or "")


# name: (prepare, run_command text, skill script, skill dict args, skill positional args, expected first-line prefix)
#   prepare: None, "fixed" (the fix written straight to the workspace), "repro" (a saved repro, tree unchanged) or
#   "fixed+repro"
PARITY = {
    "install": (None, "python3 /tmp/swe/install.py", "install.py", None, None, "swe-tools %s ready in /tmp/swe" % VERSION),
    "locate": (None, 'python3 /tmp/swe/locate.py "add numbers"', "locate.py", {"query": "add numbers"}, None,
               "LOCATE:"),
    "grep": (None, 'python3 /tmp/swe/grep.py "def add"', "grep.py", {"regex": "def add"}, None, "GREP: 1 hits"),
    "grep_tests": (None, 'python3 /tmp/swe/grep.py "def test_" --tests', "grep.py", {"regex": "def test_", "tests": True},
                   None, "GREP: 1 hits"),
    "view_range": (None, "python3 /tmp/swe/view.py calc/ops.py 1 3", "view.py", {"file": "calc/ops.py", "start": 1,
                   "end": 3}, None, "calc/ops.py lines 1-3 of 7"),
    "view_name": (None, "python3 /tmp/swe/view.py calc/ops.py add", "view.py", {"file": "calc/ops.py", "name": "add"},
                  None, "calc/ops.py"),
    "view_positional": (None, "python3 /tmp/swe/view.py calc/ops.py 5 7", "view.py", None, ["calc/ops.py", "5", "7"],
                        "calc/ops.py lines 5-7 of 7"),
    "view_obj": (None, "python3 /tmp/swe/view.py --obj calc.ops.add", "view.py", {"obj": "calc.ops.add"}, None,
                 "OBJ calc.ops.add: function"),
    "edit_search": (None, f"python3 /tmp/swe/edit.py calc/ops.py <<'EOF'\n{EDIT_BLOCK}EOF", "edit.py",
                    {"file": "calc/ops.py", "text": EDIT_BLOCK}, None, "OK (exact)"),
    "edit_lines": (None, "python3 /tmp/swe/edit.py calc/ops.py --lines 3-3 <<'EOF'\n    return a + b\nEOF", "edit.py",
                   {"file": "calc/ops.py", "lines": "3-3", "text": "    return a + b"}, None, "OK"),
    "edit_refused": (None, "python3 /tmp/swe/edit.py tests/test_ops.py --lines 1-1 <<'EOF'\nimport os\nEOF", "edit.py",
                     {"file": "tests/test_ops.py", "lines": "1-1", "text": "import os"}, None, "REFUSED"),
    "run": (None, 'python3 /tmp/swe/run.py --timeout 5 "echo parity-run"', "run.py", {"timeout": 5,
            "cmd": "echo parity-run"}, None, "exit=0"),
    "repro_only": (None, f"python3 /tmp/swe/verify.py --repro-only <<'EOF'\n{CLAIM}EOF", "verify.py",
                   {"repro-only": True, "text": CLAIM}, None, "REPRO: fails on original (1 of 1 claims)"),
    "verify_empty": (None, "python3 /tmp/swe/verify.py", "verify.py", None, None, "VERIFY: NO SOURCE CHANGE"),
    "verify_fixed": ("fixed+repro", "python3 /tmp/swe/verify.py", "verify.py", None, None, "VERIFY: GREEN"),
    "finalize_empty": (None, "python3 /tmp/swe/finalize.py", "finalize.py", None, None, "NOT READY: EMPTY"),
    "finalize_fixed": ("fixed", "python3 /tmp/swe/finalize.py", "finalize.py", None, None, "READY: 1 files changed"),
    "status": ("fixed", "python3 /tmp/swe/status.py", "status.py", None, None, "STATUS [t="),
}


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    return S.copy_bundle(tmp_path_factory.mktemp("bundle"))


@pytest.fixture(scope="module")
def shared_box(tmp_path_factory):
    pytest.importorskip("swegemma.sandbox.subprocess")
    if S.v10_missing():
        pytest.skip(S.v10_missing())
    b = S.make_box(FILES, base_dir=tmp_path_factory.mktemp("sbx"))
    yield b
    b.close()


def _prepare(box, bundle, how):
    """State both channels start from. The repro is saved through the helper itself (install + repro-only)."""
    if not how:
        return
    if "repro" in how:
        box.run_skill("verify.py", {"repro-only": True, "text": CLAIM}, skill_dir=bundle / "skills" / "swe-tools")
    if "fixed" in how:
        (box.ws / "calc" / "ops.py").write_text(FIXED)


@pytest.mark.parametrize("case", sorted(PARITY))
def test_channel_parity(shared_box, bundle, case):
    prep, cmd, script, args, pos, first = PARITY[case]
    box, skill_dir = shared_box, bundle / "skills" / "swe-tools"
    results = {}
    for channel in ("run_command", "skill"):
        box.reset()                                                     # baseline tree, /tmp/swe removed
        assert not box.swe.exists()
        if channel == "run_command":
            r = box.run_skill("install.py", skill_dir=skill_dir)       # the setup stage's one call
            assert r["status"] == "success", r
            _prepare(box, bundle, prep)
            rr = box.run_command(cmd)
            text, secs = out(rr), rr["_secs"]
            assert rr["status"] == "ok", (case, rr["_raw"][:500])      # exit 0: no duplicated CommandError output
        else:
            _prepare(box, bundle, prep)
            if prep:                                                    # the repro prep installed; start uninstalled
                gone = " ".join(f"/tmp/swe/{h}.py" for h in S.HELPERS + ("_swe_common", "_swe_index", "_swe_gate",
                                                                          "_swe_ckpt"))
                box.exec(f"rm -rf {gone} /tmp/swe/VERSION /tmp/swe/__pycache__")   # keep state and repro.py
            assert not (box.swe / "VERSION").exists()
            rr = box.run_skill(script, args, pos, skill_dir=skill_dir)  # must bootstrap the install itself
            assert rr["status"] == "success" and not rr["stderr"], rr
            text, secs = rr["stdout"], rr["_secs"]
            assert all((box.swe / f"{h}.py").is_file() for h in S.HELPERS), case
        name = script[:-3]
        assert text.splitlines()[0].startswith(first), (case, channel, text[:600])
        for bad in ("HELPER ERROR", "USAGE ERROR", "Traceback", "can't open file", "No such file"):
            assert bad not in text, (case, channel, bad, text[:600])
        assert len(text) <= CAPS[name], (case, channel, len(text))
        assert "[t=" in text, (case, channel, text[-200:])
        assert secs < (12.0 if name == "verify" else 4.0), (case, channel, secs)
        results[channel] = (norm(text), (box.ws / "calc" / "ops.py").read_text(),
                            (box.ws / "tests" / "test_ops.py").read_text())
    a, b = results["run_command"], results["skill"]
    assert a[1:] == b[1:], (case, "workspace effect differs between channels")
    assert a[0] == b[0], (case, "output differs between channels:\n--- run_command\n" + a[0] + "\n--- skill\n" + b[0])


def test_parity_covers_every_helper():
    """Every CLI helper of the bundle is in the parity table (a new helper cannot skip it)."""
    covered = {v[2][:-3] for v in PARITY.values()}
    assert covered == set(S.HELPERS), set(S.HELPERS) ^ covered


# ------------------------------------------------------------------------------------------------ make_variant (v10)
def _variant(tmp_path, *flags):
    out_dir = tmp_path / "variant"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_variant.py"), str(ROOT / "submissions" / "v10"),
                        str(out_dir), *flags], capture_output=True, text=True, timeout=60)
    return r, out_dir


def _tree(d):
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(Path(d).rglob("*")) if p.is_file()}


def test_make_variant_v10_keeps_v10_helpers(tmp_path):
    """Regression: without flags make_variant copied helpers_v9/install.py over v10's and added _ws.py."""
    r, d = _variant(tmp_path)
    assert r.returncode == 0, r.stderr
    assert _tree(d) == _tree(ROOT / "submissions" / "v10") or \
        {k: v for k, v in _tree(ROOT / "submissions" / "v10").items() if "__pycache__" not in k} == _tree(d)
    assert not (d / "skills" / "swe-tools" / "scripts" / "_ws.py").exists()


def test_make_variant_v10_work_temp_arm(tmp_path):
    """Race-2 optional arm r2_v10_t06 (SPEC 10.1): only the three working-stage temperatures change."""
    r, d = _variant(tmp_path, "--work-temp", "0.6")
    assert r.returncode == 0, r.stderr
    base = _tree(ROOT / "submissions" / "v10")
    got = _tree(d)
    assert set(got) == {k for k in base if "__pycache__" not in k}
    changed = sorted(k for k in got if got[k] != base[k])
    assert changed == ["configs/gen_fixer.yaml", "configs/gen_locator.yaml", "configs/gen_verifier.yaml"], changed
    for k in changed:
        assert re.search(rb"^temperature: 0\.6$", got[k], re.M), k
        assert got[k].replace(b"temperature: 0.6", b"temperature: 1.0") == base[k], k


def test_make_variant_v10_refuses_v9_levers(tmp_path):
    for flags in (["--gate"], ["--edit"], ["--output"]):
        r, d = _variant(tmp_path, *flags)
        assert r.returncode == 2 and "v9 levers" in r.stderr, (flags, r.stderr)
        assert not d.exists()
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_variant.py"), str(ROOT / "submissions" / "v4"),
                        str(tmp_path / "v4x"), "--work-temp", "0.6"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and not (tmp_path / "v4x").exists()


# ------------------------------------------------------------------------------------------------ real snapshots
SNAP_TIDS = ("rich_3894", "requests_6644", "rich_4075", "rich_3930")   # rich_3930: the 308 kB, 26-file gold patch
SNAP_OUT_LIMIT = 3500          # integrator bound for every helper output on real repos (view's own cap is 4,000)
# per-helper wall budgets on a loaded Mac, 3x the SPEC 4.14 perf budgets (verify: its 60 s global deadline)
SNAP_MS = {"install": 900, "locate": 9000, "grep": 3000, "view": 1500, "edit": 1500, "run": 20000, "verify": 60000,
           "finalize": 15000, "status": 1500}


def _snap_calls(tid, T, rows):
    task = T.load_task(tid)
    fps = [f for f in T.parse_patch(task["patch"]) if f.path.endswith(".py") and not f.new_file and f.hunks]
    fp = fps[0]
    h = fp.hunks[0]
    a, b = max(1, h.old_start), h.old_start + max(h.old_len, 1)
    names = re.findall(r"^[+-]\s*(?:async\s+)?def\s+(\w+)", task["patch"], re.M) or ["__init__"]
    name = names[0]
    parts = fp.path.split("/")
    pkg = parts[1] if parts[0] == "src" else parts[0]
    query = re.sub(r"\s+", " ", task["problem_statement"])[:300]

    def call(scen, helper, args=(), ws=None, env=None, stdin=None, label=None):
        t = time.perf_counter()
        r = T.run_helper(helper, args, ws=ws, env=env, stdin=stdin, timeout=120)
        ms = (time.perf_counter() - t) * 1000
        text = (r.out or "") + (r.err or "")
        rows.append({"tid": tid, "scen": scen, "helper": helper, "label": label or helper,
                     "args": " ".join(map(str, args))[:60],
                     "ms": round(ms), "chars": len(text), "first": T.first_line(text)[:120]})
        return text, ms

    with T.work_dir("integ") as d:
        ws = T.fresh_ws(tid, d / "e")
        env = T.sandbox_env(ws, task["repo"])
        call("empty", "install", (), ws, env)
        call("empty", "locate", (query,), ws, env)
        call("empty", "locate", (query,), ws, env)
        call("empty", "grep", (rf"def {name}\b",), ws, env)
        call("empty", "view", (fp.path, a, b), ws, env)
        call("empty", "view", (fp.path, name), ws, env)
        call("empty", "view", (fp.path,), ws, env)
        call("empty", "view", ("--obj", pkg), ws, env)
        call("empty", "run", ("--timeout", "20", f"python3 -c 'import {pkg}; print({pkg}.__name__)'"), ws, env)
        line = (ws / fp.path).read_bytes().split(b"\n")[a - 1].decode("utf-8", "replace")
        call("empty", "edit", (fp.path,), ws, env, stdin=f"<<<<<<< SEARCH\n{line}\n=======\n{line}\n>>>>>>> REPLACE\n")
        call("empty", "verify", ("--repro-only",), ws, env, stdin=f"import {pkg}\n# CLAIM 1: imports\nassert {pkg}\n",
             label="repro")
        call("empty", "verify", (), ws, env)
        call("empty", "finalize", (), ws, env)
        call("empty", "status", (), ws, env)
        assert T.git(ws, "status", "--porcelain", "--untracked-files=no").out.strip() == "", "empty run changed files"

        ws = T.fresh_ws(T.base_ws(tid, with_test_patch=True), d / "g")
        env = T.sandbox_env(ws, task["repo"])
        call("gold", "install", (), ws, env)
        repro = T.hidden_claims_repro(tid)
        if repro:
            call("gold", "verify", ("--repro-only",), ws, env, stdin=repro, label="repro_orig")
        ok, err = T.git_apply(ws, task["patch"])
        assert ok, err
        if repro:
            call("gold", "verify", ("--repro-only",), ws, env, label="repro_fixed")
        call("gold", "verify", (), ws, env)
        call("gold", "verify", (), ws, env, label="verify_memo")
        call("gold", "status", (), ws, env)
        call("gold", "finalize", (), ws, env)
        call("gold", "status", (), ws, env, label="status_final")
        call("gold", "locate", (query,), ws, env)
        call("gold", "grep", (rf"def {name}\b",), ws, env)
        call("gold", "view", (fp.path, name), ws, env)


@pytest.mark.skipif(not NIGHTLY, reason="nightly tier (G4_NIGHTLY=1): real snapshots and the kpar venvs")
@pytest.mark.parametrize("tid", SNAP_TIDS)
def test_real_snapshot_helpers(tid):
    from v10_support import tasks as T
    T.require_snapshot(tid)
    T.kpar_python(T.repo_key(tid))
    rows = []
    _snap_calls(tid, T, rows)
    out_dir = T.OFFLINE_OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"v10_integration_{tid}.json").write_text(json.dumps(rows, indent=1))
    bad = [r for r in rows if any(s in r["first"] for s in ("HELPER ERROR", "USAGE ERROR", "Traceback"))]
    assert not bad, bad
    big = [r for r in rows if r["chars"] >= SNAP_OUT_LIMIT]
    assert not big, big
    slow = [r for r in rows if r["ms"] > SNAP_MS[r["helper"]]]
    assert not slow, slow
    firsts = {}
    for r in rows:
        firsts.setdefault((r["scen"], r["label"]), r["first"])
    assert firsts[("empty", "edit")].startswith("NO CHANGE"), firsts
    assert firsts[("empty", "run")] == "exit=0", firsts
    assert firsts[("empty", "verify")].startswith("VERIFY: NO SOURCE CHANGE"), firsts
    assert firsts[("empty", "finalize")].startswith("NOT READY: EMPTY"), firsts
    assert firsts[("gold", "verify")].startswith(("VERIFY: GREEN", "VERIFY: AMBER")), firsts   # gold is never RED
    assert firsts[("gold", "verify_memo")].startswith("SAME AS LAST RUN"), firsts
    assert firsts[("gold", "finalize")].startswith("READY:"), firsts
    if tid not in T.KNOWN_FREE:                     # requests_6644: the hidden tests import site-packages (F10)
        assert firsts[("gold", "repro_orig")].startswith("REPRO: fails on original"), firsts
        assert re.match(r"REPRO: (\d+)/\1 claims fixed", firsts[("gold", "repro_fixed")]), firsts


def test_linux_test_script_full_mode_static():
    """Regression (integrator, 2026-09-28): the whole-suite mode of scripts/linux_test.sh piped pytest into
    'tail -5', so a run with 152 failures exited 0, and it did not install the harness wheels the v10 tests import."""
    s = (ROOT / "scripts" / "linux_test.sh").read_text()
    full = s[s.index('docker run', s.index('bash -c "$V10_SCRIPT"')):]     # the whole-suite command, not comments
    assert "harness/wheels/*.whl" in full and "g4-pip-cache" in full
    assert ("exit \\$rc" in full or "exit $rc" in full) and "| tail -5" not in full
    assert subprocess.run(["bash", "-n", str(ROOT / "scripts" / "linux_test.sh")]).returncode == 0
