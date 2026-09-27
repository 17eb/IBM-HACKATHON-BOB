# Traceability: rule → COBOL → Java → tests → data

COBOL means `legacy/LOANCALC.cbl` and Java means `modern/java/src/main/java/com/cobolbridge/LoanCalc.java`. Line numbers refer to the current files.

| Rule | COBOL | Java | Tests | Dataset cases |
|---|---|---|---|---|
| **R1** interest, `ROUNDED` (half-up) | `CALC-INTEREST` L131–132 | `calcInterest` L114–118: exact product, `divide(12, 2, HALF_UP)` | `test_one_cent_difference_fails_with_field_and_rule`, `test_faithful_java_matches_every_golden` | ds02 E0002000–E0002004, E0002016–E0002017 |
| **R2** fee 5%, truncated, minimum 5.00 | `CALC-LATE-FEE` L136–142 | `calcLateFee` L125–132: `store(..., DOWN)`, `MIN_FEE` | `test_late_fee_rule_depends_on_days_late`, `test_naive_java_is_caught` | ds02 E0002005–E0002011, E0002014, E0002021 |
| **R3** double after the minimum when over 60 days | `CALC-LATE-FEE` L143–145 | `calcLateFee` L133–135 | `test_late_fee_rule_depends_on_days_late` | ds02 E0002012–E0002013, E0002015, E0002019. ds01/ds03 records over 60 days. |
| **R4** validation → `ERR` | `VALIDATE-RECORD` L117–128. `PROCESS-RECORD` L104–107 | `validateRecord` L105–111, `isNumeric` L158. `processRecord` else-branch | `test_faithful_java_matches_every_golden[ds03_mixed_errors]` | ds03 M0003001, M0003003, M0003004, M0003006, M0003007 |
| **R5** trailer counts and sum | `PROCESS-RECORD` L96, L102, L106. `WRITE-TRAILER` L149–153 | `processRecord` L86, L92, L98. `writeTrailer` L140–143 | `test_trailer_mismatch_is_reported`, `test_missing_record_is_reported` | The trailer of every dataset |
| **Layout / framing** | FD and `DETAIL-LINE`/`TRAILER-LINE`. `READ-INPUT` L90–93 | `LoanIn.of`, `readInput` L66–81, `render` L146–153, `digits` | `test_layout_widths_are_contiguous`, `test_trailing_space_difference_is_not_ignored` | All datasets |

## Harness safety

| Guarantee | Code | Test |
|---|---|---|
| Paths stay inside the workspace | `core/paths.py` `resolve_in_root` | `test_rejects_unsafe_paths`, `test_rejects_symlink_escape`, `test_path_traversal_rejected_over_mcp` |
| Goldens are frozen | `adapters/local_gnucobol.py` `capture_golden` | `test_frozen_golden_is_not_overwritten`, `test_capture_golden_reproduces_committed_golden` |
| Clear errors | `core/workflow.py` `_error`, `core/runners.py` `RunError` | `test_compare_parity_missing_golden`, `test_unknown_candidate_is_an_error`, `test_missing_golden_error_over_mcp` |
| Discoverable MCP surface | `mcp_server/server.py` | `test_tools_resources_prompts_are_discoverable`, `test_compare_parity_over_mcp` |
