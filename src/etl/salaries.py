"""Load the salary series (USAL PDI files, SMI file + researched public catalog)."""

import json
import re
from pathlib import Path

import pandas as pd

from etl.config import CATEDRATICO_JSON, PDI_ANNUAL_JSON, SALARY_CATALOG_JSON, SMI_JSON, TITULAR_JSON
from etl.irpf import add_net_salary, load_irpf

CATEGORY_ORDER = ["academic", "minimum_wage", "politician", "low_wage", "general"]

# Monthly gross EUR from the USAL PDF tables; annual = monthly x an effective number of payments per year
# derived from the Universidad de Alicante tables (see load_pdi_factors).
USAL_SOURCE = (
    "Universidad de Salamanca, tablas salariales PDI funcionario (PDF): fila «{row}» con "
    "dedicación TC, columna «TOTAL SIN TRIENIOS, QUINQUENIOS NI SEXENIOS» de la tabla mensual"
)
USAL_NOTES = (
    "Importe mensual bruto. El anual se calcula con {factor} pagas equivalentes (no 14): las pagas extra "
    "son inferiores a una mensualidad. Factor = «Total anual» / total mensual de la Universidad de Alicante "
    "(tablas retributivas PDI 2025 y 2026, mismo resultado en ambos años), extrapolado a todos los años y "
    "aplicado a los importes de la USAL. En 2018 y 2019 se usa la tabla de julio-diciembre. 2012 repite 2011 "
    "(según la web de la USAL). 2015 y 2016 no tienen fuente en la lista de URL y se muestran como huecos."
)
TITULAR_META = {
    "id": "profesor_titular",
    "label": "University Associate Professor (Titular de Universidad)",
    "label_es": "Profesor Titular de Universidad",
    "category": "academic",
    "unit": "eur_monthly",
    "payments_per_year": 14,  # replaced by the Alicante-derived factor in load_titular
    "basis": "gross",
    "source": USAL_SOURCE.format(row="Titulares U."),
    "source_urls": [],
    "notes": USAL_NOTES,
}
CATEDRATICO_META = {
    **TITULAR_META,
    "id": "catedratico_universidad",
    "label": "University Full Professor (Catedrático de Universidad)",
    "label_es": "Catedrático de Universidad",
    "source": USAL_SOURCE.format(row="Catedráticos de Universidad"),
}
SMI_META = {
    "id": "smi",
    "label": "Minimum wage (SMI)",
    "label_es": "SMI (Salario Mínimo Interprofesional)",
    "category": "minimum_wage",
    "unit": "eur_monthly",
    "payments_per_year": 14,
    "basis": "gross",
    "irpf_exempt": True,
    "source": "Ministerio de Trabajo y Economía Social, Boletín de Estadísticas Laborales, tabla SMI-1 "
    "(evolución del salario mínimo interprofesional): columna «Mes»",
    "source_urls": [],
    "notes": "Importe mensual bruto, con 14 pagas (equivale a la columna «Año» de la tabla). Cuando el SMI "
    "cambió durante el año (2004, 2021, 2023) se usa el vigente a 31 de diciembre.",
}


def read_lenient_json(path: Path) -> dict:
    """Parse JSON that may contain empty array slots (e.g. `1,,2`), reading them as null."""
    text = path.read_text(encoding="utf-8-sig")
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"([\[,])(\s*)(?=[,\]])", r"\1\2null", text)
    return json.loads(text)


def _load_series_file(meta: dict, path: Path, key: str) -> dict:
    raw = read_lenient_json(path)
    years = raw["anyo"]
    values = raw[key]
    if len(years) != len(values):
        raise ValueError(f"anyo and {key} have different lengths")
    urls = list(dict.fromkeys(raw.get("fuentes", {}).values()))
    return {**meta, "source_urls": urls, "values": {str(y): v for y, v in zip(years, values)}}


def load_pdi_factors(path: Path = PDI_ANNUAL_JSON, tolerance: float = 0.01) -> dict[str, dict]:
    """Effective payments per year (annual total / monthly total) of each professor position, from Alicante's tables.

    Each position must give the same ratio in every published year (within `tolerance`), otherwise it could
    not be extrapolated to the other years.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for key, entry in raw["posiciones"].items():
        ratios = {y: v["anual"] / v["mensual"] for y, v in entry.items() if isinstance(v, dict)}
        if not ratios or max(ratios.values()) - min(ratios.values()) > tolerance:
            raise ValueError(f"{key}: annual/monthly ratio is not stable across years: {ratios}")
        out[key] = {
            "factor": round(sum(ratios.values()) / len(ratios), 4),
            "ratios": ratios,
            "urls": list(raw["fuentes"].values()),
        }
    return out


def _load_pdi_series(meta: dict, path: Path, key: str) -> dict:
    ua = load_pdi_factors()[key]
    factor_txt = f"{ua['factor']:.2f}".replace(".", ",")
    meta = {**meta, "payments_per_year": ua["factor"], "notes": USAL_NOTES.format(factor=factor_txt)}
    series = _load_series_file(meta, path, key)
    series["source_urls"] = [*series["source_urls"], *ua["urls"]]
    return series


def load_titular(path: Path = TITULAR_JSON) -> dict:
    return _load_pdi_series(TITULAR_META, path, "TitularUniversidad")


def load_catedratico(path: Path = CATEDRATICO_JSON) -> dict:
    return _load_pdi_series(CATEDRATICO_META, path, "CatedraticoUniversidad")


def load_smi(path: Path = SMI_JSON) -> dict:
    return _load_series_file(SMI_META, path, "SMI")



def load_catalog(path: Path = SALARY_CATALOG_JSON) -> tuple[list[dict], list[dict]]:
    if not path.exists():
        return [], []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw.get("series", []), raw.get("rejected", [])


def _annual(value: float | None, unit: str, payments: int) -> float | None:
    if value is None:
        return None
    return value * payments if unit == "eur_monthly" else value


def build_salaries() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (long salary table, series metadata). Rows exist for every year, NaN when missing."""
    series = [load_titular(), load_catedratico(), load_smi(), *load_catalog()[0]]
    series.sort(key=lambda s: CATEGORY_ORDER.index(s["category"]) if s["category"] in CATEGORY_ORDER else 99)

    rows, meta = [], []
    for order, s in enumerate(series):
        payments = s.get("payments_per_year", 12)
        payments = int(payments) if float(payments).is_integer() else float(payments)
        for year, value in s["values"].items():
            rows.append(
                {
                    "year": int(year),
                    "series_id": s["id"],
                    "published": value,
                    "annual_eur": _annual(value, s["unit"], payments),
                }
            )
        meta.append(
            {
                "series_id": s["id"],
                "order": order,
                "label": s["label"],
                "label_es": s.get("label_es", ""),
                "category": s["category"],
                "unit": s["unit"],
                "payments_per_year": payments,
                "basis": s.get("basis", "gross"),
                "source": s.get("source", ""),
                "source_urls": " | ".join(s.get("source_urls", [])),
                "notes": s.get("notes", ""),
            }
        )
    salaries = pd.DataFrame(rows).sort_values(["series_id", "year"]).reset_index(drop=True)
    salaries = add_net_salary(salaries, load_irpf(), {s["id"] for s in series if s.get("irpf_exempt")})
    return salaries, pd.DataFrame(meta)
