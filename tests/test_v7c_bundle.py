"""v7c = v7b with no read cap (docs/GAPS_2026-10-06.md, "v7c pre-registration"), built in a new directory so v7 and
v7b stay byte-identical. Strict test-first: step 1, v7c was an exact copy (cp -a, byte-identical with the same modes:
commit "v7c step 1"); every later step names the files it may change.

  fixes 1+2  no read cap; the outline on every 3rd identical re-read: view.py + _ws.py (tests/test_v7c_helpers.py,
             tests/test_v7c_sandbox.py)
  fix 3      no read-cap text: the prompts and SKILL.md never had any (byte-identical to v7b's); locator.yaml's call
             arithmetic comment is restated without it, every other line unchanged (tests/test_v7c_prompts.py, below)"""
import filecmp, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUB = ROOT / "submissions"
V7B, V7C = SUB / "v7b", SUB / "v7c"
FIX12 = {"skills/swe-tools/scripts/view.py", "skills/swe-tools/scripts/_ws.py"}
FIX3 = {"sub_agents/locator.yaml"}
CHANGED = FIX12 | FIX3


def all_files(d):
    """Every file under d, hidden ones included (a stray .DS_Store or __pycache__ is a difference too)."""
    return {str(p.relative_to(d)) for p in d.rglob("*") if p.is_file()}


def changed(a, b):
    return {rel for rel in all_files(a) & all_files(b) if not filecmp.cmp(a / rel, b / rel, shallow=False)}


def test_v7c_differs_from_v7b_only_in_the_listed_files():
    assert all_files(V7C) == all_files(V7B), all_files(V7C) ^ all_files(V7B)
    assert changed(V7B, V7C) == CHANGED, changed(V7B, V7C) ^ CHANGED
    for rel in sorted(all_files(V7B)):
        assert os.stat(V7B / rel).st_mode == os.stat(V7C / rel).st_mode, rel


# ------------------------------------------------------------------ fix 3: the call arithmetic, without a read cap

def comment(b):
    return "\n".join(l for l in (b / "sub_agents" / "locator.yaml").read_text().splitlines() if l.startswith("#"))


def test_the_locator_yaml_changes_only_its_arithmetic_comment():
    old, new = ((b / "sub_agents" / "locator.yaml").read_text().splitlines() for b in (V7B, V7C))
    assert [l for l in new if not l.startswith("#")] == [l for l in old if not l.startswith("#")]
    assert new.index(comment(V7C).splitlines()[0]) == old.index(comment(V7B).splitlines()[0])   # in the same place


def test_the_call_arithmetic_is_stated_without_a_read_cap():
    import re, yaml
    from test_v7c_helpers import ws_attrs
    (locate_cap,) = ws_attrs("LOCATE_CAP")
    c = comment(V7C)
    ev = yaml.safe_load((V7C / "eval_config.yaml").read_text())["evaluation"]
    assert ev["max_tool_calls"] == 70 and ev["max_time_minutes"] == 5
    shares = {k: int(v) for k, v in re.findall(r"^#\s+(setup|locator|fixer|verifier)\s+(\d+)\b", c, re.M)}
    assert shares == {"setup": 1, "locator": 8, "fixer": 12, "verifier": 49} and sum(shares.values()) == ev["max_tool_calls"]
    say = dict(re.findall(r"^#\s+(setup|locator|fixer|verifier)\s+\d+\s+(.*)$", c, re.M))
    assert say["locator"].startswith("its prompt cap") and f"locate.py <= {locate_cap} per task" in say["locator"]
    assert "_ws.LOCATE_CAP" in say["locator"] and say["fixer"].startswith("its prompt cap")
    assert say["verifier"].startswith("the reserve: 70 - 1 - 8 - 12")
    assert "view.py calls and raw greps: no helper limits them" in c and "the prompt cap is their only bound" in c
    assert "VIEW_CAP" not in c and not re.search(r"\b14\b", c) and "first OK edit" not in c and "read cap" not in c
    assert "at most 8 tool calls" in (V7C / "prompts" / "locator.md").read_text()
    assert "At most 12 tool calls" in (V7C / "prompts" / "fixer.md").read_text()
    assert "view.py <= 14" in comment(V7B) and "_ws.VIEW_CAP" in comment(V7B)            # control: v7b stated the cap
