import numpy as np
import pandas as pd

from src.data import customer_summary, split_periods
from src.models import baseline_predictions, error_metrics, fit_models, predict_basket, predict_purchases, recent_predictions


WINDOWS = [
    {"id": "original", "label": "Jun-Dec 2011", "cutoff": "2011-06-09", "end": "2011-12-09"},
    {"id": "seasonal_2010", "label": "Sep-Dec 2010", "cutoff": "2010-08-31", "end": "2010-12-31"},
    {"id": "non_peak_2011", "label": "Mar-May 2011", "cutoff": "2011-02-28", "end": "2011-05-31"},
]


def monthly_mae(mae, days):
    if not np.isfinite([mae, days]).all() or mae < 0 or days <= 0:
        raise ValueError("MAE must be non-negative and window days must be positive")
    return float(mae * 30 / days)


def ranking_metrics(actual, predicted):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if len(actual) != len(predicted) or not len(actual):
        raise ValueError("Ranking needs equally sized, non-empty arrays")
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Ranking contains invalid values")
    order = np.argsort(-predicted, kind="stable")
    total = actual.sum()
    result = {}
    for share in [0.10, 0.20]:
        count = max(1, int(np.ceil(len(actual) * share)))
        result[f"top_{int(share * 100)}_share"] = float(actual[order[:count]].sum() / total) if total else None
    observed, forecast = pd.Series(actual), pd.Series(predicted)
    result["revenue_spearman"] = float(observed.corr(forecast, method="spearman")) if observed.nunique() > 1 and forecast.nunique() > 1 else None
    return result


def paired_mae_difference(actual, model, baseline, resamples=1000, seed=42):
    actual, model, baseline = [np.asarray(values, dtype=float) for values in [actual, model, baseline]]
    if not len(actual) or len(actual) != len(model) or len(actual) != len(baseline):
        raise ValueError("Bootstrap needs equally sized, non-empty arrays")
    if not all(np.isfinite(values).all() for values in [actual, model, baseline]) or resamples < 1:
        raise ValueError("Check bootstrap values and resample count")
    difference = np.abs(model - actual) - np.abs(baseline - actual)
    rng = np.random.default_rng(seed)
    estimates = np.empty(resamples)
    for index in range(resamples):
        sample = rng.integers(0, len(actual), size=len(actual))
        estimates[index] = difference[sample].mean()
    low, high = np.quantile(estimates, [0.025, 0.975])
    return {"difference": float(difference.mean()), "ci_low": float(low), "ci_high": float(high), "resamples": resamples, "seed": seed}


def decile_calibration(predictions):
    rows = []
    for method in ["model", "recent", "baseline"]:
        ordered = predictions.sort_values(f"{method}_revenue", kind="stable").copy()
        ordered["decile"] = np.minimum(np.arange(len(ordered)) * 10 // len(ordered) + 1, 10)
        table = ordered.groupby("decile").agg(
            customers=("actual_revenue", "size"), actual_revenue=("actual_revenue", "sum"),
            predicted_revenue=(f"{method}_revenue", "sum"),
        ).reset_index()
        table["method"] = method
        rows.append(table)
    return pd.concat(rows, ignore_index=True)


def evaluate_window(purchases, window):
    cutoff, end = window["cutoff"], window["end"]
    calibration, holdout = split_periods(purchases, cutoff, end)
    summary = customer_summary(calibration, cutoff)
    bg_model, money_model = fit_models(summary)
    days = (pd.Timestamp(end) - pd.Timestamp(cutoff)).days
    predictions = summary.copy()
    predictions["actual_purchases"] = holdout.groupby("customer_id").size().reindex(summary.index, fill_value=0)
    predictions["actual_revenue"] = holdout.groupby("customer_id")["revenue"].sum().reindex(summary.index, fill_value=0)
    predictions["model_purchases"] = predict_purchases(bg_model, summary, days)
    predictions["expected_basket"] = predict_basket(money_model, summary)
    predictions["model_revenue"] = predictions["model_purchases"] * predictions["expected_basket"]
    predictions["baseline_purchases"], predictions["baseline_revenue"] = baseline_predictions(summary, days)
    predictions["recent_purchases"], predictions["recent_revenue"] = recent_predictions(calibration, summary.index, cutoff, days)
    predictions["decile"] = pd.qcut(predictions["model_revenue"].rank(method="first"), 10, labels=False) + 1
    metrics = {}
    for method in ["model", "baseline", "recent"]:
        metrics[method] = {
            "purchases": error_metrics(predictions["actual_purchases"], predictions[f"{method}_purchases"]),
            "revenue": error_metrics(predictions["actual_revenue"], predictions[f"{method}_revenue"]),
            **ranking_metrics(predictions["actual_revenue"], predictions[f"{method}_revenue"]),
        }
        for target in ["purchases", "revenue"]:
            metrics[method][target]["mae_per_30d"] = monthly_mae(metrics[method][target]["mae"], days)
    repeats = summary.loc[summary["frequency"] > 0, ["frequency", "monetary_value"]]
    metrics["diagnostics"] = {
        "pearson": float(repeats.corr().iloc[0, 1]),
        "spearman": float(repeats.corr(method="spearman").iloc[0, 1]),
        "gamma_training_customers": len(repeats),
    }
    metrics["calibration_parameters"] = {"bg_nbd": bg_model.params_.to_dict(), "gamma_gamma": money_model.params_.to_dict()}
    metrics["paired_bootstrap"] = {
        f"model_minus_{method}": paired_mae_difference(predictions["actual_revenue"], predictions["model_revenue"], predictions[f"{method}_revenue"])
        for method in ["recent", "baseline"]
    }
    new_ids = set(holdout["customer_id"]) - set(summary.index)
    metrics["window"] = {
        **window, "start": str((pd.Timestamp(cutoff) + pd.Timedelta(days=1)).date()),
        "days": days, "known_customers": len(summary), "new_customers": len(new_ids),
        "new_revenue": float(holdout.loc[holdout["customer_id"].isin(new_ids), "revenue"].sum()),
        "zero_purchase_customers": int(predictions["actual_purchases"].eq(0).sum()),
    }
    deciles = predictions.groupby("decile").agg(
        customers=("actual_revenue", "size"), actual_revenue=("actual_revenue", "sum"),
        model_revenue=("model_revenue", "sum"), baseline_revenue=("baseline_revenue", "sum"), recent_revenue=("recent_revenue", "sum"),
    )
    monthly = []
    previous_days = 0
    start_month, end_month = pd.Timestamp(metrics["window"]["start"]).to_period("M"), pd.Timestamp(end).to_period("M")
    known_holdout = holdout.loc[holdout["customer_id"].isin(summary.index)]
    for month in pd.period_range(start_month, end_month, freq="M"):
        month_end = min(month.end_time.normalize(), pd.Timestamp(end))
        cumulative_days = (month_end - pd.Timestamp(cutoff)).days
        before = predict_purchases(bg_model, summary, previous_days)
        after = predict_purchases(bg_model, summary, cumulative_days)
        monthly.append({
            "month": str(month), "actual_revenue": float(known_holdout.loc[known_holdout["date"].dt.to_period("M").eq(month), "revenue"].sum()),
            "model_revenue": float(((after - before) * predictions["expected_basket"]).sum()),
            "baseline_revenue": float(predictions["baseline_revenue"].sum() * (cumulative_days - previous_days) / days),
            "recent_revenue": float(predictions["recent_revenue"].sum() * (cumulative_days - previous_days) / days),
        })
        previous_days = cumulative_days
    return metrics, predictions, deciles, pd.DataFrame(monthly)


def run_backtests(purchases, output):
    results, rows, predictions, deciles, monthly = {}, [], [], [], []
    original = None
    for window in WINDOWS:
        metrics, customers, groups, months = evaluate_window(purchases, window)
        results[window["id"]] = metrics
        if window["id"] == "original":
            original = metrics, customers, groups, months
        predictions.append(customers.reset_index().assign(window=window["id"]))
        deciles.append(decile_calibration(customers).assign(window=window["id"]))
        monthly.append(months.assign(window=window["id"]))
        for method in ["model", "recent", "baseline"]:
            interval = metrics["paired_bootstrap"].get(f"model_minus_{method}", {})
            rows.append({
                "window": window["id"], "method": method, "customers": len(customers), "days": metrics["window"]["days"],
                **metrics[method]["revenue"], "top_10_share": metrics[method]["top_10_share"],
                "top_20_share": metrics[method]["top_20_share"], "revenue_spearman": metrics[method]["revenue_spearman"],
                "model_minus_baseline_mae": interval.get("difference"), "ci_low": interval.get("ci_low"), "ci_high": interval.get("ci_high"),
                "gamma_pearson": metrics["diagnostics"]["pearson"], "gamma_spearman": metrics["diagnostics"]["spearman"],
            })
    pd.DataFrame(rows).to_csv(output / "backtests_summary.csv", index=False)
    pd.concat(predictions, ignore_index=True).to_csv(output / "backtests_predictions.csv", index=False)
    pd.concat(deciles, ignore_index=True).to_csv(output / "backtests_deciles.csv", index=False)
    pd.concat(monthly, ignore_index=True).to_csv(output / "backtests_monthly.csv", index=False)
    return results, original
