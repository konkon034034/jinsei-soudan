#!/usr/bin/env python3
"""
美空ひばり売上ベスト3 動画生成（シンプル版）
"""

import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

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

OUTPUT = Path(__file__).parent.parent / 'output' / 'hibari_video'
OUTPUT.mkdir(parents=True, exist_ok=True)

# 台本
SCENES = [
    ("美空ひばり\n売上ベスト3", 3, "op"),
    ("昭和を代表する歌姫\n美空ひばりさんの\n売れた曲ベスト3を\nご紹介します", 5, "op"),
    ("第3位", 2, "3"),
    ("「悲しい酒」", 2, "3"),
    ("1966年発売\n売上 155万枚", 3, "3"),
    ("お酒を飲みながら\n別れた人を思う\n切ない歌", 5, "3"),
    ("第2位", 2, "2"),
    ("「柔」", 2, "2"),
    ("1964年発売\n売上 195万枚", 3, "2"),
    ("柔道をテーマにした\n力強い一曲", 5, "2"),
    ("第1位", 2, "1"),
    ("「川の流れのように」", 2, "1"),
    ("1989年発売\n売上 205万枚", 3, "1"),
    ("美空ひばり最後の\nシングル曲\n今も愛される名曲です", 5, "1"),
    ("美空ひばりさんの歌声は\n今も私たちの心に\n響き続けています", 4, "ed"),
    ("ご視聴ありがとう\nございました", 3, "ed"),
]


def create_image(text, bg_type, output_path, fontsize=72):
    """テキスト付き画像を生成"""
    width, height = 1920, 1080

    # 背景色/画像
    if bg_type == "op":
        bg = Image.new('RGB', (width, height), (100, 50, 30))
    elif bg_type == "ed":
        bg = Image.new('RGB', (width, height), (30, 30, 50))
    else:
        jacket_path = OUTPUT / f"jacket_{bg_type}.jpg"
        if jacket_path.exists():
            bg = Image.open(jacket_path).convert('RGB').resize((width, height), Image.Resampling.LANCZOS)
            # 暗くする
            from PIL import ImageEnhance
            enhancer = ImageEnhance.Brightness(bg)
            bg = enhancer.enhance(0.5)
        else:
            bg = Image.new('RGB', (width, height), (50, 30, 20))

    draw = ImageDraw.Draw(bg)

    # フォント
    try:
        font = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", fontsize)
    except:
        font = ImageFont.load_default()

    # テキスト描画（中央配置）
    lines = text.split('\n')
    line_height = fontsize + 20
    total_height = len(lines) * line_height
    y_start = (height - total_height) // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        y = y_start + i * line_height

        # 黒縁取り
        for dx in [-4, -2, 0, 2, 4]:
            for dy in [-4, -2, 0, 2, 4]:
                if dx != 0 or dy != 0:
                    draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0))
        # 白文字
        draw.text((x, y), line, font=font, fill=(255, 255, 255))

    bg.save(output_path)


def main():
    print("=" * 60)
    print("美空ひばり 売上ベスト3 動画生成")
    print("=" * 60)

    # 1. 台本保存
    print("\n[1/4] 台本を保存中...")
    script_path = OUTPUT / "script.txt"
    total = 0
    with open(script_path, 'w', encoding='utf-8') as f:
        for text, dur, _ in SCENES:
            f.write(f"[{dur}秒] {text.replace(chr(10), ' ')}\n")
            total += dur
    print(f"  合計: 約{total}秒")

    # 2. 音声生成
    print("\n[2/4] 音声を生成中...")
    from gtts import gTTS
    voice_files = []
    for i, (text, dur, _) in enumerate(SCENES):
        voice_path = OUTPUT / f"voice_{i:02d}.mp3"
        clean_text = text.replace('\n', '')
        if len(clean_text) > 3:
            print(f"  {i}: {clean_text[:20]}...")
            tts = gTTS(text=clean_text, lang='ja')
            tts.save(str(voice_path))
            voice_files.append(voice_path)
        else:
            voice_files.append(None)

    # 3. シーン画像生成
    print("\n[3/4] シーン画像を生成中...")
    img_files = []
    for i, (text, dur, bg_type) in enumerate(SCENES):
        img_path = OUTPUT / f"frame_{i:02d}.png"
        print(f"  {i}: {text.split(chr(10))[0][:15]}...")
        create_image(text, bg_type, img_path)
        img_files.append(img_path)

    # 4. 動画生成
    print("\n[4/4] 動画を生成中...")
    scene_files = []

    for i, (text, dur, _) in enumerate(SCENES):
        scene_path = OUTPUT / f"scene_{i:02d}.mp4"
        img_path = img_files[i]
        voice_path = voice_files[i]

        cmd = ['ffmpeg', '-y', '-loop', '1', '-i', str(img_path)]

        if voice_path and voice_path.exists():
            cmd.extend(['-i', str(voice_path)])
            cmd.extend(['-t', str(dur), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                       '-c:a', 'aac', '-shortest', '-r', '24'])
        else:
            cmd.extend(['-t', str(dur), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                       '-r', '24'])

        cmd.append(str(scene_path))

        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0:
            scene_files.append(scene_path)
            print(f"  シーン{i}: ✓")
        else:
            print(f"  シーン{i}: ✗")
            print(f"    Error: {result.stderr.decode()[-200:]}")

    # 結合
    print("\n  動画を結合中...")
    list_path = OUTPUT / "filelist.txt"
    with open(list_path, 'w') as f:
        for scene in scene_files:
            f.write(f"file '{scene}'\n")

    output_path = OUTPUT / "hibari_best3.mp4"
    result = subprocess.run([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
        '-i', str(list_path), '-c', 'copy', str(output_path)
    ], capture_output=True)

    if result.returncode == 0 and output_path.exists():
        # 動画情報
        probe = subprocess.run([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(output_path)
        ], capture_output=True, text=True)
        duration = float(probe.stdout.strip()) if probe.stdout.strip() else 0

        print("\n" + "=" * 60)
        print("完了!")
        print("=" * 60)
        print(f"\n🎬 動画: {output_path}")
        print(f"⏱️  長さ: {int(duration)}秒")
        print(f"📝 台本: {script_path}")
    else:
        print("\n❌ 動画生成に失敗しました")
        print(result.stderr.decode()[-500:])


if __name__ == '__main__':
    main()
