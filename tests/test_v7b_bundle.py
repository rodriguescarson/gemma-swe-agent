"""v7b = v7 + the two fixes pre-registered in docs/GAPS_2026-10-06.md (last section, "v7 A6000 screen read"), built in a
new directory so the v7 run on the GPU box is never touched. Strict test-first: step 1, v7b was an exact copy (cp -a,
byte-identical with the same modes: commit "v7b step 1"); every later step names the files it may change.

  fix 1  the read-cap refusal stops being a loop trap: view.py + _ws.py (tests/test_v7b_helpers.py, _sandbox, _counters)
  fix 2  submit_patch is a tool, commands never start with run_command: one new line in fixer.md and verifier.md
         (tests/test_v7b_prompts.py)"""
import filecmp, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kernel_pins import as_pinned, pinned  # noqa: E402
ROOT = Path(__file__).resolve().parent.parent
SUB = ROOT / "submissions"
V7, V7B = SUB / "v7", SUB / "v7b"
FIX1 = {"skills/swe-tools/scripts/view.py", "skills/swe-tools/scripts/_ws.py"}
FIX2 = {"prompts/fixer.md", "prompts/verifier.md", "prompts/locator.md"}   # locator added 2026-10-08: 5 of the 6 wrapper commands were its `run_command "git grep ..."`
CHANGED = FIX1 | FIX2


def all_files(d):
    """Every file under d, hidden ones included (a stray .DS_Store or __pycache__ is a difference too)."""
    return {str(p.relative_to(d)) for p in d.rglob("*") if p.is_file()}


def changed(a, b):
    return {rel for rel in all_files(a) & all_files(b) if not filecmp.cmp(a / rel, b / rel, shallow=False)}


def test_v7b_differs_from_v7_only_in_the_listed_files():
    assert all_files(V7B) == all_files(V7), all_files(V7B) ^ all_files(V7)
    assert changed(V7, V7B) == CHANGED, changed(V7, V7B) ^ CHANGED
    for rel in sorted(all_files(V7)):
        assert os.stat(V7 / rel).st_mode == os.stat(V7B / rel).st_mode, rel


# ------------------------------------------------------------------ the compiled tree, the helpers, packing, the budget

def compiled(bundle):
    import subprocess, sys
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(bundle)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-800:] + r.stderr[-1500:]
    return [l for l in r.stdout.splitlines() if l.lstrip().startswith(("SequentialAgent ", "LlmAgent ", "gen: "))]


def test_the_official_compiler_builds_v7b_with_v7s_tree():
    from test_v7_bundle import TREE
    import ast, re
    tree = compiled(V7B)
    assert tree == compiled(V7)                                         # same stages, tools, models and sampling
    got = {m.group(1): ast.literal_eval(m.group(2)) for m in re.finditer(r"^\s*LlmAgent (\w+) model=\S+ tools=(\[.*\])$", "\n".join(tree), re.M)}
    assert got == TREE, got


def test_every_helper_installs_into_the_sandbox_tmp_and_every_prompt_helper_is_probed_on_kaggle(tmp_path):
    import json, subprocess, sys
    from test_v7_bundle import helpers_used, probe_keys
    scripts = V7B / "skills" / "swe-tools" / "scripts"
    helpers = {p.name for p in scripts.glob("*.py")} - {"install.py"}
    assert helpers == {"_ws.py", "check.py", "edit.py", "locate.py", "test.py", "view.py"}
    env = dict(os.environ, TMPDIR=str(tmp_path), TEST_TMPDIR=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, str(scripts / "install.py")], capture_output=True, text=True, env=env, cwd=tmp_path)
    assert p.returncode == 0 and "helpers in" in p.stdout, p.stdout + p.stderr
    assert all((tmp_path / "swe" / h).read_bytes() == (scripts / h).read_bytes() for h in helpers)
    assert json.loads((tmp_path / "swe" / ".ledger.json").read_text()) == {"locate": 0, "view": 0, "edited": False, "refused_run": 0}
    used = helpers_used(V7B)
    assert used == helpers - {"_ws.py"} == helpers_used(V7), used       # _ws.py is a module the probed helpers import
    assert used <= probe_keys(), used - probe_keys()


def test_packs_small_and_complete(tmp_path):
    import subprocess, sys, zipfile
    z = tmp_path / "v7b.zip"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "pack_bundle.py"), str(V7B), str(z)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert z.stat().st_size < 100_000
    names = zipfile.ZipFile(z).namelist()
    assert sorted(names) == sorted(all_files(V7B)) and not any("__pycache__" in n or n.endswith(".pyc") for n in names)


def test_the_call_arithmetic_and_the_caps_are_v7s():
    import re, yaml
    from test_v7b_helpers import ws_attrs
    locate_cap, view_cap = ws_attrs("LOCATE_CAP", "VIEW_CAP")
    comment = "\n".join(l for l in (V7B / "sub_agents" / "locator.yaml").read_text().splitlines() if l.startswith("#"))
    assert f"locate.py <= {locate_cap}" in comment and f"view.py <= {view_cap}" in comment
    ev = yaml.safe_load((V7B / "eval_config.yaml").read_text())["evaluation"]
    assert ev["max_tool_calls"] == 70 and ev["max_time_minutes"] == 5


# ------------------------------------------------------------------ the Kaggle eval kernel (v5b recipe, as v7's)

KERNEL_DIR, KERNEL_SLUG = "g4-l4-v7b-p312", "g4-oracle-all"   # swapped 2026-10-08: the proven GPU slug went to v7c, the Saturday candidate
TAKEN = {"g4-lora-test": "v7", "g4-eval74-v4": "v5h2", "g4-l4-v4": "v5h2b", "g4-eval74-v3": "v6p",
         "g4-l4-v9-eog": "v6p-think", "g4-eval74-v2": "v11b probe (queued, tests/test_v7_bundle.py)", "g4-eval-v2-smoke": "v7c"}
SLUG_LOG = ROOT / "eval" / "kaggle" / "oracle_all" / "g4-oracle-all.log"


def test_the_kernel_slug_is_free_and_was_made_under_the_312_image():
    """New slugs get the 3.13 image, where every cp312 wheel of the wheelhouse fails; 'original' pins the image a slug was
    made with. g4-eval-v2-smoke made the eval-v2 smoke run (committed log): Python 3.12, vLLM on 4 L4s, and no queued
    bundle uses it (it is not g4-l4-lora-probe / g4-l4-v4h / g4-l4-v4h-think / g4-l4-v4-wh28, whose logs show 3.13)."""
    import re
    assert KERNEL_SLUG not in TAKEN
    log = SLUG_LOG.read_text()
    assert "python3.12/" in log and "python3.13" not in log and "TOTAL 74 / 129" in log   # the 2026-09-26 oracle run (CPU)
    kernels = ROOT / "kernels"
    if kernels.is_dir():
        import json
        users = {p.parent.name for p in kernels.glob("*/kernel-metadata.json")
                 if json.loads(p.read_text()).get("id") == "carsonrodrigues/" + KERNEL_SLUG}
        assert users <= {KERNEL_SLUG, KERNEL_DIR}, users


def test_eval_kernel_matches_the_recipe_and_ships_v7b(tmp_path):
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
    assert {rel: base64.b64decode(b) for rel, b in files.items()} == {rel: (V7B / rel).read_bytes() for rel in all_files(V7B)}
    ids = json.loads(data[data.index("\nIDS = ") + 7:data.index("\nPATCHES = ")])
    assert ids == [l.strip() for l in (ROOT / "data" / "kaggle_valid_ids.txt").read_text().splitlines() if l.strip()] and len(ids) == 74
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_eval_kernel.py"), str(V7B), KERNEL_DIR,
                        "--ids", str(ROOT / "data" / "kaggle_valid_ids.txt"), "--pin", "original", "--kernel-id", KERNEL_SLUG],
                       cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    for f in ("kernel-metadata.json", KERNEL_SLUG + ".ipynb"):
        assert as_pinned(tmp_path / "kernels" / KERNEL_DIR / f) == pinned(kd / f), f   # builder changes since: tests/kernel_pins.py


def test_the_v7b_kernel_is_the_queued_v7_kernel_but_the_four_files_and_the_slug():
    """Same recipe, task ids, budget and cells as v7's queued kernel (g4-l4-v7-p312 on g4-lora-test), so a v7 vs v7b
    Kaggle read compares the bundles and nothing else."""
    import json, pytest
    a_dir, b_dir = ROOT / "kernels" / "g4-l4-v7-p312", ROOT / "kernels" / KERNEL_DIR
    if not ((a_dir / "g4-lora-test.ipynb").exists() and (b_dir / f"{KERNEL_SLUG}.ipynb").exists()):
        pytest.skip("kernels/ is gitignored: both kernels are generated on the Mac")
    a = [c["source"] for c in json.loads((a_dir / "g4-lora-test.ipynb").read_text())["cells"]]
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
