"""Build submissions/<name> = a byte copy of submissions/v13 (modes kept) with the one lever text of tests/test_v13_rich_solve.py
LEVERS[<name>] inserted after its anchor in prompts/system.md. Refuses to overwrite an existing bundle.

    python scripts/forty_two/rich_solve/build_bundle.py v13_modtests"""
import importlib.util, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
name = sys.argv[1]
spec = importlib.util.spec_from_file_location("levers", ROOT / "tests" / "test_v13_rich_solve.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
anchor, added = mod.LEVERS[name]
src, dst = ROOT / "submissions" / "v13", ROOT / "submissions" / name
if dst.exists():
    sys.exit(f"{dst} exists")
shutil.copytree(src, dst, copy_function=shutil.copy2)
p = dst / "prompts" / "system.md"
s = p.read_text()
assert s.count(anchor) == 1, s.count(anchor)
p.write_text(s.replace(anchor, anchor + added))
print(f"built {dst.relative_to(ROOT)}; lever text {mod.gemma_tokens(added)} Gemma tokens, {len(added)} characters")
