"""rich_3718 under v13's lever 1: the two edits p4_b1024 said it would make at 85 s ("change partial_border_style to
border_style in both places"), written through v13's own edit template on the base snapshot, then the hidden tests; and the
title-only variant (what p4 and p4_v7c submitted) for contrast. Also shows what the template does with an old block copied
without its indentation (the title line is a substring of the subtitle line). Setup as in ev_modtests.py.

    .venv/bin/python scripts/forty_two/rich_solve/ev_l1_3718.py $WT $VENV/bin/python"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ev_jsonesc import fill, sh, template  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
TID = "rich_3718"
TITLE = "            title_text.stylize_before(partial_border_style)\n"
SUBTITLE = "            subtitle_text.stylize_before(partial_border_style)\n"


def main():
    wt, py = Path(sys.argv[1]) / TID, sys.argv[2]
    rows = [json.loads(l) for l in open(ROOT / "data/tasks.jsonl") if l.strip()]
    tp = [t for t in rows if t["instance_id"] == TID][0]["test_patch"]
    cases = [
        ("title and subtitle (p4_b1024's stated plan)", [(TITLE, TITLE.replace("partial_border_style", "border_style")),
                                                        (SUBTITLE, SUBTITLE.replace("partial_border_style", "border_style"))]),
        ("title only (what p4 and p4_v7c submitted)", [(TITLE, TITLE.replace("partial_border_style", "border_style"))]),
        ("title, old block without indentation", [(TITLE.lstrip(), TITLE.lstrip().replace("partial_border_style",
                                                                                          "border_style"))]),
    ]
    for label, edits in cases:
        sh("git checkout -q -- . && git clean -fdq", wt)
        outs = []
        ok = True
        for old, new in edits:
            r = sh(fill(template(), "rich/panel.py", old, new), wt, py)
            outs.append(r.stdout.strip() or r.stderr.strip().splitlines()[-1])
            ok = ok and r.returncode == 0
        res = "; ".join(outs)
        if ok:
            (wt / "_tp.diff").write_text(tp if tp.endswith("\n") else tp + "\n")
            assert sh("git apply _tp.diff && rm _tp.diff", wt).returncode == 0
            t = sh(f"PYTHONPATH=. {py} -m pytest -q -p no:cacheprovider tests/test_panel.py", wt)
            res += " | tests/test_panel.py with the hidden tests: " + t.stdout.strip().splitlines()[-1]
        print(f"{label}: {res}")
        sh("git checkout -q -- . && git clean -fdq", wt)


if __name__ == "__main__":
    main()
