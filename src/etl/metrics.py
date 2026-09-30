"""Comparison metrics between salary series and the CPI."""

import numpy as np
import pandas as pd


def rebase_cpi(cpi_yearly: pd.DataFrame, base_year: int) -> pd.DataFrame:
    """December CPI with December of `base_year` = 100 (cumulative change matches INE's Dec/Dec calculator)."""
    cpi = cpi_yearly[["year", "cpi_dec", "inflation_dec_pct"]].copy()
    base = cpi.loc[cpi["year"] == base_year, "cpi_dec"]
    if base.empty:
        raise ValueError(f"No CPI for base year {base_year}")
    cpi["cpi"] = cpi["cpi_dec"] / base.iloc[0] * 100
    return cpi[["year", "cpi", "inflation_dec_pct"]]


def _one_series(g: pd.DataFrame, years: range, interpolate: bool) -> pd.DataFrame:
    s = g.set_index("year")["annual_eur"].reindex(years).astype(float)
    filled = s.interpolate(method="linear", limit_area="inside") if interpolate else s
    return pd.DataFrame(
        {
            "year": list(years),
            "annual_eur": filled.to_numpy(),
            "interpolated": (s.isna() & filled.notna()).to_numpy(),
        }
    )


def compare(
    salaries: pd.DataFrame,
    cpi_yearly: pd.DataFrame,
    series_ids: list[str],
    base_year: int,
    interpolate: bool = False,
) -> pd.DataFrame:
    """Long table (year x series) with index, real-terms and gap metrics against the CPI.

    Every series is indexed to its own value in `base_year` (= 100); the CPI is rebased to the
    same year, so index lines are directly comparable.
    """
    cpi = rebase_cpi(cpi_yearly, base_year)
    years = range(int(cpi["year"].min()), int(cpi["year"].max()) + 1)

    frames = []
    for sid in series_ids:
        g = salaries[salaries["series_id"] == sid]
        f = _one_series(g, years, interpolate)
        f["series_id"] = sid
        base = f.loc[f["year"] == base_year, "annual_eur"].iloc[0]
        f["salary_index"] = f["annual_eur"] / base * 100 if pd.notna(base) else np.nan
        f["yoy_pct"] = f["annual_eur"].pct_change(fill_method=None) * 100
        frames.append(f)

    out = pd.concat(frames, ignore_index=True).merge(cpi, on="year", how="left")
    out["real_annual_eur"] = out["annual_eur"] / (out["cpi"] / 100)
    out["real_index"] = out["salary_index"] / out["cpi"] * 100
    out["gap_pts"] = out["salary_index"] - out["cpi"]
    return out


def summarize(cmp: pd.DataFrame, cpi_yearly: pd.DataFrame, start: int, end: int) -> pd.DataFrame:
    """Nominal vs CPI vs real change between the first and last year with data in [start, end]."""
    cpi = cpi_yearly.set_index("year")["cpi_dec"]
    rows = []
    for sid, g in cmp[(cmp["year"] >= start) & (cmp["year"] <= end)].groupby("series_id"):
        valid = g.dropna(subset=["annual_eur"])
        if len(valid) < 2:
            continue
        first, last = valid.iloc[0], valid.iloc[-1]
        nominal = last["annual_eur"] / first["annual_eur"] - 1
        inflation = cpi[int(last["year"])] / cpi[int(first["year"])] - 1
        rows.append(
            {
                "series_id": sid,
                "from_year": int(first["year"]),
                "to_year": int(last["year"]),
                "first_annual_eur": first["annual_eur"],
                "last_annual_eur": last["annual_eur"],
                "nominal_pct": nominal * 100,
                "cpi_pct": inflation * 100,
                "real_pct": ((1 + nominal) / (1 + inflation) - 1) * 100,
            }
        )
    return pd.DataFrame(rows)
