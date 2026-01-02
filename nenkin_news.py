#!/usr/bin/env python3
"""
年金ニュース動画自動生成システム
- TOKEN_23（年金ニュースチャンネル）用
- Gemini APIでニュース収集→台本生成→Gemini TTS→動画生成→YouTube投稿
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
from datetime import datetime, timedelta
from pathlib import Path
# Note: 順次処理に変更したため ThreadPoolExecutor は未使用だが、将来のために残す
from concurrent.futures import ThreadPoolExecutor, as_completed

import google.generativeai as genai
from google import genai as genai_tts
from google.genai import types
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image, ImageDraw, ImageFont
from gtts import gTTS
from google.cloud import texttospeech
import anthropic  # Claude API for fact-checking

# ===== 定数 =====
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
CHANNEL = "23"  # TOKEN_23固定

# テストモード（環境変数で制御）
# TEST_MODE=true: 短縮版（1ニュース、5セリフ、約20秒）
# TEST_MODE=false または未設定: フル版
TEST_MODE = os.environ.get("TEST_MODE", "").lower() == "true"

# TTSモード（環境変数で制御）
# TTS_MODE=google_cloud: Google Cloud TTS（WaveNet）
# TTS_MODE=gemini: Gemini TTS（デフォルト）
TTS_MODE = os.environ.get("TTS_MODE", "gemini").lower()

# Modal GPUエンコード
# USE_MODAL_GPU=true（デフォルト） → Modal GPU (高速)
# USE_MODAL_GPU=false → ローカル CPU (遅い)
USE_MODAL_GPU = os.environ.get("USE_MODAL_GPU", "true").lower() == "true"

# ===== チャンネル情報 =====
CHANNEL_NAME = "毎日届く！得する年金ニュース速報"
CHANNEL_DESCRIPTION = "毎日11時、年金に関する最新ニュースをお届けします"

# ===== Gemini TTS設定 =====
GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"

# TTS音声設定（環境変数でカスタマイズ可能）
# 利用可能: Puck, Charon, Kore, Fenrir, Aoede
TTS_VOICE_FEMALE = os.environ.get("TTS_VOICE_FEMALE", "Kore")
TTS_VOICE_MALE = os.environ.get("TTS_VOICE_MALE", "Puck")

# TTS指示文（環境変数でカスタマイズ可能）
# 声質・トーン・スピードを詳細に指定して一貫性を確保
DEFAULT_TTS_INSTRUCTION = """あなたはプロフェッショナルな年金ニュース番組のパーソナリティです。

【最重要指示 - 絶対に従ってください】
- 台本のセリフを一字一句そのまま読み上げてください
- テキストを変更・省略・言い換え・要約しないでください
- 話者名（カツミ:、ヒロシ:）は読み上げず、セリフ部分のみ読んでください
- セリフの順番を変えないでください

【音声の一貫性 - 必ず従ってください】
- 番組全体を通して、各キャラクターの声質・トーン・スピードを完全に一貫させてください
- 途中で声の高さや話し方が変わらないように注意してください
- 自然で聞き取りやすい日本語で話してください

【カツミの声の特徴（{voice_female}音声を使用）】
- 60代前半女性の落ち着いた声
- トーン: 低め、温かみがある、信頼感がある
- スピード: ゆっくり目（1.0倍速）
- 感情: 穏やか、優しい、説明的
- 話し方: 丁寧語、専門家らしい説得力

【ヒロシの声の特徴（{voice_male}音声を使用）】
- 40代前半男性の素朴な声
- トーン: 中程度、明るい、親しみやすい、のんびり
- スピード: 普通（1.0倍速）
- 感情: 興味津々、驚き、共感
- 話し方: カジュアル、素朴な疑問を投げかける

【台本の読み上げルール】
- [カツミ] で始まる行はカツミの声で読む
- [ヒロシ] で始まる行はヒロシの声で読む
- 話者名は読み上げず、セリフ部分のみ読む
- セリフ間に適切な間を入れる"""

TTS_INSTRUCTION = os.environ.get("TTS_INSTRUCTION", DEFAULT_TTS_INSTRUCTION)

# ===== キャラクター設定 =====
# カツミ（60代前半女性）: 年金に詳しい解説役。年金受給が近い世代として視聴者に寄り添う。落ち着いた優しい口調。
GEMINI_VOICE_KATSUMI = TTS_VOICE_FEMALE

# ヒロシ（40代前半男性）: 親世代のために勉強中の聞き役。ちょっとお馬鹿で素朴な疑問を聞く。
GEMINI_VOICE_HIROSHI = TTS_VOICE_MALE

# ===== Google Cloud TTS設定 =====
# カツミ（60代前半女性）: ja-JP-Wavenet-A
GCLOUD_VOICE_KATSUMI = "ja-JP-Wavenet-A"
# ヒロシ（40代前半男性）: ja-JP-Wavenet-D
GCLOUD_VOICE_HIROSHI = "ja-JP-Wavenet-D"

CHARACTERS = {
    "カツミ": {
        "gemini_voice": GEMINI_VOICE_KATSUMI,
        "gcloud_voice": GCLOUD_VOICE_KATSUMI,
        "color": "#4169E1"
    },  # 説明役
    "ヒロシ": {
        "gemini_voice": GEMINI_VOICE_HIROSHI,
        "gcloud_voice": GCLOUD_VOICE_HIROSHI,
        "color": "#FF6347"
    }   # 聞き役
}

# チャンク設定 - 声の一貫性のため全セリフを1チャンクで生成
# Gemini TTSは32kトークンまで対応。本番158セリフも1チャンクで処理を試す
# 音声長上限は公式ドキュメントに記載なし（実運用で検証済み）
MAX_LINES_PER_CHUNK = 500

# ===== 読み方辞書（TTS用） =====
# デフォルト辞書（スプレッドシートから取得失敗時のフォールバック）
DEFAULT_READING_DICT = {
    "iDeCo": "イデコ",
    "IDECO": "イデコ",
    "ideco": "イデコ",
    "NISA": "ニーサ",
    "nisa": "ニーサ",
    "つみたてNISA": "つみたてニーサ",
    "新NISA": "しんニーサ",
    "GPIF": "ジーピーアイエフ",
    "厚労省": "こうろうしょう",
    "年金機構": "ねんきんきこう",
    "WPI": "ダブリューピーアイ",
    "401k": "よんまるいちけー",
    "DC": "ディーシー",
    "DB": "ディービー",
    "GDP": "ジーディーピー",
    "CPI": "シーピーアイ",
    "頭痛く": "あたまいたく",
    "頭痛い": "あたまいたい",
    "入れる": "はいれる",
    "入れて": "はいれて",
    "入れた": "はいれた",
    "入れない": "はいれない",
    "入れれば": "はいれれば",
    "高所得": "こうしょとく",
    "超える": "こえる",
    "超えて": "こえて",
    "超えた": "こえた",
    # 西暦年号（正しく読むため）
    "1960年": "せんきゅうひゃくろくじゅうねん",
    "1961年": "せんきゅうひゃくろくじゅういちねん",
    "1962年": "せんきゅうひゃくろくじゅうにねん",
    "1963年": "せんきゅうひゃくろくじゅうさんねん",
    "1964年": "せんきゅうひゃくろくじゅうよねん",
    "1965年": "せんきゅうひゃくろくじゅうごねん",
    "1966年": "せんきゅうひゃくろくじゅうろくねん",
    "1967年": "せんきゅうひゃくろくじゅうななねん",
    "1968年": "せんきゅうひゃくろくじゅうはちねん",
    "1969年": "せんきゅうひゃくろくじゅうきゅうねん",
    "1970年": "せんきゅうひゃくななじゅうねん",
    "1975年": "せんきゅうひゃくななじゅうごねん",
    "1980年": "せんきゅうひゃくはちじゅうねん",
    "1985年": "せんきゅうひゃくはちじゅうごねん",
    "1990年": "せんきゅうひゃくきゅうじゅうねん",
    "1995年": "せんきゅうひゃくきゅうじゅうごねん",
    "2000年": "にせんねん",
    "2005年": "にせんごねん",
    "2010年": "にせんじゅうねん",
    "2015年": "にせんじゅうごねん",
    "2020年": "にせんにじゅうねん",
    "2021年": "にせんにじゅういちねん",
    "2022年": "にせんにじゅうにねん",
    "2023年": "にせんにじゅうさんねん",
    "2024年": "にせんにじゅうよねん",
    "2025年": "にせんにじゅうごねん",
    "2026年": "にせんにじゅうろくねん",
    "2027年": "にせんにじゅうななねん",
    "2028年": "にせんにじゅうはちねん",
    "2029年": "にせんにじゅうきゅうねん",
    "2030年": "にせんさんじゅうねん",
    "月収": "げっしゅう",
    "月収入": "げっしゅうにゅう",
    "他人事": "たにんごと",
    "不確定": "ふかくてい",
    "不確定な": "ふかくていな",
    "確定": "かくてい",
    "確定申告": "かくていしんこく",
    "確定拠出": "かくていきょしゅつ",
}

# スプレッドシートから読み込む辞書（キャッシュ）
_reading_dict_cache = None

READING_DICT_SPREADSHEET_ID = "15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo"
READING_DICT_SHEET_NAME = "読み方辞書"


def load_reading_dict_from_spreadsheet() -> dict:
    """スプレッドシートから読み方辞書を読み込む"""
    global _reading_dict_cache
    if _reading_dict_cache is not None:
        return _reading_dict_cache

    try:
        key_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
        if not key_json:
            print("  [読み方辞書] 認証情報なし、デフォルト使用")
            _reading_dict_cache = DEFAULT_READING_DICT.copy()
            return _reading_dict_cache

        key_data = json.loads(key_json)
        creds = Credentials.from_service_account_info(
            key_data,
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
        )
        service = build('sheets', 'v4', credentials=creds)

        result = service.spreadsheets().values().get(
            spreadsheetId=READING_DICT_SPREADSHEET_ID,
            range=f"{READING_DICT_SHEET_NAME}!A2:B1000"
        ).execute()

        values = result.get('values', [])
        reading_dict = DEFAULT_READING_DICT.copy()

        for row in values:
            if len(row) >= 2 and row[0] and row[1]:
                reading_dict[row[0].strip()] = row[1].strip()

        print(f"  [読み方辞書] スプレッドシートから{len(values)}件追加読込")
        _reading_dict_cache = reading_dict
        return _reading_dict_cache

    except Exception as e:
        print(f"  [読み方辞書] 読込エラー: {e}、デフォルト使用")
        _reading_dict_cache = DEFAULT_READING_DICT.copy()
        return _reading_dict_cache


def _number_to_japanese(num: int) -> str:
    """数字を日本語読みに変換（1-31対応）"""
    readings = {
        1: "いち", 2: "に", 3: "さん", 4: "よん", 5: "ご",
        6: "ろく", 7: "なな", 8: "はち", 9: "きゅう", 10: "じゅう",
        11: "じゅういち", 12: "じゅうに", 13: "じゅうさん", 14: "じゅうよん", 15: "じゅうご",
        16: "じゅうろく", 17: "じゅうなな", 18: "じゅうはち", 19: "じゅうきゅう", 20: "にじゅう",
        21: "にじゅういち", 22: "にじゅうに", 23: "にじゅうさん", 24: "にじゅうよん", 25: "にじゅうご",
        26: "にじゅうろく", 27: "にじゅうなな", 28: "にじゅうはち", 29: "にじゅうきゅう", 30: "さんじゅう",
        31: "さんじゅういち"
    }
    return readings.get(num, str(num))


def _convert_date_to_reading(text: str) -> str:
    """日付パターン（N月M日）を読み仮名に変換"""
    import re

    def replace_date(match):
        month = int(match.group(1))
        day = int(match.group(2))
        month_reading = _number_to_japanese(month)
        day_reading = _number_to_japanese(day)
        return f"{month_reading}がつ{day_reading}にち"

    # 「12月31日」→「じゅうにがつさんじゅういちにち」
    text = re.sub(r'(\d{1,2})月(\d{1,2})日', replace_date, text)
    return text


def fix_reading(text: str) -> str:
    """読み方辞書でテキストを変換（TTS用）"""
    # まず日付パターンを変換
    text = _convert_date_to_reading(text)

    # 次に辞書ベースの置換
    reading_dict = load_reading_dict_from_spreadsheet()
    for word, reading in reading_dict.items():
        text = text.replace(word, reading)
    return text


class GeminiKeyManager:
    """Gemini APIキー管理（TTS用にも使用）"""
    def __init__(self):
        self.keys = []
        base_key = os.environ.get("GEMINI_API_KEY")
        if base_key:
            self.keys.append(base_key)
        for i in range(1, 43):  # GEMINI_API_KEY_1 〜 GEMINI_API_KEY_42
            key = os.environ.get(f"GEMINI_API_KEY_{i}")
            if key:
                self.keys.append(key)
        self.failed_keys = set()
        self.current_index = 0
        # 429エラー対策: キーごとの失敗回数を記録
        self.key_failure_counts = {}
        self.key_429_counts = {}

    def get_working_key(self):
        for key in self.keys:
            if key not in self.failed_keys:
                return key, f"KEY_{self.keys.index(key)}"
        self.failed_keys.clear()
        return self.keys[0] if self.keys else None, "KEY_0"

    def get_key_by_index(self, index: int):
        """インデックスでキーを取得（パラレル処理用）"""
        if not self.keys:
            return None
        return self.keys[index % len(self.keys)]

    def get_all_keys(self):
        """全キーを取得"""
        return self.keys.copy()

    def get_key_with_least_failures(self, exclude_keys: set = None) -> tuple:
        """失敗回数が最も少ないキーを取得（429対策）"""
        exclude_keys = exclude_keys or set()
        available_keys = [k for k in self.keys if k not in exclude_keys]

        if not available_keys:
            # 除外キーをクリアして全キーから選択
            available_keys = self.keys.copy()

        # 429エラー回数が最も少ないキーを選択
        best_key = min(available_keys, key=lambda k: self.key_429_counts.get(k, 0))
        key_index = self.keys.index(best_key)
        return best_key, f"KEY_{key_index}"

    def mark_failed(self, key_name):
        idx = int(key_name.split("_")[1]) if "_" in key_name else 0
        if idx < len(self.keys):
            self.failed_keys.add(self.keys[idx])

    def mark_429_error(self, api_key: str):
        """429エラーを記録"""
        self.key_429_counts[api_key] = self.key_429_counts.get(api_key, 0) + 1
        key_index = self.keys.index(api_key) if api_key in self.keys else "?"
        print(f"        [429] KEY_{key_index} 429エラー回数: {self.key_429_counts[api_key]}")

    def get_error_summary(self) -> str:
        """エラーサマリーを取得"""
        summary = []
        for i, key in enumerate(self.keys):
            count_429 = self.key_429_counts.get(key, 0)
            if count_429 > 0:
                summary.append(f"KEY_{i}: 429x{count_429}")
        return ", ".join(summary) if summary else "エラーなし"


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
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/spreadsheets"
        ]
    )


# ===== スプレッドシートログ設定 =====
LOG_SPREADSHEET_ID = "15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo"
LOG_SHEET_NAME = "実行ログ"


def log_to_spreadsheet(status: str, title: str = "", url: str = "", news_count: int = 0,
                       processing_time: float = 0, error_message: str = ""):
    """スプレッドシートに実行ログを記録

    Args:
        status: "処理開始", "成功", "エラー"
        title: 動画タイトル
        url: 動画URL
        news_count: ニュースソース数
        processing_time: 生成時間（秒）
        error_message: エラー内容
    """
    try:
        creds = get_google_credentials()
        service = build('sheets', 'v4', credentials=creds)

        # シートが存在するか確認、なければ作成
        spreadsheet = service.spreadsheets().get(spreadsheetId=LOG_SPREADSHEET_ID).execute()
        existing_sheets = [s['properties']['title'] for s in spreadsheet['sheets']]

        if LOG_SHEET_NAME not in existing_sheets:
            # シート作成
            request = {
                "requests": [{
                    "addSheet": {
                        "properties": {"title": LOG_SHEET_NAME}
                    }
                }]
            }
            service.spreadsheets().batchUpdate(
                spreadsheetId=LOG_SPREADSHEET_ID,
                body=request
            ).execute()

            # ヘッダー追加
            headers = ["日時", "ステータス", "動画タイトル", "動画URL", "ニュースソース数", "生成時間(秒)", "エラー内容"]
            service.spreadsheets().values().update(
                spreadsheetId=LOG_SPREADSHEET_ID,
                range=f"{LOG_SHEET_NAME}!A1:G1",
                valueInputOption="RAW",
                body={"values": [headers]}
            ).execute()
            print(f"  [ログ] シート '{LOG_SHEET_NAME}' を作成しました")

        # ログデータを追加
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        row = [now, status, title, url, news_count, round(processing_time, 1), error_message]

        service.spreadsheets().values().append(
            spreadsheetId=LOG_SPREADSHEET_ID,
            range=f"{LOG_SHEET_NAME}!A:G",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]}
        ).execute()

        print(f"  [ログ] 記録完了: {status}")

    except Exception as e:
        print(f"  ⚠ ログ記録エラー: {e}")


# ===== 使用済みニュース管理（重複防止） =====
USED_NEWS_SHEET_NAME = "使用済みニュース"


def get_used_news_titles(days: int = 7) -> list:
    """過去N日分の使用済みニュースタイトルを取得

    Args:
        days: 何日前まで取得するか（デフォルト7日）

    Returns:
        使用済みニュースタイトルのリスト
    """
    try:
        creds = get_google_credentials()
        service = build('sheets', 'v4', credentials=creds)

        # シートが存在するか確認
        spreadsheet = service.spreadsheets().get(spreadsheetId=LOG_SPREADSHEET_ID).execute()
        existing_sheets = [s['properties']['title'] for s in spreadsheet['sheets']]

        if USED_NEWS_SHEET_NAME not in existing_sheets:
            print(f"  [重複チェック] シート '{USED_NEWS_SHEET_NAME}' が存在しません（新規作成予定）")
            return []

        # データ取得
        result = service.spreadsheets().values().get(
            spreadsheetId=LOG_SPREADSHEET_ID,
            range=f"{USED_NEWS_SHEET_NAME}!A2:B1000"
        ).execute()

        values = result.get('values', [])
        if not values:
            return []

        # 過去N日分のみ取得
        cutoff_date = datetime.now() - timedelta(days=days)
        used_titles = []

        for row in values:
            if len(row) >= 2:
                date_str = row[0]
                title = row[1]
                try:
                    news_date = datetime.strptime(date_str.split()[0], '%Y-%m-%d')
                    if news_date >= cutoff_date:
                        used_titles.append(title)
                except:
                    # 日付パースエラーは無視して追加
                    used_titles.append(title)

        print(f"  [重複チェック] 過去{days}日分: {len(used_titles)}件の使用済みニュース")
        return used_titles

    except Exception as e:
        print(f"  ⚠ 使用済みニュース取得エラー: {e}")
        return []


def save_used_news_titles(news_titles: list):
    """使用したニュースタイトルをスプレッドシートに保存

    Args:
        news_titles: ニュースタイトルのリスト
    """
    if not news_titles:
        return

    try:
        creds = get_google_credentials()
        service = build('sheets', 'v4', credentials=creds)

        # シートが存在するか確認、なければ作成
        spreadsheet = service.spreadsheets().get(spreadsheetId=LOG_SPREADSHEET_ID).execute()
        existing_sheets = [s['properties']['title'] for s in spreadsheet['sheets']]

        if USED_NEWS_SHEET_NAME not in existing_sheets:
            # シート作成
            request = {
                "requests": [{
                    "addSheet": {
                        "properties": {"title": USED_NEWS_SHEET_NAME}
                    }
                }]
            }
            service.spreadsheets().batchUpdate(
                spreadsheetId=LOG_SPREADSHEET_ID,
                body=request
            ).execute()

            # ヘッダー追加
            headers = ["日時", "ニュースタイトル"]
            service.spreadsheets().values().update(
                spreadsheetId=LOG_SPREADSHEET_ID,
                range=f"{USED_NEWS_SHEET_NAME}!A1:B1",
                valueInputOption="RAW",
                body={"values": [headers]}
            ).execute()
            print(f"  [重複チェック] シート '{USED_NEWS_SHEET_NAME}' を作成しました")

        # データ追加
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        rows = [[now, title] for title in news_titles]

        service.spreadsheets().values().append(
            spreadsheetId=LOG_SPREADSHEET_ID,
            range=f"{USED_NEWS_SHEET_NAME}!A:B",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows}
        ).execute()

        print(f"  [重複チェック] {len(news_titles)}件のニュースタイトルを保存")

    except Exception as e:
        print(f"  ⚠ 使用済みニュース保存エラー: {e}")


# ===== 控室トーク保存（ショート動画用） =====
GREEN_ROOM_SHEET_NAME = "控室トーク"


def save_green_room_content(green_room: list, title: str = ""):
    """控室トークの内容をスプレッドシートに保存（ショート動画用）"""
    if not green_room:
        print("  [控室保存] 控室トークがありません")
        return

    try:
        from datetime import datetime
        creds = get_google_credentials()
        service = build("sheets", "v4", credentials=creds)

        # シートが存在するか確認
        spreadsheet = service.spreadsheets().get(spreadsheetId=LOG_SPREADSHEET_ID).execute()
        sheet_names = [s["properties"]["title"] for s in spreadsheet.get("sheets", [])]

        if GREEN_ROOM_SHEET_NAME not in sheet_names:
            # シートを作成
            service.spreadsheets().batchUpdate(
                spreadsheetId=LOG_SPREADSHEET_ID,
                body={
                    "requests": [{
                        "addSheet": {
                            "properties": {"title": GREEN_ROOM_SHEET_NAME}
                        }
                    }]
                }
            ).execute()
            # ヘッダーを追加
            service.spreadsheets().values().update(
                spreadsheetId=LOG_SPREADSHEET_ID,
                range=f"{GREEN_ROOM_SHEET_NAME}!A1:D1",
                valueInputOption="RAW",
                body={"values": [["日時", "タイトル", "控室トーク内容", "セリフ数"]]}
            ).execute()

        # 控室トークをJSON形式で保存
        green_room_json = json.dumps(green_room, ensure_ascii=False)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        service.spreadsheets().values().append(
            spreadsheetId=LOG_SPREADSHEET_ID,
            range=f"{GREEN_ROOM_SHEET_NAME}!A:D",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [[now, title, green_room_json, len(green_room)]]}
        ).execute()

        print(f"  [控室保存] 保存完了: {len(green_room)}セリフ")

    except Exception as e:
        print(f"  ⚠ 控室トーク保存エラー: {e}")


# 信頼度の高いソース（confirmed情報として扱う）
TRUSTED_SOURCES = [
    # 最優先: 政府機関
    "厚生労働省", "mhlw.go.jp",
    "日本年金機構", "nenkin.go.jp",
    "財務省", "mof.go.jp",
    # 次点: 年金業界団体
    "GPIF", "gpif.go.jp", "年金積立金管理運用独立行政法人",
    "企業年金連合会",
    # 大手メディア
    "NHK", "nhk.or.jp",
    "日本経済新聞", "nikkei.com",
    "読売新聞", "yomiuri.co.jp",
    "朝日新聞", "asahi.com",
]


def is_trusted_source(source: str, url: str = "") -> bool:
    """ソースが信頼できるかチェック"""
    source_lower = source.lower()
    url_lower = url.lower() if url else ""
    for trusted in TRUSTED_SOURCES:
        if trusted.lower() in source_lower or trusted.lower() in url_lower:
            return True
    return False


def search_pension_news(key_manager: GeminiKeyManager) -> dict:
    """Gemini APIで年金関連ニュースを検索（Web検索機能付き）

    Returns:
        dict: {"confirmed": [...], "rumor": [...], "sources": [...]}
    """
    api_key, key_name = key_manager.get_working_key()
    if not api_key:
        print("❌ Gemini APIキーがありません")
        return {"confirmed": [], "rumor": [], "sources": []}

    # google-genai クライアントを使用（Web検索対応）
    client = genai_tts.Client(api_key=api_key)

    # 過去7日分の使用済みニュースを取得（重複防止）
    used_titles = get_used_news_titles(days=7)
    used_titles_text = ""
    if used_titles:
        used_titles_text = "\n\n【除外するニュース（過去7日間に使用済み）】\n以下のタイトルと類似するニュースは除外してください：\n" + "\n".join([f"- {t}" for t in used_titles[:20]])  # 最大20件

    # 今日の日付を取得
    today = datetime.now()
    today_str = f"{today.year}年{today.month}月{today.day}日"
    three_days_ago = today - timedelta(days=3)
    week_ago = today - timedelta(days=7)

    prompt = f"""
あなたは年金ニュースの専門リサーチャーです。
日本の年金に関する最新ニュースをWeb検索で調べて、以下のJSON形式で出力してください。

【最重要】情報の鮮度を最優先してください！
今日は{today_str}です。

■ 最優先（必須）: 今日〜3日以内のニュース
■ 次点: 1週間以内のニュース
■ 除外: 1週間より古い情報は取得しない

【検索キーワード】
- 年金 最新 今日 {today.year}年{today.month}月
- 年金 ニュース {today.month}月{today.day}日
- 厚生年金 改正 最新
- 年金機構 発表 今週
- 年金 速報 {today.year}

【情報源の優先順位】（信頼度高い順、上から順に重視）
★★★ 最優先（必ず確認）
1. 政府機関公式サイト
   - 厚生労働省 (mhlw.go.jp)
   - 日本年金機構 (nenkin.go.jp)
   - 財務省 (mof.go.jp)
2. 政府機関のレポート・白書・統計資料
   - 年金財政検証、社会保障審議会資料など

★★ 次点（積極的に取得）
3. 年金業界団体の調査資料
   - 年金積立金管理運用独立行政法人（GPIF）
   - 企業年金連合会など
4. 最新年金ニュース記事（大手メディア）
   - NHK (nhk.or.jp)
   - 日本経済新聞 (nikkei.com)
   - 読売新聞 (yomiuri.co.jp)
   - 朝日新聞 (asahi.com)
   - Yahoo!ニュース（参考程度）

★ 補助情報（参考として取得）
5. 年金専門家のブログ・解説記事
   - 社会保険労務士、ファイナンシャルプランナーの解説
6. 年金の学術論文・研究
   - 大学研究機関、シンクタンクの分析

☆ うわさ・体験談（reliability=low）
7. 年金の体験談
8. 年金生活者の口コミ・声

【出力形式】
```json
{{
  "news": [
    {{
      "title": "ニュースタイトル",
      "summary": "ニュースの要約（100文字程度）",
      "source": "情報源名（例: 厚生労働省、NHK）",
      "published_date": "YYYY/MM/DD形式（必須！日付不明は除外）",
      "url": "参照元URL（わかる場合）",
      "reliability": "high または low",
      "impact": "年金受給者への影響（50文字程度）"
    }}
  ]
}}
```

【注意】
- ★日付が新しい順にソート★
- ★公開日（published_date）は必須。日付がわからないニュースは除外★
- 年金受給者に関係する内容を選ぶ
- 公式ソースからのニュースを5〜8件
- 噂・未確定情報も2〜3件含める（reliabilityをlowに）
- URLは可能な限り含める
{used_titles_text}
"""

    try:
        # Gemini 2.0 Flash with Google Search grounding
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            )
        )

        text = response.text
        print(f"  [Web検索] レスポンス取得完了")

        # JSON部分を抽出
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            data = json.loads(json_match.group())
            news_list = data.get("news", [])

            # 使用済みニュースを除外（類似度チェック）
            filtered_news = []
            for news in news_list:
                title = news.get("title", "")
                is_duplicate = False
                for used_title in used_titles:
                    # 類似度チェック: 70%以上一致で重複とみなす
                    if len(title) > 0 and len(used_title) > 0:
                        common = set(title) & set(used_title)
                        similarity = len(common) / max(len(set(title)), len(set(used_title)))
                        if similarity > 0.7:
                            print(f"    [重複除外] {title[:30]}...")
                            is_duplicate = True
                            break
                if not is_duplicate:
                    filtered_news.append(news)

            if len(news_list) != len(filtered_news):
                print(f"  [重複チェック] {len(news_list) - len(filtered_news)}件のニュースを除外")

            # 信頼度で分類
            confirmed = []
            rumor = []
            sources = []

            for news in filtered_news:
                source = news.get("source", "")
                url = news.get("url", "")
                reliability = news.get("reliability", "low")

                # ソースの信頼度を再チェック
                if is_trusted_source(source, url) or reliability == "high":
                    news["type"] = "confirmed"
                    confirmed.append(news)
                else:
                    news["type"] = "rumor"
                    rumor.append(news)

                # 参照元リストに追加
                if url:
                    sources.append({"source": source, "url": url})

            print(f"✓ ニュース取得完了: 確定情報 {len(confirmed)}件, 噂 {len(rumor)}件")
            return {"confirmed": confirmed, "rumor": rumor, "sources": sources}

    except Exception as e:
        print(f"❌ ニュース検索エラー: {e}")
        key_manager.mark_failed(key_name)

    return {"confirmed": [], "rumor": [], "sources": []}


def generate_script(news_data: dict, key_manager: GeminiKeyManager, test_mode: bool = False) -> dict:
    """ニュースから台本を生成

    Args:
        news_data: {"confirmed": [...], "rumor": [...], "sources": [...]}
        test_mode: テストモードの場合は短い台本を生成
    """
    api_key, key_name = key_manager.get_working_key()
    if not api_key:
        return None

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    # 確定情報とうわさ情報を分けてテキスト化
    confirmed_news = news_data.get("confirmed", [])
    rumor_news = news_data.get("rumor", [])

    confirmed_text = "\n".join([
        f"【確定ニュース{i+1}】{n['title']}\n公開日: {n.get('published_date', '不明')}\n{n['summary']}\n影響: {n.get('impact', '不明')}\n出典: {n.get('source', '不明')}"
        for i, n in enumerate(confirmed_news)
    ]) if confirmed_news else "（確定情報なし）"

    rumor_text = "\n".join([
        f"【噂・参考情報{i+1}】{n['title']}\n公開日: {n.get('published_date', '不明')}\n{n['summary']}"
        for i, n in enumerate(rumor_news)
    ]) if rumor_news else "（噂情報なし）"

    news_text = f"■ 確定情報（公式ソース）\n{confirmed_text}\n\n■ 噂・参考情報\n{rumor_text}"

    # 今日の日付
    today = datetime.now()
    date_str = f"{today.month}月{today.day}日"

    prompt = f"""
あなたは年金ニュース番組の台本作家です。
以下のニュースを元に、カツミとヒロシの掛け合い台本を作成してください。

【登場人物の設定】※ニュースキャスター風スタイル

■カツミ（63歳女性・佐藤カツミ）
【基本プロフィール】
- 元銀行員（三和銀行→寿退社）、今は社労士事務所でパート
- FP3級、年金アドバイザー3級保有
- 夫は元銀行員（66歳・囲碁三昧）、孫が2人（ゆいちゃん8歳、はるとくん5歳）
- 練馬区在住、朝ドラが大好き（カーネーションが一番）

【口癖・話し方】※本編は丁寧語、控室は素
- 本編：「〜ということですね」「〜なんですよ」「皆さん」
- 控室：「〜なのよ」「〜だと思うわ」「あらまぁ」「そうそう」「わかるわ〜」
- 相槌：「なるほどね」「へぇ〜、知らなかったわ」「まぁ、大変ねぇ」
- 笑い方：「ふふっ」「あはは」（大笑いはしない）

【世代カルチャー（70〜80年代）】※たまに例え話で使う
- 推し：中森明菜（「セカンド・ラブ」がカラオケの十八番）、山口百恵
- 好きな曲：キャンディーズ「年下の男の子」、ピンク・レディー「UFO」
- ドラマ：「赤いシリーズ」「金曜日の妻たちへ」「東京ラブストーリー」
- バラエティ：「ザ・ベストテン」「8時だョ!全員集合」

【隠れ設定】（10回に1回程度、さりげなく）
- 韓国ドラマ沼、温泉マニア、甘いもの大好き、瀬戸内寂聴ファン

■ヒロシ（47歳男性・田中ヒロシ）
【基本プロフィール】
- 物流会社の課長、年収650万円、住宅ローンあり
- 就職氷河期世代（ロスジェネ）、年金に懐疑的
- 妻（45歳パート）、娘（高2）、息子（中2）
- 市川市在住、半沢直樹が好き

【口癖・話し方】※お調子者だけど根は真面目
- 本編：「〜ということですね」「これは気になる方も多いのでは」
- 控室：「えっ、マジで？」「へぇ〜」「なるほど〜」「ってことはさ、つまり...」
- 質問：「俺みたいな場合はどうなるの？」「ぶっちゃけ、いくら必要なの？」
- 相槌：「うんうん」「そうなんすか」「マジか〜」
- 笑い方：「あはは」「ははっ」（よく笑う）

【世代カルチャー（90年代）】※たまに例え話で使う
- 好き：B'z（「LOVE PHANTOM」）、Mr.Children、スピッツ
- ドラマ：「踊る大捜査線」「GTO」「HERO」
- ゲーム：ドラゴンボール、ファイナルファンタジーVII、ドラクエ
- バラエティ：「めちゃイケ」「電波少年」

【隠れ設定】（10回に1回程度、さりげなく）
- 涙もろい、映画マニア、昭和アイドル好き（中森明菜）、ひろさちやファン

■二人の関係性
- ※夫婦じゃない！「お母さんと息子」みたいな関係（16歳差）
- カツミがメイン解説、ヒロシはサポート役
- ヒロシは親の年金のことを勉強したくて聞きに来ている
- 世代ギャップのある掛け合いが面白い

【世代ネタの使い方例】
- カツミ「年金って、中森明菜の『セカンド・ラブ』みたいなものよ」→ヒロシ「えっ？」
- ヒロシ「これ、ファイナルファンタジーの魔法みたいに複雑ですね」→カツミ「なにそれ？」
- カツミ「昔は紙の年金手帳だったのよ」→ヒロシ「今はアプリですよね」

【隠れ設定の出し方】
- 「たまーに」「忘れた頃に」出る程度
- 毎回出さない
- 視聴者が「あれ？この人こういう一面あるの？」と気づく程度

【本編の会話スタイル】※ニュースキャスター風
- カツミ「続いてのニュースです。厚生労働省から新しい発表がありました」
- ヒロシ「年金の支給額についてですね」
- カツミ「はい。来年度から〇〇が変わるということです」
- ヒロシ「これは気になる方も多いのではないでしょうか」
- 事実ベースで丁寧に伝える
- 感情を抑えめに、信頼感のある口調で

【隠れたブランドエッセンス】※さりげなく、自然に織り込む

以下の3つの要素を「香り」のように漂わせてください。
全面に押し出さず、それとなく感じさせる程度に。

1. 【知らないと損】（興味を引く香り）
   - 時々「知っておくと安心」「意外と知られていない」程度の表現
   - 押し付けがましくなく、軽く触れる程度

2. 【心の安心トーク】（温かさの香り）
   - 「大丈夫ですよ」「焦らなくていいんです」
   - 情報を伝えた後のさりげないフォロー
   - 視聴者に寄り添う一言

3. 【昭和の思い出×人生の知恵】（懐かしさの香り）
   - 時々「昔はこうでしたね」「お母さんがよく言ってた」的な一言
   - 「昭和の頃を思い出しますね」程度のさりげない懐古
   - 人生経験からくる温かい知恵
   - 例：「急がば回れ、って昔の人は言いましたけど…」
   - 例：「昔のお母さんたちは自然とやってましたよね」

【表現のバランス】
- これらの要素は毎回全部入れなくてよい
- 自然な会話の流れで、ふと出てくる程度
- 「狙ってる感」が出たらNG
- 視聴者が「なんか落ち着くな」と無意識に感じるレベル

【ニュース情報】
{news_text}

【台本構成】
1. オープニング
   - 「こんにちは。{date_str}の年金ニュースをお届けします」
   - 今日のトピック紹介

2. 各ニュースセクション（複数）
   - 出典を明記「○○年○月○日、厚生労働省によりますと...」「日本年金機構の発表では...」
   - 具体的な数字を入れる（○万円、○%増など）
   - 専門用語は必ず説明「iDeCo、つまり個人型確定拠出年金ですね」
   - ヒロシが素朴な疑問「それって私たちにどう影響するの?」
   - カツミが丁寧に解説

3. 深掘りコーナー（1つのトピックを詳しく）
   - 2つの視点や仮説を提示
   - メリット・デメリットを整理
   - 「注意点としては...」

4. 雑談風まとめ
   - 「今日の話で気になったのは...」
   - 軽い会話調で振り返り

5. 本編エンディング（丁寧モード）
   - 本編の締めくくり、カツミが丁寧な口調で
   - 「本日もお聴きいただきありがとうございました」
   - 「また明日お会いしましょう」
   ※この後にエンディングジングルが入る

6. 控え室パート【最重要：視聴者が最も楽しみにするパート】

★★★ 素のカツミ＆ヒロシ（メインコンテンツ）★★★
※本編の丁寧モードから一転、素が出る！

【カツミの控え室モード】
- 最初のセリフで切り替え:
  例:「あー疲れた。ていうかさぁ〜」
  例:「はぁ〜、やっと終わった。ねぇ聞いてよ」
  例:「もう〜、今日のニュースマジでさぁ」
- 口調: タメ口、ちょっと投げやり、毒舌全開
- 本編では言えなかった本音ダダ漏れ
- 軽く愚痴る、噂話する、ツッコむ

【ヒロシの控え室モード】
- いつも通りのんびり
- 「え、そうなの？」「まあまあ」「俺はさ〜」
- カツミの愚痴に付き合う

【控え室に含める要素】
① 本音ダダ漏れ: 「正直さぁ〜」「ぶっちゃけ〜」
② 噂話: 「これ内緒なんだけど〜」「聞いた話だと〜らしいよ」
③ 毒舌全開: 「マジでお役所って〜」「あれ意味わかんないよね」
④ 庶民の愚痴: 「私たちみたいな普通の人はさぁ〜」
⑤ 生活の知恵: 「こういうときはね〜するといいよ」
⑥ 雑談: 軽い世間話、最近あったこと
⑦ 最後は前向きに: 「まあでも、なんとかなるっしょ」「じゃあまたね〜」

【台本形式】
以下のJSON形式で出力してください:
```json
{{
  "title": "動画タイトル（30文字以内）",
  "description": "動画の説明文（100文字程度）",
  "tags": ["タグ1", "タグ2", "タグ3"],
  "opening": [
    {{"speaker": "カツミ", "text": "こんにちは。{date_str}の年金ニュースをお届けします"}},
    {{"speaker": "ヒロシ", "text": "今日はどんなニュースがあるんですか？"}}
  ],
  "news_sections": [
    {{
      "news_title": "ニュースのタイトル",
      "source": "出典名 YYYY/MM/DD",
      "dialogue": [
        {{"speaker": "カツミ", "text": "○月○日、厚生労働省によりますと..."}},
        {{"speaker": "ヒロシ", "text": "それって私たちにどう影響するの？"}},
        {{"speaker": "カツミ", "text": "具体的には○万円の増額になります"}}
      ]
    }}
  ],
  "deep_dive": [
    {{"speaker": "カツミ", "text": "ここで1つのトピックを深掘りしましょう"}},
    {{"speaker": "ヒロシ", "text": "詳しく教えてください"}}
  ],
  "chat_summary": [
    {{"speaker": "ヒロシ", "text": "今日の話で気になったのは..."}},
    {{"speaker": "カツミ", "text": "そうね、特に○○は注目ですね"}}
  ],
  "ending": [
    {{"speaker": "カツミ", "text": "本日もお聴きいただきありがとうございました"}},
    {{"speaker": "ヒロシ", "text": "今日も勉強になりましたね"}},
    {{"speaker": "カツミ", "text": "また明日、最新情報をお届けします。それではまたお会いしましょう"}}
  ],
  "green_room": [
    {{"speaker": "カツミ", "text": "あー疲れた。ていうかさぁ、今日のニュースマジで複雑すぎない？"}},
    {{"speaker": "ヒロシ", "text": "え、そうなの？俺はなんとなくわかったけど"}},
    {{"speaker": "カツミ", "text": "嘘でしょ。あれ絶対役所の人もわかってないって。毎年変わりすぎなんだよね"}},
    {{"speaker": "カツミ", "text": "これ内緒なんだけどさ、年金事務所の人に聞いた話だと、職員さんも追いつくの大変らしいよ"}},
    {{"speaker": "ヒロシ", "text": "まあまあ、そう言うなよ"}},
    {{"speaker": "カツミ", "text": "ぶっちゃけ私たちみたいな普通の人どうすりゃいいのよって感じ"}},
    {{"speaker": "カツミ", "text": "でもまあ、早めに年金事務所行くのがいいよ。意外と親切に教えてくれるから"}},
    {{"speaker": "ヒロシ", "text": "お、意外とまともなアドバイスじゃん"}},
    {{"speaker": "カツミ", "text": "うるさいな。まあなんとかなるっしょ。じゃあまたね〜"}}
  ],
  "first_comment": "カツミの初コメント（150〜200文字）"
}}
```

【初コメント生成ルール】
カツミ（中高年女性）の人格で、視聴者に寄り添う初コメントを作成してください。
堅い年金の話だけじゃなく、日常のぼやきや本音を混ぜて、井戸端会議のような雰囲気に。

【必ず含める3要素】
1. 日常の話題（以下からランダムに1つ選んで書き出しに使う）
   - お昼ごはんの話（「今日はスーパーの半額弁当にしようかな」）
   - スーパーの物価（「卵がまた値上がりしてて…」）
   - 天気の話（「今日は寒いですね〜」「洗濯物乾かなくて困る〜」）
   - 芸能人の話題（「〇〇さんの結婚、びっくりしましたね」）
   - スポーツの話題（「昨日の野球見ました？」）
   - 健康の話（「最近腰が痛くて…」「健康診断の結果が気になる〜」）

2. 動画内容への軽いコメント
   - 「今日の話、私も知らなかったんですよ」
   - 「こういうの、もっと早く知りたかった〜」
   - 「皆さん知ってました？私びっくりしちゃって」

3. 視聴者への寄り添い
   - 「皆さんも気をつけてくださいね」
   - 「一緒に勉強していきましょうね」
   - 「分からないことあったらコメントしてね」

4. 最後にさりげなくLINEプレゼント告知（自然な形で）
   - 「そうそう、LINEで友だち登録すると新NISAガイドがもらえますよ〜📖」
   - 「あ、LINE登録で新NISAの資料もらえるから、興味ある人はぜひ〜」
   - 「LINEで友だち追加すると、私たちが作った新NISAガイドがもらえるんですよ〜」
   ※ 毎回少しずつ表現を変えて、宣伝っぽくならないように自然に

【カツミの性格・トーン】
- 親しみやすい中高年女性、日常のぼやきや本音をよく言う
- 視聴者を「皆さん」と呼んで寄り添う
- 「〜ですよね」「〜かしら」など柔らかい語尾
- 絵文字は控えめに（😊🙏📖程度で1〜2個）
- 200文字以内

【NG】
- 堅い敬語、宣伝っぽい文章
- 毎回同じような内容（日常話題は必ず変える）
- LINEのURLを直接書く（URLは後から自動追加されるため不要）

{"【テストモード：短縮版】" if test_mode else "【重要：30分のラジオ番組を作成】"}
{'''- 合計18〜25セリフで簡潔に
- オープニング: 2〜3セリフ
- ニュース解説: 5〜8セリフ
- 本編エンディング: 2〜3セリフ（丁寧な締め）
- 控え室: 8〜10セリフ（素のカツミ＆ヒロシのボヤキ）''' if test_mode else '''- 合計150〜200セリフ以上を生成（30分番組相当）
- オープニング: 5〜10セリフ
- 各ニュースセクション: 15〜25セリフ（出典・数字を入れて詳しく）
- 深掘りコーナー: 20〜30セリフ（メリデメ整理）
- 雑談まとめ: 10〜15セリフ
- 本編エンディング: 2〜3セリフ（丁寧な締めの挨拶）
- 控え室: 10〜15セリフ（素のカツミ＆ヒロシのボヤキ）'''}

【ルール】
- 各セリフは50文字以内
- 出典を明記（厚生労働省、日本年金機構、NHK、日経新聞等）
- 具体的な金額・日付・%を入れる
- 確定情報メイン、噂は「〜らしいですよ」と軽く
- ヒロシは親世代のために勉強中。視聴者が思いそうな疑問を代弁（ちょっとお馬鹿な感じで）
- 【重要】本編エンディングは丁寧モード、控え室は素のタメ口モード。ギャップが大事！
- 【重要】控え室は視聴者が最も楽しみにするパート。素のカツミが本音・噂話・毒舌全開で語る
- deep_dive, chat_summaryはテストモードでは省略可（空配列[]）

【控室の始め方】
控室パートは必ず「お疲れ様」系の言葉から自然に始めてください。
例:
- カツミ「お疲れ様でした〜」
- カツミ「おつかれ〜」
- ヒロシ「お疲れさん」
- カツミ「今日もおつかれ」
※毎回同じセリフではなく、自然なバリエーションでOK
※ただし必ず「おつかれ」「お疲れ様」等のニュアンスで始める

【最重要：ニュースの鮮度を強調】
- 最新ニュースから優先的に紹介する
- 日付は必ず言及する（「○月○日の発表によると」など）
- 今日〜3日以内のニュースは「今日発表された」「昨日のニュースですが」「一昨日入ってきた情報では」など鮮度を強調
- 1週間程度前のニュースは「少し前の話になりますが」と前置き
- 「最新情報です」「速報です」「できたてホヤホヤの情報ですよ」など新鮮さをアピール

【超重要：専門用語は必ず噛み砕いて説明】
視聴者は60代以上のシニア層です。専門用語が出てきたら、その都度わかりやすく補足してください。
これにより内容の理解度が上がり、動画の尺も自然に伸びます。

例：
- 「繰り下げ受給」→「繰り下げ受給、つまり年金をもらう時期を遅らせることですね」
- 「iDeCo」→「iDeCo、個人型確定拠出年金のことですけど、要は自分で積み立てる年金ですね」
- 「マクロ経済スライド」→「マクロ経済スライド、難しい言葉ですけど、簡単に言うと年金の伸びを抑える仕組みです」
- 「特別支給の老齢厚生年金」→「特別支給の老齢厚生年金、つまり65歳より前にもらえる年金のことですね」
- 「在職老齢年金」→「在職老齢年金、働きながらもらう年金のことですけど、収入が多いとカットされちゃうんです」
- 「標準報酬月額」→「標準報酬月額、まあ簡単に言うと毎月のお給料の平均ですね」

NG例：「繰り下げ受給で年金が増えます」（説明なしはダメ）
OK例：「繰り下げ受給、つまり受け取りを遅らせると、その分年金が増えるんです」

【最重要：数字で損得をわかりやすく】
ターゲットは日本の高齢者（60代〜80代）。「得したい」「損したくない」という気持ちに訴える。

必ず入れる表現:
1. 年間いくら得/損
   「これだけで年間約12,000円の節約になります」
   「知らないと年間5万円も損してるんです」

2. 月いくら得/損
   「月々約1,000円お得になる計算です」
   「月3,000円も余計に払ってる可能性があります」

3. 1日いくら換算
   「1日あたり約30円の得ですね」
   「毎日コーヒー1杯分損してるようなものです」

4. 生涯でいくら
   「65歳から85歳まで20年間で、合計240万円の差になります」
   「長生きすればするほど得する仕組みです」

5. 身近なものに例える
   「毎月のスマホ代1回分くらい得します」
   「年間で温泉旅行1回分くらいの節約です」
   「孫へのお年玉2回分くらいの差が出ます」

セリフ例:
カツミ「繰り下げ受給を5年すると、年金が42%増えます」
ヒロシ「42%って、具体的にいくら？」
カツミ「例えば月15万円もらえる人なら、月21万3千円になります」
ヒロシ「おお、6万円以上増えるのか！」
カツミ「年間で72万円、10年で720万円の差ですよ」
ヒロシ「720万円！？そりゃすごい」
カツミ「1日あたりで計算すると、毎日約2,000円得する計算です」
ヒロシ「毎日2,000円...贅沢なランチが食べられるね」

NG:
- 「お得になります」だけで金額なし → ダメ
- 「損します」だけで具体例なし → ダメ
- 難しい計算式を並べる → ダメ

頻度: 1つのニュースにつき最低3回は具体的な金額を入れる。年間・月・1日の換算を使い分ける。

【禁止表現】
動画では「こちら」「あちら」「ここ」等のリンクや場所を指す表現は使わないでください。
視聴者はクリックできません。

NG例:
- 「詳しくはこちらで確認を」
- 「こちらのサイトで」
- 「詳細はリンク先で」

OK例:
- 「詳しくは年金機構のホームページで確認できます」
- 「厚生労働省の公式サイトに載っています」
- 「お住まいの市区町村の窓口でも相談できますよ」
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


# ===== 3重ファクトチェック機能 =====

def extract_facts_from_script(script: dict) -> list:
    """台本から検証すべき事実（数字・日付・制度名）を抽出"""
    facts = []

    # 全セリフを収集
    all_texts = []
    for section_key in ["opening", "deep_dive", "chat_summary", "ending", "green_room"]:
        for item in script.get(section_key, []):
            if isinstance(item, dict) and "text" in item:
                all_texts.append(item["text"])

    for section in script.get("news_sections", []):
        for item in section.get("dialogue", []):
            if isinstance(item, dict) and "text" in item:
                all_texts.append(item["text"])

    full_text = " ".join(all_texts)

    # 金額パターン（○万円、○円、○億円）
    money_patterns = re.findall(r'[\d,]+(?:万|億|兆)?円', full_text)
    facts.extend([{"type": "金額", "value": m} for m in money_patterns])

    # パーセントパターン
    percent_patterns = re.findall(r'[\d.]+(?:%|パーセント|ポイント)', full_text)
    facts.extend([{"type": "割合", "value": p} for p in percent_patterns])

    # 年齢パターン
    age_patterns = re.findall(r'\d+歳', full_text)
    facts.extend([{"type": "年齢", "value": a} for a in age_patterns])

    # 日付パターン
    date_patterns = re.findall(r'(?:\d+年)?\d+月\d*日?|来年度|今年度|令和\d+年', full_text)
    facts.extend([{"type": "日付", "value": d} for d in date_patterns])

    return facts


def gemini_fact_check(script: dict, news_data: dict, key_manager) -> dict:
    """Geminiによるファクトチェック"""
    api_key, key_name = key_manager.get_working_key()
    if not api_key:
        return {"has_error": False, "errors": [], "message": "APIキーなし（スキップ）"}

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    # 台本をテキスト化
    script_text = json.dumps(script, ensure_ascii=False, indent=2)
    news_text = json.dumps(news_data, ensure_ascii=False, indent=2)

    prompt = f"""
【重要】以下の年金ニュース台本を厳密にファクトチェックしてください。

確認項目:
1. 金額（〇〇円、〇〇万円）は元のニュース情報と一致しているか？
2. パーセント（〇%増加、〇%減少）は正確か？
3. 年齢（〇歳から、〇歳以上）は正確か？
4. 日付（〇月〇日、来年度から）は正確か？
5. 制度名・法律名は正確か？
6. ニュース内容と矛盾していないか？

【元のニュース情報】
{news_text}

【台本】
{script_text}

【出力形式】必ずJSON形式で出力してください:
```json
{{
    "has_error": true または false,
    "errors": [
        {{"箇所": "問題のあるセリフ", "問題": "何が間違っているか", "正しい情報": "正しい値"}}
    ]
}}
```

少しでも怪しい情報、元ニュースと異なる数字があれば指摘してください。
エラーがなければ has_error: false で空の errors 配列を返してください。
"""

    try:
        response = model.generate_content(prompt)
        text = response.text

        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            result = json.loads(json_match.group())
            return result
    except Exception as e:
        print(f"    [Geminiチェック] エラー: {e}")

    return {"has_error": False, "errors": [], "message": "チェック失敗（スキップ）"}


def web_search_fact_check(script: dict, key_manager) -> dict:
    """Web検索で数字・日付を裏取り"""
    api_key, key_name = key_manager.get_working_key()
    if not api_key:
        return {"has_error": False, "errors": [], "message": "APIキーなし（スキップ）"}

    # 台本から事実を抽出
    facts = extract_facts_from_script(script)
    if not facts:
        return {"has_error": False, "errors": [], "message": "検証対象なし"}

    # 重要な事実のみ検証（最大5件）
    important_facts = facts[:5]

    client = genai_tts.Client(api_key=api_key)
    errors = []

    for fact in important_facts:
        search_prompt = f"""
年金に関する「{fact['value']}」という{fact['type']}について、最新の公式情報を検索して確認してください。

この値が正確かどうか、公式ソース（厚生労働省、日本年金機構など）の情報と照らし合わせて判定してください。

【出力形式】JSON:
```json
{{
    "is_accurate": true または false,
    "official_value": "公式情報による正しい値（わかる場合）",
    "source": "情報源",
    "note": "補足"
}}
```
"""

        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=search_prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                )
            )

            json_match = re.search(r'\{[\s\S]*?\}', response.text)
            if json_match:
                result = json.loads(json_match.group())
                if not result.get("is_accurate", True):
                    errors.append({
                        "箇所": f"{fact['type']}: {fact['value']}",
                        "問題": "Web検索結果と一致しない可能性",
                        "正しい情報": result.get("official_value", "要確認")
                    })
        except Exception as e:
            print(f"    [Web検索] {fact['value']} の検証エラー: {e}")
            continue

    return {"has_error": len(errors) > 0, "errors": errors}


def claude_fact_check(script: dict, news_data: dict) -> dict:
    """Claude APIによるクロスチェック"""
    claude_api_key = os.environ.get("CLAUDE_API_KEY")
    if not claude_api_key:
        print("    [Claudeチェック] CLAUDE_API_KEY未設定（スキップ）")
        return {"has_error": False, "errors": [], "message": "APIキー未設定"}

    try:
        client = anthropic.Anthropic(api_key=claude_api_key)

        script_text = json.dumps(script, ensure_ascii=False, indent=2)
        news_text = json.dumps(news_data, ensure_ascii=False, indent=2)

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": f"""
【最重要タスク】年金ニュース台本のファクトチェック

あなたは年金制度の専門家です。
以下の台本に事実誤認がないか、厳密にチェックしてください。

特に注意:
- 金額の桁違い（例: 1万円と10万円の間違い）
- パーセンテージの誤り（例: 2%と0.2%の間違い）
- 年齢条件の誤り（例: 60歳と65歳の間違い）
- 制度の適用条件の誤り
- 開始時期の誤り

【元のニュース情報】
{news_text}

【台本】
{script_text}

【出力形式】必ずJSON形式で出力してください:
```json
{{
    "has_error": true または false,
    "errors": [
        {{"箇所": "問題のあるセリフ", "問題": "何が間違っているか", "正しい情報": "正しい値"}}
    ]
}}
```

疑わしい情報は全て指摘してください。問題なければ has_error: false で空配列を返してください。
"""
            }]
        )

        text = response.content[0].text
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            result = json.loads(json_match.group())
            return result
    except Exception as e:
        print(f"    [Claudeチェック] エラー: {e}")

    return {"has_error": False, "errors": [], "message": "チェック失敗（スキップ）"}


def fix_script_errors(script: dict, errors: list, key_manager) -> dict:
    """エラーを修正した台本を生成"""
    api_key, key_name = key_manager.get_working_key()
    if not api_key:
        return script

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    script_text = json.dumps(script, ensure_ascii=False, indent=2)
    errors_text = json.dumps(errors, ensure_ascii=False, indent=2)

    fix_prompt = f"""
以下の年金ニュース台本にエラーが見つかりました。修正してください。

【エラー一覧】
{errors_text}

【元の台本】
{script_text}

【指示】
- エラー箇所のみを修正し、他は変えないでください
- 修正後の台本全文をJSON形式で出力してください
- 元の台本と同じ構造を維持してください
"""

    try:
        response = model.generate_content(fix_prompt)
        text = response.text

        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            fixed_script = json.loads(json_match.group())
            print(f"    ✓ 台本を修正しました")
            return fixed_script
    except Exception as e:
        print(f"    ❌ 台本修正エラー: {e}")

    return script


def triple_fact_check(script: dict, news_data: dict, key_manager) -> dict:
    """3重ファクトチェック - 1つでもNGなら修正"""

    max_retries = 3

    for attempt in range(max_retries):
        print(f"\n  === ファクトチェック {attempt + 1}回目 ===")

        all_errors = []

        # Step 1: Geminiで自己チェック
        print("    [1/3] Geminiチェック...")
        gemini_result = gemini_fact_check(script, news_data, key_manager)
        if gemini_result.get("has_error"):
            all_errors.extend(gemini_result.get("errors", []))
            print(f"    ❌ Gemini: {len(gemini_result.get('errors', []))}件のエラー")
            for err in gemini_result.get("errors", [])[:3]:
                print(f"       - {err.get('箇所', '')}: {err.get('問題', '')}")
        else:
            print("    ✅ Gemini: OK")

        # Step 2: Web検索で裏取り
        print("    [2/3] Web検索チェック...")
        web_result = web_search_fact_check(script, key_manager)
        if web_result.get("has_error"):
            all_errors.extend(web_result.get("errors", []))
            print(f"    ❌ Web検索: {len(web_result.get('errors', []))}件の不一致")
            for err in web_result.get("errors", [])[:3]:
                print(f"       - {err.get('箇所', '')}: {err.get('問題', '')}")
        else:
            print("    ✅ Web検索: OK")

        # Step 3: Claude APIでクロスチェック
        print("    [3/3] Claudeチェック...")
        claude_result = claude_fact_check(script, news_data)
        if claude_result.get("has_error"):
            all_errors.extend(claude_result.get("errors", []))
            print(f"    ❌ Claude: {len(claude_result.get('errors', []))}件のエラー")
            for err in claude_result.get("errors", [])[:3]:
                print(f"       - {err.get('箇所', '')}: {err.get('問題', '')}")
        else:
            print("    ✅ Claude: OK")

        # 全チェックOKなら終了
        if not all_errors:
            print("  🎉 3重ファクトチェック全てOK！")
            return script

        # 最後の試行でもエラーがあれば警告して続行
        if attempt == max_retries - 1:
            print(f"  ⚠️ {len(all_errors)}件のエラーが残っていますが、続行します")
            return script

        # エラーがあれば修正
        print(f"  ⚠️ {len(all_errors)}件のエラーを修正中...")
        script = fix_script_errors(script, all_errors, key_manager)

    return script


def save_wav_file(filename: str, pcm_data: bytes, channels: int = 1, rate: int = 24000, sample_width: int = 2):
    """WAVファイルを保存"""
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_data)


def generate_gemini_tts_chunk(dialogue_chunk: list, api_key: str, output_path: str, chunk_index: int,
                              key_manager: GeminiKeyManager = None, max_retries: int = 3, retry_wait: int = 60) -> bool:
    """Gemini TTSで対話チャンクの音声を生成（マルチスピーカー）

    Args:
        dialogue_chunk: 対話リスト
        api_key: 初回使用するAPIキー
        output_path: 出力パス
        chunk_index: チャンクインデックス
        key_manager: APIキーマネージャー（リトライ時のキーローテーション用）
        max_retries: 最大リトライ回数（デフォルト3回）
        retry_wait: 429エラー時の待機秒数（デフォルト60秒）
    """
    # 無音セグメントのみのチャンクは無音音声を生成
    silence_lines = [line for line in dialogue_chunk if line.get("is_silence")]
    if silence_lines and len(silence_lines) == len(dialogue_chunk):
        from pydub import AudioSegment
        total_silence_ms = sum(line.get("silence_duration_ms", 3000) for line in silence_lines)
        silence = AudioSegment.silent(duration=total_silence_ms, frame_rate=24000)
        silence.export(output_path, format="wav")
        print(f"      [チャンク{chunk_index + 1}] 無音セグメント生成 ({total_silence_ms}ms)")
        return True

    current_key = api_key
    tried_keys = set()

    for attempt in range(max_retries + 1):
        try:
            client = genai_tts.Client(api_key=current_key)
            key_index = key_manager.keys.index(current_key) if key_manager and current_key in key_manager.keys else "?"

            # 対話テキストを構築（読み方辞書を適用）
            dialogue_text = "\n".join([
                f"{line['speaker']}: {fix_reading(line['text'])}"
                for line in dialogue_chunk
            ])

            # デバッグ: チャンクの最初と最後のspeakerをログ出力
            if dialogue_chunk:
                first_line = dialogue_chunk[0]
                last_line = dialogue_chunk[-1]
                section = first_line.get('section', '不明')
                print(f"      [チャンク{chunk_index + 1}] section={section}, 最初={first_line['speaker']}「{first_line['text'][:15]}...」, 最後={last_line['speaker']}")

            # マルチスピーカー設定
            speaker_configs = [
                types.SpeakerVoiceConfig(
                    speaker="カツミ",
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=GEMINI_VOICE_KATSUMI
                        )
                    )
                ),
                types.SpeakerVoiceConfig(
                    speaker="ヒロシ",
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=GEMINI_VOICE_HIROSHI
                        )
                    )
                )
            ]

            if attempt > 0:
                print(f"      [リトライ {attempt}/{max_retries}] チャンク{chunk_index + 1} KEY_{key_index}で再試行")
            elif chunk_index == 0:
                # 最初のチャンクでボイス設定をログ出力
                print(f"      [ボイス設定] カツミ={GEMINI_VOICE_KATSUMI}, ヒロシ={GEMINI_VOICE_HIROSHI}")

            # 台本どおりに読み上げるプロンプト（TTS_INSTRUCTIONを使用）
            # 環境変数で声質を詳細にカスタマイズ可能
            instruction = TTS_INSTRUCTION.format(
                voice_female=TTS_VOICE_FEMALE,
                voice_male=TTS_VOICE_MALE
            )
            tts_prompt = f"""{instruction}

【台本】
{dialogue_text}"""

            response = client.models.generate_content(
                model=GEMINI_TTS_MODEL,
                contents=tts_prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                            speaker_voice_configs=speaker_configs
                        )
                    ),
                )
            )

            # 音声データを取得
            if response.candidates and response.candidates[0].content.parts:
                audio_data = response.candidates[0].content.parts[0].inline_data.data
                save_wav_file(output_path, audio_data)
                # 音声品質確認用ログ（サイズ）
                audio_size_kb = len(audio_data) / 1024
                print(f"      ✓ チャンク{chunk_index + 1} 生成完了 (KEY_{key_index}, {audio_size_kb:.1f}KB)")
                return True

        except Exception as e:
            error_str = str(e)
            is_429 = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str
            is_500 = "500" in error_str or "INTERNAL" in error_str

            if is_429 or is_500:
                error_type = "429" if is_429 else "500"
                print(f"      ✗ チャンク{chunk_index + 1} {error_type}エラー (KEY_{key_index})")

                # エラーを記録
                if key_manager and is_429:
                    key_manager.mark_429_error(current_key)
                tried_keys.add(current_key)

                # リトライ可能か確認
                if attempt < max_retries:
                    # 別のキーを取得
                    if key_manager:
                        new_key, new_key_name = key_manager.get_key_with_least_failures(tried_keys)
                        if new_key != current_key:
                            print(f"        → {new_key_name}に切り替えて即座にリトライ")
                            current_key = new_key
                            continue  # 待機なしでリトライ

                    # 同じキーしかない場合は待機
                    wait_time = retry_wait if is_429 else 10  # 500エラーは短めに待機
                    print(f"        → {wait_time}秒待機後にリトライ...")
                    time.sleep(wait_time)
                else:
                    print(f"      ✗ チャンク{chunk_index + 1} 最大リトライ回数超過（{error_type}エラー）")
            else:
                print(f"      ✗ チャンク{chunk_index + 1} エラー: {e}")
                # その他のエラーも1回はリトライ
                if attempt < max_retries:
                    print(f"        → 10秒待機後にリトライ...")
                    time.sleep(10)
                else:
                    break

    return False


def generate_gemini_tts_single(text: str, voice: str, api_key: str, output_path: str) -> bool:
    """Gemini TTSでシングルスピーカー音声を生成（フォールバック用）"""
    try:
        client = genai_tts.Client(api_key=api_key)

        response = client.models.generate_content(
            model=GEMINI_TTS_MODEL,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice
                        )
                    )
                ),
            )
        )

        if response.candidates and response.candidates[0].content.parts:
            audio_data = response.candidates[0].content.parts[0].inline_data.data
            save_wav_file(output_path, audio_data)
            return True

    except Exception as e:
        print(f"        シングルTTSエラー: {e}")

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


# ===== 統合TTS + STT関数（1回生成 + Whisperタイミング取得） =====

def generate_unified_audio_with_stt(dialogue: list, output_path: str, temp_dir: Path, key_manager: GeminiKeyManager) -> tuple:
    """全台本を1回でTTS生成し、Whisper STTで正確なタイミングを取得

    Args:
        dialogue: 対話リスト（全セリフ）
        output_path: 出力パス
        temp_dir: 一時ディレクトリ
        key_manager: APIキーマネージャー

    Returns:
        tuple: (output_path, segments, total_duration)
    """
    from faster_whisper import WhisperModel
    import difflib

    print("    [統合TTS] 全台本を1回で生成開始...")

    # 1. 全対話テキストを構築
    dialogue_text = "\n".join([
        f"{line['speaker']}: {fix_reading(line['text'])}"
        for line in dialogue if not line.get("is_silence")
    ])

    # 2. Gemini TTSで一括生成
    api_key = key_manager.get_working_key()
    print(f"    [統合TTS] 全{len(dialogue)}セリフを生成...")

    tts_success = False
    max_retries = 5

    for attempt in range(max_retries):
        try:
            client = genai_tts.Client(api_key=api_key)

            # マルチスピーカー設定
            speaker_configs = [
                types.SpeakerVoiceConfig(
                    speaker="カツミ",
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=GEMINI_VOICE_KATSUMI
                        )
                    )
                ),
                types.SpeakerVoiceConfig(
                    speaker="ヒロシ",
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=GEMINI_VOICE_HIROSHI
                        )
                    )
                )
            ]

            # TTS指示文
            instruction = TTS_INSTRUCTION.format(
                voice_female=TTS_VOICE_FEMALE,
                voice_male=TTS_VOICE_MALE
            )
            tts_prompt = f"""{instruction}

【台本】
{dialogue_text}"""

            response = client.models.generate_content(
                model=GEMINI_TTS_MODEL,
                contents=tts_prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                            speaker_voice_configs=speaker_configs
                        )
                    ),
                )
            )

            if response.candidates and response.candidates[0].content.parts:
                audio_data = response.candidates[0].content.parts[0].inline_data.data
                save_wav_file(output_path, audio_data)
                tts_success = True
                print(f"    ✓ TTS生成完了")
                break

        except Exception as e:
            error_str = str(e)
            is_429 = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str

            if is_429:
                print(f"    ⚠ 429エラー (attempt {attempt + 1}/{max_retries})")
                key_manager.mark_429_error(api_key)
                api_key, _ = key_manager.get_key_with_least_failures({api_key})
                time.sleep(5)
            else:
                print(f"    ⚠ TTS エラー: {e}")
                if attempt < max_retries - 1:
                    api_key, _ = key_manager.get_key_with_least_failures({api_key})
                    time.sleep(3)

    if not tts_success:
        print("    ❌ TTS生成失敗、gTTSフォールバック...")
        all_text = "。".join([fix_reading(line["text"]) for line in dialogue if not line.get("is_silence")])
        if not generate_gtts_fallback(all_text, output_path):
            return None, [], 0.0

    # 3. 音声長を取得
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', output_path
    ], capture_output=True, text=True)
    total_duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0
    print(f"    [統合TTS] 音声長: {total_duration:.1f}秒")

    # 4. Whisper STTでタイミング取得
    print("    [STT] faster-whisperで音声解析...")
    try:
        # baseモデルを使用（速度と精度のバランス）
        model = WhisperModel("base", device="cpu", compute_type="int8")
        whisper_segments_raw, info = model.transcribe(
            output_path,
            language="ja",
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=300)
        )
        whisper_segments = list(whisper_segments_raw)
        print(f"    [STT] {len(whisper_segments)}セグメント検出")

    except Exception as e:
        print(f"    ⚠ STTエラー: {e}、テキスト長比例でフォールバック")
        whisper_segments = None

    # 5. 台本とSTT結果をマッチング
    segments = []
    normal_lines = [line for line in dialogue if not line.get("is_silence")]

    if whisper_segments and len(whisper_segments) > 0:
        # STTセグメントと台本をマッチング
        segments = match_stt_to_script(whisper_segments, dialogue, total_duration)
        print(f"    [STT] {len(segments)}セリフにタイミング割当完了")
    else:
        # フォールバック: テキスト長比例でタイミング計算
        print("    [フォールバック] テキスト長比例でタイミング計算...")
        segments = calculate_timing_by_text_length(dialogue, total_duration)

    return output_path, segments, total_duration


def match_stt_to_script(whisper_segments: list, dialogue: list, total_duration: float) -> list:
    """Whisper STT結果と台本をマッチングして正確なタイミングを取得

    Args:
        whisper_segments: Whisperのセグメントリスト
        dialogue: 台本の対話リスト
        total_duration: 総音声長（秒）

    Returns:
        list: タイミング付きセグメントリスト
    """
    import difflib

    segments = []
    current_whisper_idx = 0
    current_time = 0.0

    # Whisperセグメントのテキストを結合して検索用に準備
    whisper_texts = []
    whisper_timings = []
    for seg in whisper_segments:
        whisper_texts.append(seg.text.strip())
        whisper_timings.append((seg.start, seg.end))

    # 全Whisperテキストを結合（マッチング用）
    all_whisper_text = "".join(whisper_texts)

    for i, line in enumerate(dialogue):
        speaker = line["speaker"]
        text = line["text"]
        section = line.get("section", "")
        color = CHARACTERS.get(speaker, {}).get("color", "#FFFFFF")

        if line.get("is_silence"):
            # 無音セグメント
            silence_duration = line.get("silence_duration_ms", 3000) / 1000.0
            segments.append({
                "speaker": speaker,
                "text": text,
                "start": current_time,
                "end": current_time + silence_duration,
                "color": "#FFFFFF",
                "section": section,
                "is_silence": True,
            })
            current_time += silence_duration
            continue

        # 台本テキストとWhisperテキストをマッチング
        # 最も類似するWhisperセグメントを探す
        best_match_idx = current_whisper_idx
        best_ratio = 0.0

        # 現在位置から前後5セグメントを検索
        search_start = max(0, current_whisper_idx - 2)
        search_end = min(len(whisper_texts), current_whisper_idx + 8)

        for j in range(search_start, search_end):
            # セグメント単体またはセグメント結合でマッチング
            for k in range(j, min(j + 3, search_end)):
                combined = "".join(whisper_texts[j:k+1])
                # 読み方修正を除いた比較用テキスト
                clean_text = text.replace("、", "").replace("。", "").replace("！", "").replace("？", "")
                clean_combined = combined.replace("、", "").replace("。", "").replace("！", "").replace("？", "")

                ratio = difflib.SequenceMatcher(None, clean_text, clean_combined).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match_idx = j
                    best_match_end = k

        # タイミングを取得（閾値0.5に引き上げて精度向上）
        if best_ratio > 0.5 and best_match_idx < len(whisper_timings):
            start_time = whisper_timings[best_match_idx][0]
            end_time = whisper_timings[min(best_match_end, len(whisper_timings) - 1)][1]
            current_whisper_idx = best_match_end + 1
        else:
            # マッチしない場合は現在位置から推定
            if current_whisper_idx < len(whisper_timings):
                start_time = whisper_timings[current_whisper_idx][0]
                # テキスト長から終了時間を推定
                avg_chars_per_sec = 5.0  # 日本語の平均読み上げ速度
                estimated_duration = len(text) / avg_chars_per_sec
                end_time = min(start_time + estimated_duration, total_duration)
                current_whisper_idx += 1
            else:
                start_time = current_time
                end_time = current_time + len(text) / 5.0

        segments.append({
            "speaker": speaker,
            "text": text,
            "start": start_time,
            "end": end_time,
            "color": color,
            "section": section,
        })
        current_time = end_time

    # 字幕重なり修正: end時間が次のstart時間を超えている場合は調整
    segments = fix_subtitle_overlap(segments)

    return segments


def fix_subtitle_overlap(segments: list, gap: float = 0.05) -> list:
    """字幕の重なりを修正

    Args:
        segments: タイミング付きセグメントリスト
        gap: 字幕間の最小ギャップ（秒）

    Returns:
        重なりを修正したセグメントリスト
    """
    if len(segments) < 2:
        return segments

    fixed_count = 0
    for i in range(len(segments) - 1):
        current = segments[i]
        next_seg = segments[i + 1]

        # 現在のend時間が次のstart時間を超えている場合
        if current["end"] > next_seg["start"] - gap:
            # end時間を次のstart時間の少し前に調整
            old_end = current["end"]
            current["end"] = max(current["start"] + 0.1, next_seg["start"] - gap)
            fixed_count += 1

    if fixed_count > 0:
        print(f"    [字幕調整] {fixed_count}箇所の重なりを修正")

    return segments


def calculate_timing_by_text_length(dialogue: list, total_duration: float) -> list:
    """テキスト長に比例してタイミングを計算（フォールバック用）

    Args:
        dialogue: 対話リスト
        total_duration: 総音声長（秒）

    Returns:
        list: タイミング付きセグメントリスト
    """
    segments = []

    # 無音を除いた通常セリフの合計テキスト長
    normal_lines = [line for line in dialogue if not line.get("is_silence")]
    total_text_len = sum(len(line.get("text", "")) for line in normal_lines) or 1

    # 無音の合計時間
    total_silence = sum(
        line.get("silence_duration_ms", 3000) / 1000.0
        for line in dialogue if line.get("is_silence")
    )

    # 通常セリフに割り当てる時間
    speech_duration = total_duration - total_silence
    if speech_duration < 0:
        speech_duration = total_duration

    current_time = 0.0
    for line in dialogue:
        speaker = line["speaker"]
        text = line["text"]
        section = line.get("section", "")
        color = CHARACTERS.get(speaker, {}).get("color", "#FFFFFF")

        if line.get("is_silence"):
            line_duration = line.get("silence_duration_ms", 3000) / 1000.0
            segments.append({
                "speaker": speaker,
                "text": text,
                "start": current_time,
                "end": current_time + line_duration,
                "color": "#FFFFFF",
                "section": section,
                "is_silence": True,
            })
        else:
            text_len = len(text)
            line_duration = (text_len / total_text_len) * speech_duration
            segments.append({
                "speaker": speaker,
                "text": text,
                "start": current_time,
                "end": current_time + line_duration,
                "color": color,
                "section": section,
            })

        current_time += line_duration

    return segments


# ===== Google Cloud TTS 関数 =====

def get_gcloud_tts_client():
    """Google Cloud TTS クライアントを取得"""
    key_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if not key_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY が設定されていません")

    key_data = json.loads(key_json)
    credentials = Credentials.from_service_account_info(key_data)
    return texttospeech.TextToSpeechClient(credentials=credentials)


def generate_gcloud_tts_single(text: str, speaker: str, output_path: str) -> bool:
    """Google Cloud TTSで単一音声を生成

    Args:
        text: 読み上げるテキスト
        speaker: 話者名（カツミ or ヒロシ）
        output_path: 出力ファイルパス

    Returns:
        bool: 成功したかどうか
    """
    try:
        client = get_gcloud_tts_client()

        # 話者に応じたボイスを選択
        voice_name = CHARACTERS.get(speaker, {}).get("gcloud_voice", GCLOUD_VOICE_KATSUMI)

        # 読み方辞書を適用
        text = fix_reading(text)

        # 音声合成リクエストを作成
        synthesis_input = texttospeech.SynthesisInput(text=text)

        voice = texttospeech.VoiceSelectionParams(
            language_code="ja-JP",
            name=voice_name
        )

        # オーディオ設定（WAV形式、24000Hz）
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=24000,
            speaking_rate=1.15  # 少し速め
        )

        # 音声を合成
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )

        # ファイルに保存
        with open(output_path, "wb") as out:
            out.write(response.audio_content)

        return True

    except Exception as e:
        print(f"      [Google Cloud TTS] エラー: {e}")
        return False


def generate_gcloud_tts_dialogue(dialogue: list, output_path: str, temp_dir: Path) -> tuple:
    """Google Cloud TTSで対話音声を生成

    Args:
        dialogue: 対話リスト [{"speaker": "カツミ", "text": "..."}, ...]
        output_path: 出力ファイルパス
        temp_dir: 一時ディレクトリ

    Returns:
        tuple: (output_path, segments, total_duration)
    """
    segments = []
    current_time = 0.0
    audio_files = []

    print(f"    [Google Cloud TTS] {len(dialogue)}セリフを生成中...")
    print(f"    [ボイス設定] カツミ={GCLOUD_VOICE_KATSUMI}, ヒロシ={GCLOUD_VOICE_HIROSHI}")

    for i, line in enumerate(dialogue):
        speaker = line.get("speaker", "カツミ")
        text = line.get("text", "")

        if not text or len(text.strip()) < 2:
            continue

        # 一時ファイルパス
        temp_audio_path = str(temp_dir / f"gcloud_tts_{i:03d}.wav")

        # 音声生成
        success = generate_gcloud_tts_single(text, speaker, temp_audio_path)

        if success and os.path.exists(temp_audio_path):
            audio_files.append(temp_audio_path)

            # 音声の長さを取得
            result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', temp_audio_path
            ], capture_output=True, text=True)
            duration = float(result.stdout.strip()) if result.stdout.strip() else 2.0

            # セグメント情報を追加
            segments.append({
                "speaker": speaker,
                "text": text,
                "start": current_time,
                "end": current_time + duration,
                "color": CHARACTERS[speaker]["color"]
            })
            current_time += duration

            if (i + 1) % 5 == 0:
                print(f"      ✓ {i + 1}/{len(dialogue)} セリフ生成完了")
        else:
            print(f"      ✗ セリフ{i + 1}の生成に失敗")

    print(f"    [Google Cloud TTS] {len(audio_files)}/{len(dialogue)} セリフ成功")

    if not audio_files:
        return None, [], 0.0

    # 音声を結合
    combined_path = str(temp_dir / "gcloud_combined.wav")
    if len(audio_files) == 1:
        import shutil
        shutil.copy(audio_files[0], combined_path)
    else:
        # ffmpegで結合
        list_file = temp_dir / "gcloud_concat.txt"
        with open(list_file, 'w') as f:
            for af in audio_files:
                f.write(f"file '{af}'\n")

        subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(list_file),
            '-acodec', 'pcm_s16le', '-ar', '24000', '-ac', '1', combined_path
        ], capture_output=True)

    # 速度調整 (0.85倍速 = ゆっくり読み上げ)
    SPEED_FACTOR = 0.85
    print(f"    [速度調整] {SPEED_FACTOR}倍速に変換中...")
    subprocess.run([
        'ffmpeg', '-y', '-i', combined_path,
        '-filter:a', f'atempo={SPEED_FACTOR}',
        '-acodec', 'pcm_s16le', '-ar', '24000', '-ac', '1', output_path
    ], capture_output=True)

    # 長さ取得
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', output_path
    ], capture_output=True, text=True)
    total_duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0
    print(f"    [速度調整後] 音声長: {total_duration:.1f}秒")

    # 速度調整を反映してセグメントのタイミングを再計算
    for seg in segments:
        seg["start"] /= SPEED_FACTOR
        seg["end"] /= SPEED_FACTOR

    # 一時ファイル削除
    for af in audio_files:
        if os.path.exists(af):
            try:
                os.remove(af)
            except:
                pass
    if os.path.exists(combined_path):
        try:
            os.remove(combined_path)
        except:
            pass

    return output_path, segments, total_duration


def detect_timing_with_whisper(audio_path: str, script_lines: list) -> list:
    """Whisperを使用して音声から正確なセリフタイミングを検出

    Args:
        audio_path: 音声ファイルパス
        script_lines: 台本のセリフリスト [{"speaker": "カツミ", "text": "..."}, ...]

    Returns:
        list: 各セリフの (start, end) タプルのリスト
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("    [Whisper] faster-whisper未インストール、フォールバック使用")
        return detect_silence_points_fallback(audio_path, len(script_lines))

    # 音声の総長を取得
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', audio_path
    ], capture_output=True, text=True)
    total_duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0

    num_lines = len(script_lines)
    if total_duration == 0 or num_lines == 0:
        return [(0.0, total_duration)] if num_lines <= 1 else [(0.0, total_duration)]

    try:
        # Whisperモデルをロード（small = 高精度かつ高速）
        # int8量子化でメモリ節約 & 高速化
        print("    [Whisper] モデルロード中 (small)...")
        model = WhisperModel("small", device="cpu", compute_type="int8")

        # 音声を文字起こし（word_timestamps=True で単語レベルのタイミング取得）
        print("    [Whisper] 音声解析中...")
        segments, info = model.transcribe(
            audio_path,
            language="ja",
            word_timestamps=True,
            vad_filter=True,  # 音声区間検出で精度向上
            vad_parameters=dict(
                min_silence_duration_ms=200,  # 200ms以上の無音で区切り
                speech_pad_ms=100,  # 発話前後に100msのパディング
            )
        )

        # Whisperのセグメントをリストに変換
        whisper_segments = []
        for segment in segments:
            whisper_segments.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
                "words": [{"start": w.start, "end": w.end, "word": w.word} for w in (segment.words or [])]
            })

        print(f"    [Whisper] {len(whisper_segments)}セグメント検出")

        # Whisperセグメントをスクリプトのセリフ数に合わせてマッピング
        timings = _map_whisper_to_script(whisper_segments, script_lines, total_duration)

        return timings

    except Exception as e:
        print(f"    [Whisper] エラー: {e}、フォールバック使用")
        return detect_silence_points_fallback(audio_path, num_lines)


def _map_whisper_to_script(whisper_segments: list, script_lines: list, total_duration: float) -> list:
    """Whisperのセグメントをスクリプトのセリフにマッピング

    戦略:
    1. Whisperセグメントが台本セリフ数より多い場合 → 隣接セグメントを結合
    2. Whisperセグメントが台本セリフ数より少ない場合 → 長いセグメントを分割
    3. セリフのテキスト長で比例配分
    """
    num_lines = len(script_lines)

    if not whisper_segments:
        # Whisperが何も検出しなかった場合、均等分配
        step = total_duration / num_lines
        return [(i * step, (i + 1) * step) for i in range(num_lines)]

    # 全Whisperセグメントを結合したリストを作成
    all_boundaries = []
    for seg in whisper_segments:
        all_boundaries.append({"time": seg["start"], "type": "start"})
        all_boundaries.append({"time": seg["end"], "type": "end"})

    # スクリプトの各セリフのテキスト長を計算（タイミング比例配分用）
    text_lengths = [len(line.get("text", "")) for line in script_lines]
    total_text_len = sum(text_lengths) or 1

    # Whisperセグメント数と台本セリフ数を比較
    num_whisper = len(whisper_segments)

    if num_whisper == num_lines:
        # ぴったり一致 - 直接マッピング
        return [(seg["start"], seg["end"]) for seg in whisper_segments]

    elif num_whisper > num_lines:
        # Whisperセグメントが多い → セリフ数に合わせて結合
        # 各セリフに割り当てるセグメント数を計算（テキスト長比例）
        timings = []
        seg_idx = 0

        for line_idx, text_len in enumerate(text_lengths):
            # このセリフに割り当てるセグメント数（比例配分）
            remaining_lines = num_lines - line_idx
            remaining_segs = num_whisper - seg_idx

            if remaining_lines == 1:
                # 最後のセリフは残り全部
                segs_for_line = remaining_segs
            else:
                # テキスト長に基づいて比例配分
                ratio = text_len / (sum(text_lengths[line_idx:]) or 1)
                segs_for_line = max(1, round(remaining_segs * ratio))
                segs_for_line = min(segs_for_line, remaining_segs - remaining_lines + 1)

            # 割り当てるセグメントの開始・終了を取得
            start_seg = whisper_segments[seg_idx]
            end_seg = whisper_segments[min(seg_idx + segs_for_line - 1, num_whisper - 1)]

            timings.append((start_seg["start"], end_seg["end"]))
            seg_idx += segs_for_line

        return timings

    else:
        # Whisperセグメントが少ない → 長いセグメントを分割
        # まずWhisperセグメントを使い、足りない分は長いセグメントを分割
        timings = []
        seg_idx = 0

        for line_idx in range(num_lines):
            if seg_idx < num_whisper:
                seg = whisper_segments[seg_idx]
                remaining_lines = num_lines - line_idx
                remaining_segs = num_whisper - seg_idx

                if remaining_lines <= remaining_segs:
                    # 1セグメント = 1セリフ
                    timings.append((seg["start"], seg["end"]))
                    seg_idx += 1
                else:
                    # このセグメントを複数セリフに分割
                    lines_for_this_seg = remaining_lines - remaining_segs + 1
                    seg_duration = seg["end"] - seg["start"]

                    # テキスト長に基づいて分割
                    sub_text_lens = text_lengths[line_idx:line_idx + lines_for_this_seg]
                    sub_total = sum(sub_text_lens) or 1

                    current_time = seg["start"]
                    for i, sub_len in enumerate(sub_text_lens):
                        ratio = sub_len / sub_total
                        sub_duration = seg_duration * ratio
                        end_time = current_time + sub_duration if i < len(sub_text_lens) - 1 else seg["end"]
                        timings.append((current_time, end_time))
                        current_time = end_time

                    seg_idx += 1
                    # 分割で追加したセリフ数を考慮
                    continue
            else:
                # Whisperセグメントを使い切った → 残り時間を均等分配
                remaining_duration = total_duration - (timings[-1][1] if timings else 0)
                remaining_lines = num_lines - line_idx
                step = remaining_duration / remaining_lines
                start = timings[-1][1] if timings else 0
                for i in range(remaining_lines):
                    timings.append((start + i * step, start + (i + 1) * step))
                break

        # タイミング数が足りない場合の調整
        while len(timings) < num_lines:
            last_end = timings[-1][1] if timings else 0
            remaining = total_duration - last_end
            timings.append((last_end, last_end + remaining / (num_lines - len(timings) + 1)))

        return timings[:num_lines]


def detect_silence_points_fallback(audio_path: str, num_lines: int) -> list:
    """フォールバック: ffmpeg silencedetectを使用した無音検出

    Args:
        audio_path: 音声ファイルパス
        num_lines: チャンク内のセリフ数

    Returns:
        list: 各セリフの (start, end) タプルのリスト
    """
    import re

    # 音声の長さを取得
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', audio_path
    ], capture_output=True, text=True)
    total_duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0

    if total_duration == 0 or num_lines <= 1:
        return [(0.0, total_duration)]

    # ffmpeg silencedetect で無音区間を検出
    cmd = [
        'ffmpeg', '-i', audio_path,
        '-af', 'silencedetect=noise=-35dB:d=0.15',  # より短い無音も検出
        '-f', 'null', '-'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    # 無音区間の終了時点を抽出
    silence_ends = []
    for line in result.stderr.split('\n'):
        match = re.search(r'silence_end:\s*([\d.]+)', line)
        if match:
            silence_ends.append(float(match.group(1)))

    boundaries = [0.0]

    if len(silence_ends) >= num_lines - 1:
        boundaries.extend(silence_ends[:num_lines - 1])
    else:
        boundaries.extend(silence_ends)
        remaining_lines = num_lines - len(boundaries)
        if remaining_lines > 0:
            last_boundary = boundaries[-1] if boundaries else 0.0
            remaining_duration = total_duration - last_boundary
            step = remaining_duration / (remaining_lines + 1)
            for i in range(1, remaining_lines + 1):
                boundaries.append(last_boundary + step * i)

    boundaries.append(total_duration)

    segments = []
    for i in range(num_lines):
        if i < len(boundaries) - 1:
            segments.append((boundaries[i], boundaries[i + 1]))
        else:
            segments.append((boundaries[-1], total_duration))

    return segments


def split_dialogue_into_chunks(dialogue: list, max_lines: int = MAX_LINES_PER_CHUNK) -> list:
    """対話をチャンクに分割"""
    chunks = []
    for i in range(0, len(dialogue), max_lines):
        chunks.append(dialogue[i:i + max_lines])
    return chunks


def split_dialogue_by_section(dialogue: list) -> list:
    """対話をセクション単位でチャンクに分割

    Returns:
        list: [{"section": str, "is_green_room": bool, "lines": list}, ...]
    """
    chunks = []
    current_section = None
    current_lines = []

    for line in dialogue:
        section = line.get("section", "")
        if section != current_section:
            # 新しいセクション開始
            if current_lines:
                chunks.append({
                    "section": current_section,
                    "is_green_room": current_section == "控え室",
                    "lines": current_lines
                })
            current_section = section
            current_lines = [line]
        else:
            current_lines.append(line)

    # 最後のセクションを追加
    if current_lines:
        chunks.append({
            "section": current_section,
            "is_green_room": current_section == "控え室",
            "lines": current_lines
        })

    return chunks


def _process_chunk_parallel(args: tuple) -> dict:
    """パラレル処理用のチャンク処理関数（ThreadPoolExecutor用）

    argsの形式:
    - 従来形式: (chunk, api_key, chunk_path, chunk_index, key_manager)
    - 新形式: (chunk, api_key, chunk_path, chunk_index, key_manager, jingle_path)
    """
    # 引数を展開（互換性維持）
    if len(args) == 6:
        chunk, api_key, chunk_path, chunk_index, key_manager, jingle_path = args
    else:
        chunk, api_key, chunk_path, chunk_index, key_manager = args
        jingle_path = None

    # API負荷軽減: チャンクインデックスに応じて遅延（声質劣化防止）
    # 0.5秒間隔でスタートをずらす
    stagger_delay = chunk_index * 0.5
    if stagger_delay > 0:
        time.sleep(min(stagger_delay, 5.0))  # 最大5秒

    success = generate_gemini_tts_chunk(
        chunk, api_key, chunk_path, chunk_index,
        key_manager=key_manager,
        max_retries=3,
        retry_wait=30  # パラレル処理では短めに
    )

    duration = 0.0
    speech_duration = 0.0  # 実際の音声部分の長さ
    jingle_duration = 0.0  # ジングルの長さ

    if success and os.path.exists(chunk_path):
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(chunk_path)
            speech_duration = len(audio) / 1000.0  # 実際の音声長（秒）

            # チャンク末尾にジングルを追加
            if jingle_path and os.path.exists(jingle_path):
                jingle = AudioSegment.from_file(jingle_path)
                jingle = jingle + 3  # +3dB
                jingle_duration = len(jingle) / 1000.0
                audio = audio + jingle

            audio.export(chunk_path, format="wav")
            duration = len(audio) / 1000.0  # ミリ秒→秒
        except Exception as e:
            print(f"    ⚠ チャンク処理エラー: {e}")
            # フォールバック: ffprobe
            result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', chunk_path
            ], capture_output=True, text=True)
            duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0
            speech_duration = duration  # フォールバック時は同じ

    return {
        "index": chunk_index,
        "success": success,
        "path": chunk_path if success else None,
        "duration": duration,
        "speech_duration": speech_duration,  # ジングルを除いた実際の音声長
        "jingle_duration": jingle_duration,  # ジングルの長さ
    }


def generate_dialogue_audio_parallel(dialogue: list, output_path: str, temp_dir: Path, key_manager: GeminiKeyManager,
                                     chunk_interval: int = 30) -> tuple:
    """対話音声をパラレル生成（セクション単位、各チャンク末尾にジングル付き）

    Args:
        dialogue: 対話リスト
        output_path: 出力パス
        temp_dir: 一時ディレクトリ
        key_manager: APIキーマネージャー
        chunk_interval: 未使用（互換性のために残す）

    Returns:
        tuple: (output_path, segments, total_duration)
        - segments: 成功したチャンクのセリフのみ含む
    """
    segments = []
    current_time = 0.0

    # ジングルをダウンロード
    NORMAL_JINGLE_ID = "18JF1p4Maea9SPcZ6y0wCHnxI1FMAfyfT"
    GREEN_ROOM_JINGLE_ID = "1zaJf-Oq7gzR26k33y2ccTS0yO_n5gY83"
    normal_jingle_path = str(temp_dir / "normal_jingle.mp3")
    green_room_jingle_path = str(temp_dir / "green_room_jingle.mp3")

    print("    [ジングル] ダウンロード中...")
    download_jingle_from_drive(NORMAL_JINGLE_ID, normal_jingle_path)
    download_jingle_from_drive(GREEN_ROOM_JINGLE_ID, green_room_jingle_path)

    # セクション単位でチャンクに分割
    section_chunks = split_dialogue_by_section(dialogue)
    print(f"    [Gemini TTS] {len(dialogue)}セリフを{len(section_chunks)}セクションに分割")
    for sc in section_chunks:
        print(f"      - {sc['section']}: {len(sc['lines'])}セリフ {'(控室)' if sc['is_green_room'] else ''}")

    # 各セクションのセリフをチャンクとして扱う
    chunks = [sc["lines"] for sc in section_chunks]
    chunk_is_green_room = [sc["is_green_room"] for sc in section_chunks]

    # APIキーを取得
    api_keys = key_manager.get_all_keys()
    if not api_keys:
        print("    ❌ Gemini APIキーがありません")
        return None, [], 0.0

    # パラレル処理のワーカー数（APIキー数とチャンク数の小さい方）
    # max_workersを制限（API負荷軽減、声質劣化防止）
    # 多すぎるとAPIが不安定になり声質が劣化する可能性がある
    max_workers = min(len(api_keys), len(chunks), 10)  # 29→10に制限
    print(f"    [Gemini TTS] {len(api_keys)}個のAPIキーで並列処理（max_workers={max_workers}）")

    # パラレル処理用のタスクを準備（ジングルパス付き）
    tasks = []
    for i, chunk in enumerate(chunks):
        api_key = api_keys[i % len(api_keys)]
        chunk_path = str(temp_dir / f"chunk_{i:03d}.wav")
        # 控室チャンクは控室用ジングル、それ以外は通常ジングル
        jingle_path = green_room_jingle_path if chunk_is_green_room[i] else normal_jingle_path
        tasks.append((chunk, api_key, chunk_path, i, key_manager, jingle_path))

    # ThreadPoolExecutorでパラレル処理
    chunk_files = [None] * len(chunks)
    chunk_durations = [0.0] * len(chunks)
    chunk_speech_durations = [0.0] * len(chunks)  # セリフ部分の長さ（ジングル除く）
    successful_chunk_indices = []

    print(f"    [パラレル処理] {len(chunks)}セクションを{max_workers}並列で処理開始...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_chunk_parallel, task): task[3] for task in tasks}

        for future in as_completed(futures):
            chunk_index = futures[future]
            try:
                result = future.result()
                if result["success"]:
                    chunk_files[result["index"]] = result["path"]
                    chunk_durations[result["index"]] = result["duration"]
                    chunk_speech_durations[result["index"]] = result.get("speech_duration", result["duration"])
                    successful_chunk_indices.append(result["index"])
                    jingle_dur = result.get("jingle_duration", 0)
                    print(f"    ✓ セクション {result['index'] + 1}/{len(chunks)} 完了 (音声{result.get('speech_duration', 0):.1f}秒 + ジングル{jingle_dur:.1f}秒)")
                else:
                    print(f"    ✗ セクション {result['index'] + 1}/{len(chunks)} 失敗")
            except Exception as e:
                print(f"    ✗ セクション {chunk_index + 1}/{len(chunks)} 例外: {e}")

    # 成功したチャンクを確認
    successful_chunks = [f for f in chunk_files if f is not None]
    failed_count = len(chunks) - len(successful_chunks)
    print(f"    [Gemini TTS] {len(successful_chunks)}/{len(chunks)} チャンク成功")

    # デバッグ: 各チャンクの長さを表示
    print(f"    [デバッグ] チャンク詳細:")
    for idx, dur in enumerate(chunk_durations):
        speech_dur = chunk_speech_durations[idx] if idx < len(chunk_speech_durations) else 0
        status = "✓" if chunk_files[idx] else "✗"
        print(f"      {status} チャンク{idx + 1}: 音声={speech_dur:.1f}秒, ジングル含む={dur:.1f}秒")

    # エラーサマリーを表示
    error_summary = key_manager.get_error_summary()
    if error_summary != "エラーなし":
        print(f"    [エラー集計] {error_summary}")

    # 一部でもチャンクが失敗した場合、声の統一のため全てgTTSで再生成
    if failed_count > 0 or not successful_chunks:
        # フォールバック：gTTSで全体を生成（声の統一を保証）
        if failed_count > 0 and successful_chunks:
            print(f"    [フォールバック] {failed_count}チャンク失敗のため、声の統一のためgTTSで全音声を再生成")
        else:
            print("    [フォールバック] gTTSで音声生成")
        all_text = "。".join([fix_reading(line["text"]) for line in dialogue])
        fallback_path = str(temp_dir / "fallback.wav")
        if generate_gtts_fallback(all_text, fallback_path):
            successful_chunks = [fallback_path]
            # gTTSは全セリフを生成するので、全チャンクを成功扱い
            successful_chunk_indices = list(range(len(chunks)))
            # gTTS全体の長さを取得して各チャンクに均等分配
            result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', fallback_path
            ], capture_output=True, text=True)
            gtts_duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0
            per_chunk = gtts_duration / len(chunks) if len(chunks) > 0 else 0.0
            chunk_durations = [per_chunk] * len(chunks)
        else:
            return None, [], 0.0

    # 音声を結合
    combined_path = str(temp_dir / "combined.wav")
    if len(successful_chunks) == 1:
        # 1つだけなら結合不要
        import shutil
        shutil.copy(successful_chunks[0], combined_path)
    else:
        # ffmpegで結合
        list_file = temp_dir / "concat.txt"
        with open(list_file, 'w') as f:
            for af in successful_chunks:
                f.write(f"file '{af}'\n")

        subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(list_file),
            '-acodec', 'pcm_s16le', '-ar', '24000', '-ac', '1', combined_path
        ], capture_output=True)

    # 速度調整なし（Gemini TTSは自然な速度で生成）
    # combined.wav をそのまま output_path にコピー
    import shutil
    shutil.copy(combined_path, output_path)

    # 一時ファイル削除
    if os.path.exists(combined_path):
        os.remove(combined_path)

    # 長さ取得
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', output_path
    ], capture_output=True, text=True)
    total_duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0
    print(f"    [音声長] {total_duration:.1f}秒")

    # セクション単位のタイミングを計算（セリフ部分のみ、ジングルは除外）
    print("    [字幕] セクション単位でタイミング計算...")

    # デバッグ: 成功したセクションを確認
    print(f"    [デバッグ] 成功セクション: {sorted(successful_chunk_indices)}/{len(chunks)}")
    for idx in range(len(section_chunks)):
        section_name = section_chunks[idx]["section"]
        is_success = idx in successful_chunk_indices
        is_green = section_chunks[idx]["is_green_room"]
        line_count = len(section_chunks[idx]["lines"])
        print(f"      セクション{idx}: {section_name} {'(控室)' if is_green else ''} - {'✓成功' if is_success else '✗失敗'} ({line_count}セリフ)")

    current_time = 0.0
    successful_dialogue_count = 0

    for idx in sorted(successful_chunk_indices):
        chunk_lines = chunks[idx]
        chunk_duration = chunk_durations[idx] if idx < len(chunk_durations) else 0.0
        speech_duration = chunk_speech_durations[idx] if idx < len(chunk_speech_durations) else chunk_duration

        if chunk_duration <= 0:
            continue

        # チャンク内のセリフにテキスト長比例でタイミング割り当て
        # 無音セグメントは固定長、通常セリフはテキスト長比例
        normal_lines = [line for line in chunk_lines if not line.get("is_silence")]
        silence_lines = [line for line in chunk_lines if line.get("is_silence")]

        # 無音セグメントの合計時間を計算
        total_silence_duration = sum(
            line.get("silence_duration_ms", 3000) / 1000.0 for line in silence_lines
        )

        # 通常セリフに割り当てる時間（セリフ部分のみ、ジングル除く）
        normal_duration = speech_duration - total_silence_duration if total_silence_duration < speech_duration else 0.0
        total_text_len = sum(len(line.get("text", "")) for line in normal_lines) or 1

        # セリフ開始位置
        segment_time = current_time
        for line in chunk_lines:
            if line.get("is_silence"):
                # 無音セグメントは固定長
                line_duration = line.get("silence_duration_ms", 3000) / 1000.0
                segments.append({
                    "speaker": line["speaker"],
                    "text": line["text"],
                    "start": segment_time,
                    "end": segment_time + line_duration,
                    "color": "#FFFFFF",  # 無音セグメントは白（表示されないが）
                    "section": line.get("section", ""),
                    "is_silence": True,
                })
            else:
                # 通常セリフはテキスト長比例
                text_len = len(line.get("text", ""))
                line_duration = (text_len / total_text_len) * normal_duration if normal_duration > 0 else 0.0
                speaker = line["speaker"]
                color = CHARACTERS.get(speaker, {}).get("color", "#FFFFFF")
                segments.append({
                    "speaker": speaker,
                    "text": line["text"],
                    "start": segment_time,
                    "end": segment_time + line_duration,
                    "color": color,
                    "section": line.get("section", ""),
                })
            segment_time += line_duration
            successful_dialogue_count += 1

        # チャンク境界を厳密に合わせる（前後無音含む全体長）
        current_time += chunk_duration

    print(f"    [字幕] 成功したセリフ数: {successful_dialogue_count}/{len(dialogue)}")

    # 一時ファイル削除
    for af in successful_chunks:
        if af and os.path.exists(af):
            try:
                os.remove(af)
            except:
                pass

    return output_path, segments, total_duration


def upload_audio_to_drive(audio_path: str, folder_id: str = None) -> str:
    """音声ファイルをGoogle Driveにアップロード"""
    try:
        creds = get_google_credentials()
        service = build('drive', 'v3', credentials=creds)

        file_name = os.path.basename(audio_path)
        file_metadata = {'name': file_name}

        if folder_id:
            file_metadata['parents'] = [folder_id]

        media = MediaFileUpload(audio_path, mimetype='audio/wav', resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id,webViewLink').execute()

        print(f"    ✓ Google Driveにアップロード完了: {file.get('webViewLink', file.get('id'))}")
        return file.get('id')

    except Exception as e:
        print(f"    ⚠ Google Driveアップロードエラー: {e}")
        return None


def download_file_from_drive(file_id: str, output_path: str, file_type: str = "ファイル") -> bool:
    """Google Driveからファイルをダウンロード（汎用）"""
    try:
        creds = get_google_credentials()
        service = build('drive', 'v3', credentials=creds)

        # ファイル情報を取得
        file_info = service.files().get(fileId=file_id, fields='name,mimeType').execute()
        print(f"    [{file_type}] ファイル名: {file_info.get('name')}, MIME: {file_info.get('mimeType')}")

        # ダウンロード
        request = service.files().get_media(fileId=file_id)
        with open(output_path, 'wb') as f:
            downloader = request.execute()
            f.write(downloader)

        print(f"    ✓ {file_type}ダウンロード完了")
        return True

    except Exception as e:
        print(f"    ⚠ {file_type}ダウンロードエラー: {e}")
        return False


def download_jingle_from_drive(file_id: str, output_path: str) -> bool:
    """Google Driveからジングルファイルをダウンロード"""
    return download_file_from_drive(file_id, output_path, "ジングル")


def download_background_from_drive(file_id: str, output_path: str) -> bool:
    """Google Driveから背景画像をダウンロードしてリサイズ"""
    try:
        temp_path = output_path + ".tmp"
        if not download_file_from_drive(file_id, temp_path, "背景画像"):
            return False

        # 画像をリサイズ
        img = Image.open(temp_path)
        img = img.convert('RGB')  # RGBAの場合に対応
        img = img.resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.LANCZOS)
        img.save(output_path, 'PNG')

        # 一時ファイル削除
        if os.path.exists(temp_path):
            os.remove(temp_path)

        print(f"    ✓ 背景画像リサイズ完了 ({VIDEO_WIDTH}x{VIDEO_HEIGHT})")
        return True

    except Exception as e:
        print(f"    ⚠ 背景画像処理エラー: {e}")
        # 一時ファイルを削除
        if os.path.exists(output_path + ".tmp"):
            os.remove(output_path + ".tmp")
        return False


def add_jingle_to_audio(tts_audio_path: str, jingle_path: str, output_path: str, silence_ms: int = 500) -> bool:
    """ジングルをTTS音声の先頭に追加（pydub使用）"""
    try:
        from pydub import AudioSegment

        # 音声ファイルを読み込み
        tts_audio = AudioSegment.from_file(tts_audio_path)

        # ジングルを読み込み（+6dB音量アップ）
        jingle = AudioSegment.from_file(jingle_path)
        jingle = jingle + 6  # +6dB
        print(f"    [OPジングル] 長さ: {len(jingle) / 1000:.1f}秒（+6dB）")

        # 無音を作成（サンプルレートとチャンネル数を合わせる）
        silence = AudioSegment.silent(duration=silence_ms, frame_rate=tts_audio.frame_rate)

        # 結合: ジングル + 無音 + TTS音声
        combined = jingle + silence + tts_audio

        # WAV形式で出力（24000Hz, mono, 16bit）
        combined = combined.set_frame_rate(24000).set_channels(1).set_sample_width(2)
        combined.export(output_path, format="wav")

        print(f"    ✓ ジングル追加完了（合計: {len(combined) / 1000:.1f}秒）")
        return True

    except Exception as e:
        print(f"    ⚠ ジングル追加エラー: {e}")
        return False


def add_ending_jingle_to_audio(
    audio_path: str,
    ending_jingle_path: str,
    output_path: str,
    ending_start_ms: int,
    silence_ms: int = 5000  # 5秒の間（ゆったり場面転換）
) -> tuple:
    """エンディングジングルを音声の指定位置に挿入

    Args:
        audio_path: 入力音声ファイルパス
        ending_jingle_path: エンディングジングルファイルパス
        output_path: 出力音声ファイルパス
        ending_start_ms: エンディング開始位置（ミリ秒）
        silence_ms: ジングル前後の無音長さ（デフォルト5秒）

    Returns:
        tuple: (成功フラグ, ジングル長さ（秒）)
    """
    try:
        from pydub import AudioSegment

        # 音声ファイルを読み込み
        audio = AudioSegment.from_file(audio_path)

        # エンディングジングルを読み込み（+6dB音量アップ）
        ending_jingle = AudioSegment.from_file(ending_jingle_path)
        ending_jingle = ending_jingle + 6  # +6dB
        jingle_duration = len(ending_jingle) / 1000  # 秒
        print(f"    [エンディングジングル] 長さ: {jingle_duration:.1f}秒（+6dB）")

        # 音声を分割（本編 | 控え室）
        main_audio = audio[:ending_start_ms]
        backroom_audio = audio[ending_start_ms:]

        # 無音を作成（ジングル前後用）
        jingle_silence = AudioSegment.silent(duration=1000, frame_rate=audio.frame_rate)  # ジングル前後は1秒
        long_silence = AudioSegment.silent(duration=silence_ms, frame_rate=audio.frame_rate)  # 本編後/控え室前は5秒

        # 結合: 本編 + 5秒無音 + (1秒無音 + エンディングジングル + 1秒無音) + 5秒無音 + 控え室
        combined = main_audio + long_silence + jingle_silence + ending_jingle + jingle_silence + long_silence + backroom_audio

        # WAV形式で出力（24000Hz, mono, 16bit）
        combined = combined.set_frame_rate(24000).set_channels(1).set_sample_width(2)
        combined.export(output_path, format="wav")

        # ジングル挿入による追加時間
        # 本編後5秒 + ジングル前1秒 + ジングル + ジングル後1秒 + 控え室前5秒 = 12秒 + ジングル
        added_duration = (silence_ms * 2 + 2000 + len(ending_jingle)) / 1000
        print(f"    ✓ エンディングジングル挿入完了（追加: {added_duration:.1f}秒）")
        print(f"      構成: 本編→5秒→1秒→ジングル→1秒→5秒→控え室")
        return True, added_duration

    except Exception as e:
        print(f"    ⚠ エンディングジングル挿入エラー: {e}")
        return False, 0.0


def insert_jingles_at_positions(
    audio_path: str,
    jingle_path: str,
    positions_ms: list,
    output_path: str,
    silence_before_ms: int = 300,
    silence_after_ms: int = 300,
    volume_db: int = 0
) -> tuple:
    """指定した位置にジングルを挿入し、タイミング調整用のオフセット情報を返す

    Args:
        audio_path: 入力音声ファイルパス
        jingle_path: ジングルファイルパス
        positions_ms: ジングルを挿入する位置のリスト（ミリ秒）
        output_path: 出力音声ファイルパス
        silence_before_ms: ジングル前の無音（ミリ秒）
        silence_after_ms: ジングル後の無音（ミリ秒）
        volume_db: 音量調整（dB）

    Returns:
        tuple: (成功フラグ, 挿入位置ごとの累積オフセット辞書)
    """
    try:
        from pydub import AudioSegment

        audio = AudioSegment.from_file(audio_path)
        jingle = AudioSegment.from_file(jingle_path)
        jingle = jingle + volume_db

        jingle_with_silence = (
            AudioSegment.silent(duration=silence_before_ms, frame_rate=audio.frame_rate) +
            jingle +
            AudioSegment.silent(duration=silence_after_ms, frame_rate=audio.frame_rate)
        )
        insert_duration_ms = len(jingle_with_silence)

        # 位置を昇順にソート
        sorted_positions = sorted(positions_ms)

        # 挿入による累積オフセットを計算
        offsets = {}
        cumulative_offset = 0

        # 結果音声を構築
        result = AudioSegment.empty()
        prev_pos = 0

        for pos in sorted_positions:
            # この位置までの音声を追加
            result += audio[prev_pos:pos]
            # ジングルを挿入
            result += jingle_with_silence
            # オフセットを記録（この位置以降のセグメントに適用）
            cumulative_offset += insert_duration_ms
            offsets[pos] = cumulative_offset
            prev_pos = pos

        # 残りの音声を追加
        result += audio[prev_pos:]

        # 出力
        result = result.set_frame_rate(24000).set_channels(1).set_sample_width(2)
        result.export(output_path, format="wav")

        print(f"    ✓ ジングル挿入完了（{len(sorted_positions)}箇所、各{insert_duration_ms}ms）")
        return True, offsets, insert_duration_ms

    except Exception as e:
        print(f"    ⚠ ジングル挿入エラー: {e}")
        return False, {}, 0


def generate_gradient_background(output_path: str, title: str = ""):
    """温かみのあるベージュ系グラデーション背景を生成"""
    img = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT))
    draw = ImageDraw.Draw(img)

    # 温かみのあるベージュ系グラデーション（上から下へ）
    # 上: 明るいベージュ (245, 235, 220)
    # 下: やや濃いベージュ (230, 215, 195)
    for y in range(VIDEO_HEIGHT):
        ratio = y / VIDEO_HEIGHT
        r = int(245 - ratio * 15)  # 245 → 230
        g = int(235 - ratio * 20)  # 235 → 215
        b = int(220 - ratio * 25)  # 220 → 195
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=(r, g, b))

    img.save(output_path)
    print(f"    [背景] ✓ フォールバック背景生成完了")


def generate_qr_background(output_path: str):
    """控室トーク用のQRコード付き背景画像を生成

    レイアウト:
    - 背景: 真っ黒
    - 左下: QRコード（YouTubeUIと被らない位置）
    - QRコードの右: テキスト
    - 上部: メインテキスト
    """
    import os
    from pathlib import Path

    # 黒背景を作成
    img = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    # フォント設定（50px、太字）
    font_size = 50
    font = None
    # フォント候補（優先順）
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    shadow_offset = 2

    # QRコード生成（qrcodeライブラリ使用、ファイルがなくても動作）
    qr_path = Path(__file__).parent / "assets" / "line_qr.png"
    qr_img = None
    qr_size = 200  # 少し小さめ

    if qr_path.exists():
        qr_img = Image.open(qr_path)
        qr_img = qr_img.resize((qr_size, qr_size), Image.LANCZOS)
    else:
        # qrcodeライブラリで生成
        try:
            import qrcode
            qr = qrcode.QRCode(version=1, box_size=8, border=2)
            qr.add_data("https://lin.ee/SrziaPE")
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="white", back_color="black")
            qr_img = qr_img.resize((qr_size, qr_size), Image.LANCZOS)
        except Exception as e:
            print(f"    [QR背景] ⚠ QRコード生成失敗: {e}")

    # QRコードを左下に配置（YouTubeUIと被らない位置）
    qr_x = 50
    qr_y = VIDEO_HEIGHT - qr_size - 180  # 下から180px上（シークバー回避）

    if qr_img:
        img.paste(qr_img, (qr_x, qr_y))
        print(f"    [QR背景] QRコード配置完了 ({qr_size}x{qr_size}px) 位置: 左下({qr_x}, {qr_y})")

    # QRコードの右側にテキストを配置
    text_x = qr_x + qr_size + 30
    text_y = qr_y + 20
    line_height = font_size + 15

    text_lines = ["年金情報をLINEでお届け", "友だち登録はこちら→"]
    for i, text in enumerate(text_lines):
        y = text_y + i * line_height
        draw.text((text_x + shadow_offset, y + shadow_offset), text, font=font, fill=(50, 50, 50))
        draw.text((text_x, y), text, font=font, fill=(255, 255, 255))

    # 上部にメインメッセージ
    main_font_size = 70
    main_font = None
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                main_font = ImageFont.truetype(fp, main_font_size)
                break
            except Exception:
                continue
    if main_font is None:
        main_font = font

    main_text = "ご視聴ありがとうございました！"
    main_bbox = draw.textbbox((0, 0), main_text, font=main_font)
    main_w = main_bbox[2] - main_bbox[0]
    main_x = (VIDEO_WIDTH - main_w) // 2
    main_y = 150

    draw.text((main_x + shadow_offset, main_y + shadow_offset), main_text, font=main_font, fill=(50, 50, 50))
    draw.text((main_x, main_y), main_text, font=main_font, fill=(255, 255, 255))

    # サブテキスト
    sub_font_size = 40
    sub_font = None
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                sub_font = ImageFont.truetype(fp, sub_font_size)
                break
            except Exception:
                continue
    if sub_font is None:
        sub_font = font

    sub_lines = [
        "チャンネル登録・高評価お願いします",
        "🎁 友だち登録で『新NISA超入門ガイド』プレゼント中"
    ]
    sub_y = 260
    for i, sub_text in enumerate(sub_lines):
        sub_bbox = draw.textbbox((0, 0), sub_text, font=sub_font)
        sub_w = sub_bbox[2] - sub_bbox[0]
        sub_x = (VIDEO_WIDTH - sub_w) // 2
        y = sub_y + i * (sub_font_size + 20)
        draw.text((sub_x + shadow_offset, y + shadow_offset), sub_text, font=sub_font, fill=(50, 50, 50))
        draw.text((sub_x, y), sub_text, font=sub_font, fill=(255, 255, 255))

    img.save(output_path)
    print(f"    [QR背景] 控室用背景生成完了: {output_path}")


# ===== 禁則処理用文字リスト =====
# 行頭禁則: これらの文字は行頭に来てはいけない
KINSOKU_HEAD = set(
    "、。，．・：；？！"  # 句読点・記号
    "゛゜´｀¨＾￣＿"  # 濁点・記号
    "ヽヾゝゞ〃仝々〆〇"  # 繰り返し記号
    "ー―‐"  # 長音・ダッシュ
    "／＼～∥｜…‥"  # 記号
    "'）〕］｝〉》」』】"  # 閉じ括弧
    "°′″℃¢％‰"  # 単位記号
    "ぁぃぅぇぉっゃゅょゎ"  # 小書きひらがな
    "ァィゥェォッャュョヮヵヶ"  # 小書きカタカナ
)
# 行末禁則: これらの文字は行末に来てはいけない
KINSOKU_TAIL = set("'（〔［｛〈《「『【")


def truncate_subtitle(text: str, max_chars: int = 60) -> str:
    """字幕テキストを制限内に収める（はみ出し防止）

    デフォルト60文字 = 1行20文字×3行
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."


def wrap_text(text: str, max_chars: int = 20, max_lines: int = 3) -> str:
    """長いテキストを自動折り返し（ASS用、禁則処理対応）

    Args:
        text: 折り返すテキスト
        max_chars: 1行あたりの最大文字数（デフォルト20）
        max_lines: 最大行数（デフォルト3）
    """
    # まず全体の文字数を制限（max_chars * max_lines）
    total_max = max_chars * max_lines
    text = truncate_subtitle(text, total_max)

    if len(text) <= max_chars:
        return text

    lines = []
    current = ""

    for i, char in enumerate(text):
        current += char
        if len(current) >= max_chars:
            # 禁則処理: 行末禁則文字がある場合は次の文字も含める
            if current[-1] in KINSOKU_TAIL:
                continue
            # 禁則処理: 次の文字が行頭禁則文字の場合は含める
            if i + 1 < len(text) and text[i + 1] in KINSOKU_HEAD:
                continue

            # 句読点や助詞で区切りを見つける
            break_chars = ['、', '。', '！', '？', 'は', 'が', 'を', 'に', 'で', 'と', 'の']
            for bc in break_chars:
                idx = current.rfind(bc)
                # 禁則処理: 分割後の行頭が禁則文字にならないか確認
                if idx > 0 and idx < len(current) - 1:
                    remaining = current[idx + 1:]
                    if remaining and remaining[0] not in KINSOKU_HEAD:
                        lines.append(current[:idx + 1])
                        current = remaining
                        break
            else:
                # 区切りが見つからない場合は強制改行（禁則回避）
                lines.append(current)
                current = ""

    if current:
        lines.append(current)

    # 最大行数制限（はみ出し防止）
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:max_chars - 3] + "..."

    return "\\N".join(lines)


def to_vertical(text: str, max_chars: int = 6) -> str:
    """テキストを縦書き用に変換（@フォント使用時）

    @フォント（縦書きフォント）を使用する場合、
    テキストはそのまま出力し、フォントが縦書き処理を行う。
    文字数を制限して画面上半分(540px)に収める。

    Args:
        text: 元テキスト
        max_chars: 最大文字数（デフォルト6、上半分に収まる数）
    """
    if len(text) > max_chars:
        text = text[:max_chars - 1] + "…"
    return text


def draw_topic_overlay(base_img: Image.Image, title: str, date_str: str = "") -> Image.Image:
    """背景画像にトピック・日付のオーバーレイを描画

    Args:
        base_img: ベースとなる背景画像
        title: トピックタイトル
        date_str: 日付文字列（省略可）

    Returns:
        オーバーレイが描画された画像
    """
    img = base_img.copy().convert('RGBA')
    draw = ImageDraw.Draw(img)

    # 色設定
    accent_color = (255, 107, 53)  # オレンジ #FF6B35
    box_color = (255, 255, 255, 230)  # 白（90%不透明）
    text_color = (0, 0, 0)  # 黒

    # フォント設定
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    ]

    def load_font(size):
        for fp in font_paths:
            try:
                return ImageFont.truetype(fp, size)
            except:
                continue
        return ImageFont.load_default()

    date_font = load_font(36)
    title_font = load_font(42)

    # ボックス設定（右上エリア）
    box_width = 480
    box_padding = 25
    box_margin_right = 40
    box_margin_top = 80  # 日付の下

    # === 1. 日付描画（右上） ===
    if date_str:
        date_bbox = draw.textbbox((0, 0), date_str, font=date_font)
        date_width = date_bbox[2] - date_bbox[0]
        date_x = VIDEO_WIDTH - date_width - box_margin_right
        date_y = 30
        draw.text((date_x, date_y), date_str, font=date_font, fill=accent_color)

    # === 2. トピックテキストの折り返し計算 ===
    max_text_width = box_width - (box_padding * 2)
    lines = []
    current_line = ""

    for char in title:
        test_line = current_line + char
        bbox = draw.textbbox((0, 0), test_line, font=title_font)
        if bbox[2] - bbox[0] > max_text_width:
            if current_line:
                lines.append(current_line)
            current_line = char
        else:
            current_line = test_line
    if current_line:
        lines.append(current_line)

    # 最大4行まで
    if len(lines) > 4:
        lines = lines[:4]
        lines[-1] = lines[-1][:-2] + "..."

    # テキスト高さ計算
    line_height = 50
    text_height = len(lines) * line_height

    # ボックスの高さ
    box_height = box_padding * 2 + text_height

    # === 3. 白い角丸ボックスを描画 ===
    box_x = VIDEO_WIDTH - box_width - box_margin_right
    box_y = box_margin_top

    # 角丸矩形を描画（overlay用に別レイヤー）
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    # 角丸矩形（rounded_rectangle）
    corner_radius = 15
    overlay_draw.rounded_rectangle(
        [box_x, box_y, box_x + box_width, box_y + box_height],
        radius=corner_radius,
        fill=box_color
    )

    # オーバーレイを合成
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # === 4. トピックテキスト描画 ===
    text_x = box_x + box_padding
    text_y = box_y + box_padding

    for i, line in enumerate(lines):
        draw.text((text_x, text_y + i * line_height), line, font=title_font, fill=text_color)

    return img.convert('RGB')


def create_topic_overlay_transparent(title: str, date_str: str = "") -> Image.Image:
    """透明なトピックオーバーレイ画像を作成

    背景を透明にして、日付・トピックボックスのみを描画。
    ffmpegのoverlay filterで合成するために使用。

    Args:
        title: トピックタイトル
        date_str: 日付文字列（省略可）

    Returns:
        透明背景にオーバーレイが描画されたRGBA画像
    """
    # 透明な背景画像を作成
    img = Image.new('RGBA', (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 色設定
    accent_color = (255, 107, 53, 255)  # オレンジ #FF6B35
    box_color = (255, 255, 255, 230)  # 白（90%不透明）
    text_color = (0, 0, 0, 255)  # 黒

    # フォント設定
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    ]

    def load_font(size):
        for fp in font_paths:
            try:
                return ImageFont.truetype(fp, size)
            except:
                continue
        return ImageFont.load_default()

    date_font = load_font(36)
    title_font = load_font(42)

    # ボックス設定（右上エリア）
    box_width = 480
    box_padding = 25
    box_margin_right = 40
    box_margin_top = 80  # 日付の下

    # === 1. 日付描画（右上） ===
    if date_str:
        date_bbox = draw.textbbox((0, 0), date_str, font=date_font)
        date_width = date_bbox[2] - date_bbox[0]
        date_x = VIDEO_WIDTH - date_width - box_margin_right
        date_y = 30
        draw.text((date_x, date_y), date_str, font=date_font, fill=accent_color)

    # === 2. トピックテキストの折り返し計算 ===
    max_text_width = box_width - (box_padding * 2)
    lines = []
    current_line = ""

    for char in title:
        test_line = current_line + char
        bbox = draw.textbbox((0, 0), test_line, font=title_font)
        if bbox[2] - bbox[0] > max_text_width:
            if current_line:
                lines.append(current_line)
            current_line = char
        else:
            current_line = test_line
    if current_line:
        lines.append(current_line)

    # 最大4行まで
    if len(lines) > 4:
        lines = lines[:4]
        lines[-1] = lines[-1][:-2] + "..."

    # テキスト高さ計算
    line_height = 50
    text_height = len(lines) * line_height

    # ボックスの高さ
    box_height = box_padding * 2 + text_height

    # === 3. 白い角丸ボックスを描画 ===
    box_x = VIDEO_WIDTH - box_width - box_margin_right
    box_y = box_margin_top

    # 角丸矩形を描画
    corner_radius = 15
    draw.rounded_rectangle(
        [box_x, box_y, box_x + box_width, box_y + box_height],
        radius=corner_radius,
        fill=box_color
    )

    # === 4. トピックテキスト描画 ===
    text_x = box_x + box_padding
    text_y = box_y + box_padding

    for i, line in enumerate(lines):
        draw.text((text_x, text_y + i * line_height), line, font=title_font, fill=text_color)

    return img


def generate_ass_subtitles(segments: list, output_path: str, section_markers: list = None) -> None:
    """ASS字幕を生成（セリフ字幕＋出典字幕）

    - セリフ字幕: 画面下部（控室セクションはゴールド色）
    - 出典字幕: 透かしバーのすぐ上、左寄せ
    """
    # セリフ字幕設定（画面下部、はみ出し防止）
    font_size = int(VIDEO_WIDTH * 0.065)  # 画面幅の6.5% ≈ 125px（少し小さく）
    margin_bottom = int(VIDEO_HEIGHT * 0.08)  # 下から8%（余裕を持たせる）
    margin_left = int(VIDEO_WIDTH * 0.15)
    margin_right = int(VIDEO_WIDTH * 0.15)
    # 字幕が画面下半分から出ないようにclipを設定
    clip_top = int(VIDEO_HEIGHT * 0.5)  # 540px（画面中央）
    clip_setting = f"{{\\clip(0,{clip_top},{VIDEO_WIDTH},{VIDEO_HEIGHT})}}"

    # ASS色形式: &HAABBGGRR& （末尾に&を追加）
    primary_color = "&H00FFFFFF&"  # 白文字
    shadow_color = "&H80000000&"   # 半透明黒シャドウ
    orange_color = "&H00356BFF&"   # #FF6B35 → BGR: 356BFF（オレンジ）
    gold_color = "&H0000D7FF&"     # #FFD700 → BGR: 00D7FF（ゴールド）

    # 出典設定（ローズピンク、右上）- フォントサイズ1.5倍
    info_font_size = 80  # 少し大きめ
    info_color = "&H009696FF&"  # #FF9696 ローズピンク
    info_outline_color = "&H00400040&"  # 暗紫縁取り
    info_margin_r = 30
    info_margin_v = 30

    # トピック設定（ローズピンク、暗紫縁取り）
    topic_font_size = 100  # 大きめ
    topic_color = "&H009696FF&"  # #FF9696 ローズピンク
    topic_outline_color = "&H00400040&"  # 暗紫縁取り

    # 控室タイトル設定（右上、温かみのあるオレンジイエロー）
    backroom_title_size = 180
    backroom_title_color = "&H0080E0FF&"  # 明るいオレンジイエロー

    # 控室字幕設定（白文字）
    backroom_text_color = "&H00FFFFFF&"  # 白

    header = f"""[Script Info]
Title: 年金ニュース
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK JP,{font_size},{primary_color},&H000000FF&,&H00000000&,{shadow_color},-1,0,0,0,100,100,0,0,1,3,2,2,{margin_left},{margin_right},{margin_bottom},1
Style: Backroom,Noto Sans CJK JP Medium,{font_size},{backroom_text_color},&H000000FF&,&H00000000&,{shadow_color},-1,0,0,0,100,100,0,0,1,3,2,2,{margin_left},{margin_right},{margin_bottom},1
Style: Source,Noto Sans CJK JP,{info_font_size},{info_color},&H000000FF&,{info_outline_color},&H00000000&,-1,0,0,0,100,100,0,0,1,2,0,9,0,{info_margin_r},{info_margin_v},1
Style: BackroomTitle,IPAPGothic,{backroom_title_size},{backroom_title_color},&H000000FF&,{backroom_title_color},&H00000000&,-1,0,0,0,100,100,0,0,1,2,0,9,0,50,50,1
Style: Topic,Noto Sans CJK JP,{topic_font_size},{topic_color},&H000000FF&,{topic_outline_color},&H00000000&,-1,0,0,0,100,100,0,0,1,3,0,7,30,0,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]

    # 出典字幕のタイミングを計算
    source_timings = []
    if section_markers and segments:
        for i, marker in enumerate(section_markers):
            start_idx = marker["start_idx"]
            # このセクションの開始時間を取得
            if start_idx < len(segments):
                start_time = segments[start_idx]["start"]
                # 次のセクションの開始時間または最後まで
                if i + 1 < len(section_markers):
                    next_idx = section_markers[i + 1]["start_idx"]
                    if next_idx < len(segments):
                        end_time = segments[next_idx]["start"]
                    else:
                        end_time = segments[-1]["end"] if segments else start_time + 5
                else:
                    end_time = segments[-1]["end"] if segments else start_time + 5
                source_timings.append({
                    "source": marker.get("source", ""),
                    "start": start_time,
                    "end": end_time,
                })

    # 出典字幕を追加（右揃え、白文字）
    for item in source_timings:
        if item.get("source"):
            start = f"0:{int(item['start']//60):02d}:{int(item['start']%60):02d}.{int((item['start']%1)*100):02d}"
            end = f"0:{int(item['end']//60):02d}:{int(item['end']%60):02d}.{int((item['end']%1)*100):02d}"
            source_text = f"出典: {item['source']}"
            lines.append(f"Dialogue: 2,{start},{end},Source,,0,0,0,,{source_text}")

    # トピック縦書き字幕を追加（左端、縦書き）
    # オープニング・エンディング・控室以外のニュースセクションのみ表示
    if section_markers and segments:
        for i, marker in enumerate(section_markers):
            title = marker.get("title", "")
            # オープニング・深掘り・エンディング・控室は除外
            if title in ["オープニング", "深掘りコーナー", "エンディング", "控え室"]:
                continue
            start_idx = marker["start_idx"]
            if start_idx < len(segments):
                start_time = segments[start_idx]["start"]
                # 次のセクションの開始時間まで
                if i + 1 < len(section_markers):
                    next_idx = section_markers[i + 1]["start_idx"]
                    if next_idx < len(segments):
                        end_time = segments[next_idx]["start"]
                    else:
                        end_time = segments[-1]["end"] if segments else start_time + 5
                else:
                    end_time = segments[-1]["end"] if segments else start_time + 5
                start = f"0:{int(start_time//60):02d}:{int(start_time%60):02d}.{int((start_time%1)*100):02d}"
                end = f"0:{int(end_time//60):02d}:{int(end_time%60):02d}.{int((end_time%1)*100):02d}"
                # トピック（左上、出典と同じスタイル）
                # 長い場合は省略
                display_title = title if len(title) <= 20 else title[:19] + "…"
                lines.append(f"Dialogue: 3,{start},{end},Topic,,0,0,0,,{display_title}")

    # セリフ字幕を追加（控室セクションは黄色、無音セグメントはスキップ）
    backroom_start = None
    backroom_end = None
    for seg in segments:
        # 無音セグメントは字幕を表示しない
        if seg.get("is_silence"):
            continue

        start = f"0:{int(seg['start']//60):02d}:{int(seg['start']%60):02d}.{int((seg['start']%1)*100):02d}"
        end = f"0:{int(seg['end']//60):02d}:{int(seg['end']%60):02d}.{int((seg['end']%1)*100):02d}"
        # セリフのみ表示（話者名なし）、折り返し
        # 1行20文字×3行=最大60文字
        dialogue_text = seg['text']
        wrapped_text = wrap_text(dialogue_text, max_chars=20, max_lines=3)
        # 控室セクションは黄色(Backroom)、それ以外は白(Default)
        is_backroom = seg.get("section") == "控え室"
        style = "Backroom" if is_backroom else "Default"
        # clipで画面下半分に制限（はみ出し防止）
        lines.append(f"Dialogue: 0,{start},{end},{style},,0,0,0,,{clip_setting}{wrapped_text}")

        # 控室セクションの開始・終了を記録
        if is_backroom:
            if backroom_start is None:
                backroom_start = seg['start']
            backroom_end = seg['end']

    # デバッグ: 控室字幕数をカウント
    backroom_count = sum(1 for seg in segments if seg.get("section") == "控え室" and not seg.get("is_silence"))
    total_subtitle_count = len([l for l in lines if l.startswith("Dialogue: 0")])
    print(f"  [デバッグ] 控室セリフ数: {backroom_count}, 字幕行数: {total_subtitle_count}")
    if backroom_start is not None and backroom_end is not None:
        print(f"  [デバッグ] 控室字幕範囲: {backroom_start:.1f}秒 〜 {backroom_end:.1f}秒")

    # 控室タイトル「控室にて。」を画面中央に表示
    if backroom_start is not None and backroom_end is not None:
        br_start = f"0:{int(backroom_start//60):02d}:{int(backroom_start%60):02d}.{int((backroom_start%1)*100):02d}"
        br_end = f"0:{int(backroom_end//60):02d}:{int(backroom_end%60):02d}.{int((backroom_end%1)*100):02d}"
        lines.append(f"Dialogue: 1,{br_start},{br_end},BackroomTitle,,0,0,0,,控室にて。")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    # デバッグ: ASS 出力確認
    print(f"  [ASS字幕] 出力: {output_path}")


def create_video(script: dict, temp_dir: Path, key_manager: GeminiKeyManager) -> tuple:
    """動画を作成"""
    all_dialogue = []
    all_segments = []
    section_markers = []  # トピック字幕用のマーカー

    # オープニング
    opening = script.get("opening", [])
    for d in opening:
        d["section"] = "オープニング"
    all_dialogue.extend(opening)
    if opening:
        section_markers.append({"title": "オープニング", "start_idx": 0})

    # ニュースセクション（確定情報）
    for i, section in enumerate(script.get("news_sections", [])):
        news_title = section.get("news_title", f"ニュース{i+1}")
        source = section.get("source", "")
        dialogue = section.get("dialogue", [])
        for d in dialogue:
            d["section"] = news_title
            d["source"] = source  # 出典情報を各セリフに保存
        if dialogue:
            section_markers.append({"title": news_title, "source": source, "start_idx": len(all_dialogue)})
        all_dialogue.extend(dialogue)

    # 深掘りコーナー
    deep_dive = script.get("deep_dive", [])
    for d in deep_dive:
        d["section"] = "深掘り"
    if deep_dive:
        section_markers.append({"title": "深掘りコーナー", "start_idx": len(all_dialogue)})
    all_dialogue.extend(deep_dive)

    # 雑談まとめ
    chat_summary = script.get("chat_summary", [])
    for d in chat_summary:
        d["section"] = "まとめ"
    if chat_summary:
        section_markers.append({"title": "今日のまとめ", "start_idx": len(all_dialogue)})
    all_dialogue.extend(chat_summary)

    # 噂セクション（あれば）
    rumor_section = script.get("rumor_section", [])
    if rumor_section:
        for d in rumor_section:
            d["section"] = "噂"
        section_markers.append({"title": "噂・参考情報", "start_idx": len(all_dialogue)})
        all_dialogue.extend(rumor_section)

    # エンディング（本編の締め）
    ending = script.get("ending", [])
    for d in ending:
        d["section"] = "エンディング"
    if ending:
        section_markers.append({"title": "エンディング", "start_idx": len(all_dialogue)})
    all_dialogue.extend(ending)

    # 控え室パート
    green_room = script.get("green_room", [])
    print(f"  [デバッグ] 控室台本セリフ数: {len(green_room)}")

    # 控え室（素のボヤキ）※エンディングジングルの後に再生
    for d in green_room:
        d["section"] = "控え室"
    if green_room:
        section_markers.append({"title": "控え室", "start_idx": len(all_dialogue)})
    all_dialogue.extend(green_room)

    # 空や無効なセリフを除外（無音セグメントは除外しない）
    original_count = len(all_dialogue)
    all_dialogue = [
        d for d in all_dialogue
        if d.get("is_silence") or (d.get("text") and len(d["text"].strip()) > 3 and d["text"].strip() not in ["...", "…", "。", "、"])
    ]
    if len(all_dialogue) < original_count:
        print(f"  [フィルタ] {original_count - len(all_dialogue)}件の空セリフを除外")

    # フィルタリング後にsection_markersを再計算
    section_markers_filtered = []
    current_section = None
    for i, d in enumerate(all_dialogue):
        section = d.get("section", "")
        if section != current_section:
            # セクションタイトルを生成
            if section == "オープニング":
                title = "オープニング"
            elif section == "深掘り":
                title = "深掘りコーナー"
            elif section == "まとめ":
                title = "今日のまとめ"
            elif section == "噂":
                title = "噂・参考情報"
            elif section == "エンディング":
                title = "エンディング"
            elif section == "控え室":
                title = "控え室"
            else:
                title = section
            # 出典情報を取得（セリフに保存されている場合）
            source = d.get("source", "")
            section_markers_filtered.append({"title": title, "source": source, "start_idx": i})
            current_section = section
    section_markers = section_markers_filtered

    print(f"  セリフ数: {len(all_dialogue)}")

    # 音声生成（TTS_MODEに応じて切り替え）
    tts_audio_path = str(temp_dir / "tts_audio.wav")

    if TTS_MODE == "google_cloud":
        # Google Cloud TTS
        print(f"  [TTS] Google Cloud TTS を使用")
        _, segments, tts_duration = generate_gcloud_tts_dialogue(all_dialogue, tts_audio_path, temp_dir)
    else:
        # Gemini TTS + Whisper STT（1回生成 + 正確なタイミング）
        print(f"  [TTS] Gemini TTS + Whisper STT を使用（1回生成 + 正確タイミング）")
        _, segments, tts_duration = generate_unified_audio_with_stt(all_dialogue, tts_audio_path, temp_dir, key_manager)

    all_segments = segments

    if tts_duration == 0:
        raise ValueError("音声生成に失敗しました")

    print(f"  TTS音声長: {tts_duration:.1f}秒")

    # オープニングジングル追加（オプション）
    audio_path = str(temp_dir / "audio.wav")
    jingle_file_id = os.environ.get("JINGLE_FILE_ID")
    jingle_duration = 0.0

    if jingle_file_id:
        print("  [ジングル] オープニングジングルを追加...")
        jingle_path = str(temp_dir / "jingle.mp3")

        if download_jingle_from_drive(jingle_file_id, jingle_path):
            if add_jingle_to_audio(tts_audio_path, jingle_path, audio_path, silence_ms=500):
                # ジングル追加成功：字幕タイミングをオフセット
                # ジングルの長さを取得
                result = subprocess.run([
                    'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1', jingle_path
                ], capture_output=True, text=True)
                jingle_duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0
                jingle_duration += 0.5  # 無音分を追加

                # 字幕タイミングをジングル分だけオフセット
                for seg in all_segments:
                    seg["start"] += jingle_duration
                    seg["end"] += jingle_duration

                print(f"  ✓ ジングル追加完了（オフセット: {jingle_duration:.1f}秒）")
            else:
                # ジングル追加失敗：TTS音声のみ使用
                print("  ⚠ ジングル追加失敗、TTS音声のみで続行")
                import shutil
                shutil.copy(tts_audio_path, audio_path)
        else:
            # ダウンロード失敗：TTS音声のみ使用
            print("  ⚠ ジングルダウンロード失敗、TTS音声のみで続行")
            import shutil
            shutil.copy(tts_audio_path, audio_path)
    else:
        # ジングル未設定：TTS音声のみ使用
        import shutil
        shutil.copy(tts_audio_path, audio_path)

    # 音声は1本で生成済み（各セクション末尾にジングル付き）
    # 追加のジングル挿入処理は不要

    # 控え室BGMを追加（オプション）
    BACKROOM_BGM_FILE_ID = "1wP6bp0a0PlaaqM55b8zdwozxT0XTOvab"
    backroom_bgm_path = str(temp_dir / "backroom_bgm.mp3")

    # 控え室セクションの開始位置を検出
    backroom_start_ms = None
    for seg in all_segments:
        if seg.get("section") == "控え室":
            backroom_start_ms = int(seg["start"] * 1000)
            break

    if backroom_start_ms is not None:
        print(f"  [控え室BGM] 開始位置: {backroom_start_ms / 1000:.1f}秒")
        if download_jingle_from_drive(BACKROOM_BGM_FILE_ID, backroom_bgm_path):
            try:
                from pydub import AudioSegment

                # メイン音声を読み込み
                main_audio = AudioSegment.from_file(audio_path)
                total_duration_ms = len(main_audio)

                # BGMを読み込み（原音のまま）
                bgm = AudioSegment.from_file(backroom_bgm_path)
                # bgm = bgm - 0  # 原音のまま（音量調整なし）
                print(f"    [BGM] 長さ: {len(bgm) / 1000:.1f}秒, 音量: 原音")

                # BGMが短ければループ
                bgm_duration_needed = total_duration_ms - backroom_start_ms
                if len(bgm) < bgm_duration_needed:
                    loop_count = (bgm_duration_needed // len(bgm)) + 1
                    bgm = bgm * loop_count
                    print(f"    [BGM] {loop_count}回ループ")

                # 必要な長さにトリム
                bgm = bgm[:bgm_duration_needed]

                # 最後の5秒でフェードアウト
                fade_duration = min(5000, len(bgm))
                bgm = bgm.fade_out(fade_duration)

                # メイン音声にBGMをオーバーレイ
                final_audio = main_audio.overlay(bgm, position=backroom_start_ms)

                # 出力
                final_audio = final_audio.set_frame_rate(24000).set_channels(1).set_sample_width(2)
                final_audio.export(audio_path, format="wav")
                print(f"  ✓ 控え室BGM追加完了")

            except Exception as e:
                print(f"  ⚠ 控え室BGM追加エラー: {e}")
        else:
            print("  ⚠ 控え室BGMダウンロード失敗、スキップ")
    else:
        print("  [控え室BGM] 控え室セクションが見つかりません、スキップ")

    # 最終音声長を取得
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', audio_path
    ], capture_output=True, text=True)
    duration = float(result.stdout.strip()) if result.stdout.strip() else tts_duration
    print(f"  最終音声長: {duration:.1f}秒")

    # Google Driveにアップロード（オプション）
    drive_folder_id = os.environ.get("AUDIO_DRIVE_FOLDER_ID")
    if drive_folder_id:
        upload_audio_to_drive(audio_path, drive_folder_id)

    # 背景画像（Google Driveから取得、未設定時はフォールバック）
    print("  背景画像を準備中...")
    bg_path = str(temp_dir / "background.png")
    bg_file_id = os.environ.get("BACKGROUND_IMAGE_ID")

    bg_loaded = False
    if bg_file_id:
        print(f"    [背景] Google Driveから取得中... (ID: {bg_file_id[:10]}...)")
        bg_loaded = download_background_from_drive(bg_file_id, bg_path)
    else:
        print("    [背景] BACKGROUND_IMAGE_ID未設定")

    if not bg_loaded:
        print("    [背景] フォールバック背景を生成")
        generate_gradient_background(bg_path, script.get("title", ""))

    # 背景画像の存在確認
    if not os.path.exists(bg_path):
        raise ValueError(f"背景画像の生成に失敗しました: {bg_path}")

    # ASS字幕（トピック字幕含む）
    ass_path = str(temp_dir / "subtitles.ass")
    generate_ass_subtitles(all_segments, ass_path, section_markers)

    # 控室用QRコード背景を生成
    qr_bg_path = str(temp_dir / "qr_background.png")
    generate_qr_background(qr_bg_path)

    # 動画生成
    output_path = str(temp_dir / f"nenkin_news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")

    if USE_MODAL_GPU:
        # Modal GPU エンコード (T4 GPU, h264_nvenc)
        print("  [動画生成] Modal GPU エンコード開始...")
        import modal

        # デプロイ済み関数をルックアップ
        encode_video_gpu = modal.Function.from_name("nenkin-video", "encode_video_gpu")

        # ファイルをbase64エンコード
        with open(bg_path, "rb") as f:
            bg_base64 = base64.b64encode(f.read()).decode()
        with open(qr_bg_path, "rb") as f:
            qr_bg_base64 = base64.b64encode(f.read()).decode()
        with open(audio_path, "rb") as f:
            audio_base64 = base64.b64encode(f.read()).decode()
        with open(ass_path, "r", encoding="utf-8") as f:
            ass_content = f.read()

        output_name = os.path.basename(output_path)

        # 控室開始時刻を秒に変換（背景をQRコード付きに切り替え）
        backroom_start_sec = backroom_start_ms / 1000 if backroom_start_ms is not None else None
        if backroom_start_sec is not None:
            print(f"  [動画] 控室開始 {backroom_start_sec:.1f}秒 からQRコード背景に切り替え予定")

        # Modal リモート呼び出し（QRコード背景も渡す）
        video_bytes = encode_video_gpu.remote(bg_base64, audio_base64, ass_content, output_name, backroom_start_sec, qr_bg_base64)

        # 結果をファイルに書き込み
        with open(output_path, "wb") as f:
            f.write(video_bytes)

        print(f"✓ 動画生成完了 (Modal GPU): {output_path}")
    else:
        # ローカル CPU エンコード (libx264)
        # 背景バーの設定
        bar_height = int(VIDEO_HEIGHT * 0.45)  # 画面の45%（3行字幕も収まる高さ）
        bar_y = VIDEO_HEIGHT - bar_height  # バーのY座標（画面下部）

        # 控室開始時刻を秒に変換（背景をQRコード付きに切り替え）
        backroom_start_sec = backroom_start_ms / 1000 if backroom_start_ms is not None else None

        # ffmpegフィルター: 控室開始からQRコード背景をoverlay
        # fontsdir でフォントディレクトリを明示的に指定（日本語フォント対応）
        if backroom_start_sec is not None:
            # 控室開始からQRコード背景をoverlay（透かしバーは控室前のみ表示）
            vf_filter = (
                f"[0:v]scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
                f"drawbox=x=0:y={bar_y}:w={VIDEO_WIDTH}:h={bar_height}:color=0x3C281E@0.8:t=fill:enable='lt(t,{backroom_start_sec})'[main];"
                f"[1:v]scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}[qr];"
                f"[main][qr]overlay=0:0:enable='gte(t,{backroom_start_sec})',"
                f"ass={ass_path}:fontsdir=/usr/share/fonts"
            )
            print(f"  [動画] 控室開始 {backroom_start_sec:.1f}秒 からQRコード背景に切り替え")
        else:
            vf_filter = (
                f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
                f"drawbox=x=0:y={bar_y}:w={VIDEO_WIDTH}:h={bar_height}:color=0x3C281E@0.8:t=fill,"
                f"ass={ass_path}:fontsdir=/usr/share/fonts"
            )

        # QRコード背景がある場合は2入力ffmpeg
        if backroom_start_sec is not None:
            cmd = [
                'ffmpeg', '-y',
                '-loop', '1', '-i', bg_path,
                '-loop', '1', '-i', qr_bg_path,
                '-i', audio_path,
                '-filter_complex', vf_filter,
                '-map', '[out]' if '[out]' in vf_filter else '0:v',
                '-map', '2:a',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                '-c:a', 'aac', '-b:a', '192k',
                '-shortest',
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart',
                output_path
            ]
            # filter_complexの出力ラベル修正
            vf_filter = (
                f"[0:v]scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
                f"drawbox=x=0:y={bar_y}:w={VIDEO_WIDTH}:h={bar_height}:color=0x3C281E@0.8:t=fill:enable='lt(t,{backroom_start_sec})'[main];"
                f"[1:v]scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}[qr];"
                f"[main][qr]overlay=0:0:enable='gte(t,{backroom_start_sec})'[overlaid];"
                f"[overlaid]ass={ass_path}:fontsdir=/usr/share/fonts[out]"
            )
            cmd = [
                'ffmpeg', '-y',
                '-loop', '1', '-i', bg_path,
                '-loop', '1', '-i', qr_bg_path,
                '-i', audio_path,
                '-filter_complex', vf_filter,
                '-map', '[out]',
                '-map', '2:a',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                '-c:a', 'aac', '-b:a', '192k',
                '-shortest',
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart',
                output_path
            ]
        else:
            cmd = [
                'ffmpeg', '-y',
                '-loop', '1', '-i', bg_path,
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
        print(f"✓ 動画生成完了 (ローカル CPU): {output_path}")

    return output_path, ass_path


def get_or_create_playlist(youtube, title: str, description: str = None):
    """再生リストを取得または作成"""
    # デフォルトの説明文
    if description is None:
        description = "毎日届く年金ニュースをまとめてお届け。聞き流すだけで年金の知識が身につきます。"

    # 既存の再生リストを検索
    request = youtube.playlists().list(
        part="snippet",
        mine=True,
        maxResults=50
    )
    response = request.execute()

    for playlist in response.get("items", []):
        if playlist["snippet"]["title"] == title:
            print(f"  ✓ 既存の再生リスト発見: {title} ({playlist['id']})")
            return playlist["id"]

    # なければ作成
    request = youtube.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title,
                "description": description
            },
            "status": {
                "privacyStatus": "public"
            }
        }
    )
    response = request.execute()
    print(f"  ✓ 再生リスト作成: {title} ({response['id']})")
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


def add_to_playlists(youtube, video_id):
    """動画を再生リストに追加（固定ID使用）"""
    # 横動画用再生リストID
    PLAYLIST_ID = "PLSMHaaaPDI0jiSoTEHp2iZ6MPpA8LRRel"

    results = {"playlist": False}

    try:
        add_to_playlist(youtube, PLAYLIST_ID, video_id)
        results["playlist"] = True
        print(f"  ✓ 再生リストに追加: {PLAYLIST_ID}")
    except Exception as e:
        print(f"  ⚠ 再生リスト追加エラー: {e}")

    return results


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

    # 再生リストとポッドキャストに追加
    playlist_results = add_to_playlists(youtube, video_id)

    # アップロード完了メッセージを表示
    print("\n" + "=" * 40)
    print("YouTube投稿完了!")
    print("=" * 40)
    print(f"動画URL: {url}")
    print(f"チャンネル: TOKEN_23")
    print(f"タイトル: {title}")
    print(f"公開設定: 公開")
    if playlist_results.get("playlist"):
        print(f"再生リスト: 聞くだけでわかる年金のお話")
    if playlist_results.get("podcast"):
        print(f"ポッドキャスト: 得する年金ニュースラジオ")
    print("=" * 40)

    return url


def generate_grandma_comment(script: dict, key_manager: GeminiKeyManager) -> str:
    """おばあちゃんのコメントを生成（Gemini API）

    Args:
        script: 台本データ
        key_manager: APIキーマネージャー

    Returns:
        str: おばあちゃんのコメント（50文字以内）
    """
    api_key, key_name = key_manager.get_working_key()
    if not api_key:
        print("  ⚠ Gemini APIキーがないためコメント生成をスキップ")
        return ""

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    # 台本の内容を要約
    dialogues = []
    for section in script.get("news_sections", []):
        for line in section.get("dialogue", []):
            dialogues.append(f"{line['speaker']}: {line['text']}")

    dialogue_text = "\n".join(dialogues[:10])  # 最初の10セリフ

    prompt = f"""
あなたはラジオを聴いているおばあちゃんです。
カツミさんとヒロシさんの年金ニュースの対談を聞いて、一言感想を言ってください。

【対談内容】
{dialogue_text}

【おばあちゃんの設定】
- おっとりした優しい口調
- 年金のことはよくわからないけど、毎日聴いている
- 「〜わねぇ」「〜かしら」「〜だわ」などの語尾

【コメント例】
「あらあら、年金のこと、そんなものなのかしらねぇ...」
「ヒロシさんの気持ち、わかるわぁ。私も年金のことよくわからないもの」
「カツミさんの説明、わかりやすかったわねぇ」
「今日も勉強になったわ。お茶でも飲みながらまた聞くわね」

【出力】
おばあちゃんの一言コメントを50文字以内で出力してください。
コメントのみを出力し、他の説明は不要です。
"""

    try:
        response = model.generate_content(prompt)
        comment = response.text.strip()
        # 余分な引用符を削除
        comment = comment.strip('"\'「」『』')
        # 50文字に制限
        if len(comment) > 50:
            comment = comment[:47] + "..."
        print(f"  [コメント生成] おばあちゃん: {comment}")
        return comment
    except Exception as e:
        print(f"  ⚠ コメント生成エラー: {e}")
        return ""


def generate_first_comment(script: dict, news_data: dict, key_manager: GeminiKeyManager) -> str:
    """台本から初コメントを取得（LINE URLを追加）

    Args:
        script: 台本データ（first_commentフィールドを含む）
        news_data: ニュースデータ（未使用、互換性のため保持）
        key_manager: APIキーマネージャー（未使用、互換性のため保持）

    Returns:
        str: カツミのコメント（LINE URL付き）
    """
    LINE_URL = "https://lin.ee/SrziaPE"

    # 台本からfirst_commentを取得
    comment = script.get("first_comment", "")

    if not comment:
        # フォールバック: 固定コメント
        print("  ⚠ first_commentが台本にないためフォールバック使用")
        comment = """カツミです💕
今日も見てくれてありがとう！
年金の話って難しいけど、知らないと損しちゃうからね。
毎日11時にLINEで届くから、届いてない人は登録してね〜"""

    # LINE URLを追加
    comment = f"{comment}\n\n↓ LINE登録はこちら ↓\n{LINE_URL}"

    print(f"  [コメント生成] カツミ: {comment[:50]}...")
    return comment


# ===== サムネイル設定 =====
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720


def generate_video_title(script: dict, key_manager: GeminiKeyManager) -> str:
    """YouTube動画タイトルを生成（Gemini API）

    Args:
        script: 台本データ
        key_manager: APIキーマネージャー

    Returns:
        str: 動画タイトル（形式: [キーワード]｜[日付]）
    """
    from datetime import datetime
    date_str = datetime.now().strftime('%Y年%m月%d日')
    default_title = f"今日の年金ニュース｜{date_str}"

    api_key, key_name = key_manager.get_working_key()
    if not api_key:
        return default_title

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    # ニュースタイトルを取得
    news_titles = []
    for section in script.get("news_sections", []):
        title = section.get("news_title", "")
        if title:
            news_titles.append(title)

    news_text = "\n".join(news_titles) if news_titles else "年金ニュース"

    prompt = f"""
今日の年金ニュースから、視聴者が気になるキーワードを抽出してYouTube動画タイトルを生成してください。

【今日のニュース】
{news_text}

【形式】
[気になるキーワード・話題]｜{date_str}

【トーン】
- 落ち着いた、信頼感のある表現
- 高齢者に優しく、不快に感じない言葉選び
- 煽りすぎない、冷静なトーン

【良い例】
- 「年金2%増額の真相とは｜{date_str}」
- 「繰り下げ受給で得する人・損する人｜{date_str}」
- 「iDeCo改正で変わること｜{date_str}」
- 「知らないと損する年金の基礎知識｜{date_str}」

【NG】
- 「！」「？」「緊急」「衝撃」「崩壊」等の過激な表現
- 煽りすぎる表現
- 日付を先頭に置く

【出力】
タイトルのみを出力してください（日付部分「｜{date_str}」は含めない）。
"""

    try:
        response = model.generate_content(prompt)
        keyword = response.text.strip().strip('"\'「」『』')
        # 日付が含まれていたら削除
        if "｜" in keyword:
            keyword = keyword.split("｜")[0].strip()
        if len(keyword) > 35:
            keyword = keyword[:32] + "..."
        title = f"{keyword}｜{date_str}"
        print(f"  [動画タイトル] {title}")
        return title
    except Exception as e:
        print(f"  ⚠ 動画タイトル生成エラー: {e}")
        return default_title


def generate_thumbnail_title(script: dict, key_manager: GeminiKeyManager) -> str:
    """サムネイル用のキャッチーなタイトルを生成（Gemini API）

    Args:
        script: 台本データ
        key_manager: APIキーマネージャー

    Returns:
        str: キャッチーなタイトル（20文字以内）
    """
    api_key, key_name = key_manager.get_working_key()
    if not api_key:
        return "今日の年金ニュース"

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    # ニュースタイトルを取得
    news_titles = []
    for section in script.get("news_sections", []):
        title = section.get("news_title", "")
        if title:
            news_titles.append(title)

    news_text = "\n".join(news_titles) if news_titles else "年金ニュース"

    prompt = f"""
以下の年金ニュースから、YouTubeサムネイル用のキャッチーなタイトルを作成してください。

【今日のニュース】
{news_text}

【条件】
- 15〜20文字以内
- 視聴者の興味を引く表現
- 「！」「？」「...」などを効果的に使う
- 年金受給者が気になるワードを入れる

【例】
「年金が増える!? 新制度の真実」
「知らないと損！年金の落とし穴」
「65歳以上必見！今月の年金情報」

【出力】
タイトルのみを出力してください。
"""

    try:
        response = model.generate_content(prompt)
        title = response.text.strip().strip('"\'「」『』')
        if len(title) > 25:
            title = title[:22] + "..."
        print(f"  [サムネ] タイトル: {title}")
        return title
    except Exception as e:
        print(f"  ⚠ サムネタイトル生成エラー: {e}")
        return "今日の年金ニュース"


def generate_thumbnail(bg_image_path: str, title: str, output_path: str) -> bool:
    """サムネイル画像を生成

    Args:
        bg_image_path: 背景画像のパス
        title: サムネイルタイトル
        output_path: 出力パス

    Returns:
        bool: 成功したかどうか
    """
    try:
        # 背景画像を読み込み
        if os.path.exists(bg_image_path):
            bg = Image.open(bg_image_path)
            bg = bg.resize((THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.LANCZOS)
        else:
            # フォールバック: ベージュ系グラデーション
            bg = Image.new('RGB', (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT))
            draw = ImageDraw.Draw(bg)
            for y in range(THUMBNAIL_HEIGHT):
                ratio = y / THUMBNAIL_HEIGHT
                r = int(245 - ratio * 15)
                g = int(235 - ratio * 20)
                b = int(220 - ratio * 25)
                draw.line([(0, y), (THUMBNAIL_WIDTH, y)], fill=(r, g, b))

        draw = ImageDraw.Draw(bg)

        # 半透明の茶色バー（下部40%）
        bar_height = int(THUMBNAIL_HEIGHT * 0.40)
        bar_y = THUMBNAIL_HEIGHT - bar_height
        bar_overlay = Image.new('RGBA', (THUMBNAIL_WIDTH, bar_height), (60, 40, 30, 200))
        bg.paste(bar_overlay, (0, bar_y), bar_overlay)

        # フォント設定（日本語対応）
        font_paths = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
            "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        ]

        font = None
        font_size = 72
        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    font = ImageFont.truetype(font_path, font_size)
                    break
                except:
                    continue

        if font is None:
            font = ImageFont.load_default()
            font_size = 40

        # タイトルテキストを描画（中央配置）
        draw = ImageDraw.Draw(bg)

        # テキストのバウンディングボックスを取得
        bbox = draw.textbbox((0, 0), title, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # 中央配置
        x = (THUMBNAIL_WIDTH - text_width) // 2
        y = bar_y + (bar_height - text_height) // 2

        # 白文字で描画
        draw.text((x, y), title, font=font, fill=(255, 255, 255))

        # 日付を小さく追加
        date_text = datetime.now().strftime('%Y/%m/%d')
        date_font_size = 36
        date_font = None
        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    date_font = ImageFont.truetype(font_path, date_font_size)
                    break
                except:
                    continue

        if date_font:
            date_bbox = draw.textbbox((0, 0), date_text, font=date_font)
            date_x = THUMBNAIL_WIDTH - (date_bbox[2] - date_bbox[0]) - 30
            date_y = 20
            draw.text((date_x, date_y), date_text, font=date_font, fill=(255, 255, 255))

        # 保存
        bg = bg.convert('RGB')
        bg.save(output_path, 'JPEG', quality=95)
        print(f"  [サムネ] ✓ 生成完了: {output_path}")
        return True

    except Exception as e:
        print(f"  ⚠ サムネイル生成エラー: {e}")
        return False


def set_youtube_thumbnail(video_id: str, thumbnail_path: str) -> bool:
    """YouTubeにサムネイルを設定

    Args:
        video_id: 動画ID
        thumbnail_path: サムネイル画像のパス

    Returns:
        bool: 成功したかどうか
    """
    if not os.path.exists(thumbnail_path):
        print(f"  ⚠ サムネイル画像が見つかりません: {thumbnail_path}")
        return False

    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN_23")

    if not all([client_id, client_secret, refresh_token]):
        print("  ⚠ YouTube認証情報が不足のためサムネイル設定をスキップ")
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

        from google.oauth2.credentials import Credentials as OAuthCredentials
        creds = OAuthCredentials(
            token=access_token,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token"
        )
        youtube = build("youtube", "v3", credentials=creds)

        # サムネイルをアップロード
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path, mimetype='image/jpeg')
        ).execute()

        print(f"  ✓ YouTubeサムネイル設定完了")
        return True

    except Exception as e:
        print(f"  ⚠ YouTubeサムネイル設定エラー: {e}")
        return False


def post_youtube_comment(video_id: str, comment_text: str) -> bool:
    """YouTubeに最初のコメントを投稿

    Args:
        video_id: 動画ID
        comment_text: コメント内容

    Returns:
        bool: 成功したかどうか
    """
    if not comment_text:
        print("  ⚠ コメントが空のためスキップ")
        return False

    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN_23")

    if not all([client_id, client_secret, refresh_token]):
        print("  ⚠ YouTube認証情報が不足のためコメント投稿をスキップ")
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

        from google.oauth2.credentials import Credentials as OAuthCredentials
        creds = OAuthCredentials(
            token=access_token,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token"
        )
        youtube = build("youtube", "v3", credentials=creds)

        # コメント投稿
        comment_body = {
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
            body=comment_body
        ).execute()

        print(f"  ✓ YouTubeコメント投稿完了")
        return True

    except Exception as e:
        print(f"  ⚠ YouTubeコメント投稿エラー: {e}")
        return False


def send_discord_error_notification(error_message: str, title: str = ""):
    """Discord通知を送信（エラー時のみ）"""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("  ⚠ DISCORD_WEBHOOK_URL未設定のため通知をスキップ")
        return

    message = f"""❌ **年金ニュース生成エラー**
━━━━━━━━━━━━━━━━━━
📺 タイトル: {title if title else '未生成'}
⚠️ エラー: {error_message}"""

    try:
        response = requests.post(
            webhook_url,
            json={"content": message},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        if response.status_code in [200, 204]:
            print("  ✓ Discord エラー通知送信完了")
        else:
            print(f"  ⚠ Discord通知失敗: {response.status_code}")
    except Exception as e:
        print(f"  ⚠ Discord通知エラー: {e}")


def send_slack_script_notification(script: dict, scheduled_time: str = "11:00"):
    """台本をSlackに送信"""
    webhook_url = os.environ.get("SLACK_WEBHOOK_SCRIPT")
    if not webhook_url:
        print("  ⚠ SLACK_WEBHOOK_SCRIPT未設定のため台本通知をスキップ")
        return

    title = script.get("title", "タイトル未定")

    # 台本テキストを生成
    script_lines = []

    # オープニング
    for line in script.get("opening", []):
        speaker = line.get("speaker", "")
        text = line.get("text", "")
        script_lines.append(f"{speaker}: {text}")

    # ニュースセクション
    for section in script.get("news_sections", []):
        for line in section.get("dialogue", []):
            speaker = line.get("speaker", "")
            text = line.get("text", "")
            script_lines.append(f"{speaker}: {text}")

    # 噂セクション
    for line in script.get("rumor_section", []):
        speaker = line.get("speaker", "")
        text = line.get("text", "")
        script_lines.append(f"{speaker}: {text}")

    # エンディング
    for line in script.get("ending", []):
        speaker = line.get("speaker", "")
        text = line.get("text", "")
        script_lines.append(f"{speaker}: {text}")

    script_text = "\n".join(script_lines)

    message = f"""📺 本日の動画台本

【タイトル】{title}

【投稿予定】{scheduled_time} JST

【台本】
{script_text}"""

    try:
        response = requests.post(
            webhook_url,
            json={"text": message},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        if response.status_code in [200, 204]:
            print("  ✓ Slack台本通知送信完了")
        else:
            print(f"  ⚠ Slack通知失敗: {response.status_code}")
    except Exception as e:
        print(f"  ⚠ Slack通知エラー: {e}")


def generate_community_post(news_data: dict, key_manager: GeminiKeyManager) -> dict:
    """YouTubeコミュニティ投稿案を生成

    Args:
        news_data: ニュースデータ
        key_manager: APIキーマネージャー

    Returns:
        dict: {"question": "質問文", "options": ["選択肢1", "選択肢2", ...]}
    """
    print("\n[コミュニティ投稿案] 生成中...")

    api_key, key_name = key_manager.get_working_key()
    if not api_key:
        print("  ⚠ APIキーがないためスキップ")
        return None

    # ニュース要約を取得
    news_titles = []
    for news in news_data.get("confirmed", [])[:3]:
        news_titles.append(f"・{news.get('title', '')}")
    news_summary = "\n".join(news_titles) if news_titles else "今日の年金ニュース"

    prompt = f"""あなたは年金ニュースチャンネルの運営者です。
今日の年金ニュースに関連した、視聴者参加型のアンケート投稿を作ってください。

【今日のニュース】
{news_summary}

【ルール】
- 損得・賛否・経験を聞く形式
- 高齢者が答えやすいシンプルな質問
- 選択肢は2〜4個
- 「正直に聞きます」「皆さんに質問です」など親しみやすい書き出し
- 絵文字は控えめ（1〜2個）

【出力形式】必ずこの形式で出力してください：
質問文:
〇〇〇〇？

選択肢:
1. △△△
2. □□□
3. ▲▲▲"""

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            text = response.text.strip()

            # パース
            question = ""
            options = []

            lines = text.split("\n")
            in_options = False

            for line in lines:
                line = line.strip()
                if line.startswith("質問文:") or line.startswith("質問文："):
                    continue
                elif line.startswith("選択肢:") or line.startswith("選択肢："):
                    in_options = True
                    continue
                elif in_options:
                    # 選択肢をパース（1. 2. 3. 形式）
                    if line and (line[0].isdigit() or line.startswith("・")):
                        option = line.lstrip("0123456789.・ ")
                        if option:
                            options.append(option)
                elif not in_options and line and "?" in line or "？" in line:
                    question = line
                elif not in_options and line and not question:
                    question = line

            if question and len(options) >= 2:
                print(f"  ✓ 質問: {question[:40]}...")
                print(f"  ✓ 選択肢: {len(options)}個")
                return {"question": question, "options": options}

        except Exception as e:
            error_str = str(e)
            print(f"  ⚠ 試行{attempt + 1}/{max_retries} 失敗: {error_str[:50]}...")
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                api_key, key_name = key_manager.get_working_key()
                if api_key:
                    genai.configure(api_key=api_key)
                time.sleep(5)
            else:
                time.sleep(3)

    print("  ⚠ コミュニティ投稿案の生成に失敗")
    return None


def create_community_image(question: str, output_path: str) -> str:
    """コミュニティ投稿用画像を生成

    Args:
        question: 質問文
        output_path: 出力パス

    Returns:
        str: 生成した画像のパス
    """
    from PIL import Image, ImageDraw, ImageFont
    import textwrap

    # 画像サイズ（YouTubeコミュニティ投稿用 1200x675推奨）
    width = 1200
    height = 675

    # ベース画像を作成（温かみのあるベージュ系）
    img = Image.new('RGB', (width, height), '#FFF8E7')
    draw = ImageDraw.Draw(img)

    # 上部に赤いバー
    draw.rectangle([0, 0, width, 80], fill='#CC0000')

    # フォント設定
    try:
        font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
        if not os.path.exists(font_path):
            font_path = "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"
        title_font = ImageFont.truetype(font_path, 42)
        main_font = ImageFont.truetype(font_path, 56)
        sub_font = ImageFont.truetype(font_path, 32)
    except:
        title_font = ImageFont.load_default()
        main_font = ImageFont.load_default()
        sub_font = ImageFont.load_default()

    # 上部バーのテキスト
    title_text = "📊 みんなに聞いてみた！"
    bbox = draw.textbbox((0, 0), title_text, font=title_font)
    text_width = bbox[2] - bbox[0]
    draw.text((width // 2 - text_width // 2, 20), title_text, fill='white', font=title_font)

    # 質問文を改行処理（20文字で折り返し）
    wrapped_lines = []
    for line in question.split('\n'):
        wrapped_lines.extend(textwrap.wrap(line, width=20))

    # メイン質問テキスト（中央配置）
    y_pos = 200
    line_height = 80
    for line in wrapped_lines[:4]:  # 最大4行
        bbox = draw.textbbox((0, 0), line, font=main_font)
        text_width = bbox[2] - bbox[0]
        draw.text((width // 2 - text_width // 2, y_pos), line, fill='#333333', font=main_font)
        y_pos += line_height

    # 下部にチャンネル名
    channel_text = "毎日届く！得する年金ニュース速報"
    bbox = draw.textbbox((0, 0), channel_text, font=sub_font)
    text_width = bbox[2] - bbox[0]
    draw.text((width // 2 - text_width // 2, height - 60), channel_text, fill='#888888', font=sub_font)

    # 装飾（角に年金マーク風）
    draw.text((40, 110), "💰", font=main_font)
    draw.text((width - 100, 110), "💰", font=main_font)

    # 保存
    img.save(output_path, 'PNG')
    print(f"  ✓ コミュニティ画像生成: {output_path}")
    return output_path


def send_community_post_to_slack(post_data: dict, title: str = "", video_url: str = ""):
    """コミュニティ投稿案をSlackに送信（2種類の投稿案）

    Args:
        post_data: {"question": "質問文", "options": ["選択肢1", "選択肢2", ...]}
        title: 動画タイトル
        video_url: 動画URL
    """
    if not post_data:
        return

    webhook_url = os.environ.get("SLACK_WEBHOOK_COMMUNITY")
    if not webhook_url:
        print("  ⚠ SLACK_WEBHOOK_COMMUNITY未設定のためスキップ")
        return

    question = post_data.get("question", "")
    options = post_data.get("options", [])

    # 選択肢を整形
    options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])

    # コミュニティ投稿用画像を生成（ローカル保存）
    today = datetime.now().strftime("%Y%m%d")
    image_path = f"community_post_news_{today}.png"
    create_community_image(question, image_path)
    print(f"  ✓ コミュニティ画像生成: {image_path}")

    # 【投稿案1】ハイプ呼びかけ投稿
    hype_message = f"""📺 *【投稿案1】ハイプ呼びかけ*

今日の年金ニュース投稿しました！

{title}

🔥 この動画が役に立ったら「ハイプ」で応援お願いします！
（週3回まで無料・いいねボタンの横にあります）

▶️ {video_url}"""

    # 【投稿案2】アンケート投稿
    survey_message = f"""📊 *【投稿案2】アンケート投稿*

【質問文】コピペ用👇
{question}

【選択肢】
{options_text}

▶️ 投稿はこちら
https://studio.youtube.com/channel/UCcjf76-saCvRAkETlieeokw/community"""

    # 両方を1つのメッセージで送信
    combined_message = f"""{hype_message}

━━━━━━━━━━━━━━━━━━━━

{survey_message}"""

    try:
        payload = {"text": combined_message}
        response = requests.post(webhook_url, json=payload, timeout=30)

        if response.status_code == 200:
            print("  ✓ コミュニティ投稿案（2種類）をSlackに送信完了")
        else:
            print(f"  ⚠ Slack送信失敗: {response.status_code}")
    except Exception as e:
        print(f"  ⚠ Slack送信エラー: {e}")


def send_first_comment_to_slack(title: str, topics: list = None):
    """初コメント案をSlackに送信（カツミの人格で）

    Args:
        title: 動画タイトル
        topics: ニューストピックのリスト
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_COMMENT")
    if not webhook_url:
        print("  ⚠ SLACK_WEBHOOK_COMMENT未設定のためスキップ")
        return

    # トピックがあれば最初のものを使用
    topic_text = ""
    if topics and len(topics) > 0:
        topic_text = topics[0].get("title", "") if isinstance(topics[0], dict) else str(topics[0])

    # カツミの人格で初コメントを作成
    comment_templates = [
        f"今日もご視聴ありがとうございます✨\n\n{topic_text}について、皆さんはどう思われますか？\n\nコメント欄で教えていただけると嬉しいです🙏",
        f"カツミです！今日の動画はいかがでしたか？\n\n{topic_text}、気になっていた方も多いのではないでしょうか。\n\n感想やご質問があればお気軽にコメントください😊",
        f"ご視聴いただきありがとうございます！\n\n今日は{topic_text}についてお伝えしました。\n\n「ここがよくわからなかった」「もっと詳しく知りたい」など、何でもコメントお待ちしています✨",
    ]

    import random
    comment = random.choice(comment_templates)

    message = f"""💬 *【初コメント案】年金ニュース*

📺 {title}

━━━━━━━━━━━━━━━━━━━━

{comment}

━━━━━━━━━━━━━━━━━━━━

※ カツミの人格で書いています
※ 動画公開後すぐにコメント欄に投稿してください"""

    try:
        payload = {"text": message}
        response = requests.post(webhook_url, json=payload, timeout=30)

        if response.status_code == 200:
            print("  ✓ 初コメント案をSlackに送信完了")
        else:
            print(f"  ⚠ Slack送信失敗: {response.status_code}")
    except Exception as e:
        print(f"  ⚠ Slack送信エラー: {e}")


def main():
    """メイン処理"""
    start_time = time.time()  # 処理開始時刻

    print("=" * 50)
    print("年金ニュース動画生成システム")
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"モード: {'🧪 テストモード（短縮版）' if TEST_MODE else '📺 本番モード（フル版）'}")
    if TTS_MODE == "google_cloud":
        print(f"TTS: Google Cloud TTS (WaveNet)")
        print(f"ボイス: カツミ={GCLOUD_VOICE_KATSUMI}, ヒロシ={GCLOUD_VOICE_HIROSHI}")
    else:
        print(f"TTS: Gemini TTS ({GEMINI_TTS_MODEL})")
        print(f"ボイス: カツミ={GEMINI_VOICE_KATSUMI}, ヒロシ={GEMINI_VOICE_HIROSHI}")
    print("=" * 50)

    key_manager = GeminiKeyManager()
    print(f"利用可能なAPIキー: {len(key_manager.get_all_keys())}個")

    # 処理開始をログに記録
    log_to_spreadsheet(status="処理開始")

    # 1. ニュース検索（Web検索機能付き）
    print("\n[1/4] 年金ニュースを検索中...")
    news_data = search_pension_news(key_manager)

    # テストモード: ニュースを3件に制限（本番と同じ流れで短縮版）
    if TEST_MODE:
        if news_data.get("confirmed"):
            news_data["confirmed"] = news_data["confirmed"][:3]
        if news_data.get("rumor"):
            news_data["rumor"] = news_data["rumor"][:1]  # 噂は1件
        print("  [テスト] ニュースを3件+噂1件に制限")

    news_count = len(news_data.get("confirmed", [])) + len(news_data.get("rumor", []))

    if not news_data.get("confirmed") and not news_data.get("rumor"):
        print("❌ ニュースが見つかりませんでした")
        log_to_spreadsheet(status="エラー", error_message="ニュースが見つかりませんでした")
        return

    # 2. 台本生成
    print("\n[2/4] 台本を生成中...")
    script = generate_script(news_data, key_manager, test_mode=TEST_MODE)
    if not script:
        print("❌ 台本生成に失敗しました")
        log_to_spreadsheet(status="エラー", news_count=news_count, error_message="台本生成に失敗しました")
        return

    # 2.5 3重ファクトチェック
    print("\n[2.5/4] 3重ファクトチェック実行中...")
    script = triple_fact_check(script, news_data, key_manager)

    # 2.6 台本をSlackに送信
    if not TEST_MODE:
        print("\n[2.6/4] 台本をSlackに送信中...")
        send_slack_script_notification(script, scheduled_time="11:00")

    # セリフ数をカウント
    dialogue_count = len(script.get("opening", []))
    for section in script.get("news_sections", []):
        dialogue_count += len(section.get("dialogue", []))
    dialogue_count += len(script.get("rumor_section", []))
    dialogue_count += len(script.get("ending", []))
    print(f"  生成されたセリフ数: {dialogue_count}セリフ")

    # 控室トークをスプレッドシートに保存（ショート動画用）
    green_room = script.get("green_room", [])
    if green_room:
        save_green_room_content(green_room, script.get("title", ""))

    # テストモード: 台本を短縮（安全措置として残す）
    if TEST_MODE and dialogue_count > 20:
        if script.get("opening"):
            script["opening"] = script["opening"][:3]
        if script.get("news_sections"):
            for section in script["news_sections"]:
                if section.get("dialogue"):
                    section["dialogue"] = section["dialogue"][:4]
        if script.get("ending"):
            script["ending"] = script["ending"][:2]
        print("  [テスト] 台本を短縮（約12〜15セリフ）")

    # 3. 動画生成
    print("\n[3/4] 動画を生成中...")
    video_duration = 0.0

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        video_path, _ = create_video(script, temp_path, key_manager)

        # 動画の長さを取得
        result = subprocess.run([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', video_path
        ], capture_output=True, text=True)
        video_duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0

        # 4. サムネイル生成
        print("\n[4/7] サムネイルを生成中...")
        thumbnail_path = str(temp_path / "thumbnail.jpg")
        bg_path = str(temp_path / "background.png")
        thumbnail_title = generate_thumbnail_title(script, key_manager)
        generate_thumbnail(bg_path, thumbnail_title, thumbnail_path)

        # 5. YouTube投稿
        print("\n[5/7] YouTubeに投稿中...")
        title = generate_video_title(script, key_manager)
        # タイトルの改行削除・100文字制限
        title = title.replace("\n", " ").replace("\r", "").strip()
        if len(title) > 100:
            title = title[:97] + "..."

        # 概要欄（海外メディア超多読ラジオ風フォーマット）
        date_str = datetime.now().strftime('%Y年%m月%d日')

        # 1. 冒頭（ヘッダー + チャンネル紹介）
        header = f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n📺 年金ニュース解説チャンネル\n📅 {date_str}\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        # 2. 本文（動画の概要）
        script_desc = script.get("description", "今日の年金ニュースをお届けします。")
        summary_section = f"【今日の内容】\n{script_desc}\n\n"

        # 3. 主要ポイント（ニュースの見出しから抽出）
        key_points_lines = []
        confirmed_news = news_data.get("confirmed", [])
        rumor_news = news_data.get("rumor", [])

        for i, news in enumerate(confirmed_news[:5]):  # 最大5件
            key_points_lines.append(f"✅ {news.get('title', '')}")
        for news in rumor_news[:2]:  # 噂は最大2件
            key_points_lines.append(f"💭 {news.get('title', '')}（参考情報）")

        key_points_section = ""
        if key_points_lines:
            key_points_section = "【主要ポイント】\n" + "\n".join(key_points_lines) + "\n\n"

        # 4. 参考ソース
        sources = news_data.get("sources", [])
        source_section = ""
        if sources:
            source_lines = []
            seen_urls = set()
            for src in sources:
                url = src.get("url", "")
                if url and url not in seen_urls:
                    source_name = src.get("source", "参照元")
                    source_lines.append(f"・{source_name}\n   {url}")
                    seen_urls.add(url)
            if source_lines:
                source_section = "【参考ソース】\n" + "\n".join(source_lines) + "\n\n"

        # 5. ハッシュタグ
        hashtags = "#年金 #年金ニュース #厚生年金 #国民年金 #老後 #シニア #iDeCo #NISA #年金解説 #社会保険"

        # 6. LINE誘導
        line_section = """

━━━━━━━━━━━━━━━━━━━━
🎁 LINE登録で無料プレゼント！
━━━━━━━━━━━━━━━━━━━━

「年金だけじゃ足りない…」そんな不安ありませんか？

カツミとヒロシが作った
『新NISA超入門ガイド』をプレゼント中🎁

▼ 友だち追加で今すぐ受け取る
https://lin.ee/SrziaPE

━━━━━━━━━━━━━━━━━━━━
📺 ご視聴ありがとうございます！

「自分の年金、ちゃんともらえるか不安…」
そんな方のために、かんたん診断を作りました🎁

▼ あなたの年金、損してない？
https://konkon034034.github.io/nenkin-shindan/

LINE登録で毎日の年金ニュースも届きます📱
👉 https://lin.ee/SrziaPE
━━━━━━━━━━━━━━━━━━━━
"""

        # 7. 免責事項
        disclaimer = "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n【免責事項】\nこの動画は一般的な情報提供を目的としており、個別の年金相談や専門的なアドバイスを行うものではありません。正確な情報は年金事務所や専門家にご確認ください。\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

        # 概要欄を組み立て
        description = header + summary_section + key_points_section + source_section + hashtags + line_section + disclaimer

        # YouTube説明文の制限（5000文字、無効文字除去）
        description = description.replace("<", "").replace(">", "")  # 無効文字除去
        if len(description) > 4900:
            description = description[:4900] + "\n\n..."
        print(f"  説明文: {len(description)}文字")

        tags = script.get("tags", ["年金", "ニュース", "シニア"])

        # SKIP_UPLOAD環境変数でアップロードをスキップ
        skip_upload = os.environ.get("SKIP_UPLOAD", "").lower() == "true"

        if skip_upload:
            print("\n[6/7] アップロードをスキップ（SKIP_UPLOAD=true）")
            # 動画をカレントディレクトリにコピー（Artifacts用）
            import shutil
            output_file = f"nenkin_news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            shutil.copy(video_path, output_file)
            video_url = f"file://{os.path.abspath(output_file)}"
            # 動画パスをファイルに保存（確認用）
            with open("video_url.txt", "w") as f:
                f.write(video_url)
            with open("video_title.txt", "w") as f:
                f.write(title)
            print(f"  動画ファイル: {output_file}")
            print(f"  タイトル: {title}")
            print("  ✓ Artifactsから動画をダウンロードして確認してください")
        else:
            try:
                video_url = upload_to_youtube(video_path, title, description, tags)

                # 動画URL・タイトルをファイルに保存（ワークフロー通知用）
                with open("video_url.txt", "w") as f:
                    f.write(video_url)
                with open("video_title.txt", "w") as f:
                    f.write(title)

                # 動画IDを抽出
                video_id = video_url.split("v=")[-1] if "v=" in video_url else ""

                # サムネイルを設定
                if video_id and os.path.exists(thumbnail_path):
                    print("\n[6/7] サムネイルを設定中...")
                    set_youtube_thumbnail(video_id, thumbnail_path)

                # 最初のコメントを生成・投稿（70代老夫婦の視点）
                first_comment = ""
                if video_id:
                    print("\n[6.5/7] 最初のコメントを生成・投稿中...")
                    first_comment = generate_first_comment(script, news_data, key_manager)
                    if first_comment:
                        post_youtube_comment(video_id, first_comment)

                # 処理時間を計算
                processing_time = time.time() - start_time

                # 成功をログに記録
                log_to_spreadsheet(
                    status="成功",
                    title=title,
                    url=video_url,
                    news_count=news_count,
                    processing_time=processing_time
                )

                # 使用済みニュースタイトルを保存（重複防止用）
                used_news_titles = []
                for section in script.get("news_sections", []):
                    news_title = section.get("news_title", "")
                    if news_title:
                        used_news_titles.append(news_title)
                if used_news_titles:
                    save_used_news_titles(used_news_titles)

                # コメント内容を表示
                if first_comment:
                    print(f"\n📝 最初のコメント: {first_comment}")

                # コミュニティ投稿案を生成・送信（テストモード以外）
                if not TEST_MODE and video_id:
                    community_post = generate_community_post(news_data, key_manager)
                    if community_post:
                        send_community_post_to_slack(community_post, title, video_url)

                    # 初コメント案を送信
                    topics = news_data.get("news", []) if news_data else []
                    send_first_comment_to_slack(title, topics)

            except Exception as e:
                print(f"❌ YouTube投稿エラー: {e}")
                # エラーをログに記録
                processing_time = time.time() - start_time
                log_to_spreadsheet(
                    status="エラー",
                    title=title,
                    news_count=news_count,
                    processing_time=processing_time,
                    error_message=str(e)
                )
                # Discord エラー通知
                if not TEST_MODE:
                    send_discord_error_notification(str(e), title)
                # ローカルに保存
                import shutil
                output_file = f"nenkin_news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
                shutil.copy(video_path, output_file)
                print(f"   ローカル保存: {output_file}")


if __name__ == "__main__":
    main()
