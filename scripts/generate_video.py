#!/usr/bin/env python3
import os
import json
import gspread
import requests
import tempfile
import time
from datetime import datetime
from google.oauth2.service_account import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]
SPREADSHEET_ID = '15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo'
DRIVE_FOLDER_ID = '1oqjzUgpNexap4mgioXO43UUO3XI5XEzl'

CHANNELS = {
    1: "昭和の宝箱", 2: "懐かしの歌謡曲ch", 3: "思い出ランキング", 4: "昭和スター名鑑",
    5: "演歌の殿堂", 6: "銀幕の思い出", 7: "懐メロ天国", 8: "朝ドラ大全集",
    9: "昭和プレイバック", 10: "昭和ノスタルジア", 11: "黄金時代ch", 12: "昭和ドラマ劇場",
    13: "戦後日本の記憶", 14: "昭和の学校", 15: "制服と校則ch", 16: "昭和の食卓",
    17: "昭和グルメ図鑑", 18: "昭和CM博覧会", 19: "CMソング大全", 20: "昭和の暮らし",
    21: "昭和の家族", 22: "おしゃれ街道", 23: "昭和ファッション", 24: "レトロビューティー",
    25: "昭和スポーツ伝説", 26: "昭和バラエティ", 27: "激動の昭和史"
}

def get_credentials():
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    creds_dict = json.loads(creds_json)
    return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)

def get_pending_neta(sh):
    ws = sh.worksheet('ネタ管理')
    all_data = ws.get_all_values()
    for i, row in enumerate(all_data[1:], start=2):
        if len(row) >= 6 and row[5] == '未作成':
            return {
                'row_num': i,
                'neta_id': row[0],
                'channel_id': int(row[1]),
                'category': row[2],
                'title': row[3],
                'ranking_num': int(row[4]) if row[4].isdigit() else 15
            }
    return None

def generate_ranking_content(neta):
    api_key = os.environ.get('CLAUDE_API_KEY')
    
    prompt = f"""あなたは昭和時代を懐かしむ語り部です。
以下の動画タイトルに基づいて、ランキング動画のナレーション原稿を作成してください。

タイトル: {neta['title']}
ランキング数: TOP{neta['ranking_num']}

【重要な雰囲気①：時の流れの切なさ】
全体を通して「時の流れの切なさ」を感じさせてください。
- 「あの頃の輝きは、今も私たちの心の中に生きています」
- 「すっかり時間が経ってしまいましたね」
- 「時の流れは切ないものですが、だからこそ思い出は美しいのかもしれません」
- 「あれから何十年...街の景色は変わっても、あの頃の記憶は色褪せません」
- 「今はもう見ることができない風景ですが...」

【重要な雰囲気②：視聴者を称え、自分ごとに】
見ている視聴者自身を称え、「自分の人生だ」と感じられるようにしてください。
- 「これをご覧のあなたも、きっとあの時代を懸命に生きてこられたのですね」
- 「あなたがいたからこそ、あの時代は輝いていたのです」
- 「今日まで歩んでこられた人生、本当に素晴らしいものです」
- 「あなたの記憶の中にも、きっとこんな思い出があるのではないでしょうか」
- 「この時代を知るあなただからこそ、分かる喜びがありますよね」
- 「あなたが積み重ねてきた日々が、どれほど尊いものか」
- 「共に時代を生きた私たちだからこそ、分かち合える思い出です」

視聴者に「私の人生を認めてもらえた」「私の時代は価値があった」と感じさせてください。

条件:
- 60歳以上の女性視聴者向け
- 各順位について2-3文で解説
- しみじみとした、切なくも温かい語り口
- 視聴者に直接語りかけるように（「あなた」「皆さま」を使う）
- 「あの頃」と「今」を対比させ、時代の移り変わりを感じさせる
- 二度と戻れない過去への愛おしさを表現
- オープニングとエンディングは特に感傷的に、視聴者への感謝を込めて
- 8分程度の動画になる分量

以下の形式で出力:
[オープニング]
（視聴者に語りかけ、時の流れを感じさせる導入。30秒程度）

[第{neta['ranking_num']}位]
項目名: ○○○
解説: （2-3文。「あなたも覚えていますか？」など視聴者に問いかけながら）

[第{neta['ranking_num']-1}位]
...

[第1位]
項目名: ○○○
解説: （2-3文。最も印象的なエピソードを）

[エンディング]
（視聴者への感謝と労い、時の流れを振り返り、心に残るまとめ。「あなたの人生は素晴らしい」というメッセージを込めて）"""

    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": "claude-3-haiku-20240307",
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        result = response.json()
        if 'content' in result:
            return result['content'][0]['text']
    except Exception as e:
        print(f"  ⚠️ 原稿生成エラー: {e}")
    return None

def generate_audio_google_tts(text, output_path):
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    creds_dict = json.loads(creds_json)
    credentials = service_account.Credentials.from_service_account_info(creds_dict)
    
    url = "https://texttospeech.googleapis.com/v1/text:synthesize"
    
    from google.auth.transport.requests import Request
    credentials.refresh(Request())
    
    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "Content-Type": "application/json"
    }
    
    max_chars = 4500
    if len(text) > max_chars:
        text = text[:max_chars]
    
    payload = {
        "input": {"text": text},
        "voice": {
            "languageCode": "ja-JP",
            "name": "ja-JP-Neural2-B",
            "ssmlGender": "FEMALE"
        },
        "audioConfig": {
            "audioEncoding": "MP3",
            "speakingRate": 0.9,
            "pitch": 0
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        result = response.json()
        
        if 'audioContent' in result:
            import base64
            audio_data = base64.b64decode(result['audioContent'])
            with open(output_path, 'wb') as f:
                f.write(audio_data)
            return True
    except Exception as e:
        print(f"  ⚠️ 音声生成エラー: {e}")
    return False

def get_unsplash_images(query, count=10):
    api_key = os.environ.get('UNSPLASH_ACCESS_KEY')
    url = f"https://api.unsplash.com/search/photos"
    params = {
        "query": query,
        "per_page": count,
        "orientation": "landscape"
    }
    headers = {"Authorization": f"Client-ID {api_key}"}
    
    try:
        response = requests.get(url, params=params, headers=headers)
        result = response.json()
        if 'results' in result:
            return [img['urls']['regular'] for img in result['results']]
    except Exception as e:
        print(f"  ⚠️ 画像取得エラー: {e}")
    return []

def download_image(url, output_path):
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            with open(output_path, 'wb') as f:
                f.write(response.content)
            return True
    except:
        pass
    return False

def create_video_with_moviepy(audio_path, images, title, output_path):
    from moviepy.editor import (
        AudioFileClip, ImageClip, CompositeVideoClip, 
        concatenate_videoclips, TextClip, ColorClip
    )
    
    audio = AudioFileClip(audio_path)
    duration = audio.duration
    
    img_duration = duration / len(images) if images else duration
    
    clips = []
    for img_path in images:
        try:
            img_clip = ImageClip(img_path).set_duration(img_duration)
            img_clip = img_clip.resize(height=720)
            clips.append(img_clip)
        except Exception as e:
            print(f"  ⚠️ 画像読み込みエラー: {e}")
    
    if not clips:
        clips = [ColorClip(size=(1280, 720), color=(0,0,0)).set_duration(duration)]
    
    video = concatenate_videoclips(clips, method="compose")
    video = video.set_audio(audio)
    
    try:
        txt_clip = TextClip(
            title, 
            fontsize=50, 
            color='white',
            font='Noto-Sans-CJK-JP'
        ).set_position(('center', 50)).set_duration(5)
        video = CompositeVideoClip([video, txt_clip])
    except:
        pass
    
    video.write_videofile(
        output_path,
        fps=24,
        codec='libx264',
        audio_codec='aac'
    )
    
    audio.close()
    return True

def upload_to_drive(file_path, file_name, creds):
    service = build('drive', 'v3', credentials=creds)
    
    file_metadata = {
        'name': file_name,
        'parents': [DRIVE_FOLDER_ID]
    }
    media = MediaFileUpload(file_path, mimetype='video/mp4')
    
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id,webViewLink'
    ).execute()
    
    return file.get('webViewLink')

def update_sheet_status(sh, row_num, status, drive_link=''):
    ws = sh.worksheet('ネタ管理')
    ws.update_cell(row_num, 6, status)
    if drive_link:
        ws.update_cell(row_num, 9, drive_link)

def main():
    print("🎬 動画生成開始...")
    
    creds = get_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)
    
    neta = get_pending_neta(sh)
    if not neta:
        print("📭 未作成のネタがありません")
        return
    
    print(f"📺 ch{neta['channel_id']}: {neta['title']}")
    
    update_sheet_status(sh, neta['row_num'], '作成中')
    
    with tempfile.TemporaryDirectory() as tmpdir:
        print("  📝 原稿生成中...")
        script = generate_ranking_content(neta)
        if not script:
            update_sheet_status(sh, neta['row_num'], 'エラー')
            return
        print(f"  ✅ 原稿生成完了（{len(script)}文字）")
        
        print("  🎤 音声生成中...")
        audio_path = os.path.join(tmpdir, "audio.mp3")
        if not generate_audio_google_tts(script, audio_path):
            update_sheet_status(sh, neta['row_num'], 'エラー')
            return
        print("  ✅ 音声生成完了")
        
        print("  🖼️ 画像取得中...")
        search_query = f"昭和 日本 {neta['category']}"
        image_urls = get_unsplash_images(search_query, neta['ranking_num'])
        
        images = []
        for i, url in enumerate(image_urls):
            img_path = os.path.join(tmpdir, f"img_{i}.jpg")
            if download_image(url, img_path):
                images.append(img_path)
        print(f"  ✅ 画像取得完了（{len(images)}枚）")
        
        print("  🎥 動画生成中...")
        video_path = os.path.join(tmpdir, "output.mp4")
        if not create_video_with_moviepy(audio_path, images, neta['title'], video_path):
            update_sheet_status(sh, neta['row_num'], 'エラー')
            return
        print("  ✅ 動画生成完了")
        
        print("  ☁️ アップロード中...")
        file_name = f"ch{neta['channel_id']}_{neta['title']}.mp4"
        drive_link = upload_to_drive(video_path, file_name, creds)
        print(f"  ✅ アップロード完了")
        
        update_sheet_status(sh, neta['row_num'], '完成', drive_link)
    
    print(f"🎉 動画生成完了！ {drive_link}")

if __name__ == "__main__":
    main()
