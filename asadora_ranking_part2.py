#!/usr/bin/env python3
"""
朝ドラランキング動画自動生成システム - Part2
モードB後半: NotebookLM音声から動画生成

フロー:
1. AUDIO_READYタスクを取得
2. Google Driveから音声をダウンロード
3. ElevenLabs STTで文字起こし
4. 台本とマッチングして字幕生成
5. 画像取得・動画合成
6. YouTubeアップロード
"""

import os
import sys
import json
import re
import time
import tempfile
import requests
from datetime import datetime
from pathlib import Path
from io import BytesIO

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
# moviepy 1.0.3 対応
try:
    from moviepy.editor import (
        ImageClip, AudioFileClip, TextClip, CompositeVideoClip,
        concatenate_videoclips
    )
except ImportError:
    # moviepy 2.0 対応
    from moviepy import (
        ImageClip, AudioFileClip, TextClip, CompositeVideoClip,
        concatenate_videoclips
    )
from PIL import Image, ImageDraw
import numpy as np


# ===== 定数 =====
SPREADSHEET_ID = "15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo"
SHEET_NAME = "YouTube自動投稿"
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
FPS = 24

CHARACTERS = {
    "ユミコ": {"color": "#FF69B4"},
    "ケンジ": {"color": "#4169E1"}
}


def get_google_credentials():
    """Google認証情報を取得"""
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if not creds_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY が設定されていません")

    creds_info = json.loads(creds_json)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    return Credentials.from_service_account_info(creds_info, scopes=scopes)


def get_sheets_service():
    return build("sheets", "v4", credentials=get_google_credentials())


def get_drive_service():
    return build("drive", "v3", credentials=get_google_credentials())


# 使用可能なチャンネル（3チャンネルのみ）
AVAILABLE_CHANNELS = ["23", "24", "27"]


def get_audio_ready_task():
    """AUDIO_READYタスクを取得"""
    import random

    service = get_sheets_service()

    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A:J"
    ).execute()

    values = result.get("values", [])

    for i, row in enumerate(values[1:], start=2):
        status = row[2] if len(row) > 2 else ""
        if status == "AUDIO_READY":
            # チャンネル番号を取得（有効な番号のみ使用）
            channel = row[3] if len(row) > 3 else ""
            if channel not in AVAILABLE_CHANNELS:
                channel = random.choice(AVAILABLE_CHANNELS)
                print(f"  チャンネル自動選択: {channel}")

            return {
                "row": i,
                "theme": row[0] if len(row) > 0 else "",
                "mode": row[1] if len(row) > 1 else "NOTEBOOK",
                "channel": channel,
                "script": row[5] if len(row) > 5 else "",
                "audio_url": row[7] if len(row) > 7 else "",
            }

    return None


def update_spreadsheet(row: int, updates: dict):
    """スプレッドシートを更新"""
    service = get_sheets_service()

    col_map = {
        "status": "C",
        "youtube_url": "I",
        "processing_time": "J"
    }

    for key, value in updates.items():
        if key in col_map:
            col = col_map[key]
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!{col}{row}",
                valueInputOption="RAW",
                body={"values": [[str(value)[:50000]]]}
            ).execute()


def download_audio_from_drive(audio_url: str, output_path: str) -> bool:
    """Google Driveから音声ファイルをダウンロード"""
    service = get_drive_service()

    # URLからファイルIDを抽出
    file_id = None
    patterns = [
        r'/file/d/([a-zA-Z0-9_-]+)',
        r'id=([a-zA-Z0-9_-]+)',
        r'/d/([a-zA-Z0-9_-]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, audio_url)
        if match:
            file_id = match.group(1)
            break

    if not file_id:
        print(f"ファイルIDを抽出できません: {audio_url}")
        return False

    try:
        request = service.files().get_media(fileId=file_id)
        with open(output_path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    print(f"ダウンロード進捗: {int(status.progress() * 100)}%")

        return True

    except Exception as e:
        print(f"ダウンロードエラー: {e}")
        return False


def transcribe_with_elevenlabs(audio_path: str) -> list:
    """ElevenLabs STTで音声を文字起こし"""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("ELEVENLABS_API_KEY が設定されていません")
        return []

    try:
        url = "https://api.elevenlabs.io/v1/speech-to-text"
        headers = {"xi-api-key": api_key}

        with open(audio_path, 'rb') as f:
            files = {"file": f}
            data = {"model_id": "scribe_v1", "language_code": "ja"}

            response = requests.post(url, headers=headers, files=files, data=data, timeout=600)
            response.raise_for_status()

        result = response.json()
        return result.get("words", [])

    except Exception as e:
        print(f"STTエラー: {e}")
        return []


def extract_dialogue_from_script(script_json: str) -> list:
    """台本JSONから対話を抽出"""
    try:
        script = json.loads(script_json)
    except json.JSONDecodeError:
        return []

    dialogue = []

    # オープニング
    for line in script.get("opening", []):
        dialogue.append(line)

    # ランキング
    for item in script.get("rankings", []):
        for line in item.get("dialogue", []):
            dialogue.append({
                **line,
                "rank": item.get("rank"),
                "work_title": item.get("work_title"),
                "year": item.get("year"),
                "cast": item.get("cast"),
                "image_keyword": item.get("image_keyword", "japan")
            })

    # エンディング
    for line in script.get("ending", []):
        dialogue.append(line)

    return dialogue


def match_stt_with_script(stt_words: list, dialogue: list, audio_duration: float) -> list:
    """STT結果と台本をマッチングして字幕セグメントを生成"""
    if not stt_words:
        # STTがない場合は均等に分割
        segment_duration = audio_duration / len(dialogue) if dialogue else 0
        segments = []
        current_time = 0

        for line in dialogue:
            segments.append({
                "speaker": line.get("speaker", ""),
                "text": line.get("text", ""),
                "start": current_time,
                "end": current_time + segment_duration,
                "rank": line.get("rank"),
                "work_title": line.get("work_title"),
                "year": line.get("year"),
                "cast": line.get("cast"),
                "image_keyword": line.get("image_keyword")
            })
            current_time += segment_duration

        return segments

    # STTワードを結合してテキストを作成
    full_stt_text = "".join([w.get("text", "") for w in stt_words])

    # 各台本セリフの位置を特定
    segments = []
    current_stt_index = 0

    for i, line in enumerate(dialogue):
        script_text = line.get("text", "")

        # STTテキスト内で台本テキストの位置を探す
        # 簡易的なマッチング（部分一致）
        start_time = 0
        end_time = audio_duration / len(dialogue) * (i + 1)

        # STTワードから時間を推定
        if current_stt_index < len(stt_words):
            start_time = stt_words[current_stt_index].get("start", 0)

            # 次のセリフまでのワード数を推定
            words_per_segment = len(stt_words) // len(dialogue)
            end_index = min(current_stt_index + words_per_segment, len(stt_words) - 1)

            end_time = stt_words[end_index].get("end", end_time)
            current_stt_index = end_index + 1

        segments.append({
            "speaker": line.get("speaker", ""),
            "text": script_text,  # 台本のテキストを使用（STTより正確）
            "start": start_time,
            "end": end_time,
            "rank": line.get("rank"),
            "work_title": line.get("work_title"),
            "year": line.get("year"),
            "cast": line.get("cast"),
            "image_keyword": line.get("image_keyword")
        })

    return segments


def fetch_unsplash_image(keyword: str, output_path: str) -> bool:
    """Unsplash APIから画像を取得"""
    access_key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not access_key:
        return False

    try:
        url = "https://api.unsplash.com/search/photos"
        params = {"query": keyword, "orientation": "landscape", "per_page": 3}
        headers = {"Authorization": f"Client-ID {access_key}"}

        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        if data["results"]:
            import random
            image_data = random.choice(data["results"])
            image_url = image_data["urls"]["regular"]

            img_response = requests.get(image_url, timeout=30)
            img_response.raise_for_status()

            with open(output_path, 'wb') as f:
                f.write(img_response.content)

            resize_image(output_path, VIDEO_WIDTH, VIDEO_HEIGHT)
            return True

    except Exception as e:
        print(f"Unsplash画像取得エラー: {e}")

    return False


def generate_gradient_background(output_path: str, rank: int = 0):
    """昭和風グラデーション背景を生成"""
    img = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT))
    draw = ImageDraw.Draw(img)

    color_schemes = [
        ((70, 35, 10), (210, 180, 140)),
        ((30, 50, 50), (176, 196, 222)),
        ((80, 20, 20), (255, 218, 185)),
        ((20, 60, 20), (144, 238, 144)),
        ((50, 20, 80), (230, 230, 250)),
        ((90, 20, 20), (255, 182, 193)),
        ((20, 20, 90), (173, 216, 230)),
        ((50, 60, 30), (238, 232, 170)),
        ((80, 20, 80), (221, 160, 221)),
        ((20, 80, 80), (224, 255, 255)),
        ((120, 90, 20), (255, 250, 205)),
    ]

    idx = (rank - 1) % len(color_schemes) if rank > 0 else 0
    if rank == 1:
        idx = 10

    top_color, bottom_color = color_schemes[idx]

    for y in range(VIDEO_HEIGHT):
        ratio = y / VIDEO_HEIGHT
        r = int(top_color[0] * (1 - ratio) + bottom_color[0] * ratio)
        g = int(top_color[1] * (1 - ratio) + bottom_color[1] * ratio)
        b = int(top_color[2] * (1 - ratio) + bottom_color[2] * ratio)
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=(r, g, b))

    img.save(output_path)


def resize_image(image_path: str, width: int, height: int):
    """画像をリサイズ"""
    img = Image.open(image_path)
    img_ratio = img.width / img.height
    target_ratio = width / height

    if img_ratio > target_ratio:
        new_width = int(img.height * target_ratio)
        left = (img.width - new_width) // 2
        img = img.crop((left, 0, left + new_width, img.height))
    else:
        new_height = int(img.width / target_ratio)
        top = (img.height - new_height) // 2
        img = img.crop((0, top, img.width, top + new_height))

    img = img.resize((width, height), Image.LANCZOS)
    img.save(image_path)


def get_font_path():
    """日本語フォントパスを取得"""
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            return fp
    return None


def create_video_from_segments(audio_path: str, segments: list, script: dict, temp_dir: Path) -> str:
    """セグメントから動画を作成"""
    audio = AudioFileClip(audio_path)
    duration = audio.duration

    # セクションごとに画像を準備
    current_rank = None
    section_images = {}

    for i, seg in enumerate(segments):
        rank = seg.get("rank")

        if rank and rank != current_rank:
            current_rank = rank
            image_path = str(temp_dir / f"rank_{rank}.jpg")

            keyword = seg.get("image_keyword", "japan drama")
            if not fetch_unsplash_image(keyword, image_path):
                image_path = str(temp_dir / f"rank_{rank}.png")
                generate_gradient_background(image_path, rank=rank)

            section_images[rank] = image_path

    # デフォルト背景
    default_bg = str(temp_dir / "default_bg.png")
    generate_gradient_background(default_bg, rank=0)

    # 背景画像クリップを作成
    bg_clips = []
    last_end = 0

    for seg in segments:
        rank = seg.get("rank")
        image_path = section_images.get(rank, default_bg)

        start = seg["start"]
        end = seg["end"]

        # 前のセグメントとのギャップを埋める
        if start > last_end:
            gap_clip = ImageClip(default_bg).set_start(last_end).set_end(start)
            bg_clips.append(gap_clip)

        clip = ImageClip(image_path).set_start(start).set_end(end)
        bg_clips.append(clip)

        last_end = end

    # 最後までの背景
    if last_end < duration:
        final_clip = ImageClip(default_bg).set_start(last_end).set_end(duration)
        bg_clips.append(final_clip)

    # 字幕クリップを作成
    subtitle_clips = []
    font = get_font_path()

    for seg in segments:
        speaker = seg.get("speaker", "")
        text = seg.get("text", "")
        color = CHARACTERS.get(speaker, {}).get("color", "white")

        full_text = f"【{speaker}】{text}" if speaker else text

        try:
            txt_clip = TextClip(
                full_text,
                fontsize=44,
                color=color,
                font=font,
                stroke_color='black',
                stroke_width=2,
                size=(VIDEO_WIDTH - 100, None),
                method='caption'
            )
            txt_clip = txt_clip.set_start(seg["start"]).set_end(seg["end"])
            txt_clip = txt_clip.set_position(('center', VIDEO_HEIGHT - 180))
            subtitle_clips.append(txt_clip)
        except Exception as e:
            print(f"字幕作成エラー: {e}")

    # 順位バッジを追加
    badge_clips = []
    current_rank = None

    for seg in segments:
        rank = seg.get("rank")
        if rank and rank != current_rank:
            current_rank = rank

            try:
                badge_text = f"第{rank}位"
                fontsize = 100 if rank == 1 else 80
                badge_color = 'gold' if rank <= 3 else 'white'

                badge = TextClip(
                    badge_text,
                    fontsize=fontsize,
                    color=badge_color,
                    font=font,
                    stroke_color='darkred' if rank == 1 else 'black',
                    stroke_width=3,
                )

                # この順位のセグメント範囲を取得
                rank_segments = [s for s in segments if s.get("rank") == rank]
                if rank_segments:
                    start = rank_segments[0]["start"]
                    end = rank_segments[-1]["end"]
                    badge = badge.set_start(start).set_end(end)
                    badge = badge.set_position((50, 50))
                    badge_clips.append(badge)

            except Exception as e:
                print(f"バッジ作成エラー: {e}")

    # 作品情報クリップを追加
    info_clips = []
    current_rank = None

    for seg in segments:
        rank = seg.get("rank")
        if rank and rank != current_rank:
            current_rank = rank
            work_title = seg.get("work_title", "")
            year = seg.get("year", "")
            cast = seg.get("cast", "")

            if work_title:
                try:
                    info_text = f"『{work_title}』（{year}年）\n主演: {cast}"
                    info_clip = TextClip(
                        info_text,
                        fontsize=48,
                        color='white',
                        font=font,
                        stroke_color='black',
                        stroke_width=2,
                        size=(VIDEO_WIDTH - 200, None),
                        method='caption'
                    )

                    rank_segments = [s for s in segments if s.get("rank") == rank]
                    if rank_segments:
                        start = rank_segments[0]["start"]
                        end = rank_segments[-1]["end"]
                        info_clip = info_clip.set_start(start).set_end(end)
                        info_clip = info_clip.set_position((100, 150))
                        info_clips.append(info_clip)

                except Exception as e:
                    print(f"作品情報作成エラー: {e}")

    # 全てのクリップを合成
    all_clips = bg_clips + badge_clips + info_clips + subtitle_clips

    video = CompositeVideoClip(all_clips, size=(VIDEO_WIDTH, VIDEO_HEIGHT))
    video = video.set_audio(audio)
    video = video.set_duration(duration)

    # 出力
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = str(temp_dir / f"asadora_ranking_{timestamp}.mp4")

    video.write_videofile(output_path, fps=FPS, codec='libx264', audio_codec='aac', threads=4)

    # SRT生成
    srt_path = output_path.replace('.mp4', '.srt')
    generate_srt(segments, srt_path)

    # クリーンアップ
    video.close()
    audio.close()

    return output_path


def generate_srt(segments: list, output_path: str):
    """SRTファイルを生成"""
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments, 1):
            start = format_srt_time(seg['start'])
            end = format_srt_time(seg['end'])
            speaker = seg.get('speaker', '')
            text = f"【{speaker}】{seg['text']}" if speaker else seg['text']
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")


def format_srt_time(seconds: float) -> str:
    """秒をSRT形式に変換"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def upload_to_youtube(video_path: str, title: str, description: str, tags: list, channel_token: str) -> str:
    """YouTubeに動画をアップロード"""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    # TOKEN環境変数名を構築（YOUTUBE_REFRESH_TOKEN_X 形式）
    token_env_name = f"YOUTUBE_REFRESH_TOKEN_{channel_token}"
    refresh_token = os.environ.get(token_env_name)

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError(f"YouTube認証情報が不足しています ({token_env_name})")

    token_url = "https://oauth2.googleapis.com/token"
    response = requests.post(token_url, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    })
    response.raise_for_status()
    access_token = response.json()["access_token"]

    from google.oauth2.credentials import Credentials as OAuthCredentials
    creds = OAuthCredentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=token_url,
        client_id=client_id,
        client_secret=client_secret
    )

    youtube = build("youtube", "v3", credentials=creds)

    hashtags = " ".join([f"#{tag}" for tag in tags[:5]])

    body = {
        "snippet": {
            "title": title,
            "description": f"{description}\n\n{hashtags}",
            "tags": tags,
            "categoryId": "24"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"アップロード進捗: {int(status.progress() * 100)}%")

    video_id = response["id"]
    return f"https://www.youtube.com/watch?v={video_id}"


def send_slack_notification(message: str, success: bool = True):
    """Slack通知"""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return

    emoji = ":white_check_mark:" if success else ":x:"
    payload = {"text": f"{emoji} *朝ドラランキング (Part2)*\n{message}"}

    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        print(f"Slack通知エラー: {e}")


def main():
    """メイン処理"""
    print("=" * 60)
    print("朝ドラランキング動画 - Part2 (NotebookLM音声処理)")
    print("=" * 60)

    try:
        task = get_audio_ready_task()
        if not task:
            print("AUDIO_READYタスクがありません")
            return

        start_time = time.time()
        row = task["row"]
        theme = task["theme"]
        channel = task["channel"]

        print(f"\nタスク発見:")
        print(f"  テーマ: {theme}")
        print(f"  チャンネル: YOUTUBE_REFRESH_TOKEN_{channel}")

        update_spreadsheet(row, {"status": "PROCESSING_PART2"})

        temp_dir = Path(tempfile.mkdtemp())

        # 1. 音声ダウンロード
        print("\n[1/5] 音声ファイルをダウンロード中...")
        audio_path = str(temp_dir / "audio.wav")
        if not download_audio_from_drive(task["audio_url"], audio_path):
            raise ValueError("音声ファイルのダウンロードに失敗しました")

        # 音声の長さを取得
        audio = AudioFileClip(audio_path)
        audio_duration = audio.duration
        audio.close()
        print(f"  音声長: {audio_duration:.1f}秒")

        # 2. STT文字起こし
        print("\n[2/5] ElevenLabs STTで文字起こし中...")
        stt_words = transcribe_with_elevenlabs(audio_path)
        print(f"  認識ワード数: {len(stt_words)}")

        # 3. 台本とマッチング
        print("\n[3/5] 台本とマッチング中...")
        dialogue = extract_dialogue_from_script(task["script"])
        segments = match_stt_with_script(stt_words, dialogue, audio_duration)
        print(f"  セグメント数: {len(segments)}")

        # 4. 動画作成
        print("\n[4/5] 動画作成中...")
        script = json.loads(task["script"]) if task["script"] else {}
        video_path = create_video_from_segments(audio_path, segments, script, temp_dir)

        # 5. YouTubeアップロード
        print("\n[5/5] YouTubeアップロード中...")
        youtube_url = upload_to_youtube(
            video_path,
            script.get("title", f"【朝ドラ】{theme}"),
            script.get("description", ""),
            script.get("tags", ["朝ドラ", "NHK", "ランキング"]),
            channel
        )

        elapsed = int(time.time() - start_time)
        update_spreadsheet(row, {
            "status": "DONE",
            "youtube_url": youtube_url,
            "processing_time": f"{elapsed}秒"
        })

        send_slack_notification(
            f"*NotebookLM高品質モード完了*\n"
            f"テーマ: {theme}\n"
            f"タイトル: {script.get('title', theme)}\n"
            f"URL: {youtube_url}\n"
            f"処理時間: {elapsed}秒"
        )

        print(f"\n完了: {youtube_url}")
        print(f"処理時間: {elapsed}秒")

    except Exception as e:
        print(f"\nエラー: {e}")
        if 'row' in dir():
            update_spreadsheet(row, {"status": f"ERROR: {str(e)[:100]}"})
        send_slack_notification(f"エラー発生\n{str(e)}", success=False)
        sys.exit(1)


if __name__ == "__main__":
    main()
