"""Version-aware values for the v10 suite (docs/v10/SPEC_v10_2.md section 7).

G4_BUNDLE points the v10 suite at a bundle; on v10.1 (submissions/v10, the default) every name here gives v10.1's
value or does nothing, so the suite runs on v10.1 unchanged. On v10.2 and later:
- VERSION / VERSION_RE: the bundle's helper version (install, status and VERSION lines print it).
- later_stage(swe): what a later stage does first in v10.2 (the fixer's and verifier's step 1 is status.py, and edit.py
  ends the locator phase too): the context meter leaves the locator phase, so the locator budget (the 14-call / t=90s
  close, 3 probes, 2 reproductions) does not apply. The v10.1 tests that simulate a later stage with SWE_FAKE_CLOCK
  past the locator call it before their first helper.
- V102: True on v10.2 and later, for the few assertions whose expected text changed by design (SPEC_v10_2 5.4-5.6).
"""
import json
import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
BUNDLE = ROOT / (os.environ.get("G4_BUNDLE") or "submissions/v10")


def _version(bundle=BUNDLE):
    p = pathlib.Path(bundle) / "skills" / "swe-tools" / "scripts" / "_swe_common.py"
    try:
        m = re.search(r'^VERSION = "(v[\d.]+)"', p.read_text(encoding="utf-8"), re.M)
    except OSError:
        m = None
    return m.group(1) if m else "v10.1"


def version_key(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))


VERSION = _version()
VERSION_RE = re.escape(VERSION)
V102 = version_key(VERSION) >= (10, 2)


def later_stage(swe):
    """v10.2+: record that a later stage started (the context meter's phase is past the locator), before any helper
    of the test runs in $SWE; a no-op on v10.1. Keeps an existing state's other fields."""
    if not V102:
        return
    swe = pathlib.Path(swe)
    swe.mkdir(parents=True, exist_ok=True)
    p = swe / "state.json"
    try:
        st = json.loads(p.read_text())
    except (OSError, ValueError):
        st = {}
    ctx = st.get("ctx") if isinstance(st.get("ctx"), dict) else {}
    if (ctx.get("phase") or "locator") == "locator":
        st["ctx"] = {"n": 0.0, "phase": "fixer", "tail": [["status", 0.0]]}
        p.write_text(json.dumps(st))
