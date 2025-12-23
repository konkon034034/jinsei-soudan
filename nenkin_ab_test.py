#!/usr/bin/env python3
"""
年金ニュース A/Bテスト自動化システム
- サムネイル・タイトルの効果測定
- YouTube Analytics APIでCTR・再生回数を取得
- 3日ごとに自動切り替え・比較
- 勝者を自動判定してDiscord通知
"""

import os
import json
import requests
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# ===== 定数 =====
LOG_SPREADSHEET_ID = "1anLnC5EEZW1S4Ec9kMlhZdp9DuIUkn3hUMbmPqV1b0E"
AB_TEST_SHEET_NAME = "ABテスト"

# テスト期間（日数）
TEST_DURATION_DAYS = 3


def get_youtube_client():
    """YouTube APIクライアントを取得"""
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

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token"
    )
    return build("youtube", "v3", credentials=creds)


def get_youtube_analytics_client():
    """YouTube Analytics APIクライアントを取得"""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN_23")

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError("YouTube認証情報が不足しています")

    response = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    })
    access_token = response.json()["access_token"]

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token"
    )
    return build("youtubeAnalytics", "v2", credentials=creds)


def get_channel_id(youtube):
    """チャンネルIDを取得"""
    response = youtube.channels().list(
        part="id",
        mine=True
    ).execute()
    return response["items"][0]["id"]


def get_video_analytics(analytics, channel_id: str, video_id: str, start_date: str, end_date: str) -> dict:
    """動画のアナリティクスデータを取得"""
    try:
        response = analytics.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained",
            dimensions="video",
            filters=f"video=={video_id}"
        ).execute()

        if response.get("rows"):
            row = response["rows"][0]
            return {
                "video_id": row[0],
                "views": row[1],
                "watch_time_minutes": row[2],
                "avg_view_duration": row[3],
                "subscribers_gained": row[4]
            }
        return None
    except Exception as e:
        print(f"  ⚠ アナリティクス取得エラー: {e}")
        return None


def get_video_impressions(analytics, channel_id: str, video_id: str, start_date: str, end_date: str) -> dict:
    """動画のインプレッション・CTRを取得"""
    try:
        response = analytics.reports().query(
            ids=f"channel=={channel_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="impressions,impressionsClickThroughRate",
            dimensions="video",
            filters=f"video=={video_id}"
        ).execute()

        if response.get("rows"):
            row = response["rows"][0]
            return {
                "video_id": row[0],
                "impressions": row[1],
                "ctr": row[2]  # パーセンテージ（例: 5.2 = 5.2%）
            }
        return None
    except Exception as e:
        print(f"  ⚠ インプレッション取得エラー: {e}")
        return None


def update_video_title(youtube, video_id: str, new_title: str) -> bool:
    """動画タイトルを更新"""
    try:
        # 現在の動画情報を取得
        response = youtube.videos().list(
            part="snippet",
            id=video_id
        ).execute()

        if not response.get("items"):
            print(f"  ⚠ 動画が見つかりません: {video_id}")
            return False

        video = response["items"][0]
        snippet = video["snippet"]
        snippet["title"] = new_title

        # 更新
        youtube.videos().update(
            part="snippet",
            body={
                "id": video_id,
                "snippet": snippet
            }
        ).execute()

        print(f"  ✓ タイトル更新完了: {new_title}")
        return True
    except Exception as e:
        print(f"  ⚠ タイトル更新エラー: {e}")
        return False


def update_video_thumbnail(youtube, video_id: str, thumbnail_path: str) -> bool:
    """動画サムネイルを更新"""
    try:
        from googleapiclient.http import MediaFileUpload
        media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")

        youtube.thumbnails().set(
            videoId=video_id,
            media_body=media
        ).execute()

        print(f"  ✓ サムネイル更新完了: {video_id}")
        return True
    except Exception as e:
        print(f"  ⚠ サムネイル更新エラー: {e}")
        return False


def get_sheets_client():
    """Google Sheets APIクライアントを取得"""
    from google.oauth2 import service_account

    key_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if not key_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEYが設定されていません")

    key_data = json.loads(key_json)
    creds = service_account.Credentials.from_service_account_info(
        key_data,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)


def get_active_tests(sheets) -> list:
    """アクティブなA/Bテストを取得"""
    try:
        # シートが存在するか確認
        spreadsheet = sheets.spreadsheets().get(spreadsheetId=LOG_SPREADSHEET_ID).execute()
        sheet_names = [s["properties"]["title"] for s in spreadsheet.get("sheets", [])]

        if AB_TEST_SHEET_NAME not in sheet_names:
            # シートを作成
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=LOG_SPREADSHEET_ID,
                body={
                    "requests": [{
                        "addSheet": {
                            "properties": {"title": AB_TEST_SHEET_NAME}
                        }
                    }]
                }
            ).execute()
            # ヘッダーを追加
            sheets.spreadsheets().values().update(
                spreadsheetId=LOG_SPREADSHEET_ID,
                range=f"{AB_TEST_SHEET_NAME}!A1:L1",
                valueInputOption="RAW",
                body={"values": [[
                    "video_id", "開始日", "現在バリアント", "タイトルA", "タイトルB",
                    "CTR_A", "再生数_A", "CTR_B", "再生数_B", "勝者", "ステータス", "最終更新"
                ]]}
            ).execute()
            return []

        # データを取得
        result = sheets.spreadsheets().values().get(
            spreadsheetId=LOG_SPREADSHEET_ID,
            range=f"{AB_TEST_SHEET_NAME}!A2:L100"
        ).execute()

        rows = result.get("values", [])
        active_tests = []
        for row in rows:
            if len(row) >= 11 and row[10] == "active":
                active_tests.append({
                    "video_id": row[0],
                    "start_date": row[1],
                    "current_variant": row[2],
                    "title_a": row[3],
                    "title_b": row[4],
                    "ctr_a": float(row[5]) if row[5] else 0,
                    "views_a": int(row[6]) if row[6] else 0,
                    "ctr_b": float(row[7]) if row[7] else 0,
                    "views_b": int(row[8]) if row[8] else 0,
                    "winner": row[9] if len(row) > 9 else "",
                    "status": row[10]
                })

        return active_tests
    except Exception as e:
        print(f"  ⚠ テストデータ取得エラー: {e}")
        return []


def save_test_result(sheets, test_data: dict):
    """テスト結果をスプレッドシートに保存"""
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 既存の行を探す
        result = sheets.spreadsheets().values().get(
            spreadsheetId=LOG_SPREADSHEET_ID,
            range=f"{AB_TEST_SHEET_NAME}!A2:A100"
        ).execute()

        rows = result.get("values", [])
        row_index = None
        for i, row in enumerate(rows):
            if row and row[0] == test_data["video_id"]:
                row_index = i + 2  # 1-indexed + header
                break

        row_data = [
            test_data["video_id"],
            test_data["start_date"],
            test_data["current_variant"],
            test_data["title_a"],
            test_data["title_b"],
            test_data["ctr_a"],
            test_data["views_a"],
            test_data["ctr_b"],
            test_data["views_b"],
            test_data.get("winner", ""),
            test_data["status"],
            now
        ]

        if row_index:
            # 更新
            sheets.spreadsheets().values().update(
                spreadsheetId=LOG_SPREADSHEET_ID,
                range=f"{AB_TEST_SHEET_NAME}!A{row_index}:L{row_index}",
                valueInputOption="RAW",
                body={"values": [row_data]}
            ).execute()
        else:
            # 追加
            sheets.spreadsheets().values().append(
                spreadsheetId=LOG_SPREADSHEET_ID,
                range=f"{AB_TEST_SHEET_NAME}!A:L",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row_data]}
            ).execute()

        print(f"  ✓ テスト結果保存完了: {test_data['video_id']}")
    except Exception as e:
        print(f"  ⚠ テスト結果保存エラー: {e}")


def send_discord_notification(message: str):
    """Discord通知を送信"""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("  ⚠ DISCORD_WEBHOOK_URL未設定")
        return

    try:
        response = requests.post(
            webhook_url,
            json={"content": message},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        if response.status_code in [200, 204]:
            print("  ✓ Discord通知送信完了")
    except Exception as e:
        print(f"  ⚠ Discord通知エラー: {e}")


def determine_winner(test_data: dict) -> str:
    """勝者を判定"""
    ctr_a = test_data.get("ctr_a", 0)
    ctr_b = test_data.get("ctr_b", 0)
    views_a = test_data.get("views_a", 0)
    views_b = test_data.get("views_b", 0)

    # CTRを主要指標とする（再生数が一定以上の場合）
    min_views = 100  # 最低再生数

    if views_a < min_views and views_b < min_views:
        return "insufficient_data"

    if views_a >= min_views and views_b >= min_views:
        # 両方十分なデータがある場合
        if ctr_a > ctr_b * 1.1:  # 10%以上の差
            return "A"
        elif ctr_b > ctr_a * 1.1:
            return "B"
        else:
            return "tie"

    # 片方だけデータがある場合は判定保留
    return "pending"


def run_ab_test_cycle():
    """A/Bテストサイクルを実行"""
    print("=" * 50)
    print("年金ニュース A/Bテスト自動化")
    print("=" * 50)

    youtube = get_youtube_client()
    analytics = get_youtube_analytics_client()
    sheets = get_sheets_client()
    channel_id = get_channel_id(youtube)

    print(f"\nチャンネルID: {channel_id}")

    # アクティブなテストを取得
    active_tests = get_active_tests(sheets)
    print(f"アクティブなテスト数: {len(active_tests)}")

    if not active_tests:
        print("アクティブなテストがありません")
        return

    today = datetime.now().date()
    end_date = today.strftime("%Y-%m-%d")

    for test in active_tests:
        print(f"\n--- テスト: {test['video_id']} ---")
        print(f"  現在のバリアント: {test['current_variant']}")

        start_date = test["start_date"]
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        days_elapsed = (today - start_dt).days

        print(f"  経過日数: {days_elapsed}日")

        # アナリティクスデータを取得
        impressions = get_video_impressions(analytics, channel_id, test["video_id"], start_date, end_date)

        if impressions:
            current_variant = test["current_variant"]
            if current_variant == "A":
                test["ctr_a"] = impressions["ctr"]
                test["views_a"] += impressions.get("impressions", 0)
            else:
                test["ctr_b"] = impressions["ctr"]
                test["views_b"] += impressions.get("impressions", 0)

            print(f"  CTR: {impressions['ctr']:.2f}%")
            print(f"  インプレッション: {impressions['impressions']}")

        # 切り替え判定
        if days_elapsed >= TEST_DURATION_DAYS:
            current_variant = test["current_variant"]

            if current_variant == "A":
                # Bに切り替え
                new_title = test["title_b"]
                update_video_title(youtube, test["video_id"], new_title)
                test["current_variant"] = "B"
                test["start_date"] = today.strftime("%Y-%m-%d")
                print(f"  → バリアントBに切り替え")

            elif current_variant == "B":
                # テスト完了、勝者判定
                winner = determine_winner(test)
                test["winner"] = winner
                test["status"] = "completed"

                # 勝者のタイトルを設定
                if winner == "A":
                    update_video_title(youtube, test["video_id"], test["title_a"])
                elif winner == "B":
                    update_video_title(youtube, test["video_id"], test["title_b"])

                # Discord通知
                message = f"""🔬 **A/Bテスト結果**
━━━━━━━━━━━━━━━━━━

📺 動画: https://youtube.com/watch?v={test['video_id']}

**バリアントA**
タイトル: {test['title_a']}
CTR: {test['ctr_a']:.2f}%

**バリアントB**
タイトル: {test['title_b']}
CTR: {test['ctr_b']:.2f}%

🏆 **勝者: {winner}**

━━━━━━━━━━━━━━━━━━"""
                send_discord_notification(message)
                print(f"  → テスト完了、勝者: {winner}")

        # 結果を保存
        save_test_result(sheets, test)

    print("\n" + "=" * 50)
    print("A/Bテストサイクル完了")
    print("=" * 50)


def register_new_test(video_id: str, title_a: str, title_b: str):
    """新しいA/Bテストを登録"""
    sheets = get_sheets_client()

    test_data = {
        "video_id": video_id,
        "start_date": datetime.now().strftime("%Y-%m-%d"),
        "current_variant": "A",
        "title_a": title_a,
        "title_b": title_b,
        "ctr_a": 0,
        "views_a": 0,
        "ctr_b": 0,
        "views_b": 0,
        "winner": "",
        "status": "active"
    }

    save_test_result(sheets, test_data)
    print(f"新しいA/Bテスト登録完了: {video_id}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "register":
        # 新規テスト登録モード
        if len(sys.argv) < 5:
            print("Usage: python nenkin_ab_test.py register <video_id> <title_a> <title_b>")
            sys.exit(1)
        register_new_test(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        # 通常のサイクル実行
        run_ab_test_cycle()
