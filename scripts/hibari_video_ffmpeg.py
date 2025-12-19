#!/usr/bin/env python3
"""
美空ひばり売上ベスト3 動画生成スクリプト（ffmpeg版）
- 1分程度
- 高齢女性向け大きめ字幕
- 女性音声読み上げ
"""

import os
import sys
import json
import subprocess
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

GOOGLE_CSE_API_KEY = os.environ.get('GOOGLE_CSE_API_KEY')
GOOGLE_CSE_ID = os.environ.get('GOOGLE_CSE_ID')

# === 台本データ ===
SONGS = [
    {"rank": 3, "title": "悲しい酒", "year": 1966, "sales": "155万枚",
     "desc": "お酒を飲みながら別れた人を思う切ない歌。美空ひばりの情感あふれる歌声が胸に染みます。"},
    {"rank": 2, "title": "柔", "year": 1964, "sales": "195万枚",
     "desc": "柔道をテーマにした力強い一曲。「勝つと思うな、思えば負けよ」の歌詞が心に響きます。"},
    {"rank": 1, "title": "川の流れのように", "year": 1989, "sales": "205万枚",
     "desc": "美空ひばり最後のシングル曲。人生を川の流れに例えた名曲で、今も多くの方に愛されています。"},
]

SCRIPT = [
    {"text": "美空ひばり 売上ベスト3", "duration": 3, "bg": "op"},
    {"text": "昭和を代表する歌姫、美空ひばりさんの\n売れた曲ベスト3をご紹介します", "duration": 5, "bg": "op"},
]

for song in SONGS:
    SCRIPT.append({"text": f"第{song['rank']}位", "duration": 2, "bg": f"jacket_{song['rank']}"})
    SCRIPT.append({"text": f"「{song['title']}」", "duration": 2, "bg": f"jacket_{song['rank']}"})
    SCRIPT.append({"text": f"{song['year']}年発売\n売上 {song['sales']}", "duration": 3, "bg": f"jacket_{song['rank']}"})
    SCRIPT.append({"text": song['desc'], "duration": 6, "bg": f"jacket_{song['rank']}"})

SCRIPT.append({"text": "美空ひばりさんの歌声は\n今も私たちの心に響き続けています", "duration": 4, "bg": "ed"})
SCRIPT.append({"text": "ご視聴ありがとうございました", "duration": 3, "bg": "ed"})


# === 画像ダウンロード ===
def download_image(query, filepath):
    """Google CSEで画像検索してダウンロード"""
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': GOOGLE_CSE_API_KEY,
        'cx': GOOGLE_CSE_ID,
        'q': query,
        'searchType': 'image',
        'num': 1,
        'imgSize': 'large'
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if 'items' in data:
                img_url = data['items'][0]['link']
                img_resp = requests.get(img_url, timeout=15)
                if img_resp.status_code == 200:
                    with open(filepath, 'wb') as f:
                        f.write(img_resp.content)
                    return True
    except Exception as e:
        print(f"    エラー: {e}")
    return False


# === OP/ED画像生成 ===
def create_title_image(text, subtitle, filepath, bg_color="brown"):
    """PILでタイトル画像生成"""
    from PIL import Image, ImageDraw, ImageFont

    width, height = 1920, 1080
    colors = {"brown": (100, 50, 30), "dark": (30, 30, 50)}
    bg = colors.get(bg_color, (100, 50, 30))

    img = Image.new('RGB', (width, height), bg)
    draw = ImageDraw.Draw(img)

    # グラデーション風
    for i in range(height):
        r = bg[0] + int(30 * (i / height))
        g = bg[1] + int(20 * (i / height))
        b = bg[2] + int(20 * (i / height))
        draw.line([(0, i), (width, i)], fill=(r, g, b))

    try:
        font_large = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 140)
        font_medium = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", 60)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()

    # メインテキスト
    draw.text((width//2, height//2 - 80), text, font=font_large, fill=(255, 255, 255), anchor="mm")
    # サブテキスト
    draw.text((width//2, height//2 + 80), subtitle, font=font_medium, fill=(255, 215, 0), anchor="mm")

    img.save(filepath)


# === 音声生成 ===
def generate_voice(text, filepath):
    """gTTSで音声生成"""
    from gtts import gTTS
    tts = gTTS(text=text.replace('\n', ''), lang='ja')
    tts.save(str(filepath))


# === 動画シーン生成（ffmpeg） ===
def create_scene(bg_image, text, duration, output_path, voice_path=None):
    """1シーンの動画を生成"""
    from PIL import Image, ImageDraw, ImageFont

    # 背景画像を読み込んでテキストを直接描画
    try:
        bg = Image.open(bg_image).convert('RGB')
        bg = bg.resize((1920, 1080), Image.Resampling.LANCZOS)
    except:
        bg = Image.new('RGB', (1920, 1080), (50, 30, 20))

    draw = ImageDraw.Draw(bg)

    # フォント（大きめ）
    try:
        font = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 72)
    except:
        font = ImageFont.load_default()

    # テキスト描画（下部中央、白文字に黒縁）
    lines = text.split('\n')
    y_offset = 1080 - 180 - (len(lines) - 1) * 80

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (1920 - text_width) // 2

        # 縁取り
        for dx in [-3, 0, 3]:
            for dy in [-3, 0, 3]:
                draw.text((x + dx, y_offset + dy), line, font=font, fill=(0, 0, 0))
        # 本体
        draw.text((x, y_offset), line, font=font, fill=(255, 255, 255))
        y_offset += 80

    # 一時画像保存
    temp_img = output_path.with_suffix('.png')
    bg.save(temp_img)

    # ffmpegで動画化
    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', str(temp_img),
        '-t', str(duration),
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-r', '24'
    ]

    if voice_path and Path(voice_path).exists():
        cmd.extend(['-i', str(voice_path), '-c:a', 'aac', '-shortest'])

    cmd.append(str(output_path))

    result = subprocess.run(cmd, capture_output=True)

    # 一時ファイル削除
    if temp_img.exists():
        temp_img.unlink()

    return result.returncode == 0


# === メイン ===
def main():
    print("=" * 60)
    print("美空ひばり 売上ベスト3 動画生成")
    print("=" * 60)

    # 1. 台本保存
    print("\n[1/5] 台本を保存中...")
    script_path = OUTPUT_DIR / "script.txt"
    with open(script_path, 'w', encoding='utf-8') as f:
        total = 0
        for item in SCRIPT:
            f.write(f"[{item['duration']}秒] {item['text']}\n\n")
            total += item['duration']
    print(f"  保存完了: {script_path}")
    print(f"  合計時間: 約{total}秒")

    # 2. 画像準備
    print("\n[2/5] 画像を準備中...")

    # OP画像
    op_path = OUTPUT_DIR / "op.png"
    create_title_image("美空ひばり", "売上ベスト3", op_path)
    print(f"  OP画像: ✓")

    # ED画像
    ed_path = OUTPUT_DIR / "ed.png"
    create_title_image("ご視聴ありがとう\nございました", "美空ひばりの歌声は永遠に", ed_path)
    print(f"  ED画像: ✓")

    # ジャケット画像
    for song in SONGS:
        jacket_path = OUTPUT_DIR / f"jacket_{song['rank']}.jpg"
        if not jacket_path.exists():
            print(f"  {song['title']}のジャケット...", end=" ")
            if download_image(f"美空ひばり {song['title']} ジャケット", jacket_path):
                print("✓")
            else:
                # ダウンロード失敗時はOPをコピー
                import shutil
                shutil.copy(op_path, jacket_path)
                print("(デフォルト使用)")

    # 3. 音声生成
    print("\n[3/5] 音声を生成中...")
    voice_files = []
    for i, item in enumerate(SCRIPT):
        voice_path = OUTPUT_DIR / f"voice_{i:02d}.mp3"
        if item['text'] and len(item['text']) > 5:
            print(f"  音声{i}: {item['text'][:15]}...")
            generate_voice(item['text'], voice_path)
            voice_files.append(voice_path)
        else:
            voice_files.append(None)

    # 4. シーン動画生成
    print("\n[4/5] シーン動画を生成中...")
    scene_files = []
    for i, item in enumerate(SCRIPT):
        scene_path = OUTPUT_DIR / f"scene_{i:02d}.mp4"
        print(f"  シーン{i}: {item['text'][:15]}...")

        # 背景画像を決定
        if item['bg'] == 'op':
            bg = op_path
        elif item['bg'] == 'ed':
            bg = ed_path
        else:
            bg = OUTPUT_DIR / f"{item['bg']}.jpg"
            if not bg.exists():
                bg = op_path

        create_scene(bg, item['text'], item['duration'], scene_path, voice_files[i])
        scene_files.append(scene_path)

    # 5. 結合
    print("\n[5/5] 動画を結合中...")

    # ファイルリスト作成
    list_path = OUTPUT_DIR / "filelist.txt"
    with open(list_path, 'w') as f:
        for scene in scene_files:
            f.write(f"file '{scene}'\n")

    # 結合
    output_path = OUTPUT_DIR / "hibari_best3.mp4"
    subprocess.run([
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0',
        '-i', str(list_path),
        '-c', 'copy',
        str(output_path)
    ], capture_output=True)

    print("\n" + "=" * 60)
    print("完了!")
    print("=" * 60)
    print(f"\n🎬 動画: {output_path}")
    print(f"📝 台本: {script_path}")


if __name__ == '__main__':
    main()
