"""view.py (v4h6g loop breaker): read a file range with line numbers; an exact repeat of an earlier range (same file,
same lines) within the task returns a short refusal instead of the content, so a model stuck re-reading cannot burn
its 70-call budget on identical output (docs/v4h/V4H2G_MISSES.md: 16/40 misses repeat one call >= 10x; fastapi_15800
resent one malformed read_file 74x). Positional args only: no JSON keys to corrupt. Written before the helper."""
import os, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
VIEW = ROOT / "submissions" / "v4h6g" / "skills" / "swe-tools" / "scripts" / "view.py"


def _repo(tmp):
    ws = tmp / "ws"; ws.mkdir(); (ws / ".git").mkdir()
    (ws / "m.py").write_text("".join(f"line{i}\n" for i in range(1, 301)))
    return ws


def _run(tmp, ws, *args):
    env = dict(os.environ, SWE_WS=str(ws), TMPDIR=str(tmp))
    return subprocess.run([sys.executable, str(VIEW), *args], capture_output=True, text=True, env=env, timeout=30)


def test_shows_numbered_lines_and_caps_the_window(tmp_path):
    ws = _repo(tmp_path)
    r = _run(tmp_path, ws, "m.py", "10", "12")
    assert r.returncode == 0 and "10| line10" in r.stdout and "12| line12" in r.stdout and "13|" not in r.stdout
    r2 = _run(tmp_path, ws, "m.py", "1", "300")
    assert r2.stdout.count("\n") <= 125 and "capped" in r2.stdout


def test_exact_repeat_is_refused_but_a_new_range_is_shown(tmp_path):
    ws = _repo(tmp_path)
    _run(tmp_path, ws, "m.py", "10", "12")
    r = _run(tmp_path, ws, "m.py", "10", "12")
    assert "ALREADY SHOWN" in r.stdout and "line10" not in r.stdout
    r3 = _run(tmp_path, ws, "m.py", "13", "15")
    assert "13| line13" in r3.stdout


def test_reread_after_the_file_changed_is_allowed(tmp_path):
    ws = _repo(tmp_path)
    _run(tmp_path, ws, "m.py", "10", "12")
    (ws / "m.py").write_text((ws / "m.py").read_text().replace("line11", "EDITED"))
    r = _run(tmp_path, ws, "m.py", "10", "12")
    assert "EDITED" in r.stdout and "ALREADY" not in r.stdout


def test_missing_file_and_bad_args_are_short_errors(tmp_path):
    ws = _repo(tmp_path)
    assert "no such file" in _run(tmp_path, ws, "nope.py", "1", "5").stdout.lower()
    assert "usage" in _run(tmp_path, ws, "m.py").stdout.lower()
