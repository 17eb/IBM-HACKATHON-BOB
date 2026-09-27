"""Generate a local stdio MCP connection for an IDE workspace.

Run with the Python environment that has cobol-bridge-mcp installed. The bridge
code stays in this repository; COBOLBRIDGE_ROOT points its tools at the project
that the developer has open in an IDE.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


CONFIG_PATHS = {
    "bob": Path(".bob/mcp.json"),
    "cursor": Path(".cursor/mcp.json"),
    "antigravity": Path(".agents/mcp_config.json"),
}


def server_config(python: Path, bridge_root: Path, workspace: Path) -> dict:
    return {
        "command": str(python.resolve()),
        "args": ["-m", "mcp_server.server"],
        "cwd": str(bridge_root.resolve()),
        "env": {"COBOLBRIDGE_ROOT": str(workspace.resolve())},
    }


def docker_server_config(bridge_root: Path, workspace: Path) -> dict:
    """Run the same MCP server with compilers available inside the dev image."""
    return {
        "command": "docker",
        "args": [
            "run", "--rm", "-i",
            "--mount", f"type=bind,source={bridge_root.resolve()},target=/work,readonly",
            "--mount", f"type=bind,source={workspace.resolve()},target=/project",
            "-w", "/work", "-e", "COBOLBRIDGE_ROOT=/project",
            "cobol-bridge-dev", "python", "-m", "mcp_server.server",
        ],
        "env": {},
    }


def codex_toml(config: dict) -> str:
    """A snippet for Codex's shared CLI/IDE config.toml."""
    quoted = lambda value: json.dumps(value, ensure_ascii=False)
    output = ("[mcp_servers.cobol-bridge]\n"
              f"command = {quoted(config['command'])}\n"
              f"args = [{', '.join(quoted(arg) for arg in config['args'])}]\n")
    if "cwd" in config:
        output += f"cwd = {quoted(config['cwd'])}\n"
    if config.get("env"):
        output += "[mcp_servers.cobol-bridge.env]\n"
        output += "".join(f"{key} = {quoted(value)}\n" for key, value in config["env"].items())
    return output


def install_json(workspace: Path, client: str, config: dict) -> Path:
    return install_json_path(workspace / CONFIG_PATHS[client], config)


def install_json_path(path: Path, config: dict) -> Path:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
            raise ValueError(f"{path} must contain an object with mcpServers")
    else:
        data = {}
    data.setdefault("mcpServers", {})["cobol-bridge"] = config
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, default=Path.cwd(),
                        help="Existing project directory opened in the IDE (default: current directory)")
    parser.add_argument("--client", choices=(*CONFIG_PATHS, "codex", "generic", "all"),
                        required=True)
    parser.add_argument("--runtime", choices=("local", "docker"), default="local",
                        help="Run with local Python or the cobol-bridge-dev Docker image")
    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        parser.error(f"workspace does not exist: {workspace}")
    bridge_root = Path(__file__).resolve().parent.parent
    config = (docker_server_config(bridge_root, workspace) if args.runtime == "docker"
              else server_config(Path(sys.executable), bridge_root, workspace))

    if args.client in CONFIG_PATHS or args.client == "all":
        selected = CONFIG_PATHS if args.client == "all" else (args.client,)
        for client in selected:
            print(f"Configured {client}: {install_json(workspace, client, config)}")
    if args.client in ("codex", "all"):
        print("Add this to your Codex config.toml (shared by the CLI and IDE extension):\n")
        print(codex_toml(config))
    if args.client == "generic":
        print(json.dumps({"mcpServers": {"cobol-bridge": config}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
