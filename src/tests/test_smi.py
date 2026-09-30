import pytest

from etl import smi

HEADER = ["Fecha", "Normativa", "", "", "Día", "Mes", "Año", "Incremento"]


def row(date, monthly, annual=None):
    return [date, "R.D. ", "1/2000", "", monthly / 30, monthly, monthly * 14 if annual is None else annual, 1.0]


def test_parse_date_reads_roman_month():
    assert smi.parse_date("14-II-2023") == (2023, 2, 14)
    assert smi.parse_date("1-VII-2004") == (2004, 7, 1)
    assert smi.parse_date("(1) Los datos hasta 1998") is None
    assert smi.parse_date("") is None


def test_parse_sheet_keeps_last_change_of_each_year():
    rows = [
        HEADER,
        row("1-I-2008", 600.0),
        row("1-I-2009", 624.0),
        row("1-VII-2009", 630.0),
        ["(1) nota", "", "", "", "", "", "", ""],
    ]
    assert smi.parse_sheet(rows, 2008) == {2008: 600.0, 2009: 630.0}


def test_parse_sheet_skips_rows_before_first_year():
    rows = [HEADER, row("1-I-1991", 320.04, annual=4477.54), row("1-I-2008", 600.0)]
    assert smi.parse_sheet(rows, 2008) == {2008: 600.0}


def test_parse_sheet_rejects_shifted_columns():
    rows = [HEADER, row("1-I-2008", 600.0, annual=9999.0)]
    with pytest.raises(ValueError):
        smi.parse_sheet(rows, 2008)


def test_parse_sheet_requires_header():
    with pytest.raises(ValueError):
        smi.parse_sheet([row("1-I-2008", 600.0)], 2008)


def test_build_smi_carries_forward_years_without_a_new_decree():
    rows = [HEADER, row("1-I-2008", 600.0), row("1-I-2010", 633.3)]
    out = smi.build_smi(rows, first_year=2008)
    assert out["anyo"] == [2008, 2009, 2010]
    assert out["SMI"] == [600.0, 600.0, 633.3]


def test_build_smi_requires_a_value_for_the_first_year():
    with pytest.raises(ValueError):
        smi.build_smi([HEADER, row("1-I-2010", 633.3)], first_year=2008)
