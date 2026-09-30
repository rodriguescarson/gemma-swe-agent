"""Export SWE-Pallets-X tasks in the competition's on-disk layout for a faithful swegemma run (pod or Kaggle L4).

  python3 scripts/pallets/pack.py --ids data/pallets/dev_ids.txt [--limit 40] [--venv default|flask-wz2]
                                   [--statements pr|dataset] [--out data/pallets/harness]

--venv default keeps the tasks whose venv is their repo's (Kaggle versions); --venv flask-wz2 packs that era set on its
own. Tasks whose venvs pin different versions of one package cannot share a wheelhouse, so pack refuses to mix them.
Writes <out>/ (research/pallets.md section 7):
  tasks.jsonl            the competition's 8 keys only (instance_id, repo, base_commit, patch, test_patch,
                         problem_statement, hints_text, created_at), rows in --ids order. problem_statement is the PR
                         title + "\n\n" + PR body (the competition's format, data/pallets/pr_statements.json) when
                         --statements pr (default) and the PR is known, else the dataset's statement
  wheels/                copies of exactly the pinned wheels of the packed tasks' venvs (+ flit_core) from
                         data/pallets/wheels (scripts/pallets/wheelhouse.py). Point the faithful install at it with
                         G4_WHEELHOUSE=<abs path> and scripts/pallets/run_eval_pallets.py: the harness itself nests a
                         copied wheels dir one level too deep and then uses the pod's /wheels (research/pallets.md 7.2)
  snapshots/<tid>.tgz    the dataset snapshot with `[user] name = Agent, email = agent@eval` added to .git/config, as in
                         the competition snapshots. The dataset's .git/config has no identity, so the harness's
                         `git commit -m baseline && git tag -f _swegemma_baseline` fails wherever git cannot guess one
                         (containers; HOME is the sandbox tmp), and the agent's diff base changes. Nothing else changes.
  graphs/<repo>_<base_commit>.json, embeddings/<repo>_<base_commit>.npz
                         renamed from data/pallets/{graphs,embeddings}/<tid>.* when fetched (the harness looks them up
                         as <repo_short>_<base_commit>, swegemma/context.py graph_repo_key); fetch first with
                         scripts/pallets/fetch.py --ids FILE graphs/graphs/ embeddings/embeddings/
  wheels/_extra-<repo>.txt  per repo in the pack (repo = the harness's REPO_PKG, e.g. click, sympy): the task venv's
                         full freeze MINUS the repo's own package. run_eval_pallets.py installs it (--no-deps) into
                         every sandbox after the faithful install, so the pod sandbox holds the same packages as the
                         oracle's venv. Needed for deps that the repo does not declare in requirements*.txt or
                         pyproject.toml: sympy before 2023 declares mpmath only in setup.py, which the faithful install
                         does not read, and mpmath is not in the competition wheels (research/pallets.md 7.2)
  env.json               {tid: {venv, pins, statement}} from data/pallets/task_env.json and the venv stamps
  ids.txt                the ids packed, in order
"""
import argparse
import io
import json
import os
import shutil
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAL = ROOT / "data" / "pallets"
VENVS = Path(os.environ.get("G4_PALLETS") or Path.home() / ".cache" / "g4" / "pallets")
KEYS = ("instance_id", "repo", "base_commit", "patch", "test_patch", "problem_statement", "hints_text", "created_at")
IDENTITY = b"[user]\n\temail = agent@eval\n\tname = Agent\n"


def repack(src: Path, dst: Path) -> bool:
    """Copy src.tgz to dst.tgz member by member, appending the identity to ./.git/config. Returns True if changed."""
    changed = False
    tmp = dst.with_suffix(".tgz.part")
    with tarfile.open(src, "r:gz") as tin, tarfile.open(tmp, "w:gz", compresslevel=6) as tout:
        for m in tin:
            data = tin.extractfile(m) if m.isfile() else None
            name = m.name[2:] if m.name.startswith("./") else m.name     # not lstrip("./"): it eats the dot of .git
            if m.isfile() and name == ".git/config":
                body = data.read()
                if b"[user]" not in body:
                    body = body + (b"" if body.endswith(b"\n") else b"\n") + IDENTITY
                    changed = True
                m.size = len(body)
                tout.addfile(m, io.BytesIO(body))
            else:
                tout.addfile(m, data)
    os.replace(tmp, dst)
    if not changed:
        raise SystemExit(f"pack: no .git/config without [user] found in {src}; refusing to guess")
    return changed


def stamp_pins(venv: str) -> list:
    p = VENVS / venv / ".g4_pallets_ok"
    return [ln for ln in p.read_text().splitlines() if ln and not ln.startswith("#")] if p.is_file() else []


def norm(name: str) -> str:
    return name.lower().replace("_", "-")


def own_packages(venv: str) -> set:
    """Normalised names from the stamp's '# own package (...): X==v' line (build_envs.sh), e.g. {'flask'}."""
    p = VENVS / venv / ".g4_pallets_ok"
    for ln in (p.read_text().splitlines() if p.is_file() else []):
        if ln.startswith("# own package"):
            return {norm(x.split("==")[0]) for x in ln.split(":", 1)[1].split() if "==" in x}
    return set()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(PAL / "harness"))
    ap.add_argument("--venv", default="default", help="default | an era venv name | any")
    ap.add_argument("--statements", choices=("pr", "dataset"), default="pr")
    ap.add_argument("--wheels", default=str(PAL / "wheels"))
    a = ap.parse_args()
    tasks = {json.loads(ln)["instance_id"]: json.loads(ln) for ln in open(PAL / "tasks.jsonl") if ln.strip()}
    task_env = json.loads((PAL / "task_env.json").read_text()) if (PAL / "task_env.json").is_file() else {}
    prs = json.loads((PAL / "pr_statements.json").read_text()) if (PAL / "pr_statements.json").is_file() else {}

    def venv_of(tid):
        return task_env.get(tid) or tasks[tid]["repo"].split("/")[-1]

    ids = [ln.strip() for ln in Path(a.ids).read_text().splitlines() if ln.strip()]
    if a.venv == "default":
        ids = [t for t in ids if venv_of(t) == tasks[t]["repo"].split("/")[-1]]
    elif a.venv != "any":
        ids = [t for t in ids if venv_of(t) == a.venv]
    if a.limit:
        ids = ids[: a.limit]
    pins = {}
    for tid in ids:
        for p in stamp_pins(venv_of(tid)) + ["flit_core==3.12.0"]:
            name, _, ver = p.partition("==")
            pins.setdefault(name.lower().replace("_", "-"), set()).add(ver)
    clash = {k: sorted(v) for k, v in pins.items() if len(v) > 1}
    if clash:
        raise SystemExit(f"pack: the selected tasks' venvs pin different versions {clash}; pack each venv separately "
                         "(--venv default, --venv flask-wz2)")
    out = Path(a.out)
    for d in ("snapshots", "graphs", "embeddings"):
        (out / d).mkdir(parents=True, exist_ok=True)
    env, n_graph = {}, 0
    with open(out / "tasks.jsonl", "w") as fh:
        for tid in ids:
            t = tasks[tid]
            row = {k: t[k] for k in KEYS}
            pr = prs.get(tid, {})
            use_pr = a.statements == "pr" and "title" in pr
            if use_pr:
                row["problem_statement"] = pr["title"] + "\n\n" + pr["body"]
            fh.write(json.dumps(row) + "\n")
            dst = out / "snapshots" / f"{tid}.tgz"
            src = PAL / "snapshots" / f"{tid}.tgz"
            if not (dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime):
                repack(src, dst)
            key = f"{t['repo'].split('/')[-1]}_{t['base_commit']}"
            for sub, ext in (("graphs", ".json"), ("embeddings", ".npz")):
                s = PAL / sub / f"{tid}{ext}"
                if s.is_file():
                    shutil.copy2(s, out / sub / f"{key}{ext}")
                    n_graph += sub == "graphs"
            venv = venv_of(tid)
            env[tid] = {"venv": venv, "pins": stamp_pins(venv), "statement": "pr" if use_pr else "dataset"}
    wdir = out / "wheels"
    shutil.rmtree(wdir, ignore_errors=True)
    wdir.mkdir()
    have = {}
    for f in Path(a.wheels).glob("*.whl"):
        # every platform build of a pin (x86_64 for pods; aarch64 only when fetched for the arm64 pod_probe)
        have.setdefault((f.name.split("-")[0].lower().replace("_", "-"), f.name.split("-")[1]), []).append(f)
    missing = []
    for name, vers in sorted(pins.items()):
        fs = have.get((name, next(iter(vers))))
        if not fs:
            missing.append(f"{name}=={next(iter(vers))}")
        for f in fs or ():
            shutil.copy2(f, wdir / f.name)          # copies, not links: the directory is rsynced to pods
    if missing:
        print(f"pack: WARNING wheels missing from {a.wheels}: {missing} (run scripts/pallets/wheelhouse.py)")
    extras = {}
    for tid in ids:
        pkg = tasks[tid]["repo"].split("/")[-1].lower()          # = run_eval.faithful_install's REPO_PKG
        venv = venv_of(tid)
        skip = own_packages(venv) | {norm(pkg)}
        lines = [p for p in stamp_pins(venv) if norm(p.split("==")[0]) not in skip]
        if extras.setdefault(pkg, lines) != lines:
            raise SystemExit(f"pack: two venvs for repo {pkg} in one pack; pack each venv separately")
    for pkg, lines in sorted(extras.items()):
        (wdir / f"_extra-{pkg}.txt").write_text("".join(ln + "\n" for ln in lines))
    (out / "env.json").write_text(json.dumps(env, indent=1, sort_keys=True) + "\n")
    (out / "ids.txt").write_text("".join(t + "\n" for t in ids))
    print(f"pack: {len(ids)} tasks -> {out} (graphs+embeddings for {n_graph}, {len(pins)} pinned wheels, "
          f"{sum(1 for e in env.values() if e['statement'] == 'pr')} PR-style statements)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
