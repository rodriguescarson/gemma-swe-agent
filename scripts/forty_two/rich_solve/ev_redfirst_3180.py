"""rich_3180 at the base commit: which simple wrap inputs show the issue's symptom (characters lost or reordered), i.e. how
easily a fail-first check finds a red example. Inputs: an ASCII prefix of 0-3 characters followed by one of b1024's CJK
words, wrapped by rich's own Text.wrap at widths 2-8; plus the probes the box runs actually ran. Run from the base snapshot:

    cd $WT/rich_3180 && PYTHONPATH=. $VENV/bin/python <repo>/scripts/forty_two/rich_solve/ev_redfirst_3180.py"""
from rich.cells import chop_cells
from rich.console import Console
from rich.text import Text

console = Console(width=80)


def lost(text, width):
    lines = [l.plain for l in Text(text).wrap(console, width)]
    return "".join(lines).replace(" ", "") != text.replace(" ", ""), lines


probes = [("abc こんにちは", 6), ("こんにちは ", 4), ("こんにちは", 1), ("ありがとう", 3), ("わさび", 2)]
print("probes the box runs ran (p4_b1024 calls 9-13, p4_v7 locator):")
for t, w in probes:
    bad, lines = lost(t, w)
    print(f"   {t!r:18} width {w}: {lines}  {'RED' if bad else 'green'}")
red = total = 0
examples = []
for prefix in ("", "a", "ab", "abc"):
    for word in ("こんにちは", "ありがとう", "わさびわさび"):
        for w in range(2, 9):
            total += 1
            bad, lines = lost(prefix + word, w)
            if bad:
                red += 1
                if len(examples) < 4:
                    examples.append((prefix + word, w, lines))
            elif prefix == "":
                pass
print(f"ASCII prefix 0-3 + CJK word, widths 2-8: {red} of {total} inputs show lost/reordered characters")
for t, w, lines in examples:
    print(f"   e.g. {t!r} width {w}: {lines}")
pure = sum(lost(word, w)[0] for word in ("こんにちは", "ありがとう", "わさびわさび") for w in range(2, 9))
print(f"pure CJK words (no prefix), widths 2-8: {pure} of 21 red")
print("chop_cells('abcdefghijk', 3) =", chop_cells("abcdefghijk", 3), "(the reversal the docstring announces)")
