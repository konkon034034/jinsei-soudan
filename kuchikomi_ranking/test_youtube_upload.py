#!/usr/bin/env python3
"""
口コミランキングチャンネル アップロードテスト
TOKEN_27 (jyb475rt@gmail.com) を使用
"""

import os
import sys
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


def get_youtube_client():
    """YouTube API クライアントを取得（TOKEN_27用）"""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN_27")

    if not all([client_id, client_secret, refresh_token]):
        print("❌ YouTube認証情報が不足しています")
        print(f"  CLIENT_ID: {'設定済み' if client_id else '未設定'}")
        print(f"  CLIENT_SECRET: {'設定済み' if client_secret else '未設定'}")
        print(f"  REFRESH_TOKEN_27: {'設定済み' if refresh_token else '未設定'}")
        return None

    # アクセストークン取得
    response = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    })

    if response.status_code != 200:
        print(f"❌ トークン取得失敗: {response.text}")
        return None

    access_token = response.json()["access_token"]

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token"
    )
    return build("youtube", "v3", credentials=creds)


def upload_video(youtube, video_path: str, title: str, description: str, private: bool = True):
    """動画をアップロード"""
    if not os.path.exists(video_path):
        print(f"❌ 動画ファイルが見つかりません: {video_path}")
        return None

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "22"  # People & Blogs
        },
        "status": {
            "privacyStatus": "private" if private else "public",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        resumable=True
    )

    print(f"📤 アップロード中: {title}")

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = request.execute()
    video_id = response.get("id")
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    print(f"✅ アップロード完了!")
    print(f"  動画ID: {video_id}")
    print(f"  URL: {video_url}")
    print(f"  公開設定: {'非公開' if private else '公開'}")

    return video_id


def delete_video(youtube, video_id: str):
    """動画を削除"""
    try:
        youtube.videos().delete(id=video_id).execute()
        print(f"🗑️ 動画を削除しました: {video_id}")
        return True
    except Exception as e:
        print(f"⚠️ 削除エラー: {e}")
        return False


def main():
    print("=" * 50)
    print("口コミランキングチャンネル アップロードテスト")
    print("=" * 50)

    # YouTube クライアント取得
    youtube = get_youtube_client()
    if not youtube:
        sys.exit(1)

    print("✅ YouTube API 接続成功")

    # チャンネル情報を取得して確認
    try:
        channel_response = youtube.channels().list(
            part="snippet",
            mine=True
        ).execute()

        if channel_response.get("items"):
            channel = channel_response["items"][0]
            print(f"✅ チャンネル: {channel['snippet']['title']}")
        else:
            print("⚠️ チャンネル情報を取得できません")
    except Exception as e:
        print(f"⚠️ チャンネル確認エラー: {e}")

    # テスト動画をアップロード
    video_path = "test_upload.mp4"
    if not os.path.exists(video_path):
        print(f"❌ テスト動画がありません: {video_path}")
        sys.exit(1)

    video_id = upload_video(
        youtube,
        video_path,
        title="【テスト】口コミランキング システムテスト",
        description="システムテスト用動画です。自動的に削除されます。",
        private=True
    )

    if video_id:
        print("\n" + "=" * 50)
        print("テスト完了！")
        print("=" * 50)

        # 削除するか確認（環境変数で制御）
        if os.environ.get("AUTO_DELETE", "false").lower() == "true":
            print("\n動画を削除中...")
            delete_video(youtube, video_id)
        else:
            print("\n動画は非公開で残っています。")
            print("手動で削除するか、AUTO_DELETE=true で再実行してください。")


if __name__ == "__main__":
    main()
