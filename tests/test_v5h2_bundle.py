"""v5h2 / v5h2b: the v5all and v5b changes rebased onto v4h2 (docs/v4h/GATE.md, Pallets dev40 + holdout57: v4h2 29 vs
v4h2g 20 of 97, paired 10-1, p = 0.012 -> rebase future variants onto v4h2).

v5h2  = v4h2 + view.py loop breaker (v4h6g) + temperature 0.2 + verifier repro step + fixer Working rules + locator
        search-term filter (v5all), WITHOUT v4h2g's locator retry line, PLUS v4h2f's install.py: on the 4xL4 traces of
        v4h2 (g4-l4-v4 v4) locate.py failed 145/151, check.py 61/62, test.py 19/19 with "can't open file" because
        v4h2's install copied only edit.py into the sandbox tmp; view.py (the fixer's only read channel once read_file is
        removed) would be dead the same way. v4h2f's install is the same single call, so it costs no model call.
v5h2b = v5h2 + v5b's three changes (repo_map.py, title-only test-driven locator step, run_skill_script file_path guard)."""
import difflib, filecmp, os, re, subprocess, sys, zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SUB = ROOT / "submissions"
V4H2, V4H2F, V4H6G, V5ALL, V5B = (SUB / n for n in ("v4h2", "v4h2f", "v4h6g", "v5all", "v5b"))
V5H2, V5H2B = SUB / "v5h2", SUB / "v5h2b"
STAGES = ("locator", "fixer", "verifier")
GUARD = 'run_skill_script takes file_path as ONE string (file_path="install.py"), never a list: a list crashes the sandbox.'
RETRY = 'If any helper later reports "can\'t open file", call it once more and repeat the helper call.'
KERNELS = {"v5h2": ("g4-l4-v5h2-p312", "g4-eval74-v4"), "v5h2b": ("g4-l4-v5h2b-p312", "g4-l4-v4")}
QUEUED_SLUGS = {"g4-l4-v9-eog", "g4-eval74-v3", "g4-eval74-v2"}  # v5all, v5b, v11b-probe (queue_after_reset.sh)


def files(d):
    return {str(p.relative_to(d)) for p in d.rglob("*")
            if p.is_file() and not p.name.startswith(".") and "__pycache__" not in p.parts}


def changed(a, b):
    return {rel for rel in files(a) & files(b) if not filecmp.cmp(a / rel, b / rel, shallow=False)}


def same(a, b, rel):
    return filecmp.cmp(a / rel, b / rel, shallow=False)


def line_delta(a, b):
    """(removed lines, added lines) between two texts."""
    rm, add = [], []
    for l in difflib.ndiff(a.splitlines(), b.splitlines()):
        if l.startswith("- "): rm.append(l[2:])
        elif l.startswith("+ "): add.append(l[2:])
    return rm, add


# ---------------------------------------------------------------- v5h2 = v4h2 + listed changes only

def test_v5h2_differs_from_v4h2_only_in_the_listed_files():
    assert files(V5H2) == files(V4H2) | {"skills/swe-tools/scripts/view.py"}
    assert changed(V4H2, V5H2) == {"skills/swe-tools/scripts/install.py", "configs/sampling.yaml", "prompts/fixer.md",
                                   "prompts/locator.md", "prompts/verifier.md", "sub_agents/fixer.yaml"}, changed(V4H2, V5H2)


def test_v5h2_takes_each_change_from_its_source_bundle():
    assert same(V4H2F, V5H2, "skills/swe-tools/scripts/install.py")             # sandbox-tmp install, unchanged
    assert same(V4H6G, V5H2, "skills/swe-tools/scripts/view.py")                # loop breaker helper
    assert same(V4H6G, V5H2, "sub_agents/fixer.yaml")                           # read_file removed from the fixer
    for rel in ("configs/sampling.yaml", "prompts/fixer.md", "prompts/verifier.md"):
        assert same(V5ALL, V5H2, rel), rel                                      # v4h2g never touched these
    assert "temperature: 0.2" in (V5H2 / "configs/sampling.yaml").read_text()


def test_v5h2_locator_has_the_search_term_filter_but_not_the_v4h2g_retry_line():
    loc = (V5H2 / "prompts/locator.md").read_text()
    assert RETRY not in loc and "can't open file" not in loc
    assert "leave out URLs, version numbers, environment dumps and doc links" in loc
    rm, add = line_delta((V4H2 / "prompts/locator.md").read_text(), loc)
    v5_rm, v5_add = line_delta((V4H6G / "prompts/locator.md").read_text(), (V5ALL / "prompts/locator.md").read_text())
    assert add == v5_add and len(rm) == 1 and rm[0].startswith("2. ")           # exactly v5all's step-2 change


def test_v5h2_fixer_reads_through_view_py_only():
    y = (V5H2 / "sub_agents/fixer.yaml").read_text()
    assert "read_file" not in y.split("tools:")[1].split("\n")[0]
    p = (V5H2 / "prompts/fixer.md").read_text()
    assert 'run_command(command="python3 /tmp/swe/view.py' in p and "read_file(" not in p and "Working rules:" in p
    assert "/tmp/repro.py" in (V5H2 / "prompts/verifier.md").read_text()


# ---------------------------------------------------------------- v5h2b = v5h2 + v5b's three changes

def test_v5h2b_differs_from_v5h2_only_in_the_listed_files():
    assert files(V5H2B) == files(V5H2) | {"skills/swe-tools/scripts/repo_map.py"}
    assert changed(V5H2, V5H2B) == {"skills/swe-tools/SKILL.md", "prompts/locator.md", "prompts/fixer.md",
                                    "prompts/verifier.md"}, changed(V5H2, V5H2B)


def test_v5h2b_ports_v5b_faithfully():
    for rel in ("skills/swe-tools/scripts/repo_map.py", "skills/swe-tools/SKILL.md", "prompts/fixer.md",
                "prompts/verifier.md"):
        assert same(V5B, V5H2B, rel), rel
    # the locator gets exactly the lines v5b added to v5all's locator, and loses nothing
    rm, add = line_delta((V5H2 / "prompts/locator.md").read_text(), (V5H2B / "prompts/locator.md").read_text())
    v5b_rm, v5b_add = line_delta((V5ALL / "prompts/locator.md").read_text(), (V5B / "prompts/locator.md").read_text())
    assert rm == v5b_rm == [] and add == v5b_add
    loc = (V5H2B / "prompts/locator.md").read_text()
    assert RETRY not in loc
    assert loc.count("only a title") == 1 and loc.count(GUARD) == 1 and "SPEC:" in loc
    # identical to v5b's locator except the v4h2g retry sentence
    assert loc == (V5B / "prompts/locator.md").read_text().replace(" " + RETRY, "")


def test_v5h2b_guard_once_wherever_run_skill_script_appears():
    texts = {p.relative_to(V5H2B).as_posix(): p.read_text() for p in V5H2B.rglob("*.md")}
    users = {k for k, t in texts.items() if "run_skill_script" in t}
    assert {"prompts/locator.md", "prompts/fixer.md", "prompts/verifier.md", "skills/swe-tools/SKILL.md"} <= users
    for k in users:
        assert texts[k].count(GUARD) == 1, k
    assert not any(re.search(r"file_path\s*=\s*\[", t) for t in texts.values())


# ---------------------------------------------------------------- per bundle: compile, pack, tools, helpers, probes

BUNDLES = [pytest.param(V5H2, id="v5h2"), pytest.param(V5H2B, id="v5h2b")]


@pytest.mark.parametrize("b", BUNDLES)
def test_compiles_with_the_official_compiler(b):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(b)], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-1500:]
    fixer_line = r.stdout.split("LlmAgent fixer")[1].split("\n")[0]
    assert "SkillToolset" in fixer_line and "read_file" not in fixer_line, fixer_line


@pytest.mark.parametrize("b", BUNDLES)
def test_packs_under_limits(b, tmp_path):
    z = tmp_path / "b.zip"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "pack_bundle.py"), str(b), str(z)], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert z.stat().st_size < 1_000_000
    names = zipfile.ZipFile(z).namelist()
    for rel in files(b):
        assert rel in names, rel
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)


@pytest.mark.parametrize("b", BUNDLES)
def test_every_tool_named_in_a_prompt_is_declared_by_that_stage(b):
    from test_v10_prompts import HALLUCINATED, REGISTRY_FALLBACK, named_tools
    from test_v10_bundle import SKILL_TOOLS
    from test_v5b_bundle import affirmative, declared_tools
    vocab = REGISTRY_FALLBACK | SKILL_TOOLS | HALLUCINATED
    for s in STAGES:
        found = named_tools(affirmative((b / "prompts" / f"{s}.md").read_text()), vocab)
        assert found <= declared_tools(s, b), (s, found - declared_tools(s, b))
        assert ("submit_patch" in found) == (s == "verifier"), s


def helpers_used(b):
    used = set()
    for p in list((b / "prompts").glob("*.md")) + [b / "skills/swe-tools/SKILL.md"]:
        used |= set(re.findall(r"python3 /tmp/swe/(\w+\.py)", p.read_text()))
    return used


@pytest.mark.parametrize("b", BUNDLES)
def test_helpers_used_by_prompts_exist_and_install_into_the_sandbox_tmp(b, tmp_path):
    used = helpers_used(b)
    assert {"edit.py", "locate.py", "test.py", "check.py", "view.py"} <= used
    if b == V5H2B:
        assert "repo_map.py" in used
    scripts = b / "skills/swe-tools/scripts"
    for h in used:
        assert (scripts / h).exists(), h
    env = dict(os.environ, TMPDIR=str(tmp_path), TEST_TMPDIR=str(tmp_path))
    p = subprocess.run([sys.executable, str(scripts / "install.py")], capture_output=True, text=True, env=env)
    assert p.returncode == 0 and "helpers in" in p.stdout, p.stdout + p.stderr
    for h in used | {"_ws.py"}:
        assert (tmp_path / "swe" / h).exists(), h                               # in <sandbox tmp>/swe, not only /tmp/swe


def probe_keys():
    src = (ROOT / "scripts" / "make_eval_kernel.py").read_text()
    block = src.split("PROBES = {", 1)[1].split("}\n", 1)[0]
    return set(re.findall(r'"(\w+\.py)":', block))


@pytest.mark.parametrize("b", BUNDLES)
def test_kaggle_helper_check_probes_cover_every_helper_the_prompts_use(b):
    keys = probe_keys()
    assert {"locate.py", "view.py"} <= keys                                     # control: the parser reads the dict
    assert helpers_used(b) <= keys, helpers_used(b) - keys


# ---------------------------------------------------------------- Kaggle eval kernels (v5b recipe)

@pytest.mark.parametrize("name", sorted(KERNELS))
def test_eval_kernel_matches_the_v5b_recipe(name, tmp_path):
    kdir, slug = KERNELS[name]
    assert slug not in QUEUED_SLUGS
    kd = ROOT / "kernels" / kdir
    meta = (kd / "kernel-metadata.json").read_text()
    assert f'"id": "carsonrodrigues/{slug}"' in meta and '"docker_image_pinning_type": "original"' in meta
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_eval_kernel.py"), str(SUB / name), kdir,
                        "--ids", str(ROOT / "data" / "kaggle_valid_ids.txt"), "--pin", "original", "--kernel-id", slug],
                       cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    for f in ("kernel-metadata.json", slug + ".ipynb"):
        assert (tmp_path / "kernels" / kdir / f).read_bytes() == (kd / f).read_bytes(), f


def test_eval_kernel_slugs_are_distinct():
    assert len({s for _, s in KERNELS.values()}) == len(KERNELS)
