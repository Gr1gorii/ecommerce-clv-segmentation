from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def test_switching_language_keeps_the_selected_portfolio():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
    app.selectbox(key="portfolio_segment").set_value("High-value dormant").run()
    app.slider(key="margin").set_value(40).run()
    app.slider(key="reserve").set_value(60).run()
    app.number_input(key="annual_discount").set_value(20.0).run()
    english = app.dataframe[0].value.copy()
    app.selectbox(key="language").set_value("Italiano").run()
    italian = app.dataframe[0].value

    assert not app.exception
    assert app.title[0].value == "CLV e budget per cliente"
    assert app.metric[0].value == "104"
    assert app.selectbox(key="portfolio_segment").value == "High-value dormant"
    assert italian.iloc[0]["Segmento"] == "Dormienti ad alto valore"
    assert app.slider(key="margin").value == 40
    assert app.slider(key="reserve").value == 60
    assert app.number_input(key="annual_discount").value == 20.0
    pd.testing.assert_frame_equal(
        english.iloc[:, 1:5].set_axis(range(4), axis=1),
        italian.iloc[:, 1:5].set_axis(range(4), axis=1),
    )


def test_all_pages_render_in_both_languages():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
    pages = ["Portfolio", "Retention and RFM", "Model validation", "Campaign budget", "Data and method"]
    for language in ["English", "Italiano"]:
        app.selectbox(key="language").set_value(language).run()
        for page in pages:
            app.radio(key="page").set_value(page).run()
            assert not app.exception, (language, page)
            assert app.title
            assert app.radio(key="page").value == page


def test_backtest_window_selection_in_both_languages():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
    app.radio(key="page").set_value("Model validation").run()
    for language in ["English", "Italiano"]:
        app.selectbox(key="language").set_value(language).run()
        for window, mae in [("original", "£564"), ("seasonal_2010", "£568"), ("non_peak_2011", "£301")]:
            app.selectbox(key="validation_window").set_value(window).run()
            assert not app.exception
            assert app.metric[0].value == mae
            overview = app.dataframe[0].value
            days_column = 'Days' if language == 'English' else 'Giorni'
            monthly_column = 'MAE per 30 days, £/customer' if language == 'English' else 'MAE per 30 giorni, £/cliente'
            assert overview[days_column].tolist() == [183] * 3 + [122] * 3 + [92] * 3
            assert overview[monthly_column].iloc[[0, 3, 6]].tolist() == [92.47, 139.71, 98.09]
            days = {'original': 183, 'seasonal_2010': 122, 'non_peak_2011': 92}[window]
            assert str(days) in app.metric[0].label
            assert len(overview) == 9
            assert len(app.dataframe[1].value) == 3
            assert len(app.dataframe[2].value) == 2


def test_discount_control_updates_the_budget():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=15).run()
    initial = app.dataframe[0].value['Segment CLV, £'].sum()
    app.number_input(key="annual_discount").set_value(20.0).run()
    assert app.dataframe[0].value['Segment CLV, £'].sum() < initial
    app.slider(key="margin").set_value(0).run()
    assert app.dataframe[0].value['Segment CLV, £'].sum() == 0
    app.radio(key="page").set_value("Campaign budget").run()
    app.slider(key="margin").set_value(0).run()
    assert not app.exception


def test_cac_bounds_follow_filters_and_language():
    app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=15).run()
    app.selectbox(key='portfolio_segment').set_value('High-value dormant').run()
    assert app.metric[3].value == '£223.16 - £379.34'
    initial = app.dataframe[0].value['Conservative CAC, £'].iloc[0]
    app.number_input(key='annual_discount').set_value(20.0).run()
    assert app.dataframe[0].value['Conservative CAC, £'].iloc[0] < initial
    app.selectbox(key='language').set_value('Italiano').run()
    assert not app.exception
    assert 'Intervallo CAC mediano' in app.metric[3].label
    assert 'CAC prudente, £' in app.dataframe[0].value.columns
    app.slider(key='margin').set_value(0).run()
    assert app.metric[3].value == '£0,00 - £0,00'
