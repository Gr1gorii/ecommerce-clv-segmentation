import pandas as pd
import pytest

from src.data import clean_data, cohort_retention, customer_summary, split_periods
from src.models import error_metrics, recent_predictions
from src.segments import apply_economics, campaign_scenario


def sample_purchases():
    return pd.DataFrame({
        "customer_id": ["1", "1", "1", "2", "3"],
        "date": pd.to_datetime(["2011-01-01", "2011-02-01", "2011-04-01", "2011-01-15", "2011-03-10"]),
        "revenue": [100.0, 200.0, 9999.0, 50.0, 60.0],
    })


def test_time_split_does_not_leak_future_or_new_customers():
    calibration, holdout = split_periods(sample_purchases(), "2011-02-28", "2011-04-30")
    summary = customer_summary(calibration, "2011-02-28")
    assert set(summary.index) == {"1", "2"}
    assert summary.loc["1", "monetary_value"] == 200
    assert summary.loc["1", "frequency"] == 1
    assert summary.loc["1", "recency"] == 31
    assert summary.loc["1", "T"] == 58
    assert summary.loc["2", "monetary_value"] == 0
    assert calibration["date"].max() <= pd.Timestamp("2011-02-28")
    assert holdout["date"].min() > pd.Timestamp("2011-02-28")


def test_cleaning_and_daily_grain():
    raw = pd.DataFrame({
        "Invoice": ["1", "2", "C3", "4", "5", "6", "7"],
        "StockCode": ["12345"] * 6 + ["POST"],
        "Quantity": [1, 2, -1, 1, 1, 1, 1],
        "Price": [10, 10, 10, 0, 10, 10, 10],
        "InvoiceDate": pd.to_datetime(["2011-01-01"] * 7),
        "Customer ID": [1, 1, 1, 1, None, 2, 1],
        "Country": ["United Kingdom"] * 5 + ["France", "United Kingdom"],
    })
    raw = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)
    purchases, audit = clean_data(raw)
    assert len(purchases) == 1
    assert purchases.iloc[0]["revenue"] == 30
    assert audit["removed"].sum() + audit.iloc[-1]["remaining"] == len(raw)


def test_retention_missing_months_are_not_zero():
    retention, sizes = cohort_retention(sample_purchases(), "2011-04-09")
    assert "2011-04" not in retention.index
    assert retention.loc["2011-01", 1] == 0.5
    assert retention.loc["2011-01", 2] == 0
    assert pd.isna(retention.loc["2011-03", 1])
    assert sizes.loc["2011-01"] == 2


def test_budget_and_campaign_use_different_calculations():
    customers = pd.DataFrame({"discounted_revenue": [1000.0, 1.0], "expected_basket": [100.0, 100.0]})
    result = apply_economics(customers, margin=0.35, returns=0.05, reserve=0.5, service_cost=2)
    assert result.loc[0, "contribution_clv"] == pytest.approx(330.5)
    assert result.loc[0, "cac_reference"] == pytest.approx(165.25)
    assert result.loc[1, "cac_reference"] == 0
    assert campaign_scenario(customers, uplift=0.02, contact_cost=1) == pytest.approx(-0.67)
    with pytest.raises(ValueError):
        apply_economics(customers, margin=1.5)


def test_error_metrics_keep_customers_with_no_future_purchases():
    values = error_metrics([0, 100], [50, 100])
    assert values["mae"] == 25
    assert values["wape"] == 0.5
    assert values["bias"] == 0.5


def test_recent_baseline_ignores_future_revenue():
    counts, revenue = recent_predictions(sample_purchases(), ["1", "2", "3"], "2011-02-28", 180)
    assert counts.loc["1"] == 4
    assert revenue.loc["1"] == 600
    assert revenue.loc["3"] == 0
