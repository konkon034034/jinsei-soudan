#!/usr/bin/env python3
"""
スプレッドシートセットアップスクリプト
- YouTube自動投稿シートをクリア・ヘッダー設定
- 3チャンネル一覧シートを作成
"""

import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SPREADSHEET_ID = "15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo"

def get_credentials():
    """Google認証情報を取得"""
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if not creds_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY が設定されていません")

    creds_info = json.loads(creds_json)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    return Credentials.from_service_account_info(creds_info, scopes=scopes)


def setup_spreadsheet():
    """スプレッドシートをセットアップ"""
    service = build("sheets", "v4", credentials=get_credentials())

    # 1. 既存のシート情報を取得
    print("既存のシート情報を取得中...")
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheets = spreadsheet.get("sheets", [])

    print(f"  現在のシート数: {len(sheets)}")
    for sheet in sheets:
        print(f"    - {sheet['properties']['title']} (ID: {sheet['properties']['sheetId']})")

    # 2. 「YouTube自動投稿」シート以外を削除
    requests = []
    youtube_sheet_id = None

    for sheet in sheets:
        title = sheet["properties"]["title"]
        sheet_id = sheet["properties"]["sheetId"]

        if title == "YouTube自動投稿":
            youtube_sheet_id = sheet_id
        else:
            requests.append({
                "deleteSheet": {"sheetId": sheet_id}
            })
            print(f"  削除予定: {title}")

    # 「YouTube自動投稿」がない場合は作成
    if youtube_sheet_id is None:
        print("  「YouTube自動投稿」シートを作成します")
        requests.append({
            "addSheet": {
                "properties": {"title": "YouTube自動投稿"}
            }
        })

    # 3. 「3チャンネル一覧」シートを追加
    requests.append({
        "addSheet": {
            "properties": {"title": "3チャンネル一覧"}
        }
    })

    if requests:
        print("\nシート操作を実行中...")
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": requests}
        ).execute()

    # 再取得してシートIDを確認
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheets = spreadsheet.get("sheets", [])

    youtube_sheet_id = None
    channel_sheet_id = None

    for sheet in sheets:
        title = sheet["properties"]["title"]
        sheet_id = sheet["properties"]["sheetId"]
        if title == "YouTube自動投稿":
            youtube_sheet_id = sheet_id
        elif title == "3チャンネル一覧":
            channel_sheet_id = sheet_id

    # 4. 「YouTube自動投稿」シートをクリアしてヘッダー設定
    print("\n「YouTube自動投稿」シートをセットアップ中...")

    # クリア
    service.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID,
        range="YouTube自動投稿!A:Z"
    ).execute()

    # ヘッダー設定
    headers = [
        ["テーマ", "モード", "ステータス", "チャンネル", "検索結果",
         "台本JSON", "記事URL", "音声URL", "YouTube URL", "処理時間"]
    ]

    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range="YouTube自動投稿!A1:J1",
        valueInputOption="RAW",
        body={"values": headers}
    ).execute()

    print("  ヘッダー設定完了")

    # 5. 「3チャンネル一覧」シートにデータ設定
    print("\n「3チャンネル一覧」シートをセットアップ中...")

    channel_data = [
        ["TOKEN", "メール", "チャンネル名"],
        ["23", "ftt357g@gmail.com", "ftt357g-チャンネル"],
        ["24", "kij876tge@gmail.com", "kij876tge-チャンネル"],
        ["27", "jyb475rt@gmail.com", "jyb475rt-チャンネル"],
    ]

    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range="3チャンネル一覧!A1:C4",
        valueInputOption="RAW",
        body={"values": channel_data}
    ).execute()

    print("  チャンネル一覧設定完了")

    # 6. 書式設定（ヘッダー行を太字に）
    print("\n書式設定中...")

    format_requests = [
        # YouTube自動投稿のヘッダー
        {
            "repeatCell": {
                "range": {
                    "sheetId": youtube_sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}
                    }
                },
                "fields": "userEnteredFormat(textFormat,backgroundColor)"
            }
        },
        # 3チャンネル一覧のヘッダー
        {
            "repeatCell": {
                "range": {
                    "sheetId": channel_sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}
                    }
                },
                "fields": "userEnteredFormat(textFormat,backgroundColor)"
            }
        },
        # 列幅調整（YouTube自動投稿）
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": youtube_sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": 10
                },
                "properties": {"pixelSize": 120},
                "fields": "pixelSize"
            }
        }
    ]

    service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": format_requests}
    ).execute()

    print("  書式設定完了")

    print("\n" + "=" * 50)
    print("セットアップ完了!")
    print(f"スプレッドシート: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")
    print("=" * 50)


if __name__ == "__main__":
    setup_spreadsheet()
