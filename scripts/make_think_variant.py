"""A bundle copy whose ONLY change is the thinking setting in configs/sampling.yaml (docs/v4h/THINK_TIMING.md).

    python scripts/make_think_variant.py submissions/v4h eval/golden/arms/v4h_think_low --level LOW

Writes `thinking_config:\n  include_thoughts: true\n  thinking_level: LOW` in place of the bundle's thinking_config block.
The bridge in adk_submission (research/config_space.md 6): include_thoughts true + LOW/MEDIUM/HIGH -> vLLM gets
chat_template_kwargs.enable_thinking=true and reasoning_effort=<level>; NONE -> thinking off. Every other file stays
byte-identical, and a test pins that.
"""
import argparse
import os
import re
import shutil

LEVELS = ("NONE", "MINIMAL", "LOW", "MEDIUM", "HIGH")
BLOCK = re.compile(r"thinking_config:\n(?:[ \t]+\S.*\n?)+")


def build(src, out, level, cap=None):
    """cap: optional max_time_minutes for eval_config.yaml (the 12 h insurance when thinking slows every step)."""
    if level not in LEVELS:
        raise SystemExit(f"thinking_level must be one of {LEVELS}; an unknown level silently leaves thinking ON")
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(src, out, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "._*", ".DS_Store"))
    if cap is not None:
        e = os.path.join(out, "eval_config.yaml")
        et, n = re.subn(r"(max_time_minutes:\s*)[0-9.]+", r"\g<1>%s" % cap, open(e).read(), count=1)
        if n != 1:
            raise SystemExit("eval_config.yaml has no max_time_minutes line")
        with open(e, "w") as f:
            f.write(et)
    p = os.path.join(out, "configs", "sampling.yaml")
    text = open(p).read()
    new = "thinking_config:\n  include_thoughts: %s\n  thinking_level: %s\n" % ("false" if level == "NONE" else "true", level)
    text2, n = BLOCK.subn(new, text, count=1)
    if n == 0:
        text2 = text.rstrip("\n") + "\n" + new
    with open(p, "w") as f:
        f.write(text2)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out"); ap.add_argument("--level", default="LOW")
    ap.add_argument("--cap", default=None, help="max_time_minutes override, e.g. 4.0")
    a = ap.parse_args()
    p = build(a.src, a.out, a.level.upper(), a.cap)
    print(open(p).read())
    if a.cap is not None:
        print(open(os.path.join(a.out, "eval_config.yaml")).read())


if __name__ == "__main__":
    main()
