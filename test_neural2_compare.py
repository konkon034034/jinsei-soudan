#!/usr/bin/env python3
"""
Google Cloud TTS Neural2 声比較テスト（10パターン）
pitch/rate の違いを1本の動画で比較
"""

import os
import json
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

from google.cloud import texttospeech
from google.oauth2.service_account import Credentials
import requests

# ===== テストセリフ =====
TEST_DIALOGUE = [
    {"speaker": "カツミ", "text": "おはようございます。今日の年金ニュースをお届けします。"},
    {"speaker": "ヒロシ", "text": "今日はどんなニュースがあるんですか？"},
]

# ===== 10パターン =====
VOICE_PATTERNS = [
    {"name": "パターン1", "katsumi": "ja-JP-Neural2-B", "hiroshi": "ja-JP-Neural2-C", "pitch": 0.0, "rate": 1.15},
    {"name": "パターン2", "katsumi": "ja-JP-Neural2-B", "hiroshi": "ja-JP-Neural2-D", "pitch": 0.0, "rate": 1.15},
    {"name": "パターン3", "katsumi": "ja-JP-Neural2-B", "hiroshi": "ja-JP-Neural2-C", "pitch": 2.0, "rate": 1.15},
    {"name": "パターン4", "katsumi": "ja-JP-Neural2-B", "hiroshi": "ja-JP-Neural2-D", "pitch": 2.0, "rate": 1.15},
    {"name": "パターン5", "katsumi": "ja-JP-Neural2-B", "hiroshi": "ja-JP-Neural2-C", "pitch": -2.0, "rate": 1.15},
    {"name": "パターン6", "katsumi": "ja-JP-Neural2-B", "hiroshi": "ja-JP-Neural2-D", "pitch": -2.0, "rate": 1.15},
    {"name": "パターン7", "katsumi": "ja-JP-Neural2-B", "hiroshi": "ja-JP-Neural2-C", "pitch": 0.0, "rate": 1.25},
    {"name": "パターン8", "katsumi": "ja-JP-Neural2-B", "hiroshi": "ja-JP-Neural2-D", "pitch": 0.0, "rate": 1.25},
    {"name": "パターン9", "katsumi": "ja-JP-Neural2-B", "hiroshi": "ja-JP-Neural2-C", "pitch": 0.0, "rate": 1.0},
    {"name": "パターン10", "katsumi": "ja-JP-Neural2-B", "hiroshi": "ja-JP-Neural2-D", "pitch": 0.0, "rate": 1.0},
]


def get_tts_client():
    """Google Cloud TTS クライアントを取得"""
    key_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if not key_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY が設定されていません")
    key_data = json.loads(key_json)
    credentials = Credentials.from_service_account_info(key_data)
    return texttospeech.TextToSpeechClient(credentials=credentials)


def generate_tts(client, text: str, voice_name: str, pitch: float, rate: float, output_path: str) -> bool:
    """単一音声を生成"""
    try:
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code="ja-JP",
            name=voice_name
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=24000,
            speaking_rate=rate,
            pitch=pitch
        )
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        with open(output_path, "wb") as out:
            out.write(response.audio_content)
        return True
    except Exception as e:
        print(f"  エラー: {e}")
        return False


def generate_pattern_audio(client, pattern: dict, temp_dir: Path) -> str:
    """1パターン分の音声を生成"""
    print(f"\n  {pattern['name']}")
    print(f"    カツミ: {pattern['katsumi']}, ヒロシ: {pattern['hiroshi']}")
    print(f"    pitch={pattern['pitch']}, rate={pattern['rate']}")

    audio_files = []

    for i, line in enumerate(TEST_DIALOGUE):
        speaker = line["speaker"]
        text = line["text"]
        voice = pattern["katsumi"] if speaker == "カツミ" else pattern["hiroshi"]

        output_path = str(temp_dir / f"line_{i:02d}.wav")
        if generate_tts(client, text, voice, pattern["pitch"], pattern["rate"], output_path):
            audio_files.append(output_path)
            print(f"    ✓ {speaker}: {text[:15]}...")
        else:
            print(f"    ✗ {speaker}: 失敗")

    # 音声を結合
    combined_path = str(temp_dir / "pattern_combined.wav")
    list_file = temp_dir / "concat.txt"
    with open(list_file, 'w') as f:
        for af in audio_files:
            f.write(f"file '{af}'\n")

    subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(list_file),
        '-acodec', 'pcm_s16le', '-ar', '24000', '-ac', '1', combined_path
    ], capture_output=True)

    # 一時ファイル削除
    for af in audio_files:
        if os.path.exists(af):
            os.remove(af)

    return combined_path


def create_pattern_title_video(pattern: dict, duration: float, temp_dir: Path) -> str:
    """パターンタイトル動画を生成（無音音声トラック付き）"""
    title_path = str(temp_dir / f"title_{pattern['name']}.mp4")

    # タイトルテキスト
    title_text = f"{pattern['name']}"
    subtitle = f"カツミ={pattern['katsumi'].split('-')[-1]}, ヒロシ={pattern['hiroshi'].split('-')[-1]}"
    detail = f"pitch={pattern['pitch']:+.1f}, rate={pattern['rate']}"

    # フォントパス（GitHub Actions Ubuntu環境用）
    font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
    if not os.path.exists(font_path):
        font_path = "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"
    if not os.path.exists(font_path):
        font_path = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"  # macOS

    # 動画生成（無音音声トラック付き）
    subprocess.run([
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', f'color=c=0x1a1a2e:s=1920x1080:d={duration}',
        '-f', 'lavfi', '-i', f'anullsrc=r=48000:cl=stereo:d={duration}',
        '-vf', f"drawtext=text='{title_text}':fontfile='{font_path}':fontsize=120:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2-100,"
               f"drawtext=text='{subtitle}':fontfile='{font_path}':fontsize=48:fontcolor=0xcccccc:x=(w-text_w)/2:y=(h-text_h)/2+50,"
               f"drawtext=text='{detail}':fontfile='{font_path}':fontsize=40:fontcolor=0x888888:x=(w-text_w)/2:y=(h-text_h)/2+120",
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '192k',
        '-t', str(duration),
        '-pix_fmt', 'yuv420p',
        title_path
    ], capture_output=True)

    return title_path


def upload_to_youtube(video_path: str, title: str, description: str) -> str:
    """YouTubeにアップロード"""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN_23")

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError("YouTube認証情報が不足しています")

    response = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    })
    access_token = response.json()["access_token"]

    from google.oauth2.credentials import Credentials as OAuthCredentials
    creds = OAuthCredentials(token=access_token)
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["TTS", "テスト", "Google Cloud", "Neural2"],
            "categoryId": "22"
        },
        "status": {
            "privacyStatus": "unlisted",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  アップロード進捗: {int(status.progress() * 100)}%")

    video_id = response["id"]
    return f"https://www.youtube.com/watch?v={video_id}"


def main():
    print("=" * 50)
    print("Google Cloud TTS Neural2 声比較テスト（10パターン）")
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    client = get_tts_client()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        video_segments = []

        # 各パターンの音声・動画を生成
        for i, pattern in enumerate(VOICE_PATTERNS):
            print(f"\n[{i+1}/10] {pattern['name']} 生成中...")

            # 音声生成
            pattern_audio = generate_pattern_audio(client, pattern, temp_path)

            # 音声の長さを取得
            result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', pattern_audio
            ], capture_output=True, text=True)
            audio_duration = float(result.stdout.strip()) if result.stdout.strip() else 5.0

            # タイトル動画生成（2秒）
            title_video = create_pattern_title_video(pattern, 2.0, temp_path)
            video_segments.append(title_video)

            # 音声付き動画生成
            audio_video = str(temp_path / f"audio_{i}.mp4")
            subprocess.run([
                'ffmpeg', '-y',
                '-f', 'lavfi', '-i', f'color=c=0x2C2C2C:s=1920x1080:d={audio_duration}',
                '-i', pattern_audio,
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
                '-shortest', '-pix_fmt', 'yuv420p',
                audio_video
            ], capture_output=True)
            video_segments.append(audio_video)

            # 1秒の無音動画（パターン間）
            silence_video = str(temp_path / f"silence_{i}.mp4")
            subprocess.run([
                'ffmpeg', '-y',
                '-f', 'lavfi', '-i', 'color=c=0x1a1a2e:s=1920x1080:d=1',
                '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                '-c:a', 'aac', '-b:a', '192k',
                '-t', '1', '-pix_fmt', 'yuv420p',
                silence_video
            ], capture_output=True)
            video_segments.append(silence_video)

            print(f"  ✓ 完了 (音声: {audio_duration:.1f}秒)")

        # 全動画を結合
        print("\n[結合中...]")
        concat_list = temp_path / "concat_videos.txt"
        with open(concat_list, 'w') as f:
            for seg in video_segments:
                f.write(f"file '{seg}'\n")

        final_video = str(temp_path / "neural2_compare.mp4")
        subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_list),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            final_video
        ], capture_output=True, check=True)

        # 動画の長さを取得
        result = subprocess.run([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', final_video
        ], capture_output=True, text=True)
        total_duration = float(result.stdout.strip()) if result.stdout.strip() else 0
        print(f"✓ 動画生成完了 (合計: {total_duration:.1f}秒)")

        # YouTube投稿
        print("\n[YouTube投稿中...]")
        title = f"【Neural2比較】Google Cloud TTS 10パターン声比較 {datetime.now().strftime('%Y/%m/%d')}"
        description = """Google Cloud TTS Neural2 の声比較テスト（10パターン）

【パターン一覧】
1. Neural2-B/C, pitch=0, rate=1.15
2. Neural2-B/D, pitch=0, rate=1.15
3. Neural2-B/C, pitch=+2, rate=1.15
4. Neural2-B/D, pitch=+2, rate=1.15
5. Neural2-B/C, pitch=-2, rate=1.15
6. Neural2-B/D, pitch=-2, rate=1.15
7. Neural2-B/C, pitch=0, rate=1.25
8. Neural2-B/D, pitch=0, rate=1.25
9. Neural2-B/C, pitch=0, rate=1.0
10. Neural2-B/D, pitch=0, rate=1.0

【セリフ】
カツミ「おはようございます。今日の年金ニュースをお届けします。」
ヒロシ「今日はどんなニュースがあるんですか？」
"""

        try:
            video_url = upload_to_youtube(final_video, title, description)
            print(f"\n{'=' * 50}")
            print("YouTube投稿完了!")
            print(f"動画URL: {video_url}")
            print("=" * 50)

            # Discord通知
            discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL")
            if discord_webhook:
                requests.post(discord_webhook, json={
                    "content": f"✅ **Neural2 声比較テスト完了**\n━━━━━━━━━━━━━━━━━━\n\n📺 {video_url}\n⏱️ {total_duration:.1f}秒\n🎤 10パターン比較\n\n━━━━━━━━━━━━━━━━━━"
                })

        except Exception as e:
            print(f"YouTube投稿エラー: {e}")
            import shutil
            output_file = f"neural2_compare_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            shutil.copy(final_video, output_file)
            print(f"ローカル保存: {output_file}")


if __name__ == "__main__":
    main()
