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
ARMS = ["v4h2", "v6p", "v6p-think"]           # stage 1a (stage 1b: v4h2 v6p v6p-b, addendum 6)
POOLABLE = ("v4h2", "v6p")                      # arms that ran in both stages; v6p-think is stage 1a only, v6p-b stage 1b only
CHOICE = Path.home() / "g4" / "runs" / "autopilot_choice.json"


def section(label, out, ids, arms, base, exclude=None):
    s = rep.summarize(out, arms, ids=ids, exclude=exclude)
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
        c = rep.contrast(out, arm, base, ids=ids, exclude=exclude)
        contrasts[arm] = {"wins": c["wins"], "losses": c["losses"], "cap_gap": c["cap_gap"]}
        lines.append(f"| {arm} vs {base} | {c['n']} | {c['wins']} | {c['losses']} | {c['p']:.3f} | {c['cap_gap']:+.2f} | {c['verdict']} | "
                     f"{c['n_nocap']} ({c['wins_nocap']}/{c['losses_nocap']}) |")
    flags = [f"{a}: {'; '.join(d['flags'])}" for a, d in s.items() if d["flags"]]
    if flags:
        lines += ["", "Health flags: " + " | ".join(flags)]
    return "\n".join(lines) + "\n", contrasts


def load_contended(path):
    try:
        d = json.loads(Path(path).read_text())
        return {tuple(x) for x in d["items"]}, d.get("why", "")
    except (FileNotFoundError, ValueError, KeyError):
        return set(), ""


def both_tables(label, out, ids, arms, base, contended_path):
    """The stage table over all items and, when a contended-items file lists any of this stage's items, again without them."""
    text, _ = section(label, out, ids, arms, base)
    ex, why = load_contended(contended_path)
    ex = {(a, t) for a, t in ex if t in set(ids)}
    body = f"##### all items\n{text}"
    if ex:
        t2, _ = section(label + " without contended items", out, ids, arms, base, exclude=ex)
        body += f"\n##### without contended items ({', '.join(f'{a}/{t}' for a, t in sorted(ex))}; {why})\n{t2}"
    return body


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out"); ap.add_argument("--label", required=True)
    ap.add_argument("--from", dest="lo", type=int, default=0); ap.add_argument("--to", type=int, required=True)
    ap.add_argument("--arms", nargs="+", default=ARMS)
    ap.add_argument("--pooled-from", type=int); ap.add_argument("--choose", choices=["p4", "p3"]); ap.add_argument("--no-append", action="store_true")
    ap.add_argument("--ids", default=str(ROOT / "data" / "heldout1k" / "s200_valid_ids.txt"))
    ap.add_argument("--contended", default=str(ROOT / "docs" / "a6000" / "contended_items.json"))
    a = ap.parse_args(argv)
    all_ids = [l.strip() for l in open(a.ids) if l.strip()]
    ids = all_ids[a.lo:a.to]
    text, contrasts = section(a.label, a.out, ids, a.arms, "v4h2")
    body = f"\n### P2 {a.label} RESULT ({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())})\n{both_tables(a.label, a.out, ids, a.arms, 'v4h2', a.contended)}"
    if a.pooled_from is not None:
        pooled_arms = [x for x in a.arms if x in POOLABLE]          # an arm that did not run in both stages is never pooled (addendum 6)
        pids = all_ids[a.pooled_from:a.to]
        _, pc = section(f"pooled ids {a.pooled_from + 1}-{a.to}", a.out, pids, pooled_arms, "v4h2")
        ptext = both_tables(f"pooled ids {a.pooled_from + 1}-{a.to}", a.out, pids, pooled_arms, "v4h2", a.contended)
        prev_ids = all_ids[a.pooled_from:a.lo]
        _, prev = section("previous stage", a.out, prev_ids, pooled_arms, "v4h2")
        het = {arm: lib.pool(prev[arm], contrasts[arm])["heterogeneous"] for arm in pc}
        body += f"\n#### Pooled stage 1a + 1b for the arms that ran in both (combination rule of addendum 4: sum of paired counts; verdict rule on the pooled counts)\n{ptext}\nHeterogeneity (stage nets differ by >= 5): {het}\n"
    if a.choose == "p4":
        arm = lib.choose_p4_arm(contrasts)
        CHOICE.parent.mkdir(parents=True, exist_ok=True)
        cur = json.loads(CHOICE.read_text()) if CHOICE.exists() else {}
        cur["p4_arm"] = arm; CHOICE.write_text(json.dumps(cur))
        body += f"\nChosen arm for P4 (addendum 6: the arm that is BETTER than v4h2 under the P2 rule, the larger net if both, else v5h2): **{arm}**.\n"
    if a.choose == "p3":
        stats = {}
        for x in ("v4h2", "v6p", "v6p-think", "v6p-b"):
            rows = rep.load_rows(a.out, x)
            valid = [r for r in rows.values() if "infra" not in rep.classify(r)]
            stats[x] = {"solved": sum(bool(r.get("resolved")) for r in valid), "valid": len(valid)}
        arm = lib.choose_p3_arm(stats)
        cur = json.loads(CHOICE.read_text()) if CHOICE.exists() else {}
        cur["p3_arm"] = arm; CHOICE.write_text(json.dumps(cur))
        body += f"\nBundle for P3 (addendum 6: highest solved share among arms with >= 40 valid tasks; ties v6p-b, v6p, v6p-think, v4h2): **{arm}**; shares {json.dumps(stats)}.\n"
    print(body)
    if not a.no_append:
        with open(ROOT / "docs" / "v4h" / "GATE.md", "a") as f:
            f.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
