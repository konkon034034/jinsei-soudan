#!/usr/bin/env python3
"""読み方辞書シートを作成"""
import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SPREADSHEET_ID = "15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo"
SHEET_NAME = "読み方辞書"

# デフォルトの読み方辞書
DEFAULT_ENTRIES = [
    ["元の言葉", "読み方"],  # ヘッダー
    ["iDeCo", "イデコ"],
    ["IDECO", "イデコ"],
    ["ideco", "イデコ"],
    ["NISA", "ニーサ"],
    ["nisa", "ニーサ"],
    ["つみたてNISA", "つみたてニーサ"],
    ["新NISA", "しんニーサ"],
    ["GPIF", "ジーピーアイエフ"],
    ["厚労省", "こうろうしょう"],
    ["年金機構", "ねんきんきこう"],
    ["WPI", "ダブリューピーアイ"],
    ["401k", "よんまるいちけー"],
    ["DC", "ディーシー"],
    ["DB", "ディービー"],
    ["GDP", "ジーディーピー"],
    ["CPI", "シーピーアイ"],
    ["頭痛く", "あたまいたく"],
    ["頭痛い", "あたまいたい"],
]


def main():
    # 認証
    key_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if not key_json:
        print("GOOGLE_SERVICE_ACCOUNT_KEY が設定されていません")
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

    print(f"スプレッドシート: {spreadsheet['properties']['title']}")
    print(f"既存シート: {existing_sheets}")

    if SHEET_NAME in existing_sheets:
        print(f"シート '{SHEET_NAME}' は既に存在します")
    else:
        # 新規シート作成
        request = {
            "requests": [{
                "addSheet": {
                    "properties": {
                        "title": SHEET_NAME,
                        "index": 0
                    }
                }
            }]
        }
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=request
        ).execute()
        print(f"シート '{SHEET_NAME}' を作成しました")

    # データを書き込み
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1:B{len(DEFAULT_ENTRIES)}",
        valueInputOption="RAW",
        body={"values": DEFAULT_ENTRIES}
    ).execute()
    print(f"{len(DEFAULT_ENTRIES) - 1}件のエントリを書き込みました")

    # 書式設定
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheet_id = None
    for s in spreadsheet['sheets']:
        if s['properties']['title'] == SHEET_NAME:
            sheet_id = s['properties']['sheetId']
            break

    if sheet_id:
        requests = [
            # ヘッダー行を太字に
            {
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat.bold"
                }
            },
            # ヘッダー行を固定
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                    "fields": "gridProperties.frozenRowCount"
                }
            },
            # 列幅設定
            {
                "updateDimensionProperties": {
                    "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                    "properties": {"pixelSize": 200},
                    "fields": "pixelSize"
                }
            },
            {
                "updateDimensionProperties": {
                    "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
                    "properties": {"pixelSize": 250},
                    "fields": "pixelSize"
                }
            },
        ]
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": requests}
        ).execute()
        print("書式を設定しました")

    print(f"\n完了！")
    print(f"シート: {SHEET_NAME}")
    print(f"読み間違いがあればシートに追加してください")


if __name__ == "__main__":
    main()
