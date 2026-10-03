import os, sys
sys.dont_write_bytecode = True
_HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("SWE_PATH0", sys.path[0] if sys.path else "")
_STD = tuple({os.path.realpath(p) for p in (sys.base_prefix, sys.base_exec_prefix)})
sys.path[:] = [_HERE] + [p for p in sys.path if p and os.path.realpath(p).startswith(_STD) and "-packages" not in p]
for _n in [n for n, m in list(sys.modules.items()) if n.split(".")[0] in getattr(sys, "stdlib_module_names", ())
           and getattr(m, "__file__", None) and not os.path.realpath(m.__file__).startswith(_STD)]:
    del sys.modules[_n]
import _swe_common as C

# What the earlier stages did, for a stage whose context was shortened: task time, repro and checkpoint summary, the
# journal tail, the diffstat and a bounded diff of the source files. It changes nothing in the repository (v10.1: it
# stores a non-empty source tree as an unscored checkpoint under $SWE). Any argument is ignored.
# v10.2 (SPEC_v10_2 5.1-5.2): the call that ends the locator phase (the fixer's first step) prints the phase-start form
# instead: the LOCATOR DIGEST of what the locator's helpers showed, within STATUS_START_CAP chars. Every status.py call
# restarts the context meter and the per-stage count of full verify runs (vsince).

NAME = "status"
USAGE = "python3 /tmp/swe/status.py"
FLAGS = {}
DIFF_CAP = 1600
JOURNAL_N = 8
VIEWED_N = 4
DIGEST_N = 3               # located files and viewed files in the LOCATOR DIGEST
DIGEST_HEAD = ("LOCATOR DIGEST (what the locator's helpers showed; a locator replies with its plan now, the fixer "
               "starts from it):")
DIGEST_EMPTY = "LOCATOR DIGEST: no locator activity recorded (no locate, view or reproduction)."
RUNS_IT = "saved; python3 /tmp/swe/verify.py runs it"


def viewed(st):
    """v10.1 (race 2, rich_4079: three compactions, each losing the locator's plan): the last source ranges viewed,
    newest first (real views only), so a stage recovering after compaction gets the plan's files back."""
    items = []
    for f, lst in (st.get("views") or {}).items():
        for v in lst if isinstance(lst, list) else []:
            if isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v) and \
                    not C.is_protected(f):
                items.append((float(v[2]), f, int(v[0]), int(v[1])))
    seen, out = set(), []
    for t, f, a, b in sorted(items, reverse=True):
        if (f, a, b) in seen:
            continue
        seen.add((f, a, b))
        out.append("%s %d-%d" % (f, a, b))
        if len(out) >= VIEWED_N:
            break
    return C._short("VIEWED (newest first): " + ", ".join(out), 300) if out else ""


def repro_summary(st):
    r = st.get("repro") if isinstance(st.get("repro"), dict) else {}
    orig = r.get("orig") if isinstance(r.get("orig"), dict) else {}
    if not orig:
        return "repro: saved, not run yet" if os.path.isfile(os.path.join(C.swe_dir(), "repro.py")) else "repro: none"
    n = len(orig)
    vals = [v if isinstance(v, dict) else {} for v in orig.values()]
    broken = sum(1 for v in vals if v.get("broken"))
    fails = sum(1 for v in vals if v.get("status") in ("FAIL", "HANG") and not v.get("broken"))
    passes = sum(1 for v in vals if v.get("status") == "PASS" and not v.get("broken"))
    word = "claim" if n == 1 else "claims"
    if fails == n:
        return "repro: %d %s (fails on original)" % (n, word)
    bits = []
    if fails:
        bits.append("%d fail on original" % fails)
    if passes:
        bits.append("%d pass on original" % passes)
    if broken:
        bits.append("%d broken" % broken)
    return "repro: %d %s (%s)" % (n, word, ", ".join(bits) or "not run")


def ckpt_summary(st):
    ck = [c for c in (st.get("ckpts") or []) if isinstance(c, dict)]
    if not ck:
        return "checkpoints: 0"

    def key(c):
        s = c.get("score")
        s = [x if isinstance(x, (int, float)) else 0 for x in s] if isinstance(s, (list, tuple)) else []
        return (s, c.get("t") if isinstance(c.get("t"), (int, float)) else 0)
    try:
        best = max(ck, key=key)
    except TypeError:
        best = ck[-1]
    return "checkpoints: %d (best %s #%s)" % (len(ck), best.get("verdict") or "?", best.get("id", "?"))


def diffstat(ch, env=None):
    src = [p for p in ch["source"]]
    stats = dict((p, (a, d)) for p, a, d in C.numstat(src + ch["deleted"], env=env)) if (src or ch["deleted"]) else {}
    parts = []
    for p in src + ch["deleted"]:
        a, d = stats.get(p, (None, None))
        if p in ch["deleted"]:
            parts.append("%s deleted" % p)
        elif a is None and d is None and p in stats:
            parts.append("%s (binary)" % p)
        else:
            parts.append("%s +%s -%s" % (p, a if a is not None else "?", d if d is not None else "?"))
    if not parts:
        return "DIFF: no source change"
    line = "DIFF: " + " | ".join(parts[:8])
    if len(parts) > 8:
        line += " | (+%d more files)" % (len(parts) - 8)
    return C._short(line, 400)


def cap_diff(text, limit):
    """Whole hunks while they fit in `limit` chars, then only the file and hunk headers."""
    out, used, headers_only, cut = [], 0, False, 0
    blocks = []
    cur = None
    for ln in text.split("\n"):
        if ln.startswith("diff --git "):
            cur = {"head": [ln], "hunks": []}
            blocks.append(cur)
        elif cur is None:
            continue
        elif ln.startswith("@@"):
            cur["hunks"].append([ln])
        elif cur["hunks"]:
            cur["hunks"][-1].append(ln)
        elif ln.startswith(("new file", "deleted file", "Binary files", "old mode", "new mode")):
            cur["head"].append(ln)
    extra = 0
    for b in blocks:
        h = "\n".join(b["head"])
        if used + len(h) + 1 > limit + 400:
            extra += len(b["hunks"])
            continue
        out.append(h)
        used += len(h) + 1
        for hk in b["hunks"]:
            body = "\n".join(C._long(x) for x in hk)
            if not headers_only and used + len(body) + 1 <= limit:
                out.append(body)
                used += len(body) + 1
                continue
            headers_only = True
            cut += 1
            if used + len(hk[0]) + 1 <= limit + 400:
                out.append(C._long(hk[0]))
                used += len(hk[0]) + 1
            else:
                extra += 1
    if cut:
        out.append("... [%d hunk bodies not shown%s; full diff: python3 /tmp/swe/run.py \"git diff\"] ..." %
                   (cut, "" if not extra else ", %d more hunks" % extra))
    return "\n".join(out)


def located_line(st):
    top = C.locate_top_entries(st)[:DIGEST_N]
    return ("  located: " + ", ".join("%s (%s)" % (f, sym) if sym else f for f, sym, _a, _b in top)) if top else ""


def viewed_entries(st):
    """At most DIGEST_N source files, newest first, each with its latest real view range and the def or class holding
    the range's midpoint (from the index cache; omitted without it). Test files never appear."""
    seen, out = set(), []
    for _t, f, a, b in C.real_views(st):
        if f in seen:
            continue
        seen.add(f)
        out.append((f, a, b))
        if len(out) >= DIGEST_N:
            break
    defs = C.cached_defs([(f, (a + b) // 2) for f, a, b in out])
    return ["%s %d-%d%s" % (f, a, b, (" (%s)" % defs[(f, (a + b) // 2)]) if (f, (a + b) // 2) in defs else "")
            for f, a, b in out]


def digest_repro(st):
    r = st.get("repro") if isinstance(st.get("repro"), dict) else {}
    orig = r.get("orig") if isinstance(r.get("orig"), dict) else {}
    saved = os.path.isfile(os.path.join(C.swe_dir(), "repro.py"))
    if not orig:
        return ("  repro: saved, not run yet; python3 /tmp/swe/verify.py runs it" if saved else "  repro: none"), saved
    vals = [v if isinstance(v, dict) else {} for v in orig.values()]
    fails = sum(1 for v in vals if v.get("status") in ("FAIL", "HANG") and not v.get("broken"))
    text = ("fails on original (%d of %d claims)" % (fails, len(vals)) if fails
            else repro_summary(st)[len("repro: "):])
    return "  repro: %s%s" % (text, (", " + RUNS_IT) if saved else ""), True


def fit(lines, located, viewed, limit_chars, limit_tokens):
    """The digest within the limits: drop `located` first, then `viewed` entries (oldest first), then shorten lines."""
    def build(loc, vw):
        out = []
        for ln in lines:
            if ln == "<located>":
                if loc:
                    out.append(loc)
            elif ln == "<viewed>":
                if vw:
                    out.append("  viewed: " + "; ".join(vw))
            else:
                out.append(ln)
        return "\n".join(out)

    def ok(text):
        return len(text) <= limit_chars and C.est_tokens(text) <= limit_tokens
    text = build(located, viewed)
    if ok(text):
        return text
    located = ""
    vw = list(viewed)
    while True:
        text = build(located, vw)
        if ok(text) or not vw:
            break
        vw.pop()
    if ok(text):
        return text
    out = []
    for ln in text.split("\n"):
        out.append(C._short(ln, 160))
    text = "\n".join(out)
    return text if ok(text) else C._token_prefix(text[:limit_chars], limit_tokens).rstrip()


def phase_start(t, st):
    """The status form of the call that ends the locator phase (5.2)."""
    ch = C.changes()
    paths = ch["source"] + ch["deleted"]
    if paths:
        with C.tmp_index() as env:
            dline = diffstat(ch, env)
            rc2, whole, _ = C.git_run(["diff", "--binary", C.baseline()], timeout=30, env=env, quotepath_off=False)
        if rc2 == 0 and whole:
            try:
                import _swe_ckpt as K
                K.save_edited(whole)
            except Exception:
                pass
    else:
        dline = "DIFF: no source change"
    loc = C.loc_state(st)
    head = "STATUS [t=%ds] helpers %s | locator closed after %d helper calls | %s | %s" % (
        int(t), C.VERSION, int(loc.get("calls") or 0), repro_summary(st), ckpt_summary(st))
    located, viewed = located_line(st), viewed_entries(st)
    rline, has_repro = digest_repro(st)
    if located or viewed or has_repro:
        lines = [DIGEST_HEAD, "<located>", "<viewed>", rline, dline]
    else:
        lines = [DIGEST_EMPTY, dline]
    try:
        foot = C.footer(t, bool(paths))
    except Exception:
        foot = "[t=%ds]" % int(t)
    room = C.STATUS_START_CAP - len(foot) - 2 - len(head) - 1 - (160 if t >= C.T_SAFE else 0)
    troom = C.STATUS_START_CAP / 3.0 - C.est_tokens(foot) - C.est_tokens(head) - 2
    body = fit(lines, located, viewed, max(80, room), max(30.0, troom))
    C.state_update(_restart)
    C.emit(NAME, head, body, C.STATUS_START_CAP, src=bool(paths))


def _restart(s):
    s["vsince"] = 0
    return s


def _count_failed_call(st0):
    """A status.py call that failed before its output (a git error, the helper watchdog) still starts the next stage's
    count: the context meter records the status call unless emit() already did, and vsince restarts. Without this a
    failed phase-start call left the locator phase open, so every later gated call was refused with "run status.py
    first" and the fixer could loop on it. Best effort: never raises (safe_main reports the original error)."""
    try:
        if C.state_load().get("ctx") == st0.get("ctx"):
            C._ctx_record(NAME, 0.0)
        C.state_update(_restart)
    except Exception:
        pass


def main():
    C.bootstrap()
    t = C.clock()
    st = C.state_load()
    try:
        return phase_start(t, st) if C.loc_open(st) else later_form(t, st)
    except BaseException:
        _count_failed_call(st)
        raise


def later_form(t, st):
    """The v10.1 status form (every call after the one that ends the locator phase)."""
    ch = C.changes()
    lines = []
    head = "STATUS [t=%ds] helpers %s | %s | %s" % (int(t), C.VERSION, repro_summary(st), ckpt_summary(st))
    sha = None
    if st.get("final_done") and st.get("final_sha"):
        sha = C.diff_sha()
        if sha != st.get("final_sha"):
            lines.append("CHANGED AFTER FINALIZE: run python3 /tmp/swe/finalize.py again.")
    vw = viewed(st)
    if vw:
        lines.append(vw)
    ent = C.jtail(JOURNAL_N)
    if ent:
        lines.append("JOURNAL (last %d):" % len(ent))
        lines += ["  " + e for e in ent]
    else:
        lines.append("JOURNAL: empty")
    paths = ch["source"] + ch["deleted"]
    if not paths:
        lines.append(diffstat(ch))
        diff = ""
    else:
        with C.tmp_index() as env:                     # one temp index for the diffstat and the diff
            lines.append(diffstat(ch, env))
            rc, diff = C.git_tmpindex(["--literal-pathspecs", "diff", "-U2", "--no-color", "--no-ext-diff",
                                       "--no-renames", C.baseline(), "--"] + paths, env=env)
            if rc != 0:
                diff = ""
            # v10.1: a tree with a source change (also one made with the harness's own edit tools) is kept as an
            # unscored checkpoint, so finalize and the late guard can bring it back if it is undone later
            rc2, whole, _ = C.git_run(["diff", "--binary", C.baseline()], timeout=30, env=env, quotepath_off=False)
        if rc2 == 0 and whole:
            try:
                import _swe_ckpt as K
                K.save_edited(whole)
            except Exception:
                pass
    if ch["protected"]:
        lines.append(C._short("PROTECTED (the helpers revert these; graders replace them): " +
                              ", ".join(ch["protected"][:6]), 300))
    scratch = [p for p in ch["untracked"] if p not in ch["source"]]
    if scratch:
        lines.append(C._short("UNTRACKED (not source): " + ", ".join(scratch[:6]) +
                              (" (+%d more)" % (len(scratch) - 6) if len(scratch) > 6 else ""), 300))
    fixed = len(head) + sum(len(x) + 1 for x in lines) + 120
    room = min(DIFF_CAP, C.CAPS[NAME] - fixed)
    if diff.strip() and room > 200:
        lines.append(cap_diff(C.clean_text(diff).rstrip("\n"), room))
    C.state_update(_restart)
    C.emit(NAME, head, "\n".join(lines), C.CAPS[NAME], src=bool(paths), sha=sha)


if __name__ == "__main__":
    C.safe_main(NAME, main)
