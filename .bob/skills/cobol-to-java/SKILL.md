---
name: cobol-to-java
description: Port a configured COBOL batch program to Java and prove exact parity with its frozen COBOL outputs using the COBOL Bridge MCP tools.
user-invocable: true
---

When asked to convert a configured COBOL program to Java:

1. Read `AGENTS.md`, `docs/BUILD_GUIDE.md`, and `docs/record_layouts.md`. Follow the project rules. Do not commit unless the user asks.
2. Call the `cobol-bridge` MCP tools `list_programs` and `prepare_java_port` for the selected program. Read the returned COBOL source and `programs/<program_id>.json` directly. Call `inspect_cobol` for clues, then confirm every important rule from the source; its findings are heuristic.
3. Read the relevant business rules, record layouts, and traceability documents. Confirm field widths, file framing, decimal scale and rounding, error cases, and trailer logic. Check `fixture_valid` for every dataset in `prepare_java_port`. If a local golden is missing, call `capture_golden` only when the local COBOL toolchain is available. For a supplied IBM-style export, follow `docs/IBM_FIXTURE_IMPORT.md` and call `import_golden`; label simulated and actual IBM exports accurately. If a manifest hash fails, investigate the changed bytes before continuing. Never overwrite a frozen golden merely to make a port pass.
4. Use Bob's file editing tools to create or fix the Java candidate at the configured source directory and main class. Use Java 17 standard libraries and exact decimal arithmetic. Do not change the COBOL source, goldens, or naive baseline to hide a Java mismatch.
5. Call `verify_java_port`. For each failing dataset, inspect the report and use `compare_parity` for the record, field, expected value, actual value, and rule ID. Fix Java and repeat `verify_java_port` until all configured datasets and trailers pass.
6. Update `docs/traceability.md` with source-to-Java rule mapping. Report which Java files changed, source hash, per-dataset results, remaining mismatches, and any toolchain limitation. Claim success only when `verify_java_port` returns `pass`.

The MCP server supplies context and checks. You are the agent that writes the Java code. Start with COBOL to Java; Java to Python is a later workflow and COBOL to Python must pass through a verified Java port.
