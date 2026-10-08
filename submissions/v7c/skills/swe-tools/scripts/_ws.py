"""Shared by the swe-tools helpers: the workspace root, and the per-task ledger of v7's pre-edit caps.

The ledger is <TMPDIR>/swe/.ledger.json, next to view.py's views log. TMPDIR is the task sandbox's own tmp dir
(adk_eval_core build_sanitized_env), so every task starts a fresh ledger; install.py creates it and the helpers create
it when it is missing. Counted (docs/a6000/FAILURE_FORENSICS.md finding 2: the locator spent the shared 70-call budget
in 28 of 43 budget-exhausted tasks): locate.py calls, refused after LOCATE_CAP per task, and view.py calls made before
the task's first OK edit.py call, refused after VIEW_CAP; edit.py records that first OK edit and view.py is uncapped
from then on. A refusal is one line that says what to do next, exit 0.

v7b (docs/GAPS_2026-10-06.md, last section, fix 1): on the A6000 v7 run the read cap was a loop trap (4 of the 6 capped
tasks sent the identical refused view.py call >= 5 times and got the identical line back). The ledger also counts the
task's consecutive refused reads (refused_run); every OUTLINE_EVERY-th refused read in a row is answered with OUTLINE
instead of the refusal line (view.py then prints an outline of the requested file) and the run starts again. A read
that goes ahead and an OK edit end the run; nothing else does."""
import json, os, tempfile

LOCATE_CAP = 3
VIEW_CAP = 14  # raised from 8 before any v7 result (2026-10-07 23:35 IST): the allowance is shared with the fixer
SEARCH_CAP_MSG = "search cap reached: use `git grep -n <name>` or write the plan now"
READ_CAP_MSG = "read cap reached before any edit: edit now with edit.py (fixer) or write the plan (locator)"
OUTLINE_EVERY = 3   # v7b: the 3rd, 6th, 9th ... consecutive refused read gets the outline instead of READ_CAP_MSG
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
        ledger_save({"locate": 0, "view": 0, "edited": False, "refused_run": 0})


def take_locate():
    """Count one locate.py call; -> the refusal line when the task's search cap is already spent, else None."""
    d = ledger_load()
    if d.get("locate", 0) >= LOCATE_CAP:
        return SEARCH_CAP_MSG
    d["locate"] = d.get("locate", 0) + 1
    ledger_save(d)
    return None


def take_view():
    """Count one view.py call made before the task's first OK edit. -> None when the read goes ahead (it ends any run of
    refused reads), the refusal line past VIEW_CAP, or OUTLINE on every OUTLINE_EVERY-th refused read in a row (v7b: the
    run then starts again, so the next two refused reads get the refusal line)."""
    d = ledger_load()
    if d.get("edited") or d.get("view", 0) < VIEW_CAP:
        save = bool(d.get("refused_run"))
        d["refused_run"] = 0
        if not d.get("edited"):
            d["view"] = d.get("view", 0) + 1
            save = True
        if save:
            ledger_save(d)
        return None
    run = d.get("refused_run", 0) + 1
    d["refused_run"] = 0 if run >= OUTLINE_EVERY else run
    ledger_save(d)
    return OUTLINE if run >= OUTLINE_EVERY else READ_CAP_MSG


def mark_edited():
    """edit.py, after an OK edit: the pre-edit read cap no longer applies in this task, and any run of refused reads
    ends (v7b)."""
    d = ledger_load()
    if not d.get("edited") or d.get("refused_run"):
        d["edited"] = True
        d["refused_run"] = 0
        ledger_save(d)
