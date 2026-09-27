# LOANCALC, explained for a new developer

**What it does:** once a month, LOANCALC reads a file of loans and works out what each borrower owes this month: interest, plus a late fee if they're behind. It writes one line per loan, then a summary line (the *trailer*) that downstream systems use to reconcile the batch.

## The flow

```
READ a loan ──► valid? ──no──► write ERR line, count an error
                   │
                  yes
                   ▼
        interest = principal × rate ÷ 12   (rounded to the cent)
                   ▼
        more than 15 days late? ──► fee = 5% of interest (cents cut off, not rounded)
                                    fee at least 5.00
                                    more than 60 days late? ──► fee × 2
                   ▼
        total due = interest + fee  → write OK line, add to the batch total
                   ▼
        (next loan…)  →  at end: write TRL line with record count, error count, batch total
```

## Reading the numbers

The files have no decimal points. Each field has a fixed width, and the position of the decimal point is implied by the field's definition (`V` in the COBOL `PIC`).

```
input   C0000123 001250000 00725 060 017
        ID       12,500.00 7.25% 60m 17 days late
output  C0000123 OK  000007552 00000500 000008052
        ID       ok  75.52     5.00     80.52
```

The fee is 5% of 75.52, which is 3.776. That's cut to 3.77 and then raised to the 5.00 minimum.

(The spaces are added here for readability. The real records have none.)

## The traps a port must respect

1. **"Rounded" means half-up.** `COMPUTE … ROUNDED` turns 1410.945 into 1410.95. Many languages default to banker's rounding (half-to-even), which gives 1410.94.
2. **No `ROUNDED` means truncate.** The late-fee `COMPUTE` has no `ROUNDED`, so 15.8075 becomes 15.80, not 15.81.
3. **Order matters.** The 5.00 minimum is applied *before* the fee is doubled, so a 75-day-late minimum fee is 10.00.
4. **Boundaries are strict.** 15 days late means no fee, and 16 means a fee. 60 days late is not doubled, and 61 is.
5. **Bad records don't stop the batch.** A letter, a blank or a short record becomes an `ERR` line with zero amounts, which is counted but excluded from the total.
6. **Framing is part of the behaviour.** GnuCOBOL drops trailing spaces on output and splits over-long input lines.
7. **Never use floating point for money.** The faithful Java port uses `BigDecimal` everywhere.

For the full rules and evidence, see `business_rules.md`. For where each rule lives in COBOL, Java and the tests, see `traceability.md`.
