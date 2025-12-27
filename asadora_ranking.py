#!/usr/bin/env python3
"""
シニアの口コミランキング動画自動生成システム
- モードA: 完全自動（Fish Audio TTS）
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
import subprocess
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
import logging

# Unsplash API設定
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")
UNSPLASH_API_URL = "https://api.unsplash.com/search/photos"


# ===== 定数 =====
SPREADSHEET_ID = "15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo"
SHEET_NAME = "YouTube自動投稿"
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
FPS = 24

# ===== テストモード設定 =====
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"
RANKING_COUNT = 3 if TEST_MODE else 10  # テスト時はTOP3、本番はTOP10

# ===== Fish Audio TTS設定 =====
# Fish Audio API
FISH_AUDIO_API_KEY = os.environ.get("FISH_AUDIO_API_KEY", "")
FISH_AUDIO_API_URL = "https://api.fish.audio/v1/tts"

# キャラクター設定を共通ファイルからインポート
from character_settings import (
    CHARACTERS,
    CHANNEL_VOICE_CONFIG,
    FISH_VOICE_KATSUMI,
    FISH_VOICE_HIROSHI,
    FISH_VOICE_NAMES,
    get_voice_name,
    setup_channel_voices,
    detect_emotion_tag,
    CHARACTER_PROMPT,
    apply_reading_dict,
)


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


# ===== シニア口コミ専用 - TOKEN_27固定 =====
# このスクリプトはTOKEN_27（シニア口コミランキング）専用
AVAILABLE_CHANNELS = ["27"]
# 注: TOKEN_23は年金ニュース用（nenkin_news.py）、TOKEN_24はテスト用


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
            # 各列の値を取得
            theme = row[0] if len(row) > 0 else ""
            mode = row[1] if len(row) > 1 else "AUTO"
            channel = row[3] if len(row) > 3 else ""

            # デバッグ: スプレッドシートから読み取った値を表示
            print(f"\n[スプレッドシート読み取り] 行{i}")
            print(f"  A列(テーマ): {theme[:30]}...")
            print(f"  B列(モード): '{mode}'")
            print(f"  C列(ステータス): '{status}'")
            print(f"  D列(チャンネル): '{channel}'")

            # チャンネル番号の検証
            if channel not in AVAILABLE_CHANNELS:
                print(f"  → チャンネル '{channel}' は無効。デフォルト '27' を使用")
                channel = "27"

            task = {
                "row": i,
                "theme": theme,
                "mode": mode,
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
    """Geminiでウェブ検索してテーマに関する情報を収集（429エラー時リトライ対応）"""

    prompt = f"""あなたはシニア世代の生活・お金・健康・人間関係に詳しい専門家です。
以下のテーマについて、実際のシニア世代の口コミや体験談を基に調査してください。

テーマ: {theme}

【調査項目】
1. このテーマに関連する具体的な事例・体験談（10件以上）
2. 各事例の背景・原因
3. 当事者の年齢層・状況
4. 具体的なエピソード・詳細
5. 教訓や学びになるポイント
6. 専門家のアドバイス（あれば）

【出力形式】
調査結果を詳細にまとめてください。
各事例について、できるだけリアルで具体的な情報を含めてください。
シニア世代が共感できる内容を重視してください。
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

    prompt = f"""あなたはYouTubeのシニア向けランキング紹介チャンネルの台本作家です。
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
2. ヒロシ：「おお、これはよく聞きますね」（リアクション）
3. カツミ：「この事例では〇〇が原因でした」（説明）
4. ヒロシ：「確かに、気をつけないといけませんね」（共感）
5. カツミ：「そうなんです、〇〇な点が重要です」（補足）
6. 交互に続く...

【エンディング】
シンプルに締めくくる：
- カツミ：「以上、ランキングでした」
- ヒロシ：「どれも身につまされる話でしたね」
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
        {{"speaker": "ヒロシ", "text": "気になりますね、早速見ていきましょう。"}},
        ...（{opening_turns}、自然な掛け合いで）
    ],
    "rankings": [
        {{
            "rank": {ranking_example},
            "work_title": "事例・原因のタイトル（例：貯金を取り崩しすぎた）",
            "year": "関連する年代や時期（例：60代, 2020年頃）",
            "cast": "当事者の属性（例：70代男性、元会社員）",
            "dialogue": [
                {{"speaker": "カツミ", "text": "第{ranking_example}位は『〇〇』です。"}},
                {{"speaker": "ヒロシ", "text": "おお、これはよく聞く話ですね。"}},
                {{"speaker": "カツミ", "text": "この方は〇〇という状況でした。"}},
                {{"speaker": "ヒロシ", "text": "なるほど、それは大変でしたね。"}},
                ...（{dialogue_turns}、カツミが紹介→ヒロシがリアクションの流れ）
            ],
            "image_keyword": "イメージの英語キーワード（例: senior citizen worried, retirement savings）"
        }},
        ... ({ranking_example}位から1位まで{ranking_example}個)
    ],
    "ending": [
        {{"speaker": "カツミ", "text": "以上、ランキングでした。いかがでしたか？"}},
        {{"speaker": "ヒロシ", "text": "どれも考えさせられる内容でしたね。"}},
        {{"speaker": "カツミ", "text": "皆さんも気をつけてくださいね。"}},
        {{"speaker": "ヒロシ", "text": "コメントで体験談も教えてください。"}},
        {{"speaker": "カツミ", "text": "チャンネル登録もよろしくお願いします。"}},
        {{"speaker": "ヒロシ", "text": "それでは、また次回お会いしましょう。"}}
    ]
}}

【重要】
- ランキングは必ず{ranking_example}位から1位まで{ranking_example}個作成
- 各セリフは20〜40文字程度（短めにテンポよく）
- カツミは紹介・説明、ヒロシはリアクション・共感
- シニア世代が共感できる具体的な事例を紹介
- 教訓やアドバイスも含める
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


def wave_file(filename: str, pcm: bytes, channels: int = 1, rate: int = 24000, sample_width: int = 2):
    """PCMデータをWAVファイルとして保存"""
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm)


def generate_fish_audio_tts(text: str, reference_id: str, output_path: str, max_retries: int = 3, timeout: int = 60) -> bool:
    """
    Fish Audio APIで音声を生成

    Args:
        text: 読み上げるテキスト
        reference_id: Fish AudioのボイスモデルID
        output_path: 出力ファイルパス（.wav）
        max_retries: 最大リトライ回数
        timeout: タイムアウト秒数

    Returns:
        bool: 成功時True
    """
    if not FISH_AUDIO_API_KEY:
        print("    [Fish Audio] エラー: FISH_AUDIO_API_KEY が設定されていません")
        return False

    headers = {
        "Authorization": f"Bearer {FISH_AUDIO_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "text": text,
        "reference_id": reference_id,
        "format": "wav"
    }

    last_error = None

    for attempt in range(max_retries):
        try:
            response = requests.post(
                FISH_AUDIO_API_URL,
                headers=headers,
                json=payload,
                timeout=timeout
            )

            if response.status_code == 200:
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                return True
            elif response.status_code == 429:
                print(f"      [試行 {attempt + 1}] レート制限 (429)")
            else:
                print(f"      [試行 {attempt + 1}] エラー: {response.status_code} - {response.text[:100]}")
                last_error = f"HTTP {response.status_code}"

        except requests.Timeout:
            print(f"      [試行 {attempt + 1}] タイムアウト")
            last_error = "Timeout"
        except Exception as e:
            print(f"      [試行 {attempt + 1}] エラー: {str(e)[:100]}")
            last_error = str(e)

        if attempt < max_retries - 1:
            wait_time = (attempt + 1) * 2
            print(f"      {wait_time}秒後にリトライ...")
            time.sleep(wait_time)

    print(f"    [Fish Audio] ✗ 全リトライ失敗: {last_error}")
    return False


def generate_silence(output_path: str, duration: float = 0.5, sample_rate: int = 24000) -> bool:
    """
    無音のWAVファイルを生成

    Args:
        output_path: 出力ファイルパス
        duration: 無音の長さ（秒）
        sample_rate: サンプルレート

    Returns:
        bool: 成功時True
    """
    try:
        cmd = [
            'ffmpeg', '-y',
            '-f', 'lavfi',
            '-i', f'anullsrc=r={sample_rate}:cl=mono',
            '-t', str(duration),
            '-acodec', 'pcm_s16le',
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0
    except Exception as e:
        print(f"    [ffmpeg] 無音生成エラー: {e}")
        return False


def add_silence_to_audio(audio_path: str, silence_duration: float = 0.5) -> bool:
    """
    音声ファイルの末尾に無音を追加

    Args:
        audio_path: 音声ファイルパス（上書き）
        silence_duration: 追加する無音の長さ（秒）

    Returns:
        bool: 成功時True
    """
    try:
        temp_dir = Path(audio_path).parent
        silence_file = str(temp_dir / "silence_padding.wav")
        temp_output = str(temp_dir / "temp_with_silence.wav")

        # 無音ファイルを生成
        if not generate_silence(silence_file, silence_duration):
            return False

        # 結合用ファイルリストを作成
        list_file = temp_dir / "silence_concat.txt"
        with open(list_file, 'w') as f:
            f.write(f"file '{audio_path}'\n")
            f.write(f"file '{silence_file}'\n")

        # 結合
        cmd = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', str(list_file),
            '-acodec', 'pcm_s16le', '-ar', '24000', '-ac', '1',
            temp_output
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        # クリーンアップと置き換え
        if list_file.exists():
            list_file.unlink()
        if os.path.exists(silence_file):
            os.remove(silence_file)

        if result.returncode == 0:
            # 元ファイルを置き換え
            import shutil
            shutil.move(temp_output, audio_path)
            return True
        else:
            if os.path.exists(temp_output):
                os.remove(temp_output)
            return False

    except Exception as e:
        print(f"    [ffmpeg] 無音追加エラー: {e}")
        return False


def concatenate_audio_files(audio_files: list, output_path: str, gap_duration: float = 0.5) -> bool:
    """
    複数の音声ファイルをffmpegで結合（各ファイル間に無音ギャップを挿入）

    Args:
        audio_files: 結合する音声ファイルのリスト
        output_path: 出力ファイルパス
        gap_duration: 各音声間のギャップ（秒）デフォルト0.5秒

    Returns:
        bool: 成功時True
    """
    if not audio_files:
        return False

    if len(audio_files) == 1:
        # 1ファイルの場合は無音を追加してコピー
        import shutil
        shutil.copy(audio_files[0], output_path)
        add_silence_to_audio(output_path, 0.5)  # 末尾に0.5秒の無音追加
        return True

    try:
        # 一時ファイルリストを作成（間に無音を挿入）
        temp_dir = Path(audio_files[0]).parent
        list_file = temp_dir / "concat_list.txt"
        silence_file = str(temp_dir / "gap_silence.wav")

        # 無音ファイルを生成
        if not generate_silence(silence_file, gap_duration):
            print(f"    [警告] ギャップ用無音生成失敗、ギャップなしで続行")
            silence_file = None

        with open(list_file, 'w') as f:
            for i, audio_file in enumerate(audio_files):
                f.write(f"file '{audio_file}'\n")
                # 最後以外のファイルの後にギャップを挿入
                if silence_file and i < len(audio_files) - 1:
                    f.write(f"file '{silence_file}'\n")

        # ffmpegで結合
        cmd = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', str(list_file),
            '-acodec', 'pcm_s16le', '-ar', '24000', '-ac', '1',
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        # 一時ファイル削除
        if list_file.exists():
            list_file.unlink()
        if silence_file and os.path.exists(silence_file):
            os.remove(silence_file)

        if result.returncode == 0:
            # 末尾に0.5秒の無音を追加（音声切れ対策）
            add_silence_to_audio(output_path, 0.5)
            return True
        else:
            print(f"    [ffmpeg] 結合エラー: {result.stderr[:200]}")
            return False

    except Exception as e:
        print(f"    [ffmpeg] 結合エラー: {e}")
        return False


def generate_fish_audio_dialogue(dialogue: list, channel: str, output_path: str, temp_dir: Path, max_retries: int = 3) -> bool:
    """
    Fish Audio APIでセリフごとに音声を生成し、結合

    Args:
        dialogue: 対話リスト [{"speaker": "カツミ", "text": "..."}, ...]
        channel: チャンネル番号（"23", "24", "27"）
        output_path: 出力WAVファイルパス
        temp_dir: 一時ファイル用ディレクトリ
        max_retries: 最大リトライ回数

    Returns:
        bool: 成功時True
    """
    # チャンネル別ボイス設定を取得
    katsumi_voice, hiroshi_voice = CHANNEL_VOICE_CONFIG.get(
        channel,
        (FISH_VOICE_KATSUMI, FISH_VOICE_HIROSHI)
    )

    print(f"    [Fish Audio] セリフごと音声生成中...")
    print(f"    カツミ={get_voice_name(katsumi_voice)}, ヒロシ={get_voice_name(hiroshi_voice)}")
    print(f"    セリフ数: {len(dialogue)}件")

    audio_files = []

    for idx, line in enumerate(dialogue):
        speaker = line["speaker"]
        text = apply_reading_dict(line["text"])  # 読み方辞書を適用

        # ボイスIDを選択
        voice_id = katsumi_voice if speaker == "カツミ" else hiroshi_voice

        # 感情タグを追加
        emotion_tag = detect_emotion_tag(speaker, text)
        tagged_text = emotion_tag + text

        # 一時ファイルパス
        temp_audio = str(temp_dir / f"line_{idx:03d}.wav")

        print(f"      [{idx + 1}/{len(dialogue)}] {speaker}: {text[:30]}...")
        if emotion_tag:
            print(f"        感情タグ: {emotion_tag.strip()}")

        # Fish Audio APIで生成
        if generate_fish_audio_tts(tagged_text, voice_id, temp_audio, max_retries):
            audio_files.append(temp_audio)
        else:
            print(f"      ✗ セリフ {idx + 1} の生成に失敗")
            # 失敗してもフォールバック（gTTSで単一セリフ）
            try:
                from gtts import gTTS
                tts = gTTS(text=text, lang='ja')
                temp_mp3 = temp_audio.replace('.wav', '.mp3')
                tts.save(temp_mp3)

                # WAVに変換
                cmd = ['ffmpeg', '-y', '-i', temp_mp3, '-acodec', 'pcm_s16le', '-ar', '24000', '-ac', '1', temp_audio]
                subprocess.run(cmd, capture_output=True)

                if os.path.exists(temp_mp3):
                    os.remove(temp_mp3)

                if os.path.exists(temp_audio):
                    audio_files.append(temp_audio)
            except Exception as e:
                print(f"        フォールバックも失敗: {e}")

    if not audio_files:
        print("    [Fish Audio] ✗ 音声ファイルが生成されませんでした")
        return False

    # 音声ファイルを結合
    print(f"    [Fish Audio] {len(audio_files)}件の音声を結合中...")
    if concatenate_audio_files(audio_files, output_path):
        # 一時ファイル削除
        for f in audio_files:
            if os.path.exists(f):
                os.remove(f)

        file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
        print(f"    [Fish Audio] ✓ 生成成功 ({file_size} bytes)")
        return True

    return False


def generate_gtts_dialogue(dialogue: list, output_path: str) -> bool:
    """gTTSで対話音声を生成（フォールバック用、WAV出力）"""
    try:
        # 全テキストを結合
        full_text = " ".join([line["text"] for line in dialogue])
        tts = gTTS(text=full_text, lang='ja')

        # 一時MP3ファイルに保存
        temp_mp3 = output_path.replace('.wav', '_temp.mp3')
        tts.save(temp_mp3)

        # MP3をWAVに変換
        cmd = [
            'ffmpeg', '-y', '-i', temp_mp3,
            '-acodec', 'pcm_s16le', '-ar', '24000', '-ac', '1',
            output_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)

        # 一時ファイル削除
        if os.path.exists(temp_mp3):
            os.remove(temp_mp3)

        return True
    except Exception as e:
        print(f"    gTTS生成エラー: {e}")
        return False


def generate_dialogue_audio(dialogue: list, output_path: str, key_manager, channel: str = "27") -> tuple:
    """
    対話の音声を生成（Fish Audio TTS版、WAV出力）

    Args:
        dialogue: 対話リスト
        output_path: 出力WAVファイルパス
        key_manager: GeminiKeyManager インスタンス（互換性のため残す）
        channel: チャンネル番号

    Returns:
        tuple: (audio_path, segments, total_duration)
    """
    segments = []

    # 一時ディレクトリを取得
    temp_dir = Path(output_path).parent

    # Fish Audio APIで音声を生成
    if FISH_AUDIO_API_KEY and generate_fish_audio_dialogue(dialogue, channel, output_path, temp_dir):
        # 音声ファイルの長さを取得
        total_duration = get_audio_duration_ffprobe(output_path)

        if total_duration > 0:
            # セグメント情報を推定（テキスト長で比例配分）
            total_chars = sum(len(line["text"]) for line in dialogue)
            current_time = 0.0

            for line in dialogue:
                speaker = line["speaker"]
                text = line["text"]

                # テキスト長に基づいて時間を推定
                char_ratio = len(text) / total_chars if total_chars > 0 else 1 / len(dialogue)
                duration = total_duration * char_ratio

                segments.append({
                    "speaker": speaker,
                    "text": text,
                    "start": current_time,
                    "end": current_time + duration,
                    "color": CHARACTERS.get(speaker, {}).get("color", "#FFFFFF")
                })

                current_time += duration

            return output_path, segments, total_duration

    # フォールバック: gTTS
    print("    [フォールバック] gTTSで音声生成...")
    if generate_gtts_dialogue(dialogue, output_path):
        total_duration = get_audio_duration_ffprobe(output_path)

        if total_duration > 0:
            # セグメント情報を推定
            total_chars = sum(len(line["text"]) for line in dialogue)
            current_time = 0.0

            for line in dialogue:
                speaker = line["speaker"]
                text = line["text"]

                char_ratio = len(text) / total_chars if total_chars > 0 else 1 / len(dialogue)
                duration = total_duration * char_ratio

                segments.append({
                    "speaker": speaker,
                    "text": text,
                    "start": current_time,
                    "end": current_time + duration,
                    "color": CHARACTERS.get(speaker, {}).get("color", "#FFFFFF")
                })

                current_time += duration

            return output_path, segments, total_duration

    return output_path, segments, 0.0


def fetch_unsplash_image(query: str, output_path: str) -> bool:
    """Unsplash APIから画像をダウンロード"""
    if not UNSPLASH_ACCESS_KEY:
        print("    [Unsplash] エラー: UNSPLASH_ACCESS_KEY が設定されていません")
        return False

    try:
        print(f"    [Unsplash] 検索中: {query}")

        # Unsplash API検索
        headers = {
            "Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"
        }
        params = {
            "query": query,
            "per_page": 3,
            "orientation": "landscape"  # 横長画像を優先
        }

        response = requests.get(UNSPLASH_API_URL, headers=headers, params=params, timeout=30)

        if response.status_code != 200:
            print(f"    [Unsplash] APIエラー: {response.status_code}")
            return False

        data = response.json()
        results = data.get("results", [])

        if not results:
            print(f"    [Unsplash] 画像が見つかりませんでした")
            return False

        # 最初の画像をダウンロード
        image_url = results[0]["urls"]["regular"]  # 1080p相当
        print(f"    [Unsplash] ダウンロード中...")

        img_response = requests.get(image_url, timeout=30)
        if img_response.status_code != 200:
            print(f"    [Unsplash] 画像ダウンロードエラー: {img_response.status_code}")
            return False

        # 画像を保存
        with open(output_path, 'wb') as f:
            f.write(img_response.content)

        # リサイズ
        resize_image(output_path, VIDEO_WIDTH, VIDEO_HEIGHT)

        print(f"    [Unsplash] ✓ 画像取得成功!")
        return True

    except requests.Timeout:
        print(f"    [Unsplash] タイムアウト")
    except Exception as e:
        print(f"    [Unsplash] エラー: {e}")

    return False


def fetch_ranking_image(work_title: str, cast: str, output_path: str) -> bool:
    """ランキング項目用の画像を取得（Unsplash APIで試行）"""
    # 検索クエリの優先順位（英語キーワードも追加でUnsplash向け最適化）
    queries = []

    # 事例タイトルでの検索（シニア向けコンテンツ）
    if work_title:
        queries.append(f"{work_title}")             # 事例のみ
        queries.append(f"senior {work_title}")      # 英語 + 事例
        queries.append("elderly lifestyle")          # 汎用シニア画像

    # 当事者属性での検索
    if cast:
        queries.append(f"{cast}")                   # 属性のみ
        queries.append("senior citizen")            # 汎用シニア

    # フォールバック用の汎用クエリ
    queries.append("elderly happy")
    queries.append("senior lifestyle")

    for query in queries:
        if not query or not query.strip():
            continue
        if fetch_unsplash_image(query, output_path):
            return True
        time.sleep(0.5)  # レート制限対策

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


def generate_ranking_table_image(
    output_path: str,
    rankings: list,
    current_rank: int = None,
    video_title: str = None
):
    """
    ランキング表の画像を生成（1920x1080横動画用）

    Args:
        output_path: 出力画像パス
        rankings: ランキングデータのリスト [{rank, work_title, year, cast}, ...]
        current_rank: 現在発表中の順位（ハイライト表示）
        video_title: 動画タイトル（上部に表示）
    """
    img = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT))
    draw = ImageDraw.Draw(img)

    # 背景グラデーション（ダークブルー系）
    for y in range(VIDEO_HEIGHT):
        ratio = y / VIDEO_HEIGHT
        r = int(20 * (1 - ratio) + 40 * ratio)
        g = int(30 * (1 - ratio) + 60 * ratio)
        b = int(60 * (1 - ratio) + 100 * ratio)
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=(r, g, b))

    # フォント設定
    font_path = get_font_path()
    try:
        font_title = ImageFont.truetype(font_path, 56) if font_path else ImageFont.load_default()
        font_rank = ImageFont.truetype(font_path, 44) if font_path else ImageFont.load_default()
        font_item = ImageFont.truetype(font_path, 36) if font_path else ImageFont.load_default()
    except:
        font_title = ImageFont.load_default()
        font_rank = ImageFont.load_default()
        font_item = ImageFont.load_default()

    # タイトル描画
    if video_title:
        # タイトルを短縮（長すぎる場合）
        display_title = video_title[:30] + "..." if len(video_title) > 30 else video_title
        bbox = draw.textbbox((0, 0), display_title, font=font_title)
        text_width = bbox[2] - bbox[0]
        x = (VIDEO_WIDTH - text_width) // 2
        # 影
        draw.text((x + 3, 33), display_title, font=font_title, fill=(0, 0, 0))
        draw.text((x, 30), display_title, font=font_title, fill=(255, 215, 0))  # ゴールド

    # テーブル設定
    table_top = 120
    table_left = 100
    table_width = VIDEO_WIDTH - 200
    row_height = 85

    # ヘッダー
    header_y = table_top
    draw.rectangle(
        [table_left, header_y, table_left + table_width, header_y + row_height],
        fill=(50, 50, 80),
        outline=(100, 100, 150),
        width=2
    )

    # ヘッダーテキスト
    col_widths = [120, 600, 150, 400]  # 順位, タイトル, 年, 詳細
    headers = ["順位", "タイトル", "年", "詳細"]
    col_x = table_left
    for i, (header, width) in enumerate(zip(headers, col_widths)):
        bbox = draw.textbbox((0, 0), header, font=font_rank)
        text_width = bbox[2] - bbox[0]
        x = col_x + (width - text_width) // 2
        draw.text((x, header_y + 20), header, font=font_rank, fill=(200, 200, 255))
        col_x += width

    # ランキング行を描画（1位が上、10位が下の順）
    # 表示：1位→2位→...→10位（上から下へ）
    # 発表：10位→9位→...→1位（下から上へ進む）
    sorted_rankings = sorted(rankings, key=lambda x: x.get("rank", 0), reverse=False)

    for idx, item in enumerate(sorted_rankings):
        rank = item.get("rank", idx + 1)
        work_title = item.get("work_title", "")[:25]  # 長すぎる場合は切る
        year = item.get("year", "")
        cast = item.get("cast", "")[:20]  # 長すぎる場合は切る

        row_y = table_top + row_height * (idx + 1)

        # 現在の順位をハイライト（10位から発表なので、current_rank以上の数字が発表済み）
        is_current = (current_rank is not None and rank == current_rank)
        is_revealed = (current_rank is not None and rank >= current_rank)

        if is_current:
            # 現在発表中: 黄色ハイライト
            bg_color = (255, 215, 0)  # ゴールド
            text_color = (0, 0, 0)
            # グロー効果
            for offset in range(5, 0, -1):
                alpha = int(50 * offset / 5)
                glow_color = (255, 255, 200)
                draw.rectangle(
                    [table_left - offset, row_y - offset,
                     table_left + table_width + offset, row_y + row_height + offset],
                    outline=glow_color,
                    width=1
                )
        elif is_revealed:
            # 発表済み: やや明るい背景
            bg_color = (60, 70, 100)
            text_color = (255, 255, 255)
        else:
            # 未発表: 暗い背景（シルエット）
            bg_color = (30, 35, 50)
            text_color = (100, 100, 120)

        # 行の背景
        draw.rectangle(
            [table_left, row_y, table_left + table_width, row_y + row_height],
            fill=bg_color,
            outline=(80, 80, 120),
            width=1
        )

        # 順位（1-3位は特別色）
        rank_text = f"第{rank}位"
        if rank <= 3 and is_revealed:
            if rank == 1:
                rank_color = (255, 215, 0) if not is_current else (180, 0, 0)  # ゴールド
            elif rank == 2:
                rank_color = (192, 192, 192) if not is_current else (0, 0, 0)  # シルバー
            else:
                rank_color = (205, 127, 50) if not is_current else (0, 0, 0)  # ブロンズ
        else:
            rank_color = text_color

        col_x = table_left
        # 順位
        bbox = draw.textbbox((0, 0), rank_text, font=font_rank)
        text_width = bbox[2] - bbox[0]
        x = col_x + (col_widths[0] - text_width) // 2
        draw.text((x, row_y + 22), rank_text, font=font_rank, fill=rank_color)
        col_x += col_widths[0]

        # タイトル（未発表時は「？？？」）
        if is_revealed:
            title_display = f"『{work_title}』" if work_title else "---"
        else:
            title_display = "？？？"
        draw.text((col_x + 20, row_y + 25), title_display, font=font_item, fill=text_color)
        col_x += col_widths[1]

        # 年
        if is_revealed:
            year_display = str(year) if year else "---"
        else:
            year_display = "？？"
        bbox = draw.textbbox((0, 0), year_display, font=font_item)
        text_width = bbox[2] - bbox[0]
        x = col_x + (col_widths[2] - text_width) // 2
        draw.text((x, row_y + 25), year_display, font=font_item, fill=text_color)
        col_x += col_widths[2]

        # 詳細（キャスト）
        if is_revealed:
            cast_display = cast if cast else "---"
        else:
            cast_display = "？？？？？"
        draw.text((col_x + 20, row_y + 25), cast_display, font=font_item, fill=text_color)

    # 装飾: 下部にチャンネル情報
    footer_text = "チャンネル登録よろしくお願いします！"
    bbox = draw.textbbox((0, 0), footer_text, font=font_item)
    text_width = bbox[2] - bbox[0]
    x = (VIDEO_WIDTH - text_width) // 2
    draw.text((x + 2, VIDEO_HEIGHT - 52), footer_text, font=font_item, fill=(0, 0, 0))
    draw.text((x, VIDEO_HEIGHT - 50), footer_text, font=font_item, fill=(255, 255, 255))

    img.save(output_path, quality=95)
    return output_path


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


def combine_audio_ffmpeg(audio_files: list, output_path: str, gap_duration: float = 0.5) -> bool:
    """FFmpegで音声ファイルを結合（WAV→MP3変換対応、無音ギャップ挿入）

    Args:
        audio_files: 結合する音声ファイルのリスト
        output_path: 出力ファイルパス（MP3）
        gap_duration: 各音声間のギャップ（秒）デフォルト0.5秒
    """
    if not audio_files:
        return False

    temp_dir = Path(audio_files[0]).parent
    silence_file = str(temp_dir / "combine_silence.wav")
    padding_file = str(temp_dir / "combine_padding.wav")

    # 無音ファイルを生成（ギャップ用）
    silence_generated = generate_silence(silence_file, gap_duration, 24000)
    if silence_generated:
        print(f"  無音ギャップ: {gap_duration}秒")

    # 末尾パディング用無音
    padding_generated = generate_silence(padding_file, 0.5, 24000)

    if len(audio_files) == 1:
        # 1ファイルの場合：末尾に無音を追加してMP3変換
        list_path = output_path + ".txt"
        with open(list_path, 'w') as f:
            f.write(f"file '{audio_files[0]}'\n")
            if padding_generated:
                f.write(f"file '{padding_file}'\n")

        cmd = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', list_path,
            '-acodec', 'libmp3lame', '-ab', '192k',
            output_path
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            os.remove(list_path)
            print(f"  末尾無音パディング: 0.5秒")
            return True
        except subprocess.CalledProcessError as e:
            print(f"音声変換エラー: {e.stderr.decode()[:200]}")
            return False

    # concat用のファイルリストを作成（無音ギャップ挿入）
    list_path = output_path + ".txt"
    with open(list_path, 'w') as f:
        for i, audio_file in enumerate(audio_files):
            f.write(f"file '{audio_file}'\n")
            # 最後以外のファイルの後にギャップを挿入
            if silence_generated and i < len(audio_files) - 1:
                f.write(f"file '{silence_file}'\n")
        # 末尾に無音パディングを追加
        if padding_generated:
            f.write(f"file '{padding_file}'\n")

    # WAVを結合してMP3にエンコード
    cmd = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
        '-i', list_path,
        '-acodec', 'libmp3lame', '-ab', '192k',
        output_path
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        os.remove(list_path)
        # 一時ファイル削除
        if os.path.exists(silence_file):
            os.remove(silence_file)
        if os.path.exists(padding_file):
            os.remove(padding_file)
        print(f"  末尾無音パディング: 0.5秒")
        return True
    except subprocess.CalledProcessError as e:
        print(f"音声結合エラー: {e.stderr.decode()[:200]}")
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

    # 4. ASS字幕ファイルを生成（話者別位置指定）
    print("\n[4/6] ASS字幕ファイルを生成中...")
    ass_path = str(temp_dir / f"asadora_ranking_{timestamp}.ass")
    srt_path = str(temp_dir / f"asadora_ranking_{timestamp}.srt")  # 互換性のため
    generate_ass_subtitles_positioned(all_segments, ass_path, VIDEO_WIDTH, VIDEO_HEIGHT)
    generate_srt(all_segments, srt_path)  # SRTも生成（アーティファクト用）
    print(f"  字幕数: {len(all_segments)}件")
    print(f"  カツミ: 画面65%位置, ヒロシ: 画面80%位置")

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
        # BGMなし: 音声の長さに合わせて動画を生成（-shortestは使用しない）
        cmd_step1 = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', concat_file,
            '-i', combined_audio,
            '-vf', f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}",
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-t', str(total_duration + 1.0),  # 音声長 + 1秒の余裕
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

    # 6. 字幕を動画全体にオーバーレイ（ASS形式で話者別位置）
    print("\n[6/6] 字幕を動画にオーバーレイ中...")
    print("  ASS形式: カツミ=65%位置(オレンジ), ヒロシ=80%位置(青)")

    # ASS字幕を使用（話者別の位置・色が設定済み）
    cmd_step2 = [
        'ffmpeg', '-y',
        '-i', temp_video,
        '-vf', f"ass={ass_path}",
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
    """SRTファイルを生成（互換性のため残す）"""
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments, 1):
            start = format_srt_time(seg['start'])
            end = format_srt_time(seg['end'])
            speaker = seg.get('speaker', '')
            text = f"{speaker}：{seg['text']}" if speaker else seg['text']
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")


def generate_ass_subtitles_positioned(segments: list, output_path: str, video_width: int = 1920, video_height: int = 1080):
    """
    ASS形式の字幕ファイルを生成（話者別の位置指定）

    位置設定:
    - タイトル/その他: 画面上部 (Alignment=8, MarginV=50)
    - カツミ: 画面の65%位置 (Alignment=2, MarginV=378)
    - ヒロシ: 画面の80%位置 (Alignment=2, MarginV=216)
    """
    # MarginVの計算（1080pベース）
    # y=65% → 上から702px → 下から378px
    # y=80% → 上から864px → 下から216px
    margin_katsumi = int(video_height * 0.35)  # 378 at 1080p
    margin_hiroshi = int(video_height * 0.20)  # 216 at 1080p

    header = f"""[Script Info]
Title: シニアの口コミランキング
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Katsumi,Noto Sans CJK JP,64,&H00FFE4B5,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,50,50,{margin_katsumi},1
Style: Hiroshi,Noto Sans CJK JP,64,&H006495ED,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,50,50,{margin_hiroshi},1
Style: Title,Noto Sans CJK JP,72,&H0000D7FF,&H000000FF,&H00000080,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,8,50,50,50,1
Style: Default,Noto Sans CJK JP,64,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,50,50,300,1

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
        if speaker == 'カツミ':
            style = 'Katsumi'
            display_text = f"カツミ：{text}"
        elif speaker == 'ヒロシ':
            style = 'Hiroshi'
            display_text = f"ヒロシ：{text}"
        else:
            style = 'Default'
            display_text = text

        lines.append(f"Dialogue: 0,{start},{end},{style},,0,0,0,,{display_text}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def format_srt_time(seconds: float) -> str:
    """秒をSRT形式に変換"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def create_video(script: dict, temp_dir: Path, key_manager: GeminiKeyManager, channel: str = "27") -> tuple:
    """動画を作成（FFmpegベース高速版、各順位ごとにWAV音声を生成）"""
    sections = []  # FFmpeg用のセクション情報
    all_segments = []
    section_timestamps = []  # チャプター用タイムスタンプ
    current_time = 0.0
    video_title = script.get("title", "")  # 動画タイトル（フォールバック用）
    rankings_data = script.get("rankings", [])  # ランキングデータ

    total_steps = RANKING_COUNT + 2  # オープニング + ランキング数 + エンディング
    print(f"動画作成開始（FFmpeg高速モード）... [全{total_steps}セクション]")

    # オープニング
    print(f"[1/{total_steps}] オープニング音声生成中...")
    opening_audio_path = str(temp_dir / "opening.wav")

    opening_audio, opening_segments, opening_duration = generate_dialogue_audio(
        script["opening"], opening_audio_path, key_manager, channel
    )

    # オープニング背景: ランキング表（全て未発表）
    opening_bg = str(temp_dir / "opening_bg.png")
    generate_ranking_table_image(
        opening_bg,
        rankings_data,
        current_rank=RANKING_COUNT + 1,  # 全て未発表
        video_title=video_title
    )
    print(f"    → ランキング表（オープニング）を生成")

    # オープニングのチャプター
    section_timestamps.append({
        "time": 0.0,
        "title": "オープニング"
    })

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

    # ランキング（順位ごとに別々のWAVファイルを生成）
    for idx, item in enumerate(script["rankings"]):
        rank = item["rank"]
        step = idx + 2  # オープニングが1なので2から
        print(f"[{step}/{total_steps}] 第{rank}位 音声生成中...")

        # チャプター用タイムスタンプを記録
        work_title = item.get("work_title", "")
        section_timestamps.append({
            "time": current_time,
            "title": f"第{rank}位 {work_title}"
        })

        # 順位ごとに別ファイルで音声を生成
        rank_audio_path = str(temp_dir / f"rank_{rank}.wav")

        audio_path, segments, duration = generate_dialogue_audio(
            item["dialogue"], rank_audio_path, key_manager, channel
        )

        # 背景画像: ランキング表（現在の順位をハイライト）
        image_path = str(temp_dir / f"rank_{rank}_table.png")
        generate_ranking_table_image(
            image_path,
            rankings_data,
            current_rank=rank,
            video_title=video_title
        )
        print(f"    → ランキング表（第{rank}位ハイライト）を生成")

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
    ending_audio_path = str(temp_dir / "ending.wav")

    ending_audio, ending_segments, ending_duration = generate_dialogue_audio(
        script["ending"], ending_audio_path, key_manager, channel
    )

    # エンディング背景: ランキング表（全て発表済み）
    ending_bg = str(temp_dir / "ending_bg.png")
    generate_ranking_table_image(
        ending_bg,
        rankings_data,
        current_rank=1,  # 全て発表済み
        video_title=video_title
    )
    print(f"    → ランキング表（エンディング・全発表）を生成")

    # エンディングのチャプター
    section_timestamps.append({
        "time": current_time,
        "title": "エンディング"
    })

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

    video_path, srt_path = create_video_ffmpeg(sections, all_segments, temp_dir)

    # チャプター情報をファイルに保存
    chapters_path = str(temp_dir / "chapters.txt")
    generate_youtube_chapters(section_timestamps, chapters_path)

    return video_path, srt_path, section_timestamps


def generate_youtube_chapters(timestamps: list, output_path: str) -> str:
    """
    YouTubeチャプター用のテキストを生成

    Args:
        timestamps: [{"time": 0.0, "title": "オープニング"}, ...]
        output_path: 出力ファイルパス

    Returns:
        チャプターテキスト
    """
    lines = []
    for item in timestamps:
        time_seconds = item["time"]
        title = item["title"]

        # 秒を MM:SS または H:MM:SS 形式に変換
        hours = int(time_seconds // 3600)
        minutes = int((time_seconds % 3600) // 60)
        seconds = int(time_seconds % 60)

        if hours > 0:
            time_str = f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            time_str = f"{minutes}:{seconds:02d}"

        lines.append(f"{time_str} {title}")

    chapters_text = "\n".join(lines)

    # ファイルに保存
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(chapters_text)

    print(f"\n[チャプター情報]")
    print(chapters_text)

    return chapters_text


def format_chapters_for_description(timestamps: list) -> str:
    """
    YouTubeの説明欄用にチャプター情報をフォーマット

    Args:
        timestamps: [{"time": 0.0, "title": "オープニング"}, ...]

    Returns:
        YouTube説明欄用のチャプターテキスト
    """
    lines = ["📋 チャプター"]
    for item in timestamps:
        time_seconds = item["time"]
        title = item["title"]

        # 秒を MM:SS または H:MM:SS 形式に変換
        hours = int(time_seconds // 3600)
        minutes = int((time_seconds % 3600) // 60)
        seconds = int(time_seconds % 60)

        if hours > 0:
            time_str = f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            time_str = f"{minutes}:{seconds:02d}"

        lines.append(f"{time_str} {title}")

    return "\n".join(lines)


def upload_to_youtube(video_path: str, title: str, description: str, tags: list, channel_token: str, mode: str = "AUTO") -> str:
    """YouTubeに動画をアップロード（常に限定公開）

    Args:
        mode: 互換性のため残すが、常に限定公開(unlisted)でアップロード
    """
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")

    # TOKEN環境変数名を構築（YOUTUBE_REFRESH_TOKEN_X 形式）
    token_env_name = f"YOUTUBE_REFRESH_TOKEN_{channel_token}"
    refresh_token = os.environ.get(token_env_name)

    # デバッグ情報
    print(f"\n[YouTubeアップロード]")
    print(f"  チャンネル: {channel_token}")
    print(f"  TOKEN環境変数: {token_env_name}")
    print(f"  TOKEN: {'✓ あり' if refresh_token else '✗ なし'}")
    print(f"  CLIENT_ID: {'✓ あり' if client_id else '✗ なし'}")
    print(f"  CLIENT_SECRET: {'✓ あり' if client_secret else '✗ なし'}")

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

    # 公開設定: 常に限定公開（unlisted）
    privacy_status = "unlisted"
    print(f"\n[公開設定]")
    print(f"  privacyStatus: {privacy_status}")
    print(f"  → 限定公開（URLを知っている人だけ視聴可能）")

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
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    # アップロード完了メッセージを表示
    print("\n" + "=" * 40)
    print("YouTube投稿完了!")
    print("=" * 40)
    print(f"動画URL: {video_url}")
    print(f"チャンネル: TOKEN_{channel_token}")
    print(f"タイトル: {title}")
    print(f"公開設定: 限定公開")
    print("=" * 40)

    return video_url


def send_slack_notification(message: str, success: bool = True):
    """Slack通知（無効化済み）"""
    return
    # 以下は無効化
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return

    emoji = ":white_check_mark:" if success else ":x:"
    payload = {"text": f"{emoji} *シニアの口コミランキング*\n{message}"}

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

    # デバッグ: タスク情報を表示
    print(f"\n{'='*50}")
    print(f"[タスク情報]")
    print(f"  テーマ: {theme}")
    print(f"  チャンネル: {channel} (TOKEN_{channel})")
    print(f"  モード: {mode} → {'限定公開' if mode == 'TEST' else '公開'}")
    print(f"{'='*50}\n")

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
        video_path, srt_path, chapter_timestamps = create_video(script, temp_dir, key_manager, channel)

        # チャプター情報を説明欄に追加
        chapters_text = format_chapters_for_description(chapter_timestamps)
        description_with_chapters = f"{script['description']}\n\n{chapters_text}"

        # 6. YouTubeアップロード
        print("[6/6] YouTubeアップロード中...")
        youtube_url = upload_to_youtube(
            video_path,
            script["title"],
            description_with_chapters,
            script.get("tags", ["シニア", "老後", "ランキング", "口コミ"]),
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
    print("シニアの口コミランキング動画自動生成システム")
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
