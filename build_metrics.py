"""Build one row per account from the track files.

The dashboard reads data/account_metrics.csv. Runway math lives in engine.py
so the table and the live shock use the same rules.
"""

import json

import pandas as pd

from engine import _self_check, apply_shock, lasts_six_months
from paths import (
    ACCOUNTS,
    CARDS,
    CLIENTS,
    DATA,
    DISPOSITIONS,
    DISTRICTS,
    LOANS,
    METRICS,
    MONTHLY,
    STANDING_ORDERS,
    SUMMARY,
)


def money(value: float) -> str:
    if pd.isna(value):
        return "n/a"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def load_profile() -> pd.DataFrame:
    accounts = pd.read_csv(ACCOUNTS)
    clients = pd.read_csv(CLIENTS)
    districts = pd.read_csv(DISTRICTS)
    dispositions = pd.read_csv(DISPOSITIONS)
    cards = pd.read_csv(CARDS)
    loans = pd.read_csv(LOANS, parse_dates=["loan_start"])
    orders = pd.read_csv(STANDING_ORDERS)

    owners = dispositions[dispositions["type"].str.lower() == "owner"].copy()
    owners = owners.sort_values("disposition_id").drop_duplicates("account_id", keep="first")
    clients = clients.rename(columns={"district_id": "home_district_id"})
    owners = owners.merge(clients, on="client_id", how="left")
    born = pd.to_datetime(owners["birth_date"], errors="coerce")
    owners["owner_age"] = ((pd.Timestamp("2025-12-31") - born).dt.days / 365.25).floordiv(1)

    branch = districts.rename(
        columns={
            "district_id": "district_id",
            "district_name": "district_name",
            "region": "region",
            "average_salary": "district_average_salary",
            "unemployment_rate_2023": "district_unemployment_2023",
        }
    )
    keep_district = [
        "district_id",
        "district_name",
        "region",
        "district_average_salary",
        "district_unemployment_2023",
    ]

    card_names = cards.merge(dispositions[["disposition_id", "account_id"]], on="disposition_id", how="left")
    card_list = (
        card_names.dropna(subset=["account_id"])
        .groupby("account_id")["card_type"]
        .apply(lambda values: ", ".join(sorted(set(values.dropna()))))
        .rename("cards")
    )

    order_total = orders.groupby("account_id")["amount"].sum().rename("standing_orders")

    loans = loans.sort_values(["account_id", "loan_start"])
    running = loans["status"].isin(["C", "D"])
    chosen = loans.loc[running].drop_duplicates("account_id", keep="last")
    if chosen.empty:
        chosen = loans.iloc[0:0]
    loan_cols = chosen[
        ["account_id", "monthly_payment", "status", "status_meaning", "defaulted", "loan_start", "duration_months"]
    ].rename(
        columns={
            "monthly_payment": "loan_payment_p",
            "status": "loan_status",
            "status_meaning": "loan_status_meaning",
            "defaulted": "loan_defaulted",
        }
    )

    profile = accounts.merge(owners[["account_id", "gender", "owner_age"]], on="account_id", how="left")
    profile = profile.merge(branch[keep_district], on="district_id", how="left")
    profile = profile.merge(card_list, on="account_id", how="left")
    profile = profile.merge(order_total, on="account_id", how="left")
    profile = profile.merge(loan_cols, on="account_id", how="left")
    profile["loan_payment_p"] = profile["loan_payment_p"].fillna(0.0)
    profile["standing_orders"] = profile["standing_orders"].fillna(0.0)
    profile["loan_status"] = profile["loan_status"].fillna("")
    profile["loan_status_meaning"] = profile["loan_status_meaning"].fillna("no loan")
    return profile


def monthly_metrics() -> tuple[pd.DataFrame, pd.DataFrame]:
    monthly = pd.read_csv(MONTHLY)
    duplicate_months = int(monthly.duplicated(["account_id", "month"]).sum())
    if duplicate_months:
        monthly = monthly.drop_duplicates(["account_id", "month"], keep="last")

    monthly["fixed"] = (
        monthly["household_bills"].fillna(0)
        + monthly["insurance"].fillna(0)
        + monthly["loan_payments"].fillna(0)
    )
    grouped = monthly.groupby("account_id", sort=False)
    summary = grouped.agg(
        income_i=("money_in", "median"),
        spending_s=("money_out", "median"),
        fixed_f=("fixed", "median"),
        bills_h=("household_bills", "median"),
        insurance=("insurance", "median"),
        loan_payments_median=("loan_payments", "median"),
        bank_fees=("bank_fees", "median"),
        pension_median=("pension_in", "median"),
        n_months=("month", "size"),
        first_month=("month", "min"),
        last_month=("month", "max"),
    ).reset_index()

    ordered = monthly.sort_values(["account_id", "month"])
    last6 = ordered.groupby("account_id", sort=False).tail(6)
    buffer = last6.groupby("account_id", sort=False).agg(
        buffer_b=("avg_daily_balance", "mean"),
        buffer_months=("month", "size"),
        days_below_zero_last6=("days_below_zero", "sum"),
    ).reset_index()
    summary = summary.merge(buffer, on="account_id", how="left")
    summary.attrs["duplicate_months"] = duplicate_months
    summary.attrs["null_money_in"] = int(monthly["money_in"].isna().sum())
    return summary, monthly


def find_samples(metrics: pd.DataFrame) -> dict:
    samples = {}
    scored = []
    for row in metrics.itertuples(index=False):
        if pd.isna(row.income_i) or pd.isna(row.buffer_b):
            continue
        result = apply_shock(row.buffer_b, row.income_i, row.spending_s, row.bills_h, 55, 0, 0)
        scored.append((row.account_id, result))

    teaching = [
        (account_id, result["months"])
        for account_id, result in scored
        if result["kind"] == "months" and result["months"] is not None and 2 <= result["months"] <= 5
    ]
    if teaching:
        samples["teaching"] = int(min(teaching, key=lambda item: abs(item[1] - 3.5))[0])

    safe = [
        account_id
        for account_id, result in scored
        if result["kind"] == "surplus"
    ]
    if safe:
        safe_rows = metrics[metrics["account_id"].isin(safe)].nlargest(1, "buffer_b")
        samples["safe"] = int(safe_rows.iloc[0]["account_id"])

    loans = metrics[metrics["loan_status"].isin(["C", "D"])]
    if not loans.empty:
        samples["loan"] = int(loans.nlargest(1, "loan_payment_p").iloc[0]["account_id"])

    pension = metrics[(metrics["income_i"] > 500) & (metrics["pension_median"] >= 0.4 * metrics["income_i"])]
    if not pension.empty:
        samples["pension"] = int(pension.nlargest(1, "pension_median").iloc[0]["account_id"])
    return samples


def cohort_summary(metrics: pd.DataFrame) -> dict:
    usable = metrics.dropna(subset=["income_i", "spending_s", "bills_h", "buffer_b"]).copy()
    fails = 0
    gaps = []
    for row in usable.itertuples(index=False):
        result = apply_shock(row.buffer_b, row.income_i, row.spending_s, row.bills_h, 55, 0, 0)
        if result["kind"] == "months":
            gaps.append(result["gap"])
        if not lasts_six_months(result):
            fails += 1

    n = int(len(usable))
    fail_pct = 100.0 * fails / n if n else 0.0
    already_short = int((usable["spending_s"] > usable["income_i"]).sum())
    already_short_pct = 100.0 * already_short / n if n else 0.0
    thin = usable[(usable["income_i"] > 0) & (usable["spending_s"] >= 0.9 * usable["income_i"])]
    thin_pct = 100.0 * len(thin) / n if n else 0.0
    below_zero = int((usable["days_below_zero_last6"] > 0).sum())
    below_zero_pct = 100.0 * below_zero / n if n else 0.0
    median_gap = float(pd.Series(gaps).median()) if gaps else 0.0
    median_buffer = float(usable["buffer_b"].median())

    sentence = (
        f"The median buffer is {money(median_buffer)}, which looks comfortable. "
        f"If income falls to 55% and spending stays typical, {fail_pct:.0f}% of {n:,} accounts "
        f"still run out before 6 months. {thin_pct:.0f}% already spend at least 90% of typical money in, "
        f"so the gap under EI is large even when the balance looks healthy."
    )
    detail = (
        f"Before any shock, {already_short_pct:.0f}% already spend more than they take in. "
        f"Among accounts that still have a monthly gap under EI, the median gap is {money(median_gap)}. "
        f"{below_zero_pct:.0f}% finished at least one day below zero in the last 6 months."
    )
    return {
        "n_accounts": n,
        "ei_fail_pct": round(fail_pct, 1),
        "ei_fail_n": fails,
        "already_short_pct": round(already_short_pct, 1),
        "thin_spend_pct": round(thin_pct, 1),
        "days_below_zero_pct": round(below_zero_pct, 1),
        "median_buffer": round(median_buffer, 2),
        "median_ei_gap": round(median_gap, 2),
        "sentence": sentence,
        "detail": detail,
    }


def main() -> None:
    _self_check()
    DATA.mkdir(parents=True, exist_ok=True)
    profile = load_profile()
    summary, _monthly = monthly_metrics()
    metrics = profile.merge(summary, on="account_id", how="left")
    metrics["buffer_percentile"] = metrics["buffer_b"].rank(pct=True, method="average")

    samples = find_samples(metrics)
    findings = cohort_summary(metrics)
    findings["samples"] = samples
    findings["duplicate_months"] = int(summary.attrs.get("duplicate_months", 0))
    findings["null_money_in"] = int(summary.attrs.get("null_money_in", 0))

    metrics = metrics.sort_values("account_id")
    metrics.to_csv(METRICS, index=False)
    SUMMARY.write_text(json.dumps(findings, indent=2), encoding="utf-8")

    print(f"wrote {len(metrics):,} accounts to {METRICS}")
    print(findings["sentence"])
    print(findings["detail"])
    print("samples", samples)
    if "teaching" in samples:
        row = metrics.loc[metrics["account_id"] == samples["teaching"]].iloc[0]
        result = apply_shock(row.buffer_b, row.income_i, row.spending_s, row.bills_h, 55, 0, 0)
        print(
            "teaching",
            int(row.account_id),
            "I", round(row.income_i, 2),
            "S", round(row.spending_s, 2),
            "B", round(row.buffer_b, 2),
            "H", round(row.bills_h, 2),
            "runway", result["label"],
            "gap", round(result["gap"], 2),
        )


if __name__ == "__main__":
    main()
