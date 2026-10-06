"""Pick the best of the three fixers' candidates and apply it to the workspace (v6p, docs/GAPS_2026-10-06.md AC-B2 + S3).
Stdlib only, Python 3.11. Run once by the selector stage:
    run_skill_script(skill_name="swe-tools", file_path="select_best.py", args={"test": "tests/test_x.py"})
or, equivalently, `python3 /tmp/swe/select_best.py --test tests/test_x.py` through run_command.

Not named select.py: installed into /tmp/swe, that would shadow the stdlib `select` module for every helper started as
`python3 /tmp/swe/<helper>.py` (sys.path[0] is the script's dir) and break `import subprocess` in test.py and check.py.

Candidates. Fixer K (a, b, c) worked in its own copy <tmp>/wK and wrote <tmp>/wK.diff. The copy is the ground truth
when it exists (diff against the workspace HEAD, untracked files included: it is current even when the fixer ran out of
calls before writing the diff); otherwise wK.diff is used. Test/config files (discarded at grading) and new scratch files
(repro/scratch/debug names, .txt/.log/.diff/...) are dropped. Identical candidates are checked once.

Checks. Each candidate is applied to one clean copy of the workspace HEAD and checked with
  1. the locator's repro <tmp>/repro.py (S3), run with cwd = the copy, the copy as sys.argv[1] and the copy first on
     PYTHONPATH (the sandbox exports PYTHONPATH=<workspace>); ignored if it already passes on the unedited code;
  2. the locator's TEST target (--test; when absent or missing, tests/test_<stem>.py of a changed module).
Each candidate has its own time budget (--timeout, default 16 s) inside a total (--total, default 52 s).

Ranking: repro pass, then TEST pass, then the smallest diff (changed lines), then a < b < c. Empty candidates never win.
All empty -> the workspace is left exactly as it was. Otherwise the workspace's tracked files are reset (git checkout --
.), untracked files are removed except ignored ones (the harness git-excludes .adk_exec_*.py, the run_skill_script
wrapper, and build artefacts) and the pick is applied with git apply. Always exits 0; prints < 2,000 chars."""
import os, re, shutil, signal, subprocess, sys, tempfile, time

LETTERS = "abc"
PROTECTED = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|"
                       r"(^|/)(conftest\.py|pytest\.ini|tox\.ini|setup\.cfg|pyproject\.toml)$")
SCRATCH = re.compile(r"(^|/)[^/]*(repro|scratch|debug)[^/]*$|\.(txt|log|out|diff|patch|orig|rej|pyc|swe_edit_tmp)$|"
                     r"(^|/)\.adk_exec_[^/]*$|(^|/)__pycache__/", re.I)
HEADER = re.compile(r"^diff --git a/(.*) b/(.*)$")
REPORT_MAX = 1900


def parse_args(argv):
    opt = {"test": "", "ws": "", "tmp": "", "timeout": "16", "total": "52"}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--") and "=" in a:
            k, v = a[2:].split("=", 1); opt[k] = v; i += 1
        elif a.startswith("--") and i + 1 < len(argv):
            opt[a[2:]] = argv[i + 1]; i += 2
        else:
            i += 1
    return opt


def is_repo(d):
    return bool(d) and os.path.isdir(os.path.join(d, ".git"))


def find_ws(explicit):
    for c in (explicit, os.environ.get("SWE_WS"), "/workspace", os.environ.get("PWD"), os.getcwd()):
        if is_repo(c):
            return c
    return None


def tmp_bases(explicit):
    out = []
    for b in (explicit, os.environ.get("TEST_TMPDIR"), os.environ.get("TMPDIR"), tempfile.gettempdir(), "/tmp"):
        if b and os.path.isdir(b) and os.path.realpath(b) not in [os.path.realpath(x) for x in out]:
            out.append(b)
    return out


def git(d, *args, stdin=None):
    r = subprocess.run(["git", "-C", d] + list(args), input=stdin, capture_output=True)
    return r.returncode, r.stdout.decode("utf-8", "surrogateescape"), r.stderr.decode("utf-8", "replace")


def split_sections(diff):
    """-> [(path, is_new_file, section_text)]"""
    out, cur = [], []
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git ") and cur:
            out.append(cur); cur = []
        cur.append(line)
    if cur and cur[0].startswith("diff --git "):
        out.append(cur)
    res = []
    for sec in out:
        m = HEADER.match(sec[0].rstrip("\n"))
        path = (m.group(2) if m else sec[0].split()[-1][2:]).strip('"')
        head = "".join(sec[:6])
        res.append((path, "\nnew file mode" in "\n" + head or "--- /dev/null" in head, "".join(sec)))
    return res


def clean_diff(diff):
    """Drop test/config files and new scratch files. -> (diff text, files, changed lines)."""
    keep, files, size = [], [], 0
    for path, new, text in split_sections(diff):
        if PROTECTED.search(path) or (new and SCRATCH.search(path)):
            continue
        keep.append(text); files.append(path)
        n = sum(1 for l in text.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---")))
        size += n or 1                                                   # a binary or mode-only change counts 1
    return "".join(keep), files, size


def load_candidate(k, bases, head):
    for b in bases:
        d = os.path.join(b, "w" + k)
        if is_repo(d):
            git(d, "add", "-N", ".")
            rc, out, err = git(d, "diff", "--binary", head)
            if rc == 0:
                return out, "copy"
    for b in bases:
        f = os.path.join(b, "w%s.diff" % k)
        if os.path.isfile(f):
            with open(f, "rb") as fh:
                return fh.read().decode("utf-8", "surrogateescape"), "diff file"
    return None, "missing"


def run(cmd, cwd, timeout, extra_env=None):
    """-> (status 'PASS'|'FAIL'|'TIMEOUT', last informative line)"""
    if timeout < 0.5:
        return "SKIP", "no time left"
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in (cwd, os.environ.get("PYTHONPATH")) if p))
    env.update(extra_env or {})
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            p.kill()
        p.communicate()
        return "TIMEOUT", "timeout after %.0fs" % timeout
    lines = [l.strip() for l in out.decode("utf-8", "replace").splitlines() if l.strip()]
    tail = next((l for l in reversed(lines) if re.search(r"Error|FAILED|failed|passed|assert", l)), lines[-1] if lines else "")
    return ("PASS" if p.returncode == 0 else "FAIL"), tail[:160]


def reset(d):
    git(d, "checkout", "-q", "--", ".")
    git(d, "clean", "-fdq", "-e", ".adk_exec_*")


def guess_test(sel, explicit, files):
    t = explicit.strip().strip("`'\" ")
    if t:
        if os.path.isfile(os.path.join(sel, t.split("::")[0])):
            return t, "from --test"
    tracked = git(sel, "ls-files")[1].splitlines()
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0].lstrip("_")
        if not stem or not f.endswith(".py"):
            continue
        hits = sorted((p for p in tracked if re.search(r"(^|/)test_%s\.py$" % re.escape(stem), p)), key=len)
        if hits:
            return hits[0], "guessed from " + os.path.basename(f) + (" (--test %s not found)" % t if t else "")
    return None, ("--test %s not found" % t) if t else "no test given"


def main(argv):
    t0 = time.time()
    opt = parse_args(argv)
    per, total = float(opt["timeout"]), float(opt["total"])
    deadline = t0 + total
    rep = []
    ws = find_ws(opt["ws"])
    if not ws:
        print("select_best: no workspace git repo found\nPICK none: workspace not found; nothing changed"); return
    bases = tmp_bases(opt["tmp"])
    head = git(ws, "rev-parse", "HEAD")[1].strip() or "HEAD"
    cands = {}
    for k in LETTERS:
        raw, src = load_candidate(k, bases, head)
        if raw is None:
            cands[k] = dict(state="missing", diff="", files=[], size=0, src=src)
            continue
        diff, files, size = clean_diff(raw)
        cands[k] = dict(state="empty" if not diff.strip() else "ok", diff=diff, files=files, size=size, src=src)
    live = [k for k in LETTERS if cands[k]["state"] == "ok"]
    if not live:
        rep.append("select_best: ws=%s" % ws)
        for k in LETTERS:
            rep.append("%s: %s" % (k, cands[k]["state"]))
        rep.append("PICK none: no candidate changed a source file; workspace left unchanged")
        print("\n".join(rep)); return
    # one clean copy of the workspace HEAD for every check
    sel = os.path.join(bases[0], "swe_sel")
    shutil.rmtree(sel, ignore_errors=True)
    shutil.copytree(ws, sel, symlinks=True)
    reset(sel)
    repro = next((os.path.join(b, "repro.py") for b in bases if os.path.isfile(os.path.join(b, "repro.py"))), None)
    repro_note = "none"
    if repro:
        st, why = run([sys.executable, repro, sel], sel, min(per, deadline - time.time()))
        if st == "PASS":
            repro_note = "passes before the fix: ignored"; repro = None
        else:
            repro_note = "fails before the fix (%s)" % st.lower()
    all_files = []
    for k in live:
        all_files += [f for f in cands[k]["files"] if f not in all_files]
    test, test_note = guess_test(sel, opt["test"], all_files)
    rep.append("select_best: test=%s (%s) | repro=%s" % (test, test_note, repro_note))
    seen = {}
    for k in live:
        c = cands[k]
        if c["diff"] in seen:
            c.update(same=seen[c["diff"]]); continue
        seen[c["diff"]] = k
        reset(sel)
        rc, _, err = git(sel, "apply", "--whitespace=nowarn", "-", stdin=c["diff"].encode("utf-8", "surrogateescape"))
        if rc != 0:
            c.update(state="does not apply", why=err.strip().splitlines()[-1][:120] if err.strip() else "")
            continue
        cdl = min(time.time() + per, deadline)
        c["repro"], c["repro_why"] = (run([sys.executable, repro, sel], sel, cdl - time.time()) if repro else ("-", ""))
        if test:
            c["test"], c["test_why"] = run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "-o",
                                            "addopts=", "--tb=line", test], sel, cdl - time.time())
        else:
            c["test"], c["test_why"] = "-", ""
    for k in live:
        c = cands[k]
        if "same" in c:
            src = cands[c["same"]]
            for f in ("state", "repro", "repro_why", "test", "test_why", "why"):
                if f in src: c[f] = src[f]
    ranked = sorted((k for k in live if cands[k]["state"] == "ok"),
                    key=lambda k: (cands[k]["repro"] != "PASS", cands[k]["test"] != "PASS", cands[k]["size"], k))
    for k in LETTERS:
        c = cands[k]
        if c["state"] in ("missing", "empty"):
            rep.append("%s: %s" % (k, c["state"])); continue
        names = ", ".join(f[-50:] for f in c["files"][:3]) + (" +%d more" % (len(c["files"]) - 3) if len(c["files"]) > 3 else "")
        line = "%s: %d lines in %s [%s]" % (k, c["size"], names, c["src"])
        if c["state"] != "ok":
            line += " | %s %s" % (c["state"], c.get("why", ""))
        else:
            line += " | repro %s | test %s" % (c["repro"], c["test"])
            if "same" in c:
                line += " | same as %s" % c["same"]
        rep.append(line)
    applied = None
    for k in ranked:
        reset(ws)
        rc, _, err = git(ws, "apply", "--whitespace=nowarn", "-", stdin=cands[k]["diff"].encode("utf-8", "surrogateescape"))
        if rc == 0:
            applied = k; break
        rep.append("%s: apply to workspace failed: %s" % (k, err.strip()[-120:]))
    shutil.rmtree(sel, ignore_errors=True)
    if applied is None:
        rep.append("PICK none: no candidate applied; workspace reset to HEAD")
    else:
        c = cands[applied]
        rep.append("PICK %s: repro %s, test %s, %d changed lines; applied to the workspace (%.0fs)"
                   % (applied, c["repro"], c["test"], c["size"], time.time() - t0))
        fails = [w for st, w in ((c["repro"], "repro: " + c.get("repro_why", "")), (c["test"], "test: " + c.get("test_why", "")))
                 if st not in ("PASS", "-")]
        if fails:
            rep.append("still failing -> " + " | ".join(fails)[:300])
    text = "\n".join(rep)
    if len(text) > REPORT_MAX:
        pick = [l for l in rep if l.startswith("PICK")]
        text = text[:REPORT_MAX - 200].rsplit("\n", 1)[0] + "\n...\n" + "\n".join(pick)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1:])
