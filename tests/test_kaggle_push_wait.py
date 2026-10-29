"""scripts/kaggle_push_wait.sh <slug>: push kernels/<slug>, poll the kernel named by its kernel-metadata.json id (NOT the
directory name: a pinned rebuild writes id=carsonrodrigues/g4-l4-v4 under kernels/g4-l4-lora-probe-p312/), and fetch the
output into eval/kaggle/<slug>/. Written before the script (docs/PLAN_TO_FINISH.txt rule)."""
import json, os, pathlib, subprocess

import pytest

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
                    ' s=$(sed -n "${n}p" "$FAKE_STATUSES"); [ -z "$s" ] && s=$(tail -1 "$FAKE_STATUSES");'
                    ' if [ "$s" = EMPTY ]; then echo ConnectionError >&2; else echo "$3 has status \\"KernelWorkerStatus.$s\\""; fi;;\n'
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


def _status_calls(tmp):
    return (tmp / "calls.log").read_text().count("kernels status")


def test_gives_up_after_ten_empty_status_reads_in_a_row(tmp_path):
    # a dead CLI or network used to loop here forever: every read returned nothing and nothing was "COMPLETE"
    env = _setup(tmp_path, "k", "k", ["RUNNING", "EMPTY"])          # one real status, then nothing for ever
    r = subprocess.run(["bash", str(SCRIPT), "k"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "10 status reads in a row returned nothing" in r.stdout, r.stdout + r.stderr
    assert _status_calls(tmp_path) == 11 and "kernels output" not in (tmp_path / "calls.log").read_text()


def test_a_real_status_resets_the_empty_read_count(tmp_path):
    env = _setup(tmp_path, "k", "k", ["EMPTY"] * 9 + ["RUNNING"] + ["EMPTY"] * 9 + ["COMPLETE"])
    r = subprocess.run(["bash", str(SCRIPT), "k"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "COMPLETE" in r.stdout, r.stdout + r.stderr
    assert _status_calls(tmp_path) == 20


def test_the_empty_read_limit_is_configurable(tmp_path):
    env = _setup(tmp_path, "k", "k", ["EMPTY"]); env["PUSH_EMPTY_MAX"] = "3"
    r = subprocess.run(["bash", str(SCRIPT), "k"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "3 status reads in a row returned nothing" in r.stdout and _status_calls(tmp_path) == 3


def test_gives_up_when_no_final_status_arrives_within_push_max_s(tmp_path):
    # a kernel that stays RUNNING must not hold a chain beyond the run deadline
    # 2 s, not 1: the script's clock is whole seconds (`date +%s`), so a 1 s limit can pass after a few milliseconds
    env = _setup(tmp_path, "k", "k", ["RUNNING"]); env.update(PUSH_MAX_S="2", PUSH_POLL_S="0.2")
    r = subprocess.run(["bash", str(SCRIPT), "k"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "no final status within PUSH_MAX_S=2s of the first RUNNING status (last: KernelWorkerStatus.RUNNING)" in r.stdout, r.stdout + r.stderr
    assert 2 <= _status_calls(tmp_path) <= 60 and "kernels output" not in (tmp_path / "calls.log").read_text()


# ---- the limits, on a fake clock: `date +%s` and `sleep` read and advance one counter, so a 14 h or 48 h wait takes no time
# and no test depends on where in the second it starts. Each status read is one POLL (PUSH_POLL_S) after the previous one.

T_START = 1_000_000


def _clock(tmp, env, poll):
    b = tmp / "clockbin"; b.mkdir()
    (b / "date").write_text('#!/bin/bash\ncase "$1 $2" in "+%s "|"-u +%s") cat "$FAKE_CLOCK"; exit 0;; esac\nexec /bin/date "$@"\n')
    (b / "sleep").write_text('#!/bin/bash\necho $(( $(cat "$FAKE_CLOCK") + ${1%.*} )) > "$FAKE_CLOCK"\n')
    for f in b.iterdir():
        f.chmod(0o755)
    (tmp / "clock").write_text(str(T_START))
    env.update(PATH=f"{b}:{env['PATH']}", FAKE_CLOCK=str(tmp / "clock"), PUSH_POLL_S=str(poll))
    return env


def _timed(tmp, statuses, poll, **limits):
    env = _clock(tmp, _setup(tmp, "k", "k", statuses), poll); env.update({k: str(v) for k, v in limits.items()})
    r = subprocess.run(["bash", str(SCRIPT), "k"], cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
    return r, _status_calls(tmp)


def test_a_long_queue_does_not_count_against_the_run_deadline(tmp_path):
    # GPU kernels sit QUEUED for about 10 h and then run for hours: the old 14 h clock started at the push and gave up on a
    # kernel that was still going to finish, and a rerun of the sequence then pushed a second billed GPU session
    r, n = _timed(tmp_path, ["QUEUED"] * 40 + ["RUNNING"] * 3 + ["COMPLETE"], poll=300, PUSH_MAX_S=3600)    # 11,700 s queued, 900 s running
    assert r.returncode == 0 and "COMPLETE" in r.stdout and n == 44, r.stdout + r.stderr
    assert "kernels output" in (tmp_path / "calls.log").read_text()


def test_the_run_deadline_counts_from_the_first_running_status(tmp_path):
    # 5 QUEUED reads, then RUNNING for ever: 3,600 s after the first RUNNING read is 12 more polls, so the 18th read is the last
    r, n = _timed(tmp_path, ["QUEUED"] * 5 + ["RUNNING"], poll=300, PUSH_MAX_S=3600)
    assert r.returncode == 1 and "no final status within PUSH_MAX_S=3600s of the first RUNNING status (last: KernelWorkerStatus.RUNNING)" in r.stdout, r.stdout
    assert n == 18 and "kernels output" not in (tmp_path / "calls.log").read_text()


def test_the_total_cap_counts_queue_time(tmp_path):
    # a kernel that never leaves the queue has no RUNNING status, so only the total cap can end the wait
    r, n = _timed(tmp_path, ["QUEUED"], poll=300, PUSH_TOTAL_MAX_S=3600, PUSH_MAX_S=600)
    assert r.returncode == 1 and "no final status after PUSH_TOTAL_MAX_S=3600s since the push, queue included (last: KernelWorkerStatus.QUEUED)" in r.stdout, r.stdout
    assert n == 13 and "PUSH_MAX_S" not in r.stdout and "kernels output" not in (tmp_path / "calls.log").read_text()


def test_the_total_cap_also_ends_a_run_that_outlasts_its_own_deadline_budget(tmp_path):
    r, n = _timed(tmp_path, ["QUEUED"] * 4 + ["RUNNING"], poll=300, PUSH_TOTAL_MAX_S=3000, PUSH_MAX_S=100000)
    assert r.returncode == 1 and "PUSH_TOTAL_MAX_S=3000s" in r.stdout and n == 11, r.stdout


def test_the_default_run_deadline_is_14_hours_from_running(tmp_path):
    r, n = _timed(tmp_path, ["QUEUED"] * 3 + ["RUNNING"], poll=3600)           # hourly reads: RUNNING first seen at read 4, 14 reads later is 50,400 s
    assert r.returncode == 1 and "PUSH_MAX_S=50400s of the first RUNNING status" in r.stdout and n == 3 + 1 + 14, r.stdout


def test_the_default_total_cap_is_48_hours(tmp_path):
    r, n = _timed(tmp_path, ["QUEUED"], poll=3600)
    assert r.returncode == 1 and "PUSH_TOTAL_MAX_S=172800s since the push" in r.stdout and n == 49, r.stdout


@pytest.mark.parametrize("limit", ["PUSH_MAX_S", "PUSH_TOTAL_MAX_S"])
def test_zero_disables_a_time_limit(tmp_path, limit):
    # 0 is "no limit", as in submit_at.sh (PENDING_DEADLINE_EPOCH=0), not "give up at once": the other limit still ends the wait
    other = {"PUSH_MAX_S": "PUSH_TOTAL_MAX_S", "PUSH_TOTAL_MAX_S": "PUSH_MAX_S"}[limit]
    r, n = _timed(tmp_path, ["RUNNING"] * 20 + ["COMPLETE"], poll=3600, **{limit: 0, other: 0})
    assert r.returncode == 0 and "COMPLETE" in r.stdout and n == 21, r.stdout      # 20 h running: past neither default, both off
    (tmp_path / "b").mkdir()
    r2, n2 = _timed(tmp_path / "b", ["RUNNING"] * 100, poll=3600, **{limit: 0})    # one off, the other left at its default
    # RUNNING from the first read: the 14 h run deadline is the 15th read, the 48 h total cap the 49th
    assert r2.returncode == 1 and f"{other}=" in r2.stdout and f"{limit}=" not in r2.stdout and n2 == {"PUSH_MAX_S": 49, "PUSH_TOTAL_MAX_S": 15}[limit], r2.stdout


def test_zero_disables_the_empty_read_limit(tmp_path):
    r, n = _timed(tmp_path, ["EMPTY"] * 30 + ["COMPLETE"], poll=300, PUSH_EMPTY_MAX=0)
    assert r.returncode == 0 and "COMPLETE" in r.stdout and n == 31, r.stdout


def test_a_final_status_inside_the_deadline_still_wins(tmp_path):
    env = _setup(tmp_path, "k", "k", ["QUEUED", "RUNNING", "COMPLETE"]); env["PUSH_MAX_S"] = "30"
    r = subprocess.run(["bash", str(SCRIPT), "k"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "COMPLETE" in r.stdout and "kernels output" in (tmp_path / "calls.log").read_text()
