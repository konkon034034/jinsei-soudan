#!/usr/bin/env python3
"""
デザイン確認用ダミー動画生成 v4
- トピック: 上部、はみ出さない、最大15文字
- 会話テキスト: 2倍サイズ
- 煽りフレーズ: 下部黒帯に追加
"""

import subprocess
import tempfile
from pathlib import Path

# ===== 設定 =====
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
SQUARE_SIZE = 1080
DURATION = 30

TOP_BAR_HEIGHT = (VIDEO_HEIGHT - SQUARE_SIZE) // 2  # 420px
BOTTOM_BAR_HEIGHT = VIDEO_HEIGHT - SQUARE_SIZE - TOP_BAR_HEIGHT  # 420px

# 背景画像
BACKGROUND_IMAGE_ID = "1runaL5Mpn051ZLcNQ0KJvluz9DJQpeyq"

# トピック（15文字以内）
TOPIC = "繰り下げ受給とは？"

# 煽りフレーズ（15文字以内、1段）
HOOK_PHRASE = "知らないと年間50万円損！"

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
    print("[1/5] 背景画像をダウンロード中...")

    output_path = Path(tempfile.gettempdir()) / "bg_preview_v4.png"
    url = f"https://drive.google.com/uc?export=download&id={BACKGROUND_IMAGE_ID}"
    cmd = ['curl', '-L', '-o', str(output_path), url]
    subprocess.run(cmd, capture_output=True)

    if output_path.exists() and output_path.stat().st_size > 1000:
        print(f"  ✓ ダウンロード完了")
        return str(output_path)
    else:
        return create_fallback_background()


def create_fallback_background():
    output_path = Path(tempfile.gettempdir()) / "bg_fallback_v4.png"
    cmd = [
        'ffmpeg', '-y', '-f', 'lavfi',
        '-i', f'color=c=#2C3E50:s={SQUARE_SIZE}x{SQUARE_SIZE}:d=1',
        '-frames:v', '1', str(output_path)
    ]
    subprocess.run(cmd, capture_output=True)
    return str(output_path)


def create_composite_background(bg_image_path: str, output_path: str):
    """上下黒帯 + 中央正方形画像の合成背景を作成"""
    print("[2/5] 合成背景を作成中...")

    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi', '-i', f'color=c=black:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d=1',
        '-i', bg_image_path,
        '-filter_complex',
        f'[1:v]scale={SQUARE_SIZE}:{SQUARE_SIZE}:force_original_aspect_ratio=increase,crop={SQUARE_SIZE}:{SQUARE_SIZE}[scaled];'
        f'[0:v][scaled]overlay=0:{TOP_BAR_HEIGHT}',
        '-frames:v', '1', output_path
    ]
    subprocess.run(cmd, capture_output=True)
    print(f"  ✓ 合成背景作成完了")


def generate_subtitles(output_path: str):
    """ASS字幕を生成"""
    print("[3/5] 字幕ファイルを生成中...")

    time_per_line = DURATION / len(DUMMY_SCRIPT)

    # === サイズ設定 ===
    topic_size = 80  # トピック：収まるサイズ
    dialogue_size = 160  # 会話：2倍（80 * 2）
    hook_size = 70  # 煽りフレーズ：コンパクト

    # === 位置設定（MarginV = 画面下端からの距離）===
    # トピック：上部黒帯の中央付近
    # 画面下端からの距離 = VIDEO_HEIGHT - (TOP_BAR_HEIGHT / 2) = 1920 - 210 = 1710
    topic_margin_v = VIDEO_HEIGHT - (TOP_BAR_HEIGHT // 2) - 50  # 1660

    # 会話：正方形エリアの下部
    dialogue_margin_v = BOTTOM_BAR_HEIGHT + 100  # 520

    # 煽りフレーズ：下部黒帯の中央
    hook_margin_v = BOTTOM_BAR_HEIGHT // 2  # 210

    header = f"""[Script Info]
Title: Design Preview v4
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Topic,Hiragino Sans,{topic_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,6,2,8,80,80,{topic_margin_v},1
Style: Katsumi,Hiragino Sans,{dialogue_size},&H0000FFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,8,3,5,50,50,{dialogue_margin_v},1
Style: Hiroshi,Hiragino Sans,{dialogue_size},&H005050FF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,8,3,5,50,50,{dialogue_margin_v},1
Style: Hook,Hiragino Sans,{hook_size},&H0080FFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,5,2,2,50,50,{hook_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]

    # トピック（常時表示、奥から飛び出す）
    topic_zoom = "{\\fscx20\\fscy20\\t(0,300,\\fscx105\\fscy105)\\t(300,500,\\fscx100\\fscy100)}"
    lines.append(f"Dialogue: 0,0:00:00.00,0:00:{DURATION:05.2f},Topic,,0,0,0,,{topic_zoom}{TOPIC}")

    # 煽りフレーズ（常時表示、少し遅れて登場）
    hook_effect = "{\\alpha&HFF&\\t(500,800,\\alpha&H00&)}"  # フェードイン
    lines.append(f"Dialogue: 0,0:00:00.50,0:00:{DURATION:05.2f},Hook,,0,0,0,,{hook_effect}{HOOK_PHRASE}")

    # 会話（ポップアップ）
    for i, line in enumerate(DUMMY_SCRIPT):
        start_time = i * time_per_line
        end_time = (i + 1) * time_per_line

        start_str = f"0:{int(start_time // 60):02d}:{start_time % 60:05.2f}"
        end_str = f"0:{int(end_time // 60):02d}:{end_time % 60:05.2f}"

        style = "Hiroshi" if line["speaker"] == "ヒロシ" else "Katsumi"
        text = line["text"]

        popup = "{\\fscx50\\fscy50\\t(0,150,\\fscx110\\fscy110)\\t(150,300,\\fscx100\\fscy100)}"
        lines.append(f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{popup}{text}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"  ✓ 字幕生成完了")
    print("\n  === デザイン設定 v4 ===")
    print(f"  トピック: 白 {topic_size}pt、上部黒帯内、横幅収まる")
    print(f"  会話: カツミ=黄/ヒロシ=赤 {dialogue_size}pt（2倍）")
    print(f"  煽りフレーズ: オレンジ {hook_size}pt、下部黒帯")
    print("  ===========================\n")


def generate_silent_audio(output_path: str):
    print("[4/5] 無音オーディオを生成中...")
    cmd = [
        'ffmpeg', '-y', '-f', 'lavfi',
        '-i', 'anullsrc=r=44100:cl=stereo',
        '-t', str(DURATION), '-c:a', 'aac', '-b:a', '128k', output_path
    ]
    subprocess.run(cmd, capture_output=True)
    print("  ✓ 完了")


def generate_video(bg_path: str, subtitle_path: str, audio_path: str, output_path: str):
    print("[5/5] 動画を生成中...")
    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', bg_path,
        '-i', audio_path,
        '-vf', f'ass={subtitle_path}',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k',
        '-shortest', '-t', str(DURATION), '-pix_fmt', 'yuv420p',
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if Path(output_path).exists():
        size_mb = Path(output_path).stat().st_size / (1024 * 1024)
        print(f"  ✓ 動画生成完了: {output_path}")
        print(f"  ✓ サイズ: {size_mb:.2f} MB")
    else:
        print(f"  ✗ 失敗: {result.stderr}")


def main():
    print("=" * 50)
    print("デザイン確認用ダミー動画 v4")
    print("トピック上部 + 会話2倍 + 煽りフレーズ下部")
    print("=" * 50)

    output_video = Path("/Users/user/jinsei-soudan/design_preview_v4.mp4")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        composite_bg = temp_path / "composite_bg.png"
        subtitle = temp_path / "subtitles.ass"
        audio = temp_path / "silent.m4a"

        bg_path = download_background()
        create_composite_background(bg_path, str(composite_bg))
        generate_subtitles(str(subtitle))
        generate_silent_audio(str(audio))
        generate_video(str(composite_bg), str(subtitle), str(audio), str(output_video))

    print("\n" + "=" * 50)
    print(f"完了！: {output_video}")
    print("=" * 50)


if __name__ == "__main__":
    main()
