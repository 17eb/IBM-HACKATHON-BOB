# COBOL Bridge MCP

COBOL Bridge is a local MCP server for COBOL-to-Java modernization. An IDE agent
reads the program and writes the Java port. Bridge captures observed COBOL
behavior and checks the Java result against it. The bundled batch example uses
field-level record comparison; console programs use exact stdin/stdout
transcript comparison.

## The problem

COBOL numeric and file semantics require deliberate handling in a modern port.
For example, `ROUNDED` and unrounded assignments can produce different cents;
fixed-width fields and file framing can produce differences even when the
business calculation appears correct. Comparing outputs from the same inputs
exposes these differences before a port is accepted.

**Who it's for:** developers and QA engineers porting COBOL batch programs, and the AI agents that increasingly write those ports.

## The solution

The batch workflow consists of five steps:

1. **Explain:** `inspect_cobol` reads the source: paragraphs, PIC clauses, `COMPUTE` statements, and flagged traps such as truncation or division.
2. **Characterize:** `capture_golden` compiles and runs the COBOL on synthetic inputs, then freezes the output with a manifest (hashes, compiler, profile). After that, the golden is read-only.
3. **Port:** an IDE agent writes the Java code.
4. **Verify:** `compare_parity` runs Java on the same inputs and compares each configured field and trailer. Mismatch reports identify the record, field, values, and mapped business rule.
5. **Loop:** the agent fixes the Java (never the golden) until every dataset passes.

An MCP-capable IDE can drive the same tools through a local stdio connection.
For interactive `ACCEPT`/`DISPLAY` programs, use the separate
[console transcript workflow](docs/INTERACTIVE_TRANSCRIPTS.md).

## Results

The same 55 synthetic records, the same frozen COBOL goldens and the same checker were used for both ports (`metrics/before_after.md`):

| Java candidate | Datasets passing | Records wrong | Field mismatches | Batch trailers wrong |
|---|---|---|---|---|
| Naive port (deliberate baseline: `double`, banker's rounding, rounded fee) | 0 / 3 | 14 / 55 | 31 | 3 / 3 |
| Faithful port (`BigDecimal`, COBOL rounding and truncation) | **3 / 3** | **0 / 55** | **0** | **0 / 3** |

The deliberately naive baseline differs by one or two cents on affected
records, including **1410.94 instead of 1410.95**. All three batch trailers
then differ from the captured COBOL output.

## MCP surface

Use list_programs to discover configured batch jobs. The dataset, capture, Java run,
comparison and report tools accept an optional program_id; they default to LOANCALC.

| Name | Kind | What it does |
|---|---|---|
| `inspect_cobol(source_path)` | tool | Heuristic static reading: sha256, paragraphs, data items, computations, unresolved questions |
| `start_cobol_port(source_path, input_path?, reference_output_path?)` | tool | Read-only starting point for a COBOL file in any connected IDE project, before registration |
| `capture_interactive_golden(source_path, case_id, stdin_text)` | tool | Run a console COBOL program with scripted input and freeze its stdout with hashes |
| `verify_interactive_java(source_path, case_id, java_source_dir, main_class)` | tool | Compare a Java console port against the frozen stdin/stdout session byte for byte |
| `prepare_java_port(program_id, candidate)` | tool | Source and Java target paths, source hash, datasets, and golden readiness for the agent |
| `verify_java_port(program_id, candidate)` | tool | Runs every configured dataset and passes only when all records and trailers match |
| `list_datasets()` | tool | Dataset IDs with committed inputs |
| `capture_golden(dataset_id, profile_id, force_new_version)` | tool | Runs COBOL and freezes the golden and its manifest. Refuses to overwrite by default. |
| `import_golden(dataset_id, profile_id, raw_input_path, raw_output_path, evidence_path)` | tool | Imports a synthetic EBCDIC FB export, preserving raw bytes and evidence; never overwrites a dataset |
| `run_java(dataset_id, candidate)` | tool | Compiles and runs `java` or `java-naive` on the dataset input |
| `compare_parity(dataset_id, candidate, run_id?)` | tool | Exact record, field and trailer comparison, returned as a JSON report with rule IDs |
| `get_run_report(run_id)` | tool | Reads a stored report |
| `cobolbridge://spec` | resource | Record layouts and business rules |
| `cobolbridge://datasets/{id}` | resource | Golden manifest |
| `modernize_cobol_to_java` | prompt | Checklist: explain → characterize → port → verify → report |

**Safety:**
- MCP file arguments are workspace-relative; absolute paths, `..`, and symlink escapes are rejected.
- Subprocesses use fixed argument lists, with timeouts and capped output.
- Goldens are frozen.
- Before parity, the source, input and golden bytes must match their dataset manifest.
  A missing manifest or hash mismatch is an error, including line-ending changes.
- Bundled fixtures contain synthetic data. External projects should use approved test data.

## Architecture

```
MCP client / AI agent ──stdio──► mcp_server/server.py ─┐
tools/verify_all.py (CLI) ─────────────────────────────┼──► core/workflow.py ──► core/parity.py   (exact compare)
app/streamlit_app.py (demo) ───────────────────────────┘          │           core/runners.py  (cobc / javac / java)
                                                                   │           core/records.py  (layouts)
                                                                   └──────────► adapters/local_gnucobol.py (golden capture)
legacy/LOANCALC.cbl ── GnuCOBOL ──► data/golden/*.out  (frozen, hashed in data/manifests/)
modern/java        ── faithful port      modern/java-naive ── deliberate baseline
```

## Run it

Everything runs in a toolchain container (GnuCOBOL 3.2, JDK 21 targeting Java 17, and Python with `mcp==1.30.0`), so the host only needs Docker:

```bash
./dev.sh bash legacy/build.sh                               # compile COBOL
./dev.sh python -m tools.generate_test_data                 # (re)create synthetic inputs (seeded)
./dev.sh python -m tools.verify_all --candidate java        # parity: exit 0 = all datasets pass
./dev.sh python -m tools.verify_all --candidate java-naive  # the "before": exits 1 with mismatches
./dev.sh python -m pytest -q                                # automated tests
```

**Demo app:**

```bash
docker build -t cobol-bridge-app . && docker run -p 8501:8501 cobol-bridge-app   # http://localhost:8501
```

**MCP server with a local toolchain** (`apt install gnucobol3 openjdk-21-jdk`):

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
python -m mcp_server.server                                  # stdio; see .mcp.json.example for a client config
```

No environment variables are required for the bundled example.
`COBOLBRIDGE_ROOT` selects an external COBOL project for IDE integration.

## Reuse with another batch program

The CLI and MCP tools now load fixed-width record layouts, source paths, Java entry points,
trailer formats and mismatch rule labels from a program definition. LOANCALC remains the
default. Add a new definition and files as described in docs/PROGRAM_PROFILES.md, then run:

~~~text
python -m tools.verify_all --program <program_id> --candidate java
~~~

This verifies the new Java port without connecting an IDE. IBM Bob or another MCP client
can call the same workflow through the stdio server; IDE integration is optional for
testing the core. The Streamlit page remains the curated LOANCALC demo.

## Agent-driven Java conversion in IBM Bob

Generate a project MCP connection with `tools/ide_setup.py`; generated
machine-specific configuration is excluded from version control. The optional
Bob skill at `.bob/skills/cobol-to-java/SKILL.md` provides a checklist for the
bundled batch example. Bob reads the source, writes the Java port, and calls
`prepare_java_port` and `verify_java_port` to check it. See the
[Bob workflow](docs/BOB_AGENT_WORKFLOW.md) for setup and verification steps.

## Use from any MCP-capable IDE agent

Developers can open their own COBOL project in an IDE and connect this local stdio
server to that project. `start_cobol_port` accepts a workspace-relative COBOL source
and optional input/reference-output paths without requiring the LOANCALC profile.
The agent can inspect first, then register a supported program and verify its Java
port against a real frozen COBOL output. The COBOL process itself does not call MCP.
Use `python -m tools.ide_setup --workspace <project> --client generic` for a
portable MCP config, or choose `bob`, `cursor`, `antigravity`, `codex`, or `all`.
See [IDE integration](docs/IDE_MCP_INTEGRATION.md) for setup and the agent prompt.

## Documentation

- `docs/LOANCALC_explained.md`: the program in plain language
- `docs/record_layouts.md`: the byte-level contract
- `docs/business_rules.md`: intended vs observed behaviour, with evidence
- `docs/traceability.md`: rule → COBOL lines → Java method → tests → data
- `metrics/before_after.md`: method and raw counts
- `docs/PROGRAM_PROFILES.md`: define and verify another fixed-width batch program
- `docs/IBM_FIXTURE_IMPORT.md`: import a declared IBM-style FB export and verify provenance
- `docs/IDE_MCP_INTEGRATION.md`: connect an external COBOL project to an IDE agent
- `docs/INTERACTIVE_TRANSCRIPTS.md`: capture and verify console input/output sessions

## Limitations

- The bundled demo contains one synthetic batch program. Other fixed-width programs can
  be configured, but this is not a general COBOL transpiler.
- Free-format console programs can use the separate transcript verifier for
  `ACCEPT`/`DISPLAY` sessions; it does not produce batch field-level reports.
- Goldens are produced by **GnuCOBOL run locally** and are **not IBM-runtime verified**. Enterprise COBOL results may differ, for example with compiler options such as `ARITH` or `TRUNC`.
- The hosted demo runs Java live against the committed goldens. It does not compile COBOL.
- No live z/OS, CICS, Db2 or VSAM connection. The import adapter accepts declared EBCDIC FB exports; it does not support VB, packed decimal, or remote job submission. The repository contains no actual IBM-runtime output.

## License

MIT
