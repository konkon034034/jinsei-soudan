#!/usr/bin/env python3
"""
LINE アフィリエイト配信スクリプト
週2回（木曜・日曜 16:00 JST）カツミの人格で日常話＋おすすめ紹介を配信
"""

import json
import os
import sys
import random
from datetime import datetime
from pathlib import Path

import requests


# ========================================
# 設定
# ========================================
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

# キャンペーンインデックス保存ファイル（順番配信用）
CAMPAIGN_INDEX_FILE = "campaign_index.txt"

# 環境変数マッピング（プレースホルダー → 環境変数名）
AFFILIATE_LINK_ENV_MAP = {
    "{{AFFILIATE_LINK_URANAI}}": "AFFILIATE_LINK_URANAI",
    "{{AFFILIATE_LINK_HOKEN}}": "AFFILIATE_LINK_HOKEN",
    "{{AFFILIATE_LINK_SHUKATSU}}": "AFFILIATE_LINK_SHUKATSU",
    "{{AFFILIATE_LINK_PET}}": "AFFILIATE_LINK_PET",
    "{{AFFILIATE_LINK_SUPPLEMENT}}": "AFFILIATE_LINK_SUPPLEMENT",
    "{{AFFILIATE_LINK_FOOD}}": "AFFILIATE_LINK_FOOD",
}


# ========================================
# キャンペーンデータ読み込み
# ========================================
def load_campaigns() -> list:
    """affiliate_campaigns.json からキャンペーンデータを読み込む"""
    script_dir = Path(__file__).parent
    json_path = script_dir / "affiliate_campaigns.json"

    if not json_path.exists():
        print(f"ERROR: {json_path} が見つかりません")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("campaigns", [])


# ========================================
# キャンペーン選択（順番方式）
# ========================================
def get_next_campaign_index(total: int) -> int:
    """次に配信するキャンペーンのインデックスを取得（順番方式）"""
    script_dir = Path(__file__).parent
    index_file = script_dir / CAMPAIGN_INDEX_FILE

    current_index = 0
    if index_file.exists():
        try:
            current_index = int(index_file.read_text().strip())
        except ValueError:
            current_index = 0

    # 次のインデックスを保存
    next_index = (current_index + 1) % total
    index_file.write_text(str(next_index))

    return current_index


def select_campaign(campaigns: list, use_random: bool = False) -> dict:
    """キャンペーンを選択（順番 or ランダム）"""
    if not campaigns:
        print("ERROR: キャンペーンが登録されていません")
        sys.exit(1)

    if use_random:
        return random.choice(campaigns)
    else:
        index = get_next_campaign_index(len(campaigns))
        return campaigns[index]


# ========================================
# メッセージ生成
# ========================================
def build_message(campaign: dict) -> str:
    """配信メッセージを構築"""
    template = campaign.get("template", "")
    link_placeholder = campaign.get("link", "")

    # 環境変数からアフィリエイトリンクを取得
    actual_link = link_placeholder
    if link_placeholder in AFFILIATE_LINK_ENV_MAP:
        env_name = AFFILIATE_LINK_ENV_MAP[link_placeholder]
        actual_link = os.environ.get(env_name, link_placeholder)

    # テンプレートのプレースホルダーを置換
    message = template.replace("{{LINK}}", actual_link)

    # 冒頭に挨拶を追加
    greeting = "皆さん、カツミです\n\n"
    full_message = greeting + message

    return full_message


# ========================================
# LINE Messaging API
# ========================================
def send_broadcast(message: str) -> bool:
    """LINE broadcast で全フォロワーに配信"""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("ERROR: LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
        return False

    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "messages": [
            {
                "type": "text",
                "text": message,
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)

        if response.status_code == 200:
            print("SUCCESS: broadcast 配信完了")
            return True
        else:
            print(f"ERROR: broadcast 失敗 - status={response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"ERROR: broadcast 送信エラー - {e}")
        return False


def send_test_log(message: str):
    """テストモード: ログ出力のみ"""
    print("=" * 50)
    print("[TEST MODE] 以下のメッセージを配信予定:")
    print("=" * 50)
    print(message)
    print("=" * 50)
    print("[TEST MODE] 実際の配信はスキップしました")


# ========================================
# メイン処理
# ========================================
def main():
    print(f"LINE アフィリエイト配信スクリプト開始")
    print(f"  日時: {datetime.now().isoformat()}")
    print(f"  テストモード: {TEST_MODE}")
    print()

    # キャンペーンデータ読み込み
    campaigns = load_campaigns()
    print(f"  登録キャンペーン数: {len(campaigns)}")

    # キャンペーン選択（順番方式）
    campaign = select_campaign(campaigns, use_random=False)
    print(f"  選択キャンペーン: {campaign.get('id')} ({campaign.get('category')})")
    print()

    # メッセージ生成
    message = build_message(campaign)

    # 配信
    if TEST_MODE:
        send_test_log(message)
    else:
        success = send_broadcast(message)
        if not success:
            sys.exit(1)

    print()
    print("LINE アフィリエイト配信スクリプト完了")


if __name__ == "__main__":
    main()
