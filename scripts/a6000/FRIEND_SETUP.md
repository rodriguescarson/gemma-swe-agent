A6000 SETUP, about 20 minutes, one time only
=============================================

Send your friend steps 1 to 5 and the file setup_wsl.sh. You (Carson) do the part at the bottom.

WHAT THIS DOES TO THE PC
- Runs inside WSL (a Linux layer that comes with Windows). Nothing is installed into Windows itself except WSL.
- The Linux side is cut off from the Windows drives, so nothing that runs there can see their files.
- Only Carson's computer can log in (one SSH key, passwords off), over a private Tailscale link.
- It uses the GPU when Carson runs jobs. To stop everything at any time: in PowerShell, run  wsl --shutdown
- To remove it all later:  wsl --unregister Ubuntu-24.04

FOR YOUR FRIEND
1. Update the NVIDIA driver (GeForce Experience / NVIDIA App, or nvidia.com/drivers, RTX A6000).
2. Open PowerShell as Administrator and run:
       wsl --install -d Ubuntu-24.04
   Restart if asked. When Ubuntu opens, pick a user name and password.
3. In the Ubuntu window, check the GPU shows up:
       nvidia-smi
   It should list "NVIDIA RTX A6000". If not, redo step 1, then run "wsl --shutdown" in PowerShell and reopen Ubuntu.
4. Save setup_wsl.sh into Windows Downloads, then in Ubuntu run (put the Windows user name in place of NAME):
       bash /mnt/c/Users/NAME/Downloads/setup_wsl.sh
   It asks for the Ubuntu password once. At the end it prints a Tailscale login link.
5. Send Carson that link and the Ubuntu user name. Then in PowerShell run:  wsl --shutdown  and reopen Ubuntu.
   While jobs run: keep the Ubuntu window open (minimised), and set Windows sleep to "Never".

FOR CARSON
a. Install Tailscale on the Mac (tailscale.com/download, free) and sign in.
b. Open your friend's link while signed in. That adds the PC to your private network as "a6000".
c. Tell Claude "a6000 is up, user is <name>". Claude then checks the connection, installs the competition's own
   software build, downloads the model (about 23 GB), and runs a 5-task speed test before any big run.
