"""FINAL SUMMARY of the autonomous run: one table per step (stage 1a, stage 1b + pooled, P4, P3), appended to docs/v4h/GATE.md and docs/a6000/P2_LOG.md.

    python scripts/a6000/final_summary.py [--no-append]"""
import argparse, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(ROOT / "scripts"))
import p2_results_md as md  # noqa: E402

G4 = Path.home() / "g4" / "runs"


def summary_text(p2_out, p4_out, p3_out, ids=None, runs_root=None):
    ids = ids or [l.strip() for l in open(ROOT / "data" / "heldout1k" / "s200_valid_ids.txt") if l.strip()]
    parts = [f"\n## FINAL SUMMARY ({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}) - every number is an A6000 screen, never a Kaggle result\n"]
    a, b, both = ids[:50], ids[50:100], ids[:100]
    for label, sel, arms in (("stage 1a (ids 1-50)", a, md.ARMS), ("stage 1b (ids 51-100)", b, ["v4h2", "v6p", "v6p-b"]), ("pooled stage 1a + 1b (ids 1-100), arms that ran in both", both, list(md.POOLABLE))):
        if sel:
            t, _ = md.section(label, p2_out, sel, arms, "v4h2")
            parts.append(f"#### {label}\n{t}")
        else:
            parts.append(f"#### {label}\nnot run\n")
    root = Path(runs_root) if runs_root else G4
    p4_dirs = sorted(p for p in root.glob("p4*") if p.is_dir() and (p / "results.jsonl").exists()) or [Path(p4_out)]
    for d in p4_dirs:
        try:
            import p4_judge
            parts.append(p4_judge.markdown(str(d), proxy_log=str(root / f"{d.name}_proxy.jsonl")))
        except Exception:
            parts.append(f"#### P4 ({d.name})\nnot run (no results)\n")
    cap = Path(p3_out) / "capture.jsonl"
    parts.append("#### P3\n" + (f"see the P3 data report above (capture file {cap.stat().st_size / 1e6:.0f} MB)\n" if cap.exists() else "not run (no capture)\n"))
    return "\n".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--no-append", action="store_true")
    a = ap.parse_args(argv)
    text = summary_text(str(G4 / "p2"), str(G4 / "p4"), str(G4 / "p3"))
    print(text)
    if not a.no_append:
        for f in (ROOT / "docs" / "v4h" / "GATE.md", ROOT / "docs" / "a6000" / "P2_LOG.md"):
            with open(f, "a") as h:
                h.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
