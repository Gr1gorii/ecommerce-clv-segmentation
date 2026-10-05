from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from lifetimes import BetaGeoFitter

from src.models import discount_schedule, predict_purchases
from src.segments import apply_economics
from src.validation import decile_calibration, paired_mae_difference, ranking_metrics


def test_ranking_shares_and_spearman():
    values = np.arange(10, 101, 10)
    result = ranking_metrics(values, values)
    assert result['top_10_share'] == pytest.approx(100 / 550)
    assert result['top_20_share'] == pytest.approx(190 / 550)
    assert result['revenue_spearman'] == pytest.approx(1)


def test_ranking_ties_ignore_actual_revenue_and_handle_zero_totals():
    result = ranking_metrics([0, 0, 100], [5, 5, 5])
    assert result['top_20_share'] == 0
    assert result['revenue_spearman'] is None
    assert ranking_metrics([0, 0], [1, 2])['top_10_share'] is None
    with pytest.raises(ValueError):
        ranking_metrics([1, 2], [1, np.nan])


def test_bootstrap_resamples_paired_errors():
    result = paired_mae_difference([0, 100], [10, 110], [20, 120])
    assert result['resamples'] == 1000
    assert result['difference'] == -10
    assert result['ci_low'] == result['ci_high'] == -10
    same = paired_mae_difference([0, 100], [10, 80], [10, 80])
    assert same['difference'] == same['ci_low'] == same['ci_high'] == 0


def test_bootstrap_is_reproducible_and_rejects_missing_predictions():
    inputs = [0, 100, 50], [20, 110, 60], [5, 80, 90]
    assert paired_mae_difference(*inputs) == paired_mae_difference(*inputs)
    with pytest.raises(ValueError):
        paired_mae_difference([0, 1], [0, np.nan], [1, 1])


def test_calibration_groups_by_each_forecast():
    predictions = pd.DataFrame({
        'actual_revenue': np.arange(10) * 100,
        'model_revenue': np.arange(10),
        'recent_revenue': np.arange(10)[::-1],
        'baseline_revenue': np.arange(10),
    })
    result = decile_calibration(predictions)
    model = result.loc[result['method'].eq('model')].set_index('decile')
    recent = result.loc[result['method'].eq('recent')].set_index('decile')
    assert model.loc[10, 'actual_revenue'] == 900
    assert recent.loc[10, 'actual_revenue'] == 0
    assert result.groupby('method')['customers'].sum().eq(10).all()


def test_cac_uses_discounted_contribution_not_gross_revenue():
    schedule = pd.DataFrame({'1': [100.0], '2': [100.0]})
    present_value = discount_schedule(schedule, annual_discount=0.21)
    expected = 100 / 1.21 ** (1 / 12) + 100 / 1.21 ** (2 / 12)
    assert present_value.iloc[0] == pytest.approx(expected)
    assert discount_schedule(schedule, 0).iloc[0] == 200
    budget = apply_economics(pd.DataFrame({'discounted_revenue': present_value}), margin=0.35, returns=0.05, service_cost=2, reserve=0.5)
    assert budget['cac_reference'].iloc[0] == pytest.approx((expected * 0.95 * 0.35 - 2) * 0.5)
    assert budget['cac_reference'].iloc[0] < 200 * 0.5
    with pytest.raises(ValueError):
        discount_schedule(schedule, -0.1)


def test_stable_bg_prediction_agrees_with_lifetimes():
    model = BetaGeoFitter()
    model.params_ = pd.Series({'r': 0.7, 'alpha': 66.0, 'a': 0.08, 'b': 1.3})
    summary = pd.DataFrame({'frequency': [0, 1, 4], 'recency': [0, 20, 50], 'T': [10, 30, 90]})
    expected = model.conditional_expected_number_of_purchases_up_to_time(122, summary['frequency'], summary['recency'], summary['T'])
    np.testing.assert_allclose(predict_purchases(model, summary, 122), expected, rtol=1e-10)


def test_stable_bg_prediction_keeps_young_one_purchase_customers():
    model = SimpleNamespace(params_={'r': 0.7971744233, 'alpha': 69.65496068, 'a': 7.9646e-8, 'b': 3.84055e-5})
    summary = pd.DataFrame({'frequency': [0, 0, 1], 'recency': [0, 0, 10], 'T': [0, 27, 50]})
    values = predict_purchases(model, summary, 122)
    assert len(values) == 3
    assert np.isfinite(values).all()
    assert values.ge(0).all()
    assert values.ge(predict_purchases(model, summary, 60)).all()
    assert predict_purchases(model, summary, 0).eq(0).all()


def test_cac_range_inverts_bias_before_costs_and_preserves_customers():
    from src.segments import apply_cac_range

    customers = pd.DataFrame({'discounted_revenue': [1000.0, 5.0]}, index=['repeat', 'small'])
    result = apply_cac_range(customers, -0.20, 0.25)
    assert result.loc['repeat', 'cac_lower'] == pytest.approx((800 * 0.95 * 0.35 - 2) * 0.5)
    assert result.loc['repeat', 'cac_upper'] == pytest.approx((1250 * 0.95 * 0.35 - 2) * 0.5)
    assert result.loc['small', 'cac_lower'] == 0
    assert result.loc['small', 'cac_upper'] > 0
    assert result['cac_lower'].le(result['cac_reference']).all()
    assert result['cac_reference'].le(result['cac_upper']).all()
    assert list(customers.columns) == ['discounted_revenue']
    assert apply_cac_range(customers, -0.20, 0.25, margin=0)['cac_upper'].eq(0).all()


def test_cac_range_rejects_invalid_bias_bounds():
    from src.segments import apply_cac_range

    customers = pd.DataFrame({'discounted_revenue': [1000.0]})
    for low, high in [(-1, 0.3), (0.3, -0.2), (np.nan, 0.3), (-0.2, np.inf)]:
        with pytest.raises(ValueError):
            apply_cac_range(customers, low, high)


def test_monthly_mae_rescales_the_full_window():
    from src.validation import monthly_mae

    assert monthly_mae(600, 180) == 100
    assert monthly_mae(300, 90) == 100
    assert monthly_mae(0, 92) == 0
    for mae, days in [(-1, 90), (100, 0), (100, -1), (np.nan, 90), (100, np.inf)]:
        with pytest.raises(ValueError):
            monthly_mae(mae, days)


def test_prepared_metrics_and_cac_ranges_use_reported_assumptions():
    import json
    from pathlib import Path

    data = Path(__file__).resolve().parents[1] / 'data/processed'
    results = json.loads((data / 'backtests_metrics.json').read_text())
    summary = pd.read_csv(data / 'backtests_summary.csv')
    for row in summary.itertuples():
        window = results[row.window]
        assert row.days == window['window']['days']
        assert row.mae_per_30d == pytest.approx(row.mae * 30 / row.days)
        assert window[row.method]['revenue']['mae_per_30d'] == pytest.approx(row.mae_per_30d)
    customers = pd.read_csv(data / 'customers.csv')
    metadata = json.loads((data / 'metadata.json').read_text())
    assumptions = metadata['assumptions']
    low, high = min(v['model']['revenue']['bias'] for v in results.values()), max(v['model']['revenue']['bias'] for v in results.values())
    assert metadata['cac_bias_scenario'] == {'bias_low': low, 'bias_high': high}
    for column, bias in [('cac_lower', high), ('cac_upper', low)]:
        expected = np.maximum(0, customers['discounted_revenue'] / (1 + bias) * (1 - assumptions['returns']) * assumptions['margin'] - assumptions['service_cost']) * assumptions['reserve']
        np.testing.assert_allclose(customers[column], expected)
    italian = pd.read_csv(data / 'customers_it.csv')
    np.testing.assert_allclose(italian['cac_prudente'], customers['cac_lower'])
    np.testing.assert_allclose(italian['cac_scenario_superiore'], customers['cac_upper'])
