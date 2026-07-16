"""Pure numeric normalization helpers for baseball statistics."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


def make_numeric(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    for column in columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def safe_number(value: object) -> float | None:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return None
    return float(number)


def safe_int(value: object) -> int:
    number = pd.to_numeric(value, errors="coerce")
    if pd.isna(number):
        return 0
    return int(number)


def safe_divide(numerator: object, denominator: object) -> float | None:
    clean_numerator = safe_number(numerator)
    clean_denominator = safe_number(denominator)
    if clean_denominator is None or clean_denominator == 0 or clean_numerator is None:
        return None
    return clean_numerator / clean_denominator


def is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return str(value).strip() == ""
