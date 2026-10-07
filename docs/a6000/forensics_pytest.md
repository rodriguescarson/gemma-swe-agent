# Full repo test suite on the A6000 box (P5 section 7)

`PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m pytest -q tests -p no:cacheprovider` finished 2026-10-07 14:09 UTC: **49 failed, 2636 passed, 861 skipped in 13 min 50 s** (log ~/g4/forensics_pytest.log).

| test | first assertion / error line | where |
|---|---|---|
| `tests/test_adaption_train.py::test_cli_refuses_small_sets_without_flag_and_never_launches_by_default` | `assert (1 != 0 and '10000' in ('' + 'Traceback (most recent call last):\n  File "/home/jc/g4/gemma-swe-agent/train/adaption_train.py", line 174, in <modul..._train.py", l` | tests/test_adaption_train.py:48 |
| `tests/test_adaption_train.py::test_download_unpacks_a_zstd_tarball` | `AssertionError: zstd CLI needed for this test` | tests/test_adaption_train.py:62 |
| `tests/test_bundles.py::test_bundle_compiles_with_official_compiler[v4_lora_test]` | `AssertionError: /jc/g4/gemma-swe-agent/scripts/validate.py", line 17, in <module>` | tests/test_bundles.py:34 |
| `tests/test_bundles.py::test_bundle_compiles_with_official_compiler[v4h2_v11a]` | `AssertionError: /home/jc/g4/gemma-swe-agent/scripts/validate.py", line 17, in <module>` | tests/test_bundles.py:34 |
| `tests/test_bundles.py::test_bundle_compiles_with_official_compiler[v4h2_v11a_probe]` | `AssertionError: /home/jc/g4/gemma-swe-agent/scripts/validate.py", line 17, in <module>` | tests/test_bundles.py:34 |
| `tests/test_bundles.py::test_bundle_compiles_with_official_compiler[v4h2g_v11b]` | `AssertionError: /home/jc/g4/gemma-swe-agent/scripts/validate.py", line 17, in <module>` | tests/test_bundles.py:34 |
| `tests/test_bundles.py::test_bundle_compiles_with_official_compiler[v4h2g_v11b_probe]` | `AssertionError: /home/jc/g4/gemma-swe-agent/scripts/validate.py", line 17, in <module>` | tests/test_bundles.py:34 |
| `tests/test_golden_fixtures.py::test_every_runnable_task_has_evidence_or_a_reason` | `AssertionError: fastapi_11194` | tests/test_golden_fixtures.py:1139 |
| `tests/test_heldout_miner.py::test_progress_keeps_rounds_and_repo_totals` | `FileNotFoundError: [Errno 2] No such file or directory: '/System/Volumes/Data'` | tests/test_heldout_miner.py:390 |
| `tests/test_heldout_miner.py::test_progress_reports_tags_added` | `FileNotFoundError: [Errno 2] No such file or directory: '/System/Volumes/Data'` | tests/test_heldout_miner.py:470 |
| `tests/test_make_eval_kernel.py::test_adapters_dataset_option_keeps_weights_out_of_the_notebook` | `AssertionError: make_eval_kernel: /home/jc/g4/gemma-swe-agent/eval/golden/arms/v4_lora_probe has no eval_config.yaml (the host notebook would fail reading it); pass all o` | tests/test_make_eval_kernel.py:29 |
| `tests/test_overnight_gate.py::test_gate_rejects_a_marker_older_than_the_current_utc_day` | `assert (0 != 0)` | tests/test_overnight_gate.py:42 |
| `tests/test_train_when_ready.py::test_stale_report_and_prior_launch_are_ignored` | `assert (0 != 0)` | tests/test_train_when_ready.py:46 |
| `tests/test_v10_integration.py::test_channel_parity[edit_lines]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[edit_refused]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[edit_search]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[finalize_empty]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[finalize_fixed]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[grep]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[grep_tests]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[install]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[locate]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[repro_only]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[run]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[status]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[verify_empty]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[verify_fixed]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[view_name]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[view_obj]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[view_positional]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_integration.py::test_channel_parity[view_range]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_sandbox.py::test_install_real_wrapper_reachable` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_sandbox.py::test_every_helper_as_skill_script[edit]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_sandbox.py::test_every_helper_as_skill_script[finalize]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_sandbox.py::test_every_helper_as_skill_script[grep]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_sandbox.py::test_every_helper_as_skill_script[install]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_sandbox.py::test_every_helper_as_skill_script[locate]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_sandbox.py::test_every_helper_as_skill_script[locate_positional]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_sandbox.py::test_every_helper_as_skill_script[run]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_sandbox.py::test_every_helper_as_skill_script[status]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_sandbox.py::test_every_helper_as_skill_script[verify]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_sandbox.py::test_every_helper_as_skill_script[view]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_sandbox.py::test_every_helper_as_skill_script[view_positional]` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_sandbox.py::test_heredoc_path_roundtrip` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v10_sandbox.py::test_stdin_inherited_in_sandbox` | `TypeError: the JSON object must be str, bytes or bytearray, not dict` | tests/v10_support/sandbox.py:115 |
| `tests/test_v5h2_bundle.py::test_eval_kernel_matches_the_v5b_recipe[v5h2]` | `FileNotFoundError: [Errno 2] No such file or directory: '/home/jc/g4/gemma-swe-agent/kernels/g4-l4-v5h2-p312/kernel-metadata.json'` | tests/test_v5h2_bundle.py:199 |
| `tests/test_v5h2_bundle.py::test_eval_kernel_matches_the_v5b_recipe[v5h2b]` | `FileNotFoundError: [Errno 2] No such file or directory: '/home/jc/g4/gemma-swe-agent/kernels/g4-l4-v5h2b-p312/kernel-metadata.json'` | tests/test_v5h2_bundle.py:199 |
| `tests/test_v6p_bundle.py::test_eval_kernel_slug_is_free_and_regenerates_identically` | `FileNotFoundError: [Errno 2] No such file or directory: '/home/jc/g4/gemma-swe-agent/kernels/g4-l4-v6p-think-p312/kernel-metadata.json'` | tests/test_v6p_think_bundle.py:85 |
| `tests/test_v6p_think_bundle.py::test_eval_kernel_slug_is_free_and_regenerates_identically` | `FileNotFoundError: [Errno 2] No such file or directory: '/home/jc/g4/gemma-swe-agent/kernels/g4-l4-v6p-think-p312/kernel-metadata.json'` | tests/test_v6p_think_bundle.py:85 |
