"""make_t0.py SRC DST: the same bundle with thinking turned off explicitly (`thinking_budget: 0`), for the scorer since 2026-10-09.

Why (docs/a6000/V7C_FAILURE_ANALYSIS.md, section 8): the Kaggle wheelhouse of 2026-10-09 14:43 UTC ships adk_submission 0.2.13,
whose generation resolver (resolvers/generation.py, apply_thinking_config_to_model) turns thinking ON whenever the merged
thinking_config carries a positive thinking_budget, before it looks at include_thoughts. The organisers' generation
constraints (swegemma.config.build_submission_limits, unchanged since 0.2.7) merge a default `thinking_budget: 4096` into
every bundle, so every bundle that turned thinking off the old way (`include_thoughts: false`, which the 0.2.11/0.2.12
resolver honoured) now runs with thinking on and a 4,096-token budget per call: enable_thinking True, thinking_token_budget
4096 (verified by compiling v7d on the new stack). The same release lowered the schema's thinking_budget floor from 1 to 0
("0 disables thinking"), and 0 is inside the constraints' NumericRange(0, 32768): with `thinking_budget: 0` the resolver
sets enable_thinking False and drops the budget. `thinking_level: none` also works but is not a google.genai ThinkingLevel
value (a warning today, a refusal whenever genai validates it), so the budget is the switch.

What changes: every configs/*.yaml of SRC that has a thinking_config gets one line, `  thinking_budget: 0`, right after
`thinking_config:`; nothing else (byte-identical otherwise, same modes). The copy refuses a bundle with no thinking_config
yaml, or one that already sets thinking_budget or thinking_level, so an intent is never silently overridden.

Stacks: the new compiler accepts 0; the old one (adk_submission 0.2.11, the A6000 box's venv on 2026-10-10) has
thinking_budget >= 1 in its schema and refuses the copy, so a -t0 bundle runs only where the venv carries the new wheels.
Behaviour there is unchanged: thinking was already off under the old resolver, so an A6000 screen of SRC stands for DST.

    python scripts/make_t0.py submissions/v7d submissions/v7d-t0"""
import os
import re
import shutil
import sys
from pathlib import Path

LINE = "  thinking_budget: 0\n"
KEY = re.compile(r"^thinking_config:\s*$", re.M)


def thinking_yamls(bundle):
    """The configs/*.yaml files of a bundle that carry a top-level `thinking_config:` block."""
    cfg = Path(bundle) / "configs"
    return sorted(p for p in cfg.glob("*.yaml") if KEY.search(p.read_text(encoding="utf-8"))) if cfg.is_dir() else []


def check_source(bundle):
    ys = thinking_yamls(bundle)
    if not ys:
        raise SystemExit("REFUSED: %s has no configs/*.yaml with a thinking_config block; add one before making a -t0 copy" % bundle)
    for y in ys:
        text = y.read_text(encoding="utf-8")
        if re.search(r"^\s+thinking_budget\s*:", text, re.M) or re.search(r"^\s+thinking_level\s*:", text, re.M):
            raise SystemExit("REFUSED: %s already sets thinking_budget or thinking_level; make the change by hand" % y)
        if KEY.search(text) is None or len(KEY.findall(text)) != 1:
            raise SystemExit("REFUSED: %s has no single top-level thinking_config block" % y)
    return ys


def make_t0(src, dst):
    src, dst = Path(src), Path(dst)
    if dst.exists():
        raise SystemExit("REFUSED: %s exists; remove it first" % dst)
    ys = check_source(src)
    shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
    changed = []
    for y in ys:
        target = dst / y.relative_to(src)
        text = target.read_text(encoding="utf-8")
        new = KEY.sub(lambda m: m.group(0) + "\n" + LINE.rstrip("\n"), text, count=1)
        assert new != text
        target.write_text(new, encoding="utf-8")
        shutil.copystat(y, target)
        changed.append(str(target.relative_to(dst)))
    return changed


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__.splitlines()[0])
    out = make_t0(sys.argv[1], sys.argv[2])
    print("made %s from %s; thinking_budget: 0 added to %s" % (sys.argv[2], sys.argv[1], ", ".join(out)))
