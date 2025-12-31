#!/usr/bin/env python3
"""
カラーパターンプレビュー v3
順位ごとにグラデーション付き
"""

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# 出力先
OUTPUT_DIR = Path.home() / "Desktop" / "color_patterns_v3"
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
ICON_SIZE = 150  # 150x150 真四角

# オレンジ系グラデーション（5パターン）
ORANGE_PATTERNS = [
    {
        "name": "orange_v1",
        "label": "オレンジ系 A（明→暗→明）",
        "base_hue": "orange",
        "header_colors": ["#FF8C00", "#FF7000", "#FF8C00", "#FF7000"],  # 明暗交互
        "year_bg": "#E65C00",
        "detail_bg": "#2D2D2D",
        "panel_bg": "#FFF5E6",
        "screen_bg": "#1A1A1A",
        "text_highlight": "#FF4500",
    },
    {
        "name": "orange_v2",
        "label": "オレンジ系 B（暖色グラデ）",
        "base_hue": "orange",
        "header_colors": ["#FFA500", "#FF8C00", "#FF7F00", "#FF6600"],  # 徐々に濃く
        "year_bg": "#E65C00",
        "detail_bg": "#2D2D2D",
        "panel_bg": "#FFF8F0",
        "screen_bg": "#1A1A1A",
        "text_highlight": "#FF4500",
    },
    {
        "name": "orange_v3",
        "label": "オレンジ系 C（コーラル寄り）",
        "base_hue": "orange",
        "header_colors": ["#FF7F50", "#FF6347", "#FF7F50", "#FF6347"],  # コーラル交互
        "year_bg": "#E64A19",
        "detail_bg": "#2D2D2D",
        "panel_bg": "#FFF0E8",
        "screen_bg": "#1A1A1A",
        "text_highlight": "#FF4500",
    },
    {
        "name": "orange_v4",
        "label": "オレンジ系 D（ゴールド寄り）",
        "base_hue": "orange",
        "header_colors": ["#FFB347", "#FFA000", "#FFB347", "#FFA000"],  # ゴールド交互
        "year_bg": "#FF8C00",
        "detail_bg": "#2D2D2D",
        "panel_bg": "#FFFAF0",
        "screen_bg": "#1A1A1A",
        "text_highlight": "#FF6600",
    },
    {
        "name": "orange_v5",
        "label": "オレンジ系 E（ピーチ寄り）",
        "base_hue": "orange",
        "header_colors": ["#FFAB76", "#FF9966", "#FF8855", "#FF9966"],  # ピーチ系
        "year_bg": "#FF7744",
        "detail_bg": "#2D2D2D",
        "panel_bg": "#FFF5EE",
        "screen_bg": "#1A1A1A",
        "text_highlight": "#FF6347",
    },
]

# ピンク系グラデーション（5パターン）
PINK_PATTERNS = [
    {
        "name": "pink_v1",
        "label": "ピンク系 A（明→暗→明）",
        "base_hue": "pink",
        "header_colors": ["#FF6B9D", "#FF5C8D", "#FF6B9D", "#FF5C8D"],  # 明暗交互
        "year_bg": "#E91E63",
        "detail_bg": "#2D2D2D",
        "panel_bg": "#FFF0F5",
        "screen_bg": "#1A1A1A",
        "text_highlight": "#FF1493",
    },
    {
        "name": "pink_v2",
        "label": "ピンク系 B（コーラル寄り）",
        "base_hue": "pink",
        "header_colors": ["#FF7F7F", "#FF6B6B", "#FF8888", "#FF6B6B"],  # コーラル系
        "year_bg": "#E55B5B",
        "detail_bg": "#2D2D2D",
        "panel_bg": "#FFF5F5",
        "screen_bg": "#1A1A1A",
        "text_highlight": "#FF4444",
    },
    {
        "name": "pink_v3",
        "label": "ピンク系 C（ローズ）",
        "base_hue": "pink",
        "header_colors": ["#FF69B4", "#FF5BA7", "#FF69B4", "#FF5BA7"],  # ホットピンク交互
        "year_bg": "#DB7093",
        "detail_bg": "#2D2D2D",
        "panel_bg": "#FFF0F8",
        "screen_bg": "#1A1A1A",
        "text_highlight": "#FF1493",
    },
    {
        "name": "pink_v4",
        "label": "ピンク系 D（サーモン）",
        "base_hue": "pink",
        "header_colors": ["#FFA07A", "#FF8C69", "#FFA07A", "#FF8C69"],  # サーモン交互
        "year_bg": "#FA8072",
        "detail_bg": "#2D2D2D",
        "panel_bg": "#FFF8F5",
        "screen_bg": "#1A1A1A",
        "text_highlight": "#FF6347",
    },
    {
        "name": "pink_v5",
        "label": "ピンク系 E（マゼンタ寄り）",
        "base_hue": "pink",
        "header_colors": ["#FF77AA", "#FF5599", "#FF88BB", "#FF5599"],  # マゼンタ系
        "year_bg": "#C71585",
        "detail_bg": "#2D2D2D",
        "panel_bg": "#FFF5FA",
        "screen_bg": "#1A1A1A",
        "text_highlight": "#FF00FF",
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

    # 1. 名前エリア（80px）- 順位に応じた色
    header_h = 80
    color_idx = (rank - 1) % len(colors["header_colors"])
    header_color = colors["header_colors"][color_idx]
    draw.rectangle([0, 0, PANEL_WIDTH, header_h], fill=header_color)

    # 名前テキスト（白＋黒縁取り）
    name_text = "グリコ"
    font_name = FontManager.get_font(42)
    bbox = draw.textbbox((0, 0), name_text, font=font_name)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x_name = (PANEL_WIDTH - text_w) // 2
    y_name = (header_h - text_h) // 2 - 5

    # 黒縁取り + 白文字
    draw_text_with_outline(draw, name_text, x_name, y_name, font_name,
                           fill_color="#FFFFFF", outline_color="#000000", outline_width=2)

    y_cursor = header_h

    # 2. 写真エリア（420px）
    img_h = 420
    draw.rectangle([5, y_cursor + 5, PANEL_WIDTH - 5, y_cursor + img_h - 5], fill="#555555")

    # プレースホルダーテキスト
    ph_font = FontManager.get_font(32)
    draw_centered_text(draw, "画像", y_cursor + img_h // 2 - 20, ph_font, "#888888")

    y_cursor += img_h

    # 3. 年代エリア（70px）
    year_h = 70
    draw.rectangle([0, y_cursor, PANEL_WIDTH, y_cursor + year_h], fill=colors["year_bg"])

    font_year_label = FontManager.get_font(22)
    font_year_value = FontManager.get_font(30)
    draw_centered_text(draw, "発売年", y_cursor + 8, font_year_label, "#FFFFFF")
    draw_centered_text(draw, "1922年", y_cursor + 32, font_year_value, "#FFFFFF")

    y_cursor += year_h

    # 4. 詳細エリア（130px）
    detail_h = 130
    draw.rectangle([0, y_cursor, PANEL_WIDTH, y_cursor + detail_h], fill=colors["detail_bg"])

    font_label = FontManager.get_font(20)
    font_value = FontManager.get_font(26)

    detail_y = y_cursor + 15
    draw_centered_text(draw, "メーカー", detail_y, font_label, "#888888")
    draw_centered_text(draw, "江崎グリコ", detail_y + 22, font_value, "#FFFFFF")
    detail_y += 55
    draw_centered_text(draw, "当時価格", detail_y, font_label, "#888888")
    draw_centered_text(draw, "10円", detail_y + 22, font_value, "#FFFFFF")

    y_cursor += detail_h

    # 5. 順位エリア - 「N位」を一体で表示
    rank_area_h = PANEL_HEIGHT - y_cursor
    draw.rectangle([0, y_cursor, PANEL_WIDTH, PANEL_HEIGHT], fill=colors["panel_bg"])

    font_rank = FontManager.get_font(100)

    # 「N位」を一体で表示
    rank_text = f"{rank}位"

    bbox = draw.textbbox((0, 0), rank_text, font=font_rank)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x_pos = (PANEL_WIDTH - text_w) // 2
    y_pos = y_cursor + (rank_area_h - text_h) // 2 - 10

    # 影
    draw.text((x_pos + 4, y_pos + 4), rank_text, font=font_rank, fill="#000000")

    # 縁取り付き（赤系）
    draw_text_with_outline(draw, rank_text, x_pos, y_pos, font_rank,
                           colors["text_highlight"], "#000000", 4)

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

    # キャラクターアイコン（150x150 真四角）
    if KATSUMI_ICON.exists():
        try:
            katsumi = Image.open(KATSUMI_ICON)
            katsumi = katsumi.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
            # 左下
            x_k = 40
            y_k = SCREEN_HEIGHT - ICON_SIZE - 40
            if katsumi.mode == 'RGBA':
                screen.paste(katsumi, (x_k, y_k), katsumi)
            else:
                screen.paste(katsumi, (x_k, y_k))
        except Exception as e:
            print(f"   ⚠️ カツミアイコンエラー: {e}")

    if HIROSHI_ICON.exists():
        try:
            hiroshi = Image.open(HIROSHI_ICON)
            hiroshi = hiroshi.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
            # 右下
            x_h = SCREEN_WIDTH - ICON_SIZE - 40
            y_h = SCREEN_HEIGHT - ICON_SIZE - 40
            if hiroshi.mode == 'RGBA':
                screen.paste(hiroshi, (x_h, y_h), hiroshi)
            else:
                screen.paste(hiroshi, (x_h, y_h))
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
                   SCREEN_WIDTH//2 + text_w//2 + 20, 60], fill="#000000CC")
    draw.text((SCREEN_WIDTH//2 - text_w//2, 15), label_text, font=font_label, fill="#FFFFFF")

    return screen


def main():
    print("\n🎨 カラーパターンプレビュー v3（グラデーション付き）")
    print("=" * 60)

    all_patterns = ORANGE_PATTERNS + PINK_PATTERNS

    for i, pattern in enumerate(all_patterns):
        print(f"   生成中: {pattern['label']}...")

        screen = create_screen_preview(pattern, pattern["name"], pattern["label"])
        output_path = OUTPUT_DIR / f"{i+1:02d}_{pattern['name']}.png"
        screen.save(output_path)

        print(f"   ✓ {output_path.name}")

    print("\n" + "=" * 60)
    print(f"✅ 完了！ {len(all_patterns)}パターンを生成")
    print(f"📁 出力先: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
