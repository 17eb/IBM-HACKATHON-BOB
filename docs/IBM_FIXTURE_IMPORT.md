# Import a synthetic IBM runtime fixture

`import_golden` accepts a declared EBCDIC fixed-block (FB) input/output export and freezes it as a dataset for the existing Java parity checker. It does not connect to z/OS or IBM i. A simulated export stays labeled `simulated_ibm_style`; an actual export is labeled `ibm_runtime_export` only when its evidence says so. That label records the supplier's declaration, not independent proof that an IBM job ran.

## Supported export

- Binary, concatenated logical FB records with no newline, RDW, BDW, transfer header, or character conversion during export.
- `cp037`, `cp500`, or `cp1140` single-byte EBCDIC display fields. The configured numeric fields must decode to display digits; packed decimal and binary numeric fields are rejected.
- Input LRECL equal to the program's input layout width, and output LRECL equal to its detail layout width. A shorter trailer occupies the last output record and must be padded with EBCDIC spaces to the output LRECL.
- Synthetic data only. For LOANCALC, the example profile uses input LRECL 28 and output LRECL 37, with a 28-byte trailer plus 9 spaces.

Traditional z/OS FB datasets have fixed LRECL records and no line terminators; VB records carry descriptor words and need a separate decoder. See [IBM record formats](https://www.ibm.com/docs/en/zos-basic-skills?topic=set-data-record-formats). The declared CCSID must match the job's character encoding; see [IBM CODEPAGE](https://www.ibm.com/docs/en/cobol-zos/6.3.0?topic=options-codepage).

## Prepare the files

1. Copy `profiles/zos_cp037_fb_example.json` to a new profile ID for a real IBM export. Set the exact `system`, `encoding`, `source`, `compiler`, `compiler_options`, `input_lrecl`, and `output_lrecl`; set `example_only` to `false`. The example profile itself accepts simulated fixtures only. Declare any copybooks in the profile for review.
2. Put the raw exported input, output, and an evidence JSON file under `data/import_sources/<dataset_id>/`. Use a new dataset ID. The importer never overwrites an existing input, golden, manifest, or archived raw file.
   Raw import directories and the `data/imported/` archive are Git-ignored.
   Review any decoded fixtures separately before adding them to version control.
3. Compute SHA-256 of the exact raw files and the configured COBOL source. On Windows, `Get-FileHash -Algorithm SHA256 <path>` can produce each hash. The evidence JSON must contain:

```json
{
  "program_id": "loancalc",
  "dataset_id": "new_ibm_case",
  "profile_id": "your_real_profile_id",
  "synthetic": true,
  "execution_origin": "ibm_runtime_export",
  "execution_ref": "your-job-or-run-id",
  "executed_at": "2026-09-26T12:00:00Z",
  "source_sha256": "<hash of configured COBOL source>",
  "raw_input_sha256": "<hash of raw input export>",
  "raw_output_sha256": "<hash of raw output export>"
}
```

Use `execution_origin: "simulated_ibm_style"` for a generated test export. The importer verifies all three hashes and the source, dataset, and profile identities before writing anything.

## Import and verify

From the repository root, run:

```powershell
.\.venv\Scripts\python.exe -m tools.import_golden new_ibm_case your_real_profile_id data/import_sources/new_ibm_case/input.bin data/import_sources/new_ibm_case/output.bin data/import_sources/new_ibm_case/evidence.json
.\.venv\Scripts\python.exe -m tools.verify_all --candidate java
```

In IBM Bob, call the MCP tool `import_golden` with the same five values, then call `compare_parity(dataset_id="new_ibm_case", candidate="java")`. No GnuCOBOL compiler is needed for an imported dataset.

The import stores the raw bytes and evidence under `data/imported/<program_id>/<dataset_id>/`, and writes decoded line-sequential input and golden files plus a manifest to the program's configured directories. Every later parity call checks the source, decoded files, archived raw files, evidence hashes, and that decoded records still reproduce the archived export. Reports state `golden_origin: imported_ibm_fixture` and the declared execution origin. Inspect the actual IBM job evidence before describing a result as IBM-runtime verified.

The automated test `python -m pytest -q tests/test_imported_fixture.py` generates a **simulated** CP037 FB export and checks import, Java parity, overwrite refusal, and tamper detection. It does not establish IBM runtime parity.
