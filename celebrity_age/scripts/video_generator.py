#!/usr/bin/env python3
"""
昭和有名人「生きていたら何歳」動画生成システム
パネル画像を右→左スクロールする動画を生成
"""

import os
import subprocess
import tempfile
from pathlib import Path
from PIL import Image

# 定数
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
PANEL_WIDTH = 640
FPS = 30
SCROLL_SPEED = 200  # ピクセル/秒


def load_panels(images_dir: Path) -> list:
    """
    画像ディレクトリからパネルを順番に読み込む

    ファイル名形式: frame_XXX_panel_Y.png
    """
    panels = []

    # フレーム番号でソート
    frame_files = sorted(images_dir.glob("frame_*_panel_*.png"))

    for file_path in frame_files:
        panels.append({
            "path": str(file_path),
            "name": file_path.stem
        })

    print(f"✓ {len(panels)}枚のパネルを読み込み")
    return panels


def create_scroll_strip(panels: list, output_path: str, spacer_width: int = 1) -> int:
    """
    全パネルを横に結合して1枚の長い画像を作成
    各パネル間に透明（黒）スペーサーを挿入

    Args:
        panels: パネルリスト
        output_path: 出力パス
        spacer_width: パネル間のスペーサー幅（デフォルト1px）

    Returns:
        総幅（ピクセル）
    """
    print("🖼️ パネルを結合中...")
    print(f"   (パネル間スペーサー: {spacer_width}px)")

    if not panels:
        raise ValueError("パネルがありません")

    # 最初のパネルで高さを確認
    first_img = Image.open(panels[0]["path"])
    panel_height = first_img.size[1]
    first_img.close()

    # 総幅を計算（パネル幅 + スペーサー）
    # スペーサーは各パネルの後に追加（最後のパネル以外）
    num_spacers = len(panels) - 1
    total_width = (len(panels) * PANEL_WIDTH) + (num_spacers * spacer_width)

    # 結合画像を作成（背景は黒=透明スペーサー）
    strip = Image.new('RGB', (total_width, panel_height), (0, 0, 0))

    # 各パネルを配置（スペーサー分のオフセットを考慮）
    current_x = 0
    for i, panel in enumerate(panels):
        img = Image.open(panel["path"])
        # パネルサイズにリサイズ（必要な場合）
        if img.size != (PANEL_WIDTH, panel_height):
            img = img.resize((PANEL_WIDTH, panel_height), Image.Resampling.LANCZOS)

        # パネルを配置
        strip.paste(img, (current_x, 0))
        img.close()

        # 次のパネルの開始位置を計算（パネル幅 + スペーサー）
        current_x += PANEL_WIDTH + spacer_width

    strip.save(output_path, quality=95)
    print(f"✓ 結合画像を保存: {total_width}x{panel_height}")
    print(f"   パネル: {len(panels)}枚, スペーサー: {num_spacers}箇所")

    return total_width


def generate_scroll_video(strip_path: str, output_path: str,
                          strip_width: int, duration_per_panel: float = 3.0) -> bool:
    """
    スクロール動画を生成

    Args:
        strip_path: 結合画像のパス
        output_path: 出力動画のパス
        strip_width: 結合画像の幅
        duration_per_panel: 1パネルあたりの表示時間（秒）
    """
    print("🎬 スクロール動画を生成中...")

    # スクロール量を計算（最初と最後は画面幅分余白）
    scroll_distance = strip_width - VIDEO_WIDTH

    if scroll_distance <= 0:
        print("⚠️ パネルが少なすぎます")
        return False

    # 動画の長さを計算
    num_panels = strip_width // PANEL_WIDTH
    total_duration = num_panels * duration_per_panel

    # ffmpegでスクロール動画を生成
    # crop filter: crop=w:h:x:y
    # x座標を時間とともに増加させる

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", strip_path,
        "-vf", f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:'min({scroll_distance},t*{scroll_distance}/{total_duration})':0",
        "-t", str(total_duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        output_path
    ]

    print(f"  総パネル数: {num_panels}")
    print(f"  動画長さ: {total_duration:.1f}秒")
    print(f"  スクロール距離: {scroll_distance}px")

    try:
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ ffmpegエラー: {result.stderr[:500]}")
            return False
    except Exception as e:
        print(f"❌ ffmpeg実行エラー: {e}")
        return False

    print(f"✅ 動画生成完了: {output_path}")
    return True


def generate_video(images_dir: str, output_path: str,
                   duration_per_panel: float = 3.0) -> bool:
    """
    メイン関数: パネル画像からスクロール動画を生成

    Args:
        images_dir: 画像ディレクトリ
        output_path: 出力動画パス
        duration_per_panel: 1パネルあたりの秒数
    """
    print("=" * 50)
    print("昭和有名人「生きていたら何歳」動画生成")
    print("=" * 50)

    images_path = Path(images_dir)

    # 1. パネルを読み込み
    panels = load_panels(images_path)

    if not panels:
        print("❌ 画像が見つかりません")
        return False

    # 2. 一時ディレクトリで作業
    with tempfile.TemporaryDirectory() as temp_dir:
        strip_path = os.path.join(temp_dir, "strip.png")

        # 3. パネルを結合
        strip_width = create_scroll_strip(panels, strip_path)

        # 4. スクロール動画を生成
        success = generate_scroll_video(
            strip_path, output_path,
            strip_width, duration_per_panel
        )

        return success


if __name__ == "__main__":
    import sys

    # デフォルトパス
    base_dir = Path(__file__).parent.parent
    images_dir = base_dir / "images"
    output_path = os.path.expanduser("~/Desktop/celebrity_age_test.mp4")

    # コマンドライン引数があれば使用
    if len(sys.argv) > 1:
        output_path = sys.argv[1]

    success = generate_video(str(images_dir), output_path)

    if success:
        print(f"\n🎉 完了！動画を確認してください: {output_path}")
        # Finderで開く
        os.system(f'open -R "{output_path}"')
    else:
        print("\n❌ 動画生成に失敗しました")
        sys.exit(1)
