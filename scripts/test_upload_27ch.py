#!/usr/bin/env python3
"""27チャンネル テストアップロードスクリプト"""

from dotenv import load_dotenv
load_dotenv()

import os
import json
import tempfile
from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 総チャンネル数
TOTAL_CHANNELS = 27

def create_test_video(channel_num, output_path):
    """テスト動画を生成（10秒、黒背景に白文字でチャンネル番号）"""
    from moviepy import ColorClip, TextClip, CompositeVideoClip

    duration = 10

    # 黒背景
    bg = ColorClip(size=(1280, 720), color=(0, 0, 0), duration=duration)

    # 白文字でチャンネル番号
    try:
        txt = TextClip(
            text=f"テスト ch{channel_num}",
            font='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            font_size=72,
            color='white',
            size=(1280, 720),
            method='caption',
            text_align='center'
        )
        txt = txt.with_duration(duration)
        txt = txt.with_position('center')
        video = CompositeVideoClip([bg, txt])
    except:
        # フォントが見つからない場合は背景のみ
        video = bg

    video.write_videofile(
        output_path,
        fps=24,
        codec='libx264',
        audio=False
    )
    return True

def get_youtube_credentials(channel_id):
    """YouTube OAuth認証情報を取得"""
    token_env_name = f'TOKEN_{channel_id}'
    token_value = os.environ.get(token_env_name)

    if not token_value:
        return None, f"TOKEN_{channel_id}が未設定"

    default_client_id = os.environ.get('YOUTUBE_CLIENT_ID', '')
    default_client_secret = os.environ.get('YOUTUBE_CLIENT_SECRET', '')

    token_value = token_value.strip()
    if token_value.startswith('{'):
        token_data = json.loads(token_value)
        refresh_token = token_data.get('refresh_token')
        client_id = token_data.get('client_id') or default_client_id
        client_secret = token_data.get('client_secret') or default_client_secret
    else:
        refresh_token = token_value
        client_id = default_client_id
        client_secret = default_client_secret

    if not client_id or not client_secret:
        return None, "CLIENT_ID/SECRETが未設定"

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=client_id,
        client_secret=client_secret,
        scopes=['https://www.googleapis.com/auth/youtube.upload']
    )
    return creds, None

def upload_to_youtube(video_path, channel_id):
    """YouTubeにアップロード"""
    creds, error = get_youtube_credentials(channel_id)
    if error:
        return None, error

    try:
        youtube = build('youtube', 'v3', credentials=creds)

        body = {
            'snippet': {
                'title': 'テスト動画',
                'description': '自動アップロードテスト',
                'tags': ['テスト'],
                'categoryId': '22'
            },
            'status': {
                'privacyStatus': 'private',
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

        response = None
        while response is None:
            status, response = request.next_chunk()

        video_id = response.get('id')
        return f"https://www.youtube.com/watch?v={video_id}", None

    except Exception as e:
        return None, str(e)

def main():
    print("=" * 60)
    print("27チャンネル テストアップロード")
    print("=" * 60)
    print(f"開始時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = {
        'success': [],
        'failed': []
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        for ch in range(1, TOTAL_CHANNELS + 1):
            print(f"\nch{ch} 処理中...")

            # テスト動画生成
            video_path = os.path.join(tmpdir, f"test_ch{ch}.mp4")
            print(f"  動画生成中...")

            try:
                create_test_video(ch, video_path)
                print(f"  動画生成完了")
            except Exception as e:
                print(f"  動画生成失敗: {e}")
                results['failed'].append({
                    'channel': ch,
                    'error': f"動画生成失敗: {e}"
                })
                continue

            # アップロード
            print(f"  アップロード中...")
            url, error = upload_to_youtube(video_path, ch)

            if url:
                print(f"  成功: {url}")
                results['success'].append({
                    'channel': ch,
                    'url': url
                })
            else:
                print(f"  失敗: {error}")
                results['failed'].append({
                    'channel': ch,
                    'error': error
                })

    # サマリー
    print("\n" + "=" * 60)
    print("結果サマリー")
    print("=" * 60)

    print(f"\n成功: {len(results['success'])}件")
    for r in results['success']:
        print(f"   ch{r['channel']}: {r['url']}")

    print(f"\n失敗: {len(results['failed'])}件")
    for r in results['failed']:
        print(f"   ch{r['channel']}: {r['error']}")

    print("\n" + "=" * 60)
    print(f"完了！ 成功:{len(results['success'])} / 失敗:{len(results['failed'])} / 合計:{TOTAL_CHANNELS}")
    print("=" * 60)

if __name__ == '__main__':
    main()
