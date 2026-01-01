#!/usr/bin/env python3
"""
昭和ランキング動画システム

使い方:
  python3 showa_ranking.py                    # ランダムテーマで生成・投稿
  python3 showa_ranking.py --theme "昭和の俳優"  # テーマ指定
  python3 showa_ranking.py --preview          # プレビューモード（投稿なし）
  python3 showa_ranking.py --shorts-only      # ショート動画のみ
"""

import os
import sys
import json
import time
import random
import shutil
import pickle
import argparse
import subprocess
from io import BytesIO
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple

import requests
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from google import genai
from google.genai import types

# 環境変数を読み込み
load_dotenv(Path(__file__).parent.parent / ".env")


# ============================================================
# 設定
# ============================================================
class Config:
    """設定"""

    # API
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY")

    # ディレクトリ
    BASE_DIR = Path(__file__).parent
    TEMP_DIR = BASE_DIR / "temp"
    THEMES_FILE = BASE_DIR / "themes.json"
    HISTORY_FILE = BASE_DIR / "history.json"

    # 出力
    OUTPUT_DIR = Path.home() / "Desktop"

    # パネルサイズ
    PANEL_WIDTH = 400
    PANEL_HEIGHT = 900
    DIVIDER_WIDTH = 1  # 透明仕切り

    # 動画設定
    HORIZONTAL_WIDTH = 1920
    HORIZONTAL_HEIGHT = 1080
    SHORTS_WIDTH = 1080
    SHORTS_HEIGHT = 1920

    # 表示設定
    PANELS_PER_SCREEN_HORIZONTAL = 4  # 横動画で同時表示
    PANELS_PER_SCREEN_SHORTS = 1      # ショートで同時表示
    TOTAL_PANELS = 30                  # 総パネル数
    SHORTS_PANELS = 10                 # ショート用パネル数

    # スクロール速度（秒/パネル）
    SCROLL_SPEED_HORIZONTAL = 3.0
    SCROLL_SPEED_SHORTS = 2.0

    # 通知
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
    SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_COMMENT")

    # 昭和カラーパレット（参考画像準拠）
    COLORS = {
        "header_bg": "#B94047",      # 臙脂（えんじ）- 名前背景
        "header_bg_alt": "#F8B500",  # 山吹色 - 交互用
        "year_bg": "#8B0000",        # えんじ色 - 年代背景
        "detail_bg": "#1A1A1A",      # 黒 - 詳細背景
        "panel_bg": "#2D2D2D",       # ダークグレー - パネル背景
        "screen_bg": "#000000",      # 黒 - 画面背景
        "text_white": "#FFFFFF",     # 白文字
        "text_highlight": "#FF3333", # 赤文字（ハイライト数字）
        "divider": "#000000",        # 黒仕切り
    }

    # キャラクターアイコン
    KATSUMI_ICON = BASE_DIR.parent / "assets" / "icons" / "katsumi_icon.png"
    HIROSHI_ICON = BASE_DIR.parent / "assets" / "icons" / "hiroshi_icon.png"
    ICON_SIZE = 100

    @classmethod
    def create_directories(cls):
        """一時ディレクトリを作成"""
        cls.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        (cls.TEMP_DIR / "images").mkdir(exist_ok=True)
        (cls.TEMP_DIR / "panels").mkdir(exist_ok=True)
        (cls.TEMP_DIR / "video").mkdir(exist_ok=True)

    @classmethod
    def cleanup(cls):
        """一時ディレクトリを削除"""
        if cls.TEMP_DIR.exists():
            shutil.rmtree(cls.TEMP_DIR)


# ============================================================
# フォント管理
# ============================================================
class FontManager:
    """フォント管理"""

    _fonts = {}

    @classmethod
    def get_font(cls, size: int) -> ImageFont.FreeTypeFont:
        """フォントを取得"""
        if size not in cls._fonts:
            font_paths = [
                "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
                "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
                "/System/Library/Fonts/Hiragino Sans GB.ttc",
            ]
            for path in font_paths:
                if Path(path).exists():
                    cls._fonts[size] = ImageFont.truetype(path, size)
                    break
            else:
                cls._fonts[size] = ImageFont.load_default()
        return cls._fonts[size]


# ============================================================
# 1. テーマ選択
# ============================================================
class ThemeSelector:
    """テーマ選択"""

    def __init__(self):
        self.themes = self._load_themes()
        self.history = self._load_history()

    def _load_themes(self) -> List[Dict]:
        """テーマ定義を読み込み"""
        with open(Config.THEMES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data["themes"]

    def _load_history(self) -> List[str]:
        """投稿履歴を読み込み"""
        if Config.HISTORY_FILE.exists():
            with open(Config.HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save_history(self, theme_id: str):
        """投稿履歴を保存"""
        self.history.append(theme_id)
        # 最新20件のみ保持
        self.history = self.history[-20:]
        with open(Config.HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def select(self, theme_name: str = None) -> Optional[Dict]:
        """テーマを選択"""
        print("\n🎯 テーマを選択中...")

        if theme_name:
            # 指定されたテーマを検索
            for theme in self.themes:
                if theme["name"] == theme_name:
                    print(f"   ✓ テーマ: {theme['name']}")
                    return theme
            print(f"   ❌ テーマが見つかりません: {theme_name}")
            return None

        # ランダム選択（最近使用したテーマを除外）
        available = [t for t in self.themes if t["id"] not in self.history[-5:]]
        if not available:
            available = self.themes

        theme = random.choice(available)
        print(f"   ✓ テーマ: {theme['name']}")
        return theme

    def mark_used(self, theme_id: str):
        """使用済みとしてマーク"""
        self._save_history(theme_id)


# ============================================================
# 2. データ生成（Gemini API）
# ============================================================
class DataGenerator:
    """ランキングデータ生成"""

    def __init__(self):
        self.client = genai.Client(api_key=Config.GEMINI_API_KEY)
        self.model = "gemini-2.0-flash"

    def generate(self, theme: Dict) -> Optional[List[Dict]]:
        """ランキングデータを生成"""
        print(f"\n📊 ランキングデータを生成中...")

        # フィールド定義を作成
        field_defs = "\n".join([
            f"   - {field}: {label}"
            for field, label in zip(theme["fields"], theme["field_labels"])
        ])

        prompt = f"""あなたは昭和時代（1926-1989年）の日本文化に詳しい専門家です。

【テーマ】{theme['name']}

以下の条件でランキングデータを30件生成してください：

1. 昭和時代に活躍した/流行した/発売されたものに限定
2. 一般的な知名度・人気度でランキング
3. 各項目には以下のデータを含める：
   - rank: 順位（1-30）
   - name: 名前/商品名
{field_defs}
   - image_query: 画像検索用キーワード（「{theme['name'].replace('昭和の', '')} 名前」の形式）
   - description: 簡潔な説明（30文字以内）

【出力形式】
JSON配列で出力してください。説明文は不要です。

例:
[
  {{
    "rank": 1,
    "name": "例の名前",
    "{theme['fields'][0]}": "データ1",
    "{theme['fields'][1]}": "データ2",
    "{theme['fields'][2]}": "データ3",
    "image_query": "{theme['name'].replace('昭和の', '')} 例の名前",
    "description": "説明文"
  }}
]
"""

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )

                response_text = response.text.strip()

                # JSONブロックを抽出
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0].strip()

                data = json.loads(response_text)

                if not isinstance(data, list) or len(data) < 30:
                    raise ValueError(f"データが不足しています: {len(data)}件")

                print(f"   ✓ データ生成完了: {len(data)}件")

                # 保存
                output_path = Config.TEMP_DIR / "ranking_data.json"
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                return data[:30]  # 30件に制限

            except json.JSONDecodeError as e:
                print(f"   ⚠️ JSONパースエラー (試行 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(2)
            except Exception as e:
                print(f"   ❌ データ生成エラー: {e}")
                return None

        return None


# ============================================================
# 3. 画像取得
# ============================================================
class ImageFetcher:
    """画像取得"""

    def __init__(self):
        self.unsplash_key = Config.UNSPLASH_ACCESS_KEY
        self.client = genai.Client(api_key=Config.GEMINI_API_KEY)

    def fetch(self, ranking_data: List[Dict]) -> List[Dict]:
        """画像を取得"""
        print(f"\n🖼️ 画像を取得中...")

        images = []
        for item in ranking_data:
            rank = item["rank"]
            query = item.get("image_query", item["name"])

            output_path = Config.TEMP_DIR / "images" / f"image_{rank:02d}.png"

            print(f"   {rank}位: {item['name'][:15]}...")

            # Unsplash検索を試行
            if self.unsplash_key:
                success = self._fetch_from_unsplash(query, output_path)
                if success:
                    images.append({"rank": rank, "path": output_path})
                    continue

            # フォールバック: ダミー画像
            self._create_placeholder(item["name"], output_path)
            images.append({"rank": rank, "path": output_path})

            time.sleep(0.5)  # API制限対策

        print(f"   ✓ 画像取得完了: {len(images)}枚")
        return images

    def _fetch_from_unsplash(self, query: str, output_path: Path) -> bool:
        """Unsplashから画像を取得"""
        try:
            url = "https://api.unsplash.com/search/photos"
            params = {
                "query": query,
                "per_page": 1,
                "orientation": "squarish"
            }
            headers = {"Authorization": f"Client-ID {self.unsplash_key}"}

            response = requests.get(url, params=params, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if data["results"]:
                    img_url = data["results"][0]["urls"]["regular"]
                    img_response = requests.get(img_url, timeout=10)

                    if img_response.status_code == 200:
                        img = Image.open(BytesIO(img_response.content))
                        img = img.resize((400, 500), Image.Resampling.LANCZOS)
                        img.save(output_path)
                        return True

            return False

        except Exception:
            return False

    def _create_placeholder(self, name: str, output_path: Path):
        """プレースホルダー画像を作成"""
        img = Image.new("RGB", (400, 500), "#555555")
        draw = ImageDraw.Draw(img)

        # 枠線
        draw.rectangle([5, 5, 395, 495], outline="#666666", width=2)

        # テキスト
        font = FontManager.get_font(24)
        text = name[:10]
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        draw.text(((400 - text_w) // 2, 230), text, font=font, fill="#AAAAAA")

        img.save(output_path)


# ============================================================
# 4. パネル生成
# ============================================================
class PanelGenerator:
    """パネル画像生成"""

    def generate(self, ranking_data: List[Dict], images: List[Dict], theme: Dict) -> List[Path]:
        """パネル画像を生成"""
        print(f"\n🎨 パネルを生成中...")

        panels = []

        for item in ranking_data:
            rank = item["rank"]

            # 対応する画像を取得
            img_data = next((i for i in images if i["rank"] == rank), None)
            if not img_data:
                continue

            panel_path = Config.TEMP_DIR / "panels" / f"panel_{rank:02d}.png"

            # パネルを生成
            panel = self._create_panel(item, img_data["path"], theme)
            panel.save(panel_path)
            panels.append(panel_path)

            print(f"   {rank}位: ✓")

        print(f"   ✓ パネル生成完了: {len(panels)}枚")
        return panels

    def _draw_text_with_outline(self, draw: ImageDraw.Draw, text: str, x: int, y: int,
                                  font: ImageFont.FreeTypeFont, fill_color: str,
                                  outline_color: str = "#000000", outline_width: int = 3):
        """縁取り付きテキストを描画"""
        # 縁取り（8方向）
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        # 本体
        draw.text((x, y), text, font=font, fill=fill_color)

    def _draw_centered_text(self, draw: ImageDraw.Draw, text: str, y: int,
                            font: ImageFont.FreeTypeFont, fill_color: str):
        """中央揃えテキストを描画"""
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        x = (Config.PANEL_WIDTH - text_w) // 2
        draw.text((x, y), text, font=font, fill=fill_color)
        return x, text_w

    def _create_panel(self, item: Dict, image_path: Path, theme: Dict) -> Image.Image:
        """1枚のパネルを生成（参考画像準拠デザイン）

        レイアウト:
        ┌─────────────────┐
        │    名前         │  80px  - 昭和カラー背景、白文字
        ├─────────────────┤
        │                 │
        │     写真        │  420px - 大きく表示
        │                 │
        ├─────────────────┤
        │   年代情報      │  70px  - えんじ色背景
        ├─────────────────┤
        │   詳細1         │
        │   詳細2         │  130px - 黒背景、白文字
        ├─────────────────┤
        │                 │
        │   順位          │  200px - 大きな数字、縁取り
        │  （赤文字）     │
        └─────────────────┘
        """
        panel = Image.new("RGB", (Config.PANEL_WIDTH, Config.PANEL_HEIGHT), Config.COLORS["panel_bg"])
        draw = ImageDraw.Draw(panel)

        rank = item['rank']
        y_cursor = 0

        # ============================================
        # 1. 名前エリア（上部 80px）- 昭和カラー背景
        # ============================================
        header_h = 80
        header_color = Config.COLORS["header_bg"] if rank % 2 == 1 else Config.COLORS["header_bg_alt"]
        draw.rectangle([0, 0, Config.PANEL_WIDTH, header_h], fill=header_color)

        # 名前テキスト（太め、白文字）
        name_text = item["name"][:10]
        font_name = FontManager.get_font(42)
        bbox = draw.textbbox((0, 0), name_text, font=font_name)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x_name = (Config.PANEL_WIDTH - text_w) // 2
        y_name = (header_h - text_h) // 2 - 5

        # 影
        draw.text((x_name + 2, y_name + 2), name_text, font=font_name, fill="#000000")
        # 本体（白）
        draw.text((x_name, y_name), name_text, font=font_name, fill=Config.COLORS["text_white"])

        y_cursor = header_h

        # ============================================
        # 2. 写真エリア（420px）- 大きく表示
        # ============================================
        img_h = 420
        img_margin = 5
        img_x = img_margin
        img_y = y_cursor + img_margin
        img_w = Config.PANEL_WIDTH - (img_margin * 2)
        img_display_h = img_h - (img_margin * 2)

        try:
            img = Image.open(image_path)
            # アスペクト比を維持してリサイズ
            img_ratio = img.width / img.height
            target_ratio = img_w / img_display_h

            if img_ratio > target_ratio:
                # 横長: 幅に合わせる
                new_w = img_w
                new_h = int(img_w / img_ratio)
            else:
                # 縦長: 高さに合わせる
                new_h = img_display_h
                new_w = int(img_display_h * img_ratio)

            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            # 中央配置
            paste_x = img_x + (img_w - new_w) // 2
            paste_y = img_y + (img_display_h - new_h) // 2
            panel.paste(img, (paste_x, paste_y))

        except Exception:
            # プレースホルダー
            draw.rectangle([img_x, img_y, img_x + img_w, img_y + img_display_h], fill="#444444")
            placeholder_font = FontManager.get_font(36)
            ph_text = item["name"][:6]
            self._draw_centered_text(draw, ph_text, img_y + img_display_h // 2 - 20,
                                     placeholder_font, "#888888")

        y_cursor += img_h

        # ============================================
        # 3. 年代情報エリア（70px）- えんじ色背景
        # ============================================
        year_h = 70
        draw.rectangle([0, y_cursor, Config.PANEL_WIDTH, y_cursor + year_h], fill=Config.COLORS["year_bg"])

        # 年代ラベルと値
        font_year_label = FontManager.get_font(22)
        font_year_value = FontManager.get_font(30)

        # テーマに応じた年代フィールドを取得
        year_field = theme["fields"][0]  # 最初のフィールド（通常は発売年など）
        year_label = theme["field_labels"][0]
        year_value = str(item.get(year_field, "-"))

        # ラベル
        self._draw_centered_text(draw, year_label, y_cursor + 8, font_year_label, "#CCCCCC")
        # 値（大きめ）
        self._draw_centered_text(draw, year_value, y_cursor + 32, font_year_value, Config.COLORS["text_white"])

        y_cursor += year_h

        # ============================================
        # 4. 詳細エリア（130px）- 黒背景、白文字
        # ============================================
        detail_h = 130
        draw.rectangle([0, y_cursor, Config.PANEL_WIDTH, y_cursor + detail_h], fill=Config.COLORS["detail_bg"])

        font_detail_label = FontManager.get_font(20)
        font_detail_value = FontManager.get_font(26)

        # 残りのフィールドを表示（2つ目以降）
        detail_y = y_cursor + 15
        for i, (field, label) in enumerate(zip(theme["fields"][1:], theme["field_labels"][1:])):
            value = item.get(field, "-")
            if isinstance(value, (int, float)):
                value = str(value)
            value = str(value)[:15]

            # ラベル（小さめ、グレー）
            self._draw_centered_text(draw, label, detail_y, font_detail_label, "#888888")
            # 値（大きめ、白）
            self._draw_centered_text(draw, value, detail_y + 22, font_detail_value, Config.COLORS["text_white"])

            detail_y += 55
            if i >= 1:  # 最大2項目
                break

        y_cursor += detail_h

        # ============================================
        # 5. 順位エリア（200px）- 大きな数字、インパクト重視
        # ============================================
        rank_area_h = Config.PANEL_HEIGHT - y_cursor
        draw.rectangle([0, y_cursor, Config.PANEL_WIDTH, Config.PANEL_HEIGHT], fill=Config.COLORS["panel_bg"])

        # 順位の大きな数字
        font_rank_num = FontManager.get_font(120)
        font_rank_label = FontManager.get_font(32)

        rank_text = f"{rank}"
        rank_label = "位"

        # 順位数字のサイズ計算
        bbox_num = draw.textbbox((0, 0), rank_text, font=font_rank_num)
        bbox_label = draw.textbbox((0, 0), rank_label, font=font_rank_label)

        num_w = bbox_num[2] - bbox_num[0]
        num_h = bbox_num[3] - bbox_num[1]
        label_w = bbox_label[2] - bbox_label[0]

        # 中央配置
        total_w = num_w + label_w + 5
        x_num = (Config.PANEL_WIDTH - total_w) // 2
        y_num = y_cursor + (rank_area_h - num_h) // 2 - 20

        # 影
        draw.text((x_num + 4, y_num + 4), rank_text, font=font_rank_num, fill="#000000")

        # 縁取り付き順位数字（赤）
        self._draw_text_with_outline(draw, rank_text, x_num, y_num, font_rank_num,
                                      fill_color=Config.COLORS["text_highlight"],
                                      outline_color="#000000", outline_width=4)

        # 「位」ラベル
        x_label = x_num + num_w + 5
        y_label = y_num + num_h - 50  # 下揃え

        draw.text((x_label + 2, y_label + 2), rank_label, font=font_rank_label, fill="#000000")
        draw.text((x_label, y_label), rank_label, font=font_rank_label, fill=Config.COLORS["text_white"])

        return panel


# ============================================================
# 5. 動画生成
# ============================================================
class VideoGenerator:
    """動画生成"""

    def _prepare_icons(self) -> Tuple[Optional[Path], Optional[Path]]:
        """キャラクターアイコンを準備（リサイズ）"""
        katsumi_resized = None
        hiroshi_resized = None

        if Config.KATSUMI_ICON.exists():
            try:
                img = Image.open(Config.KATSUMI_ICON)
                img = img.resize((Config.ICON_SIZE, Config.ICON_SIZE), Image.Resampling.LANCZOS)
                katsumi_resized = Config.TEMP_DIR / "video" / "katsumi_icon_resized.png"
                img.save(katsumi_resized)
            except Exception as e:
                print(f"   ⚠️ カツミアイコン準備エラー: {e}")

        if Config.HIROSHI_ICON.exists():
            try:
                img = Image.open(Config.HIROSHI_ICON)
                img = img.resize((Config.ICON_SIZE, Config.ICON_SIZE), Image.Resampling.LANCZOS)
                hiroshi_resized = Config.TEMP_DIR / "video" / "hiroshi_icon_resized.png"
                img.save(hiroshi_resized)
            except Exception as e:
                print(f"   ⚠️ ヒロシアイコン準備エラー: {e}")

        return katsumi_resized, hiroshi_resized

    def generate_horizontal(self, panels: List[Path], theme: Dict) -> Optional[Path]:
        """横動画を生成（1920x1080）"""
        print(f"\n🎬 横動画を生成中...")

        # 1. パネルを横に並べた長い画像を作成
        total_width = len(panels) * (Config.PANEL_WIDTH + Config.DIVIDER_WIDTH)
        strip = Image.new("RGB", (total_width, Config.PANEL_HEIGHT), Config.COLORS["screen_bg"])

        x_pos = 0
        for panel_path in panels:
            panel = Image.open(panel_path)
            strip.paste(panel, (x_pos, 0))
            x_pos += Config.PANEL_WIDTH + Config.DIVIDER_WIDTH

        strip_path = Config.TEMP_DIR / "video" / "strip_horizontal.png"
        strip.save(strip_path)

        # キャラクターアイコンを準備
        katsumi_icon, hiroshi_icon = self._prepare_icons()

        # 2. スクロール動画を生成
        output_path = Config.TEMP_DIR / "video" / f"horizontal_{theme['id']}.mp4"
        temp_output = Config.TEMP_DIR / "video" / f"horizontal_{theme['id']}_temp.mp4"

        # スクロール距離と時間を計算
        visible_width = Config.HORIZONTAL_WIDTH
        scroll_distance = total_width - visible_width
        duration = len(panels) * Config.SCROLL_SPEED_HORIZONTAL

        # パネルを画面中央に配置するためのY位置
        y_offset = (Config.HORIZONTAL_HEIGHT - Config.PANEL_HEIGHT) // 2

        # ffmpegでスクロール動画を生成
        # crop フィルタでスクロールを実現
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(strip_path),
            "-vf", f"scale={total_width}:{Config.PANEL_HEIGHT},"
                   f"pad={total_width}:{Config.HORIZONTAL_HEIGHT}:0:{y_offset}:{Config.COLORS['screen_bg'].replace('#', '0x')},"
                   f"crop={visible_width}:{Config.HORIZONTAL_HEIGHT}:"
                   f"'min({scroll_distance},max(0,{scroll_distance}*t/{duration}))':"
                   f"0",
            "-t", str(duration),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            str(temp_output if (katsumi_icon or hiroshi_icon) else output_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"   ❌ ffmpegエラー: {result.stderr[:200]}")
            return None

        # 3. キャラクターアイコンをオーバーレイ
        if katsumi_icon or hiroshi_icon:
            inputs = ["-i", str(temp_output)]
            filter_parts = []
            overlay_chain = "[0:v]"

            if katsumi_icon:
                inputs.extend(["-i", str(katsumi_icon)])
                # 左下に配置（余白20px）
                icon_y = Config.HORIZONTAL_HEIGHT - Config.ICON_SIZE - 20
                filter_parts.append(f"{overlay_chain}[1:v]overlay=20:{icon_y}[v1]")
                overlay_chain = "[v1]"

            if hiroshi_icon:
                input_idx = 2 if katsumi_icon else 1
                inputs.extend(["-i", str(hiroshi_icon)])
                # 右下に配置（余白20px）
                icon_x = Config.HORIZONTAL_WIDTH - Config.ICON_SIZE - 20
                icon_y = Config.HORIZONTAL_HEIGHT - Config.ICON_SIZE - 20
                filter_parts.append(f"{overlay_chain}[{input_idx}:v]overlay={icon_x}:{icon_y}")

            filter_complex = ";".join(filter_parts)

            cmd_overlay = [
                "ffmpeg", "-y",
                *inputs,
                "-filter_complex", filter_complex,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                str(output_path)
            ]

            result = subprocess.run(cmd_overlay, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"   ⚠️ アイコンオーバーレイエラー、一時ファイルを使用")
                shutil.copy2(temp_output, output_path)

            # 一時ファイル削除
            if temp_output.exists():
                temp_output.unlink()

        print(f"   ✓ 横動画生成完了: {duration:.1f}秒")
        return output_path

    def generate_shorts(self, panels: List[Path], theme: Dict) -> Optional[Path]:
        """ショート動画を生成（1080x1920）"""
        print(f"\n📱 ショート動画を生成中...")

        # 上位10枚のみ使用
        shorts_panels = panels[:Config.SHORTS_PANELS]

        # 1. パネルを横に並べた長い画像を作成
        total_width = len(shorts_panels) * (Config.PANEL_WIDTH + Config.DIVIDER_WIDTH)
        strip = Image.new("RGB", (total_width, Config.PANEL_HEIGHT), Config.COLORS["screen_bg"])

        x_pos = 0
        for panel_path in shorts_panels:
            panel = Image.open(panel_path)
            strip.paste(panel, (x_pos, 0))
            x_pos += Config.PANEL_WIDTH + Config.DIVIDER_WIDTH

        strip_path = Config.TEMP_DIR / "video" / "strip_shorts.png"
        strip.save(strip_path)

        # キャラクターアイコンを準備
        katsumi_icon, hiroshi_icon = self._prepare_icons()

        # 2. スクロール動画を生成
        output_path = Config.TEMP_DIR / "video" / f"shorts_{theme['id']}.mp4"
        temp_output = Config.TEMP_DIR / "video" / f"shorts_{theme['id']}_temp.mp4"

        # 縦画面では1パネル表示（パネル幅 < 画面幅なので中央配置）
        visible_width = Config.PANEL_WIDTH + 100  # 余白付き
        scroll_distance = total_width - visible_width
        duration = len(shorts_panels) * Config.SCROLL_SPEED_SHORTS

        # パネルを画面中央に配置
        y_offset = (Config.SHORTS_HEIGHT - Config.PANEL_HEIGHT) // 2
        x_pad = (Config.SHORTS_WIDTH - visible_width) // 2

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(strip_path),
            "-vf", f"scale={total_width}:{Config.PANEL_HEIGHT},"
                   f"crop={visible_width}:{Config.PANEL_HEIGHT}:"
                   f"'min({scroll_distance},max(0,{scroll_distance}*t/{duration}))':"
                   f"0,"
                   f"pad={Config.SHORTS_WIDTH}:{Config.SHORTS_HEIGHT}:{x_pad}:{y_offset}:{Config.COLORS['screen_bg'].replace('#', '0x')}",
            "-t", str(duration),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            str(temp_output if (katsumi_icon or hiroshi_icon) else output_path)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"   ❌ ffmpegエラー: {result.stderr[:200]}")
            return None

        # 3. キャラクターアイコンをオーバーレイ（ショート用）
        if katsumi_icon or hiroshi_icon:
            inputs = ["-i", str(temp_output)]
            filter_parts = []
            overlay_chain = "[0:v]"

            # ショートでは下部に横並びで配置
            icon_y = Config.SHORTS_HEIGHT - Config.ICON_SIZE - 40

            if katsumi_icon:
                inputs.extend(["-i", str(katsumi_icon)])
                # 左側に配置
                icon_x = (Config.SHORTS_WIDTH // 2) - Config.ICON_SIZE - 20
                filter_parts.append(f"{overlay_chain}[1:v]overlay={icon_x}:{icon_y}[v1]")
                overlay_chain = "[v1]"

            if hiroshi_icon:
                input_idx = 2 if katsumi_icon else 1
                inputs.extend(["-i", str(hiroshi_icon)])
                # 右側に配置
                icon_x = (Config.SHORTS_WIDTH // 2) + 20
                filter_parts.append(f"{overlay_chain}[{input_idx}:v]overlay={icon_x}:{icon_y}")

            filter_complex = ";".join(filter_parts)

            cmd_overlay = [
                "ffmpeg", "-y",
                *inputs,
                "-filter_complex", filter_complex,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                str(output_path)
            ]

            result = subprocess.run(cmd_overlay, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"   ⚠️ アイコンオーバーレイエラー、一時ファイルを使用")
                shutil.copy2(temp_output, output_path)

            # 一時ファイル削除
            if temp_output.exists():
                temp_output.unlink()

        print(f"   ✓ ショート動画生成完了: {duration:.1f}秒")
        return output_path


# ============================================================
# 6. YouTubeアップロード
# ============================================================
class YouTubeUploader:
    """YouTubeアップロード"""

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

    def __init__(self):
        self.youtube = None
        self._authenticate()

    def _authenticate(self):
        """認証"""
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = None
        token_path = Config.BASE_DIR.parent / "token_youtube.pickle"

        if token_path.exists():
            with open(token_path, "rb") as token:
                creds = pickle.load(token)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                client_secrets = Config.BASE_DIR.parent / "client_secrets.json"
                if not client_secrets.exists():
                    raise FileNotFoundError("client_secrets.json が見つかりません")

                flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), self.SCOPES)
                creds = flow.run_local_server(port=0)

            with open(token_path, "wb") as token:
                pickle.dump(creds, token)

        self.youtube = build("youtube", "v3", credentials=creds)

    def upload(self, video_path: Path, title: str, description: str, tags: List[str], is_shorts: bool = False) -> Optional[str]:
        """動画をアップロード"""
        from googleapiclient.http import MediaFileUpload

        print(f"\n📤 {'ショート' if is_shorts else '横動画'}をアップロード中...")

        try:
            if is_shorts and not title.endswith("#shorts"):
                title = f"{title} #shorts"

            request_body = {
                "snippet": {
                    "title": title[:100],
                    "description": description,
                    "tags": tags,
                    "categoryId": "22"
                },
                "status": {
                    "privacyStatus": "public",
                    "selfDeclaredMadeForKids": False
                }
            }

            media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")

            request = self.youtube.videos().insert(part="snippet,status", body=request_body, media_body=media)

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"   進捗: {int(status.progress() * 100)}%")

            video_id = response["id"]
            print(f"   ✓ アップロード完了: https://www.youtube.com/watch?v={video_id}")
            return video_id

        except Exception as e:
            print(f"   ❌ アップロードエラー: {e}")
            return None


# ============================================================
# 7. 通知
# ============================================================
class Notifier:
    """通知"""

    @staticmethod
    def discord(message: str):
        """Discord通知"""
        return  # 通知無効化
        webhook_url = Config.DISCORD_WEBHOOK_URL
        if not webhook_url:
            return

        try:
            requests.post(webhook_url, json={"content": message}, timeout=10)
            print("   ✓ Discord通知を送信しました")
        except Exception as e:
            print(f"   ⚠️ Discord通知エラー: {e}")

    @staticmethod
    def slack_error(error_message: str):
        """Slackエラー通知"""
        return  # 通知無効化
        webhook_url = Config.SLACK_WEBHOOK_URL
        if not webhook_url:
            return

        try:
            requests.post(webhook_url, json={"text": f"❌ 昭和ランキングエラー\n```\n{error_message[:500]}\n```"}, timeout=10)
        except Exception:
            pass


# ============================================================
# メインシステム
# ============================================================
class ShowaRankingSystem:
    """昭和ランキング動画システム"""

    def __init__(self, theme_name: str = None, preview: bool = False, shorts_only: bool = False):
        self.theme_name = theme_name
        self.preview = preview
        self.shorts_only = shorts_only

        self.theme_selector = ThemeSelector()
        self.data_generator = DataGenerator()
        self.image_fetcher = ImageFetcher()
        self.panel_generator = PanelGenerator()
        self.video_generator = VideoGenerator()
        self.uploader = None if preview else YouTubeUploader()

    def run(self) -> bool:
        """メイン処理"""
        start_time = time.time()

        print("\n" + "=" * 60)
        print("📺 昭和ランキング動画システム")
        print("=" * 60)
        print(f"モード: {'プレビュー' if self.preview else 'YouTube投稿'}")
        print(f"開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            Config.create_directories()

            # 1. テーマ選択
            theme = self.theme_selector.select(self.theme_name)
            if not theme:
                raise Exception("テーマ選択失敗")

            # 2. データ生成
            ranking_data = self.data_generator.generate(theme)
            if not ranking_data:
                raise Exception("データ生成失敗")

            # 3. 画像取得
            images = self.image_fetcher.fetch(ranking_data)
            if not images:
                raise Exception("画像取得失敗")

            # 4. パネル生成
            panels = self.panel_generator.generate(ranking_data, images, theme)
            if not panels:
                raise Exception("パネル生成失敗")

            # 5. 動画生成
            horizontal_path = None
            shorts_path = None

            if not self.shorts_only:
                horizontal_path = self.video_generator.generate_horizontal(panels, theme)

            shorts_path = self.video_generator.generate_shorts(panels, theme)

            # 6. 出力
            if self.preview:
                # デスクトップに保存
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                if horizontal_path:
                    output_h = Config.OUTPUT_DIR / f"showa_{theme['id']}_{timestamp}.mp4"
                    shutil.copy2(horizontal_path, output_h)
                    print(f"\n📁 横動画: {output_h}")

                if shorts_path:
                    output_s = Config.OUTPUT_DIR / f"showa_{theme['id']}_{timestamp}_shorts.mp4"
                    shutil.copy2(shorts_path, output_s)
                    print(f"📁 ショート: {output_s}")

            else:
                # YouTubeアップロード
                title = theme["title_template"]
                description = f"""昭和時代の懐かしい{theme['name'].replace('昭和の', '')}をランキング形式でご紹介！

あの頃を思い出しながらお楽しみください。

#昭和 #懐かしい #ランキング #{theme['name'].replace('昭和の', '')} #レトロ"""
                tags = ["昭和", "懐かしい", "ランキング", theme['name'].replace('昭和の', ''), "レトロ", "昭和時代"]

                horizontal_id = None
                shorts_id = None

                if horizontal_path and not self.shorts_only:
                    horizontal_id = self.uploader.upload(horizontal_path, title, description, tags, is_shorts=False)

                if shorts_path:
                    shorts_id = self.uploader.upload(shorts_path, title, description, tags, is_shorts=True)

                # 使用済みマーク
                self.theme_selector.mark_used(theme["id"])

                # Discord通知
                msg_parts = [f"✅ **昭和ランキング投稿完了**\n\n**{theme['name']}**"]
                if horizontal_id:
                    msg_parts.append(f"横動画: https://www.youtube.com/watch?v={horizontal_id}")
                if shorts_id:
                    msg_parts.append(f"ショート: https://www.youtube.com/watch?v={shorts_id}")

                Notifier.discord("\n".join(msg_parts))

            # クリーンアップ
            if not self.preview:
                Config.cleanup()

            elapsed = time.time() - start_time
            print("\n" + "=" * 60)
            print(f"✅ 完了! ({elapsed/60:.1f}分)")
            print("=" * 60)

            return True

        except Exception as e:
            import traceback
            error_msg = f"{e}\n{traceback.format_exc()}"
            print(f"\n❌ エラー: {e}")
            Notifier.slack_error(error_msg)
            return False


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="昭和ランキング動画システム")
    parser.add_argument("--theme", help="テーマを指定（例: '昭和の俳優'）")
    parser.add_argument("--preview", action="store_true", help="プレビューモード（投稿なし）")
    parser.add_argument("--shorts-only", action="store_true", help="ショート動画のみ生成")

    args = parser.parse_args()

    system = ShowaRankingSystem(
        theme_name=args.theme,
        preview=args.preview,
        shorts_only=args.shorts_only
    )

    success = system.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
