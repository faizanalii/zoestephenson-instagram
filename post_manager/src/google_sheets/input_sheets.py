"""
Input Sheets
"""

import logging

import gspread
from google.oauth2.service_account import Credentials

from src.settings import (
    INPUT_SHEET_COMMENT_STATS,
    SHEETS_CREDENTIALS_FILE,
)


def _get_sheet(sheet_id: str, worksheet_name: str = "MASTER"):
    """Get Google Sheet worksheet."""
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds: Credentials = Credentials.from_service_account_file(
            SHEETS_CREDENTIALS_FILE, scopes=scopes
        )
        client = gspread.authorize(creds)  # type: ignore
        return client.open_by_key(sheet_id).worksheet(worksheet_name)
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Credentials file not found: {SHEETS_CREDENTIALS_FILE}") from e
    except gspread.exceptions.SpreadsheetNotFound as e:
        raise gspread.exceptions.SpreadsheetNotFound(f"Spreadsheet not found: {sheet_id}") from e
    except gspread.exceptions.WorksheetNotFound as e:
        raise gspread.exceptions.WorksheetNotFound(f"Worksheet not found: {worksheet_name}") from e
    except Exception as e:
        raise Exception(f"Error accessing Google Sheet: {str(e)}") from e


def get_comment_data() -> list[dict]:
    """
    Get comment data from the input sheet.
    Get the search username, and post URL from the input sheet.
    Args:
    Returns:
        list[dict]: A list of dictionaries containing comment data.
    """
    try:
        sheet = _get_sheet(INPUT_SHEET_COMMENT_STATS)
        data = sheet.get_all_records()
        return [
            {
                "username": str(row.get("username", "")).strip().replace("@", ""),
                "post_url": str(row.get("post_url", "")).strip(),
            }
            for row in data
            if str(row.get("username", "")).strip() and str(row.get("post_url", "")).strip()
        ]
    except Exception as e:
        logging.error("Error getting comment data: %s", str(e))
        # For testing
        return []  # Return a default value to avoid breaking the pipeline
