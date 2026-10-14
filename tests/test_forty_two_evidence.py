"""Offline evidence behind the v13 levers (docs/forty_two/LEVERS.md). No model: vLLM's own argument parser (vendored, v0.19.1),
bash, and the template the v13 prompt teaches."""
import os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "forty_two")); sys.path.insert(0, str(ROOT / "tests"))
import gemma4_args_vllm as g  # noqa: E402
from test_v13_bundle import edit_template, fill  # noqa: E402

D = '<|"|>'


def test_a_slipped_closing_delimiter_swallows_the_next_argument_exactly_as_recorded():
    # p4_b1024 rich_3718 recorded {'filepath', 'new_string': '...stylize_before(border_style)`,old_string:', 'if title_text is not None': ...}
    raw = (f"filepath:{D}rich/panel.py{D},new_string:{D}        if title_text is not None:\n"
           f"            title_text.stylize_before(border_style)`,old_string:{D}        if title_text is not None:\n"
           f"            title_text.stylize_before(partial_border_style)`")
    args = g._parse_gemma4_args(raw)
    assert "old_string" not in args
    assert args["new_string"].endswith("stylize_before(border_style)`,old_string:")
    assert "if title_text is not None" in args                     # the old block's text became a key


def test_the_same_slip_in_a_single_argument_call_keeps_the_whole_command():
    raw = f"command:{D}python3 - <<'EDIT'\nprint(1)\nEDIT`"
    assert g._parse_gemma4_args(raw) == {"command": "python3 - <<'EDIT'\nprint(1)\nEDIT`"}


def test_and_that_slipped_template_command_writes_nothing(tmp_path):
    src = "def f():\n    return 1\n"
    (tmp_path / "m.py").write_text(src)
    cmd = fill(edit_template(), "m.py", "    return 1\n", "    return 2\n").rstrip("\n") + "`"      # the terminator line becomes EDIT`
    env = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    r = subprocess.run(["bash", "-c", cmd], cwd=tmp_path, capture_output=True, text=True, timeout=60, env=env)
    assert r.returncode != 0 and "SyntaxError" in r.stderr                  # python parses the whole script before running any of it
    assert (tmp_path / "m.py").read_text() == src
