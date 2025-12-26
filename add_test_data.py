#!/usr/bin/env python3
"""
スプレッドシートにテストデータを追加
"""

import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SPREADSHEET_ID = "15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo"
SHEET_NAME = "YouTube自動投稿"


def get_credentials():
    """Google認証情報を取得"""
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if not creds_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY が設定されていません")

    creds_info = json.loads(creds_json)
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    return Credentials.from_service_account_info(creds_info, scopes=scopes)


def setup_test_data():
    """テストデータをセットアップ"""
    service = build("sheets", "v4", credentials=get_credentials())

    print("=" * 50)
    print("スプレッドシートテストデータ追加")
    print("=" * 50)

    # 1. 既存データをクリア（A2以降）
    print("\n[1/3] 既存データをクリア中...")
    service.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A2:Z1000"
    ).execute()
    print("  完了")

    # 2. ヘッダー行を設定
    print("\n[2/3] ヘッダー行を設定中...")
    headers = [[
        "テーマ", "モード", "ステータス", "チャンネル", "日時",
        "台本JSON", "生成音声URL", "音声URL", "YouTube URL", "処理時間"
    ]]

    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1:J1",
        valueInputOption="RAW",
        body={"values": headers}
    ).execute()
    print("  完了")

    # 3. テストデータを追加
    print("\n[3/3] テストデータを追加中...")
    test_data = [
        ["朝ドラ 泣ける話TOP10", "AUTO", "PENDING", "23"],
        ["朝ドラ 美人ヒロインTOP10", "AUTO", "PENDING", "24"],
        ["朝ドラ 名セリフランキング", "AUTO", "PENDING", "27"],
    ]

    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A2:D4",
        valueInputOption="RAW",
        body={"values": test_data}
    ).execute()
    print("  完了")

    # 確認
    print("\n" + "=" * 50)
    print("セットアップ完了!")
    print(f"スプレッドシート: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")
    print("=" * 50)

    # 追加したデータを表示
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1:J5"
    ).execute()

    print("\n【現在のデータ】")
    for i, row in enumerate(result.get("values", [])):
        print(f"  行{i+1}: {row}")


if __name__ == "__main__":
    setup_test_data()
