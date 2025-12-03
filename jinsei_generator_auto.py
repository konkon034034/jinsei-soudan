#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人生相談チャンネル動画生成システム - 自動実行版
GitHub Actionsからの自動実行用エントリーポイント
"""

import sys
import os

# メインモジュールをインポート
from jinsei_generator import JinseiSoudanGenerator, print_header, print_error


def main():
    """自動実行のメイン処理"""
    print_header("人生相談チャンネル - 自動生成モード", 1)

    try:
        # 環境変数から動画URLを取得
        video_url = os.getenv('SOURCE_VIDEO_URL', '')

        if not video_url:
            print("📝 SOURCE_VIDEO_URL が未設定です。スプレッドシートから取得を試みます...")

        # ジェネレーターを初期化して実行
        generator = JinseiSoudanGenerator()
        result = generator.run(video_url)

        if result:
            print("\n" + "=" * 60)
            print("🎉 自動生成が完了しました！")
            print(f"📊 処理行: {result['row_num']}")
            print(f"📝 台本文字数: {len(result['script'])}文字")
            print("=" * 60)
            return 0
        else:
            print_error("自動生成に失敗しました")
            return 1

    except Exception as e:
        print_error(f"致命的エラー: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
