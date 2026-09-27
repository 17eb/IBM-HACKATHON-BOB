import json

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_server.server import mcp
from tests.conftest import needs_java
from tests.test_imported_fixture import _import_sources

EXPECTED_TOOLS = {"inspect_cobol", "start_cobol_port", "list_programs", "list_datasets", "prepare_java_port",
                  "verify_java_port", "capture_interactive_golden", "verify_interactive_java",
                  "capture_golden", "import_golden", "run_java", "compare_parity",
                  "get_run_report"}


def call(tool, args):
    async def go():
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            result = await client.call_tool(tool, args)
            return result.structuredContent or json.loads(result.content[0].text)
    return anyio.run(go)


def test_tools_resources_prompts_are_discoverable():
    async def go():
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            tools = {t.name for t in (await client.list_tools()).tools}
            resources = {str(r.uri) for r in (await client.list_resources()).resources}
            prompts = {p.name for p in (await client.list_prompts()).prompts}
            spec = await client.read_resource("cobolbridge://spec")
            return tools, resources, prompts, spec
    tools, resources, prompts, spec = anyio.run(go)
    assert EXPECTED_TOOLS <= tools
    assert "cobolbridge://spec" in resources
    assert "modernize_cobol_to_java" in prompts
    assert "LOAN-OUT" in spec.contents[0].text


def test_path_traversal_rejected_over_mcp(workspace):
    result = call("inspect_cobol", {"source_path": "../../../etc/passwd"})
    assert result["status"] == "error"


def test_unregistered_external_workspace_over_mcp(tmp_path, monkeypatch):
    source = tmp_path / "PAYROLL.cbl"
    source.write_text("       IDENTIFICATION DIVISION.\n       PROGRAM-ID. PAYROLL.\n", encoding="ascii")
    (tmp_path / "sample.dat").write_bytes(b"A001\n")
    (tmp_path / "expected.out").write_bytes(b"A001OK\n")
    monkeypatch.setenv("COBOLBRIDGE_ROOT", str(tmp_path))
    result = call("start_cobol_port", {
        "source_path": "PAYROLL.cbl", "input_path": "sample.dat",
        "reference_output_path": "expected.out",
    })
    assert result["status"] == "ok"
    assert result["registered_programs"] == []
    assert result["files"]["reference_output"]["sha256"]
    assert result["workspace_root"] == str(tmp_path)
    assert call("start_cobol_port", {"source_path": "../PAYROLL.cbl"})["status"] == "error"


def test_programs_are_discoverable_over_mcp(workspace):
    result = call("list_programs", {})
    assert result["status"] == "ok"
    assert "loancalc" in result["programs"]


def test_agent_brief_is_available_over_mcp(workspace):
    result = call("prepare_java_port", {"program_id": "loancalc"})
    assert result["status"] == "ok"
    assert result["all_goldens_ready"]


def test_import_fixture_over_mcp(workspace):
    _import_sources(workspace)
    result = call("import_golden", {
        "dataset_id": "ibm_case", "profile_id": "zos_cp037_fb_example",
        "raw_input_path": "data/import_sources/ibm_case/input.bin",
        "raw_output_path": "data/import_sources/ibm_case/output.bin",
        "evidence_path": "data/import_sources/ibm_case/evidence.json",
    })
    assert result["status"] == "imported"
    assert "ibm_case" in call("list_datasets", {})["datasets"]


@needs_java
def test_agent_acceptance_gate_over_mcp(workspace):
    result = call("verify_java_port", {"program_id": "loancalc"})
    assert result["status"] == "pass"
    assert result["datasets_passed"] == 3


def test_missing_golden_error_over_mcp(workspace):
    (workspace / "data" / "golden" / "ds03_mixed_errors.out").unlink()
    result = call("compare_parity", {"dataset_id": "ds03_mixed_errors", "candidate": "java"})
    assert result["status"] == "error"


@needs_java
def test_compare_parity_over_mcp(workspace):
    result = call("compare_parity", {"dataset_id": "ds02_edges", "candidate": "java"})
    assert result["status"] == "pass" and result["trailer_match"] is True
