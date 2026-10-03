"""scripts/kaggle_push_wait.sh <slug>: push kernels/<slug>, poll the kernel named by its kernel-metadata.json id (NOT the
directory name: a pinned rebuild writes id=carsonrodrigues/g4-l4-v4 under kernels/g4-l4-lora-probe-p312/), and fetch the
output into eval/kaggle/<slug>/. Written before the script (docs/PLAN_TO_FINISH.txt rule)."""
import json, os, pathlib, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kaggle_push_wait.sh"


def _setup(tmp, slug, kid, statuses):
    kd = tmp / "kernels" / slug; kd.mkdir(parents=True)
    (kd / "kernel-metadata.json").write_text(json.dumps({"id": "carsonrodrigues/" + kid, "code_file": kid + ".ipynb", "enable_gpu": True}))
    (kd / (kid + ".ipynb")).write_text("{}")
    fake = tmp / "kaggle"
    fake.write_text('#!/bin/bash\n[ "$1" = --version ] && { echo "Kaggle CLI ${FAKE_CLI_VERSION:-2.2.4}"; exit 0; }\necho "$@" >> "$FAKE_LOG"\n'
                    'case "$1 $2" in\n'
                    '  "kernels push") echo "Kernel version 7 successfully pushed";;\n'
                    '  "kernels status") n=$(cat "$FAKE_COUNT" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$FAKE_COUNT";'
                    ' s=$(sed -n "${n}p" "$FAKE_STATUSES"); [ -z "$s" ] && s=$(tail -1 "$FAKE_STATUSES"); echo "$3 has status \\"KernelWorkerStatus.$s\\"";;\n'
                    '  "kernels output") mkdir -p "$5"; echo "{}" > "$5/lora_probe.json";;\n'
                    'esac\n')
    fake.chmod(0o755)
    (tmp / "statuses.txt").write_text("\n".join(statuses) + "\n")
    env = dict(os.environ, KAGGLE_BIN=str(fake), FAKE_LOG=str(tmp / "calls.log"), FAKE_COUNT=str(tmp / "count"),
               FAKE_STATUSES=str(tmp / "statuses.txt"), PUSH_POLL_S="0", PUSH_SETTLE_S="0")
    return env


def test_polls_the_metadata_id_and_fetches_output_under_the_slug(tmp_path):
    env = _setup(tmp_path, "g4-l4-lora-probe-p312", "g4-l4-v4", ["QUEUED", "RUNNING", "COMPLETE"])
    r = subprocess.run(["bash", str(SCRIPT), "g4-l4-lora-probe-p312"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    calls = (tmp_path / "calls.log").read_text()
    assert r.returncode == 0, r.stdout + r.stderr
    # 2026-10-03: a push without --accelerator ran the 4xL4 probe on 2xT4 (vLLM refused bf16); the metadata's
    # machine_shape is ignored by every CLI, only the 2.x CLI's --accelerator flag selects the machine
    assert "kernels push -p kernels/g4-l4-lora-probe-p312 --accelerator NvidiaL4" in calls
    assert "kernels status carsonrodrigues/g4-l4-v4" in calls and "carsonrodrigues/g4-l4-lora-probe-p312" not in calls
    assert "kernels output carsonrodrigues/g4-l4-v4 -p eval/kaggle/g4-l4-lora-probe-p312" in calls
    assert (tmp_path / "eval" / "kaggle" / "g4-l4-lora-probe-p312" / "lora_probe.json").exists()
    assert "COMPLETE" in r.stdout


def test_error_status_is_reported_and_nonzero(tmp_path):
    env = _setup(tmp_path, "k", "k", ["RUNNING", "ERROR"])
    r = subprocess.run(["bash", str(SCRIPT), "k"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "ERROR" in r.stdout


def test_skips_when_output_already_present(tmp_path):
    env = _setup(tmp_path, "k", "k", ["COMPLETE"])
    out = tmp_path / "eval" / "kaggle" / "k"; out.mkdir(parents=True); (out / "results.jsonl").write_text("{}\n")
    r = subprocess.run(["bash", str(SCRIPT), "k"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "skip" in r.stdout and not (tmp_path / "calls.log").exists()


def test_pushes_exactly_once_and_a_failed_push_is_nonzero(tmp_path):
    env = _setup(tmp_path, "k", "k", ["COMPLETE"])
    r = subprocess.run(["bash", str(SCRIPT), "k"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and (tmp_path / "calls.log").read_text().count("kernels push") == 1
    env2 = _setup(tmp_path / "b", "k", "k", ["COMPLETE"])
    (tmp_path / "b" / "kaggle").write_text('#!/bin/bash\n[ "$1" = --version ] && { echo "Kaggle CLI 2.2.4"; exit 0; }\necho "$@" >> "$FAKE_LOG"\n[ "$1 $2" = "kernels push" ] && echo "403 Forbidden"\n')
    r2 = subprocess.run(["bash", str(SCRIPT), "k"], cwd=tmp_path / "b", env=env2, capture_output=True, text=True, timeout=60)
    assert r2.returncode != 0 and "push FAILED" in r2.stdout and "kernels status" not in (tmp_path / "b" / "calls.log").read_text()


def test_gpu_kernel_refuses_a_1x_cli_and_cpu_kernel_gets_no_accelerator(tmp_path):
    env = _setup(tmp_path, "k", "k", ["COMPLETE"])
    env["FAKE_CLI_VERSION"] = "1.7.4.5"
    r = subprocess.run(["bash", str(SCRIPT), "k"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "Kaggle CLI 2" in r.stdout and not (tmp_path / "calls.log").exists()
    env2 = _setup(tmp_path / "cpu", "c", "c", ["COMPLETE"])
    meta = tmp_path / "cpu" / "kernels" / "c" / "kernel-metadata.json"
    meta.write_text(json.dumps({"id": "carsonrodrigues/c", "code_file": "c.ipynb", "enable_gpu": False}))
    r2 = subprocess.run(["bash", str(SCRIPT), "c"], cwd=tmp_path / "cpu", env=env2, capture_output=True, text=True, timeout=60)
    assert r2.returncode == 0 and "--accelerator" not in (tmp_path / "cpu" / "calls.log").read_text()
