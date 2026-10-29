"""tests/kernel_pins.py undoes only the listed builder changes: a pinned kernel rebuilt with them compares equal, and any other
change to a cell still fails the pin."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kernel_pins import LATER, as_pinned, pinned  # noqa: E402

THEN = "x = 1\n" + "\n".join(then for _, then in LATER) + "\nprint('done')\n"
NOW = "x = 1\n" + "\n".join(now for now, _ in LATER) + "\nprint('done')\n"


def write(path, src):
    path.write_text(json.dumps({"cells": [{"cell_type": "code", "source": src}], "metadata": {}}))
    return path


def test_the_listed_builder_changes_compare_equal(tmp_path):
    assert as_pinned(write(tmp_path / "new.ipynb", NOW)) == pinned(write(tmp_path / "old.ipynb", THEN))


def test_any_other_change_still_fails_the_pin(tmp_path):
    old = pinned(write(tmp_path / "old.ipynb", THEN))
    assert as_pinned(write(tmp_path / "a.ipynb", NOW.replace("x = 1", "x = 2"))) != old
    assert as_pinned(write(tmp_path / "b.ipynb", NOW + "y = 3\n")) != old


def test_metadata_is_compared_byte_for_byte(tmp_path):
    (tmp_path / "kernel-metadata.json").write_bytes(b'{"id": "a"}')
    assert as_pinned(tmp_path / "kernel-metadata.json") == pinned(tmp_path / "kernel-metadata.json") == b'{"id": "a"}'
