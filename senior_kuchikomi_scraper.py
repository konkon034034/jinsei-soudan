#!/usr/bin/env python3
"""
口コミランキング台本自動生成スクリプト

競合チャンネルから人気動画を取得→字幕取得→Geminiでリライト→台本JSON出力
"""

import os
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# YouTube Data API
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# YouTube字幕取得
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

# Gemini API
import google.generativeai as genai

# 設定
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ファイルパス
SCRIPT_DIR = Path(__file__).parent
CHANNELS_FILE = SCRIPT_DIR / "youtube_channels.json"
OUTPUT_DIR = SCRIPT_DIR / "scripts"


def load_channels() -> list:
    """チャンネル情報を読み込み"""
    if not CHANNELS_FILE.exists():
        print(f"❌ チャンネルファイルが見つかりません: {CHANNELS_FILE}")
        return []

    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # チャンネルリストを取得
    channels = data if isinstance(data, list) else data.get("channels", [])
    print(f"📺 {len(channels)}チャンネルを読み込み")
    return channels


def get_youtube_service():
    """YouTube Data API サービスを取得"""
    if not YOUTUBE_API_KEY:
        raise ValueError("YOUTUBE_API_KEY が設定されていません")
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def get_channel_id_from_handle(handle: str) -> Optional[str]:
    """ハンドル（@username）からチャンネルIDを取得"""
    youtube = get_youtube_service()

    # @を除去
    handle_clean = handle.lstrip("@")

    try:
        # forHandle パラメータでチャンネルを検索
        response = youtube.channels().list(
            part="id,snippet",
            forHandle=handle_clean
        ).execute()

        if response.get("items"):
            channel_id = response["items"][0]["id"]
            channel_title = response["items"][0]["snippet"]["title"]
            print(f"   ✓ チャンネルID取得: {channel_id} ({channel_title})")
            return channel_id

        # forHandleが効かない場合、検索で試す
        search_response = youtube.search().list(
            part="snippet",
            q=handle_clean,
            type="channel",
            maxResults=1
        ).execute()

        if search_response.get("items"):
            channel_id = search_response["items"][0]["snippet"]["channelId"]
            print(f"   ✓ チャンネルID取得（検索）: {channel_id}")
            return channel_id

    except HttpError as e:
        print(f"   ⚠ チャンネルID取得エラー: {e}")

    return None


def get_popular_videos(channel_id: str, max_results: int = 10) -> list:
    """チャンネルの人気動画を取得"""
    youtube = get_youtube_service()

    try:
        # チャンネルの動画を検索（再生回数順）
        search_response = youtube.search().list(
            part="id,snippet",
            channelId=channel_id,
            type="video",
            order="viewCount",
            maxResults=max_results,
            publishedAfter=(datetime.now() - timedelta(days=365)).isoformat() + "Z"
        ).execute()

        videos = []
        for item in search_response.get("items", []):
            video_id = item["id"]["videoId"]
            snippet = item["snippet"]

            # 動画の詳細情報を取得
            video_response = youtube.videos().list(
                part="statistics,contentDetails",
                id=video_id
            ).execute()

            if video_response["items"]:
                stats = video_response["items"][0].get("statistics", {})
                videos.append({
                    "video_id": video_id,
                    "title": snippet["title"],
                    "channel_title": snippet["channelTitle"],
                    "published_at": snippet["publishedAt"],
                    "view_count": int(stats.get("viewCount", 0)),
                    "like_count": int(stats.get("likeCount", 0)),
                })

        # 再生回数順にソート
        videos.sort(key=lambda x: x["view_count"], reverse=True)
        return videos

    except HttpError as e:
        print(f"❌ YouTube API エラー: {e}")
        return []


def get_video_transcript(video_id: str) -> Optional[str]:
    """動画の字幕を取得（youtube-transcript-api v1.2.x対応）"""
    api = YouTubeTranscriptApi()

    try:
        # 字幕リストを取得
        transcript_list = api.list(video_id)

        # 日本語字幕を探す
        transcript = None
        for t in transcript_list:
            if t.language_code in ['ja', 'ja-JP']:
                transcript = t
                break

        # なければ自動生成を探す
        if not transcript:
            for t in transcript_list:
                if t.is_generated and t.language_code in ['ja', 'ja-JP']:
                    transcript = t
                    break

        # なければ英語
        if not transcript:
            for t in transcript_list:
                if t.language_code == 'en':
                    transcript = t
                    break

        if transcript:
            # 字幕をフェッチ
            fetched = transcript.fetch()
            text = " ".join([snippet.text for snippet in fetched])
            return text

    except (TranscriptsDisabled, NoTranscriptFound):
        print(f"  ⚠ 字幕なし: {video_id}")
        return None
    except Exception as e:
        print(f"  ⚠ 字幕取得エラー: {e}")
        return None

    return None


def rewrite_with_gemini(original_text: str, video_title: str) -> Optional[dict]:
    """Geminiで口コミ台本をリライト"""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY が設定されていません")

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash-exp")

    prompt = f"""以下の動画字幕を参考に、口コミランキング動画用の台本を作成してください。

【元動画タイトル】
{video_title}

【字幕テキスト（参考）】
{original_text[:5000]}  # 長すぎる場合は切り詰め

【出力形式】
以下のJSON形式で出力してください。5つの口コミを作成。

```json
{{
  "theme": "テーマ名（例：買ってよかったもの）",
  "kuchikomi": [
    {{
      "rank": 5,
      "item": "商品/サービス名",
      "rating": 4,
      "review_text": "口コミ本文（50-100文字）",
      "talks": [
        {{"speaker": "katsumi", "text": "カツミのセリフ"}},
        {{"speaker": "hiroshi", "text": "ヒロシのセリフ"}},
        {{"speaker": "katsumi", "text": "カツミのセリフ"}}
      ]
    }},
    // ... 5位から1位まで
  ]
}}
```

【ルール】
- 口コミは5位から1位の順で5つ
- 各口コミに3-5個のトーク（カツミとヒロシの掛け合い）
- カツミ（女性、明るい）とヒロシ（男性、落ち着いた）
- 元の内容を参考にしつつ、完全にオリジナルの文章で
- 著作権に配慮し、固有名詞は一般化
- JSONのみ出力（説明不要）
"""

    try:
        response = model.generate_content(prompt)
        text = response.text

        # JSONを抽出
        json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = text

        return json.loads(json_str)

    except Exception as e:
        print(f"❌ Gemini API エラー: {e}")
        return None


def process_channel(channel: dict) -> Optional[dict]:
    """1チャンネルを処理"""
    channel_id = channel.get("channel_id") or channel.get("id")
    channel_name = channel.get("name") or channel.get("channel_name", "Unknown")
    handle = channel.get("handle")

    print(f"\n📺 処理中: {channel_name}")

    # channel_idがなければhandleから取得
    if not channel_id and handle:
        print(f"   ハンドル: {handle}")
        channel_id = get_channel_id_from_handle(handle)

    if not channel_id:
        print(f"   ⚠ チャンネルIDを取得できません")
        return None

    print(f"   ID: {channel_id}")

    # 人気動画を取得
    videos = get_popular_videos(channel_id, max_results=5)
    if not videos:
        print(f"   ⚠ 動画が見つかりません")
        return None

    print(f"   📹 {len(videos)}本の動画を取得")

    # 最も人気の動画から字幕を取得
    for video in videos:
        print(f"   🎬 {video['title'][:40]}...")
        print(f"      再生回数: {video['view_count']:,}")

        transcript = get_video_transcript(video["video_id"])
        if transcript:
            print(f"      ✓ 字幕取得成功 ({len(transcript)}文字)")

            # Geminiでリライト
            script = rewrite_with_gemini(transcript, video["title"])
            if script:
                script["source"] = {
                    "channel_name": channel_name,
                    "video_id": video["video_id"],
                    "video_title": video["title"],
                    "view_count": video["view_count"],
                }
                return script

    return None


def main():
    """メイン処理"""
    print("=" * 50)
    print("🎯 口コミランキング台本自動生成")
    print("=" * 50)

    # チャンネル読み込み
    channels = load_channels()
    if not channels:
        print("❌ チャンネルが読み込めません")
        return

    # 出力ディレクトリ作成
    OUTPUT_DIR.mkdir(exist_ok=True)

    # 各チャンネルを処理
    scripts = []
    for channel in channels[:3]:  # テスト用に3チャンネルまで
        script = process_channel(channel)
        if script:
            scripts.append(script)
            print(f"   ✅ 台本生成成功: {script.get('theme', 'Unknown')}")

    if not scripts:
        print("\n❌ 台本を生成できませんでした")
        return

    # 結果を保存
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"kuchikomi_scripts_{timestamp}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(scripts, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完了: {len(scripts)}本の台本を生成")
    print(f"📄 出力: {output_file}")


if __name__ == "__main__":
    main()
