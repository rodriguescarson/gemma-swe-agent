"""Markdown results of a P2 stage (arm table + paired contrasts + the pre-registered verdicts), appended to docs/v4h/GATE.md, and the choices the
autonomous run needs next (docs/v4h/GATE.md, 'P2 addendum 4').

    python scripts/a6000/p2_results_md.py OUT --label "stage 1a" --from 0 --to 50 [--pooled-from 0] [--choose p4|p3] [--no-append]

--from/--to slice data/heldout1k/s200_valid_ids.txt; --pooled-from N also prints the pooled table over ids N..to and the heterogeneity flag
(stage nets from N..from and from..to differ by >= 5); --choose p4 writes ~/g4/runs/autopilot_choice.json {"p4_arm"} (best non-reference net, else v6p);
--choose p3 writes {"p3_arm"} (most pooled solved of the three arms; ties v6p, v6p-think, v4h2)."""
import argparse, json, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
import autopilot_lib as lib  # noqa: E402
import p2_report as rep  # noqa: E402

ROOT = HERE.parents[1]
ARMS = ["v4h2", "v6p", "v6p-think"]
CHOICE = Path.home() / "g4" / "runs" / "autopilot_choice.json"


def section(label, out, ids, arms, base):
    s = rep.summarize(out, arms, ids=ids)
    lines = [f"**{label}: {len(ids)} ids, arms {', '.join(arms)}; A6000 screen (int4 checkpoint, bf16 KV at 0.95, Docker-emulated sandbox, per-arm stretched cap), "
             f"1 sample per task per arm, paired, never a Kaggle result.**", "",
             "| arm | finished | solved | Wilson 95% | empty patch | errored | cap hits | median s | loops |", "|---|---|---|---|---|---|---|---|---|"]
    for arm in arms:
        d = s[arm]
        lines.append(f"| {arm} | {d['n']} | {d['solved']} | {d['ci'][0]:.3f}-{d['ci'][1]:.3f} | {d['empty']} | {d['errors']} | {d['cap']} | "
                     f"{(d['median_s'] if d['median_s'] is not None else float('nan')):.0f} | {d['loops']} |")
    contrasts = {}
    lines += ["", "| contrast | valid pairs | wins | losses | sign p | cap gap | verdict | no-cap pairs (W/L) |", "|---|---|---|---|---|---|---|---|"]
    for arm in arms:
        if arm == base:
            continue
        c = rep.contrast(out, arm, base, ids=ids)
        contrasts[arm] = {"wins": c["wins"], "losses": c["losses"]}
        lines.append(f"| {arm} vs {base} | {c['n']} | {c['wins']} | {c['losses']} | {c['p']:.3f} | {c['cap_gap']:+.2f} | {c['verdict']} | "
                     f"{c['n_nocap']} ({c['wins_nocap']}/{c['losses_nocap']}) |")
    flags = [f"{a}: {'; '.join(d['flags'])}" for a, d in s.items() if d["flags"]]
    if flags:
        lines += ["", "Health flags: " + " | ".join(flags)]
    return "\n".join(lines) + "\n", contrasts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out"); ap.add_argument("--label", required=True)
    ap.add_argument("--from", dest="lo", type=int, default=0); ap.add_argument("--to", type=int, required=True)
    ap.add_argument("--pooled-from", type=int); ap.add_argument("--choose", choices=["p4", "p3"]); ap.add_argument("--no-append", action="store_true")
    ap.add_argument("--ids", default=str(ROOT / "data" / "heldout1k" / "s200_valid_ids.txt"))
    a = ap.parse_args(argv)
    all_ids = [l.strip() for l in open(a.ids) if l.strip()]
    ids = all_ids[a.lo:a.to]
    text, contrasts = section(a.label, a.out, ids, ARMS, "v4h2")
    body = f"\n### P2 {a.label} RESULT ({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())})\n{text}"
    if a.pooled_from is not None:
        pids = all_ids[a.pooled_from:a.to]
        ptext, pc = section(f"pooled ids {a.pooled_from + 1}-{a.to}", a.out, pids, ARMS, "v4h2")
        prev_ids = all_ids[a.pooled_from:a.lo]
        _, prev = section("previous stage", a.out, prev_ids, ARMS, "v4h2")
        het = {arm: lib.pool(prev[arm], contrasts[arm])["heterogeneous"] for arm in contrasts}
        body += f"\n#### Pooled (combination rule of addendum 4: sum of paired counts; verdict rule on the pooled counts)\n{ptext}\nHeterogeneity (stage nets differ by >= 5): {het}\n"
        contrasts_for_choice = pc
    else:
        contrasts_for_choice = contrasts
    if a.choose == "p4":
        arm = lib.choose_p4_arm(contrasts_for_choice)
        CHOICE.parent.mkdir(parents=True, exist_ok=True)
        cur = json.loads(CHOICE.read_text()) if CHOICE.exists() else {}
        cur["p4_arm"] = arm; CHOICE.write_text(json.dumps(cur))
        body += f"\nChosen arm for P4 (best non-reference net vs v4h2, else v6p): **{arm}**.\n"
    if a.choose == "p3":
        s = rep.summarize(a.out, ARMS, ids=all_ids[a.pooled_from if a.pooled_from is not None else a.lo:a.to])
        order = ["v6p", "v6p-think", "v4h2"]
        arm = max(order, key=lambda x: (s[x]["solved"], -order.index(x)))
        cur = json.loads(CHOICE.read_text()) if CHOICE.exists() else {}
        cur["p3_arm"] = arm; CHOICE.write_text(json.dumps(cur))
        body += f"\nBundle for P3 (most pooled solved of the three arms; ties v6p, v6p-think, v4h2): **{arm}** ({s[arm]['solved']} solved).\n"
    print(body)
    if not a.no_append:
        with open(ROOT / "docs" / "v4h" / "GATE.md", "a") as f:
            f.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
