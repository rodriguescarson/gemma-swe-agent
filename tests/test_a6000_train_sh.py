"""scripts/a6000/train.sh: the training recipe scales with the collection (GAPS 2026-10-11 "stitch gate re-registered"): a single-agent
collector gives ONE sequence per solved trajectory, so the stitch gate is 40 sequences (not 500) and a small collection trains more
epochs with a smaller accumulation (about 180 optimizer steps), the held-out stop rule guarding overfitting. Written before the change."""
import pathlib, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "a6000" / "train.sh"


def recipe(n):
    r = subprocess.run(["bash", str(SH), "recipe", str(n)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_small_collections_train_more_epochs_with_small_accumulation():
    assert recipe(60) == "--grad-accum 2 --epochs 6 --eval-every 10 --save-every 10"
    assert recipe(100) == "--grad-accum 2 --epochs 4 --eval-every 10 --save-every 10"
    assert recipe(150) == "--grad-accum 2 --epochs 3 --eval-every 10 --save-every 10"
    assert recipe(199) == "--grad-accum 2 --epochs 2 --eval-every 10 --save-every 10"
    assert recipe(200) == "--grad-accum 8 --epochs 1 --eval-every 40 --save-every 40"   # the original recipe
    assert recipe(0).startswith("--grad-accum 2 --epochs 6")


def test_stitch_gate_is_40_sequences_and_the_full_run_applies_the_recipe_before_user_args():
    s = SH.read_text()
    assert "--min-rows 40 " in s and "--min-thought-share 0.8" in s
    i, j = s.index('recipe "$N"'), s.index('"$@" >> "$LOG"')
    assert 0 < i < j                                                     # the recipe's args come before "$@", so explicit args win


def test_train_env_works_without_uv():
    """2026-10-12: the box had neither uv nor `pip --user`; the env script must fall back to python3 -m venv + the venv's pip."""
    src = (ROOT / "scripts" / "a6000" / "train_env.sh").read_text()
    assert "pip install -q --user" not in src          # the old fallback command
    assert "python3 -m venv" in src and 'pipi()' in src and '"$VENV/bin/python" -m pip install' in src
    assert subprocess.run(["bash", "-n", str(ROOT / "scripts" / "a6000" / "train_env.sh")], capture_output=True).returncode == 0
