"""Shared by the swe-tools helpers: the workspace root, and the per-task ledger (v7's search cap, v7c's record of reads and
its run of identical re-reads).

The ledger is <TMPDIR>/swe/.ledger.json, next to view.py's views log. TMPDIR is the task sandbox's own tmp dir
(adk_eval_core build_sanitized_env), so every task starts a fresh ledger; install.py creates it and the helpers create
it when it is missing. Counted (docs/a6000/FAILURE_FORENSICS.md finding 2: the locator spent the shared 70-call budget
in 28 of 43 budget-exhausted tasks): locate.py calls, refused after LOCATE_CAP per task (one line that says what to do
next, exit 0), and, for the record only, the view.py calls made before the task's first OK edit.py call.

v7c (docs/GAPS_2026-10-06.md, v7c pre-registration): no read cap. v7's pre-edit cap on view.py (and v7b's outline on
its 3rd refusal in a row) produced 737 refusals on 50 off-repo tasks, a refused read was repeated up to 49 times, loop
tasks went 7 (v4h2) -> 18 (v7) and tasks that ran out of calls did not fall (10 -> 11): a refused call costs a harness
call too. The ledger keeps the run of identical re-reads of an unchanged range per (file, range) (repeat_key,
repeat_run): every OUTLINE_EVERY-th one in a row is answered with OUTLINE (view.py then prints an outline of the
requested file) and the run starts again. Any other view.py call (a different range, a read that goes ahead, a call
that names no readable range) and an OK edit end the run; nothing else does.

v7d (docs/a6000/V7C_FAILURE_ANALYSIS.md, step 1): view.py declines nothing any more. The other re-reads in the run print
their lines again under one SHOWN AGAIN line (v7c answered them with a one-line refusal, which the fixer, a fresh agent
whose first view often repeats the locator's, took as a reason to ask again). The ledger's code is v7c's."""
import json, os, tempfile

LOCATE_CAP = 3
SEARCH_CAP_MSG = "search cap reached: use `git grep -n <name>` or write the plan now"
OUTLINE_EVERY = 3   # v7c: the 3rd, 6th, 9th ... identical re-read in a row of an unchanged range gets the outline
OUTLINE = "OUTLINE"  # take_view()'s answer on those turns; view.py prints the outline, never this word


def ws():
    for c in (os.environ.get("SWE_WS"), "/workspace", os.environ.get("PWD"), os.getcwd()):
        if c and os.path.isdir(os.path.join(c, ".git")):
            return c
    return "/workspace"


def ledger_path():
    return os.path.join(os.environ.get("TMPDIR") or tempfile.gettempdir(), "swe", ".ledger.json")


def ledger_load():
    try:
        with open(ledger_path()) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def ledger_save(d):
    p = ledger_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = "%s.%d.tmp" % (p, os.getpid())
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, p)
    except OSError:
        pass


def ledger_init():
    """install.py: a fresh ledger for this task; a recovery install never resets the counts."""
    if not os.path.exists(ledger_path()):
        ledger_save({"locate": 0, "view": 0, "edited": False, "repeat_key": None, "repeat_run": 0})


def take_locate():
    """Count one locate.py call; -> the refusal line when the task's search cap is already spent, else None."""
    d = ledger_load()
    if d.get("locate", 0) >= LOCATE_CAP:
        return SEARCH_CAP_MSG
    d["locate"] = d.get("locate", 0) + 1
    ledger_save(d)
    return None


def take_view(repeat_of=None):
    """Record one view.py call; never refuses (v7c). repeat_of: the views-log key ("path:start-end") when the call
    re-reads that unchanged range, else None. -> OUTLINE on every OUTLINE_EVERY-th re-read in a row of the same key (the
    run then starts again), else None. A call that is not a re-read ends the run. Before the task's first OK edit
    every call is counted in "view", for the record."""
    d = ledger_load()
    before = dict(d)
    if not d.get("edited"):
        d["view"] = d.get("view", 0) + 1
    run = 0
    if repeat_of is not None:
        run = (d.get("repeat_run", 0) if d.get("repeat_key") == repeat_of else 0) + 1
    d["repeat_key"] = repeat_of
    d["repeat_run"] = 0 if run >= OUTLINE_EVERY else run
    if d != before:
        ledger_save(d)
    return OUTLINE if run >= OUTLINE_EVERY else None


def mark_edited():
    """edit.py, after an OK edit: the pre-edit count of view.py calls stops, and any run of identical re-reads ends (an
    edit to the re-read file also changes it, so the next read of that range goes ahead)."""
    d = ledger_load()
    if not d.get("edited") or d.get("repeat_key") is not None or d.get("repeat_run"):
        d["edited"] = True
        d["repeat_key"], d["repeat_run"] = None, 0
        ledger_save(d)
