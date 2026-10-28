"""v10.2 bundle (docs/v10/SPEC_v10_2.md sections 2-6; R142, R144-R146, R148 and the tree rules of section 2).

- The tree: submissions/v10_2 has v10.1's 31 files; only the files section 2 lists differ; every helper keeps v10.1's
  preamble, USAGE and FLAGS (no new flags, so SKILL.md is unchanged); stdlib only and Python 3.8 syntax (R01).
- R146: the section 5.0 constants, pinned; every timeout still at most 110 s.
- R142: BUDGET_SCALE x 60 x max_time_minutes == CAP_S for every bundle under submissions/v10*; the make_variant --cap 5.5
  arm fires FINISH / TIME / the last restore at 231 / 275 / 313.5 real s, real_budget never exceeds the real time left,
  and a pod clock scale composes with it.
- R144 / R145 / R91 / R96 on the v10.2 prompts whatever G4_BUNDLE says: the prompts equal SPEC_v10_2 3.2 and 3.3, and
  tests/test_v10_prompts.py plus tests/test_v10_bundle.py pass with G4_BUNDLE=submissions/v10_2 (the version-aware
  sizes, phrases and fixer mix, the R94/R95 context margins and the organisers' compile).
- R148: v10.1 is frozen (tests/test_v10_bundle.py FROZEN pins its tree hash).
"""
import ast
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from v10_support.repo import no_orphans, make_repo, copy_helpers, helper_env, run_py  # noqa: F401,E402
from v10_support.v102 import ROOT, V101, V102, V101_SCRIPTS, V102_SCRIPTS  # noqa: E402
from test_v10_bundle import (FROZEN, load_yaml, module_constants, spec_blocks, spec_text, tree_sha256,  # noqa: E402
                             render_prompt, _fence_after)

pytestmark = pytest.mark.skipif(not (V102_SCRIPTS / "_swe_common.py").exists(), reason="v10.2 bundle not built")
MV = ROOT / "scripts" / "make_variant.py"
SPEC2 = ROOT / "docs" / "v10" / "SPEC_v10_2.md"
SC = "skills/swe-tools/scripts"
CHANGED = {"prompts/locator.md", "prompts/fixer.md"} | {SC + "/%s.py" % n for n in (
    "_swe_common", "status", "locate", "grep", "view", "run", "verify", "_swe_gate", "_swe_ckpt", "finalize")}
CLI = ("install", "locate", "grep", "view", "edit", "run", "verify", "finalize", "status")


def tree(d):
    d = pathlib.Path(d)
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts and not p.name.startswith("._") and p.name != ".DS_Store"}


# ------------------------------------------------------------------------------------------------------------ the tree
def test_tree_changes_only_the_section2_files():
    """Section 2: the same 31 files as v10.1; exactly the listed files differ; everything else is byte-identical."""
    a, b = tree(V101), tree(V102)
    assert set(a) == set(b) and len(b) == 31, set(a) ^ set(b)
    assert {k for k in b if a[k] != b[k]} == CHANGED


def test_helpers_keep_preamble_usage_and_flags():
    """R02, R92, R93: the preamble, USAGE and FLAGS of every CLI helper are v10.1's (no new flag, SKILL.md unchanged)."""
    for name in CLI:
        old = (V101_SCRIPTS / (name + ".py")).read_text().split("\n")
        new = (V102_SCRIPTS / (name + ".py")).read_text().split("\n")
        assert new[:10] == old[:10], name
        o, n = module_constants(V101_SCRIPTS / (name + ".py")), module_constants(V102_SCRIPTS / (name + ".py"))
        assert (n.get("USAGE"), n.get("FLAGS")) == (o.get("USAGE"), o.get("FLAGS")), name


def test_stdlib_only_python38():
    """R01: every helper parses as Python 3.8 and imports only the standard library and the bundle's own modules."""
    local = {p.stem for p in V102_SCRIPTS.glob("*.py")}
    std = set(sys.stdlib_module_names)
    for p in sorted(V102_SCRIPTS.glob("*.py")):
        tree_ = ast.parse(p.read_text(), str(p), feature_version=(3, 8))
        for node in ast.walk(tree_):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module.split(".")[0]]
            for n in names:
                assert n in std or n in local, (p.name, n)


# ------------------------------------------------------------------------------------------------------------ R146
def test_v102_constants():
    """R146: the section 5.0 constants and v10.1's clock thresholds; every timeout constant still at most 110 s."""
    c = module_constants(V102_SCRIPTS / "_swe_common.py")
    want = {"VERSION": "v10.2", "LOC_MAX_CALLS": 14, "T_LOC_CLOSE": 90, "LOC_MAX_RUNS": 3, "LOC_MAX_REPROS": 2,
            "STATUS_START_CAP": 800, "REFUSAL_CAP": 600, "BUDGET_SCALE": 1.0, "BASE_MAX_MB": 300,
            "CONTEXT_TOKENS": 4600, "GATED": ("locate", "grep", "view", "run", "repro"), "CAP_S": 300,
            "T_LOCATOR": 75, "T_EDIT_NOW": 150, "T_FINISH": 210, "T_TIME": 250, "T_NO_RESTORE": 285}
    assert {k: c.get(k) for k in want} == want
    old = module_constants(V101_SCRIPTS / "_swe_common.py")
    for k in ("RUN_DEFAULT", "RUN_MAX", "VIEW_OBJ", "LOCATE_PARSE", "ORIGIN_PROBE", "VERIFY_TOTAL", "IMPORT_CHECK",
              "CLAIM_TIMEOUT", "CLAIMS_TOTAL", "PYTEST_SIDE", "FINALIZE_QUICK", "HELPER_LIMIT", "CAPS", "CTX_CALL"):
        assert c[k] == old[k], k
    for k, v in c.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and re.search(r"TIMEOUT|DEADLINE|_SECS?$|_WAIT", k):
            assert 0 < v <= 110, (k, v)
    g = module_constants(V102_SCRIPTS / "_swe_gate.py")
    assert g["T_IMPORT_MEASURE"] == 60 and T_LOC_ORDER(c)


def T_LOC_ORDER(c):
    """The close sits between LOCATOR (75) and EDIT NOW (150): the prompt's 'reply by t=90s'."""
    return c["T_LOCATOR"] < c["T_LOC_CLOSE"] < c["T_EDIT_NOW"]


# ------------------------------------------------------------------------------------------------------------ R142
def bundles():
    return sorted(p for p in (ROOT / "submissions").glob("v10*") if (p / "eval_config.yaml").exists()
                  and (p / SC / "_swe_common.py").exists())


def test_cap_parity_every_bundle():
    """R142 / hidden.md T13: BUDGET_SCALE x 60 x max_time_minutes == CAP_S for every bundle under submissions/v10*
    (BUDGET_SCALE 1.0 where a bundle predates it); the prompts' t=300s stays the helper cap."""
    seen = 0
    for b in bundles():
        c = module_constants(b / SC / "_swe_common.py")
        scale = c.get("BUDGET_SCALE", 1.0)
        minutes = load_yaml("eval_config.yaml", b)["evaluation"]["max_time_minutes"]
        assert abs(scale * 60 * minutes - c["CAP_S"]) < 1e-6, (b.name, scale, minutes)
        assert "t=300s" in (b / "prompts" / "locator.md").read_text()
        seen += 1
    assert seen >= 2


def make_variant(out, *flags, base=V102):
    return subprocess.run([sys.executable, str(MV), str(base), str(out), *flags], capture_output=True, text=True,
                          timeout=60)


@pytest.fixture(scope="module")
def cap55(tmp_path_factory):
    out = tmp_path_factory.mktemp("cap") / "v10_2_cap55"
    r = make_variant(out, "--cap", "5.5")
    assert r.returncode == 0, r.stderr
    return out


def test_cap_variant_changes_two_files(cap55):
    """R6: --cap 5.5 changes eval_config.yaml (5.5 minutes) and BUDGET_SCALE (300/330), nothing else; cap parity."""
    a, b = tree(V102), tree(cap55)
    assert set(a) == set(b)
    assert {k for k in a if a[k] != b[k]} == {"eval_config.yaml", SC + "/_swe_common.py"}
    assert load_yaml("eval_config.yaml", cap55)["evaluation"] == {"max_time_minutes": 5.5, "timeout_seconds": 180,
                                                                   "max_tool_calls": 100, "max_turns": 200}
    c = module_constants(cap55 / SC / "_swe_common.py")
    assert abs(c["BUDGET_SCALE"] - 300 / 330) < 1e-12 and abs(c["BUDGET_SCALE"] * 60 * 5.5 - 300) < 1e-9
    for p in (cap55 / SC).glob("*.py"):
        compile(p.read_text(), str(p), "exec")


@pytest.mark.parametrize("real,t,hint", [(231, 210, "FINISH: t>=210s."), (275, 250, "TIME: t>=250s."),
                                         (313.5, 285, None)])
def test_cap_variant_thresholds_in_real_seconds(tmp_path, cap55, real, t, hint):
    """R142: with the real clock (no SWE_FAKE_CLOCK) the --cap 5.5 arm reaches helper t=210 / 250 / 285 (FINISH, TIME,
    the last restore) at 231 / 275 / 313.5 real seconds; real_budget never exceeds the real time left (330 - real)."""
    scripts = copy_helpers(tmp_path, cap55 / SC)
    ws = make_repo(tmp_path, commit_time=time.time() - real)            # the task started `real` seconds ago
    env = helper_env(ws, tmp_path / "sbx" / "swe")
    (ws / "pkg/mod.py").write_text("def parse_header(x):\n    return x * 2\n")    # a source change: no EDIT NOW
    code = ("import json, time\nt0 = C.t0()\nnow = time.time()\n"
            "print(json.dumps([C.clock_scale(), C.clock(), C.real_budget(1000), now - t0, C.hint(None, True)]))\n")
    r = run_py(scripts, code, env=env, cwd=ws)
    assert r.returncode == 0, r.stderr
    scale, clock, rb, elapsed, h = json.loads(r.stdout)
    assert abs(scale - 300 / 330) < 1e-9
    assert t - 0.1 <= clock <= t + 2.0, clock
    assert rb <= 330 - elapsed - 3.9, (rb, elapsed)
    if hint:
        assert h.startswith(hint), h
    else:
        assert clock >= 285 - 0.1 and h.startswith("TIME:"), (clock, h)


def test_pod_scale_composes(tmp_path, cap55):
    """R142: the pod L4 hook ($SWE/clock_scale 1.7) composes with BUDGET_SCALE (1.7 x 0.909), clamped to 0.2..5."""
    scripts = copy_helpers(tmp_path, cap55 / SC)
    ws = make_repo(tmp_path)
    swe = tmp_path / "sbx" / "swe"
    env = helper_env(ws, swe)
    swe.mkdir(parents=True)
    got = []
    for v in ("1.7", "9", "0.01"):
        (swe / "clock_scale").write_text(v)
        r = run_py(scripts, "print(C.clock_scale())", env=env, cwd=ws)
        got.append(float(r.stdout))
    assert abs(got[0] - 1.7 * 300 / 330) < 1e-9 and got[1] == 5.0 and got[2] == 0.2, got
    base = copy_helpers(tmp_path / "base", V102_SCRIPTS)
    (swe / "clock_scale").write_text("1.7")
    assert float(run_py(base, "print(C.clock_scale())", env=env, cwd=ws).stdout) == 1.7    # BUDGET_SCALE 1.0


@pytest.mark.parametrize("flags,msg", [(["--cap", "5"], "is the base itself"), (["--cap", "6.5"], "5 < M <= 6"),
                                       (["--cap", "4.5"], "5 < M <= 6")])
def test_cap_refusals_leave_nothing(tmp_path, flags, msg):
    r = make_variant(tmp_path / "out", *flags)
    assert r.returncode == 2 and msg in r.stderr and not (tmp_path / "out").exists(), r.stderr


def test_cap_refuses_a_v101_base_and_a_stale_base(tmp_path):
    """--cap needs v10.2's BUDGET_SCALE line: v10.1 and a base whose line changed exit 2 and leave no output."""
    r = make_variant(tmp_path / "a", "--cap", "5.5", base=V101)
    assert r.returncode == 2 and "needs a v10.2 bundle" in r.stderr and not (tmp_path / "a").exists()
    base = tmp_path / "base"
    shutil.copytree(V102, base)
    ev = base / "eval_config.yaml"
    ev.write_text(ev.read_text().replace("max_time_minutes: 5", "max_time_minutes: 5.0"))
    r = make_variant(tmp_path / "b", "--cap", "5.5", base=base)
    assert r.returncode == 2 and "eval_config.yaml" in r.stderr and "not once" in r.stderr, r.stderr
    assert not (tmp_path / "b").exists()


def test_cap_composes_with_work_temp(tmp_path):
    r = make_variant(tmp_path / "both", "--cap", "5.5", "--work-temp", "0.2")
    assert r.returncode == 0, r.stderr
    got, base = tree(tmp_path / "both"), tree(V102)
    assert {k for k in base if got[k] != base[k]} == {"eval_config.yaml", SC + "/_swe_common.py",
                                                      "configs/gen_locator.yaml", "configs/gen_fixer.yaml",
                                                      "configs/gen_verifier.yaml"}


# ------------------------------------------------------------------------------------------------ R144 / R145 / R91
def test_prompts_equal_spec_v102():
    """SPEC_v10_2 3.2 and 3.3 rendered with SPEC's shared blocks are the bundle's locator and fixer prompts; the other
    prompts and SKILL.md are v10.1's bytes."""
    text, blocks = SPEC2.read_text(), spec_blocks(spec_text())
    for stage, sec in (("locator", "3.2"), ("fixer", "3.3")):
        m = re.search(r"^### %s `prompts/%s\.md` \(full text\)\n" % (re.escape(sec), stage), text, re.M)
        assert (V102 / "prompts" / (stage + ".md")).read_text() == render_prompt(_fence_after(text, m.end()), blocks)
    for rel in ("prompts/setup.md", "prompts/verifier.md", "prompts/submitter.md", "skills/swe-tools/SKILL.md"):
        assert (V102 / rel).read_bytes() == (V101 / rel).read_bytes(), rel


def test_prompt_rules_v102():
    """R144 (direct): the phrases section 7 requires, the sizes of 3.1, and the fixer's step order."""
    loc, fix = (V102 / "prompts/locator.md").read_text(), (V102 / "prompts/fixer.md").read_text()
    for p in ("the helpers stop answering after 14 calls or at t=90s", "(at most 3 runs before your plan)",
              "never ask for more information", "reply FILES: none", "ALSO:", "(no reasoning inside it)",
              "if it passes again use REPRO: none", "every use of a name you rename or remove"):
        assert p in loc, p
    for p in ("at most 1 round", "1. Run python3 /tmp/swe/status.py first", "LOCATOR DIGEST", "the plan was lost",
              "Change an ALSO place only if verify still fails"):
        assert p in fix, p
    assert "at most 2 rounds" not in fix and "{plan?}" not in fix
    for text, (w, c) in ((loc, (460, 2850)), (fix, (410, 2600))):
        body = text.replace("{problem_description}", "")
        assert len(body.split()) <= w and len(body) <= c
    order = [fix.find(x) for x in ("status.py first", "View the plan's FILES", "smallest COMPLETE change",
                                   "3. Run python3 /tmp/swe/verify.py", "Stop and reply")]
    assert all(i >= 0 for i in order) and order == sorted(order), order


def test_v10_prompt_and_bundle_suites_on_v102():
    """R144 / R145 / R91 / R94 / R95 / R148: tests/test_v10_prompts.py and tests/test_v10_bundle.py pass on the v10.2
    bundle (G4_BUNDLE=submissions/v10_2): the version-aware sizes, phrases and fixer mix, the context margins with
    CONTEXT_TOKENS 4,600, the organisers' compile and the frozen trees."""
    env = dict(os.environ, G4_BUNDLE="submissions/v10_2", PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_v10_prompts.py",
                        "tests/test_v10_bundle.py", "-x"], cwd=str(ROOT), env=env, capture_output=True, text=True,
                       timeout=900)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    assert re.search(r"\b\d+ passed", r.stdout) and " failed" not in r.stdout, r.stdout[-500:]


def test_v101_frozen_pin():
    """R148: submissions/v10 (v10.1 as submitted in sub6) is pinned and unchanged."""
    assert FROZEN["submissions/v10"] == "4b8fa33eb41996b29bc81f34290abf8410908600a1a9005e7a300762ec5396fd"
    assert tree_sha256(V101) == FROZEN["submissions/v10"]


def test_validate_and_pack(tmp_path):
    """Rung 1: scripts/validate.py compiles v10.2 with the organisers' compiler (when installed) and the pack is
    deterministic (not uploaded)."""
    if importlib_missing("adk_submission", "swegemma"):
        pytest.skip("organisers' compiler not installed here")
    r = subprocess.run([sys.executable, str(ROOT / "scripts/validate.py"), str(V102)], capture_output=True, text=True,
                       timeout=300, cwd=str(ROOT), env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-1500:] + r.stderr[-1500:]
    shas = []
    for n in ("a", "b"):
        p = subprocess.run([sys.executable, str(ROOT / "scripts/pack_bundle.py"), str(V102), str(tmp_path / (n + ".zip"))],
                           capture_output=True, text=True, timeout=60)
        assert p.returncode == 0, p.stderr
        shas.append(p.stdout.split()[0])
    assert shas[0] == shas[1]
    assert not list(V102.rglob("__pycache__"))


def importlib_missing(*mods):
    import importlib.util
    return any(importlib.util.find_spec(m) is None for m in mods)


# ------------------------------------------------------------------------------------------------ E6 / R143 (static)
def test_linux_script_python_parameter():
    """E6 / R143: scripts/linux_test.sh takes PY=3.12 (default) or PY=3.13 for both modes and refuses anything else;
    bash -n and shellcheck are clean."""
    p = ROOT / "scripts" / "linux_test.sh"
    s = p.read_text()
    assert 'PY="${PY:-3.12}"' in s and s.count('"python:${PY}-slim"') == 2 and "python:3.12-slim bash" not in s
    assert subprocess.run(["bash", "-n", str(p)]).returncode == 0
    # MIN_FREE_GB far above any disk: a bad PY must still fail as a bad argument (exit 2), before the host free-disk guard
    r = subprocess.run(["bash", str(p)], env=dict(os.environ, PY="3.11", MIN_FREE_GB="1000000"), capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 2 and "PY must be 3.12 or 3.13" in r.stderr
    if shutil.which("shellcheck"):
        assert subprocess.run(["shellcheck", str(p)], capture_output=True).returncode == 0


def v10_only_copy(dst):
    """Run linux_test.sh's V10_ONLY copy-and-link lines (from `mkdir -p /tmp/g4` up to `cd /tmp/g4`) with /g4 -> this
    repo and /tmp/g4 -> dst: the tree the container's pytest collects."""
    s = (ROOT / "scripts" / "linux_test.sh").read_text()
    block = s.split("read -r -d '' STAGE_SCRIPT <<'SH' || true\n", 1)[1].split("\nSH\n", 1)[0]   # shared staging (2026-10-15)
    start, end = block.index("mkdir -p /tmp/g4"), block.index("cd /tmp/g4 || exit 1")
    cmds = block[start:end].replace("/tmp/g4", "@DST@").replace("/g4", "@SRC@")
    cmds = cmds.replace("@DST@", str(dst)).replace("@SRC@", str(ROOT))
    r = subprocess.run(["bash", "-c", "set -e\n" + cmds], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    return pathlib.Path(dst)


def test_linux_v10_only_copy_collects(tmp_path):
    """Regression (2026-09-30): the V10_ONLY container linked only eval/race1 and eval/kaggle, so tests/test_v10_2_eval.py
    (golden_metrics lives in eval/golden) failed to import, the collection error aborted pytest ("1 error in 25s"), and
    the Linux job tested nothing. The copy now links eval/golden, and the v10 glob collects with no error there; a copy
    without eval/golden skips that module instead of aborting the collection."""
    dst = v10_only_copy(tmp_path / "g4")
    assert (dst / "eval" / "golden" / "golden_metrics.py").is_file()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", G4_BUNDLE="submissions/v10_2")
    tests = sorted(str(p.relative_to(dst)) for p in (dst / "tests").glob("test_v10_*.py"))
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"] + tests +
                       ["tests/test_make_variant_v10.py"], cwd=str(dst), env=env, capture_output=True, text=True,
                       timeout=600)
    assert r.returncode == 0 and "error" not in r.stdout.lower().split("\n")[-2], r.stdout[-2000:] + r.stderr[-1000:]
    assert "tests/test_v10_2_eval.py::test_scratch_rule_parity_with_the_bundle" in r.stdout
    (dst / "eval" / "golden").unlink()                                   # the pre-fix layout
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"] + tests,
                       cwd=str(dst), env=env, capture_output=True, text=True, timeout=600)
    last = r.stdout.strip().split("\n")[-1]
    assert r.returncode == 0 and re.match(r"^\d+ tests collected", last) and "error" not in last, r.stdout[-1500:]
    assert "tests/test_v10_2_eval.py::" not in r.stdout and "tests/test_v10_2_verify.py::" in r.stdout
