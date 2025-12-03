#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新しい動画レイアウトのテスト画像生成
"""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import math

# 動画サイズ
WIDTH = 1920
HEIGHT = 1080

# 色設定
SUBTITLE_BG_COLOR = (196, 136, 58, 240)  # #C4883A 茶色/オレンジ
LEFT_SIDEBAR_COLOR = (138, 85, 155)       # 紫/ピンク系
RIGHT_SIDEBAR_COLOR = (210, 140, 60)      # オレンジ系
CAFE_BG_COLOR = (65, 45, 35)              # 喫茶店風ダーク茶色
TEXT_WHITE = (255, 255, 255)
TEXT_BLACK = (0, 0, 0)
DIM_OVERLAY = (0, 0, 0, 120)              # 暗くするオーバーレイ

# フォント
FONT_PATH = "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc"
FONT_SIZE = 42
FONT_SIZE_SMALL = 28
FONT_SIZE_SIDEBAR = 36

# レイアウト設定
LEFT_SIDEBAR_WIDTH = 80
RIGHT_SIDEBAR_WIDTH = 80
MAIN_AREA_X = LEFT_SIDEBAR_WIDTH
MAIN_AREA_WIDTH = WIDTH - LEFT_SIDEBAR_WIDTH - RIGHT_SIDEBAR_WIDTH

# 上下段の高さ
TOP_PANEL_HEIGHT = HEIGHT // 2
BOTTOM_PANEL_HEIGHT = HEIGHT // 2

# 字幕帯設定
SUBTITLE_HEIGHT = 120
SUBTITLE_MARGIN = 30
SILHOUETTE_SIZE = 80


def create_cafe_background(width, height):
    """喫茶店風の背景を生成"""
    img = Image.new('RGB', (width, height), CAFE_BG_COLOR)
    draw = ImageDraw.Draw(img)

    # グラデーション効果（上から下へ暖色系）
    for y in range(height):
        ratio = y / height
        r = int(65 + ratio * 20)
        g = int(45 + ratio * 15)
        b = int(35 + ratio * 10)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # 装飾的な模様（木目風の横線）
    for y in range(0, height, 40):
        alpha = 20 + (y % 80)
        draw.line([(0, y), (width, y)], fill=(90, 65, 50), width=1)

    # 窓からの光の効果（右上に明るい領域）
    for i in range(100):
        x = width - 300 + i * 2
        y = i * 2
        radius = 150 - i
        if radius > 0:
            draw.ellipse([x-radius, y-radius, x+radius, y+radius],
                        fill=(100 + i//2, 80 + i//2, 60 + i//2))

    return img


def create_silhouette(size, is_female=True):
    """キャラクターのシルエットを生成"""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    center_x = size // 2

    # 頭
    head_radius = size // 4
    head_y = size // 3
    draw.ellipse([center_x - head_radius, head_y - head_radius,
                  center_x + head_radius, head_y + head_radius],
                 fill=(255, 255, 255, 230))

    # 体（肩から下）
    body_top = head_y + head_radius - 5
    body_width = size // 2
    draw.ellipse([center_x - body_width//2, body_top,
                  center_x + body_width//2, size],
                 fill=(255, 255, 255, 230))

    # 女性は髪を追加
    if is_female:
        # 髪（両サイド）
        hair_width = head_radius + 8
        draw.ellipse([center_x - hair_width, head_y - head_radius - 5,
                      center_x + hair_width, head_y + head_radius + 15],
                     fill=(255, 255, 255, 230))

    return img


def draw_text_with_outline(draw, pos, text, font, fill, outline_color, outline_width):
    """縁取り付きテキスト描画"""
    x, y = pos
    # 縁取り
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx*dx + dy*dy <= outline_width*outline_width:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    # 本文
    draw.text((x, y), text, font=font, fill=fill)


def draw_vertical_text(draw, pos, text, font, fill, spacing=5):
    """縦書きテキスト描画"""
    x, y = pos
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        bbox = draw.textbbox((0, 0), char, font=font)
        char_height = bbox[3] - bbox[1]
        y += char_height + spacing


def create_layout_test(speaker="consulter"):
    """
    レイアウトテスト画像を生成

    Args:
        speaker: "consulter"(由美子) or "advisor"(P)
    """
    # 背景生成
    img = create_cafe_background(WIDTH, HEIGHT)
    draw = ImageDraw.Draw(img, 'RGBA')

    # フォント読み込み
    try:
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
        font_small = ImageFont.truetype(FONT_PATH, FONT_SIZE_SMALL)
        font_sidebar = ImageFont.truetype(FONT_PATH, FONT_SIZE_SIDEBAR)
    except:
        font = ImageFont.truetype("/System/Library/Fonts/AppleSDGothicNeo.ttc", FONT_SIZE)
        font_small = ImageFont.truetype("/System/Library/Fonts/AppleSDGothicNeo.ttc", FONT_SIZE_SMALL)
        font_sidebar = ImageFont.truetype("/System/Library/Fonts/AppleSDGothicNeo.ttc", FONT_SIZE_SIDEBAR)

    # ===== 上段（相談者：由美子）=====
    top_y = 0
    top_subtitle_y = TOP_PANEL_HEIGHT - SUBTITLE_HEIGHT - SUBTITLE_MARGIN

    # 話していない方を暗くする
    if speaker != "consulter":
        draw.rectangle([MAIN_AREA_X, top_y, WIDTH - RIGHT_SIDEBAR_WIDTH, TOP_PANEL_HEIGHT],
                      fill=DIM_OVERLAY)

    # 字幕帯（上段）
    subtitle_x = MAIN_AREA_X + 50
    subtitle_width = MAIN_AREA_WIDTH - 100
    draw.rounded_rectangle(
        [subtitle_x, top_subtitle_y, subtitle_x + subtitle_width, top_subtitle_y + SUBTITLE_HEIGHT],
        radius=15,
        fill=SUBTITLE_BG_COLOR
    )

    # シルエット（上段）
    silhouette_consulter = create_silhouette(SILHOUETTE_SIZE, is_female=True)
    img.paste(silhouette_consulter,
              (subtitle_x + 15, top_subtitle_y + (SUBTITLE_HEIGHT - SILHOUETTE_SIZE) // 2),
              silhouette_consulter)

    # 字幕テキスト（上段）
    text_x = subtitle_x + SILHOUETTE_SIZE + 30
    text_y = top_subtitle_y + 20
    draw_text_with_outline(draw, (text_x, text_y), "【由美子】", font, TEXT_WHITE, TEXT_BLACK, 3)
    draw_text_with_outline(draw, (text_x, text_y + 50),
                          "夫との関係に葛藤があって、", font, TEXT_WHITE, TEXT_BLACK, 3)

    # ===== 下段（回答者：P）=====
    bottom_y = TOP_PANEL_HEIGHT
    bottom_subtitle_y = bottom_y + SUBTITLE_MARGIN

    # 話していない方を暗くする
    if speaker != "advisor":
        draw.rectangle([MAIN_AREA_X, bottom_y, WIDTH - RIGHT_SIDEBAR_WIDTH, HEIGHT],
                      fill=DIM_OVERLAY)

    # 字幕帯（下段）
    draw.rounded_rectangle(
        [subtitle_x, bottom_subtitle_y, subtitle_x + subtitle_width, bottom_subtitle_y + SUBTITLE_HEIGHT],
        radius=15,
        fill=SUBTITLE_BG_COLOR
    )

    # シルエット（下段）
    silhouette_advisor = create_silhouette(SILHOUETTE_SIZE, is_female=False)
    img.paste(silhouette_advisor,
              (subtitle_x + 15, bottom_subtitle_y + (SUBTITLE_HEIGHT - SILHOUETTE_SIZE) // 2),
              silhouette_advisor)

    # 字幕テキスト（下段）
    text_y = bottom_subtitle_y + 20
    draw_text_with_outline(draw, (text_x, text_y), "【P】", font, TEXT_WHITE, TEXT_BLACK, 3)
    draw_text_with_outline(draw, (text_x, text_y + 50),
                          "それは大変でしたね。", font, TEXT_WHITE, TEXT_BLACK, 3)

    # ===== 左サイドバー（相談者情報）=====
    draw.rectangle([0, 0, LEFT_SIDEBAR_WIDTH, HEIGHT], fill=LEFT_SIDEBAR_COLOR)

    # 縦書きで相談者情報
    sidebar_font = font_small
    info_items = ["年", "齢", "", "49", "", "家", "族", "", "夫", "子", "2"]
    y_pos = 100
    for item in info_items:
        if item:
            draw.text((LEFT_SIDEBAR_WIDTH // 2 - 14, y_pos), item,
                     font=sidebar_font, fill=TEXT_WHITE)
        y_pos += 40

    # ===== 右サイドバー（人生相談）=====
    draw.rectangle([WIDTH - RIGHT_SIDEBAR_WIDTH, 0, WIDTH, HEIGHT], fill=RIGHT_SIDEBAR_COLOR)

    # 縦書きで「人生相談」
    title_chars = ["人", "生", "相", "談"]
    y_pos = 150
    for char in title_chars:
        draw.text((WIDTH - RIGHT_SIDEBAR_WIDTH + 20, y_pos), char,
                 font=font_sidebar, fill=TEXT_WHITE)
        y_pos += 60

    # ===== 区切り線（上下段の境界）=====
    draw.line([(MAIN_AREA_X, TOP_PANEL_HEIGHT), (WIDTH - RIGHT_SIDEBAR_WIDTH, TOP_PANEL_HEIGHT)],
              fill=(100, 70, 50), width=3)

    return img


def main():
    output_dir = Path("output/temp")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 相談者が話している状態
    img1 = create_layout_test(speaker="consulter")
    path1 = output_dir / "layout_test_consulter.png"
    img1.save(path1)
    print(f"保存: {path1}")

    # 回答者が話している状態
    img2 = create_layout_test(speaker="advisor")
    path2 = output_dir / "layout_test_advisor.png"
    img2.save(path2)
    print(f"保存: {path2}")


if __name__ == "__main__":
    main()
