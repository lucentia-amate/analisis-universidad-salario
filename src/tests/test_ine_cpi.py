import pandas as pd
import pytest

from etl import ine_cpi


def payload(start_year=2007, end_year=2010, step=0.5):
    data, v = [], 100.0
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            data.append({"Anyo": y, "FK_Periodo": m, "Valor": v})
            v += step
    return {"Data": data}


def test_rebase_makes_base_year_average_100():
    monthly = ine_cpi.rebase_monthly(ine_cpi.parse_monthly(payload()), 2008)
    assert monthly.loc[monthly["year"] == 2008, "cpi"].mean() == pytest.approx(100)


def test_yearly_drops_incomplete_years_and_computes_inflation():
    p = payload(2007, 2009)
    p["Data"] = p["Data"][:-3]  # 2009 incomplete
    monthly = ine_cpi.rebase_monthly(ine_cpi.parse_monthly(p), 2008)
    yearly = ine_cpi.yearly_from_monthly(monthly, 2008)
    assert list(yearly["year"]) == [2008]
    assert yearly["cpi_avg"].iloc[0] == pytest.approx(100)
    assert yearly["inflation_avg_pct"].iloc[0] == pytest.approx(
        (yearly["cpi_avg"].iloc[0] / (monthly[monthly["year"] == 2007]["cpi"].mean()) - 1) * 100
    )


def test_provisional_december_is_added_for_an_unfinished_year_and_flagged():
    p = payload(2007, 2009)
    p["Data"] = p["Data"][:-3]  # 2009 incomplete
    monthly = ine_cpi.rebase_monthly(ine_cpi.parse_monthly(p), 2008)
    yearly = ine_cpi.yearly_from_monthly(monthly, 2008, provisional={2009: 4.9})
    assert list(yearly["year"]) == [2008, 2009]
    assert list(yearly["provisional"]) == [False, True]
    assert yearly["cpi_dec"].iloc[1] == pytest.approx(yearly["cpi_dec"].iloc[0] * 1.049)
    assert yearly["inflation_dec_pct"].iloc[1] == 4.9
    assert pd.isna(yearly["cpi_avg"].iloc[1])


def test_provisional_value_is_ignored_once_the_year_is_complete():
    monthly = ine_cpi.rebase_monthly(ine_cpi.parse_monthly(payload(2007, 2009)), 2008)
    yearly = ine_cpi.yearly_from_monthly(monthly, 2008, provisional={2009: 4.9})
    assert not yearly["provisional"].any()
    assert yearly["inflation_dec_pct"].iloc[-1] != 4.9


def test_rebase_requires_full_base_year():
    p = payload(2008, 2008)
    p["Data"] = p["Data"][:6]
    with pytest.raises(ValueError):
        ine_cpi.rebase_monthly(ine_cpi.parse_monthly(p), 2008)


def test_parse_ignores_missing_values():
    p = payload(2008, 2008)
    p["Data"][0]["Valor"] = None
    assert len(ine_cpi.parse_monthly(p)) == 11