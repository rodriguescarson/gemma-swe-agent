# Forum post 2: edit_file arguments arrive corrupted in about one call in five

Title: edit_file: 18-22% of calls reach the tool with corrupted argument keys (gemma4 parser), 39-52% fail on old_string

Body (plain text):

Across three of our runs, edit_file calls whose arguments carried keys outside the tool's schema: 142 of 665, 72 of 411, and 153 of 698 (18-22%). The pattern in the traces: the model closes a string value with a backtick instead of the proper delimiter, and the gemma4 tool parser folds the rest of the call into the previous value, so new_string ends with `...)` ,old_string: ` and the next key becomes a fragment of code. The tool then answers "missing mandatory input old_string", or the old_string that survives no longer matches the file. Counting every failure mode, 39-52% of all edit_file calls in those runs failed on old_string.

The same runs show the single-string tools are fine: run_command 0 corrupted of 1,001 and 0 of 1,252; write_file 0 of 70; read_file 32 of 597 (keys like `end_line"`). The corruption is specific to multi-argument calls that carry code.

Two things that follow for participants: (1) a local eval that does not use the scorer's gemma4 parser will not see this, which may be part of why local scores do not track the leaderboard; (2) editing through one plain string (a heredoc to a small helper via run_command) sidesteps it. For the organisers: if the parser could reject a call with a malformed key instead of folding it, the model would at least get a clean error to retry on.

Happy to share trace excerpts if useful.
