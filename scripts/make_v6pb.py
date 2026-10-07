"""Build submissions/v6p-b from v6p and v4h2 (docs/v4h/GATE.md, P2 addendum 6). Deterministic; run it again to regenerate.

v6p-b = v6p's structure (setup, locator, three parallel fixers in their own copies, selector, verifier) rebased on v4h2: v4h2's locator prompt and sampling for
the locator, verifier, setup and selector, v4h2's verifier text with the selection report in place of the fixer's notes, thinking off everywhere; the fixers keep
three temperatures (0.2 / 0.6 / 0.9) and get a fixed share of the 70-call total (submissions/v6p-b/skills/swe-tools/scripts/_budget.py SHARES), enforced by the
helper ledger, and they stop once one candidate passes its tests. Dropped from v6p because v4h2 has none of it: the repro-first locator (S3) and repro.py."""
import re, shutil, sys
sys.dont_write_bytecode = True      # a .pyc inside the bundle makes the official validator refuse it
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB = ROOT / "submissions"
V4, V6, B = SUB / "v4h2", SUB / "v6p", SUB / "v6p-b"

FIXER = """You are FIXER {L}, one of three fixers working at the same time on the same issue. Each fixer works in its own copy of the repository; yours is /tmp/w{l}. Implement the change now.

Issue:
{{problem_description}}

Locator's plan:
{{plan?}}

Your first tool call is run_command(command="rm -rf /tmp/w{l} && cp -a /workspace /tmp/w{l} && git -C /tmp/w{l} status --short | head -5"). After that, do ALL reads, edits and tests inside /tmp/w{l}: start every command with `cd /tmp/w{l} && `. Never edit /workspace and never touch another fixer's copy: the other fixers are copying /workspace while you work.
Helpers are never tool names. The ONLY correct call shape is run_command(command="cd /tmp/w{l} && python3 /tmp/swe/edit.py ..."); a call whose name starts with python3 or /tmp/swe is an unknown tool and ends the task with no patch.
Your share of the team's tool calls is fixed. At most {fixer} tool calls in total: your first one (the copy), at most {helper} helper calls (view.py, edit.py, test.py: each prints how many you have used), at most one other command (a git grep), and your last one (the final diff). When a helper prints STOP or SHARE SPENT, your very next call is the final diff command and then your reply: nothing else.
Rules: read the target lines with run_command(command="cd /tmp/w{l} && python3 /tmp/swe/view.py path/to/file.py START END") (at most 120 lines; a range you already saw is refused, so edit instead of re-reading), then edit ONLY with `run_command`, as raw code with no escaping:
cd /tmp/w{l} && python3 /tmp/swe/edit.py path/to/file.py <<'EOF'
<<<<<<< SEARCH
exact current lines (copied as read, unique, short)
=======
new lines
>>>>>>> REPLACE
EOF
Or replace lines by number: cd /tmp/w{l} && python3 /tmp/swe/edit.py path/to/file.py --lines 120-135 <<'EOF' then the new lines, then EOF. For a new file use --create instead of --lines. EOF appears once, as the last line. A broken edit is undone; a SEARCH that does not match prints the closest numbered lines for --lines. If a helper reports "can't open file", call `run_skill_script(skill_name="swe-tools", file_path="install.py")` once and repeat the call.
Make the smallest complete source change; create new functions/params/files with exactly the names the issue implies. Never edit tests, conftest.py, pytest.ini, pyproject.toml, setup.cfg or tox.ini. Scratch files go in /tmp, never inside /tmp/w{l}. Never repeat a tool call. If an edit fails, re-read those exact lines before retrying with a shorter SEARCH; never resend the identical edit. The current code IS wrong: do not conclude that nothing needs changing.
Working rules: make the example in the issue work first, before docstrings or cleanups. Edit by your 4th tool call; do not keep reading. To find a name, use run_command(command="cd /tmp/w{l} && git -C /tmp/w{l} grep -n NAME") once instead of viewing more pages. Wrap any script you run as `timeout 30 python3 ...`.
Check: run the relevant test once with run_command(command="cd /tmp/w{l} && python3 /tmp/swe/test.py --target <test file from the plan>"). If it passes, the other fixers are told to stop and the selection will use your candidate.
Your last tool call is always run_command(command="cd /tmp/w{l} && git -C /tmp/w{l} add -N . && git -C /tmp/w{l} diff > /tmp/w{l}.diff; git -C /tmp/w{l} diff --stat"), even if you ran out of ideas.
Then STOP calling tools and reply in under 100 words: what you changed (file, function) and which test to run.

Tools you can call: run_command, get_status, get_code_neighbors, search_similar_code, get_code_subgraph, run_skill_script. There is no edit_file tool, no write_file tool and no bash tool: edit through the edit.py helper inside /tmp/w{l} and run shell commands such as `git -C /tmp/w{l} grep` through `run_command`.
"""

LOCATOR_EDITS = [
    ("Steps (at most 8 tool calls, never repeat a call):",
     "Steps (at most {locator} tool calls, never repeat a call; locate.py and view.py are counted: after your {locator_helper}th helper call they refuse and print SHARE SPENT, and your next message must be the plan):"),
    ("3. Read the most relevant function(s) with `read_file(filepath, start_line, end_line)`.",
     "3. Read the most relevant function(s) with `run_command(command=\"python3 /tmp/swe/view.py path/to/file.py START END\")` (at most 120 lines per call; a range already shown is refused)."),
    ("Tools you can call: run_command, read_file, edit_file, write_file, get_status, get_code_neighbors, search_similar_code, get_code_subgraph, run_skill_script. There is no other tool (no git_grep, no bash tool): run shell commands such as `git grep` through `run_command`.",
     "Tools you can call: run_command, get_status, get_code_neighbors, search_similar_code, get_code_subgraph, run_skill_script. There is no read_file, edit_file, write_file, git_grep or bash tool: read with view.py and run shell commands such as `git grep` through `run_command`."),
]

VERIFIER_EDITS = [
    ("You are the VERIFIER in a three-stage team working in /workspace. The fix is already applied.",
     "You are the VERIFIER working in /workspace. Three fixers each proposed a fix; the selection script tested them and applied the best one to /workspace."),
    ("Fixer's notes:\n{fix_notes?}", "Selection report:\n{selection?}"),
    ("If `git diff` is empty, the fix was NOT applied:", "If `git diff` is empty, no candidate fix was applied:"),
]

SKILL_NOTE = ("- `python3 /tmp/swe/view.py`, `edit.py` and `test.py` inside a fixer's copy (/tmp/wa, /tmp/wb, /tmp/wc) are counted per fixer (a share of the team's 70 tool calls, "
              "see _budget.py): after the share they refuse and tell the fixer to write its diff and stop; once one fixer's test passes the others are told to stop.\n")


def shares():
    sys.path.insert(0, str(B / "skills" / "swe-tools" / "scripts"))
    import _budget
    return _budget.SHARES


def build():
    s = shares()
    for f in ("a", "b", "c"):
        (B / "prompts" / f"fixer_{f}.md").write_text(FIXER.format(L=f.upper(), l=f, fixer=s["fixer"], helper=s["helper"]))
    loc = (V4 / "prompts" / "locator.md").read_text()
    for old, new in LOCATOR_EDITS:
        assert old in loc, old
        loc = loc.replace(old, new.format(**s))
    (B / "prompts" / "locator.md").write_text(loc)
    ly = (V6 / "sub_agents" / "locator.yaml").read_text()
    ly = re.sub(r"^tools:.*$", "tools: [run_command, get_status, get_code_neighbors, search_similar_code, get_code_subgraph]", ly, flags=re.M)
    (B / "sub_agents" / "locator.yaml").write_text(ly)
    shutil.copyfile(V4 / "configs" / "sampling.yaml", B / "configs" / "sampling.yaml")
    v = (V4 / "prompts" / "verifier.md").read_text()
    for old, new in VERIFIER_EDITS:
        assert old in v, old
        v = v.replace(old, new)
    (B / "prompts" / "verifier.md").write_text(v)
    sk = B / "skills" / "swe-tools" / "SKILL.md"
    t = sk.read_text()
    t = "\n".join(l for l in t.splitlines() if "repro.py" not in l) + "\n"
    if "_budget.py" not in t:
        t += SKILL_NOTE
    sk.write_text(t)
    (B / "agent.yaml").write_text((V6 / "agent.yaml").read_text().replace("Locate, fix three ways in parallel, select the best candidate by tests, verify.",
                                  "v6p rebased on v4h2 - locate, three budgeted parallel fixers that stop once one passes, select by tests, verify."))
    fx = (V6 / "sub_agents" / "fixers.yaml").read_text().split("# Tool budget")[0].rstrip() + "\n" + (
        "# Tool budget (eval_config max_tool_calls = 70 counts every agent's calls in a task, and the harness cannot cap one agent):\n"
        "#   setup 1 + locator %d + 3 fixers x %d + selector 1 + verifier %d = %d <= 70; the locator and every fixer may overshoot by %d raw calls and the\n"
        "#   selector and verifier still have their %d (70 - 1 - (%d + %d) - 3 x %d = %d).\n"
        "# The caps live in the helper ledger (skills/swe-tools/scripts/_budget.py); tests/test_v6pb_bundle.py checks the arithmetic and the prompts.\n"
    ) % (s["locator"], s["fixer"], s["verifier"], s["setup"] + s["locator"] + 3 * s["fixer"] + s["selector"] + s["verifier"], s["allowance"],
         s["selector"] + s["verifier"], s["locator"], s["allowance"], s["fixer"] + s["allowance"], BUDGET_LEFT(s))
    (B / "sub_agents" / "fixers.yaml").write_text(fx)


def BUDGET_LEFT(s):
    return s["total"] - s["setup"] - (s["locator"] + s["allowance"]) - 3 * (s["fixer"] + s["allowance"])


if __name__ == "__main__":
    build()
    for d in B.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
    print("built", B)
