#!/usr/bin/env python3
"""
カラーパターン最終版
オレンジ系D（ゴールド寄り）ベース
順位の縁取り/装飾10パターン
"""

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# 出力先
OUTPUT_DIR = Path.home() / "Desktop" / "color_patterns_final"
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
ICON_SIZE = 200  # 200x200 大きく！

# オレンジ系D（ゴールド寄り）ベースカラー
BASE_COLORS = {
    "header_colors": ["#FFB347", "#FFA000", "#FFB347", "#FFA000"],  # ゴールド交互
    "year_bg": "#FF8C00",
    "detail_bg": "#2D2D2D",
    "panel_bg": "#FFFAF0",
    "screen_bg": "#1A1A1A",
    "text_highlight": "#FF6600",  # 順位の色
}

# 縁取り/装飾バリエーション
OUTLINE_STYLES = [
    {
        "name": "01_no_outline",
        "label": "縁取りなし（シンプル）",
        "style": "none",
    },
    {
        "name": "02_white_outline",
        "label": "白縁取り（2px）",
        "style": "white_outline",
    },
    {
        "name": "03_orange_outline",
        "label": "濃いオレンジ縁取り（同系色）",
        "style": "orange_outline",
    },
    {
        "name": "04_gradient_outline",
        "label": "グラデーション縁取り",
        "style": "gradient_outline",
    },
    {
        "name": "05_shadow_only",
        "label": "影のみ（ドロップシャドウ）",
        "style": "shadow_only",
    },
    {
        "name": "06_glow",
        "label": "光彩（グロー効果）",
        "style": "glow",
    },
    {
        "name": "07_double_outline",
        "label": "二重縁取り（白+オレンジ）",
        "style": "double_outline",
    },
    {
        "name": "08_thin_white",
        "label": "薄い縁取り（1px白）",
        "style": "thin_white",
    },
    {
        "name": "09_inner_shadow",
        "label": "内側に影",
        "style": "inner_shadow",
    },
    {
        "name": "10_3d_effect",
        "label": "立体風（3D風の影）",
        "style": "3d_effect",
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


def draw_text_with_outline(draw, text, x, y, font, fill_color, outline_color, outline_width):
    """縁取り付きテキスト"""
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    draw.text((x, y), text, font=font, fill=fill_color)


def draw_rank_text(panel, draw, text, x, y, font, style):
    """順位テキストを様々なスタイルで描画"""
    main_color = "#FF6600"  # メインのオレンジ

    if style == "none":
        # 縁取りなし（シンプル）
        draw.text((x, y), text, font=font, fill=main_color)

    elif style == "white_outline":
        # 白縁取り（2px）
        draw_text_with_outline(draw, text, x, y, font, main_color, "#FFFFFF", 2)

    elif style == "orange_outline":
        # 濃いオレンジ縁取り（同系色）
        draw_text_with_outline(draw, text, x, y, font, "#FFD700", "#CC5500", 3)

    elif style == "gradient_outline":
        # グラデーション縁取り（外側から内側へ）
        for i in range(4, 0, -1):
            alpha = 255 - (i * 40)
            outline_color = f"#FF{70 + i*20:02X}00"
            draw_text_with_outline(draw, text, x, y, font, main_color, outline_color, i)
        draw.text((x, y), text, font=font, fill="#FFD700")

    elif style == "shadow_only":
        # 影のみ（ドロップシャドウ）
        # 影を複数レイヤーで柔らかく
        for offset in [(6, 6), (5, 5), (4, 4), (3, 3)]:
            shadow_alpha = 80 + (6 - offset[0]) * 30
            draw.text((x + offset[0], y + offset[1]), text, font=font, fill=f"#333333")
        draw.text((x, y), text, font=font, fill=main_color)

    elif style == "glow":
        # 光彩（グロー効果）
        glow_color = "#FFFF00"
        for i in range(8, 0, -1):
            draw_text_with_outline(draw, text, x, y, font, glow_color, glow_color, i)
        draw.text((x, y), text, font=font, fill=main_color)

    elif style == "double_outline":
        # 二重縁取り（白+オレンジ）
        draw_text_with_outline(draw, text, x, y, font, main_color, "#CC5500", 4)
        draw_text_with_outline(draw, text, x, y, font, main_color, "#FFFFFF", 2)
        draw.text((x, y), text, font=font, fill="#FFD700")

    elif style == "thin_white":
        # 薄い縁取り（1px白）
        draw_text_with_outline(draw, text, x, y, font, main_color, "#FFFFFF", 1)

    elif style == "inner_shadow":
        # 内側に影（上に光、下に影）
        # 影
        draw.text((x + 2, y + 2), text, font=font, fill="#994400")
        # メイン
        draw.text((x, y), text, font=font, fill=main_color)
        # ハイライト（少し上にオフセット）
        draw.text((x - 1, y - 1), text, font=font, fill="#FFAA44")

    elif style == "3d_effect":
        # 立体風（3D風の影）
        # 奥行きを出す複数の影
        for i in range(6, 0, -1):
            shade = max(0, 100 - i * 15)
            draw.text((x + i, y + i), text, font=font, fill=f"#{shade:02X}{shade//2:02X}00")
        draw.text((x, y), text, font=font, fill="#FFD700")


def draw_centered_text(draw, text, y, font, fill_color, width=PANEL_WIDTH):
    """中央揃えテキスト"""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    x = (width - text_w) // 2
    draw.text((x, y), text, font=font, fill=fill_color)
    return x


def create_panel(colors, rank, outline_style):
    """パネル画像を生成"""
    panel = Image.new("RGB", (PANEL_WIDTH, PANEL_HEIGHT), colors["panel_bg"])
    draw = ImageDraw.Draw(panel)

    y_cursor = 0

    # 1. 名前エリア（80px）
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

    draw_text_with_outline(draw, name_text, x_name, y_name, font_name,
                           fill_color="#FFFFFF", outline_color="#000000", outline_width=2)

    y_cursor = header_h

    # 2. 写真エリア（420px）
    img_h = 420
    draw.rectangle([5, y_cursor + 5, PANEL_WIDTH - 5, y_cursor + img_h - 5], fill="#555555")

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

    # 5. 順位エリア
    rank_area_h = PANEL_HEIGHT - y_cursor
    draw.rectangle([0, y_cursor, PANEL_WIDTH, PANEL_HEIGHT], fill=colors["panel_bg"])

    font_rank = FontManager.get_font(100)
    rank_text = f"{rank}位"

    bbox = draw.textbbox((0, 0), rank_text, font=font_rank)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x_pos = (PANEL_WIDTH - text_w) // 2
    y_pos = y_cursor + (rank_area_h - text_h) // 2 - 10

    # 各スタイルで描画
    draw_rank_text(panel, draw, rank_text, x_pos, y_pos, font_rank, outline_style)

    return panel


def create_screen_preview(colors, style_info):
    """画面全体のプレビューを生成"""
    screen = Image.new("RGB", (SCREEN_WIDTH, SCREEN_HEIGHT), colors["screen_bg"])

    # パネルを4枚配置
    y_offset = (SCREEN_HEIGHT - PANEL_HEIGHT) // 2

    for i in range(4):
        rank = i + 1
        panel = create_panel(colors, rank, style_info["style"])
        x_pos = 60 + i * (PANEL_WIDTH + 10)
        screen.paste(panel, (x_pos, y_offset))

    # キャラクターアイコン（200x200 大きく！）
    if KATSUMI_ICON.exists():
        try:
            katsumi = Image.open(KATSUMI_ICON)
            # 正方形にクロップ
            min_dim = min(katsumi.width, katsumi.height)
            left = (katsumi.width - min_dim) // 2
            top = (katsumi.height - min_dim) // 2
            katsumi = katsumi.crop((left, top, left + min_dim, top + min_dim))
            katsumi = katsumi.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)

            x_k = 30
            y_k = SCREEN_HEIGHT - ICON_SIZE - 30
            if katsumi.mode == 'RGBA':
                screen.paste(katsumi, (x_k, y_k), katsumi)
            else:
                screen.paste(katsumi, (x_k, y_k))
        except Exception as e:
            print(f"   ⚠️ カツミアイコンエラー: {e}")

    if HIROSHI_ICON.exists():
        try:
            hiroshi = Image.open(HIROSHI_ICON)
            # 正方形にクロップ
            min_dim = min(hiroshi.width, hiroshi.height)
            left = (hiroshi.width - min_dim) // 2
            top = (hiroshi.height - min_dim) // 2
            hiroshi = hiroshi.crop((left, top, left + min_dim, top + min_dim))
            hiroshi = hiroshi.resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)

            x_h = SCREEN_WIDTH - ICON_SIZE - 30
            y_h = SCREEN_HEIGHT - ICON_SIZE - 30
            if hiroshi.mode == 'RGBA':
                screen.paste(hiroshi, (x_h, y_h), hiroshi)
            else:
                screen.paste(hiroshi, (x_h, y_h))
        except Exception as e:
            print(f"   ⚠️ ヒロシアイコンエラー: {e}")

    # パターン名を表示
    draw = ImageDraw.Draw(screen)
    font_label = FontManager.get_font(36)
    label_text = style_info["label"]
    bbox = draw.textbbox((0, 0), label_text, font=font_label)
    text_w = bbox[2] - bbox[0]

    draw.rectangle([SCREEN_WIDTH//2 - text_w//2 - 20, 10,
                   SCREEN_WIDTH//2 + text_w//2 + 20, 60], fill="#000000CC")
    draw.text((SCREEN_WIDTH//2 - text_w//2, 15), label_text, font=font_label, fill="#FFFFFF")

    return screen


def main():
    print("\n🎨 カラーパターン最終版（オレンジ系D + 縁取りバリエーション）")
    print("=" * 70)

    for style_info in OUTLINE_STYLES:
        print(f"   生成中: {style_info['label']}...")

        screen = create_screen_preview(BASE_COLORS, style_info)
        output_path = OUTPUT_DIR / f"{style_info['name']}.png"
        screen.save(output_path)

        print(f"   ✓ {output_path.name}")

    print("\n" + "=" * 70)
    print(f"✅ 完了！ {len(OUTLINE_STYLES)}パターンを生成")
    print(f"📁 出力先: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
