#!/usr/bin/env python3
"""Assemble the serving bundle vLLM loads on the box when several adapter bundles race at once (serve.sh BUNDLE=OUT; the
autopilot sets it from plan["serve_bundle"], P12). OUT = the first source bundle's files (agent.yaml, configs/, prompts/,
eval_config.yaml) plus adapters/<name>/{adapter_config.json, adapter_model.safetensors} from every source and one merged
adapters/MANIFEST.json. adk_submission.discover_adapters reads only adapters/, so the agent files are a formality. Weights are
copied and their sha256 checked against each source's manifest; duplicate adapter names refuse. tests/test_a6000_p12.py.

    python scripts/a6000/union_bundle.py OUT submissions/v12_think1 submissions/v12_think1f submissions/v12_think2
"""
import argparse, hashlib, json, os, shutil, sys
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def adapters_of(bundle):
    d = Path(bundle) / "adapters"
    return sorted(p.name for p in d.iterdir() if p.is_dir() and (p / "adapter_model.safetensors").is_file() and (p / "adapter_config.json").is_file()) if d.is_dir() else []


def build(out, sources, check_sha=True):
    out, sources = Path(out), [Path(s) for s in sources]
    if out.exists():
        shutil.rmtree(out)
    first = sources[0]
    shutil.copytree(first, out, ignore=shutil.ignore_patterns("adapters", "__pycache__", "*.pyc", ".DS_Store", "._*"))
    (out / "adapters").mkdir()
    files, seen, report = {}, {}, []
    for src in sources:
        man = json.loads((src / "adapters" / "MANIFEST.json").read_text()) if (src / "adapters" / "MANIFEST.json").is_file() else {"files": {}}
        names = adapters_of(src)
        if not names:
            raise SystemExit(f"{src}: no adapters/<name>/ with adapter_config.json + adapter_model.safetensors")
        for name in names:
            if name in seen:
                raise SystemExit(f"adapter name {name!r} appears in both {seen[name]} and {src}")
            seen[name] = str(src)
            dst = out / "adapters" / name
            dst.mkdir()
            for fn in ("adapter_config.json", "adapter_model.safetensors"):
                shutil.copyfile(src / "adapters" / name / fn, dst / fn)
                rel = f"{name}/{fn}"
                got = sha256(dst / fn)
                want = man.get("files", {}).get(rel)
                if check_sha and want and want != got:
                    raise SystemExit(f"{src}: sha256 mismatch for {rel}: manifest {want[:12]} vs file {got[:12]}")
                files[rel] = got
            report.append({"adapter": name, "from": str(src), "bytes": os.path.getsize(dst / "adapter_model.safetensors"), "sha256": files[f"{name}/adapter_model.safetensors"][:12]})
    merged = {"files": files, "sources": [str(s) for s in sources], "adapters": sorted(seen)}
    (out / "adapters" / "MANIFEST.json").write_text(json.dumps(merged, indent=1, sort_keys=True))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out"); ap.add_argument("sources", nargs="+"); ap.add_argument("--no-check-sha", action="store_true")
    a = ap.parse_args(argv)
    rep = build(a.out, a.sources, check_sha=not a.no_check_sha)
    for r in rep:
        print(f"{r['adapter']}: {r['bytes']} bytes sha {r['sha256']} from {r['from']}")
    print(f"{a.out}: {len(rep)} adapters -> adapters/MANIFEST.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
