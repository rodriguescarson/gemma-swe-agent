"""v6p (docs/GAPS_2026-10-06.md AC-B2, base v5h2): best-of-3 bundle.

    Sequential[setup, locator, Parallel[fixer_a T0.2, fixer_b T0.6, fixer_c T0.9], selector, verifier]

Each fixer copies /workspace to its own /tmp/wK and works only there (ParallelAgent children share one sandbox), the
selector is an LlmAgent with skill tools only whose one job is `run_skill_script(... file_path="select_best.py")`, and
the verifier is v5h2's. S3 (Carson 2026-10-06): the locator writes /tmp/repro.py, which must fail on the unedited code;
every fixer runs it in its copy and select_best.py ranks on it first. Written before the bundle (strict test-first)."""
import os, re, subprocess, sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SUB = ROOT / "submissions"
V5H2, V6P = SUB / "v5h2", SUB / "v6p"
FIXERS = ("fixer_a", "fixer_b", "fixer_c")
TEMPS = {"fixer_a": 0.2, "fixer_b": 0.6, "fixer_c": 0.9}
LLM_STAGES = ("setup", "locator") + FIXERS + ("selector", "verifier")
SKILL_TOOLS = {"list_skills", "load_skill", "load_skill_resource", "run_skill_script"}
SELECT_CALL = 'run_skill_script(skill_name="swe-tools", file_path="select_best.py"'
FIXER_CAP = 13
LOCATOR_CAP = 12                                                         # v5h2 8 + S3 repro: write, run, rewrite, run
BUDGET = 70
KERNEL_DIR, KERNEL_SLUG = "g4-l4-v6p-p312", "g4-eval74-v3"
QUEUED_SLUGS = {"g4-eval74-v4", "g4-l4-v4", "g4-eval74-v2"}   # v5h2, v5h2b, v11b-probe in the running queue


def _yaml(p):
    return yaml.safe_load(re.sub(r"!include\s+\S+", "INCLUDED", p.read_text()))


def _compile(b):
    """The organisers' compiler, as scripts/validate.py calls it, returning the agent object."""
    from unittest.mock import MagicMock
    from adk_submission import compile_submission, discover_adapters
    from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS, build_submission_limits
    from swegemma.models import setup_gemma_model_registry
    from swegemma.tools import create_tools
    limits, gen = build_submission_limits()
    return compile_submission(submission_dir=str(b), adapter_manifest=discover_adapters(str(b), ALLOWED_ADAPTER_EXTENSIONS),
                              tool_registry=create_tools(MagicMock()), model_registry=setup_gemma_model_registry(),
                              limits=limits, generation_constraints=gen)


def _tools(a):
    return [getattr(t, "name", getattr(t, "__name__", type(t).__name__)) for t in (a.tools or [])]


@pytest.fixture(scope="module")
def tree():
    return _compile(V6P)


# ---------------------------------------------------------------- compiled tree

def test_validate_py_compiles_the_bundle():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(V6P)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-1500:]
    assert "ParallelAgent" in r.stdout and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout


def test_compiled_tree_is_setup_locator_parallel_fixers_selector_verifier(tree):
    assert type(tree).__name__ == "SequentialAgent"
    names = [(type(a).__name__, a.name) for a in tree.sub_agents]
    assert names == [("LlmAgent", "setup"), ("LlmAgent", "locator"), ("ParallelAgent", "fixers"),
                     ("LlmAgent", "selector"), ("LlmAgent", "verifier")], names
    par = tree.sub_agents[2]
    assert [(type(a).__name__, a.name) for a in par.sub_agents] == [("LlmAgent", f) for f in FIXERS]


def test_each_fixer_carries_its_own_temperature_and_otherwise_v5h2_sampling(tree):
    base = yaml.safe_load((V5H2 / "configs/sampling.yaml").read_text())
    for a in tree.sub_agents[2].sub_agents:
        g = a.generate_content_config
        assert g.temperature == pytest.approx(TEMPS[a.name]), (a.name, g.temperature)
        assert (g.top_p, g.max_output_tokens, g.seed) == (base["top_p"], base["max_output_tokens"], base["seed"]), a.name
    for a in (tree.sub_agents[0], tree.sub_agents[1], tree.sub_agents[3], tree.sub_agents[4]):
        assert a.generate_content_config.temperature == pytest.approx(0.2), a.name


def test_tools_per_stage(tree):
    s = {a.name: a for a in tree.sub_agents}
    v5 = {a.name: a for a in _compile(V5H2).sub_agents}
    assert _tools(s["setup"]) == ["SkillToolset"]
    assert _tools(s["selector"]) == ["SkillToolset"]                    # skill tools only, like setup
    assert _tools(s["locator"]) == _tools(v5["locator"])
    assert _tools(s["verifier"]) == _tools(v5["verifier"]) and "submit_patch" in _tools(s["verifier"])
    for f in s["fixers"].sub_agents:
        # v5h2's fixer tools minus write_file: write_file can only write inside /workspace, which the fixers share
        assert _tools(f) == [t for t in _tools(v5["fixer"]) if t != "write_file"], f.name
        assert "submit_patch" not in _tools(f) and "edit_file" not in _tools(f) and "read_file" not in _tools(f)


def test_state_flow_plan_reaches_every_fixer_and_include_contents_none(tree):
    s = {a.name: a for a in tree.sub_agents}
    assert s["locator"].output_key == "plan"
    keys = set()
    for a in [s["setup"], s["locator"], s["selector"], s["verifier"]] + list(s["fixers"].sub_agents):
        assert a.include_contents == "none", a.name
    for f in s["fixers"].sub_agents:
        assert "{plan?}" in f.instruction and "{problem_description}" in f.instruction, f.name
        keys.add(f.output_key)
    assert keys == {"fix_notes_a", "fix_notes_b", "fix_notes_c"}         # distinct: parallel writers never collide
    assert s["selector"].output_key == "selection"
    assert "{selection?}" in s["verifier"].instruction and "{plan?}" in s["selector"].instruction


# ---------------------------------------------------------------- unchanged from v5h2

def test_setup_locator_and_shared_helpers_are_v5h2s():
    for rel in ("prompts/setup.md", "sub_agents/setup.yaml", "sub_agents/locator.yaml",
                "configs/sampling.yaml", "eval_config.yaml", "skills/swe-tools/scripts/edit.py",
                "skills/swe-tools/scripts/locate.py", "skills/swe-tools/scripts/check.py",
                "skills/swe-tools/scripts/install.py"):
        assert (V6P / rel).read_bytes() == (V5H2 / rel).read_bytes(), rel


def test_eval_config_keeps_the_70_call_5_minute_budget():
    e = yaml.safe_load((V6P / "eval_config.yaml").read_text())["evaluation"]
    assert e["max_tool_calls"] == BUDGET and e["max_time_minutes"] == 5


# ---------------------------------------------------------------- fixers: isolation in /tmp/wK

def fixer_prompt(k):
    return (V6P / "prompts" / f"fixer_{k}.md").read_text()


@pytest.mark.parametrize("k", "abc")
def test_fixer_first_call_copies_workspace_to_its_own_dir(k):
    p = fixer_prompt(k)
    first = re.search(r"first tool call is\s+`?(run_command\(command=\"[^\"]+\"\))", p)
    assert first, "the first call must be named"
    assert f"cp -a /workspace /tmp/w{k}" in first.group(1) and f"rm -rf /tmp/w{k}" in first.group(1)


@pytest.mark.parametrize("k", "abc")
def test_fixer_works_only_in_its_copy(k):
    p = fixer_prompt(k)
    other = [o for o in "abc" if o != k]
    for o in other:
        assert f"/tmp/w{o}" not in p, o
    # every helper/edit/test/grep example runs inside the copy
    for line in p.splitlines():
        for m in re.finditer(r"python3 /tmp/swe/(edit|view|test)\.py", line):
            assert f"cd /tmp/w{k} && python3 /tmp/swe/" in line, line
        if "git grep" in line:
            assert f"git -C /tmp/w{k} grep" in line, line
    assert "Never edit /workspace" in p
    # the result
    assert f"git -C /tmp/w{k} add -N . && git -C /tmp/w{k} diff > /tmp/w{k}.diff" in p
    assert "submit_patch" not in p


def test_the_three_fixer_prompts_differ_only_in_the_letter():
    a = fixer_prompt("a")
    for k in "bc":
        assert fixer_prompt(k) == (a.replace("/tmp/wa", f"/tmp/w{k}").replace("repro_a", f"repro_{k}")
                                  .replace("FIXER A", f"FIXER {k.upper()}")), k


@pytest.mark.parametrize("k", "abc")
def test_fixer_call_cap_and_budget_arithmetic(k):
    p = fixer_prompt(k)
    assert f"At most {FIXER_CAP} tool calls" in p
    y = (V6P / "sub_agents" / f"fixer_{k}.yaml").read_text()
    if k == "a":
        # the arithmetic lives next to the cap: setup 1 + locator + 3 x fixers + selector 1 + verifier <= 70
        m = re.search(r"1 \+ (\d+) \+ 3 x (\d+) \+ 1 \+ (\d+) = (\d+) <= 70", y)
        assert m, "budget arithmetic comment missing from fixer_a.yaml"
        loc, cap, ver, tot = map(int, m.groups())
        assert loc == LOCATOR_CAP and cap == FIXER_CAP and 1 + loc + 3 * cap + 1 + ver == tot <= BUDGET and ver >= 8


@pytest.mark.parametrize("k", "abc")
def test_fixer_runs_the_locators_repro_in_its_copy(k):
    p = fixer_prompt(k)
    assert f'run_command(command="cd /tmp/w{k} && python3 /tmp/swe/repro.py")' in p
    assert "REPRO PASS" in p and "Never edit /tmp/repro.py" in p
    assert "repro_" not in p                                              # one repro, the locator's


# ---------------------------------------------------------------- locator (S3)

def test_locator_is_v5h2s_plus_the_repro_step_and_a_raised_cap():
    loc = (V6P / "prompts/locator.md").read_text()
    v5 = (V5H2 / "prompts/locator.md").read_text()
    assert f"at most {LOCATOR_CAP} tool calls" in loc and "at most 8 tool calls" in v5
    assert "cat > /tmp/repro.py <<'EOF'" in loc and 'run_command(command="python3 /tmp/swe/repro.py")' in loc
    assert "REPRO FAIL" in loc and "rewrite it once" in loc
    assert "REPRO: /tmp/repro.py (fails before fix)" in loc and "REPRO: none" in loc
    assert "no /workspace paths" in loc
    # nothing of v5h2's locator is lost
    for line in v5.splitlines():
        if line.startswith(("1. ", "2. ", "FILES:", "ROOT CAUSE:", "CHANGE:", "TEST:", "If a helper")):
            assert line in loc, line


def test_verifier_reuses_the_locators_repro():
    v = (V6P / "prompts/verifier.md").read_text()
    assert "python3 /tmp/swe/repro.py" in v and "REPRO: none" in v


# ---------------------------------------------------------------- selector

def test_selector_calls_select_py_once_with_skill_tools_only():
    y = _yaml(V6P / "sub_agents/selector.yaml")
    assert y.get("tools", []) == [] and y["skills"] == ["skills/swe-tools"] and y["include_contents"] == "none"
    p = (V6P / "prompts/selector.md").read_text()
    assert p.count(SELECT_CALL) == 1 and "exactly once" in p
    assert 'args={"test":' in p                                           # the locator's TEST file
    assert "run_command" not in p


# ---------------------------------------------------------------- prompts name only declared tools

def _declared(stage):
    y = (V6P / "sub_agents" / f"{stage}.yaml").read_text()
    tools = {t.strip() for t in re.search(r"^tools:\s*\[(.*)\]", y, re.M).group(1).split(",") if t.strip()}
    return tools | (SKILL_TOOLS if re.search(r"^skills:\s*\[\s*skills/swe-tools\s*\]", y, re.M) else set())


@pytest.mark.parametrize("stage", LLM_STAGES)
def test_every_tool_named_in_a_prompt_is_declared_by_that_stage(stage):
    sys.path.insert(0, str(ROOT / "tests"))
    from test_v10_prompts import HALLUCINATED, REGISTRY_FALLBACK, named_tools
    from test_v5b_bundle import affirmative
    vocab = REGISTRY_FALLBACK | SKILL_TOOLS | HALLUCINATED
    found = named_tools(affirmative((V6P / "prompts" / f"{stage}.md").read_text()), vocab)
    assert found <= _declared(stage), (stage, found - _declared(stage))
    assert ("submit_patch" in found) == (stage == "verifier"), stage


# ---------------------------------------------------------------- helpers: exist, install, probes

def helpers_used(b):
    used = set()
    for p in list((b / "prompts").glob("*.md")) + [b / "skills/swe-tools/SKILL.md"]:
        t = p.read_text()
        used |= set(re.findall(r"python3 /tmp/swe/(\w+\.py)", t))
        used |= set(re.findall(r'file_path="(\w+\.py)"', t))
    return used


def test_helpers_used_exist_and_install_into_the_sandbox_tmp(tmp_path):
    used = helpers_used(V6P)
    assert {"edit.py", "view.py", "test.py", "check.py", "locate.py", "repro.py", "select_best.py", "install.py"} <= used
    scripts = V6P / "skills/swe-tools/scripts"
    for h in used:
        assert (scripts / h).exists(), h
    env = dict(os.environ, TMPDIR=str(tmp_path), TEST_TMPDIR=str(tmp_path))
    p = subprocess.run([sys.executable, str(scripts / "install.py")], capture_output=True, text=True, env=env)
    assert p.returncode == 0 and "helpers in" in p.stdout, p.stdout + p.stderr
    for h in (used - {"install.py"}) | {"_ws.py"}:
        assert (tmp_path / "swe" / h).exists(), h


def probe_keys():
    src = (ROOT / "scripts" / "make_eval_kernel.py").read_text()
    block = src.split("PROBES = {", 1)[1].split("}\n", 1)[0]
    return set(re.findall(r'"(\w+\.py)":', block))


def test_kaggle_helper_check_probes_every_helper_including_select():
    assert helpers_used(V6P) - {"install.py"} <= probe_keys(), helpers_used(V6P) - probe_keys()


def test_no_helper_shadows_a_stdlib_module_that_helpers_import():
    """python3 /tmp/swe/x.py puts /tmp/swe first on sys.path: a select.py there breaks `import subprocess`."""
    stems = {p.stem for p in (V6P / "skills/swe-tools/scripts").glob("*.py")}
    assert not (stems & set(sys.stdlib_module_names)) - {"test"}, stems & set(sys.stdlib_module_names)
    # (test.py predates v6p; nothing on a helper's import path imports the stdlib `test` package)


@pytest.mark.parametrize("name", ["select_best.py", "repro.py"])
def test_new_helpers_are_stdlib_only_and_py311_syntax(name):
    import ast
    src = (V6P / "skills/swe-tools/scripts" / name).read_text()
    mods = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module.split(".")[0])
    assert mods - {"_ws"} <= set(sys.stdlib_module_names), mods - set(sys.stdlib_module_names)
    ast.parse(src, feature_version=(3, 11))                               # rejects 3.12-only syntax


def test_skill_md_documents_select_and_the_workdir_override():
    t = (V6P / "skills/swe-tools/SKILL.md").read_text()
    assert "select_best.py" in t and "repro.py" in t and "cd /tmp/w" in t


# ---------------------------------------------------------------- Kaggle eval kernel

def test_eval_kernel_slug_is_free_and_regenerates_identically(tmp_path):
    assert KERNEL_SLUG not in QUEUED_SLUGS
    kd = ROOT / "kernels" / KERNEL_DIR
    if not (kd / "kernel-metadata.json").is_file():
        pytest.skip(f"kernels/{KERNEL_DIR} not present (kernels/*/ is gitignored; generated on the Mac)")
    meta = (kd / "kernel-metadata.json").read_text()
    assert f'"id": "carsonrodrigues/{KERNEL_SLUG}"' in meta and '"docker_image_pinning_type": "original"' in meta
    assert '"machine_shape": "NvidiaL4"' in meta
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_eval_kernel.py"), str(V6P), KERNEL_DIR,
                        "--ids", str(ROOT / "data" / "kaggle_valid_ids.txt"), "--pin", "original",
                        "--kernel-id", KERNEL_SLUG], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    for f in ("kernel-metadata.json", KERNEL_SLUG + ".ipynb"):
        assert (tmp_path / "kernels" / KERNEL_DIR / f).read_bytes() == (kd / f).read_bytes(), f
