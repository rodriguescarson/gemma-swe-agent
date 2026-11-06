"""Measurement hook for the budget ladder. Meant to run as an extra cell in the Kaggle eval kernel, right after `ev = Evaluator(ec)`.
It records, at the start of every counted tool call, the working-tree diff against _swegemma_baseline (= the tree after tool_calls_used calls),
without touching the agent's git index (temporary index file) and without spending any of the agent's budget (it calls the sandbox directly,
not through a tool). It does not change what the agent sees. Output: /kaggle/working/snapshots.jsonl, one line per distinct tree:
  {"task": id, "k": calls completed, "t": agent_elapsed_s at snapshot, "sha": sha1(patch), "patch": ...}
The tree after the LAST call is the row's own `patch` in results.jsonl (submit_patch or the harness fallback diff), which ladder_analyze.py uses."""
import hashlib, json, threading, time

# cp -p keeps the index file's own mtime: git re-reads ("racy git") any entry whose mtime is not older than the index file,
# which is what catches a same-size edit made within the second the index was written. A plain cp gave the copy a new mtime,
# so git trusted the stale stat and missed such an edit (seen 1 run in 2 of tests/test_snapshot_hook.py, 2026-11-07). The
# harness's own fallback diff uses the real index, so -p makes the snapshot see what the harness would grade.
SNAP_CMD = ("cd /workspace && cp -p .git/index /tmp/.snap_idx 2>/dev/null && "
            "GIT_INDEX_FILE=/tmp/.snap_idx git add -N . >/dev/null 2>&1; "
            "GIT_INDEX_FILE=/tmp/.snap_idx git diff --binary _swegemma_baseline 2>/dev/null")
_lock = threading.Lock()


def install(out_path="/kaggle/working/snapshots.jsonl"):
    from swegemma.context import SwegemmaContext
    from swegemma.harness.verification import strip_protected_files_from_patch
    if getattr(SwegemmaContext.check_budget, "_ladder_hook", False):
        return
    orig = SwegemmaContext.check_budget
    seen = {}      # task id -> last sha written (rows are only written when the tree changed, plus the first)

    def snap(ctx):
        t0 = time.perf_counter()
        res = ctx.docker.exec(ctx.container_id, SNAP_CMD, timeout=30)
        diff = res.stdout or ""
        extra = list(getattr(ctx.task, "test_files", None) or ())
        if diff.strip():
            diff = strip_protected_files_from_patch(diff, extra_protected_paths=extra)
        sha = hashlib.sha1(diff.encode()).hexdigest()
        tid = getattr(ctx.task, "instance_id", None) or ctx.task_id
        k = ctx.tool_calls_used; dt = round(time.perf_counter() - t0, 3)   # this time runs inside the agent's clock; ladder_analyze.py subtracts it
        with _lock:
            if seen.get(tid) == sha:
                rec = dict(task=tid, k=k, t=round(ctx.agent_elapsed_seconds, 2), dt=dt, sha=sha, same=True)
            else:
                seen[tid] = sha
                rec = dict(task=tid, k=k, t=round(ctx.agent_elapsed_seconds, 2), dt=dt, sha=sha, patch=diff)
            with open(out_path, "a") as f:
                f.write(json.dumps(rec) + "\n")

    def check_budget(self, *, count_tool_call=True):
        if count_tool_call:
            try:
                snap(self)
            except Exception as e:   # never break the run for the measurement
                with _lock, open(out_path + ".err", "a") as f:
                    f.write(repr(e)[:300] + "\n")
        return orig(self, count_tool_call=count_tool_call)

    check_budget._ladder_hook = True
    SwegemmaContext.check_budget = check_budget
