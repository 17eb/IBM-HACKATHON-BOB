"""COBOL Bridge MCP server (stdio). Thin wrappers over core.workflow.

Run: python -m mcp_server.server
Stdout belongs to the MCP protocol; diagnostics go to stderr only.
"""

from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from core import interactive, workflow
from core.paths import PathError, workspace_root

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("cobol-bridge")

mcp = FastMCP("cobol-bridge")


@mcp.tool()
def inspect_cobol(source_path: str, source_format: str = "auto") -> dict:
    """Read a COBOL source (workspace-relative path). Returns its sha256, paragraphs, data items with PIC
    clauses, COMPUTE statements and unresolved questions for a port. The findings are heuristic."""
    return workflow.inspect_cobol(source_path, source_format=source_format)


@mcp.tool()
def start_cobol_port(source_path: str, input_path: str | None = None,
                     reference_output_path: str | None = None,
                     source_format: str = "auto") -> dict:
    """Start helping with any COBOL file in the connected IDE workspace.

    Paths are relative to COBOLBRIDGE_ROOT. The program need not be registered yet.
    Reads source and optional input/reference output, hashes them, reports toolchain
    readiness and tells the agent what is needed before a Java parity claim. It does
    not run code, import a golden, or assume supplied output is trustworthy.
    """
    return workflow.start_cobol_port(source_path, input_path, reference_output_path,
                                     source_format=source_format)


@mcp.tool()
def capture_interactive_golden(source_path: str, case_id: str, stdin_text: str,
                               source_format: str = "auto") -> dict:
    """Compile a workspace COBOL source with GnuCOBOL, feed scripted stdin and freeze stdout.

    Use for an ACCEPT/DISPLAY program, for example source_path='src/program.cbl',
    case_id='balance', stdin_text='1234\\n1\\n4\\n'. Requires cobc on PATH.
    Refuses to replace an existing case and records source/input/output hashes.
    """
    return interactive.capture_golden(source_path, case_id, stdin_text, workspace_root(),
                                      source_format)


@mcp.tool()
def verify_interactive_java(source_path: str, case_id: str, java_source_dir: str,
                            main_class: str) -> dict:
    """Compile a Java console port, feed the frozen stdin and compare exact stdout bytes.

    Requires a case frozen by capture_interactive_golden. Rejects a changed source,
    input or golden before Java runs. Reports pass only for byte-identical output.
    """
    return interactive.verify_java(source_path, case_id, java_source_dir,
                                   main_class, workspace_root())


@mcp.tool()
def list_programs() -> dict:
    """List configured fixed-width batch programs."""
    return {"status": "ok", "programs": workflow.list_programs(), "errors": []}


@mcp.tool()
def prepare_java_port(program_id: str = "loancalc", candidate: str = "java") -> dict:
    """Return the COBOL source path/hash, Java target and dataset/golden readiness for an agent to port."""
    return workflow.prepare_java_port(program_id, candidate)


@mcp.tool()
def verify_java_port(program_id: str = "loancalc", candidate: str = "java") -> dict:
    """Run the Java candidate against every configured dataset and frozen COBOL golden.

    Returns pass only when all datasets pass; includes per-dataset mismatch and trailer results.
    """
    return workflow.verify_java_port(program_id, candidate)


@mcp.tool()
def list_datasets(program_id: str = "loancalc") -> dict:
    """List datasets for a configured program."""
    try:
        return {"status": "ok", "program_id": program_id,
                "datasets": workflow.list_datasets(program_id=program_id), "errors": []}
    except PathError as exc:
        return {"status": "error", "program_id": program_id, "datasets": [],
                "errors": [{"message": str(exc)}]}


@mcp.tool()
def capture_golden(dataset_id: str, profile_id: str | None = None,
                   force_new_version: bool = False, program_id: str = "loancalc") -> dict:
    """Compile and run the legacy COBOL program on a dataset, then freeze its output as the golden, with a
    manifest (hashes, compiler, profile). Refuses to overwrite an existing golden unless force_new_version."""
    log.info("capture_golden %s", dataset_id)
    return workflow.capture_golden(dataset_id, profile_id, force_new_version, program_id=program_id)


@mcp.tool()
def import_golden(dataset_id: str, profile_id: str, raw_input_path: str,
                  raw_output_path: str, evidence_path: str, program_id: str = "loancalc") -> dict:
    """Import a synthetic EBCDIC FB fixture exported from a declared IBM platform.

    All source paths are workspace-relative and must be under data/import_sources/.
    Preserves raw bytes/evidence and writes canonical files for the existing parity engine.
    A simulated export is labeled simulated; the tool does not contact an IBM system.
    """
    log.info("import_golden %s %s", program_id, dataset_id)
    return workflow.import_golden(dataset_id, profile_id, raw_input_path, raw_output_path,
                                  evidence_path, program_id=program_id)


@mcp.tool()
def run_java(dataset_id: str, candidate: str = "java", program_id: str = "loancalc") -> dict:
    """Compile and run a Java candidate ('java' = faithful port, 'java-naive' = deliberate baseline) on the
    dataset's committed input. Returns a run_id for compare_parity."""
    log.info("run_java %s %s", candidate, dataset_id)
    return workflow.run_candidate(dataset_id, candidate, program_id=program_id)


@mcp.tool()
def compare_parity(dataset_id: str, candidate: str = "java", run_id: str | None = None,
                   program_id: str = "loancalc") -> dict:
    """Exact field-level comparison of a Java candidate against the frozen COBOL golden. If run_id is omitted,
    runs the candidate first. status is 'pass' only with zero record, field and trailer mismatches. Each
    mismatch names record_no, cust_id, field, expected, actual and rule_id."""
    log.info("compare_parity %s %s", candidate, dataset_id)
    return workflow.compare_parity(dataset_id, candidate, run_id, program_id=program_id)


@mcp.tool()
def get_run_report(run_id: str, program_id: str = "loancalc") -> dict:
    """Read a stored parity report without rerunning anything."""
    return workflow.get_run_report(run_id, program_id=program_id)


@mcp.resource("cobolbridge://spec")
def spec() -> str:
    """LOANCALC record layouts and business rules."""
    root = workspace_root()
    parts = []
    for name in ("record_layouts.md", "business_rules.md"):
        path = root / "docs" / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts)


@mcp.resource("cobolbridge://programs/{program_id}/spec")
def program_spec(program_id: str) -> str:
    """Validated program definition for a configured batch job."""
    from core.programs import load_program

    root = workspace_root()
    load_program(root, program_id)
    return (root / "programs" / f"{program_id}.json").read_text(encoding="utf-8")


@mcp.resource("cobolbridge://datasets/{dataset_id}")
def dataset_manifest(dataset_id: str) -> str:
    """The frozen-golden manifest for a dataset (hashes, compiler, profile)."""
    from core.programs import load_program

    workflow.check_dataset_id(dataset_id)
    path = load_program(workspace_root()).manifest_path(dataset_id)
    return path.read_text(encoding="utf-8") if path.exists() else f'{{"error": "no manifest for {dataset_id}"}}'


@mcp.resource("cobolbridge://programs/{program_id}/datasets/{dataset_id}")
def program_dataset_manifest(program_id: str, dataset_id: str) -> str:
    """Manifest for a dataset belonging to a configured program."""
    from core.programs import load_program

    workflow.check_dataset_id(dataset_id)
    program = load_program(workspace_root(), program_id)
    path = program.manifest_path(dataset_id)
    return path.read_text(encoding="utf-8") if path.exists() else f'{{"error": "no manifest for {dataset_id}"}}'


@mcp.prompt()
def modernize_cobol_to_java(source_path: str = "legacy/LOANCALC.cbl",
                            dataset_ids: str = "ds01_normal,ds02_edges,ds03_mixed_errors",
                            program_id: str = "loancalc") -> str:
    """Checklist for porting a COBOL batch program to Java with proven parity."""
    return f"""Modernize {source_path} to Java for program {program_id}. Requested datasets: {dataset_ids}.

Use your host's file editing and execution tools to write the Java code. The MCP server supplies
source context and deterministic checks; it does not generate the port.

1. Call prepare_java_port(program_id="{program_id}"). Read the returned source and program
   definition, the relevant record/rule docs, and cobolbridge://programs/{program_id}/spec.
   Call inspect_cobol(source_path="{source_path}") for heuristic findings, then confirm
   business rules against the actual COBOL source.
2. Ensure each dataset has a frozen golden. Capture a missing one with capture_golden only
   when the declared local compiler/profile is available; never replace an existing golden.
3. Write or update the Java candidate in the configured source directory and main class.
   Preserve exact record framing and decimal assignment semantics. Do not edit the COBOL
   source, committed goldens, or the naive baseline to make parity pass.
4. Call verify_java_port(program_id="{program_id}"). For a failure, inspect its report and
   call compare_parity on the relevant dataset for field, record and rule IDs. Fix Java and
   rerun verify_java_port until every configured dataset and trailer passes.
5. Report source hash, changed Java files, each dataset result, remaining mismatches and
   any environment limitation. Do not claim a successful port without a passing run."""


def main() -> None:
    log.info("starting cobol-bridge MCP server, root=%s", workspace_root())
    mcp.run()


if __name__ == "__main__":
    main()
