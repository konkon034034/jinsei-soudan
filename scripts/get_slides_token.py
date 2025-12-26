#!/usr/bin/env python3
"""
Google Slides API用のOAuthトークンを取得

環境変数:
  YOUTUBE_CLIENT_ID: Google OAuth client ID
  YOUTUBE_CLIENT_SECRET: Google OAuth client secret
"""

import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    'https://www.googleapis.com/auth/presentations',
    'https://www.googleapis.com/auth/drive'
]

def get_client_config():
    """環境変数からクライアント設定を取得"""
    client_id = os.environ.get('YOUTUBE_CLIENT_ID')
    client_secret = os.environ.get('YOUTUBE_CLIENT_SECRET')

    if not client_id or not client_secret:
        raise ValueError(
            "環境変数が設定されていません。\n"
            ".envファイルにYOUTUBE_CLIENT_IDとYOUTUBE_CLIENT_SECRETを設定してください。"
        )

    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"]
        }
    }

def main():
    print("Google Slides API用のトークンを取得します...")
    print("ブラウザが開いたらGoogleアカウントでログインしてください。\n")

    client_config = get_client_config()
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    credentials = flow.run_local_server(port=8080)

    token_data = {
        "access_token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "client_id": client_config["installed"]["client_id"],
        "client_secret": client_config["installed"]["client_secret"]
    }

    print("\n=== トークン取得成功 ===")
    print("\n以下を .env の TOKEN_SLIDES に追加してください:\n")
    print(f"TOKEN_SLIDES={json.dumps(token_data)}")

    # 自動で.envに追加するか確認
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    with open(env_path, 'a') as f:
        f.write(f"\nTOKEN_SLIDES={json.dumps(token_data)}\n")
    print(f"\n✅ {env_path} に追加しました")

if __name__ == '__main__':
    main()
