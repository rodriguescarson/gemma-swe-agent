"""v16a = pub024 (the public LB-0.24 control, hidden 0.24) with ONE change, L1 from our v13 line: edits only through a
run_command python heredoc that asserts the old block occurs exactly once and compiles before writing; edit_file and write_file
are removed from the tools. Why (GAPS 'v16a pre-registration', 2026-10-17): on the box pub024 made 203 edit attempts of which
56 were malformed (the gemma4 tool parser corrupts edit_file arguments) inside a 28-call budget; v13/v15 with L1 had 0
malformed edits and v15 had 0 errored rows. Pinned before any v16a row exists: every file byte-identical to pub024 except
agent.yaml (exactly the two tool lines removed) and prompts/system.md (exactly the two '## 3. Edit' bullets that name
edit_file/write_file replaced by L1_TEXT); no braces in the prompt (the notebook's own assertion: ADK templating); no mention
of edit_file or write_file anywhere; scripts/validate.py OK with seven tools, temperature 0.2, thinking_budget 4096; the
evaluation limits unchanged."""
import filecmp, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "submissions" / "pub024"
V16A = ROOT / "submissions" / "v16a"
TOOL_LINES = "  - edit_file\n  - write_file\n"
OLD_BULLETS = (
    "- Use edit_file for changes to existing code. Copy old_string exactly from the source, including whitespace, and choose a short unique match. Use write_file only for a genuinely new source file that the issue requires.\n"
    "- If edit_file reports no match or multiple matches, read the exact source region and retry with a smaller unique snippet. Never repeat an identical failed edit. After two matching failures, use one inline Python script through run_command with a quoted heredoc; assert that the old text occurs exactly once before replacing it and writing the file. Preserve unrelated content and do not rewrite the file from memory.\n"
)
L1_TEXT = """- Edit existing code with run_command only, one change per command, always in this form (the old block is a few lines copied exactly from what you read, the new block is their replacement; use r\"\"\" quotes instead if the code itself contains three single quotes):
```
python3 - <<'EDIT'
from pathlib import Path
p = Path("path/to/module.py")
old = r'''
<old lines, copied exactly>
'''.lstrip("\\n")
new = r'''
<new lines>
'''.lstrip("\\n")
s = p.read_bytes().decode()
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)
if p.suffix == ".py":
    compile(s, str(p), "exec")
p.write_bytes(s.encode())
print("edited", p)
EDIT
```
- The file is written only when the old block occurs exactly once and the result compiles. If the command fails, read those lines again and retry with a shorter old block; never resend the identical command. Create a genuinely new source file that the issue requires with `cat > path/to/new_file.py <<'EOF'`. Preserve unrelated content and do not rewrite the file from memory.
"""


def all_files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())


def test_only_agent_yaml_and_the_prompt_differ_from_pub024():
    assert all_files(V16A) == all_files(PUB)
    for rel in all_files(PUB):
        same = filecmp.cmp(PUB / rel, V16A / rel, shallow=False)
        assert same == (rel not in ("agent.yaml", "prompts/system.md")), rel
        assert os.stat(PUB / rel).st_mode == os.stat(V16A / rel).st_mode, rel


def test_agent_yaml_is_pub024_minus_exactly_the_two_tool_lines():
    old = (PUB / "agent.yaml").read_text()
    assert old.count(TOOL_LINES) == 1
    assert (V16A / "agent.yaml").read_text() == old.replace(TOOL_LINES, "")


def test_prompt_is_pub024_with_the_edit_bullets_replaced_by_l1():
    old = (PUB / "prompts" / "system.md").read_text()
    new = (V16A / "prompts" / "system.md").read_text()
    assert old.count(OLD_BULLETS) == 1
    assert new == old.replace(OLD_BULLETS, L1_TEXT)
    assert "{" not in new and "}" not in new
    assert "edit_file" not in new and "write_file" not in new
    assert "<<'EDIT'" in new and "assert s.count(old) == 1" in new


def test_validator_passes_for_v16a_with_seven_tools():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(V16A)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert ("tools=['run_command', 'read_file', 'get_status', 'submit_patch', 'get_code_neighbors', 'search_similar_code', "
            "'get_code_subgraph']") in r.stdout, r.stdout[-800:]
    assert "'thinking_budget': 4096" in r.stdout and "'temperature': 0.2" in r.stdout
