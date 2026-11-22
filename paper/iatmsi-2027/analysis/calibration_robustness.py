#!/usr/bin/env python3
"""Robustness of the local-versus-hidden rank correlation in paper 23 (rigor sweep items X3, X10, X11, X22).

Reads ONLY the paper's own committed tables (../draft-emse/source/tables/a6000.tex and l4.tex), so it needs no
external data and runs in about a minute on a laptop CPU:

    python3 analysis/calibration_robustness.py          # from the paper folder 23-local-screen-coding-agent/

Writes results/calibration_robustness.json, results/calibration_robustness.md and results/robust_macros.tex
(the macros that main.tex uses, so no value in the text is typed by hand).

The unit is the CONFIGURATION (n = 7 on the paced A6000, n = 4 on Kaggle's L4s). For a configuration run or submitted
more than once, the point is the mean of its local solves and the mean of its hidden scores, the same aggregation as
paper/arxiv/make_figures.py in the competition repository (which prints rho = +0.49, p = 0.32 for the A6000 group;
this script checks that it reproduces both before doing anything else).

Everything here is exploratory: the correlation was assembled after the hidden scores were known (claim C1 in the
repository's claim log is 'observed', i.e. post hoc).
"""
from __future__ import annotations

import itertools
import json
import re
import statistics as st
import sys
from pathlib import Path

import numpy as np
from scipy.stats import kendalltau, rankdata, spearmanr

HERE = Path(__file__).resolve().parent
TABLES = HERE.parent / "draft-emse" / "source" / "tables"
if not TABLES.exists():  # public repository layout: copies of the two tables sit next to this script
    TABLES = HERE / "tables"
OUT = HERE / "results"
SEED = 20261030
N_BOOT = 20000
N_SIM = 20000
HIDDEN_TASKS = 60          # used only by the hidden-draw simulation (an approximation). The host counts 58 public hidden
                           # tasks, and denominator_check() shows the printed scores are k/58 truncated to two decimals


def parse(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        if "&" not in line or line.startswith("configuration"):
            continue
        cells = [c.strip().rstrip("\\").strip() for c in line.split("&")]
        if len(cells) != 3:
            continue
        name, local, hidden = cells
        if not re.match(r"^[\d, ]+$", local):
            continue
        if not re.match(r"^[\d., ]+$", hidden):
            rows.append({"name": name, "local": [int(x) for x in local.split(",")], "hidden": None, "why": hidden})
            continue
        rows.append({"name": name, "local": [int(x) for x in local.split(",")],
                     "hidden": [float(x) for x in hidden.split(",")]})
    return rows


def points(rows: list[dict]) -> tuple[list[str], np.ndarray, np.ndarray]:
    use = [r for r in rows if r["hidden"] is not None]
    return ([r["name"] for r in use],
            np.array([st.mean(r["local"]) for r in use], float),
            np.array([st.mean(r["hidden"]) for r in use], float))


def rho(x, y) -> float:
    if len(set(x)) < 2 or len(set(y)) < 2:
        return float("nan")
    return float(np.corrcoef(rankdata(x), rankdata(y))[0, 1])


def tau_b(x, y) -> float:
    if len(set(x)) < 2 or len(set(y)) < 2:
        return float("nan")
    return float(kendalltau(x, y).statistic)


def exact_perm_p(x, y, stat) -> float:
    """Two-sided exact permutation p over all orderings of y (n <= 8)."""
    obs = abs(stat(x, y))
    n = 0
    hit = 0
    for p in itertools.permutations(y):
        n += 1
        hit += abs(stat(x, list(p))) >= obs - 1e-12
    return hit / n


def mc_perm_p(x, y, stat, rng, n=50000) -> float:
    obs = abs(stat(x, y))
    y = np.asarray(y)
    hit = sum(abs(stat(x, rng.permutation(y))) >= obs - 1e-12 for _ in range(n))
    return (hit + 1) / (n + 1)


def boot_ci(x, y, rng, stat=rho) -> dict:
    n = len(x)
    vals, dropped = [], 0
    for _ in range(N_BOOT):
        i = rng.integers(0, n, n)
        v = stat(x[i], y[i])
        if np.isnan(v):
            dropped += 1
        else:
            vals.append(v)
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return {"lo": float(lo), "hi": float(hi), "dropped_constant_resamples": dropped, "n_boot": N_BOOT}


def fisher_ci(r: float, n: int) -> dict:
    # Fisher z interval; for Spearman the usual 1.06 variance inflation (Fieller et al.) is applied. Rough at n = 7.
    z = np.arctanh(r)
    se = np.sqrt(1.06 / (n - 3))
    return {"lo": float(np.tanh(z - 1.96 * se)), "hi": float(np.tanh(z + 1.96 * se))}


def critical_rho(n: int, alpha: float = 0.05) -> float:
    """Smallest |rho| with exact two-sided permutation p <= alpha for n untied observations."""
    x = list(range(n))
    vals = np.array([abs(rho(x, list(p))) for p in itertools.permutations(x)])
    ok = [v for v in sorted(set(np.round(vals, 10))) if (vals >= v - 1e-9).mean() <= alpha]
    return float(min(ok)) if ok else 1.0


def power_curve(n: int, crit: float, rng) -> list[tuple[float, float]]:
    """Power of the exact Spearman test for a bivariate-normal population with Pearson r."""
    out = []
    for r in np.arange(0.30, 0.96, 0.05):
        cov = [[1, r], [r, 1]]
        hit = 0
        for _ in range(N_SIM // 4):
            xy = rng.multivariate_normal([0, 0], cov, n)
            hit += abs(rho(xy[:, 0], xy[:, 1])) >= crit - 1e-12
        out.append((float(round(r, 2)), hit / (N_SIM // 4)))
    return out


def hidden_draw_noise(x, y, rng) -> dict:
    """Re-draw each hidden score as Binomial(HIDDEN_TASKS, observed k/HIDDEN_TASKS) / HIDDEN_TASKS (local fixed)."""
    k = np.round(y * HIDDEN_TASKS)
    p = k / HIDDEN_TASKS
    vals = []
    for _ in range(N_SIM):
        d = rng.binomial(HIDDEN_TASKS, p) / HIDDEN_TASKS
        v = rho(x, d)
        if not np.isnan(v):
            vals.append(v)
    vals = np.array(vals)
    crit = critical_rho(len(x))
    return {"median": float(np.median(vals)), "q025": float(np.percentile(vals, 2.5)),
            "q975": float(np.percentile(vals, 97.5)), "share_at_or_above_critical": float((vals >= crit - 1e-12).mean()),
            "critical_rho": crit}


def denominator_check(scores: list[float]) -> dict:
    """Which denominators n reproduce every printed score. Two printing rules are tested: rounding to two decimals,
    and truncation (floor(100 k / n) / 100), which is how the competition prints scores. Integer arithmetic avoids
    float error in the truncation test."""
    cents = [round(s * 100) for s in scores]
    fit_round = {n: all(any(round(k / n, 2) == s for k in range(n + 1)) for s in scores) for n in range(55, 64)}
    fit_trunc = {n: all(any((100 * k) // n == c for k in range(n + 1)) for c in cents) for n in range(55, 64)}
    return {"scores_checked": sorted(set(scores)),
            "rounding_denominators_55_to_63": [n for n, ok in fit_round.items() if ok],
            "truncation_denominators_55_to_63": [n for n, ok in fit_trunc.items() if ok],
            "n58_consistent": fit_trunc[58], "n60_consistent": fit_trunc[60],
            "n58_consistent_if_rounded": fit_round[58], "n60_consistent_if_rounded": fit_round[60]}


def summarise(label: str, x, y, rng, exact: bool) -> dict:
    r = rho(x, y)
    t = tau_b(x, y)
    res = {"n_configurations": int(len(x)), "rho": r, "kendall_tau_b": t}
    if exact:
        res["rho_p_exact_permutation"] = exact_perm_p(x, y, rho)
        res["tau_p_exact_permutation"] = exact_perm_p(x, y, tau_b)
    else:
        res["rho_p_monte_carlo_permutation"] = mc_perm_p(x, y, rho, rng)
        res["tau_p_monte_carlo_permutation"] = mc_perm_p(x, y, tau_b, rng)
    res["rho_bootstrap_ci95"] = boot_ci(x, y, rng)
    res["rho_fisher_ci95"] = fisher_ci(r, len(x))
    return res


def main() -> int:
    rng = np.random.default_rng(SEED)
    a_rows = parse(TABLES / "a6000.tex")
    l_rows = parse(TABLES / "l4.tex")
    an, ax, ay = points(a_rows)
    ln, lx, ly = points(l_rows)
    res: dict = {"seed": SEED, "source_tables": ["draft-emse/source/tables/a6000.tex", "draft-emse/source/tables/l4.tex"],
                 "a6000_configurations": an, "l4_configurations": ln,
                 "excluded_from_correlation": [r for r in a_rows + l_rows if r["hidden"] is None]}

    # 1. reproduce the paper's published numbers before anything else
    a = summarise("a6000", ax, ay, rng, exact=True)
    if abs(a["rho"] - 0.49) > 0.005 or abs(a["rho_p_exact_permutation"] - 0.32) > 0.005 or len(ax) != 7:
        print("DOES NOT REPRODUCE the paper's rho +0.49 / p 0.32 over seven configurations:", a, file=sys.stderr)
        return 1
    res["a6000"] = a
    res["l4"] = summarise("l4", lx, ly, rng, exact=True)

    # 2. leave-one-out (and the headline without the single most or least favourable configuration)
    loo = []
    for i, name in enumerate(an):
        m = np.arange(len(ax)) != i
        loo.append({"dropped": name, "rho": rho(ax[m], ay[m]), "kendall_tau_b": tau_b(ax[m], ay[m])})
    res["a6000_leave_one_out"] = loo
    rs = [d["rho"] for d in loo]
    res["a6000_leave_one_out_range"] = {"min": min(rs), "max": max(rs),
                                        "min_when_dropping": loo[int(np.argmin(rs))]["dropped"],
                                        "max_when_dropping": loo[int(np.argmax(rs))]["dropped"]}
    loo4 = []
    for i, name in enumerate(ln):
        m = np.arange(len(lx)) != i
        loo4.append({"dropped": name, "rho": rho(lx[m], ly[m])})
    res["l4_leave_one_out"] = loo4

    # 3. both hardware setups pooled (the baseline appears in both, as two rows of one bundle)
    px, py = np.concatenate([ax, lx]), np.concatenate([ay, ly])
    res["pooled_l4_and_a6000"] = summarise("pooled", px, py, rng, exact=False)
    res["pooled_note"] = ("11 rows, 10 distinct bundles: the baseline v12 contributes one row on each hardware setup, "
                          "so the rows are not fully independent.")

    # 4. each run as its own row on the A6000 (instead of per-configuration means): same data, more rows, not independent
    rows_x, rows_y = [], []
    for r in a_rows:
        if r["hidden"] is None:
            continue
        for i, loc in enumerate(r["local"]):
            rows_x.append(loc)
            rows_y.append(r["hidden"][i] if i < len(r["hidden"]) else st.mean(r["hidden"]))
    res["a6000_run_level_rows"] = {"n_rows": len(rows_x), "rho": rho(np.array(rows_x, float), np.array(rows_y, float)),
                                   "note": "rows from one configuration are not independent; shown only to see whether "
                                           "the sign depends on aggregation (a second run is paired with the matching hidden read by order)"}

    # 5. power / minimum detectable correlation at n = 7 and n = 4
    crit7, crit4 = critical_rho(7), critical_rho(4)
    pc = power_curve(7, crit7, rng)
    mdr = next((r for r, p in pc if p >= 0.80), None)
    res["power"] = {"n7_critical_abs_rho_exact_two_sided_0.05": crit7, "n4_critical_abs_rho": crit4,
                    "n7_power_by_true_pearson_r": pc, "n7_smallest_true_r_with_power_0.80": mdr,
                    "note": "bivariate-normal population, Spearman test at the exact n=7 critical value; at n=4 no |rho| "
                            "reaches p<=0.05 two-sided (the smallest attainable exact p is 2/24 = 0.083)"}

    # 6. hidden-draw noise at fixed local solves
    res["hidden_draw_noise_a6000"] = hidden_draw_noise(ax, ay, rng)

    # 7. denominators of the hidden public scores
    scores = [h for r in a_rows + l_rows if r["hidden"] for h in r["hidden"]]
    res["hidden_denominator_check"] = denominator_check(scores)

    OUT.mkdir(exist_ok=True)
    (OUT / "calibration_robustness.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    write_md(res)
    write_macros(res)
    print((OUT / "calibration_robustness.md").read_text())
    return 0


def f2(v: float) -> str:
    return f"{v:+.2f}".replace("+0.00", "0.00")


def write_md(r: dict) -> None:
    a, l, p = r["a6000"], r["l4"], r["pooled_l4_and_a6000"]
    lo = r["a6000_leave_one_out_range"]
    d = r["hidden_denominator_check"]
    pw = r["power"]
    lines = [
        "# Calibration robustness (generated by analysis/calibration_robustness.py; do not edit)",
        "",
        f"Seed {r['seed']}, {N_BOOT} bootstrap resamples, {N_SIM} simulations. Exploratory: the correlation was assembled after the hidden scores were known.",
        "",
        "| set | n configs | Spearman rho | exact/MC permutation p | 95% bootstrap CI (configs) | 95% Fisher CI (rough) | Kendall tau-b (p) |",
        "|---|---|---|---|---|---|---|",
        f"| paced A6000 | {a['n_configurations']} | {a['rho']:+.2f} | {a['rho_p_exact_permutation']:.2f} | "
        f"{a['rho_bootstrap_ci95']['lo']:+.2f} to {a['rho_bootstrap_ci95']['hi']:+.2f} | "
        f"{a['rho_fisher_ci95']['lo']:+.2f} to {a['rho_fisher_ci95']['hi']:+.2f} | {a['kendall_tau_b']:+.2f} ({a['tau_p_exact_permutation']:.2f}) |",
        f"| Kaggle 4xL4 | {l['n_configurations']} | {l['rho']:+.2f} | {l['rho_p_exact_permutation']:.2f} | "
        f"{l['rho_bootstrap_ci95']['lo']:+.2f} to {l['rho_bootstrap_ci95']['hi']:+.2f} | "
        f"{l['rho_fisher_ci95']['lo']:+.2f} to {l['rho_fisher_ci95']['hi']:+.2f} | {l['kendall_tau_b']:+.2f} ({l['tau_p_exact_permutation']:.2f}) |",
        f"| pooled (11 rows) | {p['n_configurations']} | {p['rho']:+.2f} | {p['rho_p_monte_carlo_permutation']:.3f} | "
        f"{p['rho_bootstrap_ci95']['lo']:+.2f} to {p['rho_bootstrap_ci95']['hi']:+.2f} | "
        f"{p['rho_fisher_ci95']['lo']:+.2f} to {p['rho_fisher_ci95']['hi']:+.2f} | {p['kendall_tau_b']:+.2f} ({p['tau_p_monte_carlo_permutation']:.3f}) |",
        "",
        "## Leave one out (A6000)",
        "",
        "| dropped | rho | tau-b |", "|---|---|---|",
    ]
    lines += [f"| {x['dropped']} | {x['rho']:+.2f} | {x['kendall_tau_b']:+.2f} |" for x in r["a6000_leave_one_out"]]
    lines += ["", f"Range {lo['min']:+.2f} (dropping {lo['min_when_dropping']}) to {lo['max']:+.2f} (dropping {lo['max_when_dropping']}).",
              "", "## Power at n = 7",
              "", f"Exact two-sided 0.05 critical |rho| = {pw['n7_critical_abs_rho_exact_two_sided_0.05']:.3f}; smallest true (Pearson) r with power 0.80 "
              f"in a bivariate-normal population = {pw['n7_smallest_true_r_with_power_0.80']}. n = 4: {pw['note']}",
              "", "| true r | power |", "|---|---|"]
    lines += [f"| {rr} | {pp:.2f} |" for rr, pp in pw["n7_power_by_true_pearson_r"]]
    h = r["hidden_draw_noise_a6000"]
    lines += ["", "## Hidden-draw noise (local solves fixed, each hidden score re-drawn as Binomial(60, k/60))", "",
              f"Median rho {h['median']:+.2f}, 95% range {h['q025']:+.2f} to {h['q975']:+.2f}; share of draws at or above the n=7 critical value: {h['share_at_or_above_critical']:.2f}.",
              "", "## Hidden-score denominators", "",
              f"Scores checked: {d['scores_checked']}. Denominators 55 to 63 for which every score equals floor(100 k / n) / 100 "
              f"(truncation, how the competition prints scores) for an integer k: {d['truncation_denominators_55_to_63']}; "
              f"if scores were rounded instead: {d['rounding_denominators_55_to_63']}. "
              f"Truncated: n = 58 consistent: {d['n58_consistent']}; n = 60 consistent: {d['n60_consistent']}. "
              "The hidden-draw simulation above uses Binomial(60), an approximation to the host's 58.",
              "", f"Run-level rows on the A6000 ({r['a6000_run_level_rows']['n_rows']} rows): rho {r['a6000_run_level_rows']['rho']:+.2f}.", ""]
    (OUT / "calibration_robustness.md").write_text("\n".join(lines))


def write_macros(r: dict) -> None:
    a, l, p = r["a6000"], r["l4"], r["pooled_l4_and_a6000"]
    lo = r["a6000_leave_one_out_range"]
    pw = r["power"]
    h = r["hidden_draw_noise_a6000"]

    def s(v: float, nd: int = 2) -> str:
        t = f"{abs(v):.{nd}f}"
        return ("\\textminus{}" if v < -0.0049 else "") + t

    M = {
        "rhoA": s(a["rho"]), "rhoApExact": f"{a['rho_p_exact_permutation']:.2f}",
        "rhoAciLo": s(a["rho_bootstrap_ci95"]["lo"]), "rhoAciHi": s(a["rho_bootstrap_ci95"]["hi"]),
        "tauA": s(a["kendall_tau_b"]), "tauApExact": f"{a['tau_p_exact_permutation']:.2f}",
        "rhoL": s(l["rho"]), "tauL": s(l["kendall_tau_b"]),
        "rhoLciLo": s(l["rho_bootstrap_ci95"]["lo"]), "rhoLciHi": s(l["rho_bootstrap_ci95"]["hi"]),
        "rhoLpExact": f"{l['rho_p_exact_permutation']:.2f}",
        "rhoPool": s(p["rho"]), "rhoPoolP": f"{p['rho_p_monte_carlo_permutation']:.2f}",
        "rhoPoolciLo": s(p["rho_bootstrap_ci95"]["lo"]), "rhoPoolciHi": s(p["rho_bootstrap_ci95"]["hi"]),
        "looMin": s(lo["min"]), "looMax": s(lo["max"]),
        "looMinDrop": lo["min_when_dropping"], "looMaxDrop": lo["max_when_dropping"],
        "critRhoSeven": f"{pw['n7_critical_abs_rho_exact_two_sided_0.05']:.2f}",
        "mdrSeven": f"{pw['n7_smallest_true_r_with_power_0.80']:.2f}",
        "powerAtObserved": f"{dict((round(k, 2), v) for k, v in pw['n7_power_by_true_pearson_r']).get(0.5, float('nan')):.2f}",
        "noiseShare": f"{h['share_at_or_above_critical']:.2f}",
        "noiseLo": s(h["q025"]), "noiseHi": s(h["q975"]),
    }
    lines = ["% generated by analysis/calibration_robustness.py; do not edit"]
    lines += [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in M.items()]
    (OUT / "robust_macros.tex").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
