"""v13_lost_search = submissions/v13 plus ONE change: a sentence at the end of step 1 (Locate) of prompts/system.md.

Lever (docs/forty_two/tasks/rich_4076.md): when the issue says something is lost or not preserved, search for the code that
removes it (operations that cut, trim or deduplicate) and check each hit against the issue. On rich_4076 the six box runs grepped
the lost thing's name and read the printing and pretty-printing code; none reached the one call site that drops it, which a
search for the removing operation lists first among 7 hits (measured offline, the write-up). The sentence names no task, file,
function, method or test, and none of the gold patch's tokens.

Constraints pinned here:
- every file other than prompts/system.md is byte-identical to submissions/v13 (same modes);
- prompts/system.md is v13's with exactly one inserted sentence, placed at the end of step 1;
- the inserted text has no fenced block, backtick, brace, underscore or anything shaped like a tool call (a precaution after the
  coordinator's 2026-10-14 note on one unrecovered text-call leak on the v13 screen; such leaks occurred 10 times in the six
  earlier box runs, all recovered, so this is not a known cause);
- it names no Python method (the gold patch's removed call is one), only the kinds of operation;
- no public-task specifics (the deny list of tests/test_v13_leakage.py) and scripts/validate.py passes."""
import filecmp, importlib.util, json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE, DST = ROOT / "submissions" / "v13", ROOT / "submissions" / "v13_lost_search"
STEP1_END = "Do not read files that are not in the hits."
ADDED = (" If the issue says something is lost or not preserved (whitespace, order, a field or value), also search for the code"
         " that removes it, such as operations that cut, trim or deduplicate text or collections, and check each hit against"
         " the issue.")


def all_files(d):
    return {str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file()}


def test_only_the_prompt_differs_from_v13():
    assert all_files(DST) == all_files(BASE)
    for rel in sorted(all_files(BASE)):
        assert filecmp.cmp(BASE / rel, DST / rel, shallow=False) == (rel != "prompts/system.md"), rel
        assert os.stat(BASE / rel).st_mode == os.stat(DST / rel).st_mode, rel


def test_the_prompt_is_v13_plus_one_sentence_at_the_end_of_step_1():
    old, new = (BASE / "prompts" / "system.md").read_text(), (DST / "prompts" / "system.md").read_text()
    assert old.count(STEP1_END) == 1
    assert new == old.replace(STEP1_END, STEP1_END + ADDED)
    step1 = new.split("1. Locate.")[1].split("\n2. Read")[0]
    assert step1.endswith(ADDED)


def test_the_added_text_has_no_code_block_or_tool_call_shape():
    for bad in ("```", "`", "{", "}", "<|", "|>", "call:", "tool_call", "<<", "run_command", "read_file", "submit_patch", "_", "()"):
        assert bad not in ADDED, bad
    assert ADDED.count(".") == 1 and ADDED.endswith(".")                      # one sentence


def test_the_added_text_names_no_python_method_and_no_gold_token():
    """No str/list/dict/set method name, and no identifier from any +/- line of the gold patch of the task that motivated it."""
    words = set(re.findall(r"[a-z]+", ADDED.lower()))
    methods = {m for t in (str, list, dict, set) for m in dir(t) if not m.startswith("_")}
    assert not words & methods, words & methods
    for line in (ROOT / "data" / "tasks.jsonl").read_text().splitlines():
        t = json.loads(line)
        if t["instance_id"] == "rich" + "_4076":
            changed = [l[1:] for l in t["patch"].splitlines() if l[:1] in "+-" and l[:3] not in ("+++", "---")]
            tokens = {w.lower() for w in re.findall(r"[A-Za-z_]{3,}", "\n".join(changed))}
            code = {w for w in tokens if "_" in w or w in methods or w in ("re", "line", "yield", "self")}
            assert not words & code, words & code
            break
    else:
        raise AssertionError("motivating task not found")


def _leaks(bundle):
    spec = importlib.util.spec_from_file_location("v13_leakage", ROOT / "tests" / "test_v13_leakage.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.leaks(bundle)


def test_no_public_task_specifics_in_the_bundle():
    assert (DST / "agent.yaml").is_file()
    assert not _leaks(DST)


def test_validator_passes():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(DST)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert "tools=['run_command', 'read_file', 'get_status', 'submit_patch']" in r.stdout
    assert "'thinking_budget': 1024" in r.stdout and "'temperature': 1.0" in r.stdout
