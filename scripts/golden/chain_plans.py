"""L-to-F chain datasets (docs/v10/SPEC_v10_2.md E4; docs/eval/V10_2_EVAL.md section 4, steps 5-6).

    .venv/bin/python scripts/golden/chain_plans.py --l-run eval/golden/runs/L_dev_v102_c9 --sample 0 \
        --out eval/golden/datasets/F_dev_chain_v102.json [--f-dataset eval/golden/datasets/F_dev.json]

Writes an F dev EvaluationDataset whose cases are the F dev cases of the L run's tasks with:
- golden.plan = the L run's sample-N locator reply verbatim ('' when the locator gave none: a lost plan);
- golden.repro = the locator's LAST verify.py --repro-only heredoc when that call's result said "fails on original" or
  "hangs on original", else null (the scripted F locator re-runs it, so the fixer sees a real REPRO line);
- golden.plan_source = "chain:<run_id>:s<N>", golden.plan_basis = "chain";
- golden.fixture_sha recomputed over the new golden block (build_fixtures.golden_block's rule).
A task is dropped (and listed) when its sample-N case is missing or was not counted (status other than ok or
model_error: no locator ran), or when it has no F dev case. Holdout is refused: an L run made on the holdout split, and
any holdout task (eval/golden/split.json), so the chain can never read or run a holdout case.

Exit codes: 0 written; 2 refused or unreadable input. Stdlib only (plus the golden library, stdlib itself).
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(HERE), str(ROOT / "eval" / "golden")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fixture_lib as FL        # noqa: E402
import golden_metrics as GM     # noqa: E402

F_DEV = ROOT / "eval" / "golden" / "datasets" / "F_dev.json"
SPLIT = ROOT / "eval" / "golden" / "split.json"
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[^\n]*\n(.*?)\n[ \t]*\2[ \t]*(?:\n|$)", re.S)


class Refused(Exception):
    pass


def _read(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Refused(f"cannot read {p}: {e}") from None


def heredoc_body(cmd: str) -> str | None:
    """The body of the first heredoc in a shell command (None when there is none)."""
    m = HEREDOC.search(cmd or "")
    if not m:
        return None
    body = m.group(3)
    return body if body.endswith("\n") else body + "\n"


def chain_fields(case: dict) -> dict:
    """{plan, repro, repro_status, status} of one L trace case (its golden block and agent_data)."""
    inst = GM.make_instance(case)
    c = GM._ctx(inst)
    plan = GM._reply(c)
    uses = GM._repro_uses(c)
    repro, rstat = None, "no attempt"
    if uses:
        last = uses[-1]
        out = GM._stdout(last["resp"]) if last["answered"] else ""
        if GM.REPRO_HIT.search(out):
            repro, rstat = heredoc_body(last["cmd"]), "fails on original"
            if repro is None:
                rstat = "fails on original, but no heredoc in the command"
        else:
            rstat = "last attempt did not fail on original" if last["answered"] else "last attempt unanswered"
    return {"plan": plan, "repro": repro, "repro_status": rstat, "status": c["status"]}


def load_l_traces(l_run: Path) -> tuple:
    run = _read(l_run / "run.json")
    if run.get("suite") != "L":
        raise Refused(f"{l_run} is suite {run.get('suite')}, not L")
    if run.get("split") != "dev":
        raise Refused(f"{l_run} was made on split {run.get('split')}: the chain runs on dev only (holdout refused)")
    cases = {}
    for fp in sorted((l_run / "traces").glob("*.json")):
        for case in (_read(fp).get("eval_cases") or []):
            g = case.get("golden") or {}
            cases[g.get("case_id") or case.get("eval_case_id")] = case
    if not cases:
        raise Refused(f"{l_run} has no traces (run_suite.py write first)")
    return run, cases


def holdout_tasks(split_path: Path = SPLIT) -> set:
    d = _read(split_path)
    return {t for t, v in (d.get("tasks") or {}).items() if (v or {}).get("split") == "holdout"}


def build(l_run: Path, sample: int, f_dataset: Path = F_DEV, split_path: Path = SPLIT) -> tuple:
    """-> (dataset, report). Raises Refused."""
    l_run = Path(l_run)
    run, lcases = load_l_traces(l_run)
    hold = holdout_tasks(split_path)
    fds = _read(f_dataset)
    fcases = {}
    for c in fds.get("eval_cases") or []:
        g = c.get("golden") or {}
        if g.get("split") != "dev" or g.get("task") in hold:
            raise Refused(f"{f_dataset} holds a holdout case ({c.get('eval_case_id')}): pass the F dev dataset")
        if g.get("suite") != "F":
            raise Refused(f"{f_dataset} case {c.get('eval_case_id')} is suite {g.get('suite')}, not F")
        fcases[g["task"]] = c
    run_id = run.get("run_id") or l_run.name
    tasks = sorted({(c.get("golden") or {}).get("task") for c in lcases.values()} - {None})
    bad = sorted(set(tasks) & hold)
    if bad:
        raise Refused(f"the L run holds holdout tasks {bad[:5]}: refused")
    out, dropped, rows = [], {}, []
    for tid in tasks:
        cid = f"L__{tid}__s{sample}"
        lc = lcases.get(cid)
        if lc is None:
            dropped[tid] = f"no sample {sample} in the L run"
            continue
        st = (lc.get("golden") or {}).get("status")
        if st not in GM.COUNTED_STATUS:
            dropped[tid] = f"L sample {sample} status {st} (no locator ran)"
            continue
        fc = fcases.get(tid)
        if fc is None:
            dropped[tid] = "no F dev case"
            continue
        ch = chain_fields(lc)
        new = copy.deepcopy(fc)
        g = new["golden"]
        g.pop("fixture_sha", None)
        g.update(plan=ch["plan"], repro=ch["repro"], plan_source=f"chain:{run_id}:s{sample}", plan_basis="chain")
        g["fixture_sha"] = FL.sha_obj(g)
        out.append(new)
        rows.append({"task": tid, "plan_words": len(ch["plan"].split()), "lost_plan": not ch["plan"].strip(),
                     "repro": ch["repro"] is not None, "repro_status": ch["repro_status"],
                     "fixture_sha": g["fixture_sha"]})
    ds = {"eval_cases": sorted(out, key=lambda c: c["eval_case_id"])}
    report = {"l_run": str(l_run), "run_id": run_id, "sample": sample, "f_dataset": str(f_dataset),
              "cases": len(out), "dropped": dropped, "rows": rows,
              "lost_plans": sum(r["lost_plan"] for r in rows), "repros": sum(r["repro"] for r in rows)}
    return ds, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="chain_plans.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--l-run", required=True)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--f-dataset", default=str(F_DEV))
    ap.add_argument("--split-json", default=str(SPLIT), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    try:
        ds, rep = build(Path(a.l_run), a.sample, Path(a.f_dataset), Path(a.split_json))
    except Refused as e:
        print("REFUSED: %s" % e, file=sys.stderr)
        return 2
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(ds, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    rp = out.with_name(out.stem + ".report.json")
    rp.write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("chain %s s%d: %d cases (%d lost plans, %d repros carried), dropped %d%s -> %s" % (
        rep["run_id"], a.sample, rep["cases"], rep["lost_plans"], rep["repros"], len(rep["dropped"]),
        (": " + "; ".join("%s (%s)" % kv for kv in sorted(rep["dropped"].items()))) if rep["dropped"] else "", out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
