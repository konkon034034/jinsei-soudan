#!/usr/bin/env python3
"""
年金ニュース ショート動画システム v2
- 本編とは完全に独立
- 控室トーク（60秒のショート動画）
- カツミ（女性）とヒロシ（男性）の掛け合い
"""

import os
import sys
import json
import re
import time
import tempfile
import requests
import subprocess
import io
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types
from pydub import AudioSegment
from PIL import Image, ImageDraw, ImageFont
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ===== 設定 =====
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
MAX_DURATION = 60

# テストモード
TEST_MODE = os.environ.get("TEST_MODE", "").lower() == "true"

# 背景画像（Google Drive ID）
BACKGROUND_IMAGE_ID = os.environ.get(
    "SHORT_BACKGROUND_IMAGE_ID",
    "1ywnGZHMZWavnus1-fPD1MVI3fWxSrAIp"
)

# TTS設定
TTS_MODEL = "gemini-2.5-flash-preview-tts"
VOICE_KATSUMI = "Kore"   # カツミ（女性）
VOICE_HIROSHI = "Puck"   # ヒロシ（男性）


class GeminiKeyManager:
    """Gemini APIキー管理"""
    def __init__(self):
        self.keys = []
        base_key = os.environ.get("GEMINI_API_KEY")
        if base_key:
            self.keys.append(base_key)
        for i in range(1, 29):
            key = os.environ.get(f"GEMINI_API_KEY_{i}")
            if key:
                self.keys.append(key)
        self.current_index = 0
        print(f"  利用可能なAPIキー: {len(self.keys)}個")

    def get_key(self):
        if not self.keys:
            raise ValueError("APIキーがありません")
        key = self.keys[self.current_index]
        return key

    def next_key(self):
        self.current_index = (self.current_index + 1) % len(self.keys)
        return self.get_key()


def fetch_todays_news(key_manager: GeminiKeyManager) -> str:
    """今日の年金ニュースを取得（リトライ付き）"""
    print("\n[1/6] 今日のニュースを取得中...")

    today = datetime.now().strftime("%Y年%m月%d日")

    prompt = f"""今日は{today}です。
最新の年金関連ニュースを3つ教えてください。

【形式】
1. ニュースタイトル - 簡潔な説明（50文字以内）
2. ニュースタイトル - 簡潔な説明（50文字以内）
3. ニュースタイトル - 簡潔な説明（50文字以内）

年金制度の変更、受給額の改定、繰り下げ受給、iDeCo、確定拠出年金など、
視聴者が関心を持ちそうな話題を選んでください。"""

    # リトライ処理
    max_retries = 5
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=key_manager.get_key())
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt
            )
            news = response.text.strip()
            print(f"  ✓ ニュース取得完了")
            print(f"  {news[:100]}...")
            return news
        except Exception as e:
            error_str = str(e)
            print(f"  ⚠ 試行{attempt + 1}/{max_retries} 失敗: {error_str[:50]}...")
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                key_manager.next_key()
                time.sleep(5)
            else:
                time.sleep(3)
            if attempt == max_retries - 1:
                raise RuntimeError(f"ニュース取得失敗: {error_str[:100]}")


def generate_script(key_manager: GeminiKeyManager, news: str) -> list:
    """控室トーク台本を生成（リトライ付き）"""
    print("\n[2/6] 台本を生成中...")

    today = datetime.now().strftime("%Y年%m月%d日")

    prompt = f"""あなたは年金ニュースラジオの控室にいる2人のパーソナリティです。
今日は{today}です。

【キャラクター】
- カツミ（50代女性）: 元・年金事務所勤務の専門家。ツッコミ担当。毒舌で本音をズバッと言う。
- ヒロシ（40代男性）: ボケ担当。素朴な疑問を投げかける。「え、マジで？」「それヤバくない？」が口癖。

【今日のニュース】
{news}

【ルール】
- 60秒以内で話す（10〜14セリフ、各セリフ15〜25文字）
- ヒロシから始める
- ヒロシがボケて、カツミがツッコむ流れ
- 最後にオチをつける
- 挨拶なし、いきなり本題に入る

【出力形式】以下の形式で出力してください。他の文章は不要です。
ヒロシ: セリフ1
カツミ: セリフ2
ヒロシ: セリフ3
カツミ: セリフ4
..."""

    # リトライ処理
    max_retries = 5
    response_text = None
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=key_manager.get_key())
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.9)
            )
            response_text = response.text.strip()
            break
        except Exception as e:
            error_str = str(e)
            print(f"  ⚠ 試行{attempt + 1}/{max_retries} 失敗: {error_str[:50]}...")
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                key_manager.next_key()
                time.sleep(5)
            else:
                time.sleep(3)
            if attempt == max_retries - 1:
                raise RuntimeError(f"台本生成失敗: {error_str[:100]}")

    # 台本をパース
    lines = []
    for line in response_text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # 話者を判定
        speaker = None
        text = None

        if line.startswith("ヒロシ:") or line.startswith("ヒロシ："):
            speaker = "ヒロシ"
            text = line.split(":", 1)[1].strip() if ":" in line else line.split("：", 1)[1].strip()
        elif line.startswith("カツミ:") or line.startswith("カツミ："):
            speaker = "カツミ"
            text = line.split(":", 1)[1].strip() if ":" in line else line.split("：", 1)[1].strip()

        if speaker and text:
            lines.append({"speaker": speaker, "text": text})
            print(f"    [{speaker}] {text[:30]}...")

    print(f"  ✓ 台本生成完了: {len(lines)}セリフ")
    return lines


def send_tts_failure_notification(speaker: str, text: str, error: str):
    """TTS失敗時のDiscord通知"""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return

    message = f"""❌ **ショート動画: TTS生成失敗**
━━━━━━━━━━━━━━━━━━
話者: {speaker}
テキスト: {text[:50]}...
エラー: {error[:100]}
━━━━━━━━━━━━━━━━━━
3回リトライしましたが失敗しました。"""

    try:
        requests.post(
            webhook_url,
            json={"content": message},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
    except:
        pass


def generate_tts_audio(script: list, output_path: str, key_manager: GeminiKeyManager) -> float:
    """話者ごとにTTS生成して結合（Gemini TTSのみ、gTTSなし）"""
    print("\n[3/6] 音声を生成中...")

    combined = AudioSegment.empty()

    for i, line in enumerate(script):
        speaker = line["speaker"]
        text = line["text"]
        voice = VOICE_HIROSHI if speaker == "ヒロシ" else VOICE_KATSUMI

        print(f"  [{i+1}/{len(script)}] {speaker} ({voice}): {text[:20]}...")

        # TTS生成（3回リトライ、失敗時はエラー終了）
        audio_data = None
        max_retries = 3
        wait_times = [30, 60, 0]  # 1回目失敗→30秒、2回目失敗→60秒、3回目失敗→終了
        last_error = None

        for attempt in range(max_retries):
            try:
                # 429エラー対策：まずキーを切り替えてから試行
                if attempt > 0:
                    key_manager.next_key()

                client = genai.Client(api_key=key_manager.get_key())

                response = client.models.generate_content(
                    model=TTS_MODEL,
                    contents=text,
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=voice
                                )
                            )
                        )
                    )
                )

                audio_data = response.candidates[0].content.parts[0].inline_data.data
                print(f"    ✓ TTS生成成功")
                break

            except Exception as e:
                last_error = str(e)
                print(f"    ⚠ 試行{attempt + 1}/3 失敗: {last_error[:50]}...")

                if attempt < max_retries - 1:
                    wait_sec = wait_times[attempt]
                    print(f"    → {wait_sec}秒待機してリトライ...")
                    time.sleep(wait_sec)

        # 3回失敗したらエラー終了
        if audio_data is None:
            error_msg = f"TTS生成失敗（3回リトライ後）: {speaker} - {text[:30]}"
            print(f"  ❌ {error_msg}")
            send_tts_failure_notification(speaker, text, last_error or "不明なエラー")
            raise RuntimeError(error_msg)

        # 音声を結合
        audio_segment = AudioSegment.from_file(io.BytesIO(audio_data), format="wav")
        combined += audio_segment

        # セリフ間に短い間を追加（200ms）
        combined += AudioSegment.silent(duration=200)

    # 出力
    combined.export(output_path, format="wav")

    duration = len(combined) / 1000.0
    print(f"  ✓ 音声生成完了: {duration:.1f}秒")

    return duration


def download_background(output_path: str) -> bool:
    """背景画像をダウンロード"""
    try:
        url = f"https://drive.google.com/uc?export=download&id={BACKGROUND_IMAGE_ID}"
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        with open(output_path, 'wb') as f:
            f.write(response.content)

        return True
    except Exception as e:
        print(f"  ⚠ 背景ダウンロードエラー: {e}")
        return False


def generate_thumbnail(title: str, output_path: str, temp_dir: str):
    """サムネイル生成"""
    width, height = VIDEO_WIDTH, VIDEO_HEIGHT

    # 背景画像をダウンロード
    bg_path = os.path.join(temp_dir, "bg_original.jpg")
    if download_background(bg_path):
        try:
            bg = Image.open(bg_path)
            # リサイズ（アスペクト比維持、クロップ）
            ratio = max(width / bg.width, height / bg.height)
            new_size = (int(bg.width * ratio), int(bg.height * ratio))
            bg = bg.resize(new_size, Image.LANCZOS)
            left = (bg.width - width) // 2
            top = (bg.height - height) // 2
            bg = bg.crop((left, top, left + width, top + height))
            img = bg.convert('RGB')
        except:
            img = Image.new('RGB', (width, height), '#1a1a2e')
    else:
        img = Image.new('RGB', (width, height), '#1a1a2e')

    # 半透明オーバーレイ
    img = img.convert('RGBA')
    overlay = Image.new('RGBA', (width, 500), (0, 0, 0, 150))
    img.paste(overlay, (0, height // 2 - 250), overlay)
    img = img.convert('RGB')

    # フォント
    try:
        font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 72)
    except:
        font = ImageFont.load_default()

    draw = ImageDraw.Draw(img)

    # タイトル
    title_short = title[:15] if len(title) > 15 else title

    # 縁取り
    for dx, dy in [(-3, -3), (-3, 3), (3, -3), (3, 3)]:
        draw.text((width // 2 + dx, height // 2 + dy), title_short,
                  font=font, fill='black', anchor='mm')
    draw.text((width // 2, height // 2), title_short,
              font=font, fill='white', anchor='mm')

    img.save(output_path, quality=95)


def generate_subtitles(script: list, audio_duration: float, output_path: str):
    """ASS字幕を生成"""
    # 各セリフの時間を均等に分割
    time_per_line = audio_duration / len(script)

    header = f"""[Script Info]
Title: Nenkin Short
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hiroshi,Noto Sans CJK JP,100,&H0000FFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,2,50,50,400,1
Style: Katsumi,Noto Sans CJK JP,100,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,2,50,50,400,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]

    for i, line in enumerate(script):
        start_time = i * time_per_line
        end_time = (i + 1) * time_per_line

        start_str = f"0:{int(start_time // 60):02d}:{start_time % 60:05.2f}"
        end_str = f"0:{int(end_time // 60):02d}:{end_time % 60:05.2f}"

        style = "Hiroshi" if line["speaker"] == "ヒロシ" else "Katsumi"
        text = line["text"].replace('\n', '\\N')

        lines.append(f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{text}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def generate_video(audio_path: str, thumbnail_path: str, subtitle_path: str, output_path: str):
    """動画を生成"""
    print("\n[4/6] 動画を生成中...")

    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', thumbnail_path,
        '-i', audio_path,
        '-vf', f'scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},ass={subtitle_path}',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '192k',
        '-shortest',
        '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ⚠ ffmpegエラー: {result.stderr}")
        raise RuntimeError("動画生成に失敗しました")

    print(f"  ✓ 動画生成完了: {output_path}")


def upload_to_youtube(video_path: str, title: str, description: str) -> str:
    """YouTubeにアップロード"""
    print("\n[5/6] YouTubeにアップロード中...")

    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN_23")

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError("YouTube認証情報が不足")

    # アクセストークン取得
    response = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    })
    access_token = response.json()["access_token"]

    from google.oauth2.credentials import Credentials
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token"
    )
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["年金", "ニュース", "Shorts", "控室トーク"],
            "categoryId": "25"
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
            print(f"  アップロード進捗: {int(status.progress() * 100)}%")

    video_id = response["id"]
    url = f"https://www.youtube.com/watch?v={video_id}"

    print(f"  ✓ アップロード完了: {url}")
    return url


def generate_first_comment(script: list, key_manager: GeminiKeyManager) -> str:
    """台本内容からカツミとしてのコメントを生成"""
    print("\n[6/7] コメントを生成中...")

    # 台本をテキスト化
    script_text = "\n".join([f"{line['speaker']}: {line['text']}" for line in script])

    prompt = f"""あなたはカツミ（60代女性、年金ニュースラジオのパーソナリティ）です。
今回のショート動画の内容について、視聴者へのコメントを書いてください。

【今回の動画の内容】
{script_text}

【ルール】
- カツミとして、今回の動画の話題に触れる一言（2〜3文）
- 高齢女性に親しみやすい丁寧な口調
- 最後に「お得な情報を逃さないように」という損得メリットでLINE登録を自然に誘導
- 押し売り感NG、さりげなく
- 絵文字は控えめに（1〜2個まで）

【最後に必ず入れる】
LINEのURL: https://line.me/R/ti/p/@424lkquq

コメント本文のみを出力してください。"""

    # リトライ処理
    max_retries = 3
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=key_manager.get_key())
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.7)
            )
            comment = response.text.strip()
            print(f"  ✓ コメント生成完了")
            print(f"  {comment[:50]}...")
            return comment
        except Exception as e:
            error_str = str(e)
            print(f"  ⚠ 試行{attempt + 1}/{max_retries} 失敗: {error_str[:50]}...")
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                key_manager.next_key()
                time.sleep(5)
            else:
                time.sleep(3)
            if attempt == max_retries - 1:
                print(f"  ⚠ コメント生成失敗、スキップします")
                return None


def post_first_comment(video_id: str, comment_text: str) -> bool:
    """YouTubeに最初のコメントを投稿"""
    print("\n[7/7] コメントを投稿中...")

    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN_23")

    if not all([client_id, client_secret, refresh_token]):
        print("  ⚠ YouTube認証情報が不足")
        return False

    try:
        # アクセストークン取得
        response = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        })
        access_token = response.json()["access_token"]

        from google.oauth2.credentials import Credentials
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token"
        )
        youtube = build("youtube", "v3", credentials=creds)

        # コメント投稿
        body = {
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {
                        "textOriginal": comment_text
                    }
                }
            }
        }

        youtube.commentThreads().insert(
            part="snippet",
            body=body
        ).execute()

        print(f"  ✓ コメント投稿完了")
        return True

    except Exception as e:
        print(f"  ⚠ コメント投稿エラー: {e}")
        return False


def send_discord_notification(title: str, url: str, duration: float, comment_posted: bool = False):
    """Discord通知"""
    print("\n[8/8] Discord通知...")

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("  ⚠ DISCORD_WEBHOOK_URL未設定")
        return

    prefix = "【テスト】" if TEST_MODE else ""
    comment_status = "✅" if comment_posted else "❌"

    message = f"""{prefix}🎬 **年金ショート投稿完了！**
━━━━━━━━━━━━━━━━━━
📺 タイトル: {title}
🔗 URL: {url}
⏱️ 動画長: {int(duration)}秒
💬 自動コメント: {comment_status}
━━━━━━━━━━━━━━━━━━"""

    try:
        requests.post(
            webhook_url,
            json={"content": message},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        print("  ✓ Discord通知完了")
    except Exception as e:
        print(f"  ⚠ Discord通知エラー: {e}")


def main():
    """メイン処理"""
    start_time = time.time()

    print("=" * 50)
    print("年金ニュース ショート動画システム v2")
    print("=" * 50)
    print(f"テストモード: {TEST_MODE}")
    print("=" * 50)

    key_manager = GeminiKeyManager()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # 1. ニュース取得
        news = fetch_todays_news(key_manager)

        # 2. 台本生成
        script = generate_script(key_manager, news)

        if not script:
            print("  ❌ 台本が空です")
            return

        # タイトル生成
        today = datetime.now().strftime("%m/%d")
        title = f"年金の裏話 #{today} #Shorts"

        # 3. TTS生成
        audio_path = str(temp_path / "audio.wav")
        duration = generate_tts_audio(script, audio_path, key_manager)

        if duration > MAX_DURATION:
            print(f"  ⚠ 動画が{MAX_DURATION}秒を超えています: {duration:.1f}秒")

        # 4. サムネイル・字幕・動画生成
        thumbnail_path = str(temp_path / "thumbnail.jpg")
        subtitle_path = str(temp_path / "subtitles.ass")
        video_path = str(temp_path / "short.mp4")

        generate_thumbnail(title, thumbnail_path, temp_dir)
        generate_subtitles(script, duration, subtitle_path)
        generate_video(audio_path, thumbnail_path, subtitle_path, video_path)

        # 説明文
        description = f"""🎙️ 年金の本音トーク！控室からお届け

毎日お昼に更新！
本編は毎朝7時配信。チャンネル登録よろしくお願いします。

#年金 #ニュース #Shorts"""

        # 5. YouTubeアップロード
        comment_posted = False
        video_id = None

        if TEST_MODE:
            print("\n[テストモード] YouTubeアップロードをスキップ")
            # テストモード時は動画を保存
            import shutil
            output_video = f"nenkin_short_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            shutil.copy(video_path, output_video)
            print(f"  動画を保存: {output_video}")
            video_url = f"file://{output_video}"
        else:
            video_url = upload_to_youtube(video_path, title, description)
            # URLからvideo_idを抽出
            video_id = video_url.split("v=")[-1] if "v=" in video_url else None

            # 6. コメント生成・投稿
            if video_id:
                comment_text = generate_first_comment(script, key_manager)
                if comment_text:
                    comment_posted = post_first_comment(video_id, comment_text)

        # 7. Discord通知
        send_discord_notification(title, video_url, duration, comment_posted)

        # 完了
        elapsed = time.time() - start_time
        print("\n" + "=" * 50)
        print("処理完了!")
        print(f"処理時間: {elapsed:.1f}秒")
        print("=" * 50)


if __name__ == "__main__":
    main()
