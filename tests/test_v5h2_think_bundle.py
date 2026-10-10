"""v5h2-think = v5h2 with thinking ON (docs/GAPS_2026-10-06.md, CORRECTION 2026-10-10): the forum's 129-task ablation (thread
746250) has thinking off at 23/129 and thinking on with a 4,096 budget and thought summaries at 48-51/129; every bundle of ours
since 09-25 ran it off. One change: configs/sampling.yaml gets include_thoughts: true, thinking_budget: 4096, and
max_output_tokens 8192 so the 4,096 reasoning tokens leave room for the reply (they count against max_tokens). Everything else
is byte-identical to v5h2, the best bundle measured on the real scorer stack on 2026-10-10 (31/74 thinking off).
The compile check needs the 2026-10-09 wheels (adk_submission 0.2.13) in the venv. Written before the kernel was built."""
import filecmp, os, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "tests"))
import swe_compat  # noqa: E402

SRC, DST = ROOT / "submissions" / "v5h2", ROOT / "submissions" / "v5h2-think"
KERNEL_DIR, KERNEL_SLUG = "g4-l4-v5h2-think-p312", "g4-eval74-v4"
NEW_STACK = not swe_compat.stack()["old_helpers"]


def all_files(d):
    return {str(p.relative_to(d)) for p in Path(d).rglob("*") if p.is_file()}


def test_differs_from_v5h2_only_in_the_sampling_yaml():
    assert all_files(DST) == all_files(SRC)
    for rel in sorted(all_files(SRC)):
        same = filecmp.cmp(SRC / rel, DST / rel, shallow=False)
        assert same == (rel != "configs/sampling.yaml"), rel
        assert os.stat(SRC / rel).st_mode == os.stat(DST / rel).st_mode, rel
    text = (DST / "configs" / "sampling.yaml").read_text()
    assert text == ("temperature: 0.2\ntop_p: 0.95\ntop_k: 64\nmax_output_tokens: 8192\nseed: 42\n"
                    "thinking_config:\n  include_thoughts: true\n  thinking_budget: 4096\n"), text


@pytest.mark.skipif(not NEW_STACK, reason="needs adk_submission 0.2.13 in the venv")
def test_every_stage_is_sent_thinking_on_with_the_budget_and_the_source_is_not():
    from test_make_t0 import thinking_of
    on, off = thinking_of(DST), thinking_of(SRC)
    assert set(on) == {"setup", "locator", "fixer", "verifier"}
    assert all(v == (True, 4096, None) for v in on.values()), on
    assert set(off) == set(on)                                           # the source, on this stack, also thinks (the merged default)...


@pytest.mark.skipif(not NEW_STACK, reason="needs adk_submission 0.2.13 in the venv")
def test_thought_summaries_are_carried_between_calls():
    """include_thoughts: true -> the compiled LiteLlm keeps thoughts in the chat template (the 0.2.13 meaning of the flag;
    Ayush's ablation: summaries hidden 35/129 vs shown 51/129)."""
    from unittest.mock import MagicMock
    from adk_submission import compile_submission, discover_adapters
    from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS, build_submission_limits
    from swegemma.tools import create_tools
    limits, gen = build_submission_limits()
    root = compile_submission(submission_dir=str(DST), adapter_manifest=discover_adapters(str(DST), ALLOWED_ADAPTER_EXTENSIONS),
                              tool_registry=create_tools(MagicMock()), model_registry=swe_compat.compile_only_model_registry(swe_compat.declared_model(str(DST))),
                              limits=limits, generation_constraints=gen)
    flags = {a.name: a.model.__dict__.get("_adk_include_thoughts") for a in root.sub_agents}
    assert flags == {"setup": True, "locator": True, "fixer": True, "verifier": True}, flags


def test_validator_and_output_room():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), str(DST)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "OK model=gemma-4-31b-it-qat-w4a16-ct" in r.stdout, r.stdout[-500:] + r.stderr[-1500:]
    assert r.stdout.count("'max_output_tokens': 8192") == 4 and "'thinking_budget': 4096" in r.stdout
    assert 32768 - 14336 - 8192 >= 2048                                  # the compaction headroom the harness needs (thread 747791)


def test_eval_kernel_ships_v5h2_think_on_the_proven_slug(tmp_path):
    import base64, json
    kd = ROOT / "kernels" / KERNEL_DIR
    if not (kd / "kernel-metadata.json").exists():
        pytest.skip("kernels/ is gitignored: generated on the Mac")
    meta = json.loads((kd / "kernel-metadata.json").read_text())
    assert meta["id"] == "carsonrodrigues/" + KERNEL_SLUG and meta["enable_gpu"] is True and meta["docker_image_pinning_type"] == "original"
    nb = json.loads((kd / f"{KERNEL_SLUG}.ipynb").read_text())
    data = next(c["source"] for c in nb["cells"] if c["source"].startswith("FILES = "))
    files = json.loads(data[len("FILES = "):data.index("\nIDS = ")])
    assert {k: base64.b64decode(v) for k, v in files.items()} == {rel: (DST / rel).read_bytes() for rel in all_files(DST)}
    ids = json.loads(data[data.index("\nIDS = ") + 7:data.index("\nPATCHES = ")])
    assert len(ids) == 74
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_eval_kernel.py"), str(DST), KERNEL_DIR, "--ids", str(ROOT / "data" / "kaggle_valid_ids.txt"),
                        "--pin", "original", "--kernel-id", KERNEL_SLUG], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
    for f in ("kernel-metadata.json", KERNEL_SLUG + ".ipynb"):
        assert (tmp_path / "kernels" / KERNEL_DIR / f).read_bytes() == (kd / f).read_bytes(), f
