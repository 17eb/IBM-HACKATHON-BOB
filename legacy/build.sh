#!/usr/bin/env bash
# Compile LOANCALC with GnuCOBOL. Output: legacy/build/loancalc
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build
cobc --version | head -1 >&2
cobc -x -std=default -o build/loancalc LOANCALC.cbl
echo "built legacy/build/loancalc" >&2
