#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人生相談チャンネル 動画生成モジュール v2

新レイアウト:
- 上下2段で2人の会話を表示
- 話している方をハイライト
- 左サイドバー: 相談者情報
- 右サイドバー: 人生相談
- 喫茶店風背景
"""

from dotenv import load_dotenv
load_dotenv()

import os
import re
import sys
import requests
import hashlib
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np
from janome.tokenizer import Tokenizer

# Unsplash API
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")
UNSPLASH_API_URL = "https://api.unsplash.com/search/photos"

# ffmpegパス設定
os.environ["PATH"] = os.path.expanduser("~/bin") + ":" + os.environ.get("PATH", "")

from moviepy import (
    AudioFileClip,
    ImageClip,
    CompositeVideoClip,
)
from pydub import AudioSegment

# ============================================================
# 定数設定
# ============================================================

# キャラクター名（環境変数から取得）
CHARACTER_CONSULTER = os.environ.get("CONSULTER_NAME", "由美子")
CHARACTER_ADVISOR = os.environ.get("ADVISOR_NAME", "P")

# 動画サイズ
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 30

# 色設定
SUBTITLE_BG_COLOR = (196, 136, 58, 240)   # #C4883A
CAFE_BG_BASE = (65, 45, 35)                # 喫茶店風
TEXT_WHITE = (255, 255, 255)
TEXT_BLACK = (0, 0, 0)
DIM_OVERLAY = (0, 0, 0, 120)

# フォント設定（環境に応じて自動選択）
def _get_font_path():
    """利用可能なフォントパスを取得"""
    candidates = [
        # Ubuntu (GitHub Actions)
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
        # Mac
        "/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        # Windows
        "C:/Windows/Fonts/msgothic.ttc",
        "C:/Windows/Fonts/meiryo.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    # フォールバック: 見つからない場合は最初の候補を返す
    return candidates[0]

FONT_PATH = _get_font_path()
FONT_SIZE_MAIN = 84  # さらに大きく

# ドロップシャドウ設定
SHADOW_OFFSET = (4, 4)
SHADOW_COLOR = (0, 0, 0, 200)

# レイアウト設定（上下分割）
HALF_HEIGHT = VIDEO_HEIGHT // 2  # 画面の半分
CENTER_GAP = 40  # 上下の間の隙間
SUBTITLE_PADDING_X = int(VIDEO_WIDTH * 0.05)  # 左右5%余白
SUBTITLE_BG_COLOR = (60, 60, 60, 180)  # 透過グレー
SUBTITLE_MAX_LINES = 3  # 最大行数（各エリア）

# 文節分割用
SUBTITLE_MAX_CHARS = 24

# 出力設定
OUTPUT_DIR = Path("output/video")
TEMP_DIR = Path("output/temp")
BG_CACHE_DIR = Path("output/backgrounds")

# ルビ辞書
RUBY_DICT = {
    "憂鬱": "ゆううつ",
    "躊躇": "ちゅうちょ",
    "葛藤": "かっとう",
    "曖昧": "あいまい",
    "諦める": "あきらめる",
}

# 形態素解析器
_tokenizer = None

def get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = Tokenizer()
    return _tokenizer


# ============================================================
# ヘルパー関数
# ============================================================

def print_info(msg): print(f"📝 {msg}")
def print_success(msg): print(f"✅ {msg}")
def print_error(msg): print(f"❌ {msg}", file=sys.stderr)

def ensure_dirs():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    BG_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def is_dependent_pos(part_of_speech: str) -> bool:
    """付属語判定"""
    pos_parts = part_of_speech.split(',')
    main_pos = pos_parts[0]
    sub_pos = pos_parts[1] if len(pos_parts) > 1 else ''

    if main_pos in ['助詞', '助動詞']:
        return True
    if main_pos == '動詞' and sub_pos == '非自立':
        return True
    if main_pos == '名詞' and sub_pos in ['非自立', '接尾']:
        return True
    if main_pos == '記号':
        return True
    return False


def tokenize_to_bunsetsu(text: str) -> List[str]:
    """文節単位に分割"""
    tokenizer = get_tokenizer()
    tokens = list(tokenizer.tokenize(text))

    bunsetsu_list = []
    current = ""

    for token in tokens:
        if is_dependent_pos(token.part_of_speech):
            current += token.surface
        else:
            if current:
                bunsetsu_list.append(current)
            current = token.surface

    if current:
        bunsetsu_list.append(current)

    return bunsetsu_list


def wrap_text(text: str, max_chars: int = SUBTITLE_MAX_CHARS) -> List[str]:
    """文節単位で改行"""
    bunsetsu_list = tokenize_to_bunsetsu(text)
    lines = []
    current_line = ""

    for bunsetsu in bunsetsu_list:
        if len(current_line) + len(bunsetsu) <= max_chars:
            current_line += bunsetsu
        else:
            if current_line:
                lines.append(current_line)
            if len(bunsetsu) > max_chars:
                while len(bunsetsu) > max_chars:
                    lines.append(bunsetsu[:max_chars])
                    bunsetsu = bunsetsu[max_chars:]
                current_line = bunsetsu
            else:
                current_line = bunsetsu

    if current_line:
        lines.append(current_line)

    return lines


def parse_script(script: str) -> List[Dict]:
    """台本をパース"""
    lines = []
    current_character = None
    current_line = []

    for line in script.split('\n'):
        line = line.strip()
        if not line:
            continue

        match = re.match(rf'^({CHARACTER_CONSULTER}|{CHARACTER_ADVISOR})[：:](.*)$', line)

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


# ============================================================
# Unsplash API
# ============================================================

def fetch_unsplash_image(query: str = "cafe interior cozy", index: int = 0) -> Optional[Path]:
    """
    Unsplash APIから背景画像を取得

    Args:
        query: 検索キーワード
        index: 検索結果のインデックス（0から）

    Returns:
        保存した画像のパス、失敗時はNone
    """
    if not UNSPLASH_ACCESS_KEY:
        print_error("UNSPLASH_ACCESS_KEY が設定されていません")
        return None

    # キャッシュ確認
    cache_key = hashlib.md5(f"{query}_{index}".encode()).hexdigest()[:12]
    cache_path = BG_CACHE_DIR / f"bg_{cache_key}.jpg"

    if cache_path.exists():
        print_info(f"キャッシュから背景画像を読み込み: {cache_path}")
        return cache_path

    try:
        print_info(f"Unsplash APIで背景画像を検索: {query}")

        headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
        params = {
            "query": query,
            "per_page": 10,
            "orientation": "landscape",
        }

        response = requests.get(UNSPLASH_API_URL, headers=headers, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])

        if not results:
            print_error("画像が見つかりませんでした")
            return None

        # 指定されたインデックスの画像を取得
        photo = results[index % len(results)]
        image_url = photo["urls"]["regular"]

        # 画像をダウンロード
        print_info(f"画像をダウンロード中...")
        img_response = requests.get(image_url, timeout=30)
        img_response.raise_for_status()

        # 保存
        ensure_dirs()
        with open(cache_path, "wb") as f:
            f.write(img_response.content)

        print_success(f"背景画像を保存: {cache_path}")
        return cache_path

    except requests.RequestException as e:
        print_error(f"Unsplash API エラー: {e}")
        return None


def load_background_image(image_path: Optional[Path] = None, query: str = "cafe interior") -> Image.Image:
    """
    背景画像を読み込み、動画サイズにリサイズ＆暗めに加工

    Args:
        image_path: 画像パス（指定されていればそれを使う）
        query: Unsplash検索クエリ（image_pathがない場合に使用）

    Returns:
        加工済みの背景画像
    """
    if image_path is None or not image_path.exists():
        image_path = fetch_unsplash_image(query)

    if image_path is None or not image_path.exists():
        print_info("フォールバック: 生成背景を使用")
        return create_cafe_background()

    try:
        img = Image.open(image_path).convert("RGB")

        # アスペクト比を維持してリサイズ
        img_ratio = img.width / img.height
        target_ratio = VIDEO_WIDTH / VIDEO_HEIGHT

        if img_ratio > target_ratio:
            # 横長すぎ → 高さに合わせて幅をクロップ
            new_height = img.height
            new_width = int(new_height * target_ratio)
            left = (img.width - new_width) // 2
            img = img.crop((left, 0, left + new_width, new_height))
        else:
            # 縦長すぎ → 幅に合わせて高さをクロップ
            new_width = img.width
            new_height = int(new_width / target_ratio)
            top = (img.height - new_height) // 2
            img = img.crop((0, top, new_width, top + new_height))

        # リサイズ
        img = img.resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.Resampling.LANCZOS)

        # 明るさを少し調整（暗すぎないように）
        from PIL import ImageEnhance
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(0.85)  # 85%の明るさに（ほぼそのまま）

        # 少しぼかす
        img = img.filter(ImageFilter.GaussianBlur(radius=2))

        return img

    except Exception as e:
        print_error(f"画像読み込みエラー: {e}")
        return create_cafe_background()


# キャッシュ用グローバル変数
_cached_background: Optional[Image.Image] = None
_cached_background_query: Optional[str] = None


def get_background(query: str = "bright cafe daytime sunlight interior") -> Image.Image:
    """背景画像を取得（キャッシュ付き）"""
    global _cached_background, _cached_background_query

    if _cached_background is not None and _cached_background_query == query:
        return _cached_background.copy()

    _cached_background = load_background_image(query=query)
    _cached_background_query = query

    return _cached_background.copy()


# ============================================================
# 描画関数
# ============================================================

def draw_text_with_shadow(draw, pos, text, font, fill=(255, 255, 255)):
    """ドロップシャドウ付きテキスト"""
    x, y = pos
    # 影を描画
    shadow_x = x + SHADOW_OFFSET[0]
    shadow_y = y + SHADOW_OFFSET[1]
    draw.text((shadow_x, shadow_y), text, font=font, fill=SHADOW_COLOR)
    # 本文を描画
    draw.text((x, y), text, font=font, fill=fill)


def draw_subtitle_background(draw, is_upper: bool):
    """上半分または下半分に半透明グレー背景を描画（中央に隙間あり）"""
    if is_upper:
        # 上半分（相談者）- 中央から隙間分上まで
        draw.rectangle(
            [(0, 0), (VIDEO_WIDTH, HALF_HEIGHT - CENTER_GAP // 2)],
            fill=SUBTITLE_BG_COLOR
        )
    else:
        # 下半分（回答者）- 中央から隙間分下から
        draw.rectangle(
            [(0, HALF_HEIGHT + CENTER_GAP // 2), (VIDEO_WIDTH, VIDEO_HEIGHT)],
            fill=SUBTITLE_BG_COLOR
        )


def create_silhouette(size, is_female=True):
    """シルエット生成"""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    center_x = size // 2
    head_radius = size // 4
    head_y = size // 3

    # 頭
    draw.ellipse([center_x - head_radius, head_y - head_radius,
                  center_x + head_radius, head_y + head_radius],
                 fill=(255, 255, 255, 230))

    # 体
    body_top = head_y + head_radius - 5
    body_width = size // 2
    draw.ellipse([center_x - body_width//2, body_top,
                  center_x + body_width//2, size],
                 fill=(255, 255, 255, 230))

    # 女性は髪
    if is_female:
        hair_width = head_radius + 8
        draw.ellipse([center_x - hair_width, head_y - head_radius - 5,
                      center_x + hair_width, head_y + head_radius + 15],
                     fill=(255, 255, 255, 230))

    return img


def create_cafe_background():
    """喫茶店風背景"""
    img = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), CAFE_BG_BASE)
    draw = ImageDraw.Draw(img)

    # グラデーション
    for y in range(VIDEO_HEIGHT):
        ratio = y / VIDEO_HEIGHT
        r = int(65 + ratio * 20)
        g = int(45 + ratio * 15)
        b = int(35 + ratio * 10)
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=(r, g, b))

    # 木目風ライン
    for y in range(0, VIDEO_HEIGHT, 40):
        draw.line([(0, y), (VIDEO_WIDTH, y)], fill=(90, 65, 50), width=1)

    return img


def create_frame(
    speaker: str,
    text: str,
    bg_query: str = "bright cafe daytime sunlight interior",
    consulter_text: str = "",
    advisor_text: str = "",
) -> Image.Image:
    """
    1フレームを生成（上下分割：相談者=上半分、回答者=下半分）
    両方のテキストを同時に表示可能

    Args:
        speaker: "consulter" or "advisor"（現在話している人）
        text: 現在話しているテキスト
        bg_query: 背景画像のUnsplash検索クエリ
        consulter_text: 相談者のテキスト（上半分に表示）
        advisor_text: 回答者のテキスト（下半分に表示）
    """
    # 背景（Unsplash APIから取得）
    img = get_background(bg_query)
    draw = ImageDraw.Draw(img, 'RGBA')

    # フォント
    try:
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE_MAIN)
    except:
        # フォールバック: Ubuntu用のNotoフォント
        fallback_fonts = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
        ]
        font = None
        for fb_font in fallback_fonts:
            if os.path.exists(fb_font):
                font = ImageFont.truetype(fb_font, FONT_SIZE_MAIN)
                break
        if font is None:
            font = ImageFont.load_default()

    line_height = 100  # 行間

    # 相談者テキストがあれば上半分に描画
    if consulter_text:
        draw_subtitle_background(draw, is_upper=True)
        lines = wrap_text(consulter_text)
        total_lines = min(len(lines), SUBTITLE_MAX_LINES)
        total_height = total_lines * line_height
        area_height = HALF_HEIGHT - CENTER_GAP // 2
        start_y = (area_height - total_height) // 2
        text_y = start_y
        for line in lines[:SUBTITLE_MAX_LINES]:
            line_bbox = draw.textbbox((0, 0), line, font=font)
            line_width = line_bbox[2] - line_bbox[0]
            line_x = (VIDEO_WIDTH - line_width) // 2
            draw_text_with_shadow(draw, (line_x, text_y), line, font)
            text_y += line_height

    # 回答者テキストがあれば下半分に描画
    if advisor_text:
        draw_subtitle_background(draw, is_upper=False)
        lines = wrap_text(advisor_text)
        total_lines = min(len(lines), SUBTITLE_MAX_LINES)
        total_height = total_lines * line_height
        area_top = HALF_HEIGHT + CENTER_GAP // 2
        area_height = HALF_HEIGHT - CENTER_GAP // 2
        start_y = area_top + (area_height - total_height) // 2
        text_y = start_y
        for line in lines[:SUBTITLE_MAX_LINES]:
            line_bbox = draw.textbbox((0, 0), line, font=font)
            line_width = line_bbox[2] - line_bbox[0]
            line_x = (VIDEO_WIDTH - line_width) // 2
            draw_text_with_shadow(draw, (line_x, text_y), line, font)
            text_y += line_height

    return img


# ============================================================
# 動画生成クラス
# ============================================================

class VideoGeneratorV2:
    """動画生成クラス v2"""

    def __init__(self):
        ensure_dirs()
        print_info("VideoGeneratorV2 初期化完了")

    def generate_from_audio_and_script(
        self,
        audio_path: Path,
        script: str,
        output_filename: str = "output.mp4",
        consulter_info: Dict = None,
    ) -> Optional[Path]:
        """音声と台本から動画生成"""

        print_info("動画生成を開始...")

        if not audio_path.exists():
            print_error(f"音声ファイルが見つかりません: {audio_path}")
            return None

        audio_clip = AudioFileClip(str(audio_path))
        total_duration = audio_clip.duration
        print_info(f"音声の長さ: {total_duration:.2f}秒")

        # 台本パース
        lines = parse_script(script)
        if not lines:
            print_error("台本のパースに失敗")
            return None

        print_info(f"セリフ数: {len(lines)}行")

        # タイミング計算（文字数ベース）
        total_chars = sum(len(item["line"]) for item in lines)
        current_time = 0.0
        timings = []

        for item in lines:
            char_ratio = len(item["line"]) / total_chars if total_chars > 0 else 1 / len(lines)
            duration = total_duration * char_ratio
            timings.append({
                "character": item["character"],
                "line": item["line"],
                "start": current_time,
                "duration": duration,
            })
            current_time += duration

        # 各セリフのクリップを生成（字幕を保持）
        print_info("フレームを生成中...")
        clips = []

        # 現在表示中の字幕を追跡
        current_consulter_text = ""
        current_advisor_text = ""

        for i, timing in enumerate(timings):
            print(f"\r  セリフ {i+1}/{len(timings)}", end="", flush=True)

            # 話者判定と字幕更新
            if timing["character"] == CHARACTER_CONSULTER:
                current_consulter_text = timing["line"]
            else:
                current_advisor_text = timing["line"]

            # フレーム生成（両方の字幕を渡す）
            frame_img = create_frame(
                speaker="consulter" if timing["character"] == CHARACTER_CONSULTER else "advisor",
                text=timing["line"],
                consulter_text=current_consulter_text,
                advisor_text=current_advisor_text,
            )

            frame_array = np.array(frame_img)
            clip = ImageClip(frame_array).with_duration(timing["duration"]).with_start(timing["start"])
            clips.append(clip)

        print()

        # 合成
        print_info("動画を合成中...")
        final_video = CompositeVideoClip(clips, size=(VIDEO_WIDTH, VIDEO_HEIGHT))
        final_video = final_video.with_audio(audio_clip)

        output_path = OUTPUT_DIR / output_filename
        print_info(f"動画を出力中: {output_path}")

        final_video.write_videofile(
            str(output_path),
            fps=VIDEO_FPS,
            codec="libx264",
            audio_codec="aac",
            logger="bar",
        )

        audio_clip.close()
        final_video.close()

        file_size = output_path.stat().st_size / (1024 * 1024)
        print_success(f"動画生成完了: {output_path}")
        print_info(f"ファイルサイズ: {file_size:.2f} MB")

        return output_path

    def test_frame(self):
        """テストフレーム生成"""
        print_info("テストフレームを生成中...")

        # 相談者が話している
        img1 = create_frame(
            speaker="consulter",
            text="夫との関係に葛藤があって、どうしても躊躇してしまうんです。",
        )
        path1 = TEMP_DIR / "frame_test_consulter.png"
        img1.save(path1)
        print_success(f"保存: {path1}")

        # 回答者が話している
        img2 = create_frame(
            speaker="advisor",
            text="それは大変でしたね。お気持ちよく分かります。",
        )
        path2 = TEMP_DIR / "frame_test_advisor.png"
        img2.save(path2)
        print_success(f"保存: {path2}")

        return path1, path2


# ============================================================
# メイン
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="人生相談チャンネル 動画生成 v2")
    parser.add_argument("--test-frame", action="store_true", help="テストフレーム生成")
    parser.add_argument("--test-video", action="store_true", help="テスト動画生成")
    parser.add_argument("--audio", type=str, help="音声ファイルパス")
    parser.add_argument("--script", type=str, help="台本ファイルパス")
    parser.add_argument("--output", type=str, default="output.mp4", help="出力ファイル名")

    args = parser.parse_args()

    try:
        generator = VideoGeneratorV2()

        if args.test_frame:
            generator.test_frame()
        elif args.test_video:
            # テスト用台本（15秒程度）
            test_script = f"""
{CHARACTER_CONSULTER}：今日は本当にありがとうございます。実は、最近ちょっと悩んでいることがありまして。

{CHARACTER_ADVISOR}：どうされましたか？何かあったんですか？ゆっくりお話しください。

{CHARACTER_CONSULTER}：ええ、実は夫との関係がうまくいっていなくて、毎日がつらいんです。

{CHARACTER_ADVISOR}：それは大変でしたね。お気持ちよく分かります。いつ頃からそうなったんですか？
"""
            test_audio = Path("output/audio/test_output.mp3")
            if test_audio.exists():
                generator.generate_from_audio_and_script(
                    audio_path=test_audio,
                    script=test_script,
                    output_filename="test_video_v2.mp4",
                )
            else:
                print_error("テスト音声がありません: output/audio/test_output.mp3")
        elif args.audio and args.script:
            with open(args.script, 'r', encoding='utf-8') as f:
                script = f.read()
            generator.generate_from_audio_and_script(
                audio_path=Path(args.audio),
                script=script,
                output_filename=args.output,
            )
        else:
            generator.test_frame()

    except Exception as e:
        print_error(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
