#!/usr/bin/env python3
"""運用チャンネル向け動画生成・アップロードスクリプト"""

import os
import json
import tempfile
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials as SACredentials
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SPREADSHEET_ID = '15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo'

def get_channel_config(channel_num):
    """運用チャンネルシートから設定を取得"""
    sa_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    if not sa_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON not set")

    creds = SACredentials.from_service_account_info(
        json.loads(sa_json),
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)

    ws = spreadsheet.worksheet('運用チャンネル')
    all_data = ws.get_all_values()

    for row in all_data[1:]:
        if row and row[0] == str(channel_num):
            return {
                'ch_num': row[0],
                'name': row[1],
                'token_name': row[2],
                'gmail': row[3],
                'prompt': row[5] if len(row) > 5 else ''
            }

    raise ValueError(f"Channel {channel_num} not found in 運用チャンネル sheet")


def generate_script_with_openai(prompt, channel_name):
    """OpenAI APIで台本生成"""
    try:
        from openai import OpenAI
        client = OpenAI()

        system_prompt = f"""あなたは「{channel_name}」というYouTubeチャンネルの台本ライターです。
視聴者は60代以上の女性が中心です。
以下の要件で動画台本を作成してください：
- 8分以上の動画用（2000文字以上）
- 懐かしさと共感を大切に
- ランキング形式や振り返り形式
- 親しみやすい語り口調
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            max_tokens=4000
        )

        return response.choices[0].message.content

    except Exception as e:
        print(f"OpenAI API error: {e}")
        return None


def create_video(script, channel_name, output_path):
    """MoviePyで動画生成"""
    from moviepy import ColorClip, TextClip, CompositeVideoClip, concatenate_videoclips

    # スクリプトを複数スライドに分割
    paragraphs = [p.strip() for p in script.split('\n\n') if p.strip()]
    if not paragraphs:
        paragraphs = [script[:500]]

    clips = []
    duration_per_slide = 10  # 各スライド10秒

    for i, text in enumerate(paragraphs[:20]):  # 最大20スライド
        bg = ColorClip(size=(1280, 720), color=(30, 30, 50), duration=duration_per_slide)

        try:
            # テキストを適度な長さに
            display_text = text[:200] + "..." if len(text) > 200 else text

            txt = TextClip(
                text=display_text,
                font='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                font_size=36,
                color='white',
                size=(1200, 600),
                method='caption',
                text_align='center'
            )
            txt = txt.with_duration(duration_per_slide).with_position('center')
            clip = CompositeVideoClip([bg, txt])
        except Exception as e:
            print(f"TextClip error: {e}")
            clip = bg

        clips.append(clip)

    if not clips:
        clips = [ColorClip(size=(1280, 720), color=(0, 0, 0), duration=30)]

    final = concatenate_videoclips(clips)
    final.write_videofile(output_path, fps=24, codec='libx264', audio=False)

    return True


def upload_to_youtube(video_path, title, description, channel_num):
    """YouTubeにアップロード"""
    client_id = os.environ.get('YOUTUBE_CLIENT_ID')
    client_secret = os.environ.get('YOUTUBE_CLIENT_SECRET')
    token_value = os.environ.get(f'TOKEN_{channel_num}')

    if not token_value:
        raise ValueError(f"TOKEN_{channel_num} not set")

    token_value = token_value.strip()
    if token_value.startswith('{'):
        token_data = json.loads(token_value)
        refresh_token = token_data.get('refresh_token')
        client_id = token_data.get('client_id') or client_id
        client_secret = token_data.get('client_secret') or client_secret
    else:
        refresh_token = token_value

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=client_id,
        client_secret=client_secret,
        scopes=['https://www.googleapis.com/auth/youtube.upload']
    )

    youtube = build('youtube', 'v3', credentials=creds)

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': ['昭和', 'ノスタルジー', '懐かしい'],
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': 'private',  # まずは非公開
            'selfDeclaredMadeForKids': False
        }
    }

    media = MediaFileUpload(video_path, mimetype='video/mp4', resumable=True)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()

    video_id = response.get('id')
    return f"https://www.youtube.com/watch?v={video_id}"


def update_spreadsheet(channel_num, video_url):
    """スプレッドシートを更新"""
    sa_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    creds = SACredentials.from_service_account_info(
        json.loads(sa_json),
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)

    # 運用チャンネルシート更新
    ws = spreadsheet.worksheet('運用チャンネル')
    all_data = ws.get_all_values()

    for i, row in enumerate(all_data[1:], start=2):
        if row and row[0] == str(channel_num):
            now = datetime.now().strftime('%Y-%m-%d %H:%M')
            current_count = int(row[7]) if len(row) > 7 and row[7] else 0
            ws.update_cell(i, 7, now)  # 最終投稿日
            ws.update_cell(i, 8, current_count + 1)  # 投稿数
            break

    print(f"✅ スプレッドシート更新完了")


def main():
    channel_num = int(os.environ.get('CHANNEL_NUM', '23'))

    print("=" * 60)
    print(f"動画生成開始: ch{channel_num}")
    print("=" * 60)

    # 1. チャンネル設定取得
    print("\n1. チャンネル設定取得...")
    config = get_channel_config(channel_num)
    print(f"   チャンネル名: {config['name']}")
    print(f"   プロンプト: {config['prompt'][:50]}...")

    # 2. 台本生成
    print("\n2. 台本生成中...")
    script = generate_script_with_openai(config['prompt'], config['name'])
    if not script:
        print("   ⚠️ OpenAI API失敗、サンプル台本使用")
        script = f"""
{config['name']}へようこそ！

今日は皆さんと一緒に懐かしい思い出を振り返りたいと思います。

{config['prompt']}

昭和の時代は本当に素晴らしい時代でしたね。
皆さんの青春時代の思い出が蘇ってきたでしょうか。

チャンネル登録と高評価をお願いします！
"""
    print(f"   台本生成完了 ({len(script)}文字)")

    # 3. 動画生成
    print("\n3. 動画生成中...")
    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = f"{tmpdir}/video.mp4"
        create_video(script, config['name'], video_path)
        print("   動画生成完了")

        # 4. YouTubeアップロード
        print("\n4. YouTubeアップロード中...")
        now = datetime.now()
        title = f"{config['name']} - {now.strftime('%Y年%m月%d日')}"
        description = f"{config['prompt']}\n\n#昭和 #ノスタルジー #懐かしい"

        video_url = upload_to_youtube(video_path, title, description, channel_num)
        print(f"   アップロード成功: {video_url}")

        # 5. スプレッドシート更新
        print("\n5. スプレッドシート更新中...")
        update_spreadsheet(channel_num, video_url)

    print("\n" + "=" * 60)
    print("完了!")
    print(f"動画URL: {video_url}")
    print("=" * 60)


if __name__ == '__main__':
    main()
