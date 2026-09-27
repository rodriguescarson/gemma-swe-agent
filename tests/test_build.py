"""Build checks: every script must at least parse before it is shipped to a pod or Kaggle (Carson 09-26: "always build to
catch syntax errors"). Covers shell syntax, shellcheck errors, all Python files, and Python embedded inside shell scripts."""
import pathlib, py_compile, re, shutil, subprocess, pytest
ROOT = pathlib.Path(__file__).parent.parent
SKIP = {".venv", "data", "backups", "eval", "kernels", "ref", "__pycache__"}
SH = sorted(p for d in ("pod", "scripts") for p in (ROOT / d).glob("*.sh"))
PY = sorted(p for p in ROOT.rglob("*.py") if not (set(p.relative_to(ROOT).parts) & SKIP))

@pytest.mark.parametrize("p", SH, ids=lambda p: p.name)
def test_shell_syntax(p):
    r = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not installed")
@pytest.mark.parametrize("p", SH, ids=lambda p: p.name)
def test_shellcheck_errors(p):
    r = subprocess.run(["shellcheck", "-S", "error", "-x", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]

@pytest.mark.parametrize("p", PY, ids=lambda p: str(p.relative_to(ROOT)))
def test_python_compiles(p, tmp_path):
    py_compile.compile(str(p), cfile=str(tmp_path / "x.pyc"), doraise=True)

def embedded_python(text):
    out = []
    for m in re.finditer(r"""python3?\s+-c\s+"((?:[^"\\]|\\.)*)\"""", text):
        out.append(m.group(1).replace('\\"', '"').replace("\\$", "$"))
    for m in re.finditer(r"python3?\s+-\s*(?:\"[^\"]*\"\s*)*<<\s*'?(\w+)'?\s*\n(.*?)\n\1\s*$", text, re.S | re.M):
        out.append(m.group(2))
    return out

@pytest.mark.parametrize("p", SH, ids=lambda p: p.name)
def test_embedded_python_compiles(p):
    for i, code in enumerate(embedded_python(p.read_text())):
        if "$(" in code or re.search(r"\$\{?[A-Za-z_]", code):
            continue                                         # shell-interpolated; checked at runtime on the pod
        compile(code, f"{p.name}#snippet{i}", "exec")
