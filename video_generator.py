#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人生相談チャンネル 動画生成モジュール

音声ファイルと台本から字幕付き動画を生成する。

字幕スタイル:
- 茶色/オレンジ系の帯背景（#B8860B）
- 白文字
- 太い丸ゴシック系フォント（ヒラギノ丸ゴ）
- 黒い縁取り（3〜4px）
- 影つき
- 難しい漢字にはルビ（ふりがな）
"""

from dotenv import load_dotenv
load_dotenv()

import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from janome.tokenizer import Tokenizer

# 形態素解析器（シングルトン）
_tokenizer = None

def get_tokenizer():
    """形態素解析器を取得（遅延初期化）"""
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = Tokenizer()
    return _tokenizer

# ffmpegパス設定
os.environ["PATH"] = os.path.expanduser("~/bin") + ":" + os.environ.get("PATH", "")

from moviepy import (
    VideoClip,
    AudioFileClip,
    ImageClip,
    CompositeVideoClip,
    concatenate_videoclips,
)
from pydub import AudioSegment

# ============================================================
# 定数設定
# ============================================================

# キャラクター名
CHARACTER_CONSULTER = "由美子"  # 相談者
CHARACTER_ADVISOR = "P"          # 回答者

# 動画設定
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 30
BACKGROUND_COLOR = (30, 30, 30)  # ダークグレー

# 字幕設定
SUBTITLE_FONT_PATH = "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc"
SUBTITLE_FONT_SIZE = 52
SUBTITLE_RUBY_FONT_SIZE = 20  # ルビ用フォントサイズ
SUBTITLE_MAX_CHARS_PER_LINE = 26  # 1行の最大文字数
SUBTITLE_LINE_HEIGHT = 80
SUBTITLE_PADDING_X = 50
SUBTITLE_PADDING_Y = 25

# 字幕の色設定
SUBTITLE_BG_COLOR = (184, 134, 11, 240)  # 茶色/オレンジ系帯（#B8860B, RGBA）
SUBTITLE_TEXT_COLOR = (255, 255, 255)     # 白文字
SUBTITLE_OUTLINE_COLOR = (0, 0, 0)        # 黒い縁取り
SUBTITLE_SHADOW_COLOR = (0, 0, 0, 180)    # 影の色（半透明黒）
SUBTITLE_OUTLINE_WIDTH = 4                 # 縁取りの太さ
SUBTITLE_SHADOW_OFFSET = (3, 3)           # 影のオフセット

# ルビ（ふりがな）辞書 - 難しい漢字とその読み
RUBY_DICT = {
    "憂鬱": "ゆううつ",
    "躊躇": "ちゅうちょ",
    "葛藤": "かっとう",
    "鬱陶しい": "うっとうしい",
    "蔑ろ": "ないがしろ",
    "諦める": "あきらめる",
    "曖昧": "あいまい",
    "顛末": "てんまつ",
    "齟齬": "そご",
    "杞憂": "きゆう",
    "慟哭": "どうこく",
    "懊悩": "おうのう",
    "逡巡": "しゅんじゅん",
    "邂逅": "かいこう",
    "僥倖": "ぎょうこう",
    "蹉跌": "さてつ",
    "嘆息": "たんそく",
    "煩悶": "はんもん",
    "拘泥": "こうでい",
    "恣意": "しい",
}

# 字幕位置（画面下部）
SUBTITLE_BOTTOM_MARGIN = 80

# 出力設定
OUTPUT_DIR = Path("output/video")
TEMP_DIR = Path("output/temp")

# セリフ間の無音（秒）
SILENCE_BETWEEN_LINES = 0.5
SILENCE_BETWEEN_SPEAKERS = 0.8


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


def is_dependent_pos(part_of_speech: str) -> bool:
    """
    付属語（前の語にくっつけるべき品詞）かどうか判定

    Args:
        part_of_speech: 品詞情報（カンマ区切り）

    Returns:
        付属語ならTrue
    """
    pos_parts = part_of_speech.split(',')
    main_pos = pos_parts[0]
    sub_pos = pos_parts[1] if len(pos_parts) > 1 else ''

    # 付属語: 助詞、助動詞、接尾辞、非自立（動詞・名詞）、記号
    if main_pos in ['助詞', '助動詞']:
        return True
    if main_pos == '動詞' and sub_pos == '非自立':
        return True
    if main_pos == '名詞' and sub_pos == '非自立':
        return True
    if main_pos == '名詞' and sub_pos == '接尾':
        return True
    if main_pos == '記号':
        return True

    return False


def tokenize_to_bunsetsu(text: str) -> List[str]:
    """
    テキストを文節単位に分割

    Args:
        text: 分割するテキスト

    Returns:
        文節のリスト
    """
    tokenizer = get_tokenizer()
    tokens = list(tokenizer.tokenize(text))

    bunsetsu_list = []
    current_bunsetsu = ""

    for token in tokens:
        word = token.surface
        pos = token.part_of_speech

        if is_dependent_pos(pos):
            # 付属語は現在の文節に追加
            current_bunsetsu += word
        else:
            # 自立語の場合、前の文節を保存して新しい文節を開始
            if current_bunsetsu:
                bunsetsu_list.append(current_bunsetsu)
            current_bunsetsu = word

    # 最後の文節を追加
    if current_bunsetsu:
        bunsetsu_list.append(current_bunsetsu)

    return bunsetsu_list


def wrap_text(text: str, max_chars: int = SUBTITLE_MAX_CHARS_PER_LINE) -> List[str]:
    """
    テキストを日本語の文節単位で折り返す

    Args:
        text: 折り返すテキスト
        max_chars: 1行の最大文字数

    Returns:
        折り返された行のリスト
    """
    # 文節単位に分割
    bunsetsu_list = tokenize_to_bunsetsu(text)

    lines = []
    current_line = ""

    for bunsetsu in bunsetsu_list:
        # 現在の行に文節を追加した場合の長さをチェック
        if len(current_line) + len(bunsetsu) <= max_chars:
            current_line += bunsetsu
        else:
            # 現在の行が空でなければ保存
            if current_line:
                lines.append(current_line)

            # 文節自体が最大文字数を超える場合は分割
            if len(bunsetsu) > max_chars:
                # 長い文節は文字単位で分割
                while len(bunsetsu) > max_chars:
                    lines.append(bunsetsu[:max_chars])
                    bunsetsu = bunsetsu[max_chars:]
                current_line = bunsetsu
            else:
                current_line = bunsetsu

    # 最後の行を追加
    if current_line:
        lines.append(current_line)

    return lines


def draw_text_with_outline_and_shadow(
    draw: ImageDraw.Draw,
    pos: Tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    text_color: Tuple[int, int, int],
    outline_color: Tuple[int, int, int],
    outline_width: int,
    shadow_color: Tuple[int, int, int, int],
    shadow_offset: Tuple[int, int],
):
    """
    縁取りと影付きでテキストを描画

    Args:
        draw: ImageDraw オブジェクト
        pos: (x, y) 描画位置
        text: テキスト
        font: フォント
        text_color: テキスト色
        outline_color: 縁取り色
        outline_width: 縁取りの太さ
        shadow_color: 影の色（RGBA）
        shadow_offset: 影のオフセット (x, y)
    """
    x, y = pos
    sx, sy = shadow_offset

    # 1. 影を描画
    draw.text((x + sx, y + sy), text, font=font, fill=shadow_color)

    # 2. 縁取りを描画（8方向 + 中間方向）
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            # 円形の縁取りになるよう距離チェック
            if dx * dx + dy * dy <= outline_width * outline_width:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)

    # 3. 本文を描画
    draw.text((x, y), text, font=font, fill=text_color)


def add_ruby_to_text(text: str) -> List[Tuple[str, Optional[str]]]:
    """
    テキストにルビ情報を付与

    Args:
        text: 元のテキスト

    Returns:
        [(文字または単語, ルビまたはNone), ...]
    """
    result = []
    i = 0

    while i < len(text):
        found = False
        # 長い単語から順にチェック（貪欲マッチング）
        for word in sorted(RUBY_DICT.keys(), key=len, reverse=True):
            if text[i:].startswith(word):
                result.append((word, RUBY_DICT[word]))
                i += len(word)
                found = True
                break

        if not found:
            result.append((text[i], None))
            i += 1

    return result


def create_subtitle_image(
    text: str,
    character: str,
    width: int = VIDEO_WIDTH,
) -> Image.Image:
    """
    字幕画像を生成（縁取り・影・ルビ対応）

    Args:
        text: 字幕テキスト
        character: キャラクター名
        width: 画像幅

    Returns:
        PIL Image（RGBA）
    """
    # フォントを読み込み
    try:
        font = ImageFont.truetype(SUBTITLE_FONT_PATH, SUBTITLE_FONT_SIZE)
        ruby_font = ImageFont.truetype(SUBTITLE_FONT_PATH, SUBTITLE_RUBY_FONT_SIZE)
    except:
        # フォールバック
        font = ImageFont.truetype("/System/Library/Fonts/AppleSDGothicNeo.ttc", SUBTITLE_FONT_SIZE)
        ruby_font = ImageFont.truetype("/System/Library/Fonts/AppleSDGothicNeo.ttc", SUBTITLE_RUBY_FONT_SIZE)

    # テキストを折り返し
    lines = wrap_text(text)

    # ルビがあるかチェック
    has_ruby = any(word in text for word in RUBY_DICT.keys())
    ruby_height = SUBTITLE_RUBY_FONT_SIZE + 5 if has_ruby else 0

    # 画像サイズを計算
    dummy_img = Image.new('RGBA', (1, 1))
    draw = ImageDraw.Draw(dummy_img)

    # 各行の幅を計算して最大幅を取得
    line_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])

    max_line_width = max(line_widths) if line_widths else 0
    text_height = len(lines) * (SUBTITLE_LINE_HEIGHT + ruby_height)

    # キャラクター名を含める
    char_text = f"【{character}】"
    char_bbox = draw.textbbox((0, 0), char_text, font=font)
    char_width = char_bbox[2] - char_bbox[0]

    # 背景の幅（キャラクター名 + テキスト + 縁取り分の余白）
    extra_margin = SUBTITLE_OUTLINE_WIDTH * 2 + SUBTITLE_SHADOW_OFFSET[0]
    bg_width = max(max_line_width, char_width) + SUBTITLE_PADDING_X * 2 + extra_margin
    bg_height = text_height + SUBTITLE_PADDING_Y * 2 + SUBTITLE_LINE_HEIGHT + ruby_height

    # 画像を作成（透明背景）
    img = Image.new('RGBA', (width, bg_height + 30), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 背景の位置（中央揃え）
    bg_x = (width - bg_width) // 2
    bg_y = 15

    # 角丸の茶色/オレンジ帯背景を描画
    corner_radius = 15
    draw.rounded_rectangle(
        [bg_x, bg_y, bg_x + bg_width, bg_y + bg_height],
        radius=corner_radius,
        fill=SUBTITLE_BG_COLOR
    )

    # キャラクター名を描画（縁取り・影付き）
    char_x = bg_x + SUBTITLE_PADDING_X
    char_y = bg_y + SUBTITLE_PADDING_Y
    draw_text_with_outline_and_shadow(
        draw, (char_x, char_y), char_text, font,
        SUBTITLE_TEXT_COLOR, SUBTITLE_OUTLINE_COLOR, SUBTITLE_OUTLINE_WIDTH,
        SUBTITLE_SHADOW_COLOR, SUBTITLE_SHADOW_OFFSET
    )

    # 本文を描画
    text_y = char_y + SUBTITLE_LINE_HEIGHT + ruby_height
    for line in lines:
        # 各行を中央揃え
        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        text_x = bg_x + (bg_width - line_width) // 2

        # ルビ付きで描画
        ruby_parts = add_ruby_to_text(line)
        current_x = text_x

        for word, ruby in ruby_parts:
            word_bbox = draw.textbbox((0, 0), word, font=font)
            word_width = word_bbox[2] - word_bbox[0]

            # ルビがある場合は上に描画
            if ruby:
                ruby_bbox = draw.textbbox((0, 0), ruby, font=ruby_font)
                ruby_width = ruby_bbox[2] - ruby_bbox[0]
                ruby_x = current_x + (word_width - ruby_width) // 2
                ruby_y = text_y - SUBTITLE_RUBY_FONT_SIZE - 3

                # ルビも縁取り付きで描画
                draw_text_with_outline_and_shadow(
                    draw, (ruby_x, ruby_y), ruby, ruby_font,
                    SUBTITLE_TEXT_COLOR, SUBTITLE_OUTLINE_COLOR, 2,
                    SUBTITLE_SHADOW_COLOR, (1, 1)
                )

            # 本文を縁取り・影付きで描画
            draw_text_with_outline_and_shadow(
                draw, (current_x, text_y), word, font,
                SUBTITLE_TEXT_COLOR, SUBTITLE_OUTLINE_COLOR, SUBTITLE_OUTLINE_WIDTH,
                SUBTITLE_SHADOW_COLOR, SUBTITLE_SHADOW_OFFSET
            )

            current_x += word_width

        text_y += SUBTITLE_LINE_HEIGHT + ruby_height

    return img


def get_audio_duration(audio_path: Path) -> float:
    """音声ファイルの長さを取得（秒）"""
    audio = AudioSegment.from_mp3(audio_path)
    return len(audio) / 1000.0


# ============================================================
# メインクラス
# ============================================================

class VideoGenerator:
    """動画生成クラス"""

    def __init__(self):
        """初期化"""
        ensure_dirs()
        print_info("VideoGenerator 初期化完了")

    def create_background_clip(self, duration: float) -> ImageClip:
        """背景クリップを作成"""
        bg_array = np.full((VIDEO_HEIGHT, VIDEO_WIDTH, 3), BACKGROUND_COLOR, dtype=np.uint8)
        return ImageClip(bg_array).with_duration(duration)

    def create_subtitle_clip(
        self,
        text: str,
        character: str,
        duration: float,
        start_time: float,
    ) -> ImageClip:
        """
        字幕クリップを作成

        Args:
            text: 字幕テキスト
            character: キャラクター名
            duration: 表示時間（秒）
            start_time: 開始時間（秒）

        Returns:
            ImageClip
        """
        # 字幕画像を生成
        subtitle_img = create_subtitle_image(text, character)
        subtitle_array = np.array(subtitle_img)

        # クリップを作成
        clip = ImageClip(subtitle_array).with_duration(duration)

        # 位置を設定（画面下部）
        clip = clip.with_position(("center", VIDEO_HEIGHT - subtitle_img.height - SUBTITLE_BOTTOM_MARGIN))

        # 開始時間を設定
        clip = clip.with_start(start_time)

        return clip

    def generate_from_audio_and_script(
        self,
        audio_path: Path,
        script: str,
        output_filename: str = "output.mp4",
        audio_segments: Optional[List[Tuple[Path, str, float]]] = None,
    ) -> Optional[Path]:
        """
        音声ファイルと台本から動画を生成

        Args:
            audio_path: 結合済み音声ファイルのパス
            script: 台本テキスト
            output_filename: 出力ファイル名
            audio_segments: [(セグメント音声パス, キャラクター名, 開始時間), ...]
                           指定しない場合は台本から推定

        Returns:
            生成された動画ファイルのパス（失敗時はNone）
        """
        print_info("動画生成を開始...")

        # 音声を読み込み
        if not audio_path.exists():
            print_error(f"音声ファイルが見つかりません: {audio_path}")
            return None

        audio_clip = AudioFileClip(str(audio_path))
        total_duration = audio_clip.duration

        print_info(f"音声の長さ: {total_duration:.2f}秒")

        # 台本をパース
        lines = parse_script(script)
        if not lines:
            print_error("台本のパースに失敗しました")
            return None

        print_info(f"セリフ数: {len(lines)}行")

        # 字幕のタイミングを計算
        # audio_segmentsが指定されていない場合は均等に分割
        if audio_segments is None:
            # セリフの長さに応じて時間を配分
            total_chars = sum(len(item["line"]) for item in lines)
            current_time = 0.0
            subtitle_timings = []

            for item in lines:
                char_ratio = len(item["line"]) / total_chars if total_chars > 0 else 1 / len(lines)
                duration = total_duration * char_ratio
                subtitle_timings.append({
                    "character": item["character"],
                    "line": item["line"],
                    "start": current_time,
                    "duration": duration,
                })
                current_time += duration
        else:
            # audio_segmentsから計算
            subtitle_timings = []
            for i, (seg_path, character, start_time) in enumerate(audio_segments):
                line = lines[i]["line"] if i < len(lines) else ""
                # 次のセグメントの開始時間までの長さ
                if i + 1 < len(audio_segments):
                    duration = audio_segments[i + 1][2] - start_time
                else:
                    duration = total_duration - start_time
                subtitle_timings.append({
                    "character": character,
                    "line": line,
                    "start": start_time,
                    "duration": duration,
                })

        # 背景クリップを作成
        print_info("背景を作成中...")
        background = self.create_background_clip(total_duration)

        # 字幕クリップを作成
        print_info("字幕を作成中...")
        subtitle_clips = []
        for i, timing in enumerate(subtitle_timings):
            print_progress(i + 1, len(subtitle_timings), f"{timing['character']}: {timing['line'][:15]}...")

            clip = self.create_subtitle_clip(
                text=timing["line"],
                character=timing["character"],
                duration=timing["duration"],
                start_time=timing["start"],
            )
            subtitle_clips.append(clip)

        print()  # 改行

        # 動画を合成
        print_info("動画を合成中...")
        final_video = CompositeVideoClip(
            [background] + subtitle_clips,
            size=(VIDEO_WIDTH, VIDEO_HEIGHT)
        )

        # 音声を追加
        final_video = final_video.with_audio(audio_clip)

        # 出力
        output_path = OUTPUT_DIR / output_filename
        print_info(f"動画を出力中: {output_path}")

        final_video.write_videofile(
            str(output_path),
            fps=VIDEO_FPS,
            codec="libx264",
            audio_codec="aac",
            logger="bar",
        )

        # リソースを解放
        audio_clip.close()
        final_video.close()

        # ファイルサイズを取得
        file_size = output_path.stat().st_size / (1024 * 1024)

        print_success(f"動画生成完了: {output_path}")
        print_info(f"ファイルサイズ: {file_size:.2f} MB")

        return output_path

    def test_subtitle_image(self):
        """字幕画像のテスト生成"""
        print_info("字幕画像をテスト生成中...")

        # ルビが付く難しい漢字を含むテスト文
        test_text = "夫との関係に葛藤があって、どうしても躊躇してしまうんです。"
        img = create_subtitle_image(test_text, CHARACTER_CONSULTER)

        test_path = TEMP_DIR / "test_subtitle.png"
        img.save(test_path)

        print_success(f"テスト画像を保存: {test_path}")

        # 通常のテキストもテスト
        test_text2 = "今日は本当にありがとうございます。実は、最近ちょっと悩んでいることがありまして。"
        img2 = create_subtitle_image(test_text2, CHARACTER_ADVISOR)

        test_path2 = TEMP_DIR / "test_subtitle2.png"
        img2.save(test_path2)

        print_success(f"テスト画像を保存: {test_path2}")

        return test_path


# ============================================================
# メイン実行
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="人生相談チャンネル 動画生成")
    parser.add_argument("--test-subtitle", action="store_true", help="字幕画像のテスト生成")
    parser.add_argument("--audio", type=str, help="音声ファイルパス")
    parser.add_argument("--script", type=str, help="台本ファイルパス")
    parser.add_argument("--output", type=str, default="output.mp4", help="出力ファイル名")

    args = parser.parse_args()

    try:
        generator = VideoGenerator()

        if args.test_subtitle:
            generator.test_subtitle_image()
        elif args.audio and args.script:
            with open(args.script, 'r', encoding='utf-8') as f:
                script = f.read()
            generator.generate_from_audio_and_script(
                audio_path=Path(args.audio),
                script=script,
                output_filename=args.output,
            )
        else:
            # デフォルト: テスト実行
            print_info("テスト実行...")

            # テスト用の台本
            test_script = f"""
{CHARACTER_CONSULTER}：今日は本当にありがとうございます。実は、最近ちょっと悩んでいることがありまして。

{CHARACTER_ADVISOR}：どうされましたか？何かあったんですか？

{CHARACTER_CONSULTER}：ええ、実は夫のことなんですけれど…
"""
            # テスト用の音声があれば使用
            test_audio = Path("output/audio/test_output.mp3")
            if test_audio.exists():
                generator.generate_from_audio_and_script(
                    audio_path=test_audio,
                    script=test_script,
                    output_filename="test_video.mp4",
                )
            else:
                print_info("テスト音声がないため、字幕画像のみテスト生成します")
                generator.test_subtitle_image()

    except Exception as e:
        print_error(f"エラー: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
