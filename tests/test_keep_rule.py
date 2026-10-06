"""scripts/keep_rule.py: the S1 keep rule (docs/GAPS_2026-10-06.md, Carson 2026-10-06), judged mechanically.

KEEP when, on one faithful L4 run of the public 74, the candidate solves >= 37 AND, paired task by task against v4h2g's
L4 run (eval/kaggle/g4-l4-v4h2g-p312/results.jsonl), wins - losses >= +3. A run that does not cover the baseline's
tasks is not a faithful run: INVALID. Exit 0 KEEP, 1 DROP, 2 INVALID. Written before the script."""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "keep_rule.py"
BASE = ROOT / "eval" / "kaggle" / "g4-l4-v4h2g-p312" / "results.jsonl"


def write(p, rows):
    p.write_text("".join(json.dumps(dict(cfg=None, id=i, resolved=r)) + "\n" for i, r in rows))
    return p


def judge(new, *extra, base=None):
    args = [sys.executable, str(SCRIPT), str(new)] + (["--base", str(base)] if base else []) + list(extra)
    r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout


def base_rows(n=74, solved=34):
    return [(f"t{i:02d}", i < solved) for i in range(n)]


def test_keep_needs_both_37_and_net_plus_3(tmp_path):
    base = write(tmp_path / "base.jsonl", base_rows())
    # 37 solved: base's 34 + 3 more, no losses -> net +3
    new = write(tmp_path / "new.jsonl", [(i, r or int(i[1:]) in (34, 35, 36)) for i, r in base_rows()])
    code, out = judge(new, base=base)
    assert code == 0 and "KEEP" in out and "solved 37/74" in out and "wins 3 losses 0 net +3" in out, out


def test_trading_tasks_counts_wins_and_losses_separately(tmp_path):
    base = write(tmp_path / "base.jsonl", base_rows())
    lost = ("t00", "t01", "t02", "t03", "t04")
    rows = [(i, (r and i not in lost) or int(i[1:]) in range(34, 42)) for i, r in base_rows()]   # 29 + 8 = 37
    code, out = judge(write(tmp_path / "new.jsonl", rows), base=base)
    assert code == 0 and "wins 8 losses 5 net +3" in out, out
    assert "lost: t00 t01 t02 t03 t04" in out                            # named, for reading the traces


def test_net_plus_3_but_under_37_is_dropped(tmp_path):
    base = write(tmp_path / "base.jsonl", base_rows(solved=30))
    new = write(tmp_path / "new.jsonl", [(i, int(i[1:]) < 36) for i, _ in base_rows()])   # 36 solved, net +6
    code, out = judge(new, base=base)
    assert code == 1 and "DROP" in out and "net +6" in out, out


def test_37_with_net_plus_2_is_dropped(tmp_path):
    base = write(tmp_path / "base.jsonl", base_rows(solved=35))
    new = write(tmp_path / "new.jsonl", [(i, int(i[1:]) < 37) for i, _ in base_rows()])   # 37 solved, net +2
    code, out = judge(new, base=base)
    assert code == 1 and "DROP" in out and "net +2" in out, out


def test_a_run_missing_tasks_is_invalid(tmp_path):
    base = write(tmp_path / "base.jsonl", base_rows())
    new = write(tmp_path / "new.jsonl", [(i, True) for i, _ in base_rows()[:70]])
    code, out = judge(new, base=base)
    assert code == 2 and "INVALID" in out and "missing 4" in out, out


def test_duplicate_rows_count_once_any_resolved_wins(tmp_path):
    base = write(tmp_path / "base.jsonl", base_rows())
    rows = [(i, r or int(i[1:]) in (34, 35, 36)) for i, r in base_rows()] + [("t34", False), ("t00", True)]
    code, out = judge(write(tmp_path / "new.jsonl", rows), base=base)
    assert code == 0 and "solved 37/74" in out, out


def test_thresholds_are_options(tmp_path):
    base = write(tmp_path / "base.jsonl", base_rows())
    new = write(tmp_path / "new.jsonl", base_rows())
    assert judge(new, "--min-solved", "34", "--min-net", "0", base=base)[0] == 0


def test_default_base_is_v4h2gs_l4_run_and_it_does_not_keep_itself():
    rows = [json.loads(l) for l in BASE.read_text().splitlines() if l.strip()]
    assert len({r["id"] for r in rows}) == 74 and sum(r["resolved"] for r in rows) == 34
    code, out = judge(BASE)
    assert code == 1 and "solved 34/74" in out and "net +0" in out, out
