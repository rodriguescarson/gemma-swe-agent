"""No public-task specifics in any file of submissions/v13 (the bundle is scored on ~129 hidden tasks from other repos; text that
names a public task, its gold files, its gold functions/classes or its tests is overfitting, and nothing Gemma sees may carry it).

Deny list, built from data/tasks.jsonl for the 74 public ids (data/kaggle_valid_ids.txt): every task id; every file path in a
gold patch or test patch; every `def`/`class` name in a gold patch (added, removed or in a hunk header); every `def test_*` name
in a test patch. Words in GENERIC are allowed: they are English or Python words that the name regex also picks up from gold
docstrings and comments ("class that ...") and that the prompt uses in their ordinary sense."""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "submissions" / "v13"
GENERIC = {"setup", "print", "that", "stop", "from", "create", "load", "loads", "to", "app", "log", "ask", "Text"}


def public_ids():
    return set((ROOT / "data" / "kaggle_valid_ids.txt").read_text().split())


def deny_list():
    ids = public_ids()
    deny = {}
    for line in (ROOT / "data" / "tasks.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        t = json.loads(line)
        i = t["instance_id"]
        if i not in ids:
            continue
        names = {i}
        names |= set(re.findall(r"^(?:\+\+\+ b|--- a)/(\S+)", t["patch"] + "\n" + t["test_patch"], re.M))
        names |= set(re.findall(r"(?:def|class)\s+(\w+)", t["patch"]))
        names |= set(re.findall(r"def\s+(test_\w+)", t["test_patch"]))
        for n in names - GENERIC - {"/dev/null"}:
            deny.setdefault(n, set()).add(i)
    return deny


def test_deny_list_covers_the_74_public_tasks():
    deny = deny_list()
    assert len(public_ids()) == 74
    assert {i for v in deny.values() for i in v} == public_ids()
    assert "rich/panel.py" in deny and "fastapi_15661" in deny                 # spot checks: a gold path, a task id
    assert any(k.startswith("test_") for k in deny)


def leaks(bundle):
    deny = deny_list()
    hits = []
    for p in sorted(Path(bundle).rglob("*")):
        if not p.is_file():
            continue
        text = p.read_text(errors="replace")
        for name, owners in deny.items():
            if re.search(r"(?<![\w/.])" + re.escape(name) + r"(?![\w/])", text):
                hits.append((str(p.relative_to(bundle)), name, sorted(owners)[:3]))
    return hits


def test_the_check_catches_a_planted_gold_path_function_and_test_name(tmp_path):
    import shutil
    shutil.copytree(BUNDLE, tmp_path / "b")
    f = tmp_path / "b" / "prompts" / "system.md"
    deny = deny_list()
    test_name = sorted(k for k in deny if k.startswith("test_"))[0]
    code_name = sorted(k for k in deny if re.fullmatch(r"_?[a-z]+(_[a-z]+)+", k) and not k.startswith("test_"))[0]
    f.write_text(f.read_text() + f"\nSee rich/panel.py, {code_name}, {test_name} and fastapi_15661.\n")
    names = {n for _, n, _ in leaks(tmp_path / "b")}
    assert {"rich/panel.py", "fastapi_15661", code_name, test_name} <= names


def test_no_bundle_file_names_a_public_task_its_gold_code_or_its_tests():
    assert not leaks(BUNDLE)
