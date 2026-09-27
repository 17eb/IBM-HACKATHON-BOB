# IBM Bob agent workflow

IBM Bob is the coding agent and MCP client. It reads the COBOL project, prepares
the Java port, and calls COBOL Bridge for deterministic capture and verification.
COBOL Bridge does not generate Java code by itself.

## Connect Bob

1. Open the COBOL project as a folder in Bob.
2. Configure the `cobol-bridge` MCP server for that project using
   [IDE integration](IDE_MCP_INTEGRATION.md). Restart the MCP server and confirm
   that its tools are available in a new Bob task.
3. Ask Bob to call `start_cobol_port` with a source path relative to the open
   project. Check the reported workspace root, source hash, I/O mode, and
   toolchain before capturing output.

Opening a file without opening its containing project folder may leave Bob's
file tools pointed at a different workspace. The MCP root and Bob's open
project should refer to the same COBOL project, even though the Bridge server
may be installed elsewhere.

## Console programs

For programs using `ACCEPT` and `DISPLAY`, follow the
[interactive transcript workflow](INTERACTIVE_TRANSCRIPTS.md). Ask Bob to
read the source and explain its business logic, select synthetic input scripts,
capture COBOL transcripts, write a Java console port, and call
`verify_interactive_java` for each case. Retain both passing and failing
reports during development; do not modify a frozen COBOL output to make Java
pass.

Byte-identical results establish parity for the captured cases. Add cases for
branches, validation failures, boundary values, and sequences of operations
that matter to the program. Document behavior outside the captured cases.

## Fixed-width batch programs

For the bundled `loancalc` example, open this repository as the Bob workspace
and run the setup command from [IDE integration](IDE_MCP_INTEGRATION.md) with
`--workspace` set to this repository. The project skill
`.bob/skills/cobol-to-java/SKILL.md` provides a task checklist.

Ask Bob to call `prepare_java_port` for the configured program, read the source
and record layouts, write the Java port, and run `verify_java_port` until every
dataset passes. For another batch program, first define its source, record
layouts, Java entry point, and datasets as described in
[program profiles](PROGRAM_PROFILES.md). A missing or invalid golden prevents
a parity pass.

## Verify without Bob

From the Bridge checkout, run the automated tests and the bundled Java parity
check with a configured Python environment and JDK 17 or later:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest -q
& ".\.venv\Scripts\python.exe" -m tools.verify_all --candidate java
```

The bundled goldens were captured with local GnuCOBOL. They do not establish
equivalence to an IBM runtime. A new COBOL capture requires `cobc` in the MCP
server's runtime; the Docker option in the integration guide provides it.
