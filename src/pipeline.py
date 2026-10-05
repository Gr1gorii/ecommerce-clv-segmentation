import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from src.data import clean_data, cohort_retention, customer_summary, download_data, load_data, split_periods
from src.models import discount_schedule, fit_models, predict_basket, predict_purchases, revenue_schedule
from src.segments import add_segments, apply_cac_range
from src.translations import number, translate
from src.validation import run_backtests


ROOT = Path(__file__).resolve().parents[1]
CUTOFF = "2011-06-09"
END_DATE = "2011-12-09"


def save_localized_exports(customers, audit, output):
    columns = ["customer_id", "segment", "rfm", "expected_basket", "contribution_clv", "cac_reference", "cac_lower", "cac_upper", "action"]
    export = customers.reset_index()[columns].copy()
    export["segment"] = export["segment"].map(lambda value: translate(value, "it"))
    export["action"] = export["action"].map(lambda value: translate(value, "it"))
    export = export.rename(columns={column: translate(column, "it") for column in columns})
    export.to_csv(output / "customers_it.csv", index=False, encoding="utf-8-sig")
    audit = audit.copy()
    audit["step"] = audit["step"].map(lambda value: translate(value, "it"))
    audit = audit.rename(columns={"step": "passaggio", "removed": "eliminate", "remaining": "rimanenti"})
    audit.to_csv(output / "cleaning_it.csv", index=False, encoding="utf-8-sig")


def run_pipeline(raw_path=None, language="en", margin=0.35, annual_discount=0.10):
    if raw_path is None:
        raw_path = download_data(ROOT / "data/raw")
    raw_path = Path(raw_path)
    output = ROOT / "data/processed"
    output.mkdir(parents=True, exist_ok=True)
    purchases, audit = clean_data(load_data(raw_path))
    backtests, original = run_backtests(purchases, output)
    metrics, predictions, deciles, monthly_holdout = original
    days = metrics["window"]["days"]
    full_summary = customer_summary(purchases, END_DATE)
    final_bg, final_money = fit_models(full_summary)
    customers = full_summary.copy()
    customers["expected_basket"] = predict_basket(final_money, full_summary)
    customers["predicted_purchases_360d"] = predict_purchases(final_bg, full_summary, 360)
    customers["probability_alive"] = final_bg.conditional_probability_alive(
        full_summary["frequency"], full_summary["recency"], full_summary["T"]
    )
    schedule = revenue_schedule(final_bg, full_summary, customers["expected_basket"])
    customers["discounted_revenue"] = discount_schedule(schedule, annual_discount)
    customers, threshold = add_segments(customers)
    biases = [window["model"]["revenue"]["bias"] for window in backtests.values()]
    bias_low, bias_high = min(biases), max(biases)
    customers = apply_cac_range(customers, bias_low, bias_high, margin=margin)
    retention, sizes = cohort_retention(purchases, END_DATE)
    monthly = purchases.assign(month=purchases["date"].dt.to_period("M").astype(str)).groupby("month").agg(
        revenue=("revenue", "sum"),
        purchase_days=("revenue", "size"),
        active_customers=("customer_id", "nunique"),
    )
    metadata = {
        "source": "UCI Online Retail II, Daqing Chen, 2012",
        "url": "https://archive.ics.uci.edu/dataset/502/online+retail+ii",
        "license": "CC BY 4.0",
        "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "start_date": str(purchases["date"].min().date()),
        "end_date": END_DATE,
        "cutoff": CUTOFF,
        "holdout_days": days,
        "country": "United Kingdom",
        "currency": "GBP",
        "raw_rows": int(audit.iloc[0]["remaining"]),
        "clean_rows": int(audit.iloc[-1]["remaining"]),
        "purchase_days": len(purchases),
        "customers": len(customers),
        "calibration_customers": metrics["window"]["known_customers"],
        "new_holdout_customers": metrics["window"]["new_customers"],
        "new_holdout_revenue": metrics["window"]["new_revenue"],
        "observed_revenue": float(purchases["revenue"].sum()),
        "value_threshold": threshold,
        "forecast_months": 12,
        "days_per_month": 30,
        "assumptions": {"margin": margin, "returns": 0.05, "reserve": 0.50, "service_cost": 2.0, "annual_discount": annual_discount},
        "cac_bias_scenario": {"bias_low": bias_low, "bias_high": bias_high},
        "final_parameters": {"bg_nbd": final_bg.params_.to_dict(), "gamma_gamma": final_money.params_.to_dict()},
    }
    purchases.to_csv(output / "purchases.csv", index=False)
    audit.to_csv(output / "cleaning.csv", index=False)
    customers.to_csv(output / "customers.csv", index_label="customer_id")
    schedule.to_csv(output / "revenue_schedule.csv", index_label="customer_id")
    save_localized_exports(customers, audit, output)
    predictions.to_csv(output / "validation.csv", index_label="customer_id")
    retention.to_csv(output / "retention.csv", index_label="cohort")
    sizes.to_csv(output / "cohort_sizes.csv", header=["customers"], index_label="cohort")
    monthly.to_csv(output / "monthly.csv", index_label="month")
    deciles.to_csv(output / "deciles.csv")
    monthly_holdout.to_csv(output / "holdout_monthly.csv", index=False)
    for name, content in [("metrics", metrics), ("metadata", metadata), ("backtests_metrics", backtests)]:
        (output / f"{name}.json").write_text(json.dumps(content, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(translate("Customers: {customers}; revenue: {revenue}", language).format(
        customers=number(len(customers), language=language),
        revenue="£" + number(metadata["observed_revenue"], language=language),
    ))
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build CLV results / Calcola i risultati CLV")
    parser.add_argument("--raw", type=Path, help="Original XLSX path / Percorso del file XLSX originale")
    parser.add_argument("--language", choices=["en", "it"], default="en", help="Message language / Lingua dei messaggi")
    parser.add_argument("--margin", type=float, default=0.35, help="Contribution margin / Margine di contribuzione")
    parser.add_argument("--annual-discount", type=float, default=0.10, help="Annual discount rate / Tasso di sconto annuo")
    args = parser.parse_args()
    try:
        run_pipeline(args.raw, args.language, args.margin, args.annual_discount)
    except ValueError as error:
        raise SystemExit(translate(str(error), args.language)) from error
