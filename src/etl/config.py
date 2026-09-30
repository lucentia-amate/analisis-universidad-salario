from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SRC_DIR / "data"
PROCESSED_DIR = SRC_DIR / "processeddata"

URLLIST_TXT = DATA_DIR / "urllist.txt"
TITULAR_JSON = DATA_DIR / "TitularUniversidad.json"
CATEDRATICO_JSON = DATA_DIR / "CatedraticoUniversidad.json"
SMI_JSON = DATA_DIR / "SMI.json"
PDI_ANNUAL_JSON = DATA_DIR / "PDI_annual_factors.json"
# Intermediate CA that www.mites.gob.es does not send in its TLS handshake (issued by the FNMT root).
FNMT_CA_PEM = DATA_DIR / "fnmt_ac_componentes.pem"
SALARY_CATALOG_JSON = DATA_DIR / "salary_series.json"
IRPF_CSV = DATA_DIR / "irpf_valencia.csv"

CPI_MONTHLY_CSV = PROCESSED_DIR / "cpi_monthly.csv"
CPI_YEARLY_CSV = PROCESSED_DIR / "cpi_yearly.csv"
SALARIES_CSV = PROCESSED_DIR / "salaries.csv"
SERIES_META_CSV = PROCESSED_DIR / "series_meta.csv"

BASE_YEAR = 2008
