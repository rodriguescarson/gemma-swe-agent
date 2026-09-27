"""submit_at.sh must never double-submit when two machines are armed."""
import os, subprocess, datetime, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "submit_at.sh"


def _fake_kaggle(tmp, existing):
    calls = tmp / "calls.txt"
    fake = tmp / "kaggle"
    fake.write_text(f"""#!/bin/bash
echo "$@" >> {calls}
if [ "$2" = submissions ]; then
  echo 'ref,fileName,date,description,status'
  {"".join(f'echo \'1,submission.zip,d,"{d}",COMPLETE\';' for d in existing)}
  exit 0
fi
echo "Successfully submitted"
""")
    fake.chmod(0o755)
    return fake, calls


def _run(tmp, existing, msg):
    fake, calls = _fake_kaggle(tmp, existing)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%H%M")
    env = dict(os.environ, KAGGLE_BIN=str(fake), SUBMIT_LOG=str(tmp / "log.txt"))
    subprocess.run(["bash", str(SCRIPT), "k", now, msg], env=env, check=True, timeout=60)
    return [l for l in calls.read_text().splitlines() if l.startswith("competitions submit ")]


def test_skips_when_tag_already_on_kaggle(tmp_path):
    assert _run(tmp_path, ["sub3: v4 staged"], "sub3: v4 staged") == []


def test_submits_once_when_absent(tmp_path):
    assert len(_run(tmp_path, ["sub2: older"], "sub3: v4 staged")) == 1
