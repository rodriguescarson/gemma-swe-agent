# The Mac <-> A6000 box channel (through git, since 2026-10-12)

Two Claude Code sessions work on this repo: one on the owner's Mac (plans, code, tests, Kaggle) and one on the A6000 box
(GPU runs). Until 2026-10-12 the owner relayed every message between them by hand. From now on they talk through two
append-only files on branch `wip/gemma-agent`, and the owner only watches:

| file | written by | read by |
|---|---|---|
| `docs/a6000/channel/mac_to_box.md` | the Mac (`M-001`, `M-002`, ...) | the box |
| `docs/a6000/channel/box_to_mac.md` | the box (`B-001`, `B-002`, ...) | the Mac |

`scripts/a6000/channel.sh` does all of it (the side is detected: WSL = box, otherwise Mac; `CHANNEL_SIDE=` overrides):

```
bash scripts/a6000/channel.sh send "<text>" [--re M-003]   # append my next message (or send @file.md), commit, pull --rebase, push
bash scripts/a6000/channel.sh read                         # pull; print the other side's messages I have not seen
bash scripts/a6000/channel.sh wait [secs] [max_min]        # poll origin every 180 s (up to 720 min) until the other side wrote; print it
bash scripts/a6000/channel.sh pending                      # their message ids I have not answered with a "re:"
bash scripts/a6000/channel.sh tail [n]                     # the last n messages of each file
```

## Rules

1. **Everything the other side needs goes in the message**: numbers verbatim, file paths, commit hashes, the verdict lines
   whole. A message is the report that used to be pasted; the log files (P2_LOG.md, GATE.md) are still written as before.
2. **Answer by id**: a reply carries `--re <id>`. `pending` lists what is still unanswered on your side; answer the oldest first.
3. **One message per stop point** (a gate passed or failed, a verdict, an hourly line during a run, a question). Never block on
   a question when the pre-registered rule already decides it; ask only when the rule is silent, and say what you will do
   meanwhile (usually: keep the GPU working or keep waiting).
4. **Waiting is cheap**: when you need the other side, run `wait` (re-run it when it times out). A run that is in progress
   keeps running; report its hourly line, then `wait` again.
5. **Never edit the files by hand, never rewrite history, never put secrets or the owner's name in them.** The files are
   append-only; `send` commits only its own file, so both sides can push without conflicts.
6. **Everything else is unchanged**: branch `wip/gemma-agent` only, never main, never --no-verify, pull --rebase --autostash
   before every push, weights and data never in git, the pre-registered gates in docs/a6000/TRAIN_LOCAL.md and GAPS rule.

## Box side, standing loop

```
bash scripts/a6000/channel.sh read          # new instructions?
... do the work, writing P2_LOG / GATE as the section says ...
bash scripts/a6000/channel.sh send "@report.md" --re M-00n
bash scripts/a6000/channel.sh wait          # until the Mac answers (poll every 3 min; re-run after a timeout)
```

## Mac side, standing loop

`send` the instruction, then one background `wait`; when it returns, read, decide, `send` again. At most one waiter.
