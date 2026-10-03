"""Merge row files (build_sft output) into one, dropping exact (prompt, completion) duplicates, first occurrence kept.

    python train/merge_rows.py part1.jsonl part2.jsonl ... --out merged.jsonl
Missing inputs are skipped with a note (frozen parts may not exist on a fresh checkout). tests/test_merge_rows.py.
"""
import argparse, hashlib, json, os, sys


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("parts", nargs="+"); ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    seen, n, dup, skipped = set(), 0, 0, []
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as out:
        for p in a.parts:
            if not os.path.exists(p):
                skipped.append(p); continue
            for l in open(p):
                if not l.strip():
                    continue
                r = json.loads(l)
                h = hashlib.sha1((str(r.get("prompt")) + "\x00" + str(r.get("completion"))).encode("utf-8", "replace")).hexdigest()
                if h in seen:
                    dup += 1; continue
                seen.add(h); out.write(json.dumps(r) + "\n"); n += 1
    print(f"{n} rows written to {a.out}, {dup} duplicates dropped" + (f", skipped missing: {' '.join(skipped)}" if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
