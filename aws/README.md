# aws/: the EC2 launch kit (distillation plan, Step 5)

One machine per job, in us-east-1. Each machine sets up its environment, runs one job, copies its outputs to S3 and
**terminates itself**. It is ported from the RunPod kit in `pod/` and the A6000 launcher `scripts/a6000/train.sh`.
Nothing here has been launched yet. Every launch needs Carson's go.

| Role | Instance | Hardware | AMI | Root EBS | Default setup |
|---|---|---|---|---|---|
| `cpu-collect` | c7i.xlarge (4 vCPU) or c7i.8xlarge (32 vCPU) | CPU | Ubuntu 24.04 (Canonical SSM parameter) | 120 GB gp3 | docker, data, harness, buildenv |
| `train` | g6e.2xlarge | 1x L40S 48 GB, the A6000 recipe's memory class | Deep Learning Base OSS NVIDIA Driver AMI, Ubuntu 24.04 (SSM) | 250 GB gp3, 500 MB/s | trainenv, bf16 |
| `eval` | g6.12xlarge | 4x L4, the Kaggle scorer's hardware (vLLM TP=4) | same DLAMI | 200 GB gp3, 500 MB/s | docker, data, vllm, model, harness, buildenv |
| `teacher` | g6e.12xlarge (48 vCPU) | 4x L40S 48 GB, plus 2x 1900 GB NVMe for the weights | same DLAMI | 200 GB gp3, 500 MB/s | docker, wheels, harness; the job builds the rest ([G1 teacher pilot](#g1-teacher-pilot)) |

## Costs (us-east-1, on-demand, 24 Oct 2026)

| Instance | $/h | Spot on 24 Oct (`describe-spot-price-history`) |
|---|---|---|
| g6e.12xlarge | 10.49 | $8.51 to $9.24 (81 to 88%) |
| g6.12xlarge | 4.60 | $1.73 in us-east-1f; $3.04 to $4.22 in other AZs |
| g6e.2xlarge | 2.24 | **$2.22 in every AZ: spot saves almost nothing on this type today** |
| c7i.8xlarge | 1.43 | $0.63 to $0.94 |
| c7i.xlarge | 0.18 | about $0.06 |

The usual "spot is 35 to 40% of on-demand" only held for g6.12xlarge in us-east-1f and for the c7i types on 24 Oct.
The on-demand prices were read from the AWS Pricing API on 24 Oct.
`launch.py --spot` prints the live prices and picks the cheapest AZ. On top of the instance price, each machine pays
gp3 EBS (about $0.01 to $0.05/h) and a public IPv4 address ($0.005/h). `launch.py` prints the hourly total and the
ceiling for the timer before anything happens.

## Safety guarantees

`launch.py` builds the exact `RunInstances` request. Then `check_request` reads every property below back from that
request and **refuses the launch if any is missing**, so a future edit can't drop one silently.

1. **`InstanceInitiatedShutdownBehavior=terminate`.** Any OS shutdown ends the instance, so there are no stopped boxes.
   After a real launch the attribute is read back from the live instance, and a mismatch terminates it at once.
2. **The hard timer.** The first command of the user-data is `shutdown -h +N || shutdown -h now`. `--hours` is
   required, has no default and is capped at 24. If the timer can't be set, the machine powers off immediately.
   `bootstrap.sh` re-arms the timer if it ever goes missing, and nothing in the kit cancels it.
3. **The machine stops itself when the job ends**, whether it succeeds, fails or the setup breaks. The bootstrap's
   EXIT trap kills the job's whole process group, syncs the outputs, then runs `shutdown -h now`.
4. **Outputs leave the box before teardown:**
   - every 10 minutes (`--sync-min`);
   - at the 2-minute spot reclaim notice;
   - in a systemd stop hook, so the hard timer and an API terminate still sync;
   - in a final sync, verified the way `pod/backup.sh` verified its upload: a second `aws s3 sync --dryrun` must find
     nothing left to upload.
   S3 writability is proven at boot, before any work: if the bucket or instance profile is wrong, the box stops within
   minutes.
5. **Stalls end the job.** If no output changes for `--stall-min` (default 30) and the GPUs are idle, the job is killed
   and the machine syncs and stops. This ports `pod/supervisor.sh`'s stall alarm; on EC2 it acts instead of only
   alerting.
6. **Tags and cleanup.** `Project=gemma4-agent` and `Role=<role>` go on the instance, its volumes and spot requests.
   Every EBS volume has `DeleteOnTermination=true`.
7. **No keys on the machine.**
   - The machine reaches S3 through the instance profile `gemma4-agent-ec2`. That profile may only list the bucket and
     get or put objects in it: it can't delete anything and has no other AWS permission.
   - IMDSv2 is required with a hop limit of 1, so the test sandboxes in Docker can't read the role's credentials.
   - The Mac's keys (`AWS_ACCESS_KEY` and `AWS_SECRET_KEY` in `~/Projects/.env`) are read in-process by
     `g4aws.session()` and never printed, exported or written.
8. **A dollar cap, if you give one.** `--max-usd N` refuses a launch whose worst case is over N. The worst case is
   the timer multiplied by the highest hourly price the machine can be billed: on-demand, or the spot `MaxPrice`.
9. **No accidental launch or overlap.**
   - Without `--yes`, `launch.py` creates nothing: it runs the read-only preflights and an EC2 `DryRun=True` call.
   - A second live instance of the same role is a blocker unless `--allow-concurrent` is given.
   - The quota check is the kit's own: EC2's DryRun doesn't check vCPU quotas, and it returned "would have
     succeeded" with the G quota at 0.

One trade-off is deliberate. A pod was **stopped** with its disk kept, so `pod/backup.sh` refused to stop it when an
upload failed. An EC2 machine here **terminates** and its EBS goes with it. So the final sync retries for
`--final-sync-min` (default 20 minutes), then the machine stops anyway and logs `ALERT FINAL_SYNC_FAILED`. The periodic
syncs and the boot-time S3 check keep that loss small. Keeping a GPU box up for hours on an upload that won't succeed
would break the other rule: a machine is either working or off.

## One-time setup (Carson's go)

```bash
python aws/account_setup.py
```

That command only shows the plan. To create the bucket (`gemma4-agent-<account id>`, public access blocked, SSE-S3,
tagged) and the role plus instance profile `gemma4-agent-ec2`:

```bash
python aws/account_setup.py --yes
```

Then stage the shared inputs once (from this Mac, keys in-process, sizes verified):

```bash
python aws/stage.py shared s3://gemma4-agent-<acct>/shared data/raw raw
```

```bash
kaggle datasets download metric/gemma-4-developer-agent-wheelhouse -f vllm-0.19.1-cp38-abi3-manylinux_2_31_x86_64.whl -p /tmp/wh
```

```bash
python aws/stage.py shared s3://gemma4-agent-<acct>/shared /tmp/wh/vllm-0.19.1-cp38-abi3-manylinux_2_31_x86_64.whl wheelhouse/vllm-0.19.1-cp38-abi3-manylinux_2_31_x86_64.whl
```

The organiser-patched vLLM wheel adds `SupportsLoRA` to Gemma 4; PyPI's build refuses LoRA. If Kaggle delivers a
`.whl.zip`, unzip it first. The model weights are optional in S3: without `shared/models/g4/`, the machine downloads
`google/gemma-4-31B-it-qat-w4a16-ct` from Hugging Face (Apache-2.0, not gated). The first `train` launch dequantises
the bf16 base and uploads it to `shared/models/g4-bf16/` for every later run.

Also still needed:
- **GPU quota.** On 24 Oct both 52-vCPU G-family requests (on-demand L-DB2E81BA and spot L-3819A6DF) were
  `CASE_OPENED` at quota 0. The 32-vCPU standard on-demand request (L-1216C47A) was open at quota 8, so c7i.xlarge fits
  today and c7i.8xlarge doesn't.
- **Optional:** activate `Project` as a cost allocation tag (Billing, then Cost allocation tags) so
  `cost.py --project` works.

## A run

S3 layout per run:

| S3 path | What it holds |
|---|---|
| `s3://B/runs/<id>/in/code.tgz` | `git archive` of a commit, unpacked to `/root/g4` |
| `s3://B/runs/<id>/in/overlay/<path>` | job inputs at their repo paths, e.g. `runs/train_d1/seqs.jsonl` |
| `s3://B/runs/<id>/out/box/<instance-id>/` | `boot.log`, `progress.log`, `job.out`, `RESULT` (exit code and times), `INSTANCE` |
| `s3://B/runs/<id>/out/keep/<path>` | the role's keep paths, e.g. `runs/`, `eval/runs/` |

A relaunch of the same `--run` pulls `keep/` back first, so a spot-reclaimed training run resumes from its last synced
checkpoint (`train.sh full` is resumable), and `p2_race` skips the items it already finished.

```bash
python aws/stage.py code s3://B/runs/d1
```

```bash
python aws/stage.py put s3://B/runs/d1 runs/train_d1/seqs.jsonl runs/train_d1/holdout.jsonl
```

```bash
python aws/launch.py train --hours 10 --run s3://B/runs/d1 --job 'bash aws/train.sh full d1'
```

That third command is the dry run. Read its plan, then repeat it with `--yes` to launch.

```bash
python aws/status.py
```

```bash
python aws/stage.py fetch s3://B/runs/d1
```

`status.py` shows uptime, $/h, $ so far and hours left on the timer. `fetch` downloads `out/` to `eval/aws/d1/`.

Example jobs:
- **cpu-collect:** `--job 'bash scripts/collect/collect.sh v12b data/distill/train_ids.txt t1'`. The collector's
  upstream is the sibling session's work: Bedrock was ruled out by AWS's terms (commit 1c0d1a0c). If Bedrock is cleared
  later, note that `BedrockEndpoint` reads static keys and would need the default boto3 credential chain on EC2.
- **train:** `--job 'bash aws/train.sh full d1'`. This is `scripts/a6000/train.sh` with the same recipe, run in the
  foreground. It succeeds only when `summary.json` exists.
- **eval:** `--job 'bash pod/serve.sh && bash aws/preflight.sh submissions/v12b && python scripts/a6000/p2_race.py …'`
  - `pod/serve.sh` runs unchanged and gives TP=4 on the 4 GPUs.
  - Set `LORA_GATE=0` in `aws/preflight.sh` once the main server holds the GPUs, or run the gate before `serve.sh`.
  - Use `p2_race` with the pace proxy's `--rewrite-model`; `p3_run.py` routes adapter calls to the base model
    (plan, "Fix first").

Stopping early: `python aws/teardown.py <id>` lists what would be terminated, and adding `--yes` terminates it. You can
also select by `--role ROLE` or `--all`. The script only touches `Project=gemma4-agent` instances and waits until
`describe-instances` shows them terminated. Outputs written since the last periodic sync may be lost. Never stop a
working machine without Carson's go.

Bills: `python aws/cost.py --days 7` gives daily cost by service, with credits, tax and the cash left after credits
shown separately. It flags any day with cash charged, which is the plan's "no GST in cash" check. Cost Explorer charges
**$0.01 per request**, one per result page.

## G1 teacher pilot

This is the first job, pre-registered in `docs/GAPS_2026-10-06.md` ("G1 pre-registration"). Two open teachers (both
Apache-2.0, neither gated on Hugging Face, so no token is needed) solve the 30 G1 tasks through the unchanged harness.
[aws/jobs/g1_teacher.sh](jobs/g1_teacher.sh) runs on one g6e.12xlarge:

1. **Weights on NVMe.** It mounts the NVMe instance store at `/opt/dlami/nvme`, or formats the first disk if the DLAMI
   didn't mount it, and downloads both teachers from Hugging Face there. gpt-oss skips its duplicate `original/` and
   `metal/` folders (130 GB down to 65 GB). Devstral's weights are FP8, about 26 GB per copy.
2. **Its own vLLM.** It installs vLLM **0.31.0** in `/root/tvllm`, with `mistral_common>=1.8.6` as the Devstral card asks.
   This is **not** the scorer's patched 0.19.1, which stays Gemma-only in `/root/venv`. 0.32.0 is newer but was 6 days
   old on 24 Oct; set `TEACHER_VLLM` to change the version.
3. **A scratch bundle.** It copies v12b to `/opt/g4/scratch/g1_v12b_t20` with only `max_time_minutes: 20` and
   `max_tool_calls: 100` changed (`aws/jobs/g1_race.py bundle`). The script refuses any destination under
   `submissions/`.
4. **Two servers:**
   - Devstral-Small-2-24B-Instruct-2512 on GPU0: TP1, `--tool-call-parser mistral --enable-auto-tool-choice`, port 8101.
   - gpt-oss-120b on GPUs 2-3: TP2, `--tool-call-parser openai --enable-auto-tool-choice --reasoning-parser openai_gptoss`,
     port 8102.
5. **One proxy per teacher:**
   `scripts/or_proxy.py --upstream vllm --base http://127.0.0.1:<port>/v1 --model <served name> --capture eval/g1/capture_<teacher>.jsonl --max-usd 1000`,
   on ports 8201 and 8202. Each teacher gets an uncaptured `--probe` call first.
6. **Both races in parallel.** [aws/jobs/g1_race.py](jobs/g1_race.py) is `p2_race.py`'s container and item script,
   held byte-equal by a test, except the bundle comes from the read-only `/scratch` mount. Each teacher runs 6 tasks at
   a time with no pacing. Results go to `eval/g1/<teacher>/items/g1_v12b_t20/<task>/task_results.jsonl`, the layout
   `scripts/distill/usable.py` reads.
7. **Status, then shutdown.** It writes `eval/g1/status.json`: per teacher whether it ran, its result and resolved
   counts and capture rows, plus an EC2 $ estimate. `bootstrap.sh` then syncs `eval/g1` to S3 and the machine
   terminates itself.

If a teacher's download, server or probe fails, the job skips that teacher and records it; it fails only when no
teacher ran.

Steps:

```bash
python aws/account_setup.py --yes
```

```bash
python aws/jobs/g1_stage.py --run s3://B/runs/g1 --ref wip/gemma-agent
```

That shows the plan only. It builds the 30-task subset of `data/heldout1k/harness_all` (tasks.jsonl, ids.txt,
env.json, the 30 snapshots byte-identical and the whole `wheels/` directory, about 368 MB; no graphs or embeddings).
It also lists `code.tgz` and `shared/raw/wheels` (27 MB). The ref must contain `aws/jobs/g1_teacher.sh`, so commit
`aws/` first. Repeat it with `--upload` to send the files.

```bash
python aws/launch.py teacher --hours 3.75 --max-usd 40 --run s3://B/runs/g1 --job 'bash aws/jobs/g1_teacher.sh'
```

That is the dry run. Once the G-family quota is granted (48 of the 52 requested vCPU), repeat it with `--yes`.

```bash
python aws/stage.py fetch s3://B/runs/g1
```

Then score on the Mac with `scripts/distill/usable.py`, passing `--ec2-usd` from `status.json` or `aws/cost.py`.

**Autorun (installed 24 Oct, 17:16 IST, deadline 27 Oct 17:16 IST).** [aws/jobs/g1_autorun.sh](jobs/g1_autorun.sh) is a
launchd agent that runs one short tick every 10 minutes, so it survives app restarts and reboots:
- Once at least 48 G-family vCPU are granted, it launches the pilot once with the line above (`--yes`). It uses
  on-demand, or spot if only spot is granted, and tries each zone if one has no capacity.
- When the box has terminated itself, it downloads `out/` to `eval/aws/g1/`, runs `usable.py` per teacher (writing
  `eval/aws/g1/usable_<teacher>.json`), shows a macOS notification and removes itself.
- It also removes itself at the deadline, or after 3 launch refusals that aren't capacity errors.
- It never terminates an instance.
- State and log are in `~/.local/state/g4-g1-autorun/`.

```bash
bash aws/jobs/g1_autorun.sh status
```

```bash
bash aws/jobs/g1_autorun.sh uninstall
```

**The 5 h timer and the $40 cap don't fit together.** g6e.12xlarge is $10.49/h on-demand, so 5 h can bill $52.70.
`--max-usd 40` refuses that and suggests 3.75 h ($39.53 worst case). Spot was $8.51 to $9.24 on 24 Oct, but its
default `MaxPrice` is the on-demand price, so its worst case is the same. The expected run is about 2 to 2.5 h:
- about 20 minutes of setup (venv, roughly 90 GB of weights, the container);
- vLLM load times;
- at most 5 waves of 20 minutes per teacher.

**Not yet verified on hardware:**
- whether vLLM 0.31.0 serves gpt-oss-120b's MXFP4 weights on L40S (Ada, sm_89);
- the exact Devstral and gpt-oss parser behaviour behind or_proxy.

The job's probe step catches both before any task runs. Devstral on one L40S keeps about 15 GB for its KV cache, which
6 concurrent long trajectories can exhaust. GPU1 is idle in this layout, so `DEVSTRAL_GPUS=0,1 DEVSTRAL_TP=2` (or
`DEVSTRAL_EXTRA="--kv-cache-dtype fp8"`) is the lever if Devstral queues.

## What came from where

The box keeps the pod's directory layout (`/root/g4`, `/root/venv`, `/root/hvenv`, `/root/buildenv`,
`/root/models/g4`, `/wheels`), so most of `pod/` runs on EC2 unchanged.

| RunPod kit | EC2 kit |
|---|---|
| `pod/bootstrap.sh` (env, model, Kaggle data) | `aws/bootstrap.sh` setup steps: the same patched vLLM and pins, with the wheel and `data/raw` from S3 instead of the Kaggle CLI (no Kaggle token on the box) |
| `pod/harness_env.sh`, `pod/buildenv.sh` | reused unchanged (`setup_harness`, `setup_buildenv`) |
| `pod/serve.sh`, `pod/run_eval.sh`, `pod/canary.sh` | reused unchanged |
| `pod/health.sh` (one server per GPU) | `aws/health.sh` (one TP=4 server; `SERVE_PORTS`) |
| `pod/preflight.sh` | `aws/preflight.sh`: the same 6 gates; S3 proof replaces `hf auth whoami` |
| `pod/backup.sh` (private HF dataset, size check) | `bootstrap.sh sync`: S3, verified by a dry-run sync |
| `pod/supervisor.sh` (idle stop, stall alert, `MAX_HOURS`) | the EXIT trap (idle = job over), the stall rule, and the hard timer |
| `scripts/a6000/train.sh` (backgrounds the trainer) | `aws/train.sh`: same subcommands and recipe, foreground |
| `runpodctl stop pod` | `shutdown -h now` with `InstanceInitiatedShutdownBehavior=terminate` |

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_aws_launch.py tests/test_aws_teacher.py tests/test_aws_bootstrap_e2e.py tests/test_aws_g1_job_e2e.py
```

- **`test_aws_launch.py`** stubs boto3 and covers:
  - each role's request and each refusal path, including `check_request` against 19 single-property mutations;
  - the `--yes` and blocker paths, credentials, teardown, status and cost;
  - `bash -n` and shellcheck on every script.
- **`test_aws_bootstrap_e2e.py`** runs the real generated user-data as root in `python:3.12-slim`, with fake `aws`,
  `shutdown` and `curl`. It covers success, job failure, S3 down, resume, SIGTERM mid-job, and the stall rule (about
  2 minutes). It needs Docker and skips without it.
- **`test_aws_teacher.py`** covers:
  - the teacher role and the `--max-usd` cap (5 h at $40 is refused, 3.75 h passes);
  - the scratch bundle (only the two caps change; `submissions/` is refused and left untouched);
  - `g1_race` against `p2_race` (byte-equal item script), and race and resume against a fake docker;
  - the 30-task subset built from the real `harness_all`, and verified S3 uploads;
  - static rules on the job.
- **`test_aws_g1_job_e2e.py`** runs the real `g1_teacher.sh` in Docker with the repo mounted read-only. It uses fake
  GPUs, `hf`, vLLM servers and docker, while the real `or_proxy` captures. It covers one teacher dying while the other
  completes, and no teacher at all (exit 1).
