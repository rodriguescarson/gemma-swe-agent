"""Per-fixer tool-call ledger of v6p-b (docs/v4h/GATE.md, P2 addendum 6).

The harness counts every tool call of every agent against ONE budget (swegemma/tools/base.py budget_gated), and the bundle compiler is given no callback
registry, so a per-agent cap cannot be enforced by the harness. v6p (13 calls per fixer, in the prompt only) let three parallel fixers overrun it: in the first
5 items 3 ended on the 70-call budget with an empty patch, the selector and the verifier never ran. Here the caps live in the helpers the fixers call:

  * every helper run in a fixer's copy (/tmp/wa, /tmp/wb, /tmp/wc) is counted in a ledger (one exclusive-create file per call: exact under three parallel processes);
  * after SHARES["helper"] counted calls the helpers refuse to work and say what to do (the final diff command, then reply), so the model's next tool result tells it to stop;
  * a fixer whose targeted test passes writes a flag; every other fixer's next helper call is refused with STOP (the selection will use the passing candidate).
Raw run_command calls (the copy, one git grep, the final diff) are not seen by the helpers; SHARES["allowance"] pays for them in the budget arithmetic."""
import os, tempfile

# The stage shares inside the 70-call total (tests/test_v6pb_bundle.py checks the arithmetic and that every prompt says the same numbers).
# setup 1 + locator 8 (v4h2's own cap) + 3 fixers x 10 + selector 1 + verifier 17 = 57; every fixer may overshoot by the allowance (4 raw calls) and the
# selector and verifier still have their 18 calls: 70 - 1 - 8 - 3 x 14 = 19 >= 18.
SHARES = {"setup": 1, "locator": 8, "selector": 1, "verifier": 17, "fixer": 10, "helper": 7, "allowance": 4, "total": 70}


def fixer_id(root):
    """'a' for a root named wa, 'b' for wb, 'c' for wc (the fixers' copies); None for /workspace or anything else."""
    b = os.path.basename(os.path.normpath(root or ""))
    return b[1] if len(b) == 2 and b[0] == "w" and b[1] in "abc" else None


def _base(base=None):
    d = base or os.path.join(os.environ.get("TMPDIR") or tempfile.gettempdir(), "swe", "budget")
    os.makedirs(d, exist_ok=True)
    return d


def used(root, base=None):
    k = fixer_id(root)
    if k is None:
        return 0
    return sum(1 for f in os.listdir(_base(base)) if f.startswith(k + ".call."))


def _tick(k, d):
    n = sum(1 for f in os.listdir(d) if f.startswith(k + ".call.")) + 1
    while True:
        try:
            os.close(os.open(os.path.join(d, "%s.call.%d" % (k, n)), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return n
        except FileExistsError:
            n += 1


def mark_passed(root, base=None):
    k = fixer_id(root)
    if k is None:
        return
    try:
        os.close(os.open(os.path.join(_base(base), "passed." + k), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        pass


def _final(k):
    return ('run_command(command="cd /tmp/w%s && git -C /tmp/w%s add -N . && git -C /tmp/w%s diff > /tmp/w%s.diff; git -C /tmp/w%s diff --stat")'
            % (k, k, k, k, k))


def enter(root, base=None):
    """Called first by view.py / edit.py / test.py. -> (refusal or None, footer). A non-fixer root is never counted: (None, '')."""
    k = fixer_id(root)
    if k is None:
        return None, ""
    d = _base(base)
    others = sorted(f.split(".")[1] for f in os.listdir(d) if f.startswith("passed.") and f.split(".")[1] != k)
    if others:
        return ("STOP: candidate %s already passes its tests, so the selection will use it. Your next call is the final command %s, then reply in under 50 words. "
                "Do not call anything else." % (others[0], _final(k))), ""
    n, h = _tick(k, d), SHARES["helper"]
    if n > h:
        return ("SHARE SPENT: your %d helper calls are used and nothing was done. Your next call is the final command %s, then reply in under 100 words. "
                "Do not call anything else." % (h, _final(k))), ""
    tail = "the last one: next run your final diff command and reply" if n == h else "%d left" % (h - n)
    return None, "[fixer %s: helper call %d/%d, %s]" % (k, n, h, tail)
