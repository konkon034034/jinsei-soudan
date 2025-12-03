#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人生相談チャンネル 音声生成モジュール

ElevenLabs APIを使用して、2人のキャラクターの台本を音声化する。

キャラクター設定:
- 由美子（相談者）: 柔らかめ、速め、不安げ
- P（回答者）: 低め、ゆっくり、安心感
"""

from dotenv import load_dotenv
load_dotenv()

import os
import re
import sys
import json
import time
import requests
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from pydub import AudioSegment

# ============================================================
# 定数設定
# ============================================================

# ElevenLabs API設定
ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1"

# キャラクター名
CHARACTER_CONSULTER = "由美子"  # 相談者
CHARACTER_ADVISOR = "P"          # 回答者

# ElevenLabs ボイス設定
# 注意: voice_id は ElevenLabs のアカウントで確認してください
# 以下はデフォルト値（日本語対応ボイス）
VOICE_SETTINGS = {
    CHARACTER_CONSULTER: {
        # 由美子: 柔らかめ、速め、不安げ
        "voice_id": "EXAVITQu4vr4xnSDxMaL",  # Sarah (変更可能)
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.4,           # 低め = より感情的
            "similarity_boost": 0.75,
            "style": 0.5,               # 表現力
            "use_speaker_boost": True,
        },
        "speed": 1.1,  # 速め
    },
    CHARACTER_ADVISOR: {
        # P: 低め、ゆっくり、安心感
        "voice_id": "pNInz6obpgDQGcFmaJgB",  # Adam (変更可能)
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.7,           # 高め = より安定
            "similarity_boost": 0.8,
            "style": 0.3,               # 控えめ
            "use_speaker_boost": True,
        },
        "speed": 0.9,  # ゆっくり
    },
}

# 出力設定
OUTPUT_DIR = Path("output/audio")
TEMP_DIR = Path("output/temp")

# セリフ間の無音（ミリ秒）
SILENCE_BETWEEN_LINES = 500
SILENCE_BETWEEN_SPEAKERS = 800


# ============================================================
# ヘルパー関数
# ============================================================

def print_info(message: str):
    print(f"📝 {message}")

def print_success(message: str):
    print(f"✅ {message}")

def print_error(message: str):
    print(f"❌ {message}", file=sys.stderr)

def print_progress(current: int, total: int, message: str = ""):
    percent = (current / total) * 100
    bar_length = 30
    filled = int(bar_length * current / total)
    bar = "█" * filled + "░" * (bar_length - filled)
    print(f"\r  [{bar}] {percent:.1f}% ({current}/{total}) {message}", end="", flush=True)


def ensure_dirs():
    """出力ディレクトリを作成"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def parse_script(script: str) -> List[Dict]:
    """
    台本をパースしてセリフリストに変換

    Args:
        script: 台本テキスト

    Returns:
        [{"character": "由美子", "line": "セリフ..."}, ...]
    """
    lines = []
    current_character = None
    current_line = []

    for line in script.split('\n'):
        line = line.strip()
        if not line:
            continue

        # キャラクター名:セリフ のパターンをチェック
        match = re.match(rf'^({CHARACTER_CONSULTER}|{CHARACTER_ADVISOR})[：:](.*)$', line)

        if match:
            # 前のセリフを保存
            if current_character and current_line:
                lines.append({
                    "character": current_character,
                    "line": ''.join(current_line).strip()
                })

            current_character = match.group(1)
            current_line = [match.group(2).strip()]
        elif current_character:
            # 継続行
            current_line.append(line)

    # 最後のセリフを保存
    if current_character and current_line:
        lines.append({
            "character": current_character,
            "line": ''.join(current_line).strip()
        })

    return lines


def get_available_voices(api_key: str) -> List[Dict]:
    """利用可能なボイス一覧を取得"""
    headers = {
        "xi-api-key": api_key,
    }

    response = requests.get(
        f"{ELEVENLABS_API_URL}/voices",
        headers=headers
    )

    if response.status_code == 200:
        return response.json().get("voices", [])
    else:
        print_error(f"ボイス一覧取得失敗: {response.status_code}")
        return []


def text_to_speech(
    text: str,
    character: str,
    api_key: str,
    output_path: Path,
) -> bool:
    """
    テキストを音声に変換

    Args:
        text: 変換するテキスト
        character: キャラクター名
        api_key: ElevenLabs APIキー
        output_path: 出力ファイルパス

    Returns:
        成功/失敗
    """
    settings = VOICE_SETTINGS.get(character)
    if not settings:
        print_error(f"未知のキャラクター: {character}")
        return False

    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }

    data = {
        "text": text,
        "model_id": settings["model_id"],
        "voice_settings": settings["voice_settings"],
    }

    url = f"{ELEVENLABS_API_URL}/text-to-speech/{settings['voice_id']}"

    try:
        response = requests.post(
            url,
            headers=headers,
            json=data,
            stream=True
        )

        if response.status_code == 200:
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
            return True
        else:
            error_msg = response.text[:200] if response.text else "Unknown error"
            print_error(f"TTS失敗 ({response.status_code}): {error_msg}")
            return False

    except Exception as e:
        print_error(f"TTS例外: {str(e)}")
        return False


def adjust_speed(audio: AudioSegment, speed: float) -> AudioSegment:
    """音声の速度を調整"""
    if speed == 1.0:
        return audio

    # サンプルレートを変更して速度調整
    new_frame_rate = int(audio.frame_rate * speed)
    return audio._spawn(audio.raw_data, overrides={
        "frame_rate": new_frame_rate
    }).set_frame_rate(audio.frame_rate)


def merge_audio_files(
    audio_files: List[Tuple[Path, str]],
    output_path: Path,
) -> bool:
    """
    音声ファイルを結合

    Args:
        audio_files: [(ファイルパス, キャラクター名), ...]
        output_path: 出力ファイルパス

    Returns:
        成功/失敗
    """
    try:
        combined = AudioSegment.empty()
        prev_character = None

        for audio_path, character in audio_files:
            if not audio_path.exists():
                print_error(f"ファイルが見つかりません: {audio_path}")
                continue

            # 音声を読み込み
            audio = AudioSegment.from_mp3(audio_path)

            # 速度調整
            settings = VOICE_SETTINGS.get(character, {})
            speed = settings.get("speed", 1.0)
            if speed != 1.0:
                audio = adjust_speed(audio, speed)

            # 無音を追加
            if len(combined) > 0:
                if character != prev_character:
                    # 話者が変わる場合は長めの無音
                    silence = AudioSegment.silent(duration=SILENCE_BETWEEN_SPEAKERS)
                else:
                    # 同じ話者の場合は短めの無音
                    silence = AudioSegment.silent(duration=SILENCE_BETWEEN_LINES)
                combined += silence

            combined += audio
            prev_character = character

        # MP3で出力
        combined.export(output_path, format="mp3", bitrate="192k")
        return True

    except Exception as e:
        print_error(f"音声結合失敗: {str(e)}")
        return False


# ============================================================
# メインクラス
# ============================================================

class TTSGenerator:
    """音声生成クラス"""

    def __init__(self):
        """初期化"""
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        if not self.api_key:
            raise ValueError("ELEVENLABS_API_KEY が設定されていません")

        ensure_dirs()
        print_info("TTSGenerator 初期化完了")

    def list_voices(self):
        """利用可能なボイス一覧を表示"""
        print_info("利用可能なボイス一覧を取得中...")
        voices = get_available_voices(self.api_key)

        print(f"\n📋 利用可能なボイス ({len(voices)}件):")
        for voice in voices:
            labels = voice.get("labels", {})
            accent = labels.get("accent", "")
            gender = labels.get("gender", "")
            print(f"  - {voice['name']} (ID: {voice['voice_id']}) [{gender}, {accent}]")

    def generate_from_script(
        self,
        script: str,
        output_filename: str = "output.mp3",
        row_num: Optional[int] = None,
    ) -> Optional[Path]:
        """
        台本から音声を生成

        Args:
            script: 台本テキスト
            output_filename: 出力ファイル名
            row_num: スプレッドシートの行番号（ファイル名に使用）

        Returns:
            生成された音声ファイルのパス（失敗時はNone）
        """
        print_info("台本をパース中...")
        lines = parse_script(script)

        if not lines:
            print_error("セリフが見つかりませんでした")
            return None

        print_info(f"セリフ数: {len(lines)}行")

        # 一時ファイルリスト
        temp_files: List[Tuple[Path, str]] = []

        # 各セリフを音声化
        print_info("音声生成中...")
        for i, item in enumerate(lines):
            character = item["character"]
            line = item["line"]

            # 空のセリフはスキップ
            if not line.strip():
                continue

            temp_path = TEMP_DIR / f"line_{i:04d}.mp3"

            print_progress(i + 1, len(lines), f"{character}: {line[:20]}...")

            success = text_to_speech(
                text=line,
                character=character,
                api_key=self.api_key,
                output_path=temp_path,
            )

            if success:
                temp_files.append((temp_path, character))
            else:
                print_error(f"\n  セリフ {i+1} の生成に失敗")

            # レート制限対策
            time.sleep(0.5)

        print()  # 改行

        if not temp_files:
            print_error("音声ファイルが生成されませんでした")
            return None

        # ファイル名を設定
        if row_num:
            output_filename = f"jinsei_{row_num:04d}.mp3"

        output_path = OUTPUT_DIR / output_filename

        # 音声を結合
        print_info("音声ファイルを結合中...")
        success = merge_audio_files(temp_files, output_path)

        if success:
            # 一時ファイルを削除
            for temp_path, _ in temp_files:
                if temp_path.exists():
                    temp_path.unlink()

            # ファイルサイズを取得
            file_size = output_path.stat().st_size / (1024 * 1024)

            print_success(f"音声生成完了: {output_path}")
            print_info(f"ファイルサイズ: {file_size:.2f} MB")

            return output_path
        else:
            return None

    def test_voice(self, character: str, text: str = "こんにちは、テストです。"):
        """
        ボイスのテスト

        Args:
            character: キャラクター名
            text: テストテキスト
        """
        print_info(f"{character}のボイスをテスト中...")

        output_path = OUTPUT_DIR / f"test_{character}.mp3"

        success = text_to_speech(
            text=text,
            character=character,
            api_key=self.api_key,
            output_path=output_path,
        )

        if success:
            print_success(f"テスト音声を生成: {output_path}")
        else:
            print_error("テスト音声の生成に失敗")


# ============================================================
# メイン実行
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="人生相談チャンネル 音声生成")
    parser.add_argument("--list-voices", action="store_true", help="利用可能なボイス一覧を表示")
    parser.add_argument("--test", type=str, help="指定キャラのボイスをテスト")
    parser.add_argument("--script", type=str, help="台本ファイルパス")
    parser.add_argument("--output", type=str, default="output.mp3", help="出力ファイル名")

    args = parser.parse_args()

    try:
        generator = TTSGenerator()

        if args.list_voices:
            generator.list_voices()
        elif args.test:
            generator.test_voice(args.test)
        elif args.script:
            with open(args.script, 'r', encoding='utf-8') as f:
                script = f.read()
            generator.generate_from_script(script, args.output)
        else:
            # デフォルト: テスト実行
            print_info("テスト実行...")
            test_script = f"""
{CHARACTER_CONSULTER}：今日は本当にありがとうございます。実は、最近ちょっと悩んでいることがありまして。

{CHARACTER_ADVISOR}：どうされましたか？何かあったんですか？

{CHARACTER_CONSULTER}：ええ、実は夫のことなんですけれど…
"""
            generator.generate_from_script(test_script, "test_output.mp3")

    except Exception as e:
        print_error(f"エラー: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
