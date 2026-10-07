"""Prompt vs reality for v7 (fix 2), the idea of scripts/a6000/forensics_prompts.py in its own small checker: every shell
line the locator, fixer and verifier prompts show is run against v7's own helpers in a scratch git repo with its own
tmp dir (the harness sandbox rewrites /tmp in command text, so the checker does the same), and must print what the prompt
says it prints. Placeholders are filled the way the model would. Written before the prompts were reworded.

Shell lines are the backticked spans that start with a shell word, plus the multi-line heredoc blocks (the edit block,
the repro). Every extracted line must have an expectation here, so a new line in a prompt cannot slip in unchecked."""
import os, re, shutil, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
V7 = ROOT / "submissions" / "v7"
SCRIPTS = V7 / "skills" / "swe-tools" / "scripts"
STAGES = ("locator", "fixer", "verifier")
SHELL_WORD = re.compile(r"^(python3|git|cat|timeout|rm|ls|sed|grep|cd)\b")
MENTIONS = {"python3 /tmp/swe/edit.py", "git grep"}                    # names in prose ("edit through ...", "such as ...")
MOD = "def f(x):\n    return x\n"
FIXED = "def f(x):\n    return x * 2\n"


def shell_lines(text):
    """-> [(command line, heredoc body or None)] in prompt order, de-duplicated."""
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        l = lines[i]
        if l.rstrip().endswith("<<'EOF'") and "`" not in l and SHELL_WORD.match(l.strip()):
            j = lines.index("EOF", i + 1)
            out.append((l.strip(), "\n".join(lines[i + 1:j]) + "\n"))
            i = j + 1
            continue
        i += 1
    for sp in re.findall(r"`([^`\n]+)`", text):
        if SHELL_WORD.match(sp) and sp not in MENTIONS and "..." not in sp:   # a bare name / a template
            out.append((sp, None))
    seen, uniq = set(), []
    for c in out:
        if c[0] not in seen:
            seen.add(c[0])
            uniq.append(c)
    return uniq


def fill(cmd):
    """The placeholders as the model fills them in, for the scratch repo below."""
    cmd = cmd.replace("path/to/file.py", "pkg/mod.py").replace("START END", "1 2").replace("--lines 120-135", "--lines 2-2")
    cmd = cmd.replace("<test file>", "tests/test_mod.py").replace('"<identifiers, error text and keywords from the issue>"', '"f mod"')
    cmd = re.sub(r'"<(name|symbol)>"', '"f"', cmd)
    return re.sub(r"\b(NAME|FUNCTION_YOU_EDITED)\b", "f", cmd)


def fill_body(cmd, body):
    if "<<<<<<< SEARCH" in body:                                       # the edit block
        return "<<<<<<< SEARCH\n    return x\n=======\n    return x * 2\n>>>>>>> REPLACE\n"
    if "repro.py" in cmd:                                               # the repro: the issue's example, a bare assert
        assert re.search(r"assert", body), body
        return "from pkg.mod import f\nassert f(3) == 6, f(3)\n"
    if "--lines" in cmd:
        return "    return x * 2\n"
    return "print('scratch')\n"


class Scratch:
    """A task: a git workspace and a sandbox-like tmp dir with v7's helpers installed by v7's install.py."""

    def __init__(self, root, install=True):
        self.ws, self.tmp = root / "ws", root / "tmp"
        (self.ws / "pkg").mkdir(parents=True)
        (self.ws / "tests").mkdir()
        self.tmp.mkdir()
        (self.ws / "pkg" / "__init__.py").write_text("")
        (self.ws / "pkg" / "mod.py").write_text(MOD)
        (self.ws / "tests" / "test_mod.py").write_text("from pkg.mod import f\n\n\ndef test_f():\n    assert f(2) == 4\n")
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        for c in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-qm", "base"]):
            subprocess.run(c, cwd=self.ws, env=env, check=True, capture_output=True)
        if install:
            self.install()

    def env(self):
        return dict(os.environ, SWE_WS=str(self.ws), TMPDIR=str(self.tmp), TEST_TMPDIR=str(self.tmp), PYTHONPATH=str(self.ws),
                    PYTHONDONTWRITEBYTECODE="1")

    def install(self):
        # install.py as the skill runner calls it: a copy of the skill in a temp dir; /tmp/swe stands for <tmp>/swe
        work = self.tmp.parent / "skill"
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(SCRIPTS, work / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        p = subprocess.run([sys.executable, str(work / "scripts" / "install.py")], cwd=work, env=self.env(), capture_output=True, text=True)
        return p.stdout + p.stderr

    def sh(self, cmd, body=None):
        if body is not None:
            cmd = cmd + "\n" + body + "EOF"
        cmd = re.sub(r"(?<![\w.-])/tmp(?![\w.-])", str(self.tmp), cmd)  # the sandbox's /tmp rewrite
        p = subprocess.run(["bash", "-c", cmd], cwd=self.ws, env=self.env(), capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout + p.stderr


def expectation(cmd):
    """-> (prelude: callable(Scratch) or None, check: callable(rc, out, Scratch) -> bool, what the prompt promises)."""
    edited = lambda s: (s.ws / "pkg" / "mod.py").write_text(FIXED)
    repro_written = lambda s: (s.tmp / "repro.py").write_text("from pkg.mod import f\nassert f(3) == 6, f(3)\n")
    table = [
        (r"^python3 /tmp/swe/locate\.py ", None, lambda r, o, s: r == 0 and re.search(r"workspace=.*symbols=", o) and "pkg/mod.py" in o,
         "ranked files with line ranges"),
        (r"^python3 /tmp/swe/view\.py ", None, lambda r, o, s: r == 0 and o.startswith("1| def f(x):") and "2|     return x" in o,
         "numbered lines"),
        (r"^python3 /tmp/swe/edit\.py .*<<'EOF'$", None,
         lambda r, o, s: r == 0 and o.startswith("OK pkg/mod.py") and (s.ws / "pkg" / "mod.py").read_text() == FIXED, "OK and the edit applied"),
        (r"^python3 /tmp/swe/test\.py ", None, lambda r, o, s: r == 0 and re.match(r"exit=1 ", o) and "assert" in o,
         "exit=<code> and the failure (the code is still wrong)"),
        (r"^python3 /tmp/swe/check\.py --mode preflight$", edited, lambda r, o, s: r == 0 and "DIFF:" in o and "pkg/mod.py" in o and "PROBLEMS:" in o,
         "the diff and the problems"),
        (r"^git diff$", edited, lambda r, o, s: r == 0 and "pkg/mod.py" in o and "return x * 2" in o, "the change"),
        (r"^git grep -n ", None, lambda r, o, s: r == 0 and "pkg/mod.py:1:def f(x):" in o, "the definition"),
        (r"^git grep -ln .* -- tests$", None, lambda r, o, s: r == 0 and o.strip() == "tests/test_mod.py", "a covering test file"),
        (r"^cat > /tmp/repro\.py <<'EOF'$", None, lambda r, o, s: r == 0 and (s.tmp / "repro.py").is_file() and not (s.ws / "repro.py").exists(),
         "/tmp/repro.py written, in the sandbox tmp, nothing in the workspace"),
        (r"^cat > /tmp/scratch\.py <<'EOF'$", None, lambda r, o, s: r == 0 and (s.tmp / "scratch.py").is_file(), "a scratch file in /tmp"),
        (r"^python3 /tmp/repro\.py; echo EXIT=\$\?$", repro_written, lambda r, o, s: r == 0 and "EXIT=1" in o and "AssertionError" in o,
         "EXIT=1 while the behaviour is wrong"),
    ]
    for pat, pre, check, promise in table:
        if re.search(pat, cmd):
            return pre, check, promise
    return None


def all_lines():
    return [(s, c, b) for s in STAGES for c, b in shell_lines((V7 / "prompts" / f"{s}.md").read_text())]


def test_the_checker_finds_the_shell_lines_of_every_stage():
    got = {s: [c for c, _ in shell_lines((V7 / "prompts" / f"{s}.md").read_text())] for s in STAGES}
    assert any("locate.py" in c for c in got["locator"]) and any("view.py" in c for c in got["locator"])
    assert any(c.startswith("python3 /tmp/swe/edit.py") and c.endswith("<<'EOF'") for c in got["fixer"])
    assert "cat > /tmp/repro.py <<'EOF'" in got["verifier"] and "python3 /tmp/repro.py; echo EXIT=$?" in got["verifier"]
    for s, c, _ in all_lines():
        assert expectation(fill(c)) is not None, (s, c)                # every line shown has a promise checked below


@pytest.mark.parametrize("stage,cmd,body", all_lines(), ids=lambda x: x if isinstance(x, str) and len(x) < 60 else None)
def test_every_shell_line_runs_and_prints_what_the_prompt_promises(tmp_path, stage, cmd, body):
    s = Scratch(tmp_path)
    pre, check, promise = expectation(fill(cmd))
    if pre:
        pre(s)
    rc, out = s.sh(fill(cmd), fill_body(cmd, body) if body is not None else None)
    assert check(rc, out, s), (stage, cmd, promise, rc, out[-800:])


def test_the_repro_passes_once_the_behaviour_is_fixed(tmp_path):
    s = Scratch(tmp_path)
    v = (V7 / "prompts" / "verifier.md").read_text()
    write = next((c, b) for c, b in shell_lines(v) if c.startswith("cat > /tmp/repro.py"))
    s.sh(write[0], fill_body(write[0], write[1]))
    assert "EXIT=1" in s.sh("python3 /tmp/repro.py; echo EXIT=$?")[1]
    (s.ws / "pkg" / "mod.py").write_text(FIXED)
    assert "EXIT=0" in s.sh("python3 /tmp/repro.py; echo EXIT=$?")[1]   # "EXIT=0 means the behaviour is right"


def test_the_promises_in_the_prose_hold(tmp_path):
    s = Scratch(tmp_path)
    view = fill("python3 /tmp/swe/view.py path/to/file.py START END")
    assert s.sh(view)[1].startswith("1| ")
    assert s.sh(view)[1].startswith("ALREADY SHOWN")                     # "a range you already saw is refused"
    rc, out = s.sh("python3 /tmp/swe/edit.py pkg/mod.py <<'EOF'\n<<<<<<< SEARCH\n    return x\n=======\n    return (x\n>>>>>>> REPLACE\nEOF")
    assert rc == 1 and (s.ws / "pkg" / "mod.py").read_text() == MOD      # "A broken edit is undone"
    rc, out = s.sh("python3 /tmp/swe/edit.py pkg/mod.py <<'EOF'\n<<<<<<< SEARCH\n    return y\n=======\n    return x\n>>>>>>> REPLACE\nEOF")
    assert re.search(r"closest .*line 2", out) and "--lines 2-2" in out  # "names the closest line and the --lines range to use"
    (s.ws / "repro.py").write_text("x = 1\n")
    (s.ws / "tests" / "test_mod.py").write_text("def test_f():\n    assert True\n")
    out = s.sh("python3 /tmp/swe/check.py --mode preflight")[1]
    assert "repro.py" in out and "tests/test_mod.py" in out and "NOT READY" in out   # "revert test/config edits, delete scratch files"


def test_the_recovery_sentence_works(tmp_path):
    s = Scratch(tmp_path, install=False)
    view = fill("python3 /tmp/swe/view.py path/to/file.py START END")
    assert "can't open file" in s.sh(view)[1]                            # the helper is missing: what the model sees
    assert "installed:" in s.install()                                   # "run the install script once ..."
    assert s.sh(view)[1].startswith("1| ")                               # "... and repeat the helper call"
