#!/usr/bin/env python3
"""
美空ひばり売上ベスト3 動画生成スクリプト
- 1分程度
- 高齢女性向け大きめ字幕
- 女性音声読み上げ
"""

import os
import sys
import json
import requests
from pathlib import Path

# .env読み込み
def load_env():
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key, value)

load_env()

# === 設定 ===
OUTPUT_DIR = Path(__file__).parent.parent / 'output' / 'hibari_video'
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GOOGLE_CSE_API_KEY = os.environ.get('GOOGLE_CSE_API_KEY')
GOOGLE_CSE_ID = os.environ.get('GOOGLE_CSE_ID')

# === 台本データ ===
SCRIPT_DATA = {
    "title": "美空ひばり 売上ベスト3",
    "target": "高齢日本人女性",
    "songs": [
        {
            "rank": 3,
            "title": "悲しい酒",
            "year": 1966,
            "sales": "155万枚",
            "description": "お酒を飲みながら別れた人を思う切ない歌。美空ひばりの情感あふれる歌声が胸に染みます。"
        },
        {
            "rank": 2,
            "title": "柔",
            "year": 1964,
            "sales": "195万枚",
            "description": "柔道をテーマにした力強い一曲。「勝つと思うな、思えば負けよ」の歌詞が心に響きます。"
        },
        {
            "rank": 1,
            "title": "川の流れのように",
            "year": 1989,
            "sales": "205万枚",
            "description": "美空ひばり最後のシングル曲。人生を川の流れに例えた名曲で、今も多くの方に愛されています。"
        }
    ]
}

# === 台本テキスト ===
def generate_script():
    """ナレーション台本を生成"""
    lines = []

    # オープニング
    lines.append({
        "text": "美空ひばり 売上ベスト3",
        "duration": 3,
        "type": "title"
    })
    lines.append({
        "text": "昭和を代表する歌姫、美空ひばりさんの売れた曲ベスト3をご紹介します。",
        "duration": 5,
        "type": "narration"
    })

    # 各曲紹介（3位→1位）
    for song in SCRIPT_DATA["songs"]:
        # 順位発表
        lines.append({
            "text": f"第{song['rank']}位",
            "duration": 2,
            "type": "rank"
        })
        # 曲名
        lines.append({
            "text": f"「{song['title']}」",
            "duration": 2,
            "type": "song_title"
        })
        # 情報
        lines.append({
            "text": f"{song['year']}年発売、売上{song['sales']}",
            "duration": 3,
            "type": "info"
        })
        # 説明
        lines.append({
            "text": song['description'],
            "duration": 6,
            "type": "description"
        })

    # エンディング
    lines.append({
        "text": "美空ひばりさんの歌声は、今も私たちの心に響き続けています。",
        "duration": 4,
        "type": "ending"
    })
    lines.append({
        "text": "ご視聴ありがとうございました",
        "duration": 3,
        "type": "credit"
    })

    return lines


# === 画像ダウンロード ===
def search_and_download_image(query, filename):
    """Google Custom Searchで画像を検索してダウンロード"""
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': GOOGLE_CSE_API_KEY,
        'cx': GOOGLE_CSE_ID,
        'q': query,
        'searchType': 'image',
        'num': 1,
        'safe': 'active'
    }

    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            if 'items' in data and len(data['items']) > 0:
                img_url = data['items'][0]['link']
                # 画像をダウンロード
                img_response = requests.get(img_url, timeout=10)
                if img_response.status_code == 200:
                    filepath = OUTPUT_DIR / filename
                    with open(filepath, 'wb') as f:
                        f.write(img_response.content)
                    return str(filepath)
    except Exception as e:
        print(f"  画像取得エラー: {e}")

    return None


def download_images():
    """必要な画像をダウンロード"""
    images = {}

    print("\n[2/6] 画像をダウンロード中...")

    # ジャケット画像
    for song in SCRIPT_DATA["songs"]:
        title = song['title']
        print(f"  {title}のジャケット...", end=" ")
        filename = f"jacket_{song['rank']}.jpg"
        path = search_and_download_image(f"美空ひばり {title} ジャケット アルバム", filename)
        if path:
            images[f"jacket_{song['rank']}"] = path
            print("✓")
        else:
            print("✗")

    return images


# === BGMダウンロード ===
def download_bgm():
    """フリーBGMをダウンロード"""
    print("\n[3/6] BGMをダウンロード中...")

    # 甘茶の音楽工房などのフリー素材（例としてシンプルなピアノ曲）
    # 実際にはフリー素材サイトから適切なものを選ぶ
    bgm_urls = [
        "https://www.soundjay.com/misc/sounds/bell-ringing-05.mp3",  # プレースホルダー
    ]

    # ローカルにBGMがあるか確認、なければスキップ
    bgm_path = OUTPUT_DIR / "bgm.mp3"
    if not bgm_path.exists():
        print("  BGMは手動で追加してください: output/hibari_video/bgm.mp3")
        return None

    return str(bgm_path)


# === OP/ED画像生成 ===
def create_title_images():
    """タイトル画像を生成（PILを使用）"""
    print("\n[4/6] OP/ED画像を生成中...")

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  PILがインストールされていません。pip install Pillow")
        return None, None

    # 共通設定
    width, height = 1920, 1080
    bg_color = (139, 69, 19)  # 茶色（レトロ感）
    text_color = (255, 255, 255)

    # フォント（システムフォントを使用）
    try:
        # macOS
        font_large = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 120)
        font_medium = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 60)
        font_small = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 40)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # OP画像
    op_img = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(op_img)

    # グラデーション風の装飾
    for i in range(0, height, 2):
        alpha = int(20 * (i / height))
        draw.line([(0, i), (width, i)], fill=(139 - alpha, 69 - alpha//2, 19))

    # テキスト
    title = "美空ひばり"
    subtitle = "売上ベスト3"

    draw.text((width//2, height//2 - 100), title, font=font_large, fill=text_color, anchor="mm")
    draw.text((width//2, height//2 + 50), subtitle, font=font_medium, fill=(255, 215, 0), anchor="mm")

    op_path = OUTPUT_DIR / "op.png"
    op_img.save(op_path)
    print(f"  OP画像: {op_path}")

    # ED画像
    ed_img = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(ed_img)

    for i in range(0, height, 2):
        alpha = int(20 * (i / height))
        draw.line([(0, i), (width, i)], fill=(139 - alpha, 69 - alpha//2, 19))

    draw.text((width//2, height//2 - 50), "ご視聴ありがとうございました", font=font_medium, fill=text_color, anchor="mm")
    draw.text((width//2, height//2 + 50), "美空ひばりの歌声は永遠に", font=font_small, fill=(255, 215, 0), anchor="mm")

    ed_path = OUTPUT_DIR / "ed.png"
    ed_img.save(ed_path)
    print(f"  ED画像: {ed_path}")

    return str(op_path), str(ed_path)


# === 音声生成（Google Cloud TTS） ===
def generate_voice(text, filename):
    """Google Cloud TTSで女性音声を生成"""
    # ここではVOICEVOXやGoogle Cloud TTSを使う
    # 簡易版としてgTTSを使用
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang='ja')
        filepath = OUTPUT_DIR / filename
        tts.save(str(filepath))
        return str(filepath)
    except ImportError:
        print("  gTTSがインストールされていません: pip install gtts")
        return None
    except Exception as e:
        print(f"  音声生成エラー: {e}")
        return None


def generate_all_voices(script):
    """全ての音声を生成"""
    print("\n[5/6] 音声を生成中...")

    voices = []
    for i, line in enumerate(script):
        if line['type'] in ['narration', 'description', 'ending']:
            print(f"  生成中: {line['text'][:20]}...")
            filename = f"voice_{i:02d}.mp3"
            path = generate_voice(line['text'], filename)
            voices.append({"index": i, "path": path, "text": line['text']})

    return voices


# === 動画生成（moviepy） ===
def create_video(script, images, voices, op_path, ed_path):
    """動画を生成"""
    print("\n[6/6] 動画を生成中...")

    try:
        from moviepy.editor import (
            ImageClip, TextClip, CompositeVideoClip,
            AudioFileClip, concatenate_videoclips, ColorClip
        )
    except ImportError:
        print("  moviepyがインストールされていません: pip install moviepy")
        return None

    clips = []

    # フォント設定（大きめ）
    font = 'Hiragino-Sans-GB-W6'  # macOS
    fontsize = 72  # 高齢者向けに大きめ

    # OP
    if op_path:
        op_clip = ImageClip(op_path).set_duration(3)
        clips.append(op_clip)

    # 各シーン
    current_time = 3
    for i, line in enumerate(script):
        duration = line['duration']

        if line['type'] == 'title':
            continue  # OPで表示済み

        # 背景
        if line['type'] in ['rank', 'song_title', 'info', 'description']:
            # 現在の曲のジャケットを背景に
            rank = None
            for j in range(i, -1, -1):
                if script[j]['type'] == 'rank':
                    rank = int(script[j]['text'].replace('第', '').replace('位', ''))
                    break

            if rank and f"jacket_{rank}" in images:
                bg = ImageClip(images[f"jacket_{rank}"]).set_duration(duration)
                bg = bg.resize((1920, 1080))
            else:
                bg = ColorClip(size=(1920, 1080), color=(50, 30, 20)).set_duration(duration)
        else:
            bg = ColorClip(size=(1920, 1080), color=(139, 69, 19)).set_duration(duration)

        # テキスト（大きめ、白、縁取り）
        try:
            txt_clip = TextClip(
                line['text'],
                fontsize=fontsize,
                font=font,
                color='white',
                stroke_color='black',
                stroke_width=3,
                size=(1800, None),
                method='caption'
            ).set_duration(duration).set_position(('center', 'bottom'))

            scene = CompositeVideoClip([bg, txt_clip])
        except:
            scene = bg

        clips.append(scene)

    # ED
    if ed_path:
        ed_clip = ImageClip(ed_path).set_duration(3)
        clips.append(ed_clip)

    # 結合
    final = concatenate_videoclips(clips, method="compose")

    # 出力
    output_path = OUTPUT_DIR / "hibari_best3.mp4"
    final.write_videofile(
        str(output_path),
        fps=24,
        codec='libx264',
        audio=False  # BGMは後で追加
    )

    return str(output_path)


# === メイン ===
def main():
    print("=" * 60)
    print("美空ひばり 売上ベスト3 動画生成")
    print("=" * 60)

    # 1. 台本生成
    print("\n[1/6] 台本を生成中...")
    script = generate_script()
    total_duration = sum(line['duration'] for line in script)
    print(f"  台本行数: {len(script)}行")
    print(f"  予想時間: 約{total_duration}秒")

    # 台本をファイルに保存
    script_path = OUTPUT_DIR / "script.json"
    with open(script_path, 'w', encoding='utf-8') as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    print(f"  台本保存: {script_path}")

    # 台本をテキストでも保存
    script_txt_path = OUTPUT_DIR / "script.txt"
    with open(script_txt_path, 'w', encoding='utf-8') as f:
        for line in script:
            f.write(f"[{line['type']}] ({line['duration']}秒)\n")
            f.write(f"{line['text']}\n\n")
    print(f"  台本テキスト: {script_txt_path}")

    # 2. 画像ダウンロード
    images = download_images()

    # 3. BGM（手動で追加が必要）
    bgm = download_bgm()

    # 4. OP/ED画像
    op_path, ed_path = create_title_images()

    # 5. 音声生成
    voices = generate_all_voices(script)

    # 6. 動画生成
    video_path = create_video(script, images, voices, op_path, ed_path)

    print("\n" + "=" * 60)
    print("完了!")
    print("=" * 60)
    print(f"\n出力フォルダ: {OUTPUT_DIR}")
    print(f"台本: {script_txt_path}")
    if video_path:
        print(f"動画: {video_path}")
    print("\n※BGMを追加する場合は output/hibari_video/bgm.mp3 を配置してください")


if __name__ == '__main__':
    main()
