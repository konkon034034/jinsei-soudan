#!/usr/bin/env python3
"""
Modal GPU 動画エンコーダー（PILフレーム描画方式）
- 各フレームにPILで直接テキストを焼き付け
- T4 GPU で h264_nvenc を使用して高速エンコード
"""

import modal

app = modal.App("nenkin-video")

# FFmpeg、日本語フォント、PILをインストールしたイメージ
image = modal.Image.debian_slim().apt_install(
    "ffmpeg",
    "fonts-noto-cjk",
    "fonts-noto-cjk-extra",
    "fontconfig"
).run_commands(
    "fc-cache -f -v"
).pip_install(
    "numpy",
    "Pillow"
)

# 定数
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
FPS = 30


def to_vertical(text: str) -> str:
    """テキストを縦書き用に変換（改行区切り）"""
    result = []
    for char in text:
        # 長音を縦棒に変換
        if char in ['ー', '－', '―', '─']:
            result.append('｜')
        else:
            result.append(char)
    return '\n'.join(result)


def wrap_text(text: str, max_chars: int = 16) -> list:
    """テキストを指定文字数で折り返し（リスト返却）"""
    lines = []
    while len(text) > max_chars:
        lines.append(text[:max_chars])
        text = text[max_chars:]
    if text:
        lines.append(text)
    return lines


def draw_frame(
    bg_image,
    text: str,
    speaker: str,
    is_backroom: bool,
    topic: str = None,
    source: str = None,
    fonts: dict = None
):
    """1フレームを描画"""
    from PIL import Image, ImageDraw, ImageFont

    # 背景
    if is_backroom:
        # 控室は黒背景
        frame = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0))
    else:
        # 本編は背景画像
        frame = bg_image.copy()

    draw = ImageDraw.Draw(frame)

    # フォント取得
    subtitle_font = fonts.get('subtitle')
    topic_font = fonts.get('topic')
    source_font = fonts.get('source')
    backroom_title_font = fonts.get('backroom_title')

    # 本編のみ: 下部に透かしバー
    if not is_backroom:
        bar_height = int(VIDEO_HEIGHT * 0.45)
        bar_y = VIDEO_HEIGHT - bar_height
        # 半透明の茶色バー（PILはRGBAで透明度処理）
        overlay = Image.new('RGBA', (VIDEO_WIDTH, bar_height), (60, 40, 30, 200))
        frame.paste(Image.alpha_composite(
            Image.new('RGBA', (VIDEO_WIDTH, bar_height), (0, 0, 0, 0)),
            overlay
        ).convert('RGB'), (0, bar_y))

    # セリフ（下部中央）
    if text and text.strip():
        # 40文字以上は省略
        display_text = text[:37] + "..." if len(text) > 40 else text
        # 16文字で折り返し
        lines = wrap_text(display_text, 16)

        # 色: 控室はゴールド、本編は白
        text_color = (255, 215, 0) if is_backroom else (255, 255, 255)

        # 位置計算（下から5%、中央寄せ）
        margin_bottom = int(VIDEO_HEIGHT * 0.05)
        line_height = int(VIDEO_WIDTH * 0.075) + 10  # フォントサイズ + 行間

        total_height = len(lines) * line_height
        y = VIDEO_HEIGHT - margin_bottom - total_height

        for line in lines:
            # テキスト幅を取得して中央寄せ
            bbox = draw.textbbox((0, 0), line, font=subtitle_font)
            text_width = bbox[2] - bbox[0]
            x = (VIDEO_WIDTH - text_width) // 2

            # 縁取り（黒）
            for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2), (-2, 0), (2, 0), (0, -2), (0, 2)]:
                draw.text((x + dx, y + dy), line, font=subtitle_font, fill=(0, 0, 0))
            # 本文
            draw.text((x, y), line, font=subtitle_font, fill=text_color)
            y += line_height

    # トピック縦書き（左端、本編ニュースセクションのみ）
    if topic and not is_backroom:
        vertical_topic = to_vertical(topic)
        topic_lines = vertical_topic.split('\n')

        x = 30  # 左端マージン
        y = 50  # 上端マージン

        for char in topic_lines:
            # 縁取り
            for dx, dy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
                draw.text((x + dx, y + dy), char, font=topic_font, fill=(0, 0, 0, 128))
            draw.text((x, y), char, font=topic_font, fill=(255, 255, 255))
            y += 100  # 縦書き間隔

    # 出典（右下、本編ニュースセクションのみ）
    if source and not is_backroom:
        source_text = f"出典: {source}"
        bar_height = int(VIDEO_HEIGHT * 0.45)
        source_y = VIDEO_HEIGHT - bar_height - 80  # 透かしバーの上

        bbox = draw.textbbox((0, 0), source_text, font=source_font)
        text_width = bbox[2] - bbox[0]
        source_x = VIDEO_WIDTH - text_width - 30  # 右寄せ

        draw.text((source_x, source_y), source_text, font=source_font, fill=(255, 255, 255))

    # 「控室にて。」（控室のみ、右上）
    if is_backroom:
        title_text = "控室にて。"
        # 右上寄り（MarginR=150, MarginV=250 相当）
        bbox = draw.textbbox((0, 0), title_text, font=backroom_title_font)
        text_width = bbox[2] - bbox[0]
        x = VIDEO_WIDTH - text_width - 150
        y = 250

        # 縁取り
        for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2)]:
            draw.text((x + dx, y + dy), title_text, font=backroom_title_font, fill=(255, 255, 255, 128))
        draw.text((x, y), title_text, font=backroom_title_font, fill=(255, 255, 255))

    return frame


@app.function(gpu="T4", image=image, timeout=1800)
def encode_video_with_frames(
    bg_base64: str,
    audio_base64: str,
    segments_json: str,
    output_name: str
) -> bytes:
    """
    PILでフレームを生成し、GPUでエンコード

    Args:
        bg_base64: 背景画像（base64）
        audio_base64: 音声ファイル（base64）
        segments_json: セグメント情報（JSON文字列）
        output_name: 出力ファイル名

    Returns:
        bytes: エンコードされた動画データ
    """
    import base64
    import subprocess
    import tempfile
    import os
    import json
    from PIL import Image, ImageFont
    import numpy as np

    segments = json.loads(segments_json)

    with tempfile.TemporaryDirectory() as tmpdir:
        # ファイルを一時保存
        bg_path = os.path.join(tmpdir, "bg.png")
        audio_path = os.path.join(tmpdir, "audio.wav")
        frames_dir = os.path.join(tmpdir, "frames")
        output_path = os.path.join(tmpdir, output_name)
        os.makedirs(frames_dir)

        with open(bg_path, "wb") as f:
            f.write(base64.b64decode(bg_base64))
        with open(audio_path, "wb") as f:
            f.write(base64.b64decode(audio_base64))

        # 背景画像を読み込み
        bg_image = Image.open(bg_path).convert('RGB')
        bg_image = bg_image.resize((VIDEO_WIDTH, VIDEO_HEIGHT))

        # フォント読み込み
        font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
        try:
            fonts = {
                'subtitle': ImageFont.truetype(font_path, int(VIDEO_WIDTH * 0.075)),  # 144px
                'topic': ImageFont.truetype(font_path, 90),
                'source': ImageFont.truetype(font_path, 72),
                'backroom_title': ImageFont.truetype(font_path, 180),
            }
        except Exception as e:
            print(f"Font loading error, trying alternative: {e}")
            # フォールバック
            font_path = "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"
            try:
                fonts = {
                    'subtitle': ImageFont.truetype(font_path, int(VIDEO_WIDTH * 0.075)),
                    'topic': ImageFont.truetype(font_path, 90),
                    'source': ImageFont.truetype(font_path, 72),
                    'backroom_title': ImageFont.truetype(font_path, 180),
                }
            except:
                # 最終フォールバック: デフォルトフォント
                print("Using default font")
                fonts = {
                    'subtitle': ImageFont.load_default(),
                    'topic': ImageFont.load_default(),
                    'source': ImageFont.load_default(),
                    'backroom_title': ImageFont.load_default(),
                }

        # 音声の長さを取得
        result = subprocess.run([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', audio_path
        ], capture_output=True, text=True)
        total_duration = float(result.stdout.strip()) if result.stdout.strip() else 0.0
        total_frames = int(total_duration * FPS)

        print(f"  [PILフレーム] 総フレーム数: {total_frames} ({total_duration:.1f}秒)")
        print(f"  [PILフレーム] セグメント数: {len(segments)}")

        # 現在のセグメント情報を追跡
        current_segment_idx = 0
        current_topic = None
        current_source = None

        # フレームを生成
        for frame_num in range(total_frames):
            current_time = frame_num / FPS

            # 現在のセグメントを探す
            seg = None
            for i, s in enumerate(segments):
                if s['start'] <= current_time < s['end']:
                    seg = s
                    current_segment_idx = i
                    break

            # セグメントがない場合（音声の前後の余白）
            if seg is None:
                # 最後のセグメントを使用するか、デフォルト
                if segments and current_time >= segments[-1]['end']:
                    seg = segments[-1]
                elif segments and current_time < segments[0]['start']:
                    seg = {'text': '', 'speaker': '', 'section': 'オープニング', 'is_silence': True}
                else:
                    seg = {'text': '', 'speaker': '', 'section': '', 'is_silence': True}

            # セグメント情報
            text = seg.get('text', '') if not seg.get('is_silence') else ''
            speaker = seg.get('speaker', '')
            section = seg.get('section', '')
            is_backroom = section == '控え室'

            # トピックと出典（ニュースセクションのみ）
            topic = None
            source = None
            if section and section not in ['オープニング', '深掘りコーナー', 'エンディング', '控え室', '間']:
                topic = section
                source = seg.get('source', '')

            # フレーム描画
            frame = draw_frame(
                bg_image=bg_image,
                text=text,
                speaker=speaker,
                is_backroom=is_backroom,
                topic=topic,
                source=source,
                fonts=fonts
            )

            # フレームを保存
            frame_path = os.path.join(frames_dir, f"frame_{frame_num:06d}.png")
            frame.save(frame_path, 'PNG')

            # 進捗表示（10%ごと）
            if frame_num % (total_frames // 10 + 1) == 0:
                print(f"    フレーム生成: {frame_num}/{total_frames} ({100*frame_num//total_frames}%)")

        print(f"  [PILフレーム] フレーム生成完了")

        # ffmpegでフレームを動画に結合
        print(f"  [エンコード] GPU (h264_nvenc) でエンコード中...")

        cmd = [
            'ffmpeg', '-y',
            '-framerate', str(FPS),
            '-i', os.path.join(frames_dir, 'frame_%06d.png'),
            '-i', audio_path,
            '-c:v', 'h264_nvenc',
            '-preset', 'fast',
            '-b:v', '5M',
            '-c:a', 'aac', '-b:a', '192k',
            '-shortest',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"GPU encoding failed, falling back to CPU: {result.stderr}")
            # CPUフォールバック
            cmd[cmd.index('h264_nvenc')] = 'libx264'
            cmd[cmd.index('-preset') + 1] = 'ultrafast'
            subprocess.run(cmd, check=True, capture_output=True, text=True)

        print(f"  [エンコード] 完了")

        with open(output_path, "rb") as f:
            return f.read()


# 後方互換性のため旧関数も残す（ASS版）
@app.function(gpu="T4", image=image, timeout=600)
def encode_video_gpu(bg_base64: str, audio_base64: str, ass_content: str, output_name: str, backroom_start_sec: float = None) -> bytes:
    """
    GPU (h264_nvenc) で動画をエンコード（ASS字幕版 - 後方互換用）
    """
    import base64
    import subprocess
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        bg_path = os.path.join(tmpdir, "bg.png")
        audio_path = os.path.join(tmpdir, "audio.wav")
        ass_path = os.path.join(tmpdir, "subtitles.ass")
        output_path = os.path.join(tmpdir, output_name)

        with open(bg_path, "wb") as f:
            f.write(base64.b64decode(bg_base64))
        with open(audio_path, "wb") as f:
            f.write(base64.b64decode(audio_base64))
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        bar_height = int(1080 * 0.45)
        bar_y = 1080 - bar_height

        if backroom_start_sec is not None:
            vf_filter = (
                f"scale=1920:1080,"
                f"drawbox=x=0:y=0:w=1920:h=1080:color=black:t=fill:enable='gte(t,{backroom_start_sec})',"
                f"drawbox=x=0:y={bar_y}:w=1920:h={bar_height}:color=0x3C281E@0.8:t=fill:enable='lt(t,{backroom_start_sec})',"
                f"ass={ass_path}:fontsdir=/usr/share/fonts"
            )
        else:
            vf_filter = (
                f"scale=1920:1080,"
                f"drawbox=x=0:y={bar_y}:w=1920:h={bar_height}:color=0x3C281E@0.8:t=fill,"
                f"ass={ass_path}:fontsdir=/usr/share/fonts"
            )

        cmd = [
            'ffmpeg', '-y',
            '-loop', '1', '-i', bg_path,
            '-i', audio_path,
            '-vf', vf_filter,
            '-c:v', 'h264_nvenc',
            '-preset', 'fast',
            '-b:v', '5M',
            '-c:a', 'aac', '-b:a', '192k',
            '-shortest',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"GPU encoding failed, falling back to CPU: {result.stderr}")
            cmd[cmd.index('h264_nvenc')] = 'libx264'
            cmd[cmd.index('-preset') + 1] = 'ultrafast'
            subprocess.run(cmd, check=True)

        with open(output_path, "rb") as f:
            return f.read()


@app.local_entrypoint()
def main():
    """テスト用エントリーポイント"""
    print("=" * 50)
    print("Modal GPU Video Encoder (PIL Frame Rendering)")
    print("=" * 50)
    print("利用可能な関数:")
    print("  - encode_video_with_frames: PILフレーム描画 + GPU エンコード")
    print("  - encode_video_gpu: ASS字幕版（後方互換）")
    print("=" * 50)
