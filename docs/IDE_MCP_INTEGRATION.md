# IDE integration

COBOL Bridge runs as a local Model Context Protocol (MCP) stdio server. An IDE
agent reads and edits the developer's project, while Bridge supplies source
inspection, COBOL execution, fixture capture, and parity checks. The Bridge
checkout and the COBOL project may be in different directories.

## Requirements

- Python 3.11 or later with this project's dependencies installed in `.venv`.
- An MCP-capable IDE agent, such as IBM Bob, Cursor, Antigravity, or Codex.
- GnuCOBOL (`cobc`) to capture a new local reference output.
- JDK 17 or later to verify a Java port.

The included `Dockerfile.dev` provides GnuCOBOL, Java, and Python when those
tools are not installed on the host. The IDE must be able to launch either the
local Python environment or Docker.

## Generate a project connection

Open PowerShell in the **COBOL project directory** that the IDE has opened.
Replace the placeholder below with the absolute path to your COBOL Bridge
checkout:

```powershell
$bridge = '<path-to-cobol-bridge-checkout>'
$workspace = (Get-Location).Path
& "$bridge\.venv\Scripts\python.exe" "$bridge\tools\ide_setup.py" --workspace $workspace --client bob
```

Choose `cursor`, `antigravity`, `codex`, or `generic` instead of `bob` for another
client. `all` writes the Bob, Cursor, and Antigravity project entries and prints
a Codex configuration snippet. The generator preserves unrelated MCP servers in
existing JSON configuration files. For Codex, merge the printed snippet into
the active `config.toml`.

The generated configuration launches the Bridge server from its checkout and
sets `COBOLBRIDGE_ROOT` to the COBOL project. Tool file paths are relative to
that root. Re-run setup if either directory moves. Generated project MCP files
are ignored by Git because they contain machine-specific absolute paths.

### Docker runtime

Build the development image once from the Bridge checkout:

```powershell
docker build -f "$bridge\Dockerfile.dev" -t cobol-bridge-dev "$bridge"
docker run --rm cobol-bridge-dev cobc --version
```

Then generate a Docker-backed connection for the open COBOL project:

```powershell
& "$bridge\.venv\Scripts\python.exe" "$bridge\tools\ide_setup.py" --workspace $workspace --client bob --runtime docker
```

Docker mounts the Bridge checkout read-only at `/work` and the COBOL project
read-write at `/project`. Restart the IDE's MCP server after changing its
configuration. Rebuild the image when `Dockerfile.dev` or its dependencies
change; Python source edits in the mounted checkout are available after an MCP
restart.

## Use from an IDE agent

Enable the `cobol-bridge` MCP server in the IDE, then ask the agent to call
`start_cobol_port` with a path relative to the COBOL project. The result reports
the source hash, a heuristic structure summary, detected I/O mode, and
available compilers. The agent should read the source before porting it.

For a console program using `ACCEPT` and `DISPLAY`, follow
[interactive transcript verification](INTERACTIVE_TRANSCRIPTS.md). For a
fixed-width batch program, create a [program profile](PROGRAM_PROFILES.md),
capture or import a reference output, and use `verify_java_port`.

Example request for a console program:

> Explain `src/program.cbl` in plain language. Choose synthetic input cases
> covering normal and error behavior. Use COBOL Bridge to capture real COBOL
> transcripts, write a Java console port, and verify every case against the
> frozen outputs. Report coverage and remaining limitations.

The IDE agent writes the Java code; COBOL Bridge executes and compares it.
The COBOL program does not call MCP. A reference output supplied by a user is
not treated as verified until its provenance has been established.

## Connection scope and troubleshooting

Project configuration is preferable when developers switch between COBOL
projects: each project's MCP entry points to its own root. IBM Bob can also
load a global entry from `~/.bob/settings/mcp.json`; update
`COBOLBRIDGE_ROOT` when switching projects. Keep global and generated MCP
configuration files out of version control.

If the tools do not appear, restart the MCP server and confirm that the
configured Python or Docker command runs, the Bridge checkout exists, and the
workspace root contains the requested source. If capture reports that `cobc`
is unavailable, install GnuCOBOL or use the Docker runtime above.
