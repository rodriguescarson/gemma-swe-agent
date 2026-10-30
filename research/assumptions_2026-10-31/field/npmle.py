"""Empirical-Bayes (NPMLE) fit of the board.

Each team i has N_i submissions; the board shows K_i = max of its scored draws (checked on our own row:
board 0.17 = our best, last submission 0.13).  Model: a team's draws are iid, k ~ per-draw pmf(mu_i, sigma); mu_i ~ G.
We fit G on a grid of mu by EM, optionally capped at mu <= cap, and compare log-likelihoods to ask how high the
config means must go to explain the board, then simulate boards to check the top counts.
"""
import csv, math, sys, collections, json
import numpy as np
from scipy.stats import norm

LB = sys.argv[1]
rows = list(csv.DictReader(open(LB, encoding='utf-8-sig')))


def kof(s):
    s = round(float(s), 2)
    for k in range(59):
        if math.floor(100 * k / 58) / 100 == s:
            return k


N = np.array([int(r['SubmissionCount']) for r in rows])
K = np.array([kof(r['Score']) for r in rows])
G = np.arange(0, 15.01, 0.25)          # mu grid (tasks of 58)
ks = np.arange(0, 59)


def pmf(mu, sigma, shape='normal'):
    """per-draw pmf over k=0..58 for mean mu."""
    if shape == 'normal':
        cdf = norm.cdf((ks + 0.5 - mu) / sigma)
        p = np.diff(np.concatenate([[0.0], cdf]))
        p[-1] += 1 - cdf[-1]
        p[0] = norm.cdf((0.5 - mu) / sigma)
        return p / p.sum()
    raise ValueError


def cdf_table(sigma, shape='normal'):
    P = np.array([pmf(m, sigma, shape) for m in G])      # (g, k)
    return np.cumsum(P, axis=1)                          # F_g(k)


def loglik_matrix(sigma, fail, shape='normal'):
    F = cdf_table(sigma, shape)                          # (g,k)
    Neff = np.maximum(1.0, N * (1 - fail))
    # P(max = K) = F(K)^n - F(K-1)^n
    FK = F[:, K]                                         # (g, teams)
    FKm = np.where(K[None, :] > 0, F[:, np.maximum(K - 1, 0)], 0.0)
    L = FK ** Neff[None, :] - FKm ** Neff[None, :]
    return np.maximum(L, 1e-300).T                       # (teams, g)


def em(L, cap=None, iters=3000):
    mask = np.ones(len(G), bool) if cap is None else (G <= cap + 1e-9)
    pi = np.where(mask, 1.0, 0.0)
    pi /= pi.sum()
    for _ in range(iters):
        W = L * pi[None, :]
        tot = W.sum(1, keepdims=True)
        R = W / tot
        new = R.mean(0)
        new = np.where(mask, new, 0.0)
        if np.abs(new - pi).max() < 1e-10:
            pi = new
            break
        pi = new
    ll = np.log((L * pi[None, :]).sum(1)).sum()
    return pi, ll


def simulate(pi, sigma, fail, nsim=200, shape='normal', seed=1):
    rng = np.random.default_rng(seed)
    F = cdf_table(sigma, shape)
    Neff = np.maximum(1.0, np.round(N * (1 - fail))).astype(int)
    out = []
    for s in range(nsim):
        mu_idx = rng.choice(len(G), size=len(N), p=pi)
        # draw max of Neff draws: invert F^n via uniform
        u = rng.random(len(N))
        # max cdf: F(k)^n >= u  -> smallest k with F[mu,k]**n >= u
        Fm = F[mu_idx]                                      # (teams, k)
        cm = Fm ** Neff[:, None]
        kk = (cm < u[:, None]).sum(1)
        out.append(kk)
    return np.array(out)


if __name__ == '__main__':
    obs = {t: int((K >= t).sum()) for t in (10, 11, 12, 13, 14, 15, 17)}
    print('observed teams with K>=t:', obs, 'max', K.max(), 'n teams', len(K), 'sum N', N.sum())
    res = {}
    for sigma in (1.2, 1.56, 2.0, 2.5):
        for fail in (0.0, 0.2, 0.4):
            L = loglik_matrix(sigma, fail)
            pi_free, ll_free = em(L)
            line = f'sigma={sigma} fail={fail}: free LL={ll_free:.1f}  mu_hi(99.9% mass)={G[np.searchsorted(np.cumsum(pi_free), 0.999)]:.2f}'
            caps = {}
            for cap in (8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 12.0, 13.0):
                pi_c, ll_c = em(L, cap)
                caps[cap] = ll_c - ll_free
            line += '  dLL by cap: ' + ' '.join(f'{c}:{d:.1f}' for c, d in caps.items())
            print(line)
            res[f'{sigma}_{fail}'] = {'ll_free': ll_free, 'dLL': caps, 'pi': pi_free.tolist()}
    json.dump(res, open('npmle_results.json', 'w'))
