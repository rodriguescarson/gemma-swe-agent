"""Supervisor of the autonomous A6000 run (docs/v4h/GATE.md, 'P2 addendum 4'). Detached, resumable, self-repairing.

    python scripts/a6000/autopilot.py [--plan ~/g4/runs/autopilot_plan.json] [--state ~/g4/runs/autopilot_state.json]

plan.json: {"steps": [{"name", "cmd": [argv...], "cwd", "env": {}, "proxy": {"listen", "host", "log"} | null, "stats": {"type": "p2"|"results_jsonl", ...},
            "total": N, "docker": bool, "purge": [argv...] | null, "post": [[argv...], ...]}]}   (re-read at every step start)
Hard stop = first step start + 36 h. Health line every 60 min in docs/a6000/P2_LOG.md (pushed). Exit codes: 0 finished, 3 blocked (stop rule), 4 hard stop."""
import argparse, importlib, json, os, shutil, signal, subprocess, sys, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import autopilot_lib as lib  # noqa: E402

LOG = Path(os.environ.get("AUTOPILOT_LOG") or ROOT / "docs" / "a6000" / "P2_LOG.md")
NO_PUSH = bool(os.environ.get("AUTOPILOT_NO_PUSH"))   # tests
G4 = Path.home() / "g4"
PY = str(G4 / "venv" / "bin" / "python")
ENV = dict(os.environ, PATH="/usr/bin:" + ":".join(p for p in os.environ.get("PATH", "").split(":") if not p.startswith("/mnt/")))
TICK, STOP_CHECK_S, HEALTH_S = int(os.environ.get("AUTOPILOT_TICK") or 30), 300, int(os.environ.get("AUTOPILOT_HEALTH_S") or 3600)
IDLE_S = int(os.environ.get("AUTOPILOT_IDLE_S") or 60)
SKIP_SERVICES = bool(os.environ.get("AUTOPILOT_SKIP_SERVICES"))   # tests: never touch dockerd / vLLM
CONT_CHECK_S = int(os.environ.get("AUTOPILOT_CONT_CHECK_S") or 120)      # how often a running step's slowdown is looked at
FREE_POLL_S = int(os.environ.get("AUTOPILOT_FREE_POLL_S") or 30)         # pause between two "is the GPU free" checks while waiting
FREE_SAMPLES = int(os.environ.get("AUTOPILOT_FREE_SAMPLES") or 6)        # nvidia-smi utilisation samples per check, SAMPLE_GAP_S apart
SAMPLE_GAP_S = 5
CONFIRM_WAIT_S = int(os.environ.get("AUTOPILOT_CONFIRM_WAIT_S") or 20)   # after stopping the step, let vLLM drain before sampling
FAKE_UTIL = os.environ.get("AUTOPILOT_FAKE_GPU_UTIL")                    # tests: a file of space-separated utilisation numbers


def now_iso(t=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t if t else time.time()))


def sh(argv, **kw):
    return subprocess.run(argv, env=ENV, capture_output=True, text=True, **kw)


def log_line(text, push=True):
    with open(LOG, "a") as f:
        f.write(text.rstrip("\n") + "\n")
    print(text, flush=True)
    if push:
        git_push("P2_LOG: " + text[:60].lstrip("- "))


def git_push(msg):
    if NO_PUSH:
        return True
    cmds = [["git", "add", "docs/a6000/P2_LOG.md", "docs/v4h/GATE.md"], ["git", "commit", "-q", "-m", msg, "-m", "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"],
            ["git", "pull", "-q", "--rebase", "--autostash", "origin", "wip/gemma-agent"], ["git", "push", "-q", "origin", "wip/gemma-agent"]]
    for c in cmds:
        r = sh(["flock", str(G4 / "git.lock")] + c, cwd=ROOT)
        if r.returncode != 0 and c[1] != "commit":
            print("git step failed:", c[:3], r.stderr[-200:], flush=True)
            if c[1] == "pull":
                sh(["git", "rebase", "--abort"], cwd=ROOT)
            return False
    return True


# -------------------------------------------------------------------------------------------------- services
def docker_ok():
    return sh(["/usr/bin/docker", "info"]).returncode == 0


def ensure_docker():
    if docker_ok():
        return True
    subprocess.Popen(["sudo", "-n", "nohup", "dockerd", "--host=unix:///var/run/docker.sock"], env=ENV, stdout=open(G4 / "dockerd.log", "a"),
                     stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(40):
        time.sleep(3)
        if docker_ok():
            sh(["sudo", "-n", "chmod", "666", "/var/run/docker.sock"])
            return True
    return False


def vllm_ok():
    try:
        return urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=8).status == 200
    except Exception:
        return False


def kill_vllm():
    for pat in ("vllm.entrypoints", "a6000/serve.sh"):
        r = sh(["pgrep", "-f", pat])
        for pid in r.stdout.split():
            if int(pid) != os.getpid():
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
    time.sleep(8)


def ensure_vllm():
    if vllm_ok():
        return True
    kill_vllm()
    subprocess.Popen(["bash", str(HERE / "serve.sh")], env=dict(ENV, GPU_UTIL="0.95"), stdout=open(G4 / "serve.log", "w"), stderr=subprocess.STDOUT,
                     start_new_session=True)
    for _ in range(150):
        time.sleep(5)
        if vllm_ok():
            return True
    return False


def proxy_up(spec):
    try:
        return urllib.request.urlopen(f"http://{spec['host']}:{spec['listen']}/v1/models", timeout=4).status == 200
    except Exception:
        return False


def start_proxy(spec, st=None):
    if not spec:
        return None
    if proxy_up(spec) and st and st.get("proxy_pid"):
        return Adopted(st["proxy_pid"])                 # left by an earlier supervisor
    Path(spec["log"]).parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen([PY, str(HERE / "pace_proxy.py"), "--listen", str(spec["listen"]), "--host", spec["host"], "--rewrite-model", "--log", spec["log"]],
                         env=ENV, stdout=open(spec["log"] + ".out", "a"), stderr=subprocess.STDOUT, start_new_session=True)
    time.sleep(3)
    if st is not None:
        st["proxy_pid"] = p.pid
    return p


class Adopted:
    """A step process started by an earlier supervisor (its own session): poll() is None while the pid lives; the return code is unknown."""
    returncode = None

    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        try:
            os.kill(self.pid, 0)
            return None
        except ProcessLookupError:
            return 0
        except PermissionError:
            return None

    def wait(self, timeout=None):
        t0 = time.time()
        while self.poll() is None and (timeout is None or time.time() - t0 < timeout):
            time.sleep(1)


def kill_group(p):
    if p and p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGTERM)
            p.wait(timeout=20)
        except Exception:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except Exception:
                pass


def gpu_util():
    r = sh(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"])
    try:
        return float(r.stdout.split()[0])
    except Exception:
        return None


def disk_free_gb():
    st = os.statvfs(str(G4))
    return st.f_bavail * st.f_frsize / 1e9


def gpu_samples():
    """Utilisation samples of the whole GPU (every process on it, including ones outside WSL). Taken while vLLM is idle they measure someone else's load."""
    if FAKE_UTIL:
        return [float(x) for x in Path(FAKE_UTIL).read_text().split()]
    out = []
    for _ in range(FREE_SAMPLES):
        u = gpu_util()
        if u is not None:
            out.append(u)
        time.sleep(SAMPLE_GAP_S)
    return out


def wait_gpu_free(st, name):
    """Block until two consecutive checks find the GPU free (vLLM idle); False when the hard stop arrives first. Logs every 10 minutes."""
    consecutive, last_log, t0 = 0, 0.0, time.time()
    while True:
        if lib.time_left_s(st["launch_epoch"], time.time()) <= 0:
            return False
        samples = gpu_samples()
        consecutive = consecutive + 1 if lib.gpu_free(samples) else 0
        if consecutive >= 2:
            return True
        if time.time() - last_log >= 600:
            last_log = time.time()
            log_line(f"- {now_iso()} | step={name} | EVENT waiting for a free GPU ({(time.time() - t0) / 60:.0f} min so far; utilisation samples {samples})", push=False)
        time.sleep(FREE_POLL_S)


def read_rows(path, tail=4000):
    try:
        with open(path) as f:
            lines = f.readlines()[-tail:]
    except OSError:
        return []
    rows = []
    for l in lines:
        try:
            rows.append(json.loads(l))
        except ValueError:
            pass
    return rows


def stats_for(step):
    try:
        mod = importlib.reload(importlib.import_module("autopilot_stats"))
        return mod.collect(step["stats"])
    except Exception as e:                      # a collector bug must never take the supervisor down
        print("stats error:", repr(e)[:200], flush=True)
        return dict(done=0, solved=0, empty=0, errors=0, cap=0, median_s=None, durations=[])


# -------------------------------------------------------------------------------------------------- the loop
def run_step(step, st, state_path):
    name = step["name"]
    restarts = st["restarts"].get(name, 0)
    reruns_after_infra = 0
    suppress_until = 0.0
    while True:
        left = lib.time_left_s(st["launch_epoch"], time.time())
        if left <= 0:
            return "hardstop"
        if not SKIP_SERVICES and not ensure_docker() and step.get("docker"):
            log_line(f"- {now_iso()} | step={name} | EVENT dockerd would not start"); return "failed"
        if not SKIP_SERVICES and not ensure_vllm():
            log_line(f"- {now_iso()} | step={name} | EVENT vLLM would not start"); return "failed"
        if (FAKE_UTIL or not SKIP_SERVICES) and not (st.get("child_step") == name and st.get("child") and Adopted(st["child"]).poll() is None):
            samples = gpu_samples()
            if not lib.gpu_free(samples):
                log_line(f"- {now_iso()} | step={name} | EVENT GPU busy at step start (another workload is using it; utilisation samples {samples}); waiting for it to be free", push=False)
                if not wait_gpu_free(st, name):
                    return "hardstop"
                log_line(f"- {now_iso()} | step={name} | EVENT GPU free again; starting", push=False)
        proxy = start_proxy(step.get("proxy"), st)
        adopt = st.get("child") if st.get("child_step") == name else None
        if adopt and Adopted(adopt).poll() is None:
            child = Adopted(adopt)
            log_line(f"- {now_iso()} | step={name} | EVENT adopted running pid {adopt}", push=False)
        else:
            child = subprocess.Popen(step["cmd"], cwd=step.get("cwd") or str(ROOT), env=dict(ENV, **step.get("env", {})), stdout=open(G4 / f"step_{name}.log", "a"),
                                     stderr=subprocess.STDOUT, start_new_session=True)
            log_line(f"- {now_iso()} | step={name} | EVENT started pid {child.pid} (restarts so far {restarts}; hard stop in {left / 3600:.1f} h)", push=False)
        st["child"], st["child_step"] = child.pid, name
        json.dump(st, open(state_path, "w"))
        t_stop = t_health = t_cont = time.time()
        problem = None
        while child.poll() is None:
            time.sleep(TICK)
            if lib.time_left_s(st["launch_epoch"], time.time()) <= 0:
                kill_group(child); kill_group(proxy); return "hardstop"
            if not SKIP_SERVICES and not vllm_ok():
                problem = "vLLM unhealthy"; break
            if not SKIP_SERVICES and step.get("docker") and not docker_ok():
                problem = "dockerd unhealthy"; break
            if proxy is not None and proxy.poll() is not None:
                problem = "pace proxy died"; break
            if time.time() - t_stop >= STOP_CHECK_S:
                t_stop = time.time()
                s = stats_for(step)
                why = lib.stop_reason(s["done"], s["errors"], s["median_s"])
                if why:
                    kill_group(child); kill_group(proxy)
                    log_line(f"- {now_iso()} | step={name} | BLOCKED {why}")
                    return "blocked"
            if step.get("speed_log") and time.time() - t_cont >= CONT_CHECK_S and time.time() >= suppress_until:
                t_cont = time.time()
                slow = lib.window_slowdown(read_rows(step["speed_log"]), time.time())
                if lib.contended(slow):
                    detect = time.time()
                    kill_group(child); kill_group(proxy)                  # stop my own load: the utilisation that remains is someone else's
                    time.sleep(CONFIRM_WAIT_S)
                    samples = gpu_samples()
                    if not lib.gpu_free(samples):
                        log_line(f"- {now_iso()} | step={name} | EVENT EXTERNAL GPU CONTENTION: the step's per-call slowdown over the last 10 min is S={slow:.1f} and nvidia-smi shows the GPU busy "
                                 f"with vLLM idle (samples {samples}); step paused, items finished since {time.strftime('%H:%M', time.gmtime(lib.contaminated_since(detect)))} UTC are re-run")
                        if step.get("purge_since"):
                            r = sh(step["purge_since"] + [str(lib.contaminated_since(detect))], cwd=ROOT)
                            log_line(f"- {now_iso()} | step={name} | EVENT contaminated items purged: {r.stdout.strip()[-60:]}", push=False)
                        if not wait_gpu_free(st, name):
                            return "hardstop"
                        log_line(f"- {now_iso()} | step={name} | EVENT GPU free again; resuming (the purged items are queued again)")
                        problem = "contention"
                    else:
                        suppress_until = time.time() + 1800
                        log_line(f"- {now_iso()} | step={name} | EVENT high slowdown (S={slow:.1f}) but the GPU is idle with vLLM idle (samples {samples}): false alarm, nothing purged, "
                                 f"contention check suppressed for 30 min", push=False)
                        problem = "false alarm"
                    break
            if time.time() - t_health >= HEALTH_S:
                t_health = time.time()
                s = stats_for(step)
                log_line(lib.health_line(now_iso(), name, s["done"], step["total"], s["solved"], s["empty"], s["errors"], s["median_s"], s["cap"], gpu_util(),
                                         disk_free_gb(), st["restarts"].get("vllm", 0) + st["restarts"].get("docker", 0)))
        if problem in ("contention", "false alarm"):
            continue                                               # the step was stopped above; no restart is counted, the queue resumes
        if problem:
            kill_group(child); kill_group(proxy)
            restarts += 1; st["restarts"][name] = restarts; json.dump(st, open(state_path, "w"))
            log_line(f"- {now_iso()} | step={name} | EVENT {problem}; restart {restarts}/3")
            if restarts > 3:
                return "failed"
            if "vLLM" in problem:
                kill_vllm(); st["restarts"]["vllm"] = st["restarts"].get("vllm", 0) + 1
            if step.get("purge"):
                sh(step["purge"])
            continue
        kill_group(proxy)
        if isinstance(child, Adopted) and not st.get("confirmed_" + name):
            st["confirmed_" + name] = True                     # exit code unknown: the command is resumable, run it again to confirm
            json.dump(st, open(state_path, "w"))
            continue
        if child.returncode == 0 or isinstance(child, Adopted):
            if step.get("purge") and reruns_after_infra == 0:
                r = sh(step["purge"])
                if "purged 0" not in r.stdout and "purged" in r.stdout:
                    reruns_after_infra += 1
                    log_line(f"- {now_iso()} | step={name} | EVENT re-running once after purging infrastructure-error items: {r.stdout.strip()[-80:]}", push=False)
                    continue
            return "done"
        restarts += 1; st["restarts"][name] = restarts; json.dump(st, open(state_path, "w"))
        log_line(f"- {now_iso()} | step={name} | EVENT step exited rc={child.returncode}; restart {restarts}/3")
        if restarts > 3:
            return "failed"


def finalize(plan_path, why):
    """END: finalize hooks (plan['finalize']), stop everything, check the GPU, DONE line."""
    try:
        plan = json.loads(Path(plan_path).read_text())
    except Exception:
        plan = {}
    for hook in plan.get("finalize", []):
        r = sh(hook, cwd=ROOT)
        log_line(f"- {now_iso()} | FINALIZE {' '.join(hook[:3])} rc={r.returncode}", push=False)
    kill_vllm()
    sh(["/usr/bin/docker", "rm", "-f", "g4-probe", "g4-p3"])
    for pid in sh(["pgrep", "-f", "pace_proxy.py"]).stdout.split():
        try:
            os.kill(int(pid), signal.SIGTERM)
        except Exception:
            pass
    sh(["sudo", "-n", "pkill", "-x", "dockerd"])
    time.sleep(10)
    apps = sh(["nvidia-smi", "--query-compute-apps=pid,name", "--format=csv,noheader"]).stdout.strip()
    log_line(f"- {now_iso()} | END cleanup ({why}): nvidia-smi compute apps: {apps or 'none'}")
    log_line(f"- DONE {now_iso()} ({why})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", default=str(G4 / "runs" / "autopilot_plan.json")); ap.add_argument("--state", default=str(G4 / "runs" / "autopilot_state.json"))
    a = ap.parse_args(argv)
    st = json.loads(Path(a.state).read_text()) if Path(a.state).exists() else {"done": [], "restarts": {}, "launch_epoch": None, "results": {}}
    idle_since, t_idle_health = None, 0.0
    while True:
        plan = json.loads(Path(a.plan).read_text())
        todo = [s for s in plan["steps"] if s["name"] not in st["done"]]
        if not todo:
            if plan.get("open") and lib.time_left_s(st["launch_epoch"] or time.time(), time.time()) > 0:
                if not idle_since:
                    idle_since = time.time(); t_idle_health = time.time()
                    log_line(f"- {now_iso()} | EVENT idle: every step of the plan is done; waiting for new steps (the plan is open)")
                if time.time() - t_idle_health >= HEALTH_S:          # the hourly health line continues while idle
                    t_idle_health = time.time()
                    log_line(lib.health_line(now_iso(), "idle", 0, 0, 0, 0, 0, None, 0, gpu_util(), disk_free_gb(), st["restarts"].get("vllm", 0) + st["restarts"].get("docker", 0)))
                time.sleep(IDLE_S); continue          # the plan is still being written: wait for the next step
            break
        idle_since = None
        step = todo[0]
        if st["launch_epoch"] is None:
            st["launch_epoch"] = time.time(); json.dump(st, open(a.state, "w"))
            log_line(f"- {now_iso()} | LAUNCH stage 1a; HARD STOP {now_iso(lib.deadline_utc(st['launch_epoch']))}")
        res = run_step(step, st, a.state)
        s = stats_for(step) if step.get("stats") else {"done": 0, "solved": 0}
        log_line(f"- {now_iso()} | step={step['name']} | END {res}: done={s['done']}/{step['total']} solved={s['solved']}")
        if res == "hardstop":
            json.dump(st, open(a.state, "w")); finalize(a.plan, "hard stop"); return 4
        if res == "blocked":
            json.dump(st, open(a.state, "w")); return 3
        plan_now = json.loads(Path(a.plan).read_text())          # post hooks are re-read: they can be added while the step runs
        step = next((x for x in plan_now["steps"] if x["name"] == step["name"]), step)
        for hook in step.get("post", []):
            r = sh(hook, cwd=ROOT)
            log_line(f"- {now_iso()} | step={step['name']} | POST {' '.join(hook[:3])} rc={r.returncode}", push=False)
        st["done"].append(step["name"]); json.dump(st, open(a.state, "w"))
        git_push(f"autopilot: step {step['name']} {res}")
    finalize(a.plan, "all steps finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
