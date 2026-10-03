"""Stage a bundle's adapter weights as a flat private Kaggle dataset and push it with the 2.x CLI.

    python scripts/adapters_dataset.py --bundle eval/golden/arms/v4_lora_probe2 --slug g4-adapters-probe2 [--owner carsonrodrigues]
        --out /tmp/ds [--push] [--kaggle .venv/bin/kaggle]
The dataset holds <name>__adapter_model.safetensors at its root (no directories: `kaggle datasets create` skips them
unless --dir-mode is given); adapter_config.json and adapters/MANIFEST.json stay in the notebook, and the kernel's
data cell (make_eval_kernel.py --adapters-dataset owner/slug) copies each weight file back to adapters/<name>/ and
checks its sha256 against the manifest. Why: a notebook with 2.8 MB of embedded adapters was refused (400) on
2026-10-03, and a trained r8 adapter on 60 layers is ~150 MB. tests/test_adapters_dataset.py.
"""
import argparse, json, os, shutil, subprocess, sys, time


def flat_name(rel):
    return rel.replace("/", "__")


def stage(bundle, out, owner, slug):
    os.makedirs(out, exist_ok=True)
    adir = os.path.join(bundle, "adapters")
    files = {}
    for name in sorted(os.listdir(adir)):
        w = os.path.join(adir, name, "adapter_model.safetensors")
        if os.path.isfile(w):
            rel = f"{name}/adapter_model.safetensors"; files[rel] = flat_name(rel)
            shutil.copyfile(w, os.path.join(out, files[rel]))
    meta = {"title": slug, "id": f"{owner}/{slug}", "licenses": [{"name": "CC0-1.0"}]}
    with open(os.path.join(out, "dataset-metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)
    return files


def cli_command(kaggle, out, exists):
    if exists:
        return [kaggle, "datasets", "version", "-p", out, "-m", "update " + time.strftime("%Y-%m-%d %H:%M")]
    return [kaggle, "datasets", "create", "-p", out]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True); ap.add_argument("--slug", required=True); ap.add_argument("--owner", default="carsonrodrigues")
    ap.add_argument("--out", required=True); ap.add_argument("--push", action="store_true"); ap.add_argument("--kaggle", default=".venv/bin/kaggle")
    a = ap.parse_args(argv)
    files = stage(a.bundle, a.out, a.owner, a.slug)
    total = sum(os.path.getsize(os.path.join(a.out, v)) for v in files.values())
    print(f"staged {len(files)} weight files ({total / 1e6:.2f} MB) in {a.out} as {a.owner}/{a.slug}")
    if a.push:
        r = subprocess.run([a.kaggle, "datasets", "status", f"{a.owner}/{a.slug}"], capture_output=True, text=True)
        exists = r.returncode == 0 and "not found" not in (r.stdout + r.stderr).lower() and "404" not in (r.stdout + r.stderr)
        cmd = cli_command(a.kaggle, a.out, exists)
        print("pushing:", " ".join(cmd)); out = subprocess.run(cmd, capture_output=True, text=True); print((out.stdout + out.stderr).strip()[-600:])
        if out.returncode != 0:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
