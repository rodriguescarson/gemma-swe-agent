"""The G1 teacher pilot's pieces of the aws/ kit (GAPS "G1 pre-registration"): the teacher role (g6e.12xlarge, 4x L40S), the
--max-usd cap (G1: $40), the scratch bundle (v12b with 20 min / 100 calls, never in submissions/), the p2_race-style runner,
the S3 staging of the 30-task subset, and static rules on aws/jobs/g1_teacher.sh. Stubbed boto3; nothing talks to AWS."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "aws")); sys.path.insert(0, str(ROOT / "aws" / "jobs"))
sys.path.insert(0, str(ROOT / "tests"))
from test_aws_launch import RUN, dry_request, tagmap, world  # noqa: E402,F401  (world is a fixture)

JOB = ROOT / "aws" / "jobs" / "g1_teacher.sh"
CODE = "\n".join(ln for ln in JOB.read_text().splitlines() if not ln.lstrip().startswith("#"))   # comments may name what code must not use
HARNESS = ROOT / "data" / "heldout1k" / "harness_all"
G1_IDS = [ln.strip() for ln in open(ROOT / "data" / "distill" / "g1_ids.txt") if ln.strip()]


def _teacher_world(world):
    world.objects |= {"g4-test-bucket/runs/r1/in/overlay/data/heldout1k/harness_g1/tasks.jsonl", "g4-test-bucket/shared/raw/wheels/a.whl"}
    return world


# ------------------------------------------------------------------------------------------------------- the role
def test_teacher_request_is_one_g6e_12xlarge_with_every_safety_property(world, capsys):
    rc, req = dry_request(_teacher_world(world), "teacher", hours="3.75", job="bash aws/jobs/g1_teacher.sh")
    assert rc == 0, capsys.readouterr()
    assert req["InstanceType"] == "g6e.12xlarge" and req["ImageId"].startswith("ami-0dlami")
    assert req["InstanceInitiatedShutdownBehavior"] == "terminate" and "shutdown -h +225 " in req["UserData"].splitlines()[1]
    assert tagmap(req, "instance")["Role"] == "teacher" and tagmap(req, "volume")["Project"] == "gemma4-agent"
    assert req["BlockDeviceMappings"][0]["Ebs"]["VolumeSize"] == 200 and req["BlockDeviceMappings"][0]["Ebs"]["DeleteOnTermination"]
    assert "G4_SETUP='docker wheels harness'\n" in req["UserData"] and "G4_KEEP=eval/g1\n" in req["UserData"]
    assert "G4_JOB='bash aws/jobs/g1_teacher.sh'\n" in req["UserData"]


@pytest.mark.parametrize("extra,ok", [
    (["--hours", "5", "--max-usd", "40"], False),                     # the pre-registration's 5 h does not fit $40 on-demand
    (["--hours", "3.75", "--max-usd", "40"], True),                   # 3.75 h x $10.55/h = $39.6
    (["--hours", "4", "--max-usd", "40"], False),
    (["--hours", "4.25", "--max-usd", "40", "--spot", "--max-spot-usd", "9"], True),   # spot capped at $9/h: worst $38.5
    (["--hours", "5", "--max-usd", "40", "--spot"], False),           # spot defaults to MaxPrice = on-demand: worst case is on-demand
])
def test_max_usd_refuses_a_timer_whose_worst_case_is_over_the_cap(world, extra, ok, capsys):
    import launch
    _teacher_world(world)
    rc = launch.main(["teacher", "--run", RUN, "--job", "bash aws/jobs/g1_teacher.sh", *extra])
    err = capsys.readouterr().err
    if ok:
        assert rc == 0, err
    else:
        assert rc == 2 and "over --max-usd 40" in err and "at most --hours 3.75" in err
        assert world.run_calls == []                                   # refused before any request


def test_teacher_inputs_and_shared_wheels_are_blockers(world, capsys):
    import launch
    world.objects = {o for o in world.objects if "/raw/" not in o}
    assert launch.main(["teacher", "--hours", "3", "--run", RUN, "--job", "x", "--yes"]) == 2
    out = capsys.readouterr().out
    assert "in/overlay/data/heldout1k/harness_g1/tasks.jsonl is missing" in out and "shared/raw/wheels/ is empty" in out
    assert not [c for c in world.run_calls if "DryRun" not in c]


def test_g6e_12xlarge_needs_48_of_the_52_vcpu_being_requested(world, capsys):
    import launch
    _teacher_world(world)
    world.quota["L-DB2E81BA"] = 52.0
    assert launch.main(["teacher", "--hours", "3", "--run", RUN, "--job", "x", "--yes"]) == 0
    world.quota["L-DB2E81BA"] = 40.0
    assert launch.main(["teacher", "--hours", "3", "--run", RUN, "--job", "x", "--yes", "--allow-concurrent"]) == 2
    assert "needs 48" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------ scratch bundle
def _tree(d):
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(d).rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


def test_scratch_bundle_changes_only_the_two_caps_and_never_touches_submissions(tmp_path):
    import g1_race
    from make_eval_kernel import read_budget
    base = ROOT / "submissions" / "v12b"
    before = _tree(base)
    d, budget = g1_race.make_bundle(base, tmp_path, 20, 100)
    assert _tree(base) == before and d == (tmp_path / "g1_v12b_t20").resolve()
    assert budget == {"max_time_minutes": 20.0, "max_tool_calls": 100, "max_turns": 150, "timeout_seconds": 180}
    new = _tree(d)
    assert set(new) == set(before) and [k for k in new if new[k] != before[k]] == ["eval_config.yaml"]
    old_lines = (base / "eval_config.yaml").read_text().splitlines()
    new_lines = (d / "eval_config.yaml").read_text().splitlines()
    assert [(o, n) for o, n in zip(old_lines, new_lines) if o != n] == [("  max_tool_calls: 40", "  max_tool_calls: 100"),
                                                                        ("  max_time_minutes: 5", "  max_time_minutes: 20")]
    assert read_budget(str(base))[0]["max_time_minutes"] == 5.0


@pytest.mark.parametrize("dest", ["submissions", "submissions/scratch", "submissions/v12b"])
def test_scratch_bundle_refuses_submissions(dest):
    import g1_race
    before = sorted(p.name for p in (ROOT / "submissions").iterdir())
    with pytest.raises(SystemExit, match="refusing"):
        g1_race.make_bundle(ROOT / "submissions" / "v12b", ROOT / dest)
    assert sorted(p.name for p in (ROOT / "submissions").iterdir()) == before


# ------------------------------------------------------------------------------------------------------- runner
def test_item_script_is_p2_races_with_the_bundle_from_scratch():
    import g1_race
    import p2_race
    for task in G1_IDS[:3]:
        ref = p2_race.item_script("v12b", task, 8201, 1.0)
        ours = g1_race.item_script("v12b", task, 8201, p2_race.budget_flags(str(ROOT / "submissions" / "v12b")), src="/g4/submissions")
        assert ours == ref                                             # byte-equal: drift in p2_race fails here
    s = g1_race.item_script("g1_v12b_t20", "x_1", 8202, "--max-time-minutes 20.0")
    assert "cp -r /scratch/g1_v12b_t20 /tmp/bundle_g1_v12b_t20" in s and "/g4/submissions" not in s and "G4_L4_SCALE=1.0" in s


def test_container_mounts_the_scratch_bundle_read_only_and_copies_no_submissions_bundle(tmp_path):
    import g1_race
    cmd = g1_race.docker_run("g4-g1-x", tmp_path / "out", tmp_path / "scratch" / "g1_v12b_t20", "data/heldout1k/harness_g1", "20", "64g")
    assert f"{(tmp_path / 'scratch').resolve()}:/scratch:ro" in cmd and f"{ROOT}:/g4:ro" in cmd and "ARMS=" in cmd
    assert "HARNESS=data/heldout1k/harness_g1" in cmd and cmd[cmd.index("--cpus") + 1] == "20"


class FakeRun:
    """subprocess.run for g1_race.race: SETUP prints SETUP_DONE; an item writes its task_results.jsonl under the run's /out."""
    def __init__(self, out, setup_ok=True):
        self.out, self.setup_ok, self.calls = Path(out), setup_ok, []

    def __call__(self, cmd, **kw):
        import re
        self.calls.append(cmd)
        stdout = ""
        if cmd[1] == "exec":
            script = cmd[-1]
            if "SETUP_DONE" in script:
                stdout = "SETUP_DONE" if self.setup_ok else "boom"
            else:
                arm, rdir = re.search(r"--results-dir /out/items/([^/ ]+)/(\S+)", script).groups()
                d = self.out / "items" / arm / rdir; d.mkdir(parents=True, exist_ok=True)
                (d / "task_results.jsonl").write_text(json.dumps({"instance_id": rdir, "resolved": False}) + "\n")
        return subprocess.CompletedProcess(cmd, 0, stdout, "")


def test_race_runs_every_task_once_and_a_rerun_resumes(tmp_path):
    import g1_race
    bundle, _ = g1_race.make_bundle(ROOT / "submissions" / "v12b", tmp_path / "scratch")
    ids = tmp_path / "ids.txt"; ids.write_text("".join(i + "\n" for i in G1_IDS))
    out = tmp_path / "out" / "devstral"
    fr = FakeRun(out)
    assert g1_race.race(out, bundle, "data/heldout1k/harness_g1", ids, 8201, 4, "g1-devstral", run=fr) == 0
    rows = [json.loads(ln) for ln in (out / "items.jsonl").read_text().splitlines()]
    assert sorted(r["task"] for r in rows) == sorted(G1_IDS) and {r["arm"] for r in rows} == {"g1_v12b_t20"}
    assert "ALL_DONE 30 items" in (out / "race.log").read_text() and (out / "ids.txt").read_text().split() == G1_IDS
    assert fr.calls[-1][:3] == [g1_race.p2_race.DOCKER, "rm", "-f"]   # the container goes away
    fr2 = FakeRun(out)
    assert g1_race.race(out, bundle, "data/heldout1k/harness_g1", ids, 8201, 4, "g1-devstral", run=fr2) == 0
    assert not [c for c in fr2.calls if c[1] == "exec" and "SETUP_DONE" not in c[-1]]   # everything already done


def test_race_setup_failure_returns_2_and_removes_the_container(tmp_path):
    import g1_race
    bundle, _ = g1_race.make_bundle(ROOT / "submissions" / "v12b", tmp_path / "scratch")
    ids = tmp_path / "ids.txt"; ids.write_text(G1_IDS[0] + "\n")
    fr = FakeRun(tmp_path / "out", setup_ok=False)
    assert g1_race.race(tmp_path / "out", bundle, "h", ids, 8201, 1, "g1-x", run=fr) == 2
    assert fr.calls[-1][1:3] == ["rm", "-f"] and "SETUP_FAILED" in (tmp_path / "out" / "race.log").read_text()


# ------------------------------------------------------------------------------------------------------ staging
@pytest.fixture(scope="module")
def subset():
    if not (HARNESS / "tasks.jsonl").is_file():
        pytest.skip("data/heldout1k/harness_all is not on this machine")
    import g1_stage
    with tempfile.TemporaryDirectory() as td:   # 368 MB: removed at once, not left in pytest's kept tmp dirs
        dest = Path(td) / "harness_g1"
        yield dest, g1_stage.build_subset(dest)


def test_subset_is_exactly_the_30_g1_tasks_with_byte_identical_snapshots(subset):
    dest, info = subset
    assert info["ids"] == info["tasks"] == info["snapshots"] == 30 == len(G1_IDS)
    assert [json.loads(ln)["instance_id"] for ln in open(dest / "tasks.jsonl")] == [i for i in
            (json.loads(ln)["instance_id"] for ln in open(HARNESS / "tasks.jsonl")) if i in set(G1_IDS)]
    assert (dest / "ids.txt").read_text().split() == G1_IDS
    assert sorted(json.loads((dest / "env.json").read_text())) == sorted(G1_IDS)
    for i in G1_IDS:
        assert (dest / "snapshots" / f"{i}.tgz").read_bytes() == (HARNESS / "snapshots" / f"{i}.tgz").read_bytes()
    assert sorted(p.name for p in (dest / "snapshots").iterdir()) == sorted(f"{i}.tgz" for i in G1_IDS)
    assert sorted(p.name for p in (dest / "wheels").iterdir()) == sorted(p.name for p in (HARNESS / "wheels").iterdir())
    assert not (dest / "graphs").exists() and not (dest / "embeddings").exists()


def test_subset_refuses_an_id_the_harness_lacks(tmp_path):
    import g1_stage
    if not (HARNESS / "tasks.jsonl").is_file():
        pytest.skip("no harness_all")
    ids = tmp_path / "ids.txt"; ids.write_text(G1_IDS[0] + "\nnot_a_task_000\n")
    with pytest.raises(SystemExit, match="not_a_task_000"):
        g1_stage.build_subset(tmp_path / "h", ids)


def test_stage_plan_only_makes_no_aws_call_and_upload_needs_a_commit_with_the_job(monkeypatch, capsys):
    if not (HARNESS / "tasks.jsonl").is_file():
        pytest.skip("no harness_all")
    import g1_stage
    import g4aws
    monkeypatch.setattr(g4aws, "session", lambda *a, **k: (_ for _ in ()).throw(AssertionError("AWS called")))
    has = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", "HEAD:aws/jobs/g1_teacher.sh"], capture_output=True).returncode == 0
    rc = g1_stage.main(["--run", "s3://g4-test-bucket/runs/g1"])
    out = capsys.readouterr().out
    assert "plan only: nothing was uploaded" in out and "30 tasks, 30 snapshots" in out and "shared/raw/wheels/" in out
    assert rc == (0 if has else 1)
    if not has:
        with pytest.raises(SystemExit, match="has no aws/jobs/g1_teacher.sh"):
            g1_stage.main(["--run", "s3://g4-test-bucket/runs/g1", "--upload"])


class FakeS3:
    def __init__(self):
        self.objects, self.uploads, self.corrupt = {}, [], set()

    def get_paginator(self, name):
        s = self

        class P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k, "Size": v} for k, v in s.objects.items() if k.startswith(Prefix)]}
        return P()

    def upload_file(self, path, bucket, key):
        self.uploads.append(key)
        self.objects[key] = Path(path).stat().st_size + (1 if key in self.corrupt else 0)


def test_stage_upload_skips_same_size_objects_and_fails_on_a_size_mismatch(tmp_path):
    import stage
    d = tmp_path / "h"; (d / "snapshots").mkdir(parents=True)
    (d / "tasks.jsonl").write_text("{}\n"); (d / "snapshots" / "a.tgz").write_bytes(b"x" * 10)
    s3 = FakeS3()
    assert stage.upload(s3, d, "b", "runs/g1/in/overlay/h") == (2, 0)
    assert sorted(s3.objects) == ["runs/g1/in/overlay/h/snapshots/a.tgz", "runs/g1/in/overlay/h/tasks.jsonl"]
    assert stage.upload(s3, d, "b", "runs/g1/in/overlay/h") == (0, 2)
    (d / "tasks.jsonl").write_text("{}\n{}\n")
    s3.corrupt.add("runs/g1/in/overlay/h/tasks.jsonl")
    with pytest.raises(SystemExit, match="VERIFY FAILED"):
        stage.upload(s3, d, "b", "runs/g1/in/overlay/h")


# ------------------------------------------------------------------------------------------------ the job script
def test_job_uses_its_own_latest_vllm_not_the_scorers_patched_build():
    s = CODE
    assert "TV=${TEACHER_VENV:-/root/tvllm}" in s and 'VLLM_VERSION=${TEACHER_VLLM:-0.31.0}' in s and '"vllm==$VLLM_VERSION"' in s
    assert "0.19.1" not in s and "supports_lora" not in s and "/root/venv/" not in s and "wheelhouse" not in s
    assert '"mistral_common>=1.8.6"' in s                               # the Devstral Small 2 model card's minimum


def test_job_layout_parsers_proxy_and_outputs_match_the_brief():
    s = CODE
    assert 'devstral) echo "${DEVSTRAL_GPUS:-0}"' in s and 'devstral) echo "${DEVSTRAL_TP:-1}"' in s
    assert 'gptoss) echo "${GPTOSS_GPUS:-2,3}"' in s and 'gptoss) echo "${GPTOSS_TP:-2}"' in s
    assert "--tool-call-parser mistral --enable-auto-tool-choice" in s
    assert "--tool-call-parser openai --enable-auto-tool-choice --reasoning-parser openai_gptoss" in s
    assert "mistralai/Devstral-Small-2-24B-Instruct-2512" in s and "openai/gpt-oss-120b" in s
    assert 'NVME=${G1_NVME:-/opt/dlami/nvme}' in s and 'HF_HOME="$NVME/hf"' in s and '--local-dir "$d"' in s and 'd="$NVME/models/$1"' in s
    assert 'scripts/or_proxy.py --upstream vllm --base "$base" --model "$(served "$t")" --capture "$OUT/capture_$t.jsonl"' in s
    assert "--max-usd 1000" in s and s.index("--probe") < s.index("--capture")
    assert 'OUT=${G1_OUT:-$ROOT/eval/g1}' in s and 'race "$OUT/$t"' in s and "--min 20 --calls 100" in s
    assert "submissions" not in s                                      # the scratch bundle lives in $SCRATCH
    assert 'for n in "${pids[@]}"; do wait "$n"' in s                  # never a bare wait while the servers run
    import g4aws
    assert g4aws.ROLES["teacher"]["keep"] == "eval/g1"                 # bootstrap syncs exactly the job's OUT


@pytest.mark.parametrize("path", sorted((ROOT / "aws" / "jobs").glob("*.sh")), ids=lambda p: p.name)
def test_job_scripts_parse(path):
    assert subprocess.run(["bash", "-n", str(path)], capture_output=True).returncode == 0


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not installed")
@pytest.mark.parametrize("path", sorted((ROOT / "aws" / "jobs").glob("*.sh")), ids=lambda p: p.name)
def test_job_scripts_shellcheck(path):
    r = subprocess.run(["shellcheck", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_job_modules_import_without_boto3(monkeypatch):
    import importlib
    monkeypatch.setitem(sys.modules, "boto3", None)
    for name in ("g1_race", "g1_stage"):
        sys.modules.pop(name, None)
        importlib.import_module(name)
