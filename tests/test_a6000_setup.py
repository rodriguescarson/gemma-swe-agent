"""scripts/a6000/setup_wsl.sh: one-time prep of the friend's Windows+WSL2 RTX A6000 box (Carson 2026-10-05).
Written before the script. Runs only in DRY_RUN=1 here (prints, executes nothing)."""
import os, pathlib, re, shutil, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
S = ROOT / "scripts" / "a6000" / "setup_wsl.sh"


def _run(env_extra, tmp_path, proc_version="Linux version 5.15.153.1-microsoft-standard-WSL2"):
    pv = tmp_path / "version"; pv.write_text(proc_version)
    env = dict(os.environ, DRY_RUN="1", PROC_VERSION_FILE=str(pv), SKIP_GPU_CHECK="1", **env_extra)
    return subprocess.run(["bash", str(S)], capture_output=True, text=True, env=env, timeout=60)


def test_syntax_and_strict_mode():
    assert subprocess.run(["bash", "-n", str(S)]).returncode == 0
    assert "set -euo pipefail" in S.read_text()
    if shutil.which("shellcheck"):
        r = subprocess.run(["shellcheck", "-S", "warning", str(S)], capture_output=True, text=True)
        assert r.returncode == 0, r.stdout


def test_refuses_outside_wsl(tmp_path):
    r = _run({}, tmp_path, proc_version="Linux version 6.8.0-45-generic (Ubuntu)")
    assert r.returncode != 0 and "WSL" in (r.stdout + r.stderr)


def test_dry_run_steps_in_order_and_nothing_executed(tmp_path):
    r = _run({}, tmp_path)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    steps = ["automount", "apt-get install", "docker", "authorized_keys", "PasswordAuthentication no", "tailscale up"]
    pos = [out.find(s) for s in steps]
    assert all(p >= 0 for p in pos), list(zip(steps, pos))
    assert pos == sorted(pos), list(zip(steps, pos))
    assert "DRY_RUN" in out


def test_embeds_exactly_one_ed25519_public_key_and_no_secrets():
    t = S.read_text()
    keys = re.findall(r"ssh-ed25519 [A-Za-z0-9+/=]{60,}", t)
    assert len(keys) == 1
    assert "PRIVATE KEY" not in t and "tskey-" not in t and "hf_" not in t and "OPENROUTER" not in t


def test_windows_drives_not_mounted_into_the_sandbox_host(tmp_path):
    out = _run({}, tmp_path).stdout
    assert re.search(r"\[automount\]\s*\n\s*enabled\s*=\s*false", out)
