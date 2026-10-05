from pathlib import Path
from urllib.request import urlretrieve
from zipfile import ZipFile

import pandas as pd


DATA_URL = "https://archive.ics.uci.edu/static/public/502/online%2Bretail%2Bii.zip"


def download_data(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "online_retail_II.xlsx"
    if not path.exists():
        archive = folder / "online_retail_ii.zip"
        urlretrieve(DATA_URL, archive)
        with ZipFile(archive) as files:
            with files.open("online_retail_II.xlsx") as source:
                path.write_bytes(source.read())
        archive.unlink()
    return path


def load_data(path):
    sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
    return pd.concat(sheets.values(), ignore_index=True)


def clean_data(raw):
    data = raw.copy()
    audit = [{"step": "Raw rows", "removed": 0, "remaining": len(data)}]
    filters = [
        ("Exact duplicates", lambda x: ~x.duplicated()),
        ("Missing Customer ID", lambda x: x["Customer ID"].notna()),
        ("Outside UK", lambda x: x["Country"].eq("United Kingdom")),
        ("Cancellations and returns", lambda x: ~x["Invoice"].astype(str).str.upper().str.startswith("C") & x["Quantity"].gt(0)),
        ("Zero or negative price", lambda x: x["Price"].gt(0)),
        ("Non-merchandise lines", lambda x: x["StockCode"].astype(str).str.fullmatch(r"\d{5}[A-Za-z]*", na=False)),
    ]
    for name, condition in filters:
        before = len(data)
        data = data.loc[condition(data)].copy()
        audit.append({"step": name, "removed": before - len(data), "remaining": len(data)})
    data["customer_id"] = data["Customer ID"].astype(int).astype(str)
    data["date"] = pd.to_datetime(data["InvoiceDate"]).dt.normalize()
    data["revenue"] = data["Quantity"] * data["Price"]
    purchases = data.groupby(["customer_id", "date"], as_index=False)["revenue"].sum()
    purchases = purchases.sort_values(["customer_id", "date"]).reset_index(drop=True)
    return purchases, pd.DataFrame(audit)


def customer_summary(purchases, end_date):
    end_date = pd.Timestamp(end_date)
    data = purchases.loc[purchases["date"] <= end_date].copy()
    grouped = data.groupby("customer_id")
    summary = grouped.agg(
        first_purchase=("date", "min"),
        last_purchase=("date", "max"),
        purchases=("date", "size"),
        revenue=("revenue", "sum"),
        average_basket=("revenue", "mean"),
    )
    summary["frequency"] = summary["purchases"] - 1
    summary["recency"] = (summary["last_purchase"] - summary["first_purchase"]).dt.days
    summary["T"] = (end_date - summary["first_purchase"]).dt.days
    summary["days_since_purchase"] = (end_date - summary["last_purchase"]).dt.days
    first_dates = data.groupby("customer_id")["date"].transform("min")
    repeat_baskets = data.loc[data["date"] > first_dates]
    summary["monetary_value"] = repeat_baskets.groupby("customer_id")["revenue"].mean()
    summary["monetary_value"] = summary["monetary_value"].fillna(0)
    return summary


def split_periods(purchases, cutoff, end_date):
    cutoff = pd.Timestamp(cutoff)
    end_date = pd.Timestamp(end_date)
    if cutoff >= end_date:
        raise ValueError("Training must end before the holdout ends")
    calibration = purchases.loc[purchases["date"] <= cutoff].copy()
    holdout = purchases.loc[(purchases["date"] > cutoff) & (purchases["date"] <= end_date)].copy()
    return calibration, holdout


def cohort_retention(purchases, end_date):
    end_date = pd.Timestamp(end_date)
    last_month = end_date.to_period("M")
    if end_date != last_month.end_time.normalize():
        last_month -= 1
    data = purchases.loc[purchases["date"].dt.to_period("M") <= last_month].copy()
    data["month"] = data["date"].dt.to_period("M")
    data["cohort"] = data.groupby("customer_id")["month"].transform("min")
    data["age"] = (data["month"].astype("int64") - data["cohort"].astype("int64"))
    counts = data.groupby(["cohort", "age"])["customer_id"].nunique().unstack()
    max_age = last_month.ordinal - counts.index.min().ordinal
    counts = counts.reindex(columns=range(max_age + 1))
    for cohort in counts.index:
        observed_age = last_month.ordinal - cohort.ordinal
        counts.loc[cohort, counts.columns <= observed_age] = counts.loc[cohort, counts.columns <= observed_age].fillna(0)
    sizes = counts[0].astype(int)
    retention = counts.div(sizes, axis=0)
    retention.index = retention.index.astype(str)
    sizes.index = sizes.index.astype(str)
    return retention, sizes
