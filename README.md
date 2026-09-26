# COBOL Bridge MCP

> AI can translate COBOL, but it can't prove the translation is right. COBOL Bridge is an MCP proof harness: an AI agent ports the program, and deterministic tools check every field of every record against the legacy output, down to the cent.

## The problem

Legacy modernization rarely fails on the big logic. It fails on pennies. COBOL's decimal semantics have no direct equivalent in most modern languages: `ROUNDED` means half-up, a missing `ROUNDED` means truncation, fields have a fixed width with implied decimals, and file framing has its own quirks. A port that "looks right" can be wrong by one cent on a handful of records. Nobody notices until the batch totals fail to reconcile, and then someone traces it by hand.

**Who it's for:** developers and QA engineers porting COBOL batch programs, and the AI agents that increasingly write those ports.

## The solution

COBOL Bridge turns "does the port behave like the original?" into a tool call:

1. **Explain:** `inspect_cobol` reads the source: paragraphs, PIC clauses, `COMPUTE` statements, and flagged traps such as truncation or division.
2. **Characterize:** `capture_golden` compiles and runs the COBOL on synthetic inputs, then freezes the output with a manifest (hashes, compiler, profile). After that, the golden is read-only.
3. **Port:** an AI agent writes the Java.
4. **Verify:** `compare_parity` runs the Java on the same bytes and compares every field and the trailer exactly. Each mismatch names the record, field, expected and actual values, and **the business rule** involved.
5. **Loop:** the agent fixes the Java (never the golden) until every dataset passes.

Because this is exposed as a **Model Context Protocol** server, any MCP-capable agent or IDE can drive it.

## Results

The same 55 synthetic records, the same frozen COBOL goldens and the same checker were used for both ports (`metrics/before_after.md`):

| Java candidate | Datasets passing | Records wrong | Field mismatches | Batch trailers wrong |
|---|---|---|---|---|
| Naive port (deliberate baseline: `double`, banker's rounding, rounded fee) | 0 / 3 | 14 / 55 | 31 | 3 / 3 |
| Faithful port (`BigDecimal`, COBOL rounding and truncation) | **3 / 3** | **0 / 55** | **0** | **0 / 3** |

Every naive error is only one or two cents, for example **1410.94 instead of 1410.95**. The output looks plausible, yet all three batch totals disagree with the legacy system.

## MCP surface

| Name | Kind | What it does |
|---|---|---|
| `inspect_cobol(source_path)` | tool | Heuristic static reading: sha256, paragraphs, data items, computations, unresolved questions |
| `list_datasets()` | tool | Dataset IDs with committed inputs |
| `capture_golden(dataset_id, profile_id, force_new_version)` | tool | Runs COBOL and freezes the golden and its manifest. Refuses to overwrite by default. |
| `run_java(dataset_id, candidate)` | tool | Compiles and runs `java` or `java-naive` on the dataset input |
| `compare_parity(dataset_id, candidate, run_id?)` | tool | Exact record, field and trailer comparison, returned as a JSON report with rule IDs |
| `get_run_report(run_id)` | tool | Reads a stored report |
| `cobolbridge://spec` | resource | Record layouts and business rules |
| `cobolbridge://datasets/{id}` | resource | Golden manifest |
| `modernize_cobol_to_java` | prompt | Checklist: explain → characterize → port → verify → report |

**Safety:**
- All paths are workspace-relative, and absolute paths, `..` and symlink escapes are rejected.
- Subprocesses use fixed argument lists, with timeouts and capped output.
- Goldens are frozen.
- Only synthetic data is used.

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
./dev.sh python -m pytest -q                                # 34 tests
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

No environment variables are required. `COBOLBRIDGE_ROOT` optionally overrides the workspace root.

## Documentation

- `docs/LOANCALC_explained.md`: the program in plain language
- `docs/record_layouts.md`: the byte-level contract
- `docs/business_rules.md`: intended vs observed behaviour, with evidence
- `docs/traceability.md`: rule → COBOL lines → Java method → tests → data
- `metrics/before_after.md`: method and raw counts

## Limitations

- One self-contained synthetic batch program. This is not a general COBOL transpiler.
- Goldens are produced by **GnuCOBOL run locally** and are **not IBM-runtime verified**. Enterprise COBOL results may differ, for example with compiler options such as `ARITH` or `TRUNC`.
- The hosted demo runs Java live against the committed goldens. It does not compile COBOL.
- No live z/OS, CICS, Db2 or VSAM connection. An `imported_legacy_fixture` adapter for EBCDIC/fixed-block exports is the planned next step.

## License

MIT
