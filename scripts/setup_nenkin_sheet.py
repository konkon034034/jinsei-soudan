#!/usr/bin/env python3
"""年金ニュース用シートを作成"""
import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SPREADSHEET_ID = "15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo"
SHEET_NAME = "年金ニュース"
HEADERS = ["日付", "タイトル", "動画URL", "ステータス", "処理時間", "動画長"]

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

    # 既存シートを確認
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    existing_sheets = [s['properties']['title'] for s in spreadsheet['sheets']]

    print(f"📊 スプレッドシート: {spreadsheet['properties']['title']}")
    print(f"   既存シート: {existing_sheets}")

    if SHEET_NAME in existing_sheets:
        print(f"⚠ シート '{SHEET_NAME}' は既に存在します")
        # ヘッダーだけ更新
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1:F1",
            valueInputOption="RAW",
            body={"values": [HEADERS]}
        ).execute()
        print(f"✓ ヘッダーを更新しました")
    else:
        # 新規シート作成
        request = {
            "requests": [{
                "addSheet": {
                    "properties": {
                        "title": SHEET_NAME,
                        "index": 0  # 先頭に配置
                    }
                }
            }]
        }
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=request
        ).execute()
        print(f"✓ シート '{SHEET_NAME}' を作成しました")

        # ヘッダーを追加
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1:F1",
            valueInputOption="RAW",
            body={"values": [HEADERS]}
        ).execute()
        print(f"✓ ヘッダーを追加しました: {HEADERS}")

    # 列幅を調整
    sheet_id = None
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    for s in spreadsheet['sheets']:
        if s['properties']['title'] == SHEET_NAME:
            sheet_id = s['properties']['sheetId']
            break

    if sheet_id:
        requests = [
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 120}, "fields": "pixelSize"
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
                "properties": {"pixelSize": 300}, "fields": "pixelSize"
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
                "properties": {"pixelSize": 350}, "fields": "pixelSize"
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 3, "endIndex": 4},
                "properties": {"pixelSize": 100}, "fields": "pixelSize"
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 4, "endIndex": 6},
                "properties": {"pixelSize": 100}, "fields": "pixelSize"
            }},
            # ヘッダー行を太字に
            {"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold"
            }},
            # ヘッダー行を固定
            {"updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount"
            }}
        ]
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": requests}
        ).execute()
        print(f"✓ 列幅・書式を設定しました")

    print(f"\n✅ 完了！")
    print(f"   シート: {SHEET_NAME}")
    print(f"   ヘッダー: {' | '.join(HEADERS)}")

if __name__ == "__main__":
    main()
