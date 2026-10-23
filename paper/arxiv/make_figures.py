"""Figures and summary statistics for the arXiv paper, regenerated from saved results only.

    python3 paper/arxiv/make_figures.py        # needs matplotlib (the system python3 has it)

Writes paper/arxiv/figures/{calibration,deadline,timesplit}.pdf and prints the rank-correlation statistics quoted in the
text. Inputs: eval/a6000/results/p4_*/results.jsonl (local 74-task runs), eval/kaggle/g4-l4-*/results.jsonl (Kaggle 4xL4
runs), the hidden scores listed in HIDDEN below (each with its Kaggle submission ref, checkable against
eval/analysis/out/kaggle_submissions_2026-10-21.json), and eval/analysis/out/time_split_2026-10-18.txt."""
from __future__ import annotations

import itertools
import json
import re
import statistics as st
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "figures"
SNAP = ROOT / "eval" / "analysis" / "out" / "kaggle_submissions_2026-10-21.json"
INK, SPOT, MUTE = "#1f2a33", "#0f8b8d", "#8a96a0"

# configuration -> (local runs, Kaggle refs of its hidden public reads); local runs are 74-task reads on the paced A6000
A6000 = {
    "thinking-only variant": (["p4_v0t2"], ["57191163"]),
    "baseline": (["p4_v12", "p4_v12r"], ["57070001", "57390142"]),
    "thinking budget 1,024": (["p4_b1024"], ["57154639"]),
    "baseline + public sampling": (["p4_v12b"], ["57362143"]),
    "public sampling + heredoc edits, 60 s commands": (["p4_v15b"], ["57427316"]),
    "baseline + two prompt rules": (["p4_v13", "p4_v13r"], ["57231531"]),
    "public sampling + 6-minute cap": (["p4_v12b6"], ["57470240"]),
}
TIMED_OUT = {"public 0.24 notebook": (["p4_pub024"], ["57280385", "57304025"])}
# the same question on Kaggle's own 4xL4 notebooks (no pacing proxy)
L4 = {
    "staged agent": (["g4-l4-v4-wh28-p312"], ["56824301"]),
    "+ edit helper": (["g4-l4-v4h2-p312"], ["56788077", "56864298"]),
    "+ recovery step": (["g4-l4-v4h2g-p312"], ["56837573"]),
    "baseline (on L4)": (["g4-l4-v12-p312"], ["57070001"]),
}


def load(run: str) -> dict[str, dict]:
    p = ROOT / "eval" / "a6000" / "results" / run / "results.jsonl"
    if not p.is_file():
        p = ROOT / "eval" / "kaggle" / run / "results.jsonl"
    rows = {}
    for line in p.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["id"]] = r
    assert len(rows) == 74, (run, len(rows))
    return rows


def scores() -> dict[str, str]:
    subs = json.loads(SNAP.read_text())["submissions"]
    return {s["ref"]: s["public_score"] for s in subs}


def solved(run: str) -> int:
    return sum(bool(r["resolved"]) for r in load(run).values())


def spearman(xs, ys) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


def perm_p(xs, ys) -> float:
    """Exact two-sided permutation p-value of Spearman's rho (all orderings of ys)."""
    obs = abs(spearman(xs, ys))
    perms = list(itertools.permutations(ys))
    return sum(abs(spearman(xs, list(p))) >= obs - 1e-12 for p in perms) / len(perms)


def points(group: dict) -> list[tuple[str, list[int], list[float]]]:
    sc = scores()
    out = []
    for name, (runs, refs) in group.items():
        local = [solved(r) for r in runs]
        hidden = [float(sc[r]) for r in refs if sc.get(r)]
        out.append((name, local, hidden))
    return out


def fig_calibration() -> None:
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    for pts, marker, face, label in ((points(L4), "s", "white", "Kaggle 4xL4 screen"),
                                     (points(A6000), "o", INK, "paced A6000 screen")):
        seen: dict[tuple, int] = {}
        for i, (name, local, hidden) in enumerate(pts):
            x, y = st.mean(local), st.mean(hidden)
            k = seen[(x, y)] = seen.get((x, y), -1) + 1   # identical points are nudged apart so both stay visible
            x += 0.18 * k
            xerr = [[x - min(local)], [max(local) - x]] if len(local) > 1 else None
            yerr = [[y - min(hidden)], [max(hidden) - y]] if len(hidden) > 1 else None
            ax.errorbar(x, y, xerr=xerr, yerr=yerr, fmt=marker, ms=7, mfc=face, mec=INK if face == INK else MUTE,
                        mew=1.6, ecolor=MUTE, elinewidth=1, capsize=2, label=label if i == 0 else None, zorder=3)
    tie = [st.mean(h) for _, l, h in points(A6000) if l == [28]]
    tx = [28 + 0.18 * sum(1 for t in tie[:i] if t == y) for i, y in enumerate(tie)]
    ax.scatter(tx, tie, s=170, facecolors="none", edgecolors=SPOT, linewidths=1.8, zorder=4)
    ax.annotate("three single runs at 28 locally:\nhidden 0.10, 0.10 and 0.17", xy=(28.3, 0.165), xytext=(29.2, 0.175),
                fontsize=8.5, color=SPOT)
    ax.set_xlabel("local solves (of 74 public tasks)")
    ax.set_ylabel("hidden public score")
    ax.set_xlim(23.5, 35.5)
    ax.set_ylim(0.03, 0.19)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=8.5, loc="lower right")
    fig.tight_layout()
    fig.savefig(OUT / "calibration.pdf")
    plt.close(fig)


def kept(run: str, cap: int, d: int) -> int:
    return sum(bool(r["resolved"]) and (r["secs"] < d - 5 or d == cap) for r in load(run).values())


def fig_deadline() -> None:
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    series = [("p4_v12", 300, "baseline, 5-min cap", INK, "-"),
              ("p4_v12b6", 360, "baseline + sampling, 6-min cap", SPOT, "-"),
              ("p4_pub024", 480, "public 0.24 notebook, 8-min cap", MUTE, "--"),
              ("p4_v12c", 480, "public prompt on our tools, 8-min cap", MUTE, ":")]
    for run, cap, label, color, ls in series:
        ds = list(range(120, cap + 1, 10))
        if ds[-1] != cap:
            ds.append(cap)
        ax.plot(ds, [kept(run, cap, d) for d in ds], ls, color=color, lw=1.8, label=label)
    ax.axvline(300, color=MUTE, lw=0.8, alpha=0.6)
    ax.set_xlabel("cutoff D (seconds); a solve counts only if its run ended before D")
    ax.set_ylabel("solves kept (of 74)")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT / "deadline.pdf")
    plt.close(fig)


def fig_timesplit() -> None:
    rows = []
    for line in (ROOT / "eval" / "analysis" / "out" / "time_split_2026-10-18.txt").read_text().splitlines():
        m = re.match(r"== (\S+) \(cap (\d+) s\): .*model calls (\d+)% of wall time", line)
        if m:
            rows.append((m.group(1).removeprefix("p4_"), int(m.group(2)), int(m.group(3))))
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    names = [f"{n} ({c} s cap)" for n, c, _ in rows]
    ax.barh(names, [p for _, _, p in rows], color=INK, height=0.6, label="model generation")
    ax.barh(names, [100 - p for _, _, p in rows], left=[p for _, _, p in rows], color=MUTE, height=0.6,
            label="tools, sandbox and harness")
    ax.set_xlim(0, 100)
    ax.set_xlabel("share of each task's wall time (%), ten local runs")
    ax.invert_yaxis()
    ax.tick_params(axis="y", labelsize=8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2)
    fig.tight_layout()
    fig.savefig(OUT / "timesplit.pdf")
    plt.close(fig)
    print(f"time split: model share {min(p for *_, p in rows)}-{max(p for *_, p in rows)}% over {len(rows)} runs")


def stats() -> None:
    for name, group in (("A6000", A6000), ("L4", L4)):
        pts = points(group)
        xs, ys = [st.mean(l) for _, l, _ in pts], [st.mean(h) for _, _, h in pts]
        print(f"{name}: n={len(pts)} configurations, Spearman rho={spearman(xs, ys):+.2f}, exact permutation p={perm_p(xs, ys):.2f}")
        for (n, l, h) in pts:
            print(f"   {n:34s} local {l} hidden {h}")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig_calibration()
    fig_deadline()
    fig_timesplit()
    stats()
    print(f"figures written to {OUT}")
