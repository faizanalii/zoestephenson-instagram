#!/usr/bin/env python3
"""
Google Sheets connector using service account credentials.
Reads from and writes to Google Sheets via the Sheets API.
"""

import json
from pathlib import Path
from typing import Any, List, Dict, Optional
import gspread
from google.oauth2.service_account import Credentials


class GoogleSheetsConnector:
    """Connect to Google Sheets using service account credentials."""
    
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    
    def __init__(self, credentials_path: str, spreadsheet_id: str):
        """
        Initialize the Google Sheets connector.
        
        Args:
            credentials_path: Path to the service account JSON file
            spreadsheet_id: The Google Sheet ID (from the URL)
        """
        self.credentials_path = credentials_path
        self.spreadsheet_id = spreadsheet_id
        self.client = self._authenticate()
        self.spreadsheet = self.client.open_by_key(spreadsheet_id)
    
    def _authenticate(self) -> gspread.Client:
        """Authenticate using service account credentials."""
        creds = Credentials.from_service_account_file(
            self.credentials_path,
            scopes=self.SCOPES
        )
        return gspread.authorize(creds)
    
    def get_worksheet(self, sheet_name: Optional[str] = None, sheet_index: int = 0):
        """
        Get a specific worksheet.
        
        Args:
            sheet_name: Name of the worksheet (if None, uses sheet_index)
            sheet_index: Index of the worksheet (default: 0 for first sheet)
        
        Returns:
            gspread worksheet object
        """
        if sheet_name:
            return self.spreadsheet.worksheet(sheet_name)
        else:
            return self.spreadsheet.get_worksheet(sheet_index)
    
    def read_data(self, sheet_name: Optional[str] = None, sheet_index: int = 0) -> List[List[Any]]:
        """
        Read all data from a worksheet.
        
        Args:
            sheet_name: Name of the worksheet
            sheet_index: Index of the worksheet
        
        Returns:
            List of rows (each row is a list of cell values)
        """
        worksheet = self.get_worksheet(sheet_name, sheet_index)
        return worksheet.get_all_values()
    
    def read_as_dict(self, sheet_name: Optional[str] = None, sheet_index: int = 0) -> List[Dict[str, Any]]:
        """
        Read all data as dictionaries (first row as headers).
        
        Args:
            sheet_name: Name of the worksheet
            sheet_index: Index of the worksheet
        
        Returns:
            List of dictionaries with headers as keys
        """
        worksheet = self.get_worksheet(sheet_name, sheet_index)
        records = worksheet.get_all_records()
        return records
    
    def write_data(self, data: List[List[Any]], sheet_name: Optional[str] = None, 
                   sheet_index: int = 0, start_cell: str = 'A1') -> None:
        """
        Write data to a worksheet.
        
        Args:
            data: List of rows to write
            sheet_name: Name of the worksheet
            sheet_index: Index of the worksheet
            start_cell: Starting cell (e.g., 'A1', 'B2')
        """
        worksheet = self.get_worksheet(sheet_name, sheet_index)
        worksheet.update(start_cell, data)
    
    def append_rows(self, rows: List[List[Any]], sheet_name: Optional[str] = None, 
                    sheet_index: int = 0) -> None:
        """
        Append rows to the end of a worksheet.
        
        Args:
            rows: List of rows to append
            sheet_name: Name of the worksheet
            sheet_index: Index of the worksheet
        """
        worksheet = self.get_worksheet(sheet_name, sheet_index)
        worksheet.append_rows(rows)
    
    def clear_worksheet(self, sheet_name: Optional[str] = None, sheet_index: int = 0) -> None:
        """
        Clear all data from a worksheet.
        
        Args:
            sheet_name: Name of the worksheet
            sheet_index: Index of the worksheet
        """
        worksheet = self.get_worksheet(sheet_name, sheet_index)
        worksheet.clear()
    
    def get_sheet_names(self) -> List[str]:
        """Get list of all worksheet names in the spreadsheet."""
        return [sheet.title for sheet in self.spreadsheet.worksheets()]


def main():
    """Example usage of the Google Sheets connector."""
    
    # Configuration
    CREDENTIALS_FILE = 'velvety-argon-496015-a2-34531a950d15.json'
    SPREADSHEET_ID = '1zhjLCtrtx36j7QvKJTOLGMBbK8Q5bsdIpQIKC682x9M'
    
    try:
        # Initialize connector
        connector = GoogleSheetsConnector(CREDENTIALS_FILE, SPREADSHEET_ID)
        print(f"✓ Connected to spreadsheet: {SPREADSHEET_ID}")
        
        # List available sheets
        sheets = connector.get_sheet_names()
        print(f"✓ Available sheets: {sheets}")
        
        # Read data from first sheet
        print("\n--- Reading data from Sheet1 ---")
        data = connector.read_data(sheet_index=0)
        print(f"✓ Read {len(data)} rows")
        for i, row in enumerate(data[:5]):  # Print first 5 rows
            print(f"  Row {i+1}: {row}")
        
        if len(data) > 5:
            print(f"  ... and {len(data) - 5} more rows")
        
        # Read as dictionaries (with headers)
        print("\n--- Reading as dictionaries ---")
        records = connector.read_as_dict(sheet_index=0)
        print(f"✓ Read {len(records)} records")
        if records:
            print(f"  First record: {records[0]}")
        
        # Example: Append new rows
        # new_rows = [
        #     ['John', 'Doe', 'john@example.com'],
        #     ['Jane', 'Smith', 'jane@example.com']
        # ]
        # connector.append_rows(new_rows)
        # print("✓ Appended new rows")
        
    except FileNotFoundError as e:
        print(f"✗ Error: {e}")
        print("Make sure the credentials JSON file is in the same directory.")
    except Exception as e:
        print(f"✗ Error: {e}")


if __name__ == '__main__':
    main()
