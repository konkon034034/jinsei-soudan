#!/usr/bin/env python3
"""
YouTube OAuth Token Generator
Run this script to get OAuth tokens for YouTube API access.

Required environment variables:
  YOUTUBE_CLIENT_ID: Google OAuth client ID
  YOUTUBE_CLIENT_SECRET: Google OAuth client secret
"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

# Load .env file from project root
load_dotenv(Path(__file__).parent.parent / '.env')

# YouTube API scopes (upload + comments + full access)
SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',      # 動画アップロード
    'https://www.googleapis.com/auth/youtube.force-ssl',   # コメント投稿
    'https://www.googleapis.com/auth/youtube',             # フルアクセス
]

def get_client_config():
    """Get client config from environment variables."""
    client_id = os.environ.get('YOUTUBE_CLIENT_ID')
    client_secret = os.environ.get('YOUTUBE_CLIENT_SECRET')

    if not client_id or not client_secret:
        raise ValueError(
            "Missing required environment variables.\n"
            "Please set YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in your .env file."
        )

    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost:8080/", "urn:ietf:wg:oauth:2.0:oob"]
        }
    }

def main():
    print("=" * 60)
    print("YouTube OAuth Token Generator")
    print("=" * 60)
    print()

    # Get client config from environment
    client_config = get_client_config()

    # Create flow from client config
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

    # Set redirect URI explicitly
    flow.redirect_uri = 'http://localhost:8080/'

    # Generate authorization URL without opening browser
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        prompt='consent'
    )

    print("\n👉 このURLをブラウザにコピペ:\n")
    print(auth_url)
    print("\n" + "=" * 60)
    print("認証後、リダイレクトされたURLをここに貼り付けてください：")
    print("（例: http://localhost:8080/?code=4/0A...）")
    print("=" * 60)

    redirect_response = input().strip()

    # Fetch token from redirect response
    flow.fetch_token(authorization_response=redirect_response)
    credentials = flow.credentials

    # Create token JSON for .env file
    token_data = {
        "access_token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "client_id": client_config["web"]["client_id"],
        "client_secret": client_config["web"]["client_secret"]
    }

    token_json = json.dumps(token_data)

    print()
    print("=" * 60)
    print("SUCCESS! Token obtained.")
    print("=" * 60)
    print()
    print("【Refresh Token】")
    print(credentials.refresh_token)
    print()
    print("【GitHub Secrets に設定】")
    print("  gh secret set YOUTUBE_REFRESH_TOKEN_23")
    print("  # 上記コマンド実行後、Refresh Token を貼り付け")
    print()
    print("【.env ファイル用（オプション）】")
    print(f"TOKEN_23={token_json}")
    print()
    print("=" * 60)

    # Also save to a file for convenience
    with open('youtube_token.json', 'w') as f:
        json.dump(token_data, f, indent=2)
    print("Token also saved to: youtube_token.json")

if __name__ == "__main__":
    main()
