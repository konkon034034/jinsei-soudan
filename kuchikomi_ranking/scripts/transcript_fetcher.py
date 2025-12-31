#!/usr/bin/env python3
"""
口コミランキングチャンネル - 字幕収集システム
YouTube動画から字幕を取得
"""

import re
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound


def extract_video_id(url: str) -> str:
    """YouTubeのURLから動画IDを抽出"""
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:embed/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$'
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def fetch_transcript(video_url: str, languages: list = None) -> dict:
    """
    YouTube動画の字幕を取得

    Args:
        video_url: YouTubeのURL
        languages: 優先言語リスト（デフォルト: ['ja', 'ja-JP', 'en']）

    Returns:
        {
            "video_id": str,
            "transcript": list[dict],  # [{"text": str, "start": float, "duration": float}, ...]
            "full_text": str,
            "total_duration": float
        }
    """
    if languages is None:
        languages = ['ja', 'ja-JP', 'en']

    video_id = extract_video_id(video_url)
    if not video_id:
        raise ValueError(f"無効なYouTube URL: {video_url}")

    print(f"📺 動画ID: {video_id}")
    print(f"🔍 字幕を取得中...")

    try:
        # YouTubeTranscriptApi インスタンスを作成（v1.x 新API）
        api = YouTubeTranscriptApi()

        # 字幕リストを取得
        transcript_list = api.list(video_id)

        # 手動字幕を優先、なければ自動生成を使用
        transcript = None
        for lang in languages:
            try:
                transcript = transcript_list.find_transcript([lang])
                print(f"✓ 字幕を発見: {lang} ({'手動' if not transcript.is_generated else '自動生成'})")
                break
            except NoTranscriptFound:
                continue

        if transcript is None:
            # 自動生成字幕を取得
            try:
                transcript = transcript_list.find_generated_transcript(languages)
                print(f"✓ 自動生成字幕を使用")
            except NoTranscriptFound:
                raise NoTranscriptFound(video_id, languages, transcript_list)

        # 字幕データを取得
        transcript_data = transcript.fetch()

        # FetchedTranscriptをリストに変換
        transcript_items = [
            {"text": item.text, "start": item.start, "duration": item.duration}
            for item in transcript_data
        ]

        # 結果を整形
        full_text = " ".join([item['text'] for item in transcript_items])
        total_duration = sum([item['duration'] for item in transcript_items])

        print(f"✅ 字幕取得完了: {len(transcript_items)}件, {total_duration:.1f}秒")

        return {
            "video_id": video_id,
            "transcript": transcript_items,
            "full_text": full_text,
            "total_duration": total_duration
        }

    except TranscriptsDisabled:
        raise Exception(f"この動画は字幕が無効になっています: {video_id}")
    except NoTranscriptFound:
        raise Exception(f"この動画には字幕がありません: {video_id}")


def format_transcript_for_script(transcript_data: list, max_chars: int = 5000) -> str:
    """
    台本生成用に字幕をフォーマット

    Args:
        transcript_data: fetch_transcriptの結果["transcript"]
        max_chars: 最大文字数

    Returns:
        フォーマット済みテキスト
    """
    lines = []
    current_chars = 0

    for item in transcript_data:
        text = item['text'].strip()
        if not text:
            continue

        # 改行を除去
        text = text.replace('\n', ' ')

        if current_chars + len(text) > max_chars:
            break

        lines.append(text)
        current_chars += len(text)

    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("使用方法: python transcript_fetcher.py <YouTube URL>")
        sys.exit(1)

    url = sys.argv[1]

    try:
        result = fetch_transcript(url)
        print(f"\n=== 取得結果 ===")
        print(f"動画ID: {result['video_id']}")
        print(f"字幕数: {len(result['transcript'])}件")
        print(f"総時間: {result['total_duration']:.1f}秒")
        print(f"\n=== 冒頭200文字 ===")
        print(result['full_text'][:200])
    except Exception as e:
        print(f"❌ エラー: {e}")
        sys.exit(1)
