"""v10 bundle configuration (docs/v10/SPEC.md sections 1, 2, 5 and 9.2; requirements R78-R86, owner: config, TB).

The YAML, prompts and SKILL.md under submissions/v10 are byte-exact copies of SPEC.md sections 2 and 3, which the
synthesizer compiled with scripts/validate.py. These tests pin that, compile the bundle with the organisers' compiler
(tool sets, generation configs and the thinking bridge as the scorer builds them), and check the pack script, the
frozen trees and the 12 h arithmetic. Shared helpers here are imported by tests/test_v10_prompts.py.
Nothing here runs a helper inside submissions/ (no __pycache__ can appear in the bundle)."""
import ast, functools, hashlib, importlib.util, json, os, pathlib, re, shutil, stat, subprocess, sys, time, zipfile
import pytest

try:  # R120: every v10 module takes the autouse orphan-process check from the core support package
    from v10_support.repo import no_orphans  # noqa: F401
except Exception:  # built in parallel by the core component; absent until it lands
    pass

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "submissions" / "v10"
SPEC = ROOT / "docs" / "v10" / "SPEC.md"
SCRIPTS = BUNDLE / "skills" / "swe-tools" / "scripts"
PACK = ROOT / "scripts" / "pack_bundle.py"
MODEL = "gemma-4-31b-it-qat-w4a16-ct"
STAGES = ("setup", "locator", "fixer", "verifier", "submitter")
BASE8 = ["run_command", "read_file", "edit_file", "write_file", "get_status", "get_code_neighbors",
         "search_similar_code", "get_code_subgraph"]
SUBMITTERS = ("verifier", "submitter")
SKILL_TOOLS = {"list_skills", "load_skill", "load_skill_resource", "run_skill_script"}
GRAPH_TOOLS = {"get_code_neighbors", "search_similar_code", "get_code_subgraph"}
GEN = {"setup": (0.2, 256), "locator": (1.0, 768), "fixer": (1.0, 2048), "verifier": (1.0, 2048),
       "submitter": (0.2, 1024)}
OUTPUT_KEYS = {"locator": "plan", "fixer": "fix_notes"}
EVAL = {"max_time_minutes": 5, "timeout_seconds": 180, "max_tool_calls": 100, "max_turns": 200}
CLI_SCRIPTS = ("install", "locate", "grep", "view", "edit", "run", "verify", "finalize", "status")
LIB_SCRIPTS = ("_swe_common", "_swe_index", "_swe_gate", "_swe_ckpt")
CONFIG_FILES = (["agent.yaml", "eval_config.yaml"] + [f"configs/gen_{s}.yaml" for s in STAGES]
                + [f"sub_agents/{s}.yaml" for s in STAGES] + [f"prompts/{s}.md" for s in STAGES]
                + ["skills/swe-tools/SKILL.md"])
SECTION1_FILES = set(CONFIG_FILES) | {f"skills/swe-tools/scripts/{s}.py" for s in LIB_SCRIPTS + CLI_SCRIPTS}
ALLOWED_EXT = {".yaml", ".yml", ".md", ".txt", ".py", ".json", ".safetensors"}
FROZEN = {  # R84: tree sha256 (os.walk, dirs and files sorted; skip __pycache__, *.pyc, ._*, .DS_Store)
    "submissions/v9_eog": "41db23fcd48cf2b52f21beb691097232eb4a5c5b739e7fb656fdc95fd3c940b1",
    "submissions/v4": "38eb7a97cdbb6aa91577231dcc1bf33fa256b60c48985445578c603d7ea181ed",
    # helpers_v9 re-pinned by the integrator (2026-09-28): the SPEC pinned ed996c63... at 13:12, before Carson's committed
    # fix 26dd7b9 (13:21, "gate: import/collection crash and missing pytest were reported as PASS", regression tests in
    # tests/test_gate_false_pass.py). The shipped copy of gate.py lives in submissions/v9_eog, whose pin is unchanged.
    "helpers_v9": "c40b410b58d0fca3c26708c01032c8716683bc49e5b88b2ef5a877e97bdd4157",
}
FROZEN_GIT = {"helpers_v9": "26dd7b9"}   # the pin equals this commit's tree (checked below)
# Timeout constants of _swe_common (SPEC 4.1.1). Clock thresholds (CAP_S, T_*) are times, not deadlines.
TIMEOUT_CONSTS = ("RUN_DEFAULT", "RUN_MAX", "VIEW_OBJ", "LOCATE_PARSE", "ORIGIN_PROBE", "VERIFY_TOTAL",
                  "IMPORT_CHECK", "CLAIM_TIMEOUT", "CLAIMS_TOTAL", "PYTEST_SIDE", "FINALIZE_QUICK")
# T_QUICK moved before T_TIME (review round 1: a full verify started at 225-270 s could run past T_NO_EVAL); every
# verify ends by T_VERIFY_END and every quick evaluation by T_EVAL_END.
CLOCK_ORDER = ("T_LOCATOR", "T_EDIT_NOW", "T_FINISH", "T_QUICK", "T_TIME", "T_SAFE", "T_VERIFY_END", "T_EVAL_END",
               "T_NO_EVAL", "T_NO_RESTORE", "CAP_S")


# ---------------------------------------------------------------- SPEC.md extraction (the single source of truth)
_FENCE = re.compile(r"^```[a-z]*\n(.*?)^```[ \t]*$", re.S | re.M)
BLOCK_NAMES = ("RECOVER", "AMNESIA", "TIME", "HELPERS", "EDITFORM")


def _fence_after(text, pos):
    m = _FENCE.search(text, pos)
    assert m, f"SPEC.md: no code fence after offset {pos}"
    body = m.group(1)
    return body[:-1] if body.endswith("\n") else body


def _after(text, needle):
    i = text.find(needle)
    assert i >= 0, f"SPEC.md lacks {needle!r}"
    return i + len(needle)


def spec_text():
    if not SPEC.exists():
        pytest.skip("docs/v10/SPEC.md not present")
    return SPEC.read_text(encoding="utf-8")


def spec_blocks(spec):
    """RECOVER, AMNESIA, TIME and EDITFORM, verbatim from section 3."""
    return {b: _fence_after(spec, _after(spec, f"\n{b}\n```") - 3) for b in BLOCK_NAMES}


def render_prompt(template, blocks):
    """A section 3 template with each <BLOCK> line replaced by its block, plus a trailing newline."""
    out = []
    for line in template.split("\n"):
        key = line.strip()
        out.append(blocks[key[1:-1]] if key[:1] == "<" and key[-1:] == ">" and key[1:-1] in blocks else line)
    return "\n".join(out) + "\n"


def spec_files(spec):
    """Every file of SPEC sections 2 and 3, as the bytes it must have in submissions/v10."""
    files = {}
    for rel in ["agent.yaml", "eval_config.yaml"] + [f"sub_agents/{s}.yaml" for s in STAGES]:
        files[rel] = _fence_after(spec, _after(spec, f"\n`{rel}`\n")) + "\n"
    shape = _fence_after(spec, _after(spec, "`configs/gen_<stage>.yaml`"))
    for s in STAGES:
        m = re.search(r"^\| gen_%s\.yaml \| ([0-9.]+) \| (\d+) \|" % s, spec, re.M)
        assert m, f"SPEC.md: no gen table row for {s}"
        files[f"configs/gen_{s}.yaml"] = shape.replace("<T>", m.group(1)).replace("<M>", m.group(2)) + "\n"
    blocks = spec_blocks(spec)
    for s in STAGES:
        m = re.search(r"^### 3\.\d `prompts/%s\.md`\n" % s, spec, re.M)
        assert m, f"SPEC.md: no section for prompts/{s}.md"
        files[f"prompts/{s}.md"] = render_prompt(_fence_after(spec, m.end()), blocks)
    m = re.search(r"^### 3\.6 `skills/swe-tools/SKILL\.md`\n", spec, re.M)
    assert m, "SPEC.md: no SKILL.md section"
    files["skills/swe-tools/SKILL.md"] = _fence_after(spec, m.end()) + "\n"
    return files


# ---------------------------------------------------------------- bundle readers
def read(rel):
    return (BUNDLE / rel).read_text(encoding="utf-8")


def prompts():
    return {s: read(f"prompts/{s}.md") for s in STAGES}


@functools.lru_cache(maxsize=None)
def _pyyaml_loader():
    """PyYAML's SafeLoader plus the bundle's !include tag, or None where PyYAML is absent (python:3.12-slim)."""
    try:
        import yaml
    except ImportError:
        return None

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!include", lambda loader, node: {"!include": loader.construct_scalar(node)})
    return yaml, Loader


def _mini_scalar(v):
    v = v.strip()
    if v.startswith("!include "):
        return {"!include": v[len("!include "):].strip()}
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [_mini_scalar(x) for x in inner.split(",")] if inner else []
    if v in ("true", "false"):
        return v == "true"
    if v in ("", "null", "~"):
        return None
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


def mini_yaml(text):
    """The YAML subset the bundle uses (block mappings, lists of mappings, flow lists of scalars, !include), so the
    config tests also run without PyYAML; test_mini_yaml_matches_pyyaml pins it to PyYAML on every bundle file."""
    lines = [[len(x) - len(x.lstrip(" ")), x.strip()] for x in text.splitlines()
             if x.strip() and not x.lstrip().startswith("#")]

    def block(i, indent):
        if lines[i][1].startswith("- "):
            out = []
            while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
                lines[i] = [indent + 2, lines[i][1][2:]]
                val, i = block(i, indent + 2)
                out.append(val)
            return out, i
        out = {}
        while i < len(lines) and lines[i][0] == indent and not lines[i][1].startswith("- "):
            key, _, rest = lines[i][1].partition(":")
            i += 1
            if rest.strip():
                out[key.strip()] = _mini_scalar(rest)
            elif i < len(lines) and lines[i][0] > indent:
                out[key.strip()], i = block(i, lines[i][0])
            else:
                out[key.strip()] = None
        return out, i

    return block(0, lines[0][0])[0] if lines else None


def yaml_text(text):
    py = _pyyaml_loader()
    return py[0].load(text, Loader=py[1]) if py else mini_yaml(text)


def load_yaml(rel, base=BUNDLE):
    return yaml_text((base / rel).read_text(encoding="utf-8"))


def tree_sha256(root):
    """R84 tree hash: os.walk with sorted dirs and files; skip __pycache__, *.pyc, ._*, .DS_Store; rel\\0content\\0."""
    h = hashlib.sha256()
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d != "__pycache__")
        for f in sorted(fns):
            if f.endswith(".pyc") or f.startswith("._") or f == ".DS_Store":
                continue
            full = os.path.join(dp, f)
            h.update(os.path.relpath(full, root).encode() + b"\0")
            with open(full, "rb") as fh:
                h.update(fh.read() + b"\0")
    return h.hexdigest()


# ---------------------------------------------------------------- AST readers for helper constants (no execution)
class NotConstant(Exception):
    pass


def const_eval(node, env):
    """Evaluate a constant expression: literals, str concatenation, f-strings of constants, names, C.X attributes."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            elif isinstance(v, ast.FormattedValue) and v.format_spec is None:
                val = const_eval(v.value, env)
                parts.append(repr(val) if v.conversion == ord("r") else str(val))
            else:
                raise NotConstant("format spec")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult, ast.Sub)):
        left, right = const_eval(node.left, env), const_eval(node.right, env)
        return left + right if isinstance(node.op, ast.Add) else left * right if isinstance(node.op, ast.Mult) \
            else left - right
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -const_eval(node.operand, env)
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        raise NotConstant(node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        key = f"{node.value.id}.{node.attr}"
        if key in env:
            return env[key]
        raise NotConstant(key)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        vals = [const_eval(e, env) for e in node.elts]
        return tuple(vals) if isinstance(node, ast.Tuple) else set(vals) if isinstance(node, ast.Set) else vals
    if isinstance(node, ast.Dict):
        if any(k is None for k in node.keys):
            raise NotConstant("dict unpacking")
        return {const_eval(k, env): const_eval(v, env) for k, v in zip(node.keys, node.values)}
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict"
            and not node.args and all(k.arg for k in node.keywords)):
        return {k.arg: const_eval(k.value, env) for k in node.keywords}
    raise NotConstant(type(node).__name__)


@functools.lru_cache(maxsize=None)
def _parse(path_str):
    return ast.parse(pathlib.Path(path_str).read_text(encoding="utf-8"), path_str)


def module_constants(path, env=None):
    """Module-level NAME = <constant expr> assignments of a script, evaluated without running it."""
    env = dict(env or {})
    out = {}
    for stmt in _parse(str(path)).body:
        targets, value = [], None
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets, value = [stmt.target], stmt.value
        for t in targets:
            try:
                if isinstance(t, ast.Name):
                    out[t.id] = env[t.id] = const_eval(value, env)
                elif isinstance(t, ast.Tuple) and isinstance(value, ast.Tuple) and len(t.elts) == len(value.elts):
                    for tt, vv in zip(t.elts, value.elts):
                        if isinstance(tt, ast.Name):
                            out[tt.id] = env[tt.id] = const_eval(vv, env)
            except (NotConstant, TypeError, KeyError):
                continue
    return out


@functools.lru_cache(maxsize=None)
def common_constants():
    p = SCRIPTS / "_swe_common.py"
    if not p.exists():
        return None
    # DOCKER_TMP = os.environ.get(...) or "/tmp" is not a constant expression and is simply left out.
    return module_constants(p)


def common_alias_env(script):
    """Names under which a script can refer to _swe_common constants (import _swe_common as C / from ... import X)."""
    consts = common_constants() or {}
    env = {}
    for stmt in _parse(str(script)).body:
        if isinstance(stmt, ast.Import):
            for a in stmt.names:
                if a.name == "_swe_common":
                    alias = a.asname or a.name
                    env.update({f"{alias}.{k}": v for k, v in consts.items()})
        elif isinstance(stmt, ast.ImportFrom) and stmt.module == "_swe_common":
            for a in stmt.names:
                if a.name in consts:
                    env[a.asname or a.name] = consts[a.name]
    return env


def helper_usage_flags(name):
    """(USAGE, FLAGS) of scripts/<name>.py read via AST; None when the script is not built yet."""
    p = SCRIPTS / f"{name}.py"
    if not p.exists():
        return None
    consts = module_constants(p, common_alias_env(p))
    usage, flags = consts.get("USAGE"), consts.get("FLAGS")
    if not isinstance(usage, str) or not isinstance(flags, dict):
        usage, flags = _usage_flags_runpy(p)
    return usage, flags


def _usage_flags_runpy(p):
    """Fallback when USAGE/FLAGS are not constant expressions: import the script (not as __main__) from a temp copy."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        dst = pathlib.Path(td) / "scripts"
        shutil.copytree(SCRIPTS, dst)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", HOME=td, TMPDIR=td, SWE_DIR=os.path.join(td, "swe"),
                   SWE_DUAL="0")
        env.pop("TEST_TMPDIR", None)
        code = ("import json, runpy, sys; g = runpy.run_path(sys.argv[1], run_name='v10_lint'); "
                "print('V10JSON:' + json.dumps({'u': g.get('USAGE'), 'f': g.get('FLAGS')}, default=str))")
        r = subprocess.run([sys.executable, "-c", code, str(dst / p.name)], cwd=td, env=env, capture_output=True,
                           text=True, timeout=30, stdin=subprocess.DEVNULL)
    line = [x for x in r.stdout.splitlines() if x.startswith("V10JSON:")]
    assert line, f"{p.name}: USAGE/FLAGS unreadable by AST and by import: {r.stdout[-500:]} {r.stderr[-1500:]}"
    d = json.loads(line[-1][8:])
    return d["u"], d["f"]


# ---------------------------------------------------------------- the organisers' compiler, run once per process
_COMPILE_DRIVER = r'''
import asyncio, json, sys, warnings
warnings.simplefilter("ignore")
from unittest.mock import MagicMock
from adk_submission import compile_submission, discover_adapters
from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS, build_submission_limits
from swegemma.tools import create_tools
from swegemma.models import setup_gemma_model_registry
from google.adk.models.lite_llm import _function_declaration_to_tool_param
from google.adk.models.llm_request import LlmRequest
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.function_tool import FunctionTool
d = sys.argv[1]
limits, gen = build_submission_limits()
registry = create_tools(MagicMock())
root = compile_submission(submission_dir=d, adapter_manifest=discover_adapters(d, adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS),
                          tool_registry=registry, model_registry=setup_gemma_model_registry(), limits=limits,
                          generation_constraints=gen)

async def canonical(agent):
    tools, skill_text = [], ""
    for t in agent.tools:
        if isinstance(t, BaseToolset):
            tools += await t.get_tools(None)
            req = LlmRequest()
            await t.process_llm_request(tool_context=MagicMock(), llm_request=req)
            skill_text += req.config.system_instruction or ""
        elif isinstance(t, BaseTool):
            tools.append(t)
        else:
            tools.append(FunctionTool(t))
    return tools, skill_text

out = {"root": {"class": type(root).__name__, "name": root.name}, "registry": sorted(registry), "agents": []}
for a in root.sub_agents:
    tools, skill_text = asyncio.run(canonical(a))
    decls = [(t.name, len(json.dumps(_function_declaration_to_tool_param(t._get_declaration())))) for t in tools]
    gcc = a.generate_content_config
    out["agents"].append({
        "name": a.name, "class": type(a).__name__, "include_contents": str(getattr(a, "include_contents", "")),
        "model": getattr(a.model, "model", str(a.model)), "additional_args": getattr(a.model, "_additional_args", None),
        "gen": gcc.model_dump(exclude_none=True, mode="json") if gcc is not None else None,
        "output_key": a.output_key, "instruction": a.instruction if isinstance(a.instruction, str) else None,
        "description": a.description, "tools": [n for n, _ in decls], "decl_chars": sum(c for _, c in decls),
        "skill_instruction": skill_text, "declared_objects": [type(t).__name__ for t in a.tools],
    })
print("V10JSON:" + json.dumps(out, default=str))
'''


def compiler_available():
    return all(importlib.util.find_spec(m) is not None for m in ("adk_submission", "swegemma"))


@functools.lru_cache(maxsize=None)
def _compile(bundle):
    """(info, error): the bundle compiled once per process in a subprocess (same calls as scripts/validate.py)."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-c", _COMPILE_DRIVER, bundle], capture_output=True, text=True, timeout=300,
                       env=env, cwd=str(ROOT))
    line = [x for x in r.stdout.splitlines() if x.startswith("V10JSON:")]
    if not line:
        return None, f"compile failed: {r.stdout[-1500:]} {r.stderr[-3000:]}"
    return json.loads(line[-1][8:]), None


def compiled_info(bundle=str(BUNDLE), strict=True):
    """Every stage of the compiled bundle as JSON; None without the compiler. A compile failure is an assertion
    error when strict, and None otherwise (callers that only refine an estimate fall back; R78 reports it)."""
    if not compiler_available():
        return None
    info, err = _compile(bundle)
    if err and strict:
        raise AssertionError(err)
    return info


def need_compiled():
    info = compiled_info()
    if info is None:
        pytest.skip("organisers' compiler (adk_submission, swegemma) is not installed here")
    return info


def stage_tools_yaml(stage):
    """Tools a stage declares: its YAML tool list plus the SkillToolset tools (every stage has the skill)."""
    y = load_yaml(f"sub_agents/{stage}.yaml")
    return set(y["tools"]) | (SKILL_TOOLS if y.get("skills") else set())


# ================================================================ tests
def test_bundle_files_equal_spec():
    """Brief: every file of SPEC sections 2 and 3 byte-exactly (LF, one trailing newline, UTF-8)."""
    want = spec_files(spec_text())
    assert sorted(want) == sorted(CONFIG_FILES)
    for rel, text in want.items():
        got = (BUNDLE / rel).read_bytes()
        assert got == text.encode("utf-8"), f"{rel} differs from SPEC.md"
        assert b"\r" not in got and got.endswith(b"\n") and not got.endswith(b"\n\n"), rel


def test_bundle_tree_matches_section1():
    """Section 1: 31 files, nothing else; no .sh, dotfiles, __pycache__, symlinks or extensionless files."""
    files = set()
    for dp, dns, fns in os.walk(BUNDLE):
        assert "__pycache__" not in dns, dp
        for f in fns:
            full = pathlib.Path(dp) / f
            rel = full.relative_to(BUNDLE).as_posix()
            assert not f.startswith(".") and not full.is_symlink() and full.suffix in ALLOWED_EXT, rel
            files.add(rel)
    assert set(CONFIG_FILES) <= files, set(CONFIG_FILES) - files
    assert files <= SECTION1_FILES, files - SECTION1_FILES
    for s in LIB_SCRIPTS + CLI_SCRIPTS:
        assert s not in sys.stdlib_module_names, s
    if files == SECTION1_FILES:
        assert len(files) == 31


def test_tree_and_official_compile():
    """R78: Sequential[setup, locator, fixer, verifier, submitter], LlmAgents, include_contents none, one model id,
    and scripts/validate.py compiles it with the organisers' compiler."""
    root = load_yaml("agent.yaml")
    assert root["agent_class"] == "SequentialAgent" and root["name"] == "swe_pipeline"
    assert [s["config_path"] for s in root["sub_agents"]] == [f"sub_agents/{s}.yaml" for s in STAGES]
    for s in STAGES:
        y = load_yaml(f"sub_agents/{s}.yaml")
        assert y["name"] == s and y["model"] == MODEL and y["include_contents"] == "none", s
        assert y.get("agent_class", "LlmAgent") == "LlmAgent", s
        assert y["instruction"] == {"!include": f"../prompts/{s}.md"}, s
        assert y["generate_content_config"] == {"!include": f"../configs/gen_{s}.yaml"}, s
    if not compiler_available():
        pytest.skip("organisers' compiler (adk_submission, swegemma) is not installed here")
    t0 = time.monotonic()
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(BUNDLE)], capture_output=True,
                       text=True, timeout=300, cwd=str(ROOT), env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    elapsed = time.monotonic() - t0
    assert f"OK model={MODEL}" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
    lines = [x.strip() for x in r.stdout.splitlines() if x.strip().startswith(("SequentialAgent", "LlmAgent"))]
    assert lines[0].startswith("SequentialAgent swe_pipeline")
    assert [x.split()[1] for x in lines[1:]] == list(STAGES)
    assert all(x.startswith("LlmAgent ") and f"model=openai/{MODEL}" in x for x in lines[1:])
    assert elapsed < 120, f"official compile took {elapsed:.1f} s"
    info = need_compiled()
    assert info["root"] == {"class": "SequentialAgent", "name": "swe_pipeline"}
    assert [a["name"] for a in info["agents"]] == list(STAGES)
    for a, s in zip(info["agents"], STAGES):
        assert a["class"] == "LlmAgent" and a["include_contents"] == "none" and a["model"] == f"openai/{MODEL}"
        assert a["instruction"].rstrip("\n") == read(f"prompts/{s}.md").rstrip("\n"), s
    assert not (BUNDLE / "__pycache__").exists()


def test_tool_sets_and_skills():
    """R79: BASE8 (exactly v9_eog's set, in order) plus the skill on every stage; submit_patch only on verifier and
    submitter, in the YAML and in the compiled tool names."""
    v9 = load_yaml("sub_agents/locator.yaml", ROOT / "submissions" / "v9_eog")
    assert BASE8 == v9["tools"], "BASE8 must stay the v9_eog set (0 unknown-tool crashes in race 1)"
    for s in STAGES:
        y = load_yaml(f"sub_agents/{s}.yaml")
        want = BASE8 + (["submit_patch"] if s in SUBMITTERS else [])
        assert y["tools"] == want, s
        assert y["skills"] == ["skills/swe-tools"], s
        assert (BUNDLE / y["skills"][0] / "SKILL.md").exists()
    info = need_compiled()
    registry = set(info["registry"])
    for a in info["agents"]:
        names = a["tools"]
        assert len(names) == len(set(names)), a["name"]
        want = set(BASE8) | SKILL_TOOLS | ({"submit_patch"} if a["name"] in SUBMITTERS else set())
        assert set(names) == want, (a["name"], set(names) ^ want)
        assert set(names) - SKILL_TOOLS <= registry, a["name"]
        assert "SkillToolset" in a["declared_objects"], a["name"]


def test_generation_configs():
    """R80: the section 2 table; include_thoughts false everywhere; no seed or thinking_level; the compiled model
    carries chat_template_kwargs.enable_thinking False and no reasoning_effort."""
    for s, (temp, max_out) in GEN.items():
        g = load_yaml(f"configs/gen_{s}.yaml")
        assert g == {"temperature": temp, "top_p": 0.95, "top_k": 64, "max_output_tokens": max_out,
                     "thinking_config": {"include_thoughts": False}}, s
        assert 32768 - max_out >= 30720, s   # the overflow line stays at or above 30,720 tokens
    for p in BUNDLE.rglob("*.yaml"):
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(seed|thinking_level|thinking_budget)\s*:", text, re.M), p
    info = need_compiled()
    for a in info["agents"]:
        temp, max_out = GEN[a["name"]]
        g = a["gen"]
        assert g["temperature"] == temp and g["top_p"] == 0.95 and float(g["top_k"]) == 64.0, a["name"]
        assert g["max_output_tokens"] == max_out, a["name"]
        assert g["thinking_config"]["include_thoughts"] is False, a["name"]
        args = a["additional_args"]
        assert args["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False, a["name"]
        assert "reasoning_effort" not in args and "seed" not in g, a["name"]


def test_eval_config():
    """R81: exactly the four keys the scorer reads, under evaluation:."""
    ev = load_yaml("eval_config.yaml")
    assert ev == {"evaluation": EVAL}
    assert all(type(v) is int for v in ev["evaluation"].values())
    assert ev["evaluation"]["max_turns"] >= 2 * ev["evaluation"]["max_tool_calls"]   # SPEC 5: turns never bind first


def test_output_keys():
    """R82: output_key plan on the locator, fix_notes on the fixer, none elsewhere (YAML and compiled)."""
    for s in STAGES:
        assert load_yaml(f"sub_agents/{s}.yaml").get("output_key") == OUTPUT_KEYS.get(s), s
    root = load_yaml("agent.yaml")
    assert "output_key" not in root
    info = need_compiled()
    assert {a["name"]: a["output_key"] for a in info["agents"]} == {s: OUTPUT_KEYS.get(s) for s in STAGES}


# ---------------------------------------------------------------- R83 pack_bundle.py
def run_pack(src, out, timeout=60):
    return subprocess.run([sys.executable, str(PACK), str(src), str(out)], capture_output=True, text=True,
                          timeout=timeout, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))


def _check_zip(path, expect_names=None):
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        assert names == sorted(names) and len(set(names)) == len(names)
        assert "agent.yaml" in names
        for i in infos:
            assert i.date_time == (1980, 1, 1, 0, 0, 0), i.filename
            assert (i.external_attr >> 16) & 0o777 == 0o644 and stat.S_ISREG(i.external_attr >> 16), i.filename
            assert i.create_system == 3 and not i.extra and not i.is_dir(), i.filename
            parts = i.filename.split("/")
            assert "__pycache__" not in parts and not any(p.startswith(".") for p in parts), i.filename
            assert pathlib.PurePosixPath(i.filename).suffix in ALLOWED_EXT, i.filename
        assert z.testzip() is None
        if expect_names is not None:
            assert names == sorted(expect_names)
        return {n: z.read(n) for n in names}


def _sha_line(r):
    assert r.returncode == 0, r.stdout + r.stderr
    first = r.stdout.splitlines()[0].split()
    assert re.fullmatch(r"[0-9a-f]{64}", first[0]), r.stdout
    return first[0]


def test_pack_deterministic(tmp_path):
    """R83: deterministic zip of the real bundle (same sha256 twice), allowed extensions only, agent.yaml at the
    root, sorted entries, 1980-01-01 mtimes, mode 0644, under 1 MB, byte-exact contents; packing takes < 3 s."""
    t0 = time.monotonic()
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    sha_a = _sha_line(run_pack(BUNDLE, a))
    elapsed = time.monotonic() - t0
    sha_b = _sha_line(run_pack(BUNDLE, b))
    assert sha_a == sha_b == hashlib.sha256(a.read_bytes()).hexdigest()
    assert a.read_bytes() == b.read_bytes()
    assert a.stat().st_size < 1_000_000
    expected = [p.relative_to(BUNDLE).as_posix() for p in BUNDLE.rglob("*")
                if p.is_file() and not p.is_symlink() and "__pycache__" not in p.parts
                and not any(x.startswith(".") for x in p.relative_to(BUNDLE).parts) and p.suffix]
    contents = _check_zip(a, expected)
    for rel, data in contents.items():
        assert data == (BUNDLE / rel).read_bytes(), rel
    assert elapsed < 3.0, f"pack took {elapsed:.2f} s"
    # a copy with different mtimes and creation order packs to the same bytes
    copy = tmp_path / "copy"
    for rel in sorted(contents, reverse=True):
        (copy / rel).parent.mkdir(parents=True, exist_ok=True)
        (copy / rel).write_bytes(contents[rel])
        os.utime(copy / rel, (1_700_000_000, 1_700_000_000))
    assert _sha_line(run_pack(copy, tmp_path / "c.zip")) == sha_a


def _junk_bundle(tmp_path):
    b = tmp_path / "bundle"
    (b / "skills/x/scripts/__pycache__").mkdir(parents=True)
    (b / "agent.yaml").write_text("name: a\n")
    (b / "prompts").mkdir()
    (b / "prompts/p.md").write_text("hi\n")
    (b / "skills/x/SKILL.md").write_text("---\nname: x\n---\n")
    (b / "skills/x/scripts/tool.py").write_text("print(1)\n")
    (b / "skills/x/scripts/__pycache__/tool.cpython-312.pyc").write_bytes(b"\0")
    (b / "skills/x/scripts/stale.pyc").write_bytes(b"\0")
    (b / "._agent.yaml").write_bytes(b"\0")
    (b / ".DS_Store").write_bytes(b"\0")
    (b / ".hidden").mkdir()
    (b / ".hidden/secret.py").write_text("x = 1\n")
    (b / "Makefile").write_text("all:\n")
    (b / "ünïcode.md").write_text("u\n", encoding="utf-8")
    os.symlink(b / "prompts/p.md", b / "link.md")
    os.symlink(b / "prompts", b / "linkdir")
    return b


def test_pack_excludes_junk_and_refuses_bad_bundles(tmp_path):
    """R83 edge cases: __pycache__, *.pyc, dotfiles, dot-dirs, AppleDouble, extensionless files and symlinks are
    left out; the output zip inside the bundle is not packed into itself; a rejected extension, a missing root
    agent.yaml and a wrong argument count all fail without writing a zip."""
    b = _junk_bundle(tmp_path)
    out = b / "dist.zip"
    r = run_pack(b, out)
    _sha_line(r)
    assert "skipped" in r.stderr and "files=5" in r.stdout
    _check_zip(out, ["agent.yaml", "prompts/p.md", "skills/x/SKILL.md", "skills/x/scripts/tool.py", "ünïcode.md"])
    assert _sha_line(run_pack(b, out)) == hashlib.sha256(out.read_bytes()).hexdigest()   # repack over itself
    (b / "run.sh").write_text("echo\n")
    r = run_pack(b, tmp_path / "bad.zip")
    assert r.returncode == 1 and "run.sh" in r.stderr and not (tmp_path / "bad.zip").exists()
    (b / "run.sh").unlink()
    (b / "agent.yaml").unlink()
    r = run_pack(b, tmp_path / "bad.zip")
    assert r.returncode == 1 and "agent.yaml" in r.stderr and not (tmp_path / "bad.zip").exists()
    r = subprocess.run([sys.executable, str(PACK), str(b)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and "Usage" in r.stderr


def test_frozen_unchanged():
    """R84: the shipped v9_eog and v4 bundles and helpers_v9 are byte-identical to their pinned tree hashes."""
    t0 = time.monotonic()
    changed = {rel: tree_sha256(ROOT / rel) for rel in FROZEN}
    elapsed = time.monotonic() - t0
    changed = {rel: got for rel, got in changed.items() if got != FROZEN[rel]}
    assert not changed, f"frozen (shipped) trees changed; restore them, never re-pin: {changed}"
    assert elapsed < 2.0, f"tree hashing took {elapsed:.2f} s"


def test_frozen_pins_match_git(tmp_path):
    """R84 provenance: every frozen tree has no uncommitted change, and a re-pinned tree equals its commit's tree."""
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    for rel in FROZEN:
        r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", rel], cwd=ROOT,
                           capture_output=True, text=True, timeout=30)
        assert r.returncode == 0 and r.stdout == "", f"{rel} has uncommitted changes:\n{r.stdout[:600]}"
    for rel, rev in FROZEN_GIT.items():
        # a shallow clone (the pod clones --depth 1) lacks the pinned revision: provenance is checked on the Mac
        if subprocess.run(["git", "cat-file", "-e", f"{rev}^{{commit}}"], cwd=ROOT, capture_output=True).returncode:
            pytest.skip(f"revision {rev} not in this checkout (shallow clone)")
        dst = tmp_path / rev
        dst.mkdir()
        arch = subprocess.run(["git", "archive", rev, rel], cwd=ROOT, capture_output=True, timeout=60)
        assert arch.returncode == 0, arch.stderr[-300:]
        subprocess.run(["tar", "-x", "-C", str(dst)], input=arch.stdout, check=True, timeout=60)
        assert tree_sha256(dst / rel) == FROZEN[rel], (rel, rev)


def test_tree_hash_detects_changes(tmp_path):
    """R84 control: the tree hash moves on a content change, a rename and a new file, and ignores caches."""
    t = tmp_path / "t"
    (t / "d").mkdir(parents=True)
    (t / "a.py").write_text("x\n")
    (t / "d/b.md").write_text("y\n")
    h0 = tree_sha256(t)
    (t / "d/__pycache__").mkdir()
    (t / "d/__pycache__/b.pyc").write_bytes(b"\0")
    (t / "._a.py").write_bytes(b"\0")
    (t / ".DS_Store").write_bytes(b"\0")
    assert tree_sha256(t) == h0
    (t / "a.py").write_text("x \n")
    h1 = tree_sha256(t)
    assert h1 != h0
    (t / "a.py").rename(t / "c.py")
    assert tree_sha256(t) not in (h0, h1)
    (t / "c.py").rename(t / "a.py")
    assert tree_sha256(t) == h1
    (t / "new.txt").write_text("")
    assert tree_sha256(t) != h1


def test_fits_12h():
    """R85: 600 + N x (60 x max_time_minutes + 3.6 + 5 + 1) <= 0.95 x 43,200 for N = 130 (and 120), from the
    shipped eval_config; the per-task cap and command timeout are no looser than v4's (SPEC 9.2 H1)."""
    ev = load_yaml("eval_config.yaml")["evaluation"]
    v4 = load_yaml("eval_config.yaml", ROOT / "submissions" / "v4")["evaluation"]
    per_task = 60 * ev["max_time_minutes"] + 3.6 + 5 + 1
    for n in (120, 130):
        assert 600 + n * per_task <= 0.95 * 43200, (n, 600 + n * per_task)
    assert (0.95 * 43200 - 600) / per_task >= 130
    assert ev["max_time_minutes"] <= v4["max_time_minutes"]
    assert ev["timeout_seconds"] <= v4["timeout_seconds"]
    # the scorer's worst case for N = 120 is at most v4's 10.49 h
    assert (600 + 120 * per_task) / 3600 <= 10.5


def test_deadlines_under_command_timeout():
    """R86: every timeout constant of _swe_common, and every literal timeout in any helper, is at most
    timeout_seconds - 10 (110 s); the clock thresholds are ordered and end at the task cap."""
    ev = load_yaml("eval_config.yaml")["evaluation"]
    limit = ev["timeout_seconds"] - 10
    # 2026-09-28: timeout_seconds 120 -> 180 (it also caps the hidden-test pytest run in verification,
    # verification.py:492-503; v4 = 180; research/update_0928.md). Helper watchdogs stay at 110 s, well inside.
    assert limit >= 110
    consts = common_constants()
    if consts is None:
        pytest.skip("_swe_common.py not built yet (helpers-core)")
    for name in TIMEOUT_CONSTS:
        assert isinstance(consts.get(name), (int, float)), f"_swe_common.{name} missing or not a number"
        assert 0 < consts[name] <= limit, (name, consts[name])
    for name, v in consts.items():
        if (isinstance(v, (int, float)) and not isinstance(v, bool) and name not in CLOCK_ORDER
                and re.search(r"TIMEOUT|DEADLINE|_SECS?$|BUDGET|_WAIT", name)):
            assert 0 < v <= limit, (name, v)
    order = [consts.get(n) for n in CLOCK_ORDER]
    assert all(isinstance(v, (int, float)) for v in order), dict(zip(CLOCK_ORDER, order))
    assert order == sorted(order) and len(set(order)) == len(order), dict(zip(CLOCK_ORDER, order))
    assert consts["CAP_S"] == 60 * ev["max_time_minutes"]
    assert consts["RUN_DEFAULT"] <= consts["RUN_MAX"]
    for p in sorted(SCRIPTS.glob("*.py")):
        env = common_alias_env(p)
        env.update(module_constants(p, env))
        for node in ast.walk(_parse(str(p))):
            if not isinstance(node, ast.Call):
                continue
            vals = [k.value for k in node.keywords if k.arg in ("timeout", "deadline", "timeout_s", "deadline_s")]
            fname = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if fname == "real_budget" and node.args:
                vals.append(node.args[0])
            for v in vals:
                try:
                    val = const_eval(v, env)
                except (NotConstant, TypeError):
                    continue
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    assert val <= limit, f"{p.name}:{node.lineno} timeout {val} > {limit}"


def test_ast_constant_reader_unit(tmp_path):
    """The AST reader used by R86/R92/R93 resolves literals, f-strings, concatenation and C.X constants."""
    lib = tmp_path / "_lib.py"
    lib.write_text('DISPLAY = "/tmp/swe"\nT = 20\n')
    s = tmp_path / "s.py"
    s.write_text('import os\nimport _lib as C\nNAME = "view"\nUSAGE = f"python3 {C.DISPLAY}/{NAME}.py FILE"\n'
                 'FLAGS = {"--obj": "str", "start": "int"}\nX: int = C.T * 2\nY = os.getcwd()\n')
    env = {f"C.{k}": v for k, v in module_constants(lib).items()}
    got = module_constants(s, env)
    assert got["USAGE"] == "python3 /tmp/swe/view.py FILE" and got["FLAGS"] == {"--obj": "str", "start": "int"}
    assert got["X"] == 40 and "Y" not in got


def test_mini_yaml_matches_pyyaml():
    """Control for the fallback parser: identical to PyYAML (with !include) on every YAML file of v10 and v9_eog,
    and on nested lists of mappings."""
    py = _pyyaml_loader()
    if py is None:
        pytest.skip("PyYAML not installed here")
    files = sorted(BUNDLE.rglob("*.yaml")) + sorted((ROOT / "submissions" / "v9_eog").rglob("*.yaml"))
    assert len(files) >= 13
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert mini_yaml(text) == py[0].load(text, Loader=py[1]), f
    extra = "a:\n  - x: 1\n    y: [p, q]\n  - x: 2.5\n    z:\n      w: true\nb: !include ../c.md\n"
    assert mini_yaml(extra) == py[0].load(extra, Loader=py[1])
