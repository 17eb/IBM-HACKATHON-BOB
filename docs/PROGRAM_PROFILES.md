# Add another COBOL batch program

The runner and parity checker now read a program definition from programs/<program_id>.json.
The LOANCALC definition is a complete example. A second program needs source files, a
definition, synthetic inputs, and a platform profile; it does not need Python changes.

## Supported contract

- One fixed-width detail record per line. Candidate output may use LF or CRLF, but
  frozen input and golden bytes must match the exact SHA-256 values in their manifest.
- ASCII or Latin-1 single-byte fields. Field widths are byte widths.
- An optional, distinct trailer prefix on the final output record.
- A COBOL executable that accepts input and output file paths as two arguments.
- A Java main class that accepts the same two arguments and can be compiled with javac
  targeting Java 17. Candidate code must write the output file.
- Exact field and trailer comparison. A field can carry a rule ID; optional threshold
  overrides can assign a different rule ID from an integer input field.

This is a reusable harness for this class of batch job. The separate IBM fixture adapter
can import declared EBCDIC FB display records and decode them into this layout; see
IBM_FIXTURE_IMPORT.md. The harness does not parse arbitrary COBOL copybooks, packed
decimal, VB datasets, or automatically write the Java port.

## Add a program

1. Copy programs/loancalc.json to programs/<program_id>.json. Set program_id to the new
   lowercase identifier. Put its paths in dedicated directories so datasets and reports
   cannot collide with LOANCALC.
2. Set cobol.source, cobol.binary and cobol.flags. Add the source file. The runner compiles
   it with cobc and passes input and output paths to the executable.
3. Set candidates.java.source_dir, build_dir and main_class. Add the Java source. The runner
   compiles all Java files below source_dir, then calls the main class with the same input.
4. Define input_fields, detail_fields and, if present, trailer_fields in byte order. Each
   field needs a name and positive width. Add scale for implied-decimal numeric fields and
   rule for mismatch reports. Set identifier_field to a detail field. For a trailer, set a
   prefix that cannot be confused with a detail record. The sum of field widths is the
   expected record width; unexpected bytes are reported as a length mismatch.
5. Add profiles/<platform_profile>.json with system, encoding, record_format and
   golden_origin metadata. Local capture currently requires golden_origin=local_gnucobol.
6. Add synthetic data/inputs/<dataset_id>.dat files under the configured input directory.
   Each filename stem is a lowercase dataset ID. Keep real customer data out of the demo.
7. Run the command below. A missing golden is captured by compiling and running COBOL.
   An existing golden is left frozen. Each dataset must have a manifest whose source,
   input and golden hashes match the saved bytes; a missing or changed manifest or
   fixture stops parity before Java runs. Java then runs on the verified input, and
   any detail or trailer difference gives a failing exit code and a JSON report.

~~~text
python -m tools.verify_all --program <program_id> --candidate java
~~~

Run the original example with:

~~~text
python -m tools.verify_all --program loancalc --candidate java
~~~

For local CLI use, install Python and a JDK with javac. GnuCOBOL is needed only to capture
a new golden. The development container in Dockerfile.dev includes all three toolchains.
Git attributes keep `.dat` and `.out` fixtures byte-exact on Windows, and COBOL source
files use LF. A line-ending change to a frozen fixture is an integrity error even if
its parsed records would be equivalent.

## Test without an IDE

The CLI is the simplest end-to-end test: a successful run shows every dataset passing and
exits 0; a mismatch exits 1 and writes a report under the configured reports directory.
The test suite also creates a second, two-field program profile with its own Java class
and trailer. That test proves the same runner and checker work with different record
widths, field names and rules.

An IDE is not required to run or test parity. To let IBM Bob or another MCP-capable IDE
drive the workflow, install the Python MCP dependency, start the stdio server with
python -m mcp_server.server, and configure the IDE to launch that command in the repo
directory. First call list_programs, then list_datasets(program_id), then
compare_parity(dataset_id, candidate="java", program_id=program_id). The MCP wrapper
uses the same core code and returns the same report as the CLI. A real IDE connection
is an integration test of the wrapper, not a prerequisite for testing the core.
