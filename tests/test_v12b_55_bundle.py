"""v12b_55 = v12b (hidden 0.17, our best) with ONE change: max_time_minutes 5 -> 5.5 in eval_config.yaml. Evidence (GAPS
'sub28 re-registered', research/assumptions_2026-10-31): the budget is the one systematic difference from the best public
lineages; on the Kaggle L4 traces 8% of runs still alive at 240 s solve in the next 60 s; the verified 12-hour projection at
5.5 min is 10.5-11.3 h with a breach probability of about 0-1.5%. It is not safe by construction: 120 tasks all at the cap
with 30 s of setup each would take 12.3 h; v12b6, at 6 minutes, completed on the hidden set. The prompt's "about 5 minutes"
stays, so every other file, the prompt included, is byte-identical to v12b. Both the host notebook and
scripts/make_eval_kernel.py read the cap with float(), so 5.5 is honoured rather than rounded. Pinned before any v12b_55 row
exists."""
import filecmp
import importlib.util
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v13_leakage import leaks  # noqa: E402
BASE = ROOT / "submissions" / "v12b"
NEW = ROOT / "submissions" / "v12b_55"


def files(d):
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def builder():
    spec = importlib.util.spec_from_file_location("make_eval_kernel", ROOT / "scripts" / "make_eval_kernel.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_only_eval_config_differs():
    assert files(BASE) == files(NEW)
    assert [f for f in files(BASE) if not filecmp.cmp(BASE / f, NEW / f, shallow=False)] == ["eval_config.yaml"]


def test_eval_config_is_v12b_with_the_cap_at_5_5():
    base = (BASE / "eval_config.yaml").read_text()
    assert base.count("  max_time_minutes: 5\n") == 1
    assert (NEW / "eval_config.yaml").read_text() == base.replace("  max_time_minutes: 5\n", "  max_time_minutes: 5.5\n")


def test_the_budget_parses_as_5_5_minutes_with_v12bs_other_limits():
    m = builder()
    new, base = m.read_budget(str(NEW))[0], m.read_budget(str(BASE))[0]
    assert new["max_time_minutes"] == 5.5 and isinstance(new["max_time_minutes"], float)
    assert {k: v for k, v in new.items() if k != "max_time_minutes"} == {k: v for k, v in base.items() if k != "max_time_minutes"}
    assert m.host_budget(m.load_eval_config((NEW / "eval_config.yaml").read_text()))["max_time_minutes"] == 5.5


def test_the_prompt_still_says_about_5_minutes():
    s = (NEW / "prompts/system.md").read_text()
    assert "You have about 5 minutes and 40 tool calls" in s
    assert re.findall(r"{+[^{}]*}+", s) == []


def test_no_bundle_file_names_a_public_task_its_gold_code_or_its_tests():
    assert not leaks(NEW)


def test_the_leakage_check_catches_a_planted_gold_path_and_task_id_in_this_bundle(tmp_path):
    shutil.copytree(NEW, tmp_path / "b")
    f = tmp_path / "b" / "prompts" / "system.md"
    f.write_text(f.read_text() + "\nSee rich/panel.py and fastapi_15661.\n")
    assert {"rich/panel.py", "fastapi_15661"} <= {name for _, name, _ in leaks(tmp_path / "b")}


def test_still_the_31b():
    assert "model: gemma-4-31b-it-qat-w4a16-ct" in (NEW / "agent.yaml").read_text().splitlines()
