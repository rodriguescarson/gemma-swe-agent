"""Historical eval kernels (kernels/<dir>/, generated on the Mac, gitignored) are pinned by their bundles' tests: rebuilding with
scripts/make_eval_kernel.py must give the notebook that ran. Builder changes made after those runs are listed in LATER and
undone on the rebuilt notebook before the comparison, so any other drift still fails.

29 Oct 2026 (impl/eval-tooling): the id filter asserts that every requested id was found and prints the count; a comment on
the Phase 2 verification timeout (reworded 31 Oct); result rows keep test_tail."""
import json
from pathlib import Path

LATER = [   # (what the builder writes now, what it wrote when the pinned kernels ran)
    ("if IDS:\n    tasks = [t for t in tasks if t.instance_id in set(IDS)]\n"
     "    assert len(tasks) == len(set(IDS)), ('requested ids missing from tasks.jsonl', sorted(set(IDS) - {t.instance_id for t in tasks})[:10])\n"
     "print(len(tasks), 'tasks', ('of %d requested ids' % len(set(IDS))) if IDS else '(no id filter)', 'ORACLE' if ORACLE else 'AGENT', BUDGET)",
     "if IDS: tasks = [t for t in tasks if t.instance_id in set(IDS)]\nprint(len(tasks), 'tasks', 'ORACLE' if ORACLE else 'AGENT', BUDGET)"),
    ("# Phase 2's pytest timeout: the wheelhouse Kaggle serves since 12 Oct gives EvalConfig a verification_timeout_seconds that\n"
     "# defaults to the scorer's 300 s (the host notebook passes it); only the 11 Oct build reused timeout_seconds (**BUDGET below).\n",
     ""),
    (", test_tail=(r.test_output or '')[-2500:])", ")"),
]


def as_pinned(path: Path):
    """The rebuilt file in the form the pinned kernel was built: raw bytes for metadata, the notebook with LATER undone."""
    if path.suffix != ".ipynb":
        return path.read_bytes()
    nb = json.loads(path.read_text())
    for c in nb["cells"]:
        src = "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
        for now, then in LATER:
            src = src.replace(now, then)
        c["source"] = src
    return nb


def pinned(path: Path):
    """The committed file in the same form as as_pinned() returns it."""
    if path.suffix != ".ipynb":
        return path.read_bytes()
    nb = json.loads(path.read_text())
    for c in nb["cells"]:
        c["source"] = "".join(c["source"]) if isinstance(c["source"], list) else c["source"]
    return nb
