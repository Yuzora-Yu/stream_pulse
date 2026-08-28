from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHEETS = [
    "config",
    "game_master",
    "aliases",
    "review_queue",
    "audit_log",
    "daily_game_stats",
    "daily_hour_stats",
    "system_status",
]


def _service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError("Google API packages are required; install requirements.txt") from exc
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required")
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(raw), scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def read_values(sheet_id: str, range_name: str) -> list[list[Any]]:
    result = _service().spreadsheets().values().get(spreadsheetId=sheet_id, range=range_name).execute()
    return result.get("values", [])


def write_values(sheet_id: str, range_name: str, values: list[list[Any]]) -> None:
    _service().spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=range_name,
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def verify_tabs(sheet_id: str) -> list[str]:
    metadata = (
        _service()
        .spreadsheets()
        .get(spreadsheetId=sheet_id, fields="sheets.properties.title")
        .execute()
    )
    existing = {item["properties"]["title"] for item in metadata.get("sheets", [])}
    return [name for name in SHEETS if name not in existing]


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify STREAM PULSE control-plane spreadsheet")
    parser.add_argument("--sheet-id", default=os.environ.get("GOOGLE_SHEET_ID"))
    args = parser.parse_args()
    if not args.sheet_id:
        raise SystemExit("GOOGLE_SHEET_ID or --sheet-id is required")
    missing = verify_tabs(args.sheet_id)
    if missing:
        raise SystemExit(f"Missing required sheets: {', '.join(missing)}")
    print(json.dumps({"status": "ok", "sheets": SHEETS}, ensure_ascii=False))


if __name__ == "__main__":
    main()

