import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

from src.translations import number, translate
from src.validation import monthly_mae


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/processed'
OUTPUT = ROOT / 'reports/figures'
BLUE = '#325D82'
GREY = '#8995A1'
GOLD = '#AD8244'
plt.rcParams.update({
    'font.family': 'DejaVu Sans', 'font.size': 11,
    'axes.spines.top': False, 'axes.spines.right': False,
    'axes.spines.left': False, 'axes.spines.bottom': False,
    'axes.labelcolor': '#202C38', 'text.color': '#202C38',
    'xtick.color': '#546270', 'ytick.color': '#546270',
    'figure.facecolor': 'white', 'axes.facecolor': 'white',
    'savefig.facecolor': 'white',
})


def save(figure, name, language):
    folder = OUTPUT / language
    folder.mkdir(parents=True, exist_ok=True)
    figure.savefig(folder / name, dpi=180, bbox_inches='tight')
    plt.close(figure)


def validation_figure(metrics, language):
    t = lambda text: translate(text, language)
    metadata = json.loads((DATA / 'metadata.json').read_text(encoding='utf-8'))
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.4), gridspec_kw={'width_ratios': [1, 1.4]})
    fig.suptitle(t('Revenue forecast validation on a future period'), x=0.05, ha='left', fontsize=18, fontweight='bold')
    subtitle = t('10 Jun 2011 - 09 Dec 2011 · {customers} known UK customers · {days} days')
    fig.text(0.05, 0.90, subtitle.format(customers=number(metadata['calibration_customers']), days=metadata['holdout_days']), fontsize=11, color='#546270')
    names = [t('Full history'), t('Last 90 days'), 'BG/NBD + Gamma-Gamma']
    values = [metrics[key]['revenue']['mae'] for key in ['baseline', 'recent', 'model']]
    axes[0].barh(names[::-1], values[::-1], color=[BLUE, GOLD, GREY], height=0.55)
    for y, value in enumerate(values[::-1]):
        axes[0].text(value + 10, y, '£' + number(value, language=language) + '\n£' + number(monthly_mae(value, metadata['holdout_days']), 2, language) + ' / 30d', va='center', fontsize=10)
    axes[0].set_xlim(0, 980)
    axes[0].set_xlabel(t('Revenue MAE per customer') + ' · ' + t('{days} days').format(days=metadata['holdout_days']))
    axes[0].set_title(t('Mean absolute error'), loc='left', pad=18, fontsize=13)
    axes[0].xaxis.grid(True, color='#E9EDF0')
    axes[0].set_axisbelow(True)
    deciles = pd.read_csv(DATA / 'deciles.csv')
    for column, label, color, marker, line in [
        ('actual_revenue', 'Actual', '#202C38', 'o', '-'),
        ('model_revenue', 'Model', BLUE, 's', '--'),
        ('recent_revenue', '90 days', GOLD, '^', ':'),
    ]:
        axes[1].plot(deciles['decile'], deciles[column] / 1000, label=t(label), color=color, marker=marker, linestyle=line, linewidth=2)
    axes[1].set_xticks(range(1, 11))
    axes[1].set_ylim(bottom=0)
    axes[1].set_xlabel(t('Model forecast decile: 10 = high'))
    axes[1].set_ylabel(t('Revenue, £ thousands'))
    axes[1].set_title(t('Actuals and forecasts in the same groups'), loc='left', pad=18, fontsize=13)
    axes[1].yaxis.grid(True, color='#E9EDF0')
    axes[1].legend(frameon=False, loc='upper left')
    improvement = 1 - metrics['model']['revenue']['mae'] / metrics['recent']['revenue']['mae']
    bias = metrics['model']['revenue']['bias']
    note = t('Point improvement: {improvement} over {days} days; not significant vs 90 days. Revenue bias: {bias}.')
    fig.text(0.05, 0.02, note.format(days=metadata['holdout_days'], improvement=number(improvement * 100, 1, language) + '%', bias=number(bias * 100, 1, language) + '%'), fontsize=10)
    fig.subplots_adjust(top=0.77, bottom=0.20, left=0.17, right=0.97, wspace=0.35)
    save(fig, 'validation.png', language)


def retention_figure(language):
    t = lambda text: translate(text, language)
    retention = pd.read_csv(DATA / 'retention.csv', index_col=0)
    sizes = pd.read_csv(DATA / 'cohort_sizes.csv', index_col=0)
    matrix = retention[[str(i) for i in range(1, 13)]]
    fig, ax = plt.subplots(figsize=(11, 11.2))
    fig.suptitle(t('Cohort retention: purchases in each month'), x=0.04, ha='left', fontsize=17, fontweight='bold')
    fig.text(0.04, 0.93, t('UK · share of customers purchasing · M0 = 100% · incomplete December 2011 excluded'), fontsize=10)
    color_map = plt.get_cmap('Blues').copy()
    color_map.set_bad('#F0F1F3')
    image = ax.imshow(matrix, cmap=color_map, vmin=0, vmax=0.5, aspect='auto')
    ax.set_xticks(range(12), [f'M{i}' for i in range(1, 13)])
    ax.set_yticks(range(len(matrix)), [f"{cohort}  (n={sizes.loc[cohort, 'customers']})" for cohort in matrix.index])
    ax.tick_params(length=0)
    for row in range(len(matrix)):
        for col in range(12):
            value = matrix.iloc[row, col]
            if pd.notna(value):
                ax.text(col, row, f'{value:.0%}', ha='center', va='center', fontsize=9, color='white' if value > 0.30 else '#202C38')
    bar = fig.colorbar(image, ax=ax, fraction=0.025, pad=0.03)
    bar.ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: number(value * 100, language=language) + '%'))
    fig.text(0.04, 0.015, t('Grey cells: cohort age not observed yet. The first cohort includes customers active before the dataset began.'), fontsize=9)
    fig.subplots_adjust(top=0.89, bottom=0.06, left=0.25, right=0.92)
    save(fig, 'retention.png', language)


def segment_figure(customers, language):
    t = lambda text: translate(text, language)
    totals = customers.groupby('segment').agg(customers=('customer_id', 'size'), cap=('cac_reference', 'median'), lower=('cac_lower', 'median'), upper=('cac_upper', 'median')).sort_values('customers')
    labels = [t(name) for name in totals.index]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.6), sharey=True)
    fig.suptitle(t('Customer segments and budget reference'), x=0.04, ha='left', fontsize=18, fontweight='bold')
    fig.text(0.04, 0.90, t('09 Dec 2011 snapshot · next 360 days · margin 35% · returns 5% · spending share 50% of CLV'), fontsize=10)
    axes[0].barh(labels, totals['customers'], color=BLUE, height=0.6)
    y = np.arange(len(labels))
    axes[1].hlines(y, totals['lower'], totals['upper'], color=BLUE, linewidth=2)
    axes[1].plot(totals['lower'], y, 'o', color=BLUE, markersize=5)
    axes[1].plot(totals['upper'], y, '|', color=BLUE, markersize=8)
    axes[1].set_yticks(y, labels)
    for y, (_, row) in enumerate(totals.iterrows()):
        axes[0].text(row['customers'] + 25, y, number(row['customers']), va='center')
        axes[1].text(row['upper'] + 7, y, '£' + number(row['lower'], language=language) + ' - £' + number(row['upper'], language=language), va='center', fontsize=9)
    axes[0].set_xlim(0, totals['customers'].max() * 1.2)
    axes[1].set_xlim(0, totals['upper'].max() * 1.38)
    axes[0].set_title(t('Segment size'), loc='left', pad=15)
    axes[1].set_title(t('Median CAC scenario range, £/customer'), loc='left', pad=15, fontsize=12)
    axes[0].set_xlabel(t('Customers'))
    axes[1].set_xlabel(t('£ per customer'))
    for ax in axes:
        ax.xaxis.grid(True, color='#E9EDF0')
        ax.set_axisbelow(True)
    fig.text(0.04, 0.02, t('Scenario range from observed bias · recommend the lower bound · not a confidence interval'), fontsize=9)
    fig.subplots_adjust(top=0.76, bottom=0.18, left=0.22, right=0.98, wspace=0.18)
    save(fig, 'segments.png', language)


def distribution_figure(customers, language):
    t = lambda text: translate(text, language)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle(t('Future contribution: distribution and concentration'), x=0.05, ha='left', fontsize=17, fontweight='bold')
    subtitle = t('{customers} UK customers · forecast contribution over 360 days · base profit assumptions')
    fig.text(0.05, 0.88, subtitle.format(customers=number(len(customers))), fontsize=11)
    values = customers['contribution_clv']
    axes[0].hist(np.log10(1 + values), bins=30, color=BLUE, edgecolor='white', linewidth=0.4)
    ticks = [0, 10, 100, 1000, 10000, 100000]
    axes[0].set_xticks(np.log10(1 + np.array(ticks)), [number(value) for value in ticks])
    axes[0].set_xlabel(t('CLV, £ · log10(1 + CLV) scale'))
    axes[0].set_ylabel(t('Customers'))
    ordered = values.sort_values(ascending=False).to_numpy()
    share = np.arange(1, len(ordered) + 1) / len(ordered)
    cumulative = ordered.cumsum() / ordered.sum()
    axes[1].plot(np.r_[0, share], np.r_[0, cumulative], color=BLUE, linewidth=2)
    axes[1].plot([0, 1], [0, 1], color=GREY, linestyle='--', linewidth=1, label=t('Uniform distribution'))
    axes[1].set_xlabel(t('Customer share, from high to low CLV'))
    axes[1].set_ylabel(t('Cumulative share of forecast CLV'))
    axes[1].xaxis.set_major_formatter(FuncFormatter(lambda value, _: number(value * 100, language=language) + '%'))
    axes[1].yaxis.set_major_formatter(FuncFormatter(lambda value, _: number(value * 100, language=language) + '%'))
    axes[1].set_xlim(0, 1)
    axes[1].set_ylim(0, 1)
    axes[1].legend(frameon=False, fontsize=9, loc='lower right')
    for ax in axes:
        ax.yaxis.grid(True, color='#E9EDF0')
        ax.set_axisbelow(True)
    fig.subplots_adjust(top=0.77, bottom=0.18, left=0.08, right=0.98, wspace=0.30)
    save(fig, 'clv_distribution.png', language)


def backtests_figure(results, language):
    t = lambda text: translate(text, language)
    keys = list(results)
    y = np.arange(len(keys))
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.8))
    fig.suptitle(t('Revenue forecasts across three holdout windows'), x=0.04, ha='left', fontsize=18, fontweight='bold')
    fig.text(0.04, 0.90, t('Same model settings · known UK customers, including zero purchases · no holdout tuning'), fontsize=10)
    for offset, method, label, color in [(-0.23, 'model', 'Model', BLUE), (0, 'recent', 'Last 90 days', GOLD), (0.23, 'baseline', 'Full history', GREY)]:
        maes = [results[key][method]['revenue']['mae'] for key in keys]
        biases = [results[key][method]['revenue']['bias'] * 100 for key in keys]
        axes[0].barh(y + offset, maes, height=0.20, color=color, label=t(label))
        axes[1].barh(y + offset, biases, height=0.20, color=color)
    labels = [t(results[key]['window']['label']) + '\n' + t('{days} days').format(days=results[key]['window']['days']) for key in keys]
    axes[0].set_yticks(y, labels)
    axes[1].set_yticks(y, labels)
    axes[2].set_yticks(y, labels)
    axes[0].set_title(t('Revenue MAE per customer'), fontsize=11, loc='left')
    axes[0].set_xlim(0, 950)
    axes[1].set_title(t('Aggregate revenue bias, %'), fontsize=11, loc='left')
    axes[1].axvline(0, color='#202C38', linewidth=1)
    axes[1].set_xlim(-35, 155)
    axes[1].set_xticks([-25, 0, 50, 100, 150])
    axes[2].set_title(t('MAE difference vs 90 days, £'), fontsize=11, loc='left')
    for row, key in enumerate(keys):
        interval = results[key]['paired_bootstrap']['model_minus_recent']
        value, low, high = [interval[name] for name in ['difference', 'ci_low', 'ci_high']]
        axes[2].errorbar(value, row, xerr=[[value - low], [high - value]], fmt='o', color=BLUE, capsize=5, linewidth=2)
        axes[2].text(value, row + 0.23, '[' + number(low, 1, language) + ', ' + number(high, 1, language) + ']', fontsize=9, ha='center')
    axes[2].axvline(0, color=GREY, linestyle='--', linewidth=1)
    axes[2].set_xlim(-105, 85)
    for ax in axes:
        ax.set_ylim(-0.5, len(keys) - 0.35)
        ax.invert_yaxis()
        ax.xaxis.grid(True, color='#E9EDF0')
        ax.set_axisbelow(True)
    axes[0].legend(frameon=False, fontsize=9, loc='upper left', bbox_to_anchor=(0, 1.20), ncol=3)
    fig.text(0.04, 0.025, t('95% paired customer bootstrap CI · model minus 90 days · negative favours model'), fontsize=10)
    fig.subplots_adjust(top=0.73, bottom=0.15, left=0.11, right=0.98, wspace=0.50)
    save(fig, 'backtests.png', language)



def monthly_mae_figure(results, language):
    t = lambda text: translate(text, language)
    keys = list(results)
    y = np.arange(len(keys))
    fig, ax = plt.subplots(figsize=(10, 5.2))
    fig.suptitle(t('Revenue MAE per 30-day month'), x=0.04, ha='left', fontsize=18, fontweight='bold')
    fig.text(0.04, 0.90, t('Normalised window MAE = MAE × 30 / days · known customers · same model settings'), fontsize=10)
    for offset, method, label, color in [(-0.23, 'model', 'Model', BLUE), (0, 'recent', 'Last 90 days', GOLD), (0.23, 'baseline', 'Full history', GREY)]:
        values = [monthly_mae(results[key][method]['revenue']['mae'], results[key]['window']['days']) for key in keys]
        ax.barh(y + offset, values, height=0.20, color=color, label=t(label))
        for row, value in enumerate(values):
            ax.text(value + 2, row + offset, '£' + number(value, 2, language), va='center', fontsize=9)
    labels = [t(results[key]['window']['label']) + '\n' + t('{days} days').format(days=results[key]['window']['days']) for key in keys]
    ax.set_yticks(y, labels)
    ax.set_ylim(-0.5, len(keys) - 0.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 225)
    ax.set_xlabel(t('£ per customer / 30 days'))
    ax.xaxis.grid(True, color='#E9EDF0')
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=9, loc='upper left', bbox_to_anchor=(0, 1.17), ncol=3)
    fig.text(0.04, 0.025, t('Length rescaling does not remove differences in season, customer mix or training history.'), fontsize=9)
    fig.subplots_adjust(top=0.72, bottom=0.17, left=0.20, right=0.98)
    save(fig, 'monthly_mae.png', language)


def backtest_deciles_figure(results, language):
    t = lambda text: translate(text, language)
    data = pd.read_csv(DATA / 'backtests_deciles.csv')
    fig, axes = plt.subplots(3, 2, figsize=(12, 11), sharey='row')
    fig.suptitle(t('Decile calibration across holdout windows'), x=0.05, ha='left', fontsize=18, fontweight='bold')
    fig.text(0.05, 0.94, t('Each method uses its own forecast deciles · actual and predicted mean revenue, £/customer'), fontsize=10)
    for row, (key, values) in enumerate(results.items()):
        window_groups = data.loc[data['window'].eq(key) & data['method'].isin(['model', 'recent'])]
        upper = window_groups[['actual_revenue', 'predicted_revenue']].div(window_groups['customers'], axis=0).max().max()
        for column, method, label, color in [(0, 'model', 'Model', BLUE), (1, 'recent', 'Last 90 days', GOLD)]:
            ax = axes[row, column]
            groups = data.loc[data['window'].eq(key) & data['method'].eq(method)]
            for name, legend, line_color, dash in [('actual_revenue', 'Actual', '#202C38', '-'), ('predicted_revenue', 'Forecast', color, '--')]:
                ax.plot(groups['decile'], groups[name] / groups['customers'], color=line_color, linestyle=dash, marker='o', linewidth=1.8, markersize=4, label=t(legend))
            ax.set_title(t(values['window']['label']) + ' · ' + t(label), fontsize=12, loc='left')
            ax.set_xticks(range(1, 11))
            ax.set_ylim(0, upper * 1.08)
            ax.tick_params(labelleft=True)
            ax.yaxis.grid(True, color='#E9EDF0')
            ax.set_ylabel(t('Mean revenue per customer, £'))
            ax.legend(frameon=False, fontsize=9, loc='upper left')
    for ax in axes[-1]:
        ax.set_xlabel(t('Forecast decile: 10 = high'))
    fig.subplots_adjust(top=0.89, bottom=0.07, left=0.10, right=0.97, hspace=0.40, wspace=0.28)
    save(fig, 'backtest_deciles.png', language)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create chart images / Crea le immagini dei grafici')
    parser.add_argument('--language', choices=['en', 'it', 'both'], default='both')
    args = parser.parse_args()
    metrics = json.loads((DATA / 'metrics.json').read_text(encoding='utf-8'))
    backtests = json.loads((DATA / 'backtests_metrics.json').read_text(encoding='utf-8'))
    customers = pd.read_csv(DATA / 'customers.csv')
    languages = ['en', 'it'] if args.language == 'both' else [args.language]
    for language in languages:
        backtests_figure(backtests, language)
        monthly_mae_figure(backtests, language)
        backtest_deciles_figure(backtests, language)
        validation_figure(metrics, language)
        retention_figure(language)
        segment_figure(customers, language)
        distribution_figure(customers, language)
        print(translate('Figures saved: {folder}', language).format(folder=OUTPUT / language))
