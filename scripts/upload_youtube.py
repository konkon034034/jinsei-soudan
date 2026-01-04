import os
import json
from datetime import datetime, timezone
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

# トークン保存先（環境変数またはファイル）
TOKEN_FILE = os.path.join(os.path.dirname(__file__), '.youtube_token_cache.json')


def load_cached_token():
    """キャッシュされたトークンを読み込む"""
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'r') as f:
                data = json.load(f)
                return data.get('access_token'), data.get('expiry')
        except (json.JSONDecodeError, IOError):
            pass
    return None, None


def save_token_cache(access_token: str, expiry: datetime):
    """トークンをキャッシュに保存"""
    try:
        data = {
            'access_token': access_token,
            'expiry': expiry.isoformat() if expiry else None,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        with open(TOKEN_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"✓ トークンをキャッシュに保存しました")
    except IOError as e:
        print(f"⚠️ トークンキャッシュの保存に失敗: {e}")


def is_token_expired(expiry_str: str) -> bool:
    """トークンが期限切れかチェック"""
    if not expiry_str:
        return True
    try:
        expiry = datetime.fromisoformat(expiry_str.replace('Z', '+00:00'))
        # 5分の余裕を持って期限切れ判定
        now = datetime.now(timezone.utc)
        return now >= expiry
    except (ValueError, TypeError):
        return True


def generate_auth_url():
    """認証URLを生成して表示"""
    client_id = os.environ.get('YOUTUBE_CLIENT_ID')

    if not client_id:
        return None

    auth_url = (
        f"https://accounts.google.com/o/oauth2/auth?"
        f"client_id={client_id}&"
        f"redirect_uri=http://localhost:8080/&"
        f"scope=https://www.googleapis.com/auth/youtube.upload%20"
        f"https://www.googleapis.com/auth/youtube.readonly&"
        f"response_type=code&"
        f"access_type=offline&"
        f"prompt=consent"
    )
    return auth_url


def get_youtube_service():
    """YouTube APIサービスを取得（自動トークン更新付き）"""
    refresh_token = os.environ.get('YOUTUBE_REFRESH_TOKEN')
    client_id = os.environ.get('YOUTUBE_CLIENT_ID')
    client_secret = os.environ.get('YOUTUBE_CLIENT_SECRET')

    if not all([refresh_token, client_id, client_secret]):
        raise ValueError("YOUTUBE_REFRESH_TOKEN, YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET が必要です")

    # キャッシュからトークンを読み込み
    cached_token, cached_expiry = load_cached_token()

    # トークンが有効期限内かチェック
    if cached_token and not is_token_expired(cached_expiry):
        print("✓ キャッシュされたトークンを使用")
        credentials = Credentials(
            token=cached_token,
            refresh_token=refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=client_id,
            client_secret=client_secret
        )
    else:
        # 新規またはリフレッシュが必要
        if cached_token:
            print("⏰ トークンが期限切れです。リフレッシュします...")
        else:
            print("🔄 トークンを取得します...")

        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=client_id,
            client_secret=client_secret
        )

        try:
            # トークンをリフレッシュ
            credentials.refresh(Request())
            print("✅ トークンのリフレッシュに成功しました")

            # 新しいトークンをキャッシュに保存
            save_token_cache(credentials.token, credentials.expiry)

        except RefreshError as e:
            print()
            print("=" * 70)
            print("❌ トークンのリフレッシュに失敗しました")
            print("=" * 70)
            print()
            print("リフレッシュトークンが無効または期限切れです。")
            print("再認証が必要です。")
            print()
            print("⚠️  以下のURLをシークレットウィンドウで開いてください：")
            print()
            auth_url = generate_auth_url()
            if auth_url:
                print(auth_url)
            print()
            print("=" * 70)
            print("認証後、新しいリフレッシュトークンを GitHub Secrets に設定してください。")
            print("=" * 70)
            raise RuntimeError(f"トークンリフレッシュ失敗: {e}") from e

    return build('youtube', 'v3', credentials=credentials)

def upload_video(video_path, title, description, tags=None, category_id="22", privacy_status="public"):
    """
    YouTubeに動画をアップロード

    Args:
        video_path: 動画ファイルのパス
        title: 動画タイトル
        description: 動画の説明
        tags: タグのリスト
        category_id: カテゴリID（22=People & Blogs）
        privacy_status: public, private, unlisted

    Returns:
        アップロードされた動画のID
    """
    youtube = get_youtube_service()

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags or [],
            'categoryId': category_id
        },
        'status': {
            'privacyStatus': privacy_status,
            'selfDeclaredMadeForKids': False
        }
    }

    media = MediaFileUpload(
        video_path,
        mimetype='video/mp4',
        resumable=True
    )

    request = youtube.videos().insert(
        part='snippet,status',
        body=body,
        media_body=media
    )

    response = request.execute()
    video_id = response['id']

    print(f"✅ アップロード成功！")
    print(f"🎬 動画ID: {video_id}")
    print(f"🔗 URL: https://www.youtube.com/watch?v={video_id}")

    return video_id

if __name__ == "__main__":
    # テスト用
    import sys
    if len(sys.argv) >= 3:
        video_path = sys.argv[1]
        title = sys.argv[2]
        description = sys.argv[3] if len(sys.argv) > 3 else ""
        upload_video(video_path, title, description)
    else:
        print("Usage: python upload_youtube.py <video_path> <title> [description]")
