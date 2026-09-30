import pandas as pd
import pytest

from etl import working_hours as wh


def _data():
    salaries = pd.DataFrame(
        {
            "year": [2025, 2026, 2025, 2026],
            "series_id": ["prof", "prof", "smi", "smi"],
            "annual_eur": [40000.0, 42000.0, 15000.0, 16000.0],
        }
    )
    meta = pd.DataFrame({"category": ["academic", "minimum_wage"]}, index=["prof", "smi"])
    return salaries, meta


def test_hours_factor_is_35_over_37_5():
    assert wh.hours_factor() == pytest.approx(35 / 37.5)


def test_penalty_applies_only_to_professors_from_2026():
    salaries, meta = _data()
    out = wh.apply_hours_penalty(salaries, meta)
    assert out["annual_eur"].tolist() == pytest.approx([40000.0, 42000.0 * 35 / 37.5, 15000.0, 16000.0])
    assert salaries["annual_eur"].tolist() == [40000.0, 42000.0, 15000.0, 16000.0]  # input untouched


def test_penalty_keeps_missing_values_missing():
    salaries, meta = _data()
    salaries.loc[1, "annual_eur"] = float("nan")
    assert pd.isna(wh.apply_hours_penalty(salaries, meta).loc[1, "annual_eur"])
