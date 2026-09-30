"""Download Spain's CPI from INE (Tempus API) and rebase it to 2008 = 100."""

import datetime as dt
import logging

import numpy as np
import pandas as pd
import requests

from etl.config import BASE_YEAR, CPI_MONTHLY_CSV, CPI_YEARLY_CSV, PROCESSED_DIR

log = logging.getLogger(__name__)

INE_API = "https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/{code}"
# National general index, base 2021 (INE table 50902). INE back-casts it to 2002.
CPI_SERIES_CODE = "IPC251852"
FIRST_YEAR = 2007  # one year before the base year, needed for 2008 Dec/Dec inflation
# Assumed December/December inflation (%) for years INE has not closed yet; replaced by the real value once published.
PROVISIONAL_DEC_INFLATION_PCT = {2026: 4.9}


def fetch_payload(code: str = CPI_SERIES_CODE, first_year: int = FIRST_YEAR) -> dict:
    last_year = dt.date.today().year
    resp = requests.get(
        INE_API.format(code=code),
        params={"date": f"{first_year}0101:{last_year}1231"},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def parse_monthly(payload: dict) -> pd.DataFrame:
    rows = [
        (int(d["Anyo"]), int(d["FK_Periodo"]), float(d["Valor"]))
        for d in payload["Data"]
        if d.get("Valor") is not None
    ]
    df = pd.DataFrame(rows, columns=["year", "month", "index_ine"])
    if df.empty or not df["month"].between(1, 12).all():
        raise ValueError("Unexpected INE payload: expected monthly observations")
    return df.sort_values(["year", "month"]).reset_index(drop=True)


def rebase_monthly(monthly: pd.DataFrame, base_year: int = BASE_YEAR) -> pd.DataFrame:
    """Rebase so the average of `base_year` equals 100 (INE's annual-average convention)."""
    base = monthly.loc[monthly["year"] == base_year, "index_ine"]
    if len(base) != 12:
        raise ValueError(f"Base year {base_year} needs 12 monthly observations, got {len(base)}")
    out = monthly.copy()
    out["cpi"] = out["index_ine"] / base.mean() * 100
    out["date"] = pd.to_datetime(dict(year=out["year"], month=out["month"], day=1))
    return out[["date", "year", "month", "index_ine", "cpi"]]


def yearly_from_monthly(
    monthly: pd.DataFrame, base_year: int = BASE_YEAR, provisional: dict[int, float] | None = None
) -> pd.DataFrame:
    """Annual CPI (average and December) plus inflation rates. Only complete years are kept.

    `provisional` maps a year to an assumed December/December inflation (%). It is used only when that year is
    not complete in the INE data, and the row is flagged `provisional`; the average CPI is left empty.
    """
    provisional = PROVISIONAL_DEC_INFLATION_PCT if provisional is None else provisional
    g = monthly.groupby("year")
    yearly = pd.DataFrame(
        {
            "cpi_avg": g["cpi"].mean(),
            "cpi_dec": g["cpi"].last(),
            "months": g["cpi"].count(),
        }
    )
    yearly = yearly[yearly["months"] == 12].drop(columns="months")
    yearly["inflation_avg_pct"] = yearly["cpi_avg"].pct_change(fill_method=None) * 100
    yearly["inflation_dec_pct"] = yearly["cpi_dec"].pct_change(fill_method=None) * 100
    yearly["provisional"] = False
    for year, pct in sorted(provisional.items()):
        if year in yearly.index or year - 1 not in yearly.index:
            continue
        yearly.loc[year] = {
            "cpi_avg": np.nan,
            "cpi_dec": yearly.at[year - 1, "cpi_dec"] * (1 + pct / 100),
            "inflation_avg_pct": np.nan,
            "inflation_dec_pct": pct,
            "provisional": True,
        }
    yearly["provisional"] = yearly["provisional"].astype(bool)
    return yearly[yearly.index >= base_year].reset_index()


def refresh() -> tuple[pd.DataFrame, pd.DataFrame]:
    monthly = rebase_monthly(parse_monthly(fetch_payload()))
    yearly = yearly_from_monthly(monthly)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    monthly[monthly["year"] >= BASE_YEAR].to_csv(CPI_MONTHLY_CSV, index=False)
    yearly.to_csv(CPI_YEARLY_CSV, index=False)
    log.info("CPI updated: %s complete years, last %s", len(yearly), yearly["year"].max())
    return monthly, yearly
