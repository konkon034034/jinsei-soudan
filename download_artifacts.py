#!/usr/bin/env python3
"""
GitHub Artifacts自動ダウンローダー

定期実行して新しいArtifactsをローカルにダウンロードする。
launchd/cronで5分ごとに実行することを想定。

使用方法:
    python download_artifacts.py

設定:
    - GITHUB_TOKEN環境変数が必要
    - ダウンロード済みはdownloaded_artifacts.jsonで管理
"""

import os
import sys
import json
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

# 設定
REPO = "konkon034034/jinsei-soudan"
DOWNLOAD_DIR = Path.home() / "jinsei-soudan" / "artifacts_downloads"
STATE_FILE = Path.home() / "jinsei-soudan" / "downloaded_artifacts.json"

# ダウンロード対象のArtifact名パターン
TARGET_PATTERNS = [
    "nenkin-news-",      # 年金ニュース（横動画）
    "nenkin-short-",     # 年金ショート
    "senior-kuchikomi-", # シニア口コミ
    "company-kuchikomi-", # 会社口コミ
    "asadora-ranking-",  # 朝ドラランキング
]


def load_downloaded_state():
    """ダウンロード済みIDを読み込み"""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"downloaded": []}


def save_downloaded_state(state):
    """ダウンロード済みIDを保存"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_recent_artifacts():
    """最新のArtifactsを取得"""
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{REPO}/actions/artifacts"],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        return data.get("artifacts", [])
    except subprocess.CalledProcessError as e:
        print(f"❌ Artifacts取得エラー: {e.stderr}")
        return []
    except json.JSONDecodeError as e:
        print(f"❌ JSONパースエラー: {e}")
        return []


def should_download(artifact_name):
    """ダウンロード対象かチェック"""
    for pattern in TARGET_PATTERNS:
        if artifact_name.startswith(pattern):
            return True
    return False


def download_artifact(artifact_id, artifact_name, run_id):
    """Artifactをダウンロード"""
    # 日付フォルダを作成
    today = datetime.now().strftime("%Y%m%d")
    # Artifact名をサブフォルダ名として使用（ファイル名競合を回避）
    target_dir = DOWNLOAD_DIR / today / artifact_name
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        # gh run downloadを使用
        subprocess.run(
            [
                "gh", "run", "download", str(run_id),
                "-n", artifact_name,
                "-D", str(target_dir),
                "-R", REPO,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"✅ ダウンロード完了: {artifact_name}")
        print(f"   保存先: {target_dir}")

        # mp4ファイルを一覧表示
        for mp4 in target_dir.glob("**/*.mp4"):
            print(f"   📹 {mp4.name}")

        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ ダウンロードエラー: {artifact_name}")
        print(f"   {e.stderr}")
        return False


def main():
    print("=" * 50)
    print("GitHub Artifacts自動ダウンローダー")
    print(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # 状態読み込み
    state = load_downloaded_state()
    downloaded_ids = set(state.get("downloaded", []))

    # Artifacts取得
    artifacts = get_recent_artifacts()
    print(f"📦 取得したArtifacts数: {len(artifacts)}")

    new_downloads = 0

    for artifact in artifacts:
        artifact_id = artifact["id"]
        artifact_name = artifact["name"]
        run_id = artifact["workflow_run"]["id"]

        # すでにダウンロード済みならスキップ
        if artifact_id in downloaded_ids:
            continue

        # 対象パターンにマッチするかチェック
        if not should_download(artifact_name):
            continue

        # 期限切れチェック
        if artifact.get("expired", False):
            print(f"⏰ 期限切れ: {artifact_name}")
            continue

        print(f"\n🆕 新しいArtifact発見: {artifact_name}")
        print(f"   Run ID: {run_id}")

        # ダウンロード実行
        if download_artifact(artifact_id, artifact_name, run_id):
            downloaded_ids.add(artifact_id)
            new_downloads += 1

    # 状態保存（最新1000件のみ保持）
    state["downloaded"] = list(downloaded_ids)[-1000:]
    state["last_check"] = datetime.now().isoformat()
    save_downloaded_state(state)

    print(f"\n{'=' * 50}")
    print(f"📥 新規ダウンロード: {new_downloads}件")
    print(f"📂 保存先: {DOWNLOAD_DIR}")

    return new_downloads


if __name__ == "__main__":
    try:
        new_count = main()
        sys.exit(0 if new_count >= 0 else 1)
    except KeyboardInterrupt:
        print("\n中断されました")
        sys.exit(1)
    except Exception as e:
        print(f"❌ エラー: {e}")
        sys.exit(1)
