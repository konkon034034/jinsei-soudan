#!/usr/bin/env python3
"""
朝ドラランキング動画自動生成システム
- モードA: 完全自動（gTTS）
- モードB: 高品質（NotebookLM）前半処理

参考: https://zenn.dev/xtm_blog/articles/da1eba90525f91
"""

import os
import sys
import json
import re
import time
import tempfile
import requests
import random
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
import base64
import struct
import wave

import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
# moviepy 1.0.3 対応
try:
    from moviepy.editor import (
        ImageClip, AudioFileClip, TextClip, CompositeVideoClip,
        concatenate_videoclips, concatenate_audioclips
    )
except ImportError:
    # moviepy 2.0 対応
    from moviepy import (
        ImageClip, AudioFileClip, TextClip, CompositeVideoClip,
        concatenate_videoclips, concatenate_audioclips
    )
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from gtts import gTTS
from icrawler.builtin import GoogleImageCrawler
import logging
logging.getLogger('icrawler').setLevel(logging.ERROR)  # icrawlerのログを抑制


# ===== 定数 =====
SPREADSHEET_ID = "15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo"
SHEET_NAME = "YouTube自動投稿"
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
FPS = 24

# ===== テストモード設定 =====
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"
RANKING_COUNT = 3 if TEST_MODE else 10  # テスト時はTOP3、本番はTOP10

# ElevenLabs TTS設定
# 日本語対応ボイスを使用（eleven_multilingual_v2）
ELEVENLABS_VOICE_MALE = "pNInz6obpgDQGcFmaJgB"       # 男性: Adam（落ち着いた大人の男性）
ELEVENLABS_VOICE_FEMALE = "21m00Tcm4TlvDq8ikWAM"     # 女性: Rachel（落ち着いた大人の女性）
ELEVENLABS_VOICE_IKEMEN_A = "TxGEqnHWrfWFTfGW9XjX"   # イケボA: Josh（若い爽やか男性）
ELEVENLABS_VOICE_IKEMEN_B = "yoZ06aMxZJJ28mfd3POQ"   # イケボB: Sam（若い甘い声の男性）

# チャンネルごとのボイス設定
# channel: (カツミのボイス, ヒロシのボイス)
CHANNEL_VOICE_CONFIG = {
    "27": (ELEVENLABS_VOICE_FEMALE, ELEVENLABS_VOICE_MALE),       # 朝ドラ: カツミ=女性, ヒロシ=男性
    "23": (ELEVENLABS_VOICE_MALE, ELEVENLABS_VOICE_FEMALE),       # 昭和の曲: カツミ=男性, ヒロシ=女性
    "24": (ELEVENLABS_VOICE_IKEMEN_A, ELEVENLABS_VOICE_IKEMEN_B), # 瀬戸内寂聴: カツミ=イケボA, ヒロシ=イケボB
}

# デフォルトのキャラクター設定（チャンネルに応じて voice_id を動的に設定）
CHARACTERS = {
    "カツミ": {
        "voice_id": ELEVENLABS_VOICE_FEMALE,  # デフォルト（動的に変更される）
        "color": "#4169E1",  # 青（知的）
        "description": "メインMC、論理的、紹介・説明担当"
    },
    "ヒロシ": {
        "voice_id": ELEVENLABS_VOICE_MALE,  # デフォルト（動的に変更される）
        "color": "#FF6347",  # 赤（サブ）
        "description": "サブMC、リアクション・共感担当"
    }
}


def get_voice_name(voice_id: str) -> str:
    """ボイスIDから名前を取得"""
    voice_names = {
        ELEVENLABS_VOICE_MALE: "男性(Adam)",
        ELEVENLABS_VOICE_FEMALE: "女性(Rachel)",
        ELEVENLABS_VOICE_IKEMEN_A: "イケボA(Josh)",
        ELEVENLABS_VOICE_IKEMEN_B: "イケボB(Sam)",
    }
    return voice_names.get(voice_id, "不明")


def setup_channel_voices(channel: str):
    """チャンネルに応じてキャラクターのボイスIDを設定"""
    if channel in CHANNEL_VOICE_CONFIG:
        katsumi_voice, hiroshi_voice = CHANNEL_VOICE_CONFIG[channel]
        CHARACTERS["カツミ"]["voice_id"] = katsumi_voice
        CHARACTERS["ヒロシ"]["voice_id"] = hiroshi_voice
        print(f"  ボイス設定: カツミ={get_voice_name(katsumi_voice)}, "
              f"ヒロシ={get_voice_name(hiroshi_voice)}")


class GeminiKeyManager:
    """複数のGemini APIキーを管理（429エラー時のフォールバック対応）"""

    def __init__(self):
        self.keys = []
        self.key_names = []  # デバッグ用にキー名を保持

        # GEMINI_API_KEY, GEMINI_API_KEY_1, _2, _3... を収集
        base_key = os.environ.get("GEMINI_API_KEY")
        if base_key:
            self.keys.append(base_key)
            self.key_names.append("GEMINI_API_KEY")

        for i in range(1, 10):
            key = os.environ.get(f"GEMINI_API_KEY_{i}")
            if key:
                self.keys.append(key)
                self.key_names.append(f"GEMINI_API_KEY_{i}")

        if not self.keys:
            raise ValueError("GEMINI_API_KEY が設定されていません")

        self.current_index = 0
        self.failed_keys = set()  # 失敗したキーのインデックス

        print(f"\n{'='*50}")
        print(f"Gemini APIキー: {len(self.keys)}個 検出")
        print(f"{'='*50}")
        for i, name in enumerate(self.key_names):
            print(f"  [{i+1}] {name}: ✓")
        print(f"フォールバック順: {' → '.join(self.key_names)}")
        print(f"{'='*50}\n")

    def get_key(self):
        """次のAPIキーを取得（ラウンドロビン）"""
        key = self.keys[self.current_index]
        name = self.key_names[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.keys)
        return key, name

    def get_random_key(self):
        """ランダムなAPIキーを取得"""
        idx = random.randint(0, len(self.keys) - 1)
        return self.keys[idx], self.key_names[idx]

    def mark_failed(self, key_name: str):
        """キーを失敗としてマーク"""
        if key_name in self.key_names:
            idx = self.key_names.index(key_name)
            self.failed_keys.add(idx)
            print(f"  [!] {key_name} をスキップ対象に追加")

    def get_working_key(self):
        """動作するキーを取得（失敗したキーをスキップ）"""
        for i in range(len(self.keys)):
            if i not in self.failed_keys:
                return self.keys[i], self.key_names[i]
        # 全て失敗している場合はリセットして最初から
        print("  [!] 全キーが失敗。リセットして再試行...")
        self.failed_keys.clear()
        return self.keys[0], self.key_names[0]


def call_gemini_with_retry(func, key_manager: GeminiKeyManager, max_retries: int = None):
    """Gemini APIを呼び出し、429エラー時は別のキーでリトライ"""
    if max_retries is None:
        max_retries = len(key_manager.keys)

    last_error = None

    for attempt in range(max_retries):
        api_key, key_name = key_manager.get_working_key()
        print(f"  [API] {key_name} を使用 (試行 {attempt + 1}/{max_retries})")

        try:
            genai.configure(api_key=api_key)
            result = func()
            print(f"  [✓] {key_name}: 成功")
            return result

        except Exception as e:
            error_str = str(e)
            last_error = e

            if "429" in error_str or "quota" in error_str.lower():
                print(f"  [✗] {key_name}: クォータエラー (429)")
                key_manager.mark_failed(key_name)

                # 残りのキー数を表示
                remaining = len(key_manager.keys) - len(key_manager.failed_keys)
                print(f"      → 残り {remaining} キーで再試行")

                time.sleep(1)  # 少し待つ
                continue
            else:
                # 429以外のエラーは即座に raise
                print(f"  [✗] {key_name}: その他のエラー - {str(e)[:100]}")
                raise e

    # 全てのリトライが失敗
    print(f"  [!!] 全キーがクォータ切れ。処理を中断します。")
    raise last_error


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
    """Sheets APIサービスを取得"""
    creds = get_google_credentials()
    return build("sheets", "v4", credentials=creds)


def get_drive_service():
    """Drive APIサービスを取得"""
    creds = get_google_credentials()
    return build("drive", "v3", credentials=creds)


# 使用可能なチャンネル
AVAILABLE_CHANNELS = ["23", "24", "27"]  # 23=昭和の曲, 24=瀬戸内寂聴, 27=朝ドラ


def get_pending_task():
    """スプレッドシートからPENDINGタスクを取得"""
    service = get_sheets_service()

    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A:J"
    ).execute()

    values = result.get("values", [])
    headers = values[0] if values else []

    for i, row in enumerate(values[1:], start=2):
        # C列（ステータス）がPENDINGのものを探す
        status = row[2] if len(row) > 2 else ""
        if status == "PENDING":
            # D列からチャンネル番号を取得
            channel = row[3] if len(row) > 3 else ""
            if channel not in AVAILABLE_CHANNELS:
                channel = "27"  # デフォルト

            task = {
                "row": i,
                "theme": row[0] if len(row) > 0 else "",
                "mode": row[1] if len(row) > 1 else "AUTO",
                "status": status,
                "channel": channel,
            }
            return task

    return None


def update_spreadsheet(row: int, updates: dict):
    """スプレッドシートを更新"""
    service = get_sheets_service()

    # 列マッピング
    col_map = {
        "status": "C",
        "search_results": "E",
        "script": "F",
        "article_url": "G",
        "audio_url": "H",
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
                body={"values": [[str(value)[:50000]]]}  # 50000文字制限
            ).execute()


def search_asadora_info(theme: str, key_manager: GeminiKeyManager) -> str:
    """Geminiでウェブ検索して朝ドラ情報を収集（429エラー時リトライ対応）"""

    prompt = f"""あなたは朝ドラ（NHK連続テレビ小説）の専門家です。
以下のテーマについて、正確な情報を調査してください。

テーマ: {theme}

【調査項目】
1. 関連する朝ドラ作品（10作品以上）
2. 各作品の放送年
3. 主演俳優・女優
4. あらすじ・見どころ
5. 視聴率や話題になったエピソード
6. 出演者のエピソード

【出力形式】
調査結果を詳細にまとめてください。
各作品について、できるだけ多くの情報を含めてください。
"""

    def api_call():
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        return response.text

    return call_gemini_with_retry(api_call, key_manager)


def generate_dialogue_script(theme: str, search_results: str, key_manager: GeminiKeyManager) -> dict:
    """対談形式の台本を生成（429エラー時リトライ対応）"""

    # テストモードに応じて設定を調整
    opening_turns = "2〜3往復" if TEST_MODE else "4〜6往復"
    dialogue_turns = "4〜5往復" if TEST_MODE else "8〜10往復"
    ending_turns = "2〜3往復" if TEST_MODE else "6〜8往復"
    ranking_example = RANKING_COUNT  # 3 or 10

    prompt = f"""あなたはYouTubeのランキング紹介チャンネルの台本作家です。
以下の情報を基に、2人による掛け合い形式のランキング動画台本を作成してください。

テーマ: {theme}

【調査情報】
{search_results}

【キャラクター】
🎙️ カツミ（メインMC）
- 論理的で知的、落ち着いたトーン
- ランキングの紹介・説明を担当
- 「皆さんご存知の通り」「〇〇ですよね」など丁寧語

🎙️ ヒロシ（サブMC）
- 素直な感想・リアクションを担当
- 「へぇ〜」「なるほど」「それは知らなかった」など
- 視聴者目線で質問したり感想を言う

【掛け合いの流れ】
1. カツミ：「第〇位は『〇〇』です」（発表）
2. ヒロシ：「おお、これは名作ですよね」（リアクション）
3. カツミ：「この作品は〇〇で有名ですよね」（説明）
4. ヒロシ：「確かに、〇〇が印象的でした」（共感）
5. カツミ：「そうなんです、〇〇な点が評価されています」（補足）
6. 交互に続く...

【エンディング】
シンプルに締めくくる：
- カツミ：「以上、ランキングでした」
- ヒロシ：「どれも素晴らしい作品でしたね」
- カツミ：「ぜひチャンネル登録お願いします」
- ヒロシ：「また次回お会いしましょう」

【出力形式】必ず以下のJSON形式で出力してください：
{{
    "title": "動画タイトル（60文字以内）",
    "description": "動画説明文（500文字程度、改行含む）",
    "tags": ["タグ1", "タグ2", ...],
    "opening": [
        {{"speaker": "カツミ", "text": "皆さん、こんにちは。今日もランキングをお届けします。"}},
        {{"speaker": "ヒロシ", "text": "今日のテーマは何ですか？"}},
        {{"speaker": "カツミ", "text": "今日は〇〇ランキングです。"}},
        {{"speaker": "ヒロシ", "text": "楽しみですね、早速見ていきましょう。"}},
        ...（{opening_turns}、自然な掛け合いで）
    ],
    "rankings": [
        {{
            "rank": {ranking_example},
            "work_title": "作品名",
            "year": "放送年",
            "cast": "主演・出演者名",
            "dialogue": [
                {{"speaker": "カツミ", "text": "第{ranking_example}位は『〇〇』です。"}},
                {{"speaker": "ヒロシ", "text": "おお、これは有名な作品ですね。"}},
                {{"speaker": "カツミ", "text": "この作品は〇〇で話題になりましたよね。"}},
                {{"speaker": "ヒロシ", "text": "確かに、〇〇が印象的でした。"}},
                ...（{dialogue_turns}、カツミが紹介→ヒロシがリアクションの流れ）
            ],
            "image_keyword": "作品イメージの英語キーワード（例: japanese drama scene）"
        }},
        ... ({ranking_example}位から1位まで{ranking_example}個)
    ],
    "ending": [
        {{"speaker": "カツミ", "text": "以上、ランキングでした。いかがでしたか？"}},
        {{"speaker": "ヒロシ", "text": "どれも素晴らしい作品ばかりでしたね。"}},
        {{"speaker": "カツミ", "text": "皆さんのお気に入りはありましたか？"}},
        {{"speaker": "ヒロシ", "text": "コメントで教えてくださいね。"}},
        {{"speaker": "カツミ", "text": "チャンネル登録もよろしくお願いします。"}},
        {{"speaker": "ヒロシ", "text": "それでは、また次回お会いしましょう。"}}
    ]
}}

【重要】
- ランキングは必ず{ranking_example}位から1位まで{ranking_example}個作成
- 各セリフは20〜40文字程度（短めにテンポよく）
- カツミは紹介・説明、ヒロシはリアクション・共感
- 作品を褒める・良い点を紹介するポジティブな内容で
- 作品名、放送年、出演者は正確に
- 必ず有効なJSONを出力
"""

    def api_call():
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(prompt)
        return response.text

    text = call_gemini_with_retry(api_call, key_manager)

    # JSONを抽出
    json_match = re.search(r'\{[\s\S]*\}', text)
    if not json_match:
        raise ValueError("台本のJSON抽出に失敗しました")

    script = json.loads(json_match.group())

    # rankingsを10位→1位にソート
    script["rankings"] = sorted(script["rankings"], key=lambda x: x["rank"], reverse=True)

    return script


def generate_notebooklm_article(theme: str, script: dict) -> str:
    """NotebookLM用の記事を生成"""
    article = f"""# {script['title']}

## はじめに

{script['description']}

---

## ランキング発表

"""

    for item in script["rankings"]:
        article += f"""
### 第{item['rank']}位: {item['work_title']}（{item['year']}年）

**主演:** {item['cast']}

"""
        for line in item["dialogue"]:
            article += f"**{line['speaker']}:** {line['text']}\n\n"

        article += "---\n"

    article += """
## まとめ

"""
    for line in script["ending"]:
        article += f"**{line['speaker']}:** {line['text']}\n\n"

    return article


def upload_to_drive(content: str, filename: str, folder_id: str = None) -> str:
    """Google Driveにファイルをアップロード"""
    service = get_drive_service()

    file_metadata = {"name": filename}
    if folder_id:
        file_metadata["parents"] = [folder_id]

    media = MediaIoBaseUpload(
        BytesIO(content.encode('utf-8')),
        mimetype='text/plain',
        resumable=True
    )

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id, webViewLink'
    ).execute()

    # 共有設定
    service.permissions().create(
        fileId=file['id'],
        body={'type': 'anyone', 'role': 'reader'}
    ).execute()

    return file.get('webViewLink', '')


def generate_elevenlabs_tts(text: str, voice_id: str, output_path: str) -> bool:
    """ElevenLabs TTSで音声生成"""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("    [ElevenLabs] APIキーが設定されていません → gTTSにフォールバック")
        return False

    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json"
        }
        data = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }

        response = requests.post(url, headers=headers, json=data, timeout=60)
        response.raise_for_status()

        with open(output_path, 'wb') as f:
            f.write(response.content)

        # 成功ログ（ファイルサイズも表示）
        file_size = os.path.getsize(output_path)
        print(f"    [ElevenLabs] 生成成功 ({file_size} bytes)")
        return True

    except Exception as e:
        print(f"    ElevenLabs TTSエラー: {e}")
        return False


def generate_gtts(text: str, output_path: str) -> bool:
    """gTTSで音声生成（フォールバック用）"""
    try:
        tts = gTTS(text=text, lang='ja')
        tts.save(output_path)
        return True
    except Exception as e:
        print(f"    gTTS生成エラー: {e}")
        return False


def generate_tts_for_speaker(text: str, speaker: str, output_path: str) -> bool:
    """話者に応じたTTSで音声生成（ElevenLabs優先、gTTSフォールバック）"""
    # キャラクターの音声IDを取得
    voice_id = CHARACTERS.get(speaker, {}).get("voice_id")

    # デバッグ: 話者とボイスIDを表示
    voice_name = get_voice_name(voice_id) if voice_id else "なし"
    print(f"    [{speaker}] voice_id={voice_name}")

    if voice_id:
        # ElevenLabsで生成を試みる
        if generate_elevenlabs_tts(text, voice_id, output_path):
            return True

    # フォールバック: gTTS
    print(f"    [{speaker}] → gTTSにフォールバック")
    return generate_gtts(text, output_path)


def generate_dialogue_audio_parallel(dialogue: list, temp_dir: Path, key_manager: GeminiKeyManager = None) -> tuple:
    """対話の音声を並列生成（ElevenLabs版）"""
    audio_files = []
    segments = []

    def generate_single(index, line):
        speaker = line["speaker"]
        text = line["text"]

        output_path = str(temp_dir / f"line_{index:04d}.mp3")
        success = generate_tts_for_speaker(text, speaker, output_path)

        return index, output_path, success, speaker, text

    # 並列処理
    with ThreadPoolExecutor(max_workers=min(5, len(dialogue))) as executor:
        futures = [executor.submit(generate_single, i, line) for i, line in enumerate(dialogue)]
        results = [f.result() for f in as_completed(futures)]

    # インデックス順にソート
    results.sort(key=lambda x: x[0])

    # 音声ファイルを結合
    total_duration = 0
    valid_files = []

    for index, path, success, speaker, text in results:
        if success and os.path.exists(path):
            try:
                audio = AudioFileClip(path)
                duration = audio.duration
                audio.close()

                segments.append({
                    "speaker": speaker,
                    "text": text,
                    "start": total_duration,
                    "end": total_duration + duration,
                    "color": CHARACTERS[speaker]["color"]
                })

                valid_files.append(path)
                total_duration += duration
            except Exception as e:
                print(f"音声ファイル読み込みエラー: {e}")

    # 音声を結合
    combined_path = str(temp_dir / "combined.mp3")
    if valid_files:
        clips = [AudioFileClip(f) for f in valid_files]
        combined = concatenate_audioclips(clips)
        combined.write_audiofile(combined_path)
        combined.close()
        for clip in clips:
            clip.close()

    return combined_path, segments, total_duration


def transcribe_with_elevenlabs(audio_path: str) -> list:
    """ElevenLabs STTで音声を文字起こし"""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return []

    try:
        url = "https://api.elevenlabs.io/v1/speech-to-text"
        headers = {"xi-api-key": api_key}

        with open(audio_path, 'rb') as f:
            files = {"file": f}
            data = {"model_id": "scribe_v1", "language_code": "ja"}

            response = requests.post(url, headers=headers, files=files, data=data, timeout=300)
            response.raise_for_status()

        result = response.json()
        return result.get("words", [])

    except Exception as e:
        print(f"STTエラー: {e}")
        return []


def match_script_with_stt(segments: list, stt_words: list) -> list:
    """台本とSTT結果をマッチングして正確な字幕を生成"""
    if not stt_words:
        return segments

    # STTのワードを時間順にソート
    stt_words.sort(key=lambda x: x.get("start", 0))

    matched_segments = []

    for seg in segments:
        # セグメントの時間範囲内のSTTワードを探す
        seg_start = seg["start"]
        seg_end = seg["end"]

        # 時間範囲を少し広げてマッチング
        margin = 0.5
        matching_words = [
            w for w in stt_words
            if w.get("start", 0) >= seg_start - margin and w.get("end", 0) <= seg_end + margin
        ]

        # STTテキストと台本テキストを比較
        stt_text = "".join([w.get("text", "") for w in matching_words])
        original_text = seg["text"]

        # 台本テキストを優先（STTは時間調整のみに使用）
        matched_segments.append({
            **seg,
            "text": original_text,  # 台本の正確なテキストを使用
            "stt_text": stt_text    # 参考用
        })

    return matched_segments


def fetch_google_image(query: str, output_path: str) -> bool:
    """Google画像検索から画像をダウンロード"""
    try:
        # 一時ディレクトリを作成
        temp_dir = Path(output_path).parent / "google_images"
        temp_dir.mkdir(exist_ok=True)

        # 既存ファイルを削除
        for f in temp_dir.glob("*"):
            f.unlink()

        print(f"    [icrawler] 検索開始: {query}")

        # Google画像検索でダウンロード
        crawler = GoogleImageCrawler(
            storage={'root_dir': str(temp_dir)},
            log_level=logging.WARNING  # WARNINGレベルでログ表示
        )
        crawler.crawl(keyword=query, max_num=3)  # 3枚まで試行

        # ダウンロードされた画像を取得
        images = list(temp_dir.glob("*"))
        print(f"    [icrawler] ダウンロード数: {len(images)}")

        if images:
            # 画像をリサイズして保存
            img = Image.open(images[0])
            img = img.convert('RGB')
            img.save(output_path)
            resize_image(output_path, VIDEO_WIDTH, VIDEO_HEIGHT)

            # 一時ファイルを削除
            for f in temp_dir.glob("*"):
                f.unlink()

            print(f"    [icrawler] 画像取得成功!")
            return True
        else:
            print(f"    [icrawler] 画像が見つかりませんでした")

    except Exception as e:
        print(f"    [icrawler] エラー: {e}")
        import traceback
        traceback.print_exc()

    return False


def fetch_ranking_image(work_title: str, cast: str, output_path: str) -> bool:
    """ランキング項目用の画像を取得（複数クエリで試行）"""
    # 検索クエリの優先順位（芸能人名・作品名を直接検索）
    queries = []

    # 出演者名を優先（芸能人の顔写真）
    if cast:
        queries.append(cast)                        # 出演者名のみ（例：美空ひばり）
        queries.append(f"{cast} {work_title}")      # 出演者 + 作品名

    # 作品名での検索
    if work_title:
        queries.append(f"{work_title} NHK")         # 作品名 + NHK（朝ドラ用）
        queries.append(work_title)                  # 作品名のみ

    for query in queries:
        if not query or not query.strip():
            continue
        print(f"    検索中: {query}")
        if fetch_google_image(query, output_path):
            return True
        time.sleep(0.3)  # レート制限対策

    return False


def generate_gradient_background(output_path: str, rank: int = 0,
                                  video_title: str = None, work_title: str = None):
    """昭和風グラデーション背景を生成（テキスト付き）"""
    img = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT))
    draw = ImageDraw.Draw(img)

    color_schemes = [
        ((70, 35, 10), (210, 180, 140)),     # ブラウン
        ((30, 50, 50), (176, 196, 222)),      # グレー
        ((80, 20, 20), (255, 218, 185)),      # マルーン
        ((20, 60, 20), (144, 238, 144)),      # グリーン
        ((50, 20, 80), (230, 230, 250)),      # インディゴ
        ((90, 20, 20), (255, 182, 193)),      # レッド
        ((20, 20, 90), (173, 216, 230)),      # ブルー
        ((50, 60, 30), (238, 232, 170)),      # オリーブ
        ((80, 20, 80), (221, 160, 221)),      # パープル
        ((20, 80, 80), (224, 255, 255)),      # ティール
        ((120, 90, 20), (255, 250, 205)),     # ゴールド（1位用）
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

    # テキストを描画（フォールバック用）
    if video_title or rank or work_title:
        font_path = get_font_path()
        try:
            font_large = ImageFont.truetype(font_path, 80) if font_path else ImageFont.load_default()
            font_xlarge = ImageFont.truetype(font_path, 120) if font_path else ImageFont.load_default()
            font_medium = ImageFont.truetype(font_path, 60) if font_path else ImageFont.load_default()
        except:
            font_large = ImageFont.load_default()
            font_xlarge = ImageFont.load_default()
            font_medium = ImageFont.load_default()

        # 上部: 動画タイトル
        if video_title:
            bbox = draw.textbbox((0, 0), video_title, font=font_medium)
            text_width = bbox[2] - bbox[0]
            x = (VIDEO_WIDTH - text_width) // 2
            draw.text((x + 3, 103), video_title, font=font_medium, fill=(0, 0, 0))
            draw.text((x, 100), video_title, font=font_medium, fill=(255, 255, 255))

        # 中央: 順位
        if rank and rank > 0:
            rank_text = f"第{rank}位"
            bbox = draw.textbbox((0, 0), rank_text, font=font_xlarge)
            text_width = bbox[2] - bbox[0]
            x = (VIDEO_WIDTH - text_width) // 2
            y = VIDEO_HEIGHT // 2 - 60
            # ゴールド色（1〜3位）またはシルバー色
            rank_color = (255, 215, 0) if rank <= 3 else (255, 255, 255)
            draw.text((x + 4, y + 4), rank_text, font=font_xlarge, fill=(0, 0, 0))
            draw.text((x, y), rank_text, font=font_xlarge, fill=rank_color)

        # 下部: 作品名
        if work_title:
            work_display = f"『{work_title}』"
            bbox = draw.textbbox((0, 0), work_display, font=font_large)
            text_width = bbox[2] - bbox[0]
            x = (VIDEO_WIDTH - text_width) // 2
            y = VIDEO_HEIGHT - 200
            draw.text((x + 3, y + 3), work_display, font=font_large, fill=(0, 0, 0))
            draw.text((x, y), work_display, font=font_large, fill=(255, 255, 255))

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


# ===== FFmpegベース高速動画生成 =====

import subprocess


def combine_audio_ffmpeg(audio_files: list, output_path: str) -> bool:
    """FFmpegで音声ファイルを結合"""
    if not audio_files:
        return False

    if len(audio_files) == 1:
        # 1ファイルの場合はコピー
        import shutil
        shutil.copy(audio_files[0], output_path)
        return True

    # concat用のファイルリストを作成
    list_path = output_path + ".txt"
    with open(list_path, 'w') as f:
        for audio_file in audio_files:
            f.write(f"file '{audio_file}'\n")

    cmd = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
        '-i', list_path,
        '-c', 'copy',
        output_path
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        os.remove(list_path)
        return True
    except subprocess.CalledProcessError as e:
        print(f"音声結合エラー: {e.stderr.decode()}")
        return False


def get_audio_duration_ffprobe(audio_path: str) -> float:
    """FFprobeで音声の長さを取得"""
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        audio_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except:
        return 0.0


def generate_ass_subtitles(segments: list, output_path: str, video_width: int, video_height: int):
    """ASS形式の字幕ファイルを生成（スタイル付き）"""

    # ASSヘッダー
    header = f"""[Script Info]
Title: 朝ドラランキング
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Yumiko,Noto Sans CJK JP,44,&H00B469FF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,50,50,120,1
Style: Kenji,Noto Sans CJK JP,44,&H00E16941,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,50,50,120,1
Style: Default,Noto Sans CJK JP,44,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,50,50,120,1
Style: Rank,Noto Sans CJK JP,80,&H0000D7FF,&H000000FF,&H00000080,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,7,50,50,50,1
Style: Info,Noto Sans CJK JP,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,7,100,50,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def format_ass_time(seconds: float) -> str:
        """秒をASS形式に変換"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centis = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"

    lines = [header]

    for seg in segments:
        start = format_ass_time(seg['start'])
        end = format_ass_time(seg['end'])
        speaker = seg.get('speaker', '')
        text = seg.get('text', '')

        # スタイルを選択
        if speaker == 'ユミコ':
            style = 'Yumiko'
        elif speaker == 'ケンジ':
            style = 'Kenji'
        else:
            style = 'Default'

        # 話者名を付加
        display_text = f"【{speaker}】{text}" if speaker else text

        lines.append(f"Dialogue: 0,{start},{end},{style},,0,0,0,,{display_text}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def create_slideshow_input(sections: list, output_path: str):
    """FFmpeg concat用の入力ファイルを作成"""
    with open(output_path, 'w') as f:
        for section in sections:
            image_path = section['image']
            duration = section['duration']
            f.write(f"file '{image_path}'\n")
            f.write(f"duration {duration}\n")
        # 最後の画像を追加（FFmpegの仕様で必要）
        if sections:
            f.write(f"file '{sections[-1]['image']}'\n")


def add_overlay_to_image(image_path: str, output_path: str, rank: int = None,
                         work_title: str = None, year: str = None, cast: str = None):
    """背景画像にオーバーレイテキストを焼き込む（Pillowで高速処理）"""
    from PIL import ImageFont

    img = Image.open(image_path).convert('RGB')
    img = img.resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.LANCZOS)
    draw = ImageDraw.Draw(img)

    # フォントパスを取得
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    ]

    font_path = None
    for fp in font_paths:
        if os.path.exists(fp):
            font_path = fp
            break

    if rank:
        # 順位バッジを描画
        try:
            badge_font = ImageFont.truetype(font_path, 80) if font_path else ImageFont.load_default()
        except:
            badge_font = ImageFont.load_default()

        badge_text = f"第{rank}位"
        badge_color = (255, 215, 0) if rank <= 3 else (255, 255, 255)  # gold or white

        # 影を描画
        draw.text((52, 52), badge_text, font=badge_font, fill=(0, 0, 0))
        draw.text((50, 50), badge_text, font=badge_font, fill=badge_color)

        # 作品情報を描画
        if work_title:
            try:
                info_font = ImageFont.truetype(font_path, 48) if font_path else ImageFont.load_default()
            except:
                info_font = ImageFont.load_default()

            info_text = f"『{work_title}』（{year}年）"
            draw.text((102, 152), info_text, font=info_font, fill=(0, 0, 0))
            draw.text((100, 150), info_text, font=info_font, fill=(255, 255, 255))

            if cast:
                cast_text = f"主演: {cast}"
                draw.text((102, 212), cast_text, font=info_font, fill=(0, 0, 0))
                draw.text((100, 210), cast_text, font=info_font, fill=(255, 255, 255))

    img.save(output_path, quality=95)


def download_bgm_from_drive(temp_dir: Path) -> str:
    """Google DriveからBGMをダウンロード"""
    bgm_folder_id = os.environ.get("BGM_FOLDER_ID")
    if not bgm_folder_id:
        return None

    try:
        from googleapiclient.http import MediaIoBaseDownload
        service = get_drive_service()

        # フォルダ内のファイル一覧を取得
        results = service.files().list(
            q=f"'{bgm_folder_id}' in parents and mimeType contains 'audio/'",
            fields="files(id, name)"
        ).execute()

        files = results.get('files', [])
        if not files:
            return None

        # ランダムに1曲選択
        selected = random.choice(files)
        print(f"  BGM選択: {selected['name']}")

        # ダウンロード
        bgm_path = str(temp_dir / "bgm.mp3")
        request = service.files().get_media(fileId=selected['id'])

        with open(bgm_path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()

        return bgm_path

    except Exception as e:
        print(f"  BGMダウンロードエラー: {e}")
        return None


def create_video_ffmpeg(sections: list, all_segments: list, temp_dir: Path) -> tuple:
    """FFmpegで動画を生成（2段階処理：動画作成→字幕オーバーレイ）"""
    print("\n" + "=" * 50)
    print("[FFmpeg] 動画生成開始（2段階処理）")
    print("=" * 50)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    start_time = time.time()

    # 1. 音声ファイルを結合
    print("\n[1/6] 音声ファイルを結合中...")
    audio_files = [s['audio'] for s in sections if s.get('audio') and os.path.exists(s['audio'])]
    combined_audio = str(temp_dir / "combined_audio.mp3")

    if not combine_audio_ffmpeg(audio_files, combined_audio):
        raise ValueError("音声結合に失敗しました")

    total_duration = get_audio_duration_ffprobe(combined_audio)
    print(f"  総再生時間: {total_duration:.1f}秒 ({total_duration/60:.1f}分)")

    # 2. BGMをダウンロード（オプション）
    print("\n[2/6] BGMを取得中...")
    bgm_path = download_bgm_from_drive(temp_dir)
    if bgm_path:
        print(f"  BGM: {bgm_path}")
    else:
        print("  BGMなし（音声のみ）")

    # 3. 背景画像にオーバーレイを焼き込み
    print("\n[3/6] 背景画像を処理中...")
    processed_sections = []

    for i, section in enumerate(sections):
        if not section.get('audio') or not os.path.exists(section['audio']):
            continue

        duration = get_audio_duration_ffprobe(section['audio'])
        if duration <= 0:
            continue

        # 画像を処理（テキストを焼き込み）
        processed_image = str(temp_dir / f"slide_{i:03d}.png")
        add_overlay_to_image(
            section['image'],
            processed_image,
            rank=section.get('rank'),
            work_title=section.get('work_title'),
            year=section.get('year'),
            cast=section.get('cast')
        )

        processed_sections.append({
            'image': processed_image,
            'duration': duration
        })
        print(f"  [{i+1}/{len(sections)}] {duration:.1f}秒")

    # 4. SRT字幕ファイルを生成
    print("\n[4/6] SRT字幕ファイルを生成中...")
    srt_path = str(temp_dir / f"asadora_ranking_{timestamp}.srt")
    generate_srt(all_segments, srt_path)
    print(f"  字幕数: {len(all_segments)}件")

    # 5. 画像シーケンスファイルを作成し、動画を生成（字幕なし）
    print("\n[5/6] 画像+音声で動画を生成中...")
    concat_file = str(temp_dir / "images.txt")
    create_slideshow_input(processed_sections, concat_file)

    # 中間ファイル（字幕なし動画）
    temp_video = str(temp_dir / f"temp_video_{timestamp}.mp4")
    output_path = str(temp_dir / f"asadora_ranking_{timestamp}.mp4")

    # Step 1: 画像+音声で動画作成（字幕なし）
    if bgm_path and os.path.exists(bgm_path):
        # BGMあり: 音声ミキシング
        filter_complex = (
            f"[1:a]volume=1.0[voice];"
            f"[2:a]volume=0.12,aloop=loop=-1:size=2e+09[bgm_loop];"
            f"[voice][bgm_loop]amix=inputs=2:duration=first:dropout_transition=2[a]"
        )

        cmd_step1 = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', concat_file,
            '-i', combined_audio,
            '-i', bgm_path,
            '-filter_complex', filter_complex,
            '-map', '0:v', '-map', '[a]',
            '-vf', f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}",
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            temp_video
        ]
    else:
        # BGMなし
        cmd_step1 = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', concat_file,
            '-i', combined_audio,
            '-vf', f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}",
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-shortest',
            '-movflags', '+faststart',
            temp_video
        ]

    print(f"  中間ファイル: {temp_video}")

    try:
        subprocess.run(cmd_step1, capture_output=True, text=True, check=True)
        print("  ✓ 画像+音声の動画作成完了")
    except subprocess.CalledProcessError as e:
        print(f"FFmpegエラー（Step1）: {e.stderr[:500] if e.stderr else 'unknown'}")
        raise

    # 6. 字幕を動画全体にオーバーレイ
    print("\n[6/6] 字幕を動画にオーバーレイ中...")

    # 日本語フォント設定
    # 字幕スタイル: フォントサイズ72、薄いグレーの影
    font_style = "FontName=Noto Sans CJK JP,FontSize=72,PrimaryColour=&H00FFFFFF,OutlineColour=&H00333333,BorderStyle=1,Outline=3,Shadow=0,MarginV=60"

    cmd_step2 = [
        'ffmpeg', '-y',
        '-i', temp_video,
        '-vf', f"subtitles={srt_path}:force_style='{font_style}'",
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
        '-c:a', 'copy',
        '-movflags', '+faststart',
        output_path
    ]

    try:
        subprocess.run(cmd_step2, capture_output=True, text=True, check=True)
        elapsed = time.time() - start_time
        print(f"\n✓ 動画生成完了!")
        print(f"  処理時間: {elapsed:.1f}秒")
        print(f"  動画長: {total_duration:.1f}秒")
        print(f"  速度比: {total_duration/elapsed:.1f}x リアルタイム")
        print(f"  出力: {output_path}")

        # 中間ファイルを削除
        if os.path.exists(temp_video):
            os.remove(temp_video)

    except subprocess.CalledProcessError as e:
        print(f"\nFFmpegエラー（Step2 字幕）: {e.stderr[:500] if e.stderr else 'unknown'}")

        # フォールバック: 字幕なしで中間ファイルをそのまま使用
        print("\n[フォールバック] 字幕なしで出力...")
        import shutil
        shutil.move(temp_video, output_path)
        print("  字幕なしで完了")

    return output_path, srt_path


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


def create_video(script: dict, temp_dir: Path, key_manager: GeminiKeyManager) -> tuple:
    """動画を作成（FFmpegベース高速版）"""
    sections = []  # FFmpeg用のセクション情報
    all_segments = []
    current_time = 0.0
    video_title = script.get("title", "")  # 動画タイトル（フォールバック用）

    total_steps = RANKING_COUNT + 2  # オープニング + ランキング数 + エンディング
    print(f"動画作成開始（FFmpeg高速モード）... [全{total_steps}セクション]")

    # オープニング
    print(f"[1/{total_steps}] オープニング音声生成中...")
    opening_dir = temp_dir / "opening"
    opening_dir.mkdir(exist_ok=True)

    opening_audio, opening_segments, opening_duration = generate_dialogue_audio_parallel(
        script["opening"], opening_dir, key_manager
    )

    opening_bg = str(temp_dir / "opening_bg.png")
    generate_gradient_background(opening_bg, rank=0, video_title=video_title)

    if opening_duration > 0:
        sections.append({
            'audio': opening_audio,
            'image': opening_bg,
            'rank': None,
            'work_title': None,
            'year': None,
            'cast': None
        })

        for seg in opening_segments:
            all_segments.append({**seg, "start": current_time + seg["start"], "end": current_time + seg["end"]})
        current_time += opening_duration

    # ランキング
    for idx, item in enumerate(script["rankings"]):
        rank = item["rank"]
        step = idx + 2  # オープニングが1なので2から
        print(f"[{step}/{total_steps}] 第{rank}位 音声生成中...")

        rank_dir = temp_dir / f"rank_{rank}"
        rank_dir.mkdir(exist_ok=True)

        audio_path, segments, duration = generate_dialogue_audio_parallel(
            item["dialogue"], rank_dir, key_manager
        )

        # 背景画像を取得（Google画像検索）
        image_path = str(temp_dir / f"rank_{rank}.jpg")
        work_title = item.get("work_title", "")
        cast = item.get("cast", "")
        print(f"    画像検索: {work_title} / {cast}")

        if not fetch_ranking_image(work_title, cast, image_path):
            # フォールバック: グラデーション背景（タイトル・順位・作品名付き）
            print(f"    → フォールバック: グラデーション背景")
            image_path = str(temp_dir / f"rank_{rank}.png")
            generate_gradient_background(
                image_path,
                rank=rank,
                video_title=video_title,
                work_title=work_title
            )

        if duration > 0:
            sections.append({
                'audio': audio_path,
                'image': image_path,
                'rank': rank,
                'work_title': item.get("work_title"),
                'year': item.get("year"),
                'cast': item.get("cast")
            })

            for seg in segments:
                all_segments.append({**seg, "start": current_time + seg["start"], "end": current_time + seg["end"]})
            current_time += duration

    # エンディング
    print(f"[{total_steps}/{total_steps}] エンディング音声生成中...")
    ending_dir = temp_dir / "ending"
    ending_dir.mkdir(exist_ok=True)

    ending_audio, ending_segments, ending_duration = generate_dialogue_audio_parallel(
        script["ending"], ending_dir, key_manager
    )

    ending_bg = str(temp_dir / "ending_bg.png")
    generate_gradient_background(ending_bg, rank=11, video_title=video_title)

    if ending_duration > 0:
        sections.append({
            'audio': ending_audio,
            'image': ending_bg,
            'rank': None,
            'work_title': None,
            'year': None,
            'cast': None
        })

        for seg in ending_segments:
            all_segments.append({**seg, "start": current_time + seg["start"], "end": current_time + seg["end"]})

    # FFmpegで動画生成
    if not sections:
        raise ValueError("有効なセクションがありません")

    return create_video_ffmpeg(sections, all_segments, temp_dir)


def upload_to_youtube(video_path: str, title: str, description: str, tags: list, channel_token: str, mode: str = "AUTO") -> str:
    """YouTubeに動画をアップロード

    Args:
        mode: "TEST" → 限定公開(unlisted), "AUTO" → 公開(public)
    """
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")

    # TOKEN環境変数名を構築（YOUTUBE_REFRESH_TOKEN_X 形式）
    token_env_name = f"YOUTUBE_REFRESH_TOKEN_{channel_token}"
    refresh_token = os.environ.get(token_env_name)

    # デバッグ情報
    print(f"[DEBUG] TOKEN環境変数名: {token_env_name}")
    print(f"[DEBUG] TOKEN取得結果: {'あり' if refresh_token else 'なし'}")
    print(f"[DEBUG] CLIENT_ID: {'あり' if client_id else 'なし'}")
    print(f"[DEBUG] CLIENT_SECRET: {'あり' if client_secret else 'なし'}")

    if not all([client_id, client_secret, refresh_token]):
        # 利用可能な環境変数を表示
        available_tokens = [k for k in os.environ.keys() if k.startswith("YOUTUBE_REFRESH_TOKEN")]
        print(f"[DEBUG] 利用可能なTOKEN環境変数: {available_tokens}")
        raise ValueError(f"YouTube認証情報が不足しています ({token_env_name})")

    # アクセストークン取得
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

    # モードに応じて公開設定を切り替え
    # TEST → 限定公開(unlisted), AUTO → 公開(public)
    privacy_status = "unlisted" if mode == "TEST" else "public"
    print(f"  公開設定: {privacy_status} (mode={mode})")

    body = {
        "snippet": {
            "title": title,
            "description": f"{description}\n\n{hashtags}",
            "tags": tags,
            "categoryId": "24"
        },
        "status": {
            "privacyStatus": privacy_status,
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
    payload = {"text": f"{emoji} *朝ドラランキング*\n{message}"}

    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        print(f"Slack通知エラー: {e}")


def process_auto_mode(task: dict, key_manager: GeminiKeyManager):
    """モードA: 完全自動処理"""
    start_time = time.time()
    row = task["row"]
    theme = task["theme"]
    channel = task["channel"]
    mode = task.get("mode", "AUTO")  # TEST → 限定公開, AUTO → 公開

    # チャンネルに応じたボイス設定
    setup_channel_voices(channel)

    try:
        update_spreadsheet(row, {"status": "PROCESSING"})

        # 1. ウェブ検索
        print("[1/6] ウェブ検索中...")
        search_results = search_asadora_info(theme, key_manager)
        update_spreadsheet(row, {"search_results": search_results[:10000]})

        # 2. 台本生成
        print("[2/6] 台本生成中...")
        script = generate_dialogue_script(theme, search_results, key_manager)
        update_spreadsheet(row, {"script": json.dumps(script, ensure_ascii=False)[:50000]})

        # 3-5. 動画作成
        print("[3/6] 動画作成中...")
        temp_dir = Path(tempfile.mkdtemp())
        video_path, srt_path = create_video(script, temp_dir, key_manager)

        # 6. YouTubeアップロード
        print("[6/6] YouTubeアップロード中...")
        youtube_url = upload_to_youtube(
            video_path,
            script["title"],
            script["description"],
            script.get("tags", ["朝ドラ", "NHK", "ランキング"]),
            channel,
            mode  # TEST → 限定公開, AUTO → 公開
        )

        elapsed = int(time.time() - start_time)
        update_spreadsheet(row, {
            "status": "DONE",
            "youtube_url": youtube_url,
            "processing_time": f"{elapsed}秒"
        })

        send_slack_notification(
            f"*完全自動モード完了*\n"
            f"テーマ: {theme}\n"
            f"タイトル: {script['title']}\n"
            f"URL: {youtube_url}\n"
            f"処理時間: {elapsed}秒"
        )

        print(f"\n完了: {youtube_url}")

    except Exception as e:
        update_spreadsheet(row, {"status": f"ERROR: {str(e)[:100]}"})
        send_slack_notification(f"エラー発生\nテーマ: {theme}\n{str(e)}", success=False)
        raise


def process_notebook_mode(task: dict, key_manager: GeminiKeyManager):
    """モードB: NotebookLM前半処理"""
    row = task["row"]
    theme = task["theme"]

    try:
        update_spreadsheet(row, {"status": "PROCESSING"})

        # 1. ウェブ検索
        print("[1/4] ウェブ検索中...")
        search_results = search_asadora_info(theme, key_manager)
        update_spreadsheet(row, {"search_results": search_results[:10000]})

        # 2. 台本生成
        print("[2/4] 台本生成中...")
        script = generate_dialogue_script(theme, search_results, key_manager)
        update_spreadsheet(row, {"script": json.dumps(script, ensure_ascii=False)[:50000]})

        # 3. NotebookLM用記事生成
        print("[3/4] NotebookLM用記事生成中...")
        article = generate_notebooklm_article(theme, script)

        # 4. Google Driveにアップロード
        print("[4/4] Google Driveにアップロード中...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"asadora_{timestamp}.txt"
        article_url = upload_to_drive(article, filename)

        update_spreadsheet(row, {
            "status": "WAITING_AUDIO",
            "article_url": article_url
        })

        send_slack_notification(
            f"*NotebookLM用記事が準備できました*\n"
            f"テーマ: {theme}\n"
            f"記事URL: {article_url}\n\n"
            f"1. NotebookLMで記事をアップロード\n"
            f"2. 音声概要を生成\n"
            f"3. 音声をGoogle Driveにアップロード\n"
            f"4. スプレッドシートのステータスを「AUDIO_READY」に更新"
        )

        print(f"\n記事URL: {article_url}")
        print("NotebookLMで音声を生成してください")

    except Exception as e:
        update_spreadsheet(row, {"status": f"ERROR: {str(e)[:100]}"})
        send_slack_notification(f"エラー発生\nテーマ: {theme}\n{str(e)}", success=False)
        raise


def main():
    """メイン処理"""
    print("=" * 60)
    print("朝ドラランキング動画自動生成システム")
    print("=" * 60)

    # テストモード表示
    if TEST_MODE:
        print("🧪 テストモード（TOP3・短縮版）")
        print(f"   ランキング数: {RANKING_COUNT}位まで")
    else:
        print("🎬 本番モード（TOP10・フル版）")
        print(f"   ランキング数: {RANKING_COUNT}位まで")
    print()

    try:
        key_manager = GeminiKeyManager()
        print(f"Gemini APIキー: {len(key_manager.keys)}個")

        task = get_pending_task()
        if not task:
            print("処理対象のタスクがありません")
            return

        print(f"\nタスク発見:")
        print(f"  テーマ: {task['theme']}")
        print(f"  モード: {task['mode']}")
        print(f"  チャンネル: YOUTUBE_REFRESH_TOKEN_{task['channel']}")

        if task["mode"] == "NOTEBOOK":
            process_notebook_mode(task, key_manager)
        else:
            process_auto_mode(task, key_manager)

        print("\n" + "=" * 60)
        print("処理完了")
        print("=" * 60)

    except Exception as e:
        print(f"\nエラー: {e}")
        send_slack_notification(f"システムエラー: {str(e)}", success=False)
        sys.exit(1)


if __name__ == "__main__":
    main()
