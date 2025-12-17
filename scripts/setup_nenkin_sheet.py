#!/usr/bin/env python3
"""年金ニュース用シートを作成"""
import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SPREADSHEET_ID = "15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo"
SHEET_NAME = "年金ニュース"
HEADERS = [
    "作成済",      # A: チェックボックス
    "日時",        # B
    "情報収集",    # C
    "スクリプト作成",  # D
    "文字数カウント",  # E
    "script",     # F: 台本全文
    "生成URL",    # G: 動画URL
    "編集後プロンプト", # H
    "概要",        # I
    "metadata",   # J
    "comment",    # K
    "search",     # L
    "YouTubeサムネ" # M
]

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
            range=f"{SHEET_NAME}!A1:M1",
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
            range=f"{SHEET_NAME}!A1:M1",
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
        # 列幅設定 (A-M: 13列)
        column_widths = [
            70,   # A: 作成済 (チェックボックス)
            150,  # B: 日時
            300,  # C: 情報収集
            300,  # D: スクリプト作成
            100,  # E: 文字数カウント
            400,  # F: script (台本全文)
            200,  # G: 生成URL
            300,  # H: 編集後プロンプト
            300,  # I: 概要
            200,  # J: metadata
            200,  # K: comment
            200,  # L: search
            150,  # M: YouTubeサムネ
        ]

        requests = []
        for i, width in enumerate(column_widths):
            requests.append({
                "updateDimensionProperties": {
                    "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize"
                }
            })

        # ヘッダー行を太字に
        requests.append({
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold"
            }
        })
        # ヘッダー行を固定
        requests.append({
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount"
            }
        })
        # A列にチェックボックスを設定
        requests.append({
            "setDataValidation": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 1},
                "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}
            }
        })
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
