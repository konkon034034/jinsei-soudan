#!/usr/bin/env python3
"""
YouTube自動アップロードスクリプト

生成された動画を10742krチャンネルにアップロードする。
OAuth2認証を使用してYouTube Data API v3でアップロード。

認証方法:
1. 環境変数 YOUTUBE_REFRESH_TOKEN_3 + YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET
2. ローカルの youtube_credentials.json + youtube_token.pickle
"""

import os
import sys
import json
import pickle
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# .envファイルを読み込み
load_dotenv()

# 定数
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
CREDENTIALS_FILE = DATA_DIR / "youtube_credentials.json"
TOKEN_FILE = DATA_DIR / "youtube_token.pickle"

# YouTube API設定
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"

# 環境変数から認証情報を取得（10742kr用: YOUTUBE_REFRESH_TOKEN_3）
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN_3")  # 10742kr

# デフォルトアップロード設定
DEFAULT_CATEGORY = "22"  # People & Blogs
DEFAULT_PRIVACY = "public"  # public, private, unlisted


def refresh_token_with_request(refresh_token: str, client_id: str, client_secret: str) -> dict | None:
    """リフレッシュトークンを使って新しいアクセストークンを取得"""
    import requests

    try:
        response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30
        )

        if response.status_code == 200:
            return response.json()
        else:
            print(f"❌ トークンリフレッシュ失敗: {response.status_code}")
            print(f"   {response.text}")
            return None
    except Exception as e:
        print(f"❌ トークンリフレッシュエラー: {e}")
        return None


def get_auth_url(client_id: str) -> str:
    """OAuth認証URLを生成"""
    from urllib.parse import urlencode

    params = {
        "client_id": client_id,
        "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def get_authenticated_service():
    """YouTube API認証済みサービスを取得"""
    credentials = None

    # 方法1: 環境変数からリフレッシュトークンを使用（優先）
    if YOUTUBE_REFRESH_TOKEN and YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET:
        print("🔐 環境変数から認証情報を使用（10742kr）")

        # リフレッシュトークンで新しいアクセストークンを取得
        token_data = refresh_token_with_request(
            YOUTUBE_REFRESH_TOKEN,
            YOUTUBE_CLIENT_ID,
            YOUTUBE_CLIENT_SECRET
        )

        if token_data and "access_token" in token_data:
            print("✅ トークン取得成功")
            credentials = Credentials(
                token=token_data["access_token"],
                refresh_token=YOUTUBE_REFRESH_TOKEN,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=YOUTUBE_CLIENT_ID,
                client_secret=YOUTUBE_CLIENT_SECRET,
                scopes=SCOPES
            )
        else:
            print("❌ 環境変数のリフレッシュトークンが無効です")
            print("")
            print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            print("🔑 再認証が必要です")
            print("")
            print("以下のURLをシークレットウィンドウで開いてください：")
            print("")
            auth_url = get_auth_url(YOUTUBE_CLIENT_ID)
            print(auth_url)
            print("")
            print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return None

    # 方法2: ローカルファイルから認証
    if not credentials:
        # 保存済みトークンがあれば読み込み
        if TOKEN_FILE.exists():
            with open(TOKEN_FILE, "rb") as f:
                credentials = pickle.load(f)
            print(f"📂 保存済みトークンを読み込み: {TOKEN_FILE}")

        # トークンがないか期限切れの場合
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                print("🔄 トークンを更新中...")
                try:
                    credentials.refresh(Request())
                    print("✅ トークン更新成功")
                    # 更新したトークンを保存
                    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
                    with open(TOKEN_FILE, "wb") as f:
                        pickle.dump(credentials, f)
                    print(f"💾 トークンを保存: {TOKEN_FILE}")
                except Exception as e:
                    print(f"❌ トークン更新失敗: {e}")
                    print("")
                    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    print("🔑 再認証が必要です")
                    print("")
                    if YOUTUBE_CLIENT_ID:
                        print("以下のURLをシークレットウィンドウで開いてください：")
                        print("")
                        auth_url = get_auth_url(YOUTUBE_CLIENT_ID)
                        print(auth_url)
                    else:
                        print("環境変数 YOUTUBE_CLIENT_ID を設定してください")
                    print("")
                    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    return None
            else:
                if not CREDENTIALS_FILE.exists():
                    print(f"❌ エラー: 認証情報が見つかりません")
                    print("   環境変数 YOUTUBE_REFRESH_TOKEN_3, YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET を設定するか、")
                    print(f"   {CREDENTIALS_FILE} を配置してください")
                    return None

                print("🔐 YouTube認証を開始...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS_FILE), SCOPES
                )
                credentials = flow.run_local_server(port=8080)

                # トークンを保存
                TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(TOKEN_FILE, "wb") as f:
                    pickle.dump(credentials, f)
                print(f"💾 トークンを保存: {TOKEN_FILE}")

    if not credentials:
        return None

    return build(API_SERVICE_NAME, API_VERSION, credentials=credentials)


def generate_title_and_description(talk_script_path: Path = None) -> tuple[str, str]:
    """台本からタイトルと説明文を生成"""
    talk_json = DATA_DIR / "talk_script.json"

    if talk_script_path and talk_script_path.exists():
        talk_json = talk_script_path

    title = "ランキング動画"
    description = "カツミとヒロシがランキングについて雑談する動画です。"

    if talk_json.exists():
        try:
            with open(talk_json, "r", encoding="utf-8") as f:
                script = json.load(f)

            # タイトルを取得
            if script.get("title"):
                title = script["title"]

            # 説明文を生成
            lines = script.get("lines", [])
            if lines:
                # 最初の数行を抜粋
                preview_lines = []
                for line in lines[:5]:
                    speaker = line.get("speaker", "")
                    text = line.get("text", "")
                    preview_lines.append(f"{speaker}: {text}")

                description = f"""カツミとヒロシの雑談ランキング動画

【内容プレビュー】
{chr(10).join(preview_lines)}
...

#ランキング #雑談 #カツミ #ヒロシ
"""

        except Exception as e:
            print(f"⚠️ 台本読み込みエラー: {e}")

    # タイトルの長さ制限（100文字）
    if len(title) > 100:
        title = title[:97] + "..."

    return title, description


def upload_video(
    video_path: str,
    title: str = None,
    description: str = None,
    tags: list = None,
    category: str = DEFAULT_CATEGORY,
    privacy: str = DEFAULT_PRIVACY
) -> str | None:
    """動画をYouTubeにアップロード"""

    if not os.path.exists(video_path):
        print(f"❌ エラー: 動画ファイルが見つかりません: {video_path}")
        return None

    # タイトルと説明文を生成
    if not title or not description:
        gen_title, gen_description = generate_title_and_description()
        title = title or gen_title
        description = description or gen_description

    # デフォルトタグ
    if not tags:
        tags = ["ランキング", "雑談", "カツミ", "ヒロシ", "横スクロール"]

    print(f"\n📤 YouTube アップロード開始")
    print(f"   タイトル: {title}")
    print(f"   ファイル: {video_path}")
    print(f"   公開設定: {privacy}")

    # YouTube APIサービスを取得
    youtube = get_authenticated_service()
    if not youtube:
        return None

    # 動画メタデータ
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        }
    }

    # アップロード
    try:
        media = MediaFileUpload(
            video_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=1024 * 1024  # 1MB chunks
        )

        request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media
        )

        response = None
        print("   アップロード中...")

        while response is None:
            status, response = request.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                print(f"   進捗: {progress}%")

        video_id = response["id"]
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        print(f"\n✅ アップロード完了！")
        print(f"   動画ID: {video_id}")
        print(f"   URL: {video_url}")

        return video_url

    except HttpError as e:
        print(f"❌ YouTube APIエラー: {e}")
        return None
    except Exception as e:
        print(f"❌ アップロードエラー: {e}")
        return None


def find_latest_video() -> Path | None:
    """最新の生成動画を検索"""
    output_dir = SCRIPT_DIR / "output"

    if not output_dir.exists():
        return None

    # ranking_final_*.mp4 または ranking_*.mp4 を検索
    videos = list(output_dir.glob("ranking_final_*.mp4"))
    if not videos:
        videos = list(output_dir.glob("ranking_*.mp4"))

    if not videos:
        return None

    # 最新のファイルを返す
    return max(videos, key=lambda p: p.stat().st_mtime)


def main():
    """メイン処理"""
    # 引数から動画パスを取得、なければ最新の動画を使用
    if len(sys.argv) > 1:
        video_path = Path(sys.argv[1])
    else:
        video_path = find_latest_video()

    if not video_path or not video_path.exists():
        print("❌ エラー: アップロードする動画が見つかりません")
        print("使い方: python youtube_upload.py <動画ファイルパス>")
        sys.exit(1)

    print(f"🎬 動画ファイル: {video_path}")

    # アップロード
    video_url = upload_video(str(video_path))

    if video_url:
        print(f"\n🎉 アップロード成功！")
        print(f"   {video_url}")

        # 結果をファイルに保存
        result_file = DATA_DIR / "last_upload.json"
        result = {
            "timestamp": datetime.now().isoformat(),
            "video_path": str(video_path),
            "video_url": video_url,
        }
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    else:
        print("\n❌ アップロード失敗")
        sys.exit(1)


if __name__ == "__main__":
    main()
