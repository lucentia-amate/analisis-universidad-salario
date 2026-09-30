"""Build SMI.json from the Ministry of Labour's "SMI-1" spreadsheet (Boletín de Estadísticas Laborales).

Run: `python -m etl.smi` (needs `xlrd`).

Value per year: the monthly SMI (paid 14 times) in force at year end, i.e. the last change of that year.
"""

import json
import logging
import re
import ssl

import certifi
import requests
import requests.adapters

from etl.config import BASE_YEAR, FNMT_CA_PEM, SMI_JSON

log = logging.getLogger(__name__)

PAGE_URL = "https://www.mites.gob.es/estadisticas/bel/SMI/smi1_top_EXCEL.htm"
XLS_URL = "https://www.mites.gob.es/estadisticas/bel/SMI/smi1.xls"
HEADERS = {"User-Agent": "Mozilla/5.0"}
PAYMENTS = 14

DATE = re.compile(r"^(\d{1,2})-([IVX]+)-(\d{4})$")
ROMAN_MONTHS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


def parse_date(text: str) -> tuple[int, int, int] | None:
    """'14-II-2023' -> (2023, 2, 14); None when the cell is not a date."""
    m = DATE.match(str(text).strip())
    if not m or m.group(2) not in ROMAN_MONTHS:
        return None
    return int(m.group(3)), ROMAN_MONTHS.index(m.group(2)) + 1, int(m.group(1))


def parse_sheet(rows: list[list], first_year: int) -> dict[int, float]:
    """Map year -> monthly SMI in force at year end, from the raw rows of the SMI-1 sheet (years >= first_year).

    Older rows are skipped: their amounts were converted from pesetas and do not multiply out to the annual column.
    """
    header = next((r for r in rows if "Mes" in r and "Año" in r), None)
    if header is None:
        raise ValueError("Unexpected SMI sheet: header with 'Mes' and 'Año' columns not found")
    month_col, year_col = header.index("Mes"), header.index("Año")

    changes = []
    for r in rows:
        date = parse_date(r[0])
        if date is None or date[0] < first_year:
            continue
        monthly, annual = r[month_col], r[year_col]
        if not isinstance(monthly, float):
            raise ValueError(f"Unexpected monthly SMI {monthly!r} on {r[0]}")
        if isinstance(annual, float) and abs(monthly * PAYMENTS - annual) > 1:
            raise ValueError(f"SMI on {r[0]}: monthly {monthly} x {PAYMENTS} != annual {annual}")
        changes.append((date, monthly))
    if not changes:
        raise ValueError(f"Unexpected SMI sheet: no dated rows from {first_year}")

    out: dict[int, float] = {}
    for (year, _, _), monthly in sorted(changes):
        out[year] = round(monthly, 2)
    return out


def _session() -> requests.Session:
    """Session that verifies TLS with certifi's roots plus the FNMT intermediate the MITES server omits."""
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.load_verify_locations(cafile=str(FNMT_CA_PEM))

    class Adapter(requests.adapters.HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            super().init_poolmanager(*args, ssl_context=ctx, **kwargs)

    session = requests.Session()
    session.mount("https://", Adapter())
    return session


def fetch_rows() -> list[list]:
    import xlrd

    resp = _session().get(XLS_URL, timeout=60, headers=HEADERS)
    resp.raise_for_status()
    sheet = xlrd.open_workbook(file_contents=resp.content).sheet_by_index(0)
    return [sheet.row_values(r) for r in range(sheet.nrows)]


def build_smi(rows: list[list], first_year: int = BASE_YEAR) -> dict:
    by_year = parse_sheet(rows, first_year)
    if min(by_year) > first_year:
        raise ValueError(f"SMI sheet has no change in {first_year}; cannot tell which amount was in force")
    # The sheet lists only the changes, so a year without a new decree keeps the previous amount.
    years, values, current = [], [], None
    for y in range(first_year, max(by_year) + 1):
        current = by_year.get(y, current)
        years.append(y)
        values.append(current)
    return {"anyo": years, "SMI": values, "fuentes": {"SMI-1": PAGE_URL}}


def main() -> None:
    data = build_smi(fetch_rows())
    SMI_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log.info("Written %s (%s-%s)", SMI_JSON, data["anyo"][0], data["anyo"][-1])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    main()
