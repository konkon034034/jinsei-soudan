#!/usr/bin/env python3
"""
口コミランキングチャンネル - 動画生成システム
Gemini TTSで音声生成、ffmpegで動画合成
"""

import os
import sys
import json
import wave
import struct
import tempfile
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# 親ディレクトリをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from google import genai
from google.genai import types
from PIL import Image, ImageDraw, ImageFont

# キャラクター設定をインポート
try:
    from character_settings import CHARACTERS, get_voice_for_speaker
except ImportError:
    CHARACTERS = {
        "カツミ": {"voice": "kore", "color_rgb": (255, 228, 181)},
        "ヒロシ": {"voice": "puck", "color_rgb": (100, 149, 237)}
    }
    def get_voice_for_speaker(speaker):
        return CHARACTERS.get(speaker, {}).get("voice", "kore")


# ===== 定数 =====
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
SAMPLE_RATE = 24000
TTS_MODEL = "gemini-2.5-flash-preview-tts"


class GeminiKeyManager:
    """複数のGemini APIキーを管理"""

    def __init__(self):
        self.keys = []
        # 基本キー
        base_key = os.environ.get("GEMINI_API_KEY")
        if base_key:
            self.keys.append(base_key)
        # 番号付きキー
        for i in range(1, 43):
            key = os.environ.get(f"GEMINI_API_KEY_{i}")
            if key:
                self.keys.append(key)

        if not self.keys:
            raise ValueError("GEMINI_API_KEY が設定されていません")

        print(f"✓ Gemini APIキー: {len(self.keys)}個")
        self.current_index = 0

    def get_key(self) -> str:
        """次のキーを取得"""
        key = self.keys[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.keys)
        return key


import time

def generate_tts_single(text: str, voice: str, api_key: str, output_path: str, max_retries: int = 3) -> bool:
    """
    単一のセリフをTTSで音声生成

    Args:
        text: セリフテキスト
        voice: 音声名（kore, puck など - 小文字）
        api_key: Gemini APIキー
        output_path: 出力ファイルパス
        max_retries: 最大リトライ回数

    Returns:
        成功したらTrue
    """
    # ボイス名を小文字に正規化
    voice = voice.lower()

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

            # 音声データを取得
            audio_data = response.candidates[0].content.parts[0].inline_data.data

            # WAVファイルとして保存
            with wave.open(output_path, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(SAMPLE_RATE)
                wav_file.writeframes(audio_data)

            return True

        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                # レート制限: 待機してリトライ
                wait_time = 20 * (attempt + 1)  # 20秒, 40秒, 60秒
                print(f"    ⏳ レート制限 - {wait_time}秒待機中...")
                time.sleep(wait_time)
                continue
            else:
                print(f"⚠️ TTS生成エラー: {e}")
                return False

    print(f"⚠️ TTS生成失敗（リトライ上限）")
    return False


def generate_all_audio(dialogue: list, temp_dir: Path, key_manager: GeminiKeyManager) -> list:
    """
    全セリフの音声を順次生成（レート制限対策）

    Returns:
        [(audio_path, speaker, text, duration), ...]
    """
    print("🎤 音声を生成中...")
    print("   (レート制限: 1分あたり3リクエスト - 各リクエスト後に20秒待機)")

    audio_files = []

    # 順次処理（レート制限対策: 3 requests/min = 20秒間隔）
    for i, line in enumerate(dialogue):
        speaker = line["speaker"]
        text = line["text"]
        voice = get_voice_for_speaker(speaker)

        output_path = str(temp_dir / f"audio_{i:03d}.wav")
        api_key = key_manager.get_key()

        print(f"  [{i+1}/{len(dialogue)}] {speaker}: {text[:20]}...")

        success = generate_tts_single(text, voice, api_key, output_path)

        if success and Path(output_path).exists():
            # 音声の長さを取得
            with wave.open(output_path, 'rb') as wav:
                frames = wav.getnframes()
                rate = wav.getframerate()
                duration = frames / rate

            audio_files.append({
                "path": output_path,
                "speaker": speaker,
                "text": text,
                "duration": duration,
                "index": i
            })
            print(f"    ✓ 成功 ({duration:.1f}秒)")

            # レート制限対策: 次のリクエストまで待機
            if i < len(dialogue) - 1:
                print(f"    ⏳ 20秒待機...")
                time.sleep(20)
        else:
            print(f"⚠️ 音声生成失敗: {text[:20]}")

    print(f"✅ 音声生成完了: {len(audio_files)}/{len(dialogue)}件")
    return audio_files


def concat_audio_files(audio_files: list, output_path: str, gap_ms: int = 300) -> float:
    """
    複数の音声ファイルを結合

    Returns:
        総時間（秒）
    """
    print("🔊 音声を結合中...")

    # ソート
    audio_files = sorted(audio_files, key=lambda x: x["index"])

    # 無音データを作成
    gap_samples = int(SAMPLE_RATE * gap_ms / 1000)
    silence = b'\x00\x00' * gap_samples

    # 結合
    all_audio = b''
    for audio in audio_files:
        with wave.open(audio["path"], 'rb') as wav:
            all_audio += wav.readframes(wav.getnframes())
        all_audio += silence

    # 保存
    with wave.open(output_path, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(all_audio)

    total_duration = len(all_audio) / 2 / SAMPLE_RATE
    print(f"✅ 音声結合完了: {total_duration:.1f}秒")
    return total_duration


def create_frame(title: str, speaker: str, text: str,
                 katsumi_icon: str, hiroshi_icon: str) -> Image.Image:
    """
    動画フレームを生成

    画面構成:
    - 上部: 黄色バーにタイトル
    - 左: カツミ画像
    - 右: ヒロシ画像
    - 中央: 口コミテキスト
    - 下部: 字幕バー
    """
    # 背景
    img = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), (30, 30, 40))
    draw = ImageDraw.Draw(img)

    # フォント
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", 48)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", 36)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", 28)
    except:
        try:
            font_large = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 48)
            font_medium = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 36)
            font_small = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 28)
        except:
            font_large = font_medium = font_small = ImageFont.load_default()

    # 上部: タイトルバー
    draw.rectangle([0, 0, VIDEO_WIDTH, 80], fill=(255, 200, 50))
    draw.text((VIDEO_WIDTH // 2, 40), title[:40], font=font_medium,
              fill=(30, 30, 30), anchor="mm")

    # キャラクター画像
    icon_size = 300

    # カツミ（左）
    try:
        katsumi_img = Image.open(katsumi_icon).convert('RGBA')
        katsumi_img = katsumi_img.resize((icon_size, icon_size))

        # 話している方をハイライト
        if speaker == "カツミ":
            # 発光エフェクト
            highlight = Image.new('RGBA', (icon_size + 20, icon_size + 20), (255, 228, 181, 100))
            img.paste(highlight, (90, 200), highlight)

        img.paste(katsumi_img, (100, 210), katsumi_img)
    except:
        draw.ellipse([100, 210, 400, 510], fill=(255, 228, 181))
        draw.text((250, 360), "カツミ", font=font_medium, fill=(30, 30, 30), anchor="mm")

    # ヒロシ（右）
    try:
        hiroshi_img = Image.open(hiroshi_icon).convert('RGBA')
        hiroshi_img = hiroshi_img.resize((icon_size, icon_size))

        if speaker == "ヒロシ":
            highlight = Image.new('RGBA', (icon_size + 20, icon_size + 20), (100, 149, 237, 100))
            img.paste(highlight, (VIDEO_WIDTH - 410, 200), highlight)

        img.paste(hiroshi_img, (VIDEO_WIDTH - 400, 210), hiroshi_img)
    except:
        draw.ellipse([VIDEO_WIDTH - 400, 210, VIDEO_WIDTH - 100, 510], fill=(100, 149, 237))
        draw.text((VIDEO_WIDTH - 250, 360), "ヒロシ", font=font_medium, fill=(255, 255, 255), anchor="mm")

    # キャラクター名
    draw.text((250, 530), "カツミ", font=font_small, fill=(255, 228, 181), anchor="mm")
    draw.text((VIDEO_WIDTH - 250, 530), "ヒロシ", font=font_small, fill=(100, 149, 237), anchor="mm")

    # 中央: テキストエリア
    text_area_x = 500
    text_area_width = VIDEO_WIDTH - 1000
    text_area_y = 600

    # テキストボックス背景
    draw.rounded_rectangle(
        [text_area_x - 20, text_area_y - 20, text_area_x + text_area_width + 20, text_area_y + 200],
        radius=20,
        fill=(50, 50, 60)
    )

    # テキストを折り返し
    words = text
    max_chars_per_line = 25
    lines = []
    current_line = ""
    for char in words:
        current_line += char
        if len(current_line) >= max_chars_per_line:
            lines.append(current_line)
            current_line = ""
    if current_line:
        lines.append(current_line)

    # テキストを描画
    y_offset = text_area_y + 20
    for line in lines[:4]:  # 最大4行
        draw.text((text_area_x + text_area_width // 2, y_offset),
                  line, font=font_medium, fill=(255, 255, 255), anchor="mm")
        y_offset += 50

    # 下部: 字幕バー
    subtitle_y = VIDEO_HEIGHT - 120
    speaker_color = CHARACTERS.get(speaker, {}).get("color_rgb", (255, 255, 255))

    draw.rectangle([0, subtitle_y - 10, VIDEO_WIDTH, VIDEO_HEIGHT], fill=(0, 0, 0, 180))

    # 話者名
    draw.text((100, subtitle_y + 30), f"【{speaker}】", font=font_medium,
              fill=speaker_color, anchor="lm")

    # 字幕テキスト
    subtitle_text = text[:50] + ("..." if len(text) > 50 else "")
    draw.text((300, subtitle_y + 30), subtitle_text, font=font_medium,
              fill=(255, 255, 255), anchor="lm")

    return img


def generate_video(script: dict, output_path: str, temp_dir: Path = None) -> bool:
    """
    台本から動画を生成

    Args:
        script: 台本データ
        output_path: 出力ファイルパス
        temp_dir: 一時ディレクトリ

    Returns:
        成功したらTrue
    """
    print("🎬 動画生成開始")

    if temp_dir is None:
        temp_dir = Path(tempfile.mkdtemp())

    title = script.get("title", "口コミランキング")
    dialogue = script.get("dialogue", [])

    if not dialogue:
        print("❌ セリフがありません")
        return False

    # キャラクターアイコンのパス
    base_dir = Path(__file__).parent.parent
    katsumi_icon = str(base_dir / "assets" / "characters" / "katsumi_icon.png")
    hiroshi_icon = str(base_dir / "assets" / "characters" / "hiroshi_icon.png")

    # 1. 音声生成
    key_manager = GeminiKeyManager()
    audio_files = generate_all_audio(dialogue, temp_dir, key_manager)

    if not audio_files:
        print("❌ 音声生成に失敗")
        return False

    # 2. 音声結合
    combined_audio = str(temp_dir / "combined_audio.wav")
    total_duration = concat_audio_files(audio_files, combined_audio)

    # 3. フレーム生成
    print("🖼️ フレームを生成中...")
    frames_dir = temp_dir / "frames"
    frames_dir.mkdir(exist_ok=True)

    # 各セリフに対応するフレームを生成
    frame_index = 0
    fps = 30
    gap_seconds = 0.3  # セリフ間の間隔

    for audio in sorted(audio_files, key=lambda x: x["index"]):
        speaker = audio["speaker"]
        text = audio["text"]
        duration = audio["duration"]

        # このセリフに必要なフレーム数
        num_frames = int((duration + gap_seconds) * fps)

        # フレームを生成
        frame = create_frame(title, speaker, text, katsumi_icon, hiroshi_icon)

        for _ in range(num_frames):
            frame_path = frames_dir / f"frame_{frame_index:05d}.png"
            frame.save(frame_path)
            frame_index += 1

    print(f"✅ フレーム生成完了: {frame_index}枚")

    # 4. 動画エンコード
    print("🎥 動画をエンコード中...")

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-i", combined_audio,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        output_path
    ]

    try:
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ ffmpegエラー: {result.stderr[:500]}")
            return False
    except Exception as e:
        print(f"❌ ffmpeg実行エラー: {e}")
        return False

    print(f"✅ 動画生成完了: {output_path}")
    return True


if __name__ == "__main__":
    # テスト
    test_script = {
        "title": "テスト動画",
        "dialogue": [
            {"speaker": "カツミ", "text": "あら、今日は口コミランキングをお届けするわよ"},
            {"speaker": "ヒロシ", "text": "楽しみですね、カツミさん"},
            {"speaker": "カツミ", "text": "第3位は、100均の便利グッズなのよ"},
            {"speaker": "ヒロシ", "text": "100均、最近すごいですよね"},
        ]
    }

    output = "/tmp/test_video.mp4"
    success = generate_video(test_script, output)

    if success:
        print(f"\n✅ テスト動画を生成しました: {output}")
    else:
        print("\n❌ テスト失敗")
