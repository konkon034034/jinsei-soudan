#!/usr/bin/env python3
"""
口コミランキング動画自動生成スクリプト
- Gemini APIで口コミ生成
- 画面生成（番号カード、口コミ画面、掛け合いトーク）
- Gemini TTS音声生成
- MoviePyで動画合成
"""

import os
import json
import random
import tempfile
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image, ImageDraw, ImageFont
import google.generativeai as genai
from google import genai as genai_new
from google.genai import types as genai_types
from moviepy import (
    ImageClip, AudioFileClip, concatenate_videoclips,
    CompositeVideoClip, TextClip
)

# ========== 設定 ==========
BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"
OUTPUT_DIR = BASE_DIR / "output"
THEMES_FILE = BASE_DIR / "themes.json"

# 画面サイズ
WIDTH, HEIGHT = 1920, 1080

# カラーパレット
COLORS = {
    "mint_green": "#5BBFBA",
    "light_gray": "#F5F5F5",
    "cream": "#FFFAF0",
    "yellow": "#FFEB3B",
    "gold": "#FFD700",
    "gray_star": "#D3D3D3",
    "red": "#FF0000",
    "white": "#FFFFFF",
    "black": "#000000",
}

# デザイン設定（design_09 アプリコット系）
DESIGN = {
    "title_bg": "#F57C00",      # タイトル帯: オレンジ
    "bg": "#FFF8E1",            # 背景: クリーム
    "subtitle_bg": "#FBCEB1",   # 字幕帯: アプリコット
    "title_text": "#FFFFFF",    # タイトル文字: 白
    "text_color": "#4E342E",    # 本文: ダークブラウン
    "subtitle_text": "#4E342E", # 字幕文字: ダークブラウン
    "char_outline": "#E07020",  # キャラ枠: オレンジ
    "title_size": 52,           # タイトルフォント
    "text_size": 60,            # 本文フォント（大きく）
    "subtitle_size": 52,        # 字幕フォント（収まるように小さく）
    "title_height": 100,        # タイトル帯高さ
    "subtitle_height": 180,     # 字幕帯高さ（2行対応）
    "char_size": 150,           # キャラサイズ（控えめに）
    "line_height": 1.5,         # 行間倍率
}

# Gemini TTS 音声設定
VOICE_CONFIG = {
    "katsumi": "Kore",   # 女性声
    "hiroshi": "Puck",   # 男性声
}

# テストモード（口コミ件数）
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"
TEST_COUNT = 5  # テスト時の口コミ件数


def hex_to_rgb(hex_color):
    """HEXカラーをRGBタプルに変換"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def draw_text_with_effects(draw, pos, text, font, fill, outline_color=None, shadow=True,
                           outline_width=1, shadow_strength=2, shadow_alpha=40):
    """テキストに影と縁取りを付けて描画（控えめ設定）"""
    x, y = pos
    fill_rgb = hex_to_rgb(fill) if isinstance(fill, str) else fill

    # 影（控えめに）
    if shadow:
        for offset in range(1, 1 + shadow_strength):
            draw.text((x + offset, y + offset), text, font=font, fill=(0, 0, 0, shadow_alpha))

    # 縁取り（控えめに）
    if outline_color:
        outline_rgb = hex_to_rgb(outline_color) if isinstance(outline_color, str) else outline_color
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), text, font=font, fill=outline_rgb)

    # 本文
    draw.text((x, y), text, font=font, fill=fill_rgb)


def get_font(size=48, bold=False):
    """日本語フォントを取得"""
    font_paths = [
        # Linux (GitHub Actions) - Noto CJK fonts
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        # macOS
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except:
                continue
    return ImageFont.load_default()


def create_number_card(num, rating, theme_title):
    """
    番号カードを作成（旧デザイン - 後方互換用）
    """
    img = Image.new('RGB', (WIDTH, HEIGHT), hex_to_rgb(COLORS["mint_green"]))
    draw = ImageDraw.Draw(img)

    card_w, card_h = 800, 500
    card_x = (WIDTH - card_w) // 2
    card_y = (HEIGHT - card_h) // 2
    draw.rounded_rectangle(
        [card_x, card_y, card_x + card_w, card_y + card_h],
        radius=30,
        fill=hex_to_rgb(COLORS["white"])
    )

    font_title = get_font(36)
    title_bbox = draw.textbbox((0, 0), theme_title, font=font_title)
    title_w = title_bbox[2] - title_bbox[0]
    draw.text(
        ((WIDTH - title_w) // 2, card_y + 40),
        theme_title,
        fill=hex_to_rgb(COLORS["black"]),
        font=font_title
    )

    num_text = f"口コミ {num}"
    font_num = get_font(80, bold=True)
    num_bbox = draw.textbbox((0, 0), num_text, font=font_num)
    num_w = num_bbox[2] - num_bbox[0]
    draw.text(
        ((WIDTH - num_w) // 2, card_y + 150),
        num_text,
        fill=hex_to_rgb("#333333"),
        font=font_num
    )

    star_y = card_y + 300
    star_size = 50
    star_spacing = 60
    total_star_width = 5 * star_spacing
    start_x = (WIDTH - total_star_width) // 2

    for i in range(5):
        x = start_x + i * star_spacing
        color = hex_to_rgb(COLORS["gold"]) if i < rating else hex_to_rgb(COLORS["gray_star"])
        draw.ellipse([x, star_y, x + star_size, star_y + star_size], fill=color)

    rating_text = f"評価: {'★' * rating}{'☆' * (5 - rating)}"
    font_rating = get_font(36)
    rating_bbox = draw.textbbox((0, 0), rating_text, font=font_rating)
    rating_w = rating_bbox[2] - rating_bbox[0]
    draw.text(
        ((WIDTH - rating_w) // 2, star_y + 70),
        rating_text,
        fill=hex_to_rgb("#666666"),
        font=font_rating
    )

    return img


def create_gradient_background(width, height):
    """グラデーション背景を作成（黄色/ゴールド/ベージュ系）"""
    img = Image.new('RGB', (width, height))
    pixels = img.load()

    # グラデーションカラー定義
    colors = [
        (255, 248, 220),  # #FFF8DC - コーンシルク
        (255, 228, 181),  # #FFE4B5 - モカシン
        (255, 215, 0),    # #FFD700 - ゴールド
        (218, 165, 32),   # #DAA520 - ゴールデンロッド
        (245, 222, 179),  # #F5DEB3 - 小麦
    ]

    for y in range(height):
        for x in range(width):
            # 135度グラデーション
            t = (x + y) / (width + height)

            # 5色間の補間
            segment = t * (len(colors) - 1)
            idx = int(segment)
            idx = min(idx, len(colors) - 2)
            local_t = segment - idx

            r = int(colors[idx][0] * (1 - local_t) + colors[idx + 1][0] * local_t)
            g = int(colors[idx][1] * (1 - local_t) + colors[idx + 1][1] * local_t)
            b = int(colors[idx][2] * (1 - local_t) + colors[idx + 1][2] * local_t)

            pixels[x, y] = (r, g, b)

    return img


def create_rank_card(rank, percent, topic=""):
    """
    口コミランキングカード
    - グラデーション背景
    - 第X位 + 支持率ラベル + グラフバー + パーセント
    - トピック名
    - カツミ・ヒロシ下部配置
    """
    # グラデーション背景
    img = create_gradient_background(WIDTH, HEIGHT).convert('RGBA')
    draw = ImageDraw.Draw(img)

    # カラー定義
    text_brown = (139, 115, 85)  # #8B7355
    orange_red = (255, 107, 53)  # #FF6B35

    # === 第X位（上部中央、影付き）===
    title_font = get_font(150)  # 140 -> 150
    title_text = f"第{rank}位"
    bbox = draw.textbbox((0, 0), title_text, font=title_font)
    title_x = (WIDTH - (bbox[2] - bbox[0])) // 2
    title_y = 50

    # 影（多重）
    shadow_data = [
        (10, 10, (0, 0, 0, 50)),      # ぼかし影
        (6, 6, (205, 133, 63)),       # #CD853F
        (3, 3, (255, 215, 0)),        # #FFD700
    ]
    for ox, oy, color in shadow_data:
        draw.text((title_x + ox, title_y + oy), title_text, fill=color[:3], font=title_font)

    # メイン文字
    draw.text((title_x, title_y), title_text, fill=text_brown, font=title_font)

    # === 支持率ラベル ===
    label_font = get_font(80)  # フォントサイズ拡大（32→80）
    label_text = "支持率"
    label_bbox = draw.textbbox((0, 0), label_text, font=label_font)
    label_x = (WIDTH - (label_bbox[2] - label_bbox[0])) // 2
    label_y = title_y + 180  # 第X位の直下に配置
    draw.text((label_x, label_y), label_text, fill=text_brown, font=label_font)

    # === グラフバー ===
    bar_max_width = int(WIDTH * 0.8)
    bar_height = 50
    bar_x = (WIDTH - bar_max_width) // 2
    bar_y = label_y + 100  # 支持率が大きくなったので下にずらす

    # バー背景（半透明グレー）
    draw.rounded_rectangle(
        [bar_x, bar_y, bar_x + bar_max_width, bar_y + bar_height],
        radius=25,
        fill=(200, 200, 200, 100)
    )

    # バー実体（オレンジ→イエロー→グリーン グラデーション）
    bar_width = int(bar_max_width * percent / 100)
    if bar_width > 0:
        bar_img = Image.new('RGBA', (bar_width, bar_height), (0, 0, 0, 0))
        bar_pixels = bar_img.load()
        for bx in range(bar_width):
            t = bx / bar_width
            # #FF6B00 → #FFB800 → #7FD858
            if t < 0.5:
                t2 = t * 2
                r = int(255)
                g = int(107 + (184 - 107) * t2)
                b = int(0)
            else:
                t2 = (t - 0.5) * 2
                r = int(255 - (255 - 127) * t2)
                g = int(184 + (216 - 184) * t2)
                b = int(0 + 88 * t2)
            for by in range(bar_height):
                bar_pixels[bx, by] = (r, g, b, 255)

        # 角丸マスク
        mask = Image.new('L', (bar_width, bar_height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([0, 0, bar_width, bar_height], radius=25, fill=255)
        bar_img.putalpha(mask)
        img.paste(bar_img, (bar_x, bar_y), bar_img)

    # === パーセント（派手に）===
    percent_font = get_font(100)  # そのまま100px
    percent_text = f"{percent}%"
    percent_bbox = draw.textbbox((0, 0), percent_text, font=percent_font)
    percent_x = (WIDTH - (percent_bbox[2] - percent_bbox[0])) // 2
    percent_y = bar_y + bar_height + 20

    # 白縁取り
    for ox in range(-3, 4):
        for oy in range(-3, 4):
            if ox != 0 or oy != 0:
                draw.text((percent_x + ox, percent_y + oy), percent_text, fill=(255, 255, 255), font=percent_font)

    draw.text((percent_x, percent_y), percent_text, fill=orange_red, font=percent_font)

    # === トピック名（でっかく派手に！）===
    if topic:
        topic_font = get_font(96)  # 2倍サイズ
        topic_text = f"「{topic}」"

        # タイトルが18文字以上の場合は2行に分割
        if len(topic) >= 18:
            # 中間で分割
            mid = len(topic) // 2
            line1 = f"「{topic[:mid]}"
            line2 = f"{topic[mid:]}」"
            topic_lines = [line1, line2]
        else:
            topic_lines = [topic_text]

        topic_y = percent_y + 130
        line_spacing = 110  # 行間

        for idx, line in enumerate(topic_lines):
            topic_bbox = draw.textbbox((0, 0), line, font=topic_font)
            topic_x = (WIDTH - (topic_bbox[2] - topic_bbox[0])) // 2
            current_y = topic_y + idx * line_spacing

            # 影（ぼかし効果）
            for i in range(6, 0, -1):
                alpha = int(40 * (7 - i) / 6)
                shadow_color = (0, 0, 0)
                draw.text((topic_x + i, current_y + i), line, fill=shadow_color, font=topic_font)

            # 白縁取り（太め 4px）
            for ox in range(-4, 5):
                for oy in range(-4, 5):
                    if ox != 0 or oy != 0:
                        draw.text((topic_x + ox, current_y + oy), line, fill=(255, 255, 255), font=topic_font)

            # メイン文字（オレンジレッド #FF4500）
            draw.text((topic_x, current_y), line, fill=(255, 69, 0), font=topic_font)

    # === キャラクター（下部配置）===
    char_size = 300
    char_y = HEIGHT - char_size - 30

    # カツミ（左下）
    katsumi_x = 100
    katsumi_path = ASSETS_DIR / "katsumi.png"
    if katsumi_path.exists():
        katsumi_img = Image.open(katsumi_path).convert('RGBA')
        katsumi_img = katsumi_img.resize((char_size, char_size), Image.Resampling.LANCZOS)
        img.paste(katsumi_img, (katsumi_x, char_y), katsumi_img)

    # ヒロシ（右下）
    hiroshi_x = WIDTH - char_size - 100
    hiroshi_path = ASSETS_DIR / "hiroshi.png"
    if hiroshi_path.exists():
        hiroshi_img = Image.open(hiroshi_path).convert('RGBA')
        hiroshi_img = hiroshi_img.resize((char_size, char_size), Image.Resampling.LANCZOS)
        img.paste(hiroshi_img, (hiroshi_x, char_y), hiroshi_img)

    return img.convert('RGB')


def wrap_text(text, font, max_width, draw):
    """テキストを指定幅で折り返し"""
    lines = []
    current_line = ""

    for char in text:
        test_line = current_line + char
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = char

    if current_line:
        lines.append(current_line)

    return lines


def create_animated_rank_card_frame(rank, percent, topic, t):
    """
    アニメーション付きランキングカードのフレームを生成
    t: 時間（秒）

    アニメーションタイムライン:
    - 0.0-0.2s: 待機
    - 0.2-0.4s: 第X位がスケールイン
    - 0.4-0.6s: 支持率ラベル表示
    - 0.6-1.8s: バーが伸びる（1.2秒）
    - 1.4-1.6s: パーセント表示
    - 1.8-2.0s: トピック表示
    - 2.0-3.0s: ホールド
    """
    img = create_gradient_background(WIDTH, HEIGHT).convert('RGBA')
    draw = ImageDraw.Draw(img)

    text_brown = (139, 115, 85)
    orange_red = (255, 107, 53)

    # === アニメーション計算 ===
    # 第X位: 0.2-0.4秒でスケールイン
    rank_scale = 0 if t < 0.2 else min(1.0, (t - 0.2) / 0.2)
    rank_scale = ease_out_back(rank_scale)  # バウンス効果

    # 支持率ラベル: 0.4秒以降
    label_alpha = 0 if t < 0.4 else min(1.0, (t - 0.4) / 0.2)

    # バー進捗: 0.6-1.8秒で伸びる
    bar_progress = 0 if t < 0.6 else min(1.0, (t - 0.6) / 1.2)
    bar_progress = ease_out_quad(bar_progress)

    # パーセント: 1.4秒以降
    percent_alpha = 0 if t < 1.4 else min(1.0, (t - 1.4) / 0.2)

    # トピック: 1.8秒以降
    topic_alpha = 0 if t < 1.8 else min(1.0, (t - 1.8) / 0.2)

    # キャラ: 最初から表示
    char_visible = True

    # === 第X位（スケールアニメーション）===
    if rank_scale > 0:
        title_font_size = int(140 * rank_scale)
        if title_font_size > 10:
            title_font = get_font(title_font_size)
            title_text = f"第{rank}位"
            bbox = draw.textbbox((0, 0), title_text, font=title_font)
            title_w = bbox[2] - bbox[0]
            title_h = bbox[3] - bbox[1]
            title_x = (WIDTH - title_w) // 2
            title_y = 50 + int((1 - rank_scale) * 30)  # 少し下から上へ

            # 影
            for ox, oy, color in [(10, 10, (0, 0, 0)), (6, 6, (205, 133, 63)), (3, 3, (255, 215, 0))]:
                draw.text((title_x + int(ox * rank_scale), title_y + int(oy * rank_scale)),
                          title_text, fill=color, font=title_font)
            draw.text((title_x, title_y), title_text, fill=text_brown, font=title_font)

    # === 支持率ラベル ===
    if label_alpha > 0:
        label_font = get_font(80)  # フォントサイズ拡大（32→80）
        label_text = "支持率"
        label_bbox = draw.textbbox((0, 0), label_text, font=label_font)
        label_x = (WIDTH - (label_bbox[2] - label_bbox[0])) // 2
        label_y = 230  # 第X位の直下に配置
        alpha_color = tuple(int(c * label_alpha) for c in text_brown)
        draw.text((label_x, label_y), label_text, fill=text_brown, font=label_font)

    # === グラフバー ===
    bar_max_width = int(WIDTH * 0.8)
    bar_height = 50
    bar_x = (WIDTH - bar_max_width) // 2
    bar_y = 330  # 支持率が大きくなったので下にずらす（280→330）

    # バー背景
    draw.rounded_rectangle(
        [bar_x, bar_y, bar_x + bar_max_width, bar_y + bar_height],
        radius=25, fill=(200, 200, 200, 100)
    )

    # バー実体（アニメーション）
    current_percent = percent * bar_progress
    bar_width = int(bar_max_width * current_percent / 100)
    if bar_width > 5:
        bar_img = Image.new('RGBA', (bar_width, bar_height), (0, 0, 0, 0))
        bar_pixels = bar_img.load()
        for bx in range(bar_width):
            t_bar = bx / max(bar_width, 1)
            if t_bar < 0.5:
                t2 = t_bar * 2
                r, g, b = 255, int(107 + 77 * t2), 0
            else:
                t2 = (t_bar - 0.5) * 2
                r = int(255 - 128 * t2)
                g = int(184 + 32 * t2)
                b = int(88 * t2)
            for by in range(bar_height):
                bar_pixels[bx, by] = (r, g, b, 255)
        mask = Image.new('L', (bar_width, bar_height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([0, 0, bar_width, bar_height], radius=25, fill=255)
        bar_img.putalpha(mask)
        img.paste(bar_img, (bar_x, bar_y), bar_img)

    # === パーセント ===
    if percent_alpha > 0:
        percent_font = get_font(100)
        percent_text = f"{int(current_percent)}%"
        percent_bbox = draw.textbbox((0, 0), percent_text, font=percent_font)
        percent_x = (WIDTH - (percent_bbox[2] - percent_bbox[0])) // 2
        percent_y = bar_y + bar_height + 20

        # 白縁取り
        for ox in range(-3, 4):
            for oy in range(-3, 4):
                if ox != 0 or oy != 0:
                    draw.text((percent_x + ox, percent_y + oy), percent_text, fill=(255, 255, 255), font=percent_font)
        draw.text((percent_x, percent_y), percent_text, fill=orange_red, font=percent_font)

    # === トピック名（自動改行対応） ===
    if topic and topic_alpha > 0:
        topic_font = get_font(96)
        topic_text = f"「{topic}」"
        max_topic_width = int(WIDTH * 0.9)  # 画面幅の90%まで

        # テキスト幅をチェックして必要なら改行
        topic_bbox = draw.textbbox((0, 0), topic_text, font=topic_font)
        topic_text_width = topic_bbox[2] - topic_bbox[0]

        if topic_text_width > max_topic_width:
            # 改行が必要
            topic_lines = wrap_text(topic_text, topic_font, max_topic_width, draw)
        else:
            topic_lines = [topic_text]

        topic_y = 500  # バー位置調整に合わせて下にずらす（450→500）
        line_height = 110  # 行間

        for line_idx, line in enumerate(topic_lines):
            line_bbox = draw.textbbox((0, 0), line, font=topic_font)
            line_x = (WIDTH - (line_bbox[2] - line_bbox[0])) // 2
            line_y = topic_y + line_idx * line_height

            # 影
            for i in range(6, 0, -1):
                draw.text((line_x + i, line_y + i), line, fill=(0, 0, 0), font=topic_font)
            # 白縁取り
            for ox in range(-4, 5):
                for oy in range(-4, 5):
                    if ox != 0 or oy != 0:
                        draw.text((line_x + ox, line_y + oy), line, fill=(255, 255, 255), font=topic_font)
            draw.text((line_x, line_y), line, fill=(255, 69, 0), font=topic_font)

    # === キャラクターは表示しない（順位発表画面はシンプルに） ===

    return img.convert('RGB')


def ease_out_back(t):
    """バウンス効果のイージング"""
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)


def ease_out_quad(t):
    """スムーズなイージング"""
    return 1 - (1 - t) * (1 - t)


def ease_out_elastic(t):
    """弾むようなイージング"""
    if t == 0:
        return 0
    if t == 1:
        return 1
    p = 0.3
    s = p / 4
    return pow(2, -10 * t) * pow(2, 10 * (t - 1)) * (-1) + 1


def create_animated_rank_card_clip(rank, percent, topic, duration=3.0, fps=30):
    """アニメーション付きランキングカードのVideoClipを生成"""
    import numpy as np

    def make_frame(t):
        img = create_animated_rank_card_frame(rank, percent, topic, t)
        return np.array(img)

    from moviepy import VideoClip
    clip = VideoClip(make_frame, duration=duration)
    return clip


def create_animated_kuchikomi_frame(num, text, speaker, theme_title, subtitle, t, total_duration):
    """
    アニメーション付き口コミ読み上げ画面のフレームを生成

    アニメーションタイムライン:
    - 0.0-0.2s: 待機
    - 0.2-1.0s: タイトルバーが左(-600px)→左端(0px)へスライド
    - 0.8s〜: 口コミテキストが1文字50msでタイピング表示
    - 1.0-1.3s: カツミが下(-200px)→下部へバウンド
    - 1.2-1.5s: ヒロシが下(-200px)→下部へバウンド
    - 話し手のキャラは上下に揺れる
    """
    import math

    img = Image.new('RGBA', (WIDTH, HEIGHT), hex_to_rgb(DESIGN["bg"]) + (255,))
    draw = ImageDraw.Draw(img)

    # フォント
    title_font = get_font(DESIGN["title_size"])
    text_font = get_font(DESIGN["text_size"])
    subtitle_font = get_font(DESIGN["subtitle_size"])
    name_font = get_font(24)

    title_height = DESIGN["title_height"]
    subtitle_height = DESIGN["subtitle_height"]
    char_size = 200  # キャラサイズを大きく

    # === アニメーション計算 ===
    # タイトルバー: 0.2-1.0秒でスライド
    if t < 0.2:
        title_offset_x = -600
    elif t < 1.0:
        progress = (t - 0.2) / 0.8
        progress = ease_out_quad(progress)
        title_offset_x = int(-600 * (1 - progress))
    else:
        title_offset_x = 0

    # テキストタイピング: 0.8秒から開始、1文字50ms
    typing_start = 0.8
    chars_per_second = 20  # 1文字50ms = 20文字/秒
    if t < typing_start:
        visible_chars = 0
    else:
        visible_chars = int((t - typing_start) * chars_per_second)
    visible_chars = min(visible_chars, len(text))

    # カーソル点滅（500ms周期）
    cursor_visible = (int(t * 4) % 2 == 0) if visible_chars < len(text) else False

    # カツミ: 1.0-1.3秒でバウンド
    katsumi_start_y = HEIGHT + 50  # 画面外下
    katsumi_end_y = HEIGHT - subtitle_height - char_size + 20
    if t < 1.0:
        katsumi_y = katsumi_start_y
    elif t < 1.3:
        progress = (t - 1.0) / 0.3
        progress = ease_out_back(progress)
        katsumi_y = int(katsumi_start_y + (katsumi_end_y - katsumi_start_y) * progress)
    else:
        katsumi_y = katsumi_end_y

    # ヒロシ: 1.2-1.5秒でバウンド
    hiroshi_start_y = HEIGHT + 50
    hiroshi_end_y = HEIGHT - subtitle_height - char_size + 20
    if t < 1.2:
        hiroshi_y = hiroshi_start_y
    elif t < 1.5:
        progress = (t - 1.2) / 0.3
        progress = ease_out_back(progress)
        hiroshi_y = int(hiroshi_start_y + (hiroshi_end_y - hiroshi_start_y) * progress)
    else:
        hiroshi_y = hiroshi_end_y

    # 話し手キャラの揺れ → 全部なし（チャンク音声の一貫性維持）
    speaker_wobble = 0

    # === タイトルバー（上部）===
    # 薄い影
    for offset in range(1, 4):
        alpha = 30 - offset * 8
        draw.rectangle([title_offset_x, title_height + offset,
                       WIDTH + title_offset_x, title_height + offset + 1],
                       fill=(0, 0, 0, max(alpha, 0)))
    draw.rectangle([title_offset_x, 0, WIDTH + title_offset_x, title_height],
                  fill=hex_to_rgb(DESIGN["title_bg"]))

    # タイトルテキスト
    header_text = f"{theme_title} - 口コミ{num}"
    bbox = draw.textbbox((0, 0), header_text, font=title_font)
    title_text_x = title_offset_x + (WIDTH - (bbox[2] - bbox[0])) // 2
    title_text_y = (title_height - (bbox[3] - bbox[1])) // 2
    if title_offset_x > -WIDTH:  # 画面内にある場合のみ描画
        draw_text_with_effects(draw, (title_text_x, title_text_y), header_text, title_font,
                               DESIGN["title_text"], None, shadow=True,
                               shadow_strength=2, shadow_alpha=30)

    # === 口コミテキスト（タイピング表示）===
    kuchikomi_y = title_height + 60
    max_text_width = WIDTH - 160

    # 表示する文字列
    display_text = text[:visible_chars]
    if cursor_visible:
        display_text += "｜"

    # 折り返し処理
    lines = wrap_text(display_text, text_font, max_text_width, draw)
    line_spacing = int(DESIGN["text_size"] * 1.5)

    for i, line in enumerate(lines):
        draw_text_with_effects(draw, (80, kuchikomi_y + i * line_spacing), line, text_font,
                               DESIGN["text_color"], None, shadow=True,
                               shadow_strength=1, shadow_alpha=25)

    # === 字幕エリア（下部）→ 帯のみ、字幕は削除（上のトピックと重複するため）===
    subtitle_y = HEIGHT - subtitle_height
    for offset in range(1, 3):
        alpha = 20 - offset * 6
        draw.rectangle([0, subtitle_y - offset - 1, WIDTH, subtitle_y - offset],
                       fill=(0, 0, 0, max(alpha, 0)))
    draw.rectangle([0, subtitle_y, WIDTH, HEIGHT], fill=hex_to_rgb(DESIGN["subtitle_bg"]))

    # 字幕テキストは表示しない（削除）

    # === キャラクター（新しい画像を使用）===
    katsumi_x = 30
    hiroshi_x = WIDTH - char_size - 30

    # 話し手に揺れを適用
    if speaker == "katsumi":
        katsumi_y += speaker_wobble
    elif speaker == "hiroshi":
        hiroshi_y += speaker_wobble

    # カツミ
    katsumi_path = ASSETS_DIR / "katsumi.png"
    if katsumi_path.exists() and katsumi_y < HEIGHT:
        katsumi_img = Image.open(katsumi_path).convert('RGBA')
        katsumi_img = katsumi_img.resize((char_size, char_size), Image.Resampling.LANCZOS)

        # 話し手なら少し大きく・明るく
        if speaker == "katsumi":
            # 少し拡大
            scale = 1.1
            new_size = int(char_size * scale)
            katsumi_img = katsumi_img.resize((new_size, new_size), Image.Resampling.LANCZOS)
            paste_x = katsumi_x - (new_size - char_size) // 2
            paste_y = katsumi_y - (new_size - char_size)
        else:
            paste_x = katsumi_x
            paste_y = katsumi_y

        if paste_y + katsumi_img.height > 0:  # 画面内にある場合
            img.paste(katsumi_img, (paste_x, paste_y), katsumi_img)
            # 名前は表示しない（create_kuchikomi_talk_frameと統一）

    # ヒロシ
    hiroshi_path = ASSETS_DIR / "hiroshi.png"
    if hiroshi_path.exists() and hiroshi_y < HEIGHT:
        hiroshi_img = Image.open(hiroshi_path).convert('RGBA')
        hiroshi_img = hiroshi_img.resize((char_size, char_size), Image.Resampling.LANCZOS)

        if speaker == "hiroshi":
            scale = 1.1
            new_size = int(char_size * scale)
            hiroshi_img = hiroshi_img.resize((new_size, new_size), Image.Resampling.LANCZOS)
            paste_x = hiroshi_x - (new_size - char_size) // 2
            paste_y = hiroshi_y - (new_size - char_size)
        else:
            paste_x = hiroshi_x
            paste_y = hiroshi_y

        if paste_y + hiroshi_img.height > 0:
            img.paste(hiroshi_img, (paste_x, paste_y), hiroshi_img)
            # 名前は表示しない（create_kuchikomi_talk_frameと統一）

    return img.convert('RGB')


def create_animated_kuchikomi_clip(num, text, speaker, theme_title, subtitle, duration, fps=24):
    """アニメーション付き口コミ読み上げ画面のVideoClipを生成"""
    import numpy as np
    from moviepy import VideoClip

    def make_frame(t):
        img = create_animated_kuchikomi_frame(num, text, speaker, theme_title, subtitle, t, duration)
        return np.array(img)

    clip = VideoClip(make_frame, duration=duration)
    return clip


def create_kuchikomi_talk_frame(num, kuchikomi_text, theme_title, speaker, talk_subtitle, t):
    """
    口コミ画面ベースのトーク画面（画面切り替えなし）
    - 背景: 口コミ読み上げ画面と同じ
    - 口コミテキストは表示したまま
    - 下部に字幕帯を追加してトークを表示
    - キャラクターは字幕帯の左右に配置
    """
    import math

    img = Image.new('RGBA', (WIDTH, HEIGHT), hex_to_rgb(DESIGN["bg"]) + (255,))
    draw = ImageDraw.Draw(img)

    # フォント
    title_font = get_font(DESIGN["title_size"])
    text_font = get_font(DESIGN["text_size"])
    subtitle_font = get_font(DESIGN["subtitle_size"])
    name_font = get_font(24)

    title_height = DESIGN["title_height"]
    subtitle_height = DESIGN["subtitle_height"]
    char_size = 200

    # === タイトルバー（上部）===
    for offset in range(1, 4):
        alpha = 30 - offset * 8
        draw.rectangle([0, title_height + offset, WIDTH, title_height + offset + 1],
                       fill=(0, 0, 0, max(alpha, 0)))
    draw.rectangle([0, 0, WIDTH, title_height], fill=hex_to_rgb(DESIGN["title_bg"]))

    # タイトルテキスト
    header_text = f"{theme_title} - 口コミ{num}"
    bbox = draw.textbbox((0, 0), header_text, font=title_font)
    title_text_x = (WIDTH - (bbox[2] - bbox[0])) // 2
    title_text_y = (title_height - (bbox[3] - bbox[1])) // 2
    draw_text_with_effects(draw, (title_text_x, title_text_y), header_text, title_font,
                           DESIGN["title_text"], None, shadow=True,
                           shadow_strength=2, shadow_alpha=30)

    # === 口コミテキスト（全文表示、静的）===
    kuchikomi_y = title_height + 60
    max_text_width = WIDTH - 160

    lines = wrap_text(kuchikomi_text, text_font, max_text_width, draw)
    line_spacing = int(DESIGN["text_size"] * 1.5)

    for i, line in enumerate(lines):
        draw_text_with_effects(draw, (80, kuchikomi_y + i * line_spacing), line, text_font,
                               DESIGN["text_color"], None, shadow=True,
                               shadow_strength=1, shadow_alpha=25)

    # === 字幕エリア（下部）===
    subtitle_y = HEIGHT - subtitle_height
    for offset in range(1, 3):
        alpha = 20 - offset * 6
        draw.rectangle([0, subtitle_y - offset - 1, WIDTH, subtitle_y - offset],
                       fill=(0, 0, 0, max(alpha, 0)))
    draw.rectangle([0, subtitle_y, WIDTH, HEIGHT], fill=hex_to_rgb(DESIGN["subtitle_bg"]))

    # === トーク字幕を表示 ===
    if talk_subtitle:
        talk_font = get_font(48)
        speaker_name = "カツミ" if speaker == "katsumi" else "ヒロシ"

        # 話者名の色
        name_color = (233, 30, 99) if speaker == "katsumi" else (33, 150, 243)  # カツミ=ピンク、ヒロシ=水色
        body_color = (255, 255, 255)  # 本文は白

        # 折り返し処理（キャラ分の余白を確保）
        sub_max_width = WIDTH - char_size * 2 - 100
        full_text = f"{speaker_name}：{talk_subtitle}"
        sub_lines = wrap_text(full_text, talk_font, sub_max_width, draw)
        total_sub_height = len(sub_lines) * int(48 * 1.3)
        sub_start_y = subtitle_y + (subtitle_height - total_sub_height) // 2

        for i, line in enumerate(sub_lines):
            sub_x = 50
            sub_y = sub_start_y + i * int(48 * 1.3)

            # 最初の行は話者名と本文を分けて描画
            if i == 0 and "：" in line:
                parts = line.split("：", 1)
                # 話者名部分（影付き）
                for offset in range(1, 2):
                    draw.text((sub_x + offset, sub_y + offset), parts[0] + "：", font=talk_font, fill=(0, 0, 0, 25))
                draw.text((sub_x, sub_y), parts[0] + "：", fill=name_color, font=talk_font)

                # 本文部分の開始位置を計算
                name_bbox = draw.textbbox((0, 0), parts[0] + "：", font=talk_font)
                body_x = sub_x + (name_bbox[2] - name_bbox[0])

                # 本文部分（影付き）
                for offset in range(1, 2):
                    draw.text((body_x + offset, sub_y + offset), parts[1], font=talk_font, fill=(0, 0, 0, 25))
                draw.text((body_x, sub_y), parts[1], fill=body_color, font=talk_font)
            else:
                # 2行目以降は本文のみ（白）
                for offset in range(1, 2):
                    draw.text((sub_x + offset, sub_y + offset), line, font=talk_font, fill=(0, 0, 0, 25))
                draw.text((sub_x, sub_y), line, fill=body_color, font=talk_font)

    # === キャラクター（create_animated_kuchikomi_frameと同じ位置に統一）===
    # 固定位置（口コミ読み上げ画面と同じ）
    katsumi_x = 30
    hiroshi_x = WIDTH - char_size - 30
    char_y = HEIGHT - subtitle_height - char_size + 20

    # 話し手の揺れアニメーション（軽い上下動き）
    speaker_wobble = int(math.sin(t * 8) * 5)  # 8Hzで±5px揺れ

    # カツミ（左）
    katsumi_path = ASSETS_DIR / "katsumi.png"
    if katsumi_path.exists():
        katsumi_img = Image.open(katsumi_path).convert('RGBA')
        # 話し手なら少し大きく＋揺れる
        if speaker == "katsumi":
            scale = 1.1
            new_size = int(char_size * scale)
            katsumi_img = katsumi_img.resize((new_size, new_size), Image.Resampling.LANCZOS)
            paste_x = katsumi_x - (new_size - char_size) // 2
            paste_y = char_y - (new_size - char_size) + speaker_wobble
        else:
            katsumi_img = katsumi_img.resize((char_size, char_size), Image.Resampling.LANCZOS)
            paste_x = katsumi_x
            paste_y = char_y
        img.paste(katsumi_img, (paste_x, paste_y), katsumi_img)

    # ヒロシ（右）
    hiroshi_path = ASSETS_DIR / "hiroshi.png"
    if hiroshi_path.exists():
        hiroshi_img = Image.open(hiroshi_path).convert('RGBA')
        if speaker == "hiroshi":
            scale = 1.1
            new_size = int(char_size * scale)
            hiroshi_img = hiroshi_img.resize((new_size, new_size), Image.Resampling.LANCZOS)
            paste_x = hiroshi_x - (new_size - char_size) // 2
            paste_y = char_y - (new_size - char_size) + speaker_wobble
        else:
            hiroshi_img = hiroshi_img.resize((char_size, char_size), Image.Resampling.LANCZOS)
            paste_x = hiroshi_x
            paste_y = char_y
        img.paste(hiroshi_img, (paste_x, paste_y), hiroshi_img)

    return img.convert('RGB')


def create_kuchikomi_talk_clip(num, kuchikomi_text, theme_title, speaker, talk_subtitle, duration, fps=24):
    """口コミ画面ベースのトーク画面のVideoClipを生成"""
    import numpy as np
    from moviepy import VideoClip

    def make_frame(t):
        img = create_kuchikomi_talk_frame(num, kuchikomi_text, theme_title, speaker, talk_subtitle, t)
        return np.array(img)

    clip = VideoClip(make_frame, duration=duration)
    return clip


def create_greenroom_frame(speaker, speech_text, theme_title, t, total_duration):
    """
    控室トーク画面（オフレコ雰囲気）のフレームを生成

    アニメーション:
    - 0-0.3s: フェードイン
    - 話し手キャラが上下に揺れる
    """
    import math

    # 暗めのベージュ/セピア系背景
    bg_color = (221, 213, 199)  # #DDD5C7
    img = Image.new('RGBA', (WIDTH, HEIGHT), bg_color + (255,))
    draw = ImageDraw.Draw(img)

    # フェードイン計算
    if t < 0.3:
        fade_alpha = t / 0.3
    else:
        fade_alpha = 1.0

    # 話し手の揺れ
    speaker_wobble = int(math.sin(t * 6) * 10) if t > 0.3 else 0

    # フォント
    title_font = get_font(36)
    speech_font = get_font(42)
    name_font = get_font(28)

    # === 上部タイトル（控えめ）===
    title_text = f"【控室トーク】{theme_title}"
    bbox = draw.textbbox((0, 0), title_text, font=title_font)
    title_x = (WIDTH - (bbox[2] - bbox[0])) // 2
    title_y = 30
    draw.text((title_x, title_y), title_text, fill=(100, 90, 80), font=title_font)

    # === キャラクター配置（中央寄り、大きめ）===
    char_size = 280

    # カツミ位置（左寄り）
    katsumi_x = WIDTH // 2 - char_size - 100
    katsumi_y = HEIGHT // 2 - char_size // 2 + 50

    # ヒロシ位置（右寄り）
    hiroshi_x = WIDTH // 2 + 100
    hiroshi_y = HEIGHT // 2 - char_size // 2 + 50

    # 話し手の揺れを適用
    if speaker == "katsumi":
        katsumi_y += speaker_wobble
    else:
        hiroshi_y += speaker_wobble

    # カツミを描画
    katsumi_path = ASSETS_DIR / "katsumi.png"
    if katsumi_path.exists():
        katsumi_img = Image.open(katsumi_path).convert('RGBA')
        katsumi_img = katsumi_img.resize((char_size, char_size), Image.Resampling.LANCZOS)
        img.paste(katsumi_img, (katsumi_x, katsumi_y), katsumi_img)
        # 名前
        name_bbox = draw.textbbox((0, 0), "カツミ", font=name_font)
        name_x = katsumi_x + (char_size - (name_bbox[2] - name_bbox[0])) // 2
        draw.text((name_x, katsumi_y + char_size + 10), "カツミ", fill=(80, 70, 60), font=name_font)

    # ヒロシを描画
    hiroshi_path = ASSETS_DIR / "hiroshi.png"
    if hiroshi_path.exists():
        hiroshi_img = Image.open(hiroshi_path).convert('RGBA')
        hiroshi_img = hiroshi_img.resize((char_size, char_size), Image.Resampling.LANCZOS)
        img.paste(hiroshi_img, (hiroshi_x, hiroshi_y), hiroshi_img)
        # 名前
        name_bbox = draw.textbbox((0, 0), "ヒロシ", font=name_font)
        name_x = hiroshi_x + (char_size - (name_bbox[2] - name_bbox[0])) // 2
        draw.text((name_x, hiroshi_y + char_size + 10), "ヒロシ", fill=(80, 70, 60), font=name_font)

    # === 吹き出し（話し手側に表示）===
    bubble_width = 500
    bubble_height = 150
    bubble_radius = 20

    if speaker == "katsumi":
        # カツミの上に吹き出し
        bubble_x = katsumi_x + char_size // 2 - bubble_width // 2
        bubble_y = katsumi_y - bubble_height - 30
    else:
        # ヒロシの上に吹き出し
        bubble_x = hiroshi_x + char_size // 2 - bubble_width // 2
        bubble_y = hiroshi_y - bubble_height - 30

    # 吹き出し背景（白、角丸）
    draw.rounded_rectangle(
        [bubble_x, bubble_y, bubble_x + bubble_width, bubble_y + bubble_height],
        radius=bubble_radius,
        fill=(255, 255, 255),
        outline=(180, 170, 160),
        width=2
    )

    # 吹き出しの尻尾（三角形）
    tail_x = bubble_x + bubble_width // 2
    tail_y = bubble_y + bubble_height
    draw.polygon([
        (tail_x - 15, tail_y),
        (tail_x + 15, tail_y),
        (tail_x, tail_y + 20)
    ], fill=(255, 255, 255), outline=(180, 170, 160))
    # 尻尾の内側を白で塗りつぶし（境界線を消す）
    draw.polygon([
        (tail_x - 12, tail_y),
        (tail_x + 12, tail_y),
        (tail_x, tail_y + 15)
    ], fill=(255, 255, 255))

    # セリフテキスト（折り返し対応）
    lines = wrap_text(speech_text, speech_font, bubble_width - 40, draw)
    total_text_height = len(lines) * 50
    text_start_y = bubble_y + (bubble_height - total_text_height) // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=speech_font)
        text_x = bubble_x + (bubble_width - (bbox[2] - bbox[0])) // 2
        text_y = text_start_y + i * 50
        draw.text((text_x, text_y), line, fill=(60, 50, 40), font=speech_font)

    # === フェードイン処理 ===
    if fade_alpha < 1.0:
        # 半透明の黒オーバーレイでフェード効果
        overlay = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, int(255 * (1 - fade_alpha))))
        img = Image.alpha_composite(img, overlay)

    return img.convert('RGB')


def create_greenroom_clip(speaker, speech_text, theme_title, duration, fps=24):
    """控室トーク画面のVideoClipを生成"""
    import numpy as np
    from moviepy import VideoClip

    def make_frame(t):
        img = create_greenroom_frame(speaker, speech_text, theme_title, t, duration)
        return np.array(img)

    clip = VideoClip(make_frame, duration=duration)
    return clip


def create_talk_with_topic_frame(rank, percent, topic, speaker, subtitle_text, t):
    """
    トピック背景＋字幕でトークを表示するフレームを生成
    - 背景: ランキングカード（静的）
    - 字幕: 下部に表示
    - キャラ: 喋ってる方だけ揺れる
    """
    import math

    img = create_gradient_background(WIDTH, HEIGHT).convert('RGBA')
    draw = ImageDraw.Draw(img)

    text_brown = (139, 115, 85)
    orange_red = (255, 107, 53)

    # === 静的な背景（完成状態のランキングカード）===
    # 第X位
    title_font = get_font(150)
    title_text = f"第{rank}位"
    bbox = draw.textbbox((0, 0), title_text, font=title_font)
    title_w = bbox[2] - bbox[0]
    title_x = (WIDTH - title_w) // 2
    title_y = 50

    for ox, oy, color in [(10, 10, (0, 0, 0)), (6, 6, (205, 133, 63)), (3, 3, (255, 215, 0))]:
        draw.text((title_x + ox, title_y + oy), title_text, fill=color, font=title_font)
    draw.text((title_x, title_y), title_text, fill=text_brown, font=title_font)

    # 支持率ラベル
    label_font = get_font(28)
    label_text = "支持率"
    label_bbox = draw.textbbox((0, 0), label_text, font=label_font)
    label_x = (WIDTH - (label_bbox[2] - label_bbox[0])) // 2
    label_y = 250
    draw.text((label_x, label_y), label_text, fill=text_brown, font=label_font)

    # グラフバー（100%表示）
    bar_max_width = int(WIDTH * 0.8)
    bar_height = 50
    bar_x = (WIDTH - bar_max_width) // 2
    bar_y = 300

    draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_max_width, bar_y + bar_height],
                          radius=25, fill=(200, 200, 200, 100))

    bar_width = int(bar_max_width * percent / 100)
    if bar_width > 5:
        bar_img = Image.new('RGBA', (bar_width, bar_height), (0, 0, 0, 0))
        bar_pixels = bar_img.load()
        for bx in range(bar_width):
            t_bar = bx / max(bar_width, 1)
            if t_bar < 0.5:
                t2 = t_bar * 2
                r, g, b = 255, int(107 + 77 * t2), 0
            else:
                t2 = (t_bar - 0.5) * 2
                r = int(255 - 128 * t2)
                g = int(184 + 32 * t2)
                b = int(88 * t2)
            for by in range(bar_height):
                bar_pixels[bx, by] = (r, g, b, 255)
        mask = Image.new('L', (bar_width, bar_height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([0, 0, bar_width, bar_height], radius=25, fill=255)
        bar_img.putalpha(mask)
        img.paste(bar_img, (bar_x, bar_y), bar_img)

    # パーセント
    percent_font = get_font(100)
    percent_text = f"{percent}%"
    percent_bbox = draw.textbbox((0, 0), percent_text, font=percent_font)
    percent_x = (WIDTH - (percent_bbox[2] - percent_bbox[0])) // 2
    percent_y = bar_y + bar_height + 20

    for ox in range(-3, 4):
        for oy in range(-3, 4):
            if ox != 0 or oy != 0:
                draw.text((percent_x + ox, percent_y + oy), percent_text, fill=(255, 255, 255), font=percent_font)
    draw.text((percent_x, percent_y), percent_text, fill=orange_red, font=percent_font)

    # トピック名
    topic_font = get_font(96)
    topic_text_display = f"「{topic}」"
    topic_bbox = draw.textbbox((0, 0), topic_text_display, font=topic_font)
    topic_x = (WIDTH - (topic_bbox[2] - topic_bbox[0])) // 2
    topic_y = 450

    for i in range(6, 0, -1):
        draw.text((topic_x + i, topic_y + i), topic_text_display, fill=(0, 0, 0), font=topic_font)
    for ox in range(-4, 5):
        for oy in range(-4, 5):
            if ox != 0 or oy != 0:
                draw.text((topic_x + ox, topic_y + oy), topic_text_display, fill=(255, 255, 255), font=topic_font)
    draw.text((topic_x, topic_y), topic_text_display, fill=(255, 69, 0), font=topic_font)

    # === 字幕エリア（下部）===
    subtitle_height = 180
    subtitle_y = HEIGHT - subtitle_height

    # 薄いピンクベージュ背景 rgba(255, 228, 225, 0.9)
    subtitle_bg = Image.new('RGBA', (WIDTH, subtitle_height), (255, 228, 225, 230))  # 0.9 * 255 ≈ 230
    img.paste(subtitle_bg, (0, subtitle_y), subtitle_bg)

    # 字幕テキスト
    if subtitle_text:
        subtitle_font = get_font(48)
        # 話者名＋テキスト
        speaker_name = "カツミ" if speaker == "katsumi" else "ヒロシ"

        # 話者名の色: カツミ=ピンク #FF69B4、ヒロシ=青 #0066CC
        name_color = (255, 105, 180) if speaker == "katsumi" else (0, 102, 204)
        body_color = (139, 69, 19)  # メインテキスト: 茶色 #8B4513

        # 折り返し処理
        max_text_width = WIDTH - 100
        full_text = f"{speaker_name}：{subtitle_text}"
        lines = wrap_text(full_text, subtitle_font, max_text_width, draw)
        line_spacing = int(48 * 1.3)
        total_height = len(lines) * line_spacing
        start_y = subtitle_y + (subtitle_height - total_height) // 2

        for i, line in enumerate(lines):
            line_x = 50
            line_y = start_y + i * line_spacing

            # 最初の行は話者名と本文を分けて描画
            if i == 0 and "：" in line:
                parts = line.split("：", 1)
                # 話者名部分（縁取りなし）
                draw.text((line_x, line_y), parts[0] + "：", fill=name_color, font=subtitle_font)

                # 本文部分の開始位置を計算
                name_bbox = draw.textbbox((0, 0), parts[0] + "：", font=subtitle_font)
                body_x = line_x + (name_bbox[2] - name_bbox[0])

                # 本文部分（縁取りなし）
                draw.text((body_x, line_y), parts[1], fill=body_color, font=subtitle_font)
            else:
                # 2行目以降は本文のみ（縁取りなし）
                draw.text((line_x, line_y), line, fill=body_color, font=subtitle_font)

    # === キャラクター（揺れなし）===
    char_size = 160
    char_y = subtitle_y - char_size + 20

    # カツミ（左）
    katsumi_y = char_y

    katsumi_path = ASSETS_DIR / "katsumi.png"
    if katsumi_path.exists():
        katsumi_img = Image.open(katsumi_path).convert('RGBA')
        katsumi_img = katsumi_img.resize((char_size, char_size), Image.Resampling.LANCZOS)
        img.paste(katsumi_img, (100, katsumi_y), katsumi_img)

    # ヒロシ（右）
    hiroshi_y = char_y

    hiroshi_path = ASSETS_DIR / "hiroshi.png"
    if hiroshi_path.exists():
        hiroshi_img = Image.open(hiroshi_path).convert('RGBA')
        hiroshi_img = hiroshi_img.resize((char_size, char_size), Image.Resampling.LANCZOS)
        img.paste(hiroshi_img, (WIDTH - char_size - 100, hiroshi_y), hiroshi_img)

    return img.convert('RGB')


def create_talk_with_topic_clip(rank, percent, topic, speaker, subtitle_text, duration, fps=24):
    """トピック背景＋字幕でトークを表示するVideoClipを生成"""
    import numpy as np
    from moviepy import VideoClip

    def make_frame(t):
        img = create_talk_with_topic_frame(rank, percent, topic, speaker, subtitle_text, t)
        return np.array(img)

    clip = VideoClip(make_frame, duration=duration)
    return clip


def create_kuchikomi_frame(num, text, speaker, theme_title, subtitle=None):
    """
    口コミ読み上げ画面を作成（design_09 アプリコット系）
    - 上部: オレンジ帯タイトル
    - 中央: 口コミテキスト（左揃え、上詰め、行間1.5倍）
    - 下部: アプリコット帯＋字幕（折り返し対応）
    - キャラクター: 左右端の下部に控えめに配置
    """
    # RGBA画像（透明度対応）
    img = Image.new('RGBA', (WIDTH, HEIGHT), hex_to_rgb(DESIGN["bg"]) + (255,))
    draw = ImageDraw.Draw(img)

    # フォント
    title_font = get_font(DESIGN["title_size"])
    text_font = get_font(DESIGN["text_size"])
    subtitle_font = get_font(DESIGN["subtitle_size"])
    name_font = get_font(20)

    title_height = DESIGN["title_height"]
    subtitle_height = DESIGN["subtitle_height"]
    char_size = DESIGN["char_size"]
    line_height = DESIGN.get("line_height", 1.5)

    # タイトル帯（上部）- 薄い影
    for offset in range(1, 4):
        alpha = 30 - offset * 8
        draw.rectangle([0, title_height + offset, WIDTH, title_height + offset + 1],
                       fill=(0, 0, 0, max(alpha, 0)))
    draw.rectangle([0, 0, WIDTH, title_height], fill=hex_to_rgb(DESIGN["title_bg"]))

    # タイトルテキスト
    header_text = f"{theme_title} - 口コミ{num}"
    bbox = draw.textbbox((0, 0), header_text, font=title_font)
    title_x = (WIDTH - (bbox[2] - bbox[0])) // 2
    title_y = (title_height - (bbox[3] - bbox[1])) // 2
    draw_text_with_effects(draw, (title_x, title_y), header_text, title_font,
                           DESIGN["title_text"], None, shadow=True,
                           shadow_strength=2, shadow_alpha=30)

    # 口コミテキスト（左揃え、上詰め）
    kuchikomi_y = title_height + 40  # 上から開始
    max_text_width = WIDTH - 120  # 左右余白60px
    lines = wrap_text(text, text_font, max_text_width, draw)

    # 行間を1.5倍に
    line_spacing = int(DESIGN["text_size"] * line_height)
    for i, line in enumerate(lines):
        draw_text_with_effects(draw, (60, kuchikomi_y + i * line_spacing), line, text_font,
                               DESIGN["text_color"], None, shadow=True,
                               shadow_strength=1, shadow_alpha=25)

    # 字幕エリア（下部）- 薄い影
    subtitle_y = HEIGHT - subtitle_height
    for offset in range(1, 3):
        alpha = 20 - offset * 6
        draw.rectangle([0, subtitle_y - offset - 1, WIDTH, subtitle_y - offset],
                       fill=(0, 0, 0, max(alpha, 0)))
    draw.rectangle([0, subtitle_y, WIDTH, HEIGHT], fill=hex_to_rgb(DESIGN["subtitle_bg"]))

    # 字幕テキスト（折り返し対応）
    if subtitle:
        # キャラ分の余白を確保（左右にキャラがいるので中央部分を使う）
        sub_max_width = WIDTH - char_size * 2 - 80  # キャラ分の余白
        sub_lines = wrap_text(subtitle, subtitle_font, sub_max_width, draw)

        # 字幕を中央に配置
        total_sub_height = len(sub_lines) * int(DESIGN["subtitle_size"] * 1.2)
        sub_start_y = subtitle_y + (subtitle_height - total_sub_height) // 2

        for i, line in enumerate(sub_lines):
            sub_x = 50
            sub_y = sub_start_y + i * int(DESIGN["subtitle_size"] * 1.2)
            draw_text_with_effects(draw, (sub_x, sub_y), line, subtitle_font,
                                   DESIGN["subtitle_text"], None, shadow=True,
                                   shadow_strength=1, shadow_alpha=25)

    # キャラクター位置（字幕帯の中、下部に配置）
    char_y = subtitle_y + (subtitle_height - char_size) // 2 + 10  # 字幕帯内で少し下
    char_outline = hex_to_rgb(DESIGN["char_outline"])

    # カツミ（左端）- 小さめに描画
    katsumi_x = 20
    # 薄い影
    for offset in range(4, 0, -1):
        draw.ellipse([katsumi_x - 3 + offset, char_y - 3 + offset,
                      katsumi_x + char_size + 3 + offset, char_y + char_size + 3 + offset],
                     fill=(0, 0, 0, 10 + offset * 2))
    # 白枠
    draw.ellipse([katsumi_x - 3, char_y - 3, katsumi_x + char_size + 3, char_y + char_size + 3],
                 fill=(255, 255, 255, 255), outline=char_outline, width=3)
    # ピンク背景
    draw.ellipse([katsumi_x, char_y, katsumi_x + char_size, char_y + char_size],
                 fill=(255, 200, 200, 255))
    # 顔（小さめ）
    cx, cy = katsumi_x + char_size // 2, char_y + char_size // 2
    face_r = int(char_size * 0.35)
    draw.ellipse([cx - face_r, cy - face_r, cx + face_r, cy + face_r], fill=(255, 220, 200))
    # 髪
    hair_r = int(char_size * 0.4)
    draw.ellipse([cx - hair_r, cy - hair_r - 10, cx + hair_r, cy], fill=(60, 40, 30))
    draw.rectangle([cx - hair_r + 5, cy - 10, cx + hair_r - 5, cy + 20], fill=(60, 40, 30))
    # 目
    eye_size = int(char_size * 0.08)
    draw.ellipse([cx - 15, cy - 8, cx - 15 + eye_size, cy - 8 + eye_size], fill=(60, 40, 30))
    draw.ellipse([cx + 5, cy - 8, cx + 5 + eye_size, cy - 8 + eye_size], fill=(60, 40, 30))
    # 口
    draw.arc([cx - 10, cy + 5, cx + 10, cy + 20], 0, 180, fill=(200, 100, 100), width=2)
    # 名前
    name_bbox = draw.textbbox((0, 0), "カツミ", font=name_font)
    name_x = katsumi_x + (char_size - (name_bbox[2] - name_bbox[0])) // 2
    draw_text_with_effects(draw, (name_x, char_y + char_size + 5), "カツミ", name_font,
                           DESIGN["text_color"], None, shadow=False)

    # ヒロシ（右端）
    hiroshi_x = WIDTH - char_size - 20
    # 薄い影
    for offset in range(4, 0, -1):
        draw.ellipse([hiroshi_x - 3 + offset, char_y - 3 + offset,
                      hiroshi_x + char_size + 3 + offset, char_y + char_size + 3 + offset],
                     fill=(0, 0, 0, 10 + offset * 2))
    # 白枠
    draw.ellipse([hiroshi_x - 3, char_y - 3, hiroshi_x + char_size + 3, char_y + char_size + 3],
                 fill=(255, 255, 255, 255), outline=char_outline, width=3)
    # ブルー背景
    draw.ellipse([hiroshi_x, char_y, hiroshi_x + char_size, char_y + char_size],
                 fill=(200, 220, 255, 255))
    # 顔（小さめ）
    hx, hy = hiroshi_x + char_size // 2, char_y + char_size // 2
    draw.ellipse([hx - face_r, hy - face_r, hx + face_r, hy + face_r], fill=(255, 220, 200))
    # 帽子
    hat_r = int(char_size * 0.38)
    draw.ellipse([hx - hat_r, hy - hat_r - 15, hx + hat_r, hy - 10], fill=(70, 90, 110))
    draw.rectangle([hx - hat_r - 5, hy - 25, hx + hat_r + 5, hy - 15], fill=(70, 90, 110))
    # 目
    draw.ellipse([hx - 15, hy - 5, hx - 15 + eye_size, hy - 5 + eye_size], fill=(60, 40, 30))
    draw.ellipse([hx + 5, hy - 5, hx + 5 + eye_size, hy - 5 + eye_size], fill=(60, 40, 30))
    # 口
    draw.line([hx - 8, hy + 12, hx + 8, hy + 12], fill=(150, 100, 100), width=2)
    # 名前
    name_bbox = draw.textbbox((0, 0), "ヒロシ", font=name_font)
    name_x = hiroshi_x + (char_size - (name_bbox[2] - name_bbox[0])) // 2
    draw_text_with_effects(draw, (name_x, char_y + char_size + 5), "ヒロシ", name_font,
                           DESIGN["text_color"], None, shadow=False)

    # RGBに変換して返す
    return img.convert('RGB')


def create_talk_frame(katsumi_text, hiroshi_text, theme_title):
    """
    掛け合いトーク画面
    - 左: カツミ + 吹き出し
    - 右: ヒロシ + 吹き出し
    """
    img = Image.new('RGB', (WIDTH, HEIGHT), hex_to_rgb(COLORS["cream"]))
    draw = ImageDraw.Draw(img)

    # タイトルバー
    draw.rectangle([0, 0, WIDTH, 60], fill=hex_to_rgb("#E8E8E8"))
    font_header = get_font(28)
    draw.text((30, 15), f"【トーク】{theme_title}", fill=hex_to_rgb(COLORS["black"]), font=font_header)

    # カツミ（左側）
    katsumi_img_path = ASSETS_DIR / "katsumi.png"
    if katsumi_img_path.exists():
        katsumi_img = Image.open(katsumi_img_path).convert('RGBA')
        katsumi_img = katsumi_img.resize((200, 200), Image.Resampling.LANCZOS)
        img.paste(katsumi_img, (50, HEIGHT - 280), katsumi_img)

    # カツミの吹き出し
    bubble_x, bubble_y = 280, 150
    bubble_w, bubble_h = 600, 300
    draw.rounded_rectangle(
        [bubble_x, bubble_y, bubble_x + bubble_w, bubble_y + bubble_h],
        radius=20,
        fill=hex_to_rgb(COLORS["white"]),
        outline=hex_to_rgb("#FFB6C1"),
        width=3
    )
    font_bubble = get_font(32)
    lines = wrap_text(katsumi_text, font_bubble, bubble_w - 40, draw)
    for i, line in enumerate(lines[:6]):
        draw.text((bubble_x + 20, bubble_y + 20 + i * 45), line, fill=hex_to_rgb(COLORS["black"]), font=font_bubble)

    # ヒロシ（右側）
    hiroshi_img_path = ASSETS_DIR / "hiroshi.png"
    if hiroshi_img_path.exists():
        hiroshi_img = Image.open(hiroshi_img_path).convert('RGBA')
        hiroshi_img = hiroshi_img.resize((200, 200), Image.Resampling.LANCZOS)
        img.paste(hiroshi_img, (WIDTH - 250, HEIGHT - 280), hiroshi_img)

    # ヒロシの吹き出し
    bubble2_x = WIDTH - 880
    bubble2_y = 500
    draw.rounded_rectangle(
        [bubble2_x, bubble2_y, bubble2_x + bubble_w, bubble2_y + bubble_h],
        radius=20,
        fill=hex_to_rgb(COLORS["white"]),
        outline=hex_to_rgb("#87CEEB"),
        width=3
    )
    lines2 = wrap_text(hiroshi_text, font_bubble, bubble_w - 40, draw)
    for i, line in enumerate(lines2[:6]):
        draw.text((bubble2_x + 20, bubble2_y + 20 + i * 45), line, fill=hex_to_rgb(COLORS["black"]), font=font_bubble)

    return img


def load_script_json(script_path):
    """
    kuchikomi_scraper.pyで生成したJSONを読み込み、内部形式に変換

    スクレイパー形式:
    {
        "theme": "テーマ名",
        "kuchikomi": [
            {"rank": 5, "item": "商品名", "rating": 4, "review_text": "...", "talks": [...]}
        ]
    }

    内部形式:
    {
        "kuchikomi": [
            {"num": 1, "text": "...", "rating": 4, "reader": "katsumi", "percent": 85, "talk_lines": [...]}
        ]
    }
    """
    with open(script_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 配列の場合は最初の要素を使用
    if isinstance(data, list):
        data = data[0]

    theme_title = data.get("theme", "口コミランキング")

    # rankでソート（5→1の順）して逆順にnum割り当て
    items = sorted(data["kuchikomi"], key=lambda x: x["rank"], reverse=True)

    # 支持率を割り当て（低いrank=高い支持率）
    base_percents = [65, 72, 78, 84, 90]

    converted = []
    for i, item in enumerate(items):
        # reader決定: 最初のtalkのspeaker
        talks = item.get("talks", [])
        reader = talks[0]["speaker"] if talks else "katsumi"

        # テキスト: item名 + review_text
        text = f"{item.get('item', '')}。{item.get('review_text', '')}"

        converted.append({
            "num": i + 1,
            "text": text,
            "rating": item.get("rating", 4),
            "reader": reader,
            "percent": base_percents[i] if i < len(base_percents) else 60 + i * 5,
            "talk_lines": [{"speaker": t["speaker"], "text": t["text"]} for t in talks],
            "item": item.get("item", ""),  # 追加: 商品名保持
        })

    return {"kuchikomi": converted}, theme_title


def generate_kuchikomi_with_gemini(theme, count):
    """Gemini APIで口コミを生成（性別判定付き）"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY環境変数が設定されていません")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = f"""
あなたは「{theme['target']}」の視点でリアルな口コミを生成するエキスパートです。

テーマ: 「{theme['title']}」

以下の形式で{count}件の口コミを生成してください。
各口コミは150〜200文字程度で、リアルな体験談風に書いてください。

【重要】口コミの読み上げ担当（reader）の決め方:
- 口コミの内容から「書いた人の性別」を推測してください
- 女性っぽい口コミ → "katsumi"（女性キャラ）が読む
- 男性っぽい口コミ → "hiroshi"（男性キャラ）が読む

性別判定の基準:
- 「主人」「夫」「旦那」「彼氏」と書いてる → 女性
- 「妻」「嫁」「彼女」と書いてる → 男性
- 「〜だわ」「〜のよ」「〜かしら」などの言葉遣い → 女性
- 「〜だな」「〜だぜ」などの言葉遣い → 男性
- 料理、家事、子育ての話題が多い → どちらかの文脈で判断
- 迷った場合は交互でOK

【キャラクター設定】
talk_linesでの掛け合いは以下のキャラ設定に沿って:

【カツミ】63歳女性（勝間和代風）
- 独善的で西洋的な視点
- データや数字で論破する
- 口調例：
  - 「それは完全に自己責任よね」
  - 「海外では当たり前だけど、日本は遅れてるわ」
  - 「私に言わせれば、情報弱者なのよ」
  - 「損してる人は単純に勉強不足ね」
  - 「合理的に考えれば、答えは明白よ」

【ヒロシ】47歳男性（ひろゆき風）
- ぶっちゃけで身も蓋もない
- 冷めた目で本質をつく
- 口調例：
  - 「それってあなたの感想ですよね」
  - 「なんかそれ、データあるんですか？」
  - 「結局、運ゲーじゃないですか」
  - 「でもそれ、やる意味あります？」
  - 「嘘くさいっすね」

【重要】上品に！
- 汚い言葉や攻撃的な表現は使わない
- 「〜かもしれませんね」「〜という見方もありますが」で和らげる
- ユーモアを交えて、笑いながら言う感じ
- 視聴者が気分悪くならないように
- 二人の掛け合いで面白く

出力形式（JSON）:
{{
  "kuchikomi": [
    {{
      "num": 1,
      "text": "口コミ本文...",
      "rating": 4,
      "reader": "katsumi",
      "gender_reason": "「主人が〜」という表現があるため女性と判定",
      "talk_lines": [
        {{"speaker": "katsumi", "text": "それは完全に自己責任よね"}},
        {{"speaker": "hiroshi", "text": "でもそれ、やる意味あります？"}},
        {{"speaker": "katsumi", "text": "合理的に考えれば、答えは明白よ"}},
        {{"speaker": "hiroshi", "text": "それってあなたの感想ですよね"}}
      ]
    }},
    ...
  ]
}}

注意:
- ratingは1〜5の整数
- readerは口コミ内容の性別に基づいて決定
- talk_linesは口コミ読み上げ後の2人の掛け合い（2〜4往復、4〜8セリフ程度）
- talk_linesの各セリフは短く自然に（10〜25文字程度）
- カツミとヒロシのキャラ設定に沿ったセリフにする
- 具体的なエピソードを含めてリアルに
- 共感を呼ぶ内容に
"""

    response = model.generate_content(prompt)
    response_text = response.text

    # JSONを抽出
    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0]
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0]

    return json.loads(response_text.strip())


def generate_tts_audio(text, voice, output_path):
    """Gemini TTSで音声を生成（新しいgoogle.genai APIを使用）"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY環境変数が設定されていません")

    # 新しいgoogle.genai Clientを使用
    client = genai_new.Client(api_key=api_key)

    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=text,
        config=genai_types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=genai_types.SpeechConfig(
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                        voice_name=voice
                    )
                )
            )
        )
    )

    audio_data = response.candidates[0].content.parts[0].inline_data.data
    mime_type = response.candidates[0].content.parts[0].inline_data.mime_type

    # MP3として一時保存してFFmpegでWAVに変換
    output_path_str = str(output_path)
    if mime_type and "mp3" in mime_type:
        # MP3をWAVに変換
        mp3_path = output_path_str.replace(".wav", ".mp3")
        with open(mp3_path, "wb") as f:
            f.write(audio_data)
        # ffmpegで変換
        subprocess.run(
            ["ffmpeg", "-y", "-i", mp3_path, "-ar", "44100", "-ac", "2", output_path_str],
            capture_output=True
        )
        os.remove(mp3_path)
    else:
        # PCM/raw audioの場合、ffmpegでWAVに変換
        raw_path = output_path_str.replace(".wav", ".raw")
        with open(raw_path, "wb") as f:
            f.write(audio_data)
        # PCM 24kHz mono -> WAV 44.1kHz stereo
        subprocess.run(
            ["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", raw_path,
             "-ar", "44100", "-ac", "2", output_path_str],
            capture_output=True
        )
        os.remove(raw_path)

    return output_path


def generate_all_audio(kuchikomi_data, theme_title, temp_dir):
    """全ての音声を並列生成（ランキングカードはジングル使用のためTTS不要）"""
    audio_files = []
    tasks = []

    # 口コミ読み上げの音声（ランキングカードはジングルを使うのでイントロ不要）
    for item in kuchikomi_data["kuchikomi"]:
        num = item["num"]
        text = item["text"]
        reader = item["reader"]
        voice = VOICE_CONFIG[reader]

        # 口コミ本文
        content_path = temp_dir / f"kuchikomi_{num}.wav"

        tasks.append({
            "type": "content",
            "num": num,
            "text": text,
            "voice": voice,
            "path": content_path
        })

    # 各口コミのtalk_lines音声
    for item in kuchikomi_data["kuchikomi"]:
        num = item["num"]
        talk_lines = item.get("talk_lines", [])

        for line_idx, line in enumerate(talk_lines):
            speaker = line["speaker"]
            line_text = line["text"]
            voice = VOICE_CONFIG[speaker]
            line_path = temp_dir / f"talk_{num}_{line_idx}.wav"

            tasks.append({
                "type": "talk_line",
                "num": num,
                "line_idx": line_idx,
                "speaker": speaker,
                "text": line_text,
                "voice": voice,
                "path": line_path
            })

    # 並列生成
    print(f"音声を生成中... ({len(tasks)}件)")

    def generate_one(task):
        try:
            generate_tts_audio(task["text"], task["voice"], task["path"])
            print(f"  生成完了: {task['path'].name}")
            return task
        except Exception as e:
            print(f"  エラー: {task['path'].name} - {e}")
            return None

    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(generate_one, tasks))

    return [r for r in results if r is not None]


def get_audio_duration(audio_path):
    """音声ファイルの長さを取得"""
    try:
        audio = AudioFileClip(str(audio_path))
        duration = audio.duration
        audio.close()
        return duration
    except:
        return 3.0  # デフォルト


def concatenate_audio_with_silence(audio_paths, output_path, silence_duration=0.3):
    """
    複数の音声ファイルを無音を挟んで連結
    FFmpegを使用して途切れなく連結
    """
    if not audio_paths:
        return None

    existing_paths = [p for p in audio_paths if Path(p).exists()]
    if not existing_paths:
        return None

    if len(existing_paths) == 1:
        # 1つだけの場合はそのまま返す
        return existing_paths[0]

    # FFmpegで連結（無音を挟む）
    # concat filter を使用
    filter_parts = []
    inputs = []

    for i, path in enumerate(existing_paths):
        inputs.extend(["-i", str(path)])
        filter_parts.append(f"[{i}:a]")

    # 無音を生成して挟む
    # 例: [0:a][silence][1:a] -> concat
    silence_filter = f"anullsrc=r=44100:cl=stereo:d={silence_duration}"

    # 複雑なフィルターを構築
    n = len(existing_paths)
    filter_complex_parts = []

    for i in range(n):
        filter_complex_parts.append(f"[{i}:a]aresample=44100[a{i}]")

    # 無音と交互に連結
    concat_inputs = []
    for i in range(n):
        concat_inputs.append(f"[a{i}]")
        if i < n - 1:
            # 無音を追加
            silence_idx = n + i
            filter_complex_parts.append(f"anullsrc=r=44100:cl=stereo:d={silence_duration}[s{i}]")
            concat_inputs.append(f"[s{i}]")

    total_streams = n + (n - 1)  # 音声 + 無音
    concat_str = "".join(concat_inputs) + f"concat=n={total_streams}:v=0:a=1[out]"
    filter_complex_parts.append(concat_str)

    filter_complex = ";".join(filter_complex_parts)

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-ar", "44100",
        "-ac", "2",
        str(output_path)
    ]

    result = subprocess.run(cmd, capture_output=True)
    if result.returncode == 0:
        return output_path
    else:
        print(f"  音声連結エラー: {result.stderr.decode()[:200]}")
        # フォールバック: 最初の音声のみ返す
        return existing_paths[0]


def create_video(kuchikomi_data, theme, temp_dir, output_path):
    """
    動画を生成（アニメーション対応版）

    動画の流れ:
    1. 第3位: ランキングカード（アニメーション3秒 + ジングル）
    2. 第3位: 口コミ読み上げ画面（アニメーション + TTS音声）
    3. 第3位: 控室トーク（各セリフ）
    4. 第2位: ...
    5. 第1位: ...
    """
    clips = []
    theme_title = theme["title"]
    total_count = len(kuchikomi_data["kuchikomi"])

    # ジングル音声ファイル
    jingle_path = ASSETS_DIR / "rank_jingle.mp3"
    if jingle_path.exists():
        jingle_duration = get_audio_duration(jingle_path)
    else:
        jingle_duration = 3.0  # デフォルト3秒

    # ランキングカードの長さ（ジングルに合わせる、最低3秒）
    rank_card_duration = max(3.0, jingle_duration)

    print("動画クリップを作成中...")

    for idx, item in enumerate(kuchikomi_data["kuchikomi"]):
        num = item["num"]
        text = item["text"]
        rating = item["rating"]
        reader = item["reader"]
        talk_lines = item.get("talk_lines", [])
        percent = item.get("percent", 100 - idx * 10)  # デフォルト: 1位=90%, 2位=80%...

        # ランキング順位（3位→2位→1位の順で表示）
        rank = total_count - idx

        print(f"  第{rank}位（口コミ {num}）を処理中...")

        # === 画面1: アニメーション付きランキングカード ===
        rank_clip = create_animated_rank_card_clip(
            rank, percent, theme_title,
            duration=rank_card_duration, fps=24
        )
        if jingle_path.exists():
            jingle_audio = AudioFileClip(str(jingle_path))
            # 音声が短い場合はループ
            if jingle_audio.duration < rank_card_duration:
                jingle_audio = jingle_audio.with_effects([])  # そのまま使用
            rank_clip = rank_clip.with_audio(jingle_audio)
        clips.append(rank_clip)

        # === 画面2: アニメーション付き口コミ読み上げ画面 ===
        reader_name = "カツミ" if reader == "katsumi" else "ヒロシ"
        subtitle_text = f"{reader_name}「{text[:30]}...」" if len(text) > 30 else f"{reader_name}「{text}」"

        content_audio_path = temp_dir / f"kuchikomi_{num}.wav"
        if content_audio_path.exists():
            content_duration = get_audio_duration(content_audio_path) + 1.0  # アニメーション分追加
        else:
            # テキスト長から推定（1文字50ms + アニメーション分）
            content_duration = max(5.0, len(text) * 0.05 + 2.0)

        kuchikomi_clip = create_animated_kuchikomi_clip(
            num, text, reader, theme_title, subtitle_text,
            duration=content_duration, fps=24
        )
        if content_audio_path.exists():
            content_audio = AudioFileClip(str(content_audio_path))
            # 音声の開始を0.8秒遅らせる（タイピング開始に合わせる）
            silence_duration = 0.8
            # 音声を遅延させる（with_startを使用）
            delayed_audio = content_audio.with_start(silence_duration)
            kuchikomi_clip = kuchikomi_clip.with_audio(delayed_audio)
        clips.append(kuchikomi_clip)

        # === 画面3: トピック背景＋字幕でトーク表示（控室画面を削除）===
        for line_idx, line in enumerate(talk_lines):
            speaker = line["speaker"]
            line_text = line["text"]

            # 音声ファイル
            talk_audio_path = temp_dir / f"talk_{num}_{line_idx}.wav"
            if talk_audio_path.exists():
                talk_duration = get_audio_duration(talk_audio_path) + 0.5
            else:
                # 音声がない場合はテキスト長から推定
                talk_duration = max(2.0, len(line_text) * 0.08 + 0.5)

            # 口コミ画面ベース＋字幕でトーク表示（画面切り替えなし）
            talk_clip = create_kuchikomi_talk_clip(
                num, text, theme_title, speaker, line_text,
                duration=talk_duration, fps=24
            )

            if talk_audio_path.exists():
                talk_audio = AudioFileClip(str(talk_audio_path))
                talk_clip = talk_clip.with_audio(talk_audio)

            clips.append(talk_clip)

    print("動画を結合中...")
    final_video = concatenate_videoclips(clips, method="compose")

    print(f"動画を書き出し中: {output_path}")
    final_video.write_videofile(
        str(output_path),
        fps=24,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=str(temp_dir / "temp_audio.m4a"),
        remove_temp=True,
        logger="bar"
    )

    # クリップをクローズ
    for clip in clips:
        clip.close()
    final_video.close()

    return output_path


# ========== サムネイル・タイトル・説明文・コメント・YouTube機能 ==========

# サムネイルサイズ
THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT = 1280, 720


def generate_thumbnail_title(theme_title: str, kuchikomi_data: dict) -> str:
    """サムネイル用のキャッチーなタイトルを生成（Gemini API）

    Args:
        theme_title: テーマタイトル
        kuchikomi_data: 口コミデータ

    Returns:
        str: キャッチーなタイトル（20文字以内）
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return f"会社員の{theme_title}"

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    # 口コミテキストを取得
    kuchikomi_texts = []
    for k in kuchikomi_data.get("kuchikomi", [])[:3]:
        text = k.get("text", "")
        if text:
            kuchikomi_texts.append(text[:50])

    kuchikomi_summary = "\n".join(kuchikomi_texts) if kuchikomi_texts else theme_title

    prompt = f"""
以下の会社員向け口コミランキングから、YouTubeサムネイル用のキャッチーなタイトルを作成してください。

【テーマ】
{theme_title}

【口コミサンプル】
{kuchikomi_summary}

【条件】
- 15〜20文字以内
- 会社員層の興味を引く表現
- 「！」「？」「...」などを効果的に使う
- 共感を呼ぶワードを入れる

【例】
「会社員が選んだ!? 本音ランキング」
「知らないと損！ビジネスマンの常識」
「みんな同じ！共感の嵐ランキング」

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
        return f"会社員の{theme_title}"


def generate_thumbnail(bg_image_path: str, title: str, output_path: str) -> bool:
    """サムネイル画像を生成（オレンジ背景+白文字スタイル）

    Args:
        bg_image_path: 背景画像のパス（未使用時はグラデーション）
        title: サムネイルタイトル
        output_path: 出力パス

    Returns:
        bool: 成功したかどうか
    """
    from datetime import datetime

    try:
        # オレンジ系グラデーション背景
        bg = Image.new('RGB', (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT))
        draw = ImageDraw.Draw(bg)
        for y in range(THUMBNAIL_HEIGHT):
            ratio = y / THUMBNAIL_HEIGHT
            r = int(255 - ratio * 30)
            g = int(140 - ratio * 40)
            b = int(0 + ratio * 20)
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


def generate_video_title(theme_title: str, kuchikomi_data: dict) -> str:
    """YouTube動画タイトルを生成（Gemini API）

    Args:
        theme_title: テーマタイトル
        kuchikomi_data: 口コミデータ

    Returns:
        str: 動画タイトル
    """
    from datetime import datetime

    api_key = os.environ.get("GEMINI_API_KEY")
    date_str = datetime.now().strftime('%Y年%m月%d日')

    if not api_key:
        return f"【会社口コミ】{theme_title}ランキング｜{date_str}"

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    count = len(kuchikomi_data.get("kuchikomi", []))

    prompt = f"""
以下の会社員向け口コミランキング動画のYouTubeタイトルを作成してください。

【テーマ】{theme_title}
【口コミ数】{count}件
【日付】{date_str}

【条件】
- 50文字以内
- 会社員層が興味を持つ表現
- 【】や｜を効果的に使う
- 日付を入れる

【例】
「【会社員必見】{theme_title}本音ランキングTOP{count}｜{date_str}」
「ビジネスマンが選んだ！{theme_title}ランキング｜みんなの声{count}件」

【出力】
タイトルのみを出力してください。
"""

    try:
        response = model.generate_content(prompt)
        title = response.text.strip().strip('"\'「」『』')
        if len(title) > 60:
            title = title[:57] + "..."
        print(f"  [タイトル] {title}")
        return title
    except Exception as e:
        print(f"  ⚠ タイトル生成エラー: {e}")
        return f"【会社口コミ】{theme_title}ランキング｜{date_str}"


def generate_video_description(theme_title: str, kuchikomi_data: dict) -> str:
    """YouTube動画説明文を生成

    Args:
        theme_title: テーマタイトル
        kuchikomi_data: 口コミデータ

    Returns:
        str: 動画説明文
    """
    from datetime import datetime

    date_str = datetime.now().strftime('%Y年%m月%d日')
    count = len(kuchikomi_data.get("kuchikomi", []))

    # 基本説明文
    description = f"""📢 {date_str}の口コミランキング

【テーマ】{theme_title}
【口コミ数】{count}件

会社員のリアルな声を集めた口コミランキングをお届けします。
カツミとヒロシの楽しいトークでご紹介！

━━━━━━━━━━━━━━━━━━━━━━━━

📺 チャンネル登録・高評価よろしくお願いします！
🔔 通知をONにして最新動画をチェック！

━━━━━━━━━━━━━━━━━━━━━━━━

#会社員 #口コミ #ランキング #{theme_title.replace(' ', '')} #ビジネス #サラリーマン #人生相談
"""

    return description


def generate_katsumi_comment(theme_title: str, kuchikomi_data: dict) -> str:
    """カツミのキャラクターでコメントを生成（Gemini API）

    Args:
        theme_title: テーマタイトル
        kuchikomi_data: 口コミデータ

    Returns:
        str: カツミのコメント
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return f"今日も見てくれてありがとう〜！{theme_title}のランキング、どうだった？共感してくれたら嬉しいわ〜♪"

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = f"""
あなたはYouTubeの口コミランキング動画のナビゲーター「カツミ」です。
動画を見てくれた視聴者への最初のコメントを書いてください。

【カツミの設定】
- 60代女性、明るくてポジティブ
- 「〜わ」「〜よ」「〜ね」などの女性的な語尾
- 視聴者を「みなさん」と呼ぶ
- 絵文字を2-3個使う

【今日のテーマ】{theme_title}

【コメント例】
「みなさん、今日も見てくれてありがとう〜！✨ {theme_title}のランキング、いかがでしたか？私も共感できるものばかりだったわ〜♪ コメント欄であなたの意見も聞かせてね！🎵」

【条件】
- 80〜120文字程度
- 温かみのある口調
- コメント欄での交流を促す

【出力】
コメントのみを出力してください。
"""

    try:
        response = model.generate_content(prompt)
        comment = response.text.strip().strip('"\'')
        print(f"  [コメント] {comment[:50]}...")
        return comment
    except Exception as e:
        print(f"  ⚠ コメント生成エラー: {e}")
        return f"今日も見てくれてありがとう〜！{theme_title}のランキング、どうだった？共感してくれたら嬉しいわ〜♪"


def upload_to_youtube(video_path: str, title: str, description: str, tags: list) -> str:
    """YouTubeにアップロード

    Args:
        video_path: 動画ファイルパス
        title: タイトル
        description: 説明文
        tags: タグリスト

    Returns:
        str: 動画URL（失敗時は空文字）
    """
    import requests
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN_23")

    if not all([client_id, client_secret, refresh_token]):
        print("  ⚠ YouTube認証情報が不足しています")
        return ""

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

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "22"  # People & Blogs
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

        print("\n" + "=" * 40)
        print("YouTube投稿完了!")
        print("=" * 40)
        print(f"動画URL: {url}")
        print(f"タイトル: {title}")
        print(f"公開設定: 公開")
        print("=" * 40)

        return video_id

    except Exception as e:
        print(f"  ⚠ YouTubeアップロードエラー: {e}")
        return ""


def set_youtube_thumbnail(video_id: str, thumbnail_path: str) -> bool:
    """YouTubeにサムネイルを設定

    Args:
        video_id: 動画ID
        thumbnail_path: サムネイル画像のパス

    Returns:
        bool: 成功したかどうか
    """
    import requests
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

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
    import requests
    from googleapiclient.discovery import build

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


def main():
    """メイン処理"""
    import argparse
    import glob

    parser = argparse.ArgumentParser(description="口コミランキング動画生成")
    parser.add_argument("--theme", type=int, default=0, help="テーマのインデックス（0から）")
    parser.add_argument("--count", type=int, default=None, help="口コミ件数（指定しない場合はthemes.jsonの値）")
    parser.add_argument("--output", type=str, default=None, help="出力ファイル名")
    parser.add_argument("--skip-api", action="store_true", help="API呼び出しをスキップ（デバッグ用）")
    parser.add_argument("--script", type=str, default=None, help="kuchikomi_scraper.pyで生成したJSONファイルパス")
    parser.add_argument("--script-index", type=int, default=0, help="JSONが配列の場合のインデックス（デフォルト: 0）")
    args = parser.parse_args()

    # 出力ディレクトリ作成
    OUTPUT_DIR.mkdir(exist_ok=True)

    # --script モード: スクレイパーで生成したJSONから動画作成
    if args.script:
        script_path = args.script

        # 最新のスクリプトファイルを自動選択
        if script_path == "latest":
            script_files = sorted(glob.glob(str(BASE_DIR / "company_scripts" / "company_kuchikomi_scripts_*.json")))
            if not script_files:
                print("company_scriptsディレクトリにJSONファイルがありません")
                return
            script_path = script_files[-1]  # 最新

        print(f"=== スクリプトファイルから動画生成 ===")
        print(f"ファイル: {script_path}")

        # JSON読み込み・変換
        kuchikomi_data, theme_title = load_script_json(script_path)

        # 配列の場合、インデックスで選択
        if isinstance(kuchikomi_data, list):
            kuchikomi_data = kuchikomi_data[args.script_index]

        count = len(kuchikomi_data["kuchikomi"])
        print(f"テーマ: {theme_title}")
        print(f"口コミ件数: {count}")
        print()

        # ダミーのtheme辞書を作成
        theme = {
            "id": "scraped",
            "title": theme_title,
            "target": "シニア層",
            "count": count,
        }

        # 一時ディレクトリ
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)

            # 音声生成
            if not args.skip_api:
                print("Gemini TTSで音声を生成中...")
                generate_all_audio(kuchikomi_data, theme_title, temp_dir)

            # 動画生成
            print()
            output_name = args.output or f"kuchikomi_scraped_{count}.mp4"
            if TEST_MODE:
                output_name = "test_kuchikomi_scraped.mp4"
            output_path = OUTPUT_DIR / output_name

            create_video(kuchikomi_data, theme, temp_dir, output_path)

            print()
            print(f"✅ 完了! 出力ファイル: {output_path}")

        return

    # 通常モード: themes.jsonから動画生成
    with open(THEMES_FILE) as f:
        themes_data = json.load(f)

    theme = themes_data["themes"][args.theme]
    count = args.count or (TEST_COUNT if TEST_MODE else theme["count"])

    print(f"=== 口コミランキング動画生成 ===")
    print(f"テーマ: {theme['title']}")
    print(f"口コミ件数: {count}")
    print()

    # 一時ディレクトリ
    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)

        if args.skip_api:
            # デバッグ用のダミーデータ
            print("APIスキップモード: ダミーデータを使用")
            # 支持率: 3位=65%, 2位=72%, 1位=85% (逆順表示)
            percents = [65, 72, 85, 88, 90]  # 最大5件分
            kuchikomi_data = {
                "kuchikomi": [
                    {
                        "num": i + 1,
                        "text": f"これはテスト用の口コミ{i + 1}です。年齢を重ねて手放してよかったものについて語っています。実際にはGemini APIで生成されたリアルな口コミが入ります。",
                        "rating": random.randint(3, 5),
                        "reader": "katsumi" if i % 2 == 0 else "hiroshi",
                        "percent": percents[i] if i < len(percents) else 60 + i * 5,
                        "talk_lines": [
                            {"speaker": "katsumi", "text": "そうよね〜、これわかるわ"},
                            {"speaker": "hiroshi", "text": "俺もそう思うな"},
                            {"speaker": "katsumi", "text": "やっぱり〜？"},
                            {"speaker": "hiroshi", "text": "うん、共感するよ"}
                        ]
                    }
                    for i in range(count)
                ]
            }
        else:
            # Gemini APIで口コミ生成
            print("Gemini APIで口コミを生成中...")
            kuchikomi_data = generate_kuchikomi_with_gemini(theme, count)
            print(f"  生成完了: {len(kuchikomi_data['kuchikomi'])}件")

            # 音声生成
            print()
            generate_all_audio(kuchikomi_data, theme["title"], temp_dir)

        # 動画生成
        print()
        output_name = args.output or f"kuchikomi_{theme['id']}_{count}.mp4"
        if TEST_MODE:
            output_name = "test_kuchikomi.mp4"
        output_path = OUTPUT_DIR / output_name

        create_video(kuchikomi_data, theme, temp_dir, output_path)

        print()
        print(f"完了! 出力ファイル: {output_path}")

        # 通知用にファイル出力
        with open("video_url.txt", "w") as f:
            f.write(f"file://{output_path}")
        with open("video_title.txt", "w") as f:
            f.write(theme["title"])


if __name__ == "__main__":
    main()
