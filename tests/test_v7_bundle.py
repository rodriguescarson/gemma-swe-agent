"""v7 = v5h2 + the fixes for every "ours" finding of docs/a6000/FAILURE_FORENSICS.md that needs no new measurement,
pre-registered in docs/GAPS_2026-10-06.md (last section), plus fix 9 (the pre-edit read cap) and the refusal-message
audit (Carson 2026-10-07: "ensure the refused, failed or skipped stuff will be accepted in this build"). Written before
the changes (strict test-first).

  1 view.py takes FILE A B, A-B, A:B, A and bare FILE       5 the locator reads through view.py: [run_command, get_status]
  2 prompts describe calls in words, show the command alone  6 graph tools and edit_file dropped from every stage
  3 no forced install call in the fixer and verifier         7 edit.py: SEARCH/REPLACE markers in a --lines body
  4 repro through run_command + a quoted heredoc; only the   8 "budget exhausted" -> stop (verifier: submit_patch)
    fixer declares write_file                                9 locate.py <= 3 per task, view.py <= 14 before the first edit

This file: the file delta against v5h2, the compiled tree, packing, the tools per stage, the prompt wording rules, the
helpers' coverage (install + Kaggle PROBES), the call arithmetic and the Kaggle kernel. Helper behaviour:
tests/test_v7_helpers.py; the harness sandbox: tests/test_v7_sandbox.py; prompt vs reality: tests/test_v7_prompts.py;
the trace counters of the pass rule: tests/test_v7_counters.py (scripts/v7_counters.py)."""
import ast, filecmp, os, re, subprocess, sys, zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SUB = ROOT / "submissions"
V5H2, V7 = SUB / "v5h2", SUB / "v7"
STAGES = ("locator", "fixer", "verifier")
CHANGED = {"prompts/fixer.md", "prompts/locator.md", "prompts/verifier.md",
           "sub_agents/locator.yaml", "sub_agents/fixer.yaml", "sub_agents/verifier.yaml",
           "skills/swe-tools/scripts/view.py", "skills/swe-tools/scripts/edit.py", "skills/swe-tools/scripts/locate.py",
           "skills/swe-tools/scripts/test.py", "skills/swe-tools/scripts/check.py", "skills/swe-tools/scripts/install.py",
           "skills/swe-tools/scripts/_ws.py"}
TREE = {"setup": ["SkillToolset"], "locator": ["run_command", "get_status", "SkillToolset"],
        "fixer": ["run_command", "write_file", "get_status", "SkillToolset"],
        "verifier": ["run_command", "get_status", "submit_patch", "SkillToolset"]}
GRAPH = {"get_code_neighbors", "search_similar_code", "get_code_subgraph"}
TOOL_NAMES = ("run_command", "run_skill_script", "submit_patch", "read_file", "write_file", "edit_file", "get_status")
FORBIDDEN = ("run_command(", "run_skill_script(", "submit_patch(", "read_file(")
RECOVERY = ('If any helper reports "can\'t open file", run the install script once with the run_skill_script tool '
            '(skill swe-tools, file install.py) and repeat the helper call.')
KERNEL_DIR, KERNEL_SLUG = "g4-l4-v7-p312", "g4-lora-test"
TAKEN = {"g4-eval74-v4": "v5h2", "g4-l4-v4": "v5h2b", "g4-eval74-v3": "v6p", "g4-l4-v9-eog": "v6p-think",
         "g4-eval74-v2": "v11b probe (queued)"}


def files(d):
    return {str(p.relative_to(d)) for p in d.rglob("*")
            if p.is_file() and not p.name.startswith(".") and "__pycache__" not in p.parts}


def changed(a, b):
    return {rel for rel in files(a) & files(b) if not filecmp.cmp(a / rel, b / rel, shallow=False)}


def prompt(stage, b=V7):
    return (b / "prompts" / f"{stage}.md").read_text()


def stage_yaml(stage, b=V7):
    return yaml.safe_load(re.sub(r"!include\s+\S+", "INCLUDED", (b / "sub_agents" / f"{stage}.yaml").read_text()))


def spans(text):
    return re.findall(r"`([^`\n]+)`", text)


# ------------------------------------------------------------------ the delta against v5h2

def test_v7_differs_from_v5h2_only_in_the_listed_files():
    assert files(V7) == files(V5H2), files(V7) ^ files(V5H2)
    assert changed(V5H2, V7) == CHANGED, changed(V5H2, V7) ^ CHANGED
    for rel in ("agent.yaml", "eval_config.yaml", "configs/sampling.yaml", "prompts/setup.md", "sub_agents/setup.yaml",
                "skills/swe-tools/SKILL.md"):
        assert filecmp.cmp(V5H2 / rel, V7 / rel, shallow=False), rel


def test_each_prompt_keeps_its_template_variables():
    for s in STAGES:
        assert set(re.findall(r"\{[a-z_]+\??\}", prompt(s))) == set(re.findall(r"\{[a-z_]+\??\}", prompt(s, V5H2))), s


# ------------------------------------------------------------------ compiled tree (fixes 4, 5, 6)

def test_the_official_compiler_builds_the_four_stages_with_exactly_these_tools():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(V7)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-800:] + r.stderr[-1500:]
    tree = {m.group(1): ast.literal_eval(m.group(2)) for m in re.finditer(r"^\s*LlmAgent (\w+) model=\S+ tools=(\[.*\])$", r.stdout, re.M)}
    assert tree == TREE, tree
    assert re.search(r"^SequentialAgent swe_pipeline", r.stdout, re.M)
    order = re.findall(r"^\s*LlmAgent (\w+)", r.stdout, re.M)
    assert order == ["setup", "locator", "fixer", "verifier"], order


def test_stage_yamls_declare_those_tools_and_keep_the_skill():
    for s, tools in TREE.items():
        y = stage_yaml(s)
        assert (y.get("tools") or []) == [t for t in tools if t != "SkillToolset"], (s, y.get("tools"))
        assert y["skills"] == ["skills/swe-tools"] and y.get("include_contents") == "none", s


def test_graph_tools_and_edit_file_are_gone_from_every_stage_and_prompt():
    from test_v5b_bundle import affirmative
    from test_v10_prompts import named_tools
    for s in ("setup",) + STAGES:
        assert not set(stage_yaml(s).get("tools") or []) & (GRAPH | {"edit_file"}), s
    for s in STAGES:
        assert named_tools(prompt(s), GRAPH) == set(), s
        assert named_tools(affirmative(prompt(s)), {"edit_file", "read_file"}) == set(), s   # only "There is no edit_file tool"


def test_only_the_fixer_declares_write_file():
    assert [s for s in ("setup",) + STAGES if "write_file" in (stage_yaml(s).get("tools") or [])] == ["fixer"]


def test_every_tool_named_in_a_prompt_is_declared_by_that_stage():
    from test_v10_prompts import HALLUCINATED, REGISTRY_FALLBACK, named_tools
    from test_v10_bundle import SKILL_TOOLS
    from test_v5b_bundle import affirmative, declared_tools
    vocab = REGISTRY_FALLBACK | SKILL_TOOLS | HALLUCINATED
    for s in STAGES:
        found = named_tools(affirmative(prompt(s)), vocab)
        assert found <= declared_tools(s, V7), (s, found - declared_tools(s, V7))
        assert ("submit_patch" in found) == (s == "verifier"), s
        listed = re.search(r"^Tools you can call: ([^.]+)\.", prompt(s), re.M).group(1).split(", ")
        assert set(listed) == set(stage_yaml(s)["tools"]) | {"run_skill_script"}, (s, listed)


# ------------------------------------------------------------------ fix 2: calls in words, the command alone

def test_no_prompt_but_setup_shows_a_tool_call_shape():
    for s in STAGES:
        t = prompt(s)
        for bad in FORBIDDEN:
            assert bad not in t, (s, bad)
        assert not re.search(r"\b(%s)`?\s*:" % "|".join(TOOL_NAMES), t), s        # no "`run_command`: cmd" labels
        assert "with the run_command tool" in t, s
    assert any(bad in prompt("fixer", V5H2) for bad in FORBIDDEN)                # control: v5h2 has them
    assert 'run_skill_script(skill_name="swe-tools", file_path="install.py")' in (V7 / "prompts" / "setup.md").read_text()


def test_a_backticked_span_is_a_shell_line_or_a_path_never_a_tool_call():
    for s in STAGES:
        for sp in spans(prompt(s)):
            assert not any(re.search(r"\b%s\b" % n, sp) for n in TOOL_NAMES), (s, sp)


V5H2_RULES = {
    "locator": ["You only find the code; a later stage edits it.", "at most 8 tool calls, never repeat a call",
                "(use code identifiers and error text only: leave out URLs, version numbers, environment dumps and doc links)",
                'Use `git grep -n "<name>"` for exact names.', "Also find one existing test file that covers this code",
                '`git grep -ln "<symbol>" -- tests`', "Then STOP calling tools and reply with this plan (plain text, under 250 words):",
                "FILES: path:start-end for each place to change", "ROOT CAUSE: one or two sentences",
                "CHANGE: exactly what to add or modify, with the exact names/messages/signatures the issue implies",
                "TEST: the test file to run"],
    "fixer": ["Implement the change now.", "Helpers are never tool names",
              "a call whose name starts with python3 or /tmp/swe is an unknown tool and ends the task with no patch",
              "(at most 120 lines; a range you already saw is refused, so edit instead of re-reading)",
              "as raw code with no escaping:", "<<<<<<< SEARCH\nexact current lines (copied as read, unique, short)\n=======\nnew lines\n>>>>>>> REPLACE\nEOF\n",
              "--lines 120-135 <<'EOF'` then the new lines, then EOF.", "For a new file use --create instead of --lines.",
              "EOF appears once, as the last line.", "A broken edit is undone",
              "Make the smallest complete source change; create new functions/params/files with exactly the names the issue implies.",
              "Never edit tests, conftest.py, pytest.ini, pyproject.toml, setup.cfg or tox.ini.", "Scratch files go in /tmp",
              "Never repeat a tool call. At most 12 tool calls.",
              "If an edit fails, re-read those exact lines before retrying with a shorter SEARCH; never resend the identical edit.",
              "The current code IS wrong: do not conclude that nothing needs changing.",
              "Working rules: make the example in the issue work first, before docstrings or cleanups.",
              "Edit by your 6th tool call; do not keep reading.", "`git grep -n NAME` instead of viewing more pages",
              "`git grep -n FUNCTION_YOU_EDITED` once and apply the same fix to any sibling function or caller with the same bug "
              "(for example load and loads, or both branches of an if).", "Wrap any script you run as `timeout 30 python3 ...`.",
              "When the edit is done, STOP calling tools and reply in under 100 words: what you changed (file, function) and which test to run."],
    "verifier": ["The fix is already applied.", "Helpers are never tool names",
                 "a call whose name starts with python3 or /tmp/swe is an unknown tool and ends the task with no patch",
                 "Steps (never repeat a call):", "1. `git diff` to see the change.",
                 "2. Run the relevant test: `python3 /tmp/swe/test.py --target <test file>` (never the whole suite). "
                 "If the change has a clear bug, fix it and re-run once. Failures unrelated to the change can be ignored.",
                 "2b. If the issue states an input and the expected output or behaviour",
                 "bare assert (no try/except, no print-only checks; it must exit non-zero when the behaviour is wrong)",
                 "treat it like a failing test in step 2", "Skip this step if the issue states no example.",
                 "3. `python3 /tmp/swe/check.py --mode preflight` and fix what it flags (revert test/config edits, delete scratch files in /workspace).",
                 "4. Never submit an empty diff. If `git diff` is empty, the fix was NOT applied: make the change described in the plan "
                 "yourself, even if you are unsure. \"Already fixed\" is never the right conclusion; the grading tests fail on the current code.",
                 "then reply with one sentence.", "as raw code with no escaping:",
                 "<<<<<<< SEARCH\nexact current lines (copied as read, unique, short)\n=======\nnew lines\n>>>>>>> REPLACE\nEOF\n",
                 "--lines 120-135 <<'EOF'` then the new lines, then EOF. EOF appears once, as the last line."],
}


@pytest.mark.parametrize("stage", STAGES)
def test_every_v5h2_rule_survives_the_rewording(stage):
    t = prompt(stage)
    missing = [r for r in V5H2_RULES[stage] if r not in t]
    assert not missing, (stage, missing)


# ------------------------------------------------------------------ fix 3: the setup stage installs; one recovery line

@pytest.mark.parametrize("stage", STAGES)
def test_no_forced_install_and_exactly_one_recovery_sentence(stage):
    t = prompt(stage)
    assert "first tool call is always" not in t and "first, always" not in t, stage
    assert t.count("install.py") == 1 and t.count(RECOVERY) == 1, stage
    steps = re.findall(r"^\d+\. .*$", t, re.M)                              # the fixer has rules, not steps
    assert not steps or "install.py" not in steps[0]                           # step 1 is never the install
    assert "first tool call is always" in prompt("fixer", V5H2)                 # control


def test_setup_stage_is_v5h2s_and_installs_first():
    root = yaml.safe_load(re.sub(r"!include\s+\S+", "INCLUDED", (V7 / "agent.yaml").read_text()))
    assert [s["config_path"] for s in root["sub_agents"]] == ["sub_agents/setup.yaml", "sub_agents/locator.yaml",
                                                              "sub_agents/fixer.yaml", "sub_agents/verifier.yaml"]
    s = stage_yaml("setup")
    assert s.get("tools", []) == [] and s["skills"] == ["skills/swe-tools"]
    src = (V7 / "skills" / "swe-tools" / "scripts" / "install.py").read_text()
    assert "exist_ok=True" in src                                               # a recovery install is harmless


# ------------------------------------------------------------------ fix 4: the repro mechanism

def test_the_verifier_writes_the_repro_with_a_quoted_heredoc_through_run_command():
    v = prompt("verifier")
    lines = v.splitlines()
    i = lines.index("cat > /tmp/repro.py <<'EOF'")
    j = lines.index("EOF", i)
    assert j - i >= 2 and "assert" in "\n".join(lines[i + 1:j])
    assert "`python3 /tmp/repro.py; echo EXIT=$?`" in v and "with one run_command call" in v
    assert "write_file" not in v and "write /tmp/repro.py" in v


def test_the_fixer_writes_scratch_files_in_tmp_through_run_command_not_write_file():
    # P4 traces: 4 fixer write_file calls to /tmp were refused ("Path traversal detected") besides the verifier's 29
    f = prompt("fixer")
    rule = next(l for l in f.splitlines() if "Scratch files go in /tmp" in l)
    assert "`cat > /tmp/scratch.py <<'EOF'`" in rule and "write_file only writes inside /workspace" in rule


# ------------------------------------------------------------------ fix 5: the locator reads through view.py

def test_the_locator_reads_through_view_py_with_two_tools():
    y = stage_yaml("locator")
    assert y["tools"] == ["run_command", "get_status"]
    t = prompt("locator")
    assert "`python3 /tmp/swe/view.py path/to/file.py START END`" in t and "read_file" not in t
    assert re.findall(r"^(\d+)\. ", t, re.M) == ["1", "2"] and "at most 8 tool calls" in t
    assert "`python3 /tmp/swe/locate.py \"<identifiers, error text and keywords from the issue>\"`" in t


# ------------------------------------------------------------------ fix 8: budget exhausted

def test_budget_exhausted_line_in_the_fixer_and_the_verifier():
    f = [l for l in prompt("fixer").splitlines() if "budget exhausted" in l]
    v = [l for l in prompt("verifier").splitlines() if "budget exhausted" in l]
    assert len(f) == 1 and "stop" in f[0] and "reply with your notes at once" in f[0], f
    assert len(v) == 1 and "stop" in v[0] and "submit_patch at once" in v[0], v
    assert "budget exhausted" not in prompt("locator")


# ------------------------------------------------------------------ fix 9: the call arithmetic

def test_the_locator_yaml_states_the_per_stage_arithmetic_and_the_budget_is_unchanged():
    from test_v7_helpers import ws_constants
    locate_cap, view_cap = ws_constants()[:2]
    raw = (V7 / "sub_agents" / "locator.yaml").read_text()
    comment = "\n".join(l for l in raw.splitlines() if l.startswith("#"))
    shares = {k: int(v) for k, v in re.findall(r"^#\s+(setup|locator|fixer|verifier)\s+(\d+)\b", comment, re.M)}
    ev = yaml.safe_load((V7 / "eval_config.yaml").read_text())["evaluation"]
    assert ev["max_tool_calls"] == 70 and ev["max_time_minutes"] == 5
    assert shares == {"setup": 1, "locator": 8, "fixer": 12, "verifier": 49} and sum(shares.values()) == ev["max_tool_calls"]
    assert f"locate.py <= {locate_cap}" in comment and f"view.py <= {view_cap}" in comment and "raw greps" in comment
    assert "at most 8 tool calls" in prompt("locator") and "At most 12 tool calls" in prompt("fixer")


# ------------------------------------------------------------------ helpers, install, Kaggle probes, packing

def helpers_used(b):
    used = set()
    for p in list((b / "prompts").glob("*.md")) + [b / "skills/swe-tools/SKILL.md"]:
        used |= set(re.findall(r"python3 /tmp/swe/(\w+\.py)", p.read_text()))
    return used


def probe_keys():
    src = (ROOT / "scripts" / "make_eval_kernel.py").read_text()
    return set(re.findall(r'"(\w+\.py)":', src.split("PROBES = {", 1)[1].split("}\n", 1)[0]))


def test_every_helper_referenced_exists_installs_into_the_sandbox_tmp_and_is_probed_on_kaggle(tmp_path):
    used = helpers_used(V7)
    assert used == {"edit.py", "locate.py", "test.py", "check.py", "view.py"}, used
    scripts = V7 / "skills" / "swe-tools" / "scripts"
    assert all((scripts / h).exists() for h in used)
    env = dict(os.environ, TMPDIR=str(tmp_path), TEST_TMPDIR=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, str(scripts / "install.py")], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert p.returncode == 0 and "helpers in" in p.stdout, p.stdout + p.stderr
    for h in used | {"_ws.py"}:
        assert (tmp_path / "swe" / h).exists(), h
    assert (tmp_path / "swe" / ".ledger.json").exists()
    assert {"locate.py", "view.py"} <= probe_keys() and used <= probe_keys(), used - probe_keys()


def test_packs_small_and_complete(tmp_path):
    z = tmp_path / "v7.zip"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "pack_bundle.py"), str(V7), str(z)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert z.stat().st_size < 100_000
    names = zipfile.ZipFile(z).namelist()
    assert sorted(names) == sorted(files(V7)) and not any("__pycache__" in n or n.endswith(".pyc") for n in names)


# ------------------------------------------------------------------ the Kaggle eval kernel (v5b recipe)

def test_the_kernel_slug_is_an_existing_one_no_queued_bundle_uses():
    assert KERNEL_SLUG not in TAKEN
    # an existing slug made under the 3.12 image (new slugs get the 3.13 image and every cp312 wheel fails): its last use
    # was the CPU helper check of 2026-10-04, recorded in GATE.md ("g4-lora-test v3", HELPER_CHECK PASS)
    assert "g4-hc-v4h2f-p312 on slug g4-lora-test" in (ROOT / "docs" / "v4h" / "GATE.md").read_text()


@pytest.mark.skipif(not (ROOT / "kernels" / KERNEL_DIR / "kernel-metadata.json").exists(),
                    reason="kernels/ is gitignored: the kernel is generated on the Mac")
def test_eval_kernel_matches_the_recipe(tmp_path):
    kd = ROOT / "kernels" / KERNEL_DIR
    meta = (kd / "kernel-metadata.json").read_text()
    for s in (f'"id": "carsonrodrigues/{KERNEL_SLUG}"', '"docker_image_pinning_type": "original"', '"enable_gpu": true',
              '"machine_shape": "NvidiaL4"'):
        assert s in meta, s
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_eval_kernel.py"), str(V7), KERNEL_DIR,
                        "--ids", str(ROOT / "data" / "kaggle_valid_ids.txt"), "--pin", "original", "--kernel-id", KERNEL_SLUG],
                       cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    for f in ("kernel-metadata.json", KERNEL_SLUG + ".ipynb"):
        assert (tmp_path / "kernels" / KERNEL_DIR / f).read_bytes() == (kd / f).read_bytes(), f
