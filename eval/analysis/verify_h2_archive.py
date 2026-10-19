"""Verify a Harness² archive the box pushed (paper/EVIDENCE.md D1-D5; the archive rule is channel M-046), so that "the results
are saved" is a checked fact, not an instruction that was sent.

    python eval/analysis/verify_h2_archive.py eval/a6000/results/h2_argon [--kind sweep|transfer|evidence] [--prereg "HEADING TEXT"]

Checks (each prints PASS/FAIL; exit 1 if any FAIL):
  manifest   MANIFEST.sha256 lists every file and every hash matches
  env        env.txt names the harness2 pin (1cfe254) and holds a pip freeze
  proxy      proxy.jsonl has per-call rows (t, latency_s)
  sweep      root/adapt (summaries), root/adapt/_audit (improver sessions), root/library, the rollouts (results + traces in
             equal numbers; under root/race/items/<arm>/<task> each with a record root/race/staged/<arm>/<task>.json naming its run and fingerprint, or the
             pre-B-208 root/rollouts/<run>/items/<arm>/<task>), judged.json and base_judged.json
  transfer   eval_base_a.json and eval_base_b.json, and a frozen/<label>/ tree for every non-base eval_<label>.json
  secrets    no OpenRouter key material ("sk-or-") anywhere
  prereg     (optional) the commit that added the GAPS section titled HEADING is an ancestor of the first commit that added
             this archive: the reading rule existed before the result did"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIN = "1cfe254"
EXPECTED = json.loads((ROOT / "eval" / "analysis" / "h2_expected.json").read_text())


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def files_under(d: Path) -> list[Path]:
    return sorted(p for p in d.rglob("*") if p.is_file())


def _load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def check_manifest(d: Path) -> tuple[bool, str]:
    m = d / "MANIFEST.sha256"
    if not m.is_file():
        return False, "MANIFEST.sha256 missing"
    listed = {}
    for line in m.read_text().splitlines():
        if line.strip():
            h, rel = line.split(None, 1)
            listed[rel.strip().lstrip("*").removeprefix("./")] = h
    listed.pop("VERIFY.txt", None)
    present = {str(p.relative_to(d)) for p in files_under(d)} - {"MANIFEST.sha256", "VERIFY.txt"}   # VERIFY.txt is this script's
    # own output, written after the manifest; listing it in the manifest it verifies would be circular (box B-216)
    missing = sorted(set(listed) - present)
    unlisted = sorted(present - set(listed))
    bad = sorted(rel for rel, h in listed.items() if rel in present and sha256(d / rel) != h)
    ok = not (missing or unlisted or bad)
    return ok, f"{len(listed)} listed; missing {missing[:3]}{'...' if len(missing) > 3 else ''}; unlisted {unlisted[:3]}; " \
               f"hash mismatches {bad[:3]}" if not ok else f"{len(listed)} files, all hashes match"


def check_env(d: Path) -> tuple[bool, str]:
    e = d / "env.txt"
    if not e.is_file():
        return False, "env.txt missing"
    t = e.read_text(errors="replace")
    ok = PIN in t and t.count("==") >= 10
    return ok, "harness2 pin and pip freeze present" if ok else f"pin {PIN} present: {PIN in t}; pip freeze lines: {t.count('==')}"


def check_proxy(d: Path) -> tuple[bool, str]:
    p = d / "proxy.jsonl"
    if not p.is_file():
        return False, "proxy.jsonl missing"
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    ok = bool(rows) and all("t" in r and "latency_s" in r for r in rows)
    return ok, f"{len(rows)} per-call rows" if ok else f"{len(rows)} rows, some without t/latency_s"


def _record(r: Path, item: Path) -> Path:
    return r / "race" / "staged" / item.parent.name / f"{item.name}.json"


def _rollouts(r: Path) -> list[tuple[str, str | None, Path]]:
    """(task, run_id, item dir) for every result. Since 19 Oct (box B-208) the launcher writes root/race/items/<arm>/<task>
    with the run id in the rollout's record root/race/staged/<arm>/<task>.json, written before the rollout (B-209: the race
    container's item dirs are root-owned; None if the record is missing); before that, root/rollouts/<run>/items/<arm>/<task>
    with the run id in the path."""
    out = []
    race = r / "race" / "items"
    for res in sorted(race.rglob("task_results.jsonl")) if race.is_dir() else []:
        try:
            rid = json.loads(_record(r, res.parent).read_text()).get("run_id")
        except (OSError, ValueError):
            rid = None
        out.append((res.parent.name, rid, res.parent))
    old = r / "rollouts"
    for res in sorted(old.rglob("task_results.jsonl")) if old.is_dir() else []:
        parts = res.parent.relative_to(old).parts
        out.append((res.parent.name, "/".join(parts[:parts.index("items")]) if "items" in parts else None, res.parent))
    return out


def _rollouts_by_task(r: Path) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for task, _, p in _rollouts(r):
        out.setdefault(task, []).append(p)
    return out


def check_sweep(d: Path, expected: dict | None = None) -> tuple[bool, str]:
    """Task-level completeness against the pre-registered list: every expected task (or, after a BudgetStop, every task its
    record lists as finished) has a summary, at least min_rollouts rollouts each with a result AND a trace, and a judged
    row; plus the improver transcripts and the library."""
    exp = expected or EXPECTED[EXPECTED["sweeps"].get(d.name, "pilot")]
    r = d / "root"
    stops = sorted((r / "adapt").rglob("_sweeps/budget-stop-*.json"))
    tasks = list(exp["tasks"])
    note = ""
    if stops:
        finished = set(json.loads(stops[-1].read_text()).get("finished_task_summaries", []))
        tasks = [t for t in tasks if t in finished]
        note = f"; BUDGET STOP after {len(tasks)} of {len(exp['tasks'])} tasks"
    summaries = {p.parent.name for p in (r / "adapt").glob("*/*/summary.json")}
    roll = _rollouts_by_task(r)
    judged = []
    for j in (r / "adapt").rglob("judged.json"):
        try:
            judged += [row.get("task_id") for row in json.loads(j.read_text())]
        except (ValueError, AttributeError):
            pass
    problems = []
    for t in tasks:
        if t not in summaries:
            problems.append(f"{t}: no summary")
        runs = roll.get(t, [])
        if len(runs) < exp["min_rollouts_per_task"]:
            problems.append(f"{t}: {len(runs)} rollouts < {exp['min_rollouts_per_task']}")
        untraced = [x for x in runs if not list((x / "traces").glob("trace_*.json"))]
        if untraced:
            problems.append(f"{t}: {len(untraced)} rollouts without a trace")
        unrecorded = [x for x in runs if "race" in x.relative_to(r).parts[:1] and not _record(r, x).is_file()]
        if unrecorded:
            problems.append(f"{t}: {len(unrecorded)} rollouts without a staged record")
        if t not in judged:
            problems.append(f"{t}: no judged row")
    if not tasks:
        problems.append("no task to verify")
    audit = files_under(r / "adapt" / "_audit") if (r / "adapt" / "_audit").is_dir() else []
    if not audit:
        problems.append("no improver-session transcripts (adapt/_audit)")
    carried = [p.parent.name for p in (r / "adapt").glob("*/*/summary.json")
               if any((sel or {}).get("ok") and (sel or {}).get("experience")
                      for sel in (_load_json(p).get("selections") or {}).values())]
    if not (r / "library").is_dir():
        if carried:
            problems.append(f"no library/ although {len(carried)} selection(s) carried an experience ({carried[:3]})")
        else:
            note += "; no library/ (no selection carried an experience, so harness2 wrote none)"
    if not list((r / "adapt").rglob("base_judged.json")):
        problems.append("no base_judged.json")
    lib = list((r / "library").rglob("harnesses/*/harness")) if (r / "library").is_dir() else []
    ok = not problems
    head = (f"{len(tasks)} tasks checked, {sum(len(roll.get(t, [])) for t in tasks)} rollouts, {len(audit)} session files, "
            f"{len(lib)} adopted harnesses{note}")
    return ok, head if ok else head + "; " + "; ".join(problems[:6]) + ("..." if len(problems) > 6 else "")


def check_transfer(d: Path, expected: dict | None = None) -> tuple[bool, str]:
    """Every required label (both base runs) and every candidate that was evaluated has a row for each of the 12 tasks,
    each row's rollout is in the archive with a result and a trace, and each non-base candidate has its frozen tree."""
    exp = expected or EXPECTED["transfer"]
    evals = {p.stem.removeprefix("eval_"): p for p in d.rglob("eval_*.json")}
    problems = [f"missing eval_{lbl}.json" for lbl in exp["required_labels"] if lbl not in evals]
    roll = _rollouts(d / "root")
    for lbl, p in sorted(evals.items()):
        rows = {row["task"]: row for row in json.loads(p.read_text()).get("rows", [])}
        for t in exp["tasks"]:
            if t not in rows:
                problems.append(f"{lbl}: no row for {t}")
                continue
            mine = [x for task, rid, x in roll if task == t and rid == f"eval-{lbl}-{t}"]
            if not mine:
                problems.append(f"{lbl}/{t}: rollout not in the archive")
            elif not list((mine[0] / "traces").glob("trace_*.json")):
                problems.append(f"{lbl}/{t}: no trace")
        if not lbl.startswith("base") and not any(d.rglob(f"frozen/{lbl}/systemprompt.md")):
            problems.append(f"{lbl}: no frozen tree")
    ok = not problems
    head = f"labels {sorted(evals)} x {len(exp['tasks'])} tasks"
    return ok, head if ok else head + "; " + "; ".join(problems[:6]) + ("..." if len(problems) > 6 else "")


def check_secrets(d: Path) -> tuple[bool, str]:
    hits = [str(p.relative_to(d)) for p in files_under(d) if b"sk-or-" in p.read_bytes()]
    return not hits, "no key material" if not hits else f"KEY MATERIAL in {len(hits)} file(s): {hits[:5]}"


def git(*args) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True).stdout.strip()


def check_prereg(d: Path, heading: str) -> tuple[bool, str]:
    pre = git("log", "--reverse", "--format=%H", "-S", heading, "--", "docs/GAPS_2026-10-06.md").splitlines()
    res = git("log", "--reverse", "--diff-filter=A", "--format=%H", "--", str(d.relative_to(ROOT))).splitlines()
    if not pre:
        return False, f"no commit adds a GAPS section containing {heading!r}"
    if not res:
        return False, f"no commit adds {d.relative_to(ROOT)} yet"
    anc = subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", pre[0], res[0]]).returncode == 0
    return anc, f"pre-registration {pre[0][:8]} {'is' if anc else 'is NOT'} an ancestor of the first result commit {res[0][:8]}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("archive", type=Path)
    ap.add_argument("--kind", choices=("sweep", "transfer", "evidence"), default=None,
                    help="evidence = failed or smoke roots kept for the record: manifest and secrets only")
    ap.add_argument("--prereg", default=None, help="text of the GAPS heading this archive is read against")
    a = ap.parse_args(argv)
    d = a.archive.resolve()
    kind = a.kind or ("transfer" if d.name.endswith("transfer") else "sweep")
    if kind == "evidence":
        checks = [("manifest", check_manifest), ("secrets", check_secrets)]
    else:
        checks = [("manifest", check_manifest), ("env", check_env), ("proxy", check_proxy),
                  (kind, check_sweep if kind == "sweep" else check_transfer), ("secrets", check_secrets)]
    failed = 0
    for name, fn in checks:
        ok, msg = fn(d)
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'} {name:9s} {msg}")
    if a.prereg:
        ok, msg = check_prereg(d, a.prereg)
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'} {'prereg':9s} {msg}")
    print(f"{d.name}: {'VERIFIED' if not failed else f'{failed} check(s) FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
