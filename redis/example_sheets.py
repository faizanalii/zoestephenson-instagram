#!/usr/bin/env python3
"""
Quick example script to test Google Sheets connection.
"""

from google_sheets_connector import GoogleSheetsConnector

# Configuration - Update these values
CREDENTIALS_FILE = 'velvety-argon-496015-a2-34531a950d15.json'
SPREADSHEET_ID = '1zhjLCtrtx36j7QvKJTOLGMBbK8Q5bsdIpQIKC682x9M'


def main():
    """Run examples of common operations."""
    
    print("=" * 60)
    print("Google Sheets Connector - Example Usage")
    print("=" * 60)
    
    # Connect to the spreadsheet
    print("\n1. Connecting to Google Sheet...")
    connector = GoogleSheetsConnector(CREDENTIALS_FILE, SPREADSHEET_ID)
    print("   ✓ Connected successfully!")
    
    # List all sheets
    print("\n2. Available Worksheets:")
    sheets = connector.get_sheet_names()
    for i, sheet in enumerate(sheets):
        print(f"   [{i}] {sheet}")
    
    # Read data from first sheet
    print("\n3. Reading data from first sheet...")
    data = connector.read_data(sheet_index=0)
    print(f"   ✓ Read {len(data)} rows")
    if data:
        print("\n   First 3 rows:")
        for i, row in enumerate(data[:3]):
            print(f"      {row}")
    
    # Read as dictionaries (if headers exist)
    print("\n4. Reading as dictionaries (with headers)...")
    records = connector.read_as_dict(sheet_index=0)
    print(f"   ✓ Read {len(records)} records")
    if records:
        print(f"   First record keys: {list(records[0].keys())}")
        print(f"   First record: {records[0]}")
    
    # Examples of other operations (commented out)
    print("\n5. Other available operations:")
    print("   - connector.write_data(data, start_cell='A1')")
    print("   - connector.append_rows(new_rows)")
    print("   - connector.clear_worksheet()")
    print("   - connector.get_worksheet('Sheet Name')")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"\n✗ Error: {e}")
        print("\nTroubleshooting:")
        print("  1. Make sure credentials JSON file exists in this directory")
        print("  2. Make sure the Google Sheet ID is correct")
        print("  3. Make sure the service account has access to the sheet")
        print("  4. Install dependencies: pip install -r requirements-sheets.txt")
