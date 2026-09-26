"""Generate the synthetic LOANCALC datasets (deterministic, seeded).

Writes data/inputs/<dataset_id>.dat. All data is synthetic.
Usage: python -m tools.generate_test_data
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUTS = ROOT / "data" / "inputs"
SEED = 20260926
TERMS = [12, 24, 36, 48, 60, 120, 180, 360]


def rec(cust: str, principal_cents: int, rate_bp4: int, term: int, days: int) -> str:
    """Format one 28-byte input record. rate_bp4 is the rate in units of 0.0001."""
    return f"{cust:<8.8}{principal_cents:09d}{rate_bp4:05d}{term:03d}{days:03d}"


def monthly_interest_scaled(principal_cents: int, rate_bp4: int) -> tuple[int, int]:
    """Exact P*R/12 as (quotient, remainder) at scale 6 (cents * 1e-4)."""
    return divmod(principal_cents * rate_bp4, 12)


def find_half_cent(rng: random.Random, want_even_cent: bool) -> tuple[int, int]:
    """Find a loan whose exact monthly interest ends in exactly .xx5 (a half cent)."""
    while True:
        p = rng.randrange(100_000, 50_000_000)
        r = rng.randrange(100, 2_500)
        q, rem = monthly_interest_scaled(p, r)
        if rem == 0 and q % 10_000 == 5_000:
            cent_digit = (q // 10_000) % 10
            if (cent_digit % 2 == 0) == want_even_cent:
                return p, r


def find_fee_third_decimal(rng: random.Random) -> tuple[int, int]:
    """Find a loan (not a half-cent case) whose 5% fee has a third decimal >= 5."""
    while True:
        p = rng.randrange(1_000_000, 50_000_000)
        r = rng.randrange(100, 2_500)
        q, rem = monthly_interest_scaled(p, r)
        if rem == 0 and q % 10_000 == 5_000:
            continue
        cents = (p * r + 60_000) // 120_000  # interest in cents, rounded half-up
        fee4 = cents * 5                     # 5% fee at scale 4 (units of 0.0001)
        if fee4 >= 50_000 and fee4 % 100 >= 50:
            return p, r


def ds01_normal(rng: random.Random) -> list[str]:
    rows = []
    for i in range(20):
        p = rng.randrange(100_000, 50_000_000)  # 1,000.00 .. 500,000.00
        r = rng.randrange(100, 2_500)            # 0.0100 .. 0.2499
        days = rng.choice([0, 0, 0, 5, 10, 20, 30, 45, 75, 90])
        rows.append(rec(f"C{1000 + i:07d}", p, r, rng.choice(TERMS), days))
    return rows


def ds02_edges(rng: random.Random) -> list[str]:
    rows: list[tuple[int, int, int, int, str]] = []
    # R1: exact half-cent interest, preceding cent digit even and odd (HALF_UP vs HALF_EVEN)
    for want_even in (True, True, True, False, False):
        p, r = find_half_cent(rng, want_even)
        rows.append((p, r, 60, 0, "half-cent"))
    # R2: fee with a third decimal >= 5 (truncate vs round)
    for _ in range(5):
        p, r = find_fee_third_decimal(rng)
        rows.append((p, r, 60, 30, "fee-3rd-decimal"))
    # R2/R3 day boundaries on one loan
    base_p, base_r = 2_500_000, 1_200  # 25,000.00 at 12% -> 250.00 interest -> fee 12.50
    for days in (15, 16, 60, 61):
        rows.append((base_p, base_r, 36, days, f"days-{days}"))
    # R2 minimum fee, and minimum then doubled (R3)
    rows.append((100_000, 500, 12, 20, "min-fee"))          # 1,000.00 at 5% -> 4.17 -> fee 5.00
    rows.append((100_000, 500, 12, 75, "min-fee-doubled"))  # -> 10.00
    # Half-cent interest combined with a late fee (R1 feeds R2)
    p, r = find_half_cent(rng, True)
    rows.append((p, r, 60, 45, "half-cent+fee"))
    p, r = find_half_cent(rng, True)
    rows.append((p, r, 60, 90, "half-cent+fee-doubled"))
    # Maximum representable values
    rows.append((999_999_999, 99_999, 999, 0, "max-no-fee"))
    rows.append((999_999_999, 99_999, 999, 999, "max-fee-doubled"))
    # Smallest non-zero values
    rows.append((1, 1, 1, 0, "min-values"))
    rows.append((1, 1, 1, 16, "min-values-min-fee"))
    # Typical loans with and without fees
    for days in (0, 16, 61):
        rows.append((rng.randrange(100_000, 50_000_000), rng.randrange(100, 2_500), 360, days, "typical"))
    return [rec(f"E{2000 + i:07d}", p, r, t, d) for i, (p, r, t, d, _) in enumerate(rows)]


def ds03_mixed_errors(rng: random.Random) -> list[str]:
    good = lambda i, d: rec(f"M{3000 + i:07d}", rng.randrange(100_000, 50_000_000), rng.randrange(100, 2_500), 60, d)
    rows = [
        good(0, 0),
        rec("M0003001", 0, 725, 60, 17),                    # zero principal -> ERR
        good(2, 20),
        rec("M0003003", 1_250_000, 0, 60, 17),              # zero rate -> ERR
        "M0003004" + "0012A0000" + "00725" + "060" + "017", # non-numeric principal -> ERR
        good(5, 65),
        "M0003006" + "001250000" + "00725" + "060" + "  7", # spaces in DAYS-LATE -> ERR
        "M0003007" + "001250000" + "00725",                 # short record (padded with spaces) -> ERR
        good(8, 16),
        good(9, 0),
    ]
    return rows


DATASETS = {
    "ds01_normal": ds01_normal,
    "ds02_edges": ds02_edges,
    "ds03_mixed_errors": ds03_mixed_errors,
}


def main() -> int:
    INPUTS.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    for dataset_id, build in DATASETS.items():
        rows = build(rng)
        assert all(len(r) <= 28 for r in rows), f"{dataset_id}: record longer than 28 bytes"
        (INPUTS / f"{dataset_id}.dat").write_bytes(("\n".join(rows) + "\n").encode("ascii"))
        print(f"{dataset_id}: {len(rows)} records", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
