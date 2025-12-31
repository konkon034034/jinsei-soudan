#!/usr/bin/env python3
"""
横スクロール動画用レイアウトパターン生成
10種類のデザインパターン（data_talks_jp参考）
"""

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# 定数
PANEL_WIDTH = 480  # 4パネルで1920px
PANEL_HEIGHT = 1080
SPACER_WIDTH = 1   # パネル間仕切り
OUTPUT_DIR = Path.home() / "Desktop" / "layout_patterns"


def get_font(size: int):
    """日本語フォントを取得"""
    font_paths = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except:
                continue
    return ImageFont.load_default()


def create_dummy_photo(width: int, height: int, style: str = "person") -> Image.Image:
    """ダミー写真を生成"""
    colors = {
        "person": (120, 100, 90),
        "landscape": (100, 140, 100),
        "action": (90, 110, 140),
        "ukiyoe": (200, 180, 150),
        "sepia": (160, 140, 120),
    }
    base_color = colors.get(style, (128, 128, 128))
    img = Image.new('RGB', (width, height), base_color)
    draw = ImageDraw.Draw(img)

    # グラデーション
    for y in range(height):
        ratio = y / height
        r = int(base_color[0] * (1 - ratio * 0.3))
        g = int(base_color[1] * (1 - ratio * 0.3))
        b = int(base_color[2] * (1 - ratio * 0.3))
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # 人物シルエット
    if style == "person":
        cx, cy = width // 2, height // 3
        r = min(width, height) // 4
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(180, 160, 150))

    return img


# ========== パターン1: シンプル人物 ==========
def pattern_01_simple_person(rank: int, name: str, value: str) -> Image.Image:
    """シンプル人物カード（緑ヘッダー）"""
    img = Image.new('RGB', (PANEL_WIDTH, PANEL_HEIGHT), (245, 245, 245))
    draw = ImageDraw.Draw(img)

    # 上部: 緑背景に順位
    draw.rectangle([0, 0, PANEL_WIDTH, 100], fill=(46, 139, 87))
    draw.text((PANEL_WIDTH // 2, 50), f"{rank}位", font=get_font(48), fill=(255, 255, 255), anchor="mm")

    # 中央: 顔写真
    photo = create_dummy_photo(320, 450, "person")
    img.paste(photo, ((PANEL_WIDTH - 320) // 2, 140))

    # 下部: 名前＋数値
    draw.text((PANEL_WIDTH // 2, 650), name, font=get_font(44), fill=(30, 30, 30), anchor="mm")
    draw.text((PANEL_WIDTH // 2, 750), value, font=get_font(72), fill=(220, 50, 50), anchor="mm")

    return img


# ========== パターン2: 都道府県データ ==========
def pattern_02_prefecture_data(rank: int, prefecture: str, photo_desc: str, value: str, change: str, desc: str) -> Image.Image:
    """都道府県データカード（緑ヘッダー）"""
    img = Image.new('RGB', (PANEL_WIDTH, PANEL_HEIGHT), (240, 245, 240))
    draw = ImageDraw.Draw(img)

    # 上部: 順位＋県名
    draw.rectangle([0, 0, PANEL_WIDTH, 120], fill=(34, 139, 34))
    draw.text((80, 60), f"{rank}位", font=get_font(40), fill=(255, 255, 200), anchor="mm")
    draw.text((PANEL_WIDTH // 2 + 40, 60), prefecture, font=get_font(52), fill=(255, 255, 255), anchor="mm")

    # 中央: 風景写真
    photo = create_dummy_photo(400, 350, "landscape")
    img.paste(photo, ((PANEL_WIDTH - 400) // 2, 150))

    # 下部: 数値＋増減率＋解説
    draw.text((PANEL_WIDTH // 2, 550), value, font=get_font(64), fill=(30, 30, 30), anchor="mm")

    change_color = (34, 139, 34) if change.startswith('+') else (220, 50, 50)
    draw.text((PANEL_WIDTH // 2, 640), change, font=get_font(48), fill=change_color, anchor="mm")

    # 解説（複数行対応）
    draw.rounded_rectangle([40, 720, PANEL_WIDTH - 40, 850], radius=10, fill=(255, 255, 255))
    draw.text((PANEL_WIDTH // 2, 785), desc, font=get_font(28), fill=(80, 80, 80), anchor="mm")

    return img


# ========== パターン3: ランキング詳細 ==========
def pattern_03_ranking_detail(rank: int, name: str, details: list) -> Image.Image:
    """ランキング詳細カード（青ヘッダー）"""
    img = Image.new('RGB', (PANEL_WIDTH, PANEL_HEIGHT), (240, 245, 255))
    draw = ImageDraw.Draw(img)

    # 上部: 順位＋名前
    draw.rectangle([0, 0, PANEL_WIDTH, 120], fill=(30, 60, 150))
    draw.text((80, 60), f"{rank}位", font=get_font(40), fill=(255, 200, 100), anchor="mm")
    draw.text((PANEL_WIDTH // 2 + 40, 60), name, font=get_font(44), fill=(255, 255, 255), anchor="mm")

    # 中央: 写真
    photo = create_dummy_photo(340, 380, "person")
    img.paste(photo, ((PANEL_WIDTH - 340) // 2, 150))

    # 下部: 詳細情報（複数行）
    draw.rounded_rectangle([30, 560, PANEL_WIDTH - 30, 900], radius=15, fill=(255, 255, 255))
    y = 590
    for label, value in details:
        draw.text((60, y), f"【{label}】", font=get_font(26), fill=(30, 60, 150))
        draw.text((60, y + 35), value, font=get_font(30), fill=(50, 50, 50))
        y += 85

    return img


# ========== パターン4: 数値特化 ==========
def pattern_04_number_focused(rank: int, name: str, main_value: str, sub_data: list) -> Image.Image:
    """数値特化カード（青緑ヘッダー）"""
    img = Image.new('RGB', (PANEL_WIDTH, PANEL_HEIGHT), (235, 250, 250))
    draw = ImageDraw.Draw(img)

    # 上部: 順位＋名前
    draw.rectangle([0, 0, PANEL_WIDTH, 100], fill=(0, 128, 128))
    draw.text((70, 50), f"{rank}位", font=get_font(36), fill=(255, 255, 200), anchor="mm")
    draw.text((PANEL_WIDTH // 2 + 30, 50), name, font=get_font(40), fill=(255, 255, 255), anchor="mm")

    # 中央: 大きな数値
    draw.rectangle([40, 200, PANEL_WIDTH - 40, 500], fill=(0, 100, 100))
    draw.text((PANEL_WIDTH // 2, 350), main_value, font=get_font(100), fill=(255, 255, 255), anchor="mm")

    # 下部: 補足データ
    y = 550
    for label, value in sub_data:
        draw.rounded_rectangle([50, y, PANEL_WIDTH - 50, y + 70], radius=8, fill=(255, 255, 255))
        draw.text((70, y + 35), label, font=get_font(24), fill=(0, 100, 100), anchor="lm")
        draw.text((PANEL_WIDTH - 70, y + 35), value, font=get_font(28), fill=(50, 50, 50), anchor="rm")
        y += 90

    return img


# ========== パターン5: 歴史人物 ==========
def pattern_05_historical(num: int, name: str, period: str, achievement: str) -> Image.Image:
    """歴史人物カード（緑ヘッダー）"""
    img = Image.new('RGB', (PANEL_WIDTH, PANEL_HEIGHT), (250, 245, 235))
    draw = ImageDraw.Draw(img)

    # 上部: 番号＋名前
    draw.rectangle([0, 0, PANEL_WIDTH, 100], fill=(85, 107, 47))
    draw.text((70, 50), f"{num}", font=get_font(48), fill=(255, 255, 200), anchor="mm")
    draw.text((PANEL_WIDTH // 2 + 30, 50), name, font=get_font(40), fill=(255, 255, 255), anchor="mm")

    # 中央: 浮世絵風
    photo = create_dummy_photo(350, 450, "ukiyoe")
    img.paste(photo, ((PANEL_WIDTH - 350) // 2, 130))

    # 下部: 期間＋実績
    draw.text((PANEL_WIDTH // 2, 620), period, font=get_font(32), fill=(100, 80, 60), anchor="mm")

    draw.rounded_rectangle([40, 680, PANEL_WIDTH - 40, 820], radius=10, fill=(255, 250, 240), outline=(139, 119, 101))
    draw.text((PANEL_WIDTH // 2, 750), achievement, font=get_font(36), fill=(80, 60, 40), anchor="mm")

    return img


# ========== パターン6: 享年/死因 ==========
def pattern_06_death_info(rank: int, name: str, age: str, birthdate: str, cause: str) -> Image.Image:
    """享年/死因カード（緑ヘッダー）"""
    img = Image.new('RGB', (PANEL_WIDTH, PANEL_HEIGHT), (245, 240, 235))
    draw = ImageDraw.Draw(img)

    # 上部: 順位
    draw.rectangle([0, 0, PANEL_WIDTH, 80], fill=(60, 120, 60))
    draw.text((PANEL_WIDTH // 2, 40), f"{rank}位", font=get_font(40), fill=(255, 255, 255), anchor="mm")

    # 写真
    photo = create_dummy_photo(300, 350, "sepia")
    img.paste(photo, ((PANEL_WIDTH - 300) // 2, 100))

    # 名前
    draw.text((PANEL_WIDTH // 2, 480), name, font=get_font(44), fill=(50, 50, 50), anchor="mm")

    # 享年（大きく）
    draw.rounded_rectangle([60, 530, PANEL_WIDTH - 60, 640], radius=10, fill=(255, 255, 255))
    draw.text((100, 585), "〈享年〉", font=get_font(28), fill=(100, 100, 100), anchor="lm")
    draw.text((PANEL_WIDTH - 80, 585), age, font=get_font(56), fill=(200, 50, 50), anchor="rm")

    # 生年月日
    draw.text((80, 680), "〈生年月日〉", font=get_font(24), fill=(100, 100, 100))
    draw.text((80, 715), birthdate, font=get_font(28), fill=(50, 50, 50))

    # 死因
    draw.text((80, 780), "〈病名〉", font=get_font(24), fill=(100, 100, 100))
    draw.text((80, 815), cause, font=get_font(28), fill=(50, 50, 50))

    return img


# ========== パターン7: 政治家/著名人 ==========
def pattern_07_politician(rank: int, affiliation: str, count: str, name: str) -> Image.Image:
    """政治家/著名人カード（金色ヘッダー）"""
    img = Image.new('RGB', (PANEL_WIDTH, PANEL_HEIGHT), (255, 250, 240))
    draw = ImageDraw.Draw(img)

    # 上部: 順位＋所属（金色）
    draw.rectangle([0, 0, PANEL_WIDTH, 110], fill=(184, 134, 11))
    draw.rounded_rectangle([20, 15, 100, 75], radius=5, fill=(255, 215, 0))
    draw.text((60, 45), f"{rank}位", font=get_font(28), fill=(100, 70, 0), anchor="mm")
    draw.text((PANEL_WIDTH // 2 + 30, 55), affiliation, font=get_font(48), fill=(255, 255, 255), anchor="mm")

    # 顔写真
    photo = create_dummy_photo(320, 400, "person")
    img.paste(photo, ((PANEL_WIDTH - 320) // 2, 140))

    # 人数
    draw.rounded_rectangle([80, 570, PANEL_WIDTH - 80, 680], radius=15, fill=(255, 255, 255), outline=(200, 170, 100), width=3)
    draw.text((PANEL_WIDTH // 2, 625), count, font=get_font(64), fill=(184, 134, 11), anchor="mm")

    # 名前
    draw.text((PANEL_WIDTH // 2, 750), name, font=get_font(36), fill=(80, 60, 40), anchor="mm")

    return img


# ========== パターン8: スポーツ選手 ==========
def pattern_08_athlete(rank: int, team: str, stats: str, record: str) -> Image.Image:
    """スポーツ選手カード"""
    img = Image.new('RGB', (PANEL_WIDTH, PANEL_HEIGHT), (240, 245, 255))
    draw = ImageDraw.Draw(img)

    # 上部: 順位＋チーム
    draw.rectangle([0, 0, PANEL_WIDTH, 100], fill=(25, 25, 112))
    draw.text((70, 50), f"{rank}位", font=get_font(36), fill=(255, 200, 0), anchor="mm")
    draw.text((PANEL_WIDTH // 2 + 40, 50), team, font=get_font(36), fill=(255, 255, 255), anchor="mm")

    # アクション写真
    photo = create_dummy_photo(380, 420, "action")
    img.paste(photo, ((PANEL_WIDTH - 380) // 2, 130))

    # 成績
    draw.rounded_rectangle([40, 580, PANEL_WIDTH - 40, 680], radius=10, fill=(25, 25, 112))
    draw.text((PANEL_WIDTH // 2, 630), stats, font=get_font(44), fill=(255, 255, 255), anchor="mm")

    # 記録
    draw.text((PANEL_WIDTH // 2, 750), record, font=get_font(52), fill=(200, 50, 50), anchor="mm")

    return img


# ========== パターン9: 比較型 ==========
def pattern_09_comparison(category: str, item1: tuple, item2: tuple, data: str) -> Image.Image:
    """比較型カード（2つ並列）"""
    img = Image.new('RGB', (PANEL_WIDTH, PANEL_HEIGHT), (250, 250, 250))
    draw = ImageDraw.Draw(img)

    # 上部: カテゴリ名
    draw.rectangle([0, 0, PANEL_WIDTH, 80], fill=(70, 70, 70))
    draw.text((PANEL_WIDTH // 2, 40), category, font=get_font(36), fill=(255, 255, 255), anchor="mm")

    # 2つの写真並列
    photo1 = create_dummy_photo(200, 280, "person")
    photo2 = create_dummy_photo(200, 280, "person")
    img.paste(photo1, (30, 120))
    img.paste(photo2, (PANEL_WIDTH - 230, 120))

    # VS
    draw.text((PANEL_WIDTH // 2, 260), "VS", font=get_font(40), fill=(200, 50, 50), anchor="mm")

    # 名前
    draw.text((130, 420), item1[0], font=get_font(28), fill=(50, 50, 50), anchor="mm")
    draw.text((PANEL_WIDTH - 130, 420), item2[0], font=get_font(28), fill=(50, 50, 50), anchor="mm")

    # 値
    draw.text((130, 470), item1[1], font=get_font(36), fill=(30, 100, 200), anchor="mm")
    draw.text((PANEL_WIDTH - 130, 470), item2[1], font=get_font(36), fill=(200, 50, 50), anchor="mm")

    # 比較データ
    draw.rounded_rectangle([30, 550, PANEL_WIDTH - 30, 700], radius=15, fill=(240, 240, 245))
    draw.text((PANEL_WIDTH // 2, 625), data, font=get_font(32), fill=(50, 50, 50), anchor="mm")

    return img


# ========== パターン10: タイムライン型 ==========
def pattern_10_timeline(year: str, event: str, description: str) -> Image.Image:
    """タイムライン型カード"""
    img = Image.new('RGB', (PANEL_WIDTH, PANEL_HEIGHT), (245, 248, 250))
    draw = ImageDraw.Draw(img)

    # 上部: 年代
    draw.rectangle([0, 0, PANEL_WIDTH, 120], fill=(50, 50, 80))
    draw.text((PANEL_WIDTH // 2, 60), year, font=get_font(60), fill=(255, 220, 100), anchor="mm")

    # タイムラインライン
    draw.rectangle([PANEL_WIDTH // 2 - 3, 120, PANEL_WIDTH // 2 + 3, 200], fill=(100, 100, 150))
    draw.ellipse([PANEL_WIDTH // 2 - 15, 185, PANEL_WIDTH // 2 + 15, 215], fill=(100, 100, 150))

    # 写真
    photo = create_dummy_photo(340, 350, "sepia")
    img.paste(photo, ((PANEL_WIDTH - 340) // 2, 240))

    # 出来事
    draw.text((PANEL_WIDTH // 2, 620), event, font=get_font(36), fill=(50, 50, 80), anchor="mm")

    # 説明
    draw.rounded_rectangle([40, 680, PANEL_WIDTH - 40, 820], radius=10, fill=(255, 255, 255))
    # 複数行対応（簡易）
    lines = [description[i:i+15] for i in range(0, len(description), 15)]
    y = 720
    for line in lines[:3]:
        draw.text((PANEL_WIDTH // 2, y), line, font=get_font(26), fill=(80, 80, 80), anchor="mm")
        y += 35

    return img


def generate_strip(pattern_func, panel_count: int = 4, **kwargs_list) -> Image.Image:
    """パターンからストリップ（横並び）を生成"""
    import inspect
    func_params = set(inspect.signature(pattern_func).parameters.keys())

    panels = []
    for i in range(panel_count):
        kwargs = {k: v[i] if isinstance(v, list) else v for k, v in kwargs_list.items()}
        # rank/numは関数が期待するパラメータのみ追加
        if 'rank' in func_params and 'rank' not in kwargs:
            kwargs['rank'] = i + 1
        if 'num' in func_params and 'num' not in kwargs:
            kwargs['num'] = i + 1
        panel = pattern_func(**kwargs)
        panels.append(panel)

    # スペーサー込みで結合
    total_width = PANEL_WIDTH * panel_count + SPACER_WIDTH * (panel_count - 1)
    strip = Image.new('RGB', (total_width, PANEL_HEIGHT), (0, 0, 0))  # 黒=仕切り

    x = 0
    for panel in panels:
        strip.paste(panel, (x, 0))
        x += PANEL_WIDTH + SPACER_WIDTH

    return strip


def main():
    """全10パターンを生成"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("横スクロール動画レイアウト 10パターン生成")
    print("=" * 60)

    patterns = [
        ("01_simple_person", pattern_01_simple_person, {
            "name": ["田中一郎", "山田花子", "佐藤太郎", "鈴木次郎"],
            "value": ["85歳", "72歳", "91歳", "68歳"]
        }),
        ("02_prefecture_data", pattern_02_prefecture_data, {
            "prefecture": ["東京都", "大阪府", "愛知県", "福岡県"],
            "photo_desc": ["都市風景"] * 4,
            "value": ["1,396万人", "882万人", "754万人", "513万人"],
            "change": ["+2.3%", "-1.5%", "+0.8%", "-0.3%"],
            "desc": ["首都圏の中心", "関西の中心都市", "中部地方の中心", "九州最大都市"]
        }),
        ("03_ranking_detail", pattern_03_ranking_detail, {
            "name": ["石原裕次郎", "渥美清", "美空ひばり", "三船敏郎"],
            "details": [
                [("生年", "1934年"), ("没年", "1987年"), ("職業", "俳優・歌手")],
                [("生年", "1928年"), ("没年", "1996年"), ("職業", "俳優")],
                [("生年", "1937年"), ("没年", "1989年"), ("職業", "歌手")],
                [("生年", "1920年"), ("没年", "1997年"), ("職業", "俳優")]
            ]
        }),
        ("04_number_focused", pattern_04_number_focused, {
            "name": ["新潟県", "長野県", "北海道", "沖縄県"],
            "main_value": ["-2.53%", "-1.87%", "-1.45%", "+0.32%"],
            "sub_data": [
                [("転入者数", "21,236人"), ("転出者数", "25,773人")],
                [("転入者数", "18,542人"), ("転出者数", "21,876人")],
                [("転入者数", "45,123人"), ("転出者数", "48,765人")],
                [("転入者数", "32,456人"), ("転出者数", "31,234人")]
            ]
        }),
        ("05_historical", pattern_05_historical, {
            "num": [1, 2, 3, 4],
            "name": ["緒川五郎次", "丸山権太左衛門", "谷風梶之助", "雷電為右衛門"],
            "period": ["1703年-1765年", "1713年-1749年", "1750年-1795年", "1767年-1825年"],
            "achievement": ["優勝回数: 不明", "優勝回数: 不明", "優勝回数: 21回", "優勝回数: 28回"]
        }),
        ("06_death_info", pattern_06_death_info, {
            "name": ["羽黒山光司", "双葉山定次", "前田山英五郎", "吉葉山潤之輔"],
            "age": ["55歳", "56歳", "57歳3ヶ月", "57歳7ヶ月"],
            "birthdate": ["昭和38年8月12日", "明治45年2月9日", "大正3年5月4日", "大正9年4月3日"],
            "cause": ["慢性腎不全", "激症肝炎", "肝臓がん", "腎不全"]
        }),
        ("07_politician", pattern_07_politician, {
            "affiliation": ["鳥取県", "秋田県", "千葉県", "神奈川県"],
            "count": ["1人", "1人", "1人", "1人"],
            "name": ["石破茂", "菅義偉", "野田佳彦", "小泉純一郎"]
        }),
        ("08_athlete", pattern_08_athlete, {
            "team": ["読売ジャイアンツ", "阪神タイガース", "中日ドラゴンズ", "広島カープ"],
            "stats": ["打率.334 / 本塁打45", "打率.312 / 本塁打38", "打率.298 / 本塁打32", "打率.321 / 本塁打28"],
            "record": ["MVP 3回", "首位打者 2回", "盗塁王 1回", "新人王"]
        }),
        ("09_comparison", pattern_09_comparison, {
            "category": ["東西対決", "新旧比較", "男女差", "世代間"],
            "item1": [("東京", "1396万"), ("昭和", "3500万"), ("男性", "52%"), ("20代", "15%")],
            "item2": [("大阪", "882万"), ("令和", "1億2千万"), ("女性", "48%"), ("60代", "28%")],
            "data": ["人口差: 514万人", "人口増加: 約3倍", "差: 4ポイント", "差: 13ポイント"]
        }),
        ("10_timeline", pattern_10_timeline, {
            "year": ["1945年", "1964年", "1989年", "2020年"],
            "event": ["終戦", "東京オリンピック", "平成元年", "コロナ禍"],
            "description": ["第二次世界大戦が終結し、日本は新たな時代へ", "アジア初のオリンピックが東京で開催された", "昭和天皇崩御、新元号「平成」がスタート", "新型コロナウイルスが世界的に流行"]
        }),
    ]

    for name, func, kwargs in patterns:
        print(f"\n📝 {name}")
        strip = generate_strip(func, **kwargs)
        output_path = OUTPUT_DIR / f"{name}.png"
        strip.save(output_path, quality=95)
        print(f"   ✓ 保存: {output_path}")

    print(f"\n✅ 完了！出力: {OUTPUT_DIR}")
    os.system(f'open "{OUTPUT_DIR}"')


if __name__ == "__main__":
    main()
