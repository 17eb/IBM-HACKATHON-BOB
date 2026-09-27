# Verify an interactive COBOL program

This workflow covers console programs that read standard input with `ACCEPT`
and write standard output with `DISPLAY`. It accepts workspace-relative `.cbl`
or `.cob` source paths and a Java console main class. Fixed-width batch files
use the separate program-profile workflow.

## Agent workflow

1. Open the COBOL project in an MCP-capable IDE agent. Connect COBOL Bridge with
   `COBOLBRIDGE_ROOT` set to that project. Call `start_cobol_port` for the source.
   If the source lacks `>>SOURCE FORMAT FREE`, pass `source_format="free"` when
   appropriate. The result is heuristic; read the program itself.
2. Choose synthetic scripted input for one case. Newlines stand for Enter. Call
   `capture_interactive_golden(source_path, case_id, stdin_text, source_format)`.
   The local MCP process needs `cobc` on PATH. It compiles and executes the real
   COBOL source, saves stdin and stdout under `.cobol-bridge/transcripts/`, and
   freezes a manifest with source, input, and output hashes. A case ID cannot be
   reused with different input. Repeat for other behavior paths.
3. Use the IDE agent's file tools to write a Java console port in the same
   project. The Java `main` method must read standard input and write standard
   output. The MCP server does not generate Java by itself.
4. Call `verify_interactive_java(source_path, case_id, java_source_dir,
   main_class)` for every case. The tool validates the frozen hashes first,
   compiles Java with `javac --release 17`, feeds the identical stdin bytes, and
   compares stdout **byte for byte**. A mismatch reports the first differing byte
   and saves the Java stdout and JSON report. Fix Java and rerun until every case
   passes. Do not change the COBOL golden to make Java pass.

Example agent request for any console COBOL program:

> Use COBOL Bridge on `src/program.cbl`. Read the source and choose several
> synthetic input scripts covering normal and error behavior. Capture each
> real COBOL transcript, port the program to Java in `java/src`, then call
> `verify_interactive_java` for every case with the Java main class. Show each
> result and identify behavior not covered by the cases.

## Limits

- A compilable COBOL program is required to capture a new golden. The MCP
  runtime must provide `cobc`, either on the host or through the included
  Docker development image.
- This is exact **console transcript** parity, not field-level record parity.
  Extra prompts, line endings, spaces, and output encoding can cause mismatches.
- `stdin_text` is stored in the project. Use synthetic values, not real PINs or
  customer data.
- The tool does not support CICS screens, VSAM, databases, terminal control
  sequences, or external services. Such programs need a suitable execution and
  capture adapter.
