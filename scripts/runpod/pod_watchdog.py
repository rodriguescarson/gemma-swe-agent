"""Self-termination for the RunPod Linux-gate pod (scripts/runpod/pod_body.py starts it before sshd).

A pod is either working or gone (owner's rule): the Mac-side chain deletes the pod when its last gate is done, and this
watchdog is the backstop when the chain dies, the Mac sleeps or the session ends. It runs as a child of the pod's PID 1,
so it has RUNPOD_POD_ID and the pod-scoped RUNPOD_API_KEY that an ssh login does not (runpodctl self-removal
failed from ssh-launched scripts on 15 Sep and 2 Nov). It terminates (not stops) the pod when:
  - the hard limit G4_POD_MAX_HOURS since start passes;
  - /root/g4m/terminate_now exists (the chain's normal teardown);
  - no run is active (/root/g4m/busy absent) and /root/g4m/heartbeat is older than G4_POD_IDLE_MIN minutes.
The shim (scripts/runpod/bin/docker) sets busy for the whole of each run and touches the heartbeat every poll.
Every attempt is logged to /root/g4m/watchdog.log without the key."""
import json
import os
import time
import urllib.request

ROOT = os.environ.get("G4_POD_ROOT", "/root/g4m")


def reason(now, start, max_hours, idle_min, busy, heartbeat_mtime, terminate_now):
    """Why the pod should go now, or None."""
    if now - start > max_hours * 3600:
        return "hard limit"
    if terminate_now:
        return "terminate_now"
    if not busy and heartbeat_mtime is not None and now - heartbeat_mtime > idle_min * 60:
        return "idle"
    return None


def attempts(pod_id):
    """REST DELETE first, then the GraphQL mutation runpodctl's remove used (the route that worked with a pod key)."""
    gql = json.dumps({"query": 'mutation { podTerminate(input: {podId: "%s"}) }' % pod_id}).encode()
    return [("DELETE", f"https://rest.runpod.io/v1/pods/{pod_id}", None),
            ("POST", "https://api.runpod.io/graphql", gql)]


def terminate(pod_id, key, log, opener=urllib.request.urlopen):
    for method, url, body in attempts(pod_id):
        req = urllib.request.Request(url, data=body, method=method,
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with opener(req, timeout=60) as r:
                log(f"{method} {url} -> {r.status}")
        except Exception as e:  # noqa: BLE001 - every failure is logged and the next route tried
            log(f"{method} {url} failed: {type(e).__name__} {getattr(e, 'code', '')}".rstrip())


def main():
    pod_id, key = os.environ.get("RUNPOD_POD_ID", ""), os.environ.get("RUNPOD_API_KEY", "")
    max_hours = float(os.environ.get("G4_POD_MAX_HOURS", "4"))
    idle_min = float(os.environ.get("G4_POD_IDLE_MIN", "40"))
    os.makedirs(ROOT, exist_ok=True)
    hb = os.path.join(ROOT, "heartbeat")
    open(hb, "a").close()

    def log(msg):
        with open(os.path.join(ROOT, "watchdog.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S UTC ", time.gmtime()) + msg + "\n")

    start = time.time()
    log(f"start: pod {pod_id or 'UNKNOWN'}, key {'present' if key else 'MISSING'}, max {max_hours} h, idle {idle_min} min")
    while True:
        now = time.time()
        try:
            hb_mtime = os.path.getmtime(hb)
        except OSError:
            hb_mtime = None
        why = reason(now, start, max_hours, idle_min, os.path.exists(os.path.join(ROOT, "busy")), hb_mtime,
                     os.path.exists(os.path.join(ROOT, "terminate_now")))
        if why:
            log(f"terminating: {why}")
            terminate(pod_id, key, log)
            time.sleep(120)            # a successful call removes the container long before this returns
            continue
        time.sleep(30)


if __name__ == "__main__":
    main()
