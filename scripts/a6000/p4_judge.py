"""P4 verdict (docs/v4h/GATE.md, 'P2 addendum 4'): scripts/keep_rule.py on OUT/results.jsonl against eval/kaggle/g4-l4-v4h2g-p312, helper reachability,
cap hits, median seconds and the run's own slowdown S(1) from the proxy log; appended to GATE.md as an A6000 screen.

    python scripts/a6000/p4_judge.py [--out ~/g4/runs/p4] [--proxy-log ~/g4/runs/p4_proxy.jsonl] [--no-append]"""
import argparse, json, statistics, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT / "scripts"))
import p2_lib  # noqa: E402


def markdown(out, proxy_log=None):
    out = Path(out)
    arm = (out / "ARM").read_text().strip() if (out / "ARM").exists() else "?"
    rows = [json.loads(l) for l in (out / "results.jsonl").read_text().splitlines() if l.strip()]
    solved = sum(bool(r.get("resolved")) for r in rows)
    cap = sum("session timeout" in (r.get("err") or "") for r in rows)
    errs = sum(bool(r.get("err")) and "session timeout" not in (r.get("err") or "") and "budget" not in (r.get("err") or "") for r in rows)
    med = statistics.median(r.get("secs") or 0 for r in rows) if rows else float("nan")
    k = subprocess.run([sys.executable, str(ROOT / "scripts" / "keep_rule.py"), str(out / "results.jsonl")], capture_output=True, text=True)
    verdict = {0: "KEEP", 1: "DROP", 2: "INVALID"}.get(k.returncode, f"rc={k.returncode}")
    helper = "n/a"
    try:
        import analyze_helper_reachability as ahr
        rep = ahr.analyse(str(out))
        helper = f"{rep['tasks_with_failure']}/{rep['tasks']} tasks with a can't-open"
    except Exception as e:
        helper = f"analyzer unavailable ({e!r})"[:80]
    s1 = "n/a"
    if proxy_log and Path(proxy_log).exists():
        sd = p2_lib.slowdown([json.loads(l) for l in open(proxy_log) if l.strip()])
        s1 = f"S(1) = {sd['effective']:.2f} (raw {sd['raw']:.2f}, {sd['calls']} calls)"
    return (f"\n### P4 A6000 screen RESULT: {arm} on the public 74 ({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())})\n"
            f"**A6000 screen, never a Kaggle result:** int4 checkpoint, bf16 KV at 0.95, the bundle's own (not stretched) budgets, sequential, pace proxy; the A6000 is slower "
            f"than the L4 model, so a miss is pessimistic.\n\n"
            f"- solved {solved}/{len(rows)} (L4 reference v4h2g: 34/74); keep rule (solved >= 37 and paired wins - losses >= +3 vs eval/kaggle/g4-l4-v4h2g-p312): **{verdict}**\n"
            f"  `{k.stdout.strip()[-300:]}`\n"
            f"- helper reachability: {helper}; cap hits {cap}; errored rows {errs}; median task seconds {med:.0f}; {s1}\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(Path.home() / "g4" / "runs" / "p4")); ap.add_argument("--proxy-log", default=str(Path.home() / "g4" / "runs" / "p4_proxy.jsonl"))
    ap.add_argument("--no-append", action="store_true")
    a = ap.parse_args(argv)
    text = markdown(a.out, a.proxy_log)
    print(text)
    if not a.no_append:
        with open(ROOT / "docs" / "v4h" / "GATE.md", "a") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
