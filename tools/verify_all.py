"""Capture missing goldens, run a Java candidate and check parity on every dataset.

Usage: python -m tools.verify_all [--candidate java|java-naive] [--json]
Exit code 0 only if every dataset passes.
"""

from __future__ import annotations

import argparse
import json
import sys

from core import workflow
from core.paths import PathError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--program", default="loancalc",
                        help="program definition under programs/ (default: loancalc)")
    parser.add_argument("--candidate", default="java",
                        help="Java candidate name from the program definition")
    parser.add_argument("--json", action="store_true", help="print full reports as JSON")
    args = parser.parse_args(argv)

    try:
        datasets = workflow.list_datasets(program_id=args.program)
    except PathError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not datasets:
        print(f"no datasets configured for program {args.program!r}", file=sys.stderr)
        return 2

    reports, ok = [], True
    print(f"{'dataset':<20} {'status':<7} {'records':>7} {'matched':>7} {'mismatch':>8}  trailer  by rule")
    for dataset_id in datasets:
        cap = workflow.capture_golden(dataset_id, program_id=args.program)
        if cap["status"] == "error":
            print(f"{dataset_id:<20} ERROR   capture_golden: {cap['errors']}")
            ok = False
            continue
        report = workflow.compare_parity(dataset_id, args.candidate, program_id=args.program)
        reports.append(report)
        if report["status"] == "error":
            print(f"{dataset_id:<20} ERROR   {report['errors'][0].get('message')}")
            for err in report["errors"]:
                if err.get("stderr"):
                    print(err["stderr"], file=sys.stderr)
            ok = False
            continue
        ok &= report["status"] == "pass"
        print(f"{dataset_id:<20} {report['status'].upper():<7} {report['records_expected']:>7} "
              f"{report['records_matched']:>7} {report['mismatch_count']:>8}  "
              f"{'yes' if report['trailer_match'] else 'NO':<7}  {report['mismatches_by_rule'] or '-'}")
    if args.json:
        print(json.dumps(reports, indent=2))
    print(f"\n{args.candidate}: {'ALL DATASETS PASS' if ok else 'PARITY FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
