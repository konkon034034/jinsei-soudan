#!/usr/bin/env python3
"""
年金データ表ショート動画システム v2
- 毎日違う年金ネタの「保存したくなる表」を表示
- カツミとヒロシが60秒トーク
- 最後に「この画像保存しとこっと」で保存を促す
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
import random
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

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
SKIP_API = os.environ.get("SKIP_API", "").lower() == "true"

# TTS設定
TTS_MODEL = "gemini-2.5-flash-preview-tts"
VOICE_KATSUMI = "Kore"   # カツミ（女性）
VOICE_HIROSHI = "Puck"   # ヒロシ（男性）

# ジングル・BGM設定（Google Drive ID）
JINGLE_FILE_ID = "1TdXxBkuGHWBwGcLxyGJCkuggDxomHqfD"
BGM_FILE_ID = "14X_YrRkGvq5rKofXsOL9X42zmYnaXjF1"
BGM_VOLUME_REDUCTION = 18  # dB減（トークの邪魔にならないように）

# 背景画像（Google Drive ID）
BACKGROUND_IMAGE_ID = "1ywnGZHMZWavnus1-fPD1MVI3fWxSrAIp"

# ===== テーマリスト =====
THEMES = [
    {
        "id": 1,
        "name": "年金受給開始年齢別の損益分岐点",
        "description": "繰り上げ・繰り下げ受給による総受給額の違いと損益分岐点を表にする"
    },
    {
        "id": 2,
        "name": "年金だけで暮らせる都道府県ランキング",
        "description": "生活費と年金受給額を比較した都道府県別ランキング"
    },
    {
        "id": 3,
        "name": "年金世代の節約術ランキング",
        "description": "年金生活者が実践している節約術の人気ランキング"
    },
    {
        "id": 4,
        "name": "知らないと損する年金届出一覧",
        "description": "届け出忘れで損する可能性がある年金関連の届出リスト"
    },
    {
        "id": 5,
        "name": "年金事務所に行く前の準備物リスト",
        "description": "年金事務所での手続きに必要な持ち物チェックリスト"
    },
    {
        "id": 6,
        "name": "繰り下げvs繰り上げ受給総額比較",
        "description": "受給開始年齢別の総受給額シミュレーション表"
    },
    {
        "id": 7,
        "name": "年金から引かれるもの一覧",
        "description": "年金から天引きされる税金・保険料の一覧と金額目安"
    },
    {
        "id": 8,
        "name": "遺族年金の早見表",
        "description": "遺族年金の受給条件と金額の早見表"
    },
    {
        "id": 9,
        "name": "年金世代の副業ランキング",
        "description": "年金受給者に人気の副業・収入源ランキング"
    },
    {
        "id": 10,
        "name": "年金相談先の比較表",
        "description": "年金事務所・社労士・FPなど相談先の特徴比較"
    },
]

# ダミーデータ（SKIP_API時に使用）
DUMMY_TABLE_DATA = {
    "title": "知らないと大損！",
    "subtitle": "年金受給額の損益分岐点",
    "headers": ["受給開始年齢", "受給率", "損益分岐点"],
    "rows": [
        {"cells": ["60歳", "76.0%", "82歳以上生きると損"], "highlight": "loss"},
        {"cells": ["61歳", "80.8%", "81歳以上生きると損"], "highlight": "loss"},
        {"cells": ["62歳", "85.6%", "80歳以上生きると損"], "highlight": "loss"},
        {"cells": ["63歳", "90.4%", "79歳以上生きると損"], "highlight": "loss"},
        {"cells": ["64歳", "95.2%", "78歳以上生きると損"], "highlight": "loss"},
        {"cells": ["65歳", "100%", "基準"], "highlight": "neutral"},
        {"cells": ["66歳", "108.4%", "78歳以上生きると得"], "highlight": "gain"},
        {"cells": ["67歳", "116.8%", "79歳以上生きると得"], "highlight": "gain"},
        {"cells": ["68歳", "125.2%", "80歳以上生きると得"], "highlight": "gain"},
        {"cells": ["69歳", "133.6%", "81歳以上生きると得"], "highlight": "gain"},
        {"cells": ["70歳", "142.0%", "82歳以上生きると得"], "highlight": "gain"},
    ],
    "footer": "※2024年度の年金制度に基づく目安です"
}

DUMMY_SCRIPT = [
    {"speaker": "ヒロシ", "text": "うわ、この表見て！60歳から受給すると76%しかもらえないんだ"},
    {"speaker": "カツミ", "text": "そうなのよ。でもね、82歳まで生きないと損なの"},
    {"speaker": "ヒロシ", "text": "え、マジで？じゃあ長生きする自信あれば繰り下げた方がいいの？"},
    {"speaker": "カツミ", "text": "70歳まで待てば142%よ。でも82歳以上生きないとトントンね"},
    {"speaker": "ヒロシ", "text": "うーん、悩むなぁ"},
    {"speaker": "カツミ", "text": "まあ健康状態と相談ね。損しないようにこの画像保存しとこっと"},
]


class GeminiKeyManager:
    """Gemini APIキー管理"""
    def __init__(self):
        self.keys = []
        self.key_names = []

        base_key = os.environ.get("GEMINI_API_KEY")
        if base_key:
            self.keys.append(base_key)
            self.key_names.append("GEMINI_API_KEY")

        for i in range(1, 43):
            key = os.environ.get(f"GEMINI_API_KEY_{i}")
            if key:
                self.keys.append(key)
                self.key_names.append(f"GEMINI_API_KEY_{i}")

        self.current_index = 0
        print(f"  利用可能なAPIキー: {len(self.keys)}個")

    def get_key(self):
        if not self.keys:
            raise ValueError("APIキーがありません")
        return self.keys[self.current_index]

    def get_key_name(self):
        return self.key_names[self.current_index]

    def next_key(self):
        self.current_index = (self.current_index + 1) % len(self.keys)
        return self.get_key()

    def get_key_for_index(self, index):
        """指定インデックス用のキーを取得（ラウンドロビン）"""
        idx = index % len(self.keys)
        return self.keys[idx], self.key_names[idx]


def download_from_drive(file_id: str, output_path: str) -> bool:
    """Google Driveからファイルをダウンロード（gdown使用）"""
    try:
        import gdown
        url = f"https://drive.google.com/uc?id={file_id}"
        gdown.download(url, output_path, quiet=False)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            print(f"    ダウンロード成功: {os.path.getsize(output_path)} bytes")
            return True
        else:
            print(f"    ⚠ ダウンロード失敗: ファイルが小さすぎる")
    except Exception as e:
        print(f"    ⚠ ダウンロードエラー: {e}")
    return False


def download_background_image(file_id: str, output_path: str) -> bool:
    """背景画像をダウンロードして1080x1920にリサイズ"""
    try:
        import gdown
        from PIL import Image

        # 一時ファイルにダウンロード
        temp_path = output_path + ".tmp"
        url = f"https://drive.google.com/uc?id={file_id}"
        gdown.download(url, temp_path, quiet=False)

        if os.path.exists(temp_path) and os.path.getsize(temp_path) > 1000:
            # 1080x1920にリサイズ
            img = Image.open(temp_path)
            img = img.resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.Resampling.LANCZOS)
            img.save(output_path)
            os.remove(temp_path)
            print(f"    背景画像ダウンロード・リサイズ成功: {VIDEO_WIDTH}x{VIDEO_HEIGHT}")
            return True
        else:
            print(f"    ⚠ 背景画像ダウンロード失敗")
    except Exception as e:
        print(f"    ⚠ 背景画像エラー: {e}")
    return False


def select_theme() -> dict:
    """今日のテーマを選択"""
    # 日付ベースでローテーション（毎日違うテーマ）
    day_of_year = datetime.now().timetuple().tm_yday
    theme_index = day_of_year % len(THEMES)
    return THEMES[theme_index]


def generate_table_data(theme: dict, key_manager: GeminiKeyManager) -> dict:
    """Gemini APIで表データを生成"""
    print(f"\n[1/6] 表データを生成中... テーマ: {theme['name']}")

    if SKIP_API:
        print("  [SKIP_API] ダミーデータを使用")
        return DUMMY_TABLE_DATA

    prompt = f"""あなたは年金の専門家です。
テーマ「{theme['name']}」について、ショート動画用のデータ表を作成してください。

{theme['description']}

以下のJSON形式で出力してください（JSONのみ、説明不要）：
{{
  "title": "知らないと大損！",
  "subtitle": "{theme['name']}",
  "headers": ["列1", "列2", "列3"],
  "rows": [
    {{"cells": ["データ1", "データ2", "データ3"], "highlight": "loss"}},
    {{"cells": ["データ4", "データ5", "データ6"], "highlight": "neutral"}},
    {{"cells": ["データ7", "データ8", "データ9"], "highlight": "gain"}}
  ],
  "footer": "※注釈"
}}

ルール：
- 行数は8〜12行程度（多すぎると見づらい）
- 列数は2〜4列
- highlight: "loss"=損する情報（赤）, "gain"=得する情報（緑）, "neutral"=中立（黒）
- 数字は最新の2024年度データを使用
- タイトルは煽り系（「知らないと損！」「これ知ってた？」「保存必須！」等）
- subtitleはテーマを分かりやすく
- 具体的な数字や金額を入れる"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=key_manager.get_key())

            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    response_mime_type="application/json"
                )
            )

            result_text = response.text.strip()
            # JSON抽出
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0]
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0]

            table_data = json.loads(result_text)
            print(f"  ✓ 表データ生成完了: {table_data['subtitle']}")
            print(f"    行数: {len(table_data['rows'])}, 列数: {len(table_data['headers'])}")
            return table_data

        except Exception as e:
            print(f"  ⚠ 試行{attempt + 1}/{max_retries} 失敗: {str(e)[:50]}...")
            key_manager.next_key()
            time.sleep(3)

    print("  ❌ 表データ生成失敗、ダミーデータを使用")
    return DUMMY_TABLE_DATA


def generate_table_image(table_data: dict, output_path: str):
    """表画像を生成（PIL）- スクロール用に縦長

    画像サイズ: 1080 x 2420
    - 最初は下半分だけ表示 (y=500からスタート)
    - 50秒かけてy=0までスクロール
    - 最後10秒はy=0で固定
    """
    print("\n[2/6] 表画像を生成中...")

    width = VIDEO_WIDTH
    # スクロール用に縦長画像 (1920 + 500 = 2420)
    height = VIDEO_HEIGHT + 500

    # 背景（真っ黒、表と字幕が映える）
    img = Image.new('RGB', (width, height), '#000000')
    draw = ImageDraw.Draw(img)

    # フォント設定
    try:
        font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
        if not os.path.exists(font_path):
            font_path = "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"
        if not os.path.exists(font_path):
            font_path = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"

        title_font = ImageFont.truetype(font_path, 70)
        subtitle_font = ImageFont.truetype(font_path, 50)
        header_font = ImageFont.truetype(font_path, 36)
        cell_font = ImageFont.truetype(font_path, 32)
        footer_font = ImageFont.truetype(font_path, 24)
    except:
        title_font = ImageFont.load_default()
        subtitle_font = title_font
        header_font = title_font
        cell_font = title_font
        footer_font = title_font

    # タイトル（上部、黄色、影付き）
    title = table_data.get("title", "知らないと損！")
    title_y = 80

    # 影
    draw.text((width//2 + 3, title_y + 3), title, fill='#333333', font=title_font, anchor="mm")
    # 本体（黄色）
    draw.text((width//2, title_y), title, fill='#FFD700', font=title_font, anchor="mm")

    # サブタイトル
    subtitle = table_data.get("subtitle", "")
    subtitle_y = 150
    draw.text((width//2 + 2, subtitle_y + 2), subtitle, fill='#333333', font=subtitle_font, anchor="mm")
    draw.text((width//2, subtitle_y), subtitle, fill='#FFFFFF', font=subtitle_font, anchor="mm")

    # 表の描画
    headers = table_data.get("headers", [])
    rows = table_data.get("rows", [])

    if not headers or not rows:
        print("  ⚠ 表データが不正です")
        img.save(output_path, "PNG")
        return

    num_cols = len(headers)
    num_rows = len(rows)

    # 表のサイズと位置
    table_width = width - 80
    cell_height = 60
    header_height = 70
    table_height = header_height + cell_height * num_rows

    table_x = 40
    table_y = 220

    cell_width = table_width // num_cols

    # 表の背景（白、角丸）
    table_rect = [table_x, table_y, table_x + table_width, table_y + table_height]
    draw.rounded_rectangle(table_rect, radius=15, fill='#FFFFFF', outline='#333333', width=3)

    # ヘッダー行（黄色背景）
    header_rect = [table_x, table_y, table_x + table_width, table_y + header_height]
    draw.rounded_rectangle(header_rect, radius=15, fill='#FFD700', outline='#333333', width=2)
    # 下の角を四角にするために上書き
    draw.rectangle([table_x, table_y + header_height - 15, table_x + table_width, table_y + header_height], fill='#FFD700')

    # ヘッダーテキスト
    for i, header in enumerate(headers):
        x = table_x + cell_width * i + cell_width // 2
        y = table_y + header_height // 2
        draw.text((x, y), header, fill='#000000', font=header_font, anchor="mm")

    # データ行
    for row_idx, row in enumerate(rows):
        cells = row.get("cells", [])
        highlight = row.get("highlight", "neutral")

        row_y = table_y + header_height + cell_height * row_idx

        # 行の区切り線
        if row_idx > 0:
            draw.line([(table_x + 10, row_y), (table_x + table_width - 10, row_y)], fill='#CCCCCC', width=1)

        # 色設定
        if highlight == "loss":
            text_color = '#E53935'  # 赤
        elif highlight == "gain":
            text_color = '#43A047'  # 緑
        else:
            text_color = '#333333'  # 黒

        # セルテキスト
        for col_idx, cell in enumerate(cells):
            x = table_x + cell_width * col_idx + cell_width // 2
            y = row_y + cell_height // 2

            # テキストが長い場合は縮小
            display_text = cell[:20] + "..." if len(cell) > 20 else cell
            draw.text((x, y), display_text, fill=text_color, font=cell_font, anchor="mm")

    # 列の区切り線
    for i in range(1, num_cols):
        x = table_x + cell_width * i
        draw.line([(x, table_y + header_height), (x, table_y + table_height - 10)], fill='#CCCCCC', width=1)

    # フッター
    footer = table_data.get("footer", "")
    if footer:
        footer_y = table_y + table_height + 30
        draw.text((width//2, footer_y), footer, fill='#666666', font=footer_font, anchor="mm")

    # 「保存してね」メッセージは削除（セリフで言わせる）

    img.save(output_path, "PNG")
    print(f"  ✓ 表画像生成完了: {output_path}")


def generate_script(table_data: dict, key_manager: GeminiKeyManager) -> list:
    """台本を生成"""
    print("\n[3/6] 台本を生成中...")

    if SKIP_API:
        print("  [SKIP_API] ダミー台本を使用")
        return DUMMY_SCRIPT

    # 表の内容を要約
    rows_summary = ""
    for row in table_data.get("rows", [])[:5]:  # 最初の5行
        cells = row.get("cells", [])
        rows_summary += "・" + " / ".join(cells) + "\n"

    prompt = f"""あなたは年金ニュースラジオの控室にいるカツミとヒロシです。
以下の表について60秒で本音トークしてください。

【表のタイトル】{table_data.get('subtitle', '')}
【表の内容（一部）】
{rows_summary}

カツミ（60代女性）: 年金の先輩、本音で話す、落ち着いた口調
ヒロシ（40代男性）: 素朴な疑問、驚き担当、リアクション大きめ

ルール：
- 60秒以内（6〜8往復、合計250〜350文字程度）
- 控室モード、砕けた口調OK
- 表のポイントを2〜3個解説
- 「え、マジで？」「それヤバくない？」的なリアクション多め
- 具体的な数字を引用する
- 【最重要】会話の最後の方で、カツミまたはヒロシが自然に保存を促すセリフを入れる。
  宣伝っぽくなく、自然な会話の流れで。例：
  「この動画保存しとかないと損しちゃうね」
  「これスクショしといた方がいいわよ」
  「保存しとかないと忘れちゃうからね」
  「損しないようにこの動画保存しとこっと」

出力形式（JSONのみ、説明不要）：
[
  {{"speaker": "ヒロシ", "text": "セリフ"}},
  {{"speaker": "カツミ", "text": "セリフ"}},
  ...
]"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=key_manager.get_key())

            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.8,
                    response_mime_type="application/json"
                )
            )

            result_text = response.text.strip()
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0]
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0]

            script = json.loads(result_text)
            print(f"  ✓ 台本生成完了: {len(script)}セリフ")
            return script

        except Exception as e:
            print(f"  ⚠ 試行{attempt + 1}/{max_retries} 失敗: {str(e)[:50]}...")
            key_manager.next_key()
            time.sleep(3)

    print("  ❌ 台本生成失敗、ダミー台本を使用")
    return DUMMY_SCRIPT


def _generate_single_tts(args: tuple) -> dict:
    """単一セリフのTTS生成"""
    index, line, api_key, key_name = args
    speaker = line["speaker"]
    text = line["text"]
    voice = VOICE_HIROSHI if speaker == "ヒロシ" else VOICE_KATSUMI

    max_retries = 3
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=api_key)
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
            return {"index": index, "success": True, "audio_data": audio_data, "speaker": speaker, "key_name": key_name}
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(5)
    return {"index": index, "success": False, "audio_data": None, "speaker": speaker, "key_name": key_name}


def generate_tts_audio(script: list, output_path: str, key_manager: GeminiKeyManager) -> tuple:
    """TTS並列生成"""
    print("\n[4/6] 音声を並列生成中...")

    if SKIP_API:
        # 無音音声を生成
        duration = len(script) * 4.0
        silent = AudioSegment.silent(duration=int(duration * 1000))
        silent.export(output_path, format="wav")
        timings = []
        current = 0.0
        for i in range(len(script)):
            timings.append({"start": current, "end": current + 3.5})
            current += 4.0
        return duration, timings

    all_keys = key_manager.keys
    all_key_names = key_manager.key_names
    num_keys = len(all_keys)

    # タスク準備
    tasks = []
    for i, line in enumerate(script):
        key_idx = i % num_keys
        tasks.append((i, line, all_keys[key_idx], all_key_names[key_idx]))

    max_workers = min(len(script), num_keys, 10)
    print(f"  並列数: {max_workers}")

    results = [None] * len(script)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_generate_single_tts, task): task[0] for task in tasks}
        for future in as_completed(futures):
            result = future.result()
            results[result["index"]] = result
            status = "✓" if result["success"] else "✗"
            print(f"  {status} [{result['index']+1}/{len(script)}] {result['speaker']}")

    # 失敗リトライ
    for idx, r in enumerate(results):
        if not r["success"]:
            for key_idx in range(num_keys):
                retry_result = _generate_single_tts((idx, script[idx], all_keys[key_idx], all_key_names[key_idx]))
                if retry_result["success"]:
                    results[idx] = retry_result
                    break

    # 結合
    combined = AudioSegment.empty()
    timings = []
    current_time = 0.0
    gap_duration = 200

    for result in results:
        if not result["success"]:
            raise RuntimeError(f"TTS生成失敗: {script[result['index']]}")

        audio_segment = AudioSegment.from_raw(
            io.BytesIO(result["audio_data"]),
            sample_width=2, frame_rate=24000, channels=1
        )
        segment_duration = len(audio_segment) / 1000.0
        timings.append({"start": current_time, "end": current_time + segment_duration})
        current_time += segment_duration
        combined += audio_segment
        combined += AudioSegment.silent(duration=gap_duration)
        current_time += gap_duration / 1000.0

    combined.export(output_path, format="wav")
    duration = len(combined) / 1000.0
    print(f"  ✓ 音声生成完了: {duration:.1f}秒")
    return duration, timings


def wrap_subtitle_text(text: str, max_chars: int = 13) -> str:
    """字幕テキストを折り返し（最大13文字/行）"""
    if len(text) <= max_chars:
        return text

    lines = []
    current = ""
    for char in text:
        current += char
        if len(current) >= max_chars:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)

    return "\\N".join(lines)


def generate_subtitles(script: list, audio_duration: float, output_path: str, timings: list = None, jingle_duration: float = 0, video_title: str = ""):
    """ASS字幕を生成（表の下、60-70%位置に配置、大きめフォント）"""
    print("  字幕を生成中...")

    # 字幕位置（画面の60-70%あたり = 画面下端から600-700px）
    # 1920px * 0.35 = 672px (下から35%の位置 = 上から65%の位置)
    # 字幕位置: 画面の60%位置（55-65%セーフゾーン内）
    margin_v = 768  # 下から768px = 上から約60%

    # フォントサイズ: 120px（2倍）
    font_size = 120

    # タイトル用設定（画面65-75%セーフゾーン）
    # YouTube Shortsは下25%にUIが被るため、75%より上に配置
    title_font_size = 120  # 大きめ（3倍）
    title_margin_v = 576   # 下から576px = 上から約70%位置（65-75%範囲内）

    # BorderStyle=1 で縁取り+影、高齢者に見やすい配色
    # カツミ: 濃いピンク(#FF6B9D)、白縁取り3px、黒影2px
    # ヒロシ: 濃い青(#4A90D9)、白縁取り3px、黒影2px
    # VideoTitle: 黄色文字、半透明オレンジ背景（BorderStyle=3）、Outline=0
    # ※ BorderStyle=3でOutline>0だとOutlineColourが背景になるのでOutline=0必須
    header = f"""[Script Info]
Title: Nenkin Table Short
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Katsumi,Noto Sans CJK JP,{font_size},&H009D6BFF,&H000000FF,&H00000000,&H00FFFFFF,1,0,0,0,100,100,0,0,1,3,2,2,30,30,{margin_v},1
Style: Hiroshi,Noto Sans CJK JP,{font_size},&H00D9904A,&H000000FF,&H00000000,&H00FFFFFF,1,0,0,0,100,100,0,0,1,3,2,2,30,30,{margin_v},1
Style: VideoTitle,Noto Sans CJK JP,{title_font_size},&H0000FFFF,&H000000FF,&H00000000,&H80004080,1,0,0,0,100,100,0,0,3,0,0,2,30,30,{title_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]

    # 動画タイトルを最初から最後まで固定表示
    if video_title:
        end_time_str = f"0:{int(audio_duration // 60):02d}:{audio_duration % 60:05.2f}"
        lines.append(f"Dialogue: 1,0:00:00.00,{end_time_str},VideoTitle,,0,0,0,,{video_title}")

    for i, line in enumerate(script):
        if timings and i < len(timings):
            # ジングル分のオフセットを追加
            start_time = timings[i]["start"] + jingle_duration
            end_time = timings[i]["end"] + jingle_duration
        else:
            time_per_line = audio_duration / len(script)
            start_time = i * time_per_line + jingle_duration
            end_time = (i + 1) * time_per_line + jingle_duration

        start_str = f"0:{int(start_time // 60):02d}:{start_time % 60:05.2f}"
        end_str = f"0:{int(end_time // 60):02d}:{end_time % 60:05.2f}"

        style = "Hiroshi" if line["speaker"] == "ヒロシ" else "Katsumi"

        # 13文字で折り返し
        wrapped_text = wrap_subtitle_text(line["text"], max_chars=13)

        # ポップアップアニメーション
        popup = "{\\fscx80\\fscy80\\t(0,100,\\fscx100\\fscy100)}"
        lines.append(f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{popup}{wrapped_text}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def process_audio_with_jingle_bgm(talk_audio_path: str, output_path: str, temp_dir: Path) -> float:
    """ジングルとBGMを追加して最終音声を生成

    Returns:
        float: ジングルの長さ（秒）
    """
    print("\n[4.5/6] ジングル・BGM処理中...")

    # トーク音声を読み込み
    talk = AudioSegment.from_file(talk_audio_path)
    talk_duration = len(talk)

    jingle_duration = 0.0
    final_audio = talk

    # ジングルをダウンロード
    jingle_path = str(temp_dir / "jingle.mp3")
    print("  ジングルをダウンロード中...")
    if download_from_drive(JINGLE_FILE_ID, jingle_path):
        try:
            jingle = AudioSegment.from_file(jingle_path)
            jingle_duration = len(jingle) / 1000.0
            print(f"    ✓ ジングル: {jingle_duration:.1f}秒")

            # BGMをダウンロード
            bgm_path = str(temp_dir / "bgm.mp3")
            print("  BGMをダウンロード中...")
            if download_from_drive(BGM_FILE_ID, bgm_path):
                try:
                    bgm = AudioSegment.from_file(bgm_path)
                    print(f"    ✓ BGM: {len(bgm) / 1000:.1f}秒")

                    # BGMをトークの長さに調整（ループまたはカット）
                    if len(bgm) < talk_duration:
                        # ループして延長
                        loops_needed = (talk_duration // len(bgm)) + 1
                        bgm = bgm * loops_needed
                    bgm = bgm[:talk_duration]

                    # BGM音量を下げる
                    bgm = bgm - BGM_VOLUME_REDUCTION
                    print(f"    BGM音量: -{BGM_VOLUME_REDUCTION}dB")

                    # トークとBGMをミックス
                    talk_with_bgm = talk.overlay(bgm)
                    print("    ✓ トーク+BGMミックス完了")

                    # ジングル + (トーク+BGM)
                    final_audio = jingle + talk_with_bgm
                    print(f"    ✓ 最終音声: {len(final_audio) / 1000:.1f}秒")

                except Exception as e:
                    print(f"    ⚠ BGM処理エラー: {e}")
                    # BGMなしでジングル + トーク
                    final_audio = jingle + talk
            else:
                print("    ⚠ BGMダウンロード失敗、BGMなしで続行")
                final_audio = jingle + talk

        except Exception as e:
            print(f"    ⚠ ジングル処理エラー: {e}")
            # ジングルなしでトークのみ
            final_audio = talk
            jingle_duration = 0.0
    else:
        print("    ⚠ ジングルダウンロード失敗、スキップ")
        jingle_duration = 0.0

    # 最終音声を出力
    final_audio.export(output_path, format="wav")
    print(f"  ✓ 最終音声出力: {len(final_audio) / 1000:.1f}秒")

    return jingle_duration


def generate_video(table_image_path: str, bg_image_path: str, audio_path: str, subtitle_path: str, output_path: str, duration: float = 60):
    """動画を生成（背景固定 + 表スクロールアニメーション）

    レイヤー構成（下から上）:
    - 背景画像（固定）
    - 表画像（上から下にスクロール）
    - 字幕、動画タイトル

    スクロールタイミング（上から降りてくる）:
    - 動画の半分の時点でスクロール完了
    - 例: 60秒動画 → 30秒でスクロール完了、残り30秒は固定
    """
    print("\n[5/6] 動画を生成中（背景固定 + 表スクロール）...")

    # スクロールタイミング計算
    # 動画の半分の時点でスクロール完了
    scroll_distance = 500  # 表の移動距離（ピクセル）
    scroll_end_time = duration / 2  # 動画の半分でスクロール完了
    scroll_speed = scroll_distance / scroll_end_time  # ピクセル/秒

    # filter_complex:
    # [0] 背景画像を1080x1920にスケール
    # [1] 表画像をそのまま使用（1080x2420）
    # overlay: 表を背景の上に重ねる、y座標をアニメーション
    # 式: if(lt(t,scroll_end_time), -500+speed*t, 0)
    filter_complex = (
        f"[0:v]scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},setsar=1[bg];"
        f"[bg][1:v]overlay=0:'if(lt(t,{scroll_end_time}),-{scroll_distance}+{scroll_speed}*t,0)'[video];"
        f"[video]ass={subtitle_path}[out]"
    )

    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', bg_image_path,   # 背景画像
        '-loop', '1', '-i', table_image_path, # 表画像
        '-i', audio_path,                     # 音声
        '-filter_complex', filter_complex,
        '-map', '[out]',
        '-map', '2:a',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '192k',
        '-shortest', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        output_path
    ]

    print(f"  レイヤー: 背景(固定) + 表(上から下) + 字幕")
    print(f"  スクロール: y=-{scroll_distance}→0 ({scroll_end_time:.1f}秒), 固定 ({duration - scroll_end_time:.1f}秒)")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if os.path.exists(output_path):
        print(f"  ✓ 動画生成完了: {output_path}")
    else:
        print(f"  ❌ 動画生成失敗: {result.stderr[:500]}")
        raise RuntimeError("動画生成に失敗しました")


def upload_to_youtube(video_path: str, title: str, description: str) -> str:
    """YouTubeにアップロード"""
    print("\n[6/6] YouTubeにアップロード中...")

    try:
        from google.oauth2.credentials import Credentials

        client_id = os.environ.get("YOUTUBE_CLIENT_ID")
        client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
        refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN_23")

        if not all([client_id, client_secret, refresh_token]):
            print("  ⚠ YouTube認証情報が不足しています")
            return ""

        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret
        )

        youtube = build("youtube", "v3", credentials=creds)

        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": ["年金", "年金制度", "老後", "お金", "Shorts"],
                "categoryId": "22"
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }

        media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = request.execute()

        video_id = response["id"]
        video_url = f"https://youtube.com/shorts/{video_id}"
        print(f"  ✓ アップロード完了: {video_url}")
        return video_url

    except Exception as e:
        print(f"  ❌ アップロード失敗: {e}")
        return ""


def send_discord_notification(message: str):
    """Discord通知"""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook_url:
        try:
            requests.post(webhook_url, json={"content": message}, timeout=10)
        except:
            pass


def main():
    """メイン処理"""
    start_time = time.time()

    print("=" * 50)
    print("年金データ表ショート動画システム v2")
    print("=" * 50)
    if TEST_MODE:
        print("🟡 テストモード（YouTubeアップロードをスキップ）")
    else:
        print("🔴 本番モード（YouTubeにアップロード）")
    if SKIP_API:
        print("⚙️  APIスキップ: 有効（ダミーデータでテスト）")
    print("=" * 50)

    key_manager = GeminiKeyManager()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # STEP1: テーマ選択
        theme = select_theme()
        print(f"\n📊 今日のテーマ: {theme['name']}")

        # STEP2: 表データ生成
        table_data = generate_table_data(theme, key_manager)

        # STEP3: 表画像生成
        image_path = str(temp_path / "table.png")
        generate_table_image(table_data, image_path)

        # STEP4: 台本生成
        script = generate_script(table_data, key_manager)

        # STEP5: TTS生成
        tts_audio_path = str(temp_path / "tts_audio.wav")
        tts_duration, timings = generate_tts_audio(script, tts_audio_path, key_manager)

        # STEP5.5: ジングル・BGM追加
        final_audio_path = str(temp_path / "audio.wav")
        jingle_duration = process_audio_with_jingle_bgm(tts_audio_path, final_audio_path, temp_path)

        # 最終音声の長さを取得
        final_audio = AudioSegment.from_file(final_audio_path)
        duration = len(final_audio) / 1000.0
        print(f"  最終音声長: {duration:.1f}秒 (ジングル: {jingle_duration:.1f}秒)")

        # 動画タイトル（字幕用）
        video_title = table_data.get('subtitle', '')

        # 字幕生成（ジングル分だけタイミングをオフセット、タイトル固定表示）
        subtitle_path = str(temp_path / "subtitles.ass")
        generate_subtitles(script, duration, subtitle_path, timings, jingle_duration, video_title)

        # STEP5.8: 背景画像をダウンロード（gdown + 1080x1920リサイズ）
        bg_image_path = str(temp_path / "background.png")
        print(f"\n  背景画像をダウンロード中...")
        if download_background_image(BACKGROUND_IMAGE_ID, bg_image_path):
            print(f"  ✓ 背景画像準備完了")
        else:
            # フォールバック：黒背景を生成
            print(f"  ⚠ 背景画像ダウンロード失敗、黒背景を使用")
            from PIL import Image
            bg = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), '#000000')
            bg.save(bg_image_path)

        # STEP6: 動画生成（背景固定 + 表スクロール）
        video_path = str(temp_path / "short.mp4")
        generate_video(image_path, bg_image_path, final_audio_path, subtitle_path, video_path, duration)

        # タイトルと説明文
        title = f"{table_data.get('title', '')} {video_title} #Shorts"
        description = f"""📊 {table_data.get('subtitle', '')}

年金の気になる情報を分かりやすい表でお届け！
保存して活用してくださいね。

#年金 #年金制度 #老後資金 #お金 #Shorts"""

        # STEP7: アップロード
        if TEST_MODE:
            print("\n[テストモード] YouTubeアップロードをスキップ")
            import shutil
            output_video = f"nenkin_table_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
            shutil.copy(video_path, output_video)
            print(f"  動画を保存: {output_video}")
            video_url = f"file://{output_video}"
        else:
            video_url = upload_to_youtube(video_path, title, description)

        # 完了
        elapsed = time.time() - start_time
        print("\n" + "=" * 50)
        print(f"✅ 完了！ 処理時間: {elapsed:.1f}秒")
        print(f"📊 テーマ: {theme['name']}")
        print(f"🎬 動画URL: {video_url}")
        print("=" * 50)

        # Discord通知
        if video_url and not TEST_MODE:
            send_discord_notification(f"📊 年金データ表ショート動画を投稿しました！\n\n{video_url}")
        elif TEST_MODE:
            send_discord_notification(f"🧪 テスト完了: {table_data.get('subtitle', '')}")


if __name__ == "__main__":
    main()
