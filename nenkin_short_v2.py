#!/usr/bin/env python3
"""
年金ニュース ショート動画システム v2
- 本編とは完全に独立
- 「知ってた？年金Q&A」形式（60秒のショート動画）
- ヒロシ（質問担当）とカツミ（回答担当）のQ&A形式
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

# APIスキップモード（Gemini APIを使わずにダミーデータで動画生成をテスト）
SKIP_API = os.environ.get("SKIP_API", "").lower() == "true"

# ダミー台本（SKIP_API時に使用）
DUMMY_SCRIPT = [
    {"speaker": "ヒロシ", "text": "知ってた？年金って繰り下げると増えるんだって！"},
    {"speaker": "カツミ", "text": "そうなのよ、最大で42%も増えるの。"},
    {"speaker": "ヒロシ", "text": "マジで！？でも何歳まで待てばいいの？"},
    {"speaker": "カツミ", "text": "75歳まで繰り下げると最大よ。"},
    {"speaker": "ヒロシ", "text": "へー！でも長生きしないと損じゃない？"},
    {"speaker": "カツミ", "text": "損益分岐点は約12年後。考えて決めてね。"},
]
DUMMY_TOPIC = "年金繰り下げの話"

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
    def __init__(self, diagnose=False, use_only_base_key=False):
        self.keys = []
        self.key_names = []  # キー名を保持
        base_key = os.environ.get("GEMINI_API_KEY")
        if base_key:
            self.keys.append(base_key)
            self.key_names.append("GEMINI_API_KEY")

        # use_only_base_key=True の場合は GEMINI_API_KEY のみを使用
        if not use_only_base_key:
            for i in range(1, 43):  # GEMINI_API_KEY_1 〜 GEMINI_API_KEY_42
                key = os.environ.get(f"GEMINI_API_KEY_{i}")
                if key:
                    self.keys.append(key)
                    self.key_names.append(f"GEMINI_API_KEY_{i}")
        else:
            print("  ⚠ GEMINI_API_KEY のみ使用モード（有料枠テスト）")

        self.current_index = 0
        print(f"  利用可能なAPIキー: {len(self.keys)}個")

        # 診断モード: 各キーをテスト
        if diagnose:
            self._diagnose_keys()

    def get_key(self):
        if not self.keys:
            raise ValueError("APIキーがありません")
        key = self.keys[self.current_index]
        return key

    def next_key(self):
        self.current_index = (self.current_index + 1) % len(self.keys)
        return self.get_key()

    def _diagnose_keys(self):
        """全キーをテストして動作状況を報告"""
        print("\n=== APIキー診断開始 ===")
        working_keys = []
        failed_keys = []

        for i, (key, name) in enumerate(zip(self.keys, self.key_names)):
            try:
                client = genai.Client(api_key=key)
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents="こんにちは"
                )
                if response.text:
                    working_keys.append(name)
                    print(f"  ✓ {name}: OK")
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    failed_keys.append((name, "クォータ制限"))
                    print(f"  ✗ {name}: クォータ制限")
                else:
                    failed_keys.append((name, error_str[:50]))
                    print(f"  ✗ {name}: {error_str[:50]}")
            time.sleep(0.5)  # レート制限対策

        print("\n=== 診断結果 ===")
        print(f"動作するキー: {len(working_keys)}個")
        for name in working_keys:
            print(f"  ✓ {name}")
        print(f"\n失敗したキー: {len(failed_keys)}個")

        # 動作するキーのみを保持
        if working_keys:
            self.keys = [self.keys[self.key_names.index(name)] for name in working_keys]
            self.key_names = working_keys
            print(f"\n動作するキーのみで続行: {len(self.keys)}個")
        else:
            print("\n警告: 動作するキーがありません！")


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

    # リトライ処理（全キーを試す）
    max_retries = max(len(key_manager.keys), 10)  # 全キー数または最低10回
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=key_manager.get_key())
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt
            )
            news = response.text.strip()
            print(f"  ✓ ニュース取得完了（キー{key_manager.current_index + 1}番目）")
            print(f"  {news[:100]}...")
            return news
        except Exception as e:
            error_str = str(e)
            key_idx = key_manager.current_index + 1
            # 最初の1回は全文表示、それ以降は短縮
            if attempt == 0:
                print(f"  ⚠ 試行{attempt + 1}/{max_retries} (キー{key_idx}番目) 失敗:")
                print(f"    エラー全文: {error_str}")
            elif attempt < 3 or attempt >= max_retries - 3:
                print(f"  ⚠ 試行{attempt + 1}/{max_retries} (キー{key_idx}番目) 失敗:")
                print(f"    エラー: {error_str[:200]}")
            else:
                print(f"  ⚠ 試行{attempt + 1}/{max_retries} (キー{key_idx}番目) 失敗: {error_str[:50]}...")
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                key_manager.next_key()
                time.sleep(2)
            else:
                time.sleep(3)
            if attempt == max_retries - 1:
                raise RuntimeError(f"ニュース取得失敗: {error_str[:200]}")


def generate_script(key_manager: GeminiKeyManager, news: str) -> list:
    """控室トーク台本を生成（リトライ付き）"""
    print("\n[2/6] 台本を生成中...")

    today = datetime.now().strftime("%Y年%m月%d日")

    prompt = f"""あなたは「知ってた？年金Q&A」という年金クイズショートのパーソナリティです。
今日は{today}です。

【番組コンセプト】
視聴者が「知らなかった！」と思うような年金の豆知識をQ&A形式で紹介する

【キャラクター】
- ヒロシ（40代前半男性）: 質問担当。「知ってた？」で話を切り出す。親世代のために勉強中。驚きのリアクションが得意。
- カツミ（60代前半女性）: 回答担当。年金の専門家。わかりやすく解説する。時々毒舌。年金受給が近い世代として視聴者に寄り添う。

【今日のニュース】
{news}

【台本の流れ】
1. ヒロシ「知ってた？〇〇って△△らしいよ」（問いかけ）
2. カツミが答えを解説
3. ヒロシが驚く・追加質問する
4. カツミがさらに詳しく説明
5. 最後に視聴者への一言

【ルール】
- 60秒以内で話す（10〜14セリフ、各セリフ15〜25文字）
- ヒロシの「知ってた？」から始める（必須！）
- Q&A形式でテンポよく
- ヒロシは視聴者目線で質問・驚く
- カツミは専門家として回答
- 挨拶なし、いきなり本題に入る

【出力形式】以下の形式で出力してください。他の文章は不要です。
ヒロシ: 知ってた？〇〇って...
カツミ: そうなのよ、実は...
ヒロシ: マジで！？じゃあ...
カツミ: それはね...
..."""

    # リトライ処理（全キーを試す）
    max_retries = max(len(key_manager.keys), 10)
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
            print(f"  ✓ 台本生成成功（キー{key_manager.current_index + 1}番目）")
            break
        except Exception as e:
            error_str = str(e)
            print(f"  ⚠ 試行{attempt + 1}/{max_retries} 失敗: {error_str[:50]}...")
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                key_manager.next_key()
                time.sleep(2)
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


def generate_silent_audio(script: list, output_path: str) -> float:
    """SKIP_APIモード用：無音音声を生成（セリフ数に基づく長さ）"""
    print("\n[3/6] 無音音声を生成中... (SKIP_APIモード)")

    # 1セリフあたり約3秒 + 間隔0.2秒
    duration_per_line = 3.0
    gap = 0.2
    total_duration = len(script) * (duration_per_line + gap)

    # 最低30秒、最大55秒に調整
    total_duration = max(30.0, min(55.0, total_duration))
    total_ms = int(total_duration * 1000)

    # 無音音声を生成
    silent = AudioSegment.silent(duration=total_ms)
    silent.export(output_path, format="wav")

    print(f"  ✓ 無音音声生成完了: {total_duration:.1f}秒")
    return total_duration


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


def generate_topic_from_news(news: str, key_manager: 'GeminiKeyManager') -> str:
    """ニュースからトピックを生成（「知ってた？〇〇の話」形式、15文字以内）"""
    print("  トピックを生成中...")

    prompt = f"""以下の年金ニュースから、Q&A動画のトピック（見出し）を作ってください。

【ニュース】
{news[:500]}

【ルール】
- 15文字以内（絶対厳守）
- 「知ってた？〇〇の話」形式
- 〇〇は年金の具体的なキーワード（4〜8文字）
- 絵文字なし

【例】
- 知ってた？繰り下げの話
- 知ってた？在職老齢年金
- 知ってた？加給年金の話
- 知ってた？遺族年金って

トピックのみを出力（説明不要）:"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=key_manager.get_key())
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.7)
            )
            topic = response.text.strip().strip('「」\'\"')
            if len(topic) > 15:
                topic = topic[:15]
            print(f"  ✓ トピック: {topic}")
            return topic
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                key_manager.next_key()
                time.sleep(3)
            else:
                time.sleep(2)
            if attempt == max_retries - 1:
                print(f"  ⚠ トピック生成失敗、デフォルト使用")
                return "知ってた？年金の話"

    return "知ってた？年金の話"


def generate_hook_phrase(script: list, key_manager: 'GeminiKeyManager') -> str:
    """煽りフレーズを生成（15文字以内）"""
    print("  煽りフレーズを生成中...")

    script_text = "\n".join([f"{line['speaker']}: {line['text']}" for line in script])

    prompt = f"""以下のQ&A形式の年金会話から、視聴者の興味を引く「煽りフレーズ」を作ってください。

【会話内容】
{script_text}

【ルール】
- 15文字以内（絶対厳守）
- Q&Aの答えに対する驚きや発見を表現
- 「知らなかった！」「意外すぎる」「これは重要」的なニュアンス
- 1行で完結
- 絵文字なし

【例】
- 知らない人多すぎ問題
- これ知らないと損する
- 意外と知られてない事実
- 正解率たった3割…
- マジで知らなかった

フレーズのみを出力（説明不要）:"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=key_manager.get_key())
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.8)
            )
            phrase = response.text.strip().strip('「」\'\"')
            # 15文字に制限
            if len(phrase) > 15:
                phrase = phrase[:15]
            print(f"  ✓ 煽りフレーズ: {phrase}")
            return phrase
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                key_manager.next_key()
                time.sleep(3)
            else:
                time.sleep(2)
            if attempt == max_retries - 1:
                print(f"  ⚠ 煽りフレーズ生成失敗、デフォルト使用")
                return "知らない人多すぎ問題"

    return "知らない人多すぎ問題"


def generate_subtitles(script: list, audio_duration: float, output_path: str,
                       topic: str = "", hook_phrase: str = ""):
    """ASS字幕を生成（新デザイン：上部トピック + 中央会話2倍 + 下部煽り）"""
    time_per_line = audio_duration / len(script)

    # === レイアウト設定 ===
    # 画面: 1080x1920、正方形エリア: 1080x1080、上下黒帯: 各420px
    TOP_BAR = 420
    BOTTOM_BAR = 420

    # サイズ
    topic_size = 80      # トピック
    dialogue_size = 160  # 会話（2倍）
    hook_size = 70       # 煽りフレーズ

    # 位置（MarginV = 画面下端からの距離）
    topic_margin_v = VIDEO_HEIGHT - (TOP_BAR // 2) - 50  # 上部黒帯中央やや下
    dialogue_margin_v = BOTTOM_BAR + 100                  # 正方形エリア下部
    hook_margin_v = BOTTOM_BAR // 2                       # 下部黒帯中央

    header = f"""[Script Info]
Title: Nenkin Short v2
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Topic,Noto Sans CJK JP,{topic_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,6,2,8,80,80,{topic_margin_v},1
Style: Katsumi,Noto Sans CJK JP,{dialogue_size},&H0000FFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,8,3,5,50,50,{dialogue_margin_v},1
Style: Hiroshi,Noto Sans CJK JP,{dialogue_size},&H005050FF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,8,3,5,50,50,{dialogue_margin_v},1
Style: Hook,Noto Sans CJK JP,{hook_size},&H0080FFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,5,2,2,50,50,{hook_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]

    # トピック（常時表示、奥から飛び出す）
    if topic:
        # 15文字超えたら2行に分割
        if len(topic) > 15:
            topic = topic[:15] + "\\N" + topic[15:]
        topic_anim = "{\\fscx20\\fscy20\\t(0,300,\\fscx105\\fscy105)\\t(300,500,\\fscx100\\fscy100)}"
        lines.append(f"Dialogue: 0,0:00:00.00,0:00:{audio_duration:05.2f},Topic,,0,0,0,,{topic_anim}{topic}")

    # 煽りフレーズ（少し遅れてフェードイン）
    if hook_phrase:
        hook_anim = "{\\alpha&HFF&\\t(500,800,\\alpha&H00&)}"
        lines.append(f"Dialogue: 0,0:00:00.50,0:00:{audio_duration:05.2f},Hook,,0,0,0,,{hook_anim}{hook_phrase}")

    # 会話（ポップアップ）
    for i, line in enumerate(script):
        start_time = i * time_per_line
        end_time = (i + 1) * time_per_line

        start_str = f"0:{int(start_time // 60):02d}:{start_time % 60:05.2f}"
        end_str = f"0:{int(end_time // 60):02d}:{end_time % 60:05.2f}"

        style = "Hiroshi" if line["speaker"] == "ヒロシ" else "Katsumi"
        text = line["text"].replace('\n', '\\N')

        popup = "{\\fscx50\\fscy50\\t(0,150,\\fscx110\\fscy110)\\t(150,300,\\fscx100\\fscy100)}"
        lines.append(f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{popup}{text}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def generate_video(audio_path: str, thumbnail_path: str, subtitle_path: str, output_path: str):
    """動画を生成（上下黒帯 + 中央正方形レイアウト）"""
    print("\n[4/6] 動画を生成中...")

    # レイアウト: 1080x1920、中央に1080x1080の正方形、上下に420pxの黒帯
    SQUARE_SIZE = 1080
    TOP_BAR = (VIDEO_HEIGHT - SQUARE_SIZE) // 2  # 420px

    # フィルター: 黒背景に正方形画像を中央配置 + 字幕
    filter_complex = (
        f"color=c=black:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}[bg];"
        f"[1:v]scale={SQUARE_SIZE}:{SQUARE_SIZE}:force_original_aspect_ratio=increase,"
        f"crop={SQUARE_SIZE}:{SQUARE_SIZE}[img];"
        f"[bg][img]overlay=0:{TOP_BAR}[composed];"
        f"[composed]ass={subtitle_path}[out]"
    )

    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', f'color=c=black:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d=1',
        '-loop', '1', '-i', thumbnail_path,
        '-i', audio_path,
        '-filter_complex', filter_complex,
        '-map', '[out]', '-map', '2:a',
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

    prompt = f"""あなたはカツミ（60代前半女性、「知ってた？年金Q&A」のパーソナリティ）です。
今回のQ&A動画の内容について、視聴者へのコメントを書いてください。

【カツミの設定】
- 60代前半（60〜62歳くらいを想像させる）
- 具体的な年齢は絶対に言わない（「あと何年で年金」「私は〇歳だから」などNG）
- 年金受給が近い世代として視聴者に寄り添う雰囲気
- Q&Aの回答者として親しみやすい

【今回の動画の内容】
{script_text}

【ルール】
- カツミとして、今回のQ&Aの答えに触れる一言（2〜3文）
- 「知ってた？」に対する補足や視聴者への問いかけ
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
    print(f"APIスキップ: {SKIP_API}")
    print("=" * 50)

    # SKIP_APIモードの場合はAPIを使わずにダミーデータで動画生成をテスト
    if SKIP_API:
        print("\n🧪 SKIP_APIモード: Gemini APIを使用せずダミーデータでテスト")
        key_manager = None
    else:
        # テストモード時は GEMINI_API_KEY のみを使用（有料枠テスト）
        key_manager = GeminiKeyManager(diagnose=False, use_only_base_key=TEST_MODE)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        if SKIP_API:
            # SKIP_APIモード: ダミーデータを使用
            print("\n[1/6] ダミーニュース使用 (SKIP_APIモード)")
            print("  ✓ ダミーニュースを使用")
            news = "ダミーニュース：年金繰り下げに関する情報"

            print("\n[2/6] ダミー台本使用 (SKIP_APIモード)")
            script = DUMMY_SCRIPT
            print(f"  ✓ ダミー台本: {len(script)}セリフ")

            topic = DUMMY_TOPIC
            print(f"  ✓ トピック: {topic}")

            hook_phrase = "知らないと損！"
        else:
            # 通常モード: APIを使用
            # 1. ニュース取得
            news = fetch_todays_news(key_manager)

            # 2. 台本生成
            script = generate_script(key_manager, news)

            if not script:
                print("  ❌ 台本が空です")
                return

            # トピック生成（ニュースから短いフレーズを抽出）
            topic = generate_topic_from_news(news, key_manager)

            # 煽りフレーズ生成
            hook_phrase = generate_hook_phrase(script, key_manager)

        # タイトル生成（トピックから動的に生成）
        today = datetime.now().strftime("%m/%d")

        # タイトル生成（トピックから）
        # トピックから「知ってた？」部分を抽出してタイトル化
        topic_keyword = topic.replace("知ってた？", "").replace("の話", "").strip()
        title = f"知ってた？{topic_keyword} #年金 #年金Q&A #Shorts"

        # 3. TTS生成または無音音声生成
        audio_path = str(temp_path / "audio.wav")
        if SKIP_API:
            duration = generate_silent_audio(script, audio_path)
        else:
            duration = generate_tts_audio(script, audio_path, key_manager)

        if duration > MAX_DURATION:
            print(f"  ⚠ 動画が{MAX_DURATION}秒を超えています: {duration:.1f}秒")

        # 4. サムネイル・字幕・動画生成
        thumbnail_path = str(temp_path / "thumbnail.jpg")
        subtitle_path = str(temp_path / "subtitles.ass")
        video_path = str(temp_path / "short.mp4")

        generate_thumbnail(title, thumbnail_path, temp_dir)
        generate_subtitles(script, duration, subtitle_path, topic=topic, hook_phrase=hook_phrase)
        generate_video(audio_path, thumbnail_path, subtitle_path, video_path)

        # 説明文
        description = f"""❓ 知ってた？年金Q&A

年金の気になる疑問をQ&A形式でサクッと解説！
毎日お昼に更新中。

本編は毎朝7時配信。チャンネル登録よろしくお願いします。

#年金 #年金Q&A #年金クイズ #Shorts"""

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
