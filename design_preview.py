#!/usr/bin/env python3
"""
デザイン確認用ダミー動画生成
- APIは使用しない
- 背景画像 + ダミー字幕
- 無音30秒動画
"""

import subprocess
import tempfile
from pathlib import Path

# ===== 設定 =====
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
DURATION = 30  # 秒

# 背景画像（Google Drive ID）
BACKGROUND_IMAGE_ID = "1ywnGZHMZWavnus1-fPD1MVI3fWxSrAIp"

# ダミー台本
DUMMY_SCRIPT = [
    {"speaker": "カツミ", "text": "年金のお話、今日もお届けしますね"},
    {"speaker": "ヒロシ", "text": "おー、今日は何の話？"},
    {"speaker": "カツミ", "text": "繰り下げ受給について解説しますよ"},
    {"speaker": "ヒロシ", "text": "それって得なの？"},
    {"speaker": "カツミ", "text": "最大42%増えるんですよ"},
    {"speaker": "ヒロシ", "text": "マジで！？"},
]


def download_background():
    """Google Driveから背景画像をダウンロード"""
    print("[1/4] 背景画像をダウンロード中...")

    url = f"https://drive.google.com/uc?export=download&id={BACKGROUND_IMAGE_ID}"
    output_path = Path(tempfile.gettempdir()) / "bg_preview.png"

    cmd = ['curl', '-L', '-o', str(output_path), url]
    result = subprocess.run(cmd, capture_output=True)

    if output_path.exists() and output_path.stat().st_size > 1000:
        print(f"  ✓ ダウンロード完了: {output_path}")
        return str(output_path)
    else:
        # フォールバック：単色背景を生成
        print("  ⚠ ダウンロード失敗、単色背景を生成")
        return create_fallback_background()


def create_fallback_background():
    """フォールバック用の単色背景を生成"""
    output_path = Path(tempfile.gettempdir()) / "bg_fallback.png"

    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi',
        '-i', f'color=c=#2C3E50:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d=1',
        '-frames:v', '1',
        str(output_path)
    ]
    subprocess.run(cmd, capture_output=True)
    print(f"  ✓ フォールバック背景生成: {output_path}")
    return str(output_path)


def generate_subtitles(output_path: str):
    """ASS字幕を生成"""
    print("[2/4] 字幕ファイルを生成中...")

    time_per_line = DURATION / len(DUMMY_SCRIPT)

    header = f"""[Script Info]
Title: Design Preview
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hiroshi,Noto Sans CJK JP,100,&H0000FFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,2,50,50,400,1
Style: Katsumi,Noto Sans CJK JP,100,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,2,50,50,400,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]

    for i, line in enumerate(DUMMY_SCRIPT):
        start_time = i * time_per_line
        end_time = (i + 1) * time_per_line

        start_str = f"0:{int(start_time // 60):02d}:{start_time % 60:05.2f}"
        end_str = f"0:{int(end_time // 60):02d}:{end_time % 60:05.2f}"

        style = "Hiroshi" if line["speaker"] == "ヒロシ" else "Katsumi"
        text = line["text"]

        lines.append(f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{text}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"  ✓ 字幕生成完了: {output_path}")

    # デザイン設定を表示
    print("\n  === 現在のデザイン設定 ===")
    print("  フォント: Noto Sans CJK JP")
    print("  フォントサイズ: 100pt")
    print("  カツミ: 白文字 (&H00FFFFFF)")
    print("  ヒロシ: 黄色文字 (&H0000FFFF)")
    print("  縁取り: 黒 4px")
    print("  影: 2px")
    print("  字幕位置: 下から400px (MarginV=400)")
    print("  ===========================\n")


def generate_silent_audio(output_path: str):
    """無音オーディオを生成"""
    print("[3/4] 無音オーディオを生成中...")

    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi',
        '-i', f'anullsrc=r=44100:cl=stereo',
        '-t', str(DURATION),
        '-c:a', 'aac',
        '-b:a', '128k',
        output_path
    ]
    subprocess.run(cmd, capture_output=True)
    print(f"  ✓ 無音オーディオ生成完了")


def generate_video(bg_path: str, subtitle_path: str, audio_path: str, output_path: str):
    """動画を生成"""
    print("[4/4] 動画を生成中...")

    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', bg_path,
        '-i', audio_path,
        '-vf', f'scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},ass={subtitle_path}',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k',
        '-shortest',
        '-t', str(DURATION),
        '-pix_fmt', 'yuv420p',
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if Path(output_path).exists():
        size_mb = Path(output_path).stat().st_size / (1024 * 1024)
        print(f"  ✓ 動画生成完了: {output_path}")
        print(f"  ✓ ファイルサイズ: {size_mb:.2f} MB")
    else:
        print(f"  ✗ 動画生成失敗")
        print(f"  stderr: {result.stderr}")


def main():
    print("=" * 50)
    print("デザイン確認用ダミー動画生成")
    print("=" * 50)

    # 出力先
    output_dir = Path("/Users/user/jinsei-soudan")
    output_video = output_dir / "design_preview.mp4"

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        subtitle_path = temp_path / "subtitles.ass"
        audio_path = temp_path / "silent.m4a"

        # 1. 背景画像
        bg_path = download_background()

        # 2. 字幕生成
        generate_subtitles(str(subtitle_path))

        # 3. 無音オーディオ
        generate_silent_audio(str(audio_path))

        # 4. 動画生成
        generate_video(bg_path, str(subtitle_path), str(audio_path), str(output_video))

    print("\n" + "=" * 50)
    print(f"完了！ダウンロード: {output_video}")
    print("=" * 50)


if __name__ == "__main__":
    main()
