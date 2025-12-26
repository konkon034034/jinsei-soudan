#!/usr/bin/env python3
"""
Google Cloud TTS 女性声比較テスト（10パターン）
カツミの女性声バリエーションを比較（ヒロシは固定）
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

# ===== ヒロシ固定設定 =====
HIROSHI_VOICE = "ja-JP-Neural2-C"
HIROSHI_PITCH = 0
HIROSHI_RATE = 1.15

# ===== カツミ10パターン =====
VOICE_PATTERNS = [
    {"name": "パターン1",  "katsumi_voice": "ja-JP-Wavenet-A",  "katsumi_pitch": 0},
    {"name": "パターン2",  "katsumi_voice": "ja-JP-Wavenet-A",  "katsumi_pitch": -2},
    {"name": "パターン3",  "katsumi_voice": "ja-JP-Wavenet-A",  "katsumi_pitch": -4},
    {"name": "パターン4",  "katsumi_voice": "ja-JP-Wavenet-B",  "katsumi_pitch": 0},
    {"name": "パターン5",  "katsumi_voice": "ja-JP-Wavenet-B",  "katsumi_pitch": -2},
    {"name": "パターン6",  "katsumi_voice": "ja-JP-Wavenet-B",  "katsumi_pitch": -4},
    {"name": "パターン7",  "katsumi_voice": "ja-JP-Neural2-B",  "katsumi_pitch": -4},
    {"name": "パターン8",  "katsumi_voice": "ja-JP-Neural2-B",  "katsumi_pitch": -6},
    {"name": "パターン9",  "katsumi_voice": "ja-JP-Standard-A", "katsumi_pitch": -2},
    {"name": "パターン10", "katsumi_voice": "ja-JP-Standard-B", "katsumi_pitch": -2},
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
    katsumi_voice_short = pattern['katsumi_voice'].split('-')[-1]

    print(f"\n  {pattern['name']}")
    print(f"    カツミ: {katsumi_voice_short} pitch={pattern['katsumi_pitch']}")
    print(f"    ヒロシ: Neural2-C pitch=0 (固定)")

    audio_files = []

    for i, line in enumerate(TEST_DIALOGUE):
        speaker = line["speaker"]
        text = line["text"]

        if speaker == "カツミ":
            voice = pattern["katsumi_voice"]
            pitch = pattern["katsumi_pitch"]
            rate = HIROSHI_RATE
        else:
            voice = HIROSHI_VOICE
            pitch = HIROSHI_PITCH
            rate = HIROSHI_RATE

        output_path = str(temp_dir / f"line_{i:02d}.wav")
        if generate_tts(client, text, voice, pitch, rate, output_path):
            audio_files.append(output_path)
            print(f"    ✓ {speaker}")
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

    for af in audio_files:
        if os.path.exists(af):
            os.remove(af)

    return combined_path


def create_pattern_title_video(pattern: dict, duration: float, temp_dir: Path, index: int) -> str:
    """パターンタイトル動画を生成（無音音声トラック付き）"""
    title_path = str(temp_dir / f"title_{index}.mp4")

    katsumi_voice_short = pattern['katsumi_voice'].split('-')[-1]

    title_text = f"{pattern['name']}"
    line1 = f"カツミ: {katsumi_voice_short} pitch={pattern['katsumi_pitch']:+d}"
    line2 = f"ヒロシ: Neural2-C pitch=0 (固定)"
    line3 = f"rate=1.15"

    font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
    if not os.path.exists(font_path):
        font_path = "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"
    if not os.path.exists(font_path):
        font_path = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"

    subprocess.run([
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', f'color=c=0x1a1a2e:s=1920x1080:d={duration}',
        '-f', 'lavfi', '-i', f'anullsrc=r=48000:cl=stereo:d={duration}',
        '-vf', f"drawtext=text='{title_text}':fontfile='{font_path}':fontsize=100:fontcolor=white:x=(w-text_w)/2:y=300,"
               f"drawtext=text='{line1}':fontfile='{font_path}':fontsize=44:fontcolor=0xcccccc:x=(w-text_w)/2:y=480,"
               f"drawtext=text='{line2}':fontfile='{font_path}':fontsize=44:fontcolor=0x888888:x=(w-text_w)/2:y=550,"
               f"drawtext=text='{line3}':fontfile='{font_path}':fontsize=40:fontcolor=0x888888:x=(w-text_w)/2:y=620",
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
            "tags": ["TTS", "テスト", "Google Cloud", "女性声"],
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
    print("Google Cloud TTS 女性声比較テスト（10パターン）")
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    print(f"ヒロシ固定: {HIROSHI_VOICE} pitch={HIROSHI_PITCH} rate={HIROSHI_RATE}")

    client = get_tts_client()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        video_segments = []

        for i, pattern in enumerate(VOICE_PATTERNS):
            print(f"\n[{i+1}/10] {pattern['name']} 生成中...")

            pattern_audio = generate_pattern_audio(client, pattern, temp_path)

            result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', pattern_audio
            ], capture_output=True, text=True)
            audio_duration = float(result.stdout.strip()) if result.stdout.strip() else 5.0

            title_video = create_pattern_title_video(pattern, 2.0, temp_path, i)
            video_segments.append(title_video)

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

        print("\n[結合中...]")
        concat_list = temp_path / "concat_videos.txt"
        with open(concat_list, 'w') as f:
            for seg in video_segments:
                f.write(f"file '{seg}'\n")

        final_video = str(temp_path / "female_voice_compare.mp4")
        subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_list),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            final_video
        ], capture_output=True, check=True)

        result = subprocess.run([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', final_video
        ], capture_output=True, text=True)
        total_duration = float(result.stdout.strip()) if result.stdout.strip() else 0
        print(f"✓ 動画生成完了 (合計: {total_duration:.1f}秒)")

        print("\n[YouTube投稿中...]")
        title = f"【女性声比較】Google Cloud TTS 10パターン {datetime.now().strftime('%Y/%m/%d')}"
        description = """Google Cloud TTS 女性声比較テスト（10パターン）

【ヒロシ（固定）】
Neural2-C, pitch=0, rate=1.15

【カツミ（女性）10パターン】
1. Wavenet-A, pitch=0
2. Wavenet-A, pitch=-2
3. Wavenet-A, pitch=-4
4. Wavenet-A, pitch=-6
5. Wavenet-B, pitch=0
6. Wavenet-B, pitch=-2
7. Wavenet-B, pitch=-4
8. Wavenet-B, pitch=-6
9. Standard-A, pitch=-2
10. Standard-A, pitch=-4

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

            discord_webhook = os.environ.get("DISCORD_WEBHOOK_URL")
            if discord_webhook:
                requests.post(discord_webhook, json={
                    "content": f"✅ **女性声比較テスト完了**\n━━━━━━━━━━━━━━━━━━\n\n📺 {video_url}\n⏱️ {total_duration:.1f}秒\n🎤 カツミ女性声10パターン（Wavenet-A/B, Standard-A）\n👤 ヒロシ固定: Neural2-C\n\n━━━━━━━━━━━━━━━━━━"
                })

        except Exception as e:
            print(f"YouTube投稿エラー: {e}")
            import shutil
            output_file = f"female_voice_compare_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            shutil.copy(final_video, output_file)
            print(f"ローカル保存: {output_file}")


if __name__ == "__main__":
    main()
