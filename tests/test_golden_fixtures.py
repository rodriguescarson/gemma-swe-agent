"""Component (a) of docs/eval/GOLDEN_EVALS_SPEC.md v1.1: the DEV/HOLDOUT split and the golden-data builder
(scripts/golden/fixture_lib.py, scripts/golden/build_fixtures.py). Section 12(a) tests plus gotchas 6, 11, 12, 20-22.

Default tier: no network, no model, no GPU; synthetic repos and traces, plus read-only checks of the committed files and
the real task data (the leak rules on all 74 plans). Tests that run the bundle helpers need only the bundle scripts
(copied to a temp dir, never run inside submissions/). NIGHTLY (G4_NIGHTLY=1): gradability on 3 real rich tasks and a
full `build_fixtures.py --check`.
"""
from __future__ import annotations

import ast
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "golden"))
sys.path.insert(0, str(ROOT / "tests"))
import fixture_lib as F  # noqa: E402
from v10_support import repo as RP  # noqa: E402
from v10_support import tasks as T  # noqa: E402

NIGHTLY = os.environ.get("G4_NIGHTLY") == "1"
NINE = ("fastapi_14616", "fastapi_14794", "rich_2943", "rich_3006", "rich_3105", "rich_3278", "rich_3470",
        "rich_3472", "rich_3905")
SPEC_HOLDOUT = {
    "fastapi/both": (9, ["fastapi_11194", "fastapi_14492"]),
    "fastapi/none": (15, ["fastapi_15800", "fastapi_14616", "fastapi_14258", "fastapi_15661"]),
    "fastapi/one": (7, ["fastapi_5624", "fastapi_15589"]),
    "requests/none": (1, []),
    "rich/both": (10, ["rich_3882", "rich_3905", "rich_3006"]),
    "rich/none": (28, ["rich_4076", "rich_3052", "rich_3930", "rich_3942", "rich_3061", "rich_3934", "rich_3944"]),
    "rich/one": (4, ["rich_3454"]),
}


# =====================================================================================================================
# split (section 2)
# =====================================================================================================================
@pytest.mark.parametrize("n,k", [(0, 0), (1, 0), (2, 1), (3, 1), (4, 1), (5, 1), (6, 2), (7, 2), (9, 2), (10, 3),
                                 (15, 4), (28, 7)])
def test_holdout_k(n, k):
    assert F.holdout_k(n) == k == (n + 2) // 4          # floor(n*0.25+0.5), exact in integers too


def test_split_order_is_sha256_of_seeded_id():
    import hashlib
    assert F.order_key("rich_1") == hashlib.sha256(b"golden-v1:rich_1").hexdigest()
    strata, tasks = F.compute_split(["b", "a", "c"], {"a": "r", "b": "r", "c": "r"}, {"a": "none", "b": "none",
                                                                                     "c": "none"})
    order = sorted("abc", key=F.order_key)
    assert strata["r/none"] == {"n": 3, "holdout": order[:1], "dev": order[1:]}
    assert tasks[order[0]]["split"] == "holdout" and {tasks[t]["split"] for t in order[1:]} == {"dev"}


def test_split_small_strata_and_labels():
    runs = [{"x": True, "y": True, "z": False}, {"x": True, "y": False, "z": False}]
    assert [F.race2_label(t, runs) for t in "xyzw"] == ["both", "one", "none", "none"]
    ids = ["x", "y", "z"]
    strata, tasks = F.compute_split(ids, {t: "r" for t in ids}, {t: F.race2_label(t, runs) for t in ids})
    assert {k: (v["n"], len(v["holdout"])) for k, v in strata.items()} == {"r/both": (1, 0), "r/one": (1, 0),
                                                                           "r/none": (1, 0)}
    strata, _ = F.compute_split(["p", "q"], {"p": "r", "q": "r"}, {"p": "none", "q": "none"})
    assert len(strata["r/none"]["holdout"]) == 1 and len(strata["r/none"]["dev"]) == 1


def test_split_deterministic_disjoint_complete_and_equals_spec_table():
    a, b = F.build_split(), F.build_split()
    assert F.dumps(a) == F.dumps(b)
    ids = F.load_ids()
    assert sorted(a["tasks"]) == sorted(ids) and len(ids) == 74
    hold = [t for s in a["strata"].values() for t in s["holdout"]]
    dev = [t for s in a["strata"].values() for t in s["dev"]]
    assert not set(hold) & set(dev) and sorted(hold + dev) == sorted(ids) and len(hold) == 19 and len(dev) == 55
    assert {k: (v["n"], v["holdout"]) for k, v in a["strata"].items()} == SPEC_HOLDOUT
    for tid, t in a["tasks"].items():
        assert (tid in hold) == (t["split"] == "holdout")
        assert tid in a["strata"][f"{t['repo']}/{t['race2']}"][t["split"]]


def test_committed_split_equals_recomputation():
    text = F.SPLIT_FILE.read_text()
    assert text == F.dumps(F.build_split())
    doc = json.loads(text)
    assert doc["schema"] == "golden-split-v1" and doc["seed"] == "golden-v1" and doc["holdout_frac"] == 0.25
    for path, sha in doc["inputs"].items():
        assert F.sha_file(ROOT / path) == sha, path


def test_runnable_today_counts_and_split_independent_of_runnable():
    doc = json.loads(F.SPLIT_FILE.read_text())
    assert sorted(v["split"] for v in doc["tasks"].values()).count("dev") == 55 and len(doc["tasks"]) == 74
    run = {t for t in doc["tasks"] if F.runnable(t)[0]}
    dev = {t for t in run if doc["tasks"][t]["split"] == "dev"}
    if not all(T.kpar_ok(r) for r in ("rich", "requests")):
        pytest.skip(f"kpar venvs missing: {T.build_cmd('rich')}")
    local = {t for t in doc["tasks"] if T.has_snapshot(t)}
    assert run == {t for t in local if T.kpar_ok(t)}
    if len(local) == 74 and T.kpar_ok("fastapi"):      # 2026-09-30: all 74 snapshots fetched, fastapi venv built
        assert (len(dev), len(run - dev)) == (55, 19)
    elif local == {t for t in doc["tasks"] if not t.startswith("fastapi_") and t not in
                   ("rich_4076", "rich_4077", "rich_4079")}:
        assert (len(dev), len(run - dev)) == (30, 10)   # the 40 snapshots of 2026-09-29
    assert "runnable" not in json.dumps(doc)


# =====================================================================================================================
# golden plan (4.1)
# =====================================================================================================================
SRC = '''import os


class Box:
    size = 1

    @property
    def area(self):
        x = 1
        return x * 2

    def grow(self, n):
        def inner(k):
            return k + 1
        return inner(n)


def top(a):
    return a
'''


def _diff(tmp_path, before: dict, after: dict) -> str:
    """A real git diff between two trees (the builder's inputs are git diffs). Read as bytes: RP.git's text mode uses
    universal newlines, which would turn a CRLF body line into LF before the builder ever sees it."""
    ws = RP.make_repo(tmp_path, before, harness_config=False)
    for rel in before:
        if rel not in after:
            (ws / rel).unlink()
    RP.write_files(ws, after)
    RP.git(ws, "add", "-A")
    return RP.git(ws, "diff", "--cached", "_swegemma_baseline", text=False).decode("utf-8", "surrogateescape")


def test_plan_entries_ast_qualnames_module_level_merged_and_new_file(tmp_path):
    after = SRC.replace("        x = 1\n", "        x = 3\n").replace("        return x * 2\n", "        return x * 4\n") \
        .replace("            return k + 1\n", "            return k + 2\n").replace("import os\n", "import os\nimport re\n")
    patch = _diff(tmp_path, {"pkg/m.py": SRC}, {"pkg/m.py": after, "pkg/new.py": "A = 1\nB = 2\n"})
    entries, basis = F.plan_entries(patch, {"pkg/m.py": SRC})
    assert basis == "ast"
    texts = [F.entry_text(e) for e in entries]
    assert texts == ["pkg/m.py:1-1 (module level)", "pkg/m.py:9-10 (Box.area)", "pkg/m.py:14-14 (Box.grow.inner)",
                     "pkg/new.py (new file)"], texts
    funcs = F.gold_functions(entries)
    assert funcs == [{"file": "pkg/m.py", "qualname": "Box.area", "name": "area"},
                     {"file": "pkg/m.py", "qualname": "Box.grow.inner", "name": "inner"}]


def test_plan_merges_separate_hunks_of_one_function(tmp_path):
    body = "".join(f"    s{i} = {i}\n" for i in range(1, 21))
    src = "def big(a):\n" + body + "    return a\n\n\ndef other():\n    return 0\n"
    after = src.replace("    s2 = 2\n", "    s2 = 22\n").replace("    s18 = 18\n", "    s18 = 180\n") \
        .replace("    return 0\n", "    return 1\n")
    patch = _diff(tmp_path, {"m.py": src}, {"m.py": after})
    hunks = [ln for ln in patch.splitlines() if ln.startswith("@@ ")]
    assert len(hunks) == 2 and hunks[0].startswith("@@ -1,"), patch     # big()'s two changes: separate hunks
    entries, _ = F.plan_entries(patch, {"m.py": src})
    assert [F.entry_text(e) for e in entries] == ["m.py:3-19 (big)", "m.py:26-26 (other)"]
    assert F.notes_changed(entries) == "CHANGED: m.py big (3-19); m.py other (26-26)"


def test_plan_entry_for_pure_insertion_and_decorator_range(tmp_path):
    after = SRC.replace("    @property\n", "    extra = 2\n\n    @property\n")
    patch = _diff(tmp_path / "a", {"m.py": SRC}, {"m.py": after})
    assert "@@ -6,0 +7,2 @@" in patch or "\n+    extra = 2\n+\n" in patch
    (e,), _ = F.plan_entries(patch, {"m.py": SRC})
    assert (e["start"], e["end"], e["qualname"]) == (6, 6, "Box")      # inserted after line 6, inside class Box
    deco = SRC.replace("    @property\n", "    @functools.cached_property\n")
    (e,), _ = F.plan_entries(_diff(tmp_path / "b", {"m.py": SRC}, {"m.py": deco}), {"m.py": SRC})
    assert (e["start"], e["qualname"]) == (7, "Box.area")               # a decorator line belongs to its function


def test_plan_entries_hunk_header_fallback_without_snapshot():
    patch = ("--- a/m.py\n+++ b/m.py\n@@ -10,4 +10,4 @@ class Box:\n     def grow(self, n):\n         y = 1\n"
             "-        return y\n+        return y + n\n")
    entries, basis = F.plan_entries(patch, {})
    assert basis == "hunk_header" and F.entry_text(entries[0]) == "m.py:12-12 (grow)"
    patch2 = "--- a/m.py\n+++ b/m.py\n@@ -3,2 +3,2 @@ class Box:\n     a = 1\n-    b = 2\n+    b = 3\n"
    assert F.entry_text(F.plan_entries(patch2, {})[0][0]) == "m.py:4-4 (Box)"
    patch3 = "--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,2 @@\n a = 1\n-b = 2\n+b = 3\n"
    assert F.entry_text(F.plan_entries(patch3, {})[0][0]) == "m.py:2-2 (module level)"


def test_plan_more_than_six_places_and_word_cap():
    ents = [{"file": f"p/f{i % 3}.py", "start": i, "end": i, "qualname": f"f{i}", "new_file": False, "nstart": i,
             "nend": i} for i in range(1, 10)]
    line = F.files_line(ents)
    assert line.startswith("FILES: p/f1.py:1-1 (f1), ") and line.count("(f") == 6
    assert line.endswith("and 3 more places in p/f1.py, p/f2.py, p/f0.py")
    long_cause = " ".join(f"word{i}" for i in range(60)) + "."
    plan, info = F.make_plan(ents, long_cause, "Do the thing.", True, "tests/test_x.py")
    assert F.plan_words(plan) <= F.PLAN_WORDS_MAX
    assert plan.split("\n")[0].startswith("FILES:") and [ln.split(":")[0] for ln in plan.split("\n")] == \
        ["FILES", "CAUSE", "FIX", "REPRO", "TESTS"]
    assert len(F.plan_line(plan, "CAUSE").split()) == 35 and info["files_keep"] == 6
    huge = [dict(e, file="p/" + "x" * 3 + f"{i}.py") for i, e in enumerate(ents * 4)]
    fix = " ".join(["w"] * 60)
    plan2, info2 = F.make_plan(huge, long_cause, fix, False, "none")
    assert info2["cause_words"] == 20 and info2["files_keep"] in (3, 1)
    assert "REPRO: none" in plan2 and "REPRO: fails on original" in F.make_plan(ents, "C.", "F.", True, "none")[0]


def test_plan_names_the_functions_of_cut_entries():
    """Regression 2026-09-30: the 6-entry FILES cap dropped gold functions from the golden plan, so the oracle L control
    failed its 'functions' check on fastapi_14306 (serialize_response, get_request_handler.app, ...) the first time
    fastapi ran; fastapi_15800, rich_3061 and rich_3930 had the same latent gap. Base: <= 6 entries, no tail. Edges:
    a cut function the plan already names elsewhere (tail unchanged, so older fixtures keep their sha), a name that
    only occurs inside a longer identifier, module-level and new-file entries, a qualname cut twice, and the word cap
    forcing a shorter FILES line (the tail then names more)."""
    def ent(i, q, f="p/a.py", new=False):
        return {"file": f, "start": i, "end": i, "qualname": q, "new_file": new, "nstart": i, "nend": i}
    six = [ent(i, f"f{i}") for i in range(1, 7)]
    plan, _ = F.make_plan(six, "C.", "F.", False, "none")
    assert "more places" not in plan and all(F.named(f"f{i}", plan) for i in range(1, 7))
    # the cut function is named in FIX already: the tail keeps its old form
    seven = six + [ent(7, "Box.apply")]
    plan, _ = F.make_plan(seven, "C.", "Call apply once.", False, "none")
    assert plan.split("\n")[0].endswith("and 1 more places in p/a.py")
    # not named: 'app' inside get_websocket_app does not count; a cut module-level / new-file entry adds nothing
    cut = six + [ent(7, None), ent(8, "get_request_handler.app", "p/r.py"), ent(9, "get_websocket_app.app", "p/r.py"),
                 ent(10, None, "p/new.py", new=True), ent(11, "get_request_handler.app", "p/r.py"),
                 ent(12, "Err.__str__")]
    plan, info = F.make_plan(cut, "C.", "Touch get_websocket_app.", False, "none")
    first = plan.split("\n")[0]
    assert first.endswith("and 6 more places in p/a.py, p/r.py, p/new.py "
                          "(get_request_handler.app, get_websocket_app.app, Err.__str__)"), first
    names = [g["name"] for g in F.gold_functions(cut)]
    assert names and all(F.named(n, plan) for n in names) and info["files_keep"] == 6
    assert F.plan_words(plan) <= F.PLAN_WORDS_MAX
    assert not F.named("app", "get_websocket_app") and F.named("__str__", "Err.__str__")
    # the word cap shrinks FILES to 3 entries: the functions of entries 4-6 are then named in the tail too
    many = [ent(i, f"handler_{i}") for i in range(1, 9)]
    plan, info = F.make_plan(many, " ".join(["w"] * 40) + ".", " ".join(["x"] * 75), False, "none")
    assert info["files_keep"] == 3 and all(F.named(f"handler_{i}", plan) for i in range(1, 9)), plan
    assert F.plan_words(plan) <= F.PLAN_WORDS_MAX
    assert plan.split("\n")[0].endswith("(handler_4, handler_5, handler_6, handler_7, handler_8)")


def test_committed_golden_plans_name_every_gold_function():
    """The oracle L control's 'functions' check, on every committed fixture (dev and holdout, read-only): the golden
    plan names each gold function, and stays within 120 words."""
    fx = json.loads((ROOT / "eval" / "golden" / "fixtures" / "task_fixtures.json").read_text())["tasks"]
    bad = {t: [g["name"] for g in f["gold_functions"] if not F.named(g["name"], f["plan"])] for t, f in fx.items()}
    assert not {t: m for t, m in bad.items() if m}
    assert all(F.plan_words(f["plan"]) <= F.PLAN_WORDS_MAX for f in fx.values())


def test_first_sentence_and_cut_words():
    assert F.first_sentence("Foo breaks, e.g. on Bar. Then more.") == "Foo breaks, e.g. on Bar."
    assert F.first_sentence("It matched OSC (ESC ] ... ESC \\) only. Next") == "It matched OSC (ESC ] ... ESC \\) only."
    assert F.first_sentence("calls getattr(call, '__globals__'). For a wrapper") == "calls getattr(call, '__globals__')."
    assert F.first_sentence("no period at all") == "no period at all"
    assert F.cut_words("a b c d", 2) == "a b"


def test_tests_line_rules():
    tp = ("--- /dev/null\n+++ b/tests/test_new.py\n@@ -0,0 +1 @@\n+x = 1\n"
          "--- a/tests/conftest.py\n+++ b/tests/conftest.py\n@@ -1 +1 @@\n-a\n+b\n"
          "--- a/tests/test_old.py\n+++ b/tests/test_old.py\n@@ -1 +1 @@\n-a\n+b\n")
    assert F.tests_line(tp, ["pkg/mod.py"], lambda p: True) == "tests/test_old.py"
    assert F.tests_line(tp, ["pkg/mod.py"], lambda p: p == "tests/test_mod.py") == "tests/test_mod.py"
    assert F.tests_line(tp, ["pkg/mod.py"], lambda p: False) == "none"


def test_title_words_are_shell_safe():
    assert F.title_words('\n  Fix `Console.print` "$HOME" \\n it\'s\nbody') == "Fix Console.print HOME n its"
    assert len(F.title_words("x" * 200)) == 80


# =====================================================================================================================
# leak rules
# =====================================================================================================================
def _known(issue="", repo_text="", paths=""):
    has, word, p = F.text_known([repo_text], [paths])
    return F.Known(issue, has, word, p)


GOLD = ("--- a/pkg/m.py\n+++ b/pkg/m.py\n@@ -1,3 +1,4 @@\n def f(x):\n-    return x\n"
        "+    cleaned = _brand_new_helper(x)\n+    return cleaned if x is not None else default_value()\n")
TP = ("--- /dev/null\n+++ b/tests/test_m.py\n@@ -0,0 +1,2 @@\n+def test_hidden_expectation_name():\n"
      "+    assert f('secret-input-value') == 'secret-output'\n")


def _plan(cause, fix, tests="none"):
    return F.render_plan("FILES: pkg/m.py:2-2 (f)", cause, fix, False, tests)


def test_rule1_catches_added_code_and_exempts_old_side_and_issue():
    k = _known(issue="f returns x unchanged", repo_text="def f(x):\n    return x\n")
    bad = F.leak_check(_plan("f returns x unchanged.", "Return `cleaned if x is not None else default`."), GOLD, "",
                       "f returns x unchanged", k)
    assert [v["rule"] for v in bad if v["rule"] == 1] and any("if x is not None" in v["text"] for v in bad)
    ok = F.leak_check(_plan("f returns x unchanged.", "Guard f against None input."), GOLD, "",
                      "f returns x unchanged", k)
    assert ok == []
    # a 12+ char code fragment that is in the issue is allowed
    iss = "please use cleaned if x is not None"
    k2 = _known(issue=iss, repo_text="def f(x):\n    return x\n")
    assert not [v for v in F.leak_check(_plan("C.", "Use cleaned if x is not None there."), GOLD, "", iss, k2)
                if v["rule"] == 1]


def test_rule2_stdlib_name_passes_gold_only_name_fails():
    k = _known(issue="wrapped functions break", repo_text="def f(x):\n    return x\n")
    plan = _plan("f ignores wrappers.", "Call inspect.unwrap and typing.get_type_hints on it.")
    assert [v for v in F.leak_check(plan, GOLD, "", "wrapped functions break", k) if v["rule"] == 2] == []
    plan = _plan("f ignores wrappers.", "Add _brand_new_helper and call it.")
    names = [v["text"] for v in F.leak_check(plan, GOLD, "", "wrapped functions break", k) if v["rule"] == 2]
    assert names == ["_brand_new_helper"]
    assert F.stdlib_name("inspect.unwrap") and F.stdlib_name("os.path.join") and F.stdlib_name("__wrapped__")
    assert not F.stdlib_name("inspect.no_such_thing") and not F.stdlib_name("rich.console.Console")


def test_rule2_token_shapes():
    assert F.plan_identifiers("Use `a + b` in foo_bar, Pkg.mod and camelCase; EVERY BOTH PR plain") == \
        ["a + b", "foo_bar", "Pkg.mod", "camelCase"]
    k = _known(repo_text="alpha beta")
    assert k.name("alpha.beta") and not k.name("alpha.gamma") and k.name("len(alpha)") and not k.name("gamma(x)")


def test_rule3_catches_hidden_test_content_but_not_repo_names():
    k = _known(repo_text="def f(x):\n    return x\n", paths="pkg/m.py")
    bad = F.leak_check(_plan("f fails on 'secret-input-value'.", "Fix f."), GOLD, TP, "", k)
    assert [v for v in bad if v["rule"] == 3 and "secret-input-value" in v["text"]]
    assert not F.leak_check(_plan("f fails on some input.", "Fix f."), GOLD, TP, "", k)


def test_leak_rules_ignore_files_line_by_construction():
    k = _known(repo_text="def f(x):\n    return x\n")
    plan = F.render_plan("FILES: pkg/_brand_new_helper_module.py (new file)", "C.", "Fix f.", False, "none")
    gold = GOLD + "--- /dev/null\n+++ b/pkg/_brand_new_helper_module.py\n@@ -0,0 +1 @@\n+X = 1\n"
    assert F.leak_check(plan, gold, "", "", k) == []


def test_name_fragment_judged_by_enclosing_token():
    gold = "--- a/m.py\n+++ b/m.py\n@@ -1 +1,2 @@\n x = 1\n+except BrokenPipeError:\n"
    k = _known(repo_text="x = 1")
    assert F.leak_check(_plan("No BrokenPipeError handling.", "Handle it."), gold, "", "", k) == []
    assert F.enclosing_tokens("a BrokenPipeError. b", "rokenPipeError") == ["BrokenPipeError"]


def test_override_applied_and_rechecked():
    k = _known(issue="", repo_text="def f(x):\n    return x\n")
    ents = [{"file": "pkg/m.py", "start": 2, "end": 2, "qualname": "f", "new_file": False, "nstart": 2, "nend": 3}]
    tmpl, _ = F.make_plan(ents, "f returns x.", "`cleaned if x is not None else default_value()`", False, "none")
    assert F.leak_check(tmpl, GOLD, "", "", k)
    good, _ = F.make_plan(ents, "f returns x.", "x", False, "none", {"FIX": "Guard f against a None input."})
    assert "FIX: Guard f against a None input." in good and F.leak_check(good, GOLD, "", "", k) == []
    still, _ = F.make_plan(ents, "f returns x.", "x", False, "none", {"FIX": "Call _brand_new_helper."})
    assert F.leak_check(still, GOLD, "", "", k)                       # an override is re-checked, never trusted


@pytest.fixture(scope="module")
def statics():
    """static_task for the 9 v1 leak tasks (real data; the base workspaces are built on demand)."""
    import build_fixtures as B
    ctx = B.Ctx()
    return ctx, {t: B.static_task(ctx, t) for t in NINE}


def test_the_nine_known_leaks_caught_by_rule_1(statics):
    _ctx, sts = statics
    for tid in NINE:
        assert [v for v in sts[tid]["template_leaks"] if v["rule"] == 1], tid


def test_committed_overrides_cover_every_leak_and_leave_none(statics):
    import concurrent.futures as cf

    import build_fixtures as B
    ctx = statics[0]
    assert B.check_overrides(ctx.overrides, ctx.ids) == []
    missing = [t for t in ctx.ids if not ctx.T.has_snapshot(t)]
    if missing:                       # without a snapshot, rule 2 sees only the patch context (RepoIndex): false leaks
        pytest.skip(f"rule-2 lookups grep each task's base workspace; {len(missing)} of {len(ctx.ids)} snapshots absent "
                    f"(gitignored data/raw/snapshots), e.g. {missing[0]}")
    left = {}
    with cf.ThreadPoolExecutor(6) as ex:
        all_st = dict(zip(ctx.ids, ex.map(lambda t: B.static_task(ctx, t), ctx.ids)))
    for tid in ctx.ids:
        st = all_st[tid]
        if st["template_leaks"]:
            assert st["override"], f"{tid} leaks with no override: {st['template_leaks']}"
        for rep in (True, False):
            leaks = B.final_plan(st, rep)[2]
            if leaks:
                left[tid] = leaks
    assert left == {}
    raw = json.loads(F.OVERRIDES_FILE.read_text())
    for tid, ov in raw.items():
        if tid.startswith("_"):
            continue
        for key in ("FIX", "CAUSE"):                 # words, never code: no backticks, no call syntax
            text = ov.get(key, "")
            assert "`" not in text and "==" not in text and "()" not in text, (tid, key)


def test_check_overrides_rejects_bad_entries():
    import build_fixtures as B
    errs = B.check_overrides({"nope_1": {"FIX": "x", "why": "y"}, "rich_3006": {"why": "y"},
                              "rich_3278": {"FIX": "x"}, "rich_3470": {"FIX": "x", "why": "y", "CODE": "z"}},
                             ["rich_3006", "rich_3278", "rich_3470"])
    assert len(errs) == 4


def test_plan_never_reads_hidden_test_demands(statics):
    import build_fixtures as B
    ctx = statics[0]
    tid = "rich_3278"
    a = B.final_plan(B.static_task(ctx, tid), True)[0]
    keep = ctx.catalog[tid]
    try:
        ctx.catalog[tid] = dict(keep, hidden_test_demands="SENTINEL_HIDDEN_DEMANDS " * 20)
        b = B.final_plan(B.static_task(ctx, tid), True)[0]
    finally:
        ctx.catalog[tid] = keep
    assert a == b and "SENTINEL" not in b


# =====================================================================================================================
# repro extraction (4.2, gotcha 11) and t0 (gotcha 22)
# =====================================================================================================================
def _step(sid, author, command=None, obs="", text=None):
    s = {"step_id": sid, "source": "agent", "extra": {"author": author}}
    if command is not None:
        s["tool_calls"] = [{"tool_call_id": f"c{sid}", "function_name": "run_command",
                            "arguments": {"command": command}, "extra": {"author": author}}]
        s["observation"] = {"content": obs}
    else:
        s["message"] = text or "done"
    return s


def _repro_cmd(body):
    return f"python3 /tmp/swe/verify.py --repro-only <<'EOF'\n{body}EOF"


def test_repro_extraction_picks_last_failing_locator_heredoc():
    tr = {"steps": [
        {"step_id": 1, "source": "user", "message": "task"},
        _step(2, "setup", "x", obs="swe-tools v10.0 ready in /tmp/swe (9 helpers).\n[t=2s]"),
        _step(3, "locator", _repro_cmd("assert 1 == 2  # A\n"), obs='{"stdout": "REPRO: fails on original (1 of 1)"}'),
        _step(4, "locator", _repro_cmd("assert 1 == 3  # B\n"), obs="REPRO: claim 1 hangs on original (expected)"),
        _step(5, "locator", _repro_cmd("assert 1 == 1  # C\n"), obs="REPRO: claim 1 passes on original - it misses"),
        _step(6, "locator", "python3 /tmp/swe/run.py \"python3 /tmp/swe/verify.py --repro-only <<'EOF'\"",
              obs="REPRO: fails on original"),
        _step(7, "locator", text="FILES: x"),
        _step(8, "fixer", _repro_cmd("assert 0  # D\n"), obs="REPRO: fails on original"),
    ]}
    got = F.extract_repro(tr)
    assert got["body"] == "assert 1 == 3  # B\n" and got["step_id"] == 4 and got["verdict"] == "hangs"
    assert F.extract_repro({"steps": tr["steps"][:3]})["verdict"] == "fails"
    assert F.extract_repro({"steps": tr["steps"][4:6]}) is None


def test_heredoc_body_bash_semantics():
    assert F.heredoc_body("python3 /tmp/swe/verify.py --repro-only <<'EOF'\na\nEOF") == "a\n"
    assert F.heredoc_body("python3 /tmp/swe/verify.py --repro-only <<'EOF'\na\nEOF\nb\nEOF") == "a\n"
    assert F.heredoc_body("python3 /tmp/swe/verify.py --repro-only << \"PY\"\nx\n  EOF\nPY") == "x\n  EOF\n"
    assert F.heredoc_body("python3 /tmp/swe/verify.py --repro-only <<'EOF'\nno terminator") == "no terminator\n"
    assert F.heredoc_body("python3 /tmp/swe/verify.py <<'EOF'\na\nEOF") is None


def test_t0_counts_only_tasks_where_the_stage_ran():
    def trace(ts, verifier):
        steps = [_step(1, "setup", "i", obs=f"[t={ts[0]}s]"), _step(2, "locator", "l", obs=f"[t={ts[1]}s]"),
                 _step(3, "fixer", "f", obs=f"x [t={ts[2]}s] y [t={ts[3]}s]")]
        if verifier:
            steps.append(_step(4, "verifier", "v", obs="[t=200s]"))
        return {"steps": steps}
    t0 = F.compute_t0({"a": trace((2, 40, 80, 95), True), "b": trace((4, 60, 290, 300), False)})
    assert t0["L"] == {"t0": 3, "n": 2} and t0["F"] == {"t0": 50, "n": 2}
    assert t0["V"] == {"t0": 95, "n": 1}              # b's verifier never started: its fixer footer (300) is not used
    assert F.compute_t0({"a": trace((2, 41, 80, 95), False), "b": trace((2, 40, 80, 95), False)})["F"]["t0"] == 40.5


def test_t0_recorded_in_manifest_matches_traces():
    man = json.loads(F.MANIFEST_FILE.read_text())
    traces = {t: F.load_trace(t) for t in F.load_ids()}
    assert man["t0"] == F.compute_t0({k: v for k, v in traces.items() if v})
    assert {s: man["t0"][s]["t0"] for s in "LFV"} == {"L": 2, "F": 47, "V": 91}
    assert {s: man["t0"][s]["n"] for s in "LFV"} == {"L": 74, "F": 73, "V": 69}


# =====================================================================================================================
# replay steps (4.4, gotchas 6 and 20)
# =====================================================================================================================
def _replay_case(tmp_path, before: dict, after: dict, expect_mode: str):
    patch = _diff(tmp_path / "d", before, after)
    rp = F.build_replay(patch)
    assert rp["replay"] == expect_mode, (rp["why"], patch)
    ws = RP.make_repo(tmp_path / "r", before)
    env = RP.helper_env(ws, tmp_path / "r" / "sbx" / "swe", fake_t=20)
    res = F.replay_in_ws(ws, env, rp["steps"], patch, rp["replay"])
    assert res["ok"], (res, rp["steps"])
    return rp, res


BASE = {"pkg/__init__.py": "", "pkg/m.py": "".join(f"v{i} = {i}\n" for i in range(1, 41))}


def test_replay_edit_modify_insert_delete_create_bottom_up(tmp_path):
    m = BASE["pkg/m.py"]
    after = m.replace("v2 = 2\n", "v2 = 20\nv2b = 21\n").replace("v15 = 15\n", "").replace("v30 = 30\n",
                                                                                         "v30 = 30\nv30b = 1\n")
    rp, res = _replay_case(tmp_path, BASE, {**BASE, "pkg/m.py": after, "pkg/new.py": "x = 1\n\ny = 2\n"}, "edit")
    cmds = [s["args"]["command"] for s in rp["steps"]]
    assert len(cmds) == 4
    assert cmds[0] == "python3 /tmp/swe/edit.py pkg/m.py --insert-after 30 <<'EOF'\nv30b = 1\nEOF"
    assert cmds[1] == "python3 /tmp/swe/edit.py pkg/m.py --lines 15-15 --delete"
    assert cmds[2] == "python3 /tmp/swe/edit.py pkg/m.py --lines 2-2 <<'EOF'\nv2 = 20\nv2b = 21\nEOF"
    assert cmds[3] == "python3 /tmp/swe/edit.py pkg/new.py --create <<'EOF'\nx = 1\n\ny = 2\nEOF"
    assert all(f.startswith("OK") for f in res["firsts"])


def test_replay_trailing_blank_line_and_no_newline_at_eof(tmp_path):
    m = BASE["pkg/m.py"]
    rp, _ = _replay_case(tmp_path / "a", BASE, {**BASE, "pkg/m.py": m.replace("v3 = 3\n", "v3 = 30\n\n")}, "edit")
    assert rp["steps"][0]["args"]["command"].endswith("v3 = 30\n\nEOF")
    noeol = {"pkg/m.py": m[:-1]}                                     # "v40 = 40" without a final newline
    rp1, _ = _replay_case(tmp_path / "b", noeol, {"pkg/m.py": noeol["pkg/m.py"].replace("v38 = 38", "v38 = 380")},
                          "edit")
    assert "\\ No newline at end of file" in _diff(tmp_path / "e", noeol, {"pkg/m.py": noeol["pkg/m.py"].replace(
        "v38 = 38", "v38 = 380")})
    rp2, _ = _replay_case(tmp_path / "c", noeol, {"pkg/m.py": noeol["pkg/m.py"].replace("v40 = 40", "v40 = 400")},
                          "git_apply")
    assert "no newline at end of file" in rp2["why"]


@pytest.mark.parametrize("new_line,why", [
    ("p = '/tmp/x'", "/tmp"), ("p = '/workspace/y'", "/workspace"), ("p = '/usr/local/bin/z'", "/usr/local/bin"),
    ("p = '/wheels/w'", "/wheels")])
def test_rewrite_sensitive_body_forces_base64_fallback(tmp_path, new_line, why):
    m = BASE["pkg/m.py"]
    rp, _ = _replay_case(tmp_path, BASE, {**BASE, "pkg/m.py": m.replace("v4 = 4\n", new_line + "\n")}, "git_apply")
    assert why in rp["why"]
    cmd = rp["steps"][0]["args"]["command"]
    assert all(x not in cmd for x in F.REWRITTEN) and "base64.b64decode(" in cmd


@pytest.mark.parametrize("body,why", [
    ("EOF", "exactly EOF"), ("=======", "SEARCH/REPLACE marker"), ("<<<<<<< SEARCH", "SEARCH/REPLACE marker"),
    ("x = 1\r", "CR")])
def test_heredoc_hostile_body_forces_fallback(tmp_path, body, why):
    m = "'''doc\nTitle\n-----\n'''\na = 1\nb = 2\nc = 3\n"
    after = m.replace("b = 2\n", f"b = 2\n{body}\n") if body != "x = 1\r" else m.replace("b = 2\n", "b = 2\r\n")
    files = {"doc.txt": m}                                           # a text file: edit.py's compile check is moot
    rp, _ = _replay_case(tmp_path, files, {"doc.txt": after}, "git_apply")
    assert why in rp["why"], rp["why"]


def test_file_delete_and_rename_force_fallback(tmp_path):
    rp, _ = _replay_case(tmp_path / "d", BASE, {"pkg/__init__.py": ""}, "git_apply")
    assert "deletes a file" in rp["why"]
    ws = RP.make_repo(tmp_path / "r", BASE)
    RP.git(ws, "mv", "pkg/m.py", "pkg/renamed.py")
    patch = RP.git(ws, "diff", "--cached", "-M", "_swegemma_baseline")
    assert "rename from" in patch
    rp2 = F.build_replay(patch)
    assert rp2["replay"] == "git_apply" and "renames a file" in rp2["why"]
    ws2 = RP.make_repo(tmp_path / "r2", BASE)
    env = RP.helper_env(ws2, tmp_path / "r2" / "sbx" / "swe", fake_t=20)
    assert F.replay_in_ws(ws2, env, rp2["steps"], patch, "git_apply")["ok"]


def test_mode_only_and_binary_sections_force_fallback():
    mode = "diff --git a/s.sh b/s.sh\nold mode 100644\nnew mode 100755\n"
    binary = "diff --git a/x.bin b/x.bin\nindex 1..2 100644\nGIT binary patch\nliteral 1\nIcmZ?l0000\n\n"
    assert "mode change" in F.build_replay(mode)["why"] and "binary" in F.build_replay(binary)["why"]
    assert F.build_replay("")["replay"] == "none"


def test_base64_fallback_chunks_large_patches(tmp_path):
    m = BASE["pkg/m.py"]
    patch = _diff(tmp_path / "d", BASE, {**BASE, "pkg/m.py": m.replace("v4 = 4\n", "p = '/tmp/" + "q" * 300 + "'\n")})
    steps = F.git_apply_steps(patch, chunk=100)
    assert len(steps) > 3 and all(len(s["args"]["command"]) < 200 for s in steps[:-1])
    ws = RP.make_repo(tmp_path / "r", BASE)
    env = RP.helper_env(ws, tmp_path / "r" / "sbx" / "swe", fake_t=20)
    assert F.replay_in_ws(ws, env, steps, patch, "git_apply")["ok"]
    assert not (ws / F.B64_FILE).exists()
    one = F.git_apply_steps("x\n")[0]["args"]["command"]
    assert base64.b64encode(b"x\n").decode() in one and one.startswith('python3 -c "import base64,subprocess,sys;')


def test_replay_validation_rejects_wrong_steps(tmp_path):
    m = BASE["pkg/m.py"]
    patch = _diff(tmp_path / "d", BASE, {**BASE, "pkg/m.py": m.replace("v2 = 2\n", "v2 = 20\n")})
    ws = RP.make_repo(tmp_path / "r", BASE)
    env = RP.helper_env(ws, tmp_path / "r" / "sbx" / "swe", fake_t=20)
    bad = [F._step("python3 /tmp/swe/edit.py pkg/m.py --lines 3-3 <<'EOF'\nv2 = 20\nEOF")]
    res = F.replay_in_ws(ws, env, bad, patch, "edit")
    assert not res["ok"] and "changed lines differ" in res["why"]


def test_notes_changed_line():
    ents = [{"file": "a.py", "start": 3, "end": 4, "qualname": "C.m", "new_file": False, "nstart": 3, "nend": 5},
            {"file": "b.py", "start": 0, "end": 0, "qualname": None, "new_file": True, "nstart": 1, "nend": 9},
            {"file": "a.py", "start": 1, "end": 1, "qualname": None, "new_file": False, "nstart": 1, "nend": 1}]
    assert F.notes_changed(ents) == ("CHANGED: a.py C.m (3-5); b.py new file (1-9); a.py module level (1-1)")
    assert F.notes_changed([]) == "CHANGED: nothing"


# =====================================================================================================================
# wrong patch (4.3)
# =====================================================================================================================
def _p(path, old="a", new="b", n=1):
    return (f"diff --git a/{path} b/{path}\nindex 1..2 100644\n--- a/{path}\n+++ b/{path}\n@@ -{n} +{n} @@\n"
            f"-{old}\n+{new}\n")


def test_protected_sections_stripped_before_qualification():
    text = _p("tests/test_x.py") + _p("pkg/m.py", new="c") + _p("conftest.py")
    kept, dropped = F.strip_protected(text)
    assert dropped == ["tests/test_x.py", "conftest.py"] and [s.path for s in F.sections(kept)] == ["pkg/m.py"]
    recs = F.static_wrong([{"source": "s1", "raw": _p("tests/test_x.py")},
                           {"source": "s2", "raw": _p("tests/test_x.py") + _p("pkg/m.py", new="c")}],
                          _p("pkg/m.py", new="gold"), ["pkg/m.py"])
    assert recs[0]["status"] == "rejected" and "empty after dropping protected" in recs[0]["why"]
    assert recs[1]["status"] == "candidate" and recs[1]["dropped"] == ["tests/test_x.py"]


def test_static_rejections_and_pick_order():
    gold = _p("pkg/m.py", new="gold")
    cands = [{"source": "r2_v10_1", "raw": _p("docs/readme.md")},                 # no .py source file
             {"source": "r2_v9_eog_1", "raw": gold},                              # equals gold
             {"source": "g4-l4-v9-eog", "raw": _p("pkg/other.py", new="x")},      # not a gold file
             {"source": "g4-l4-v4", "raw": _p("pkg/m.py", new="near")},           # near miss on the gold file
             {"source": "dup", "raw": _p("pkg/m.py", new="near")},                # identical to the one above
             {"source": "scratch", "raw": "diff --git a/repro.py b/repro.py\nnew file mode 100644\n--- /dev/null\n"
                                          "+++ b/repro.py\n@@ -0,0 +1 @@\n+x\n"}]
    recs = F.static_wrong(cands, gold, ["pkg/m.py"])
    st = [(r["source"], r["status"], r["why"]) for r in recs]
    assert st[0][1:] == ("rejected", "touches no non-test source file")
    assert st[1][1:] == ("rejected", "changed lines equal gold")
    assert st[4][1:] == ("rejected", "same patch as g4-l4-v4")
    assert st[5][1:] == ("rejected", "touches no non-test source file")
    assert [r["source"] for r in F.pick_order(recs)] == ["g4-l4-v4", "g4-l4-v9-eog"]    # gold-file-touching first


def test_select_wrong_exec_rejections_and_pick():
    gold = _p("pkg/m.py", new="gold")
    cands = [{"source": s, "raw": _p("pkg/m.py", new=s)} for s in ("noapply", "passes", "asgold", "crash", "good",
                                                                    "later")]
    recs = F.static_wrong(cands, gold, ["pkg/m.py"])

    def canonical(patch):
        if "+noapply" in patch:
            return {"applies": False, "why": "does not apply: hunk failed", "patch": ""}
        if "+asgold" in patch:
            return {"applies": True, "why": "", "patch": gold}
        return {"applies": True, "why": "", "patch": patch}

    def verify(canon):
        if "+crash" in canon:
            return {"error": "pytest.skipped: parity venv missing"}
        return {"pass": "+passes" in canon, "why": "pytest exit 1: 2 failed", "retried": False}
    picked = F.select_wrong(recs, gold, canonical, verify)
    st = {r["source"]: (r["status"], r["why"]) for r in recs}
    assert picked["source"] == "good" and picked["canonical"].count("+good") == 1
    assert st["noapply"] == ("rejected", "does not apply: hunk failed")
    assert st["passes"] == ("rejected", "passes the hidden tests")
    assert st["asgold"] == ("rejected", "changed lines equal gold after applying")
    assert st["crash"][0] == "rejected" and "crashed" in st["crash"][1]
    assert st["later"] == ("not_evaluated", "a higher-priority candidate qualified")
    none = F.static_wrong([{"source": "x", "raw": _p("pkg/m.py", new="p")}], gold, ["pkg/m.py"])
    assert F.select_wrong(none, gold, canonical, lambda c: {"pass": True, "why": "", "retried": False}) is None


def _guard_env(ws, d):
    """A helper env whose install finds the workspace (PWD, as tasks.sandbox_env sets it; install runs from the temp
    skill copy, so without PWD it arms no guard)."""
    return RP.helper_env(ws, d / "sbx" / "swe", fake_t=20, PWD=str(ws))


def test_canonical_drops_what_the_submit_guard_hides_and_then_replays(tmp_path):
    """Regression (rich_3180, rich_3894): a recorded wrong patch that creates a root scratch file (reproduce_*.py) can
    never be submitted by v10.1 (the submit guard's exclude file keeps it out of `git add -N .`), so its replay could
    never validate. The canonical tree patch is the guard-armed submit diff: scratch gone, recorded as unsubmittable,
    and the replay of the canonical patch validates."""
    m = BASE["pkg/m.py"]
    raw = _diff(tmp_path / "d", BASE, {**BASE, "pkg/m.py": m.replace("v5 = 5\n", "v5 = 50\n"),
                                       "reproduce_bug.py": "import pkg.m\nprint(pkg.m.v5)\n"})
    assert "reproduce_bug.py" in F.changed_paths(raw)
    ws = RP.make_repo(tmp_path / "c", BASE)
    env = _guard_env(ws, tmp_path / "c")
    cn = F.canonical_in_ws(ws, env, raw)
    assert cn["applies"] and cn["unsubmittable"] == ["reproduce_bug.py"]
    assert F.changed_paths(cn["patch"]) == ["pkg/m.py"] and "+v5 = 50" in cn["patch"]
    for label, patch, ok in (("raw", raw, False), ("canonical", cn["patch"], True)):
        rp = F.build_replay(patch)
        ws2 = RP.make_repo(tmp_path / label, BASE)
        env2 = _guard_env(ws2, tmp_path / label)
        res = F.replay_in_ws(ws2, env2, rp["steps"], patch, rp["replay"])
        assert res["ok"] is ok, (label, res)
    # a candidate that is only scratch plus a test edit is rejected after applying, never picked
    only = _diff(tmp_path / "o", BASE, {**BASE, "repro.py": "x = 1\n"})
    ws3 = RP.make_repo(tmp_path / "c3", BASE)
    cn3 = F.canonical_in_ws(ws3, _guard_env(ws3, tmp_path / "c3"), only)
    assert cn3["applies"] and cn3["patch"] == "" and cn3["unsubmittable"] == ["repro.py"]


def test_select_wrong_rejects_candidates_the_guard_empties():
    gold = _p("pkg/m.py", new="gold")
    recs = F.static_wrong([{"source": "a", "raw": _p("pkg/m.py", new="a")}, {"source": "b", "raw": _p("pkg/m.py",
                                                                                                    new="b")}],
                          gold, ["pkg/m.py"])

    def canonical(patch):
        if "+a" in patch:
            return {"applies": True, "why": "", "patch": "", "unsubmittable": ["pkg/m.py"]}
        return {"applies": True, "why": "", "patch": _p("docs/x.md"), "unsubmittable": ["pkg/m.py"]}
    assert F.select_wrong(recs, gold, canonical, lambda c: {"pass": False, "why": "x", "retried": False}) is None
    assert recs[0]["why"].startswith("no change after applying (the v10.1 submit guard")
    assert recs[0]["unsubmittable"] == ["pkg/m.py"]
    assert recs[1]["why"] == "touches no non-test source file after applying under the submit guard"


def test_submitted_part_keeps_only_candidate_paths():
    d = _p("a.py") + _p("b.py") + _p("c.py")
    assert F.submitted_part(d, {"a.py", "c.py"}) == _p("a.py") + _p("c.py")
    assert F.submitted_part("", {"a.py"}) == ""


def test_wrong_candidates_source_order(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "t_1.patch").write_text(_p("m.py"))
    (tmp_path / "r.jsonl").write_text(json.dumps({"id": "t_1", "patch": _p("n.py")}) + "\n"
                                      + json.dumps({"id": "t_2", "patch": ""}) + "\n")
    srcs = (("A", "patch_dir", tmp_path / "a"), ("B", "patch_dir", tmp_path / "missing"),
            ("C", "results", tmp_path / "r.jsonl"))
    assert [c["source"] for c in F.wrong_candidates("t_1", srcs)] == ["A", "C"]
    assert F.wrong_candidates("t_2", srcs) == []


# =====================================================================================================================
# gradability (4.5, gotcha 21) and pytest.skip containment (gotcha 12)
# =====================================================================================================================
def test_mini_verify_called_with_timeout_180_and_flaky_retry(monkeypatch):
    calls = []
    outcomes = iter([(False, "pytest exit 1: 1 failed, 90 passed in 3.2s", 1.0), (True, None, 1.0)])

    def fake_mv(ws, patch, test_patch, **kw):
        calls.append(kw)
        return next(outcomes)
    monkeypatch.setattr(T, "mini_verify", fake_mv)
    monkeypatch.setattr(T, "base_ws", lambda tid, with_test_patch=False: Path("/nonexistent"))
    monkeypatch.setattr(F, "x_failing_nodes", lambda tid, patch: [("tests.test_console", "test_brokenpipeerror")])
    r = F.x_mini_verify("rich_3278", "patch")
    assert r == {"pass": True, "why": "", "retried": True}
    assert [c["timeout"] for c in calls] == [180, 180] and all(c["repo"] == "rich_3278" for c in calls)
    calls.clear()
    outcomes = iter([(False, "pytest exit 1: 1 failed, 90 passed in 3.2s", 1.0)])
    monkeypatch.setattr(F, "x_failing_nodes", lambda tid, patch: [("tests.test_console", "test_other")])
    assert F.x_mini_verify("rich_3278", "patch") == {"pass": False, "why": "pytest exit 1: 1 failed, 90 passed",
                                                      "retried": False}
    assert len(calls) == 1
    calls.clear()
    outcomes = iter([(False, "pytest exit 1: 3 failed, 90 passed", 1.0)])
    monkeypatch.setattr(F, "x_failing_nodes", lambda *a: pytest.fail("not needed when more fail than are flaky"))
    assert F.x_mini_verify("rich_3278", "patch")["retried"] is False


def _fake_pytest_run(outputs):
    """A tasks.run stand-in: str commands running pytest get the next scripted stdout."""
    import types
    it = iter(outputs)

    def run(cmd, *a, **kw):
        return types.SimpleNamespace(rc=1, out=next(it) if " -m pytest " in str(cmd) else "", err="", timed_out=False,
                                     secs=0.0)
    return run


def test_flaky_retry_reads_the_same_runs_failures(monkeypatch):
    """Regression (cold build, rich_3675): the KNOWN_FLAKY retry must be decided from the failing run's own pytest
    summary, not from a second identification run where the load-dependent flake may not recur."""
    grader = "cd /x && PYTHONSAFEPATH=1 python3 -s -m pytest tests/test_console.py --junitxml=j -q"
    flaky_out = "....F\nFAILED tests/test_console.py::test_brokenpipeerror - assert 0 == 1\n1 failed, 98 passed\n"
    other_out = "....F\nFAILED tests/test_console.py::test_other - boom\n1 failed, 98 passed\n"
    res = iter([(False, "pytest exit 1: 1 failed, 98 passed in 3.1s"), (True, None)])

    def fake_mv(ws, patch, test_patch, **kw):
        assert kw["timeout"] == 180
        T.run(grader, cwd="/x")
        r = next(res)
        return r[0], r[1], 1.0
    monkeypatch.setattr(T, "mini_verify", fake_mv)
    monkeypatch.setattr(T, "base_ws", lambda tid, with_test_patch=False: Path("/nonexistent"))
    monkeypatch.setattr(T, "run", _fake_pytest_run([flaky_out, "1 passed\n"]))
    monkeypatch.setattr(F, "x_failing_nodes", lambda *a: pytest.fail("the same run already named the failure"))
    assert F.x_mini_verify("rich_3675", "p") == {"pass": True, "why": "", "retried": True}
    # the same run names a real failure: no retry, even if a rerun would only have seen the flake
    res = iter([(False, "pytest exit 1: 1 failed, 98 passed")])
    monkeypatch.setattr(T, "run", _fake_pytest_run([other_out]))
    monkeypatch.setattr(F, "x_failing_nodes", lambda *a: [("test_console", "test_brokenpipeerror")])
    assert F.x_mini_verify("rich_3675", "p") == {
        "pass": False, "why": "pytest exit 1: 1 failed [tests/test_console.py::test_other]", "retried": False}


def test_failure_reason_is_independent_of_flakes():
    """A flake next to a real failure changes neither the outcome nor the committed reason (cold rebuilds of
    rich_3675 / rich_4075 recorded '2 failed, 97 passed' or '1 failed, 98 passed' by chance)."""
    flaky, a, b = "tests/test_console.py::test_brokenpipeerror", "tests/test_console.py::test_a", "tests/t.py::test_b"
    mixed = F.failure_reason("pytest exit 1: 2 failed, 97 passed", [flaky, a])
    clean = F.failure_reason("pytest exit 1: 1 failed, 98 passed", [a])
    assert mixed == clean == "pytest exit 1: 1 failed [tests/test_console.py::test_a]"
    assert F.failure_reason("pytest exit 1: 1 failed, 98 passed", [flaky]) == \
        "pytest exit 1: 1 failed, only known-flaky tests [tests/test_console.py::test_brokenpipeerror]"
    assert F.failure_reason("pytest exit 1: 4 failed", [a, b, "tests/t.py::c", "tests/t.py::d"]).endswith(
        "4 failed [tests/test_console.py::test_a, tests/t.py::test_b, tests/t.py::c, ...]")
    assert F.failure_reason("timeout after 180s (hang)", []) == "timeout after 180s (hang)"
    assert F.failure_reason("pytest exit 1: 1 failed, 9 passed in 0.3s", []) == "pytest exit 1: 1 failed, 9 passed"
    assert F.known_flaky_targets(["tests/test_console.py", "tests/test_x.py"]) == [flaky]
    assert F.known_flaky_targets(["tests/test_x.py"]) == []


def test_hidden_pass_repeats_a_flaky_node_alone(monkeypatch):
    calls = []
    flaky = "tests/test_console.py::test_brokenpipeerror"

    class Gate:
        def __init__(self, kind):
            self.kind = kind

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(F, "LOAD", type("L", (), {"shared": lambda self: Gate("shared"),
                                                  "exclusive": lambda self: Gate("exclusive")})())
    results = iter([{flaky: "fail", "tests/t.py::test_x": "pass"}, {flaky: "pass", "tests/t.py::test_x": "pass"}])

    def fake(tid, nodes, patch, gate):
        calls.append(gate.kind)
        return next(results)
    monkeypatch.setattr(F, "_hidden_outcomes", fake)
    assert F.x_hidden_pass("rich_3468", [flaky, "tests/t.py::test_x"], "p")["pass"] == 2
    assert calls == ["shared", "exclusive"]
    calls.clear()
    results = iter([{"tests/t.py::test_x": "fail"}])
    assert F.x_hidden_pass("rich_3468", ["tests/t.py::test_x"], "p")["pass"] == 0 and calls == ["shared"]


def test_pytest_output_tap_is_per_thread_and_restores_run(monkeypatch):
    import threading
    import time
    import types

    def slow_run(cmd, *a, **kw):
        time.sleep(0.05)
        return types.SimpleNamespace(out=f"out of {cmd}", rc=0, err="", timed_out=False, secs=0.0)
    monkeypatch.setattr(T, "run", slow_run)
    got = {}

    def worker(name):
        with F.pytest_output_tap() as outs:
            T.run(f"python3 -m pytest {name} ", cwd=".")
            T.run(["git", "status"])                             # argv lists (junit_cases, git) are not recorded
            got[name] = list(outs)
    ths = [threading.Thread(target=worker, args=(n,)) for n in ("a", "b", "c")]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    assert got == {n: [f"out of python3 -m pytest {n} "] for n in "abc"}
    assert T.run is slow_run and F._TAP["n"] == 0


def test_load_gate_runs_the_flaky_retry_alone():
    """The KNOWN_FLAKY retry holds the gate exclusively: it waits for in-flight runs and a reader that arrives while it
    waits enters only after it (writer preference), so the retry never shares the machine with the builder's runs."""
    import threading
    import time
    gate, order = F.LoadGate(), []
    release = threading.Event()

    def reader(name, hold=None):
        with gate.shared():
            order.append(name + "+")
            if hold:
                hold.wait(5)
            order.append(name + "-")

    def writer():
        with gate.exclusive():
            order.append("W+")
            assert gate.readers == 0
            order.append("W-")
    r1 = threading.Thread(target=reader, args=("R1", release))
    r1.start()
    while gate.readers != 1:
        time.sleep(0.005)
    w = threading.Thread(target=writer)
    w.start()
    while gate.waiting != 1:
        time.sleep(0.005)
    r2 = threading.Thread(target=reader, args=("R2",))
    r2.start()
    time.sleep(0.05)
    assert order == ["R1+"]                                   # the writer waits for R1; R2 waits behind the writer
    release.set()
    for th in (r1, w, r2):
        th.join(5)
    assert order == ["R1+", "R1-", "W+", "W-", "R2+", "R2-"]


def test_flaky_retry_takes_the_gate_exclusively(monkeypatch):
    seen = []

    class Gate:
        def shared(self):
            seen.append("shared")
            return F.contextlib.nullcontext()

        def exclusive(self):
            seen.append("exclusive")
            return F.contextlib.nullcontext()
    monkeypatch.setattr(F, "LOAD", Gate())
    res = iter([(False, "pytest exit 1: 1 failed, 9 passed"), (True, None)])

    def fake_mv(ws, patch, test_patch, **kw):
        T.run("python3 -s -m pytest tests/test_console.py -q")
        r = next(res)
        return r[0], r[1], 1.0
    monkeypatch.setattr(T, "mini_verify", fake_mv)
    monkeypatch.setattr(T, "base_ws", lambda tid, with_test_patch=False: Path("/nonexistent"))
    monkeypatch.setattr(T, "run", _fake_pytest_run(["FAILED tests/test_console.py::test_brokenpipeerror - x\n", ""]))
    assert F.x_mini_verify("rich_3675", "p")["retried"] is True and seen == ["shared", "exclusive"]


def test_failed_node_ids_and_flaky_rule():
    out = ("FAILED tests/test_console.py::test_brokenpipeerror - x\nERROR tests/test_a.py - ImportError\n"
           "FAILED tests/test_console.py::test_brokenpipeerror - again\n  FAILED not-at-line-start\n")
    assert F.failed_node_ids(out) == ["tests/test_console.py::test_brokenpipeerror", "tests/test_a.py"]
    assert F.all_known_flaky(["tests/test_console.py::test_brokenpipeerror"])
    assert F.all_known_flaky(["tests/test_console.py::test_brokenpipeerror[1]"])
    assert not F.all_known_flaky([]) and not F.all_known_flaky(F.failed_node_ids(out))


def test_known_flaky_mirrors_test_v10_flow():
    tree = ast.parse((ROOT / "tests" / "test_v10_flow.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "KNOWN_FLAKY")
    assert set(ast.literal_eval(node.value)) == set(F.KNOWN_FLAKY)


def test_gradable_rules():
    t = T.load_task("rich_3278")

    def mv_for(gold_ok, empty_ok):
        runs = iter(gold_ok)

        def mv(tid, patch):
            if patch == t["patch"]:
                return {"pass": next(runs), "why": "" if gold_ok else "fail", "retried": False}
            return {"pass": empty_ok, "why": "e", "retried": False}
        return mv
    g = F.x_gradable("rich_3278", mv=mv_for([True, True], False))
    assert g["gradable"] and g["gold_pass_runs"] == 2 and g["gradable_why"] == ""
    g = F.x_gradable("rich_3278", mv=mv_for([True, False], False))
    assert not g["gradable"] and g["gradable_why"].startswith("gold passed 1/2")
    g = F.x_gradable("rich_3278", mv=mv_for([True, True], True))
    assert not g["gradable"] and "empty patch passes" in g["gradable_why"]


def test_failure_count_parsing():
    assert F.failure_count("pytest exit 1: 1 failed, 93 passed") == 1
    assert F.failure_count("pytest exit 1: 2 failed, 1 error") == 3
    assert F.failure_count("timeout after 180s (hang)") is None and F.failure_count("") is None


def test_pytest_skip_never_leaks_out_of_the_builder(monkeypatch, tmp_path):
    # pytest sets OutcomeException.__module__ = "builtins"; a __module__ test missed every skip (regression)
    assert F.is_pytest_outcome(pytest.skip.Exception("x")) and F.is_pytest_outcome(pytest.fail.Exception("x"))
    assert not F.is_pytest_outcome(ValueError("x")) and not F.is_pytest_outcome(KeyboardInterrupt())
    # hermetic: an empty snapshot dir (every snapshot is local since 2026-09-30, so a real missing one no longer exists)
    monkeypatch.setattr(T, "SNAP_DIR", tmp_path)
    monkeypatch.setattr(T, "_BASE_MEMO", {})
    assert F._T() is T and not T.has_snapshot("fastapi_15661")
    r = F.guarded(T.base_ws, "fastapi_15661")                 # tasks.require_snapshot -> pytest.skip
    assert "error" in r and "skipped" in r["error"] and "snapshot missing" in r["error"]
    assert F.runnable("fastapi_15661") == (False, "snapshot missing: data/raw/snapshots/fastapi_15661.tgz")
    r = F.guarded(lambda: pytest.fail("boom"))
    assert r["error"].startswith("pytest.failed")
    with pytest.raises(KeyboardInterrupt):
        F.guarded(lambda: (_ for _ in ()).throw(KeyboardInterrupt()))


def test_exec_task_skip_is_recorded_not_raised(monkeypatch, tmp_path):
    """tasks.py skips raised anywhere in one task's exec phase become recorded reasons; nothing escapes, nothing is
    cached, and the assembled fixture says why (gotcha 12)."""
    import build_fixtures as B
    if not T.has_snapshot("rich_3278"):
        pytest.skip(T.fetch_cmd("rich_3278"))

    def skip(*_a, **_k):
        pytest.skip("parity venv missing: build it")
    for name in ("x_gradable", "x_run_repro", "x_replay", "x_canonical", "x_mini_verify", "x_hidden_pass"):
        monkeypatch.setattr(F, name, skip)
    monkeypatch.setattr(T, "hidden_claim_nodes", skip)
    ctx = B.Ctx(no_cache=True)
    ctx.cache.root = tmp_path
    st = B.static_task(ctx, "rich_3278")
    ex = B.exec_task(ctx, st)
    assert ex["grad"] == {"error": "pytest.skipped: parity venv missing: build it"}
    fx = B.assemble(ctx, st, ex, True, "")
    assert fx["gradable"] is False and "skipped" in fx["gradable_why"]
    assert fx["reproducible"] is False and "skipped" in fx["repro_why"]
    assert fx["variants"]["gold"]["replay_ok"] is False and "wrong" not in fx["variants"]
    assert all(c["status"] == "rejected" for c in fx["wrong_candidates"])
    ctx.cache.save("rich_3278")
    assert json.loads((tmp_path / "rich_3278.json").read_text())["entries"] == {}


def test_static_phase_skip_stops_cleanly(monkeypatch, capsys):
    """A tasks.py pytest.skip in the static phase (a base workspace that cannot be built) stops the build with a clean
    reason per task: SystemExit(2), never a pytest outcome escaping the builder (gotcha 12)."""
    import types

    import build_fixtures as B

    def fake_static(ctx, tid):
        if tid == "b":
            pytest.skip("snapshot missing: fetch it")
        return {"tid": tid}
    monkeypatch.setattr(B, "static_task", fake_static)
    ctx = types.SimpleNamespace(ids=["a", "b", "c"])
    with pytest.raises(SystemExit) as ei:
        B.static_all(ctx, 2)
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert "b: pytest.skipped: snapshot missing: fetch it" in err and "a:" not in err
    monkeypatch.setattr(B, "static_task", lambda ctx, tid: {"tid": tid})
    assert sorted(B.static_all(ctx, 2)) == ["a", "b", "c"]


def test_repro_verdict_rules():
    ok = {"rc": 0, "timed_out": False}
    fail = {"rc": 1, "timed_out": False}
    hang = {"rc": None, "timed_out": True}
    assert F.repro_verdict(fail, ok) == (True, "") and F.repro_verdict(hang, ok) == (True, "")
    assert F.repro_verdict(ok, ok)[1] == "passes on the original tree"
    assert "gold" in F.repro_verdict(fail, fail)[1] and "times out" in F.repro_verdict(fail, hang)[1]


def test_clean_why_strips_timings_and_paths():
    s = F.clean_why(f"pytest exit 1: 3 failed, 93 passed in 0.97s at {Path.home()}/.cache/g4/work/mv_abc/ws "
                    "/private/var/folders/xy/T/tmp1 " + str(ROOT))
    assert "0.97" not in s and "mv_abc" not in s and str(Path.home()) not in s and "/var/folders" not in s
    assert s.startswith("pytest exit 1: 3 failed, 93 passed")


# =====================================================================================================================
# committed outputs (4.6)
# =====================================================================================================================
def _datasets():
    return {p.stem: json.loads(p.read_text()) for p in sorted(F.DATASETS_DIR.glob("*.json"))}


GOLDEN_KEYS = {"schema", "suite", "task", "variant", "split", "repo", "stratum", "runnable", "runnable_why", "gradable",
               "gradable_why", "fixture_sha", "t0", "pre_s", "plan", "plan_source", "plan_basis", "title_words",
               "repro", "reproducible", "tree_patch", "tree_source", "replay", "replay_steps", "notes_changed",
               "gold_files", "gold_new_files", "gold_functions", "test_files", "hidden_nodes",
               "pre_hidden_nodes_pass", "known"}


def test_committed_files_are_canonical_json():
    for p in [F.SPLIT_FILE, F.TASK_FIXTURES_FILE, F.MANIFEST_FILE, *F.DATASETS_DIR.glob("*.json")]:
        text = p.read_text()
        assert text == F.dumps(json.loads(text)), p


def test_datasets_are_inference_input_evaluation_datasets():
    sets = _datasets()
    assert sorted(sets) == ["F_dev", "F_holdout", "L_dev", "L_holdout", "V_dev", "V_holdout"]
    split = json.loads(F.SPLIT_FILE.read_text())["tasks"]
    man = json.loads(F.MANIFEST_FILE.read_text())
    rows = F.load_rows()
    for name, ds in sets.items():
        suite, sp = name.split("_")
        assert set(ds) == {"eval_cases"}
        ids = [c["eval_case_id"] for c in ds["eval_cases"]]
        assert ids == sorted(ids) and len(set(ids)) == len(ids)
        for c in ds["eval_cases"]:
            g = c["golden"]
            assert set(c) == {"eval_case_id", "prompt", "reference", "golden"}              # no responses/agent_data
            assert c["prompt"] == {"role": "user", "parts": [{"text": rows[g["task"]]["problem_statement"]}]}
            ref = c["reference"]["response"]
            assert ref["role"] == "model" and len(ref["parts"]) == 1
            assert ref["parts"][0]["text"] == (g["plan"] if suite == "L" else rows[g["task"]]["patch"])
            assert set(g) == GOLDEN_KEYS, set(g) ^ GOLDEN_KEYS
            assert g["schema"] == "golden-case-v1" and g["suite"] == suite and g["split"] == sp
            assert split[g["task"]]["split"] == sp                                          # holdout only in *_holdout
            assert g["t0"] == man["t0"][suite]["t0"] and g["pre_s"] == 150
            want = f"{suite}__{g['task']}" + (f"__{g['variant']}" if suite == "V" else "")
            assert c["eval_case_id"] == want
            body = {k: v for k, v in g.items() if k != "fixture_sha"}
            assert g["fixture_sha"] == F.sha_obj(body)
            if suite == "V":
                assert g["variant"] in F.VARIANTS and g["tree_source"]
                if g["variant"] == "empty":
                    assert g["tree_patch"] == "" and g["replay_steps"] == [] and g["notes_changed"] == "CHANGED: nothing"
            else:
                assert g["variant"] == "-" and g["tree_patch"] == "" and g["replay_steps"] == [] \
                    and g["pre_hidden_nodes_pass"] is None
            assert F.plan_words(g["plan"]) <= F.PLAN_WORDS_MAX and g["plan"].startswith("FILES: ")
            assert g["plan"].split("\n")[3] == "REPRO: " + ("fails on original" if g["reproducible"] else "none")
    n = {k: len(v["eval_cases"]) for k, v in sets.items()}
    assert (n["L_dev"], n["L_holdout"], n["F_dev"], n["F_holdout"]) == (55, 19, 55, 19)


def test_hidden_test_demands_never_in_model_visible_text():
    cat = F.load_catalog()
    for ds in _datasets().values():
        for c in ds["eval_cases"]:
            g = c["golden"]
            demands = cat[g["task"]].get("hidden_test_demands") or ""
            visible = g["plan"] + (g["repro"] or "") + g["notes_changed"]
            assert not demands or demands not in visible
            for sentence in (s.strip() for s in demands.split(". ") if len(s.strip()) > 40):
                assert sentence not in g["plan"], (g["task"], sentence)


def test_runnable_flags_match_this_machine():
    """`runnable` is the live has_snapshot + kpar_ok verdict where the fixtures were built (the Mac: 74 of 74). A
    checkout without the gitignored snapshots (data/raw/snapshots) or the kpar venvs (~/.cache/g4/kpar) cannot
    re-derive it, which is not a fixture error (A6000 box, 2026-10-07: 'AssertionError: fastapi_11194', the first task
    in the file); a task this machine CAN run that the fixture calls unrunnable is a stale fixture and fails."""
    fx = json.loads(F.TASK_FIXTURES_FILE.read_text())["tasks"]
    live = {tid: F.runnable(tid) for tid in fx}
    stale = [tid for tid, (ok, _) in live.items() if ok and not fx[tid]["runnable"]]
    assert not stale, stale
    absent = [tid for tid, (ok, _) in live.items() if not ok and fx[tid]["runnable"]]
    if absent:
        pytest.skip(f"{len(absent)} of {len(fx)} runnable tasks lack a local snapshot or kpar venv (gitignored), e.g. "
                    f"{absent[0]}: {live[absent[0]][1]}")


def test_every_runnable_task_has_evidence_or_a_reason():
    """The fixture's own bookkeeping; whether this machine can run each task is test_runnable_flags_match_this_machine."""
    fx = json.loads(F.TASK_FIXTURES_FILE.read_text())["tasks"]
    assert len(fx) == 74
    for tid, f in fx.items():
        if not f["runnable"]:
            assert f["runnable_why"] and f["gradable"] is False and f["gradable_why"].startswith("not measured")
            continue
        assert f["gradable"] or f["gradable_why"], tid
        if f["gradable"]:
            assert f["gold_pass_runs"] == 2 and f["empty_pass"] is False
        assert f["reproducible"] or f["repro_why"], tid
        if f["reproducible"]:
            assert f["repro"] and f["repro_orig_rc"] != 0 and f["repro_gold_rc"] == 0
        g = f["variants"]["gold"]
        assert g["replay_ok"] is True, (tid, g["replay_why"])
        assert g["replay"] == "edit" or g["replay_fallback_why"], tid
        assert "wrong" in f["variants"] or f["wrong_why"], tid
        if "wrong" in f["variants"]:
            w = f["variants"]["wrong"]
            assert w["replay_ok"] is True and f["wrong_source"] == w["tree_source"]
            assert not any(R_protected(p) for p in F.changed_paths(w["tree_patch"])), tid
        assert isinstance(g["pre_hidden_nodes_pass"], int) and isinstance(f["variants"]["empty"]["pre_hidden_nodes_pass"],
                                                                          int)


def R_protected(path):
    return F.R.is_protected(path)


def test_manifest_counts_match_datasets():
    man = json.loads(F.MANIFEST_FILE.read_text())
    assert man["schema"] == "golden-manifest-v1" and man["leaks"]["final_violations"] == 0
    sets = _datasets()
    for name, ds in sets.items():
        suite, sp = name.split("_")
        tot = sum(v["cases"] for v in man["counts"][suite][sp].values())
        assert tot == len(ds["eval_cases"])
        for key, v in man["counts"][suite][sp].items():                  # the R x G x P cross-tab adds up
            assert sum(v["cells"].values()) == v["cases"]
            mine = [c["golden"] for c in ds["eval_cases"] if suite != "V" or c["golden"]["variant"] == key]
            for cell, n in v["cells"].items():
                r, g, p = (int(x.split("=")[1]) for x in cell.split())
                assert n == sum(1 for b in mine if (b["runnable"], b["gradable"], b["reproducible"]) == (r, g, p))
    for rel_path, sha in man["outputs"].items():
        assert F.sha_file(ROOT / rel_path) == sha, rel_path
    assert man["mini_verify_timeout"] == 180


# =====================================================================================================================
# NIGHTLY
# =====================================================================================================================
@pytest.mark.skipif(not NIGHTLY, reason="NIGHTLY tier (G4_NIGHTLY=1)")
@pytest.mark.parametrize("tid", ["rich_3278", "rich_3043", "rich_3470"])
def test_nightly_gradability_on_real_rich_tasks(tid):
    if not (T.has_snapshot(tid) and T.kpar_ok(tid)):
        pytest.skip(f"needs the snapshot and the rich kpar venv: {T.fetch_cmd(tid)}; {T.build_cmd('rich')}")
    g = F.x_gradable(tid)
    assert g["gradable"], g
    assert g["gold_pass_runs"] == 2 and g["empty_pass"] is False


@pytest.mark.skipif(not NIGHTLY, reason="NIGHTLY tier (G4_NIGHTLY=1)")
def test_nightly_build_check_is_byte_identical():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "golden" / "build_fixtures.py"), "--check", "-j", "6",
                        "--quiet"], cwd=ROOT, capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, r.stderr[-3000:]
