"""One-screen resilience engine for the Tangerine track.

Open an account, apply a shock, and read the official runway plus a plan.
"""

import json
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_metrics import main as build_main
from engine import EI_MONTHS, apply_shock
from paths import METRICS, MONTHLY, SUMMARY

st.set_page_config(page_title="Resilience Rewired", layout="wide")
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Source+Sans+3:wght@400;600;700&display=swap');
    html, body, .stApp, [class*="css"], button, button p, input, textarea, label, p, li, h1, h2, h3,
    div[data-testid="stMetricValue"], div[data-testid="stCaptionContainer"] {
        font-family: "Source Sans 3", "Segoe UI", sans-serif !important;
    }
    .stApp {background: #070B0C;}
    .block-container {padding-top: 1.2rem; max-width: 1240px;}
    button[data-testid="stBaseButton-primary"], button[data-testid="stBaseButton-primary"] p {
        font-weight: 700 !important;
        background: #143528 !important;
        color: #F4FFF8 !important;
        border: 1px solid #3DDC97 !important;
    }
    button[data-testid="stBaseButton-secondary"], button[data-testid="stBaseButton-secondary"] p {
        font-weight: 400 !important;
        color: #C5D0C8 !important;
    }
    h1 {letter-spacing: -0.03em; font-weight: 600; color: #F4FFF8;}
    h3 {color: #D7E7DC; font-size: 1rem; letter-spacing: 0.04em; text-transform: uppercase;}
    div[data-testid="stMetric"] {
        background: #101816;
        border: 1px solid #1C3A2E;
        border-radius: 10px;
        padding: 0.65rem 0.8rem 0.5rem;
    }
    div[data-testid="stMetricLabel"] {
        color: #8B9BB4;
        font-size: 0.72rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }
    div[data-testid="stMetricLabel"] p {font-size: 0.72rem;}
    div[data-testid="stMetricValue"] {
        color: #3DDC97;
        font-size: 1.35rem;
        font-variant-numeric: tabular-nums;
    }
    div[data-testid="stCode"], div[data-testid="stCode"] *, pre, code, kbd, samp {
        font-family: "IBM Plex Mono", ui-monospace, monospace !important;
    }
    div[data-testid="stCode"], pre {
        background: #070B0C !important;
        border: 1px solid #1C3A2E;
        border-radius: 10px;
    }
    .finding {
        background: #101816;
        border: 1px solid #1C3A2E;
        border-left: 3px solid #3DDC97;
        color: #E8F0EA;
        border-radius: 10px;
        padding: 0.85rem 1rem;
        line-height: 1.45;
        margin: 0.2rem 0 0.6rem;
    }
    .panel {
        background: #101816;
        border: 1px solid #1C3A2E;
        border-radius: 12px;
        padding: 0.7rem 0.85rem 0.4rem;
        margin-bottom: 0.7rem;
    }
    .panel-label {
        color: #8B9BB4;
        font-size: 0.72rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 0.15rem;
    }
    .gauge-num {
        color: #3DDC97;
        font-family: "Source Sans 3", "Segoe UI", sans-serif;
        font-size: 2rem;
        font-weight: 600;
        line-height: 1;
        text-align: center;
        margin-top: 0.2rem;
    }
    .gauge-num span {color: #8B9BB4; font-size: 0.95rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def ensure_metrics() -> None:
    if METRICS.exists() and SUMMARY.exists():
        return
    build_main()


def money(value: float) -> str:
    if pd.isna(value):
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _time_axis():
    return alt.Axis(format="%b %Y", labelColor="#8B9BB4", grid=False, domain=False, tickCount=5, title=None)


def _money_axis():
    return alt.Axis(format="$,.0f", labelColor="#8B9BB4", gridColor="#163028", domain=False, title=None)


def balance_chart(history: pd.DataFrame) -> alt.Chart:
    frame = history.copy()
    frame["month_dt"] = pd.to_datetime(frame["month"] + "-01")
    base = alt.Chart(frame).encode(x=alt.X("month_dt:T", axis=_time_axis()))
    y = alt.Y("avg_daily_balance:Q", axis=_money_axis())
    area = base.mark_area(color="#1BD67A", opacity=0.22, interpolate="monotone").encode(y=y)
    line = base.mark_line(color="#3DDC97", strokeWidth=2.4, interpolate="monotone").encode(y=y)
    return (area + line).properties(height=250, background="transparent").configure_view(strokeWidth=0).configure(background="transparent")


def flow_chart(history: pd.DataFrame) -> alt.Chart:
    frame = history.copy()
    frame["month_dt"] = pd.to_datetime(frame["month"] + "-01")
    long = frame.melt(id_vars="month_dt", value_vars=["money_in", "money_out"], var_name="flow", value_name="amount")
    long["flow"] = long["flow"].map({"money_in": "Money in", "money_out": "Money out"})
    return (
        alt.Chart(long)
        .mark_line(strokeWidth=2, interpolate="monotone")
        .encode(
            x=alt.X("month_dt:T", axis=_time_axis()),
            y=alt.Y("amount:Q", axis=_money_axis()),
            color=alt.Color(
                "flow:N",
                scale=alt.Scale(domain=["Money in", "Money out"], range=["#3DDC97", "#8B9BB4"]),
                legend=alt.Legend(title=None, orient="top", labelColor="#D7E7DC"),
            ),
        )
        .properties(height=210, background="transparent")
        .configure_view(strokeWidth=0)
        .configure(background="transparent")
        .configure_legend(symbolStrokeWidth=3)
    )


def spend_donut(row: pd.Series) -> alt.Chart | None:
    bills = max(float(row.bills_h), 0)
    insurance = max(float(row.insurance), 0)
    loans = max(float(row.loan_payments_median), 0)
    other = max(float(row.spending_s) - bills - insurance - loans, 0)
    parts = pd.DataFrame(
        {"part": ["Bills", "Insurance", "Loan payments", "Other"], "amount": [bills, insurance, loans, other]}
    )
    parts = parts[parts["amount"] > 1]
    if parts.empty:
        return None
    return (
        alt.Chart(parts)
        .mark_arc(innerRadius=58, outerRadius=88, cornerRadius=3)
        .encode(
            theta=alt.Theta("amount:Q", stack=True),
            color=alt.Color(
                "part:N",
                scale=alt.Scale(range=["#3DDC97", "#1F6F5B", "#8B9BB4", "#16382C"]),
                legend=alt.Legend(title=None, orient="bottom", labelColor="#D7E7DC", columns=2),
            ),
            tooltip=["part", alt.Tooltip("amount:Q", format="$,.0f")],
        )
        .properties(height=220, background="transparent")
        .configure_view(strokeWidth=0)
        .configure(background="transparent")
    )


def rank_gauge(percentile: int) -> alt.Chart:
    filled = min(max(percentile, 0), 100)
    slices = pd.DataFrame({"slice": ["Rank", "Rest"], "value": [max(filled, 0.01), max(100 - filled, 0.01)]})
    return (
        alt.Chart(slices)
        .mark_arc(innerRadius=58, outerRadius=78, cornerRadius=4)
        .encode(
            theta=alt.Theta("value:Q", stack=True),
            color=alt.Color(
                "slice:N",
                scale=alt.Scale(domain=["Rank", "Rest"], range=["#3DDC97", "#163028"]),
                legend=None,
            ),
        )
        .properties(height=180, background="transparent")
        .configure_view(strokeWidth=0)
        .configure(background="transparent")
    )


def set_mode(name: str) -> None:
    st.session_state.mode = name


def set_account(account_id: int) -> None:
    st.session_state.account_raw = str(account_id)


@st.cache_data
def load_metrics(_mtime: float) -> pd.DataFrame:
    frame = pd.read_csv(METRICS)
    return frame.set_index("account_id", drop=False)


@st.cache_data
def load_monthly(_mtime: float) -> pd.DataFrame:
    frame = pd.read_csv(
        MONTHLY,
        usecols=[
            "account_id",
            "month",
            "money_in",
            "money_out",
            "household_bills",
            "insurance",
            "loan_payments",
            "avg_daily_balance",
        ],
    )
    return frame.sort_values(["account_id", "month"])


@st.cache_data
def load_summary(_mtime: float) -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def formula_text(result: dict) -> str:
    left = result["buffer_left"]
    gap = result["gap"]
    lines = [
        f"buffer left = {money(result['buffer_left'] + result['one_off'])} - {money(result['one_off'])} = {money(left)}",
        f"gap = {money(result['spending'])} - {money(result['income'])} = {money(gap)}",
    ]
    if result["kind"] == "zero":
        lines.append("Buffer left is 0 or below, so runway = 0.0 months.")
    elif result["kind"] == "surplus":
        lines.append("Gap is 0 or below. Income covers spending. Runway = no shortfall (120+).")
    else:
        lines.append(
            f"runway = min({money(left)} / {money(gap)}, 120) = {result['label']} months."
        )
        raw = result.get("raw_months")
        if raw is not None and raw > 120:
            lines.append(f"Uncapped, that division is {raw:.1f} months. The brief caps the shown number at 120.")
    return "\n".join(lines)


def goal_plan(row: pd.Series) -> str:
    target = 3 * float(row.fixed_f)
    shortfall = target - float(row.buffer_b)
    if float(row.fixed_f) <= 0:
        return "Typical fixed costs are $0, so a 3-month bill fund is $0."
    if shortfall <= 0:
        return (
            f"Buffer already covers a 3-month fixed-cost fund of {money(target)}. "
            f"Fixed costs are {money(row.fixed_f)} a month."
        )
    surplus = float(row.income_i) - float(row.spending_s)
    if surplus > 0:
        months = shortfall / surplus
        if months > 120:
            timing = "Saving the monthly surplus would take more than 10 years."
        else:
            timing = f"Saving the {money(surplus)} monthly surplus gets there in about {months:.1f} months."
        return (
            f"A 3-month fixed-cost fund is {money(target)}. "
            f"The buffer is short {money(shortfall)}. {timing}"
        )
    return (
        f"A 3-month fixed-cost fund is {money(target)}. "
        f"The buffer is short {money(shortfall)}. "
        "Typical spending is at or above money in, so the fund does not grow unless spending drops."
    )


def backup_plan(row: pd.Series, result: dict, income_pct: float, bill_pct: float) -> str:
    shocked = not (income_pct == 100 and bill_pct == 0 and result["one_off"] == 0)
    if not shocked:
        return "No shock is applied. The backup plan appears when income, bills, or a one-off cost changes."

    bills_after = float(row.bills_h) * (1 + bill_pct / 100.0)
    essential = bills_after + float(row.insurance) + float(row.loan_payment_p)
    flexible = result["spending"] - essential
    job_loss = income_pct < 100

    if result["kind"] == "zero" and result["one_off"] > 0:
        return (
            f"The one-off cost of {money(result['one_off'])} is at least as large as the buffer, so runway is 0. "
            "A monthly spending cut does not change that official result, because the buffer is already gone."
        )

    if result["kind"] == "surplus" and job_loss:
        return (
            f"They make it. At {income_pct:.0f}% of typical income, money in still covers spending. "
            f"EI in this track lasts {EI_MONTHS} months, and the buffer is not being drained."
        )
    if result["kind"] == "surplus":
        return (
            f"Income still covers spending. Buffer left after the one-off cost is {money(result['buffer_left'])}."
        )

    if result["kind"] == "zero":
        return "The buffer is already empty, so runway is 0 before this shock does any further damage."

    runway = result["label"]
    gap = result["gap"]
    if job_loss and result["months"] >= EI_MONTHS:
        return (
            f"They make it. Runway is {runway} months, and EI in this track lasts {EI_MONTHS}. "
            f"The monthly gap is {money(gap)}."
        )

    if job_loss:
        affordable = result["buffer_left"] / EI_MONTHS
        cut = gap - affordable
        text = (
            f"They do not make it. Runway is {runway} months and EI lasts {EI_MONTHS}. "
            f"The monthly gap is {money(gap)}. "
            f"To last {EI_MONTHS} months they need to cut about {money(cut)} a month."
        )
        if flexible > 0:
            if cut <= flexible:
                text += f" About {money(flexible)} of spending sits outside bills, insurance, and the loan payment, so that cut can come from there."
            else:
                text += (
                    f" Only about {money(flexible)} sits outside bills, insurance, and the loan payment. "
                    "Cutting that flexible spending is not enough."
                )
        return text

    return (
        f"After the shock they are short {money(gap)} a month. "
        f"The remaining buffer lasts {runway} months."
    )


def customer_line(row: pd.Series) -> str:
    bits = []
    if pd.notna(row.gender) and pd.notna(row.owner_age):
        bits.append(f"Owner {row.gender}, age {int(row.owner_age)} at the end of 2025")
    elif pd.notna(row.gender):
        bits.append(f"Owner {row.gender}")
    if isinstance(row.district_name, str) and row.district_name:
        place = row.district_name
        if isinstance(row.region, str) and row.region:
            place = f"{place}, {row.region}"
        bits.append(f"branch district {place}")
    if isinstance(row.cards, str) and row.cards:
        bits.append(f"cards: {row.cards}")
    if row.loan_status in ("C", "D"):
        bits.append(f"loan {row.loan_status_meaning}, {money(row.loan_payment_p)} a month")
    elif row.loan_status in ("A", "B"):
        bits.append(f"loan {row.loan_status_meaning}")
    return " · ".join(bits)


ensure_metrics()
metrics = load_metrics(METRICS.stat().st_mtime)
monthly = load_monthly(MONTHLY.stat().st_mtime)
summary = load_summary(SUMMARY.stat().st_mtime)

if "mode" not in st.session_state:
    st.session_state.mode = "none"
if "account_raw" not in st.session_state:
    starter = summary.get("samples", {}).get("teaching")
    st.session_state.account_raw = "" if starter is None else str(starter)
if "income_pct" not in st.session_state:
    st.session_state.income_pct = 100
if "bill_pct" not in st.session_state:
    st.session_state.bill_pct = 0
if "one_off_dollars" not in st.session_state:
    st.session_state.one_off_dollars = 0.0

st.title("Resilience Rewired")
st.caption("Type an account, apply a shock, and read how many months the buffer lasts.")
st.markdown(f'<div class="finding">{summary["sentence"]}</div>', unsafe_allow_html=True)
st.caption(summary["detail"])

samples = summary.get("samples", {})
sample_labels = [
    ("teaching", "Practice account"),
    ("loan", "Has a running loan"),
    ("pension", "Pension is a large share"),
    ("safe", "Still covered if laid off"),
]
picked = str(st.session_state.get("account_raw", "")).strip()
sample_cols = st.columns(4)
for column, (key, label) in zip(sample_cols, sample_labels):
    sample_id = samples.get(key)
    if sample_id is None:
        column.button(label, disabled=True)
    else:
        chosen = picked == str(int(sample_id))
        column.button(
            label,
            on_click=set_account,
            args=(int(sample_id),),
            type="primary" if chosen else "secondary",
        )

raw = st.text_input("Account ID", key="account_raw")
try:
    account_id = int(str(raw).strip())
except ValueError:
    st.error("Enter a numeric account ID.")
    st.stop()

if account_id not in metrics.index:
    st.error(f"Account {account_id} is not in the metrics table.")
    st.stop()

row = metrics.loc[account_id]
if isinstance(row, pd.DataFrame):
    row = row.iloc[0]
if pd.isna(row.income_i) or pd.isna(row.buffer_b):
    st.error("This account has no monthly history, so runway cannot be calculated.")
    st.stop()

preset_values = {
    "none": (100, 0, 0.0),
    "ei": (55, 0, 0.0),
    "both": (55, 15, 0.0),
    "furnace": (100, 0, float(row.spending_s)),
}
if st.session_state.mode in preset_values:
    income_value, bill_value, one_off_value = preset_values[st.session_state.mode]
    st.session_state.income_pct = income_value
    st.session_state.bill_pct = bill_value
    st.session_state.one_off_dollars = one_off_value

st.subheader("Customer")
line = customer_line(row)
if line:
    st.write(line)

baseline = apply_shock(row.buffer_b, row.income_i, row.spending_s, row.bills_h, 100, 0, 0)
top = st.columns(4)
top[0].metric("Money in / month", money(row.income_i))
top[1].metric("Spending / month", money(row.spending_s))
top[2].metric("Fixed costs / month", money(row.fixed_f))
top[3].metric("Buffer", money(row.buffer_b))

second = st.columns(4)
second[0].metric("Household bills / month", money(row.bills_h))
second[1].metric("Insurance / month", money(row.insurance))
second[2].metric("Loan payment now", money(row.loan_payment_p))
second[3].metric("Runway today", baseline["label"])

percentile = int(round(float(row.buffer_percentile) * 100))
notes = [
    f"Buffer is the average daily balance of the last {int(row.buffer_months)} months. It ranks at the {percentile}th percentile.",
    f"History runs {row.first_month} to {row.last_month} ({int(row.n_months)} months). Medians use every month.",
    "Fixed costs are the median of household bills + insurance + loan payments. Runway does not use that total. It uses the buffer, money in, and money out.",
]
if float(row.days_below_zero_last6) > 0:
    notes.append(f"The balance finished below zero on {int(row.days_below_zero_last6)} days in the last {int(row.buffer_months)} months.")
if float(row.income_i) > 0 and float(row.pension_median) >= 0.3 * float(row.income_i):
    share = 100 * float(row.pension_median) / float(row.income_i)
    notes.append(
        f"Pension is about {share:.0f}% of typical money in. A job-loss shock fits a paycheque, not a pension, so say that out loud if you use EI here."
    )
if pd.notna(row.district_unemployment_2023):
    notes.append(
        f"Branch district unemployment in 2023 was {float(row.district_unemployment_2023):.2f}%, "
        f"and the average monthly salary there was {money(row.district_average_salary)}."
    )
if float(row.standing_orders) > 0:
    notes.append(f"Standing orders on file add up to {money(row.standing_orders)} a month. They are context, not part of the runway formula.")
for note in notes:
    st.caption(note)

history = monthly[monthly["account_id"] == account_id].copy()
if not history.empty:
    st.subheader("Charts")
    chart_left, chart_right = st.columns([1.7, 1])
    with chart_left:
        st.markdown('<div class="panel-label">Average daily balance</div>', unsafe_allow_html=True)
        st.altair_chart(balance_chart(history), use_container_width=True, theme=None)
        st.markdown('<div class="panel-label">Money in and money out</div>', unsafe_allow_html=True)
        st.altair_chart(flow_chart(history), use_container_width=True, theme=None)
    with chart_right:
        st.markdown('<div class="panel-label">Buffer rank</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="gauge-num">{percentile}<span>%</span></div>', unsafe_allow_html=True)
        st.altair_chart(rank_gauge(percentile), use_container_width=True, theme=None)
        st.caption("Share of accounts with a lower buffer.")
        donut = spend_donut(row)
        if donut is not None:
            st.markdown('<div class="panel-label">Typical month of spending</div>', unsafe_allow_html=True)
            st.altair_chart(donut, use_container_width=True, theme=None)
            st.caption("Bills, insurance, and loan payments are medians. Other is the rest of typical spending.")
    last6 = history.tail(int(row.buffer_months))[
        ["month", "avg_daily_balance", "money_in", "money_out", "household_bills"]
    ]
    with st.expander("Months used for the buffer"):
        st.dataframe(last6, hide_index=True, width="stretch")
        st.caption("Buffer is the average of avg daily balance in this table.")

st.subheader("Shock")
shock_options = [
    ("none", "No shock"),
    ("ei", "Laid off, EI 55%"),
    ("furnace", "Furnace repair"),
    ("both", "Laid off and bills +15%"),
]
buttons = st.columns(4)
for column, (mode_name, label) in zip(buttons, shock_options):
    column.button(
        label,
        on_click=set_mode,
        args=(mode_name,),
        type="primary" if st.session_state.mode == mode_name else "secondary",
    )

controls = st.columns(3)
controls[0].slider("Income replacement (% of typical money in)", 0, 100, step=5, key="income_pct", on_change=set_mode, args=("custom",))
controls[1].slider("Household bill change (%)", -20, 50, step=5, key="bill_pct", on_change=set_mode, args=("custom",))
controls[2].number_input("One-off cost ($)", min_value=0.0, step=100.0, key="one_off_dollars", on_change=set_mode, args=("custom",))

income_pct = float(st.session_state.income_pct)
bill_pct = float(st.session_state.bill_pct)
one_off = float(st.session_state.one_off_dollars)
result = apply_shock(row.buffer_b, row.income_i, row.spending_s, row.bills_h, income_pct, bill_pct, one_off)

if income_pct == 100 and bill_pct == 0 and one_off == 0:
    description = "No shock. Money in and spending stay at their typical levels."
elif st.session_state.mode == "ei":
    description = "Laid off. EI pays 55% of typical money in. This track treats EI as lasting 6 months."
elif st.session_state.mode == "furnace":
    description = "The furnace dies. The repair costs one month of typical spending and comes out of the buffer once."
elif st.session_state.mode == "both":
    description = "Laid off, EI at 55%, and household bills up 15% in the same month. EI lasts 6 months."
else:
    description = "Custom shock, using the sliders above."
st.write(description)

st.subheader("After the shock")
after = st.columns(5)
after[0].metric("Money in", money(result["income"]))
after[1].metric("Spending", money(result["spending"]))
after[2].metric("One-off cost", money(result["one_off"]))
after[3].metric("Buffer left", money(result["buffer_left"]))
after[4].metric("Runway (months)", result["label"])

st.code(formula_text(result), language="text")

job_loss = income_pct < 100
if job_loss and result["kind"] == "surplus":
    st.success(f"They make it. Money in still covers spending for the {EI_MONTHS} months of EI.")
elif job_loss and result["kind"] == "months" and result["months"] >= EI_MONTHS:
    st.success(f"They make it. Runway is {result['label']} months, longer than the {EI_MONTHS} months of EI.")
elif job_loss:
    st.error(f"They do not make it. Runway is {result['label']} months and EI lasts {EI_MONTHS}.")
elif result["kind"] == "zero":
    st.error("Runway is 0. The buffer does not survive this shock.")
elif result["kind"] == "surplus":
    st.success("No monthly shortfall. The buffer is not being drained.")
else:
    st.warning(f"The remaining buffer covers {result['label']} months of the new monthly gap.")

st.subheader("Plan")
plan_cols = st.columns(2)
plan_cols[0].markdown("**Goal, from today's numbers**")
plan_cols[0].write(goal_plan(row))
plan_cols[1].markdown("**Backup if this shock hits**")
plan_cols[1].write(backup_plan(row, result, income_pct, bill_pct))

st.caption("Canadian dollars. Definitions match the Tangerine track brief. Data: PKDD'99 Discovery Challenge Financial dataset.")
