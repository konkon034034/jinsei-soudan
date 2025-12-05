#!/usr/bin/env python3
"""
人生相談チャンネル 自動生成ラッパー
環境変数 CHANNEL_KEY に応じて設定を切り替え
"""

import os
import sys

# チャンネルキーを取得（デフォルトは jinsei）
CHANNEL_KEY = os.environ.get("CHANNEL_KEY", "jinsei")

print(f"=" * 50)
print(f"🎬 チャンネル: {CHANNEL_KEY}")
print(f"=" * 50)

# config から設定を取得
from config import get_config, CHANNEL_CONFIGS

if CHANNEL_KEY not in CHANNEL_CONFIGS:
    print(f"❌ 不明なチャンネルキー: {CHANNEL_KEY}")
    print(f"有効なキー: {list(CHANNEL_CONFIGS.keys())}")
    sys.exit(1)

config = get_config(CHANNEL_KEY)

print(f"📺 チャンネル名: {config['name']}")
print(f"📋 シート: {config['sheet_name']}")
print(f"🎭 回答者: {config['advisor_name']}")
print(f"👤 相談者: {config['consulter_name']}")
print(f"🎯 参考チャンネル: {config['reference_channel']}")
print(f"=" * 50)

# 環境変数に設定を書き込む（他のスクリプトが参照できるように）
os.environ["SHEET_NAME"] = config["sheet_name"]
os.environ["ADVISOR_NAME"] = config["advisor_name"]
os.environ["CONSULTER_NAME"] = config["consulter_name"]
os.environ["ADVISOR_VOICE"] = config["advisor_voice"]
os.environ["ADVISOR_PITCH"] = str(config["advisor_pitch"])
os.environ["ADVISOR_RATE"] = str(config["advisor_rate"])
os.environ["CONSULTER_VOICE"] = config["consulter_voice"]
os.environ["CONSULTER_PITCH"] = str(config["consulter_pitch"])
os.environ["CONSULTER_RATE"] = str(config["consulter_rate"])
os.environ["REFERENCE_CHANNEL"] = config["reference_channel"]

# メイン処理を実行
from jinsei_generator import main

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
