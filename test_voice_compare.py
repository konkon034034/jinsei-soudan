#!/usr/bin/env python3
"""
Google Cloud TTS 声比較テスト
4つのボイスパターンを1本の動画にまとめて比較
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
    {"speaker": "カツミ", "text": "厚生労働省から新しい発表がありました。"},
    {"speaker": "ヒロシ", "text": "えー、また難しい話ですか？"},
    {"speaker": "カツミ", "text": "大丈夫、わかりやすく説明しますね。"},
    {"speaker": "ヒロシ", "text": "はぁ〜、年金って難しいなぁ..."},
]

# ===== ボイスパターン =====
VOICE_PATTERNS = [
    {
        "name": "パターン1: Wavenet-A / Wavenet-D（現在の設定）",
        "katsumi": "ja-JP-Wavenet-A",
        "hiroshi": "ja-JP-Wavenet-D",
    },
    {
        "name": "パターン2: Wavenet-B / Wavenet-C",
        "katsumi": "ja-JP-Wavenet-B",
        "hiroshi": "ja-JP-Wavenet-C",
    },
    {
        "name": "パターン3: Neural2-B / Neural2-C",
        "katsumi": "ja-JP-Neural2-B",
        "hiroshi": "ja-JP-Neural2-C",
    },
    {
        "name": "パターン4: Neural2-B / Neural2-D",
        "katsumi": "ja-JP-Neural2-B",
        "hiroshi": "ja-JP-Neural2-D",
    },
]


def get_tts_client():
    """Google Cloud TTS クライアントを取得"""
    key_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if not key_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY が設定されていません")
    key_data = json.loads(key_json)
    credentials = Credentials.from_service_account_info(key_data)
    return texttospeech.TextToSpeechClient(credentials=credentials)


def generate_tts(client, text: str, voice_name: str, output_path: str) -> bool:
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
            speaking_rate=1.15
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
    print(f"    カツミ: {pattern['katsumi']}")
    print(f"    ヒロシ: {pattern['hiroshi']}")

    audio_files = []

    for i, line in enumerate(TEST_DIALOGUE):
        speaker = line["speaker"]
        text = line["text"]
        voice = pattern["katsumi"] if speaker == "カツミ" else pattern["hiroshi"]

        output_path = str(temp_dir / f"line_{i:02d}.wav")
        if generate_tts(client, text, voice, output_path):
            audio_files.append(output_path)
            print(f"    ✓ {speaker}: {text[:20]}...")
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


def generate_announcement(client, text: str, temp_dir: Path) -> str:
    """アナウンス音声を生成"""
    output_path = str(temp_dir / "announce.wav")
    generate_tts(client, text, "ja-JP-Wavenet-A", output_path)
    return output_path


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
            "tags": ["TTS", "テスト", "Google Cloud"],
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
    print("Google Cloud TTS 声比較テスト")
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    client = get_tts_client()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        all_audio_files = []

        # 各パターンの音声を生成
        for i, pattern in enumerate(VOICE_PATTERNS):
            # アナウンス
            announce_text = f"{pattern['name']}。カツミは{pattern['katsumi']}、ヒロシは{pattern['hiroshi']}です。"
            announce_path = str(temp_path / f"announce_{i}.wav")
            generate_tts(client, announce_text, "ja-JP-Wavenet-A", announce_path)
            all_audio_files.append(announce_path)

            # 1秒の無音
            silence_path = str(temp_path / f"silence_{i}.wav")
            subprocess.run([
                'ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono',
                '-t', '1', '-acodec', 'pcm_s16le', silence_path
            ], capture_output=True)
            all_audio_files.append(silence_path)

            # パターンの音声
            pattern_audio = generate_pattern_audio(client, pattern, temp_path)
            pattern_final = str(temp_path / f"pattern_{i}.wav")
            os.rename(pattern_audio, pattern_final)
            all_audio_files.append(pattern_final)

            # 2秒の無音（パターン間）
            silence2_path = str(temp_path / f"silence2_{i}.wav")
            subprocess.run([
                'ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono',
                '-t', '2', '-acodec', 'pcm_s16le', silence2_path
            ], capture_output=True)
            all_audio_files.append(silence2_path)

        # 全音声を結合
        print("\n[結合中...]")
        final_audio = str(temp_path / "final_audio.wav")
        list_file = temp_path / "final_concat.txt"
        with open(list_file, 'w') as f:
            for af in all_audio_files:
                f.write(f"file '{af}'\n")

        subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(list_file),
            '-acodec', 'pcm_s16le', '-ar', '24000', '-ac', '1', final_audio
        ], capture_output=True)

        # 音声の長さを取得
        result = subprocess.run([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', final_audio
        ], capture_output=True, text=True)
        duration = float(result.stdout.strip()) if result.stdout.strip() else 0
        print(f"  音声長: {duration:.1f}秒")

        # 動画生成（シンプルな背景）
        print("\n[動画生成中...]")
        bg_path = str(temp_path / "bg.png")
        subprocess.run([
            'ffmpeg', '-y', '-f', 'lavfi',
            '-i', 'color=c=0x2C2C2C:s=1920x1080:d=1',
            '-frames:v', '1', bg_path
        ], capture_output=True)

        video_path = str(temp_path / "voice_compare.mp4")
        subprocess.run([
            'ffmpeg', '-y',
            '-loop', '1', '-i', bg_path,
            '-i', final_audio,
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '192k',
            '-shortest',
            '-pix_fmt', 'yuv420p',
            video_path
        ], capture_output=True, check=True)

        print("✓ 動画生成完了")

        # YouTube投稿
        print("\n[YouTube投稿中...]")
        title = f"【TTS比較テスト】Google Cloud TTS ボイス比較 {datetime.now().strftime('%Y/%m/%d')}"
        description = """Google Cloud TTS のボイス比較テスト

【パターン】
1. Wavenet-A / Wavenet-D（現在の設定）
2. Wavenet-B / Wavenet-C
3. Neural2-B / Neural2-C
4. Neural2-B / Neural2-D

【テストセリフ】
カツミ（説明役）とヒロシ（聞き役）の掛け合い
"""

        try:
            video_url = upload_to_youtube(video_path, title, description)
            print(f"\n{'=' * 50}")
            print("YouTube投稿完了!")
            print(f"動画URL: {video_url}")
            print("=" * 50)
        except Exception as e:
            print(f"YouTube投稿エラー: {e}")
            # ローカル保存
            import shutil
            output_file = f"voice_compare_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            shutil.copy(video_path, output_file)
            print(f"ローカル保存: {output_file}")


if __name__ == "__main__":
    main()
