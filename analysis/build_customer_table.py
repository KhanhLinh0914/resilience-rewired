"""
Builds the one-row-per-customer table for all 4,500 accounts.

Run from the repo root:
    python analysis/build_customer_table.py
It writes analysis/output/customer_table.csv (one row per account).

Runway and shocks come from the team's engine.py in the repo root,
so the analysis and the dashboard use exactly the same formula.
"""

import os
import sys
import pandas as pd

# Make the repo root importable, then use the team's engine.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as team_engine  # noqa: E402

DATA_DIR = "data"
OUT_DIR = "analysis/output"


# ---------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------
def load_data(data_dir=DATA_DIR):
    ms = pd.read_csv(f"{data_dir}/monthly_summary.csv")
    loans = pd.read_csv(f"{data_dir}/loans.csv")
    accounts = pd.read_csv(f"{data_dir}/accounts.csv")
    districts = pd.read_csv(f"{data_dir}/districts.csv")
    clients = pd.read_csv(f"{data_dir}/clients.csv")
    disps = pd.read_csv(f"{data_dir}/dispositions.csv")
    cards = pd.read_csv(f"{data_dir}/cards.csv")
    return ms, loans, accounts, districts, clients, disps, cards


# ---------------------------------------------------------------
# 2. Runway formula: uses the team's engine.py (same one the dashboard uses)
# ---------------------------------------------------------------
def runway(B, income, spending, one_off=0.0):
    """Returns (runway_months, label). 'No shortfall' is stored as 120."""
    r = team_engine.runway_result(B, one_off, income, spending)
    months = 120.0 if r["kind"] == "surplus" else r["months"]
    return months, r["label"]


def apply_shock(p, ei_rate=None, bills_up=0.0, one_off=0.0):
    """
    p        : a profile dict from customer_profile()
    ei_rate  : None = keeps job; 0.55 = job loss with EI at 55%
    bills_up : 0.15 = household bills up 15%
    one_off  : one-time cost in $ (e.g. p["S"] for "a month of spending")
    """
    income_pct = 100.0 if ei_rate is None else ei_rate * 100.0
    r = team_engine.apply_shock(p["B"], p["I"], p["S"], p["H"],
                                income_pct, bills_up * 100.0, one_off)
    months = 120.0 if r["kind"] == "surplus" else r["months"]
    return months, r["label"]


# ---------------------------------------------------------------
# 3. Per-customer numbers (judges' definitions)
# ---------------------------------------------------------------
def build_profiles(ms, loans):
    ms = ms.copy()
    ms["fixed"] = ms["household_bills"] + ms["insurance"] + ms["loan_payments"]

    g = ms.groupby("account_id")
    prof = pd.DataFrame({
        "I": g["money_in"].median(),        # typical monthly money in
        "F": g["fixed"].median(),           # typical fixed costs
        "S": g["money_out"].median(),       # typical monthly spending
        "H": g["household_bills"].median(), # household bills
        "months_of_data": g.size(),
        "total_days_below_zero": g["days_below_zero"].sum(),
    })

    # Buffer B: mean avg_daily_balance over the last 6 rows, sorted by month
    last6 = (ms.sort_values(["account_id", "month"])
               .groupby("account_id").tail(6))
    prof["B"] = last6.groupby("account_id")["avg_daily_balance"].mean()

    # Loan payment P: only if the loan is still running at end of 2025 (C or D)
    l = loans.set_index("account_id")
    prof["has_loan"] = prof.index.isin(l.index).astype(int)
    running = l["status"].isin(["C", "D"])
    prof["P"] = l.loc[running, "monthly_payment"].reindex(prof.index).fillna(0)
    prof["loan_status"] = l["status"].reindex(prof.index)
    prof["defaulted"] = l["defaulted"].reindex(prof.index)  # NaN = no loan

    return prof.reset_index()


def customer_profile(prof, account_id):
    """One customer's numbers as a dict (for the dashboard)."""
    row = prof.loc[prof["account_id"] == account_id]
    if row.empty:
        raise ValueError(f"account_id {account_id} not found")
    return row.iloc[0].to_dict()


# ---------------------------------------------------------------
# 4. Standard shocks for every customer
# ---------------------------------------------------------------
SCENARIOS = {
    "base":           dict(),
    "job_loss":       dict(ei_rate=0.55),
    "bills_up_15":    dict(bills_up=0.15),
    "repair_1month":  "repair",              # one-off = S
    "job_loss_bills": dict(ei_rate=0.55, bills_up=0.15),
}


def add_scenarios(prof):
    prof = prof.copy()
    for name, kw in SCENARIOS.items():
        vals = []
        for p in prof.to_dict("records"):
            if kw == "repair":
                r, _ = apply_shock(p, one_off=p["S"])
            else:
                r, _ = apply_shock(p, **kw)
            vals.append(r)
        prof[f"runway_{name}"] = vals
    # Does the customer last through 6 months of EI?
    prof["survives_6m_EI"] = (prof["runway_job_loss"] >= 6).astype(int)
    return prof


# ---------------------------------------------------------------
# 5. Add district / client / card info
# ---------------------------------------------------------------
def add_context(prof, accounts, districts, clients, disps, cards):
    t = prof.merge(accounts, on="account_id", how="left")
    t = t.merge(
        districts[["district_id", "district_name", "region", "average_salary",
                   "unemployment_rate_2023", "urban_ratio_pct"]],
        on="district_id", how="left")

    # Account owner (one per account)
    owners = disps[disps["type"].str.lower() == "owner"]
    o = owners.merge(clients[["client_id", "gender", "birth_date"]],
                     on="client_id", how="left")
    o["age_2025"] = (pd.Timestamp("2025-12-31")
                     - pd.to_datetime(o["birth_date"])).dt.days // 365
    t = t.merge(o[["account_id", "gender", "age_2025"]],
                on="account_id", how="left")

    # Best card type on the account (none / junior / classic / gold)
    c = cards.merge(disps[["disposition_id", "account_id"]],
                    on="disposition_id")
    rank = {"junior": 1, "classic": 2, "gold": 3}
    c["rank"] = c["card_type"].str.lower().map(rank)
    best = c.sort_values("rank").groupby("account_id").tail(1)
    t = t.merge(best[["account_id", "card_type"]], on="account_id", how="left")
    t["card_type"] = t["card_type"].fillna("none")
    return t


# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------
if __name__ == "__main__":
    ms, loans, accounts, districts, clients, disps, cards = load_data()
    prof = build_profiles(ms, loans)
    prof = add_scenarios(prof)
    table = add_context(prof, accounts, districts, clients, disps, cards)
    os.makedirs(OUT_DIR, exist_ok=True)
    table.to_csv(f"{OUT_DIR}/customer_table.csv", index=False)

    print(f"Saved {OUT_DIR}/customer_table.csv: {len(table)} accounts")
    print(table[["I", "S", "B", "runway_base", "runway_job_loss"]]
          .describe().round(1))
