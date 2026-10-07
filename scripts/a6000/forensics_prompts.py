"""Prompt vs reality (scripts/a6000/PROMPTS.md P5.2): every helper invocation a bundle's prompts and SKILL.md show, run with placeholder arguments against the
bundle's own scripts in a scratch git repo. Prints, per bundle, each invocation, whether it ran as the prompt describes, and the first lines of its output;
plus tools named in a prompt that the stage's yaml does not declare. tests/test_a6000_forensics_prompts.py.

    python scripts/a6000/forensics_prompts.py [BUNDLE ...]"""
import collections
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
Invocation = collections.namedtuple("Invocation", "text helper heredoc mention")
Result = collections.namedtuple("Result", "invocation ok output exit")
INV_RE = re.compile(r"python3 /tmp/swe/(\w+)\.py[^\n`\")]*|run_skill_script\([^)]*\)")
TOOLS_RE = re.compile(r"Tools you can call: ([^\n]+)")
SKILL_TOOLS = ("run_skill_script", "load_skill", "list_skills", "load_skill_resource")
EXPECT = {"view": r"(^|\n)\d+\| ", "test": r"exit=\d", "edit": r"(^|\n)OK ", "check": r"(DIFF:|PROBLEMS:|READY|NOT READY)", "locate": r"workspace=.*symbols=",
          "install": r"installed:", "select_best": r"select_best:|PICK|no candidate|candidates", "repro": r"REPRO (PASS|FAIL|MISSING|TIMEOUT)", "repo_map": r"\S"}
EDIT_BLOCK = "<<<<<<< SEARCH\n    return x\n=======\n    return x + 1\n>>>>>>> REPLACE\n"
LINES_BLOCK = "    return x + 1\n"                 # the --lines and --create forms take plain lines


def extract_invocations(text):
    out, seen = [], set()
    for m in INV_RE.finditer(text):
        t = m.group(0).rstrip(" .,;:")
        if t.startswith("run_skill_script"):
            fm = re.search(r'file_path="([\w.]+)"', t)
            helper = (fm.group(1) if fm else "install").replace(".py", "")
        else:
            helper = m.group(1)
        key = t.strip()
        if key in seen:
            continue
        seen.add(key)
        mention = not key.startswith("run_skill_script") and re.fullmatch(r"python3 /tmp/swe/\w+\.py", key) is not None
        out.append(Invocation(key, helper, "<<'EOF'" in key, mention))
    return out


def substitute(text, repo_file, test_file):
    t = text.split("<<'EOF'")[0] if "<<'EOF'" in text else text
    t = re.split(r"`", t)[0].rstrip()
    t = t.replace("path/to/file.py", repo_file).replace("tests/test_x.py::test_name", test_file + "::test_f").replace("tests/test_x.py", test_file)
    t = re.sub(r"<(test file from the plan|TEST file from the plan|test file)>", test_file, t)
    t = re.sub(r"\bFILE\b", repo_file, t)
    t = t.replace("START END", "1 3").replace("--lines 120-135", "--lines 2-2").replace("--lines A-B", "--lines 2-2")
    t = re.sub(r"<[^>]*>", "f", t)
    t = re.sub(r"\b(NAME|FUNCTION_YOU_EDITED)\b", "f", t)
    t = t.replace(" ...", "").rstrip().rstrip(".,;:")
    return t.strip()


def tools_named(text):
    m = TOOLS_RE.search(text)
    if not m:
        return []
    return [x.strip().rstrip(".") for x in m.group(1).split(".")[0].split(",") if x.strip()]


def undeclared(text, declared, skills=False):
    dec = set(declared) | (set(SKILL_TOOLS) if skills else set())
    return [t for t in tools_named(text) if t not in dec]


def scratch_repo(tmp):
    r = Path(tmp) / "repo"
    r.mkdir(parents=True, exist_ok=True)
    (r / "mod.py").write_text("def f(x):\n    return x\n")
    (r / "test_mod.py").write_text("from mod import f\n\ndef test_f():\n    assert f(1) == 2\n")
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    for c in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-qm", "init"]):
        subprocess.run(c, cwd=r, env=env, check=True, capture_output=True)
    (Path(tmp) / "tmpdir" / "swe").mkdir(parents=True, exist_ok=True)
    return r


def run_invocations(bundle, repo, invocations):
    """Each invocation runs in its own fresh copy of the scratch repo with its own tmp dir (helpers, ledger), so invocations never interact."""
    repo = Path(repo)
    src = Path(bundle) / "skills" / "swe-tools" / "scripts"
    results = []
    for k, inv in enumerate(invocations):
        if inv.mention:
            results.append(Result(inv, None, "mention only, not an invocation", 0))
            continue
        work = repo.parent / f"run_{k}"
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(repo, work / "repo", symlinks=True)
        tmpdir = work / "tmpdir"
        swe = tmpdir / "swe"
        swe.mkdir(parents=True)
        for f in src.glob("*.py"):
            shutil.copy(f, swe / f.name)
        env = dict(os.environ, TMPDIR=str(tmpdir), TEST_TMPDIR=str(tmpdir), PYTHONDONTWRITEBYTECODE="1")
        repo_k = work / "repo"
        if inv.text.startswith("run_skill_script"):
            fm = re.search(r'file_path="([\w.]+)"', inv.text)
            script = fm.group(1) if fm else "install.py"
            am = re.search(r'args=\{"test": "([^"]+)"\}', inv.text)
            argv = [sys.executable, str(src / script)] + (["--test", substitute(am.group(1), "mod.py", "test_mod.py")] if am else [])
            p = subprocess.run(argv, cwd=repo_k, env=env, capture_output=True, text=True)
        else:
            cmd = substitute(inv.text, "mod.py", "test_mod.py").replace("/tmp/swe/", str(swe) + "/")
            p = subprocess.run(["bash", "-c", cmd], cwd=repo_k, env=env, capture_output=True, text=True, input=(LINES_BLOCK if ("--lines" in inv.text or "--create" in inv.text) else EDIT_BLOCK) if inv.heredoc else None)
        out = (p.stdout + p.stderr).strip()
        ok = p.returncode == 0 and bool(re.search(EXPECT.get(inv.helper, r"\S"), out)) and "Traceback" not in out
        results.append(Result(inv, ok, out[:400], p.returncode))
    return results


def bundle_report(bundle):
    import yaml
    b = Path(bundle)
    texts = {p.name: p.read_text() for p in sorted((b / "prompts").glob("*.md"))}
    texts["SKILL.md"] = (b / "skills" / "swe-tools" / "SKILL.md").read_text()
    invs, where = [], {}
    for name, t in texts.items():
        for inv in extract_invocations(t):
            where.setdefault(inv.text, []).append(name)
            if inv.text not in {i.text for i in invs}:
                invs.append(inv)
    tmp = tempfile.mkdtemp(prefix="forensics_")
    had_tmp_swe = os.path.isdir("/tmp/swe")
    try:
        res = run_invocations(b, scratch_repo(tmp), invs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if not had_tmp_swe and os.path.isdir("/tmp/swe"):
            shutil.rmtree("/tmp/swe", ignore_errors=True)
    lines = [f"### {b.name}", "", "| invocation (as written) | in | runs as described | output head |", "|---|---|---|---|"]
    for r in res:
        head = r.output.split("\n")[0][:110].replace("|", "\\|")
        lines.append(f"| `{r.invocation.text[:90].replace('|', chr(92) + '|')}` | {', '.join(where[r.invocation.text])} | {'mention' if r.ok is None else 'yes' if r.ok else 'NO'} | `{head}` |")
    tools = []
    for y in sorted((b / "sub_agents").glob("*.yaml")):
        d = yaml.safe_load(re.sub(r"!include\s+\S+", "X", y.read_text()))
        if d.get("agent_class"):
            continue
        prompt = texts.get(Path(str(d.get("instruction", ""))).name) or texts.get(y.stem + ".md", "")
        inc = re.search(r"!include\s+\.\./prompts/(\S+)", y.read_text())
        prompt = texts.get(inc.group(1), "") if inc else prompt
        und = undeclared(prompt, d.get("tools") or [], skills=bool(d.get("skills")))
        tools.append(f"- {d['name']}: declared {d.get('tools') or []}{' + skill tools' if d.get('skills') else ''}; named in its prompt but not declared: {und or 'none'}")
    return "\n".join(lines + [""] + tools) + "\n"


def main(argv=None):
    bundles = argv if argv else ["v4h2", "v5h2", "v6p", "v6p-think", "v6p-b"]
    for name in bundles:
        print(bundle_report(ROOT / "submissions" / name))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
