"""Print `--pair capture=results` arguments for every non-empty (capture_s<k>.jsonl, s<k>/task_results.jsonl) of every
pass under the collect dir, all samples (coverage.sh's first stitch paired s1 only). tests/test_collect_pairs.py."""
import argparse, glob, os, re, sys


def pairs(collect_dir):
    out = []
    for cap in sorted(glob.glob(os.path.join(collect_dir, "*", "capture_s*.jsonl"))):
        m = re.search(r"capture_s(\d+)\.jsonl$", cap)
        res = os.path.join(os.path.dirname(cap), f"s{m.group(1)}", "task_results.jsonl")
        if os.path.getsize(cap) > 0 and os.path.exists(res) and os.path.getsize(res) > 0:
            out.append(f"{cap}={res}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--collect-dir", default="eval/collect")
    a = ap.parse_args(argv)
    print(" ".join(f"--pair {p}" for p in pairs(a.collect_dir)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
