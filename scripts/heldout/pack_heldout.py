"""Pack heldout1k tasks (data/heldout1k/tasks.jsonl, mined by scripts/pallets/heldout_miner.py) in the SWE-Pallets-X
harness layout that scripts/pallets/pack.py writes, so scripts/pallets/or_race.sh (HARNESS=<dir>) and
scripts/pallets/pod_probe.sh (PROBE_HARNESS=<dir>) run them unchanged.

  .venv/bin/python scripts/heldout/pack_heldout.py --ids data/heldout1k/sample200_ids.txt \
      --out data/heldout1k/harness_s200 [--no-graphs] [--no-fetch] [--min-free-gb 15]

Writes <out>/ (same names and meaning as pack.py):
  tasks.jsonl          pack.KEYS only (the competition's 8 keys), rows in --ids order. problem_statement is the miner's
                       PR title + "\\n\\n" + body already (title-only rows keep their bare title), hints_text "".
  snapshots/<tid>.tgz  the repo tree at base_commit as a single-commit git repo ("baseline", branch main), with the
                       competition identity `[user] name = Agent, email = agent@eval` in .git/config, like the Pallets
                       snapshots: no history, so neither base_commit nor its ancestors are in the object store.
                       Submodule gitlinks are vendored as plain files at their recorded commit (the miner's
                       init_submodules did the same for validation). The miner's prep, write_scm_version_file (the
                       hatch-vcs / setuptools-scm version module `pip install -e` would generate), is applied; it is
                       gitignored in those repos, so it stays untracked. Deterministic: fixed commit dates (base
                       commit's committer date), a stat-free index (read-tree), sorted members, fixed mtimes, gzip mtime 0.
  graphs/<repo short>_<base_commit>.json, embeddings/<same>.npz
                       built with the SWE-Pallets-X pipeline (data/pallets/pipeline/pipeline/graphs.py and embeddings.py,
                       fetched by scripts/pallets/fetch.py), the way the Pallets graphs were made; the harness only
                       advertises the graph tools when both files exist (agent_runner.py), so without them a run sees a
                       different prompt than the competition's. --no-graphs skips them.
  wheels/              the exact pinned wheels of the packed tasks' freezes (row env.deps) for linux x86_64 AND aarch64
                       (the local Docker probe is arm64), + flit_core==3.12.0, minus each repo's own distribution; from
                       --wheel-cache, downloaded there first unless --no-fetch (sdist-only pins are built to a pure wheel).
  wheels/_extra-<REPO_PKG>.txt  per repo (REPO_PKG = repo short name lower-cased, run_eval.faithful_install): the freeze
                       minus the repo's own distribution. scripts/pallets/run_eval_pallets.py installs it --no-deps into
                       every sandbox, so the sandbox holds the miner's validation venv. Mixed versions of one package
                       across repos are fine here (unlike pack.py's single-venv packs): every repo's own exact pins are
                       installed last.
  env.json             {tid: {venv (= env_id), python, pins, own, prep, submodules, statement: pr | title_only}}
  ids.txt, manifest.json (counts, missing wheels, graph failures; not part of the determinism contract)
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "pallets"))
import heldout_miner as miner  # noqa: E402
import pack as pallets_pack  # noqa: E402

KEYS = pallets_pack.KEYS
HELD = ROOT / "data" / "heldout1k"
CACHE = Path(os.environ.get("G4_HELDOUT_SCRATCH") or Path.home() / ".cache" / "g4" / "heldout1k")
PIPE = ROOT / "data" / "pallets" / "pipeline" / "pipeline"
TOOL_PY = CACHE / "toolenv" / "bin" / "python"          # python 3.12 + pip + scikit-learn (graphs, downloads)
GIT_ENV = {**miner.HERMETIC_GIT, "LC_ALL": "C"}
CONFIG = ("[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n\tlogallrefupdates = true\n"
          "[user]\n\temail = agent@eval\n\tname = Agent\n")
X86 = ["manylinux2014_x86_64", "manylinux_2_17_x86_64", "manylinux_2_28_x86_64", "manylinux_2_34_x86_64",
       "linux_x86_64"]
ARM = ["manylinux2014_aarch64", "manylinux_2_17_aarch64", "manylinux_2_28_aarch64", "manylinux_2_34_aarch64",
       "linux_aarch64"]
FLIT = "flit_core==3.12.0"


def git(cwd, *args, env=None, check=True) -> str:
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, errors="surrogateescape",
                       env={**os.environ, **GIT_ENV, **(env or {})})
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} in {cwd}: {p.stderr.strip()[-300:]}")
    return p.stdout


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def repo_short(repo: str) -> str:
    return repo.split("/")[-1]


def repo_pkg(repo: str) -> str:
    return repo_short(repo).lower()                     # = run_eval.faithful_install's REPO_PKG


def clone_dir(clones: Path, repo: str) -> Path:
    return Path(clones) / repo.replace("/", "_")


# ------------------------------------------------------------------------------------------- tree + snapshot
def checkout_tree(clone: Path, sha: str, dest: Path) -> None:
    """Write sha's tree to dest without touching the clone's own index or worktree (temp index + checkout-index)."""
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        env = {"GIT_INDEX_FILE": str(Path(td) / "index")}
        git(clone, "read-tree", sha, env=env)
        git(clone, "checkout-index", "-a", "-f", f"--prefix={dest}/", env=env)


def vendor_submodules(clone: Path, sha: str, dest: Path, modules: Path) -> list:
    """Each gitlink in sha's .gitmodules -> plain files at its recorded commit (one cached clone per url)."""
    if not (dest / ".gitmodules").is_file():
        return []
    cfg = git(dest, "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.(path|url)$", check=False)
    info: dict = {}
    for ln in cfg.splitlines():
        key, _, val = ln.partition(" ")
        name, field = key[len("submodule."):].rsplit(".", 1)
        info.setdefault(name, {})[field] = val
    done = []
    for name, d in sorted(info.items()):
        path, url = d.get("path"), d.get("url")
        ls = git(clone, "ls-tree", sha, "--", path).split()
        if not path or len(ls) < 3 or ls[1] != "commit":
            continue
        sub_sha = ls[2]
        if url and url.startswith(("./", "../")):
            raise RuntimeError(f"relative submodule url {url} not supported")
        local = Path(modules) / re.sub(r"[^A-Za-z0-9._-]+", "_", url)
        if not (local / ".git").is_dir() and not (local / "HEAD").is_file():
            local.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "-c", "protocol.file.allow=always", "clone", "-q", "--no-checkout", url, str(local)],
                           check=True, capture_output=True, env={**os.environ, **GIT_ENV})
        if subprocess.run(["git", "-C", str(local), "cat-file", "-e", f"{sub_sha}^{{commit}}"],
                          capture_output=True).returncode != 0:
            git(local, "-c", "protocol.file.allow=always", "fetch", "-q", "origin", sub_sha)
        target = dest / path
        shutil.rmtree(target, ignore_errors=True)
        checkout_tree(local, sub_sha, target)
        done.append(path)
    return done


def commit_date(clone: Path, sha: str) -> int:
    return int(git(clone, "show", "-s", "--format=%ct", sha).strip())


def make_repo(tree: Path, epoch: int) -> None:
    """tree -> single-commit repo 'baseline' on main, competition identity, stat-free (deterministic) index."""
    when = f"@{epoch} +0000"
    env = {"GIT_AUTHOR_NAME": "Agent", "GIT_AUTHOR_EMAIL": "agent@eval", "GIT_COMMITTER_NAME": "Agent",
           "GIT_COMMITTER_EMAIL": "agent@eval", "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    git(tree, "init", "-q", "-b", "main", env=env)
    (tree / ".git" / "config").write_text(CONFIG)            # no macOS ignorecase / precomposeunicode keys
    git(tree, "add", "-A", env=env)
    git(tree, "commit", "-q", "--no-verify", "-m", "baseline", env=env)
    (tree / ".git" / "index").unlink()
    git(tree, "read-tree", "HEAD", env=env)                  # index without stat data: same bytes on every pack


def write_tgz(tree: Path, dst: Path, epoch: int) -> None:
    """Deterministic tar.gz of tree with './' member names (the Pallets/competition snapshot style)."""
    tmp = dst.with_name(dst.name + ".part")
    with open(tmp, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as gz, \
            tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
        def add(p: Path, arc: str):
            st = os.lstat(p)
            ti = tarfile.TarInfo(arc)
            ti.mtime, ti.uid, ti.gid, ti.uname, ti.gname = epoch, 0, 0, "", ""
            ti.mode = st.st_mode & 0o7777
            if p.is_symlink():
                ti.type, ti.linkname = tarfile.SYMTYPE, os.readlink(p)
                tar.addfile(ti)
            elif p.is_dir():
                ti.type = tarfile.DIRTYPE
                tar.addfile(ti)
            else:
                ti.size = st.st_size
                with open(p, "rb") as fh:
                    tar.addfile(ti, fh)

        add(tree, "./")
        for dirpath, dirnames, filenames in os.walk(tree):
            dirnames.sort()
            base = Path(dirpath)
            for n in sorted(dirnames + filenames):
                p = base / n
                arc = "./" + p.relative_to(tree).as_posix()
                if n in dirnames and not p.is_symlink():
                    add(p, arc + "/")
                else:
                    add(p, arc)
            dirnames[:] = [d for d in dirnames if not (base / d).is_symlink()]
    os.replace(tmp, dst)


def build_snapshot(row: dict, clones: Path, dst: Path, work: Path) -> dict:
    clone = clone_dir(clones, row["repo"])
    if not clone.is_dir():
        raise SystemExit(f"pack_heldout: no clone for {row['repo']} at {clone} (git clone --no-checkout it there)")
    tree = work / row["instance_id"]
    shutil.rmtree(tree, ignore_errors=True)
    try:
        checkout_tree(clone, row["base_commit"], tree)
        subs = vendor_submodules(clone, row["base_commit"], tree, Path(clones) / "_modules")
        prep = miner.write_scm_version_file(tree)
        epoch = commit_date(clone, row["base_commit"])
        make_repo(tree, epoch)
        write_tgz(tree, dst, epoch)
        return {"prep": prep, "submodules": subs, "tree": tree}
    except BaseException:
        shutil.rmtree(tree, ignore_errors=True)
        raise


# ------------------------------------------------------------------------------------------- graphs
SORTED_WALK = (
    "import os, runpy, sys\n"
    "_walk = os.walk\n"
    "def walk(top, *a, **k):\n"
    "    for d, ds, fs in _walk(top, *a, **k):\n"
    "        ds.sort()\n"
    "        yield d, ds, sorted(fs)\n"
    "os.walk = walk\n"
    "sys.argv = sys.argv[1:]\n"
    "runpy.run_path(sys.argv[0], run_name='__main__')\n"
)


def build_graph(tree: Path, repo: str, out_json: Path, python: str) -> bool:
    """data/pallets/pipeline/pipeline/graphs.py (stdlib only), run with a sorted os.walk so node order is stable."""
    tmp = out_json.with_name(out_json.name + ".part")
    p = subprocess.run([python, "-c", SORTED_WALK, str(PIPE / "graphs.py"), str(tree), repo_short(repo), str(tmp)],
                       capture_output=True, text=True)
    if p.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        return False
    os.replace(tmp, out_json)
    return True


def build_embeddings(graph_json: Path, npz: Path, python: str) -> bool:
    """data/pallets/pipeline/pipeline/embeddings.py (TF-IDF -> TruncatedSVD(256), seeded); needs scikit-learn."""
    tmp = Path(str(npz)[:-4] + ".part.npz")
    p = subprocess.run([python, str(PIPE / "embeddings.py"), str(graph_json), str(tmp)], capture_output=True, text=True)
    if p.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        return False
    os.replace(tmp, npz)
    return True


# ------------------------------------------------------------------------------------------- wheels
def own_dist(repo: str) -> str:
    return norm(miner.own_package(repo))


def extra_lines(row: dict) -> list:
    skip = {own_dist(row["repo"]), norm(repo_pkg(row["repo"]))}
    return [p for p in row["env"]["deps"] if norm(p.split("==")[0]) not in skip]


def wheel_key(fname: str) -> tuple:
    parts = fname[:-4].split("-")
    return norm(parts[0]), parts[1]


def is_pure(fname: str) -> bool:
    return fname.endswith("-none-any.whl")


def cache_index(cache: Path) -> dict:
    have: dict = {}
    for f in sorted(Path(cache).glob("*.whl")):
        have.setdefault(wheel_key(f.name), []).append(f)
    return have


def arch_ok(files: list) -> bool:
    names = [f.name for f in files]
    return any(is_pure(n) for n in names) or (any("x86_64" in n for n in names) and any("aarch64" in n for n in names))


def fetch_wheel(pin: str, cache: Path, python: str) -> None:
    base = [python, "-m", "pip", "download", "-q", "--no-deps", "--only-binary=:all:", "--python-version", "3.12",
            "--implementation", "cp", "--abi", "cp312", "--abi", "abi3", "--abi", "none", "-d", str(cache)]
    for plat in (X86, ARM):
        args = [a for p in plat for a in ("--platform", p)]
        subprocess.run(base + args + [pin], capture_output=True, text=True)
    name, _, ver = pin.partition("==")
    if (norm(name), ver) not in cache_index(cache):          # sdist only: build it (kept only when pure python)
        with tempfile.TemporaryDirectory() as td:
            subprocess.run([python, "-m", "pip", "wheel", "-q", "--no-deps", "--no-binary", ":all:", "-w", td, pin],
                           capture_output=True, text=True)
            for f in Path(td).glob("*.whl"):
                if is_pure(f.name):
                    shutil.copy2(f, Path(cache) / f.name)


def ship_wheels(pins: list, cache: Path, wdir: Path, fetch: bool, python: str) -> dict:
    Path(cache).mkdir(parents=True, exist_ok=True)
    have = cache_index(cache)
    if fetch:
        for pin in pins:
            name, _, ver = pin.partition("==")
            if not arch_ok(have.get((norm(name), ver), [])):
                fetch_wheel(pin, cache, python)
        have = cache_index(cache)
    missing, one_arch = [], []
    for pin in pins:
        name, _, ver = pin.partition("==")
        fs = have.get((norm(name), ver), [])
        if not fs:
            missing.append(pin)
            continue
        if not arch_ok(fs):
            one_arch.append(pin)
        for f in fs:
            d = wdir / f.name
            if not (d.is_file() and d.stat().st_size == f.stat().st_size):
                shutil.copy2(f, d)                    # copies, not links: the directory is rsynced to pods
    return {"missing_wheels": missing, "one_arch_only": one_arch}


# ------------------------------------------------------------------------------------------- main
def load_rows(tasks: Path) -> dict:
    out = {}
    with open(tasks) as fh:
        for ln in fh:
            if ln.strip():
                r = json.loads(ln)
                out[r["instance_id"]] = r
    return out


def free_gb(path: Path) -> float:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / 1e9


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True)
    ap.add_argument("--tasks", default=str(HELD / "tasks.jsonl"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--clones", default=str(CACHE / "clones"))
    ap.add_argument("--wheel-cache", default=str(CACHE / "wheels"))
    ap.add_argument("--tool-python", default=str(TOOL_PY), help="python with pip + scikit-learn")
    ap.add_argument("--no-fetch", action="store_true", help="never download wheels; report missing ones")
    ap.add_argument("--no-graphs", action="store_true")
    ap.add_argument("--min-free-gb", type=float, default=0.0, help="stop (exit 3) when free disk drops below this")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)

    rows = load_rows(Path(a.tasks))
    ids = [ln.strip() for ln in Path(a.ids).read_text().splitlines() if ln.strip()]
    unknown = [t for t in ids if t not in rows]
    if unknown:
        raise SystemExit(f"pack_heldout: {len(unknown)} ids not in {a.tasks}: {unknown[:5]}")
    if a.limit:
        ids = ids[: a.limit]
    out = Path(a.out)
    for d in ("snapshots", "graphs", "embeddings", "wheels"):
        (out / d).mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="pack_heldout_", dir=os.environ.get("TMPDIR")))
    py = a.tool_python if Path(a.tool_python).exists() else sys.executable
    env, graph_fail, stopped, packed = {}, [], None, []
    prev = json.loads((out / "env.json").read_text()) if (out / "env.json").is_file() else {}
    try:
        for n, tid in enumerate(ids, 1):
            if a.min_free_gb and free_gb(out) < a.min_free_gb:
                stopped = f"disk below {a.min_free_gb} GB free after {len(packed)} tasks"
                break
            r = rows[tid]
            dst = out / "snapshots" / f"{tid}.tgz"
            key = f"{repo_short(r['repo'])}_{r['base_commit']}"
            gj, gz = out / "graphs" / f"{key}.json", out / "embeddings" / f"{key}.npz"
            need_graph = not a.no_graphs and not (gj.is_file() and gz.is_file())
            info = None
            if dst.is_file() and tid in prev and not need_graph:
                info = {"prep": prev[tid]["prep"], "submodules": prev[tid]["submodules"], "tree": None}
            else:
                info = build_snapshot(r, Path(a.clones), dst, work)
            if need_graph:
                tree = info["tree"]
                if tree is None:
                    tree = work / tid
                    with tarfile.open(dst) as t:
                        t.extractall(tree, filter="tar")
                ok = build_graph(tree, r["repo"], gj, py) and build_embeddings(gj, gz, py)
                if not ok:
                    gj.unlink(missing_ok=True)
                    gz.unlink(missing_ok=True)
                    graph_fail.append(tid)
            if info.get("tree") is not None or (work / tid).exists():
                shutil.rmtree(work / tid, ignore_errors=True)
            env[tid] = {"venv": r["env"]["env_id"], "python": r["env"]["python"], "pins": r["env"]["deps"],
                        "own": miner.own_package(r["repo"]), "prep": info["prep"], "submodules": info["submodules"],
                        "statement": "title_only" if r.get("statement_title_only") else "pr"}
            packed.append(tid)
            if n % 25 == 0:
                print(f"pack_heldout: {n}/{len(ids)} packed, {free_gb(out):.1f} GB free", flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    with open(out / "tasks.jsonl", "w") as fh:
        for tid in packed:
            fh.write(json.dumps({k: rows[tid][k] for k in KEYS}) + "\n")
    (out / "ids.txt").write_text("".join(t + "\n" for t in packed))
    (out / "env.json").write_text(json.dumps(env, indent=1, sort_keys=True) + "\n")

    pins, extras = {FLIT}, {}
    for tid in packed:
        r = rows[tid]
        lines = extra_lines(r)
        pins.update(lines)
        pkg = repo_pkg(r["repo"])
        if extras.setdefault(pkg, lines) != lines:
            raise SystemExit(f"pack_heldout: two different freezes for repo {r['repo']} in one pack")
    wdir = out / "wheels"
    for f in wdir.glob("_extra-*.txt"):
        f.unlink()
    for pkg, lines in sorted(extras.items()):
        (wdir / f"_extra-{pkg}.txt").write_text("".join(ln + "\n" for ln in lines))
    w = ship_wheels(sorted(pins), Path(a.wheel_cache), wdir, not a.no_fetch, py)
    pinset = {(norm(p.split("==")[0]), p.split("==")[1]) for p in pins}
    for f in wdir.glob("*.whl"):                              # a re-pack with fewer tasks drops their wheels
        if wheel_key(f.name) not in pinset:
            f.unlink()
    n_graph = sum(1 for tid in packed
                  if (out / "graphs" / f"{repo_short(rows[tid]['repo'])}_{rows[tid]['base_commit']}.json").is_file())
    man = {"n_tasks": len(packed), "n_requested": len(ids), "stopped": stopped, "graphs": n_graph,
           "graph_failures": graph_fail, "n_pins": len(pins), **w,
           "title_only": sum(1 for t in packed if rows[t].get("statement_title_only"))}
    (out / "manifest.json").write_text(json.dumps(man, indent=1, sort_keys=True) + "\n")
    print(f"pack_heldout: {len(packed)}/{len(ids)} tasks -> {out} (graphs {n_graph}, {len(pins)} pins, missing wheels "
          f"{len(w['missing_wheels'])}, one-arch {len(w['one_arch_only'])}){' STOPPED: ' + stopped if stopped else ''}")
    return 3 if stopped else 0


if __name__ == "__main__":
    raise SystemExit(main())
