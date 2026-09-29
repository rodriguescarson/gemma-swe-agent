# ESTIMATE: sensitivity of PATH_TO_020.md's odds table to the corrections in its "Addendum: critique".
# Same engine as odds.py (same seed, same run-noise SD); only the inputs named below change.
# Run: python3 research/path020/odds_critique.py > research/path020/odds_critique.out
import numpy as np

M = 400_000
SIG_RUN = 0.033 * 58  # gap_6 sect. 6 run-noise SD on 58 tasks, as in odds.py


def run(label, *, temp_mu=0.3, temp_sd=0.8, rob_mu=0.4, rob_sd=0.4, p_lora=0.6, rel_overlap=1.0, seed=20261202):
    rng = np.random.default_rng(seed)
    lever = lambda mu, sd: rng.normal(mu, sd, M)
    base = 7.2
    v101 = lever(0.5, 0.6)
    speed = lever(0.35, 0.25)
    robust = lever(rob_mu, rob_sd)
    temp = np.maximum(lever(temp_mu, temp_sd), 0) * 0.8
    fixq = lever(0.6, 0.6)
    # rel_overlap < 1: the four reliability levers harvest the same union of sometimes-solved tasks (hidden.md 3.5),
    # so their sum is shrunk; fix quality and distillation are left additive.
    nodist = base + rel_overlap * (v101 + speed + robust + temp) + fixq
    works = rng.random(M) < p_lora * 0.75 * 0.65
    dgain = np.exp(rng.normal(np.log(1.6), 0.45, M)) * 0.7
    withd = nodist + np.where(works, dgain, 0)
    out = []
    for name, mu in (("no distill", nodist), ("distill pursued", withd)):
        reads3 = mu[:, None] + rng.normal(0, SIG_RUN, (M, 3))
        reads20 = mu[:, None] + rng.normal(0, SIG_RUN, (M, 20))
        out.append(
            f"{name}: mean {mu.mean():.2f}, p10-p90 {np.percentile(mu,10):.1f}-{np.percentile(mu,90):.1f}, P(true>=11.6) {(mu >= 11.6).mean():.3f}, "
            f"P(mean3>=11.5) {(reads3.mean(1) >= 11.5).mean():.3f}, "
            f"P(best20>=12) {(np.floor(reads20.max(1) + 0.5) >= 12).mean():.3f}"
        )
    print(f"[{label}] P(distill works) {works.mean():.3f}\n  " + "\n  ".join(out))


run("A. odds.py inputs (reproduces odds.out)")
run("B. temperature prior centred on the measured null (sweep1, 47 tasks, p>0.45): N(0, 0.5)", temp_mu=0.0, temp_sd=0.5)
run("C. B + robustness without T2 (0 of 605 gold patches add a root module): N(0.3, 0.35)",
    temp_mu=0.0, temp_sd=0.5, rob_mu=0.3, rob_sd=0.35)
run("D. C + P(LoRA applied on scorer) 0.6 -> 0.45 after the 09-29 re-test", temp_mu=0.0, temp_sd=0.5, rob_mu=0.3,
    rob_sd=0.35, p_lora=0.45)
run("E. D + reliability levers 20% sub-additive (shared union)", temp_mu=0.0, temp_sd=0.5, rob_mu=0.3, rob_sd=0.35,
    p_lora=0.45, rel_overlap=0.8)
