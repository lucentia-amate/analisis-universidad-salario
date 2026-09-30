import pytest

from etl import usal_pdf

URLLIST = """url2026= "https://x/6.pdf"
url2019juldic = "https://x/19b.pdf"
url2019enejun = "https://x/19a.pdf"
url2016 = None
url2012 = "https://x/tablas-2012"
"""


def test_parse_urllist_prefers_second_half_and_keeps_missing_years():
    assert usal_pdf.parse_urllist(URLLIST) == {
        2012: "https://x/tablas-2012",
        2016: None,
        2019: "https://x/19b.pdf",
        2026: "https://x/6.pdf",
    }


def test_resolve_html_finds_pdi_table_link():
    html = '<a href="files/Retribuciones/tablas/2008/PDI/PDIFUN08.pdf">Retribuciones</a>'
    url, ref = usal_pdf.resolve_html(html, "https://www.usal.es/tablas-salariales-ano-2008", 2008)
    assert url == "https://www.usal.es/files/Retribuciones/tablas/2008/PDI/PDIFUN08.pdf" and ref is None


def test_resolve_html_reads_same_as_previous_year():
    html = "Las retribuciones para el año 2012 son iguales a las que figuran en las tablas de 2011, con la salvedad"
    assert usal_pdf.resolve_html(html, "https://x/p", 2012) == (None, 2011)


def test_resolve_html_fails_without_table_or_reference():
    with pytest.raises(ValueError):
        usal_pdf.resolve_html("<p>nada</p>", "https://x/p", 2012)


class FakePdf:
    def __init__(self, text):
        self.pages = [type("Page", (), {"extract_text": lambda self_: text})()]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


PAGE_2025 = """CÓMPUTO MENSUAL AÑO 2025
Catedráticos de Universidad TC 29 52,60 183,14 3.658,89 979,43 4.638,32
Titulares U./Catedráticos E.U. TC 27 52,60 148,32 2.924,74 778,69 3.703,43
COSTE TOTAL"""
PAGE_2008 = """CÓMPUTO MENSUAL AÑO 2008
Catedráticos de Universidad TC 29 43,63 152,86 101,91 3.037,15
Titulares Univ./Catedráticos E.U. TC 27 43,63 123,81 82,54 2.424,21"""


@pytest.mark.parametrize(
    "page, year, expected",
    [
        (PAGE_2025, 2025, {"TitularUniversidad": 2924.74, "CatedraticoUniversidad": 3658.89}),
        (PAGE_2008, 2008, {"TitularUniversidad": 2424.21, "CatedraticoUniversidad": 3037.15}),
    ],
)
def test_extract_tc_totals_reads_both_positions(monkeypatch, page, year, expected):
    import pdfplumber

    monkeypatch.setattr(pdfplumber, "open", lambda *a, **k: FakePdf(page))
    assert usal_pdf.extract_tc_totals(b"", year) == expected


def test_extract_tc_totals_rejects_wrong_year(monkeypatch):
    import pdfplumber

    monkeypatch.setattr(pdfplumber, "open", lambda *a, **k: FakePdf(PAGE_2025))
    with pytest.raises(ValueError):
        usal_pdf.extract_tc_totals(b"", 2024)
