#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人生相談チャンネル 音声生成モジュール

Google Cloud Text-to-Speech APIを使用して、2人のキャラクターの台本を音声化する。
環境変数からキャラクター名とボイス設定を取得。
"""

from dotenv import load_dotenv
load_dotenv()

import os
import re
import sys
import json
import time
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from pydub import AudioSegment
from google.cloud import texttospeech
from google.oauth2 import service_account

# ============================================================
# 定数設定（環境変数から取得）
# ============================================================

# キャラクター名
CHARACTER_CONSULTER = os.environ.get("CONSULTER_NAME", "由美子")
CHARACTER_ADVISOR = os.environ.get("ADVISOR_NAME", "P")

# ボイス設定（環境変数から取得）
VOICE_SETTINGS = {
    CHARACTER_CONSULTER: {
        "voice_name": os.environ.get("CONSULTER_VOICE", "ja-JP-Neural2-B"),
        "pitch": float(os.environ.get("CONSULTER_PITCH", "2.0")),
        "speaking_rate": float(os.environ.get("CONSULTER_RATE", "1.1")),
    },
    CHARACTER_ADVISOR: {
        "voice_name": os.environ.get("ADVISOR_VOICE", "ja-JP-Wavenet-A"),
        "pitch": float(os.environ.get("ADVISOR_PITCH", "-2.0")),
        "speaking_rate": float(os.environ.get("ADVISOR_RATE", "0.9")),
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
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def parse_script(script: str) -> List[Dict]:
    """台本をパースしてセリフリストに変換"""
    lines = []
    current_character = None
    current_line = []

    for line in script.split('\n'):
        line = line.strip()
        if not line:
            continue

        match = re.match(rf'^({re.escape(CHARACTER_CONSULTER)}|{re.escape(CHARACTER_ADVISOR)})[：:](.*)$', line)

        if match:
            if current_character and current_line:
                lines.append({
                    "character": current_character,
                    "line": ''.join(current_line).strip()
                })

            current_character = match.group(1)
            current_line = [match.group(2).strip()]
        elif current_character:
            current_line.append(line)

    if current_character and current_line:
        lines.append({
            "character": current_character,
            "line": ''.join(current_line).strip()
        })

    return lines


def get_tts_client():
    """Google Cloud TTS クライアントを取得"""
    # 優先順位: GOOGLE_SERVICE_ACCOUNT_KEY > GOOGLE_CREDENTIALS_JSON > デフォルト
    sa_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if sa_key:
        credentials_info = json.loads(sa_key)
        credentials = service_account.Credentials.from_service_account_info(credentials_info)
        return texttospeech.TextToSpeechClient(credentials=credentials)
    
    credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if credentials_json:
        credentials_info = json.loads(credentials_json)
        credentials = service_account.Credentials.from_service_account_info(credentials_info)
        return texttospeech.TextToSpeechClient(credentials=credentials)
    
    return texttospeech.TextToSpeechClient()


def text_to_speech(
    text: str,
    character: str,
    client: texttospeech.TextToSpeechClient,
    output_path: Path,
) -> bool:
    """テキストを音声に変換"""
    settings = VOICE_SETTINGS.get(character)
    if not settings:
        print_error(f"未知のキャラクター: {character}")
        return False

    try:
        synthesis_input = texttospeech.SynthesisInput(text=text)

        voice = texttospeech.VoiceSelectionParams(
            language_code="ja-JP",
            name=settings["voice_name"],
        )

        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            pitch=settings["pitch"],
            speaking_rate=settings["speaking_rate"],
        )

        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )

        with open(output_path, "wb") as out:
            out.write(response.audio_content)

        return True

    except Exception as e:
        print_error(f"TTS例外: {str(e)}")
        return False


def merge_audio_files(
    audio_files: List[Tuple[Path, str]],
    output_path: Path,
) -> bool:
    """音声ファイルを結合"""
    try:
        combined = AudioSegment.empty()
        prev_character = None

        for audio_path, character in audio_files:
            if not audio_path.exists():
                print_error(f"ファイルが見つかりません: {audio_path}")
                continue

            audio = AudioSegment.from_mp3(audio_path)

            if len(combined) > 0:
                if character != prev_character:
                    silence = AudioSegment.silent(duration=SILENCE_BETWEEN_SPEAKERS)
                else:
                    silence = AudioSegment.silent(duration=SILENCE_BETWEEN_LINES)
                combined += silence

            combined += audio
            prev_character = character

        combined.export(output_path, format="mp3", bitrate="192k")
        return True

    except Exception as e:
        print_error(f"音声結合失敗: {str(e)}")
        return False


# ============================================================
# メインクラス
# ============================================================

class TTSGenerator:

    def __init__(self):
        self.client = get_tts_client()
        ensure_dirs()
        print_info("TTSGenerator 初期化完了（Google Cloud TTS）")
        print_info(f"相談者: {CHARACTER_CONSULTER} ({VOICE_SETTINGS[CHARACTER_CONSULTER]['voice_name']})")
        print_info(f"回答者: {CHARACTER_ADVISOR} ({VOICE_SETTINGS[CHARACTER_ADVISOR]['voice_name']})")

    def generate_from_script(
        self,
        script: str,
        output_filename: str = "output.mp3",
        row_num: Optional[int] = None,
    ) -> Optional[Path]:
        """台本から音声を生成"""
        print_info("台本をパース中...")
        lines = parse_script(script)

        if not lines:
            print_error("セリフが見つかりませんでした")
            return None

        print_info(f"セリフ数: {len(lines)}行")

        temp_files: List[Tuple[Path, str]] = []

        print_info("音声生成中（Google Cloud TTS）...")
        for i, item in enumerate(lines):
            character = item["character"]
            line = item["line"]

            if not line.strip():
                continue

            temp_path = TEMP_DIR / f"line_{i:04d}.mp3"

            print_progress(i + 1, len(lines), f"{character}: {line[:20]}...")

            success = text_to_speech(
                text=line,
                character=character,
                client=self.client,
                output_path=temp_path,
            )

            if success:
                temp_files.append((temp_path, character))
            else:
                print_error(f"\n  セリフ {i+1} の生成に失敗")

            time.sleep(0.1)

        print()

        if not temp_files:
            print_error("音声ファイルが生成されませんでした")
            return None

        if row_num:
            output_filename = f"jinsei_{row_num:04d}.mp3"

        output_path = OUTPUT_DIR / output_filename

        print_info("音声ファイルを結合中...")
        success = merge_audio_files(temp_files, output_path)

        if success:
            for temp_path, _ in temp_files:
                if temp_path.exists():
                    temp_path.unlink()

            file_size = output_path.stat().st_size / (1024 * 1024)

            print_success(f"音声生成完了: {output_path}")
            print_info(f"ファイルサイズ: {file_size:.2f} MB")

            return output_path
        else:
            return None

    def test_voice(self, character: str, text: str = "こんにちは、テストです。"):
        """ボイスのテスト"""
        print_info(f"{character}のボイスをテスト中...")

        output_path = OUTPUT_DIR / f"test_{character}.mp3"

        success = text_to_speech(
            text=text,
            character=character,
            client=self.client,
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
    parser.add_argument("--test", type=str, help="指定キャラのボイスをテスト")
    parser.add_argument("--script", type=str, help="台本ファイルパス")
    parser.add_argument("--output", type=str, default="output.mp3", help="出力ファイル名")

    args = parser.parse_args()

    try:
        generator = TTSGenerator()

        if args.test:
            generator.test_voice(args.test)
        elif args.script:
            with open(args.script, 'r', encoding='utf-8') as f:
                script = f.read()
            generator.generate_from_script(script, args.output)
        else:
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
