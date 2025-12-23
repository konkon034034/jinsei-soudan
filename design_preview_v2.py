#!/usr/bin/env python3
"""
デザイン確認用ダミー動画生成 v2
- 新レイアウト：上部トピック + 中央会話
- ポップアップアニメーション
- カツミ=黄色、ヒロシ=赤、トピック=白
"""

import subprocess
import tempfile
from pathlib import Path

# ===== 設定 =====
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
DURATION = 30  # 秒

# 背景画像（Google Drive ID）
BACKGROUND_IMAGE_ID = "1runaL5Mpn051ZLcNQ0KJvluz9DJQpeyq"

# トピック
TOPIC = "繰り下げ受給"

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

    output_path = Path(tempfile.gettempdir()) / "bg_preview_v2.png"

    # Google Drive直接ダウンロードURL
    url = f"https://drive.google.com/uc?export=download&id={BACKGROUND_IMAGE_ID}"

    cmd = ['curl', '-L', '-o', str(output_path), url]
    result = subprocess.run(cmd, capture_output=True)

    if output_path.exists() and output_path.stat().st_size > 1000:
        print(f"  ✓ ダウンロード完了: {output_path}")
        return str(output_path)
    else:
        print("  ⚠ ダウンロード失敗、単色背景を生成")
        return create_fallback_background()


def create_fallback_background():
    """フォールバック用の単色背景を生成"""
    output_path = Path(tempfile.gettempdir()) / "bg_fallback_v2.png"

    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi',
        '-i', f'color=c=#1a1a2e:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d=1',
        '-frames:v', '1',
        str(output_path)
    ]
    subprocess.run(cmd, capture_output=True)
    print(f"  ✓ フォールバック背景生成: {output_path}")
    return str(output_path)


def generate_subtitles(output_path: str):
    """ASS字幕を生成（ポップアップアニメーション付き）"""
    print("[2/4] 字幕ファイルを生成中...")

    time_per_line = DURATION / len(DUMMY_SCRIPT)

    # ASS形式のカラーコード（BGR形式）
    # 黄色: &H00FFFF（BGR: 00FFFF = Yellow）
    # 赤色: &H0000FF（BGR: 0000FF = Red）
    # 白色: &H00FFFFFF

    header = f"""[Script Info]
Title: Design Preview v2
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Topic,Hiragino Sans,90,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,6,3,8,50,50,120,1
Style: Katsumi,Hiragino Sans,80,&H0000FFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,6,3,5,50,50,700,1
Style: Hiroshi,Hiragino Sans,80,&H005050FF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,6,3,5,50,50,700,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]

    # トピック（常時表示、ポップアップで登場）
    # ポップアップ効果: \\t(0,200,\\fscx120\\fscy120)\\t(200,400,\\fscx100\\fscy100)
    topic_popup = "{\\fscx50\\fscy50\\t(0,200,\\fscx110\\fscy110)\\t(200,400,\\fscx100\\fscy100)}"
    lines.append(f"Dialogue: 0,0:00:00.00,0:00:{DURATION:05.2f},Topic,,0,0,0,,{topic_popup}【{TOPIC}】")

    # 各セリフ（ポップアップアニメーション付き）
    for i, line in enumerate(DUMMY_SCRIPT):
        start_time = i * time_per_line
        end_time = (i + 1) * time_per_line

        start_str = f"0:{int(start_time // 60):02d}:{start_time % 60:05.2f}"
        end_str = f"0:{int(end_time // 60):02d}:{end_time % 60:05.2f}"

        style = "Hiroshi" if line["speaker"] == "ヒロシ" else "Katsumi"
        text = line["text"]

        # ポップアップ効果
        popup_effect = "{\\fscx50\\fscy50\\t(0,150,\\fscx115\\fscy115)\\t(150,300,\\fscx100\\fscy100)}"

        lines.append(f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{popup_effect}{text}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"  ✓ 字幕生成完了: {output_path}")

    # デザイン設定を表示
    print("\n  === 新デザイン設定 ===")
    print("  フォント: Hiragino Sans (太ゴシック)")
    print("  トピック: 白文字 90pt、上部 (MarginV=120)")
    print("  カツミ: 黄色文字 80pt")
    print("  ヒロシ: 赤文字 80pt")
    print("  会話位置: 中央〜やや下 (MarginV=700)")
    print("  縁取り: 黒 6px（太め）")
    print("  影: 3px")
    print("  アニメ: ポップアップ効果")
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
        '-vf', f'scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},ass={subtitle_path}',
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
    print("デザイン確認用ダミー動画生成 v2")
    print("=" * 50)

    # 出力先
    output_dir = Path("/Users/user/jinsei-soudan")
    output_video = output_dir / "design_preview_v2.mp4"

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
