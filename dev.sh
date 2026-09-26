#!/usr/bin/env bash
# Run a command inside the dev toolchain container with this repo mounted at /work.
set -euo pipefail
cd "$(dirname "$0")"
if ! docker image inspect cobol-bridge-dev >/dev/null 2>&1; then
  docker build -q -f Dockerfile.dev -t cobol-bridge-dev . >&2
fi
exec docker run --rm -i -v "$PWD":/work -w /work -u "$(id -u):$(id -g)" cobol-bridge-dev "$@"
