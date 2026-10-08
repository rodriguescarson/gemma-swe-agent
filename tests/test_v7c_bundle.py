"""v7c = v7b with no read cap (docs/GAPS_2026-10-06.md, "v7c pre-registration"), built in a new directory so v7 and
v7b stay byte-identical. Strict test-first: step 1, v7c was an exact copy (cp -a, byte-identical with the same modes:
commit "v7c step 1"); every later step names the files it may change.

  fixes 1+2  no read cap; the outline on every 3rd identical re-read: view.py + _ws.py (tests/test_v7c_helpers.py,
             tests/test_v7c_sandbox.py)
  fix 3      no read-cap text: the prompts and SKILL.md never had any (byte-identical to v7b's); locator.yaml's call
             arithmetic comment is restated without it, every other line unchanged (tests/test_v7c_prompts.py, below)
  kernel     g4-l4-v7c-p312 on the free existing 3.12 slug g4-oracle-all: v7b's kernel but the changed files and the slug

Below: the compiled tree (v7b's), the helpers (install + Kaggle PROBES, and the Kaggle helper check run on v7c), packing,
the call arithmetic and the kernel."""
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


# ------------------------------------------------------------------ the compiled tree, the helpers, packing

def test_the_official_compiler_builds_v7c_with_v7bs_tree():
    import ast, re
    from test_v7_bundle import TREE
    from test_v7b_bundle import compiled
    tree = compiled(V7C)
    assert tree == compiled(V7B)                                        # same stages, tools, models and sampling
    got = {m.group(1): ast.literal_eval(m.group(2)) for m in re.finditer(r"^\s*LlmAgent (\w+) model=\S+ tools=(\[.*\])$", "\n".join(tree), re.M)}
    assert got == TREE, got


def test_every_helper_installs_into_the_sandbox_tmp_and_every_prompt_helper_is_probed_on_kaggle(tmp_path):
    import json, subprocess, sys
    from test_v7_bundle import helpers_used, probe_keys
    scripts = V7C / "skills" / "swe-tools" / "scripts"
    helpers = {p.name for p in scripts.glob("*.py")} - {"install.py"}
    assert helpers == {"_ws.py", "check.py", "edit.py", "locate.py", "test.py", "view.py"}
    env = dict(os.environ, TMPDIR=str(tmp_path), TEST_TMPDIR=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, str(scripts / "install.py")], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert p.returncode == 0 and "helpers in" in p.stdout, p.stdout + p.stderr
    assert all((tmp_path / "swe" / h).read_bytes() == (scripts / h).read_bytes() for h in helpers)
    assert json.loads((tmp_path / "swe" / ".ledger.json").read_text()) == {"locate": 0, "view": 0, "edited": False,
                                                                         "repeat_key": None, "repeat_run": 0}
    used = helpers_used(V7C)
    assert used == helpers - {"_ws.py"} == helpers_used(V7B), used       # _ws.py is a module the probed helpers import
    assert used <= probe_keys(), used - probe_keys()


def test_the_kaggle_helper_check_passes_on_v7c(tmp_path):
    """make_eval_kernel.py --helper-check (HELPER_BODY, run as is in swegemma's SubprocessManager): every PROBES line,
    then view.py's exact repeat, which must still say ALREADY SHOWN (v4h6g's loop breaker; v7c keeps that line for the
    1st and 2nd repeat). Only the report path is moved off /kaggle/working."""
    import base64, importlib.util, pytest
    pytest.importorskip("swegemma.sandbox.subprocess")
    spec = importlib.util.spec_from_file_location("make_eval_kernel_v7c", ROOT / "scripts" / "make_eval_kernel.py")
    mk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mk)
    scripts = V7C / "skills" / "swe-tools" / "scripts"
    report = tmp_path / "helper_check.txt"
    body = mk.HELPER_BODY.replace("/kaggle/working/helper_check.txt", str(report))
    ns = {"HELPERS_B64": {p.name: base64.b64encode(p.read_bytes()).decode() for p in sorted(scripts.glob("*.py"))}}
    try:
        exec(compile(body, "HELPER_BODY", "exec"), ns)
    finally:
        if "m" in ns:
            ns["m"].cleanup_all()
    lines = report.read_text().splitlines()
    assert lines[-1] == "HELPER_CHECK PASS" and not [l for l in lines if l.startswith("FAIL")], lines
    assert any(l.startswith("ok   view.py repeat refused -> ALREADY SHOWN: pkg/mod.py lines 1-2") for l in lines), lines


def test_packs_small_and_complete(tmp_path):
    import subprocess, sys, zipfile
    z = tmp_path / "v7c.zip"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "pack_bundle.py"), str(V7C), str(z)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert z.stat().st_size < 100_000
    names = zipfile.ZipFile(z).namelist()
    assert sorted(names) == sorted(all_files(V7C)) and not any("__pycache__" in n or n.endswith(".pyc") for n in names)


# ------------------------------------------------------------------ the Kaggle eval kernel (v5b recipe, as v7's and v7b's)

KERNEL_DIR, KERNEL_SLUG = "g4-l4-v7c-p312", "g4-oracle-all"
TAKEN = {"g4-lora-test": "v7", "g4-eval-v2-smoke": "v7b", "g4-eval74-v4": "v5h2", "g4-eval74-v2": "v11b probe",
         "g4-l4-v4": "v5h2b", "g4-eval74-v3": "v6p", "g4-l4-v9-eog": "v6p-think"}
SLUG_LOG = ROOT / "eval" / "kaggle" / "oracle_all" / "g4-oracle-all.log"
FREE_BUT_313 = {"g4-l4-lora-probe": "g4-l4-lora-probe", "g4-l4-v4h": "g4-l4-v4h", "g4-l4-v4h-think": "g4-l4-v4h-think",
                "g4-l4-v4-wh28": "g4-l4-v4-wh28"}                     # slug -> eval/kaggle/<dir> holding its log


def test_the_kernel_slug_is_free_existing_and_was_made_under_the_312_image():
    """New slugs get the 3.13 image, where every cp312 wheel of the wheelhouse fails; 'original' pins the image a slug
    was made with. Every existing slug whose committed log shows a 3.12 GPU run is taken (TAKEN), and the four free
    ones that ran on GPU were made under 3.13 (their logs). g4-oracle-all exists (its committed log: the 2026-09-26
    oracle run on the Kaggle image, TOTAL 74 / 129), ran Python 3.12, and no queued bundle, kernel dir or script uses it
    (g4-rescore-fair, the other free 3.12 slug, is still named by scripts/go_race.sh). It was made as a CPU kernel; a
    GPU session under its 'original' pin is unproven here (the reverse switch is: g4-lora-test, made on GPU, ran the
    CPU helper check under 'original' on 3.12, docs/v4h/GATE.md), and the install cell stops with a message on 3.13."""
    import json, re
    assert KERNEL_SLUG not in TAKEN and not set(FREE_BUT_313) & set(TAKEN)
    log = SLUG_LOG.read_text()
    assert "python3.12/" in log and "python3.13" not in log and "TOTAL 74 / 129" in log
    for slug, d in FREE_BUT_313.items():
        other = (ROOT / "eval" / "kaggle" / d / (slug + ".log")).read_text()
        assert "python3.13" in other and "python3.12/" not in other, slug
    assert not [p for p in (ROOT / "scripts").rglob("*") if p.is_file() and p.suffix in (".py", ".sh") and KERNEL_SLUG in p.read_text(errors="ignore")]
    kernels = ROOT / "kernels"
    if kernels.is_dir():
        users = {p.parent.name for p in kernels.glob("*/kernel-metadata.json")
                 if json.loads(p.read_text()).get("id") == "carsonrodrigues/" + KERNEL_SLUG}
        assert users <= {KERNEL_SLUG, KERNEL_DIR}, users
    if (kernels / KERNEL_DIR).is_dir():                                 # the Mac that generates the kernels: the taken
        for slug in TAKEN:                                              # slugs are what its kernel dirs say
            assert any(json.loads(p.read_text()).get("id") == "carsonrodrigues/" + slug for p in kernels.glob("*/kernel-metadata.json")), slug
    assert re.search(r"\bv7\b", TAKEN["g4-lora-test"]) and TAKEN["g4-eval-v2-smoke"] == "v7b"


def test_eval_kernel_matches_the_recipe_and_ships_v7c(tmp_path):
    import base64, json, pytest, subprocess, sys
    kd = ROOT / "kernels" / KERNEL_DIR
    if not (kd / "kernel-metadata.json").exists():
        pytest.skip("kernels/ is gitignored: the kernel is generated on the Mac")
    meta = (kd / "kernel-metadata.json").read_text()
    for s in (f'"id": "carsonrodrigues/{KERNEL_SLUG}"', '"docker_image_pinning_type": "original"', '"enable_gpu": true',
              '"machine_shape": "NvidiaL4"'):
        assert s in meta, s
    nb = json.loads((kd / f"{KERNEL_SLUG}.ipynb").read_text())
    data = next(c["source"] for c in nb["cells"] if c["source"].startswith("FILES = "))
    files = json.loads(data[len("FILES = "):data.index("\nIDS = ")])
    assert {rel: base64.b64decode(b) for rel, b in files.items()} == {rel: (V7C / rel).read_bytes() for rel in all_files(V7C)}
    ids = json.loads(data[data.index("\nIDS = ") + 7:data.index("\nPATCHES = ")])
    assert ids == [l.strip() for l in (ROOT / "data" / "kaggle_valid_ids.txt").read_text().splitlines() if l.strip()] and len(ids) == 74
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_eval_kernel.py"), str(V7C), KERNEL_DIR,
                        "--ids", str(ROOT / "data" / "kaggle_valid_ids.txt"), "--pin", "original", "--kernel-id", KERNEL_SLUG],
                       cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    for f in ("kernel-metadata.json", KERNEL_SLUG + ".ipynb"):
        assert (tmp_path / "kernels" / KERNEL_DIR / f).read_bytes() == (kd / f).read_bytes(), f


def test_the_v7c_kernel_is_the_v7b_kernel_but_the_changed_files_and_the_slug():
    """Same recipe, task ids, budget and cells as v7b's queued kernel (g4-l4-v7b-p312 on g4-eval-v2-smoke), so a v7b vs
    v7c Kaggle read compares the bundles and nothing else."""
    import json, pytest
    a_dir, b_dir = ROOT / "kernels" / "g4-l4-v7b-p312", ROOT / "kernels" / KERNEL_DIR
    if not ((a_dir / "g4-eval-v2-smoke.ipynb").exists() and (b_dir / f"{KERNEL_SLUG}.ipynb").exists()):
        pytest.skip("kernels/ is gitignored: both kernels are generated on the Mac")
    a = [c["source"] for c in json.loads((a_dir / "g4-eval-v2-smoke.ipynb").read_text())["cells"]]
    b = [c["source"] for c in json.loads((b_dir / f"{KERNEL_SLUG}.ipynb").read_text())["cells"]]
    assert len(a) == len(b)
    for x, y in zip(a, b):
        if x.startswith("FILES = "):
            fa, fb = json.loads(x[8:x.index("\nIDS = ")]), json.loads(y[8:y.index("\nIDS = ")])
            assert {k for k in set(fa) | set(fb) if fa.get(k) != fb.get(k)} == CHANGED
            assert x[x.index("\nIDS = "):] == y[y.index("\nIDS = "):]
        else:
            assert x == y
    ma, mb = (json.loads((d / "kernel-metadata.json").read_text()) for d in (a_dir, b_dir))
    assert {k for k in set(ma) | set(mb) if ma.get(k) != mb.get(k)} == {"id", "title", "code_file"}
