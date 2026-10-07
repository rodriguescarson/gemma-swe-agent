"""Back up the run's result files into the repo and push them (so a crash loses at most one interval).

    python scripts/a6000/backup_results.py [--runs ~/g4/runs] [--loop 1200]

Copies new or changed files from ~/g4/runs/{p2,p3,p4,p4_proxy.jsonl} into eval/a6000/results/ (per-item rows, summaries, patches, test outputs, traces; the run files
and proxy logs), then commits and pushes under the same lock as the supervisor. Never copied: container logs, P3's raw capture and SFT rows (GBs; they stay on this box),
P3 traces, anything over 8 MB. Item directories are written by root inside the container but are world-readable."""
import argparse, fnmatch, os, re, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX_BYTES = 8 * 1024 * 1024
G4 = Path.home() / "g4"


def _p2_like(rel, p3):
    """rel = path below the step dir. -> keep?"""
    parts = rel.split("/")
    if parts[0] in ("items",) or (len(parts) > 1 and parts[0].startswith("probe_")):
        if "logs" in parts[:-1]:
            return False
        if "traces" in parts[:-1] and p3:
            return False
        return True
    return False


def plan(src_root, dst_root, max_bytes=MAX_BYTES):
    """[(src, dst)] of files that are new or whose size changed."""
    src_root, dst_root = Path(src_root), Path(dst_root)
    out = []

    def want(rel):
        top = rel.split("/")[0]
        name = rel.split("/")[-1]
        if re.fullmatch(r"p4(_\w+)?_proxy\.jsonl", top):
            return True
        if top == "p2":
            r = rel[3:]
            if "/" not in r:
                return name in ("items.jsonl", "probe_summary.json", "probe_gate.json", "ids.txt") or fnmatch.fnmatch(name, "proxy_*.jsonl") or fnmatch.fnmatch(name, "report_*.txt")
            return _p2_like(r, p3=False)
        if top == "p3":
            r = rel[3:]
            if "/" not in r:
                return name in ("ARM", "rebalance_report.json", "validate_report.json", "proxy.jsonl", "pairs_raw.jsonl")
            if re.fullmatch(r"s\d+/task_results\.jsonl", r):
                return True
            return _p2_like(r, p3=True)
        if re.fullmatch(r"p4(_\w+)?", top):
            r = rel[len(top) + 1:]
            if "/" not in r:
                return name in ("results.jsonl", "ARM")
            return r.startswith("results/") and not r.startswith("results/logs/")
        return False

    tops = [p.name for p in src_root.iterdir() if p.is_dir() and (p.name in ("p2", "p3") or re.fullmatch(r"p4(_\w+)?", p.name))] if src_root.exists() else []
    for top in sorted(tops):
        base = src_root / top
        for dirpath, _, files in os.walk(base):
            for f in files:
                s = Path(dirpath) / f
                rel = str(s.relative_to(src_root))
                if not want(rel):
                    continue
                try:
                    size = s.stat().st_size
                except OSError:
                    continue
                if size > max_bytes:
                    continue
                d = dst_root / rel
                if d.exists() and d.stat().st_size == size:
                    continue
                out.append((s, d))
    for s in sorted(src_root.glob("p4*_proxy.jsonl")):
        if s.stat().st_size <= max_bytes:
            d = dst_root / s.name
            if not (d.exists() and d.stat().st_size == s.stat().st_size):
                out.append((s, d))
    return out


def copy(pairs):
    for s, d in pairs:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(s, d)
    return len(pairs)


def push(n):
    dst = "eval/a6000/results"
    steps = [["git", "add", dst], ["git", "commit", "-q", "-m", f"a6000 results backup: {n} new/changed files", "-m", "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"],
             ["git", "pull", "-q", "--rebase", "--autostash", "origin", "wip/gemma-agent"], ["git", "push", "-q", "origin", "wip/gemma-agent"]]
    for c in steps:
        r = subprocess.run(["flock", str(G4 / "git.lock")] + c, cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0 and c[1] != "commit":
            print("backup git step failed:", c[:3], r.stderr[-200:], flush=True)
            if c[1] == "pull":
                subprocess.run(["git", "rebase", "--abort"], cwd=ROOT, capture_output=True)
            return False
    return True


def once(runs):
    n = copy(plan(runs, ROOT / "eval" / "a6000" / "results"))
    if n:
        ok = push(n)
        print(f"{time.strftime('%H:%M:%S')} backup: {n} files, push {'ok' if ok else 'FAILED'}", flush=True)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", default=str(G4 / "runs")); ap.add_argument("--loop", type=int, default=0)
    a = ap.parse_args(argv)
    while True:
        try:
            once(a.runs)
        except Exception as e:
            print("backup error:", repr(e)[:200], flush=True)
        if not a.loop:
            return 0
        time.sleep(a.loop)


if __name__ == "__main__":
    sys.exit(main())
