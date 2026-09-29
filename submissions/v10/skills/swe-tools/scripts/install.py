import os, sys
sys.dont_write_bytecode = True
_HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("SWE_PATH0", sys.path[0] if sys.path else "")
_STD = tuple({os.path.realpath(p) for p in (sys.base_prefix, sys.base_exec_prefix)})
sys.path[:] = [_HERE] + [p for p in sys.path if p and os.path.realpath(p).startswith(_STD) and "-packages" not in p]
for _n in [n for n, m in list(sys.modules.items()) if n.split(".")[0] in getattr(sys, "stdlib_module_names", ())
           and getattr(m, "__file__", None) and not os.path.realpath(m.__file__).startswith(_STD)]:
    del sys.modules[_n]
import _swe_common as C

# Install the swe-tools helpers where `python3 /tmp/swe/NAME.py` resolves in this sandbox. Idempotent; never touches
# the repository. Run as run_skill_script(file_path="install.py", skill_name="swe-tools") or python3 /tmp/swe/install.py.
# Any argument is ignored: installing must never fail on a malformed call.

NAME = "install"
USAGE = "python3 /tmp/swe/install.py"
FLAGS = {}


def main():
    res = C.install_all()
    try:
        C.state_load()                       # resets a stale state left by another task in the same dir
    except Exception:
        pass
    try:
        C.arm_submit_guard()                 # v10.1: the first tool call, before any agent write (SPEC 4.2)
    except Exception:
        pass
    helpers = sorted(f[:-3] for f in os.listdir(_HERE) if f.endswith(".py") and not f.startswith(("_", ".")))
    ok = [r for r in res if r[3] is None]
    if not ok or res[0][3] is not None:
        why = res[0][3] if res and res[0][3] else "no install target"
        first = ("INSTALL FAILED: %s. Run a helper directly instead: run_skill_script(file_path=\"NAME.py\", "
                 "skill_name=\"swe-tools\")." % C._short(why, 160))
    else:
        first = ("swe-tools %s ready in %s (%d helpers). Next: python3 %s/locate.py \"key words\""
                 % (C.VERSION, C.DISPLAY_SWE, len(helpers), C.DISPLAY_SWE))
        C.journal({"h": NAME, "msg": "install: %d helpers (%d copied)" % (len(helpers), sum(r[1] for r in ok))})
    C.emit(NAME, first)


if __name__ == "__main__":
    C.safe_main(NAME, main)
