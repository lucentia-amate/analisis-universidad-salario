import json

import pandas as pd
import pytest

from etl import salaries


def test_lenient_json_reads_empty_slots_as_null(tmp_path):
    f = tmp_path / "x.json"
    f.write_text('{"anyo": [1, 2, 3, 4], "v": [1.5,,,4.5]}')
    assert salaries.read_lenient_json(f) == {"anyo": [1, 2, 3, 4], "v": [1.5, None, None, 4.5]}


def test_titular_file_is_parsed_with_gaps():
    t = salaries.load_titular()
    assert t["values"]["2008"] == 2424.21
    assert t["values"]["2015"] is None and t["values"]["2016"] is None
    assert t["values"]["2012"] == 2361.96
    assert t["values"]["2024"] == 2839.49
    assert t["values"]["2025"] == 2924.74
    assert len(t["values"]) == 19
    assert t["source_urls"] and t["source_urls"][0].startswith("https://www.usal.es/")
    assert any("sgp.ua.es" in u for u in t["source_urls"])  # Alicante tables behind the annual factor
    assert t["payments_per_year"] == pytest.approx(13.6404, abs=1e-3)


def test_catedratico_file_is_parsed_with_gaps():
    c = salaries.load_catedratico()
    assert c["id"] == "catedratico_universidad" and c["category"] == "academic"
    assert c["values"]["2008"] == 3037.15
    assert c["values"]["2015"] is None and c["values"]["2016"] is None
    assert c["values"]["2012"] == 2957.69
    assert c["values"]["2025"] == 3658.89
    assert len(c["values"]) == 19
    assert c["source_urls"] and c["source_urls"][0].startswith("https://www.usal.es/")
    assert c["payments_per_year"] == pytest.approx(13.7127, abs=1e-3)


def test_pdi_factors_reproduce_alicante_total_anual():
    f = salaries.load_pdi_factors()
    # 2026 monthly total x factor ~ published "Total anual"
    assert 3699.56 * f["CatedraticoUniversidad"]["factor"] == pytest.approx(50731.46, abs=1)
    assert 2954.41 * f["TitularUniversidad"]["factor"] == pytest.approx(40299.36, abs=1)
    assert 2910.74 * f["TitularUniversidad"]["factor"] == pytest.approx(39703.73, abs=1)
    assert set(f["TitularUniversidad"]["ratios"]) == {"2025", "2026"}


def test_pdi_factors_reject_unstable_ratios(tmp_path):
    p = tmp_path / "f.json"
    p.write_text(
        json.dumps(
            {
                "fuentes": {},
                "posiciones": {
                    "X": {
                        "2025": {"mensual": 100.0, "anual": 1400.0},
                        "2026": {"mensual": 100.0, "anual": 1370.0},
                    }
                },
            }
        )
    )
    with pytest.raises(ValueError):
        salaries.load_pdi_factors(p)


def test_smi_file_keeps_the_amount_in_force_at_year_end():
    s = salaries.load_smi()
    assert s["id"] == "smi" and s["category"] == "minimum_wage"
    assert s["values"]["2008"] == 600.0
    assert s["values"]["2012"] == 641.4  # prorogued: same as 2011
    assert s["values"]["2021"] == 965.0  # January 950 -> September 965
    assert s["values"]["2023"] == 1080.0
    assert list(s["values"]) == [str(y) for y in range(2008, 2027)]
    assert all(v is not None for v in s["values"].values())
    assert s["source_urls"] == ["https://www.mites.gob.es/estadisticas/bel/SMI/smi1_top_EXCEL.htm"]


def test_build_salaries_annualises_monthly_amounts(monkeypatch):
    monkeypatch.setattr(
        salaries,
        "load_catalog",
        lambda *a: (
            [
                {
                    "id": "fake_wage",
                    "label": "Fake wage",
                    "category": "minimum_wage",
                    "unit": "eur_monthly",
                    "payments_per_year": 14,
                    "values": {"2008": 600.0},
                },
                {
                    "id": "annual",
                    "label": "Annual",
                    "category": "general",
                    "unit": "eur_annual",
                    "payments_per_year": 1,
                    "values": {"2008": 20000.0},
                },
            ],
            [],
        ),
    )
    sal, meta = salaries.build_salaries()
    row = lambda sid, year=2008: sal[(sal.series_id == sid) & (sal.year == year)].iloc[0]
    assert row("fake_wage").annual_eur == 8400
    assert row("annual").annual_eur == 20000
    assert row("smi").annual_eur == 8400  # 600 EUR x 14 payments
    factors = salaries.load_pdi_factors()
    assert row("catedratico_universidad").annual_eur == pytest.approx(
        3037.15 * factors["CatedraticoUniversidad"]["factor"]
    )
    assert row("profesor_titular").annual_eur == pytest.approx(2424.21 * factors["TitularUniversidad"]["factor"])
    assert list(meta["series_id"]) == [
        "profesor_titular",
        "catedratico_universidad",
        "smi",
        "fake_wage",
        "annual",
    ]
    assert pd.isna(row("smi").net_annual_eur)  # 2008: no IRPF brackets
    assert pd.isna(row("profesor_titular", 2015).annual_eur)
    assert pd.isna(row("catedratico_universidad", 2015).annual_eur)


def test_build_salaries_adds_net_salary_only_where_irpf_brackets_exist():
    sal, _ = salaries.build_salaries()
    smi = sal[sal.series_id == "smi"].set_index("year")
    assert smi.loc[2013, "net_annual_eur"] != smi.loc[2013, "net_annual_eur"]  # NaN
    assert smi.loc[2025, "net_annual_eur"] == smi.loc[2025, "annual_eur"]
    assert smi.loc[2026, "net_annual_eur"] == smi.loc[2026, "annual_eur"]
    assert smi.loc[2013, "net_annual_eur"] != smi.loc[2013, "net_annual_eur"]  # NaN: before IRPF data
    # The SMI is exempt from IRPF: net equals gross (9.034,20 = 645,30 x 14 in 2014)
    assert smi.loc[2014, "annual_eur"] == pytest.approx(9034.2)
    assert smi.loc[2014, "net_annual_eur"] == smi.loc[2014, "annual_eur"]
    assert (smi.loc[2014:2026, "net_annual_eur"] == smi.loc[2014:2026, "annual_eur"]).all()
    titular = sal[sal.series_id == "profesor_titular"].set_index("year")
    assert titular.loc[2014, "net_annual_eur"] < titular.loc[2014, "annual_eur"]
    net = sal.dropna(subset=["net_annual_eur"])
    assert sorted(net["year"].unique()) == list(range(2014, 2027))
    taxed = net[net.series_id != "smi"]
    assert (taxed["net_annual_eur"] < taxed["annual_eur"]).all()


def test_committed_catalog_is_valid():
    series, _ = salaries.load_catalog()
    for s in series:
        years = sorted(int(y) for y in s["values"])
        assert years[0] == 2008, s["id"]
        assert years == list(range(2008, years[-1] + 1)), s["id"]
        assert years[-1] >= 2024, s["id"]
        assert all(v is not None for v in s["values"].values()), s["id"]