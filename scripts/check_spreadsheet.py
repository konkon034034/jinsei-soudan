#!/usr/bin/env python3
"""スプレッドシートの構成を確認"""
import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SPREADSHEET_ID = "15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo"

def main():
    # 認証
    key_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if not key_json:
        print("❌ GOOGLE_SERVICE_ACCOUNT_KEY が設定されていません")
        return

    key_data = json.loads(key_json)
    creds = Credentials.from_service_account_info(
        key_data,
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )

    service = build('sheets', 'v4', credentials=creds)

    # スプレッドシートの情報を取得
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()

    print(f"📊 スプレッドシート名: {spreadsheet['properties']['title']}")
    print(f"\n=== シート一覧 ({len(spreadsheet['sheets'])}件) ===")

    for sheet in spreadsheet['sheets']:
        props = sheet['properties']
        hidden = "🔒非表示" if props.get('hidden', False) else "📄表示"
        print(f"  {hidden} | ID:{props['sheetId']:>10} | {props['title']}")

if __name__ == "__main__":
    main()
