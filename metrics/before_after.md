# Before / after: naive port vs faithful port

## Method

- **Same inputs:** 3 committed synthetic datasets with 55 detail records and 3 trailers (`data/inputs/`).
- **Same truth:** the COBOL goldens captured once with GnuCOBOL 3.2.0 and frozen (`data/golden/`, hashes in `data/manifests/`).
- **Same checker:** `compare_parity` (`core/parity.py`), which compares every field exactly, with no trimming and no tolerance.
- **Before** is `modern/java-naive`, a **deliberately** naive port of the kind written from the record layout alone: `double` arithmetic, `Math.rint` (HALF_EVEN) for interest, and a rounded late fee.
- **After** is `modern/java`, the faithful port: `BigDecimal`, half-up for `ROUNDED`, truncation where COBOL has no `ROUNDED`, and COBOL framing.
- To reproduce: `python -m tools.verify_all --candidate java-naive` and `python -m tools.verify_all --candidate java`. The full reports are in `metrics/reports/`.

## Results (raw counts)

| Candidate | Datasets passing | Detail records wrong | Field mismatches | Trailers wrong |
|---|---|---|---|---|
| Naive (before) | 0 / 3 | 14 / 55 | 31 | 3 / 3 |
| Faithful (after) | **3 / 3** | **0 / 55** | **0** | **0 / 3** |

The naive mismatches by rule are R1 ×3, R2 ×8, R3 ×3, derived TOTAL-DUE ×14 and R5 trailer sum ×3. None came from R4. The naive port handles bad input the same way COBOL does.

**Every naive error is one or two cents.** For example, E0002000 gives interest 1410.94 where COBOL gives 1410.95, and E0002005 gives a fee of 15.81 where COBOL gives 15.80. The output looks plausible, and a spot check or a test based on totals would not catch it. Yet all three batch trailers disagree with the legacy system, and that is the kind of discrepancy that turns into a manual reconciliation ticket.

Only 3 of the 5 half-cent cases failed for the naive port. Banker's rounding only diverges when the preceding digit is even, and binary `double` error sometimes nudges the value in either direction. The failures depend on the data, which is why exact, record-by-record parity is needed.

## Limits of this evidence

This is one synthetic program with 55 records. It shows that the harness catches cent-level drift, names the record, field and rule, and confirms a fix. It does not estimate effort savings for real COBOL estates. The goldens are GnuCOBOL local output and are not IBM-runtime verified.
