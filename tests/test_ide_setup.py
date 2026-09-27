import json
import tomllib

from tools.ide_setup import codex_toml, docker_server_config, install_json, server_config


def test_generated_configs_point_at_external_workspace_and_preserve_other_server(tmp_path):
    bridge = tmp_path / "bridge"
    project = tmp_path / "customer-project"
    bridge.mkdir()
    project.mkdir()
    python = bridge / "python.exe"
    config = server_config(python, bridge, project)
    target = project / ".cursor" / "mcp.json"
    target.parent.mkdir()
    target.write_text(json.dumps({"mcpServers": {"other": {"command": "other"}}}))

    assert install_json(project, "cursor", config) == target
    saved = json.loads(target.read_text())
    assert saved["mcpServers"]["other"] == {"command": "other"}
    assert saved["mcpServers"]["cobol-bridge"]["env"]["COBOLBRIDGE_ROOT"] == str(project)
    assert tomllib.loads(codex_toml(config))["mcp_servers"]["cobol-bridge"]["cwd"] == str(bridge)


def test_docker_config_mounts_external_workspace_and_has_valid_codex_toml(tmp_path):
    bridge = tmp_path / "bridge"
    project = tmp_path / "another-project"
    bridge.mkdir()
    project.mkdir()

    config = docker_server_config(bridge, project)

    assert config["command"] == "docker"
    assert f"type=bind,source={bridge},target=/work,readonly" in config["args"]
    assert f"type=bind,source={project},target=/project" in config["args"]
    assert "COBOLBRIDGE_ROOT=/project" in config["args"]
    assert "cwd" not in config
    assert tomllib.loads(codex_toml(config))["mcp_servers"]["cobol-bridge"]["args"] == config["args"]
