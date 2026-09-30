"""Build TitularUniversidad.json and CatedraticoUniversidad.json from the USAL "PDI funcionario" salary PDFs
listed in urllist.txt.

Run: `python -m etl.usal_pdf` (needs `pdfplumber`, see requirements-dev.txt).

Value taken per year: monthly table, row "Titulares U." / "Catedráticos de Universidad" with dedication "TC",
column "TOTAL SIN TRIENIOS, QUINQUENIOS NI SEXENIOS".
"""

import io
import json
import logging
import re
from urllib.parse import urljoin

import requests

from etl.config import CATEDRATICO_JSON, TITULAR_JSON, URLLIST_TXT

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0"}
# JSON key -> (start of the row label in the PDF table, output file)
POSITIONS = {
    "TitularUniversidad": ("Titulares U", TITULAR_JSON),
    "CatedraticoUniversidad": ("Catedráticos de Universidad", CATEDRATICO_JSON),
}
AMOUNT = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}")
# When a year has two tables (Jan-Jun and Jul-Dec) the Jul-Dec one is used, i.e. the rate in force at year end.
PREFERRED_SUFFIX = "juldic"


def parse_urllist(text: str) -> dict[int, str | None]:
    """Map year -> url (None when the list has no source for that year)."""
    candidates: dict[int, dict[str, str | None]] = {}
    for year, suffix, url in re.findall(r'^url(\d{4})(\w*)\s*=\s*(?:"([^"]+)"|None)', text, re.M):
        candidates.setdefault(int(year), {})[suffix] = url or None
    out = {}
    for year, by_suffix in candidates.items():
        out[year] = by_suffix[PREFERRED_SUFFIX] if PREFERRED_SUFFIX in by_suffix else next(iter(by_suffix.values()))
    return dict(sorted(out.items()))


def _amount(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def extract_tc_totals(pdf_bytes: bytes, expected_year: int) -> dict[str, float]:
    """Monthly 'TOTAL SIN TRIENIOS, QUINQUENIOS NI SEXENIOS' of the TC row of every position in POSITIONS."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        page = pdf.pages[0].extract_text() or ""

    title = re.search(r"CÓMPUTO MENSUAL[^\n]*?(\d{4})", page)
    if not title or int(title.group(1)) != expected_year:
        raise ValueError(f"PDF title does not match {expected_year}: {title.group(0) if title else 'not found'}")

    totals = {}
    for key, (prefix, _) in POSITIONS.items():
        row = next((ln for ln in page.splitlines() if ln.startswith(prefix) and " TC " in ln), None)
        if row is None:
            raise ValueError(f"Row '{prefix} ... TC' not found for {expected_year}")
        amounts = AMOUNT.findall(row)
        # From 2011 the table appends two Social Security columns after the total ("S. SOCIAL", "COSTE TOTAL").
        totals[key] = _amount(amounts[-3] if "COSTE" in page else amounts[-1])
    return totals


def resolve_html(html: str, page_url: str, year: int) -> tuple[str | None, int | None]:
    """For a year given as a web page return (pdf_url, None), or (None, ref_year) if pay equals another year."""
    link = re.search(r'href="([^"]*/PDI/[^"]*FUN[^"]*\.pdf)"', html, re.I)
    if link:
        return urljoin(page_url, "/" + link.group(1).lstrip("/")), None
    same = re.search(r"iguales a las que figuran en las tablas de (\d{4})", html)
    if same and int(same.group(1)) < year:
        return None, int(same.group(1))
    raise ValueError(f"Cannot find a PDI table or a reference year in {page_url}")


def build_positions(urls: dict[int, str | None]) -> dict[str, dict]:
    """Return one JSON-ready dict per position in POSITIONS, all built from the same PDFs."""
    values: dict[int, dict[str, float | None]] = {}
    sources: dict[int, str] = {}
    for year, url in urls.items():
        if url is None:
            values[year] = dict.fromkeys(POSITIONS)
            continue
        resp = requests.get(url, timeout=60, headers=HEADERS)
        resp.raise_for_status()
        if not resp.content.startswith(b"%PDF"):
            resp.encoding = "utf-8"
            pdf_url, ref_year = resolve_html(resp.text, url, year)
            if pdf_url is None:
                values[year], sources[year] = values[ref_year], url
                log.info("%s: same as %s -> %s", year, ref_year, values[year])
                continue
            url, resp = pdf_url, requests.get(pdf_url, timeout=60, headers=HEADERS)
            resp.raise_for_status()
        values[year], sources[year] = extract_tc_totals(resp.content, year), url
        log.info("%s: %s (%s)", year, values[year], url)
    return {
        key: {
            "anyo": list(values),
            key: [v[key] for v in values.values()],
            "fuentes": {str(y): u for y, u in sources.items()},
        }
        for key in POSITIONS
    }


def main() -> None:
    data = build_positions(parse_urllist(URLLIST_TXT.read_text(encoding="utf-8")))
    for key, (_, path) in POSITIONS.items():
        path.write_text(json.dumps(data[key], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        log.info("Written %s", path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    main()
