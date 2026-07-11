import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from src.api_client import get as api_get


STATS_API_BASE = "https://statsapi.mlb.com/api/v1"
REQUEST_TIMEOUT = 12
REQUEST_HEADERS = {"User-Agent": "All Rise Analytics/1.0"}


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.date()


def injured_list_days(status_code):
    match = re.fullmatch(r"D(\d+)", str(status_code or "").upper())
    return int(match.group(1)) if match else None


def eligible_return_date(status_code, effective_date):
    list_days = injured_list_days(status_code)
    effective_date = _as_date(effective_date)
    if not list_days or effective_date is None:
        return None
    return effective_date + timedelta(days=list_days)


def _get_json(path, params, request_get=None):
    request_get = request_get or api_get
    kwargs = {
        "params": params,
        "headers": REQUEST_HEADERS,
        "timeout": REQUEST_TIMEOUT,
    }
    if request_get is api_get:
        kwargs["provider"] = "MLB StatsAPI"
    response = request_get(f"{STATS_API_BASE}/{path.lstrip('/')}", **kwargs)
    response.raise_for_status()
    return response.json()


def _injury_transactions(transactions):
    latest = {}
    for transaction in transactions:
        description = str(transaction.get("description") or "")
        lowered = description.lower()
        if "placed" not in lowered or "injured list" not in lowered:
            continue
        player_id = transaction.get("person", {}).get("id")
        if player_id is None:
            continue
        transaction_date = _as_date(
            transaction.get("effectiveDate") or transaction.get("date")
        )
        current = latest.get(int(player_id))
        if current is None or (
            transaction_date
            and transaction_date > (current.get("effective_date") or date.min)
        ):
            latest[int(player_id)] = {
                "description": description,
                "effective_date": transaction_date,
            }
    return latest


def _injury_detail(description):
    if not description:
        return ""
    parts = [part.strip() for part in str(description).split(".") if part.strip()]
    if len(parts) >= 2:
        return parts[-1]
    return ""


def _injury_tooltip(status_description, transaction, status_code, as_of_date):
    pieces = [str(status_description or "Injured list")]
    detail = _injury_detail((transaction or {}).get("description"))
    if detail:
        pieces.append(detail)
    return_date = eligible_return_date(
        status_code,
        (transaction or {}).get("effective_date"),
    )
    if return_date:
        return_label = (
            "Est. eligible return"
            if return_date >= as_of_date
            else "Eligible since"
        )
        pieces.append(f"{return_label}: {return_date.strftime('%m/%d/%y')}")
    return ". ".join(piece.rstrip(".") for piece in pieces if piece) + "."


def fetch_injury_report(team_ids, as_of_date, request_get=None):
    as_of_date = _as_date(as_of_date) or date.today()
    start_date = max(date(as_of_date.year, 1, 1), as_of_date - timedelta(days=180))
    team_ids = sorted({int(team_id) for team_id in team_ids if team_id})
    if not team_ids:
        return {}

    try:
        transactions_payload = _get_json(
            "transactions",
            {
                "sportId": 1,
                "transactionTypes": "SC",
                "startDate": start_date.strftime("%m/%d/%Y"),
                "endDate": as_of_date.strftime("%m/%d/%Y"),
            },
            request_get,
        )
        transactions = _injury_transactions(
            transactions_payload.get("transactions", [])
        )
    except (requests.RequestException, ValueError, TypeError):
        transactions = {}

    report = {}

    def fetch_roster(team_id):
        return _get_json(
            f"teams/{team_id}/roster",
            {
                "rosterType": "40Man",
                "date": as_of_date.strftime("%m/%d/%Y"),
            },
            request_get,
        )

    max_workers = min(8, len(team_ids))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        roster_requests = {
            executor.submit(fetch_roster, team_id): team_id
            for team_id in team_ids
        }
        roster_payloads = []
        for future in as_completed(roster_requests):
            try:
                roster_payloads.append(future.result())
            except (requests.RequestException, ValueError, TypeError):
                continue

    for roster_payload in roster_payloads:
        try:
            for entry in roster_payload.get("roster", []):
                status = entry.get("status") or {}
                status_code = status.get("code")
                if injured_list_days(status_code) is None:
                    continue
                player_id = entry.get("person", {}).get("id")
                if player_id is None:
                    continue
                player_id = int(player_id)
                transaction = transactions.get(player_id, {})
                return_date = eligible_return_date(
                    status.get("code"),
                    transaction.get("effective_date"),
                )
                report[player_id] = {
                    "injury_status": status.get("description") or "Injured list",
                    "injury_tooltip": _injury_tooltip(
                        status.get("description"),
                        transaction,
                        status.get("code"),
                        as_of_date,
                    ),
                    "injury_return_date": (
                        return_date.isoformat() if return_date else None
                    ),
                }
        except (requests.RequestException, ValueError, TypeError):
            continue

    return report


def add_injury_columns(dataframe, player_id_column, injury_report):
    if dataframe is None or dataframe.empty:
        return dataframe

    result = dataframe.copy()

    def lookup(player_id, field):
        numeric_id = pd.to_numeric(player_id, errors="coerce")
        if pd.isna(numeric_id):
            return None
        return injury_report.get(int(numeric_id), {}).get(field)

    for field in ("injury_status", "injury_tooltip", "injury_return_date"):
        result[field] = result[player_id_column].map(
            lambda player_id, field=field: lookup(player_id, field)
        )
    return result
