#!/usr/bin/env python3
"""
ランダム動画選択スクリプト

登録済みチャンネルからランダムに1つ選び、
ランキング関連の動画を取得してDiscordに通知する。
"""

import json
import os
import random
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from googleapiclient.discovery import build

# .envファイルを読み込み
load_dotenv()

# 環境変数
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

# 定数
SCRIPT_DIR = Path(__file__).parent
CHANNELS_JSON = SCRIPT_DIR / "data" / "channels.json"

# ランキング動画を判定するキーワード
RANKING_KEYWORDS = ["ランキング", "TOP", "位", "選"]


def load_channels() -> list[dict]:
    """チャンネルJSONを読み込む"""
    with open(CHANNELS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def get_latest_videos(youtube, channel_id: str, max_results: int = 10) -> list[dict]:
    """指定チャンネルの最新動画を取得"""
    # チャンネルの動画をsearch.listで取得
    request = youtube.search().list(
        part="snippet",
        channelId=channel_id,
        order="date",
        type="video",
        maxResults=max_results,
    )
    response = request.execute()

    videos = []
    for item in response.get("items", []):
        videos.append(
            {
                "video_id": item["id"]["videoId"],
                "title": item["snippet"]["title"],
                "description": item["snippet"]["description"],
                "published_at": item["snippet"]["publishedAt"],
                "thumbnail": item["snippet"]["thumbnails"]["high"]["url"],
                "channel_title": item["snippet"]["channelTitle"],
            }
        )
    return videos


def filter_ranking_videos(videos: list[dict]) -> list[dict]:
    """ランキング関連の動画をフィルタリング"""
    ranking_videos = []
    for video in videos:
        title = video["title"]
        # キーワードが含まれているかチェック
        if any(keyword in title for keyword in RANKING_KEYWORDS):
            ranking_videos.append(video)
    return ranking_videos


def send_discord_notification(
    channel_name: str,
    video: dict,
    all_videos_count: int,
    ranking_videos_count: int,
) -> bool:
    """Discord Webhookで通知を送信"""
    if not DISCORD_WEBHOOK:
        print("DISCORD_WEBHOOK が設定されていません")
        return False

    video_url = f"https://www.youtube.com/watch?v={video['video_id']}"

    embed = {
        "title": "🎬 ランキング動画を発見！",
        "color": 0xFF0000,  # 赤色
        "fields": [
            {"name": "チャンネル", "value": channel_name, "inline": True},
            {
                "name": "検索結果",
                "value": f"{all_videos_count}本中 {ranking_videos_count}本がランキング動画",
                "inline": True,
            },
            {"name": "動画タイトル", "value": video["title"], "inline": False},
            {"name": "URL", "value": video_url, "inline": False},
        ],
        "thumbnail": {"url": video["thumbnail"]},
        "footer": {"text": f"公開日: {video['published_at'][:10]}"},
    }

    payload = {"embeds": [embed]}

    try:
        response = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"Discord通知エラー: {e}")
        return False


def send_no_video_notification(channel_name: str, all_videos_count: int) -> bool:
    """ランキング動画が見つからなかった場合の通知"""
    if not DISCORD_WEBHOOK:
        print("DISCORD_WEBHOOK が設定されていません")
        return False

    embed = {
        "title": "❌ ランキング動画が見つかりませんでした",
        "color": 0x808080,  # グレー
        "fields": [
            {"name": "チャンネル", "value": channel_name, "inline": True},
            {"name": "検索した動画数", "value": str(all_videos_count), "inline": True},
        ],
        "footer": {"text": "別のチャンネルで再試行してください"},
    }

    payload = {"embeds": [embed]}

    try:
        response = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"Discord通知エラー: {e}")
        return False


def main():
    # 環境変数チェック
    if not YOUTUBE_API_KEY:
        print("エラー: YOUTUBE_API_KEY が設定されていません")
        sys.exit(1)

    # チャンネル読み込み
    channels = load_channels()
    if not channels:
        print("エラー: チャンネルが登録されていません")
        sys.exit(1)

    # ランダムに1チャンネル選択
    selected_channel = random.choice(channels)
    channel_id = selected_channel["channel_id"]
    channel_name = selected_channel["channel_name"]

    print(f"選択されたチャンネル: {channel_name}")
    print(f"チャンネルID: {channel_id}")

    # YouTube API クライアント作成
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    # 最新動画を取得
    print("最新動画を取得中...")
    videos = get_latest_videos(youtube, channel_id)
    print(f"取得した動画数: {len(videos)}")

    # ランキング動画をフィルタリング
    ranking_videos = filter_ranking_videos(videos)
    print(f"ランキング動画数: {len(ranking_videos)}")

    if ranking_videos:
        # ランダムに1つ選択
        selected_video = random.choice(ranking_videos)
        print(f"\n選択された動画: {selected_video['title']}")
        print(f"URL: https://www.youtube.com/watch?v={selected_video['video_id']}")

        # Discord通知
        send_discord_notification(
            channel_name, selected_video, len(videos), len(ranking_videos)
        )
    else:
        print("\nランキング動画が見つかりませんでした")
        send_no_video_notification(channel_name, len(videos))


if __name__ == "__main__":
    main()
