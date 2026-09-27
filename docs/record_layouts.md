# LOANCALC record layouts: the contract

> **Status: FROZEN v1.0.** Confirmed against the compiled COBOL (GnuCOBOL 3.2.0) and the committed goldens. For observed edge behaviour, see `business_rules.md`.

## Platform profile: `loancalc_local`

| Property | Value |
|---|---|
| System | `local` |
| Compiler | GnuCOBOL 3.2, `cobc -x` in fixed source format. The exact flags are recorded in `legacy/build.sh` and in each manifest. |
| Encoding | ASCII / UTF-8 subset. All bytes are 0x20–0x7E. |
| Record framing | `LINE SEQUENTIAL`: one record per line, terminated by `\n` |
| Numeric storage | DISPLAY only, unsigned. No `COMP-3` in this sample. |
| Golden origin | `local_gnucobol` |

**Trailing-space gotcha:** GnuCOBOL `LINE SEQUENTIAL` **drops trailing spaces** when writing. Because of this, no output record or trailer ends in a space-filled field. Embedded spaces (for example STATUS `OK␠`) are significant and are compared exactly.

## Input record (`LOAN-IN`), 28 bytes

| Field | Cols | Width | PIC | Example | Meaning |
|---|---:|---:|---|---|---|
| CUST-ID | 1–8 | 8 | `X(8)` | `C0000123` | Synthetic ID |
| PRINCIPAL | 9–17 | 9 | `9(7)V99` | `001250000` | 12,500.00 |
| ANNUAL-RATE | 18–22 | 5 | `9V9(4)` | `00725` | 0.0725 |
| TERM-MONTHS | 23–25 | 3 | `9(3)` | `060` | Carried, not used in the math |
| DAYS-LATE | 26–28 | 3 | `9(3)` | `017` | Days past due |

## Output detail record (`LOAN-OUT`), 37 bytes

| Field | Cols | Width | PIC | Rule |
|---|---:|---:|---|---|
| CUST-ID | 1–8 | 8 | `X(8)` | Copied from the input, even for ERR records |
| STATUS | 9–11 | 3 | `X(3)` | `OK␠` or `ERR` (R4) |
| MONTHLY-INT | 12–20 | 9 | `9(7)V99` | R1. All zeros when ERR. |
| LATE-FEE | 21–28 | 8 | `9(6)V99` | R2, R3. All zeros when ERR. |
| TOTAL-DUE | 29–37 | 9 | `9(7)V99` | MONTHLY-INT + LATE-FEE. All zeros when ERR. |

## Trailer record, 28 bytes (written last)

| Field | Cols | Width | PIC | Rule |
|---|---:|---:|---|---|
| TRL-ID | 1–3 | 3 | `X(3)` | Literal `TRL` |
| REC-COUNT | 4–9 | 6 | `9(6)` | All input records read (OK + ERR) |
| ERR-COUNT | 10–15 | 6 | `9(6)` | ERR records |
| TOTAL-DUE-SUM | 16–28 | 13 | `9(11)V99` | Sum of TOTAL-DUE over **OK** records only (R5) |

## Business rules (to be confirmed against compiled COBOL; see `business_rules.md`)

| ID | Rule | COBOL intent |
|---|---|---|
| R1 | MONTHLY-INT = PRINCIPAL × ANNUAL-RATE ÷ 12, rounded to cents | `COMPUTE WS-INT ROUNDED = PRINCIPAL * ANNUAL-RATE / 12` |
| R2 | If DAYS-LATE > 15: LATE-FEE = 5% of MONTHLY-INT, **truncated** (no `ROUNDED`), with a minimum of 5.00. Otherwise 0. | `COMPUTE WS-FEE = WS-INT * 0.05` then `IF WS-FEE < 5.00 MOVE 5.00 TO WS-FEE` |
| R3 | If DAYS-LATE > 60: double the fee **after** the minimum is applied | `COMPUTE WS-FEE = WS-FEE * 2` |
| R4 | A non-numeric PRINCIPAL/ANNUAL-RATE/TERM-MONTHS/DAYS-LATE, or PRINCIPAL = 0, or ANNUAL-RATE = 0, gives `ERR` with zeros. The record is counted in ERR-COUNT and excluded from the sum. | `IF ... IS NOT NUMERIC` class tests |
| R5 | The trailer counts every record, counts the errors, and sums TOTAL-DUE for OK records only | Accumulators |

## Datasets

| ID | Purpose |
|---|---|
| `ds01_normal` | About 20 typical loans |
| `ds02_edges` | Half-cent R1 cases, fees with a 3rd decimal, days late of 15/16/60/61, minimum fee, maximum values |
| `ds03_mixed_errors` | OK and ERR records mixed together: zero principal, zero rate, non-numeric bytes. Exercises the trailer. |

The files are `data/inputs/<id>.dat` → `data/golden/<id>.out`, with a manifest at `data/manifests/<id>.json` containing the sha256 of the source, input and output, the `cobc --version` output, the flags, the profile and a timestamp.
