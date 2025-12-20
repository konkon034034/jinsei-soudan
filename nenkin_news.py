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
from datetime import datetime
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
CHANNEL_NAME = "毎朝届く！おはよう年金ニュースラジオ"
CHANNEL_DESCRIPTION = "毎朝7時、年金に関する最新ニュースをお届けします"

# ===== Gemini TTS設定 =====
GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"

# TTS音声設定（環境変数でカスタマイズ可能）
# 利用可能: Puck, Charon, Kore, Fenrir, Aoede
TTS_VOICE_FEMALE = os.environ.get("TTS_VOICE_FEMALE", "Kore")
TTS_VOICE_MALE = os.environ.get("TTS_VOICE_MALE", "Puck")

# TTS指示文（環境変数でカスタマイズ可能）
# 声質・トーン・スピードを詳細に指定して一貫性を確保
DEFAULT_TTS_INSTRUCTION = """あなたはプロフェッショナルな年金ニュース番組のパーソナリティです。

【重要な指示 - 必ず従ってください】
- 番組全体を通して、各キャラクターの声質・トーン・スピードを完全に一貫させてください
- 途中で声の高さや話し方が変わらないように注意してください
- 自然で聞き取りやすい日本語で話してください

【カツミの声の特徴（{voice_female}音声を使用）】
- 60代女性の落ち着いた声
- トーン: 低め、温かみがある、信頼感がある
- スピード: ゆっくり目（1.0倍速）
- 感情: 穏やか、優しい、説明的
- 話し方: 丁寧語、専門家らしい説得力

【ヒロシの声の特徴（{voice_male}音声を使用）】
- 60代男性の素朴な声
- トーン: 中程度、明るい、親しみやすい
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
# カツミ（女性）: 年金に詳しい説明役。落ち着いた優しい口調。
GEMINI_VOICE_KATSUMI = TTS_VOICE_FEMALE

# ヒロシ（男性）: 年金に詳しくない聞き役。ちょっとお馬鹿で素朴な疑問を聞く。
GEMINI_VOICE_HIROSHI = TTS_VOICE_MALE

# ===== Google Cloud TTS設定 =====
# カツミ（女性）: ja-JP-Wavenet-A
GCLOUD_VOICE_KATSUMI = "ja-JP-Wavenet-A"
# ヒロシ（男性）: ja-JP-Wavenet-D
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
    "高所得": "こうしょとく",
    "超える": "こえる",
    "超えて": "こえて",
    "超えた": "こえた",
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


def fix_reading(text: str) -> str:
    """読み方辞書でテキストを変換（TTS用）"""
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
        for i in range(1, 10):
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


# 信頼度の高いソース（confirmed情報として扱う）
TRUSTED_SOURCES = [
    "厚生労働省", "mhlw.go.jp",
    "日本年金機構", "nenkin.go.jp",
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

    prompt = """
あなたは年金ニュースの専門リサーチャーです。
今日の日本の年金に関する最新ニュースをWeb検索で調べて、以下のJSON形式で出力してください。

【検索クエリ例】
- 年金 最新ニュース 2024
- 厚生年金 改正
- 年金受給 変更

【優先する情報源】（信頼度高い順）
1. 厚生労働省 (mhlw.go.jp)
2. 日本年金機構 (nenkin.go.jp)
3. NHK (nhk.or.jp)
4. 日本経済新聞 (nikkei.com)
5. 読売新聞 (yomiuri.co.jp)
6. 朝日新聞 (asahi.com)
7. Yahoo!ニュース（参考程度）

【出力形式】
```json
{
  "news": [
    {
      "title": "ニュースタイトル",
      "summary": "ニュースの要約（100文字程度）",
      "source": "情報源名（例: 厚生労働省、NHK）",
      "url": "参照元URL（わかる場合）",
      "reliability": "high または low",
      "impact": "年金受給者への影響（50文字程度）"
    }
  ]
}
```

【注意】
- 最新のニュースを優先（過去1週間以内）
- 年金受給者に関係する内容を選ぶ
- 公式ソースからのニュースを5〜8件（できるだけ多く）
- 噂・未確定情報も2〜3件含める（reliabilityをlowに）
- URLは可能な限り含める
- ニュースは多ければ多いほど良い（30分番組に使用）
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

            # 信頼度で分類
            confirmed = []
            rumor = []
            sources = []

            for news in news_list:
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
        f"【確定ニュース{i+1}】{n['title']}\n{n['summary']}\n影響: {n.get('impact', '不明')}\n出典: {n.get('source', '不明')}"
        for i, n in enumerate(confirmed_news)
    ]) if confirmed_news else "（確定情報なし）"

    rumor_text = "\n".join([
        f"【噂・参考情報{i+1}】{n['title']}\n{n['summary']}"
        for i, n in enumerate(rumor_news)
    ]) if rumor_news else "（噂情報なし）"

    news_text = f"■ 確定情報（公式ソース）\n{confirmed_text}\n\n■ 噂・参考情報\n{rumor_text}"

    # 今日の日付
    today = datetime.now()
    date_str = f"{today.month}月{today.day}日"

    prompt = f"""
あなたは年金ニュース番組の台本作家です。
以下のニュースを元に、カツミとヒロシの掛け合い台本を作成してください。

【登場人物】
- カツミ（60代女性）: 年金の専門家、解説役。優しく丁寧だけど、最後に本音（ぼやき・毒舌）が出る。
- ヒロシ（60代男性）: 視聴者代弁、素朴な疑問を聞く。ちょっとお馬鹿。最後にカツミにツッコミを入れる。

【ニュース情報】
{news_text}

【台本構成】
1. オープニング
   - 「おはようございます。{date_str}の年金ニュースをお届けします」
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
    {{"speaker": "カツミ", "text": "おはようございます。{date_str}の年金ニュースをお届けします"}},
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
  ]
}}
```

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
- 難しい用語は必ず言い換えor説明（例：iDeCo、つまり個人型確定拠出年金）
- 出典を明記（厚生労働省、日本年金機構、NHK、日経新聞等）
- 具体的な金額・日付・%を入れる
- 確定情報メイン、噂は「〜らしいですよ」と軽く
- ヒロシは視聴者が思いそうな疑問を代弁（ちょっとお馬鹿な感じで）
- 【重要】本編エンディングは丁寧モード、控え室は素のタメ口モード。ギャップが大事！
- 【重要】控え室は視聴者が最も楽しみにするパート。素のカツミが本音・噂話・毒舌全開で語る
- 控え室の最初のセリフは必ず「あー疲れた」「はぁ〜やっと終わった」など素が出る導入
- deep_dive, chat_summaryはテストモードでは省略可（空配列[]）
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
                print(f"      ✓ チャンク{chunk_index + 1} 生成完了 (KEY_{key_index})")
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


def _process_chunk_parallel(args: tuple) -> dict:
    """パラレル処理用のチャンク処理関数（ThreadPoolExecutor用）"""
    chunk, api_key, chunk_path, chunk_index, key_manager = args

    success = generate_gemini_tts_chunk(
        chunk, api_key, chunk_path, chunk_index,
        key_manager=key_manager,
        max_retries=3,
        retry_wait=30  # パラレル処理では短めに
    )

    duration = 0.0
    if success and os.path.exists(chunk_path):
        result = subprocess.run([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', chunk_path
        ], capture_output=True, text=True)
        duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0

    return {
        "index": chunk_index,
        "success": success,
        "path": chunk_path if success else None,
        "duration": duration
    }


def generate_dialogue_audio_parallel(dialogue: list, output_path: str, temp_dir: Path, key_manager: GeminiKeyManager,
                                     chunk_interval: int = 30) -> tuple:
    """対話音声をパラレル生成（29個のAPIキーを同時使用）

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

    # チャンクに分割
    chunks = split_dialogue_into_chunks(dialogue)
    print(f"    [Gemini TTS] {len(dialogue)}セリフを{len(chunks)}チャンクに分割")

    # APIキーを取得
    api_keys = key_manager.get_all_keys()
    if not api_keys:
        print("    ❌ Gemini APIキーがありません")
        return None, [], 0.0

    # パラレル処理のワーカー数（APIキー数とチャンク数の小さい方）
    max_workers = min(len(api_keys), len(chunks), 29)
    print(f"    [Gemini TTS] {len(api_keys)}個のAPIキーで並列処理（max_workers={max_workers}）")

    # パラレル処理用のタスクを準備
    tasks = []
    for i, chunk in enumerate(chunks):
        api_key = api_keys[i % len(api_keys)]
        chunk_path = str(temp_dir / f"chunk_{i:03d}.wav")
        tasks.append((chunk, api_key, chunk_path, i, key_manager))

    # ThreadPoolExecutorでパラレル処理
    chunk_files = [None] * len(chunks)
    chunk_durations = [0.0] * len(chunks)
    successful_chunk_indices = []

    print(f"    [パラレル処理] {len(chunks)}チャンクを{max_workers}並列で処理開始...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_chunk_parallel, task): task[3] for task in tasks}

        for future in as_completed(futures):
            chunk_index = futures[future]
            try:
                result = future.result()
                if result["success"]:
                    chunk_files[result["index"]] = result["path"]
                    chunk_durations[result["index"]] = result["duration"]
                    successful_chunk_indices.append(result["index"])
                    print(f"    ✓ チャンク {result['index'] + 1}/{len(chunks)} 完了 ({result['duration']:.1f}秒)")
                else:
                    print(f"    ✗ チャンク {result['index'] + 1}/{len(chunks)} 失敗")
            except Exception as e:
                print(f"    ✗ チャンク {chunk_index + 1}/{len(chunks)} 例外: {e}")

    # 成功したチャンクを確認
    successful_chunks = [f for f in chunk_files if f is not None]
    failed_count = len(chunks) - len(successful_chunks)
    print(f"    [Gemini TTS] {len(successful_chunks)}/{len(chunks)} チャンク成功")

    # エラーサマリーを表示
    error_summary = key_manager.get_error_summary()
    if error_summary != "エラーなし":
        print(f"    [エラー集計] {error_summary}")

    if not successful_chunks:
        # フォールバック：gTTSで全体を生成
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

    # チャンク単位のタイミングを計算（Whisperより正確）
    print("    [字幕] チャンク単位でタイミング計算...")

    current_time = 0.0
    successful_dialogue_count = 0

    for idx in sorted(successful_chunk_indices):
        chunk_lines = chunks[idx]
        chunk_duration = chunk_durations[idx] if idx < len(chunk_durations) else 0.0

        if chunk_duration <= 0:
            continue

        # チャンク内のセリフにテキスト長比例でタイミング割り当て
        total_text_len = sum(len(line.get("text", "")) for line in chunk_lines) or 1

        chunk_start = current_time
        for line in chunk_lines:
            text_len = len(line.get("text", ""))
            line_duration = (text_len / total_text_len) * chunk_duration

            segments.append({
                "speaker": line["speaker"],
                "text": line["text"],
                "start": current_time,
                "end": current_time + line_duration,
                "color": CHARACTERS[line["speaker"]]["color"],
                "section": line.get("section", ""),  # セクション情報
            })
            current_time += line_duration
            successful_dialogue_count += 1

        # チャンク境界を厳密に合わせる
        current_time = chunk_start + chunk_duration

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

        # ジングルを読み込み
        jingle = AudioSegment.from_file(jingle_path)
        print(f"    [ジングル] 長さ: {len(jingle) / 1000:.1f}秒")

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

        # エンディングジングルを読み込み
        ending_jingle = AudioSegment.from_file(ending_jingle_path)
        jingle_duration = len(ending_jingle) / 1000  # 秒
        print(f"    [エンディングジングル] 長さ: {jingle_duration:.1f}秒")

        # 音声を分割
        main_audio = audio[:ending_start_ms]
        ending_audio = audio[ending_start_ms:]

        # 無音を作成
        silence = AudioSegment.silent(duration=silence_ms, frame_rate=audio.frame_rate)

        # 結合: 本編 + 無音 + エンディングジングル + 無音 + エンディング音声
        combined = main_audio + silence + ending_jingle + silence + ending_audio

        # WAV形式で出力（24000Hz, mono, 16bit）
        combined = combined.set_frame_rate(24000).set_channels(1).set_sample_width(2)
        combined.export(output_path, format="wav")

        # ジングル挿入による追加時間（無音×2 + ジングル長さ）
        added_duration = (silence_ms * 2 + len(ending_jingle)) / 1000
        print(f"    ✓ エンディングジングル挿入完了（追加: {added_duration:.1f}秒）")
        return True, added_duration

    except Exception as e:
        print(f"    ⚠ エンディングジングル挿入エラー: {e}")
        return False, 0.0


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


def wrap_text(text: str, max_chars: int = 30) -> str:
    """長いテキストを自動折り返し（ASS用）"""
    if len(text) <= max_chars:
        return text

    # 句読点や助詞で区切りを見つける
    break_chars = ['、', '。', '！', '？', 'は', 'が', 'を', 'に', 'で', 'と', 'の']
    lines = []
    current = ""

    for char in text:
        current += char
        if len(current) >= max_chars:
            # 区切り文字を探す
            for bc in break_chars:
                idx = current.rfind(bc)
                if idx > 0 and idx < len(current) - 1:
                    lines.append(current[:idx + 1])
                    current = current[idx + 1:]
                    break
            else:
                # 区切りが見つからない場合は強制改行
                lines.append(current)
                current = ""

    if current:
        lines.append(current)

    # 最大3行まで
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = lines[-1][:max_chars - 3] + "..."

    return "\\N".join(lines)


def draw_topic_overlay(base_img: Image.Image, title: str, source: str = "", date_str: str = "") -> Image.Image:
    """背景画像にトピック・出典・日付のオーバーレイを描画

    Args:
        base_img: ベースとなる背景画像
        title: トピックタイトル
        source: 出典（省略可）
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
    source_font = load_font(28)

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

    # 出典の高さ
    source_height = 35 if source else 0

    # ボックスの高さ
    box_height = box_padding * 2 + text_height + source_height

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

    # === 5. 出典描画（ボックス右下） ===
    if source:
        source_text = f"出典: {source}"
        source_bbox = draw.textbbox((0, 0), source_text, font=source_font)
        source_width = source_bbox[2] - source_bbox[0]
        source_x = box_x + box_width - box_padding - source_width
        source_y = box_y + box_height - box_padding - 25
        draw.text((source_x, source_y), source_text, font=source_font, fill=accent_color)

    return img.convert('RGB')


def create_topic_overlay_transparent(title: str, source: str = "", date_str: str = "") -> Image.Image:
    """透明なトピックオーバーレイ画像を作成

    背景を透明にして、日付・トピックボックス・出典のみを描画。
    ffmpegのoverlay filterで合成するために使用。

    Args:
        title: トピックタイトル
        source: 出典（省略可）
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
    source_font = load_font(28)

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

    # 出典の高さ
    source_height = 35 if source else 0

    # ボックスの高さ
    box_height = box_padding * 2 + text_height + source_height

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

    # === 5. 出典描画（ボックス右下） ===
    if source:
        source_text = f"出典: {source}"
        source_bbox = draw.textbbox((0, 0), source_text, font=source_font)
        source_width = source_bbox[2] - source_bbox[0]
        source_x = box_x + box_width - box_padding - source_width
        source_y = box_y + box_height - box_padding - 25
        draw.text((source_x, source_y), source_text, font=source_font, fill=accent_color)

    return img


def generate_ass_subtitles(segments: list, output_path: str, section_markers: list = None) -> list:
    """ASS字幕を生成（セリフ字幕＋トピック字幕＋出典）

    背景バーはffmpegのdrawboxで描画するため、ここではセリフ字幕のみ
    トピック情報はtopic_timingsとして返し、PIL描画で使用

    Returns:
        topic_timings: トピックのタイミング情報リスト
    """
    # 字幕設定
    font_size = int(VIDEO_WIDTH * 0.075)  # 画面幅の7.5% ≈ 144px（3行対応で少し小さく）
    margin_bottom = int(VIDEO_HEIGHT * 0.05)  # 下から5%（38%バー内に収まるよう調整）
    margin_left = int(VIDEO_WIDTH * 0.15)   # 左マージン（画面幅の15% ≈ 288px）
    margin_right = int(VIDEO_WIDTH * 0.15)  # 右マージン（画面幅の15% ≈ 288px）

    # トピック字幕の設定（画面上部）
    topic_font_size = int(VIDEO_WIDTH * 0.045)  # 画面幅の4.5% ≈ 86px
    topic_margin_top = int(VIDEO_HEIGHT * 0.02)  # 上から2%
    source_font_size = int(VIDEO_WIDTH * 0.025)  # 画面幅の2.5% ≈ 48px

    # ASS色形式: &HAABBGGRR
    primary_color = "&H00FFFFFF"  # 白文字
    shadow_color = "&H80000000"   # 半透明黒シャドウ
    topic_bg_color = "&HCC2E1A0D"  # 濃い茶色（透明度80%）  0D1A2E -> BGR
    source_color = "&H004080FF"   # オレンジ/赤系 (BGR: FF8040)

    header = f"""[Script Info]
Title: 年金ニュース
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK JP,{font_size},{primary_color},&H000000FF,{primary_color},{shadow_color},-1,0,0,0,100,100,0,0,1,0,0,1,{margin_left},{margin_right},{margin_bottom},1
Style: Topic,Noto Sans CJK JP,{topic_font_size},{primary_color},&H000000FF,&H00000000,{topic_bg_color},-1,0,0,0,100,100,0,0,3,3,0,7,20,20,{topic_margin_top},1
Style: Source,Noto Sans CJK JP,{source_font_size},{source_color},&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,9,20,20,{topic_margin_top + topic_font_size + 10},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]

    # トピック字幕のタイミングを計算
    topic_timings = []
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
                topic_timings.append({
                    "title": marker["title"],
                    "source": marker.get("source", ""),
                    "start": start_time,
                    "end": end_time,
                })

    # トピック字幕を追加（画面上部）
    for topic in topic_timings:
        start = f"0:{int(topic['start']//60):02d}:{int(topic['start']%60):02d}.{int((topic['start']%1)*100):02d}"
        end = f"0:{int(topic['end']//60):02d}:{int(topic['end']%60):02d}.{int((topic['end']%1)*100):02d}"
        # トピックタイトル
        lines.append(f"Dialogue: 1,{start},{end},Topic,,0,0,0,,{topic['title']}")
        # 出典（あれば）
        if topic.get("source"):
            source_text = f"出典: {topic['source']}"
            lines.append(f"Dialogue: 1,{start},{end},Source,,0,0,0,,{source_text}")

    # セリフ字幕を追加
    for seg in segments:
        start = f"0:{int(seg['start']//60):02d}:{int(seg['start']%60):02d}.{int((seg['start']%1)*100):02d}"
        end = f"0:{int(seg['end']//60):02d}:{int(seg['end']%60):02d}.{int((seg['end']%1)*100):02d}"
        # セリフのみ表示（話者名なし）、長い場合は折り返し
        wrapped_text = wrap_text(seg['text'], max_chars=16)  # 1行16文字で折り返し（3行対応）
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{wrapped_text}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return topic_timings


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
        dialogue = section.get("dialogue", [])
        for d in dialogue:
            d["section"] = news_title
        if dialogue:
            source = section.get("source", "")
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

    # 控え室（素のボヤキ）※エンディングジングルの後に再生
    green_room = script.get("green_room", [])
    for d in green_room:
        d["section"] = "控え室"
    if green_room:
        section_markers.append({"title": "控え室", "start_idx": len(all_dialogue)})
    all_dialogue.extend(green_room)

    # 空や無効なセリフを除外
    original_count = len(all_dialogue)
    all_dialogue = [
        d for d in all_dialogue
        if d.get("text") and len(d["text"].strip()) > 3 and d["text"].strip() not in ["...", "…", "。", "、"]
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
            section_markers_filtered.append({"title": title, "start_idx": i})
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
        # Gemini TTS（デフォルト）
        print(f"  [TTS] Gemini TTS を使用")
        _, segments, tts_duration = generate_dialogue_audio_parallel(all_dialogue, tts_audio_path, temp_dir, key_manager)

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

    # エンディングジングル追加（オプション）
    ending_jingle_file_id = os.environ.get("ENDING_JINGLE_FILE_ID")
    if ending_jingle_file_id:
        print("  [エンディングジングル] 挿入中...")
        ending_jingle_path = str(temp_dir / "ending_jingle.mp3")

        # 控え室セクションの開始インデックスを探す（エンディングジングルは控え室の直前に挿入）
        green_room_start_idx = None
        for i, d in enumerate(all_dialogue):
            if d.get("section") == "控え室":
                green_room_start_idx = i
                break

        if green_room_start_idx is not None and green_room_start_idx < len(all_segments):
            # 控え室開始時間を取得（ジングル追加後の値）
            green_room_start_time = all_segments[green_room_start_idx]["start"]
            green_room_start_ms = int(green_room_start_time * 1000)

            if download_jingle_from_drive(ending_jingle_file_id, ending_jingle_path):
                audio_with_ending_path = str(temp_dir / "audio_with_ending.wav")
                success, added_duration = add_ending_jingle_to_audio(
                    audio_path, ending_jingle_path, audio_with_ending_path, green_room_start_ms
                )
                if success:
                    # 出力ファイルを上書き
                    import shutil
                    shutil.move(audio_with_ending_path, audio_path)

                    # 控え室セグメント以降のタイミングをオフセット
                    for i in range(green_room_start_idx, len(all_segments)):
                        all_segments[i]["start"] += added_duration
                        all_segments[i]["end"] += added_duration

                    print(f"  ✓ エンディングジングル挿入完了（オフセット: {added_duration:.1f}秒）")
                else:
                    print("  ⚠ エンディングジングル挿入失敗、スキップ")
            else:
                print("  ⚠ エンディングジングルダウンロード失敗、スキップ")
        else:
            print("  ⚠ 控え室セクションが見つかりません、スキップ")

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
        with open(audio_path, "rb") as f:
            audio_base64 = base64.b64encode(f.read()).decode()
        with open(ass_path, "r", encoding="utf-8") as f:
            ass_content = f.read()

        output_name = os.path.basename(output_path)

        # Modal リモート呼び出し
        video_bytes = encode_video_gpu.remote(bg_base64, audio_base64, ass_content, output_name)

        # 結果をファイルに書き込み
        with open(output_path, "wb") as f:
            f.write(video_bytes)

        print(f"✓ 動画生成完了 (Modal GPU): {output_path}")
    else:
        # ローカル CPU エンコード (libx264)
        # 背景バーの設定
        bar_height = int(VIDEO_HEIGHT * 0.45)  # 画面の45%（3行字幕も収まる高さ）
        bar_y = VIDEO_HEIGHT - bar_height  # バーのY座標（画面下部）

        # ffmpegフィルター: scale → 背景バー描画 → 字幕
        # 茶色系: rgba(60,40,30,0.8) → ffmpegでは 0x3C281E@0.8
        # fontsdir でフォントディレクトリを明示的に指定（日本語フォント対応）
        vf_filter = (
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
            f"drawbox=x=0:y={bar_y}:w={VIDEO_WIDTH}:h={bar_height}:color=0x3C281E@0.8:t=fill,"
            f"ass={ass_path}:fontsdir=/usr/share/fonts"
        )

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
    """最初のコメントを生成（70代老夫婦の視点）

    Args:
        script: 台本データ
        news_data: ニュースデータ
        key_manager: APIキーマネージャー

    Returns:
        str: 老夫婦のコメント（50〜100文字）
    """
    api_key, key_name = key_manager.get_working_key()
    if not api_key:
        print("  ⚠ Gemini APIキーがないためコメント生成をスキップ")
        return ""

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    # ニュース要約を取得
    news_summary_lines = []
    confirmed_news = news_data.get("confirmed", [])
    rumor_news = news_data.get("rumor", [])

    for news in confirmed_news[:3]:
        news_summary_lines.append(f"・{news.get('title', '')}")
    for news in rumor_news[:1]:
        news_summary_lines.append(f"・{news.get('title', '')}（参考情報）")

    news_summary = "\n".join(news_summary_lines) if news_summary_lines else "今日の年金ニュース"

    prompt = f"""あなたは70代の老夫婦です。年金ニュースラジオを聞いた感想をコメントしてください。

【今日のニュース内容】
{news_summary}

【パーソナリティ】
- カツミ（女性）: 年金に詳しく、わかりやすく解説してくれる
- ヒロシ（男性）: ちょっとお馬鹿だけど、視聴者目線で素朴な質問をしてくれる

【コメントの条件】
- 70代老夫婦が一緒にラジオを聴いた温かみのある感想
- 50〜100文字程度
- 絵文字を1〜2個使用
- ニュースの内容やカツミ・ヒロシへの感想を自然に入れる
- 「私たち夫婦」「うちのおじいさん/おばあさん」などの表現OK

【コメント例】
「今日も勉強になりました😊 ヒロシさんの質問、うちのおじいさんも同じこと言ってました笑」
「年金の話、難しいけどカツミさんの説明でよくわかりました✨ 夫婦で毎日聴いてます」
「ヒロシさん面白い🤣 カツミさんの丁寧な解説に感謝です」

【出力】
老夫婦のコメントのみを出力してください。他の説明は不要です。
"""

    try:
        response = model.generate_content(prompt)
        comment = response.text.strip()
        # 余分な引用符を削除
        comment = comment.strip('"\'「」『』')
        # 100文字に制限
        if len(comment) > 100:
            comment = comment[:97] + "..."
        print(f"  [コメント生成] 老夫婦: {comment}")
        return comment
    except Exception as e:
        print(f"  ⚠ コメント生成エラー: {e}")
        return ""


# ===== サムネイル設定 =====
THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720


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


def send_discord_notification(title: str, url: str, video_duration: float, processing_time: float):
    """Discord通知を送信"""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    print(f"  [DEBUG] DISCORD_WEBHOOK_URL: {'設定済み (' + webhook_url[:30] + '...)' if webhook_url else '未設定'}")

    if not webhook_url:
        print("  ⚠ DISCORD_WEBHOOK_URL未設定のため通知をスキップ")
        return

    # 処理時間をフォーマット
    proc_minutes = int(processing_time // 60)
    proc_seconds = int(processing_time % 60)
    proc_time_str = f"{proc_minutes}分{proc_seconds}秒" if proc_minutes > 0 else f"{proc_seconds}秒"

    # 動画長をフォーマット
    vid_minutes = int(video_duration // 60)
    vid_seconds = int(video_duration % 60)
    vid_time_str = f"{vid_minutes}分{vid_seconds}秒" if vid_minutes > 0 else f"{vid_seconds}秒"

    message = f"""🎬 **年金ニュース投稿完了！**
━━━━━━━━━━━━━━━━━━
📺 タイトル: {title}
🔗 URL: {url}
⏱️ 動画長: {vid_time_str}
🕐 処理時間: {proc_time_str}"""

    print(f"  [DEBUG] Discord通知メッセージ作成完了")

    try:
        response = requests.post(
            webhook_url,
            json={"content": message},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        print(f"  [DEBUG] Discord API レスポンス: status={response.status_code}")
        if response.status_code in [200, 204]:
            print("  ✓ Discord通知送信完了")
        else:
            print(f"  ⚠ Discord通知失敗: {response.status_code}, body={response.text[:200]}")
    except Exception as e:
        print(f"  ⚠ Discord通知エラー: {type(e).__name__}: {e}")


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

    # セリフ数をカウント
    dialogue_count = len(script.get("opening", []))
    for section in script.get("news_sections", []):
        dialogue_count += len(section.get("dialogue", []))
    dialogue_count += len(script.get("rumor_section", []))
    dialogue_count += len(script.get("ending", []))
    print(f"  生成されたセリフ数: {dialogue_count}セリフ")

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
        title = f"【{datetime.now().strftime('%Y/%m/%d')}】今日の年金ニュース"

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

        # 6. 免責事項
        disclaimer = "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n【免責事項】\nこの動画は一般的な情報提供を目的としており、個別の年金相談や専門的なアドバイスを行うものではありません。正確な情報は年金事務所や専門家にご確認ください。\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

        # 概要欄を組み立て
        description = header + summary_section + key_points_section + source_section + hashtags + disclaimer

        # YouTube説明文の制限（5000文字、無効文字除去）
        description = description.replace("<", "").replace(">", "")  # 無効文字除去
        if len(description) > 4900:
            description = description[:4900] + "\n\n..."
        print(f"  説明文: {len(description)}文字")

        tags = script.get("tags", ["年金", "ニュース", "シニア"])

        try:
            video_url = upload_to_youtube(video_path, title, description, tags)

            # 動画URLをファイルに保存（ワークフロー通知用）
            with open("video_url.txt", "w") as f:
                f.write(video_url)

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

            # Discord通知を送信
            print("\n[7/7] Discord通知を送信中...")
            send_discord_notification(title, video_url, video_duration, processing_time)

            # 成功をログに記録
            log_to_spreadsheet(
                status="成功",
                title=title,
                url=video_url,
                news_count=news_count,
                processing_time=processing_time
            )

            # コメント内容を表示
            if first_comment:
                print(f"\n📝 最初のコメント: {first_comment}")

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
            # ローカルに保存
            import shutil
            output_file = f"nenkin_news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            shutil.copy(video_path, output_file)
            print(f"   ローカル保存: {output_file}")


if __name__ == "__main__":
    main()
