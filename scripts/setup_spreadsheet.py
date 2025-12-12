#!/usr/bin/env python3
"""30チャンネル スプレッドシート再構築"""

import gspread
from google.oauth2.service_account import Credentials
import json
import os
import time

SPREADSHEET_ID = '15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo'

CHANNELS = [
    (1, "kiuy1010sa@gmail.com", "昭和名車ランキング"),
    (2, "cvf334zy@gmail.com", "昭和鉄道ベスト"),
    (3, "10742kr@gmail.com", "昭和家電ランキング"),
    (4, "gug476ry@gmail.com", "昭和おもちゃ大全"),
    (5, "567trfs@gmail.com", "昭和お菓子ランキング"),
    (6, "usy35ft@gmail.com", "昭和ヒット曲ベスト"),
    (7, "gyg198gy@gmail.com", "昭和映画ランキング"),
    (8, "top23toonji@gmail.com", "昭和アイドル名鑑"),
    (9, "639jn467@gmail.com", "昭和俳優列伝"),
    (10, "hyg578gth@gmail.com", "昭和女優ベスト"),
    (11, "147rygfd@gmail.com", "昭和化粧品ランキング"),
    (12, "8108kdie@gmail.com", "昭和特撮ヒーロー"),
    (13, "juj565ft@gmail.com", "昭和朝ドラ名作選"),
    (14, "65ruohyx@gmail.com", "昭和野球名選手"),
    (15, "gyy169guj@gmail.com", "昭和建築ベスト"),
    (16, "bubu156bu@gmail.com", "昭和団地ランキング"),
    (17, "huh168ht@gmail.com", "昭和商店街の記憶"),
    (18, "13678dp@gmail.com", "昭和デパート物語"),
    (19, "34uy57tj@gmail.com", "昭和喫茶店ベスト"),
    (20, "hyhy368ryi@gmail.com", "昭和食堂ランキング"),
    (21, "kokop123kop@gmail.com", "昭和制服コレクション"),
    (22, "urvf476g@gmail.com", "昭和文房具ベスト"),
    (23, "jyb475rt@gmail.com", "昭和ゲームランキング"),
    (24, "kiuj98hj@gmail.com", "昭和CMベスト100"),
    (25, "369fsi@gmail.com", "昭和ポスター美術館"),
    (26, "09871gh@gmail.com", "昭和看板コレクション"),
    (27, "kij876tge@gmail.com", "昭和レコードベスト"),
    (28, "ftt357g@gmail.com", "昭和雑誌ランキング"),
    (29, "136gmw@gmail.com", "昭和美容室ベスト"),
    (30, "jei738ieb@gmail.com", "昭和家具ランキング"),
]

def main():
    sa_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not sa_json:
        print("❌ GOOGLE_SERVICE_ACCOUNT_JSON が設定されていません")
        return
    
    creds = Credentials.from_service_account_info(
        json.loads(sa_json),
        scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    )
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    print(f"✅ スプレッドシート '{spreadsheet.title}' を開きました")
    
    existing = [ws.title for ws in spreadsheet.worksheets()]
    print(f"📋 現在のシート: {existing}")
    
    # 30チャンネル一覧を先に作成
    if "30チャンネル一覧" not in existing:
        spreadsheet.add_worksheet(title="30チャンネル一覧", rows=35, cols=10)
        print("✅ 30チャンネル一覧 作成")
        time.sleep(1)
    
    # 古いシート削除
    print("\n🗑️ 古いシート削除中...")
    for name in [ws.title for ws in spreadsheet.worksheets()]:
        if name != "30チャンネル一覧":
            spreadsheet.del_worksheet(spreadsheet.worksheet(name))
            print(f"  🗑️ {name}")
            time.sleep(0.5)
    
    # 30チャンネル一覧にデータ入力
    print("\n📊 30チャンネル一覧 データ入力...")
    ws = spreadsheet.worksheet("30チャンネル一覧")
    data = [["TOKEN番号", "メールアドレス", "チャンネル名", "シート名"]]
    for n, email, ch in CHANNELS:
        data.append([f"TOKEN_{n}", email, ch, f"ch{n}"])
    ws.clear()
    ws.update('A1', data)
    
    # ch1〜ch30 作成
    print("\n📝 ch1〜ch30 作成中...")
    for i in range(1, 31):
        ws = spreadsheet.add_worksheet(title=f"ch{i}", rows=100, cols=10)
        ws.update('A1:D1', [['タイトル', 'ステータス', '作成日', '動画URL']])
        print(f"  ✅ ch{i}")
        time.sleep(0.3)
    
    print(f"\n🎉 完了！ https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")

if __name__ == '__main__':
    main()
