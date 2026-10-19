---
## Goal

The goal is to adapt an autonomous agent's harness (system prompts, guardrails, and skills) based on provided trajectories and a specific mission. The objective is to improve the agent's performance on a maintenance task: making the smallest correct change to a Python library to fix an issue, within 5 minutes and 40 tool calls.

## Instructions

- **Objective**: Trace the workflow from `context/rollouts/`, identify divergences or failures, and implement the cheapest effective fix (Skill > Skill Script > Always-on text).
- **Constraints**: 
    - No curly braces `{}` in always-on text.
    - Every skill must have a trigger line in `systemprompt.md` or `guardrails.md`.
    - All scripts must reside in `skills/<skill-name>/scripts/`.
    - Avoid modifying tests; only source changes count.
    - Do not add professional rules or domain facts not supported by evidence.
- **Deliverable**: The adapted harness files in `context/harness/` and a `<notes>` block explaining every change mapped to a specific trajectory moment.

## Discoveries

- **The Task**: The agent was tasked with adding `FORMAT_RFC3339_STRICT` to the `arrow` library (replacing a space with 'T' as a separator).
- **Base Rollout Analysis (`base1.md`)**:
    - The agent correctly identified the necessary files (`arrow/formatter.py` and `arrow/__init__.py`).
    - **Critical Failure**: The agent struggled significantly with the `edit_file` tool. When trying to add a new line using `\n` in the `new_string`, the tool literally inserted the characters `\n` into the source code instead of a newline character.
    - The agent spent several tool calls and a significant amount of time attempting to recover from this mechanical error, eventually failing to produce a clean patch before the trajectory ended.
- **Technical Insight**: The `edit_file` tool's handling of newline characters in strings needs to be carefully managed, or the agent needs a more robust way to handle multi-line edits.

## Accomplished

- [x] Read and understood `MISSION.md`.
- [x] Analyzed the task (`context/task.md`) and the base trajectory (`context/rollouts/base1.md`).
- [x] Inspected the current harness files in `context/harness/`.
- [x] Identified the primary point of failure: mechanical struggle with `edit_file` and string escaping/newlines.
- [ ] **Pending**: Determine the best harness modification to prevent this (e.g., a skill for multi-line edits or updated `systemprompt.md` guidance on `edit_file` failures).
- [ ] **Pending**: Implement changes in `context/harness/` and write the final `<notes>`.

## Relevant files / directories

- `MISSION.md`: The primary instructions for the adaptation task.
- `context/task.md`: The original problem statement (adding `FORMAT_RFC3339_STRICT`).
- `context/rollouts/base1.md`: The trajectory showing the agent's failure with `edit_file`.
- `context/harness/`:
    - `systemprompt.md`: The agent's core operating procedure.
    - `guardrails.md`: Standing rules.
    - `LongTermMEMORY.md`: Durable repository facts.
    - `tool_descriptions/tool_guidance.md`: Guidance on tool usage.
---

The previous request exceeded the provider's size limit due to large media attachments. The conversation was compacted and media files were removed from context. If the user was asking about attached images or files, explain that the attachments were too large to process and suggest they try again with smaller or fewer files.

Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed.

I will now focus on implementing the cheapest effective fix to prevent the `edit_file` newline issue identified in `base1.md`. I'll start by examining the existing `systemprompt.md` and `tool_guidance.md` to see if adding specific guidance on multi-line edits is sufficient, or if a dedicated skill is required.