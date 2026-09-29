"""make_variant.py v10 levers for the next faithful Kaggle-L4 A/B (docs/v10/AB_L4.md, 2026-09-29).

One test (or more) per mechanism of docs/v10/v10_1_diag_5.md section 4 that an arm changes, base and edge cases, each
with a control on the unchanged v10.1 base:
- the committed arms (submissions/v10_1_flip, _sweep, _t02) are exactly what make_variant builds from submissions/v10
  now, and each changes only its lever's files;
- lever A (--flip): the locator phase's own CONTEXT threshold while t < 75 s; verify's NEXT line on the two AMBER cases
  without a failing claim, and never after FINISH;
- lever B (--sweep): edit.py prints SAME CODE ELSEWHERE (the removed-line scan, rarer patterns first) and drops generic
  lines; SIBLINGS keeps a same-named def only when its code repeats a removed line; verify prints SIBLINGS when a
  hanging claim ate the quick-mode deadline (rich_3480); the scan is fast;
- a stale patch (the base changed under make_variant) exits 2 and leaves no bundle.
Every helper runs from a temp copy (no __pycache__ in submissions/).
"""
import json, os, pathlib, re, shutil, subprocess, sys, time
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from v10_support.repo import no_orphans, make_repo, copy_helpers, helper_env, run_helper, run_py, git  # noqa: F401,E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "submissions" / "v10"
MV = ROOT / "scripts" / "make_variant.py"
SC = "skills/swe-tools/scripts"
VBIN = str(pathlib.Path(sys.executable).parent)
# The arms of docs/v10/AB_L4.md: bundle -> make_variant flags, and the only files each may change.
ARMS = {
    "v10_1_flip": (["--flip"], {SC + "/_swe_common.py", SC + "/_swe_gate.py", "prompts/fixer.md"}),
    "v10_1_sweep": (["--sweep"], {SC + "/_swe_gate.py", SC + "/edit.py"}),
    "v10_1_t02": (["--work-temp", "0.2"], {"configs/gen_locator.yaml", "configs/gen_fixer.yaml",
                                          "configs/gen_verifier.yaml"}),
}


def make_variant(out, *flags, base=BASE):
    return subprocess.run([sys.executable, str(MV), str(base), str(out), *flags], capture_output=True, text=True,
                          timeout=60)


def tree(d):
    d = pathlib.Path(d)
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts and not p.name.startswith("._") and p.name != ".DS_Store"}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Each lever built from the current v10 base: {arm: bundle dir}."""
    root = tmp_path_factory.mktemp("arms")
    out = {}
    for arm, (flags, _) in ARMS.items():
        r = make_variant(root / arm, *flags)
        assert r.returncode == 0, r.stderr
        out[arm] = root / arm
    return out


# ------------------------------------------------------------------------------------------------ the arms themselves
@pytest.mark.parametrize("arm", sorted(ARMS))
def test_committed_arm_is_fresh(built, arm):
    """submissions/<arm> is byte-identical to a fresh make_variant build from submissions/v10: an arm never drifts from
    'the v10.1 control plus one lever' (rebuild with the command in docs/v10/AB_L4.md when v10 changes)."""
    committed = ROOT / "submissions" / arm
    assert committed.is_dir(), "build it: python scripts/make_variant.py submissions/v10 submissions/%s %s" % (
        arm, " ".join(ARMS[arm][0]))
    assert tree(committed) == tree(built[arm]), sorted(k for k in set(tree(committed)) | set(tree(built[arm]))
                                                        if tree(committed).get(k) != tree(built[arm]).get(k))


@pytest.mark.parametrize("arm", sorted(ARMS))
def test_arm_changes_only_its_lever(built, arm):
    base, got = tree(BASE), tree(built[arm])
    assert set(got) == set(base), set(got) ^ set(base)
    changed = {k for k in got if got[k] != base[k]}
    assert changed == ARMS[arm][1], changed


def test_t02_only_temperature():
    """Lever D: the three working stages at T 0.2 (setup and submitter already are), nothing else in those files."""
    for st in ("locator", "fixer", "verifier"):
        a = (BASE / "configs" / ("gen_%s.yaml" % st)).read_text()
        b = (ROOT / "submissions" / "v10_1_t02" / "configs" / ("gen_%s.yaml" % st)).read_text()
        assert re.search(r"^temperature: 0\.2$", b, re.M) and b.replace("temperature: 0.2", "temperature: 1.0") == a


def test_levers_compose_and_compile(tmp_path):
    """--flip and --sweep patch different anchors, so a later combined arm builds from both; every script compiles."""
    r = make_variant(tmp_path / "both", "--flip", "--sweep")
    assert r.returncode == 0, r.stderr
    got = tree(tmp_path / "both")
    for arm in ("v10_1_flip", "v10_1_sweep"):
        for k in ARMS[arm][1]:
            assert got[k] != tree(BASE)[k], k
    for p in (tmp_path / "both" / SC).glob("*.py"):
        compile(p.read_text(), str(p), "exec")


def test_v10_levers_refuse_non_v10(tmp_path):
    for flag in ("--flip", "--sweep"):
        r = make_variant(tmp_path / "v4x", flag, base=ROOT / "submissions" / "v4")
        assert r.returncode == 2 and "v10 levers" in r.stderr, r.stderr
        assert not (tmp_path / "v4x").exists()


def test_stale_patch_exits_2_and_leaves_nothing(tmp_path):
    """Base case of the exact-once rule: when the base no longer holds the text a lever patches, make_variant names the
    file and removes the half-built output (never a bundle with half a lever)."""
    base = tmp_path / "base"
    shutil.copytree(BASE, base, ignore=shutil.ignore_patterns("__pycache__"))
    p = base / "prompts" / "fixer.md"
    p.write_text(p.read_text().replace("for REGRESSIONS follow its note.", "for REGRESSIONS read its note."))
    r = make_variant(tmp_path / "out", "--flip", base=base)
    assert r.returncode == 2 and "prompts/fixer.md" in r.stderr and "not once" in r.stderr, r.stderr
    assert not (tmp_path / "out").exists()
    r = make_variant(base, "--flip", base=base)                   # never overwrite the base itself
    assert r.returncode == 2 and (base / "agent.yaml").exists()


# ------------------------------------------------------------------------------ --repair-rounds (ablation arm A0)
# docs/eval/ABLATION_REPAIR.md: A0 is v10.1 with repair rounds = 0; the lever exists only because the review of
# 2026-09-30 found the pre-registered A0 arm could not be built (make_variant had no such lever).
REPAIR_FILES = {"prompts/fixer.md", "prompts/verifier.md"}


def _step3(text):
    return next(ln for ln in text.splitlines() if ln.startswith("3. Run python3 /tmp/swe/verify.py"))


def test_repair_rounds_zero_is_arm_a0(tmp_path):
    """Base case: --repair-rounds 0 changes only the two prompts' repair lines; everything else is byte-identical."""
    r = make_variant(tmp_path / "a0", "--repair-rounds", "0")
    assert r.returncode == 0, r.stderr
    base, got = tree(BASE), tree(tmp_path / "a0")
    assert set(got) == set(base) and {k for k in got if got[k] != base[k]} == REPAIR_FILES
    fx = (tmp_path / "a0" / "prompts" / "fixer.md").read_text()
    assert _step3(fx) == ("3. Run python3 /tmp/swe/verify.py once, for its first line only; do not edit after it (no "
                          "repair round).")
    assert "at most 2 rounds" not in fx and "VERIFY: the first line verify printed" in fx
    bfx = (BASE / "prompts" / "fixer.md").read_text()
    assert fx.replace(_step3(fx), _step3(bfx)) == bfx                           # one line, nothing else
    vr = (tmp_path / "a0" / "prompts" / "verifier.md").read_text()
    assert "- RED: go to step 4 (no repair round).\n- REGRESSIONS: go to step 4 (no repair round).\n" in vr
    assert "repair rounds" not in vr and "fix the regression" not in vr
    assert "4. Run python3 /tmp/swe/finalize.py" in vr                            # finalize is not a verify round


def test_repair_rounds_one_and_five_only_change_the_count(tmp_path):
    for n, word in ((1, "round"), (5, "rounds")):
        r = make_variant(tmp_path / str(n), "--repair-rounds", str(n))
        assert r.returncode == 0, r.stderr
        got = tree(tmp_path / str(n))
        assert {k for k in got if got[k] != tree(BASE)[k]} == REPAIR_FILES
        fx = (tmp_path / str(n) / "prompts" / "fixer.md").read_text()
        assert fx == (BASE / "prompts" / "fixer.md").read_text().replace("at most 2 rounds:", "at most %d %s:" % (n, word))
        vr = (tmp_path / str(n) / "prompts" / "verifier.md").read_text()
        assert vr == (BASE / "prompts" / "verifier.md").read_text().replace(
            "at most 2 repair rounds, none", "at most %d repair %s, none" % (n, word))


@pytest.mark.parametrize("flags,msg", [
    (["--repair-rounds", "2"], "is the base itself"),            # B2 is the unchanged base, never a rebuilt copy
    (["--repair-rounds", "-1"], "0 <= N <= 5"),
    (["--repair-rounds", "6"], "0 <= N <= 5"),
    (["--repair-rounds", "0", "--flip"], "--flip extends"),     # A0 replaces the step --flip appends to
])
def test_repair_rounds_refusals_leave_nothing(tmp_path, flags, msg):
    r = make_variant(tmp_path / "x", *flags)
    assert r.returncode == 2 and msg in r.stderr, r.stderr
    assert not (tmp_path / "x").exists()


def test_repair_rounds_refuses_non_v10_and_a_stale_base(tmp_path):
    r = make_variant(tmp_path / "v4x", "--repair-rounds", "0", base=ROOT / "submissions" / "v4")
    assert r.returncode == 2 and "v10 lever" in r.stderr and not (tmp_path / "v4x").exists()
    base = tmp_path / "base"
    shutil.copytree(BASE, base, ignore=shutil.ignore_patterns("__pycache__"))
    p = base / "prompts" / "verifier.md"
    p.write_text(p.read_text().replace("at most 2 repair rounds", "at most two repair rounds"))
    for n in ("0", "1"):
        r = make_variant(tmp_path / "out", "--repair-rounds", n, base=base)
        assert r.returncode == 2 and "prompts/verifier.md" in r.stderr and "not once" in r.stderr, r.stderr
        assert not (tmp_path / "out").exists()


def test_repair_rounds_composes_with_flip_and_sweep(tmp_path):
    """--repair-rounds 1 patches only the round count, so it builds on top of --flip (which extends the same step)."""
    r = make_variant(tmp_path / "both", "--flip", "--sweep", "--repair-rounds", "1")
    assert r.returncode == 0, r.stderr
    fx = (tmp_path / "both" / "prompts" / "fixer.md").read_text()
    assert "at most 1 round:" in fx and "AMBER: follow its NEXT line." in fx


def test_repair_arm_compiles_and_the_golden_runner_accepts_it(tmp_path):
    """The A0 arm compiles with the organisers' compiler (scripts/validate.py) and has the five sub-agents the golden
    runner needs; its bundle sha differs from the base's, which summary.py ablation checks (B2 != A0)."""
    r = make_variant(tmp_path / "a0", "--repair-rounds", "0")
    assert r.returncode == 0, r.stderr
    env = dict(os.environ, LITELLM_LOCAL_MODEL_COST_MAP="True")
    v = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(tmp_path / "a0")],
                       capture_output=True, text=True, timeout=300, env=env)
    assert v.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in v.stdout, v.stdout[-2000:] + v.stderr[-2000:]
    sys.path.insert(0, str(ROOT / "scripts" / "golden"))
    import run_suite as RS
    assert RS.check_bundle(tmp_path / "a0") == list(RS.EXPECTED_AGENTS)
    assert RS.bundle_sha(tmp_path / "a0") != RS.bundle_sha(BASE)


# ------------------------------------------------------------------------------------------------ helpers under test
def scripts_of(tmp_path, bundle, name="scripts"):
    d = tmp_path / name
    d.mkdir()
    for p in (pathlib.Path(bundle) / SC).glob("*.py"):
        shutil.copyfile(p, d / p.name)
    return d


def env_at(ws, swe, t):
    e = helper_env(ws, swe, fake_t=t)
    e["PATH"] = VBIN + os.pathsep + e.get("PATH", "")
    return e


def helper(scripts, name, args=(), *, ws, swe, t=100, stdin=None, timeout=90):
    r = run_helper(scripts, name, list(args), ws=ws, env=env_at(ws, swe, t), stdin=stdin, timeout=timeout)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "HELPER ERROR" not in r.stdout and "Traceback (most recent" not in r.stdout, r.stdout
    return r.stdout


def py_out(scripts, code):
    r = run_py(scripts, code)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# ------------------------------------------------------------------------------------------------ lever A: --flip
def test_flip_ctx_limit_values(tmp_path, built):
    """test_ctx_locator_threshold (diag 5): the locator phase has 7,000 before t=75 s; the fixer, verifier and a late
    locator keep 4,700 (the R95 value)."""
    sc = scripts_of(tmp_path, built["v10_1_flip"])
    got = json.loads(py_out(sc, "import json\nprint(json.dumps([C.ctx_limit(p, t) for p, t in "
                                "[('locator', 10), (None, 74.9), ('locator', 75), ('fixer', 10), ('verifier', 10), "
                                "('locator', 'x')]] + [C.CONTEXT_TOKENS, C.CONTEXT_TOKENS_LOCATOR]))"))
    assert got == [7000, 7000, 4700, 4700, 4700, 4700, 4700, 7000]


def _big(ws):
    body = "".join("def fn_%03d(value):\n    return value + %d  # %s\n" % (i, i, "c" * 40) for i in range(60))
    (ws / "pkg" / "big.py").write_text(body)


def _views_until_context(sc, ws, swe, t, max_calls=14):
    env = env_at(ws, swe, t)
    for i in range(max_calls):
        r = run_helper(sc, "view", ["pkg/big.py", str(1 + i), str(100 + i)], ws=ws, env=env)
        if "CONTEXT:" in r.stdout:
            return json.loads((swe / "state.json").read_text())["ctx"]["n"], i + 1
    return json.loads((swe / "state.json").read_text())["ctx"]["n"], None


@pytest.mark.parametrize("arm,t,lo,hi", [("v10_1_flip", 30, 7000, 8200), ("v10", 30, 4700, 5900),
                                         ("v10_1_flip", 80, 4700, 5900)])
def test_flip_locator_context_through_real_helpers(tmp_path, built, arm, t, lo, hi):
    """Locator-phase views (no edit yet) reach CONTEXT at 7,000 estimated tokens before t=75 s in the flip arm; the
    base (control) and a flip locator at t=80 s show it at 4,700."""
    sc = scripts_of(tmp_path, built[arm] if arm in built else BASE)
    ws = make_repo(tmp_path)
    _big(ws)
    n, calls = _views_until_context(sc, ws, tmp_path / "sbx" / "swe", t)
    assert calls is not None and lo <= n < hi, (arm, t, n, calls)


def _amber_repo(tmp_path):
    ws = make_repo(tmp_path, {"pkg/__init__.py": "", "pkg/mod.py": "def double(x):\n    return x + 1\n",
                              "tests/__init__.py": "",
                              "tests/test_mod.py": "from pkg.mod import double\n\n\ndef test_zero():\n"
                                                   "    assert double(0) in (0, 1)\n"})
    (ws / "pkg" / "mod.py").write_text("def double(x):\n    return x * 2\n")
    return ws


@pytest.mark.parametrize("repro,reason", [
    (None, "no reproduction saved"),
    ("from pkg.mod import double\n# CLAIM 1: one doubles to two\nassert double(1) == 2, double(1)\n",
     "the reproduction passes on original"),
])
def test_amber_next_requires_flip(tmp_path, built, repro, reason):
    """test_amber_next_requires_flip (diag 5): both AMBER cases without a failing claim give a NEXT line asking for a
    claim that fails on original, with the issue's literal inputs and the heredoc form; from FINISH (210 s) on it is
    the plain READY line (no new repro late). Control: the base prints READY in the same state."""
    flip = scripts_of(tmp_path, built["v10_1_flip"], "flip")
    base = scripts_of(tmp_path, BASE, "base")
    outs = {}
    for name, sc, t in (("flip", flip, 100), ("late", flip, 215), ("base", base, 100)):
        ws = _amber_repo(tmp_path / name)
        swe = tmp_path / name / "sbx" / "swe"
        if repro:
            helper(sc, "verify", ["--repro-only"], ws=ws, swe=swe, t=t - 5, stdin=repro)
        outs[name] = helper(sc, "verify", [], ws=ws, swe=swe, t=t)
        assert ("VERIFY: AMBER - " + reason) in outs[name], outs[name]
    nxt = [ln for ln in outs["flip"].splitlines() if ln.startswith("NEXT:")]
    assert nxt and "no claim fails on original yet" in nxt[0], outs["flip"]
    for want in ("python3 /tmp/swe/verify.py --repro-only <<'EOF' ... EOF", "# CLAIM 1:", "literal inputs",
                 "return value", "every position", "change the code, not the claim", "Verifier: run python3 /tmp/swe/finalize.py"):
        assert want in nxt[0], want
    for name in ("late", "base"):
        assert "NEXT: ready. Fixer: reply with your notes." in outs[name], (name, outs[name])
        assert "no claim fails on original" not in outs[name]


def test_flip_green_stays_ready(tmp_path, built):
    """Edge: a claim that fails on original and passes now is GREEN with the READY line in the flip arm too."""
    sc = scripts_of(tmp_path, built["v10_1_flip"])
    ws = _amber_repo(tmp_path)
    swe = tmp_path / "sbx" / "swe"
    helper(sc, "verify", ["--repro-only"], ws=ws, swe=swe, t=90,
           stdin="from pkg.mod import double\n# CLAIM 1: three doubles to six\nassert double(3) == 6, double(3)\n")
    out = helper(sc, "verify", [], ws=ws, swe=swe, t=100)
    assert "VERIFY: GREEN" in out and "NEXT: ready." in out and "no claim fails" not in out, out


# ------------------------------------------------------------------------------------------------ lever B: --sweep
SPANS = '''class Text:
    def __init__(self):
        self._spans = []
        self.plain = ""

    def append(self, text):
        offset = len(self.plain)
        for start, end, style in text._spans:
            self._spans.append((offset + start, offset + end, style))
        self.plain += text.plain
        return self

    def append_text(self, text):
        offset = len(self.plain)
        for start, end, style in text._spans:
            self._spans.append((offset + start, offset + end, style))
        self.plain += text.plain
        return self

    def render(self, width, options):
        result = compute_width(self, width=width,
                               options=options)
        return result
'''
OTHER = '''def append(value):
    """A same-name def with different code: never a sibling."""
    return [value]


def render(width, options):
    result = compute_width(None, width=width,
                           options=options)
    return result
'''
FIX_SPANS = ("<<<<<<< SEARCH\n    def append(self, text):\n        offset = len(self.plain)\n"
             "        for start, end, style in text._spans:\n"
             "            self._spans.append((offset + start, offset + end, style))\n=======\n"
             "    def append(self, text):\n        offset = len(self.plain)\n"
             "        for start, end, style in text._spans:\n"
             "            self._spans.append((offset + start, offset + end, style or None))\n>>>>>>> REPLACE\n"
             "<<<<<<< SEARCH\n                               options=options)\n=======\n"
             "                               options=options or {})\n>>>>>>> REPLACE\n")


def _spans_repo(tmp_path, extra=None):
    files = {"pkg/__init__.py": "", "pkg/text.py": SPANS, "pkg/other.py": OTHER, "tests/__init__.py": "",
             "tests/test_text.py": "from pkg.text import Text\n\n\ndef test_t():\n    assert Text().plain == ''\n"}
    files.update(extra or {})
    return make_repo(tmp_path, files)


def test_edit_prints_same_code_elsewhere(tmp_path, built):
    """test_edit_prints_same_code_elsewhere (diag 5, rich_3480): fixing the spans loop in append prints the same line in
    append_text; the same-name def in pkg/other.py and the generic 'options=options)' line are not listed.
    Control: the base edit.py prints no such block."""
    for arm, want in (("v10_1_sweep", True), ("v10", False)):
        (tmp_path / arm).mkdir()
        sc = scripts_of(tmp_path / arm, built.get(arm, BASE))
        ws = _spans_repo(tmp_path / arm)
        out = helper(sc, "edit", ["pkg/text.py"], ws=ws, swe=tmp_path / arm / "sbx" / "swe", t=120,
                     stdin=FIX_SPANS)
        assert out.startswith("OK"), out
        assert ("SAME CODE ELSEWHERE" in out) is want, (arm, out)
        if want:
            block = out.split("SAME CODE ELSEWHERE", 1)[1]
            rows = [ln for ln in block.splitlines() if ln.startswith("  pkg/")]
            assert rows and rows[0].startswith("  pkg/text.py:16  ") and "self._spans.append" in rows[0], rows
            assert "pkg/other.py" not in block, block                   # generic line, same-name def
            assert out.rstrip().splitlines()[-2].startswith("NEXT: python3 /tmp/swe/verify.py"), out
            assert len(out) <= 1500


@pytest.mark.parametrize("line,generic", [
    ("width=width,", True), ("options=options)", True), ("return None", True), ("import os", True),
    ("self.x = y", True), ('"""', True), ("pass", True), ("for start, end, style in text._spans:", False),
    ("result = compute_width(cell, options)", False), ("first_field = body_fields[0]", False),
])
def test_generic_lines(tmp_path, built, line, generic):
    """Edge cases of the scan's filter: pass-through keywords, bare returns, imports, attribute stores and docstring
    quotes are dropped; real code lines (the fastapi_11194 second site) are kept."""
    sc = scripts_of(tmp_path, built["v10_1_sweep"])
    got = py_out(sc, "import _swe_gate as G\nprint(G.generic_line(%r))" % line)
    assert got == str(generic), (line, got)


def test_same_code_ranking(tmp_path, built):
    """Whole-line matches rank before lines that only hold a long call from the removed code; within a rank the rarer
    pattern comes first (a line copied 10 times cannot hide a specific one); the edited file's changed lines are never
    listed; the limit holds."""
    sc = scripts_of(tmp_path, built["v10_1_sweep"])
    common = "value = normalize_value(value)"
    files = {"pkg/__init__.py": "", "pkg/a.py": "def f(x):\n    total = accumulate_parts(x, 3)\n    %s\n    return total\n"
             % common,
             "pkg/b.py": "def g(x):\n    y = [total_of(x)] + [accumulate_parts(x, 3)]\n    return y\n",
             "pkg/z.py": "def h(x):\n    total = accumulate_parts(x, 3)\n    return total\n"}
    for i in range(10):
        files["pkg/n%02d.py" % i] = "def k(value):\n    %s\n    return value\n" % common
    ws = make_repo(tmp_path, files)
    (ws / "pkg" / "a.py").write_text("def f(x):\n    total = accumulate_parts(x, 4)\n    return total\n")
    code = ("import json, _swe_gate as G\nf = G.diff_facts(C.diff_bytes())\n"
            "print(json.dumps([G.same_code(f, %r), G.same_code(f, %r, limit=20)]))" % (str(ws), str(ws)))
    r = run_py(sc, code, env=helper_env(ws, tmp_path / "sbx" / "swe"), cwd=ws)
    assert r.returncode == 0, r.stderr
    six, rows = json.loads(r.stdout)
    assert six[0].startswith("  pkg/z.py:2  ") and len(six) == 6, six             # the rare exact line first
    assert all("normalize_value" in x for x in six[1:]), six
    assert len(rows) == 12 and rows[-1].startswith("  pkg/b.py:2  "), rows          # the call-only match last
    assert not any(x.startswith("  pkg/a.py") for x in rows), rows


def test_siblings_same_name_needs_same_code(tmp_path, built):
    """Full-mode verify (t=100 s): a same-named def elsewhere is listed only when its body repeats a line the change
    removed (B.render_row, as in the v10 test); one with different code is dropped (the rich_3063 / fastapi_14986 /
    rich_3905 noise). Control: the base lists both."""
    twin = ("class A:\n    def render_row(self, x):\n        return x.strip()\n\n\n"
            "class B:\n    def render_row(self, x):\n        return x.strip()\n")
    other = "class C:\n    def render_row(self, x):\n        return x.upper().center(10)\n"
    outs = {}
    for arm in ("v10_1_sweep", "v10"):
        (tmp_path / arm).mkdir()
        sc = scripts_of(tmp_path / arm, built.get(arm, BASE))
        ws = make_repo(tmp_path / arm, {"pkg/__init__.py": "", "pkg/twin.py": twin, "pkg/other.py": other})
        (ws / "pkg" / "twin.py").write_text(twin.replace("return x.strip()", "return x.strip(' ')", 1))
        outs[arm] = helper(sc, "verify", [], ws=ws, swe=tmp_path / arm / "sbx" / "swe", t=100)
    sib = outs["v10_1_sweep"][outs["v10_1_sweep"].index("SIBLINGS"):]
    assert "B.render_row" in sib and "pkg/other.py" not in sib, outs["v10_1_sweep"]
    base = outs["v10"][outs["v10"].index("SIBLINGS"):]
    assert "B.render_row" in base and "pkg/other.py" in base, outs["v10"]


def test_siblings_in_quick_mode(tmp_path, built):
    """test_siblings_in_quick_mode (diag 5, rich_3480): a hanging claim eats verify's end-game deadline (t=256 s), and
    SIBLINGS is still printed; same-name defs are not. Control: the base skips SIBLINGS in the same state."""
    repro = ("from pkg.text import Text\nimport time\n# CLAIM 1: append terminates\ntime.sleep(60)\n"
             "assert Text().append(Text()).plain == ''\n")
    outs = {}
    for arm in ("v10_1_sweep", "v10"):
        (tmp_path / arm).mkdir()
        sc = scripts_of(tmp_path / arm, built.get(arm, BASE))
        ws = _spans_repo(tmp_path / arm)
        swe = tmp_path / arm / "sbx" / "swe"
        src = (ws / "pkg" / "text.py").read_text()
        (ws / "pkg" / "text.py").write_text(src.replace("offset + end, style))\n        self.plain += text.plain\n"
                                                        "        return self\n\n    def append_text",
                                                        "offset + end, style or None))\n        self.plain += "
                                                        "text.plain\n        return self\n\n    def append_text", 1))
        swe.mkdir(parents=True)
        (swe / "repro.py").write_text(repro)          # saved, never run: both sides then hang inside this verify
        t0 = time.monotonic()
        outs[arm] = helper(sc, "verify", [], ws=ws, swe=swe, t=256, timeout=60)
        assert time.monotonic() - t0 < 20, outs[arm]
    assert "SIBLINGS" in outs["v10_1_sweep"] and "pkg/text.py:16" in outs["v10_1_sweep"], outs["v10_1_sweep"]
    assert "same name as your changed" not in outs["v10_1_sweep"]
    assert "SIBLINGS" not in outs["v10"], outs["v10"]


def test_same_code_scan_is_fast(tmp_path, built):
    """Edge: the scan stays under 0.5 s on a 3,000-file repository (fastapi has about 2,500 .py files)."""
    sc = scripts_of(tmp_path, built["v10_1_sweep"])
    files = {"pkg/__init__.py": "", "pkg/text.py": SPANS}
    for i in range(3000):
        files["pkg/m%02d/f%04d.py" % (i % 30, i)] = ("def fn_%d(value, options):\n    total = combine_parts(value, %d)\n"
                                                     "    return total\n" % (i, i))
    ws = make_repo(tmp_path, files)
    (ws / "pkg" / "text.py").write_text(SPANS.replace("offset + end, style))", "offset + end, style or None))", 1))
    code = ("import json, time, _swe_gate as G\nf = G.diff_facts(C.diff_bytes())\nt = time.perf_counter()\n"
            "rows = G.same_code(f, %r)\nprint(json.dumps([time.perf_counter() - t, rows]))" % str(ws))
    r = run_py(sc, code, env=helper_env(ws, tmp_path / "sbx" / "swe"), cwd=ws)
    assert r.returncode == 0, r.stderr
    secs, rows = json.loads(r.stdout)
    assert rows and rows[0].startswith("  pkg/text.py:16"), rows
    assert secs < 0.5, secs


def test_edit_scan_uses_whole_lines_only(tmp_path, built):
    """Regression (measured 2026-09-29): with call patterns, the scan inside edit.py grew to 0.44 s after 8 edits (4 -F
    patterns sharing a prefix made git grep take 0.24-0.39 s); edit.py now greps whole removed lines only (about
    +50 ms per edit, paired, on a loaded Mac). verify keeps the call patterns. The edit-time scan stays fast after 20
    accumulated edits."""
    sc = scripts_of(tmp_path, built["v10_1_sweep"])
    body = "".join("def fn_%04d(value):\n    return compute_total(value, %d)\n\n\n" % (i, i) for i in range(1250))
    files = {"pkg/__init__.py": "", "pkg/big.py": body}
    for i in range(300):
        files["pkg/m/f%03d.py" % i] = "def g_%d(value):\n    return compute_total(value, %d)\n" % (i, i)
    ws = make_repo(tmp_path, files)
    for k in range(20):
        body = body.replace("compute_total(value, %d)\n" % k, "compute_total(value, %d) + 0\n" % k, 1)
    (ws / "pkg" / "big.py").write_text(body)
    code = ("import json, os, time, _swe_gate as G\nseen = []\nreal = G._git\n"
            "def spy(args, *a, **k):\n    seen.append(list(args))\n    return real(args, *a, **k)\nG._git = spy\n"
            "f = G.diff_facts(C.diff_bytes())\nt = time.perf_counter()\n"
            "rows = G.same_code(f, paths=['pkg/big.py'], limit=3, timeout=2, calls=False)\n"
            "secs = time.perf_counter() - t\nG.same_code(f, paths=['pkg/big.py'])\n"
            "print(json.dumps([secs, rows, seen, os.getloadavg()[0], os.cpu_count()]))")
    r = run_py(sc, code, env=helper_env(ws, tmp_path / "sbx" / "swe"), cwd=ws)
    assert r.returncode == 0, r.stderr
    secs, rows, seen, load, cpus = json.loads(r.stdout)
    pats = [seen[0][i + 1] for i, a in enumerate(seen[0]) if a == "-e"]
    assert pats and all(p.startswith("return compute_total(value, ") and p.endswith(")") for p in pats), pats
    assert len(pats) == 8                                                  # SAME_PATS
    assert any(not p.endswith(")") for i, p in enumerate(seen[1]) if seen[1][i - 1] == "-e")   # verify: calls too
    assert rows and all(":" in x for x in rows), rows
    assert secs < (0.2 if load <= cpus else 1.0), (secs, load)


# ------------------------------------------------------------------------------------------------ the A/B document
def test_ab_doc_names_every_arm_and_command():
    """docs/v10/AB_L4.md carries, per arm, the make_variant command that builds it and the make_eval_kernel command,
    plus the pre-registered rule; the doc and ARMS cannot drift apart."""
    doc = (ROOT / "docs" / "v10" / "AB_L4.md").read_text()
    for arm, (flags, _) in ARMS.items():
        assert "python scripts/make_variant.py submissions/v10 submissions/%s %s" % (arm, " ".join(flags)) in doc, arm
        assert re.search(r"python scripts/make_eval_kernel\.py submissions/%s \S+ --ids data/kaggle_valid_ids\.txt"
                         % arm, doc), arm
    assert re.search(r"python scripts/make_eval_kernel\.py submissions/v10 \S+ --ids data/kaggle_valid_ids\.txt", doc)
    for must in ("+4", "1.1", "14 h", "00:01 UTC", "no new crash class"):
        assert must in doc, must


def test_linux_gate_runs_the_arms():
    """The Linux gate (scripts/linux_test.sh, V10_ONLY) forwards G4_BUNDLE, so each arm's helpers run the v10 suite on
    Linux under the Docker scorer's limits, and it always runs this file (the lever code on Linux)."""
    s = (ROOT / "scripts" / "linux_test.sh").read_text()
    v10 = s[s.index('if [ "${V10_ONLY:-0}" = 1 ]'):s.index('bash -c "$V10_SCRIPT"')]
    assert '-e "G4_BUNDLE=${G4_BUNDLE:-}"' in v10 and "tests/test_make_variant_v10.py" in v10
    assert subprocess.run(["bash", "-n", str(ROOT / "scripts" / "linux_test.sh")]).returncode == 0
    for mod in ("test_v10_bundle.py", "test_v10_edit.py", "test_v10_verify.py", "v10_support/repo.py",
                "v10_support/sandbox.py"):
        assert '(os.environ.get("G4_BUNDLE") or "submissions/v10")' in (ROOT / "tests" / mod).read_text(), mod


KERNELS = {"g4-l4-v101": "v10", "g4-l4-v101-flip": "v10_1_flip", "g4-l4-v101-sweep": "v10_1_sweep",
           "g4-l4-v101-t02": "v10_1_t02"}


@pytest.mark.parametrize("slug", sorted(KERNELS))
def test_built_kernels_carry_the_committed_bundles(slug):
    """The four A/B kernels under kernels/ embed exactly today's bundle bytes, the 74 Kaggle-valid ids and the bundle's
    own budget, and ask for 4 x L4. A bundle rebuilt without its kernel (or the reverse) fails here, before a push."""
    import ast, base64
    kd = ROOT / "kernels" / slug
    if not kd.is_dir():
        pytest.skip("kernel not built: python scripts/make_eval_kernel.py submissions/%s %s --ids "
                    "data/kaggle_valid_ids.txt" % (KERNELS[slug], slug))
    nb = json.loads((kd / (slug + ".ipynb")).read_text())
    data = next(c["source"] for c in nb["cells"] if c["source"].startswith("FILES = "))
    vals = {}
    for node in ast.parse(data).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in (
                "FILES", "IDS", "EXPECTED_BUDGET", "BUDGET_OVERRIDE", "ORACLE"):
            vals[node.targets[0].id] = ast.literal_eval(node.value)
    files = {k: base64.b64decode(v) for k, v in vals["FILES"].items()}
    assert files == tree(ROOT / "submissions" / KERNELS[slug]), slug
    assert vals["IDS"] == (ROOT / "data" / "kaggle_valid_ids.txt").read_text().split() and len(vals["IDS"]) == 74
    assert vals["EXPECTED_BUDGET"] == {"max_time_minutes": 5.0, "max_tool_calls": 100, "max_turns": 200,
                                       "timeout_seconds": 180} and vals["BUDGET_OVERRIDE"] == {} and not vals["ORACLE"]
    meta = json.loads((kd / "kernel-metadata.json").read_text())
    assert meta["id"] == "carsonrodrigues/" + slug and meta["machine_shape"] == "NvidiaL4" and meta["enable_gpu"]
