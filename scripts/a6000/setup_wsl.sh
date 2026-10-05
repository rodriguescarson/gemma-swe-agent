#!/usr/bin/env bash
# One-time prep of the RTX A6000 box (Windows 11 + WSL2 Ubuntu) so Carson's Mac can run Gemma-4 evals on it.
# Run INSIDE the Ubuntu (WSL) window, as the normal user (it asks for sudo):   bash setup_wsl.sh
# What it does, in order:
#   1. checks it is WSL2 with the GPU visible (nvidia-smi)
#   2. stops WSL from mounting the Windows drives (C:, D:) into this Linux, so nothing run here can see Windows files
#   3. installs git, curl, docker, openssh-server
#   4. lets ONE key (Carson's Mac) log in over SSH, passwords off
#   5. installs Tailscale and prints a login link: send that link to Carson; he approves it, then he can connect
# It installs nothing on Windows itself and stores no passwords or API keys. DRY_RUN=1 prints the steps only.
set -euo pipefail
CARSON_KEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG9+26/m1wL6Q7liQ38/TPWR8vVH8uRws5wQhbt5/w1P carson-mac"
PROC_VERSION_FILE=${PROC_VERSION_FILE:-/proc/version}
DRY_RUN=${DRY_RUN:-0}
run() { if [ "$DRY_RUN" = 1 ]; then echo "DRY_RUN: $*"; else echo "+ $*"; bash -c "$*"; fi; }

grep -qi microsoft "$PROC_VERSION_FILE" || { echo "This is not WSL2 Ubuntu. Open the Ubuntu app on Windows and run it there." >&2; exit 1; }
if [ "${SKIP_GPU_CHECK:-0}" != 1 ]; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || {
    echo "GPU not visible in WSL. Update the NVIDIA driver on Windows (Game Ready or Studio, 2025 or newer), then run: wsl --shutdown" >&2; exit 1; }
fi

echo "== 2. keep Windows drives out of this Linux"
WSL_CONF=$'[automount]\nenabled = false\nmountFsTab = false\n\n[boot]\nsystemd = true\n'
if [ "$DRY_RUN" = 1 ]; then printf 'DRY_RUN: write /etc/wsl.conf:\n%s' "$WSL_CONF"; else printf '%s' "$WSL_CONF" | sudo tee /etc/wsl.conf; fi

echo "== 3. packages"
run "sudo apt-get update -y && sudo apt-get install -y git curl ca-certificates build-essential openssh-server docker.io"
run "sudo usermod -aG docker \$USER && sudo systemctl enable --now docker"

echo "== 4. SSH: Carson's key only, no passwords"
run "mkdir -p ~/.ssh && chmod 700 ~/.ssh && (grep -qF '$CARSON_KEY' ~/.ssh/authorized_keys 2>/dev/null || echo '$CARSON_KEY' >> ~/.ssh/authorized_keys) && chmod 600 ~/.ssh/authorized_keys"
run "printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n' | sudo tee /etc/ssh/sshd_config.d/99-keyonly.conf && sudo systemctl enable --now ssh"

echo "== 5. Tailscale (private network link to Carson's Mac)"
run "command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh"
run "sudo tailscale up --hostname=a6000"
echo
echo "Done. Send Carson: (a) the login link Tailscale printed above, (b) your Linux user name: $(whoami)."
echo "Then, in Windows PowerShell, run once:  wsl --shutdown   and reopen Ubuntu (applies step 2)."
echo "Keep this Ubuntu window open (minimised) and Windows sleep set to Never while runs are going."
