"""Verify a Harness² archive the box pushed (paper/EVIDENCE.md D1-D5; the archive rule is channel M-046), so that "the results
are saved" is a checked fact, not an instruction that was sent.

    python eval/analysis/verify_h2_archive.py eval/a6000/results/h2_argon [--kind sweep|transfer] [--prereg "HEADING TEXT"]

Checks (each prints PASS/FAIL; exit 1 if any FAIL):
  manifest   MANIFEST.sha256 lists every file and every hash matches
  env        env.txt names the harness2 pin (1cfe254) and holds a pip freeze
  proxy      proxy.jsonl has per-call rows (t, latency_s)
  sweep      root/adapt (summaries), root/adapt/_audit (improver sessions), root/library, root/rollouts (results + traces in
             equal numbers), judged.json and base_judged.json
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


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def files_under(d: Path) -> list[Path]:
    return sorted(p for p in d.rglob("*") if p.is_file())


def check_manifest(d: Path) -> tuple[bool, str]:
    m = d / "MANIFEST.sha256"
    if not m.is_file():
        return False, "MANIFEST.sha256 missing"
    listed = {}
    for line in m.read_text().splitlines():
        if line.strip():
            h, rel = line.split(None, 1)
            listed[rel.strip().lstrip("*").removeprefix("./")] = h
    present = {str(p.relative_to(d)) for p in files_under(d)} - {"MANIFEST.sha256"}
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


def check_sweep(d: Path) -> tuple[bool, str]:
    r = d / "root"
    summaries = list((r / "adapt").glob("*/*/summary.json"))
    audit = files_under(r / "adapt" / "_audit") if (r / "adapt" / "_audit").is_dir() else []
    lib = list((r / "library").rglob("harnesses/*/harness")) if (r / "library").is_dir() else []
    results = list((r / "rollouts").rglob("task_results.jsonl"))
    traces = list((r / "rollouts").rglob("traces/trace_*.json"))
    judged = list((r / "adapt").rglob("judged.json")) and list((r / "adapt").rglob("base_judged.json"))
    ok = bool(summaries) and bool(audit) and (r / "library").is_dir() and bool(results) and len(traces) == len(results) and bool(judged)
    return ok, (f"{len(summaries)} task summaries, {len(audit)} improver-session files, {len(lib)} adopted harnesses, "
                f"{len(results)} rollouts with {len(traces)} traces, judged files {'present' if judged else 'MISSING'}")


def check_transfer(d: Path) -> tuple[bool, str]:
    evals = {p.stem.removeprefix("eval_"): p for p in d.rglob("eval_*.json")}
    need = {"base_a", "base_b"}
    frozen_missing = sorted(lbl for lbl in evals if not lbl.startswith("base") and not any(d.rglob(f"frozen/{lbl}/systemprompt.md")))
    ok = need <= set(evals) and not frozen_missing
    return ok, f"evals {sorted(evals)}; base runs present: {need <= set(evals)}; frozen trees missing for {frozen_missing}"


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
    ap.add_argument("--kind", choices=("sweep", "transfer"), default=None)
    ap.add_argument("--prereg", default=None, help="text of the GAPS heading this archive is read against")
    a = ap.parse_args(argv)
    d = a.archive.resolve()
    kind = a.kind or ("transfer" if d.name.endswith("transfer") else "sweep")
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
