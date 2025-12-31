#!/usr/bin/env python3
"""
カラーパターンプレビュー生成
10種類の配色パターンを静止画で出力
"""

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# 出力先
OUTPUT_DIR = Path.home() / "Desktop" / "color_patterns"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# アイコンパス
ICONS_DIR = Path(__file__).parent.parent / "assets" / "icons"
KATSUMI_ICON = ICONS_DIR / "katsumi_icon.png"
HIROSHI_ICON = ICONS_DIR / "hiroshi_icon.png"

# サイズ設定
PANEL_WIDTH = 400
PANEL_HEIGHT = 900
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
ICON_SIZE = 180  # 大きく！

# 10種類のカラーパターン
COLOR_PATTERNS = [
    {
        "name": "01_orange",
        "label": "オレンジ系",
        "header_bg": "#FF8C00",      # ダークオレンジ
        "header_bg_alt": "#FFA500",  # オレンジ
        "year_bg": "#FF6B00",        # 濃いオレンジ
        "detail_bg": "#2D2D2D",      # ダークグレー
        "panel_bg": "#FFF5E6",       # 薄いオレンジ
        "screen_bg": "#1A1A1A",
        "text_main": "#FFFFFF",
        "text_highlight": "#FF4500", # 赤オレンジ
        "accent": "#FFD700",         # ゴールド
    },
    {
        "name": "02_pink",
        "label": "ピンク系",
        "header_bg": "#FF6B6B",      # サーモンピンク
        "header_bg_alt": "#FF8E8E",  # 明るいピンク
        "year_bg": "#E55B5B",        # コーラル
        "detail_bg": "#2D2D2D",
        "panel_bg": "#FFF0F0",       # 薄いピンク
        "screen_bg": "#1A1A1A",
        "text_main": "#FFFFFF",
        "text_highlight": "#FF1493", # ディープピンク
        "accent": "#FFD700",
    },
    {
        "name": "03_yellow",
        "label": "黄色系（山吹）",
        "header_bg": "#F8B500",      # 山吹色
        "header_bg_alt": "#FFD700",  # ゴールド
        "year_bg": "#DAA520",        # からし色
        "detail_bg": "#2D2D2D",
        "panel_bg": "#FFFACD",       # レモンシフォン
        "screen_bg": "#1A1A1A",
        "text_main": "#FFFFFF",
        "text_highlight": "#FF8C00", # オレンジ
        "accent": "#FF6347",         # トマト
    },
    {
        "name": "04_green",
        "label": "緑系（若草）",
        "header_bg": "#7CB342",      # 若草色
        "header_bg_alt": "#8BC34A",  # ライトグリーン
        "year_bg": "#558B2F",        # 深緑
        "detail_bg": "#2D2D2D",
        "panel_bg": "#F0FFF0",       # ハニーデュー
        "screen_bg": "#1A1A1A",
        "text_main": "#FFFFFF",
        "text_highlight": "#32CD32", # ライムグリーン
        "accent": "#FFD700",
    },
    {
        "name": "05_blue",
        "label": "青系（水色）",
        "header_bg": "#4FC3F7",      # 水色
        "header_bg_alt": "#29B6F6",  # ライトブルー
        "year_bg": "#0288D1",        # 紺
        "detail_bg": "#2D2D2D",
        "panel_bg": "#E0F7FA",       # 薄い水色
        "screen_bg": "#1A1A1A",
        "text_main": "#FFFFFF",
        "text_highlight": "#00BFFF", # ディープスカイブルー
        "accent": "#FFD700",
    },
    {
        "name": "06_purple",
        "label": "紫系（藤色）",
        "header_bg": "#AB47BC",      # 紫
        "header_bg_alt": "#BA68C8",  # 藤色
        "year_bg": "#8E24AA",        # 濃い紫
        "detail_bg": "#2D2D2D",
        "panel_bg": "#F3E5F5",       # 薄い紫
        "screen_bg": "#1A1A1A",
        "text_main": "#FFFFFF",
        "text_highlight": "#FF00FF", # マゼンタ
        "accent": "#FFD700",
    },
    {
        "name": "07_red",
        "label": "赤系（朱色）",
        "header_bg": "#E53935",      # 朱色
        "header_bg_alt": "#EF5350",  # 明るい赤
        "year_bg": "#B71C1C",        # えんじ
        "detail_bg": "#2D2D2D",
        "panel_bg": "#FFEBEE",       # 薄いピンク
        "screen_bg": "#1A1A1A",
        "text_main": "#FFFFFF",
        "text_highlight": "#FF0000", # 赤
        "accent": "#FFD700",
    },
    {
        "name": "08_cream",
        "label": "クリーム系（レトロ）",
        "header_bg": "#D4A574",      # キャメル
        "header_bg_alt": "#DEB887",  # バーリーウッド
        "year_bg": "#8B4513",        # サドルブラウン
        "detail_bg": "#3E2723",      # ダークブラウン
        "panel_bg": "#FFF8DC",       # コーンシルク
        "screen_bg": "#1A1A1A",
        "text_main": "#FFFFFF",
        "text_highlight": "#CD853F", # ペルー
        "accent": "#FFD700",
    },
    {
        "name": "09_pastel",
        "label": "パステル系",
        "header_bg": "#FFB6C1",      # ライトピンク
        "header_bg_alt": "#87CEEB",  # スカイブルー
        "year_bg": "#DDA0DD",        # プラム
        "detail_bg": "#2D2D2D",
        "panel_bg": "#FFFAF0",       # フローラルホワイト
        "screen_bg": "#1A1A1A",
        "text_main": "#FFFFFF",
        "text_highlight": "#FF69B4", # ホットピンク
        "accent": "#98FB98",         # ペールグリーン
    },
    {
        "name": "10_pop",
        "label": "ポップ系（ビビッド）",
        "header_bg": "#FF1493",      # ディープピンク
        "header_bg_alt": "#00CED1",  # ダークターコイズ
        "year_bg": "#FF4500",        # オレンジレッド
        "detail_bg": "#1A1A1A",
        "panel_bg": "#FFFFFF",       # 白
        "screen_bg": "#000000",
        "text_main": "#FFFFFF",
        "text_highlight": "#FFD700", # ゴールド
        "accent": "#00FF00",         # ライム
    },
]


class FontManager:
    """フォント管理"""
    _fonts = {}

    @classmethod
    def get_font(cls, size: int) -> ImageFont.FreeTypeFont:
        if size not in cls._fonts:
            font_paths = [
                "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
                "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
            ]
            for path in font_paths:
                if Path(path).exists():
                    cls._fonts[size] = ImageFont.truetype(path, size)
                    break
            else:
                cls._fonts[size] = ImageFont.load_default()
        return cls._fonts[size]


def draw_text_with_outline(draw, text, x, y, font, fill_color, outline_color="#000000", outline_width=3):
    """縁取り付きテキスト"""
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    draw.text((x, y), text, font=font, fill=fill_color)


def draw_centered_text(draw, text, y, font, fill_color, width=PANEL_WIDTH):
    """中央揃えテキスト"""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    x = (width - text_w) // 2
    draw.text((x, y), text, font=font, fill=fill_color)
    return x


def create_panel(colors, rank=1):
    """パネル画像を生成"""
    panel = Image.new("RGB", (PANEL_WIDTH, PANEL_HEIGHT), colors["panel_bg"])
    draw = ImageDraw.Draw(panel)

    y_cursor = 0

    # 1. 名前エリア（80px）
    header_h = 80
    header_color = colors["header_bg"] if rank % 2 == 1 else colors["header_bg_alt"]
    draw.rectangle([0, 0, PANEL_WIDTH, header_h], fill=header_color)

    name_text = "グリコ"
    font_name = FontManager.get_font(42)
    bbox = draw.textbbox((0, 0), name_text, font=font_name)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x_name = (PANEL_WIDTH - text_w) // 2
    y_name = (header_h - text_h) // 2 - 5

    draw.text((x_name + 2, y_name + 2), name_text, font=font_name, fill="#000000")
    draw.text((x_name, y_name), name_text, font=font_name, fill=colors["text_main"])

    y_cursor = header_h

    # 2. 写真エリア（420px）
    img_h = 420
    draw.rectangle([5, y_cursor + 5, PANEL_WIDTH - 5, y_cursor + img_h - 5], fill="#666666")

    # プレースホルダーテキスト
    ph_font = FontManager.get_font(32)
    draw_centered_text(draw, "画像", y_cursor + img_h // 2 - 20, ph_font, "#999999")

    y_cursor += img_h

    # 3. 年代エリア（70px）
    year_h = 70
    draw.rectangle([0, y_cursor, PANEL_WIDTH, y_cursor + year_h], fill=colors["year_bg"])

    font_year_label = FontManager.get_font(22)
    font_year_value = FontManager.get_font(30)
    draw_centered_text(draw, "発売年", y_cursor + 8, font_year_label, "#CCCCCC")
    draw_centered_text(draw, "1922年", y_cursor + 32, font_year_value, colors["text_main"])

    y_cursor += year_h

    # 4. 詳細エリア（130px）
    detail_h = 130
    draw.rectangle([0, y_cursor, PANEL_WIDTH, y_cursor + detail_h], fill=colors["detail_bg"])

    font_label = FontManager.get_font(20)
    font_value = FontManager.get_font(26)

    detail_y = y_cursor + 15
    draw_centered_text(draw, "メーカー", detail_y, font_label, "#888888")
    draw_centered_text(draw, "江崎グリコ", detail_y + 22, font_value, colors["text_main"])
    detail_y += 55
    draw_centered_text(draw, "当時価格", detail_y, font_label, "#888888")
    draw_centered_text(draw, "10円", detail_y + 22, font_value, colors["text_main"])

    y_cursor += detail_h

    # 5. 順位エリア
    rank_area_h = PANEL_HEIGHT - y_cursor
    draw.rectangle([0, y_cursor, PANEL_WIDTH, PANEL_HEIGHT], fill=colors["panel_bg"])

    font_rank_num = FontManager.get_font(120)
    font_rank_label = FontManager.get_font(32)

    rank_text = str(rank)
    rank_label = "位"

    bbox_num = draw.textbbox((0, 0), rank_text, font=font_rank_num)
    bbox_label = draw.textbbox((0, 0), rank_label, font=font_rank_label)

    num_w = bbox_num[2] - bbox_num[0]
    num_h = bbox_num[3] - bbox_num[1]
    label_w = bbox_label[2] - bbox_label[0]

    total_w = num_w + label_w + 5
    x_num = (PANEL_WIDTH - total_w) // 2
    y_num = y_cursor + (rank_area_h - num_h) // 2 - 20

    draw.text((x_num + 4, y_num + 4), rank_text, font=font_rank_num, fill="#000000")
    draw_text_with_outline(draw, rank_text, x_num, y_num, font_rank_num,
                           colors["text_highlight"], "#000000", 4)

    x_label = x_num + num_w + 5
    y_label = y_num + num_h - 50

    draw.text((x_label + 2, y_label + 2), rank_label, font=font_rank_label, fill="#000000")
    draw.text((x_label, y_label), rank_label, font=font_rank_label, fill=colors["text_main"])

    return panel


def create_screen_preview(colors, pattern_name, pattern_label):
    """画面全体のプレビューを生成"""
    screen = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), colors["screen_bg"])

    # パネルを4枚配置
    y_offset = (SCREEN_HEIGHT - PANEL_HEIGHT) // 2

    for i in range(4):
        rank = i + 1
        panel = create_panel(colors, rank)
        x_pos = 60 + i * (PANEL_WIDTH + 10)
        screen.paste(panel, (x_pos, y_offset))

    # キャラクターアイコンを大きく配置
    if KATSUMI_ICON.exists():
        try:
            katsumi = Image.open(KATSUMI_ICON)
            katsumi = katsumi.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
            # 左下
            screen.paste(katsumi, (30, SCREEN_HEIGHT - ICON_SIZE - 30),
                        katsumi if katsumi.mode == 'RGBA' else None)
        except Exception as e:
            print(f"   ⚠️ カツミアイコンエラー: {e}")

    if HIROSHI_ICON.exists():
        try:
            hiroshi = Image.open(HIROSHI_ICON)
            hiroshi = hiroshi.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
            # 右下
            screen.paste(hiroshi, (SCREEN_WIDTH - ICON_SIZE - 30, SCREEN_HEIGHT - ICON_SIZE - 30),
                        hiroshi if hiroshi.mode == 'RGBA' else None)
        except Exception as e:
            print(f"   ⚠️ ヒロシアイコンエラー: {e}")

    # パターン名を表示
    draw = ImageDraw.Draw(screen)
    font_label = FontManager.get_font(36)
    label_text = f"{pattern_label}"
    bbox = draw.textbbox((0, 0), label_text, font=font_label)
    text_w = bbox[2] - bbox[0]

    # 上部中央に表示
    draw.rectangle([SCREEN_WIDTH//2 - text_w//2 - 20, 10,
                   SCREEN_WIDTH//2 + text_w//2 + 20, 60], fill="#000000AA")
    draw.text((SCREEN_WIDTH//2 - text_w//2, 15), label_text, font=font_label, fill="#FFFFFF")

    return screen


def main():
    print("\n🎨 カラーパターンプレビュー生成")
    print("=" * 50)

    for pattern in COLOR_PATTERNS:
        print(f"   生成中: {pattern['label']}...")

        screen = create_screen_preview(pattern, pattern["name"], pattern["label"])
        output_path = OUTPUT_DIR / f"{pattern['name']}.png"
        screen.save(output_path)

        print(f"   ✓ {output_path.name}")

    print("\n" + "=" * 50)
    print(f"✅ 完了！ {len(COLOR_PATTERNS)}パターンを生成")
    print(f"📁 出力先: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
