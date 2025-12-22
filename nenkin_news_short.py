#!/usr/bin/env python3
"""
年金ニュース ショート動画自動生成システム
- TOKEN_23（年金ニュースチャンネル）用
- 縦型 1080x1920、60秒以内
- 控室トーク（攻めた本音モード）
"""

import os
import sys
import json
import re
import time
import tempfile
import requests
import subprocess
import wave
import base64
from datetime import datetime
from pathlib import Path

import google.generativeai as genai
from google import genai as genai_tts
from google.genai import types
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image, ImageDraw, ImageFont

# ===== 定数 =====
VIDEO_WIDTH = 1080   # 縦型
VIDEO_HEIGHT = 1920  # 縦型
MAX_DURATION = 60    # 60秒以内

# テストモード
TEST_MODE = os.environ.get("TEST_MODE", "").lower() == "true"

# ===== TTS設定 =====
GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"
TTS_VOICE_KATSUMI = "Kore"   # カツミ（女性）
TTS_VOICE_HIROSHI = "Puck"  # ヒロシ（男性）

# 控室モードの指示文
TTS_INSTRUCTION = """あなたはラジオ番組の控室でくつろいでいるパーソナリティです。

【重要な指示】
- リラックスした本音トーク
- 番組では言えないぶっちゃけトーク
- テンポよく、でも自然に

【カツミの声の特徴（Kore音声）】
- 控室では砕けた口調
- ぶっちゃけ発言多め
- でも基本は優しい

【ヒロシの声の特徴（Puck音声）】
- のんびり素朴
- でも鋭いツッコミ
- 共感力高い

【読み上げルール】
- [カツミ] で始まる行はカツミの声で読む
- [ヒロシ] で始まる行はヒロシの声で読む
- 話者名は読み上げず、セリフ部分のみ読む"""


class GeminiKeyManager:
    """Gemini APIキー管理"""
    def __init__(self):
        self.keys = []
        base_key = os.environ.get("GEMINI_API_KEY")
        if base_key:
            self.keys.append(base_key)
        for i in range(1, 10):
            key = os.environ.get(f"GEMINI_API_KEY_{i}")
            if key:
                self.keys.append(key)
        self.failed_keys = set()

    def get_working_key(self):
        for key in self.keys:
            if key not in self.failed_keys:
                return key, f"KEY_{self.keys.index(key)}"
        self.failed_keys.clear()
        return self.keys[0] if self.keys else None, "KEY_0"

    def mark_failed(self, key_name):
        idx = int(key_name.split("_")[1]) if "_" in key_name else 0
        if idx < len(self.keys):
            self.failed_keys.add(self.keys[idx])


def fetch_pension_news(key_manager: GeminiKeyManager) -> dict:
    """年金ニュースを1件取得"""
    api_key, key_name = key_manager.get_working_key()
    if not api_key:
        raise ValueError("Gemini APIキーが設定されていません")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    today = datetime.now().strftime("%Y年%m月%d日")

    prompt = f"""今日は{today}です。

年金に関する最新ニュースを1件、インターネットで検索して教えてください。
ショート動画で使うので、インパクトのある話題を選んでください。

【出力形式】JSONのみ出力
```json
{{
  "headline": "ニュースの見出し（30文字以内）",
  "summary": "ニュースの要約（100文字以内）",
  "impact": "国民への影響（50文字以内）",
  "source": "情報源",
  "date": "ニュースの日付"
}}
```"""

    response = model.generate_content(
        prompt,
        generation_config={"temperature": 0.7}
    )

    text = response.text
    json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))

    # JSONブロックがない場合
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(0))

    raise ValueError("ニュース取得失敗")


def generate_short_script(news: dict, key_manager: GeminiKeyManager) -> dict:
    """ショート用の控室トーク台本を生成（60秒以内）"""
    api_key, key_name = key_manager.get_working_key()
    if not api_key:
        raise ValueError("Gemini APIキーが設定されていません")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = f"""あなたは年金ラジオ番組の台本作家です。
控室でのオフレコ本音トークの台本を作成してください。

【ニュース】
{news['headline']}
{news['summary']}
影響: {news['impact']}

【設定】
- 控室でくつろぎながらの雑談
- 番組では言えない本音、ぶっちゃけトーク
- 攻めた発言OK（でも下品にはならない）
- 「これ言っていいのかな」的な発言も歓迎

【キャラクター】
- カツミ（50代女性）: 元・年金事務所勤務。裏事情に詳しい。控室では毒舌。
- ヒロシ（40代男性）: 素朴なサラリーマン。鋭いツッコミ。

【重要な制約】
- 合計6〜8セリフ（60秒以内に収まるように）
- 各セリフは短く（30文字以内推奨）
- テンポよく
- 最後は「あっ、本番始まるよ」的な終わり方

【出力形式】JSONのみ
```json
{{
  "title": "攻めたタイトル（例：年金の闇を暴露）",
  "dialogue": [
    {{"speaker": "カツミ", "text": "セリフ"}},
    {{"speaker": "ヒロシ", "text": "セリフ"}}
  ]
}}
```"""

    response = model.generate_content(
        prompt,
        generation_config={"temperature": 0.9}
    )

    text = response.text
    json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))

    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(0))

    raise ValueError("台本生成失敗")


def generate_tts_audio(dialogue: list, output_path: str, key_manager: GeminiKeyManager) -> float:
    """Gemini TTSで音声生成（リトライ付き）"""

    # 台本をテキスト形式に変換
    script_text = ""
    for line in dialogue:
        speaker = line["speaker"]
        text = line["text"]
        script_text += f"[{speaker}] {text}\n"

    # リトライロジック（最大10回、異なるAPIキーを試す）
    max_retries = 10
    last_error = None

    for attempt in range(max_retries):
        api_key, key_name = key_manager.get_working_key()
        if not api_key:
            raise ValueError("Gemini APIキーが設定されていません")

        try:
            print(f"  TTS生成試行 {attempt + 1}/{max_retries} ({key_name})")
            client = genai_tts.Client(api_key=api_key)

            response = client.models.generate_content(
                model=GEMINI_TTS_MODEL,
                contents=script_text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                            speaker_voice_configs=[
                                types.SpeakerVoiceConfig(
                                    speaker="カツミ",
                                    voice_config=types.VoiceConfig(
                                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                            voice_name=TTS_VOICE_KATSUMI
                                        )
                                    )
                                ),
                                types.SpeakerVoiceConfig(
                                    speaker="ヒロシ",
                                    voice_config=types.VoiceConfig(
                                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                            voice_name=TTS_VOICE_HIROSHI
                                        )
                                    )
                                )
                            ]
                        )
                    ),
                    system_instruction=TTS_INSTRUCTION
                )
            )

            # 音声データを保存
            audio_data = response.candidates[0].content.parts[0].inline_data.data
            break  # 成功したらループを抜ける

        except Exception as e:
            last_error = e
            print(f"  ⚠ TTS生成エラー (試行 {attempt + 1}): {e}")
            key_manager.mark_failed(key_name)
            if attempt < max_retries - 1:
                print(f"  リトライします...")
                time.sleep(2)  # 2秒待機
            else:
                raise ValueError(f"TTS生成に{max_retries}回失敗しました: {last_error}")

    with open(output_path, "wb") as f:
        f.write(audio_data)

    # 音声長を取得
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', output_path],
        capture_output=True, text=True
    )
    duration = float(result.stdout.strip())

    print(f"  ✓ TTS生成完了: {duration:.1f}秒")
    return duration


def generate_thumbnail(title: str, output_path: str):
    """縦型サムネイル生成（赤と黄色で派手に）"""
    width, height = 1080, 1920

    # 赤いグラデーション背景
    img = Image.new('RGB', (width, height), '#CC0000')
    draw = ImageDraw.Draw(img)

    # 黄色の斜めストライプ
    for i in range(-height, width + height, 80):
        draw.line([(i, 0), (i + height, height)], fill='#FFD700', width=30)

    # 黒い半透明オーバーレイ（中央）
    overlay = Image.new('RGBA', (width, 400), (0, 0, 0, 180))
    img.paste(Image.alpha_composite(
        Image.new('RGBA', overlay.size, (0, 0, 0, 0)), overlay
    ).convert('RGB'), (0, height // 2 - 200))

    # フォント設定
    try:
        font_large = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W9.ttc", 80)
        font_small = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 50)
    except:
        try:
            font_large = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 80)
            font_small = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 50)
        except:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

    draw = ImageDraw.Draw(img)

    # タイトルを描画（黄色、縁取り）
    title_short = title[:15] if len(title) > 15 else title

    # 縁取り（黒）
    for dx, dy in [(-3, -3), (-3, 3), (3, -3), (3, 3)]:
        draw.text((width // 2 + dx, height // 2 + dy), title_short,
                  font=font_large, fill='black', anchor='mm')

    # 本体（黄色）
    draw.text((width // 2, height // 2), title_short,
              font=font_large, fill='#FFD700', anchor='mm')

    # 「控室トーク」ラベル
    draw.text((width // 2, height // 2 - 150), "🎙️ 控室トーク",
              font=font_small, fill='white', anchor='mm')

    # 「#Shorts」ラベル
    draw.text((width // 2, height // 2 + 150), "#Shorts",
              font=font_small, fill='#FFD700', anchor='mm')

    img.save(output_path, quality=95)
    print(f"  ✓ サムネイル生成完了: {output_path}")


def generate_video(audio_path: str, thumbnail_path: str, dialogue: list, output_path: str) -> str:
    """縦型動画を生成（1080x1920）"""

    # 字幕ファイル生成
    ass_path = output_path.replace('.mp4', '.ass')

    # 音声長を取得
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
        capture_output=True, text=True
    )
    total_duration = float(result.stdout.strip())

    # 字幕タイミングを計算（均等分割）
    num_lines = len(dialogue)
    time_per_line = total_duration / num_lines

    # ASS字幕ファイル作成
    ass_content = """[Script Info]
Title: Nenkin Short
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Katsumi,Hiragino Sans,60,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,2,2,50,50,400,1
Style: Hiroshi,Hiragino Sans,60,&H0000FFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,2,2,50,50,400,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    for i, line in enumerate(dialogue):
        start_time = i * time_per_line
        end_time = (i + 1) * time_per_line

        start_str = f"{int(start_time // 3600)}:{int((start_time % 3600) // 60):02d}:{start_time % 60:05.2f}"
        end_str = f"{int(end_time // 3600)}:{int((end_time % 3600) // 60):02d}:{end_time % 60:05.2f}"

        style = "Katsumi" if line["speaker"] == "カツミ" else "Hiroshi"
        text = line["text"].replace('\n', '\\N')

        ass_content += f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{text}\n"

    with open(ass_path, 'w', encoding='utf-8') as f:
        f.write(ass_content)

    # ffmpegで動画生成
    vf_filter = f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,ass={ass_path}"

    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', thumbnail_path,
        '-i', audio_path,
        '-vf', vf_filter,
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '192k',
        '-shortest',
        '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        output_path
    ]

    subprocess.run(cmd, capture_output=True, check=True)
    print(f"  ✓ 動画生成完了: {output_path}")

    return output_path


def get_or_create_playlist(youtube, title="年金ショート"):
    """再生リストを取得または作成"""
    request = youtube.playlists().list(
        part="snippet",
        mine=True,
        maxResults=50
    )
    response = request.execute()

    for playlist in response.get("items", []):
        if playlist["snippet"]["title"] == title:
            print(f"  ✓ 既存の再生リスト発見: {playlist['id']}")
            return playlist["id"]

    # なければ作成
    request = youtube.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title,
                "description": "年金の本音トーク。控室からお届けするショート動画。"
            },
            "status": {
                "privacyStatus": "public"
            }
        }
    )
    response = request.execute()
    print(f"  ✓ 再生リスト作成: {response['id']}")
    return response["id"]


def add_to_playlist(youtube, playlist_id, video_id):
    """動画を再生リストに追加"""
    request = youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": video_id
                }
            }
        }
    )
    response = request.execute()
    print(f"  ✓ 再生リストに追加完了: {video_id}")
    return response


def upload_to_youtube(video_path: str, title: str, description: str, tags: list) -> str:
    """YouTubeにアップロード（TOKEN_23、公開）"""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN_23")

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError("YouTube認証情報が不足しています")

    # アクセストークン取得
    response = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    })
    access_token = response.json()["access_token"]

    from google.oauth2.credentials import Credentials as OAuthCredentials
    creds = OAuthCredentials(
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
            "tags": tags,
            "categoryId": "25"  # ニュース
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

    # 再生リストに追加
    try:
        playlist_id = get_or_create_playlist(youtube, "年金ショート")
        add_to_playlist(youtube, playlist_id, video_id)
        playlist_added = True
    except Exception as e:
        print(f"  ⚠ 再生リスト追加エラー: {e}")
        playlist_added = False

    # 完了メッセージ
    print("\n" + "=" * 40)
    print("YouTube投稿完了!")
    print("=" * 40)
    print(f"動画URL: {url}")
    print(f"チャンネル: TOKEN_23")
    print(f"タイトル: {title}")
    print(f"公開設定: 公開")
    if playlist_added:
        print(f"再生リスト: 年金ショート")
    print("=" * 40)

    return url


def send_discord_notification(title: str, url: str, duration: float, processing_time: float):
    """Discord通知を送信"""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("  ⚠ DISCORD_WEBHOOK_URL未設定")
        return

    proc_minutes = int(processing_time // 60)
    proc_seconds = int(processing_time % 60)
    proc_time_str = f"{proc_minutes}分{proc_seconds}秒" if proc_minutes > 0 else f"{proc_seconds}秒"

    message = f"""🎬 **年金ショート投稿完了！**
━━━━━━━━━━━━━━━━━━
📺 タイトル: {title}
🔗 URL: {url}
📂 再生リスト: 年金ショート
⏱️ 動画長: {int(duration)}秒
🕐 処理時間: {proc_time_str}"""

    try:
        response = requests.post(
            webhook_url,
            json={"content": message},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        if response.status_code in [200, 204]:
            print("  ✓ Discord通知送信完了")
    except Exception as e:
        print(f"  ⚠ Discord通知エラー: {e}")


def main():
    """メイン処理"""
    start_time = time.time()

    print("=" * 50)
    print("年金ニュース ショート動画生成システム")
    print("=" * 50)
    print(f"解像度: {VIDEO_WIDTH}x{VIDEO_HEIGHT} (縦型)")
    print(f"最大長: {MAX_DURATION}秒")
    print(f"テストモード: {TEST_MODE}")
    print("=" * 50)

    key_manager = GeminiKeyManager()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # 1. ニュース取得
        print("\n[1/5] ニュース取得中...")
        news = fetch_pension_news(key_manager)
        print(f"  ✓ {news['headline']}")

        # 2. 台本生成
        print("\n[2/5] 控室トーク台本生成中...")
        script = generate_short_script(news, key_manager)
        print(f"  ✓ タイトル: {script['title']}")
        print(f"  ✓ セリフ数: {len(script['dialogue'])}")

        # 3. TTS生成
        print("\n[3/5] 音声生成中...")
        audio_path = str(temp_path / "audio.wav")
        duration = generate_tts_audio(script['dialogue'], audio_path, key_manager)

        if duration > MAX_DURATION:
            print(f"  ⚠ 音声が{MAX_DURATION}秒を超えています: {duration:.1f}秒")

        # 4. サムネイル生成
        print("\n[4/5] サムネイル生成中...")
        thumbnail_path = str(temp_path / "thumbnail.jpg")
        generate_thumbnail(script['title'], thumbnail_path)

        # 5. 動画生成
        print("\n[5/5] 動画生成中...")
        video_path = str(temp_path / "short.mp4")
        generate_video(audio_path, thumbnail_path, script['dialogue'], video_path)

        # タイトル作成（攻めた感じ + #Shorts）
        today = datetime.now().strftime("%m/%d")
        title = f"{script['title']} #{today} #Shorts"

        # 説明文
        description = f"""🎙️ 控室からお届けする本音トーク

{news['headline']}

毎日お昼に更新！
チャンネル登録よろしくお願いします。

#年金 #ニュース #Shorts #控室トーク"""

        tags = ["年金", "ニュース", "Shorts", "控室トーク", "本音", "ぶっちゃけ"]

        # YouTubeアップロード
        if TEST_MODE:
            print("\n[テストモード] YouTubeアップロードをスキップ")
            video_url = "https://youtube.com/test"
        else:
            print("\n[6/5] YouTubeアップロード中...")
            video_url = upload_to_youtube(video_path, title, description, tags)

        # 処理時間
        processing_time = time.time() - start_time

        # Discord通知
        send_discord_notification(title, video_url, duration, processing_time)

        print("\n" + "=" * 50)
        print("処理完了!")
        print(f"処理時間: {processing_time:.1f}秒")
        print("=" * 50)


if __name__ == "__main__":
    main()
