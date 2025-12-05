#!/usr/bin/env python3
"""スプレッドシートにシート（タブ）を追加"""

import os
import json
import gspread
from google.oauth2.service_account import Credentials

# スプレッドシートID
SPREADSHEET_ID = "15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo"

# 認証
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# 環境変数からサービスアカウントキーを取得
sa_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
if not sa_key:
    raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY が設定されていません")

creds_dict = json.loads(sa_key)
creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

gc = gspread.authorize(creds)

# スプレッドシートを開く
print(f"スプレッドシートを開いています...")
spreadsheet = gc.open_by_key(SPREADSHEET_ID)

# 既存のシート名を確認
existing_sheets = [ws.title for ws in spreadsheet.worksheets()]
print(f"既存のシート: {existing_sheets}")

# ヘッダー行
HEADERS = ["video_id", "title", "status", "script", "audio_path", "video_path", "video_url", "created_at", "updated_at"]

# 追加するシート
sheets_to_add = ["人生相談", "電話相談", "人間関係相談"]

for sheet_name in sheets_to_add:
    if sheet_name in existing_sheets:
        print(f"✓ '{sheet_name}' は既に存在します")
    else:
        print(f"+ '{sheet_name}' を作成中...")
        worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=10)
        # ヘッダーを追加
        worksheet.update('A1:I1', [HEADERS])
        print(f"✓ '{sheet_name}' を作成しました")

# 最初のシート（シート1）が残っていたら削除
worksheets = spreadsheet.worksheets()
for ws in worksheets:
    if ws.title == "シート1" or ws.title == "Sheet1":
        print(f"- '{ws.title}' を削除中...")
        spreadsheet.del_worksheet(ws)
        print(f"✓ 削除完了")

print("\n=== 完了 ===")
final_sheets = [ws.title for ws in spreadsheet.worksheets()]
print(f"最終的なシート: {final_sheets}")
