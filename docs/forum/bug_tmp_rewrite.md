# Forum post 1: the sandbox rewrites /tmp in command text but not in skill scripts

Title: Skill scripts that write to /tmp are invisible to run_command (the subprocess sandbox rewrites the path)

Body (plain text):

If your skill installs helper scripts under /tmp and the agent then calls them with run_command, the calls fail on the scorer with "can't open file". The two sides see different directories.

What happens (swegemma/sandbox/subprocess.py, around lines 432-481): the subprocess sandbox rewrites the literals /tmp, /workspace, /usr/local/bin and /wheels in every run_command string, including heredoc bodies and python -c source, to its own per-task root (for example <root>/tmp). It does not rewrite the source of skill scripts run through run_skill_script, nor file contents written with write_file or edit_file. So a skill script that does os.makedirs("/tmp/swe") writes to the real /tmp, while `python3 /tmp/swe/x.py` in run_command is rewritten to <root>/tmp/swe/x.py, which does not exist.

Measured on our own Kaggle 4xL4 faithful runs: 137 of 157 helper calls failed this way in one run, 164 of 177 in another. The Docker backend does no rewriting, so local Docker runs never show it.

Workaround inside a skill script: write to os.environ.get("TEST_TMPDIR") or os.environ.get("TMPDIR") (or tempfile.gettempdir()) instead of a literal /tmp, so the file lands where the rewritten command will look. If the organisers can either rewrite skill-script paths the same way or document this, it would save others the week it cost us.
