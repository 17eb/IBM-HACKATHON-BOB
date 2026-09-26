# AGENTS.md: instructions for coding agents

The full design is in `docs/BUILD_GUIDE.md`. The record contract is in `docs/record_layouts.md`. **Read both before you change code.** This file is the condensed version for a 31-hour hackathon build (deadline Sun Sep 27, 23:00 PHT).

## Mission

We're building an MCP server that lets an AI agent **port the `LOANCALC` COBOL batch program to Java and prove parity**, meaning exact, field-level equality with frozen COBOL outputs. "Done" means that `compare_parity` returns 0 mismatches and a matching trailer on every dataset.

## Hard rules

1. **The COBOL goldens are the truth.** Never edit `data/golden/*` or `legacy/LOANCALC.cbl` to make Java pass. When parity fails, fix the **Java**.
2. **No `double` or `float`** in `modern/java` (the faithful port). Use `BigDecimal`, with explicit scale and `RoundingMode` at every assignment. The deliberately naive baseline lives only in `modern/java-naive` and must stay naive, because it's our "before" metric.
3. **Only standard libraries for Java** (Java 17 API, compiled with `javac --release 17`). No Maven or Gradle. Python uses only the deps in `pyproject.toml`.
4. **MCP stdio hygiene:** never `print()` to stdout inside `mcp_server/` or `core/`. Log to stderr.
5. **Safety:** every path argument is workspace-relative. Reject absolute paths, `..` and symlink escapes. Run subprocesses with argument lists (never `shell=True`), plus timeouts and output caps. `capture_golden` refuses to overwrite an existing golden unless `force_new_version=true`.
6. **Shared core:** the MCP server, the CLI (`tools/verify_all.py`), the tests and the Streamlit app all call `core/`. Parity logic exists in exactly one place: `core/parity.py`.
7. **Honesty:** goldens are "GnuCOBOL local". Never write "IBM-verified". Never hardcode a green result.
8. **Synthetic data only.**

## Layout

```
legacy/LOANCALC.cbl, legacy/build.sh      COBOL source and a compile/run script
tools/generate_test_data.py               deterministic (seeded) dataset generator
data/{inputs,golden,manifests}/           <dataset_id>.dat / .out / .json
core/records.py                           layout definitions, parse/format fixed-width
core/runners.py                           run COBOL / compile+run Java (bounded subprocess)
core/parity.py                            exact compare → report dict (record/field/rule/trailer)
core/paths.py                             workspace-root path validation
core/workflow.py                          shared operations used by MCP, CLI, tests and app
adapters/local_gnucobol.py                capture_golden implementation
mcp_server/server.py                      FastMCP server (mcp==1.30.0), stdio
modern/java/                              faithful port   com.cobolbridge.LoanCalc
modern/java-naive/                        naive baseline  com.cobolbridge.naive.LoanCalcNaive
reports/<run_id>.json                     parity reports (git-ignored; curated copies in metrics/reports/)
app/streamlit_app.py                      hosted demo (runs Java live vs committed goldens)
tests/                                    pytest
```

Java CLI contract (both ports): `java -cp <build> <MainClass> <input.dat> <output.out>`, with exit code 0 on success.

## MCP surface

| Name | Kind | Contract |
|---|---|---|
| `inspect_cobol(source_path)` | tool | sha256, paragraph names, FD/record fields with PICs, unresolved questions. The output is labeled `"heuristic": true`. |
| `capture_golden(dataset_id, profile_id="loancalc_local", force_new_version=false)` | tool | Compiles and runs COBOL, then writes the golden and manifest |
| `run_java(dataset_id, candidate="java"\|"java-naive")` | tool | Compiles and runs that port on `data/inputs/<id>.dat` and writes `runs/<run_id>/output.out` |
| `compare_parity(dataset_id, candidate="java"\|"java-naive", run_id=None)` | tool | Runs Java if `run_id` is None, compares against the golden, writes `reports/<run_id>.json`. `status` is `"pass"` or `"fail"`. |
| `get_run_report(run_id)` | tool | Reads a stored report |
| `cobolbridge://spec` | resource | Contents of `docs/record_layouts.md` and `docs/business_rules.md` |
| `modernize_cobol_to_java(source_path, dataset_ids)` | prompt | Checklist: explain → characterize → port → verify → report |

Every tool returns JSON with `status`, `dataset_id`, `artifact_paths` and `errors` (where relevant).

The parity report contains `dataset_id`, `candidate`, `run_id`, `golden_sha256`, `candidate_sha256`, `records_expected`, `records_actual`, `records_matched`, `mismatch_count`, `trailer_match`, and `mismatches[]` with `{record_no, cust_id, field, expected, actual, rule_id}`. Field-to-rule map: MONTHLY-INT→R1, LATE-FEE→R2/R3 (R3 if DAYS-LATE > 60), TOTAL-DUE→R1+R2, STATUS→R4, trailer fields→R5.

## Parity-debug loop (use the MCP tools)

1. `compare_parity` → read the first mismatch (record, field, expected vs actual, rule).
2. Find the COBOL statement and the Java method for that rule. Check parse scale, rounding mode, truncation vs rounding, order of operations (minimum before doubling), and accumulators.
3. Fix the Java. Re-run `compare_parity` on **all** datasets.
4. Update `docs/traceability.md` (rule → COBOL lines → Java method → test).

## Commands (keep these working)

```bash
# prefix with ./dev.sh to run inside the toolchain container
bash legacy/build.sh                       # compile COBOL -> legacy/build/loancalc
python -m tools.generate_test_data         # write data/inputs/*.dat (seeded)
python -m tools.verify_all --candidate java   # capture missing goldens, run java, parity for every dataset
python -m pytest -q
```
