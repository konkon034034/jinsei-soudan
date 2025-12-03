#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Slack通知モジュール
台本生成完了時にSlackへ通知し、承認ワークフローを実現

使用ライブラリ:
- slack_sdk: Bot Token経由の通知・ファイルアップロード
- requests: Webhook経由の通知
"""

from dotenv import load_dotenv
load_dotenv()

import os
import json
import requests
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

# slack_sdk（オプション）
try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
    SLACK_SDK_AVAILABLE = True
except ImportError:
    SLACK_SDK_AVAILABLE = False
    print("⚠️ slack_sdk がインストールされていません。pip install slack_sdk でインストールしてください")


# 環境変数
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')
SLACK_BOT_TOKEN = os.getenv('SLACK_BOT_TOKEN')
SLACK_CHANNEL_ID = os.getenv('SLACK_CHANNEL_ID')


def extract_dialogue_preview(script: str, num_exchanges: int = 3) -> str:
    """
    台本から冒頭の対話を抽出

    Args:
        script: 台本テキスト
        num_exchanges: 抽出する往復数（デフォルト3往復 = 6行）

    Returns:
        抽出された対話テキスト
    """
    lines = script.strip().split('\n')
    dialogue_lines = []

    for line in lines:
        line = line.strip()
        # 「キャラ名：セリフ」または「キャラ名:セリフ」形式を検出
        if '：' in line or ':' in line:
            dialogue_lines.append(line)
            if len(dialogue_lines) >= num_exchanges * 2:
                break

    if dialogue_lines:
        return '\n'.join(dialogue_lines)
    else:
        # 対話形式でない場合は冒頭500文字
        return script[:500] + "..." if len(script) > 500 else script


def extract_consulter_info(consultation: str) -> str:
    """
    相談内容から相談者情報を抽出

    Args:
        consultation: 相談内容テキスト

    Returns:
        相談者情報（年齢/性別/家族構成など）
    """
    if not consultation:
        return "情報なし"

    # 「相談者:」または「相談者：」の行を探す
    for line in consultation.split('\n'):
        line = line.strip()
        if line.startswith('相談者:') or line.startswith('相談者：'):
            info = line.replace('相談者:', '').replace('相談者：', '').strip()
            return info if info else "情報なし"

    return "情報なし"


def format_summary(summary: str, max_lines: int = 3) -> str:
    """
    要約を整形（箇条書き形式）

    Args:
        summary: 要約テキスト
        max_lines: 最大行数

    Returns:
        整形された要約
    """
    if not summary:
        return "要約なし"

    # 句点で分割
    sentences = [s.strip() for s in summary.split('。') if s.strip()]

    if sentences:
        formatted = '\n'.join([f"• {s}。" for s in sentences[:max_lines]])
        return formatted
    else:
        return summary[:200]


def create_notification_blocks(
    consulter_info: str,
    theme: str,
    summary: str,
    script_preview: str,
    char_count: int,
    spreadsheet_url: str,
    row_num: int = 0
) -> list:
    """
    Slack Block Kit形式の通知ブロックを作成

    Args:
        consulter_info: 相談者情報
        theme: テーマ/タイトル
        summary: 要約
        script_preview: 台本プレビュー
        char_count: 文字数
        spreadsheet_url: スプレッドシートURL
        row_num: 行番号（ボタンのvalue用）

    Returns:
        Block Kit形式のリスト
    """
    blocks = [
        # ヘッダー
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📝 台本生成完了",
                "emoji": True
            }
        },
        # 相談者情報 & テーマ
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*👤 相談者情報*\n{consulter_info}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*🏷️ テーマ*\n{theme[:50]}{'...' if len(theme) > 50 else ''}"
                }
            ]
        },
        # 要約
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*📋 要約*\n{summary}"
            }
        },
        {"type": "divider"},
        # 台本プレビュー
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*💬 台本プレビュー（冒頭3往復）*\n```{script_preview[:1000]}```"
            }
        },
        # 文字数 & 生成日時
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*📊 文字数*\n{char_count:,}文字"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*📅 生成日時*\n{datetime.now().strftime('%Y/%m/%d %H:%M')}"
                }
            ]
        },
        # スプレッドシートリンク
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"📄 *<{spreadsheet_url}|スプレッドシートで全文を確認>*"
            }
        },
        {"type": "divider"},
        # 承認ボタン（Interactive Components）
        {
            "type": "actions",
            "block_id": f"script_approval_{row_num}",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "🟢 OK",
                        "emoji": True
                    },
                    "style": "primary",
                    "value": json.dumps({"action": "approve", "row": row_num}),
                    "action_id": "approve_script"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "🟡 修正",
                        "emoji": True
                    },
                    "value": json.dumps({"action": "revise", "row": row_num}),
                    "action_id": "revise_script"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "🔴 ボツ",
                        "emoji": True
                    },
                    "style": "danger",
                    "value": json.dumps({"action": "reject", "row": row_num}),
                    "action_id": "reject_script"
                }
            ]
        }
    ]

    return blocks


def send_via_webhook(blocks: list, text: str = "台本生成完了") -> bool:
    """
    Incoming Webhook経由で通知を送信

    ※ WebhookではInteractive Componentsのボタンクリックは受け取れません
    　 ボタンを使う場合はBot Token + Slack Appが必要です

    Args:
        blocks: Block Kit形式のブロック
        text: フォールバックテキスト

    Returns:
        送信成功/失敗
    """
    if not SLACK_WEBHOOK_URL:
        print("⚠️ SLACK_WEBHOOK_URL が設定されていません")
        return False

    payload = {
        "text": text,
        "blocks": blocks
    }

    try:
        response = requests.post(
            SLACK_WEBHOOK_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        if response.status_code == 200:
            print("✅ Slack通知送信成功（Webhook）")
            return True
        else:
            print(f"❌ Slack通知失敗: {response.status_code} - {response.text}")
            return False

    except requests.exceptions.Timeout:
        print("❌ Slack通知タイムアウト")
        return False
    except Exception as e:
        print(f"❌ Slack通知エラー: {e}")
        return False


def send_via_bot(
    blocks: list,
    text: str = "台本生成完了",
    thumbnail_path: Optional[Path] = None
) -> bool:
    """
    Bot Token経由で通知を送信（slack_sdk使用）

    Args:
        blocks: Block Kit形式のブロック
        text: フォールバックテキスト
        thumbnail_path: サムネイル画像のパス（オプション）

    Returns:
        送信成功/失敗
    """
    if not SLACK_SDK_AVAILABLE:
        print("⚠️ slack_sdk が利用できません")
        return False

    if not SLACK_BOT_TOKEN or not SLACK_CHANNEL_ID:
        print("⚠️ SLACK_BOT_TOKEN または SLACK_CHANNEL_ID が設定されていません")
        return False

    try:
        client = WebClient(token=SLACK_BOT_TOKEN)

        # メッセージ送信
        response = client.chat_postMessage(
            channel=SLACK_CHANNEL_ID,
            text=text,
            blocks=blocks
        )

        if response["ok"]:
            print("✅ Slack通知送信成功（Bot）")
            message_ts = response["ts"]

            # サムネイル画像がある場合はスレッドに添付
            if thumbnail_path and thumbnail_path.exists():
                try:
                    client.files_upload_v2(
                        channel=SLACK_CHANNEL_ID,
                        file=str(thumbnail_path),
                        title="サムネイル画像",
                        initial_comment="📷 サムネイル候補",
                        thread_ts=message_ts
                    )
                    print("✅ サムネイル画像アップロード成功")
                except SlackApiError as e:
                    print(f"⚠️ サムネイル画像アップロード失敗: {e.response['error']}")

            return True
        else:
            print(f"❌ Slack通知失敗: {response.get('error', 'Unknown error')}")
            return False

    except SlackApiError as e:
        print(f"❌ Slack API エラー: {e.response['error']}")
        return False
    except Exception as e:
        print(f"❌ Slack通知エラー: {e}")
        return False


def notify_script_complete(
    source_info: Dict,
    script: str,
    metadata: Dict,
    row_num: int,
    spreadsheet_id: str,
    thumbnail_path: Optional[Path] = None
) -> bool:
    """
    台本生成完了通知を送信

    Args:
        source_info: 元動画情報
            - title: タイトル
            - summary: 要約
            - consultation: 相談内容
        script: 生成された台本
        metadata: メタデータ
            - title: YouTube動画タイトル
            - description: 説明文
            - tags: タグリスト
        row_num: スプレッドシートの行番号
        spreadsheet_id: スプレッドシートID
        thumbnail_path: サムネイル画像のパス（オプション）

    Returns:
        送信成功/失敗
    """
    # 相談者情報
    consultation = source_info.get('consultation', '')
    consulter_info = extract_consulter_info(consultation)

    # テーマ
    theme = metadata.get('title', source_info.get('title', 'テーマ不明'))

    # 要約（3行に整形）
    summary = source_info.get('summary', '')
    summary_formatted = format_summary(summary, max_lines=3)

    # 台本プレビュー（冒頭3往復）
    script_preview = extract_dialogue_preview(script, num_exchanges=3)

    # 文字数
    char_count = len(script)

    # スプレッドシートURL（F列=台本にジャンプ）
    spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid=0&range=F{row_num}"

    # Block Kit形式のブロックを作成
    blocks = create_notification_blocks(
        consulter_info=consulter_info,
        theme=theme,
        summary=summary_formatted,
        script_preview=script_preview,
        char_count=char_count,
        spreadsheet_url=spreadsheet_url,
        row_num=row_num
    )

    # 送信方法を選択（Bot優先）
    if SLACK_BOT_TOKEN and SLACK_CHANNEL_ID and SLACK_SDK_AVAILABLE:
        return send_via_bot(blocks, thumbnail_path=thumbnail_path)
    elif SLACK_WEBHOOK_URL:
        return send_via_webhook(blocks)
    else:
        print("⚠️ Slack通知の設定がありません")
        print("  SLACK_WEBHOOK_URL または SLACK_BOT_TOKEN + SLACK_CHANNEL_ID を設定してください")
        return False


# ============================================================
# テスト実行
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("🔔 Slack通知モジュール テスト")
    print("=" * 60)

    # 環境変数チェック
    print("\n📋 環境変数チェック:")
    print(f"  SLACK_WEBHOOK_URL: {'✅ 設定済み' if SLACK_WEBHOOK_URL else '❌ 未設定'}")
    print(f"  SLACK_BOT_TOKEN:   {'✅ 設定済み' if SLACK_BOT_TOKEN else '❌ 未設定'}")
    print(f"  SLACK_CHANNEL_ID:  {'✅ 設定済み' if SLACK_CHANNEL_ID else '❌ 未設定'}")
    print(f"  slack_sdk:         {'✅ インストール済み' if SLACK_SDK_AVAILABLE else '❌ 未インストール'}")

    # テストデータ
    test_source_info = {
        "title": "【人生相談】30代独身、このまま結婚できないのか不安です",
        "summary": "30代女性からの相談。仕事は順調だが恋愛がうまくいかない。周りは結婚していく中で焦りを感じている。婚活アプリも試したが良い出会いがない。",
        "consultation": """
相談者: 32歳女性、会社員、一人暮らし
相談内容:
仕事は順調で、昇進も決まりました。でも恋愛がうまくいきません。
学生時代から付き合った人はいましたが、長続きせず...
友人たちが次々と結婚していく中、私だけ取り残されている気がします。
"""
    }

    test_script = """
ミサキ：こんにちは！今日も人生相談にお答えしていきましょう！
アヤネ：はい、今回は30代女性からのご相談ですね。
ミサキ：仕事は順調なのに、恋愛がうまくいかないというお悩み。
アヤネ：よくあるパターンですね。まずは現状を整理しましょう。
ミサキ：そうですね、焦る気持ちはとてもよく分かります。
アヤネ：でも、焦りすぎると逆効果になることもありますよね。
ミサキ：まず大切なのは、自分自身を大切にすることだと思います。
アヤネ：その通り。仕事で成果を出しているということは、素晴らしい強みですよね。
"""

    test_metadata = {
        "title": "【人生相談】30代独身女性の恋愛の悩み｜仕事は順調なのに結婚できない..."
    }

    print("\n📝 テストデータ:")
    print(f"  テーマ: {test_metadata['title'][:40]}...")
    print(f"  台本文字数: {len(test_script)}文字")

    # 通知テスト
    if SLACK_WEBHOOK_URL or (SLACK_BOT_TOKEN and SLACK_CHANNEL_ID):
        print("\n🚀 通知を送信中...")
        result = notify_script_complete(
            source_info=test_source_info,
            script=test_script,
            metadata=test_metadata,
            row_num=2,
            spreadsheet_id="15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo"
        )
        print(f"\n結果: {'✅ 成功' if result else '❌ 失敗'}")
    else:
        print("\n⚠️ Slack通知の設定がありません")
        print("  .env に以下を設定してください:")
        print("  - SLACK_WEBHOOK_URL（Webhook使用の場合）")
        print("  - SLACK_BOT_TOKEN + SLACK_CHANNEL_ID（Bot使用の場合）")
