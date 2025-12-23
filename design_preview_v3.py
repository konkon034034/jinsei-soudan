#!/usr/bin/env python3
"""
デザイン確認用ダミー動画生成 v3
- 上下黒帯 + 中央正方形（1080x1080）
- トピック: 上部黒帯のやや下、1.8倍サイズ、奥から飛び出すアニメ
- 会話: 中央正方形内に表示
"""

import subprocess
import tempfile
from pathlib import Path

# ===== 設定 =====
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
SQUARE_SIZE = 1080  # 中央の正方形
DURATION = 30  # 秒

# 上下の黒帯の高さ
TOP_BAR_HEIGHT = (VIDEO_HEIGHT - SQUARE_SIZE) // 2  # 420px
BOTTOM_BAR_HEIGHT = VIDEO_HEIGHT - SQUARE_SIZE - TOP_BAR_HEIGHT  # 420px

# 背景画像（Google Drive ID）
BACKGROUND_IMAGE_ID = "1runaL5Mpn051ZLcNQ0KJvluz9DJQpeyq"

# トピック
TOPIC = "知らないと損！繰り下げ受給"

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

    output_path = Path(tempfile.gettempdir()) / "bg_preview_v3.png"

    url = f"https://drive.google.com/uc?export=download&id={BACKGROUND_IMAGE_ID}"
    cmd = ['curl', '-L', '-o', str(output_path), url]
    subprocess.run(cmd, capture_output=True)

    if output_path.exists() and output_path.stat().st_size > 1000:
        print(f"  ✓ ダウンロード完了: {output_path}")
        return str(output_path)
    else:
        print("  ⚠ ダウンロード失敗、単色背景を生成")
        return create_fallback_background()


def create_fallback_background():
    """フォールバック用の単色背景を生成"""
    output_path = Path(tempfile.gettempdir()) / "bg_fallback_v3.png"

    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi',
        '-i', f'color=c=#2C3E50:s={SQUARE_SIZE}x{SQUARE_SIZE}:d=1',
        '-frames:v', '1',
        str(output_path)
    ]
    subprocess.run(cmd, capture_output=True)
    print(f"  ✓ フォールバック背景生成: {output_path}")
    return str(output_path)


def create_composite_background(bg_image_path: str, output_path: str):
    """上下黒帯 + 中央正方形画像の合成背景を作成"""
    print("[2/5] 合成背景を作成中...")

    # ffmpegで合成
    # 1. 黒背景を作成
    # 2. 中央に正方形画像を配置
    cmd = [
        'ffmpeg', '-y',
        # 黒背景
        '-f', 'lavfi', '-i', f'color=c=black:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d=1',
        # 背景画像
        '-i', bg_image_path,
        # フィルター: 背景画像を正方形にリサイズして中央に配置
        '-filter_complex',
        f'[1:v]scale={SQUARE_SIZE}:{SQUARE_SIZE}:force_original_aspect_ratio=increase,crop={SQUARE_SIZE}:{SQUARE_SIZE}[scaled];'
        f'[0:v][scaled]overlay=0:{TOP_BAR_HEIGHT}',
        '-frames:v', '1',
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if Path(output_path).exists():
        print(f"  ✓ 合成背景作成完了: {output_path}")
    else:
        print(f"  ✗ 合成背景作成失敗")
        print(f"  stderr: {result.stderr}")


def generate_subtitles(output_path: str):
    """ASS字幕を生成"""
    print("[3/5] 字幕ファイルを生成中...")

    time_per_line = DURATION / len(DUMMY_SCRIPT)

    # トピック位置: 上部黒帯のやや下（中央寄り）
    # MarginV = 画面下端からの距離
    # 上部黒帯の下端 = VIDEO_HEIGHT - TOP_BAR_HEIGHT = 1500
    # やや下め = 1500 + 少し = 画面下端から約1400くらい
    topic_margin_v = VIDEO_HEIGHT - TOP_BAR_HEIGHT + 50  # 上部黒帯のやや下

    # 会話位置: 正方形エリアの下部
    # 正方形の下端 = BOTTOM_BAR_HEIGHT = 420
    # 正方形内のやや下 = 約500くらい
    dialogue_margin_v = BOTTOM_BAR_HEIGHT + 150

    # フォントサイズ
    topic_size = 144  # 80 * 1.8 ≈ 144
    dialogue_size = 80

    header = f"""[Script Info]
Title: Design Preview v3
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Topic,Hiragino Sans,{topic_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,8,3,8,50,50,{topic_margin_v},1
Style: Katsumi,Hiragino Sans,{dialogue_size},&H0000FFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,6,3,5,50,50,{dialogue_margin_v},1
Style: Hiroshi,Hiragino Sans,{dialogue_size},&H005050FF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,6,3,5,50,50,{dialogue_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]

    # トピック（常時表示、奥から飛び出すアニメーション）
    # scale 0→1 を \\fscx, \\fscy で表現
    # 奥から手前へ = 小さい→大きい + 少しオーバーシュート
    topic_zoom = "{\\fscx10\\fscy10\\t(0,400,\\fscx110\\fscy110)\\t(400,600,\\fscx100\\fscy100)}"
    lines.append(f"Dialogue: 0,0:00:00.00,0:00:{DURATION:05.2f},Topic,,0,0,0,,{topic_zoom}{TOPIC}")

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
    print("\n  === 新デザイン設定 v3 ===")
    print(f"  レイアウト: 上黒帯{TOP_BAR_HEIGHT}px + 正方形{SQUARE_SIZE}px + 下黒帯{BOTTOM_BAR_HEIGHT}px")
    print(f"  トピック: 白文字 {topic_size}pt（1.8倍）、上部黒帯のやや下")
    print(f"  トピックアニメ: 奥から飛び出す（scale 10%→110%→100%）")
    print(f"  カツミ: 黄色文字 {dialogue_size}pt")
    print(f"  ヒロシ: 赤文字 {dialogue_size}pt")
    print(f"  会話位置: 正方形エリア内の下部")
    print("  縁取り: トピック8px、会話6px")
    print("  ===========================\n")


def generate_silent_audio(output_path: str):
    """無音オーディオを生成"""
    print("[4/5] 無音オーディオを生成中...")

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
    print("[5/5] 動画を生成中...")

    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', bg_path,
        '-i', audio_path,
        '-vf', f'ass={subtitle_path}',
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
    print("デザイン確認用ダミー動画生成 v3")
    print("上下黒帯 + 中央正方形レイアウト")
    print("=" * 50)

    # 出力先
    output_dir = Path("/Users/user/jinsei-soudan")
    output_video = output_dir / "design_preview_v3.mp4"

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        composite_bg_path = temp_path / "composite_bg.png"
        subtitle_path = temp_path / "subtitles.ass"
        audio_path = temp_path / "silent.m4a"

        # 1. 背景画像ダウンロード
        bg_path = download_background()

        # 2. 合成背景作成（上下黒帯 + 中央正方形）
        create_composite_background(bg_path, str(composite_bg_path))

        # 3. 字幕生成
        generate_subtitles(str(subtitle_path))

        # 4. 無音オーディオ
        generate_silent_audio(str(audio_path))

        # 5. 動画生成
        generate_video(str(composite_bg_path), str(subtitle_path), str(audio_path), str(output_video))

    print("\n" + "=" * 50)
    print(f"完了！ダウンロード: {output_video}")
    print("=" * 50)


if __name__ == "__main__":
    main()
