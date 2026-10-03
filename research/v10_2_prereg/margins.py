import os, sys, pathlib, tempfile
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))
import test_v10_prompts as TP
out = {}
for stage in TP.STAGES:
    d = pathlib.Path(tempfile.mkdtemp())
    for q in ("p50", "p95", "worst", "cap"):
        (d / q).mkdir()
    _, s50 = TP.stage_start(stage, d / "p50", TP.P95_PROBLEM_CHARS, q="p50")
    _, s95 = TP.stage_start(stage, d / "p95", TP.P95_PROBLEM_CHARS)
    _, sw = TP.stage_start(stage, d / "worst")
    _, sc = TP.stage_start(stage, d / "cap", q="cap")
    A = TP.stage_peak(stage, s50, False, TP.TOOL)
    B = TP.guarded_peak(stage, s95, TP.TOOL_P10)
    C = TP.guarded_peak(stage, sw, TP.TOOL)
    D = TP.stage_peak(stage, sc, True, TP.TOOL_P10) + TP.max_output(stage)
    print("%-9s start_worst %5d | A %5d | B %5d (margin %5d) | C %5d (margin %5d) | D %5d" % (
        stage, sw, A, B, TP.COMPACTION - B, C, TP.COMPACTION - C, D))
thr, per = TP.meter_consts()
est = lambda calls: sum(n * (TP.HELPER_OUT[h][0] / 3.0 + o + per) for h, n, o in calls)
print("CONTEXT_TOKENS", thr)
