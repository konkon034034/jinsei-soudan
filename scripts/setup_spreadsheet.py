#!/usr/bin/env python3
import os
import json
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = '15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo'

def get_credentials():
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    creds_dict = json.loads(creds_json)
    return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

def main():
    creds = get_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    
    # チャンネル管理シート作成
    try:
        ws1 = sh.worksheet('チャンネル管理')
        ws1.clear()
        print("✅ チャンネル管理シート：既存をクリア")
    except:
        ws1 = sh.add_worksheet(title='チャンネル管理', rows=50, cols=10)
        print("✅ チャンネル管理シート：新規作成")
    
    channels = [
        ['チャンネル番号', 'トークン名', 'チャンネル名', 'ジャンル', '状態'],
        [1, 'TOKEN_1', '昭和の宝箱', '総合・歴史', '稼働中'],
        [2, 'TOKEN_2', '懐かしの歌謡曲ch', '音楽・演歌', '稼働中'],
        [3, 'TOKEN_3', '思い出ランキング', '社会・女性', '稼働中'],
        [4, 'TOKEN_4', '昭和スター名鑑', '芸能・俳優', '稼働中'],
        [5, 'TOKEN_5', '演歌の殿堂', '音楽・フォーク', '稼働中'],
        [6, 'TOKEN_6', '銀幕の思い出', '映画', '稼働中'],
        [7, 'TOKEN_7', '懐メロ天国', '音楽・アイドル', '稼働中'],
        [8, 'TOKEN_8', '朝ドラ大全集', 'ドラマ', '稼働中'],
        [9, 'TOKEN_9', '昭和プレイバック', '遊び・行事', '稼働中'],
        [10, 'TOKEN_10', '昭和ノスタルジア', '季節・自然', '稼働中'],
        [11, 'TOKEN_11', '黄金時代ch', '映画・特撮', '稼働中'],
        [12, 'TOKEN_12', '昭和ドラマ劇場', 'ドラマ・学園', '稼働中'],
        [13, 'TOKEN_13', '戦後日本の記憶', '戦争・復興', '稼働中'],
        [14, 'TOKEN_14', '昭和の学校', '教育・学校', '稼働中'],
        [15, 'TOKEN_15', '制服と校則ch', '教育・部活', '稼働中'],
        [16, 'TOKEN_16', '昭和の食卓', '給食・家庭料理', '稼働中'],
        [17, 'TOKEN_17', '昭和グルメ図鑑', '外食・お菓子', '稼働中'],
        [18, 'TOKEN_18', '昭和CM博覧会', 'CM・広告', '稼働中'],
        [19, 'TOKEN_19', 'CMソング大全', 'CM・企業', '稼働中'],
        [20, 'TOKEN_20', '昭和の暮らし', '家電・家具', '稼働中'],
        [21, 'TOKEN_21', '昭和の家族', '家庭・結婚', '稼働中'],
        [22, 'TOKEN_22', 'おしゃれ街道', '街・観光地', '稼働中'],
        [23, 'TOKEN_23', '昭和ファッション', '服・髪型', '稼働中'],
        [24, 'TOKEN_24', 'レトロビューティー', '化粧品・美容', '稼働中'],
        [25, 'TOKEN_25', '昭和スポーツ伝説', 'スポーツ', '稼働中'],
        [26, 'TOKEN_26', '昭和バラエティ', 'テレビ・番組', '稼働中'],
        [27, 'TOKEN_27', '激動の昭和史', '政治・経済', '稼働中'],
    ]
    ws1.update('A1', channels)
    print("✅ チャンネル管理データ書き込み完了")
    
    # ネタ管理シート作成
    try:
        ws2 = sh.worksheet('ネタ管理')
        ws2.clear()
        print("✅ ネタ管理シート：既存をクリア")
    except:
        ws2 = sh.add_worksheet(title='ネタ管理', rows=1000, cols=10)
        print("✅ ネタ管理シート：新規作成")
    
    header = [['ネタID', 'チャンネル番号', 'カテゴリ', '動画タイトル', 'ランキング数', '状態', '作成日', 'アップロード日']]
    ws2.update('A1', header)
    print("✅ ネタ管理ヘッダー書き込み完了")
    
    print("🎉 スプレッドシート設定完了！")

if __name__ == "__main__":
    main()
