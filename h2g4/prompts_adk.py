"""The improver's description of the ADK surface (harness2.core.prompts keeps one per substrate in _SURFACE_TEXTS and ships only
'opencode' and 'codex'; without this entry every Propose/Compose stage fails with "no prompt surface for 'adk'", as the box
found on 2026-10-18, B-203). Modelled on harness2's _SURFACE_OPENCODE (same sections, same rules where they hold), rewritten for
what this runtime actually does: one ADK agent, a 5-minute wall clock and 40 tool calls per task, skills run through
run_skill_script, and no sub-agents, top-level scripts or plugins (h2g4/adk.py tree_problems rejects them). register() is idempotent
and runs when h2g4.adk is imported."""
from __future__ import annotations

from harness2.core import prompts as P

SURFACE_ADK = """\
# WHAT YOU CAN CHANGE

The harness is a tree of components. The four always-on files are joined, in this order, into the agent's single system
prompt; skills are loaded only when the agent asks for them:

| path | what it is | when it is in context |
|---|---|---|
| `systemprompt.md` | role and procedure | ALWAYS ON -- every token competes with the agent's own output budget |
| `guardrails.md` | standing rules | ALWAYS ON -- same cost |
| `LongTermMEMORY.md` | durable facts about this repository | ALWAYS ON -- same cost |
| `tool_descriptions/tool_guidance.md` | how to use the tools | ALWAYS ON -- same cost |
| `skills/<name>/SKILL.md` | a reusable workflow | loaded ON DEMAND with `load_skill_resource`, only when invoked |
| `skills/<name>/scripts/<file>.py` | a deterministic helper of that skill | run ON DEMAND with `run_skill_script(skill_name, file_path)` |

There are NO sub-agents, NO top-level `scripts/`, and NO plugins or hooks in this runtime: the agent is one model in one
context with the tools run_command, read_file, edit_file, write_file, get_status and submit_patch, plus the two skill tools. A
proposal that adds `sub_agents/`, `scripts/` or `plugin/` is rejected. The model, its tools, its sampling settings and its
limits are fixed and are not yours to change.

THE BUDGET IS TIME. Each task gets 5 minutes of wall clock and 40 tool calls, and nearly all of the 5 minutes is the model
generating text: tool calls are cheap, long reasoning is not. A run that reasons until the clock runs out delivers whatever
source edit exists at that moment, and an unedited tree delivers nothing. The context window is 32k tokens and is compacted
at about 14k, so long always-on text also pushes the task itself out sooner.

The two that are easy to get wrong:

`skills/` -- SKILL.md needs frontmatter with `name:` equal to its directory and a `description:`, or it is dropped. Its
helpers live in `skills/<name>/scripts/` and are standard-library Python only, run offline from a temporary directory with
arguments as `--key value`; the agent calls them with run_skill_script, never by a path (the harness files are not on the
sandbox's disk).

`guardrails.md` -- the place for a short rule that applies to every task. Every word of it costs time on every task.

Change only what a trajectory shows needs changing -- but WHERE you change something, the FORM matters as much as the
content, and the cheap form is not the obvious one.

ALWAYS-ON PROSE IS THE EXPENSIVE OPTION. Every word of it is in context on every run and is re-read on every step, and the
most costly failure here is a run that reasons until the clock is gone and edits nothing. Adding prose makes that MORE
likely, not less. An on-demand skill costs nothing until the moment it is invoked.

So prefer, in this order:
  - a SKILL for anything with a recognisable trigger -- a kind of failure, a kind of fix, a repository convention.
  - a SKILL SCRIPT for a deterministic operation the runs hand-rolled and got wrong or did slowly: locating a symbol,
    checking that an edit compiles, running one targeted test with a timeout and compact output.
  - ALWAYS-ON TEXT last, and only for a short rule that genuinely applies to every run. If you add always-on text, cut
    something else to pay for it.

THREE RULES THAT DISCARD THE WHOLE PROPOSAL. Validation runs before any rollout, and a harness that fails it is thrown away
entire.

1. EVERY SKILL NEEDS A TRIGGER LINE. If you create or keep `skills/<name>/SKILL.md`, its directory name must appear
   VERBATIM in `systemprompt.md` or `guardrails.md`, in the SAME edit:

       When <the situation this skill handles>, use the `<name>` skill.

   An unnamed skill is never opened anyway: the line is what makes it exist.

2. NO CURLY BRACES ANYWHERE IN ALWAYS-ON TEXT. The agent framework treats a word in braces as a template variable and the
   run fails before any work starts. Write the word without braces, or use angle brackets.

3. EVERY SCRIPT YOU NAME MUST EXIST, at `skills/<skill-name>/scripts/<file>.py`, in the same proposal; a file anywhere else
   is off the surface and silently discarded. The always-on text is also capped at 16,000 characters in total.

THE DELIVERABLE'S SHAPE BELONGS TO THE REQUEST, NOT TO YOU. The deliverable is a change to the repository's SOURCE files that
makes the behaviour the issue describes hold. Test files are reset before grading, so a harness that tells the agent to edit
tests, add a test, or leave notes and scratch files in the repository changes nothing or adds noise to the patch; scratch
work belongs in /tmp. A harness changes HOW the agent works; it must never change what is graded.

# HOW TO MAKE A CHANGE

The harness is in `context/harness/`, and it is YOURS TO EDIT. Open the files, change them in place with your normal tools,
and create new ones where a new component is the right lever. Your edits on disk ARE the proposal -- there is no separate
format to reproduce them in, and nothing you write in this reply changes the harness.

- Files you do not touch are inherited unchanged. Do not rewrite a file to keep it the same.
- Delete a file to remove that component.
- If the evidence does not argue for any change, leave everything as it is and say KEEP_BASE in your notes. That is a real
  answer, not a failure: adaptation the evidence does not support costs context and buys nothing.

Then reply with ONE `<notes>` block and nothing else: for each change, the moment in a trajectory that motivated it. The
notes are read by a person, not applied by a machine."""

TTS_SURFACE_HEAD_ADK = """\
# EDITABLE HARNESS SURFACE

You may write ONLY these paths. Anything else is off the editable surface: it is dropped before your work is used, however
good it is.

| path | component | when it is in context |
|---|---|---|
| `systemprompt.md` | persona/procedure | ALWAYS ON -- every token competes with the 5-minute budget |
| `guardrails.md` | always-on rules | ALWAYS ON -- same cost |
| `LongTermMEMORY.md` | durable repository facts | ALWAYS ON -- same cost |
| `tool_descriptions/tool_guidance.md` | tool prose | ALWAYS ON -- same cost |
| `skills/<name>/SKILL.md` | reusable workflow | loaded ON DEMAND with `load_skill_resource` |
| `skills/<name>/scripts/<file>.py` | deterministic helper | run ON DEMAND with `run_skill_script` |

There are no sub-agents, top-level scripts, plugins or hooks in this runtime."""

INV_ADK = P._INV_TEMPLATE.replace(
    "use `scripts/<name>.py` for repeated deterministic extraction",
    "use a skill script `skills/<name>/scripts/<file>.py` (run with run_skill_script) for repeated deterministic extraction",
).replace(
    "__LOOP_LEVER__",
    "check script in a skill that the always-on text requires before submit_patch -- for example, one that refuses to "
    "report done while no {deliverable} exists, with a corrective message",
)
DOM_ADK = P._DOM_TEMPLATE.replace(
    "__TRIGGER_SENTENCE__",
    "A skill exists only once its name appears in the always-on text: write that trigger line in the same edit.",
)


def register() -> None:
    if "adk" in P._SURFACE_TEXTS:
        return
    tts = "\n\n".join([
        TTS_SURFACE_HEAD_ADK,
        P._surface_part(SURFACE_ADK, "THREE RULES THAT DISCARD", "THE DELIVERABLE'S SHAPE"),
        P._surface_part(SURFACE_ADK, "# HOW TO MAKE A CHANGE"),
    ])
    P._SURFACE_TEXTS["adk"] = P._SurfaceText(surface_md=SURFACE_ADK, inv=INV_ADK, dom=DOM_ADK, tts_surface=tts)
