import os
import pickle
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

def get_youtube_service():
    """YouTube APIサービスを取得"""
    credentials = Credentials(
        token=None,
        refresh_token=os.environ['YOUTUBE_REFRESH_TOKEN'],
        token_uri='https://oauth2.googleapis.com/token',
        client_id=os.environ['YOUTUBE_CLIENT_ID'],
        client_secret=os.environ['YOUTUBE_CLIENT_SECRET']
    )
    
    # トークンをリフレッシュ
    credentials.refresh(Request())
    
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
