"""
Find the "biggest finding".

Run from the repo root, AFTER analysis/build_customer_table.py:
    pip install matplotlib
    python analysis/findings.py

Prints tables in the Run window and saves charts to analysis/output/charts/.
Every table shows n (number of customers) - be careful with small groups.
"""

import os
import pandas as pd
import matplotlib.pyplot as plt

t = pd.read_csv("analysis/output/customer_table.csv")
CHARTS = "analysis/output/charts"
os.makedirs(CHARTS, exist_ok=True)
pd.set_option("display.width", 160)

N = len(t)
loans = t[t["has_loan"] == 1].copy()

RUNWAY_BINS = [-0.01, 1, 3, 6, 12, 119.9, 120]
RUNWAY_LABELS = ["0-1", "1-3", "3-6", "6-12", "12-120", "no shortfall"]


def title(s):
    print("\n" + "=" * 70 + f"\n{s}\n" + "=" * 70)


def bar(series, ylabel, fname, chart_title, pct=False):
    ax = series.plot(kind="bar", figsize=(8, 4.5), color="#E86A1A", rot=0)
    ax.set_ylabel(ylabel)
    ax.set_title(chart_title)
    for p in ax.patches:
        v = p.get_height()
        ax.annotate(f"{v:.0%}" if pct else f"{v:.1f}",
                    (p.get_x() + p.get_width() / 2, v),
                    ha="center", va="bottom", fontsize=9)
    plt.tight_layout()
    plt.savefig(f"{CHARTS}/{fname}", dpi=150)
    plt.close()


# ------------------------------------------------------------------
# 1. Does runway predict loan default?
# ------------------------------------------------------------------
title("1. Default rate by runway (customers with a loan)")
print(f"Loan customers: {len(loans)}, overall default rate: "
      f"{loans['defaulted'].mean():.1%}")

for col, name in [("runway_base", "no shock"),
                  ("runway_job_loss", "after job loss")]:
    loans["grp"] = pd.cut(loans[col], RUNWAY_BINS, labels=RUNWAY_LABELS)
    tab = loans.groupby("grp", observed=True)["defaulted"].agg(
        n="size", default_rate="mean")
    print(f"\nRunway {name} (months):")
    print(tab.round(3))
    if col == "runway_base":
        bar(tab["default_rate"], "Default rate", "1_default_by_runway.png",
            "Loan default rate by runway (no shock)", pct=True)

# Overdraft days as an early warning sign
loans["overdraft"] = pd.cut(loans["total_days_below_zero"],
                            [-1, 0, 10, 50, 1e9],
                            labels=["never", "1-10 days", "11-50 days", "50+ days"])
tab = loans.groupby("overdraft", observed=True)["defaulted"].agg(
    n="size", default_rate="mean")
print("\nDefault rate by total days below zero:")
print(tab.round(3))
bar(tab["default_rate"], "Default rate", "1b_default_by_overdraft.png",
    "Loan default rate by days with a negative balance", pct=True)

# ------------------------------------------------------------------
# 2. How many survive 6 months of EI?
# ------------------------------------------------------------------
title("2. Job loss with EI at 55%")
share = t["survives_6m_EI"].mean()
print(f"Last 6+ months: {share:.1%}   |   Run out before EI ends: {1-share:.1%}")
print(f"Median runway after job loss: {t['runway_job_loss'].median():.1f} months")
print(f"Already short with NO shock (runway < 120): "
      f"{(t['runway_base'] < 120).mean():.1%}")

dist = pd.cut(t["runway_job_loss"], RUNWAY_BINS, labels=RUNWAY_LABELS) \
         .value_counts(normalize=True).sort_index()
print("\nRunway after job loss (share of customers):")
print(dist.round(3))
bar(dist, "Share of customers", "2_runway_after_job_loss.png",
    "How long customers last after a job loss (EI 55%)", pct=True)

# ------------------------------------------------------------------
# 3. Are high-income customers more resilient?
# ------------------------------------------------------------------
title("3. Income vs resilience (income in 5 equal groups)")
t["income_grp"] = pd.qcut(t["I"].rank(method="first"), 5,
                          labels=["lowest", "low", "middle", "high", "highest"])
tab = t.groupby("income_grp", observed=True).agg(
    n=("I", "size"),
    median_income=("I", "median"),
    median_buffer=("B", "median"),
    median_runway_job_loss=("runway_job_loss", "median"),
    share_survive_6m=("survives_6m_EI", "mean"))
print(tab.round(2))
bar(tab["share_survive_6m"], "Share lasting 6+ months",
    "3_survive_by_income.png",
    "Share who outlast 6 months of EI, by income group", pct=True)

# Buffer in "months of spending" (a fairer comparison across incomes)
t["buffer_months"] = t["B"] / t["S"].where(t["S"] > 0)
print("\nMedian buffer in months of spending, by income group:")
print(t.groupby("income_grp", observed=True)["buffer_months"].median().round(2))

# ------------------------------------------------------------------
# 4. Which shock hurts most?
# ------------------------------------------------------------------
title("4. Which shock hurts most?")
shocks = {"bills +15%": "runway_bills_up_15",
          "repair (1 month)": "runway_repair_1month",
          "job loss": "runway_job_loss",
          "job loss + bills": "runway_job_loss_bills"}
rows = []
for name, col in shocks.items():
    rows.append({"shock": name,
                 "median_runway": t[col].median(),
                 "share_under_6m": (t[col] < 6).mean(),
                 "share_at_0": (t[col] == 0).mean()})
tab = pd.DataFrame(rows).set_index("shock")
print(tab.round(3))
bar(tab["share_under_6m"], "Share with runway < 6 months",
    "4_shock_comparison.png", "Share of customers under 6 months, by shock",
    pct=True)

print(f"\nNote: {(t['H'] == 0).mean():.1%} of customers have household bills = 0,")
print("so a bills shock does not change their runway at all.")

# ------------------------------------------------------------------
# 5. Region and local unemployment
# ------------------------------------------------------------------
title("5. Region")
tab = t.groupby("region").agg(
    n=("I", "size"),
    unemployment=("unemployment_rate_2023", "mean"),
    median_runway_job_loss=("runway_job_loss", "median"),
    share_survive_6m=("survives_6m_EI", "mean")).sort_values("share_survive_6m")
print(tab.round(2))

d = t.groupby("district_id").agg(
    unemployment=("unemployment_rate_2023", "first"),
    survive=("survives_6m_EI", "mean"))
print(f"\nCorrelation, district unemployment vs share surviving: "
      f"{d['unemployment'].corr(d['survive']):.2f}  (near 0 = no relationship)")

# ------------------------------------------------------------------
# 6. Age, card type, gender
# ------------------------------------------------------------------
title("6. Age, card type, gender")
t["age_grp"] = pd.cut(t["age_2025"], [0, 30, 45, 60, 120],
                      labels=["<30", "30-44", "45-59", "60+"])
for col in ["age_grp", "card_type", "gender"]:
    tab = t.groupby(col, observed=True).agg(
        n=("I", "size"),
        median_runway_job_loss=("runway_job_loss", "median"),
        share_survive_6m=("survives_6m_EI", "mean"))
    print(f"\nBy {col}:")
    print(tab.round(2))

print("\nCharts saved in analysis/output/charts/")
