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
# journal tail, the diffstat and a bounded diff of the source files. Read-only. Any argument is ignored.

NAME = "status"
USAGE = "python3 /tmp/swe/status.py"
FLAGS = {}
DIFF_CAP = 1600
JOURNAL_N = 8


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


def main():
    C.bootstrap()
    t = C.clock()
    st = C.state_load()
    ch = C.changes()
    lines = []
    head = "STATUS [t=%ds] helpers %s | %s | %s" % (int(t), C.VERSION, repro_summary(st), ckpt_summary(st))
    sha = None
    if st.get("final_done") and st.get("final_sha"):
        sha = C.diff_sha()
        if sha != st.get("final_sha"):
            lines.append("CHANGED AFTER FINALIZE: run finalize.py again.")
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
    if ch["protected"]:
        lines.append(C._short("PROTECTED (reverted by edit.py, verify.py and finalize.py): " +
                              ", ".join(ch["protected"][:6]), 300))
    scratch = [p for p in ch["untracked"] if p not in ch["source"]]
    if scratch:
        lines.append(C._short("UNTRACKED (not source): " + ", ".join(scratch[:6]) +
                              (" (+%d more)" % (len(scratch) - 6) if len(scratch) > 6 else ""), 300))
    fixed = len(head) + sum(len(x) + 1 for x in lines) + 120
    room = min(DIFF_CAP, C.CAPS[NAME] - fixed)
    if diff.strip() and room > 200:
        lines.append(cap_diff(C.clean_text(diff).rstrip("\n"), room))
    C.emit(NAME, head, "\n".join(lines), C.CAPS[NAME], src=bool(paths), sha=sha)


if __name__ == "__main__":
    C.safe_main(NAME, main)
