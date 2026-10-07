"""Shared by the swe-tools helpers: the workspace root, and the per-task ledger of v7's pre-edit caps.

The ledger is <TMPDIR>/swe/.ledger.json, next to view.py's views log. TMPDIR is the task sandbox's own tmp dir
(adk_eval_core build_sanitized_env), so every task starts a fresh ledger; install.py creates it and the helpers create
it when it is missing. Counted (docs/a6000/FAILURE_FORENSICS.md finding 2: the locator spent the shared 70-call budget
in 28 of 43 budget-exhausted tasks): locate.py calls, refused after LOCATE_CAP per task, and view.py calls made before
the task's first OK edit.py call, refused after VIEW_CAP; edit.py records that first OK edit and view.py is uncapped
from then on. A refusal is one line that says what to do next, exit 0."""
import json, os, tempfile

LOCATE_CAP = 3
VIEW_CAP = 8
SEARCH_CAP_MSG = "search cap reached: use `git grep -n <name>` or write the plan now"
READ_CAP_MSG = "read cap reached before any edit: edit now with edit.py (fixer) or write the plan (locator)"


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
        ledger_save({"locate": 0, "view": 0, "edited": False})


def take_locate():
    """Count one locate.py call; -> the refusal line when the task's search cap is already spent, else None."""
    d = ledger_load()
    if d.get("locate", 0) >= LOCATE_CAP:
        return SEARCH_CAP_MSG
    d["locate"] = d.get("locate", 0) + 1
    ledger_save(d)
    return None


def take_view():
    """Count one view.py call made before the task's first OK edit; -> the refusal line past VIEW_CAP, else None."""
    d = ledger_load()
    if d.get("edited"):
        return None
    if d.get("view", 0) >= VIEW_CAP:
        return READ_CAP_MSG
    d["view"] = d.get("view", 0) + 1
    ledger_save(d)
    return None


def mark_edited():
    """edit.py, after an OK edit: the pre-edit read cap no longer applies in this task."""
    d = ledger_load()
    if not d.get("edited"):
        d["edited"] = True
        ledger_save(d)
