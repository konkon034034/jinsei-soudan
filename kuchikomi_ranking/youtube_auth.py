#!/usr/bin/env python3
"""
口コミランキングチャンネル YouTube OAuth認証スクリプト
jyb475rt@gmail.com (TOKEN_27) 用

使い方:
1. このスクリプトを実行
2. 表示されたURLをシークレットウィンドウで開く
3. jyb475rt@gmail.com でログイン
4. 権限を許可
5. リダイレクトされたURLをコピーして貼り付け
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# 親ディレクトリの.envを読み込み
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]
REDIRECT_URI = "http://localhost:8080/"


def generate_auth_url():
    """認証URLを生成して表示"""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("❌ YOUTUBE_CLIENT_ID または YOUTUBE_CLIENT_SECRET が設定されていません")
        print("   .env ファイルを確認してください")
        return None

    # client_secrets.json を一時的に作成
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": [REDIRECT_URI],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    flow.redirect_uri = REDIRECT_URI

    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )

    print()
    print("=" * 70)
    print("口コミランキングチャンネル YouTube認証")
    print("=" * 70)
    print()
    print("⚠️  以下のURLをシークレットウィンドウで開いてください：")
    print()
    print(auth_url)
    print()
    print("=" * 70)
    print("👆 jyb475rt@gmail.com でログインして権限を許可")
    print()
    print("許可後、「このサイトにアクセスできません」と表示されますが正常です。")
    print("アドレスバーのURL（http://localhost:8080/?code=...）をコピーしてください。")
    print("=" * 70)

    return flow, state


def exchange_code_for_token(flow, redirect_url: str):
    """認証コードをトークンに交換"""
    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)

    if 'code' not in params:
        print("❌ 認証コードが見つかりません")
        return None

    code = params['code'][0]
    print(f"✓ 認証コードを取得しました")

    flow.fetch_token(code=code)
    creds = flow.credentials

    # refresh_token を表示
    print()
    print("=" * 70)
    print("✅ 認証成功！")
    print("=" * 70)
    print()
    print("以下の refresh_token を GitHub Secrets に設定してください:")
    print()
    print(f"YOUTUBE_REFRESH_TOKEN_27={creds.refresh_token}")
    print()
    print("=" * 70)

    return creds


def main():
    result = generate_auth_url()
    if not result:
        sys.exit(1)

    flow, state = result

    print()
    redirect_url = input("リダイレクトされたURLを貼り付けてください: ").strip()

    if not redirect_url:
        print("❌ URLが入力されませんでした")
        sys.exit(1)

    creds = exchange_code_for_token(flow, redirect_url)
    if not creds:
        sys.exit(1)

    # チャンネル情報を確認
    try:
        from googleapiclient.discovery import build
        youtube = build("youtube", "v3", credentials=creds)
        response = youtube.channels().list(part="snippet", mine=True).execute()

        if response.get("items"):
            channel = response["items"][0]
            print()
            print(f"認証されたチャンネル: {channel['snippet']['title']}")
            print(f"チャンネルID: {channel['id']}")
    except Exception as e:
        print(f"⚠️ チャンネル情報の取得に失敗: {e}")


if __name__ == "__main__":
    main()
