#!/usr/bin/env python3
"""
YouTube競合チャンネル監視システム
- 指定チャンネルの新着動画を監視
- JSONファイルで動画リストを管理
- 新着動画をSlackに通知
"""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
import requests

# 監視対象チャンネル
COMPETITOR_CHANNELS = {
    "moraeru_okane": {
        "name": "もらえるお金チャンネル",
        "url": "https://www.youtube.com/@moraeru_okane",
    },
    "tayoreru_nenkinTV": {
        "name": "頼れる年金TV",
        "url": "https://www.youtube.com/@tayoreru_nenkinTV",
    },
    "ponpon_tanuki": {
        "name": "ポンポンたぬき",
        "url": "https://www.youtube.com/@ponpon.tanuki_3",
    },
}

# データファイル
DATA_FILE = Path(__file__).parent / "competitor_videos.json"

# 取得する動画数（チャンネルあたり）
MAX_VIDEOS_PER_CHANNEL = 20


def load_data() -> dict:
    """保存済みデータを読み込み"""
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "channels": {},
        "last_checked": None
    }


def save_data(data: dict):
    """データを保存"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✓ データ保存: {DATA_FILE}")


def get_channel_videos(channel_url: str, max_videos: int = MAX_VIDEOS_PER_CHANNEL) -> list:
    """yt-dlpでチャンネルの動画リストを取得"""
    try:
        # yt-dlpコマンドを実行（python -m yt_dlp を使用）
        import sys
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--flat-playlist",
            "--no-download",
            "-J",  # JSON出力
            f"--playlist-end={max_videos}",
            f"{channel_url}/videos"
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            print(f"  ⚠ yt-dlpエラー: {result.stderr[:200]}")
            return []

        data = json.loads(result.stdout)
        videos = []

        entries = data.get("entries", [])
        for entry in entries:
            if entry:
                video = {
                    "video_id": entry.get("id", ""),
                    "title": entry.get("title", ""),
                    "url": entry.get("url", f"https://www.youtube.com/watch?v={entry.get('id', '')}"),
                    "upload_date": entry.get("upload_date", ""),  # YYYYMMDD形式
                    "duration": entry.get("duration", 0),
                    "view_count": entry.get("view_count", 0),
                }
                videos.append(video)

        return videos

    except subprocess.TimeoutExpired:
        print(f"  ⚠ タイムアウト")
        return []
    except json.JSONDecodeError as e:
        print(f"  ⚠ JSON解析エラー: {e}")
        return []
    except Exception as e:
        print(f"  ⚠ エラー: {e}")
        return []


def find_new_videos(existing_videos: list, fetched_videos: list) -> list:
    """新着動画を検出"""
    existing_ids = {v["video_id"] for v in existing_videos}
    new_videos = [v for v in fetched_videos if v["video_id"] not in existing_ids]
    return new_videos


def send_slack_notification(new_videos_by_channel: dict):
    """新着動画をSlackに通知"""
    webhook_url = os.environ.get("SLACK_WEBHOOK_SCRIPT")
    if not webhook_url:
        print("  ⚠ SLACK_WEBHOOK_SCRIPT未設定のためスキップ")
        return

    if not new_videos_by_channel:
        return

    # メッセージ作成
    lines = ["🔔 *競合チャンネル新着動画*\n"]

    for channel_key, videos in new_videos_by_channel.items():
        channel_info = COMPETITOR_CHANNELS.get(channel_key, {})
        channel_name = channel_info.get("name", channel_key)

        lines.append(f"\n📺 *{channel_name}*")
        for video in videos:
            title = video.get("title", "タイトル不明")
            url = video.get("url", "")
            upload_date = video.get("upload_date", "")

            # 日付フォーマット
            if upload_date and len(upload_date) == 8:
                date_str = f"{upload_date[:4]}/{upload_date[4:6]}/{upload_date[6:]}"
            else:
                date_str = "日付不明"

            lines.append(f"  • [{date_str}] {title}")
            lines.append(f"    {url}")

    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"チェック日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    message = "\n".join(lines)

    try:
        payload = {"text": message}
        response = requests.post(webhook_url, json=payload, timeout=30)

        if response.status_code == 200:
            print("  ✓ Slack通知送信完了")
        else:
            print(f"  ⚠ Slack送信失敗: {response.status_code}")
    except Exception as e:
        print(f"  ⚠ Slack送信エラー: {e}")


def check_all_channels():
    """全チャンネルをチェック"""
    print("=" * 50)
    print("競合チャンネル監視システム")
    print("=" * 50)
    print(f"チェック日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 既存データを読み込み
    data = load_data()

    new_videos_by_channel = {}
    total_new = 0

    for channel_key, channel_info in COMPETITOR_CHANNELS.items():
        channel_name = channel_info["name"]
        channel_url = channel_info["url"]

        print(f"[{channel_name}]")
        print(f"  URL: {channel_url}")

        # 動画リストを取得
        print(f"  動画リストを取得中...")
        fetched_videos = get_channel_videos(channel_url)
        print(f"  取得件数: {len(fetched_videos)}件")

        if not fetched_videos:
            print(f"  ⚠ 動画を取得できませんでした")
            continue

        # 既存の動画リストと比較
        existing_data = data.get("channels", {}).get(channel_key, {})
        existing_videos = existing_data.get("videos", [])

        # 新着動画を検出
        new_videos = find_new_videos(existing_videos, fetched_videos)

        if new_videos:
            print(f"  🆕 新着: {len(new_videos)}件")
            for v in new_videos:
                print(f"    • {v['title'][:40]}...")
            new_videos_by_channel[channel_key] = new_videos
            total_new += len(new_videos)
        else:
            print(f"  新着なし")

        # データを更新（usedフラグを保持しながらマージ）
        existing_ids = {v["video_id"]: v for v in existing_videos}
        updated_videos = []

        for video in fetched_videos:
            vid = video["video_id"]
            if vid in existing_ids:
                # 既存動画: usedフラグを保持
                existing_video = existing_ids[vid]
                video["used"] = existing_video.get("used", False)
            else:
                # 新規動画
                video["used"] = False
            updated_videos.append(video)

        # チャンネルデータを更新
        if "channels" not in data:
            data["channels"] = {}

        data["channels"][channel_key] = {
            "channel_url": channel_url,
            "channel_name": channel_name,
            "videos": updated_videos,
            "last_updated": datetime.now().isoformat()
        }

        print()

    # 最終チェック日時を更新
    data["last_checked"] = datetime.now().isoformat()

    # データを保存
    save_data(data)

    # 新着があればSlack通知
    if new_videos_by_channel:
        print(f"\n📢 新着動画をSlackに通知中...")
        send_slack_notification(new_videos_by_channel)

    print()
    print("=" * 50)
    print(f"✅ チェック完了")
    print(f"   新着動画: {total_new}件")
    print("=" * 50)

    return new_videos_by_channel


def mark_video_as_used(channel_key: str, video_id: str):
    """動画を使用済みにマーク"""
    data = load_data()

    channel_data = data.get("channels", {}).get(channel_key, {})
    videos = channel_data.get("videos", [])

    for video in videos:
        if video["video_id"] == video_id:
            video["used"] = True
            save_data(data)
            print(f"✓ {video_id} を使用済みにマークしました")
            return True

    print(f"⚠ {video_id} が見つかりませんでした")
    return False


def list_unused_videos():
    """未使用の動画一覧を表示"""
    data = load_data()

    print("=" * 50)
    print("未使用動画一覧")
    print("=" * 50)

    for channel_key, channel_data in data.get("channels", {}).items():
        channel_name = channel_data.get("channel_name", channel_key)
        videos = channel_data.get("videos", [])
        unused = [v for v in videos if not v.get("used", False)]

        if unused:
            print(f"\n📺 {channel_name} ({len(unused)}件)")
            for v in unused[:10]:  # 最大10件表示
                title = v.get("title", "")[:50]
                print(f"  • {title}")
                print(f"    ID: {v.get('video_id', '')}")


def main():
    """メイン処理"""
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "list":
            list_unused_videos()
        elif cmd == "mark" and len(sys.argv) >= 4:
            channel_key = sys.argv[2]
            video_id = sys.argv[3]
            mark_video_as_used(channel_key, video_id)
        else:
            print("使用方法:")
            print("  python competitor_monitor.py          # チェック実行")
            print("  python competitor_monitor.py list     # 未使用動画一覧")
            print("  python competitor_monitor.py mark <channel_key> <video_id>  # 使用済みマーク")
    else:
        check_all_channels()


if __name__ == "__main__":
    main()
