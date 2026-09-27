"""Import a synthetic IBM-style EBCDIC FB fixture into a configured program.

All supplied files must be under data/import_sources/. Existing datasets are never replaced.
"""

from __future__ import annotations

import argparse
import json

from core import workflow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dataset_id")
    parser.add_argument("profile_id")
    parser.add_argument("raw_input_path")
    parser.add_argument("raw_output_path")
    parser.add_argument("evidence_path")
    parser.add_argument("--program", default="loancalc")
    args = parser.parse_args(argv)
    result = workflow.import_golden(
        args.dataset_id, args.profile_id, args.raw_input_path,
        args.raw_output_path, args.evidence_path, program_id=args.program,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "imported" else 1


if __name__ == "__main__":
    raise SystemExit(main())
