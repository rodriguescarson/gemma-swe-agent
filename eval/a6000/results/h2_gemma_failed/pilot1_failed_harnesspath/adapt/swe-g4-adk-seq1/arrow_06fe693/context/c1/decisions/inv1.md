---
## Goal

The user wants to execute the instructions contained in `MISSION.md`, generate a specific output based on those instructions, and save that output verbatim to `output/answer.md`.

## Instructions

- Read `MISSION.md` first.
- Follow all requests specified within `MISSION.md`.
- Provide the requested output as the final response.
- Save the final output verbatim to `output/answer.md`.

## Discoveries

- A direct attempt to use the `read` tool on `MISSION.md` failed due to tool-call permissions/restrictions.
- An attempt to find `MISSION.md` using `ls -R /` timed out and produced a massive output of system directories (mostly VS Code node_modules), but did not explicitly confirm the location of `MISSION.md` within the accessible workspace.

## Accomplished

- **Attempted**: Read `MISSION.md` (Failed).
- **Attempted**: Locate `MISSION.md` via filesystem search (Timed out/Incomplete).
- **Current Status**: Stuck at the initial step of reading the mission file.

## Relevant files / directories

- `MISSION.md`: The primary target file containing the task instructions (Location not yet confirmed/read).
- `output/answer.md`: The destination file for the final output.
---

The previous request exceeded the provider's size limit due to large media attachments. The conversation was compacted and media files were removed from context. If the user was asking about attached images or files, explain that the attachments were too large to process and suggest they try again with smaller or fewer files.

Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed.

I need to read `MISSION.md` to understand the task. I will start by searching for the file.



I cannot find `MISSION.md` in the current environment. Please provide the file or its correct path.