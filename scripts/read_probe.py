"""Read the G-A probe output (lora_probe.json from kernel g4-l4-lora-probe*) against docs/v11/GA_PROBE.md's rules.

    python scripts/read_probe.py eval/kaggle/<slug>/lora_probe.json [--doc docs/v11/GA_PROBE.md]
Prints GA=PASS|FAIL and KEY_STYLE=loud|loud2|none (the --key-style for train/package_adapter.py: the probe's
'plan_A' prefix is the packager's 'loud'), appends one result block to the doc (idempotent, keyed by the probe's
sha), exit 0 on PASS, 2 on FAIL. tests/test_read_probe.py.
"""
import argparse, datetime, hashlib, json, sys
from pathlib import Path

STYLE = {"plan_A": "loud", "loud2": "loud2", "none": "none"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("probe"); ap.add_argument("--doc", default="docs/v11/GA_PROBE.md")
    a = ap.parse_args(argv)
    raw = Path(a.probe).read_bytes(); r = json.loads(raw); sha = hashlib.sha256(raw).hexdigest()[:12]
    ga = r.get("GA") or r.get("GA_pre_smoke") or "FAIL"
    style = STYLE.get(r.get("prefix"), "none")
    checks = r.get("checks", {}); A = r.get("A", {})
    diffs = {n: A.get(n, {}).get("diff_vs_base") for n in ("loud", "loud2", "zb")}
    print(f"GA={ga} KEY_STYLE={style} checks={checks} P6={r.get('P6_agent_smoke')} diffs={diffs}")
    doc = Path(a.doc)
    text = doc.read_text() if doc.exists() else ""
    if f"probe sha {sha}" in text:
        print("already recorded"); return 0 if ga == "PASS" else 2
    when = datetime.datetime.now(datetime.timezone.utc).astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M IST")
    if ga == "PASS":
        block = (f"\n### Result {when}: G-A PASS (probe sha {sha})\nchecks {json.dumps(checks)}; P6 {r.get('P6_agent_smoke')}; diff_vs_base {json.dumps(diffs)}; "
                 f"prefix {r.get('prefix')} -> every adapter is packaged with `train/package_adapter.py ... --key-style {style}`.\n")
    else:
        block = (f"\n### Result {when}: G-A FAIL (probe sha {sha})\nchecks {json.dumps(checks)}; P6 {r.get('P6_agent_smoke')}; diff_vs_base {json.dumps(diffs)}; "
                 f"prefix {r.get('prefix')}. LoRA track closed until a new wheelhouse version says otherwise (rule above).\n")
    doc.write_text(text + block)
    print(f"recorded in {doc}")
    return 0 if ga == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
