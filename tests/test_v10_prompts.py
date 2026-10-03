"""v10 prompt and SKILL.md lints plus the context budget (docs/v10/SPEC.md sections 3 and 6; R87-R96, owner: config,
TP). Helper USAGE/FLAGS are read from the scripts via AST, and each test that needs a helper skips cleanly while that
script is not built yet. Helpers are never run inside submissions/ (the parse check runs on a temp copy)."""
import ast, asyncio, importlib.util, json, os, pathlib, re, shutil, subprocess, sys, tempfile, time, types
import pytest

try:  # R120: every v10 module takes the autouse orphan-process check from the core support package
    from v10_support.repo import no_orphans  # noqa: F401
except Exception:  # built in parallel by the core component; absent until it lands
    pass

from test_v10_bundle import (BUNDLE, CLI_SCRIPTS, GEN, GRAPH_TOOLS, LIB_SCRIPTS, ROOT, SCRIPTS, SKILL_TOOLS,
                             STAGES, SUBMITTERS, NotConstant, _parse, common_alias_env, common_constants,
                             compiled_info, const_eval, helper_usage_flags, is_v102, load_yaml, module_constants,
                             prompts, read, spec_blocks, spec_text, stage_tools_yaml, SPEC_V102)

PLACEHOLDERS = ("{problem_description}", "{plan?}", "{fix_notes?}")
STAGE_PLACEHOLDERS = {"setup": set(), "locator": {"{problem_description}"},
                      "fixer": {"{problem_description}"},       # the plan arrives as the handoff (review round 2)
                      "verifier": {"{problem_description}", "{plan?}"},
                      "submitter": {"{problem_description}", "{plan?}"}}     # v10.1: the submitter sees the issue
REGISTRY_FALLBACK = {"run_command", "read_file", "edit_file", "write_file", "get_status", "submit_patch",
                     "get_code_neighbors", "search_similar_code", "get_code_subgraph"}
HALLUCINATED = {"git_grep", "exit_loop", "bash", "transfer_to_agent", "search_skills"}
HELPER_OUTPUT_TOOLS = {"run_command", "run_skill_script"}   # SPEC 4.0.10: the only tools helper output may name
BLOCK_STAGES = {"RECOVER": ("locator", "fixer", "verifier", "submitter"), "AMNESIA": ("locator", "fixer", "verifier"),
                "TIME": ("locator", "fixer", "verifier"), "HELPERS": ("locator", "fixer", "verifier", "submitter"),
                "EDITFORM": ("fixer", "verifier", "submitter")}
INSTALL_CALL = 'run_skill_script(file_path="install.py", skill_name="swe-tools")'
SKILL_MD = BUNDLE / "skills" / "swe-tools" / "SKILL.md"

# SPEC 6: token estimates are 3.4 chars/token for prose and declarations. Tool output (review round 1, measured on the
# race-1 and e74 traces): median 3.06 chars/token, worst decile 2.3 (p10 2.18-2.39).
PROSE, TOOL = 3.4, 3.06
TOOL_P10 = 2.3
COMPACTION = 14336
DECL_FALLBACK = {False: 7181, True: 7553}   # compiled declaration chars without/with submit_patch (measured 09-28)
SKILL_FALLBACK = 1333
WORST_PROBLEM_CHARS = 10095                 # fastapi_14463, the longest Kaggle-valid statement (a lone outlier)
P95_PROBLEM_CHARS = 2455                    # the p95 Kaggle-valid statement (74 tasks; next after it: 2,679)
WORST_TREE_CHARS = 4777                     # the longest 150-line workspace tree in the race-1 traces
# SPEC 4.14 (typical, cap) stdout chars; "repro" is verify.py --repro-only (SPEC 4.11 cap 1,200; SPEC 6 typical
# out 300 tokens); "submit" is submit_patch's short confirmation.
HELPER_OUT = {"install": (180, 400), "locate": (1200, 1800), "grep": (800, 1800), "view": (2500, 2800),
              "edit": (700, 1500), "run": (600, 2500), "verify": (900, 2000), "finalize": (250, 1000),
              "status": (1200, 2200), "status_start": (600, 800), "repro": (900, 1200), "submit": (150, 150)}
# v10.2 (SPEC_v10_2 6): "status_start" is the phase-start status (the LOCATOR DIGEST, cap 800) that the v10.2 fixer
# runs first; a v10.1 bundle's fixer prompt has no such step, so its mix is unchanged.
V102 = is_v102()
STATUS_FIRST = "1. Run python3 /tmp/swe/status.py first"


def permitted_mix():
    """The call mix each prompt PERMITS (review round 1: R95 used to model a lighter mix than the prompts allow), as
    {stage: ([(helper, calls, model-written tokens per call)], final reply tokens)}. The round limits are read from the
    prompts, so loosening a prompt loosens the model with it: the fixer makes 3 edits after viewing the plan's files,
    then verifies up to R rounds with a view and an edit between rounds; the verifier checks status, verifies, repairs
    up to K rounds (view + edit + verify each) and runs finalize twice (NOT READY once) before submitting."""
    ps = prompts()
    r = int(re.search(r"at most (\d+) rounds?", ps["fixer"]).group(1))
    k = int(re.search(r"at most (\d+) repair rounds", ps["verifier"]).group(1))
    start = [("status_start", 1, 30)] if STATUS_FIRST in ps["fixer"] else []
    return {"setup": ([("install", 2, 30)], 5),
            "locator": ([("locate", 1, 30), ("view", 3, 30), ("grep", 2, 30), ("repro", 2, 350), ("run", 1, 30)], 250),
            "fixer": (start + [("view", 3 + (r - 1), 30), ("edit", 3 + (r - 1), 400), ("verify", r, 30)], 100),
            "verifier": ([("status", 1, 30), ("verify", 1 + k, 30), ("view", k, 30), ("edit", k, 400),
                          ("finalize", 2, 30), ("submit", 1, 30)], 20),
            "submitter": ([("finalize", 2, 30), ("edit", 1, 400), ("submit", 1, 30)], 5)}


# What a stage may still do after the CONTEXT hint (the hint text): the locator replies; the fixer makes one missing
# edit; the verifier runs finalize and submits; setup and the submitter never reach it.
AFTER_HINT = {"setup": [], "locator": [], "fixer": [("edit", 1, 400)],
              "verifier": [("finalize", 1, 30), ("submit", 1, 30)], "submitter": [("finalize", 1, 30)]}
PREV_STAGE = {"locator": "setup", "fixer": "locator", "verifier": "fixer", "submitter": "verifier"}


def strip_placeholders(text):
    for p in PLACEHOLDERS:
        text = text.replace(p, "")
    return text


# ---------------------------------------------------------------- R87 braces
def test_brace_lint():
    """R87: the only {...} are {problem_description}, {plan?} and {fix_notes?}, each where its stage needs it; no
    other brace characters; downstream placeholders are optional and produced by an earlier stage's output_key."""
    produced = {"problem_description"}   # the harness puts it in session state
    for s, text in prompts().items():
        found = re.findall(r"\{[^{}]*\}", text)
        assert set(found) == STAGE_PLACEHOLDERS[s], (s, found)
        assert all(text.count(p) <= 1 for p in PLACEHOLDERS), s
        rest = strip_placeholders(text)
        assert "{" not in rest and "}" not in rest, s
        for ph in found:
            var = ph.strip("{}")
            assert var.rstrip("?") in produced, (s, ph, "used before any stage produces it")
            assert var == "problem_description" or var.endswith("?"), (s, ph, "output_key only exists after a reply")
        okey = load_yaml(f"sub_agents/{s}.yaml").get("output_key")
        if okey:
            produced.add(okey)
    skill = SKILL_MD.read_text(encoding="utf-8")
    assert "{" not in skill and "}" not in skill


def _manual_render(text, state):
    """One pass, like ADK: an inserted value is never templated again (a statement may contain {plan?})."""
    def sub(m):
        var = m.group(1)
        return str(state[var]) if not m.group(2) else str(state.get(var, ""))
    return re.sub(r"\{(problem_description|plan|fix_notes)(\?)?\}", sub, text)


def adk_render(text, state):
    from google.adk.utils.instructions_utils import inject_session_state
    ctx = types.SimpleNamespace(_invocation_context=types.SimpleNamespace(
        session=types.SimpleNamespace(state=state, app_name="a", user_id="u", id="s"), artifact_service=None))
    return asyncio.run(inject_session_state(text, ctx))


def test_brace_render_with_adk():
    """R87 with ADK's own templating: renders with plan/fix_notes absent (first pass, and after a nudge), a problem
    statement full of braces is inserted verbatim, and ADK gives exactly the manual substitution."""
    if importlib.util.find_spec("google.adk") is None:
        pytest.skip("google-adk not installed here")
    problem = "Fix {x} and {{y}} in f'{z!r}' / {plan?} literal"
    for state in ({"problem_description": problem},
                  {"problem_description": problem, "plan": "FILES: a.py:1-2 {k}", "fix_notes": "CHANGED: a.py"}):
        for s, text in prompts().items():
            got = adk_render(text, dict(state))
            assert got == _manual_render(text, dict(state)), s
            if "{problem_description}" in text:
                assert problem in got, s


# ---------------------------------------------------------------- R88 backticks, template order, format
def test_no_backticks_template_order():
    """R88: 0 backticks in prompts and SKILL.md; every run_skill_script( example lists file_path= before skill_name=
    and is the exact install call; files are ASCII, LF, tab-free, with no trailing spaces and one final newline."""
    texts = dict(prompts())
    texts["SKILL.md"] = SKILL_MD.read_text(encoding="utf-8")
    skill_name = re.search(r"^name:\s*(\S+)", texts["SKILL.md"], re.M).group(1)
    n_calls = 0
    for name, text in texts.items():
        assert "`" not in text, name
        assert text.isascii() and "\r" not in text and "\t" not in text, name
        assert not re.search(r"[ ]+\n", text) and text.endswith("\n") and not text.endswith("\n\n"), name
        for m in re.finditer(r"run_skill_script\(([^)]*)\)", text):
            n_calls += 1
            args = m.group(1)
            assert args.find("file_path=") >= 0 and args.find("file_path=") < args.find("skill_name="), (name, args)
            assert m.group(0) == INSTALL_CALL, (name, m.group(0))
            assert f'skill_name="{skill_name}"' in args
        assert text.count("run_skill_script(") == len(re.findall(r"run_skill_script\(([^)]*)\)", text)), name
    assert n_calls >= 5   # setup, RECOVER in 4 stages, SKILL.md
    setup_lines = texts["setup"].splitlines()
    assert INSTALL_CALL in setup_lines, "setup must show the call alone on its own line"
    assert skill_name == SKILL_MD.parent.name


# ---------------------------------------------------------------- R89 named tools
def _tool_vocabulary():
    info = compiled_info(strict=False)
    registry = set(info["registry"]) if info else set(REGISTRY_FALLBACK)
    return registry | SKILL_TOOLS | HALLUCINATED


def named_tools(text, vocab):
    """Tool names a text mentions: snake_case names as whole words; bash only in call form (it is also a shell)."""
    found = set()
    for n in vocab:
        pat = r"(?<![A-Za-z0-9_])bash\s*\(" if n == "bash" else r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(n)
        if re.search(pat, text):
            found.add(n)
    return found


def test_named_tools_declared():
    """R89 (bundle text): each prompt names only tools its stage declares; submit_patch only in the verifier and
    submitter prompts; graph tools and known hallucinations nowhere; SKILL.md only tools every stage declares."""
    vocab = _tool_vocabulary()
    every_stage = set.intersection(*(stage_tools_yaml(s) for s in STAGES))
    for s, text in prompts().items():
        found = named_tools(text, vocab)
        assert found <= stage_tools_yaml(s), (s, found - stage_tools_yaml(s))
        assert not found & (GRAPH_TOOLS | HALLUCINATED), (s, found)
        assert ("submit_patch" in found) == (s in SUBMITTERS), s
    skill = named_tools(SKILL_MD.read_text(encoding="utf-8"), vocab)
    assert skill <= every_stage - {"submit_patch"} and not skill & GRAPH_TOOLS, skill
    assert {"run_skill_script", "run_command"} <= skill


def test_named_tools_lint_catches_violations():
    """R89 control: the matcher flags a graph tool, submit_patch in a non-submitting prompt, a hallucinated call and
    ignores lookalikes (my_run_command, bash as a shell)."""
    vocab = REGISTRY_FALLBACK | SKILL_TOOLS | HALLUCINATED
    assert named_tools("use search_similar_code(query)", vocab) == {"search_similar_code"}
    assert named_tools("then call submit_patch.", vocab) == {"submit_patch"}
    assert named_tools("git_grep('x') or bash(command='ls')", vocab) == {"git_grep", "bash"}
    assert named_tools("my_run_command and run_commands; bash -c 'x'", vocab) == set()
    assert not named_tools("Call submit_patch.", vocab) <= stage_tools_yaml("fixer")


def _string_constants(tree):
    """(docstrings, other string constants) of a module; f-string constant parts count as other constants."""
    docs, others = [], []
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and \
                    isinstance(first.value.value, str):
                docs.append(first.value.value)
                doc_ids.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in doc_ids:
            others.append(node.value)
    return docs, others


@pytest.mark.parametrize("script", LIB_SCRIPTS + CLI_SCRIPTS)
def test_named_tools_declared_helpers(script):
    """R89 (helper strings, AST): output strings name only run_command and run_skill_script (SPEC 4.0.10);
    docstrings only tools every stage declares; submit_patch, graph tools and hallucinations in no helper string;
    the skill is never called swe_tools (the v9 locate.py docstring bug)."""
    p = SCRIPTS / f"{script}.py"
    if not p.exists():
        pytest.skip(f"{p.name} not built yet")
    vocab = _tool_vocabulary()
    every_stage = set.intersection(*(stage_tools_yaml(s) for s in STAGES)) - {"submit_patch"}
    docs, others = _string_constants(_parse(str(p)))
    for text in docs + others:
        found = named_tools(text, vocab)
        assert not found & ({"submit_patch"} | GRAPH_TOOLS | HALLUCINATED), (p.name, found, text[:120])
        assert "swe_tools" not in text, (p.name, text[:120])
    for text in docs:
        assert named_tools(text, vocab) <= every_stage, (p.name, text[:120])
    for text in others:
        assert named_tools(text, vocab) <= HELPER_OUTPUT_TOOLS, (p.name, text[:120])


def harness_prompts(tmp_path, problem, tree):
    """The stage-1 user message exactly as the scorer builds it (graphs on), with testing enabled and masked."""
    runner = pytest.importorskip("swegemma.harness.agent_runner")
    from swegemma.budget import EvaluationBudget, HarnessLimits
    ev = load_yaml("eval_config.yaml")["evaluation"]
    gdir, edir = tmp_path / "graphs", tmp_path / "emb"
    gdir.mkdir()
    edir.mkdir()
    (gdir / "fastapi.json").write_bytes(b"{" + b" " * 200 + b"}")
    (edir / "fastapi.npz").write_bytes(b"\0" * 200)
    cfg = types.SimpleNamespace(
        budget=EvaluationBudget(time_minutes=ev["max_time_minutes"], tool_calls=ev["max_tool_calls"],
                                turns=ev["max_turns"]),
        harness=HarnessLimits(command_timeout_seconds=ev["timeout_seconds"]),
        graph_dir=str(gdir), embeddings_dir=str(edir))
    task = types.SimpleNamespace(repo="fastapi/fastapi", problem_statement=problem, hints_text="",
                                 base_commit="0" * 40, instance_id="fastapi_x")
    out = [runner.build_agent_prompt(task, cfg, tree, enable_sandbox_testing=flag) for flag in (True, False)]
    assert all("## Code Intelligence Tools" in t for t in out), "graphs were not rendered"
    return out


def test_named_tools_declared_harness_prompt(tmp_path):
    """R89 (harness prompt): with graphs on, every tool the stage-1 prompt names is declared on setup, except
    submit_patch (the documented exception, SPEC 0.2)."""
    vocab = _tool_vocabulary()
    for text in harness_prompts(tmp_path, "Fix the bug.", "."):
        found = named_tools(text, vocab)
        assert "submit_patch" in found and GRAPH_TOOLS <= found
        assert found - {"submit_patch"} <= stage_tools_yaml("setup"), found - stage_tools_yaml("setup")


# ---------------------------------------------------------------- R90 shared blocks
def missing_blocks(text, names, blocks):
    return [b for b in names if ("\n" + text).count("\n" + blocks[b] + "\n") != 1]


def test_shared_blocks_identical():
    """R90: RECOVER, AMNESIA and TIME appear once, byte-identical, in locator, fixer and verifier; RECOVER also in
    submitter; EDITFORM in fixer, verifier and submitter; all equal the SPEC section 3 text; setup has none."""
    blocks = spec_blocks(spec_text())
    ps = prompts()
    for s, text in ps.items():
        want = [b for b, stages in BLOCK_STAGES.items() if s in stages]
        assert not missing_blocks(text, want, blocks), (s, missing_blocks(text, want, blocks))
        for b in set(blocks) - set(want):
            assert blocks[b] not in text, (s, b)
    # control: one changed character in a copy is detected
    mutated = ps["verifier"].replace("Never resend a failing edit.", "Never resend a failing edit!")
    assert missing_blocks(mutated, ["EDITFORM"], blocks) == ["EDITFORM"]


# ---------------------------------------------------------------- R91 sizes
def prompt_size(text):
    body = strip_placeholders(text)
    return len(body.split()), len(body)


R91_LIMITS = {"locator": (460, 2850), "fixer": (410, 2600)} if V102 else {}     # SPEC_v10_2 3.1


def test_prompt_sizes():
    """R91: at most 370 words and 2,600 chars per prompt excluding placeholders (v10.2: locator 460 / 2,850, fixer
    410 / 2,600); submitter at most 1,300 chars; setup at most 600; the measurement reproduces the SPEC section 3
    table (v10.2: SPEC_v10_2 3.1's column, 'unchanged' meaning SPEC's)."""
    sizes = {s: prompt_size(t) for s, t in prompts().items()}
    for s, (words, chars) in sizes.items():
        lim = R91_LIMITS.get(s, (370, 2600))
        assert words <= lim[0] and chars <= lim[1], (s, words, chars)
    assert sizes["submitter"][1] <= 1300 and sizes["setup"][1] <= 600, sizes
    spec = spec_text()
    v102 = SPEC_V102.read_text(encoding="utf-8") if V102 else ""
    for s in STAGES:
        m = re.search(r"^\s*\| %s \| (\d+) \| ([\d,]+) \|" % s, spec, re.M)
        assert m, s
        want = (int(m.group(1)), int(m.group(2).replace(",", "")))
        if V102:
            m2 = re.search(r"^\| %s \| [\d,]+ / [\d,]+ \| (?:(\d+) / ([\d,]+)|unchanged) \|" % s, v102, re.M)
            assert m2, s
            if m2.group(1):
                want = (int(m2.group(1)), int(m2.group(2).replace(",", "")))
        assert sizes[s] == want, (s, sizes[s], want)


# ---------------------------------------------------------------- R92 commands and flags
_CMD = re.compile(r"python3 /tmp/swe/(\w+)\.py")
_TOKEN = re.compile(r"""(\s*)("[^"]*"|'[^']*'|<<'?\w+'?|\S+)""")
_PROSE = re.compile(r"^[a-z]+[.,;:]?$")
_FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9_-]*")
_HELPER_MENTION = re.compile(r"(?<![\w/.])(?:python3 /tmp/swe/)?(\w+)\.py\b")
RENDER = {"FILE": "pkg/mod.py", "START": "10", "END": "40", "NAME": "Class.method"}


def _scan_args(rest):
    """Arguments of one command example, up to the first prose, annotation or heredoc; (tokens, heredoc)."""
    toks, pos = [], 0
    while True:
        m = _TOKEN.match(rest, pos)
        if not m:
            return toks, False
        gap, tok = m.group(1), m.group(2)
        if toks and len(gap) >= 3 or tok.startswith("("):
            return toks, False
        if tok.startswith("<<"):
            return toks, True
        if _PROSE.match(tok) or (tok.endswith((".", ",")) and not tok.startswith(("'", '"')) and "/" not in tok):
            return toks, False
        toks.append(tok)
        pos = m.end()


def command_examples(text):
    """[(script, raw tokens, heredoc, line)] for every python3 /tmp/swe/X.py example, including the items of an
    'each as python3 /tmp/swe/NAME.py: a.py ARGS, b.py' list."""
    out = []
    for line in text.splitlines():
        if line.startswith("- python3 /tmp/swe/"):
            continue   # SKILL.md synopsis lines: checked against USAGE (R93) and for flags only
        for m in _CMD.finditer(line):
            name, rest = m.group(1), line[m.end():]
            if name == "NAME":
                if rest.startswith(":"):
                    for item in rest[1:].split(","):
                        item = item.strip().rstrip(".")
                        im = re.match(r"(\w+)\.py\b(.*)$", item)
                        assert im, (item, line)
                        toks, heredoc = _scan_args(im.group(2))
                        out.append((im.group(1), toks, heredoc, line))
                continue
            toks, heredoc = _scan_args(rest)
            out.append((name, toks, heredoc, line))
    return out


def flag_mentions(text):
    """[(script, --flag)]: each flag is attributed to the helper mentioned last before it (prose included)."""
    out, current = [], None
    events = sorted([(m.start(), "h", m.group(1)) for m in _HELPER_MENTION.finditer(text)
                     if m.group(1) in CLI_SCRIPTS] + [(m.start(), "f", m.group(0)) for m in _FLAG.finditer(text)])
    for _, kind, val in events:
        if kind == "h":
            current = val
        else:
            assert current is not None, f"flag {val} before any helper is named"
            out.append((current, val))
    return out


def all_texts():
    t = {f"prompts/{s}.md": v for s, v in prompts().items()}
    t["SKILL.md"] = SKILL_MD.read_text(encoding="utf-8")
    return t


def render_example(tokens):
    argv = []
    for tok in tokens:
        if tok[:1] in "\"'" and tok[-1:] == tok[:1]:
            tok = tok[1:-1]
        argv.append(RENDER.get(tok, tok))
    return argv


def _norm(flag):
    return flag.lstrip("-").replace("_", "-")


def test_prompt_commands_name_known_scripts():
    """R92: every python3 /tmp/swe/X.py (and every item of a helper list) names a section-1 CLI script; the
    extraction itself sees every example (a count guard against a silently broken parser)."""
    total = 0
    for name, text in all_texts().items():
        for m in _CMD.finditer(text):
            assert m.group(1) in CLI_SCRIPTS + ("NAME",), (name, m.group(0))
        for script, toks, heredoc, line in command_examples(text):
            assert script in CLI_SCRIPTS, (name, script, line)
            total += 1
    assert total >= 25, total      # v10.1: the NAME.py item lists are gone (R89b); every example is a full command
    ex = {(s, tuple(t), h) for s, t, h, _ in command_examples(prompts()["locator"])}
    assert ("view", ("--obj", "package.module.Name"), False) in ex
    assert ("run", ("--timeout", "20", '"command"'), False) in ex
    assert ("verify", ("--repro-only",), True) in ex
    assert ("view", ("FILE", "START", "END"), False) in ex and ("status", (), False) in ex
    ex = {(s, tuple(t), h) for s, t, h, _ in command_examples(prompts()["fixer"])}
    assert ("edit", ("path/to/file.py", "--lines", "120-135"), True) in ex
    assert ("grep", ('"regex"',), False) in ex and ("locate", ('"key words"',), False) in ex


def test_flag_attribution_unit():
    """R92 control: prose flags go to the helper named last; SKILL synopsis flags to their line's helper."""
    got = flag_mentions('python3 /tmp/swe/grep.py "x"   (add --tests)\nview.py a; use view.py --obj it.\n'
                        "python3 /tmp/swe/edit.py path/to/file.py --lines 1-2\nFor a new file use --create.\n"
                        "- python3 /tmp/swe/verify.py [--repro-only] [--tests FILE ...]\n")
    assert got == [("grep", "--tests"), ("view", "--obj"), ("edit", "--lines"), ("edit", "--create"),
                   ("verify", "--repro-only"), ("verify", "--tests")]
    toks, heredoc = _scan_args(" and continue from it.")
    assert toks == [] and heredoc is False


def parse_call_spec(path, env):
    """How the script calls parse_args: (usable, positionals, keyword args), from its first call in source order.
    A script without a call is checked against parse_args' defaults; a non-constant argument makes it unusable."""
    calls = sorted((n for n in ast.walk(_parse(str(path))) if isinstance(n, ast.Call) and
                    (n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")) == "parse_args"),
                   key=lambda n: (n.lineno, n.col_offset))
    if not calls:
        return True, (), {}
    node = calls[0]
    try:
        pos = const_eval(node.args[2], env) if len(node.args) >= 3 else ()
        kwargs = {k.arg: const_eval(k.value, env) for k in node.keywords if k.arg and k.arg != "usage"}
    except (NotConstant, TypeError):
        return False, None, {}
    if "positionals" in kwargs:
        pos = kwargs.pop("positionals")
    return True, list(pos) if isinstance(pos, (list, tuple)) else pos, kwargs


_PARSE_DRIVER = r'''
import contextlib, inspect, io, json, sys
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import _swe_common as C
jobs = json.loads(sys.stdin.read())
sig = inspect.signature(C.parse_args)
names = list(sig.parameters)
out = []
for job in jobs:
    buf, err, code = io.StringIO(), None, None
    args = [job["argv"], job["flags"], job["positionals"]]
    kwargs = dict(job["kwargs"])
    if "usage" in names[len(args):]:
        kwargs["usage"] = job["usage"]
    try:
        with contextlib.redirect_stdout(buf):
            C.parse_args(*args, **kwargs)
    except SystemExit as e:
        code = e.code
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, e)
    out.append({"stdout": buf.getvalue()[-600:], "exit": code, "error": err})
print("V10JSON:" + json.dumps(out))
'''


def run_parse_args(jobs):
    with tempfile.TemporaryDirectory() as td:
        dst = pathlib.Path(td) / "scripts"
        shutil.copytree(SCRIPTS, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", HOME=td, TMPDIR=td, SWE_DIR=os.path.join(td, "swe"),
                   SWE_DUAL="0", SWE_WS=td)
        env.pop("TEST_TMPDIR", None)
        r = subprocess.run([sys.executable, "-c", _PARSE_DRIVER, str(dst)], input=json.dumps(jobs), text=True,
                           capture_output=True, timeout=60, cwd=td, env=env)
    line = [x for x in r.stdout.splitlines() if x.startswith("V10JSON:")]
    assert line, f"parse driver failed: {r.stdout[-800:]} {r.stderr[-2000:]}"
    return json.loads(line[-1][8:])


def _error_signal(res):
    text = (res["stdout"] or "") + (res["error"] or "")
    return bool(res["error"]) or res["exit"] not in (None, 0) or "USAGE ERROR" in text or "unknown option" in text


@pytest.mark.parametrize("script", [s for s in CLI_SCRIPTS if s != "install"])
def test_prompt_commands_match_flags(script):
    """R92: every flag the prompts and SKILL.md give this helper is in its FLAGS, and every rendered example parses
    with _swe_common.parse_args (no USAGE ERROR); control: an unknown flag is reported."""
    uf = helper_usage_flags(script)
    if uf is None:
        pytest.skip(f"{script}.py not built yet")
    usage, flags = uf
    assert isinstance(flags, dict) and isinstance(usage, str), script
    known = {_norm(k) for k in flags}
    mentions = [(src, f) for src, text in all_texts().items() for s, f in flag_mentions(text) if s == script]
    for src, f in mentions:
        assert _norm(f) in known, f"{src}: {f} is not in {script}.py FLAGS {sorted(flags)}"
    examples = [(src, render_example(t)) for src, text in all_texts().items()
                for s, t, _, _ in command_examples(text) if s == script]
    assert examples, f"no example of {script}.py in any prompt"
    if not (SCRIPTS / "_swe_common.py").exists():
        pytest.skip("_swe_common.py not built yet: flags checked statically only")
    p = SCRIPTS / f"{script}.py"
    env = common_alias_env(p)
    env.update(module_constants(p, env))
    usable, positionals, kwargs = parse_call_spec(p, env)
    if not usable:
        pytest.skip(f"{script}.py: its parse_args call has non-constant arguments; flags checked statically only")
    t0 = time.monotonic()
    jobs = [{"argv": argv, "flags": flags, "positionals": positionals, "kwargs": kwargs, "usage": usage}
            for _, argv in examples]
    jobs.append({"argv": ["--zz-not-a-flag"], "flags": flags, "positionals": positionals, "kwargs": kwargs,
                 "usage": usage})
    res = run_parse_args(jobs)
    assert time.monotonic() - t0 < 10
    assert _error_signal(res[-1]), f"control: parse_args accepted an unknown flag, so R92 cannot discriminate: {res[-1]}"
    for (src, argv), r in zip(examples, res):
        assert not _error_signal(r), f"{src}: {script}.py {argv} -> {r}"


# ---------------------------------------------------------------- R93 SKILL.md
def skill_parts():
    text = SKILL_MD.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)\Z", text, re.S)
    assert m, "SKILL.md needs a front matter block"
    front = dict(line.split(": ", 1) for line in m.group(1).splitlines())
    return front, m.group(2).splitlines()


def test_skill_md():
    """R93: name equals the directory (kebab case); description 300 chars or fewer with the install call; the body
    starts with the heading and the install line; one usage line per CLI helper except install."""
    front, body = skill_parts()
    assert set(front) == {"name", "description"}
    assert front["name"] == SKILL_MD.parent.name == "swe-tools"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", front["name"])
    assert len(front["description"]) <= 300 and INSTALL_CALL in front["description"]
    lines = [x for x in body if x.strip()]
    assert lines[0] == "# swe-tools" and lines[1] == "Install: " + INSTALL_CALL
    usage = [x[2:] for x in lines if x.startswith("- python3 /tmp/swe/")]
    stems = [re.match(r"python3 /tmp/swe/(\w+)\.py", u).group(1) for u in usage]
    assert sorted(stems) == sorted(s for s in CLI_SCRIPTS if s != "install") and len(set(stems)) == len(stems)
    assert all(u.startswith(f"python3 /tmp/swe/{st}.py") and "`" not in u for u, st in zip(usage, stems))


@pytest.mark.parametrize("script", CLI_SCRIPTS)
def test_skill_md_usage_matches(script):
    """R93: each helper's USAGE constant (AST) starts with its /tmp/swe path and equals its SKILL.md usage line."""
    uf = helper_usage_flags(script)
    if uf is None:
        pytest.skip(f"{script}.py not built yet")
    usage, flags = uf
    assert usage.startswith(f"python3 /tmp/swe/{script}.py"), usage
    assert "`" not in usage and "swe_tools" not in usage
    if script == "install":
        return
    _, body = skill_parts()
    assert "- " + usage in body, f"SKILL.md usage line for {script}.py differs from USAGE {usage!r}"


# ---------------------------------------------------------------- R94/R95 context budget
def _cycle_words(template, n):
    words = template.split()
    return " ".join(words[i % len(words)] for i in range(n))


PLAN = _cycle_words(
    "FILES: fastapi/dependencies/utils.py:512-590 (solve_dependencies) fastapi/routing.py:210-260 "
    "(APIRoute.__init__) CAUSE: the dependency cache key ignores the security scopes, so two routes share one "
    "resolved value. FIX: include security_scopes in the cache key tuple and pass them through get_sub_dependant "
    "unchanged. REPRO: fails on original TESTS: tests/test_dependency_cache.py", 120)
NOTES = _cycle_words(
    "CHANGED: fastapi/dependencies/utils.py solve_dependencies (512-530) and get_sub_dependant (140-176) "
    "VERIFY: VERIFY: RED - 1/2 claims fixed; the second claim still fails on the scope order", 60)

# Review round 2: the handoffs are sized from the MEASURED race-1 stage-final replies, not from the word counts the
# prompts ask for (v9 asked for 250 words and got 2-4x that). Completion tokens, r_v4 / r_v9_eog, 46-53 replies per
# stage per run: locator median 418 / 442, p90 1,020 / 1,087, 2 / 4 runaways of 1,536+; fixer median 144 / 145, p90
# 244 / 205; verifier median 76 / 86, p90 147 / 188. The larger run is used. A reply longer than its stage's
# max_output_tokens is cut there (a text reply cut at the cap still ends the stage, facts_internal 2.3), so every size
# is also bounded by configs/gen_<stage>.yaml; "cap" is that bound itself.
REPLY_TOKENS = {"p50": {"locator": 442, "fixer": 145, "verifier": 86},
                "p90": {"locator": 1087, "fixer": 244, "verifier": 188}}
REPLY_TEMPLATE = {"locator": PLAN, "fixer": NOTES, "verifier": "Submitted the patch after finalize said READY."}
B_MARGIN = 1000             # check B must clear the compaction line by this many tokens (review round 2)
# Model-written tokens of edit-like calls (edit_file, write_file, replace.py, edit.py) in all six race-1 runs, n=5,329:
# median 101, p75 147, p90 256. The permitted mix keeps 400 per edit (its worst case); the first-round control uses p90.
EDIT_TOKENS_P90 = 256


def max_output(stage):
    return int(load_yaml(f"configs/gen_{stage}.yaml")["max_output_tokens"])


def reply_tokens(stage, q):
    """A stage's final reply in tokens at quantile q ('p50', 'p90' or 'cap'), bounded by its max_output_tokens."""
    cap = max_output(stage)
    return cap if q == "cap" else min(REPLY_TOKENS[q][stage], cap)


def reply_text(stage, q):
    """Reply text of reply_tokens(stage, q) tokens at the prose density the model counts (3.4 chars/token)."""
    n = int(round(reply_tokens(stage, q) * PROSE))
    t = REPLY_TEMPLATE[stage]
    return ((t + " ") * (n // (len(t) + 1) + 1))[:n]


def worst_problem():
    tasks, ids = ROOT / "data" / "tasks.jsonl", ROOT / "data" / "kaggle_valid_ids.txt"
    if tasks.exists() and ids.exists():
        valid = set(ids.read_text().split())
        rows = [json.loads(x) for x in tasks.read_text(encoding="utf-8").splitlines() if x.strip()]
        text = max((r["problem_statement"] for r in rows if r["instance_id"] in valid), key=len)
        assert len(text) >= WORST_PROBLEM_CHARS
        return text
    return _cycle_words("Response model validation fails for nested generic aliases when a default is set.",
                        2000)[:WORST_PROBLEM_CHARS]


def worst_tree():
    """150 lines, 5,067 chars: longer than the longest real tree (4,777 chars, fastapi)."""
    lines = ["."] + [f"./pkg_{i:03d}/sub_module/file_{i:03d}.pyi"[:33].ljust(33, "x") for i in range(149)]
    tree = "\n".join(lines)
    assert len(tree.splitlines()) == 150 and len(tree) >= WORST_TREE_CHARS
    return tree


def fixed_chars(stage):
    """Tool declarations plus the skill instruction, from the compiled bundle (fallback: measured constants)."""
    info = compiled_info(strict=False)
    if info:
        a = next(x for x in info["agents"] if x["name"] == stage)
        return a["decl_chars"], len(a["skill_instruction"])
    return DECL_FALLBACK[stage in SUBMITTERS], SKILL_FALLBACK


def stage_start(stage, tmp_path, problem_chars=None, q="p90", text=None):
    """Prompt chars at a stage's first call (system instruction, declarations, turn contents) -> (parts, tokens).
    problem_chars: the statement cut to that length (default: the longest Kaggle-valid statement). q: the size of every
    earlier stage's reply (reply_tokens). The previous stage's reply is paid in the handoff event ('For context:' +
    '[prev] said: <reply>', facts_internal 2.3) AND again wherever the instruction has a placeholder for it. text: the
    prompt template to render instead of the bundle's (the double-payment control)."""
    y = load_yaml(f"sub_agents/{stage}.yaml")
    identity = f'You are an agent. Your internal name is "{y["name"]}". The description about you is "{y["description"]}".'
    problem = worst_problem()
    if problem_chars is not None:
        problem = problem[:problem_chars]
    plan, notes = reply_text("locator", q), reply_text("fixer", q)
    state = {"problem_description": problem, "plan": plan, "fix_notes": notes}
    instruction = _manual_render(read(f"prompts/{stage}.md") if text is None else text, state)
    decl, skill = fixed_chars(stage)
    if stage == "setup":
        contents = max(len(t) for t in harness_prompts(tmp_path, problem, worst_tree()))
    else:
        said = {"locator": "READY", "fixer": plan, "verifier": notes, "submitter": reply_text("verifier", q)}[stage]
        contents = len("For context:") + len(f"[{PREV_STAGE[stage]}] said: {said}")
    parts = {"declarations": decl, "skill": skill, "identity": len(identity), "instruction": len(instruction),
             "contents": contents}
    return parts, sum(parts.values()) / PROSE


def helper_caps():
    caps = {k: v[1] for k, v in HELPER_OUT.items()}
    consts = common_constants() or {}
    for k, v in (consts.get("CAPS") or {}).items():
        if k in caps and isinstance(v, int):
            caps[k] = max(caps[k], v)   # a helper cap above the SPEC table must still fit the budget
    if isinstance(consts.get("STATUS_START_CAP"), int):            # v10.2: the phase-start status form
        caps["status_start"] = max(caps["status_start"], consts["STATUS_START_CAP"])
    return caps


def meter_consts(stage=None):
    """CONTEXT_TOKENS and CTX_CALL of _swe_common (the context meter; review round 1). For the locator stage, a
    bundle's CONTEXT_TOKENS_LOCATOR when it defines one (lever A arms, make_variant --flip: it applies while t < 75 s;
    this time-free model takes it for the whole stage, the conservative reading)."""
    consts = common_constants() or {}
    thr = int(consts.get("CONTEXT_TOKENS") or 5500)
    if stage == "locator" and consts.get("CONTEXT_TOKENS_LOCATOR"):
        thr = max(thr, int(consts["CONTEXT_TOKENS_LOCATOR"]))
    return thr, int(consts.get("CTX_CALL") or 30)


def calls_tokens(calls, cap, density):
    """Real prompt tokens the calls add: model-written tokens plus the helper output at `density` chars/token."""
    caps = helper_caps()
    return sum(n * (o + (caps[h] if cap else HELPER_OUT[h][0]) / density) for h, n, o in calls)


def stage_peak(stage, start_tokens, cap, density=TOOL):
    """start + the whole permitted mix + the final reply, no CONTEXT hint (the unguarded model)."""
    calls, reply = permitted_mix()[stage]
    return start_tokens + calls_tokens(calls, cap, density) + reply


def guarded_peak(stage, start_tokens, density):
    """start + what the stage can hold once the context meter works: the meter reaches CONTEXT_TOKENS (estimated at
    3 chars/token, so real tokens are est x 3 / density) at most one call past the threshold, then the stage makes the
    calls AFTER_HINT allows and replies. Never more than the unguarded mix at caps."""
    thr, per_call = meter_consts(stage)
    calls, reply = permitted_mix()[stage]
    caps = helper_caps()
    if not calls:
        return start_tokens + reply
    max_est = max(caps[h] / 3.0 + o + per_call for h, n, o in calls)
    guard = (thr + max_est) * 3.0 / density + calls_tokens(AFTER_HINT[stage], True, density) + reply
    return start_tokens + min(calls_tokens(calls, True, density) + reply, guard)


@pytest.mark.parametrize("stage", STAGES)
def test_static_stage_start_budget(stage, tmp_path):
    """R94 (re-derived in review round 2): the worst-case stage-start prompt (10,095-char problem, every earlier reply
    at its measured p90 bounded by max_output_tokens, compiled declarations, skill boilerplate, and the harness prompt
    for setup) is 8,000 tokens or fewer. The sizes really are the measured ones: the plan is the locator's cap (its
    p90 of 1,087 is above it), the notes the fixer's p90."""
    compiled_info(strict=False)   # warm the per-process compile cache so the timing below measures the budget model only
    t0 = time.monotonic()
    parts, tokens = stage_start(stage, tmp_path)
    elapsed = time.monotonic() - t0
    assert tokens <= 8000, (stage, round(tokens), parts)
    assert reply_tokens("locator", "p90") == max_output("locator") == 768
    assert reply_tokens("fixer", "p90") == 244 and reply_tokens("verifier", "p90") == 188
    assert abs(len(reply_text("locator", "p90")) - 768 * PROSE) <= 1
    assert elapsed < 5.0, f"stage-start model took {elapsed:.2f} s"


def test_handoff_paid_once():
    """Review round 2: a stage's previous reply already arrives as the handoff event ('For context:[prev] said: ...',
    facts_internal 2.3), so a placeholder for that same output_key paid for it twice (fixer: {plan?}; verifier:
    {fix_notes?}). No stage has a placeholder for its previous stage's output_key. Earlier stages' keys are fine (the
    verifier's {plan?}, the submitter's {plan?}): the handoff carries only the stage just before."""
    ps = prompts()
    for s, prev in PREV_STAGE.items():
        okey = load_yaml(f"sub_agents/{prev}.yaml").get("output_key")
        if okey:
            assert "{%s?}" % okey not in ps[s] and "{%s}" % okey not in ps[s], (s, okey)
    assert "[locator] message below" in ps["fixer"] and "[fixer] message below" in ps["verifier"]
    assert "{plan?}" in ps["verifier"] and "{plan?}" in ps["submitter"]


def test_double_paid_handoff_breaks_the_margin(tmp_path):
    """Control for R95 B: the fixer prompt as it was (the plan both in {plan?} and in the handoff) misses the 1,000-token
    margin at the measured p90 plan; the shipped prompt meets it. The model sees the defect, not just the constants."""
    old = prompts()["fixer"].replace("The locator's plan is the [locator] message below.", "Locator's plan:\n{plan?}")
    assert "{plan?}" in old
    (tmp_path / "old").mkdir()
    (tmp_path / "new").mkdir()
    _, old95 = stage_start("fixer", tmp_path / "old", P95_PROBLEM_CHARS, text=old)
    _, new95 = stage_start("fixer", tmp_path / "new", P95_PROBLEM_CHARS)
    assert abs((old95 - new95) - reply_tokens("locator", "p90")) < 30      # exactly one more plan, give or take a label
    assert guarded_peak("fixer", old95, TOOL_P10) > COMPACTION - B_MARGIN
    assert guarded_peak("fixer", new95, TOOL_P10) <= COMPACTION - B_MARGIN


@pytest.mark.parametrize("stage", STAGES)
def test_worst_case_stage_budget(stage, tmp_path):
    """R95 (review rounds 1 and 2): the call mix each prompt PERMITS, not a lighter one, against the compaction line,
    with every earlier reply at its MEASURED size (reply_tokens), not the size the prompt asks for.
    A. typical: a p95 statement, median replies, typical helper output at the median 3.06 chars/token: 12,000 tokens
       or fewer.
    B. worst decile: a p95 statement, p90 replies, output at 2.3 chars/token, every output at its cap, the context
       meter and its CONTEXT hint bounding the stage: at least B_MARGIN (1,000) tokens under the 14,336 compaction line.
    C. the outlier statement (10,095 chars), p90 replies, the median density, guarded the same way: under the line.
    D. overflow: the outlier statement, every earlier reply at its max_output_tokens, the whole permitted mix at caps
       and 2.3 chars/token with no hint at all, plus the stage's largest generation, stays 2,048 tokens or more below
       32,768."""
    for d in ("p50", "p95", "worst", "cap"):
        (tmp_path / d).mkdir()
    _, start50 = stage_start(stage, tmp_path / "p50", P95_PROBLEM_CHARS, q="p50")
    _, start95 = stage_start(stage, tmp_path / "p95", P95_PROBLEM_CHARS)
    parts, start = stage_start(stage, tmp_path / "worst")
    _, start_cap = stage_start(stage, tmp_path / "cap", q="cap")
    typical = stage_peak(stage, start50, False, TOOL)
    assert typical <= 12000, ("A", stage, round(start50), round(typical))
    g95 = guarded_peak(stage, start95, TOOL_P10)
    assert g95 <= COMPACTION - B_MARGIN, ("B", stage, round(start95), round(g95), round(COMPACTION - g95))
    gworst = guarded_peak(stage, start, TOOL)
    assert gworst < COMPACTION, ("C", stage, round(start), round(gworst), parts)
    unguarded = stage_peak(stage, start_cap, True, TOOL_P10)
    assert unguarded + max_output(stage) <= 32768 - 2048, ("D", stage, round(unguarded))
    assert typical < unguarded and start50 <= start95 <= start <= start_cap


def test_context_meter_does_not_cut_a_normal_first_round():
    """R95 control: a typical first fixer round (the plan's 3 views, 3 edits, 1 verify) and a typical verifier pass
    (status, verify, one repair, finalize) stay below CONTEXT_TOKENS as the meter estimates them (ASCII / 3 plus the
    model-written tokens plus CTX_CALL), so the hint only fires in later rounds. Review round 2 lowered CONTEXT_TOKENS
    for R95 B's margin, so "typical" is now measured: an edit writes EDIT_TOKENS_P90 (256) tokens, the p90 of 5,329
    race-1 edit calls (the permitted mix keeps 400 as its worst case)."""
    thr, per_call = meter_consts()

    def est(calls):
        return sum(n * (HELPER_OUT[h][0] / 3.0 + o + per_call) for h, n, o in calls)
    if STATUS_FIRST in prompts()["fixer"]:     # v10.2 (SPEC_v10_2 6): status first, then the measured first round
        fixer_round1 = est([("status_start", 1, 30), ("view", 3, 30), ("edit", 2, EDIT_TOKENS_P90), ("verify", 1, 30)])
    else:
        fixer_round1 = est([("view", 3, 30), ("edit", 3, EDIT_TOKENS_P90), ("verify", 1, 30)])
    verifier_pass = est([("status", 1, 30), ("verify", 2, 30), ("view", 1, 30), ("edit", 1, EDIT_TOKENS_P90),
                         ("finalize", 1, 30)])
    assert fixer_round1 < thr and verifier_pass < thr, (fixer_round1, verifier_pass, thr)
    fixer_all = est(permitted_mix()["fixer"][0])
    assert fixer_all > thr, (fixer_all, thr)        # the full permitted fixer mix does reach it: the guard matters


def test_budget_model_unit():
    """R95 control: the model counts every call of the permitted mix; the cap scenario uses the larger of the SPEC cap
    and the helper's own CAPS; the prompts' round limits drive the mix; the guard never exceeds the unguarded mix."""
    mix = permitted_mix()
    calls, reply = mix["fixer"]
    want = reply + sum(n * (o + HELPER_OUT[h][0] / TOOL) for h, n, o in calls)
    assert abs(stage_peak("fixer", 0, False) - want) < 1e-9
    assert stage_peak("fixer", 0, True) > stage_peak("fixer", 0, False)
    assert stage_peak("fixer", 0, True, TOOL_P10) > stage_peak("fixer", 0, True)
    assert all(helper_caps()[k] >= v[1] for k, v in HELPER_OUT.items())
    if V102:     # v10.2 (R145): status first and 1 repair round (fixer.md)
        assert dict((h, n) for h, n, _ in calls) == {"status_start": 1, "view": 3, "edit": 3, "verify": 1}
    else:
        assert dict((h, n) for h, n, _ in calls) == {"view": 4, "edit": 4, "verify": 2}      # 2 rounds (fixer.md)
    assert dict((h, n) for h, n, _ in mix["verifier"][0])["verify"] == 3                  # 2 repair rounds
    for st in STAGES:
        assert guarded_peak(st, 0, TOOL_P10) <= stage_peak(st, 0, True, TOOL_P10) + 1e-9
    assert (common_constants() or {}).get("CAPS", {}).get("view", 2800) <= 2800


# ---------------------------------------------------------------- R96 protocol rules
# Review round 2: the context meter sees only helper output, so raw read_file (up to 10,000 chars) and raw run_command
# output (5,000 + 5,000) would fill a stage unseen; the fixer and verifier are told to use the metered helpers.
# v10.1 (R89b): each helper appears as its full command.
RAW_IO = ("View files only with python3 /tmp/swe/view.py FILE START END",
          "run other code only with python3 /tmp/swe/run.py --timeout 20")
RULES = {
    "setup": ["Your whole job is one tool call", INSTALL_CALL, "reply with the single word READY",
              "Do not call any other tool"],
    "locator": ["If the issue is only a title, turn its words into code names", "Never search issue numbers",
                "python3 /tmp/swe/view.py --obj", "Print real objects; never guess library types", "# CLAIM 1:",
                "one # CLAIM line per behaviour", "It must say fails on original", "rewrite it once",
                "FILES: path:start-end", "CAUSE:", "FIX:", "REPRO: fails on original, or none", "TESTS:",
                "you edit nothing", "under 120 words", "starting with FILES:", "at most 25 lines and no other comments"],
    "fixer": ["smallest COMPLETE change", "never conclude that nothing needs changing", "python3 /tmp/swe/verify.py",
              "at most 2 rounds", "SIBLINGS", "SPEC GAPS", "REGRESSIONS", "fix the code (not the reproduction)",
              "Never edit tests, conftest.py, pytest.ini, pyproject.toml, setup.cfg or tox.ini", "CHANGED:",
              "VERIFY:", "under 60 words", "first edit by t=150s", "stop editing by t=210s", *RAW_IO],
    "verifier": ["1. Run python3 /tmp/swe/status.py", "If no source file is changed", "at most 2 repair rounds",
                 "none after t=240s", "OLD behaviour the issue asks to change, keep your fix",
                 "python3 /tmp/swe/finalize.py", "If it says NOT READY", "Call submit_patch after READY",
                 "submit_patch is your last tool call", "If a helper prints TIME, go straight to step 4",
                 "(no flags)", "a tool call written there as text never ran", *RAW_IO],
    "submitter": ["1. Run python3 /tmp/swe/finalize.py", "Only if it says EMPTY", "Call submit_patch after READY",
                  "The patch has not been submitted yet", "{problem_description}"],
}
if V102:        # SPEC_v10_2 7, R144: the phrases v10.2's locator adds, and the fixer's repair budget of 1 round
    RULES["locator"] += ["the helpers stop answering after 14 calls or at t=90s", "(at most 3 runs before your plan)",
                         "never ask for more information", "reply FILES: none", "ALSO:", "(no reasoning inside it)",
                         "if it passes again use REPRO: none", "every use of a name you rename or remove"]
    RULES["fixer"] = [r for r in RULES["fixer"] if r != "at most 2 rounds"] + [
        "at most 1 round", "1. Run python3 /tmp/swe/status.py first", "LOCATOR DIGEST", "the plan was lost",
        "Change an ALSO place only if verify still fails"]
ORDER = {"locator": ["python3 /tmp/swe/locate.py", "python3 /tmp/swe/view.py", "python3 /tmp/swe/verify.py --repro-only",
                     "Stop and reply with the plan"],
         "fixer": ["View the plan's FILES", "smallest COMPLETE change", "Run python3 /tmp/swe/verify.py",
                   "Stop and reply"],
         "verifier": ["1. Run python3 /tmp/swe/status.py", "3. Run python3 /tmp/swe/verify.py",
                      "4. Run python3 /tmp/swe/finalize.py", "5. Call submit_patch"],
         "submitter": ["1. Run python3 /tmp/swe/finalize.py", "EMPTY", "3. Call submit_patch"]}


def test_prompt_rules_present():
    """R96: each stage's protocol rules are present, in order (status, verify, finalize, submit last)."""
    ps = prompts()
    for s, rules in RULES.items():
        for r in rules:
            assert r in ps[s], (s, r)
    for s, seq in ORDER.items():
        idx = [ps[s].find(x) for x in seq]
        assert all(i >= 0 for i in idx) and idx == sorted(idx), (s, dict(zip(seq, idx)))
    v = ps["verifier"]
    assert v.rfind("submit_patch") > v.find("4. Run python3 /tmp/swe/finalize.py")
    for s in ("locator", "fixer", "verifier"):
        assert "status.py" in ps[s] and "t=300s" in ps[s], s


def test_prompt_times_match_helper_clock():
    """R96 cross-check: the times the prompts give match the helper clock (CAP_S, T_EDIT_NOW, T_FINISH; repairs end
    before T_TIME; the locator replies by T_LOCATOR + 15), and the footer lines the TIME block names exist."""
    consts = common_constants()
    if consts is None:
        pytest.skip("_swe_common.py not built yet (helpers-core)")
    ps = prompts()
    assert f"t={consts['CAP_S']}s" in ps["locator"]
    assert f"first edit by t={consts['T_EDIT_NOW']}s" in ps["fixer"]
    assert f"stop editing by t={consts['T_FINISH']}s" in ps["fixer"]
    repair_end = int(re.search(r"none after t=(\d+)s", ps["verifier"]).group(1))
    assert consts["T_FINISH"] < repair_end < consts["T_TIME"]
    reply_by = int(re.search(r"reply by t=(\d+)s", ps["locator"]).group(1))
    assert consts["T_LOCATOR"] < reply_by < consts["T_EDIT_NOW"]
    for s in ("verifier", "submitter"):     # v10.1: submit after READY, or once no restore is possible any more
        assert int(re.search(r"after READY \(or at t>=(\d+)s\)", ps[s]).group(1)) == consts["T_NO_RESTORE"], s
    strings = " ".join(s for s in _string_constants(_parse(str(SCRIPTS / "_swe_common.py")))[1])
    for hint in ("LOCATOR:", "EDIT NOW:", "CONTEXT:", "FINISH:", "TIME:", "FINAL:"):
        assert hint in strings, f"_swe_common has no {hint} footer line although the TIME block names it"


def test_parse_call_spec_unit(tmp_path):
    """R92 support: the parse_args call is replicated as written (positionals, keywords), a script without a call
    uses the defaults, and a non-constant argument is reported unusable."""
    cases = {
        "a.py": ('import _swe_common as C\nFLAGS = {}\nPOS = ["file", "start"]\n'
                 'def main():\n    C.parse_args([], FLAGS, POS, usage="u", interspersed=False)\n',
                 (True, ["file", "start"], {"interspersed": False})),
        "b.py": ("FLAGS = {}\ndef main():\n    return 0\n", (True, (), {})),
        "c.py": ("import sys\nimport _swe_common as C\ndef main():\n    C.parse_args([], {}, sys.argv)\n",
                 (False, None, {})),
        "d.py": ("import _swe_common as C\ndef main():\n    C.parse_args([], {}, positionals=('x',))\n",
                 (True, ["x"], {})),
    }
    for name, (src, want) in cases.items():
        (tmp_path / name).write_text(src)
        env = module_constants(tmp_path / name)
        assert parse_call_spec(tmp_path / name, env) == want, name
