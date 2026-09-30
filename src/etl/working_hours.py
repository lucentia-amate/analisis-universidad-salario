"""Working-hours penalty: from 2026 most jobs work 35 h/week for the same pay, professors stay at 37.5 h."""

import pandas as pd

OLD_WEEKLY_HOURS = 37.5
NEW_WEEKLY_HOURS = 35.0
REDUCTION_YEAR = 2026
PENALISED_CATEGORIES = frozenset({"academic"})


def hours_factor() -> float:
    """Pay per hour worked of a 37.5 h job relative to a 35 h job on the same pay."""
    return NEW_WEEKLY_HOURS / OLD_WEEKLY_HOURS


def apply_hours_penalty(salaries: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """Copy of `salaries` with `annual_eur` scaled by hours_factor() from REDUCTION_YEAR for the penalised categories.

    `meta` is indexed by series_id and has a `category` column.
    """
    penalised = salaries["series_id"].map(meta["category"]).isin(PENALISED_CATEGORIES)
    scale = (penalised & (salaries["year"] >= REDUCTION_YEAR)).map({True: hours_factor(), False: 1.0})
    return salaries.assign(annual_eur=salaries["annual_eur"] * scale)
