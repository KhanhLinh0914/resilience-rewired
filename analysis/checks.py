"""
Robustness checks for the findings.

Run from the repo root, AFTER analysis/build_customer_table.py:
    python analysis/checks.py

Check 1: Is "higher income = more fragile" still true without pensioners?
Check 2: Does overdraft happen BEFORE the loan starts? (early warning or not)
Check 3: Using ONLY data from before the loan, does runway predict default?
"""

import os

import matplotlib.pyplot as plt
import pandas as pd
from build_customer_table import runway

CHARTS = "analysis/output/charts"
os.makedirs(CHARTS, exist_ok=True)

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)

t = pd.read_csv("analysis/output/customer_table.csv")
ms = pd.read_csv("data/monthly_summary.csv")
loans = pd.read_csv("data/loans.csv")
def parse_date(s):
    """Handles both 2025-04-02 (ISO) and 02/04/2025 (day/month/year)."""
    s = s.astype(str).str.strip()
    iso = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    dmy = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    return iso.fillna(dmy)


loans["loan_start"] = parse_date(loans["loan_start"])
if loans["loan_start"].isna().any():
    print("WARNING: some loan_start dates could not be read:",
          loans.loc[loans["loan_start"].isna(), "loan_start"].head().tolist())
loans["start_month"] = loans["loan_start"].dt.strftime("%Y-%m")


def title(s):
    print("\n" + "=" * 70 + f"\n{s}\n" + "=" * 70)


INCOME_LABELS = ["lowest", "low", "middle", "high", "highest"]


def by_income(df, survive_col="survives_6m_EI"):
    df = df.copy()
    df["income_grp"] = pd.qcut(df["I"].rank(method="first"), 5,
                               labels=INCOME_LABELS)
    df["buffer_months"] = df["B"] / df["S"].where(df["S"] > 0)
    return df.groupby("income_grp", observed=True).agg(
        n=("I", "size"),
        median_income=("I", "median"),
        buffer_months=("buffer_months", "median"),
        share_survive_6m=(survive_col, "mean")).round(2)


# ------------------------------------------------------------------
# Check 1: pensioners
# ------------------------------------------------------------------
title("CHECK 1: income vs resilience, with and without pensioners")

pen = ms.groupby("account_id").agg(
    pension_months=("pension_in", lambda s: (s > 0).sum()),
    pension_median=("pension_in", "median"))
t = t.merge(pen, on="account_id", how="left")
t["pensioner"] = (t["pension_months"] > 0).astype(int)

print(f"Pensioners: {t['pensioner'].sum()} of {len(t)} "
      f"({t['pensioner'].mean():.1%})")

tmp = t.copy()
tmp["income_grp"] = pd.qcut(tmp["I"].rank(method="first"), 5,
                            labels=INCOME_LABELS)
print("\nShare of pensioners in each income group:")
print(tmp.groupby("income_grp", observed=True)["pensioner"].mean().round(2))

print("\nA) Everyone (original result):")
print(by_income(t))

print("\nB) Without pensioners:")
no_pen = by_income(t[t["pensioner"] == 0])
print(no_pen)

# Chart: the headline finding (pensioners excluded)
labels = ["Lowest", "Low", "Middle", "High", "Highest"]
vals = no_pen["share_survive_6m"].values
colors = ["#9AA5B1"] * 5
colors[0] = colors[-1] = "#E86A1A"
fig, ax = plt.subplots(figsize=(8, 4.5))
bars = ax.bar(labels, vals, color=colors)
for b, v in zip(bars, vals):
    ax.annotate(f"{v:.0%}", (b.get_x() + b.get_width() / 2, v),
                ha="center", va="bottom", fontsize=12, fontweight="bold")
ax.set_ylim(0, 1.08)
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
ax.set_xlabel("Income group (20% of customers each)")
ax.set_ylabel("Outlast 6 months of EI")
ax.set_title("Higher earners are less likely to outlast a job loss",
             fontsize=13, fontweight="bold")
n = int(no_pen["n"].iloc[0])
fig.text(0.01, 0.01, f"Job loss with EI at 55% of income. Pensioners excluded; "
         f"n = {n} customers per group.", fontsize=8, color="#555")
for side in ["top", "right"]:
    ax.spines[side].set_visible(False)
plt.tight_layout(rect=(0, 0.04, 1, 1))
plt.savefig(f"{CHARTS}/5_survive_by_income_no_pensioners.png", dpi=200)
plt.close()
print(f"Chart saved: {CHARTS}/5_survive_by_income_no_pensioners.png")

# C) Fairer job-loss shock: pension income is NOT lost, only the rest
def jobloss_keep_pension(p):
    pension = min(p["pension_median"], p["I"])
    income = pension + 0.55 * (p["I"] - pension)
    r, _ = runway(p["B"], income, p["S"])
    return r

t["runway_job_loss_keep_pension"] = t.apply(jobloss_keep_pension, axis=1)
t["survives_6m_keep_pension"] = (t["runway_job_loss_keep_pension"] >= 6).astype(int)
print("\nC) Everyone, but job loss does not cut pension income:")
print(by_income(t, "survives_6m_keep_pension"))


# ------------------------------------------------------------------
# Check 2: overdraft before or after the loan starts?
# ------------------------------------------------------------------
title("CHECK 2: when does the overdraft happen?")

m = ms[["account_id", "month", "days_below_zero"]].merge(
    loans[["account_id", "start_month", "defaulted", "status"]],
    on="account_id")
m["period"] = (m["month"] >= m["start_month"]).map(
    {True: "after", False: "before"})

od = m.pivot_table(index="account_id", columns="period",
                   values="days_below_zero", aggfunc="sum", fill_value=0)
od = od.reindex(columns=["before", "after"], fill_value=0)
months_before = m[m["period"] == "before"].groupby("account_id").size()
od["months_before_loan"] = months_before.reindex(od.index).fillna(0)
od = od.join(loans.set_index("account_id")[["defaulted", "status"]])

def when(r):
    if r["before"] > 0:
        return "overdrawn BEFORE loan"
    if r["after"] > 0:
        return "overdrawn only AFTER loan"
    return "never overdrawn"

od["overdraft_timing"] = od.apply(when, axis=1)
print(od.groupby("overdraft_timing").agg(
    n=("defaulted", "size"), default_rate=("defaulted", "mean")).round(3))

print("\nLoan status vs timing:")
print(pd.crosstab(od["overdraft_timing"], od["status"]))

print(f"\nLoans with at least 6 months of history before they start: "
      f"{(od['months_before_loan'] >= 6).sum()} of {len(od)}")


# ------------------------------------------------------------------
# Check 3: runway using only pre-loan data
# ------------------------------------------------------------------
title("CHECK 3: runway from BEFORE the loan -> later default?")

pre = m[m["period"] == "before"][["account_id", "month"]].merge(
    ms, on=["account_id", "month"])
counts = pre.groupby("account_id").size()
pre = pre[pre["account_id"].isin(counts[counts >= 6].index)]

g = pre.groupby("account_id")
p = pd.DataFrame({"I": g["money_in"].median(), "S": g["money_out"].median()})
last6 = pre.sort_values(["account_id", "month"]).groupby("account_id").tail(6)
p["B"] = last6.groupby("account_id")["avg_daily_balance"].mean()
p["runway_pre"] = [runway(r.B, r.I, r.S)[0] for r in p.itertuples()]
p["runway_pre_jobloss"] = [runway(r.B, 0.55 * r.I, r.S)[0]
                           for r in p.itertuples()]
p = p.join(loans.set_index("account_id")["defaulted"])

print(f"Loans with 6+ months of pre-loan data: {len(p)}  "
      f"(default rate {p['defaulted'].mean():.1%})")

bins = [-0.01, 3, 6, 12, 119.9, 120]
labels = ["0-3", "3-6", "6-12", "12-120", "no shortfall"]
for col, name in [("runway_pre", "no shock"),
                  ("runway_pre_jobloss", "after job loss")]:
    p["grp"] = pd.cut(p[col], bins, labels=labels)
    print(f"\nPre-loan runway, {name}:")
    print(p.groupby("grp", observed=True)["defaulted"].agg(
        n="size", default_rate="mean").round(3))

print("\nGroups with n < 30 are too small to trust.")
