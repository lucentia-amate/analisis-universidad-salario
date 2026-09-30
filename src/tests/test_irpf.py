import pandas as pd
import pytest

from etl import irpf


def cell(v, text=""):
    return f'<td class="numero" data-value="{v}">{text}</td>'


def html(year, rows):
    body = "".join("<tr>" + "".join(cell(v) for v in r) + "</tr>" for r in rows)
    return (
        f"<h2>Tramos de IRPF en Comunidad Valenciana {year}</h2>"
        "<table><thead><tr><th>Base liquidable desde</th><th>Tipo total</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


ROWS_2014 = [
    (0, 17707, 12.8, 11.9, 24.7),
    (17707, 33007, 16, 13.9, 29.9),
    (33007, 53407, 21.5, 18.5, 40),
    (53407, "", 25, 22, 47),
]


def test_parse_brackets_reads_data_values_and_open_last_bracket():
    df = irpf.parse_brackets(html(2014, ROWS_2014), 2014)
    assert list(df.columns) == irpf.COLUMNS
    assert df["from_eur"].tolist() == [0, 17707, 33007, 53407]
    assert df["total_rate_pct"].tolist() == [24.7, 29.9, 40, 47]
    assert pd.isna(df["to_eur"].iloc[-1]) and df["to_eur"].iloc[0] == 17707


def test_parse_brackets_rejects_other_year_and_gaps():
    with pytest.raises(ValueError):
        irpf.parse_brackets(html(2015, ROWS_2014), 2014)
    gap = [ROWS_2014[0], (18000, "", 16, 13.9, 29.9)]
    with pytest.raises(ValueError):
        irpf.parse_brackets(html(2014, gap), 2014)


@pytest.fixture
def brackets_2014():
    return irpf.parse_brackets(html(2014, ROWS_2014), 2014)


def test_personal_allowance_depends_on_the_period():
    assert [irpf.personal_allowance(y) for y in (2008, 2014)] == [5151.0, 5151.0]
    assert [irpf.personal_allowance(y) for y in (2015, 2026)] == [5550.0, 5550.0]
    with pytest.raises(ValueError):
        irpf.personal_allowance(2007)


def test_net_annual_is_progressive_after_the_exempt_amount(brackets_2014):
    allowance = 5151.0
    # base 14.500 -> all in the first bracket
    assert irpf.net_annual(14500 + allowance, brackets_2014, allowance) == pytest.approx(
        14500 + allowance - 14500 * 0.247
    )
    # base 34.500 -> three brackets
    tax = 17707 * 0.247 + (33007 - 17707) * 0.299 + (34500 - 33007) * 0.40
    assert irpf.net_annual(34500 + allowance, brackets_2014, allowance) == pytest.approx(34500 + allowance - tax)


def test_net_annual_below_the_exempt_amount_pays_nothing(brackets_2014):
    assert irpf.net_annual(5000, brackets_2014, 5151.0) == 5000
    assert irpf.net_annual(5550.0, brackets_2014, 5550.0) == 5550.0
    assert pd.isna(irpf.net_annual(float("nan"), brackets_2014, 5151.0))


def test_net_annual_reaches_the_open_ended_bracket(brackets_2014):
    base, allowance = 100000, 5151.0
    tax = (
        17707 * 0.247
        + (33007 - 17707) * 0.299
        + (53407 - 33007) * 0.40
        + (base - 53407) * 0.47
    )
    assert irpf.net_annual(base + allowance, brackets_2014, allowance) == pytest.approx(base + allowance - tax)


def test_add_net_salary_leaves_years_without_brackets_blank(brackets_2014):
    sal = pd.DataFrame({"year": [2013, 2014, 2025], "series_id": "x", "annual_eur": [20000.0, 20000.0, 20000.0]})
    out = irpf.add_net_salary(sal, brackets_2014)
    assert pd.isna(out.loc[0, "net_annual_eur"]) and pd.isna(out.loc[2, "net_annual_eur"])
    assert out.loc[1, "net_annual_eur"] == pytest.approx(20000 - (20000 - 5151) * 0.247)


def test_add_net_salary_uses_the_allowance_of_each_year():
    irpf_flat = pd.DataFrame(
        {
            "year": [2014, 2015],
            "from_eur": [0.0, 0.0],
            "to_eur": [float("nan")] * 2,
            "state_rate_pct": [10.0, 10.0],
            "regional_rate_pct": [10.0, 10.0],
            "total_rate_pct": [20.0, 20.0],
        }
    )
    sal = pd.DataFrame({"year": [2014, 2015], "series_id": "x", "annual_eur": [20000.0, 20000.0]})
    out = irpf.add_net_salary(sal, irpf_flat)
    assert out.loc[0, "net_annual_eur"] == pytest.approx(20000 - (20000 - 5151) * 0.2)
    assert out.loc[1, "net_annual_eur"] == pytest.approx(20000 - (20000 - 5550) * 0.2)


def test_add_net_salary_leaves_exempt_series_untaxed(brackets_2014):
    sal = pd.DataFrame(
        {"year": [2013, 2014, 2014], "series_id": ["smi", "smi", "x"], "annual_eur": [20000.0] * 3}
    )
    out = irpf.add_net_salary(sal, brackets_2014, {"smi"})
    assert pd.isna(out.loc[0, "net_annual_eur"])  # still no brackets for 2013
    assert out.loc[1, "net_annual_eur"] == 20000
    assert out.loc[2, "net_annual_eur"] == pytest.approx(20000 - (20000 - 5151) * 0.247)


def test_combine_2025_adds_the_regional_scale_to_the_state_scale():
    state_2024 = irpf.load_irpf().query("year == 2024")
    b = irpf.combine_2025(state_2024)
    assert (b["year"] == 2025).all()
    assert b["from_eur"].iloc[0] == 0 and b["to_eur"].iloc[0] == 12000
    assert b["total_rate_pct"].iloc[0] == 18.5  # 9,5 state + 9,0 regional
    row = lambda x: b[b["from_eur"] <= x].iloc[-1]
    assert row(13000).total_rate_pct == pytest.approx(12.0 + 12.0)
    assert row(23000).total_rate_pct == pytest.approx(15.0 + 15.0)
    assert row(70000).total_rate_pct == pytest.approx(22.5 + 25.0)
    assert row(250000).total_rate_pct == pytest.approx(22.5 + 29.5)
    assert row(400000).total_rate_pct == pytest.approx(24.5 + 29.5)
    # the regional part alone reproduces the provided cumulative tax at 200.000
    regional_tax = sum((min(200000, hi) - lo) * r / 100 for lo, hi, r in zip(b.from_eur, b.to_eur.fillna(1e12), b.regional_rate_pct) if lo < 200000)
    assert regional_tax == pytest.approx(47700)


def test_combine_2025_rejects_an_inconsistent_regional_table(monkeypatch):
    bad = [(0, 0.0, 9.0), (12_000, 1_000.0, 12.0)]
    monkeypatch.setattr(irpf, "REGIONAL_2025", bad)
    with pytest.raises(ValueError):
        irpf.combine_2025(irpf.load_irpf().query("year == 2024"))


def test_scale_2026_is_the_provided_table():
    b = irpf.scale_2026()
    assert len(b) == 16 and (b["year"] == 2026).all()
    assert b["from_eur"].tolist()[:3] == [0, 12000, 12450] and pd.isna(b["to_eur"].iloc[-1])
    assert b["total_rate_pct"].tolist()[0] == 18.3 and b["total_rate_pct"].tolist()[-1] == 53.85
    # 40.050 EUR gross - 5.550 exempt -> base 34.500 spans the first six brackets
    tax = 12000 * 0.183 + 450 * 0.212 + 7750 * 0.237 + 1800 * 0.267 + 10000 * 0.296 + 2500 * 0.32
    assert irpf.net_annual(40050, b, irpf.personal_allowance(2026)) == pytest.approx(40050 - tax)


def test_committed_brackets_cover_2014_to_2026_and_match_datosmacro_2014():
    df = irpf.load_irpf()
    assert sorted(df["year"].unique()) == list(range(2014, 2027))
    first = df[df["year"] == 2014].sort_values("from_eur").iloc[:2]
    assert first["to_eur"].tolist() == [17707, 33007]
    assert first["total_rate_pct"].tolist() == [24.7, 29.9]
    for year, g in df.groupby("year"):
        irpf.validate_brackets(g.sort_values("from_eur").reset_index(drop=True), year)
