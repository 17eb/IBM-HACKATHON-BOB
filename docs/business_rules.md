# LOANCALC business rules: intent vs observed behaviour

All observations come from `legacy/LOANCALC.cbl` compiled with **GnuCOBOL 3.2.0** (`cobc -x -std=default`) and run on the committed synthetic datasets. The frozen outputs are in `data/golden/`, and the provenance is in `data/manifests/`. These results are **not** verified on an IBM runtime.

| ID | Intended rule | Observed COBOL behaviour | Evidence (ds02_edges unless noted) |
|---|---|---|---|
| R1 | Monthly interest = principal × rate ÷ 12, stored to cents with `ROUNDED` | Rounds **half-up** on the exact quotient. An exact half cent always goes up. | E0002000: 169,313.40 × 0.1000 ÷ 12 = 1410.945 → **1410.95** |
| R2 | Over 15 days late: fee = 5% of monthly interest, **not** `ROUNDED`, minimum 5.00 | **Truncates** to cents. The minimum applies when the fee is below 5.00. Exactly 15 days late gives no fee. | E0002005: 316.15 × 0.05 = 15.8075 → **15.80**. E0002010 (15 days): 0.00. E0002011 (16 days): 12.50. E0002014: 0.20 → **5.00** |
| R3 | Over 60 days late: double the fee after the minimum | Doubling happens **after** the minimum, so a minimum fee becomes 10.00. Exactly 60 days late is not doubled. | E0002012 (60): 12.50. E0002013 (61): **25.00**. E0002015: **10.00** |
| R4 | Non-numeric fields, zero principal or zero rate → `ERR`, excluded from totals | The class test `NOT NUMERIC` catches letters, spaces and short records (a short line is padded with spaces). ERR records carry the CUST-ID and all-zero amounts. The program never aborts. | ds03: M0003001 (zero principal), M0003003 (zero rate), M0003004 (`A` in principal), M0003006 (spaces in days), M0003007 (short record) |
| R5 | The trailer counts all records and errors, and sums TOTAL-DUE for OK records | As intended. The trailer is 28 bytes with no trailing padding. | ds03 trailer `TRL000010000005…`: 10 records, 5 errors |

## Characterized platform behaviour (not business rules, but a port must match them)

- **Trailing spaces are dropped** when GnuCOBOL writes a `LINE SEQUENTIAL` record. Every record in the contract ends with a digit, and the Java port strips trailing spaces on write as well.
- **An over-long input line is split.** In a hand test, a 29-byte line was read as a 28-byte record, and the extra byte was read as a *second* record padded with spaces (which then became `ERR`). The Java port reproduces this framing in `readInput`. The committed datasets contain no over-long lines.
- **No overflow in range.** The maximum input (9,999,999.99 at 9.9999) gives interest 8,333,249.99 and a doubled fee of 833,324.98, which exactly fill `9(7)V99` and `9(6)V99`. The Java port still mirrors COBOL high-order truncation (`store`) in case the layout changes.
- **Smallest values.** 0.01 at 0.0001 gives interest 0.00, which is a valid `OK` record. At 16 days late the fee is the 5.00 minimum.
