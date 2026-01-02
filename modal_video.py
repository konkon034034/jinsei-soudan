#!/usr/bin/env python3
"""
Modal GPU 動画エンコーダー
- A10G GPU で h264_nvenc を使用して高速エンコード（T4比3-4倍速）
"""

import modal

app = modal.App("nenkin-video")

# FFmpegと日本語フォントをインストールしたイメージ（NVIDIA GPU対応）
image = modal.Image.debian_slim().apt_install(
    "ffmpeg",
    "fonts-noto-cjk",
    "fonts-noto-cjk-extra",
    "fonts-ipafont",
    "fonts-ipaexfont",
    "fontconfig"
).run_commands(
    "fc-cache -f -v"  # フォントキャッシュを更新
).pip_install(
    "numpy"
)


@app.function(gpu="A10G", image=image, timeout=600)
def encode_video_gpu(bg_base64: str, audio_base64: str, ass_content: str, output_name: str, backroom_start_sec: float = None, qr_bg_base64: str = None) -> bytes:
    """
    GPU (h264_nvenc) で動画をエンコード

    Args:
        bg_base64: 背景画像（base64）
        audio_base64: 音声ファイル（base64）
        ass_content: 字幕ファイルの内容
        output_name: 出力ファイル名
        backroom_start_sec: 控室開始時刻（秒）。指定時はQRコード背景に切り替え
        qr_bg_base64: QRコード付き控室背景画像（base64）

    Returns:
        bytes: エンコードされた動画データ
    """
    import base64
    import subprocess
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        # ファイルを一時保存
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

        # QRコード背景を保存
        qr_bg_path = None
        if qr_bg_base64:
            qr_bg_path = os.path.join(tmpdir, "qr_bg.png")
            with open(qr_bg_path, "wb") as f:
                f.write(base64.b64decode(qr_bg_base64))

        # 背景バーの設定（画面の45%）
        bar_height = int(1080 * 0.45)  # 486
        bar_y = 1080 - bar_height  # 594

        # GPU エンコード（h264_nvenc）
        # fontsdir でフォントディレクトリを明示的に指定
        if backroom_start_sec is not None and qr_bg_path:
            # 控室開始からQRコード背景をoverlay（透かしバーは控室前のみ表示）
            vf_filter = (
                f"[0:v]scale=1920:1080,"
                f"drawbox=x=0:y={bar_y}:w=1920:h={bar_height}:color=0x3C281E@0.8:t=fill:enable='lt(t,{backroom_start_sec})'[main];"
                f"[1:v]scale=1920:1080[qr];"
                f"[main][qr]overlay=0:0:enable='gte(t,{backroom_start_sec})'[overlaid];"
                f"[overlaid]ass={ass_path}:fontsdir=/usr/share/fonts[out]"
            )
            print(f"  [動画] 控室開始 {backroom_start_sec:.1f}秒 からQRコード背景に切り替え")

            cmd = [
                'ffmpeg', '-y',
                '-loop', '1', '-i', bg_path,
                '-loop', '1', '-i', qr_bg_path,
                '-i', audio_path,
                '-filter_complex', vf_filter,
                '-map', '[out]',
                '-map', '2:a',
                '-c:v', 'h264_nvenc',  # NVIDIA GPU エンコード
                '-preset', 'fast',
                '-b:v', '5M',
                '-c:a', 'aac', '-b:a', '192k',
                '-shortest',
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart',
                output_path
            ]
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
                '-c:v', 'h264_nvenc',  # NVIDIA GPU エンコード
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
            # GPU非対応の場合はCPUフォールバック
            print(f"GPU encoding failed, falling back to CPU: {result.stderr}")
            # h264_nvenc を libx264 に置換
            for i, arg in enumerate(cmd):
                if arg == 'h264_nvenc':
                    cmd[i] = 'libx264'
                elif arg == '-preset' and i + 1 < len(cmd):
                    cmd[i + 1] = 'ultrafast'
            subprocess.run(cmd, check=True)

        with open(output_path, "rb") as f:
            return f.read()


@app.function(image=image, timeout=300)
def encode_video_cpu(bg_base64: str, audio_base64: str, ass_content: str, output_name: str) -> bytes:
    """
    CPU (libx264) で動画をエンコード（GPUが不要な場合用）
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

        # fontsdir でフォントディレクトリを明示的に指定
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
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '192k',
            '-shortest',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            output_path
        ]

        subprocess.run(cmd, check=True)

        with open(output_path, "rb") as f:
            return f.read()


@app.function(gpu="A10G", image=image, timeout=1800)
def encode_video_from_clips(clip_videos_base64: list, output_name: str) -> bytes:
    """
    複数の動画クリップを結合してGPUエンコード

    Args:
        clip_videos_base64: 動画クリップのbase64リスト
        output_name: 出力ファイル名

    Returns:
        bytes: エンコードされた動画データ
    """
    import base64
    import subprocess
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        # 各クリップを一時ファイルに保存
        clip_paths = []
        for i, clip_b64 in enumerate(clip_videos_base64):
            clip_path = os.path.join(tmpdir, f"clip_{i:04d}.mp4")
            with open(clip_path, "wb") as f:
                f.write(base64.b64decode(clip_b64))
            clip_paths.append(clip_path)

        # concat用のリストファイル作成
        list_path = os.path.join(tmpdir, "list.txt")
        with open(list_path, "w") as f:
            for path in clip_paths:
                f.write(f"file '{path}'\n")

        output_path = os.path.join(tmpdir, output_name)

        # ffmpeg concat + GPU re-encode
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', list_path,
            '-c:v', 'h264_nvenc',
            '-preset', 'fast',
            '-b:v', '5M',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"GPU encoding failed, falling back to CPU: {result.stderr}")
            # CPU fallback
            cmd = [
                'ffmpeg', '-y',
                '-f', 'concat', '-safe', '0', '-i', list_path,
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                '-c:a', 'aac', '-b:a', '192k',
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart',
                output_path
            ]
            subprocess.run(cmd, check=True)

        with open(output_path, "rb") as f:
            return f.read()


@app.function(gpu="A10G", image=image, timeout=1800)
def encode_video_from_frames(
    frames_base64: list,
    audio_base64: str,
    fps: int,
    output_name: str
) -> bytes:
    """
    フレーム画像のリストと音声から動画をGPUエンコード

    Args:
        frames_base64: フレーム画像のbase64リスト（PNG）
        audio_base64: 音声ファイル（WAV/MP3）のbase64
        fps: フレームレート
        output_name: 出力ファイル名

    Returns:
        bytes: エンコードされた動画データ
    """
    import base64
    import subprocess
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        # フレーム画像を保存
        frames_dir = os.path.join(tmpdir, "frames")
        os.makedirs(frames_dir)
        for i, frame_b64 in enumerate(frames_base64):
            frame_path = os.path.join(frames_dir, f"frame_{i:06d}.png")
            with open(frame_path, "wb") as f:
                f.write(base64.b64decode(frame_b64))

        # 音声を保存
        audio_path = os.path.join(tmpdir, "audio.wav")
        with open(audio_path, "wb") as f:
            f.write(base64.b64decode(audio_base64))

        output_path = os.path.join(tmpdir, output_name)

        # ffmpeg: フレーム + 音声 → 動画
        cmd = [
            'ffmpeg', '-y',
            '-framerate', str(fps),
            '-i', os.path.join(frames_dir, 'frame_%06d.png'),
            '-i', audio_path,
            '-c:v', 'h264_nvenc',
            '-preset', 'fast',
            '-b:v', '5M',
            '-c:a', 'aac', '-b:a', '192k',
            '-pix_fmt', 'yuv420p',
            '-shortest',
            '-movflags', '+faststart',
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"GPU encoding failed, falling back to CPU: {result.stderr}")
            cmd = [
                'ffmpeg', '-y',
                '-framerate', str(fps),
                '-i', os.path.join(frames_dir, 'frame_%06d.png'),
                '-i', audio_path,
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
                '-c:a', 'aac', '-b:a', '192k',
                '-pix_fmt', 'yuv420p',
                '-shortest',
                '-movflags', '+faststart',
                output_path
            ]
            subprocess.run(cmd, check=True)

        with open(output_path, "rb") as f:
            return f.read()


# ローカルからの呼び出し用テスト
@app.local_entrypoint()
def main():
    """テスト用エントリーポイント"""
    print("=" * 50)
    print("Modal GPU Video Encoder")
    print("=" * 50)
    print("利用可能な関数:")
    print("  - encode_video_gpu: A10G GPU (h264_nvenc) - 背景+音声+ASS字幕")
    print("  - encode_video_cpu: CPU (libx264) - 背景+音声+ASS字幕")
    print("  - encode_video_from_clips: A10G GPU - 複数クリップ結合")
    print("  - encode_video_from_frames: A10G GPU - フレーム画像から動画生成")
    print("")
    print("使用例:")
    print("  import modal")
    print("  encode_fn = modal.Function.from_name('nenkin-video', 'encode_video_gpu')")
    print("  result = encode_fn.remote(bg_b64, audio_b64, ass, 'output.mp4')")
    print("=" * 50)
