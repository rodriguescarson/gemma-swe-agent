"""The compiled v10 bundle end to end in the REAL Evaluator with a scripted model (SPEC R113, R114).

Each scenario runs `scripts/run_eval.py eval` (the pod runner, so its default EventsCompactionConfig(5, 2, 14336, 5) is
what compacts here) in a child process: real SubprocessManager sandboxes, real harness setup, the real ADK
SequentialAgent / skill toolset / LiteLLM path, and real verification of the hidden test. Only the model is replaced:
tests/v10_support/mock_llm.py answers per agent name from server-side step counters and reports realistic
usage.prompt_tokens, so compaction fires exactly when a real run would. The six R113 scenarios run concurrently
(one mock route each), about 30 s in total. R114 (NIGHTLY) replays the gold patch of three local rich tasks through
the helpers, with a hidden-test reproduction and a raw `sed` tamper of the hidden test file.
"""
import binascii
import json
import os
import re
import sys
import tarfile
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v10_support import sandbox as S  # noqa: E402
from v10_support.mock_llm import (MockLLM, cmd, heredoc, last_result_has, skill, submit, text,  # noqa: E402
                                  when, COMPACTION_LINE)

try:
    from v10_support.repo import no_orphans  # noqa: F401,E402  (autouse, R120)
except ImportError:  # core's support module not present: same contract, minimal form
    import subprocess

    @pytest.fixture(autouse=True)
    def no_orphans(tmp_path):
        yield
        deadline, left = time.monotonic() + 1.0, []
        while True:
            ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
            left = [line for line in ps.splitlines() if str(tmp_path) in line and "ps -axo" not in line]
            if not left or time.monotonic() > deadline:
                break
            time.sleep(0.1)
        assert not left, f"orphan processes survived the test: {left[:3]}"

pytest.importorskip("swegemma.evaluate")
pytestmark = pytest.mark.skipif(S.bundle_missing() is not None, reason=S.bundle_missing() or "")
NIGHTLY = os.environ.get("G4_NIGHTLY") == "1"
NUDGE = "Please continue your work using the available tools"

# ---------------------------------------------------------------------------------------------------------------------
# Synthetic task: calc.add subtracts. The hidden test (test_patch) adds test_add to tests/test_ops.py.
# ---------------------------------------------------------------------------------------------------------------------
TID = "calc_1"
FILES = {
    "calc/__init__.py": "",
    "calc/ops.py": 'def add(a, b):\n    """Add two numbers."""\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n',
    "tests/__init__.py": "",
    "tests/test_ops.py": "from calc.ops import add, mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n",
}
TEST_PATCH = ("--- a/tests/test_ops.py\n+++ b/tests/test_ops.py\n@@ -3,3 +3,7 @@ from calc.ops import add, mul\n"
              " \n def test_mul():\n     assert mul(2, 3) == 6\n+\n+\n+def test_add():\n+    assert add(2, 3) == 5\n")
GOLD = ("--- a/calc/ops.py\n+++ b/calc/ops.py\n@@ -1,3 +1,3 @@\n def add(a, b):\n     \"\"\"Add two numbers.\"\"\"\n"
        "-    return a - b\n+    return a + b\n")
STATEMENT = "calc.ops.add subtracts instead of adding\n\nadd(2, 3) returns -1; expected 5."

CLAIM = "from calc.ops import add\n# CLAIM 1: add sums\nassert add(2, 3) == 5, add(2, 3)\n"
EDIT = heredoc("python3 /tmp/swe/edit.py calc/ops.py",
               "<<<<<<< SEARCH\n    return a - b\n=======\n    return a + b\n>>>>>>> REPLACE\n")
LOCATE = cmd('python3 /tmp/swe/locate.py "add sums calc ops"')
VIEW = cmd("python3 /tmp/swe/view.py calc/ops.py add")
REPRO = heredoc("python3 /tmp/swe/verify.py --repro-only", CLAIM)
PLAN = text("FILES: calc/ops.py:1-3 (add)\nCAUSE: add subtracts.\nFIX: return a + b.\nREPRO: fails on original\n"
            "TESTS: tests/test_ops.py")
VERIFY = cmd("python3 /tmp/swe/verify.py")
STATUS = cmd("python3 /tmp/swe/status.py")
FINALIZE = cmd("python3 /tmp/swe/finalize.py")
NOTES = text("CHANGED: calc/ops.py add (3)\nVERIFY: VERIFY: GREEN")
SETUP_OK = [skill("install.py"), text("READY")]
FINAL = last_result_has("FINAL: the patch was finalized")
# v10.1 (diag 3): writes through the harness's own tools, which run no bundle code
EDIT_TEST = {"tool": "edit_file", "args": {"filepath": "tests/test_ops.py", "old_string": "assert mul(2, 3) == 6",
                                           "new_string": "assert mul(2, 3) == 7"}}
WRITE_REPRO = {"tool": "write_file", "args": {"filepath": "repro.py", "content": "from calc.ops import add\nprint(add(2, 3))\n"}}

SCENARIOS = {
    # (a) the happy path ends at the verifier's submit + text; the submitter never runs
    "a": {"setup": SETUP_OK, "locator": [LOCATE, VIEW, REPRO, PLAN], "fixer": [EDIT, VERIFY, NOTES],
          "verifier": [STATUS, VERIFY, FINALIZE, submit(), text("Submitted.")],
          "submitter": [text("the submitter must not run in scenario a")]},
    # (b) the verifier replies without submitting; the submitter finalizes and submits
    "b": {"setup": SETUP_OK, "locator": [LOCATE, REPRO, PLAN], "fixer": [EDIT, VERIFY, NOTES],
          "verifier": [STATUS, VERIFY, text("The change looks right.")],
          "submitter": [FINALIZE, submit(), text("submitted")]},
    # (c) setup replies READY without a call; the locator's "can't open file" leads to the RECOVER install
    "c": {"setup": [text("READY")],
          "locator": [LOCATE, when(last_result_has("can't open file"), skill("install.py"), text("no helpers needed")),
                      LOCATE, REPRO, PLAN],
          "fixer": [EDIT, VERIFY, NOTES], "verifier": [STATUS, VERIFY, FINALIZE, submit(), text("Submitted.")]},
    # (d) a compaction forced mid-fixer (reported prompt 15,000 tokens) raises nothing; status.py recovers the state
    "d": {"setup": SETUP_OK, "locator": [LOCATE, REPRO, PLAN],
          "fixer": [EDIT, {**VERIFY, "ptok": 15000}, STATUS, NOTES],
          "verifier": [STATUS, VERIFY, FINALIZE, submit(), text("Submitted.")]},
    # (f) the submitter replies without submitting -> the harness nudges -> the pipeline restarts at setup; the FINAL
    #     banner (shown by every helper once finalize ran) makes each stage reply at once and the verifier submits
    "f": {"setup": SETUP_OK + SETUP_OK,
          "locator": [LOCATE, REPRO, PLAN, STATUS, when(FINAL, text("done"), LOCATE), text("done")],
          "fixer": [EDIT, VERIFY, NOTES, STATUS, when(FINAL, text("done"), EDIT), text("done")],
          "verifier": [STATUS, VERIFY, FINALIZE, text("done"), STATUS, when(FINAL, submit(), VERIFY), text("Submitted.")],
          "submitter": [FINALIZE, text("submitted")]},
    # (g) v10.1, fastapi_14077: after finalize printed READY the verifier edits a test file with the harness's edit_file
    #     and submits; the submit guard (armed by setup's install) keeps it out of the patch, so the hidden test_patch
    #     applies and the task resolves
    "g": {"setup": SETUP_OK, "locator": [LOCATE, REPRO, PLAN], "fixer": [EDIT, VERIFY, NOTES],
          "verifier": [STATUS, VERIFY, FINALIZE, EDIT_TEST, submit(), text("Submitted.")]},
    # (h) v10.1, fastapi_14258: the fixer fixes the code, writes a root repro.py with write_file and then only replies;
    #     no helper runs again, the harness nudges until it gives up and takes the fallback diff, which must carry the
    #     fix and not repro.py
    "h": {"setup": SETUP_OK, "locator": [LOCATE, REPRO, PLAN], "fixer": [EDIT, WRITE_REPRO, text("done")],
          "verifier": [text("done")], "submitter": [text("done")]},
}


def make_task(root: Path, tid=TID, files=FILES, test_patch=TEST_PATCH, statement=STATEMENT, gold=GOLD):
    """tasks.jsonl + a snapshot tarball (repo root with .git, like data/raw/snapshots/*.tgz)."""
    repo = root / "repo"
    repo.mkdir(parents=True)
    S.write_tree(repo, files)
    S.git_init(repo)
    snaps = root / "snapshots"
    snaps.mkdir()
    with tarfile.open(snaps / f"{tid}.tgz", "w:gz") as tf:
        tf.add(repo, arcname=".")
    row = {"instance_id": tid, "repo": "synthetic/calc", "base_commit": "0" * 40, "patch": gold, "test_patch": test_patch,
           "problem_statement": statement, "hints_text": "", "created_at": "2026-09-28T00:00:00Z"}
    (root / "tasks.jsonl").write_text(json.dumps(row) + "\n")
    return root / "tasks.jsonl", snaps


@pytest.fixture(scope="module")
def flows(tmp_path_factory):
    """Run every R113 scenario once, concurrently: {name: (EvalRun, mock log, summarizer calls)}."""
    root = tmp_path_factory.mktemp("flows")
    bundle = S.copy_bundle(root)
    tasks, snaps = make_task(root / "task")
    out = {}
    with MockLLM() as mock:
        routes = {k: mock.add_route(f"s{k}", v) for k, v in SCENARIOS.items()}

        def one(k):
            return k, S.run_eval_cli(bundle=bundle, tasks=tasks, snapshots=snaps, results=root / f"res_{k}",
                                     api_base=routes[k], task_ids=[TID], timeout=420)
        with ThreadPoolExecutor(len(SCENARIOS)) as ex:
            runs = dict(ex.map(one, SCENARIOS))
        for k, run in runs.items():
            out[k] = (run, mock.log(f"s{k}"), mock.summarizer_calls(f"s{k}"))
        assert not mock.errors, mock.errors
    return out


def observations(run, author=None):
    return [(a, t, o) for a, t, o in S.trace_observations(run.trace(TID)) if author is None or a == author]


def requests(log, agent):
    return [e for e in log if e["agent"] == agent]


def common_checks(run, log):
    row = run.row(TID)
    assert run.rc == 0, run.stderr[-2000:]
    assert "Traceback" not in run.stderr, run.stderr[-3000:]
    assert row["error"] is None, row
    assert row["resolved"] is True, (row, run.patch(TID), run.log(TID)[-3000:])
    patch = run.patch(TID)
    assert "calc/ops.py" in patch and "+    return a + b" in patch and "tests/" not in patch
    assert not [e for e in log if e["exhausted"]], [(e["agent"], e["index"]) for e in log if e["exhausted"]]
    agent_calls = [e for e in log if e["kind"] == "agent"]
    last = max(agent_calls, key=lambda e: e["t_in"])
    assert last["est_prompt_tokens"] < COMPACTION_LINE, last["est_prompt_tokens"]                     # (e)
    assert max(e["est_prompt_tokens"] for e in agent_calls) < COMPACTION_LINE
    stage_order = [e["agent"] for e in agent_calls]
    assert stage_order[0] == "setup" and "_unknown" not in stage_order
    return row


def check_a(flows):
    run, log, summ = flows["a"]
    common_checks(run, log)
    assert requests(log, "submitter") == []                                   # the submitter never runs
    assert [e["agent"] for e in log if e["kind"] == "agent"][-1] == "verifier"
    obs = " ".join(o for _, _, o in observations(run))
    for want in ("swe-tools v10.1 ready", "LOCATE:", "REPRO: fails on original", "OK (exact)", "VERIFY: GREEN", "READY:"):
        assert want in obs, want
    assert "can't open file" not in obs
    assert run.secs < 240


def check_b(flows):
    run, log, summ = flows["b"]
    common_checks(run, log)
    sub = requests(log, "submitter")
    assert [e["step"].get("tool") or "text" for e in sub] == ["run_command", "submit_patch", "text"]
    fin = [o for a, t, o in observations(run, "submitter") if t == "run_command"]
    assert fin and "READY:" in fin[0] and "FINAL:" in fin[0], fin


def check_c(flows):
    run, log, summ = flows["c"]
    common_checks(run, log)
    loc = observations(run, "locator")
    assert "can't open file" in loc[0][2], loc[0]
    assert loc[1][1] == "run_skill_script" and "swe-tools v10.1 ready" in loc[1][2], loc[1]
    assert "LOCATE:" in loc[2][2]
    assert requests(log, "setup")[0]["step"] == {"text": "READY"}


def check_d(flows):
    run, log, summ = flows["d"]
    common_checks(run, log)
    assert summ >= 1, "the forced 15,000-token prompt must trigger an in-flow compaction"
    fixer = requests(log, "fixer")
    i = next(n for n, e in enumerate(log) if e["kind"] == "summarizer")
    assert log[i - 1]["agent"] == "fixer" and log[i + 1]["agent"] == "fixer"   # compacted between two fixer calls
    st = [o for a, t, o in observations(run, "fixer") if "STATUS [t=" in o]
    assert st and "edit calc/ops.py OK" in st[0] and "verify: GREEN" in st[0], st   # status.py recovers the work
    assert len(fixer) == 4


def check_e(flows):
    for k, (run, log, _) in flows.items():
        agent_calls = [e for e in log if e["kind"] == "agent"]
        assert agent_calls, k
        last = max(agent_calls, key=lambda e: e["t_in"])
        assert last["est_prompt_tokens"] < COMPACTION_LINE, (k, last["est_prompt_tokens"])
        biggest = max(e["est_prompt_tokens"] for e in agent_calls)
        assert biggest < 12000, (k, biggest)          # SPEC 6 typical-cap peak; these runs are short


def check_f(flows):
    run, log, summ = flows["f"]
    common_checks(run, log)
    setup = requests(log, "setup")
    assert len(setup) == 4 and any(NUDGE in u for u in _user_texts(setup[2]))     # exactly one restart, after a nudge
    assert len(requests(log, "submitter")) == 2                                   # pass 1 only
    ver = requests(log, "verifier")
    assert ver[-2]["step"]["tool"] == "submit_patch" and ver[-1]["step"] == {"text": "Submitted."}
    obs = observations(run)
    finals = [o for a, t, o in obs if "FINAL: the patch was finalized" in o]
    assert len(finals) >= 4, len(finals)                  # install + locator/fixer/verifier status in pass 2
    for agent in ("locator", "fixer"):
        assert requests(log, agent)[4]["step"] == {"text": "done"}               # the banner made them stop at once


def check_g(flows):
    run, log, summ = flows["g"]
    common_checks(run, log)                                   # resolved, and no tests/ path in the submitted patch
    ver = [o for a, t, o in observations(run, "verifier")]
    assert any("READY:" in o for o in ver)
    edit = [o for a, t, o in observations(run, "verifier") if t == "edit_file"]
    assert edit and "error" not in edit[0].lower()[:40], edit   # the edit itself succeeded on disk


def check_h(flows):
    run, log, summ = flows["h"]
    row = run.row(TID)
    assert run.rc == 0 and "Traceback" not in run.stderr, run.stderr[-3000:]
    patch = run.patch(TID)
    assert "+    return a + b" in patch and "repro.py" not in patch, patch
    assert not [e for e in log if e["kind"] == "agent" and e["agent"] == "submitter"
                and e["step"].get("tool") == "submit_patch"]     # nothing was submitted: this is the fallback diff
    assert any(t == "write_file" for a, t, o in observations(run, "fixer"))
    assert row["resolved"] is True, (row, patch)


@pytest.mark.parametrize("scenario", list("abcdefgh"))
def test_flow(flows, scenario):
    """R113 (a)-(f); (e) checks every scenario's prompts against the 14,336 compaction line; (g) and (h) are the v10.1
    submit-guard ends (diag 3)."""
    {"a": check_a, "b": check_b, "c": check_c, "d": check_d, "e": check_e, "f": check_f, "g": check_g,
     "h": check_h}[scenario](flows)


def _user_texts(entry):
    return [m.get("content") if isinstance(m.get("content"), str) else json.dumps(m.get("content"))
            for m in entry["body"].get("messages", []) if m.get("role") == "user"]


# ---------------------------------------------------------------------------------------------------------------------
# R114 scripted-gold end to end on three local rich tasks (NIGHTLY)
# ---------------------------------------------------------------------------------------------------------------------
GOLD_TIDS = ("rich_3278", "rich_3480", "rich_4075")
DATA = S.ROOT / "data"


def _task(tid):
    for line in (DATA / "tasks.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r["instance_id"] == tid:
            return r
    raise KeyError(tid)


def hunks(patch):
    """[(path, new_file, [(old_start, old_len, new_lines)])] of a unified diff (test-harness code)."""
    out, cur, h = [], None, None
    for line in patch.splitlines():
        if line.startswith("--- "):
            continue
        if line.startswith("+++ "):
            cur = [line[6:] if line.startswith("+++ b/") else line[4:], False, []]
            out.append(cur)
            continue
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if m:
            h = [int(m.group(1)), int(m.group(2) or 1), []]
            cur[2].append(h)
            if h[0] == 0:
                cur[1] = True
            continue
        if h is not None and line[:1] in (" ", "+"):
            h[2].append(line[1:])
        elif h is not None and line == "":
            h[2].append("")
    return out


def gold_steps(patch):
    """Gold applied through edit.py, bottom-up per file (--lines / --insert-after / --create), one call per hunk."""
    steps = []

    def body(lines):   # every line newline-terminated: a trailing blank context line must survive
        return "".join(x + "\n" for x in lines)

    for path, new, hs in hunks(patch):
        if new:
            steps.append(heredoc(f"python3 /tmp/swe/edit.py {path} --create", body(hs[0][2])))
            continue
        for start, n, lines in sorted(hs, key=lambda x: -x[0]):
            if n == 0:
                steps.append(heredoc(f"python3 /tmp/swe/edit.py {path} --insert-after {start}", body(lines)))
            elif not lines:
                steps.append(cmd(f"python3 /tmp/swe/edit.py {path} --lines {start}-{start + n - 1} --delete"))
            else:
                steps.append(heredoc(f"python3 /tmp/swe/edit.py {path} --lines {start}-{start + n - 1}", body(lines)))
    return steps


def hidden_claims(test_patch):
    """One CLAIM per test function the hidden test_patch adds; each runs it in a scratch copy of the tree with the
    test_patch applied (the hidden tests are not in the agent workspace). The patch travels hex-encoded, so the
    sandbox's /tmp rewrite of the command text cannot touch it."""
    if not test_patch.endswith("\n"):          # the harness appends it too (verification.py); git apply needs it
        test_patch += "\n"
    blob = binascii.hexlify(zlib.compress(test_patch.encode())).decode()
    files = [p for p, _, _ in hunks(test_patch)]
    # [ \t]* on purpose: \s* would cross the newline after a bare "+" line and pick up a CONTEXT def
    # (rich_4075: "+\n def test_print_multiple"); verification._extract_test_functions_from_patch has that quirk
    tests = re.findall(r"^\+[ \t]*(?:async[ \t]+)?def[ \t]+(test_\w+)[ \t]*\(", test_patch, re.M)
    prelude = f'''import os, shutil, subprocess, sys, tempfile, zlib, binascii
TP = zlib.decompress(binascii.unhexlify("{blob}"))
def hidden(node):
    d = tempfile.mkdtemp()
    t = os.path.join(d, "t")
    try:
        shutil.copytree(".", t, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"), symlinks=True)
        a = subprocess.run(["git", "apply", "-"], input=TP, cwd=t, capture_output=True)
        if a.returncode != 0:
            raise SystemExit("TEST PATCH DID NOT APPLY: " + a.stderr.decode(errors="replace")[-200:])
        env = dict(os.environ, PYTHONPATH=t)
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "-p", "no:anyio", node],
                           cwd=t, env=env, capture_output=True, text=True)
        assert r.returncode == 0, "HIDDEN TEST FAILED: " + r.stdout[-300:]
    finally:
        shutil.rmtree(d, ignore_errors=True)
'''
    body = "".join(f"# CLAIM {i}: {files[0]}::{name}\nhidden({(files[0] + '::' + name)!r})\n"
                   for i, name in enumerate(tests[:6], 1))
    return prelude + body


KNOWN_FLAKY = {   # grader-side tests whose outcome depends on machine load, not on the patch
    "tests/test_console.py::test_brokenpipeerror": "`python -m rich | head -1` races the pipe buffer: exit 0 when rich "
                                                  "finishes before head closes the pipe (seen on a loaded Mac)",
}


def _grader_failures(run, tid):
    p = run.results_dir / "test_outputs" / f"{tid}.log"
    txt = p.read_text(errors="replace") if p.is_file() else ""
    return set(re.findall(r"^FAILED (\S+)", txt, re.M)) | set(re.findall(r"^ERROR (\S+)", txt, re.M))


def _changed_lines(patch):
    return sorted(line for line in patch.splitlines()
                  if line[:1] in "+-" and not line.startswith(("+++ ", "--- ")))


def gold_script(tid):
    t = _task(tid)
    test_file = hunks(t["test_patch"])[0][0]
    title = t["problem_statement"].splitlines()[0][:80].replace('"', "")
    tamper = cmd(f"sed -i.bak 's/$/ /' {test_file} && rm -f {test_file}.bak")      # raw edit of the HIDDEN test file
    return {"setup": SETUP_OK,
            "locator": [cmd(f'python3 /tmp/swe/locate.py "{title}"'),
                        heredoc("python3 /tmp/swe/verify.py --repro-only", hidden_claims(t["test_patch"])),
                        text(f"FILES: see gold\nREPRO: fails on original\nTESTS: {test_file}")],
            "fixer": [tamper, *gold_steps(t["patch"]), VERIFY, text("CHANGED: gold")],
            "verifier": [STATUS, VERIFY, FINALIZE, submit(), text("Submitted.")]}


@pytest.mark.skipif(not NIGHTLY, reason="NIGHTLY tier (G4_NIGHTLY=1)")
@pytest.mark.skipif(not all((DATA / "raw" / "snapshots" / f"{t}.tgz").is_file() for t in GOLD_TIDS),
                    reason="local snapshots for rich_3278/3480/4075 absent")
@pytest.mark.parametrize("tid", GOLD_TIDS)
def test_scripted_gold_e2e(tmp_path, tid):
    bundle = S.copy_bundle(tmp_path)
    t = _task(tid)
    test_file = hunks(t["test_patch"])[0][0]
    for attempt in (1, 2):
        with MockLLM() as mock:
            base = mock.add_route(tid, gold_script(tid))
            run = S.run_eval_cli(bundle=bundle, tasks=DATA / "tasks.jsonl", snapshots=DATA / "raw" / "snapshots",
                                 results=tmp_path / f"res{attempt}", api_base=base, task_ids=[tid], timeout=900)
            log = mock.log(tid)
            assert not mock.errors, mock.errors
        failed = _grader_failures(run, tid)
        if run.row(tid)["resolved"] or not failed or not failed <= set(KNOWN_FLAKY):
            break                     # retry only when every failing grader test is a documented upstream flake
    row = run.row(tid)
    obs = {k: [o for a, tt, o in S.trace_observations(run.trace(tid)) if a == k] for k in ("locator", "fixer", "verifier")}
    repro = next(o for o in obs["locator"] if "REPRO:" in o)
    assert "fails on original" in repro or "hangs on original" in repro, repro[:600]
    everything = json.dumps(obs)
    assert "TEST PATCH DID NOT APPLY" not in everything, "claims failed for the wrong reason: " + repro[:600]
    edits = [o for o in obs["fixer"] if "edit.py" in o or o.lstrip('{"status": "ok", "stdout": "').startswith("OK")]
    assert all("REFUSED" not in o and "NO MATCH" not in o and "REVERTED" not in o for o in edits), edits
    full = [o for o in obs["fixer"] + obs["verifier"] if "VERIFY:" in o and "SAME AS LAST RUN" not in o]
    assert full and re.search(r"REPRO: (\d+)/\1 claims fixed", full[-1]), full[-1][:800] if full else obs
    last = [o for o in obs["verifier"] if "VERIFY:" in o][-1]
    assert re.search(r"VERIFY: (GREEN|AMBER)", last), last[:600]
    assert row["error"] is None and row["resolved"] is True, (row, run.log(tid)[-3000:])
    patch = run.patch(tid)
    assert test_file not in patch, "the raw sed of the hidden test file must have been reverted"
    assert _changed_lines(patch) == _changed_lines(t["patch"]), "edit.py did not reproduce the gold hunks exactly"
    assert not [e for e in log if e["exhausted"]]
    assert max(e["est_prompt_tokens"] for e in log if e["kind"] == "agent") < COMPACTION_LINE
