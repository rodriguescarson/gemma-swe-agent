# Golden eval comparison: mock_F_dev_oracle -> mock_F_dev_null

Suite F, split dev, labels CONTROL -> CONTROL. Paired cases: 2 (only in base 0, only in candidate 0, fixture changed and dropped 0).

Decision rule on this suite: headline f_hidden_pass not met (wins - losses -2, one-sided p 1.0); X count totals not higher: True; dev split: True -> **NOT ELIGIBLE**.
Other suites: not checked here: run summary.py compare on the other suites' runs; none may show a 'worse' headline verdict. Then: confirm once on the holdout (and FAITHFUL when an L4 is available) before shipping.

The verdict column uses two-sided p <= 0.05; the pre-registered rule uses one-sided p <= 0.10 with wins - losses >= 3, so a change can be eligible while its verdict reads 'no evidence'.

Transition table for f_hidden_pass (paired cases, base rows -> candidate columns):

| base \ candidate | 1 | 0 |
|---|---|---|
| 1 | 0 | 2 |
| 0 | 0 | 0 |

0 -> 1 (0): none
1 -> 0 (2): F__rich_3278, F__rich_3471

| metric | better | n | base | cand | diff | W | L | T | p one-sided | p two-sided | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| f_hidden_pass | higher | 2 | 1 | 0 | -1 | 0 | 2 | 0 | 1 | 0.500 | no evidence |
| f_touches_all_gold_files | higher | 2 | 1 | 0 | -1 | 0 | 2 | 0 | 1 | 0.500 | no evidence |
| f_gold_files_touched | higher | 2 | 1 | 0 | -1 | 0 | 2 | 0 | 1 | 0.500 | no evidence |
| f_nonempty | higher | 2 | 1 | 0 | -1 | 0 | 2 | 0 | 1 | 0.500 | no evidence |
| f_applies | higher | 2 | 1 | 1 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| f_compiles | higher | 2 | 1 | 1 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| f_no_protected | higher | 2 | 1 | 1 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| f_no_scratch | higher | 2 | 1 | 1 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| f_notes_format | higher | 2 | 1 | 0 | -1 | 0 | 2 | 0 | 1 | 0.500 | no evidence |
| f_ended_by_text | higher | 2 | 1 | 1 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| f_first_edit_t | lower | 0 | - | - | - | 0 | 0 | 0 | 1 | 1 | no evidence |
| f_first_edit_in_time | higher | 0 | - | - | - | 0 | 0 | 0 | 1 | 1 | no evidence |
| f_verify_rounds | higher | 2 | 1 | 0 | -1 | 0 | 2 | 0 | 1 | 0.500 | no evidence |
| f_t_end | lower | 0 | - | - | - | 0 | 0 | 0 | 1 | 1 | no evidence |
| f_calls | lower | 2 | 2 | 0 | -2 | 2 | 0 | 0 | 0.250 | 0.500 | no evidence |
| f_llm_calls | lower | 2 | 3 | 1 | -2 | 2 | 0 | 0 | 0.250 | 0.500 | no evidence |
| f_prompt_tokens | lower | 2 | 11274 | 3481 | -7793 | 2 | 0 | 0 | 0.250 | 0.500 | no evidence |
| x_invented_tool_calls | lower | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| x_bare_helper_calls | lower | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| x_malformed_calls | lower | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| x_forbidden_edit_tools | lower | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| x_edit_helper_failures | lower | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| x_text_tool_calls | lower | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| x_compaction_exceedances | lower | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| x_compactions | lower | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| x_runaway_outputs | lower | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| x_cant_open_file | lower | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| x_crash | lower | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| x_live_restarts | lower | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| x_capped | lower | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |
| x_clean | higher | 2 | 1 | 1 | 0 | 0 | 0 | 2 | 1 | 1 | no evidence |

Pre-registered decision rule (spec section 8): adopt a prompt change on PROXY evidence only if, on the dev split, the target suite's headline improves with one-sided sign-test p <= 0.10 and wins - losses >= 3, no X count metric has a higher total, and the other suites' headlines have no 'worse' verdict; then confirm once on the holdout (and FAITHFUL when an L4 is available) before shipping.

agents-cli eval compare is a key-level JSON diff with no pairing or statistics; decisions use this file.
