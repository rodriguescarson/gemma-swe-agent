"""Write the two G1 Kaggle kernels (GAPS 'G1 amendment 2'): thin notebooks that unpack the code from the private dataset
and run aws/kaggle_g1/g1_kaggle.py.

    python aws/kaggle_g1/make_kernels.py        # -> kernels/g1_gold/ (CPU) and kernels/g1_devstral/ (4x L4)

Push each with scripts/kaggle_push_wait.sh <dir> (KAGGLE_BIN=.venv/bin/kaggle, the 2.x CLI: only its --accelerator
picks the 4x L4 machine); output lands in eval/kaggle/<dir>/. Both kernels are private; internet is on (pip, Hugging
Face) for the CPU gold kernel; the 4x L4 kernel is offline (see metadata()). Both read carsonrodrigues/g4-g1-harness
(aws/kaggle_g1/stage_dataset.py) and attach the competition's data (for /wheels only). Neither is a competition submission.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASET = "carsonrodrigues/g4-g1-harness"
KERNELS = {   # dir under kernels/ -> (kernel id, mode, gpu)
    "g1_gold": ("g4-g1-gold", "gold", False),
    "g1_devstral": ("g4-g1-devstral", "teacher", True),
}

CELL = r'''# G1 teacher pilot ({mode}): docs/GAPS_2026-10-06.md 'G1 amendment 2'; the work is in aws/kaggle_g1/g1_kaggle.py
import base64, glob, os, shutil, subprocess, sys, time
os.environ["G1_T0"] = str(time.time())
dst = "/root/g4"; os.makedirs(dst, exist_ok=True)
src = (sorted(glob.glob("/kaggle/input/**/g1_code.tgz", recursive=True)) + sorted(glob.glob("/kaggle/input/**/g1_code", recursive=True)))
if src and os.path.isfile(src[0]):
    subprocess.run(["tar", "xzf", src[0], "-C", dst], check=True)
else:   # Kaggle unpacked the archive: copy the tree that holds scripts/ and harness/
    roots = src or [os.path.dirname(os.path.dirname(p)) for p in sorted(glob.glob("/kaggle/input/**/scripts/or_proxy.py", recursive=True))]
    assert roots, ("no g1_code under /kaggle/input", sorted(glob.glob("/kaggle/input/*/*"))[:20])
    shutil.copytree(roots[0], dst, dirs_exist_ok=True)
# the driver and its strip proxy travel inside this notebook, so a fix needs a kernel push, not a dataset upload
os.makedirs(dst + "/aws/kaggle_g1", exist_ok=True)
for _name, _b64 in {files_b64}.items():
    open(dst + "/aws/kaggle_g1/" + _name, "wb").write(base64.b64decode(_b64))
r = subprocess.run([sys.executable, dst + "/aws/kaggle_g1/g1_kaggle.py", "{mode}"])
print("driver exit", r.returncode, open("/kaggle/working/status.json").read() if os.path.exists("/kaggle/working/status.json") else "no status.json")
'''


EMBEDDED = ("g1_kaggle.py", "strip_proxy.py")


def notebook(mode):
    import base64
    here = Path(__file__).resolve().parent
    files = {n: base64.b64encode((here / n).read_bytes()).decode() for n in EMBEDDED}
    src = CELL.replace("{mode}", mode).replace("{files_b64}", json.dumps(files))
    return {"cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": src}],
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
            "nbformat": 4, "nbformat_minor": 5}


def metadata(kid, gpu):
    meta = {"id": "carsonrodrigues/" + kid, "title": kid, "code_file": kid + ".ipynb", "language": "python", "kernel_type": "notebook",
            "is_private": True, "enable_gpu": gpu, "enable_tpu": False, "enable_internet": True,
            "dataset_sources": [DATASET], "competition_sources": ["gemma-4-developer-agent"], "kernel_sources": [], "model_sources": []}
    if gpu:
        meta["machine_shape"] = "NvidiaL4"   # ignored by the CLIs; kaggle_push_wait.sh passes --accelerator NvidiaL4
        # 2026-10-26: Kaggle gives the 4x L4 machine only with the competition attached (without it the run got 2x T4) and
        # then refuses internet (SaveKernel 400). So this kernel runs offline: uv, CPython 3.12 and every wheel come from
        # the g4-g1-assets kernel's output, the weights from g4-g1-w1 / g4-g1-w2 (aws/kaggle_g1/assets_kernels.py).
        meta["enable_internet"] = False
        meta["kernel_sources"] = ["carsonrodrigues/g4-g1-assets", "carsonrodrigues/g4-g1-w1", "carsonrodrigues/g4-g1-w2"]
    return meta


def main(argv=None):
    for d, (kid, mode, gpu) in KERNELS.items():
        kd = ROOT / "kernels" / d
        kd.mkdir(parents=True, exist_ok=True)
        (kd / (kid + ".ipynb")).write_text(json.dumps(notebook(mode), indent=1))
        (kd / "kernel-metadata.json").write_text(json.dumps(metadata(kid, gpu), indent=2))
        print(kd.relative_to(ROOT), "->", "carsonrodrigues/" + kid, mode, "4x L4" if gpu else "CPU")
    return 0


if __name__ == "__main__":
    sys.exit(main())
