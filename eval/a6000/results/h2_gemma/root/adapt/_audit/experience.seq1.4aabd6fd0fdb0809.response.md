---
## Goal

The user wants the AI to read the instructions in `MISSION.md`, execute the requested tasks, and save the final output to `output/answer.md` while also replying with that same output.

## Instructions

- Read `MISSION.md` first to understand the specific task.
- The final response must be the requested output from `MISSION.md`.
- The final output must be saved verbatim to `output/answer.md`.

## Discoveries

- Initial attempts to read `MISSION.md` using a specific `read` tool failed due to permission restrictions.
- A follow-up attempt to locate the file using `ls -R /` timed out because the directory structure (particularly the `node_modules` folder) is too large to list entirely.
- The file `MISSION.md` has not yet been successfully read or located.

## Accomplished

- **Completed**: Initial attempt to access `MISSION.md` (failed).
- **In Progress**: Locating the exact path of `MISSION.md` within the environment.
- **Remaining**: Read `MISSION.md`, execute the mission, save the result to `output/answer.md`, and provide the final answer.

## Relevant files / directories

- `MISSION.md`: The primary instruction file (target for reading).
- `output/answer.md`: The destination file for the final output.
---

The previous request exceeded the provider's size limit due to large media attachments. The conversation was compacted and media files were removed from context. If the user was asking about attached images or files, explain that the attachments were too large to process and suggest they try again with smaller or fewer files.

Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed.

I haven't performed any actions yet. I need to locate and read `MISSION.md` to understand the task.