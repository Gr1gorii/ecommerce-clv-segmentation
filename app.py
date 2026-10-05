import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.segments import ACTIONS, apply_cac_range, campaign_scenario
from src.models import discount_schedule
from src.validation import monthly_mae
from src.translations import number, translate


ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data/processed'
BLUE = '#325D82'
GREY = '#8995A1'
GOLD = '#AD8244'
st.set_page_config(page_title='CLV | Online Retail II', layout='wide')
st.markdown('''
<style>
.block-container {padding-top: 2.5rem; padding-bottom: 2rem;}
h1 {font-size: 2rem;}
h3 {font-size: 1.25rem;}
</style>
''', unsafe_allow_html=True)

def keep_preferences():
    keys = ['page', 'portfolio_segment', 'campaign_segment', 'margin', 'returns', 'reserve', 'service', 'uplift', 'contact_cost', 'discount', 'annual_discount', 'validation_window', 'calibration_baseline']
    st.session_state['preferences'] = {key: st.session_state[key] for key in keys if key in st.session_state}


st.sidebar.title('Online Retail II')
language_name = st.sidebar.selectbox('Language / Lingua', ['English', 'Italiano'], key='language', on_change=keep_preferences)
if 'preferences' in st.session_state:
    st.session_state.update(st.session_state.pop('preferences'))
language = 'it' if language_name == 'Italiano' else 'en'


def t(text):
    return translate(text, language)


def count(value):
    return number(value, language=language)


def percent(value, signed=False):
    sign = '+' if signed and value > 0 else ''
    return sign + number(value * 100, 1, language) + '%'


def money(value, decimals=0):
    sign = '-' if value < 0 else ''
    return sign + '£' + number(abs(value), decimals, language)


@st.cache_data
def load_results(updated_at):
    customers = pd.read_csv(DATA / 'customers.csv', dtype={'customer_id': str})
    metrics = json.loads((DATA / 'metrics.json').read_text(encoding='utf-8'))
    metadata = json.loads((DATA / 'metadata.json').read_text(encoding='utf-8'))
    backtests = json.loads((DATA / 'backtests_metrics.json').read_text(encoding='utf-8'))
    schedule = pd.read_csv(DATA / 'revenue_schedule.csv', index_col='customer_id', dtype={'customer_id': str})
    return customers, metrics, metadata, backtests, schedule


def show_chart(figure, height=350):
    figure.update_layout(
        height=height, margin=dict(l=10, r=20, t=20, b=40),
        font=dict(family='Arial', size=13, color='#202C38'),
        paper_bgcolor='white', plot_bgcolor='white',
        legend=dict(orientation='h', y=1.14, x=0),
        separators=', ' if language == 'it' else '. ',
    )
    figure.update_xaxes(showgrid=False, zeroline=False)
    figure.update_yaxes(gridcolor='#E9EDF0', zeroline=False)
    st.plotly_chart(figure, use_container_width=True, config={'displayModeBar': False})


if not (DATA / 'customers.csv').exists():
    st.error(t('Run python -m src.pipeline first'))
    st.stop()

customers, metrics, metadata, backtests, schedule = load_results((DATA / 'customers.csv').stat().st_mtime)
pages = ['Portfolio', 'Retention and RFM', 'Model validation', 'Campaign budget', 'Data and method']
page = st.sidebar.radio(t('Section'), pages, format_func=t, key='page')
st.sidebar.caption('UK · GBP · 01.12.2009 - 09.12.2011')
margin, returns, reserve, service_cost = 0.35, 0.05, 0.50, 2.0
annual_discount = metadata['assumptions']['annual_discount']
if page in ['Portfolio', 'Campaign budget']:
    for key, value in {'margin': int(round(metadata['assumptions']['margin'] * 100)), 'annual_discount': annual_discount * 100, 'returns': 5, 'reserve': 50, 'service': 2.0}.items():
        st.session_state.setdefault(key, value)
    with st.sidebar.expander(t('Budget assumptions'), expanded=True):
        margin = st.slider(t('Margin after variable costs, %'), 0, 100, key='margin') / 100
        annual_discount = st.number_input(t('Annual discount rate, %'), 0.0, 100.0, step=1.0, key='annual_discount') / 100
        returns = st.slider(t('Revenue lost to returns, %'), 0, 20, key='returns') / 100
        reserve = st.slider(t('CLV share available for spending, %'), 0, 100, key='reserve') / 100
        service_cost = st.number_input(t('Fixed cost per customer, £'), 0.0, 100.0, step=0.5, key='service')
    st.sidebar.caption(t('Horizon: 360 days. Margin: {margin}. Annual discount: {rate}.').format(margin=percent(margin), rate=percent(annual_discount)))
    customers['discounted_revenue'] = discount_schedule(schedule, annual_discount).reindex(customers['customer_id']).to_numpy()
biases = [values['model']['revenue']['bias'] for values in backtests.values()]
bias_low, bias_high = min(biases), max(biases)
customers = apply_cac_range(customers, bias_low, bias_high, margin, returns, reserve, service_cost)

if page == 'Portfolio':
    st.title(t('CLV and customer budget'))
    st.caption(t('Snapshot: 09 Dec 2011 · existing UK customers · forecast for the next 360 days'))
    segment = st.selectbox(t('Portfolio segment'), ['All'] + list(ACTIONS), format_func=t, key='portfolio_segment')
    selected = customers if segment == 'All' else customers.loc[customers['segment'] == segment]
    if selected.empty:
        st.info(t('No customers in this segment'))
        st.stop()
    cols = st.columns([1, 1, 1, 2])
    cols[0].metric(t('Customers'), count(len(selected)))
    cols[1].metric(t('Revenue PV, £m'), number(selected['discounted_revenue'].sum() / 1e6, 2, language))
    cols[2].metric(t('CLV, £m'), number(selected['contribution_clv'].sum() / 1e6, 2, language))
    cols[3].metric(t('Median CAC scenario range'), money(selected['cac_lower'].median(), 2) + ' - ' + money(selected['cac_upper'].median(), 2))
    st.caption(t('Point CAC: {point}. Recommended conservative limit: {lower} per customer.').format(point=money(selected['cac_reference'].median(), 2), lower=money(selected['cac_lower'].median(), 2)))
    st.caption(t('CLV = max(0, revenue PV × (1 - returns) × margin - fixed costs). Limit = CLV × spending share.'))
    with st.container(border=True):
        st.subheader(t('Key result'))
        st.write(t('I use the model to rank customers: it beats both baselines in all three windows. Absolute revenue bias ranges from -21% to +34% across seasonal windows. MAE gains versus the 90-day baseline are not statistically significant. I recommend the conservative CAC bound.'))
    st.caption(t('Observed model bias: {low} to {high}. Scenario PV = forecast PV / (1 + bias), then margin, returns, fixed costs and spending share. This range is not a confidence interval or an individual prediction bound.').format(low=percent(bias_low, signed=True), high=percent(bias_high, signed=True)))
    left, right = st.columns(2)
    with left:
        st.subheader(t('Segment contribution to CLV'))
        totals = selected.groupby('segment')['contribution_clv'].sum().sort_values()
        fig = go.Figure(go.Bar(x=totals.values, y=[t(name) for name in totals.index], orientation='h', marker_color=BLUE, hovertemplate='%{y}<br>CLV: £%{x:,.0f}<extra></extra>'))
        fig.update_xaxes(title=t('Expected contribution over 360 days, £'), rangemode='tozero')
        show_chart(fig)
    with right:
        st.subheader(t('CLV distribution'))
        values, edges = np.histogram(np.log10(1 + selected['contribution_clv']), bins=30)
        fig = go.Figure(go.Bar(
            x=(edges[:-1] + edges[1:]) / 2, y=values,
            width=np.diff(edges) * 0.96, marker_color=BLUE,
            customdata=np.column_stack([10 ** edges[:-1] - 1, 10 ** edges[1:] - 1]),
            hovertemplate='CLV £%{customdata[0]:,.0f} - £%{customdata[1]:,.0f}<br>' + t('Customers') + ': %{y}<extra></extra>',
        ))
        ticks = [0, 10, 100, 1000, 10000, 100000]
        fig.update_xaxes(title=t('CLV, £ · logarithmic scale'), tickvals=np.log10(1 + np.array(ticks)), ticktext=[count(x) for x in ticks])
        fig.update_yaxes(title=t('Customers'), rangemode='tozero')
        show_chart(fig)
    st.subheader(t('Action and budget reference'))
    table = selected.groupby('segment').agg(
        customers=('customer_id', 'size'), median_clv=('contribution_clv', 'median'),
        median_limit=('cac_reference', 'median'), lower_limit=('cac_lower', 'median'), upper_limit=('cac_upper', 'median'), total_clv=('contribution_clv', 'sum'),
    ).reset_index()
    table['action'] = table['segment'].map(ACTIONS).map(t)
    table['segment'] = table['segment'].map(t)
    labels = {'segment': 'Segment', 'customers': 'Customers', 'median_clv': 'Median CLV, £', 'median_limit': 'Point CAC, £', 'lower_limit': 'Conservative CAC, £', 'upper_limit': 'Upper scenario CAC, £', 'total_clv': 'Segment CLV, £', 'action': 'Action'}
    table = table.rename(columns={key: t(value) for key, value in labels.items()})
    st.dataframe(table.round(1), hide_index=True, use_container_width=True)
    st.info(t('This limit uses existing customer histories. Validate CAC for a new acquisition channel using its own cohorts. Measure retention impact with an experiment.'))
    export = selected[['customer_id', 'segment', 'rfm', 'expected_basket', 'contribution_clv', 'cac_reference', 'cac_lower', 'cac_upper', 'action']].copy()
    export['segment'] = export['segment'].map(t)
    export['action'] = export['action'].map(t)
    export = export.rename(columns={column: t(column) for column in export.columns})
    st.download_button(t('Download selected customers, CSV'), export.to_csv(index=False).encode('utf-8-sig'), f'customers_{language}.csv', 'text/csv')

elif page == 'Retention and RFM':
    st.title(t('Retention and RFM'))
    st.caption(t('Purchase = a customer purchase day. Retention = the cohort share with a purchase in a given month.'))
    retention = pd.read_csv(DATA / 'retention.csv', index_col=0)
    sizes = pd.read_csv(DATA / 'cohort_sizes.csv', index_col=0)
    month_one = retention['1'].notna()
    weighted = (retention.loc[month_one, '1'] * sizes.loc[month_one, 'customers']).sum() / sizes.loc[month_one, 'customers'].sum()
    cols = st.columns(3)
    cols[0].metric(t('Weighted M1 retention'), percent(weighted))
    cols[1].metric(t('Customers with one purchase'), percent(customers['purchases'].eq(1).mean()))
    cols[2].metric(t('Median days since purchase'), count(customers['days_since_purchase'].median()))
    st.subheader(t('Monthly cohort retention'))
    matrix = retention.loc[:, [str(i) for i in range(1, 13)]]
    labels = [f"{cohort} · n={sizes.loc[cohort, 'customers']}" for cohort in matrix.index]
    fig = go.Figure(go.Heatmap(
        z=matrix.values, x=[f'M{i}' for i in range(1, 13)], y=labels,
        zmin=0, zmax=0.5, colorscale=[[0, '#F3F6F9'], [0.5, '#BFCDDA'], [1, '#7F9DB7']],
        text=np.where(matrix.notna(), matrix.fillna(0).map(lambda x: f'{x:.0%}'), ''),
        texttemplate='%{text}', textfont={'size': 11},
        hovertemplate='%{y}<br>%{x}: %{z:.1%}<extra></extra>', colorbar=dict(tickformat='.0%', title='Retention'),
    ))
    fig.update_yaxes(autorange='reversed', showgrid=False)
    show_chart(fig, 650)
    st.caption(t('Blank cells: the month has not been observed yet. I exclude incomplete December 2011 entirely. The first cohort includes customers who joined before the dataset started.'))
    left, right = st.columns(2)
    with left:
        st.subheader(t('Number of purchase days'))
        counts = customers['purchases'].clip(upper=10).value_counts().sort_index()
        fig = go.Figure(go.Bar(x=counts.index, y=counts.values, marker_color=BLUE))
        fig.update_xaxes(title=t('Purchase days'), tickvals=list(range(1, 11)), ticktext=[str(i) for i in range(1, 10)] + ['10+'])
        fig.update_yaxes(title=t('Customers'), rangemode='tozero')
        show_chart(fig, 310)
    with right:
        st.subheader(t('RFM: recency and frequency'))
        rfm = customers.groupby(['r_score', 'f_score']).size().unstack(fill_value=0).reindex(index=range(1, 6), columns=range(1, 6), fill_value=0)
        fig = go.Figure(go.Heatmap(z=rfm.values, x=rfm.columns, y=rfm.index, colorscale=[[0, '#F3F6F9'], [1, '#7F9DB7']], text=rfm.values, texttemplate='%{text}', showscale=False))
        fig.update_xaxes(title=t('F: frequency, 5 = higher'))
        fig.update_yaxes(title=t('R: recency, 5 = more recent'), showgrid=False)
        show_chart(fig, 310)
    with st.expander(t('How I calculate RFM and segments')):
        st.write(t('R is days since the last purchase, F is purchase days, and M is cumulative positive revenue. Scores 1-5 use percentile ranks; equal values receive equal scores.'))
        st.write(t('New: one purchase and age up to 90 days. Returning customers are dormant after more than 90 days without a purchase. High CLV: the top 25% of forecast revenue. Thresholds are fixed at the full snapshot.'))
    st.subheader(t('Observed monthly revenue, £'))
    monthly = pd.read_csv(DATA / 'monthly.csv')
    fig = go.Figure(go.Bar(x=monthly['month'], y=monthly['revenue'], marker_color=BLUE))
    show_chart(fig, 310)
    st.caption(t('December 2011 includes only days 1-9. This is positive merchandise revenue before subtracting returns.'))

elif page == 'Model validation':
    st.title(t('Validation on future periods'))
    with st.container(border=True):
        st.subheader(t('Key result'))
        st.write(t('I use the model to rank customers: it beats both baselines in all three windows. Absolute revenue bias ranges from -21% to +34% across seasonal windows. MAE gains versus the 90-day baseline are not statistically significant. I recommend the conservative CAC bound.'))
    labels = {key: values['window']['label'] for key, values in backtests.items()}
    selected_window = st.selectbox(t('Backtest window'), list(backtests), format_func=lambda key: t(labels[key]), key='validation_window')
    result = backtests[selected_window]
    window = result['window']
    st.caption(t('Training: {start} - {cutoff}. Holdout: {holdout_start} - {end}, {days} days.').format(start=metadata['start_date'], cutoff=window['cutoff'], holdout_start=window['start'], end=window['end'], days=window['days']))
    model, recent = result['model']['revenue'], result['recent']['revenue']
    improvement = 1 - model['mae'] / recent['mae']
    cols = st.columns(4)
    cols[0].metric(t('MAE per customer, {days} days').format(days=window['days']), money(model['mae']))
    cols[0].caption(t('£{mae} per customer / 30 days').format(mae=number(monthly_mae(model['mae'], window['days']), 2, language)))
    cols[1].metric(t('MAE reduction vs 90 days'), percent(improvement))
    cols[2].metric(t('Total revenue bias'), percent(model['bias'], signed=True))
    cols[3].metric(t('Revenue captured by top 20%'), percent(result['model']['top_20_share']))
    st.caption(t('I evaluate {known} known customers, including those with no holdout purchases. The {new} new holdout customers are excluded from these forecast metrics.').format(known=count(window['known_customers']), new=count(window['new_customers'])))
    st.subheader(t('Three backtests, unchanged fitting settings'))
    overview = []
    for key, values in backtests.items():
        for method, label in [('model', 'BG/NBD + Gamma-Gamma'), ('recent', 'Last 90 days'), ('baseline', 'Full history')]:
            revenue = values[method]['revenue']
            overview.append({t('Window'): t(labels[key]), t('Days'): values['window']['days'], t('Forecast'): t(label), t('MAE, £/customer'): round(revenue['mae'], 2), t('MAE per 30 days, £/customer'): round(monthly_mae(revenue['mae'], values['window']['days']), 2), t('Bias'): percent(revenue['bias'], signed=True)})
    st.dataframe(pd.DataFrame(overview), hide_index=True, use_container_width=True)
    st.caption(t('Monthly normalisation = window MAE × 30 / window days. It rescales the full-window error; it is not MAE calculated from monthly forecasts. Season and customer mix still differ.'))
    st.info(t('Bias is negative in both peak windows and positive in spring. This is consistent with seasonal miscalibration, but different horizons and training histories prevent a causal conclusion.'))
    left, right = st.columns(2)
    with left:
        st.subheader(t('Revenue error per customer, £') + ' · ' + t('{days} days').format(days=window['days']))
        fig = go.Figure()
        for method, color, label in [('baseline', GREY, 'Full history'), ('recent', GOLD, 'Last 90 days'), ('model', BLUE, 'BG/NBD + Gamma-Gamma')]:
            values = result[method]['revenue']
            fig.add_trace(go.Bar(name=t(label), x=[t('MAE, {days} days').format(days=window['days']), t('RMSE, {days} days').format(days=window['days'])], y=[values['mae'], values['rmse']], marker_color=color))
        fig.update_layout(barmode='group')
        fig.update_yaxes(rangemode='tozero')
        show_chart(fig)
    with right:
        st.subheader(t('Ranking on holdout revenue'))
        ranking = []
        for method, label in [('model', 'BG/NBD + Gamma-Gamma'), ('recent', 'Last 90 days'), ('baseline', 'Full history')]:
            values = result[method]
            ranking.append({t('Forecast'): t(label), 'Top 10%': percent(values['top_10_share']), 'Top 20%': percent(values['top_20_share']), 'Spearman': round(values['revenue_spearman'], 3)})
        st.dataframe(pd.DataFrame(ranking), hide_index=True, use_container_width=True)
        st.caption(t('Each method selects its own top customers before observing the holdout. Shares use known-customer revenue. Spearman compares predicted and actual customer revenue.'))
    st.subheader(t('Paired bootstrap: MAE difference, £/customer') + ' · ' + t('{days} days').format(days=window['days']))
    intervals = []
    for method, label in [('recent', 'Last 90 days'), ('baseline', 'Full history')]:
        interval = result['paired_bootstrap'][f'model_minus_{method}']
        intervals.append({t('Comparison baseline'): t(label), t('Model minus baseline'): round(interval['difference'], 2), t('95% CI lower'): round(interval['ci_low'], 2), t('95% CI upper'): round(interval['ci_high'], 2)})
    st.dataframe(pd.DataFrame(intervals), hide_index=True, use_container_width=True)
    st.caption(t('1 000 paired customer resamples, seed 42, percentile 95% CI. Negative favours the model. Predictions stay fixed; the interval does not cover refitting or shared time shocks.'))
    st.subheader(t('Decile calibration'))
    comparison = st.selectbox(t('Calibration baseline'), ['recent', 'baseline'], format_func=lambda key: t('Last 90 days' if key == 'recent' else 'Full history'), key='calibration_baseline')
    deciles = pd.read_csv(DATA / 'backtests_deciles.csv')
    deciles = deciles.loc[deciles['window'].eq(selected_window)]
    left, right = st.columns(2)
    for column, method, label in [(left, 'model', 'BG/NBD + Gamma-Gamma'), (right, comparison, 'Last 90 days' if comparison == 'recent' else 'Full history')]:
        with column:
            st.write(t(label))
            groups = deciles.loc[deciles['method'].eq(method)]
            fig = go.Figure()
            for name, legend, color, dash in [('actual_revenue', 'Actual', '#202C38', 'solid'), ('predicted_revenue', 'Forecast', BLUE if method == 'model' else GOLD, 'dash')]:
                fig.add_trace(go.Scatter(x=groups['decile'], y=groups[name] / groups['customers'], mode='lines+markers', name=t(legend), line=dict(color=color, dash=dash)))
            fig.update_xaxes(title=t('Forecast decile: 10 = high'), dtick=1)
            fig.update_yaxes(title=t('Mean revenue per customer, £'), rangemode='tozero')
            show_chart(fig)
    st.caption(t('Each method has its own approximately equal-sized forecast deciles. Customers are grouped by prediction only; ties use customer ID order.'))
    st.subheader(t('Monthly holdout revenue, £'))
    monthly = pd.read_csv(DATA / 'backtests_monthly.csv')
    monthly = monthly.loc[monthly['window'].eq(selected_window)]
    fig = go.Figure()
    for name, label, color in [('actual_revenue', 'Actual', '#202C38'), ('model_revenue', 'Model', BLUE), ('recent_revenue', '90 days', GOLD)]:
        fig.add_trace(go.Bar(x=monthly['month'], y=monthly[name], name=t(label), marker_color=color))
    fig.update_layout(barmode='group')
    show_chart(fig, 310)
    st.caption(t('Each month uses actual and forecast revenue for exactly the same holdout dates. BG/NBD does not model seasonality.'))
    diagnostic = result['diagnostics']
    st.write(t('Frequency versus repeat daily basket in training: Pearson {pearson}; Spearman {spearman}. Low correlation does not establish Gamma-Gamma independence.').format(pearson=number(diagnostic['pearson'], 3, language), spearman=number(diagnostic['spearman'], 3, language)))
    st.info(t('The model settings are fixed across windows. New holdout customers are excluded; known customers with zero purchases remain included. The 360-day CLV forecast still extends beyond the longest validated horizon of 183 days.'))

elif page == 'Campaign budget':
    st.title(t('Campaign budget and CAC'))
    st.caption(t('Scenario for an additional purchase within 90 days. Uplift is an assumption, not a model result.'))
    for key, value in {'campaign_segment': 'High-value dormant', 'uplift': 2.0, 'contact_cost': 1.0, 'discount': 0}.items():
        st.session_state.setdefault(key, value)
    segment = st.selectbox(t('Campaign segment'), list(ACTIONS), format_func=t, key='campaign_segment')
    selected = customers.loc[customers['segment'] == segment]
    left, right, third = st.columns(3)
    uplift = left.slider(t('Additional purchase probability, pp'), 0.0, 15.0, step=0.5, key='uplift') / 100
    contact_cost = right.number_input(t('Contact cost per customer, £'), 0.0, 50.0, step=0.1, key='contact_cost')
    if margin > 0:
        discount = third.slider(t('Discount on the additional purchase, %'), 0, int(round(margin * 100)), key='discount') / 100
    else:
        discount = 0.0
        third.caption(t('No discount at zero margin.'))
    expected = campaign_scenario(selected, uplift, contact_cost, discount, margin, returns)
    incremental_contribution = uplift * selected['expected_basket'].sum() * (1 - returns) * (margin - discount)
    total_cost = len(selected) * contact_cost
    cols = st.columns(4)
    cols[0].metric(t('Campaign customers'), count(len(selected)))
    cols[1].metric(t('Incremental contribution'), money(incremental_contribution))
    cols[2].metric(t('Contact costs'), money(total_cost))
    cols[3].metric(t('Scenario result'), money(expected))
    unit_contribution = selected['expected_basket'].mean() * (1 - returns) * (margin - discount)
    if unit_contribution > 0:
        break_even = contact_cost / unit_contribution
        st.write(t('Expected average basket: {basket}. Break-even uplift: {uplift} pp.').format(basket=money(selected['expected_basket'].mean()), uplift=number(break_even * 100, 2, language)))
    else:
        st.write(t('Contribution after the discount is zero. It cannot cover contact costs.'))
    st.write(t(ACTIONS[segment]))
    fig = go.Figure(go.Waterfall(
        x=[t('Incremental contribution'), t('Contacts'), t('Result')], y=[incremental_contribution, -total_cost, 0],
        measure=['relative', 'relative', 'total'],
        increasing=dict(marker_color=BLUE), decreasing=dict(marker_color=GOLD), totals=dict(marker_color='#202C38'),
        text=[money(incremental_contribution), money(-total_cost), money(expected)], textposition='outside',
    ))
    fig.update_yaxes(range=[min(0, expected) * 1.15, max(incremental_contribution, total_cost, expected, 1) * 1.15])
    show_chart(fig, 340)
    st.caption(t('Result = n × uplift × expected average basket × (1 - returns) × (margin - discount) - n × contact cost. I exclude cannibalisation and discounts on purchases that would happen without the campaign.'))
    st.warning(t('CLV measures future customer value, not contact impact. A retention budget needs an A/B test. CAC before the first purchase needs channel, first basket and conversion data.'))
    st.subheader(t('Conditional CAC scenario'))
    cols = st.columns([1, 1.7, 1.3])
    cols[0].metric(t('Point CAC, £'), money(selected['cac_reference'].median(), 2))
    cols[1].metric(t('Median CAC scenario range'), money(selected['cac_lower'].median(), 2) + ' - ' + money(selected['cac_upper'].median(), 2))
    cols[2].metric(t('Recommended conservative CAC'), money(selected['cac_lower'].median(), 2))
    st.caption(t('Observed model bias: {low} to {high}. Scenario PV = forecast PV / (1 + bias), then margin, returns, fixed costs and spending share. This range is not a confidence interval or an individual prediction bound.').format(low=percent(bias_low, signed=True), high=percent(bias_high, signed=True)))
    st.caption(t('These CAC references exclude the first basket and do not measure retention campaign impact.'))

else:
    st.title(t('Data and method'))
    st.write(t('I use both Online Retail II worksheets. I keep positive UK merchandise sales with a Customer ID and aggregate them into customer purchase days.'))
    st.markdown(t('Source: [Daqing Chen, Online Retail II, UCI](https://archive.ics.uci.edu/dataset/502/online+retail+ii), CC BY 4.0 licence.'))
    cols = st.columns(3)
    cols[0].metric(t('Raw rows'), count(metadata['raw_rows']))
    cols[1].metric(t('UK merchandise rows'), count(metadata['clean_rows']))
    cols[2].metric(t('Purchase days'), count(metadata['purchase_days']))
    audit = pd.read_csv(DATA / 'cleaning.csv')
    audit['step'] = audit['step'].map(t)
    audit = audit.rename(columns={'step': t('Step'), 'removed': t('Removed'), 'remaining': t('Remaining')})
    st.dataframe(audit, hide_index=True, use_container_width=True)
    st.subheader(t('How I validate the model'))
    st.write(t('BG/NBD frequency is purchase days minus one. Model recency is days between the first and last purchase, and T is age since the first purchase. RFM recency instead means days since the last purchase.'))
    st.write(t("I fit Gamma-Gamma only on returning customers. The average basket excludes the first purchase day. One-purchase customers use the model's population average basket."))
    st.write(t('Full-history baseline: purchase days / (T + 1) × forecast days. Revenue equals this forecast × historical average daily basket. I fix both models before the holdout.'))
    st.write(t('Second baseline: purchases and revenue in the last 90 training days × 183 / 90. The window is fixed for everyone, including recent customers. I do not select the window on holdout data.'))
    st.write(t('After validation I refit on the full period. I keep validation metrics separate and do not recalculate them with the final model.'))
    diagnostics = metrics['diagnostics']
    st.write(t('Training correlation between frequency and repeat basket: Pearson {pearson}, Spearman {spearman}. This diagnoses the Gamma-Gamma independence assumption; it does not prove independence.').format(pearson=number(diagnostics['pearson'], 3, language), spearman=number(diagnostics['spearman'], 3, language)))
    st.write(t('I evaluate three temporal windows with identical fitting settings, including paired bootstrap intervals and revenue ranking metrics. I calculate BG/NBD forecasts with an equivalent signed hypergeometric expression to avoid invalid logarithms for young one-purchase customers.'))
    st.subheader(t('Limitations'))
    st.write(t('Data ends in 2011. Acquisition channels, actual costs, margins and contact outcomes are unavailable. I exclude returns from purchases and use an assumed future loss rate. Large wholesale customers influence RMSE. The first cohort is not a true acquisition cohort.'))
    st.write(t('BG/NBD does not model seasonality. For one-purchase customers its alive probability is 1 by construction, so I do not treat it as evidence of activity. Individual uncertainty intervals are not available yet.'))
    st.code(metadata['sha256'], language=None)
    st.caption(t('Original XLSX SHA-256. Full calculation: python -m src.pipeline'))
