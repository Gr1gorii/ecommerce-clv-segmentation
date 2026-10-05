import numpy as np
import pandas as pd
from lifetimes import BetaGeoFitter, GammaGammaFitter
from scipy.special import hyp2f1


def fit_models(summary):
    bg_model = BetaGeoFitter(penalizer_coef=0.001)
    bg_model.fit(summary["frequency"], summary["recency"], summary["T"])
    repeats = summary.loc[(summary["frequency"] > 0) & (summary["monetary_value"] > 0)]
    money_model = GammaGammaFitter(penalizer_coef=0)
    money_model.fit(repeats["frequency"], repeats["monetary_value"], q_constraint=True)
    if money_model.params_["q"] <= 1.01:
        raise ValueError("Gamma-Gamma: the population average basket is unstable")
    return bg_model, money_model


def predict_purchases(bg_model, summary, days):
    r, alpha, a, b = [bg_model.params_[key] for key in ["r", "alpha", "a", "b"]]
    frequency = summary["frequency"].to_numpy(dtype=float)
    age = summary["T"].to_numpy(dtype=float)
    recency = summary["recency"].to_numpy(dtype=float)
    z = days / (alpha + age + days)
    scaled_hypergeom = (1 - z) ** (a - 1) * hyp2f1(a + b - 1 - r, a - 1, a + b + frequency - 1, z)
    denominator = np.ones(len(summary))
    repeats = frequency > 0
    denominator[repeats] += a / (b + frequency[repeats] - 1) * ((alpha + age[repeats]) / (alpha + recency[repeats])) ** (r + frequency[repeats])
    values = (a + b + frequency - 1) / (a - 1) * (1 - scaled_hypergeom) / denominator
    if not np.isfinite(values).all() or (values < -1e-9).any():
        raise ValueError("Predictions contain invalid values")
    return pd.Series(np.maximum(values, 0), index=summary.index)


def predict_basket(money_model, summary):
    return money_model.conditional_expected_average_profit(
        summary["frequency"], summary["monetary_value"]
    )


def revenue_schedule(bg_model, summary, expected_basket, months=12):
    if not 1 <= months <= 24:
        raise ValueError("Check the horizon and discount rate")
    schedule = pd.DataFrame(index=summary.index)
    previous = pd.Series(0.0, index=summary.index)
    for month in range(1, months + 1):
        cumulative = predict_purchases(bg_model, summary, month * 30)
        schedule[str(month)] = (cumulative - previous) * expected_basket
        previous = cumulative
    return schedule


def discount_schedule(schedule, annual_discount=0.10):
    if not np.isfinite(annual_discount) or annual_discount < 0:
        raise ValueError("Check the horizon and discount rate")
    months = np.asarray(schedule.columns, dtype=int)
    factors = (1 + annual_discount) ** (months / 12)
    return schedule.div(factors, axis=1).sum(axis=1)


def discounted_revenue(bg_model, summary, expected_basket, months=12, annual_discount=0.10):
    schedule = revenue_schedule(bg_model, summary, expected_basket, months)
    return discount_schedule(schedule, annual_discount)


def baseline_predictions(summary, days):
    purchases = summary["purchases"] / (summary["T"] + 1) * days
    return purchases, purchases * summary["average_basket"]


def recent_predictions(calibration, customer_ids, cutoff, days):
    cutoff = pd.Timestamp(cutoff)
    recent = calibration.loc[(calibration["date"] > cutoff - pd.Timedelta(days=90)) & (calibration["date"] <= cutoff)]
    purchases = recent.groupby("customer_id").size().reindex(customer_ids, fill_value=0) * days / 90
    revenue = recent.groupby("customer_id")["revenue"].sum().reindex(customer_ids, fill_value=0) * days / 90
    return purchases, revenue


def error_metrics(actual, predicted):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if not np.isfinite(predicted).all() or (predicted < 0).any():
        raise ValueError("Predictions contain invalid values")
    error = predicted - actual
    total = actual.sum()
    return {
        "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt((error ** 2).mean())),
        "wape": float(np.abs(error).sum() / total) if total else None,
        "bias": float(error.sum() / total) if total else None,
        "actual_total": float(total),
        "predicted_total": float(predicted.sum()),
    }


def top_revenue_share(actual, predicted, share=0.20):
    count = max(1, int(np.ceil(len(actual) * share)))
    selected = predicted.sort_values(ascending=False).head(count).index
    return float(actual.loc[selected].sum() / actual.sum())
