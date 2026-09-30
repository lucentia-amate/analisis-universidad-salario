"""IRPF brackets for Comunidad Valenciana (datosmacro.com) and the net-salary calculation.

Run: `python -m etl.irpf` to download the brackets of FIRST_YEAR..LAST_YEAR into data/irpf_valencia.csv
(2014-2024 from datosmacro; 2025 = provided regional scale + the 2024 state scale, which did not change;
2026 = full scale provided).

Model: taxable base = max(gross - personal_allowance(year), 0), taxed progressively with the "Tipo total"
(state + regional) bracket rates of that year. Social security contributions are NOT deducted.
"""

import logging
import re

import pandas as pd
import requests

from etl.config import IRPF_CSV

log = logging.getLogger(__name__)

PAGE_URL = "https://datosmacro.expansion.com/impuestos/impuesto-renta-trabajadores/espana-comunidades-autonomas/valencia"
HEADERS = {"User-Agent": "Mozilla/5.0"}
FIRST_YEAR, LAST_YEAR = 2014, 2026
DATAMACRO_LAST_YEAR = 2024
# EUR of gross income exempt from the tax base: (first year, amount) periods, each valid until the next starts.
ALLOWANCE_PERIODS = [(2008, 5151.0), (2015, 5550.0)]


def personal_allowance(year: int) -> float:
    """Exempt amount in force in `year` (2008-2014: 5.151 EUR, 2015 onwards: 5.550 EUR)."""
    amount = None
    for first_year, value in ALLOWANCE_PERIODS:
        if year >= first_year:
            amount = value
    if amount is None:
        raise ValueError(f"No personal allowance defined for {year}")
    return amount

# Full Valencian scale for 2026 (provided by the project owner):
# (taxable base from, state rate %, regional rate %, total rate %); each bracket ends where the next starts.
SCALE_2026 = [
    (0, 9.5, 8.8, 18.3),
    (12_000, 9.5, 11.7, 21.2),
    (12_450, 12.0, 11.7, 23.7),
    (20_200, 15.0, 11.7, 26.7),
    (22_000, 15.0, 14.6, 29.6),
    (32_000, 15.0, 17.0, 32.0),
    (35_200, 18.5, 17.0, 35.5),
    (42_000, 18.5, 19.4, 37.9),
    (52_000, 18.5, 21.9, 40.4),
    (60_000, 22.5, 21.9, 44.4),
    (62_000, 22.5, 24.4, 46.9),
    (72_000, 22.5, 26.1, 48.6),
    (100_000, 22.5, 27.35, 49.85),
    (150_000, 22.5, 28.35, 50.85),
    (200_000, 22.5, 29.35, 51.85),
    (300_000, 24.5, 29.35, 53.85),
]

# Valencian regional scale for 2025 (provided by the project owner; datosmacro has no 2025 page yet):
# (taxable base from, cumulative regional tax at that point, marginal rate %).
REGIONAL_2025 = [
    (0, 0.00, 9.0),
    (12_000, 1_080.00, 12.0),
    (22_000, 2_280.00, 15.0),
    (32_000, 3_780.00, 17.5),
    (42_000, 5_530.00, 20.0),
    (52_000, 7_530.00, 22.5),
    (62_000, 9_780.00, 25.0),
    (72_000, 12_280.00, 26.5),
    (100_000, 19_700.00, 27.5),
    (150_000, 33_450.00, 28.5),
    (200_000, 47_700.00, 29.5),
]

COLUMNS = ["year", "from_eur", "to_eur", "state_rate_pct", "regional_rate_pct", "total_rate_pct"]
TABLE = re.compile(r"<table[^>]*>.*?</table>", re.S)
ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL = re.compile(r'<td[^>]*data-value="([^"]*)"[^>]*>')


def parse_brackets(html: str, year: int) -> pd.DataFrame:
    """Bracket table of one datosmacro page: one row per bracket, `to_eur` NaN for the open-ended last one."""
    if f"Tramos de IRPF en Comunidad Valenciana {year}" not in html:
        raise ValueError(f"Page does not show the IRPF brackets for {year}")
    rows = []
    for table in TABLE.findall(html):
        if "Tipo total" not in table:
            continue
        for tr in ROW.findall(table):
            cells = CELL.findall(tr)
            if len(cells) != 5:
                continue
            lo, hi, state, regional, total = cells
            rows.append(
                {
                    "year": year,
                    "from_eur": float(lo),
                    "to_eur": float(hi) if hi else float("nan"),
                    "state_rate_pct": float(state),
                    "regional_rate_pct": float(regional),
                    "total_rate_pct": float(total),
                }
            )
        break
    if not rows:
        raise ValueError(f"No IRPF bracket table found for {year}")
    df = pd.DataFrame(rows, columns=COLUMNS)
    validate_brackets(df, year)
    return df


def validate_brackets(df: pd.DataFrame, year: int) -> None:
    """Brackets must start at 0, be contiguous, end open, and rates must add up."""
    if df["from_eur"].iloc[0] != 0:
        raise ValueError(f"{year}: first bracket does not start at 0")
    if not df["to_eur"].iloc[:-1].tolist() == df["from_eur"].iloc[1:].tolist():
        raise ValueError(f"{year}: brackets are not contiguous")
    if not pd.isna(df["to_eur"].iloc[-1]):
        raise ValueError(f"{year}: last bracket should be open-ended")
    gap = (df["state_rate_pct"] + df["regional_rate_pct"] - df["total_rate_pct"]).abs().max()
    if gap > 0.11:
        raise ValueError(f"{year}: state + regional rate differs from total rate")


def fetch_year(year: int) -> pd.DataFrame:
    resp = requests.get(PAGE_URL, params={"anio": year}, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return parse_brackets(resp.text, year)


def build_irpf(first_year: int = FIRST_YEAR, last_year: int = LAST_YEAR) -> pd.DataFrame:
    """Brackets for first_year..last_year: downloaded up to DATAMACRO_LAST_YEAR, provided scales afterwards."""
    if last_year > 2026:
        raise ValueError("No IRPF scale is available beyond 2026")
    df = pd.concat(
        [fetch_year(y) for y in range(first_year, min(last_year, DATAMACRO_LAST_YEAR) + 1)], ignore_index=True
    )
    extra = []
    if last_year >= 2025:
        extra.append(combine_2025(df[df["year"] == DATAMACRO_LAST_YEAR]))
    if last_year >= 2026:
        extra.append(scale_2026())
    return pd.concat([df, *extra], ignore_index=True)


def scale_2026() -> pd.DataFrame:
    starts = [row[0] for row in SCALE_2026]
    rows = [
        {
            "year": 2026,
            "from_eur": float(lo),
            "to_eur": float(hi) if hi is not None else float("nan"),
            "state_rate_pct": state,
            "regional_rate_pct": regional,
            "total_rate_pct": total,
        }
        for (lo, state, regional, total), hi in zip(SCALE_2026, starts[1:] + [None])
    ]
    out = pd.DataFrame(rows, columns=COLUMNS)
    validate_brackets(out, 2026)
    return out


def combine_2025(state_year: pd.DataFrame) -> pd.DataFrame:
    """2025 brackets: the regional scale above plus the state scale of `state_year` (unchanged since 2021)."""
    cumulative = 0.0
    for (lo, quota, rate), nxt in zip(REGIONAL_2025, REGIONAL_2025[1:] + [None]):
        if abs(cumulative - quota) > 0.005:
            raise ValueError(f"2025 regional scale: cumulative tax at {lo} is {cumulative}, expected {quota}")
        if nxt:
            cumulative += (nxt[0] - lo) * rate / 100

    state = state_year.sort_values("from_eur")
    starts = sorted({float(lo) for lo, _, _ in REGIONAL_2025} | set(state["from_eur"]))
    rows = []
    for lo, hi in zip(starts, starts[1:] + [float("nan")]):
        state_rate = state.loc[state["from_eur"] <= lo, "state_rate_pct"].iloc[-1]
        regional_rate = [r for start, _, r in REGIONAL_2025 if start <= lo][-1]
        rows.append(
            {
                "year": 2025,
                "from_eur": lo,
                "to_eur": hi,
                "state_rate_pct": state_rate,
                "regional_rate_pct": regional_rate,
                "total_rate_pct": state_rate + regional_rate,
            }
        )
    out = pd.DataFrame(rows, columns=COLUMNS)
    validate_brackets(out, 2025)
    return out


def load_irpf(path=IRPF_CSV) -> pd.DataFrame:
    return pd.read_csv(path)


def net_annual(gross: float, brackets: pd.DataFrame, allowance: float) -> float:
    """Gross annual salary minus progressive IRPF on (gross - allowance) using one year's brackets."""
    if pd.isna(gross):
        return float("nan")
    base = max(gross - allowance, 0.0)
    tax = 0.0
    for b in brackets.itertuples():
        upper = b.to_eur if not pd.isna(b.to_eur) else float("inf")
        if base <= b.from_eur:
            break
        tax += (min(base, upper) - b.from_eur) * b.total_rate_pct / 100
    return gross - tax


def add_net_salary(salaries: pd.DataFrame, irpf: pd.DataFrame, exempt_series: frozenset | set = frozenset()) -> pd.DataFrame:
    """Copy of `salaries` with `net_annual_eur`; NaN for years without bracket data.

    Series in `exempt_series` (e.g. the SMI) pay no IRPF, so their net amount equals the gross one.
    """
    by_year = {y: g.sort_values("from_eur") for y, g in irpf.groupby("year")}
    out = salaries.copy()
    out["net_annual_eur"] = [
        float("nan")
        if y not in by_year
        else g
        if sid in exempt_series
        else net_annual(g, by_year[y], personal_allowance(y))
        for y, sid, g in zip(out["year"], out["series_id"], out["annual_eur"])
    ]
    return out


def main() -> None:
    df = build_irpf()
    df.to_csv(IRPF_CSV, index=False)
    log.info("Written %s (%s-%s, %d rows)", IRPF_CSV, FIRST_YEAR, LAST_YEAR, len(df))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    main()
