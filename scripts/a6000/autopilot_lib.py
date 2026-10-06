"""Pure rules of the autonomous P2 -> P4 -> P2 stage 1b -> P3 run (docs/v4h/GATE.md, 'P2 addendum 4'). No I/O."""

HARD_STOP_H = 36.0
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
    """contrasts: {arm: {"wins", "losses"}} vs v4h2 from stage 1a. The best non-reference arm = the larger net (wins - losses) if it is > 0;
    otherwise v6p (the planned first L4 run); a tie goes to v6p."""
    best, best_net = "v6p", 0
    for arm in ("v6p", "v6p-think"):
        c = contrasts.get(arm)
        if c is None:
            continue
        net = c["wins"] - c["losses"]
        if net > best_net or (net == best_net and net > 0 and arm == "v6p"):
            best, best_net = arm, net
    return best


def pool(a, b):
    """Stage 1a + 1b paired counts: simple sums; heterogeneous when the two stages' nets differ by 5 or more."""
    na, nb = a["wins"] - a["losses"], b["wins"] - b["losses"]
    return {"wins": a["wins"] + b["wins"], "losses": a["losses"] + b["losses"], "net": na + nb, "heterogeneous": abs(na - nb) >= 5}

import re
_INFRA = re.compile(r"APIConnection|Connection error|ConnectError|Connection refused|Service Unavailable|BadGateway|Bad Gateway|"
                    r"InternalServerError|Max retries exceeded|Read timed out|RemoteProtocolError|ServerDisconnected", re.I)


def is_infra_error(err):
    """An item error caused by the model server or network (re-run it), as opposed to the bundle's own behaviour or a budget end."""
    return bool(err) and bool(_INFRA.search(str(err)))
