"""Developer-side patch judge probe (never shipped in a submission).
Asks an external model P(hidden tests pass | issue, patch) for every labelled
patch in data/patch_labels.json and measures whether it predicts our evaluator.
PRE-REGISTERED (2026-09-27, before any run): useful iff AUROC >= 0.70 over all
non-empty patches AND on tasks with both passing and failing candidates it picks
a passing patch more often than the 'always take v4' baseline."""
import json, os, sys, concurrent.futures as cf, urllib.request
MODEL = sys.argv[1] if len(sys.argv) > 1 else "typesafe/jev-1.13"
OUT = f"eval/judge_{MODEL.split('/')[-1]}.jsonl"
KEY = os.environ["OPENROUTER_KEY"]
T = {json.loads(l)["instance_id"]: json.loads(l) for l in open("data/tasks.jsonl")}
rows = [r for r in json.load(open("data/patch_labels.json")) if r["patch"].strip()]
done = {(j["task"], j["cfg"]) for j in map(json.loads, open(OUT))} if os.path.exists(OUT) else set()
PROMPT = """You review a patch for a GitHub issue in a Python repository. Hidden unit tests written by the maintainers will check whether the issue is fixed.

ISSUE:
{issue}

CANDIDATE PATCH:
{patch}

Estimate the probability (0-100) that the hidden tests pass with this patch applied. Consider whether it fixes the root cause, handles the cases in the issue, matches the API names the issue implies, and does not break existing behaviour.
Reply with JSON only: {{"p_pass": <integer 0-100>, "reason": "<one sentence>"}}"""

CRIT = {"pass": "The patch fixes the root cause of the issue and the maintainers' hidden tests will pass.",
        "fail": "The patch is wrong, incomplete, uses the wrong API/names, or breaks behaviour; hidden tests will fail."}

def decide(state, order):
    body = {"model": MODEL, "state": state, "questions": {"verdict": {"type": "choice",
            "instructions": "Judge whether this candidate patch resolves the GitHub issue so that hidden unit tests pass.",
            "criteria": {k: CRIT[k] for k in order}}}}
    req = urllib.request.Request("https://openrouter.ai/api/alpha/decisions", json.dumps(body).encode(),
          {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    a = json.load(urllib.request.urlopen(req, timeout=120))["answers"]["verdict"]
    return float(a["probabilities"]["pass"])

def ask(r):
    state = "ISSUE:\n" + T[r["task"]]["problem_statement"][:6000] + "\n\nCANDIDATE PATCH:\n" + r["patch"][:9000]
    err = ""
    for _ in range(3):
        try:
            ps = [decide(state, o) for o in (("pass", "fail"), ("fail", "pass"))]
            return dict(task=r["task"], cfg=r["cfg"], resolved=r["resolved"], p=sum(ps) / 2, both=ps)
        except Exception as e:
            err = getattr(e, "read", lambda: b"")()[:300].decode(errors="ignore") or str(e)
    return dict(task=r["task"], cfg=r["cfg"], resolved=r["resolved"], p=None, raw=err)

todo = [r for r in rows if (r["task"], r["cfg"]) not in done]
if "--one" in sys.argv: print(ask(todo[0])); sys.exit()
with cf.ThreadPoolExecutor(4) as ex, open(OUT, "a") as f:
    for j in ex.map(ask, todo): f.write(json.dumps(j) + "\n"); f.flush()
print("wrote", OUT, len(todo))
