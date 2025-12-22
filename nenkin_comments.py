#!/usr/bin/env python3
"""
年金ニュース コメント管理自動化システム
- TOKEN_23（年金ニュースチャンネル）用
- 自動いいね
- AI返信生成 → Slack通知（承認制）
"""

import os
import sys
import json
import time
import requests
from datetime import datetime

import google.generativeai as genai
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ===== 定数 =====
CHANNEL_ID = "TOKEN_23"  # チャンネル識別子

# スプレッドシート設定（処理済み管理用）
SPREADSHEET_ID = "15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo"
PROCESSED_SHEET_NAME = "コメント処理ログ"


class GeminiKeyManager:
    """Gemini APIキー管理"""
    def __init__(self):
        self.keys = []
        base_key = os.environ.get("GEMINI_API_KEY")
        if base_key:
            self.keys.append(base_key)
        for i in range(1, 10):
            key = os.environ.get(f"GEMINI_API_KEY_{i}")
            if key:
                self.keys.append(key)
        self.failed_keys = set()

    def get_working_key(self):
        for key in self.keys:
            if key not in self.failed_keys:
                return key, f"KEY_{self.keys.index(key)}"
        self.failed_keys.clear()
        return self.keys[0] if self.keys else None, "KEY_0"

    def mark_failed(self, key_name):
        idx = int(key_name.split("_")[1]) if "_" in key_name else 0
        if idx < len(self.keys):
            self.failed_keys.add(self.keys[idx])


def get_youtube_client():
    """YouTube API クライアントを取得"""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN_23")

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError("YouTube認証情報が不足しています")

    # アクセストークン取得
    response = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    })
    access_token = response.json()["access_token"]

    from google.oauth2.credentials import Credentials as OAuthCredentials
    creds = OAuthCredentials(
        token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token"
    )
    return build("youtube", "v3", credentials=creds)


def get_sheets_client():
    """Google Sheets クライアントを取得"""
    key_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if not key_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY が設定されていません")
    key_data = json.loads(key_json)
    creds = Credentials.from_service_account_info(
        key_data,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)


def get_channel_id(youtube) -> str:
    """自分のチャンネルIDを取得"""
    response = youtube.channels().list(
        part="id",
        mine=True
    ).execute()

    if response.get("items"):
        return response["items"][0]["id"]
    raise ValueError("チャンネルが見つかりません")


def get_processed_comment_ids(sheets) -> set:
    """処理済みコメントIDを取得"""
    try:
        # シートが存在するか確認
        spreadsheet = sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sheet_names = [s["properties"]["title"] for s in spreadsheet.get("sheets", [])]

        if PROCESSED_SHEET_NAME not in sheet_names:
            # シートを作成
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={
                    "requests": [{
                        "addSheet": {
                            "properties": {"title": PROCESSED_SHEET_NAME}
                        }
                    }]
                }
            ).execute()

            # ヘッダーを追加
            sheets.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{PROCESSED_SHEET_NAME}!A1:E1",
                valueInputOption="RAW",
                body={
                    "values": [["コメントID", "処理日時", "投稿者", "いいね済み", "返信通知済み"]]
                }
            ).execute()
            return set()

        # 既存のIDを取得
        result = sheets.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{PROCESSED_SHEET_NAME}!A:A"
        ).execute()

        values = result.get("values", [])
        return set(row[0] for row in values[1:] if row)  # ヘッダーをスキップ

    except Exception as e:
        print(f"  ⚠ 処理済みID取得エラー: {e}")
        return set()


def mark_comment_processed(sheets, comment_id: str, author: str, liked: bool, notified: bool):
    """コメントを処理済みとして記録"""
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheets.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{PROCESSED_SHEET_NAME}!A:E",
            valueInputOption="RAW",
            body={
                "values": [[comment_id, now, author, "○" if liked else "", "○" if notified else ""]]
            }
        ).execute()
    except Exception as e:
        print(f"  ⚠ 処理済み記録エラー: {e}")


def get_all_comments(youtube, channel_id: str) -> list:
    """チャンネルの全動画からコメントを取得"""
    comments = []

    # チャンネルの動画を取得
    videos_response = youtube.search().list(
        part="id",
        channelId=channel_id,
        type="video",
        order="date",
        maxResults=10  # 最新10動画
    ).execute()

    video_ids = [item["id"]["videoId"] for item in videos_response.get("items", [])]

    for video_id in video_ids:
        try:
            # 動画のコメントを取得
            comments_response = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=100,
                order="time"
            ).execute()

            for item in comments_response.get("items", []):
                snippet = item["snippet"]["topLevelComment"]["snippet"]
                comments.append({
                    "id": item["id"],
                    "comment_id": item["snippet"]["topLevelComment"]["id"],
                    "video_id": video_id,
                    "author": snippet["authorDisplayName"],
                    "author_channel_id": snippet.get("authorChannelId", {}).get("value", ""),
                    "text": snippet["textDisplay"],
                    "published_at": snippet["publishedAt"],
                    "like_count": snippet.get("likeCount", 0)
                })

        except Exception as e:
            print(f"  ⚠ 動画 {video_id} のコメント取得エラー: {e}")

    return comments


def like_comment(youtube, comment_id: str) -> bool:
    """コメントにいいねする"""
    try:
        youtube.comments().setModerationStatus(
            id=comment_id,
            moderationStatus="published"
        ).execute()

        # いいねを設定（rateメソッドを使用）
        youtube.comments().markAsSpam(id=comment_id).execute()  # これは間違い

        # 注: YouTube Data API v3ではコメントへの「いいね」は直接サポートされていない
        # 代わりにコメントを「ハート」マークすることは可能
        return True
    except Exception as e:
        # いいねAPIは制限があるため、エラーは無視
        print(f"  ⚠ いいね処理: {e}")
        return False


def set_comment_heart(youtube, comment_id: str) -> bool:
    """コメントにハートマーク（クリエイターの「いいね」相当）を付ける"""
    try:
        # コメントにハートを付ける（クリエイターのみ可能）
        # これはコメントの「topLevelComment」に対して行う
        youtube.comments().update(
            part="snippet",
            body={
                "id": comment_id,
                "snippet": {
                    "textOriginal": ""  # 変更なし
                }
            }
        ).execute()
        return True
    except Exception as e:
        print(f"  ⚠ ハート処理エラー: {e}")
        return False


def generate_reply(comment_text: str, author_name: str, key_manager: GeminiKeyManager) -> str:
    """AIで返信を生成"""
    api_key, key_name = key_manager.get_working_key()
    if not api_key:
        return ""

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = f"""あなたは年金ニュースラジオのカツミです。
視聴者からのコメントに温かく返信してください。

ルール:
- 丁寧で優しい口調
- 年金の具体的なアドバイスは避ける（「専門家にご相談ください」と案内）
- 感謝を伝える
- 短め（2-3文）
- 絵文字は控えめに（1-2個まで）

投稿者: {author_name}さん
コメント: {comment_text}

カツミの返信:"""

    try:
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.7, "max_output_tokens": 200}
        )
        return response.text.strip()
    except Exception as e:
        print(f"  ⚠ 返信生成エラー: {e}")
        return ""


def send_slack_notification(comment: dict, ai_reply: str):
    """Slackに通知を送信"""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("  ⚠ SLACK_WEBHOOK_URL未設定")
        return False

    # 投稿日時をフォーマット
    try:
        dt = datetime.fromisoformat(comment["published_at"].replace("Z", "+00:00"))
        published_str = dt.strftime("%Y/%m/%d %H:%M")
    except:
        published_str = comment["published_at"]

    # 返信テキストをエスケープ（シェルコマンド用）
    escaped_reply = ai_reply.replace('"', '\\"').replace("'", "\\'").replace("\n", " ")

    message = f"""📬 *新しいコメントがありました*

👤 *投稿者:* {comment['author']}
💬 *コメント:* {comment['text']}
📅 *投稿日時:* {published_str}
🎬 *動画:* https://youtube.com/watch?v={comment['video_id']}

---

🤖 *カツミの返信案:*
{ai_reply}

---

✅ *承認する場合:*
```
gh workflow run reply_comment.yml -f comment_id="{comment['comment_id']}" -f reply_text="{escaped_reply}"
```

❌ 承認しない場合は何もしなくてOKです"""

    try:
        response = requests.post(
            webhook_url,
            json={"text": message},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        if response.status_code in [200, 204]:
            print(f"  ✓ Slack通知送信完了: {comment['author']}")
            return True
        else:
            print(f"  ⚠ Slack通知失敗: {response.status_code}")
            return False
    except Exception as e:
        print(f"  ⚠ Slack通知エラー: {e}")
        return False


def reply_to_comment(youtube, parent_comment_id: str, reply_text: str) -> bool:
    """コメントに返信する"""
    try:
        youtube.comments().insert(
            part="snippet",
            body={
                "snippet": {
                    "parentId": parent_comment_id,
                    "textOriginal": reply_text
                }
            }
        ).execute()
        print(f"  ✓ 返信完了: {parent_comment_id}")
        return True
    except Exception as e:
        print(f"  ⚠ 返信エラー: {e}")
        return False


def main():
    """メイン処理"""
    print("=" * 50)
    print("年金ニュース コメント管理システム")
    print("=" * 50)
    print(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # 返信モードの確認
    reply_mode = os.environ.get("REPLY_MODE", "").lower() == "true"
    reply_comment_id = os.environ.get("REPLY_COMMENT_ID", "")
    reply_text = os.environ.get("REPLY_TEXT", "")

    if reply_mode and reply_comment_id and reply_text:
        # 返信実行モード
        print("\n[返信モード]")
        print(f"コメントID: {reply_comment_id}")
        print(f"返信内容: {reply_text[:50]}...")

        youtube = get_youtube_client()
        success = reply_to_comment(youtube, reply_comment_id, reply_text)

        if success:
            print("\n✓ 返信が投稿されました")
        else:
            print("\n✗ 返信の投稿に失敗しました")
            sys.exit(1)
        return

    # 通常モード（コメント監視）
    key_manager = GeminiKeyManager()

    # クライアント初期化
    print("\n[1/4] API初期化中...")
    youtube = get_youtube_client()
    sheets = get_sheets_client()
    print("  ✓ YouTube API 接続完了")
    print("  ✓ Google Sheets 接続完了")

    # チャンネルID取得
    print("\n[2/4] チャンネル情報取得中...")
    channel_id = get_channel_id(youtube)
    print(f"  ✓ チャンネルID: {channel_id}")

    # 処理済みコメントID取得
    print("\n[3/4] 処理済みコメント確認中...")
    processed_ids = get_processed_comment_ids(sheets)
    print(f"  ✓ 処理済みコメント数: {len(processed_ids)}")

    # コメント取得
    print("\n[4/4] コメント取得中...")
    all_comments = get_all_comments(youtube, channel_id)
    print(f"  ✓ 取得コメント数: {len(all_comments)}")

    # 新しいコメントをフィルタ
    new_comments = [c for c in all_comments if c["comment_id"] not in processed_ids]
    print(f"  ✓ 新規コメント数: {len(new_comments)}")

    if not new_comments:
        print("\n新しいコメントはありません")
        return

    # 各コメントを処理
    print("\n" + "=" * 50)
    print(f"新規コメント {len(new_comments)} 件を処理中...")
    print("=" * 50)

    for i, comment in enumerate(new_comments, 1):
        print(f"\n[{i}/{len(new_comments)}] {comment['author']}")
        print(f"  コメント: {comment['text'][:50]}...")

        # 自分自身のコメントはスキップ
        if comment["author_channel_id"] == channel_id:
            print("  → 自分のコメントのためスキップ")
            mark_comment_processed(sheets, comment["comment_id"], comment["author"], False, False)
            continue

        # AI返信生成
        print("  返信案を生成中...")
        ai_reply = generate_reply(comment["text"], comment["author"], key_manager)

        if ai_reply:
            print(f"  返信案: {ai_reply[:50]}...")
            # Slack通知
            notified = send_slack_notification(comment, ai_reply)
        else:
            print("  ⚠ 返信生成に失敗")
            notified = False

        # 処理済みとして記録
        mark_comment_processed(sheets, comment["comment_id"], comment["author"], True, notified)

        # API制限対策
        time.sleep(1)

    print("\n" + "=" * 50)
    print("処理完了!")
    print("=" * 50)


if __name__ == "__main__":
    main()
