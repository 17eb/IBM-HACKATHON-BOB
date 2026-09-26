"""COBOL Bridge MCP server (stdio). Thin wrappers over core.workflow.

Run: python -m mcp_server.server
Stdout belongs to the MCP protocol; diagnostics go to stderr only.
"""

from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from core import workflow
from core.paths import workspace_root

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("cobol-bridge")

mcp = FastMCP("cobol-bridge")


@mcp.tool()
def inspect_cobol(source_path: str) -> dict:
    """Read a COBOL source (workspace-relative path). Returns its sha256, paragraphs, data items with PIC
    clauses, COMPUTE statements and unresolved questions for a port. The findings are heuristic."""
    return workflow.inspect_cobol(source_path)


@mcp.tool()
def list_datasets() -> dict:
    """List the dataset IDs that have committed synthetic inputs."""
    return {"status": "ok", "datasets": workflow.list_datasets(), "errors": []}


@mcp.tool()
def capture_golden(dataset_id: str, profile_id: str = "loancalc_local", force_new_version: bool = False) -> dict:
    """Compile and run the legacy COBOL program on a dataset, then freeze its output as the golden, with a
    manifest (hashes, compiler, profile). Refuses to overwrite an existing golden unless force_new_version."""
    log.info("capture_golden %s", dataset_id)
    return workflow.capture_golden(dataset_id, profile_id, force_new_version)


@mcp.tool()
def run_java(dataset_id: str, candidate: str = "java") -> dict:
    """Compile and run a Java candidate ('java' = faithful port, 'java-naive' = deliberate baseline) on the
    dataset's committed input. Returns a run_id for compare_parity."""
    log.info("run_java %s %s", candidate, dataset_id)
    return workflow.run_candidate(dataset_id, candidate)


@mcp.tool()
def compare_parity(dataset_id: str, candidate: str = "java", run_id: str | None = None) -> dict:
    """Exact field-level comparison of a Java candidate against the frozen COBOL golden. If run_id is omitted,
    runs the candidate first. status is 'pass' only with zero record, field and trailer mismatches. Each
    mismatch names record_no, cust_id, field, expected, actual and rule_id."""
    log.info("compare_parity %s %s", candidate, dataset_id)
    return workflow.compare_parity(dataset_id, candidate, run_id)


@mcp.tool()
def get_run_report(run_id: str) -> dict:
    """Read a stored parity report without rerunning anything."""
    return workflow.get_run_report(run_id)


@mcp.resource("cobolbridge://spec")
def spec() -> str:
    """Current record layouts, business rules and limitations."""
    root = workspace_root()
    parts = []
    for name in ("record_layouts.md", "business_rules.md"):
        path = root / "docs" / name
        if path.exists():
            parts.append(path.read_text())
    return "\n\n---\n\n".join(parts)


@mcp.resource("cobolbridge://datasets/{dataset_id}")
def dataset_manifest(dataset_id: str) -> str:
    """The frozen-golden manifest for a dataset (hashes, compiler, profile)."""
    workflow.check_dataset_id(dataset_id)
    path = workspace_root() / "data" / "manifests" / f"{dataset_id}.json"
    return path.read_text() if path.exists() else f'{{"error": "no manifest for {dataset_id}"}}'


@mcp.prompt()
def modernize_cobol_to_java(source_path: str = "legacy/LOANCALC.cbl",
                            dataset_ids: str = "ds01_normal,ds02_edges,ds03_mixed_errors") -> str:
    """Checklist for porting a COBOL batch program to Java with proven parity."""
    return f"""You are modernizing the COBOL program `{source_path}` to Java. Datasets: {dataset_ids}.

1. Explain: call inspect_cobol("{source_path}") and read the cobolbridge://spec resource. Summarise the
   record layouts and rules R1-R5, and list the unresolved questions.
2. Characterize: call capture_golden for each dataset. Goldens are the source of truth, so never edit them.
3. Port: write modern/java/src/main/java/com/cobolbridge/LoanCalc.java. Use BigDecimal only (no double or
   float), with explicit scale and RoundingMode at each assignment. Write one method per COBOL paragraph and
   cite the rule ID in a comment.
4. Verify: call compare_parity(dataset_id, "java") for every dataset. For each mismatch, find the COBOL
   statement for its rule_id, explain the difference, fix the Java, and re-run all datasets.
5. Report: stop only when every dataset passes with trailer_match=true. List each bug found and its fix,
   and update docs/traceability.md."""


def main() -> None:
    log.info("starting cobol-bridge MCP server, root=%s", workspace_root())
    mcp.run()


if __name__ == "__main__":
    main()
