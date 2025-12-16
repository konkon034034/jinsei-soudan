#!/usr/bin/env python3
"""
年金ニュース動画自動生成システム
- TOKEN_23（年金ニュースチャンネル）用
- Gemini APIでニュース収集→台本生成→Fish Audio TTS→動画生成→YouTube投稿
"""

import os
import sys
import json
import re
import time
import tempfile
import requests
import subprocess
from datetime import datetime
from pathlib import Path

import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image, ImageDraw, ImageFont
from gtts import gTTS

# ===== 定数 =====
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
CHANNEL = "23"  # TOKEN_23固定

# ===== Fish Audio TTS設定 =====
FISH_AUDIO_API_KEY = os.environ.get("FISH_AUDIO_API_KEY", "")
FISH_AUDIO_API_URL = "https://api.fish.audio/v1/tts"

# TOKEN_23用ボイス設定（カツミ=男性、ヒロシ=女性）
FISH_VOICE_KATSUMI = "3ea9e8922a2549f5833c2198de843041"  # Takaeshi（男性）
FISH_VOICE_HIROSHI = "acc8237220d8470985ec9be6c4c480a9"  # Hatsune Miku（女性）

CHARACTERS = {
    "カツミ": {"voice": FISH_VOICE_KATSUMI, "color": "#4169E1"},
    "ヒロシ": {"voice": FISH_VOICE_HIROSHI, "color": "#FF6347"}
}

# Unsplash API設定
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
UNSPLASH_API_URL = "https://api.unsplash.com/search/photos"


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


def get_google_credentials():
    """サービスアカウント認証"""
    key_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if not key_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY が設定されていません")
    key_data = json.loads(key_json)
    return Credentials.from_service_account_info(
        key_data,
        scopes=[
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/drive"
        ]
    )


def search_pension_news(key_manager: GeminiKeyManager) -> list:
    """Gemini APIで年金関連ニュースを検索"""
    api_key, key_name = key_manager.get_working_key()
    if not api_key:
        print("❌ Gemini APIキーがありません")
        return []

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = """
あなたは年金ニュースの専門リサーチャーです。
今日の日本の年金に関する最新ニュースを3つ調べて、以下のJSON形式で出力してください。

情報源:
- 厚生労働省
- 日本年金機構
- Yahoo!ニュース
- NHKニュース

出力形式:
```json
[
  {
    "title": "ニュースタイトル",
    "summary": "ニュースの要約（100文字程度）",
    "source": "情報源",
    "impact": "年金受給者への影響（50文字程度）"
  }
]
```

注意:
- 最新のニュースを優先
- 年金受給者に関係する内容を選ぶ
- デマや不確かな情報は含めない
"""

    try:
        response = model.generate_content(prompt)
        text = response.text

        # JSON部分を抽出
        json_match = re.search(r'\[[\s\S]*\]', text)
        if json_match:
            news_list = json.loads(json_match.group())
            print(f"✓ {len(news_list)}件のニュースを取得")
            return news_list
    except Exception as e:
        print(f"❌ ニュース検索エラー: {e}")
        key_manager.mark_failed(key_name)

    return []


def generate_script(news_list: list, key_manager: GeminiKeyManager) -> dict:
    """ニュースから台本を生成"""
    api_key, key_name = key_manager.get_working_key()
    if not api_key:
        return None

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    news_text = "\n".join([
        f"【ニュース{i+1}】{n['title']}\n{n['summary']}\n影響: {n['impact']}"
        for i, n in enumerate(news_list)
    ])

    prompt = f"""
あなたは年金ニュース番組の台本作家です。
以下のニュースを元に、カツミとヒロシの掛け合い台本を作成してください。

【登場人物】
- カツミ: 優しく丁寧に解説する司会者。年金制度に詳しい。
- ヒロシ: 視聴者目線で質問する。時々ツッコミも入れる。

【ニュース】
{news_text}

【台本形式】
以下のJSON形式で出力してください:
```json
{{
  "title": "動画タイトル（30文字以内）",
  "description": "動画の説明文（100文字程度）",
  "tags": ["タグ1", "タグ2", "タグ3"],
  "opening": [
    {{"speaker": "カツミ", "text": "オープニングの挨拶"}},
    {{"speaker": "ヒロシ", "text": "リアクション"}}
  ],
  "news_sections": [
    {{
      "news_title": "ニュース1のタイトル",
      "dialogue": [
        {{"speaker": "カツミ", "text": "ニュースの解説"}},
        {{"speaker": "ヒロシ", "text": "質問やリアクション"}},
        {{"speaker": "カツミ", "text": "補足説明"}}
      ]
    }}
  ],
  "ending": [
    {{"speaker": "カツミ", "text": "まとめ"}},
    {{"speaker": "ヒロシ", "text": "締めの一言"}}
  ]
}}
```

【注意】
- 各セリフは50文字以内
- 難しい用語は分かりやすく言い換える
- ヒロシは視聴者が思いそうな疑問を代弁する
"""

    try:
        response = model.generate_content(prompt)
        text = response.text

        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            script = json.loads(json_match.group())
            print(f"✓ 台本生成完了: {script.get('title', 'タイトルなし')}")
            return script
    except Exception as e:
        print(f"❌ 台本生成エラー: {e}")
        key_manager.mark_failed(key_name)

    return None


def detect_emotion_tag(speaker: str, text: str) -> str:
    """感情タグを判定"""
    if speaker == "ヒロシ":
        if any(w in text for w in ["えっ", "マジ", "本当"]):
            return "(surprised) "
        if any(w in text for w in ["なるほど", "そうなんだ"]):
            return "(empathetic) "
    return ""


def generate_fish_audio_tts(text: str, voice_id: str, output_path: str, max_retries: int = 3) -> bool:
    """Fish Audio APIで音声生成"""
    if not FISH_AUDIO_API_KEY:
        print("    [Fish Audio] APIキーなし")
        return False

    headers = {
        "Authorization": f"Bearer {FISH_AUDIO_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {"text": text, "reference_id": voice_id, "format": "wav"}

    for attempt in range(max_retries):
        try:
            response = requests.post(FISH_AUDIO_API_URL, headers=headers, json=payload, timeout=60)
            if response.status_code == 200:
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return True
            print(f"      [試行{attempt+1}] エラー: {response.status_code}")
        except Exception as e:
            print(f"      [試行{attempt+1}] 例外: {e}")
        time.sleep(2)

    return False


def generate_gtts_fallback(text: str, output_path: str) -> bool:
    """gTTSフォールバック"""
    try:
        tts = gTTS(text=text, lang='ja')
        temp_mp3 = output_path.replace('.wav', '.mp3')
        tts.save(temp_mp3)
        subprocess.run([
            'ffmpeg', '-y', '-i', temp_mp3,
            '-acodec', 'pcm_s16le', '-ar', '24000', '-ac', '1',
            output_path
        ], capture_output=True)
        if os.path.exists(temp_mp3):
            os.remove(temp_mp3)
        return True
    except:
        return False


def generate_dialogue_audio(dialogue: list, output_path: str, temp_dir: Path) -> tuple:
    """対話音声を生成"""
    audio_files = []
    segments = []
    current_time = 0.0

    for idx, line in enumerate(dialogue):
        speaker = line["speaker"]
        text = line["text"]
        voice_id = CHARACTERS[speaker]["voice"]

        emotion_tag = detect_emotion_tag(speaker, text)
        tagged_text = emotion_tag + text

        temp_audio = str(temp_dir / f"line_{idx:03d}.wav")

        if generate_fish_audio_tts(tagged_text, voice_id, temp_audio):
            audio_files.append(temp_audio)
        elif generate_gtts_fallback(text, temp_audio):
            audio_files.append(temp_audio)

    if not audio_files:
        return None, [], 0.0

    # 音声を結合
    list_file = temp_dir / "concat.txt"
    with open(list_file, 'w') as f:
        for af in audio_files:
            f.write(f"file '{af}'\n")

    subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(list_file),
        '-acodec', 'pcm_s16le', '-ar', '24000', '-ac', '1', output_path
    ], capture_output=True)

    # 長さ取得
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', output_path
    ], capture_output=True, text=True)
    total_duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0

    # セグメント情報を推定
    total_chars = sum(len(line["text"]) for line in dialogue)
    for line in dialogue:
        ratio = len(line["text"]) / total_chars if total_chars > 0 else 1/len(dialogue)
        duration = total_duration * ratio
        segments.append({
            "speaker": line["speaker"],
            "text": line["text"],
            "start": current_time,
            "end": current_time + duration,
            "color": CHARACTERS[line["speaker"]]["color"]
        })
        current_time += duration

    # 一時ファイル削除
    for af in audio_files:
        if os.path.exists(af):
            os.remove(af)

    return output_path, segments, total_duration


def fetch_unsplash_image(query: str, output_path: str) -> bool:
    """Unsplash APIで画像取得"""
    if not UNSPLASH_ACCESS_KEY:
        return False

    try:
        headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
        params = {"query": query, "per_page": 1, "orientation": "landscape"}
        response = requests.get(UNSPLASH_API_URL, headers=headers, params=params, timeout=30)

        if response.status_code == 200:
            data = response.json()
            if data.get("results"):
                img_url = data["results"][0]["urls"]["regular"]
                img_response = requests.get(img_url, timeout=30)
                with open(output_path, 'wb') as f:
                    f.write(img_response.content)

                # リサイズ
                img = Image.open(output_path)
                img = img.resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.LANCZOS)
                img.save(output_path)
                return True
    except Exception as e:
        print(f"    [Unsplash] エラー: {e}")

    return False


def generate_gradient_background(output_path: str, title: str = ""):
    """グラデーション背景を生成"""
    img = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT))
    draw = ImageDraw.Draw(img)

    # 青系グラデーション
    for y in range(VIDEO_HEIGHT):
        r = int(20 + (y / VIDEO_HEIGHT) * 30)
        g = int(40 + (y / VIDEO_HEIGHT) * 60)
        b = int(80 + (y / VIDEO_HEIGHT) * 100)
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=(r, g, b))

    img.save(output_path)


def generate_ass_subtitles(segments: list, output_path: str):
    """ASS字幕を生成"""
    margin_katsumi = int(VIDEO_HEIGHT * 0.35)
    margin_hiroshi = int(VIDEO_HEIGHT * 0.20)

    header = f"""[Script Info]
Title: 年金ニュース
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Katsumi,Noto Sans CJK JP,64,&H00FFE4B5,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,50,50,{margin_katsumi},1
Style: Hiroshi,Noto Sans CJK JP,64,&H006495ED,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,50,50,{margin_hiroshi},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    for seg in segments:
        start = f"0:{int(seg['start']//60):02d}:{int(seg['start']%60):02d}.{int((seg['start']%1)*100):02d}"
        end = f"0:{int(seg['end']//60):02d}:{int(seg['end']%60):02d}.{int((seg['end']%1)*100):02d}"
        style = "Katsumi" if seg["speaker"] == "カツミ" else "Hiroshi"
        text = f"{seg['speaker']}：{seg['text']}"
        lines.append(f"Dialogue: 0,{start},{end},{style},,0,0,0,,{text}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def create_video(script: dict, temp_dir: Path, key_manager: GeminiKeyManager) -> tuple:
    """動画を作成"""
    all_dialogue = []
    all_segments = []

    # オープニング
    all_dialogue.extend(script.get("opening", []))

    # ニュースセクション
    for section in script.get("news_sections", []):
        all_dialogue.extend(section.get("dialogue", []))

    # エンディング
    all_dialogue.extend(script.get("ending", []))

    print(f"  セリフ数: {len(all_dialogue)}")

    # 音声生成
    audio_path = str(temp_dir / "audio.wav")
    _, segments, duration = generate_dialogue_audio(all_dialogue, audio_path, temp_dir)
    all_segments = segments

    if duration == 0:
        raise ValueError("音声生成に失敗しました")

    print(f"  音声長: {duration:.1f}秒")

    # 背景画像
    bg_path = str(temp_dir / "background.png")
    if not fetch_unsplash_image("pension elderly japan", bg_path):
        generate_gradient_background(bg_path, script.get("title", ""))

    # ASS字幕
    ass_path = str(temp_dir / "subtitles.ass")
    generate_ass_subtitles(all_segments, ass_path)

    # 動画生成
    output_path = str(temp_dir / f"nenkin_news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")

    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', bg_path,
        '-i', audio_path,
        '-vf', f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},ass={ass_path}",
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '192k',
        '-shortest',
        '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        output_path
    ]

    subprocess.run(cmd, capture_output=True, check=True)
    print(f"✓ 動画生成完了: {output_path}")

    return output_path, ass_path


def upload_to_youtube(video_path: str, title: str, description: str, tags: list) -> str:
    """YouTubeにアップロード（TOKEN_23、限定公開）"""
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
    creds = OAuthCredentials(token=access_token)
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "25"  # ニュース
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
    url = f"https://www.youtube.com/watch?v={video_id}"

    # アップロード完了メッセージを表示
    print("\n" + "=" * 40)
    print("YouTube投稿完了!")
    print("=" * 40)
    print(f"動画URL: {url}")
    print(f"チャンネル: TOKEN_23")
    print(f"タイトル: {title}")
    print(f"公開設定: 限定公開")
    print("=" * 40)

    return url


def main():
    """メイン処理"""
    print("=" * 50)
    print("年金ニュース動画生成システム")
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    key_manager = GeminiKeyManager()

    # 1. ニュース検索
    print("\n[1/4] 年金ニュースを検索中...")
    news_list = search_pension_news(key_manager)
    if not news_list:
        print("❌ ニュースが見つかりませんでした")
        return

    # 2. 台本生成
    print("\n[2/4] 台本を生成中...")
    script = generate_script(news_list, key_manager)
    if not script:
        print("❌ 台本生成に失敗しました")
        return

    # 3. 動画生成
    print("\n[3/4] 動画を生成中...")
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        video_path, _ = create_video(script, temp_path, key_manager)

        # 4. YouTube投稿
        print("\n[4/4] YouTubeに投稿中...")
        title = f"【{datetime.now().strftime('%Y/%m/%d')}】今日の年金ニュース"
        description = script.get("description", "今日の年金ニュースをお届けします。")
        tags = script.get("tags", ["年金", "ニュース", "シニア"])

        try:
            url = upload_to_youtube(video_path, title, description, tags)
            # アップロード完了メッセージは upload_to_youtube 内で表示済み
        except Exception as e:
            print(f"❌ YouTube投稿エラー: {e}")
            # ローカルに保存
            import shutil
            output_file = f"nenkin_news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            shutil.copy(video_path, output_file)
            print(f"   ローカル保存: {output_file}")


if __name__ == "__main__":
    main()
