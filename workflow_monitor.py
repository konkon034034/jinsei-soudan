#!/usr/bin/env python3
"""
GitHub Actions ワークフロー監視システム

毎日22:00 JSTに実行し、全チャンネルのワークフローが正常に実行されたかチェック。
異常があればDiscordに通知。
"""

import os
import json
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Optional
import requests

# 日本時間
JST = timezone(timedelta(hours=9))

# 監視対象ワークフロー設定
# key: ワークフローファイル名, value: (表示名, 期待実行時刻リスト(JST))
MONITORED_WORKFLOWS = {
    # 年金ニュースチャンネル
    "nenkin_news.yml": ("年金ニュース動画", ["11:00"]),
    "nenkin_short_v2.yml": ("年金ショート動画", ["10:00", "15:00"]),
    "nenkin_ranking.yml": ("年金ランキング動画", ["19:00"]),
    # 口コミランキングチャンネル
    "senior_kuchikomi_ranking.yml": ("シニア口コミランキング", ["07:00"]),
    "company_kuchikomi_ranking.yml": ("会社口コミランキング", ["08:00"]),
}

# リポジトリ設定
REPO = "konkon034034/jinsei-soudan"


def get_workflow_runs(workflow_file: str, hours: int = 24) -> list:
    """
    GitHub CLIを使用してワークフローの実行履歴を取得

    Args:
        workflow_file: ワークフローファイル名（例: nenkin_news.yml）
        hours: 過去何時間分を取得するか

    Returns:
        実行履歴のリスト
    """
    try:
        # gh api を使用してワークフロー実行履歴を取得
        result = subprocess.run(
            [
                "gh", "api",
                f"repos/{REPO}/actions/workflows/{workflow_file}/runs",
                "--jq", ".workflow_runs[:10]"
            ],
            capture_output=True,
            text=True,
            check=True
        )
        runs = json.loads(result.stdout)

        # 指定時間内の実行のみフィルタ
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent_runs = []
        for run in runs:
            created_at = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
            if created_at > cutoff:
                recent_runs.append(run)

        return recent_runs
    except subprocess.CalledProcessError as e:
        print(f"Error fetching runs for {workflow_file}: {e.stderr}")
        return []
    except json.JSONDecodeError:
        print(f"Error parsing JSON for {workflow_file}")
        return []


def check_workflow_status(workflow_file: str, display_name: str, expected_times: list) -> dict:
    """
    ワークフローのステータスをチェック

    Returns:
        {
            "name": 表示名,
            "status": "success" | "failure" | "missing" | "in_progress",
            "runs": [実行情報リスト],
            "issues": [問題リスト]
        }
    """
    runs = get_workflow_runs(workflow_file)

    result = {
        "name": display_name,
        "workflow_file": workflow_file,
        "status": "success",
        "runs": [],
        "issues": []
    }

    if not runs:
        result["status"] = "missing"
        result["issues"].append(f"過去24時間に実行がありません（期待: {', '.join(expected_times)} JST）")
        return result

    # スケジュール実行のみを対象（workflow_dispatchは除外しない）
    schedule_runs = [r for r in runs if r.get("event") in ["schedule", "workflow_dispatch"]]

    for run in schedule_runs:
        run_info = {
            "id": run["id"],
            "status": run["status"],
            "conclusion": run.get("conclusion"),
            "created_at": run["created_at"],
            "html_url": run["html_url"],
            "event": run["event"]
        }
        result["runs"].append(run_info)

        # 失敗チェック
        if run["status"] == "completed":
            if run.get("conclusion") == "failure":
                result["status"] = "failure"
                created_jst = datetime.fromisoformat(
                    run["created_at"].replace("Z", "+00:00")
                ).astimezone(JST).strftime("%H:%M")
                result["issues"].append(
                    f"実行失敗 ({created_jst} JST): {run['html_url']}"
                )
            elif run.get("conclusion") == "cancelled":
                if result["status"] != "failure":
                    result["status"] = "cancelled"
                created_jst = datetime.fromisoformat(
                    run["created_at"].replace("Z", "+00:00")
                ).astimezone(JST).strftime("%H:%M")
                result["issues"].append(
                    f"キャンセル ({created_jst} JST): {run['html_url']}"
                )
        elif run["status"] == "in_progress":
            if result["status"] not in ["failure", "cancelled"]:
                result["status"] = "in_progress"

    # 期待される実行回数との比較
    successful_runs = [
        r for r in schedule_runs
        if r["status"] == "completed" and r.get("conclusion") == "success"
    ]

    if len(successful_runs) < len(expected_times):
        if result["status"] == "success" and len(schedule_runs) < len(expected_times):
            result["status"] = "missing"
            result["issues"].append(
                f"実行回数不足: {len(successful_runs)}/{len(expected_times)} "
                f"(期待: {', '.join(expected_times)} JST)"
            )

    return result


def send_discord_notification(webhook_url: str, results: list) -> bool:
    """
    Discord Webhookで通知を送信

    Args:
        webhook_url: Discord Webhook URL
        results: チェック結果リスト

    Returns:
        送信成功かどうか
    """
    # 全体ステータス判定
    has_issues = any(r["status"] != "success" for r in results)

    now_jst = datetime.now(JST).strftime("%Y-%m-%d %H:%M")

    if has_issues:
        # 問題あり
        content_lines = [
            "❌ **ワークフロー監視レポート**",
            f"📅 {now_jst} JST",
            "━━━━━━━━━━━━━━━━━━",
            ""
        ]

        for result in results:
            if result["status"] == "success":
                content_lines.append(f"✅ {result['name']}")
            elif result["status"] == "failure":
                content_lines.append(f"❌ {result['name']}")
                for issue in result["issues"]:
                    content_lines.append(f"   └ {issue}")
            elif result["status"] == "missing":
                content_lines.append(f"⚠️ {result['name']}")
                for issue in result["issues"]:
                    content_lines.append(f"   └ {issue}")
            elif result["status"] == "cancelled":
                content_lines.append(f"🚫 {result['name']}")
                for issue in result["issues"]:
                    content_lines.append(f"   └ {issue}")
            elif result["status"] == "in_progress":
                content_lines.append(f"🔄 {result['name']} (実行中)")

        content_lines.append("")
        content_lines.append("━━━━━━━━━━━━━━━━━━")
    else:
        # 全て正常
        content_lines = [
            "✅ **ワークフロー監視レポート**",
            f"📅 {now_jst} JST",
            "━━━━━━━━━━━━━━━━━━",
            "",
            "全ワークフロー正常実行",
            ""
        ]
        for result in results:
            success_count = len([
                r for r in result["runs"]
                if r["status"] == "completed" and r["conclusion"] == "success"
            ])
            content_lines.append(f"✅ {result['name']} ({success_count}回成功)")

        content_lines.append("")
        content_lines.append("━━━━━━━━━━━━━━━━━━")

    content = "\n".join(content_lines)

    # Discord Webhook送信
    try:
        response = requests.post(
            webhook_url,
            json={"content": content},
            timeout=10
        )
        response.raise_for_status()
        print("Discord通知を送信しました")
        return True
    except requests.RequestException as e:
        print(f"Discord通知の送信に失敗: {e}")
        return False


def main():
    """メイン処理"""
    print("=" * 50)
    print("GitHub Actions ワークフロー監視")
    print("=" * 50)
    print()

    # Discord Webhook URL取得
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("⚠️ DISCORD_WEBHOOK_URL が設定されていません")
        print("環境変数を設定してください")

    # 各ワークフローをチェック
    results = []
    for workflow_file, (display_name, expected_times) in MONITORED_WORKFLOWS.items():
        print(f"チェック中: {display_name} ({workflow_file})")
        result = check_workflow_status(workflow_file, display_name, expected_times)
        results.append(result)

        # 結果表示
        status_icon = {
            "success": "✅",
            "failure": "❌",
            "missing": "⚠️",
            "cancelled": "🚫",
            "in_progress": "🔄"
        }.get(result["status"], "❓")

        print(f"  {status_icon} ステータス: {result['status']}")
        if result["issues"]:
            for issue in result["issues"]:
                print(f"     └ {issue}")
        print()

    # サマリー
    print("=" * 50)
    print("サマリー:")
    success_count = sum(1 for r in results if r["status"] == "success")
    total_count = len(results)
    print(f"  正常: {success_count}/{total_count}")

    has_issues = any(r["status"] != "success" for r in results)
    if has_issues:
        print("  ⚠️ 問題が検出されました")
    else:
        print("  ✅ 全て正常")
    print()

    # Discord通知
    if webhook_url:
        send_discord_notification(webhook_url, results)
    else:
        print("Discord通知をスキップ（Webhook URLなし）")

    # 終了コード（問題があれば1）
    return 1 if has_issues else 0


if __name__ == "__main__":
    exit(main())
