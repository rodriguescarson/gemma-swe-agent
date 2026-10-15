"""No module in a directory the tests put on sys.path may share a name with a stdlib module (the Linux-only failure class
this repo's Linux gate exists for: select.py in 2026-09, and on 2026-10-15 scripts/pallets/profile.py, inserted by
test_heldout_miner/test_or_race_summary at import time, made `import cProfile` raise in the qlora tests later in the same
session). Written before the rename."""
import pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _dirs_on_sys_path():
    dirs = {ROOT, ROOT / "tests"}
    for t in (ROOT / "tests").rglob("test_*.py"):
        s = t.read_text()
        for line in s.splitlines():
            if "sys.path.insert" not in line and "sys.path.append" not in line: continue
            for seg in line.split("sys.path.")[1:]:                  # two inserts on one line are common here
                parts = re.findall(r'"([^"]+)"', seg)               # ROOT / "scripts" / "pallets" -> scripts/pallets
                dirs.add(ROOT.joinpath(*parts) if parts else ROOT)
    return sorted(d for d in dirs if d.is_dir())


def test_no_stdlib_module_is_shadowed_on_the_test_sys_path():
    std = set(sys.stdlib_module_names)
    dirs = _dirs_on_sys_path()
    assert ROOT / "scripts" / "pallets" in dirs, dirs                # the inserts are parsed, not guessed
    shadows = []
    for d in dirs:
        shadows += [p for p in d.glob("*.py") if p.stem in std]
        shadows += [p for p in d.iterdir() if p.is_dir() and p.name in std and (p / "__init__.py").exists()]
    assert not shadows, [str(p.relative_to(ROOT)) for p in shadows]
