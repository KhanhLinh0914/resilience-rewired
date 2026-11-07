"""Runway definitions from the Tangerine track brief.

I  typical monthly money in    median of money_in
S  typical monthly spending    median of money_out
F  typical fixed costs         median of (household bills + insurance + loan payments)
H  household bills             median of household_bills
B  buffer                      mean of avg_daily_balance over the last 6 months
P  loan payment                loans.monthly_payment when the loan is still running
                               (status C or D) at the end of 2025, otherwise 0

F and P are shown on the profile. They are not inputs to runway.

buffer_left = B - one_off_costs
gap         = spending_after_shock - income_after_shock

A job loss with EI at 55% sets income to 0.55 * I.
Household bills up 15% sets spending to S + 0.15 * H.
A one-off repair is subtracted from the buffer.

buffer_left <= 0              runway = 0
gap <= 0                      runway = no shortfall (120+)
otherwise                     runway = min(buffer_left / gap, 120)

Runway is rounded to 1 decimal. The cap of 120 is applied before rounding.
"""

from decimal import Decimal, ROUND_HALF_UP

EI_MONTHS = 6
RUNWAY_CAP = 120


def round1(value: float) -> float:
    cleaned = format(float(value), ".10f")
    return float(Decimal(cleaned).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def runway_result(buffer: float, one_off: float, income: float, spending: float) -> dict:
    buffer_left = float(buffer) - float(one_off)
    gap = float(spending) - float(income)

    if buffer_left <= 0:
        return {
            "buffer_left": buffer_left,
            "gap": gap,
            "kind": "zero",
            "months": 0.0,
            "label": "0.0",
        }

    if gap <= 0:
        return {
            "buffer_left": buffer_left,
            "gap": gap,
            "kind": "surplus",
            "months": None,
            "label": "No shortfall (120+)",
        }

    raw = buffer_left / gap
    capped = min(raw, RUNWAY_CAP)
    months = round1(capped)
    return {
        "buffer_left": buffer_left,
        "gap": gap,
        "kind": "months",
        "months": months,
        "raw_months": raw,
        "label": f"{months:.1f}",
    }


def apply_shock(buffer: float, income_i: float, spending_s: float, bills_h: float, income_pct: float, bill_pct: float, one_off: float) -> dict:
    income = float(income_i) * float(income_pct) / 100.0
    spending = float(spending_s) + float(bills_h) * float(bill_pct) / 100.0
    result = runway_result(buffer, one_off, income, spending)
    result["income"] = income
    result["spending"] = spending
    result["one_off"] = float(one_off)
    return result


def lasts_six_months(result: dict) -> bool:
    if result["kind"] == "surplus":
        return True
    if result["kind"] == "zero":
        return False
    return result["months"] >= EI_MONTHS


def _self_check() -> None:
    sample = runway_result(4000, 0, 1650, 2800)
    assert sample["label"] == "3.5", sample
    assert abs(sample["gap"] - 1150) < 1e-6
    assert runway_result(4000, 4000, 3000, 2800)["kind"] == "zero"
    assert runway_result(4000, 0, 3000, 2800)["kind"] == "surplus"
    assert runway_result(13000, 0, 0, 100)["label"] == "120.0"
    assert round1(1.25) == 1.3
    both = apply_shock(4000, 3000, 2800, 1200, 55, 15, 0)
    assert both["label"] == "3.0", both
    assert abs(both["spending"] - 2980) < 1e-6
    repair = apply_shock(4000, 3000, 2800, 1200, 100, 0, 2800)
    assert repair["kind"] == "surplus"
    assert abs(repair["buffer_left"] - 1200) < 1e-6


if __name__ == "__main__":
    _self_check()
    print("engine ok")
