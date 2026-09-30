import pandas as pd
import pytest

from etl import metrics


@pytest.fixture
def cpi():
    return pd.DataFrame(
        {
            "year": [2008, 2009, 2010],
            "cpi_dec": [100.0, 101.0, 103.02],
            "inflation_dec_pct": [None, 1.0, 2.0],
        }
    )


@pytest.fixture
def sal():
    return pd.DataFrame(
        {
            "year": [2008, 2009, 2010, 2008, 2010],
            "series_id": ["a", "a", "a", "b", "b"],
            "annual_eur": [1000.0, 1010.0, 1030.2, 500.0, 600.0],
        }
    )


def test_rebase_to_other_year(cpi):
    out = metrics.rebase_cpi(cpi, 2009)
    assert out.loc[out.year == 2009, "cpi"].iloc[0] == pytest.approx(100)
    assert out.loc[out.year == 2008, "cpi"].iloc[0] == pytest.approx(100 / 1.01)


def test_salary_tracking_cpi_has_flat_real_index(cpi, sal):
    cmp = metrics.compare(sal, cpi, ["a"], 2008)
    assert cmp["real_index"].tolist() == pytest.approx([100, 100, 100], rel=1e-3)
    assert cmp["gap_pts"].abs().max() < 0.1


def test_gaps_stay_nan_unless_interpolated(cpi, sal):
    plain = metrics.compare(sal, cpi, ["b"], 2008).set_index("year")
    assert pd.isna(plain.loc[2009, "annual_eur"]) and not plain["interpolated"].any()
    filled = metrics.compare(sal, cpi, ["b"], 2008, interpolate=True).set_index("year")
    assert filled.loc[2009, "annual_eur"] == pytest.approx(550)
    assert filled["interpolated"].tolist() == [False, True, False]


def test_missing_base_year_gives_nan_index(cpi, sal):
    cmp = metrics.compare(sal, cpi, ["b"], 2009)
    assert cmp["salary_index"].isna().all()


def test_summary_real_change(cpi, sal):
    cmp = metrics.compare(sal, cpi, ["b"], 2008)
    s = metrics.summarize(cmp, cpi, 2008, 2010).iloc[0]
    assert (s.from_year, s.to_year) == (2008, 2010)
    assert s.nominal_pct == pytest.approx(20)
    assert s.cpi_pct == pytest.approx(3.02)
    assert s.real_pct == pytest.approx((1.2 / 1.0302 - 1) * 100)