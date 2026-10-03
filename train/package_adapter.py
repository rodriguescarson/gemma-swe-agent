"""Package a downloaded PEFT LoRA adapter (Adaption/Together tgz, extracted) into a submission bundle in one command.

    python train/package_adapter.py adapters/v11a --bundle submissions/v4h2 --out submissions/v4h2_v11a \
        --name v11a --key-style loud|loud2 [--stages fixer,verifier]

Writes <out>/ = a copy of <bundle> plus adapters/<name>/{adapter_config.json, adapter_model.safetensors}, an
`adapter: <name>` line before `model:` in sub_agents/<stage>.yaml for each stage, and adapters/MANIFEST.json (sha256
of every adapter file, merged with any manifest already in the bundle). Only the two PEFT files are copied; the tgz's
config.json, tokenizer, chat template and trainer_state stay behind. Exit 2 = refused, nothing written.

--key-style (docs/v11/GA_PROBE.md decides which one the scorer's vLLM maps):
  loud   base_model.model.model.language_model.layers.N.<rest>
  loud2  base_model.model.language_model.layers.N.<rest>
Any input prefix before `layers.N.` is accepted (both styles above, and Together's Llama-style
base_model.model.model.layers.N); keys outside the text layers (vision/audio/embeddings) are refused. Only the
safetensors header is rewritten: dtype, shape and data offsets stay, and the data section is copied byte for byte.

Limits enforced (vendored wheels, read 2026-10-03): rank <= 128 (adk_submission.server.VllmConfig.max_lora_rank),
adapter name ^[a-zA-Z0-9_.-]+$ (server._VALID_ADAPTER_NAME_RE) plus the plan_A.md name rule (no "gemma4", not o<digit>
or gpt-5 prefix), whole bundle <= 3 GiB (swegemma.config), DoRA refused (vLLM LoRA has no DoRA path).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
from pathlib import Path

MAX_RANK = 128
MAX_BUNDLE_BYTES = 3 * 1024 ** 3
PREFIX = {"loud": "base_model.model.model.language_model.", "loud2": "base_model.model.language_model."}
KEY_RE = re.compile(r"^(?P<prefix>base_model\.model\.(?:[A-Za-z_]+\.)*?)(?P<tail>layers\.\d+\..+)$")
NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")
NON_TEXT = ("vision", "audio", "embed", "multi_modal")


class Refuse(Exception):
    pass


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_peft_dir(root: Path) -> Path:
    if (root / "adapter_config.json").is_file():
        return root
    hits = sorted(p.parent for p in root.rglob("adapter_config.json") if (p.parent / "adapter_model.safetensors").is_file())
    if len(hits) != 1:
        raise Refuse(f"expected exactly one PEFT dir (adapter_config.json + adapter_model.safetensors) under {root}, found {len(hits)}: {hits}")
    return hits[0]


def read_header(path):
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        return json.loads(f.read(n)), 8 + n


def check_config(cfg, header):
    ranks = {"r": cfg.get("r")}
    ranks.update({f"rank_pattern[{k}]": v for k, v in (cfg.get("rank_pattern") or {}).items()})
    for k, v in header.items():                     # the tensors themselves: lora_A is [r, in], lora_B is [out, r]
        if k != "__metadata__" and ".lora_A." in k:
            ranks[k] = v["shape"][0]
    if ranks["r"] is None:
        raise Refuse("adapter_config.json has no 'r'")
    bad = {k: v for k, v in ranks.items() if int(v) > MAX_RANK}
    if bad:
        raise Refuse(f"rank > {MAX_RANK} (scorer vLLM max_lora_rank): {dict(list(bad.items())[:4])}")
    if cfg.get("use_dora"):
        raise Refuse("use_dora=true: vLLM LoRA serving has no DoRA path")
    if cfg.get("peft_type", "LORA") != "LORA":
        raise Refuse(f"peft_type {cfg.get('peft_type')!r} is not LORA")
    return max(int(v) for v in ranks.values())


def rewrite_keys(header, style):
    out, seen = {}, set()
    for k, v in header.items():
        if k == "__metadata__":
            out[k] = v
            continue
        m = KEY_RE.match(k)
        if not m or any(w in m["prefix"] for w in NON_TEXT):
            raise Refuse(f"tensor key outside the text-model layers, cannot map: {k}")
        new = PREFIX[style] + m["tail"]
        if new in seen:
            raise Refuse(f"two keys map to {new}")
        seen.add(new)
        out[new] = v
    return out


def write_rewritten(src, dst, header, data_start):
    h = json.dumps(header, separators=(",", ":"), sort_keys=True).encode()
    h += b" " * (-len(h) % 8)
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fo.write(struct.pack("<Q", len(h)))
        fo.write(h)
        fi.seek(data_start)
        shutil.copyfileobj(fi, fo, 1 << 22)


def stage_files(bundle: Path, stages):
    files = {}
    for s in stages:
        p = bundle / "sub_agents" / f"{s}.yaml"
        if not p.is_file():
            raise Refuse(f"stage {s!r}: {p} does not exist")
        if not re.search(r"(?m)^model: ", p.read_text()):
            raise Refuse(f"stage {s!r}: {p} has no top-level 'model:' line (an adapter needs a base model)")
        files[s] = p
    return files


def add_adapter_line(path: Path, name):
    text = path.read_text()
    text = re.sub(r"(?m)^adapter: .*\n", "", text)
    text = re.sub(r"(?m)^model: ", f"adapter: {name}\nmodel: ", text, count=1)
    path.write_text(text)


def package(adapter_dir, bundle, out, name, style, stages):
    adapter_dir, bundle, out = Path(adapter_dir), Path(bundle), Path(out)
    if not NAME_RE.match(name) or "gemma4" in name.lower() or re.match(r"^(o\d|gpt-5)", name):
        raise Refuse(f"bad adapter name {name!r}: ^[a-zA-Z0-9_.-]+$, no 'gemma4', not starting with o<digit> or gpt-5")
    if style not in PREFIX:
        raise Refuse(f"--key-style must be one of {sorted(PREFIX)}")
    if out.exists():
        raise Refuse(f"{out} exists; refusing to overwrite")
    if not (bundle / "agent.yaml").is_file():
        raise Refuse(f"{bundle} has no agent.yaml")
    if (bundle / "adapters" / name).exists():
        raise Refuse(f"{bundle}/adapters/{name} already exists")
    stage_files(bundle, stages)
    peft = find_peft_dir(adapter_dir)
    src_st, src_cfg = peft / "adapter_model.safetensors", peft / "adapter_config.json"
    if not src_st.is_file():
        raise Refuse(f"{src_st} missing (only .safetensors weights are allowed by swegemma)")
    cfg = json.loads(src_cfg.read_text())
    header, data_start = read_header(src_st)
    rank = check_config(cfg, header)
    new_header = rewrite_keys(header, style)

    # Build in a sibling temp dir, then rename: a refusal or crash never leaves a half-written bundle at <out>.
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{out.name}.", dir=out.parent))
    try:
        stage = tmp / "b"
        shutil.copytree(bundle, stage, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "._*", ".DS_Store"))
        ad = stage / "adapters" / name
        ad.mkdir(parents=True)
        shutil.copyfile(src_cfg, ad / "adapter_config.json")
        write_rewritten(src_st, ad / "adapter_model.safetensors", new_header, data_start)
        for p in stage_files(stage, stages).values():
            add_adapter_line(p, name)
        size = sum(f.stat().st_size for f in stage.rglob("*") if f.is_file())
        if size > MAX_BUNDLE_BYTES:
            raise Refuse(f"bundle is {size / 2**30:.2f} GiB > 3 GiB cap")
        mpath = stage / "adapters" / "MANIFEST.json"
        man = json.loads(mpath.read_text()) if mpath.is_file() else {}
        man.setdefault("files", {})
        for fn in ("adapter_config.json", "adapter_model.safetensors"):
            man["files"][f"{name}/{fn}"] = sha256(ad / fn)
        man.setdefault("packaged", {})[name] = {
            "source": str(peft), "source_sha256": {fn: sha256(peft / fn) for fn in ("adapter_config.json", "adapter_model.safetensors")},
            "key_style": style, "stages": list(stages), "r": rank, "lora_alpha": cfg.get("lora_alpha"),
            "target_modules": cfg.get("target_modules"), "base_model_name_or_path": cfg.get("base_model_name_or_path"),
            "tensors": len(new_header) - ("__metadata__" in new_header),
            "dtypes": sorted({v["dtype"] for k, v in new_header.items() if k != "__metadata__"}), "bundle": str(bundle)}
        mpath.write_text(json.dumps(man, indent=2, sort_keys=True) + "\n")
        os.rename(stage, out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    info = man["packaged"][name]
    print(f"{out}: adapter {name} r={rank} alpha={info['lora_alpha']} {info['tensors']} tensors {info['dtypes']} "
          f"modules={info['target_modules']} key-style={style} stages={','.join(stages)} bundle={size / 1e6:.1f} MB "
          f"sha={man['files'][f'{name}/adapter_model.safetensors'][:12]}")
    return man


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("adapter_dir", help="extracted PEFT adapter dir (or a dir containing exactly one)")
    ap.add_argument("--bundle", required=True, help="source submission bundle, e.g. submissions/v4h2")
    ap.add_argument("--out", required=True, help="destination bundle dir (must not exist)")
    ap.add_argument("--name", default="v11a")
    ap.add_argument("--key-style", required=True, choices=sorted(PREFIX))
    ap.add_argument("--stages", default="fixer,verifier", help="comma list of sub_agents/<stage>.yaml that get the adapter")
    a = ap.parse_args(argv)
    stages = [s.strip() for s in a.stages.split(",") if s.strip()]
    try:
        package(a.adapter_dir, a.bundle, a.out, a.name, a.key_style, stages)
    except Refuse as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
