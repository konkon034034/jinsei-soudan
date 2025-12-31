#!/usr/bin/env python3
"""
YouTube動画リメイクシステム（Claude Code統合版）

使い方:
  python3 remake_video.py "https://youtube.com/watch?v=XXXX" --desktop  # 確認用
  python3 remake_video.py "https://youtube.com/watch?v=XXXX" --upload   # 本番用

または エイリアス:
  remake "URL" --desktop
  remake "URL" --upload
"""

import os
import sys
import json
import time
import wave
import shutil
import pickle
import argparse
import subprocess
import traceback
from io import BytesIO
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

import requests
from PIL import Image, ImageDraw
from dotenv import load_dotenv
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai
from google.genai import types

# 環境変数を読み込み
load_dotenv(Path(__file__).parent / ".env")


# ============================================================
# 設定
# ============================================================
class Config:
    """設定クラス"""

    # API
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    # ディレクトリ
    BASE_DIR = Path(__file__).parent
    TEMP_DIR = BASE_DIR / "temp_remake"
    OUTPUT_DIR = Path.home() / "Desktop"

    # キャラクター
    CHARACTERS = {
        "カツミ": {"voice": "Kore", "description": "60代女性・年金専門家"},
        "ヒロシ": {"voice": "Puck", "description": "40代男性・視聴者代表"},
    }

    # 動画設定
    VIDEO_WIDTH = 1920
    VIDEO_HEIGHT = 1080
    AUDIO_BITRATE = "192k"

    # YouTube設定
    YOUTUBE_CATEGORY_ID = "22"  # People & Blogs
    YOUTUBE_PRIVACY = "public"

    # 通知
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
    SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_COMMENT")

    @classmethod
    def create_directories(cls):
        """一時ディレクトリを作成"""
        cls.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        (cls.TEMP_DIR / "images").mkdir(exist_ok=True)
        (cls.TEMP_DIR / "audio").mkdir(exist_ok=True)
        (cls.TEMP_DIR / "video").mkdir(exist_ok=True)

    @classmethod
    def cleanup(cls):
        """一時ディレクトリを削除"""
        if cls.TEMP_DIR.exists():
            shutil.rmtree(cls.TEMP_DIR)


# ============================================================
# 1. 字幕取得（youtube-transcript-api）
# ============================================================
class TranscriptFetcher:
    """YouTube字幕取得"""

    def __init__(self):
        self.api = YouTubeTranscriptApi()

    def extract_video_id(self, url: str) -> str:
        """URLから動画IDを抽出"""
        if "v=" in url:
            return url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in url:
            return url.split("youtu.be/")[1].split("?")[0]
        else:
            raise ValueError(f"無効なYouTube URL: {url}")

    def fetch(self, video_url: str) -> Optional[Dict]:
        """字幕を取得"""
        print(f"\n📝 字幕を取得中...")
        print(f"   URL: {video_url}")

        try:
            video_id = self.extract_video_id(video_url)
            print(f"   動画ID: {video_id}")

            transcript_list = self.api.fetch(video_id, languages=['ja', 'jp'])

            if not transcript_list:
                print("   ❌ 字幕が見つかりません")
                return None

            print(f"   ✓ 字幕取得完了: {len(transcript_list)}件")

            return {
                "video_id": video_id,
                "transcript": transcript_list
            }

        except Exception as e:
            print(f"   ❌ 字幕取得エラー: {e}")
            return None


# ============================================================
# 2. 台本リライト（Gemini API）
# ============================================================
class ScriptRewriter:
    """台本リライト"""

    def __init__(self):
        self.client = genai.Client(api_key=Config.GEMINI_API_KEY)
        self.model = "gemini-2.0-flash"  # 安定版を使用

    def rewrite(self, transcript: list) -> Optional[Dict]:
        """字幕を台本にリライト"""
        print(f"\n📜 台本をリライト中...")

        # 字幕テキストを結合
        transcript_text = "\n".join([
            f"[{item.start:.1f}s] {item.text}"
            for item in transcript
            if hasattr(item, 'text') and item.text
        ])

        prompt = f"""以下の年金ニュース動画の字幕を、カツミ（63歳女性・年金専門家）とヒロシ（47歳男性・視聴者代表）の掛け合い形式の台本にリライトしてください。

【元の字幕】
{transcript_text}

【キャラクター設定】
カツミ（63歳女性）:
- 役割: 年金専門家、メイン解説者
- 口調: 落ち着いた丁寧語、「〜ですね」「〜なんですよ」

ヒロシ（47歳男性）:
- 役割: 視聴者代表、質問役
- 口調: 親しみやすい、「なるほど！」「それって〜ですか？」

【リライトの方針】
1. 元の情報を正確に伝える
2. カツミが主に解説、ヒロシが質問や相槌
3. 1シーンあたり1-2文程度
4. 専門用語は「iDeCo→イデコ」のように読みやすく
5. 各セリフは最低10文字以上

【出力形式】
JSON形式:
{{
  "title": "動画タイトル（30文字以内）",
  "description": "動画の説明文（100文字程度）",
  "scenes": [
    {{
      "scene_id": 1,
      "speaker": "カツミ",
      "text": "セリフ",
      "image_description": "画像の説明"
    }}
  ]
}}

JSONのみを出力してください。"""

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )

                response_text = response.text.strip()

                # JSONブロックを抽出
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0].strip()

                script = json.loads(response_text)

                print(f"   ✓ 台本リライト完了")
                print(f"     タイトル: {script['title']}")
                print(f"     シーン数: {len(script['scenes'])}")

                return script

            except json.JSONDecodeError as e:
                print(f"   ⚠️ JSONパースエラー (試行 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    print(f"   ❌ 台本リライト失敗")
                    return None
            except Exception as e:
                print(f"   ❌ 台本リライトエラー: {e}")
                return None


# ============================================================
# 3. 画像生成（Gemini API）
# ============================================================
class ImageGenerator:
    """画像生成"""

    def __init__(self):
        self.client = genai.Client(api_key=Config.GEMINI_API_KEY)
        self.model = "gemini-2.0-flash-exp-image-generation"
        # フォールバック: Imagen 3
        self.fallback_model = "imagen-3.0-generate-002"

    def generate(self, script: Dict) -> Optional[List[Dict]]:
        """台本から画像を生成"""
        print(f"\n🎨 画像を生成中...")

        images = []
        scenes = script.get("scenes", [])

        for scene in scenes:
            scene_id = scene["scene_id"]
            image_desc = scene["image_description"]

            print(f"   シーン{scene_id}: {image_desc[:30]}...")

            output_path = Config.TEMP_DIR / "images" / f"scene_{scene_id:03d}.png"

            prompt = f"""{image_desc}を表現したイラスト。

【デザイン要件】
- スタイル: Lo-fi風のやさしいイラスト調
- 配色: パステルカラーで温かみのある雰囲気
- レイアウト: シンプルで見やすく
- 文字: なし（イラストのみ）
- アスペクト比: 16:9の横長画像
- 雰囲気: 年金ニュースチャンネル向け"""

            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=[prompt],
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE", "TEXT"],
                    )
                )

                # 画像データを取得
                image_saved = False
                if hasattr(response, 'candidates') and response.candidates:
                    for candidate in response.candidates:
                        if hasattr(candidate, 'content') and candidate.content:
                            if hasattr(candidate.content, 'parts') and candidate.content.parts:
                                for part in candidate.content.parts:
                                    if hasattr(part, 'inline_data') and part.inline_data is not None:
                                        image_bytes = part.inline_data.data
                                        pil_image = Image.open(BytesIO(image_bytes))
                                        image_resized = pil_image.resize((1920, 1080), Image.Resampling.LANCZOS)
                                        image_resized.save(output_path)
                                        image_saved = True
                                        break

                if not image_saved:
                    # ダミー画像を生成
                    self._create_dummy_image(output_path, image_desc)

                images.append({
                    "scene_id": scene_id,
                    "path": output_path
                })
                print(f"     ✓ 保存: {output_path.name}")

                time.sleep(2)  # API制限対策

            except Exception as e:
                print(f"     ⚠️ 画像生成エラー: {e}")
                self._create_dummy_image(output_path, str(e))
                images.append({
                    "scene_id": scene_id,
                    "path": output_path
                })

        print(f"   ✓ 画像生成完了: {len(images)}枚")
        return images

    def _create_dummy_image(self, output_path: Path, text: str):
        """ダミー画像を生成"""
        img = Image.new('RGB', (1920, 1080), color='#2D2D2D')
        draw = ImageDraw.Draw(img)
        draw.text((960, 540), text[:50], fill='white', anchor='mm')
        img.save(output_path)


# ============================================================
# 4. 音声生成（Gemini TTS）
# ============================================================
class TTSGenerator:
    """音声生成（Gemini TTS）"""

    PRONUNCIATION_DICT = {
        "iDeCo": "イデコ",
        "NISA": "ニーサ",
        "65歳": "ろくじゅうごさい",
        "60歳": "ろくじゅっさい",
        "70歳": "ななじゅっさい",
        "75歳": "ななじゅうごさい",
    }

    def __init__(self):
        # 複数のAPIキーをロード
        self.api_keys = self._load_api_keys()
        self.current_key_index = 0
        self.client = genai.Client(api_key=self.api_keys[self.current_key_index])
        self.model = "gemini-2.5-flash-preview-tts"
        print(f"   TTS初期化完了 (キー数: {len(self.api_keys)})")

    def _load_api_keys(self) -> List[str]:
        """複数のAPIキーを読み込み"""
        keys = []

        # GEMINI_API_KEY_1, _2, ... を取得
        i = 1
        while True:
            key = os.getenv(f"GEMINI_API_KEY_{i}")
            if key:
                keys.append(key)
                i += 1
            else:
                break

        # GEMINI_API_KEY も追加
        single_key = os.getenv("GEMINI_API_KEY")
        if single_key and single_key not in keys:
            keys.insert(0, single_key)

        if not keys:
            raise ValueError("GEMINI_API_KEYが設定されていません")

        return keys

    def _switch_api_key(self):
        """次のAPIキーに切り替え"""
        old_idx = self.current_key_index
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        self.client = genai.Client(api_key=self.api_keys[self.current_key_index])
        print(f"     → APIキー切替 ({old_idx + 1} → {self.current_key_index + 1})")

    def normalize_text(self, text: str) -> str:
        """読み方を正規化"""
        for key, value in self.PRONUNCIATION_DICT.items():
            text = text.replace(key, value)
        return text

    def generate(self, script: Dict) -> Optional[Dict]:
        """台本から音声を生成"""
        print(f"\n🎙️ 音声を生成中...")

        audio_files = []
        total_duration = 0.0

        for scene in script["scenes"]:
            scene_id = scene["scene_id"]
            speaker = scene["speaker"]
            text = scene["text"]

            voice_name = Config.CHARACTERS.get(speaker, {}).get("voice", "Kore")
            normalized_text = self.normalize_text(text)

            output_path = Config.TEMP_DIR / "audio" / f"scene_{scene_id:03d}.wav"

            print(f"   シーン{scene_id}: {speaker} - {text[:25]}...")

            # 全APIキーを試行
            success = False
            for attempt in range(len(self.api_keys)):
                try:
                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=normalized_text,
                        config=types.GenerateContentConfig(
                            response_modalities=["AUDIO"],
                            speech_config=types.SpeechConfig(
                                voice_config=types.VoiceConfig(
                                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                        voice_name=voice_name
                                    )
                                )
                            )
                        )
                    )

                    # 音声データを保存
                    if response.candidates and len(response.candidates) > 0:
                        candidate = response.candidates[0]
                        if hasattr(candidate, 'content') and candidate.content:
                            if hasattr(candidate.content, 'parts') and candidate.content.parts:
                                for part in candidate.content.parts:
                                    if hasattr(part, 'inline_data') and part.inline_data:
                                        if hasattr(part.inline_data, 'data'):
                                            pcm_data = part.inline_data.data
                                            self._save_as_wav(pcm_data, output_path)

                                            # 音声の長さを取得
                                            duration = self._get_duration(output_path)

                                            audio_files.append({
                                                "scene_id": scene_id,
                                                "speaker": speaker,
                                                "path": output_path,
                                                "duration": duration
                                            })
                                            total_duration += duration

                                            print(f"     ✓ {duration:.1f}秒")
                                            success = True
                                            break

                    if success:
                        break

                except Exception as e:
                    error_str = str(e)
                    if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                        if attempt < len(self.api_keys) - 1:
                            self._switch_api_key()
                            continue
                    print(f"     ❌ エラー: {e}")
                    break

            if not success:
                print(f"     ⚠️ 音声生成スキップ")

        if not audio_files:
            print("   ❌ 音声ファイルが生成されませんでした")
            return None

        print(f"   ✓ 音声生成完了: {len(audio_files)}ファイル ({total_duration:.1f}秒)")

        return {
            "files": audio_files,
            "total_duration": total_duration
        }

    def _save_as_wav(self, pcm_data: bytes, output_path: Path):
        """PCMデータをWAVファイルとして保存"""
        with wave.open(str(output_path), 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(24000)
            wav_file.writeframes(pcm_data)

    def _get_duration(self, audio_path: Path) -> float:
        """音声ファイルの長さを取得"""
        with wave.open(str(audio_path), 'rb') as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            return frames / float(rate)


# ============================================================
# 5. 動画エンコード（ffmpeg）
# ============================================================
class VideoEncoder:
    """動画エンコード"""

    def encode(self, script: Dict, images: List[Dict], audio_data: Dict) -> Optional[Path]:
        """画像と音声から動画を生成"""
        print(f"\n🎬 動画をエンコード中...")

        video_segments = []

        for scene in script["scenes"]:
            scene_id = scene["scene_id"]

            image = next((img for img in images if img["scene_id"] == scene_id), None)
            audio = next((aud for aud in audio_data["files"] if aud["scene_id"] == scene_id), None)

            if not image or not audio:
                print(f"   ⚠️ シーン{scene_id}: 画像または音声が見つかりません")
                continue

            segment_path = Config.TEMP_DIR / "video" / f"segment_{scene_id:03d}.mp4"

            # ffmpegでセグメントを作成
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", str(image["path"]),
                "-i", str(audio["path"]),
                "-c:v", "libx264",
                "-tune", "stillimage",
                "-c:a", "aac",
                "-b:a", Config.AUDIO_BITRATE,
                "-pix_fmt", "yuv420p",
                "-shortest",
                "-t", str(audio["duration"]),
                str(segment_path)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                video_segments.append(segment_path)
                print(f"   シーン{scene_id}: ✓ ({audio['duration']:.1f}秒)")
            else:
                print(f"   シーン{scene_id}: ❌ ffmpegエラー")

        if not video_segments:
            print("   ❌ 動画セグメントが作成されませんでした")
            return None

        # セグメントを結合
        final_path = Config.TEMP_DIR / "video" / f"{script['title'][:20]}.mp4"

        concat_file = Config.TEMP_DIR / "concat_list.txt"
        with open(concat_file, "w") as f:
            for segment in video_segments:
                f.write(f"file '{segment.absolute()}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(final_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print("   ❌ 動画結合エラー")
            return None

        # クリーンアップ
        concat_file.unlink()
        for segment in video_segments:
            segment.unlink()

        print(f"   ✓ 動画エンコード完了: {final_path.name}")

        return final_path


# ============================================================
# 6. YouTubeアップロード
# ============================================================
class YouTubeUploader:
    """YouTubeアップロード"""

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

    def __init__(self):
        self.youtube = None
        self._authenticate()

    def _authenticate(self):
        """YouTube APIの認証"""
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = None
        token_path = Config.BASE_DIR / "token_youtube.pickle"

        if token_path.exists():
            with open(token_path, "rb") as token:
                creds = pickle.load(token)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # client_secrets.jsonから認証
                client_secrets = Config.BASE_DIR / "client_secrets.json"
                if not client_secrets.exists():
                    raise FileNotFoundError(
                        "client_secrets.json が見つかりません。"
                        "YouTube認証にはclient_secrets.jsonが必要です。"
                    )

                flow = InstalledAppFlow.from_client_secrets_file(
                    str(client_secrets),
                    self.SCOPES
                )
                creds = flow.run_local_server(port=0)

            with open(token_path, "wb") as token:
                pickle.dump(creds, token)

        self.youtube = build("youtube", "v3", credentials=creds)

    def upload(self, video_path: Path, script: Dict) -> Optional[str]:
        """動画をYouTubeにアップロード"""
        from googleapiclient.http import MediaFileUpload

        print(f"\n📤 YouTubeにアップロード中...")

        try:
            title = script["title"]
            description = f"""{script['description']}

【年金ニュースチャンネル】
カツミとヒロシが年金について分かりやすく解説します。

#年金 #老後 #年金制度"""

            request_body = {
                "snippet": {
                    "title": title,
                    "description": description,
                    "tags": ["年金", "老後", "年金制度", "iDeCo", "NISA"],
                    "categoryId": Config.YOUTUBE_CATEGORY_ID
                },
                "status": {
                    "privacyStatus": Config.YOUTUBE_PRIVACY,
                    "selfDeclaredMadeForKids": False
                }
            }

            media = MediaFileUpload(
                str(video_path),
                chunksize=-1,
                resumable=True,
                mimetype="video/mp4"
            )

            request = self.youtube.videos().insert(
                part="snippet,status",
                body=request_body,
                media_body=media
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"   進捗: {int(status.progress() * 100)}%")

            video_id = response["id"]

            print(f"   ✓ アップロード完了")
            print(f"   URL: https://www.youtube.com/watch?v={video_id}")

            return video_id

        except Exception as e:
            print(f"   ❌ アップロードエラー: {e}")
            return None


# ============================================================
# 7. 通知
# ============================================================
class Notifier:
    """通知"""

    @staticmethod
    def discord_success(video_url: str, title: str):
        """Discord成功通知"""
        webhook_url = Config.DISCORD_WEBHOOK_URL
        if not webhook_url:
            print("   ⚠️ DISCORD_WEBHOOK_URLが設定されていません")
            return

        try:
            requests.post(
                webhook_url,
                json={
                    "content": f"✅ **リメイク動画アップロード完了**\n\n**{title}**\n{video_url}"
                },
                timeout=10
            )
            print("   ✓ Discord通知を送信しました")
        except Exception as e:
            print(f"   ⚠️ Discord通知エラー: {e}")

    @staticmethod
    def slack_error(error_message: str):
        """Slackエラー通知"""
        webhook_url = Config.SLACK_WEBHOOK_URL
        if not webhook_url:
            return

        try:
            requests.post(
                webhook_url,
                json={
                    "text": f"❌ リメイクシステムエラー\n```\n{error_message[:500]}\n```"
                },
                timeout=10
            )
        except Exception:
            pass


# ============================================================
# メイン処理
# ============================================================
class VideoRemakeSystem:
    """動画リメイクシステム"""

    def __init__(self, video_url: str, mode: str = "desktop"):
        self.video_url = video_url
        self.mode = mode  # "desktop" or "upload"

        self.transcript_fetcher = TranscriptFetcher()
        self.script_rewriter = ScriptRewriter()
        self.image_generator = ImageGenerator()
        self.tts_generator = TTSGenerator()
        self.video_encoder = VideoEncoder()
        self.youtube_uploader = None

        if mode == "upload":
            self.youtube_uploader = YouTubeUploader()

    def run(self) -> bool:
        """メイン処理"""
        start_time = time.time()

        print("\n" + "=" * 60)
        print("🎬 YouTube動画リメイクシステム")
        print("=" * 60)
        print(f"動画URL: {self.video_url}")
        print(f"モード: {'YouTubeアップロード' if self.mode == 'upload' else 'デスクトップ保存'}")
        print(f"開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            Config.create_directories()

            # 1. 字幕取得
            result = self.transcript_fetcher.fetch(self.video_url)
            if not result:
                raise Exception("字幕取得失敗")

            # 2. 台本リライト
            script = self.script_rewriter.rewrite(result["transcript"])
            if not script:
                raise Exception("台本リライト失敗")

            # 3. 画像生成
            images = self.image_generator.generate(script)
            if not images:
                raise Exception("画像生成失敗")

            # 4. 音声生成
            audio_data = self.tts_generator.generate(script)
            if not audio_data:
                raise Exception("音声生成失敗")

            # 5. 動画エンコード
            video_path = self.video_encoder.encode(script, images, audio_data)
            if not video_path:
                raise Exception("動画エンコード失敗")

            # 6. 出力
            if self.mode == "upload":
                # YouTubeアップロード
                video_id = self.youtube_uploader.upload(video_path, script)
                if not video_id:
                    raise Exception("YouTubeアップロード失敗")

                video_url = f"https://www.youtube.com/watch?v={video_id}"

                # Discord通知
                Notifier.discord_success(video_url, script["title"])

            else:
                # デスクトップに保存
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"remake_{timestamp}.mp4"
                output_path = Config.OUTPUT_DIR / output_filename
                shutil.copy2(video_path, output_path)
                print(f"\n📁 保存先: {output_path}")

            # クリーンアップ
            Config.cleanup()

            # 完了
            elapsed = time.time() - start_time
            print("\n" + "=" * 60)
            print(f"✅ 完了! ({elapsed/60:.1f}分)")
            print("=" * 60)

            return True

        except Exception as e:
            error_msg = f"{e}\n{traceback.format_exc()}"
            print(f"\n❌ エラー: {e}")
            Notifier.slack_error(error_msg)
            Config.cleanup()
            return False


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="YouTube動画リメイクシステム",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  remake "https://youtube.com/watch?v=XXXX" --desktop  # 確認用
  remake "https://youtube.com/watch?v=XXXX" --upload   # 本番用
        """
    )

    parser.add_argument("url", help="YouTube動画のURL")
    parser.add_argument("--desktop", action="store_true", help="デスクトップに保存（確認用）")
    parser.add_argument("--upload", action="store_true", help="YouTubeにアップロード（本番用）")

    args = parser.parse_args()

    # モード判定
    if args.upload:
        mode = "upload"
    else:
        mode = "desktop"  # デフォルト

    # 実行
    system = VideoRemakeSystem(args.url, mode)
    success = system.run()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
