"""ETL entrypoint: `python -m etl.build` refreshes every table in src/processeddata."""

import logging
import sys

import requests

from etl import ine_cpi
from etl.config import CPI_MONTHLY_CSV, CPI_YEARLY_CSV, PROCESSED_DIR, SALARIES_CSV, SERIES_META_CSV
from etl.salaries import build_salaries

log = logging.getLogger(__name__)


def build(refresh_cpi: bool = True) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    cached = CPI_MONTHLY_CSV.exists() and CPI_YEARLY_CSV.exists()
    if refresh_cpi or not cached:
        try:
            ine_cpi.refresh()
        except (requests.RequestException, ValueError, KeyError) as exc:
            if not cached:
                raise
            log.warning("INE download failed (%s); keeping cached CPI data", exc)

    salaries, meta = build_salaries()
    salaries.to_csv(SALARIES_CSV, index=False)
    meta.to_csv(SERIES_META_CSV, index=False)
    log.info("Salaries updated: %s series", len(meta))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    build(refresh_cpi="--no-refresh" not in sys.argv)
