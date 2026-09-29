"""The pre-registered decision rule of docs/v10/AB_L4.md, executable (2026-09-29). Stdlib only.

Each arm is compared with the v10.1 control kernel on the same 74 ids, one run each. An arm is SHIP-ELIGIBLE only if
  1. resolved(arm) - resolved(control) >= +4 on the paired ids,
  2. no new crash class: no class below has a row in the arm and none in the control,
  3. wall time (sum of per-task seconds, vLLM start excluded) <= 1.1 x the control's.
A pair is INVALID (rerun, never decide) when either run misses ids of the other or of --ids, or when both runs recorded
their wheel set (wheelhouse_sha256.txt, written by make_eval_kernel.py) and the sets differ.
Reported, never deciding: paired wins/losses with the exact one-sided sign test, session timeouts, mean seconds.

Usage: python scripts/ab_l4_decide.py CONTROL_DIR ARM_DIR [ARM_DIR ...] [--ids data/kaggle_valid_ids.txt]
Each DIR holds a kernel's results.jsonl (kaggle kernels output carsonrodrigues/<slug> -p eval/kaggle/<slug>)."""
import argparse, json, math, os, re, sys

MIN_DELTA = 4
MAX_WALL_RATIO = 1.1
# Crash classes: race2_checklist row 3 (replay_l4.CRASH), plus the two ways the kernel loop itself can lose a task.
CRASH = {
    "context_overflow": re.compile(r"ContextWindowExceeded|maximum context length|prompt contains at least", re.I),
    "unknown_tool": re.compile(r"Tool '[^']+' not found"),
    "key_error": re.compile(r"KeyError|Context variable not found"),
    "post_invocation": re.compile(r"No LlmAgent model available"),
    "kernel_exception": re.compile(r"^EXC "),
    "sandbox_error": re.compile(r"^Sandbox execution error"),
}
TIMEOUT = re.compile(r"exceeded session timeout|turn limit|tool call limit", re.I)


def load(d):
    rows = {}
    with open(os.path.join(d, "results.jsonl")) as f:
        for ln in f:
            if ln.strip():
                r = json.loads(ln)
                rows[r["id"]] = r
    sha = os.path.join(d, "wheelhouse_sha256.txt")
    wheels = open(sha).read() if os.path.isfile(sha) else None
    return rows, wheels


def crash_classes(rows):
    """{class: count}; an error matching no class counts as other_error (a new kind of failure is still a class)."""
    out = {}
    for r in rows.values():
        err = r.get("err") or ""
        if not err or TIMEOUT.search(err):
            continue
        k = next((k for k, rx in CRASH.items() if rx.search(err)), "other_error")
        out[k] = out.get(k, 0) + 1
    return out


def sign_p(wins, losses):
    """One-sided exact sign test: P(W >= wins | n = wins + losses, p = 0.5)."""
    n = wins + losses
    return sum(math.comb(n, w) for w in range(wins, n + 1)) / 2 ** n if n else 1.0


def decide(control, arm, ids=None):
    """-> dict with 'verdict' in SHIP-ELIGIBLE / NO / INVALID and every number the rule used."""
    (c, cw), (a, aw) = control, arm
    want = set(ids) if ids else set(c) | set(a)
    missing = sorted((want - set(c)) | (want - set(a)))
    out = {"n": len(want), "missing": missing[:10], "n_missing": len(missing)}
    if missing:
        return dict(out, verdict="INVALID", why="%d ids missing from a run" % len(missing))
    if cw is not None and aw is not None and cw != aw:
        return dict(out, verdict="INVALID", why="the runs used different wheel sets (wheelhouse_sha256.txt)")
    res = lambda rows, i: bool(rows[i].get("resolved"))
    rc = sum(res(c, i) for i in want)
    ra = sum(res(a, i) for i in want)
    wins = sum(res(a, i) and not res(c, i) for i in want)
    losses = sum(res(c, i) and not res(a, i) for i in want)
    cc, ac = crash_classes({i: c[i] for i in want}), crash_classes({i: a[i] for i in want})
    new = sorted(k for k in ac if not cc.get(k))
    wall_c = sum(float(c[i].get("secs") or 0) for i in want)
    wall_a = sum(float(a[i].get("secs") or 0) for i in want)
    ratio = wall_a / wall_c if wall_c else float("inf")
    checks = {"delta": ra - rc >= MIN_DELTA, "no_new_crash_class": not new, "wall": ratio <= MAX_WALL_RATIO + 1e-9}
    out.update(resolved_control=rc, resolved_arm=ra, delta=ra - rc, wins=wins, losses=losses,
               sign_p=round(sign_p(wins, losses), 4), crashes_control=cc, crashes_arm=ac, new_crash_classes=new,
               wall_control_s=round(wall_c), wall_arm_s=round(wall_a), wall_ratio=round(ratio, 3), checks=checks,
               timeouts_control=sum(bool(TIMEOUT.search(c[i].get("err") or "")) for i in want),
               timeouts_arm=sum(bool(TIMEOUT.search(a[i].get("err") or "")) for i in want),
               wheels="same" if cw is not None and aw is not None else "unrecorded",
               verdict="SHIP-ELIGIBLE" if all(checks.values()) else "NO")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("control")
    ap.add_argument("arms", nargs="+")
    ap.add_argument("--ids", help="the paired id list (default: the union of both runs)")
    a = ap.parse_args(argv)
    ids = None
    if a.ids:
        with open(a.ids) as f:
            ids = [x.strip() for x in f if x.strip()]
    control = load(a.control)
    results = {}
    for d in a.arms:
        r = decide(control, load(d), ids)
        results[d] = r
        print("%s\t%s\t%s" % (r["verdict"], os.path.basename(os.path.normpath(d)), json.dumps(
            {k: v for k, v in r.items() if k != "verdict"}, sort_keys=True)))
    ok = [d for d, r in results.items() if r["verdict"] == "SHIP-ELIGIBLE"]
    if len(ok) > 1:          # AB_L4.md: the largest delta, then the lower wall ratio; combining arms needs its own A/B
        ok.sort(key=lambda d: (-results[d]["delta"], results[d]["wall_ratio"]))
    print("PICK", os.path.basename(os.path.normpath(ok[0])) if ok else "none (keep the control)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
