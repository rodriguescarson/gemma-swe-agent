"""data/HARNESS_README.md (the live 13 Oct copy) against what scripts/make_eval_kernel.py embeds in the kernel cell.

Why: the 25 Sep copy said gpu_memory_utilization 0.80 and compaction_interval 5 while the kernel already ran 0.90 and 15;
nobody noticed until the README was refreshed on 29 Oct (docs/HARNESS_README_DIFF_2026-10-29.md). Refreshing
data/HARNESS_README.md again, or editing the kernel, now fails here instead of drifting silently.

Everything is read as text: the README bullets "`key = value`" (thousands separators stripped) and the kernel source. The
kernel is not imported or changed. Compaction is what the kernel cell receives: the keyword values of
EventsCompactionConfig(...) in the CELL_RUN template, resolved through the @PLACEHOLDER@ to COMPACTION[...] bindings in
build_cells (or taken literally if the template ever holds numbers). The 25 Sep copy kept at
data/HARNESS_README_2026-09-25.md is the control: the same parser must see it disagree with the kernel.
"""
import ast, hashlib, pathlib, re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = ROOT / "data" / "HARNESS_README.md"
README_0925 = ROOT / "data" / "HARNESS_README_2026-09-25.md"
KERNEL = ROOT / "scripts" / "make_eval_kernel.py"

COMPACTION_KEYS = ("compaction_interval", "overlap_size", "token_threshold", "event_retention_size")
SHA256_0925 = "3d6e57a13234cb4e783ba24eaab486459af76e0923ea4c6607cd41cc8961bbbb"     # git show e0e924e6:data/HARNESS_README.md


def readme_value(text, key):
    """The one number the README gives for `key`, read from its "`key = value`" bullet ("14,336" is 14336).
    Fails if the bullet is missing or the README states two different values."""
    found = re.findall(r"`%s = ([0-9][0-9,]*(?:\.[0-9]+)?)`" % re.escape(key), text)
    assert found, "no '`%s = <number>`' bullet in the README text: the phrasing changed, update readme_value()" % key
    values = {float(v.replace(",", "")) for v in found}
    assert len(values) == 1, "README gives %s more than one value: %s" % (key, sorted(values))
    return values.pop()


def kernel_gpu_memory_utilization(src):
    found = re.findall(r"\bgpu_memory_utilization\s*=\s*([0-9]+(?:\.[0-9]+)?)", src)
    assert found, "make_eval_kernel.py no longer sets gpu_memory_utilization as a literal"
    values = {float(v) for v in found}
    assert len(values) == 1, "kernel cells disagree on gpu_memory_utilization: %s" % sorted(values)
    return values.pop()


def _kernel_compaction_constant(src):
    """COMPACTION = dict(...) at module level, as numbers."""
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "COMPACTION" for t in node.targets):
            assert isinstance(node.value, ast.Call) and node.value.func.id == "dict", "COMPACTION is no longer dict(...)"
            return {kw.arg: float(ast.literal_eval(kw.value)) for kw in node.value.keywords}
    raise AssertionError("no module-level COMPACTION in make_eval_kernel.py")


def kernel_compaction_embedded(src):
    """The four values the kernel cell receives in EventsCompactionConfig(...)."""
    call = re.findall(r"\bEventsCompactionConfig\(([^()]*)\)", src)
    assert len(call) == 1, "expected one EventsCompactionConfig(...) call in the kernel template, found %d" % len(call)
    args = dict(re.findall(r"(\w+)=([^,\s]+)", call[0]))
    assert set(args) == set(COMPACTION_KEYS), set(args) ^ set(COMPACTION_KEYS)
    const = _kernel_compaction_constant(src)
    bound = dict(re.findall(r'\("(@\w+@)",\s*COMPACTION\["(\w+)"\]\)', src))      # placeholder -> COMPACTION key
    out = {}
    for key, token in args.items():
        if re.fullmatch(r"[0-9]+", token):
            out[key] = float(token)                                              # a literal inside the template
        else:
            assert token in bound, "placeholder %s in the kernel template is not bound to COMPACTION in build_cells" % token
            out[key] = const[bound[token]]
    return out


@pytest.fixture(scope="module")
def kernel_src():
    return KERNEL.read_text()


@pytest.fixture(scope="module")
def readme_text():
    return README.read_text()


def test_gpu_memory_utilization_matches_the_kernel(readme_text, kernel_src):
    assert readme_value(readme_text, "gpu_memory_utilization") == kernel_gpu_memory_utilization(kernel_src)


@pytest.mark.parametrize("key", COMPACTION_KEYS)
def test_compaction_matches_what_the_kernel_embeds(key, readme_text, kernel_src):
    assert readme_value(readme_text, key) == kernel_compaction_embedded(kernel_src)[key]


def test_kernel_compaction_constant_is_what_the_cell_embeds(kernel_src):
    """COMPACTION (also imported by tests and scripts/a6000/run_eval.py) must be the dict the cell is filled from."""
    assert kernel_compaction_embedded(kernel_src) == _kernel_compaction_constant(kernel_src)


def test_the_25_sep_copy_is_kept_byte_for_byte():
    """Line-number citations dated before 29 Oct 2026 point into this file (docs/HARNESS_README_DIFF_2026-10-29.md)."""
    assert hashlib.sha256(README_0925.read_bytes()).hexdigest() == SHA256_0925


def test_the_check_sees_the_25_sep_copy_disagree(kernel_src):
    """Control: the stale copy reads 0.80 and 5 (and the same 2 / 14,336 / 5), so the comparison above is live."""
    old = README_0925.read_text()
    assert readme_value(old, "gpu_memory_utilization") == 0.80 != kernel_gpu_memory_utilization(kernel_src)
    embedded = kernel_compaction_embedded(kernel_src)
    assert readme_value(old, "compaction_interval") == 5 != embedded["compaction_interval"]
    for key in ("overlap_size", "token_threshold", "event_retention_size"):
        assert readme_value(old, key) == embedded[key]


def test_readme_value_fails_loudly_on_a_missing_or_conflicting_bullet():
    with pytest.raises(AssertionError, match="phrasing changed"):
        readme_value("compaction_interval is fifteen", "compaction_interval")
    with pytest.raises(AssertionError, match="more than one value"):
        readme_value("`overlap_size = 2` and later `overlap_size = 3`", "overlap_size")
    assert readme_value("`token_threshold = 14,336`", "token_threshold") == 14336
