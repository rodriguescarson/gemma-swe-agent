"""v5b = v5all + three changes, one commit each (Carson 2026-10-05):
1. repo_map.py, an AST map of the repository (classes, functions, signatures, methods, line numbers), shipped in the
   swe-tools skill so install.py copies it into the sandbox tmp like every other helper.
2. Title-only issues: the locator maps the package and runs the nearest existing tests to get a spec.
3. Prompt guard: run_skill_script's file_path is one string, never a list (a list crashes the sandbox)."""
import ast, filecmp, os, re, subprocess, sys, time, zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
V5ALL, V5B = ROOT / "submissions" / "v5all", ROOT / "submissions" / "v5b"
SCRIPTS = V5B / "skills" / "swe-tools" / "scripts"
REPO_MAP = SCRIPTS / "repo_map.py"
CAP = 4500


def files(d):
    return {str(p.relative_to(d)) for p in d.rglob("*")
            if p.is_file() and not p.name.startswith(".") and "__pycache__" not in p.parts}


# ---------------------------------------------------------------- repo_map.py

def git_repo(tmp_path, tree):
    for rel, text in tree.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    subprocess.run("git init -q && git add -A && git -c user.email=a@b -c user.name=t commit -qm i", shell=True,
                   cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def repo_map(repo, *args, timeout=30):
    env = dict(os.environ, SWE_WS=str(repo))
    r = subprocess.run([sys.executable, str(REPO_MAP), *args], cwd=repo, env=env, capture_output=True, text=True,
                       timeout=timeout)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


SMALL = {
    "pkg/__init__.py": "",
    "pkg/core.py": ("import os\n\n"
                    "class Parser(Base):\n"
                    "    def __init__(self, text):\n        self.text = text\n\n"
                    "    def parse_header(self, line: str) -> dict:\n        return {}\n\n"
                    "    async def fetch(self, url, *, retries=3):\n        return None\n\n"
                    "def helper(a, b=1, *args, **kw) -> int:\n    return a\n\n"
                    "async def stream_rows(path):\n    yield path\n"),
    "pkg/util.py": "def slugify(s):\n    return s\n",
    "pkg/broken.py": "def oops(:\n    pass\n",
    "tests/test_core.py": "def test_parse_header_in_tests():\n    pass\n",
    "venv/lib/site.py": "def venv_only():\n    pass\n",
    ".venv/x.py": "def dot_venv_only():\n    pass\n",
}


def test_repo_map_lists_classes_functions_signatures_methods_and_lines(tmp_path):
    out = repo_map(git_repo(tmp_path, SMALL))
    assert "pkg/core.py" in out and "pkg/util.py" in out
    assert re.search(r"\b3\b.*class Parser\(Base\)", out), out
    assert re.search(r"def helper\(a, b=1, \*args, \*\*kw\) -> int", out), out
    assert re.search(r"parse_header:7\b", out) and re.search(r"__init__:4\b", out), out
    assert "slugify" in out


def test_repo_map_shows_async_defs(tmp_path):
    out = repo_map(git_repo(tmp_path, SMALL))
    assert re.search(r"async def stream_rows\(path\)", out), out
    assert re.search(r"async fetch:10\b", out), out


def test_repo_map_skips_syntax_errors_instead_of_failing(tmp_path):
    out = repo_map(git_repo(tmp_path, SMALL))
    assert "oops" not in out and "pkg/core.py" in out
    assert "broken.py" in out and "skipped" in out          # named once so the model knows it was not mapped


def test_repo_map_skips_tests_git_and_venvs(tmp_path):
    out = repo_map(git_repo(tmp_path, SMALL))
    for s in ("test_parse_header_in_tests", "venv_only", "dot_venv_only", ".git/"):
        assert s not in out, s


def test_repo_map_grep_filters_symbols_and_files(tmp_path):
    out = repo_map(git_repo(tmp_path, SMALL), "--grep", "header")
    assert "parse_header" in out and "pkg/core.py" in out
    assert "slugify" not in out and "pkg/util.py" not in out and "helper" not in out and "stream_rows" not in out
    assert "class Parser" in out                             # the class is kept as the context of its matching method
    assert "fetch" not in out                                # but its other methods are not


def test_repo_map_path_and_dotted_package_arguments(tmp_path):
    repo = git_repo(tmp_path, dict(SMALL, **{"src/other/deep/mod.py": "def deep_fn():\n    pass\n"}))
    out = repo_map(repo, "pkg/util.py")
    assert "slugify" in out and "Parser" not in out
    out = repo_map(repo, "other.deep")                       # a dotted package name, found under src/
    assert "deep_fn" in out and "slugify" not in out
    out = repo_map(repo, "pkg")
    assert "Parser" in out and "deep_fn" not in out


def big_repo(tmp_path, n_files=300, n_defs=30, reverse=False):
    tree = {}
    for i in range(n_files):
        body = "".join(f"def function_number_{j}_in_module_{i}(alpha, beta=None, *gamma, **delta) -> int:\n    return {j}\n\n"
                       for j in range(n_defs))
        body += f"class Klass{i}:\n" + "".join(f"    def method_{k}(self):\n        pass\n" for k in range(40))
        tree[f"pkg/sub{i % 7}/mod_{i:03d}.py"] = body
    items = sorted(tree.items(), reverse=reverse)
    return git_repo(tmp_path, dict(items))


def test_repo_map_output_is_capped_with_a_narrowing_footer(tmp_path):
    out = repo_map(big_repo(tmp_path))
    assert len(out) <= CAP, len(out)
    m = re.search(r"\.\.\. (\d+) more files, narrow with PATH or --grep", out)
    assert m and int(m.group(1)) > 0, out[-300:]
    assert out.count("mod_") >= 3                            # the cap still leaves room for real content


def test_repo_map_caps_one_huge_file_too(tmp_path):
    body = "".join(f"def f{j}_{'x' * 60}(a, b, c, d, e, f, g, h, i, j, k, l, m, n, o, p):\n    pass\n" for j in range(400))
    out = repo_map(git_repo(tmp_path, {"pkg/huge.py": body}))
    assert len(out) <= CAP and "pkg/huge.py" in out and "narrow with PATH or --grep" in out


def test_repo_map_is_deterministic(tmp_path):
    a = repo_map(big_repo(tmp_path / "a", n_files=40, reverse=False))
    b = repo_map(big_repo(tmp_path / "b", n_files=40, reverse=True))
    assert a == b == repo_map(tmp_path / "a")


def test_repo_map_is_fast_on_a_large_repo(tmp_path):
    repo = big_repo(tmp_path, n_files=600, n_defs=40)
    t = time.monotonic(); repo_map(repo); repo_map(repo, "--grep", "method_7"); dt = time.monotonic() - t
    assert dt < 5.0, dt


def test_repo_map_is_stdlib_only_and_python_3_11():
    src = REPO_MAP.read_text()
    tree = ast.parse(src, feature_version=(3, 11))
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert mods - {"_ws"} <= set(sys.stdlib_module_names), mods - set(sys.stdlib_module_names)


def test_install_copies_repo_map_into_the_sandbox_tmp(tmp_path):
    env = dict(os.environ, TMPDIR=str(tmp_path), TEST_TMPDIR=str(tmp_path))
    p = subprocess.run([sys.executable, str(SCRIPTS / "install.py")], capture_output=True, text=True, env=env)
    assert p.returncode == 0 and "repo_map.py" in p.stdout, p.stdout + p.stderr
    for h in ("repo_map.py", "edit.py", "locate.py", "test.py", "check.py", "view.py", "_ws.py"):
        assert (tmp_path / "swe" / h).exists(), h


def test_repo_map_reachable_through_the_subprocess_sandbox():
    """The harness sandbox rewrites /tmp in command text; repo_map.py must be callable the way the prompt says."""
    tsp = pytest.importorskip("test_sandbox_tmp_paths")
    m = tsp.sandbox_with_repo()
    assert "repo_map.py" in tsp.install_like_skill(m, SCRIPTS)
    r = m.run_command("python3 /tmp/swe/repo_map.py pkg --grep parse")
    o = r.stdout + r.stderr
    assert "can't open file" not in o and "parse_header" in o and "pkg/mod.py" in o, o


def test_kaggle_helper_check_probes_repo_map(tmp_path):
    mek = pytest.importorskip("test_make_eval_kernel")
    ids = tmp_path / "ids.txt"; ids.write_text("rich_3006\n")
    mek.build(tmp_path, V5B, "hc5b", "--ids", str(ids), "--oracle", "--helper-check", str(SCRIPTS))
    cell = mek.cells(tmp_path, "hc5b")[1]
    assert '"repo_map.py": "python3 /tmp/swe/repo_map.py pkg' in cell, cell[:2000]


def test_skill_md_lists_repo_map():
    s = (V5B / "skills" / "swe-tools" / "SKILL.md").read_text()
    assert "python3 /tmp/swe/repo_map.py" in s


# ---------------------------------------------------------------- bundle shape, compile, zip

def changed_vs_v5all():
    return {rel for rel in files(V5ALL) & files(V5B) if not filecmp.cmp(V5ALL / rel, V5B / rel, shallow=False)}


def test_v5b_is_v5all_plus_the_listed_changes_only():
    assert files(V5B) == files(V5ALL) | {"skills/swe-tools/scripts/repo_map.py"}
    assert changed_vs_v5all() <= {"skills/swe-tools/SKILL.md", "prompts/locator.md", "prompts/fixer.md",
                                  "prompts/verifier.md"}, changed_vs_v5all()


def test_v5b_compiles_with_the_official_compiler():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(V5B)], capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-1500:]
    assert "LlmAgent locator" in r.stdout and "SkillToolset" in r.stdout.split("LlmAgent locator")[1].split("\n")[0]


def test_v5b_packs_under_1_mb_with_repo_map_inside(tmp_path):
    z = tmp_path / "v5b.zip"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "pack_bundle.py"), str(V5B), str(z)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert z.stat().st_size < 1_000_000
    assert "skills/swe-tools/scripts/repo_map.py" in zipfile.ZipFile(z).namelist()


# ---------------------------------------------------------------- change 2: title-only issues -> tests as the spec

STAGES = ("locator", "fixer", "verifier")


def v5b_prompt(stage, bundle=V5B):
    return (bundle / "prompts" / f"{stage}.md").read_text()


def declared_tools(stage, bundle=V5B):
    """Tools a stage can call: its yaml tools list, plus the skill toolset when it declares a skill."""
    from test_v10_bundle import SKILL_TOOLS
    y = (bundle / "sub_agents" / f"{stage}.yaml").read_text()
    tools = {t.strip() for t in re.search(r"^tools:\s*\[(.*)\]", y, re.M).group(1).split(",")}
    return tools | (SKILL_TOOLS if re.search(r"^skills:\s*\[\s*skills/swe-tools\s*\]", y, re.M) else set())


def test_locator_has_the_title_only_rule_with_repo_map_and_nearest_tests():
    p = v5b_prompt("locator")
    rule = next((l for l in p.splitlines() if "only a title" in l), None)
    assert rule, "title-only rule missing"
    assert "under 3 lines" in rule
    assert 'python3 /tmp/swe/repo_map.py' in rule and "--grep" in rule        # the sandbox path, through run_command
    assert 'git grep -ln' in rule and "-- tests" in rule
    assert "python3 /tmp/swe/test.py --target" in rule                       # the real helper and flag
    assert "SPEC:" in p and "traceback" in p.lower()                          # failures reported as the spec
    assert "at most 8 tool calls" in p                                        # the call cap is unchanged
    base = v5b_prompt("locator", V5ALL).splitlines()
    assert 0 < len(p.splitlines()) - len(base) <= 6


def test_test_helper_named_in_prompts_takes_target():
    """The prompts use test.py --target; the shipped helper must read exactly that flag."""
    src = (SCRIPTS / "test.py").read_text()
    assert 'opt.get("target"' in src
    for s in STAGES:
        for m in re.finditer(r"python3 /tmp/swe/(\w+)\.py", v5b_prompt(s)):
            assert (SCRIPTS / f"{m.group(1)}.py").exists(), (s, m.group(0))


def affirmative(text):
    """Drop the explicit negations ("There is no edit_file tool", "(no git_grep, no bash tool)"): naming a tool to say
    it does not exist is the point of those lines, not a call."""
    text = re.sub(r"\(no [^)]*\)", " ", text)
    return re.sub(r"There is no [^.:]*[.:]", " ", text)


def test_every_tool_named_in_a_v5b_prompt_is_declared_by_that_stage():
    """Reuses the R89 matcher from the v10 prompt lints (tests/test_v10_prompts.named_tools)."""
    from test_v10_prompts import HALLUCINATED, REGISTRY_FALLBACK, named_tools
    from test_v10_bundle import SKILL_TOOLS
    vocab = REGISTRY_FALLBACK | SKILL_TOOLS | HALLUCINATED
    for s in STAGES:
        found = named_tools(affirmative(v5b_prompt(s)), vocab)
        assert found <= declared_tools(s), (s, found - declared_tools(s))
        assert ("submit_patch" in found) == (s == "verifier"), s
    assert named_tools(affirmative("then call git_grep('x')"), vocab) - declared_tools("locator") == {"git_grep"}  # control
    assert named_tools(affirmative("There is no edit_file tool and no bash tool: use x."), vocab) == set()


# ---------------------------------------------------------------- change 3: run_skill_script file_path guard

GUARD = 'run_skill_script takes file_path as ONE string (file_path="install.py"), never a list: a list crashes the sandbox.'


def test_file_path_guard_wherever_run_skill_script_appears():
    texts = {p.relative_to(V5B).as_posix(): p.read_text() for p in V5B.rglob("*.md")}
    texts.update({p.relative_to(V5B).as_posix(): p.read_text() for p in (V5B / "sub_agents").glob("*.yaml")})
    users = {k for k, t in texts.items() if "run_skill_script" in t}
    assert {"prompts/locator.md", "prompts/fixer.md", "prompts/verifier.md"} <= users
    for k in users:
        assert texts[k].count(GUARD) == 1, k
        assert len(texts[k].splitlines()) - len((V5ALL / k).read_text().splitlines()) >= 1, k


def test_guard_examples_never_show_a_list_file_path():
    for p in V5B.rglob("*.md"):
        assert not re.search(r"file_path\s*=\s*\[", p.read_text()), p
