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

import time

USAGE = "python3 /tmp/swe/verify.py [--repro-only] [--tests FILE ...] [--list-tests]"
FLAGS = {"repro-only": "bool", "tests": "list", "list-tests": "bool", "timeout": "int", "text": "str"}
NAME = "verify"
REPRO_CAP = 1200
BODY_BUDGET = 1450
NONE_SAVED = "REPRO: none saved. Pipe one in: python3 /tmp/swe/verify.py --repro-only <<'EOF' ... EOF"
READY = "NEXT: ready. Fixer: reply with your notes. Verifier: run finalize.py."


def get_args(argv):
    """C.parse_args -> (opts dict with dashed keys, positionals), whatever container shape it returns; None when it
    already printed a usage line."""
    got = C.parse_args(argv, FLAGS, [])
    if got is None:
        return None
    if isinstance(got, tuple) and len(got) == 2 and isinstance(got[0], dict):
        opts, pos = dict(got[0]), list(got[1] or [])
    elif isinstance(got, dict):
        opts = dict(got)
        pos = []
        for k in ("_", "_positional", "positionals", "_pos", "args"):
            v = opts.pop(k, None)
            if v:
                pos = list(v)
    else:
        opts = dict(vars(got))
        pos = list(opts.pop("_", None) or opts.pop("positionals", None) or [])
    for k in list(opts):
        if "_" in k and k.replace("_", "-") in FLAGS:
            opts[k.replace("_", "-")] = opts.pop(k)
    opts["_positional"] = [str(x) for x in pos]
    return opts


def _opt(opts, name, default=None):
    for k in (name, name.replace("-", "_"), "--" + name):
        if k in opts and opts[k] is not None:
            return opts[k]
    return default


def _tests_arg(opts):
    raw = _opt(opts, "tests") or []
    if isinstance(raw, str):
        raw = [raw]
    out = []
    for x in raw:
        for y in str(x).replace(",", " ").split():
            y = y.strip()
            if y and y not in out:
                out.append(y)
    for p in opts.get("_positional") or []:
        if str(p).endswith(".py") or "::" in str(p):
            out.append(str(p))
    return out


def _emit(first, lines, cap=None, tail=None, src=None, sha=None):
    body = "\n".join(x for x in lines if x is not None)
    C.emit(NAME, first, body, cap or C.CAPS[NAME], tail=tail, src=src, sha=sha)


def _sha1(b):
    import hashlib
    return hashlib.sha1(b if isinstance(b, bytes) else b.encode("utf-8", "surrogateescape")).hexdigest()


def _changes():
    """changes() with hygiene: hygiene_revert() only acts on protected paths, so it runs only when there are some."""
    ch = C.changes() or {}
    hyg = []
    if ch.get("protected"):
        hyg = C.hygiene_revert() or []
        ch = C.changes() or {}
    return {k: list(ch.get(k) or []) for k in ("source", "protected", "untracked", "deleted")}, hyg


def _saved_repro():
    try:
        with open(os.path.join(C.swe_dir(), "repro.py"), "rb") as f:
            return f.read().decode("utf-8", "surrogateescape")
    except OSError:
        return ""


def _journal(ev):
    try:
        ev = dict(ev)
        ev.setdefault("h", NAME)
        C.journal(ev)
    except Exception:
        pass


def _cut(s, n):
    s = " ".join(str(s).split()) if "\n" in str(s) else str(s)
    return s if len(s) <= n else s[:n - 3] + "..."


# ----------------------------------------------------------------------------------------------------------------------
# --repro-only

def repro_only(G, opts, text):
    if text and text.strip():
        text = G.save_repro(text)
        try:
            compile(text, "repro.py", "exec", dont_inherit=True)
        except SyntaxError as e:
            first = "REPRO INVALID: syntax error line %s: %s. Fix the reproduction and pipe it again." % (
                e.lineno or 0, _cut(e.msg or e, 120))
            _journal({"mode": "repro-only", "first": first, "msg": "repro invalid"})
            _emit(first, [])
            return
    else:
        text = G.repro_text()
        if not text.strip():
            _journal({"mode": "repro-only", "first": NONE_SAVED, "msg": "repro: none saved"})
            _emit(NONE_SAVED, [])
            return
    ch = G.changes()
    secs = G.end_budget(C.CLAIMS_TOTAL + (C.IMPORT_CHECK if G.nonempty(ch) else 0) + 3, C.T_EVAL_END)
    R = G.evaluate(quick=True, run_tests=False, advice=False, repro_only=True, deadline=time.time() + secs, ch=ch)
    rp = R.get("repro") or {}
    cl = rp.get("claims") or []
    orig = rp.get("orig") or {}
    lines = []
    if not R["nonempty"]:
        first = _orig_line(cl, orig)
        for c in cl:
            o = orig.get(c.idx) or {}
            lines.append(_cut("  claim %d %s%s%s" % (c.idx, o.get("status", "UNKNOWN"),
                                                   (": " + o["sig"]) if o.get("sig") else "",
                                                   ("  [BROKEN: %s]" % o["broken"]) if o.get("broken") else ""), 220))
            if o.get("hint"):
                lines.append("  hint: " + o["hint"])
        _journal({"mode": "repro-only", "first": first, "msg": first[len("REPRO: "):] if first.startswith("REPRO: ")
                  else first})
        _emit(first, _fit(lines, REPRO_CAP - len(first) - 150), REPRO_CAP, src=False)
        return
    summ = rp.get("summary") or {}
    first = "REPRO: %s" % summ.get("text", "0/0 claims fixed")
    imp = R.get("import") or {}
    if imp.get("ok") is False:
        lines.append(_cut("IMPORT: RED %s: %s%s" % (imp.get("module"), imp.get("line"),
                                                    (" (%s)" % imp["where"]) if imp.get("where") else ""), 260))
    lines += _claim_lines(cl, orig, rp.get("cur") or {}, summ)
    cid = _save_ckpt(R, G.verdict(R)[2], quick=True)
    if cid:
        lines.append("CHECKPOINT: #%s saved (quick)" % cid)
    _journal({"mode": "repro-only", "first": first, "msg": summ.get("text", "")})
    body = _fit(lines, REPRO_CAP - len(first) - 150)
    C.record_views(printed_views(body))
    _emit(first, body, REPRO_CAP, src=True, sha=R.get("diff_sha"))


def _orig_line(cl, orig):
    res = [(c.idx, orig.get(c.idx) or {"status": "UNKNOWN"}) for c in cl]
    broken = [(i, r) for i, r in res if r.get("broken")]
    if broken:
        i, r = broken[0]
        return "REPRO: claim %d is BROKEN (%s, in the reproduction itself): fix the reproduction." % (
            i, _cut(r["broken"], 110))
    passing = [i for i, r in res if r.get("status") == "PASS"]
    if passing:
        return ("REPRO: claim %d passes on original - it misses the bug; rewrite it once with another input shape."
                % passing[0])
    fails = [(i, r) for i, r in res if r.get("status") == "FAIL"]
    hangs = [i for i, r in res if r.get("status") == "HANG"]
    if fails:
        i, r = fails[0]
        return "REPRO: fails on original (%d of %d claims): claim %d %s" % (
            len(fails) + len(hangs), len(res), i, _cut(r.get("sig") or "fails", 120))
    if hangs:
        return "REPRO: claim %d hangs on original (expected for hang bugs)." % hangs[0]
    return "REPRO: the claims did not finish in time on original; shorten them and pipe the reproduction again."


def _claim_lines(cl, orig, cur, summ):
    out = []
    for c in cl:
        k = (summ.get("classes") or {}).get(c.idx) or "UNKNOWN"
        r = cur.get(c.idx) or {}
        o = orig.get(c.idx) or {}
        detail = ""
        if k in ("STILL FAILS", "BROKE", "UNKNOWN") and r.get("sig"):
            detail = ": " + r["sig"]
        elif k == "BROKEN":
            detail = ": " + (o.get("broken") or "")
        elif k == "INVALID":
            detail = ": passes on original too"
        title = (" (%s)" % c.title) if c.title else ""
        out.append(_cut("  claim %d%s %s%s" % (c.idx, title, k, detail), 200))
        if k == "BROKEN" and o.get("hint"):
            out.append("  hint: " + o["hint"])
    return out


def printed_views(lines):
    """(path, n, n) for every current line number verify.py prints: SIBLINGS rows and the IMPORT: RED file:line. They
    are recorded as views so edit.py's STALE guard trusts numbers taken from this output."""
    import re
    out, sib = [], False
    for ln in lines:
        if ln is None:
            continue
        if ln.startswith("IMPORT: RED"):
            m = re.search(r"\(([^()\s]+):(\d+)\)\s*$", ln)
            if m:
                out.append((m.group(1), m.group(2), m.group(2)))
        if ln.startswith("SIBLINGS"):
            sib = True
            continue
        if not ln.startswith("  "):
            sib = False
        elif sib:
            m = re.match(r"^  (\S+?):(\d+)  ", ln)
            if m:
                out.append((m.group(1), m.group(2), m.group(2)))
    return out


def _fit(lines, budget):
    out, used = [], 0
    for i, ln in enumerate(lines):
        if used + len(ln) + 1 > budget:
            out.append("  ... %d more" % (len(lines) - i))
            break
        out.append(ln)
        used += len(ln) + 1
    return out


def _save_ckpt(R, word, quick):
    try:
        import _swe_ckpt as K
        return K.save(R["diff"], R["score"], R["key"], word, quick, rkey=R.get("rkey"), meta=R)
    except Exception:
        return None


# ----------------------------------------------------------------------------------------------------------------------
# --list-tests

def list_tests(G, opts):
    ch = G.changes()
    diff = C.diff_bytes()
    facts = G.diff_facts(diff)
    idx = G._load_index(min(5.0, C.real_budget(10)))
    files = G.discover(ch["source"] + ch["deleted"], _tests_arg(opts), facts, idx)
    first = ("TESTS: " + " ".join(files)) if files else "TESTS: none related"
    _emit(first, [])


# ----------------------------------------------------------------------------------------------------------------------
# full pipeline

def quick_mode(clock, last):
    """Tests are skipped from T_QUICK on, or when a full run (1.2 x the last test time plus QUICK_PAD for the import
    check and the claims) would not be over by T_VERIFY_END."""
    return clock >= C.T_QUICK or clock + 1.2 * last + C.QUICK_PAD > C.T_VERIFY_END


def span(G):
    """Real seconds this verify run may take: VERIFY_TOTAL, clamped so it ends by T_VERIFY_END (finalize then still
    has time to evaluate before T_EVAL_END and restore before T_NO_RESTORE), never below PHASE_MIN while the helper
    budget allows it."""
    return min(G.budget(C.VERIFY_TOTAL), max(G.PHASE_MIN, G.end_budget(C.VERIFY_TOTAL, C.T_VERIFY_END)))


def _diff_line(R):
    parts = []
    for p, f in sorted(R.get("facts", {}).items()):
        parts.append("%s +%d -%d" % (p, f["plus"], f["minus"]) if not f.get("binary") else "%s (binary)" % p)
    s = "DIFF: " + " | ".join(parts[:6])
    if len(parts) > 6:
        s += " | +%d more" % (len(parts) - 6)
    return _cut(s, 240)


def _import_line(R):
    imp = R.get("import") or {}
    if imp.get("ok") is False:
        return _cut("IMPORT: RED %s: %s%s" % (imp.get("module"), imp.get("line"),
                                              (" (%s)" % imp["where"]) if imp.get("where") else ""), 300)
    if imp.get("ok") is None:
        return "IMPORT: %s" % (imp.get("note") or "not checked")
    bits = []
    for top, o in sorted((imp.get("origins") or {}).items()):
        if top in (imp.get("outside") or {}):
            bits.append("%s OUTSIDE WORKSPACE: %s; tests import that copy, not your edit" % (top, _cut(o, 90)))
        else:
            bits.append("%s from workspace" % top)
    s = "IMPORT: ok"
    if imp.get("pre"):
        s = "IMPORT: " + imp.get("note", "fails on original too")
    elif bits:
        s += " (%s)" % "; ".join(bits[:3])
    elif imp.get("note"):
        s += " (%s)" % imp["note"]
    return _cut(s, 300)


def _tests_lines(R):
    t = R.get("tests")
    if t is None:
        return []
    st = t.get("status")
    if st == "none":
        return ["TESTS: none related"]
    if st == "unavailable":
        return [_cut("TESTS: unavailable (%s)" % (t.get("why") or "pytest missing"), 160)]
    if st == "skipped":
        return ["TESTS: skipped (%s)" % (t.get("why") or "quick mode")]
    files = " ".join(t.get("files") or [])
    o, c = t.get("orig_res") or t.get("orig") or {}, t.get("cur_res") or {}
    out = []
    if t.get("hang_now"):
        out.append(_cut("TESTS: %s | HANG-NOW: timed out after %ss (finished on original)" % (
            files, int((c or {}).get("secs", 0) + 0.5)), 300))
    elif st != "ok":
        out.append(_cut("TESTS: %s | UNKNOWN (%s)" % (files, t.get("why") or "no result"), 300))
    else:
        s = "TESTS: %s | original %s | now %s (%.1f s)" % (files, _counts(o), _counts(c), float(t.get("secs") or 0))
        if t.get("flaky"):
            s += " | %d flaky (passed on rerun)" % len(t["flaky"])
        if t.get("unknown_files"):
            s += " | collection error on both sides: %s" % " ".join(t["unknown_files"][:2])
        out.append(_cut(s, 360))
    if t.get("coll_now"):
        out.append("COLLECTION ERRORS (collect on original, not now):")
        for f, msg in sorted(t["coll_now"].items())[:3]:
            out.append(_cut("  %s  %s" % (f, msg), 200))
    return out


def _counts(side):
    import _swe_gate as G
    if not side:
        return "unknown"
    if side.get("status") == "timeout":
        return "timed out"
    if side.get("status") not in ("ok",):
        return "unknown (%s)" % _cut(side.get("why") or side.get("status"), 60)
    return G.counts(side.get("outcomes") or {})


def _regression_lines(R, note):
    t = R.get("tests") or {}
    regs = t.get("regressions") or []
    if t.get("status") != "ok" or not regs:
        return []
    msgs = ((t.get("cur_res") or {}).get("msgs") or {})
    out = ["REGRESSIONS (passed on original, fail now):"]
    for tid in regs[:5]:
        out.append(_cut("  %s  %s" % (tid, msgs.get(tid, "")), 200))
    if len(regs) > 5:
        out.append("  ... %d more" % (len(regs) - 5))
    if note:
        out.append(note)
    return out


def full(opts):
    t_start = time.time()
    ch, hyg = _changes()
    hline = ("HYGIENE: reverted %s" % _cut(", ".join(hyg), 200)) if hyg else None
    if not (ch["source"] or ch["deleted"]):
        first = "VERIFY: NO SOURCE CHANGE - make the plan's change with edit.py first."
        _journal({"first": first, "msg": "no source change"})
        _emit(first, [hline], src=False)
        return
    extra = _tests_arg(opts)
    diff = C.diff_bytes()
    dsha = _sha1(diff)
    text = _saved_repro()
    rsha = _sha1(text) if text.strip() else ""
    st = C.state_load() or {}
    clock = float(C.clock())
    last = float(st.get("last_test_secs") or 0)
    quick = quick_mode(clock, last)
    mode = "quick" if quick else "full"
    tmo = _opt(opts, "timeout")
    memo_key = _sha1("\0".join([dsha, rsha, " ".join(extra), mode, str(tmo or "")]))
    memo = ((st.get("memo") or {}).get("verify") or {})
    if memo.get("key") == memo_key and memo.get("first"):
        n = int(memo.get("n") or 1) + 1

        def bump(s):
            m = dict(s.get("memo") or {})
            v = dict(m.get("verify") or {})
            v["n"] = n
            m["verify"] = v
            s["memo"] = m
            return s
        C.state_update(bump)
        first = "SAME AS LAST RUN (t=%ds): %s" % (int(float(memo.get("t") or 0)), memo["first"])
        tail = [memo.get("next") or READY]
        if n >= 3:
            tail.append("STOP re-running verify; decide now.")
        _journal({"first": first, "msg": "same as last run"})
        _emit(first, [hline], tail=tail, src=True, sha=dsha)
        return
    import _swe_gate as G
    deadline = t_start + span(G)
    pcap = None
    if tmo is not None:
        try:
            pcap = max(5, min(60, int(tmo)))
        except (TypeError, ValueError):
            pcap = None
    R = G.evaluate(quick=quick, extra_tests=extra, deadline=deadline, diff=diff, ch=ch, pytest_cap=pcap)
    first, nxt, word = G.verdict(R)
    lines = _report(G, R, hline, nxt)
    cid = _save_ckpt(R, word, quick)
    best = None
    try:
        import _swe_ckpt as K
        b = K.best(R["key"], quick=quick)
        best = b.get("id") if b else None
    except Exception:
        pass
    if cid:
        lines.append("CHECKPOINT: #%s saved (best: #%s)%s" % (cid, best or cid, " (quick)" if quick else ""))
    t = R.get("tests") or {}
    secs = t.get("secs")

    def upd(s):
        m = dict(s.get("memo") or {})
        m["verify"] = {"key": memo_key, "n": 1, "t": round(float(C.clock()), 1), "first": first, "next": nxt}
        s["memo"] = m
        if secs:
            s["last_test_secs"] = float(secs)
        return s
    C.state_update(upd)
    _journal({"first": first, "msg": first[len("VERIFY: "):], "verdict": word, "secs": round(time.time() - t_start, 1)})
    body = _budget(lines)
    C.record_views(printed_views(body))
    _emit(first, body, tail=[nxt if nxt.startswith("NEXT:") else "NEXT: " + nxt], src=True, sha=dsha)


def _report(G, R, hline, nxt):
    """Sections in display order; NEXT is always last."""
    rp = R.get("repro") or {}
    summ = rp.get("summary") or {}
    lines = [_diff_line(R)]
    if hline:
        lines.append(hline)
    lines.append(_import_line(R))
    if rp:
        lines.append("REPRO: %s" % summ.get("text", "0/0 claims fixed"))
        lines += _claim_lines(rp.get("claims") or [], rp.get("orig") or {}, rp.get("cur") or {}, summ)[:6]
    else:
        lines.append("REPRO: none saved (write one: python3 /tmp/swe/verify.py --repro-only <<'EOF' ... EOF)")
    lines += _tests_lines(R)
    lines += _regression_lines(R, None if nxt == "NEXT: " + G.REGRESSION_NOTE or nxt.endswith(G.REGRESSION_NOTE)
                               else G.REGRESSION_NOTE)
    if R.get("siblings"):
        lines.append("SIBLINGS (same code elsewhere, unchanged; fix them too if they have the same defect):")
        lines += [_cut(x, 130) for x in R["siblings"][:6]]
    if R.get("gaps"):
        lines.append("SPEC GAPS:")
        lines += [_cut(x, 130) for x in R["gaps"][:4]]
    return lines


def _budget(lines):
    """Keep the body within BODY_BUDGET (NEXT travels separately as emit's tail): drop SPEC GAPS, then SIBLINGS, then
    trim indented detail lines from the bottom, the CHECKPOINT line always kept."""
    def size(ls):
        return sum(len(x) + 1 for x in ls)
    lines = [x for x in lines if x is not None]
    for head in ("SPEC GAPS:", "SIBLINGS ("):
        if size(lines) <= BODY_BUDGET:
            break
        out, skip = [], False
        for x in lines:
            if x.startswith(head):
                skip = True
                continue
            if skip and x.startswith("  "):
                continue
            skip = False
            out.append(x)
        lines = out
    while size(lines) > BODY_BUDGET:
        cand = [i for i, x in enumerate(lines) if x.startswith("  ")]
        if not cand:
            break
        del lines[cand[-1]]
    while size(lines) > BODY_BUDGET and len(lines) > 1:
        victim = max(range(len(lines)), key=lambda i: len(lines[i]) if not lines[i].startswith("CHECKPOINT") else -1)
        lines[victim] = _cut(lines[victim], max(40, len(lines[victim]) - (size(lines) - BODY_BUDGET)))
        if size(lines) > BODY_BUDGET and len(lines[victim]) <= 40:
            del lines[victim]
    return lines


def main():
    C.bootstrap()
    opts = get_args(sys.argv[1:])
    if opts is None:
        return
    if _opt(opts, "repro-only"):
        text = _opt(opts, "text")
        text = C.input_text({"text": text}) if text else C.read_stdin()
        import _swe_gate as G
        return repro_only(G, opts, text)
    if _opt(opts, "list-tests"):
        import _swe_gate as G
        return list_tests(G, opts)
    try:
        return full(opts)
    except Exception as e:
        first = "VERIFY: UNKNOWN - internal error (%s: %s)" % (type(e).__name__, _cut(e, 120))
        _journal({"first": first, "msg": "unknown"})
        _emit(first, ["NEXT: run verify.py once more; if it repeats, continue without it (verifier: run finalize.py)."])


if __name__ == "__main__":
    C.safe_main(NAME, main)
