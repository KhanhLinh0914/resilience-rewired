from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DOWNLOADS = Path(r"C:\Users\phamt\Downloads")


def pick(name: str) -> Path:
    local = DATA / name
    if local.exists():
        return local
    return DOWNLOADS / name


ACCOUNTS = pick("accounts.csv")
CLIENTS = pick("clients.csv")
CARDS = pick("cards.csv")
DISPOSITIONS = pick("dispositions.csv")
DISTRICTS = pick("districts.csv")
LOANS = pick("loans.csv")
STANDING_ORDERS = pick("standing_orders.csv")
MONTHLY = pick("monthly_summary.csv")

METRICS = DATA / "account_metrics.csv"
SUMMARY = DATA / "summary.json"
