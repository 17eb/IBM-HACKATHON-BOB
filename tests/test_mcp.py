import json

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_server.server import mcp
from tests.conftest import needs_java

EXPECTED_TOOLS = {"inspect_cobol", "list_datasets", "capture_golden", "run_java", "compare_parity",
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


def test_missing_golden_error_over_mcp(workspace):
    (workspace / "data" / "golden" / "ds03_mixed_errors.out").unlink()
    result = call("compare_parity", {"dataset_id": "ds03_mixed_errors", "candidate": "java"})
    assert result["status"] == "error"


@needs_java
def test_compare_parity_over_mcp(workspace):
    result = call("compare_parity", {"dataset_id": "ds02_edges", "candidate": "java"})
    assert result["status"] == "pass" and result["trailer_match"] is True
