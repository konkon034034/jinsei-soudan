#!/bin/bash
# Artifacts自動ダウンロードのセットアップスクリプト

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_DIR="$HOME/jinsei-soudan"
PLIST_NAME="com.jinsei-soudan.download-artifacts.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

echo "=================================="
echo "Artifacts自動ダウンロード セットアップ"
echo "=================================="

# ログディレクトリ作成
mkdir -p "$TARGET_DIR/logs"
mkdir -p "$TARGET_DIR/artifacts_downloads"

# スクリプトをコピー（同一ファイルの場合はスキップ）
echo "📦 スクリプトをコピー中..."
if [ "$SCRIPT_DIR" != "$TARGET_DIR" ]; then
    cp "$SCRIPT_DIR/download_artifacts.py" "$TARGET_DIR/"
fi
chmod +x "$TARGET_DIR/download_artifacts.py"

# plistをコピー
echo "⚙️ launchd設定をインストール中..."
mkdir -p "$LAUNCH_AGENTS_DIR"
if [ "$SCRIPT_DIR" != "$TARGET_DIR" ]; then
    cp "$SCRIPT_DIR/$PLIST_NAME" "$LAUNCH_AGENTS_DIR/"
else
    cp "$TARGET_DIR/$PLIST_NAME" "$LAUNCH_AGENTS_DIR/"
fi

# 既存のジョブを停止（エラーは無視）
launchctl unload "$LAUNCH_AGENTS_DIR/$PLIST_NAME" 2>/dev/null || true

# 新しいジョブを開始
launchctl load "$LAUNCH_AGENTS_DIR/$PLIST_NAME"

echo ""
echo "✅ セットアップ完了！"
echo ""
echo "📂 ダウンロード先: $TARGET_DIR/artifacts_downloads/"
echo "📋 ログファイル: $TARGET_DIR/logs/download_artifacts.log"
echo "⏰ 実行間隔: 5分ごと"
echo ""
echo "手動実行: python3 $TARGET_DIR/download_artifacts.py"
echo "停止: launchctl unload $LAUNCH_AGENTS_DIR/$PLIST_NAME"
echo "開始: launchctl load $LAUNCH_AGENTS_DIR/$PLIST_NAME"
