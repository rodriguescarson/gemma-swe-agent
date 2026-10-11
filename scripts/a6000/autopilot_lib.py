"""Pure rules of the autonomous P2 -> P4 -> P2 stage 1b -> P3 run (docs/v4h/GATE.md, 'P2 addendum 4'). No I/O."""

import os

HARD_STOP_H = float(os.environ.get("AUTOPILOT_HARD_STOP_H") or 36.0)   # P8 runs the supervisor with AUTOPILOT_HARD_STOP_H=24
STOP_ERR_SHARE, STOP_MIN_ITEMS, STOP_MEDIAN_S = 0.15, 10, 60.0


def health_line(ts, step, done, total, solved, empty, errors, median_s, cap, gpu_util, disk_free_gb, restarts):
    med = "n/a" if median_s is None else f"{median_s:.1f}"
    gpu = "n/a" if gpu_util is None else f"{gpu_util:.0f}%"
    return (f"- {ts} | step={step} | done={done}/{total} | solved={solved} | empty={empty} | errors={errors} | median_s={med} | cap={cap} | "
            f"gpu={gpu} | disk_free={disk_free_gb:.0f}GB | restarts={restarts}")


def deadline_utc(launch_epoch):
    return launch_epoch + HARD_STOP_H * 3600


def time_left_s(launch_epoch, now):
    return deadline_utc(launch_epoch) - now


def stop_reason(done, errors, median_s):
    """None, or why the step must stop for diagnosis: more than 15% of items errored (judged from 10 items), or median task time under 60 s."""
    if done < STOP_MIN_ITEMS:
        return None
    if errors / done > STOP_ERR_SHARE:
        return f"{errors}/{done} items errored (> {STOP_ERR_SHARE:.0%})"
    if median_s is not None and median_s < STOP_MEDIAN_S:
        return f"median task time {median_s:.0f} s < {STOP_MEDIAN_S:.0f} s"
    return None


def choose_p4_arm(contrasts):
    """contrasts: {arm: {"wins", "losses", "cap_gap"}} vs v4h2 from stage 1a. The arm whose verdict is BETTER under the P2 rule (p2_lib.verdict); both BETTER: the larger net,
    a tie goes to v6p; none BETTER: v5h2 (addendum 6)."""
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from p2_lib import verdict
    best, best_net = "v5h2", None
    for arm in ("v6p", "v6p-think"):
        c = contrasts.get(arm)
        if c is None or verdict(c["wins"], c["losses"], c.get("cap_gap", 0.0)) != "BETTER":
            continue
        net = c["wins"] - c["losses"]
        if best_net is None or net > best_net:
            best, best_net = arm, net
    return best


def choose_p3_arm(stats):
    """stats: {arm: {"solved", "valid"}}. Highest solved share among arms with >= 40 valid tasks; ties v6p-b, v6p, v6p-think, v4h2; nothing eligible: v6p (addendum 6)."""
    order = ["v6p-b", "v6p", "v6p-think", "v4h2"]
    ok = [a for a in order if a in stats and stats[a]["valid"] >= 40]
    if not ok:
        return "v6p"
    return max(ok, key=lambda a: (round(stats[a]["solved"] / stats[a]["valid"], 9), -order.index(a)))


def pool(a, b):
    """Stage 1a + 1b paired counts: simple sums; heterogeneous when the two stages' nets differ by 5 or more."""
    na, nb = a["wins"] - a["losses"], b["wins"] - b["losses"]
    return {"wins": a["wins"] + b["wins"], "losses": a["losses"] + b["losses"], "net": na + nb, "heterogeneous": abs(na - nb) >= 5}

import re
_INFRA = re.compile(r"APIError|APIConnection|Connection error|ConnectError|Connection refused|Service Unavailable|BadGateway|Bad Gateway|"
                    r"InternalServerError|Max retries exceeded|Read timed out|RemoteProtocolError|ServerDisconnected", re.I)


def is_infra_error(err):
    """An item error caused by the model server or network (re-run it), as opposed to the bundle's own behaviour or a budget end."""
    return bool(err) and bool(_INFRA.search(str(err)))


# ------------------------------------------------------------------------------------- external GPU contention (2026-10-07)
CONT_S, CONT_WINDOW_S, CONT_MIN_CALLS, CONT_MARGIN_S = 3.0, 600, 8, 900


def window_slowdown(rows, now, window_s=CONT_WINDOW_S, min_calls=CONT_MIN_CALLS):
    """Effective slowdown (sum max(latency, L4-model time) / sum L4-model time) over the pace-proxy rows of the last window_s seconds, or None with too few calls."""
    r = [x for x in rows if x.get("status") == 200 and x.get("l4_target_s") is not None and now - window_s <= x.get("t", 0) <= now]
    tgt = sum(x["l4_target_s"] for x in r)
    if len(r) < min_calls or tgt <= 0:
        return None
    return sum(max(x["latency_s"], x["l4_target_s"]) for x in r) / tgt


def contended(s):
    return s is not None and s > CONT_S


def gpu_free(samples):
    """nvidia-smi utilisation samples taken while vLLM is idle: free = median <= 20% and no sample above 60% (a mostly-busy GPU with brief zeros is busy)."""
    if not samples:
        return False
    s = sorted(samples)
    return s[len(s) // 2] <= 20 and max(samples) <= 60


def contaminated_since(detect_epoch):
    """Items finishing after this time (or still running) are re-run: the contention began before it was noticed."""
    return detect_epoch - CONT_MARGIN_S


VLLM_PATTERNS = ("vllm.entrypoints", "a6000/serve.sh", "vllm::")          # vLLM 0.19 renames its engine/workers to VLLM::EngineCore, VLLM::Worker_*


def vllm_pids(ps_text, self_pid):
    """PIDs of every vLLM process in a `ps -eo pid=,args=` listing, case-insensitive, the caller excluded; a stray
    multiprocessing.resource_tracker counts only when a vLLM process is present (it is vLLM's own, left behind with the engine).
    2026-10-11: the hard stop killed the API server and left `VLLM::EngineCore` holding 48.5 GB on the box."""
    found, trackers = [], []
    for line in ps_text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        pid, args = int(parts[0]), parts[1]
        if pid == self_pid:
            continue
        low = args.lower()
        if any(p in low for p in VLLM_PATTERNS):
            found.append(pid)
        elif "multiprocessing.resource_tracker" in low:
            trackers.append(pid)
    return sorted(found + trackers) if found else []


def gpu_mem_used_mib(text):
    """`nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits` -> MiB, or None when it did not answer. WSL reports
    memory but never lists compute apps, so this is the only truthful "is the card empty" check there."""
    m = re.match(r"\s*(\d+)", text or "")
    return int(m.group(1)) if m else None
