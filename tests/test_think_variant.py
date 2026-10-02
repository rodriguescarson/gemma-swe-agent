"""make_think_variant: only configs/sampling.yaml changes, and only its thinking_config block."""
import filecmp, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import make_think_variant as T  # noqa: E402

V4H = ROOT / "submissions" / "v4h"


def test_only_the_thinking_block_changes(tmp_path):
    out = tmp_path / "t"
    T.build(str(V4H), str(out), "LOW")
    for p in V4H.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            rel = p.relative_to(V4H)
            if str(rel) == "configs/sampling.yaml":
                continue
            assert filecmp.cmp(p, out / rel, shallow=False), rel
    s = (out / "configs" / "sampling.yaml").read_text()
    assert s.endswith("thinking_config:\n  include_thoughts: true\n  thinking_level: LOW\n")
    assert s.count("thinking_config:") == 1 and "temperature: 1.0" in s and "max_output_tokens: 4096" in s


def test_none_turns_thinking_off_and_unknown_level_is_refused(tmp_path):
    T.build(str(V4H), str(tmp_path / "n"), "NONE")
    assert "include_thoughts: false\n  thinking_level: NONE" in (tmp_path / "n" / "configs" / "sampling.yaml").read_text()
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_think_variant.py"), str(V4H), str(tmp_path / "u"), "--level", "ULTRA"],
                       capture_output=True, text=True)
    assert p.returncode != 0 and "silently leaves thinking ON" in p.stderr


def test_variant_compiles_with_the_official_compiler(tmp_path):
    T.build(str(V4H), str(tmp_path / "t"), "LOW")
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(tmp_path / "t")], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout[-600:] + p.stderr[-1200:]
    assert "'include_thoughts': True" in p.stdout and "'thinking_level': 'LOW'" in p.stdout, p.stdout
