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

LOG = ROOT / "docs" / "a6000" / "P2_LOG.md"
G4 = Path.home() / "g4"
PY = str(G4 / "venv" / "bin" / "python")
ENV = dict(os.environ, PATH="/usr/bin:" + ":".join(p for p in os.environ.get("PATH", "").split(":") if not p.startswith("/mnt/")))
TICK, STOP_CHECK_S, HEALTH_S = 30, 300, 3600


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


def start_proxy(spec):
    if not spec:
        return None
    Path(spec["log"]).parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen([PY, str(HERE / "pace_proxy.py"), "--listen", str(spec["listen"]), "--host", spec["host"], "--rewrite-model", "--log", spec["log"]],
                         env=ENV, stdout=open(spec["log"] + ".out", "a"), stderr=subprocess.STDOUT, start_new_session=True)
    time.sleep(3)
    return p


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


def stats_for(step):
    mod = importlib.reload(importlib.import_module("autopilot_stats"))
    return mod.collect(step["stats"])


# -------------------------------------------------------------------------------------------------- the loop
def run_step(step, st, state_path):
    name = step["name"]
    restarts = st["restarts"].get(name, 0)
    reruns_after_infra = 0
    while True:
        left = lib.time_left_s(st["launch_epoch"], time.time())
        if left <= 0:
            return "hardstop"
        if not ensure_docker() and step.get("docker"):
            log_line(f"- {now_iso()} | step={name} | EVENT dockerd would not start"); return "failed"
        if not ensure_vllm():
            log_line(f"- {now_iso()} | step={name} | EVENT vLLM would not start"); return "failed"
        proxy = start_proxy(step.get("proxy"))
        child = subprocess.Popen(step["cmd"], cwd=step.get("cwd") or str(ROOT), env=dict(ENV, **step.get("env", {})), stdout=open(G4 / f"step_{name}.log", "a"),
                                 stderr=subprocess.STDOUT, start_new_session=True)
        log_line(f"- {now_iso()} | step={name} | EVENT started pid {child.pid} (restarts so far {restarts}; hard stop in {left / 3600:.1f} h)", push=False)
        t_stop = t_health = time.time()
        problem = None
        while child.poll() is None:
            time.sleep(TICK)
            if lib.time_left_s(st["launch_epoch"], time.time()) <= 0:
                kill_group(child); kill_group(proxy); return "hardstop"
            if not vllm_ok():
                problem = "vLLM unhealthy"; break
            if step.get("docker") and not docker_ok():
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
            if time.time() - t_health >= HEALTH_S:
                t_health = time.time()
                s = stats_for(step)
                log_line(lib.health_line(now_iso(), name, s["done"], step["total"], s["solved"], s["empty"], s["errors"], s["median_s"], s["cap"], gpu_util(),
                                         disk_free_gb(), st["restarts"].get("vllm", 0) + st["restarts"].get("docker", 0)))
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
        if child.returncode == 0:
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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--plan", default=str(G4 / "runs" / "autopilot_plan.json")); ap.add_argument("--state", default=str(G4 / "runs" / "autopilot_state.json"))
    a = ap.parse_args(argv)
    st = json.loads(Path(a.state).read_text()) if Path(a.state).exists() else {"done": [], "restarts": {}, "launch_epoch": None, "results": {}}
    while True:
        plan = json.loads(Path(a.plan).read_text())
        todo = [s for s in plan["steps"] if s["name"] not in st["done"]]
        if not todo:
            if plan.get("open") and lib.time_left_s(st["launch_epoch"] or time.time(), time.time()) > 0:
                time.sleep(60); continue          # the plan is still being written: wait for the next step
            break
        step = todo[0]
        if st["launch_epoch"] is None:
            st["launch_epoch"] = time.time(); json.dump(st, open(a.state, "w"))
            log_line(f"- {now_iso()} | LAUNCH stage 1a; HARD STOP {now_iso(lib.deadline_utc(st['launch_epoch']))}")
        res = run_step(step, st, a.state)
        s = stats_for(step) if step.get("stats") else {"done": 0, "solved": 0}
        log_line(f"- {now_iso()} | step={step['name']} | END {res}: done={s['done']}/{step['total']} solved={s['solved']}")
        if res == "hardstop":
            json.dump(st, open(a.state, "w")); return 4
        if res == "blocked":
            json.dump(st, open(a.state, "w")); return 3
        plan_now = json.loads(Path(a.plan).read_text())          # post hooks are re-read: they can be added while the step runs
        step = next((x for x in plan_now["steps"] if x["name"] == step["name"]), step)
        for hook in step.get("post", []):
            r = sh(hook, cwd=ROOT)
            log_line(f"- {now_iso()} | step={step['name']} | POST {' '.join(hook[:3])} rc={r.returncode}", push=False)
        st["done"].append(step["name"]); json.dump(st, open(a.state, "w"))
        git_push(f"autopilot: step {step['name']} {res}")
    log_line(f"- {now_iso()} | DONE all steps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
