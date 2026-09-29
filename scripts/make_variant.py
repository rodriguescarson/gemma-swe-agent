"""Build a race variant from a base bundle by switching on independent levers (2026-09-27 diagnosis).
  --edit   replace.py (line-range edit, syntax-checked, auto-revert) + edit-failure rules      [EDIT_TOOL_FAILURE]
  --output run.py (timeout, ANSI strip, head+tail) + test.py timeout 45 s and ANSI strip       [context overflow, hangs]
  (default) install helpers into $TMPDIR/swe so sandbox commands can reach them       [helpers never ran]
  --gate   gate.py regression gate + repro rule in the verifier                               [never ran tests, regressions]
  --work-temp T   v10 bundles only: temperature T in configs/gen_{locator,fixer,verifier}.yaml   [race-2 arm r2_v10_t06;
                  L4 A/B arm v10_1_t02, lever D of docs/v10/v10_1_diag_5.md]
  --flip   v10 bundles only, lever A of v10_1_diag_5.md (repro-must-flip): verify's NEXT line on AMBER "no reproduction
           saved" / "passes on original" before FINISH asks for a reproduction with a claim failing on original (literal
           inputs, return values, a sweep for invariants); the fixer follows it; the locator phase gets its own CONTEXT
           threshold (CONTEXT_TOKENS_LOCATOR 7,000 while t < 75 s)                          [L4 A/B arm v10_1_flip]
  --sweep  v10 bundles only, lever B of v10_1_diag_5.md (completeness sweep): edit.py prints SAME CODE ELSEWHERE (the
           removed-line scan, exact whole-line matches first, generic lines dropped); verify's SIBLINGS is
           that scan (same-name defs only when their code repeats a removed line) and never skipped in quick mode (diag 5's prompt parts of B do not fit
           the locator's 370-word cap and are left out)                                     [L4 A/B arm v10_1_sweep]
A v10 bundle (scripts/_swe_common.py) carries its own install/bootstrap: the v9 $TMPDIR fix and the v9 levers are
never applied to it (they would overwrite v10's install.py with helpers_v9/install.py); asking for a v9 lever exits 2.
Every v10 lever is an exact-once text patch: if the base no longer contains the text it patches, make_variant exits 2
and leaves no output dir (tests/test_make_variant_v10.py rebuilds the committed arms and compares them byte for byte).
Usage: python scripts/make_variant.py <base_bundle> <out_dir> [--edit] [--output] [--gate] [--work-temp T] [--flip] [--sweep]"""
import argparse, os, re, shutil, sys

SC_REL = "skills/swe-tools/scripts"

# ------------------------------------------------------------------------------------------------ lever A (--flip)
FLIP_COMMON = [
    ("CONTEXT_TOKENS = 4700\n",
     "CONTEXT_TOKENS = 4700\n"
     "# Lever A (docs/v10/v10_1_diag_5.md 4.A, make_variant --flip): while t < T_LOCATOR the locator phase gets its own\n"
     "# threshold, so the stage that writes most reproductions is not sent to reply before it wrote one (race 2: CONTEXT\n"
     "# fired in 42/74 locators, 27 of them before any repro). From T_LOCATOR on the LOCATOR footer bounds it anyway.\n"
     "CONTEXT_TOKENS_LOCATOR = 7000\n"),
    ("\n\ndef _ctx_record(name, est):\n",
     "\n\ndef ctx_limit(phase, t):\n"
     "    \"\"\"The CONTEXT threshold for the phase the meter is in (lever A): CONTEXT_TOKENS_LOCATOR in the locator phase\n"
     "    while t < T_LOCATOR, else CONTEXT_TOKENS.\"\"\"\n"
     "    try:\n"
     "        early = float(t) < T_LOCATOR\n"
     "    except (TypeError, ValueError):\n"
     "        early = False\n"
     "    return CONTEXT_TOKENS_LOCATOR if (phase or \"locator\") == \"locator\" and early else CONTEXT_TOKENS\n"
     "\n\ndef _ctx_record(name, est):\n"),
    ("    try:\n"
     "        proj = ctx_next(state_load().get(\"ctx\"), name, in_est + est_tokens(out))[\"n\"]\n"
     "    except Exception:\n"
     "        proj = 0.0\n"
     "    if proj >= CONTEXT_TOKENS:\n",
     "    try:\n"
     "        nxt = ctx_next(state_load().get(\"ctx\"), name, in_est + est_tokens(out))\n"
     "        proj, lim = nxt[\"n\"], ctx_limit(nxt.get(\"phase\"), t)\n"
     "    except Exception:\n"
     "        proj, lim = 0.0, CONTEXT_TOKENS\n"
     "    if proj >= lim:\n"),
]
# verify's NEXT line on AMBER without a failing claim (lever A). The fixer never saw the locator's prompt, so the line
# carries the heredoc form and the # CLAIM header that _swe_gate parses.
FLIP_NEXT = ("NEXT: no claim fails on original yet, so nothing checks this change. Fixer: write the reproduction now "
             "with python3 /tmp/swe/verify.py --repro-only <<'EOF' ... EOF, a # CLAIM 1: line before each behaviour's "
             "asserts, with the issue's literal inputs, failing on original: one claim per behaviour, the return value "
             "included; for a rule that must hold everywhere, loop over every position and example input (wide and "
             "zero-width characters too). Then run python3 /tmp/swe/verify.py again. A claim that still fails means "
             "change the code, not the claim. Verifier: run python3 /tmp/swe/finalize.py.")


def _chunks(text, width=100):
    """text as source-sized pieces cut after a space (never inside a word or a helper command)."""
    out, cur = [], ""
    for w in re.findall(r"python3 /tmp/swe/\S+\s*|\S+\s*", text):
        if cur and len(cur) + len(w) > width:
            out.append(cur)
            cur = ""
        cur += w
    return out + ([cur] if cur else [])


FLIP_GATE = [
    ("READY_NEXT = \"NEXT: ready. Fixer: reply with your notes. Verifier: run python3 /tmp/swe/finalize.py.\"\n",
     "READY_NEXT = \"NEXT: ready. Fixer: reply with your notes. Verifier: run python3 /tmp/swe/finalize.py.\"\n"
     "# Lever A (docs/v10/v10_1_diag_5.md 4.A, make_variant --flip): AMBER without a claim that fails on original is not\n"
     "# \"ready\" for the fixer before FINISH (race 2: 23 of 26 AMBER tasks; flipping claims went with 19/36 solved on\n"
     "# feasible tasks against 6/20). The claim guides the fix and never vetoes it. No new repro from T_FINISH on.\n"
     "FLIP_NEXT = (%s)\n"
     "FLIP_REASONS = (\"no reproduction saved\", \"the reproduction passes on original\")\n"
     "\n\ndef _before_finish():\n"
     "    try:\n"
     "        return float(C.clock()) < C.T_FINISH\n"
     "    except Exception:\n"
     "        return False\n" % "\n             ".join(repr(c) for c in _chunks(FLIP_NEXT))),
    ("    return \"VERIFY: AMBER - %s\" % reason, ready, \"AMBER\"\n",
     "    if reason in FLIP_REASONS and _before_finish():\n"
     "        ready = FLIP_NEXT\n"
     "    return \"VERIFY: AMBER - %s\" % reason, ready, \"AMBER\"\n"),
]
FLIP_FIXER = [
    ("for REGRESSIONS follow its note.\n", "for REGRESSIONS follow its note; AMBER: follow its NEXT line.\n"),
]

# ------------------------------------------------------------------------------------------------ lever B (--sweep)
# The code lever B adds to _swe_gate.py, verbatim (the v10 siblings() is kept, renamed _siblings_v10).
SWEEP_GATE_SRC = r'''# Lever B (docs/v10/v10_1_diag_5.md 4.B, make_variant --sweep): SIBLINGS is the removed-line scan (whole-line
# matches first), plus a same-named def only when its body repeats removed code; generic lines and same-name defs whose
# code differs (9 of 17 race-2 SIBLINGS lists were only those) are dropped. edit.py prints the scan at every edit
# (whole lines only), and verify runs it in quick mode too.
_GENERIC = re.compile(r"^[\w.]+\s*=\s*[\w.]+,?$|^[\w.]+,?$")
_KW = frozenset("self cls def class return None True False and not for with while elif else try except finally "
                "import from pass raise yield lambda async await assert break continue global nonlocal del in is "
                "if or".split())


def generic_line(s):
    """True for a removed line too common to point at a sibling: short, a keyword, an import, a docstring quote, a
    bare name or 'name=name,' pass-through, or fewer than two distinct identifiers of 3+ chars."""
    s = s.strip()
    if not _sib_line_ok(s) or _GENERIC.match(s):
        return True
    return len({w for w in re.findall(r"[A-Za-z_]\w{2,}", s) if w not in _KW}) < 2


def _word_re(p):
    """p as a whole-word match (git grep -w): no word character right before or right after it."""
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(p) + r"(?![A-Za-z0-9_])")


def same_code(facts, ws=None, paths=None, limit=SIB_MAX, timeout=5, calls=True):
    """['  path:line  code'] for unchanged lines elsewhere that repeat code the diff removed: whole-line matches
    first, then lines containing a removed line, then lines holding a long call from one, each at word boundaries
    (compute_total(value, 3 never matches compute_total(value, 30)); within a rank the rarer pattern first, so a line
    copied many times cannot hide a specific one. paths: only lines removed from these files. calls=False skips the
    call patterns: several -F patterns sharing a prefix cost git grep about 0.3 s against 0.03 s for whole lines
    (measured on a 1,550-line fixture), so edit.py uses whole lines only. One git grep -F -w; is_protected only for
    the rows kept."""
    ws = ws or C.ws()
    pats, found = [], []
    for path, f in sorted(facts.items()):
        if paths is not None and path not in paths:
            continue
        if not path.endswith(".py") or C.is_protected(path) or f.get("binary"):
            continue
        for ln in f["removed"]:
            s = ln.strip()
            if s in pats or generic_line(s):
                continue
            pats.append(s)
            for c in _CALL.findall(s) if calls else ():
                if len(c) >= 16 and c not in found and c not in pats:
                    found.append(c)
    pats, found = pats[:SAME_PATS], found[:4]
    if not pats and not found:
        return []
    args = ["grep", "-n", "-F", "-w", "-I", "-z"]
    for p in pats + found:
        args += ["-e", p]
    rc, data, _ = _git(args + ["--", "*.py"], timeout, cwd=ws)
    exact = set(pats)
    within = [(p, _word_re(p)) for p in pats]
    held = [(c, _word_re(c)) for c in found]
    rows, per = [], {}
    for ln in _dec(data).split("\n"):
        parts = ln.split("\0")
        if len(parts) < 3:
            continue
        path, no, code = parts[0], parts[1], parts[2]
        try:
            no = int(no)
        except ValueError:
            continue
        f = facts.get(path)
        if f and no in f["added_lines"]:
            continue
        s = code.strip()
        if s in exact:
            rank, key = 0, s
        else:
            rank, key = 1, next((p for p, rx in within if rx.search(s)), None)
            if key is None:
                rank, key = 2, next((c for c, rx in held if rx.search(s)), None)
        if key is None:
            continue
        per[key] = per.get(key, 0) + 1
        rows.append((rank, key, path, no, s))
    out, seen, prot = [], set(), {}
    for rank, key, path, no, s in sorted(rows, key=lambda r: (r[0], per[r[1]], r[2], r[3])):
        if (path, no) in seen:
            continue
        if path not in prot:
            prot[path] = bool(C.is_protected(path))
        if prot[path]:
            continue
        seen.add((path, no))
        out.append("  %s:%d  %s" % (path, no, s[:100]))
        if len(out) >= limit:
            break
    return out


def _def_body(ws, path, a, b):
    try:
        with open(os.path.join(ws, path), "rb") as f:
            lines = f.read(2 << 20).decode("utf-8", "replace").split("\n")
    except OSError:
        return set()
    return {ln.strip() for ln in lines[max(0, a - 1):b]}


def siblings(facts, idx, ws=None):
    """Lever B: the ranked removed-line scan (same_code), then same-named defs elsewhere only when their body repeats a
    line the change removed from that file (same name AND same code: race 2's A.render_row / B.render_row). Same-name
    defs whose code differs are dropped (rich_3063 jupyter escape, fastapi_14986 FastAPI.openapi, rich_3905 Live.stop)."""
    ws = ws or C.ws()
    out = same_code(facts, ws)
    if idx is None or len(out) >= SIB_MAX:
        return out
    removed = {p: {ln.strip() for ln in f["removed"] if _sib_line_ok(ln.strip())} for p, f in facts.items()}
    changed = []
    for path, f in sorted(facts.items()):
        if not path.endswith(".py") or C.is_protected(path) or f.get("deleted") or f.get("binary"):
            continue
        for ln in sorted(f["added_lines"])[:400]:
            try:
                sym = _sym(idx.enclosing(path, ln))
            except Exception:
                sym = None
            if sym and sym[1] in ("def", "async def") and (path, sym[0]) not in changed:
                changed.append((path, sym[0]))
    listed = {r.split()[0] for r in out}
    done = set()
    for path, qn in changed:
        name = qn.rsplit(".", 1)[-1]
        if len(name) < 4 or (name.startswith("__") and name.endswith("__")) or name in done or not removed.get(path):
            continue
        done.add(name)
        try:
            defs = [(p, _sym(x)) for p, x in idx.defs_named(name)]
        except Exception:
            continue
        others = []
        for p, x in defs:
            if (p, x[0]) in changed or C.is_protected(p) or "def" not in x[1]:
                continue
            ff = facts.get(p)
            if ff and any(x[2] <= ln <= x[3] for ln in ff["added_lines"]):
                continue
            others.append((p, x))
        if not others or len(others) > 4:
            continue
        for p, x in others:
            if "%s:%d" % (p, x[2]) in listed or not (removed[path] & _def_body(ws, p, x[2], x[3])):
                continue
            listed.add("%s:%d" % (p, x[2]))
            out.append("  %s:%d  %s %s (same name as your changed %s)" % (p, x[2], x[1], x[0], qn))
            if len(out) >= SIB_MAX:
                return out
    return out'''

SWEEP_GATE = [
    ("SIB_MAX = 6\n",
     "SIB_MAX = 6\n"
     "SAME_PATS = 8              # lever B: removed lines searched per scan (plus up to 4 long calls inside them)\n"),
    ("\n\ndef siblings(facts, idx, ws=None):\n",
     "\n\n" + SWEEP_GATE_SRC + "\n\n\ndef _siblings_v10(facts, idx, ws=None):\n"),
    ("        try:\n"
     "            R[\"gaps\"] = spec_gaps(rp.get(\"new_names\") or [], rp.get(\"messages\") or [], idx, ws)\n"
     "        except Exception:\n"
     "            R[\"gaps\"] = []\n",
     "        try:\n"
     "            R[\"gaps\"] = spec_gaps(rp.get(\"new_names\") or [], rp.get(\"messages\") or [], idx, ws)\n"
     "        except Exception:\n"
     "            R[\"gaps\"] = []\n"
     "    elif advice and ne and not repro_only:    # lever B: the removed-line scan (one git grep) is never skipped\n"
     "        try:\n"
     "            R[\"siblings\"] = same_code(facts, ws, timeout=2)\n"
     "        except Exception:\n"
     "            R[\"siblings\"] = []\n"),
]
SWEEP_EDIT = [
    ("RECIPE = \"python3 /tmp/swe/edit.py %s --lines %d-%d <<'EOF' ... EOF\"\n",
     "RECIPE = \"python3 /tmp/swe/edit.py %s --lines %d-%d <<'EOF' ... EOF\"\n"
     "# Lever B (docs/v10/v10_1_diag_5.md 4.B, make_variant --sweep): at each edit, the same removed code elsewhere\n"
     "# (race 2: rich_3480 fixed Text.append and left the same `_spans` loop in append_text; verify ran in quick mode).\n"
     "SAME_HEAD = \"SAME CODE ELSEWHERE (unchanged; fix it too if it has the same defect):\"\n"
     "SAME_ROWS = 3\n"
     "SAME_CUT = 120\n"),
    ("    try:                                     # v10.1: a landed edit is restorable even if it is undone later\n"
     "        d = C.diff_bytes()\n",
     "    d = b\"\"\n"
     "    try:                                     # v10.1: a landed edit is restorable even if it is undone later\n"
     "        d = C.diff_bytes()\n"),
    ("    if py:\n"
     "        x.extra.append(\"NEXT: python3 /tmp/swe/verify.py\")\n",
     "    if py and d:\n"
     "        try:\n"
     "            import _swe_gate as G\n"
     "            sib = G.same_code(G.diff_facts(d), paths=[rel], limit=SAME_ROWS, timeout=2, calls=False)\n"
     "        except Exception:\n"
     "            sib = []\n"
     "        if sib:\n"
     "            x.extra.append(SAME_HEAD)\n"
     "            x.extra.extend(r[:SAME_CUT] for r in sib)\n"
     "    if py:\n"
     "        x.extra.append(\"NEXT: python3 /tmp/swe/verify.py\")\n"),
]

V10_LEVERS = {
    "flip": [("%s/_swe_common.py" % SC_REL, FLIP_COMMON), ("%s/_swe_gate.py" % SC_REL, FLIP_GATE),
             ("prompts/fixer.md", FLIP_FIXER)],
    # Diag 5's prompt parts of lever B (a FILES entry per linked issue and clause, model plus renderer, loop branches)
    # are not in this arm: locator.md is at 369 of the 370 words R91 allows (tests/test_v10_prompts.py), and room
    # for them would mean cutting other locator rules, a second lever. The arm is the mechanical sweep only.
    "sweep": [("%s/_swe_gate.py" % SC_REL, SWEEP_GATE), ("%s/edit.py" % SC_REL, SWEEP_EDIT)],
}


class LeverError(Exception):
    pass


def apply_patches(out, lever, patches):
    """Apply each (old, new) exactly once; raise LeverError naming the file when the base does not match."""
    for rel, subs in patches:
        p = os.path.join(out, rel)
        with open(p, encoding="utf-8") as f:
            s = f.read()
        for old, new in subs:
            n = s.count(old)
            if n != 1:
                raise LeverError("--%s: %s contains the text to patch %d times, not once (was the base changed? "
                                 "update scripts/make_variant.py): %r" % (lever, rel, n, old[:80]))
            s = s.replace(old, new, 1)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(s)


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("base"); ap.add_argument("out")
    for f in ("edit", "output", "gate", "flip", "sweep"): ap.add_argument("--" + f, action="store_true")
    ap.add_argument("--keep-tmp-bug", action="store_true", help="do NOT apply the $TMPDIR install fix (reproduces v4 as submitted)")
    ap.add_argument("--work-temp", type=float, default=None, help="v10 only: temperature of the locator, fixer and verifier")
    a = ap.parse_args(argv)
    H = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "helpers_v9")
    V10 = os.path.isfile(os.path.join(a.base, SC_REL, "_swe_common.py"))
    if V10 and (a.edit or a.output or a.gate):
        ap.exit(2, "make_variant: --edit/--output/--gate are v9 levers; a v10 bundle already has edit.py, run.py and verify.py\n")
    if a.work_temp is not None and (not V10 or not 0.0 <= a.work_temp <= 2.0):
        ap.exit(2, "make_variant: --work-temp needs a v10 bundle and 0 <= T <= 2\n")
    if (a.flip or a.sweep) and not V10:
        ap.exit(2, "make_variant: --flip/--sweep are v10 levers; %s is not a v10 bundle\n" % a.base)
    if os.path.abspath(a.out) == os.path.abspath(a.base):
        ap.exit(2, "make_variant: the output dir is the base bundle\n")
    if os.path.exists(a.out): shutil.rmtree(a.out)
    shutil.copytree(a.base, a.out, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "._*", ".DS_Store"))
    SK = os.path.join(a.out, "skills/swe-tools"); SC = os.path.join(SK, "scripts")

    def edit(rel, fn):
        p = os.path.join(a.out, rel); s = open(p).read(); t = fn(s)
        assert t != s, f"lever did not change {rel}"; open(p, "w").write(t)
    try:
        usage = []
        if not a.keep_tmp_bug and not V10:  # helpers were installed to the host /tmp, unreachable from sandbox commands (81/85 locate calls failed in v4)
            for f in ("_ws.py", "install.py"): shutil.copy(os.path.join(H, f), SC)
        if a.edit:
            shutil.copy(os.path.join(H, "replace.py"), SC)
            rule = ("\nEditing: if `edit_file` fails ONCE, do not retry it; instead replace whole lines by number (raw text, no escaping):\n"
                    "`python3 /tmp/swe/replace.py --file <path> --start <first line> --end <last line> <<'EOF'` + newline + the new lines + newline + `EOF` "
                    "(run it with run_command). It syntax-checks and reverts bad edits. Read the exact line numbers with read_file first. "
                    "Never rewrite a whole file with write_file.\n")
            for r in ("prompts/fixer.md", "prompts/verifier.md"):
                edit(r, lambda s: s.replace("\nTools you can call:", rule + "\nTools you can call:", 1))
            usage.append("python3 /tmp/swe/replace.py --file F --start N --end M <<'EOF' ... EOF")
        if a.output:
            shutil.copy(os.path.join(H, "run.py"), SC)
            edit("skills/swe-tools/scripts/test.py", lambda s: s.replace('int(opt.get("timeout", 150))', 'int(opt.get("timeout", 45))')
                 .replace('out = r.stdout + r.stderr;', 'out = re.sub(r"\\x1b\\[[0-9;?]*[ -/]*[@-~]", "", r.stdout + r.stderr);'))
            rule = ("\nCommands: run anything that may print a lot or may hang through `python3 /tmp/swe/run.py --timeout 20 \"<command>\"` "
                    "(colour stripped, long output cut, full log in /tmp/swe/last.log for grep). Never cat large files; use read_file with line ranges.\n")
            for r in ("prompts/locator.md", "prompts/fixer.md", "prompts/verifier.md"):
                edit(r, lambda s: s.replace("\nTools you can call:", rule + "\nTools you can call:", 1))
            usage.append('python3 /tmp/swe/run.py --timeout 20 "<cmd>"')
        if a.gate:
            shutil.copy(os.path.join(H, "gate.py"), SC)
            step = ("2. Run `python3 /tmp/swe/gate.py` (add `--target <test file>` if the plan names one). It runs the related existing tests on your "
                    "version and on the original code. If it lists REGRESSIONS, the change is wrong: fix it (or undo the offending part) and run gate.py again, "
                    "at most twice. Then check the issue's own example: `cat > /tmp/repro.py <<'EOF'` ... `EOF` and `python3 /tmp/repro.py`; "
                    "if it still shows the bug, fix it.")
            edit("prompts/verifier.md", lambda s: re.sub(r"^2\. Run the relevant test:.*$", step.replace("\\", r"\\"), s, count=1, flags=re.M))
            usage.append("python3 /tmp/swe/gate.py [--target tests/test_x.py]")
        if a.work_temp is not None:
            for st in ("locator", "fixer", "verifier"):
                edit(f"configs/gen_{st}.yaml", lambda s: re.sub(r"^temperature: .*$", f"temperature: {a.work_temp:g}", s, count=1, flags=re.M))
        for lever in ("flip", "sweep"):
            if getattr(a, lever):
                apply_patches(a.out, lever, V10_LEVERS[lever])
        if usage:
            edit("skills/swe-tools/SKILL.md", lambda s: s.rstrip("\n") + "\n" + "\n".join(f"- `{u}`" for u in usage) + "\n")
    except LeverError as e:
        shutil.rmtree(a.out, ignore_errors=True)
        ap.exit(2, "make_variant: %s\n" % e)
    print(a.out, "tmpfix:", "n/a (v10)" if V10 else not a.keep_tmp_bug, "work_temp:", a.work_temp, "levers:",
          [f for f in ("edit", "output", "gate", "flip", "sweep") if getattr(a, f)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
