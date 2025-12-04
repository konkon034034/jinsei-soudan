#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人生相談チャンネル 音声生成モジュール

Google Cloud Text-to-Speech APIを使用して、2人のキャラクターの台本を音声化する。

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
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from pydub import AudioSegment
from google.cloud import texttospeech
from google.oauth2 import service_account

# ============================================================
# 定数設定
# ============================================================

# キャラクター名
CHARACTER_CONSULTER = "由美子"  # 相談者
CHARACTER_ADVISOR = "P"          # 回答者

# Google Cloud TTS ボイス設定
VOICE_SETTINGS = {
    CHARACTER_CONSULTER: {
        # 由美子: 柔らかめ、速め、不安げ（女性）
        "voice_name": "ja-JP-Neural2-B",
        "pitch": 2.0,           # 少し高め
        "speaking_rate": 1.1,   # 速め
    },
    CHARACTER_ADVISOR: {
        # P: 低め、ゆっくり、安心感（女性）
        "voice_name": "ja-JP-Wavenet-A",
        "pitch": -2.0,          # 少し低め
        "speaking_rate": 0.9,   # ゆっくり
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


def get_tts_client():
    """Google Cloud TTS クライアントを取得"""
    credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    
    if credentials_json:
        # 環境変数からJSON文字列を読み込み
        credentials_info = json.loads(credentials_json)
        credentials = service_account.Credentials.from_service_account_info(credentials_info)
        return texttospeech.TextToSpeechClient(credentials=credentials)
    else:
        # デフォルトの認証情報を使用
        return texttospeech.TextToSpeechClient()


def text_to_speech(
    text: str,
    character: str,
    client: texttospeech.TextToSpeechClient,
    output_path: Path,
) -> bool:
    """
    テキストを音声に変換

    Args:
        text: 変換するテキスト
        character: キャラクター名
        client: Google Cloud TTS クライアント
        output_path: 出力ファイルパス

    Returns:
        成功/失敗
    """
    settings = VOICE_SETTINGS.get(character)
    if not settings:
        print_error(f"未知のキャラクター: {character}")
        return False

    try:
        # 入力テキストを設定
        synthesis_input = texttospeech.SynthesisInput(text=text)

        # ボイス設定
        voice = texttospeech.VoiceSelectionParams(
            language_code="ja-JP",
            name=settings["voice_name"],
        )

        # オーディオ設定
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            pitch=settings["pitch"],
            speaking_rate=settings["speaking_rate"],
        )

        # 音声を生成
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
        print_error(f"TTS例外: {str(e)}")
        return False


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
        self.client = get_tts_client()
        ensure_dirs()
        print_info("TTSGenerator 初期化完了（Google Cloud TTS）")

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
        print_info("音声生成中（Google Cloud TTS）...")
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
                client=self.client,
                output_path=temp_path,
            )

            if success:
                temp_files.append((temp_path, character))
            else:
                print_error(f"\n  セリフ {i+1} の生成に失敗")

            # レート制限対策（Google Cloud TTSは緩いが念のため）
            time.sleep(0.1)

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
