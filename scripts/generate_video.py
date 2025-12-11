#!/usr/bin/env python3
from dotenv import load_dotenv
load_dotenv()

import os
import json
import gspread
import requests
import tempfile
from datetime import datetime
from google.oauth2.service_account import Credentials
from google.oauth2.credentials import Credentials as OAuthCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/youtube.upload'
]
SPREADSHEET_ID = '15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo'

# YouTube OAuth tokens (from GitHub Secrets)
YOUTUBE_TOKENS = {
    1: 'TOKEN_1',  # Channel 1-9
    2: 'TOKEN_2',  # Channel 10-18
    3: 'TOKEN_3',  # Channel 19-27
}

# Cache for channel info from spreadsheet
_channel_info_cache = None

def get_channel_info_from_sheet(sh):
    """Read channel information from '27チャンネル一覧' sheet."""
    global _channel_info_cache

    if _channel_info_cache is not None:
        return _channel_info_cache

    try:
        ws = sh.worksheet('27チャンネル一覧')
        all_data = ws.get_all_values()

        channel_info = {}
        for row in all_data[1:]:  # Skip header
            if len(row) >= 3:
                try:
                    token_num = int(row[0])
                    email = row[1]
                    channel_name = row[2]
                    channel_info[token_num] = {
                        'email': email,
                        'name': channel_name if channel_name != '（未設定）' else None
                    }
                except (ValueError, IndexError):
                    continue

        _channel_info_cache = channel_info
        return channel_info
    except Exception as e:
        print(f"  ⚠️ チャンネル情報読み込みエラー: {e}")
        return {}

def get_channel_name(sh, channel_id):
    """Get channel name for the given channel ID."""
    channel_info = get_channel_info_from_sheet(sh)

    # Get channel number from environment or use channel_id
    channel_number = int(os.environ.get('CHANNEL_NUMBER', channel_id))

    info = channel_info.get(channel_number, {})
    return info.get('name')

# Fallback channel names (used when spreadsheet doesn't have the info)
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
    from gtts import gTTS
    
    try:
        max_chars = 5000
        if len(text) > max_chars:
            text = text[:max_chars]
        
        tts = gTTS(text=text, lang='ja', slow=False)
        tts.save(output_path)
        return True
    except Exception as e:
        print(f"  ⚠️ 音声生成エラー: {e}")
    return False

# Japanese to English keyword mapping for Unsplash search
KEYWORD_MAP = {
    # Categories
    '歌謡曲': 'japanese music vintage',
    '演歌': 'japanese traditional music',
    '映画': 'vintage cinema japan',
    '銀幕': 'classic movie theater',
    'ドラマ': 'vintage television japan',
    '朝ドラ': 'japanese morning drama vintage',
    'CM': 'vintage advertisement japan',
    '広告': 'retro advertising',
    'ファッション': 'vintage fashion 1960s 1970s',
    'おしゃれ': 'retro style fashion',
    '化粧品': 'vintage cosmetics beauty',
    'ビューティー': 'retro beauty makeup',
    '食卓': 'japanese home cooking vintage',
    'グルメ': 'vintage japanese food',
    '学校': 'vintage school classroom japan',
    '制服': 'japanese school uniform vintage',
    'スポーツ': 'vintage sports japan',
    'バラエティ': 'japanese entertainment vintage',
    '暮らし': 'vintage japanese lifestyle',
    '家族': 'japanese family vintage',
    '昭和': 'japan 1960s 1970s vintage',
    'レトロ': 'retro vintage nostalgic',
    '懐かしい': 'nostalgic vintage memories',
    '思い出': 'memories nostalgia vintage',
    'スター': 'vintage celebrity star',
    '名鑑': 'vintage portrait classic',
    '戦後': 'postwar japan vintage',
    '黄金時代': 'golden age vintage',
    '歴史': 'japanese history vintage',
}

# Fallback search queries for different themes
FALLBACK_QUERIES = [
    'vintage japan street',
    'retro japanese aesthetic',
    'nostalgic sunset',
    'vintage paper texture',
    'retro gradient background',
    'old photograph sepia',
    'cherry blossom vintage',
    'japanese garden peaceful',
]

def translate_to_english_keywords(japanese_text):
    """Convert Japanese title/category to English keywords for Unsplash."""
    keywords = []

    # Check for matching keywords in the text
    for jp_word, en_keywords in KEYWORD_MAP.items():
        if jp_word in japanese_text:
            keywords.append(en_keywords)

    # If no keywords found, use general nostalgic terms
    if not keywords:
        keywords = ['vintage japan nostalgic', 'retro aesthetic']

    # Combine and deduplicate
    combined = ' '.join(keywords[:3])  # Limit to avoid overly complex queries
    return combined

def get_unsplash_images(query, count=10, category=''):
    """Fetch images from Unsplash with English keyword translation."""
    api_key = os.environ.get('UNSPLASH_ACCESS_KEY')
    url = "https://api.unsplash.com/search/photos"
    headers = {"Authorization": f"Client-ID {api_key}"}

    # Translate Japanese to English keywords
    english_query = translate_to_english_keywords(query + ' ' + category)
    print(f"    🔍 検索キーワード: {english_query}")

    # Try multiple search strategies
    search_queries = [
        english_query,
        'vintage japan nostalgic',
        'retro aesthetic background',
    ]

    all_urls = []
    for search_query in search_queries:
        if len(all_urls) >= count:
            break

        params = {
            "query": search_query,
            "per_page": min(count - len(all_urls) + 5, 30),  # Get extra in case of duplicates
            "orientation": "landscape"
        }

        try:
            response = requests.get(url, params=params, headers=headers)
            result = response.json()
            if 'results' in result:
                for img in result['results']:
                    img_url = img['urls']['regular']
                    if img_url not in all_urls:
                        all_urls.append(img_url)
                        if len(all_urls) >= count:
                            break
        except Exception as e:
            print(f"    ⚠️ 検索エラー ({search_query}): {e}")

    return all_urls[:count]

def generate_gradient_background(output_path, width=1280, height=720, style='showa'):
    """Generate a nostalgic gradient background image."""
    from PIL import Image, ImageDraw, ImageFilter
    import random

    # Color palettes for different styles
    palettes = {
        'showa': [
            [(139, 90, 43), (205, 133, 63)],      # Sepia brown
            [(70, 50, 30), (150, 100, 50)],       # Dark brown to tan
            [(80, 60, 40), (180, 140, 90)],       # Earthy tones
            [(100, 70, 50), (200, 160, 100)],     # Warm vintage
        ],
        'sunset': [
            [(255, 94, 77), (255, 154, 139)],     # Coral sunset
            [(255, 123, 84), (255, 184, 140)],    # Orange sunset
            [(180, 80, 100), (255, 150, 120)],    # Pink sunset
        ],
        'nostalgic': [
            [(60, 60, 80), (120, 100, 140)],      # Muted purple
            [(50, 70, 90), (100, 130, 150)],      # Dusty blue
            [(80, 70, 60), (160, 140, 120)],      # Faded vintage
        ]
    }

    # Select palette
    palette_list = palettes.get(style, palettes['showa'])
    colors = random.choice(palette_list)

    # Create gradient image
    img = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(img)

    # Vertical gradient
    for y in range(height):
        ratio = y / height
        r = int(colors[0][0] + (colors[1][0] - colors[0][0]) * ratio)
        g = int(colors[0][1] + (colors[1][1] - colors[0][1]) * ratio)
        b = int(colors[0][2] + (colors[1][2] - colors[0][2]) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Add subtle noise/grain for vintage effect
    noise_img = Image.new('RGB', (width, height))
    noise_draw = ImageDraw.Draw(noise_img)
    for _ in range(5000):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        gray = random.randint(0, 30)
        noise_draw.point((x, y), fill=(gray, gray, gray))

    # Blend noise with gradient
    img = Image.blend(img, noise_img, 0.05)

    # Add vignette effect
    vignette = Image.new('L', (width, height), 255)
    vignette_draw = ImageDraw.Draw(vignette)
    for i in range(min(width, height) // 2):
        alpha = int(255 * (1 - (i / (min(width, height) / 2)) ** 2))
        vignette_draw.ellipse(
            [i, i, width - i, height - i],
            outline=alpha
        )
    vignette = vignette.filter(ImageFilter.GaussianBlur(50))

    # Apply vignette
    img_array = list(img.getdata())
    vignette_array = list(vignette.getdata())
    result_data = []
    for i, (pixel, v) in enumerate(zip(img_array, vignette_array)):
        factor = v / 255
        result_data.append((
            int(pixel[0] * factor),
            int(pixel[1] * factor),
            int(pixel[2] * factor)
        ))
    img.putdata(result_data)

    img.save(output_path, 'JPEG', quality=90)
    return True

def get_images_with_fallback(title, category, count, tmpdir):
    """Get images from Unsplash with fallback to generated backgrounds."""
    images = []

    # Try to get images from Unsplash
    search_query = f"{title} {category}"
    image_urls = get_unsplash_images(search_query, count, category)

    # Download Unsplash images
    for i, url in enumerate(image_urls):
        img_path = os.path.join(tmpdir, f"img_{i}.jpg")
        if download_image(url, img_path):
            images.append(img_path)

    # If we don't have enough images, generate fallback backgrounds
    if len(images) < count:
        print(f"    🎨 フォールバック背景を生成中...")
        styles = ['showa', 'sunset', 'nostalgic']
        for i in range(len(images), count):
            img_path = os.path.join(tmpdir, f"fallback_{i}.jpg")
            style = styles[i % len(styles)]
            if generate_gradient_background(img_path, style=style):
                images.append(img_path)

    return images

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
    from moviepy import (
        AudioFileClip, ImageClip,
        concatenate_videoclips, ColorClip
    )

    audio = AudioFileClip(audio_path)
    duration = audio.duration

    img_duration = duration / len(images) if images else duration

    clips = []
    for img_path in images:
        try:
            img_clip = ImageClip(img_path, duration=img_duration)
            img_clip = img_clip.resized(height=720)
            clips.append(img_clip)
        except Exception as e:
            print(f"  ⚠️ 画像読み込みエラー: {e}")

    if not clips:
        clips = [ColorClip(size=(1280, 720), color=(0,0,0), duration=duration)]

    video = concatenate_videoclips(clips, method="compose")
    video = video.with_audio(audio)

    video.write_videofile(
        output_path,
        fps=24,
        codec='libx264',
        audio_codec='aac'
    )

    audio.close()
    return True

def get_youtube_credentials(channel_id):
    """Get YouTube OAuth credentials for the channel.

    Supports two token formats:
    1. JSON format: {"refresh_token": "...", "client_id": "...", "client_secret": "..."}
    2. Simple string: 1//0e... (refresh_token only, uses YOUTUBE_CLIENT_ID/SECRET env vars)
    """
    # Determine which token to use (1-9: TOKEN_1, 10-18: TOKEN_2, 19-27: TOKEN_3)
    token_num = ((channel_id - 1) // 9) + 1
    token_env_name = f'TOKEN_{token_num}'

    token_value = os.environ.get(token_env_name) or os.environ.get('TOKEN_1')
    if not token_value:
        raise ValueError(f"{token_env_name} not found in environment variables")

    # Default credentials from environment
    default_client_id = os.environ.get('YOUTUBE_CLIENT_ID', '')
    default_client_secret = os.environ.get('YOUTUBE_CLIENT_SECRET', '')

    # Check if token is JSON format or simple string
    token_value = token_value.strip()
    if token_value.startswith('{'):
        # JSON format
        token_data = json.loads(token_value)
        refresh_token = token_data.get('refresh_token')
        client_id = token_data.get('client_id') or default_client_id
        client_secret = token_data.get('client_secret') or default_client_secret
    else:
        # Simple string format (refresh_token only)
        refresh_token = token_value
        client_id = default_client_id
        client_secret = default_client_secret

    if not client_id or not client_secret:
        raise ValueError("YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set")

    creds = OAuthCredentials(
        token=None,
        refresh_token=refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=client_id,
        client_secret=client_secret,
        scopes=['https://www.googleapis.com/auth/youtube.upload']
    )

    return creds

def upload_to_youtube(file_path, title, description, channel_id, privacy='private'):
    """Upload video to YouTube and return the video URL."""
    creds = get_youtube_credentials(channel_id)
    youtube = build('youtube', 'v3', credentials=creds)

    # Prepare video metadata
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': ['昭和', '懐かしい', 'ランキング', '思い出'],
            'categoryId': '22'  # People & Blogs
        },
        'status': {
            'privacyStatus': privacy,  # 'private', 'unlisted', or 'public'
            'selfDeclaredMadeForKids': False
        }
    }

    media = MediaFileUpload(
        file_path,
        mimetype='video/mp4',
        resumable=True,
        chunksize=1024*1024  # 1MB chunks
    )

    request = youtube.videos().insert(
        part='snippet,status',
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"    📤 {int(status.progress() * 100)}%")

    video_id = response.get('id')
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    return video_url

def update_sheet_status(sh, row_num, status, video_url=''):
    """Update status and YouTube URL in spreadsheet."""
    ws = sh.worksheet('ネタ管理')
    ws.update_cell(row_num, 6, status)
    if video_url:
        ws.update_cell(row_num, 9, video_url)

def main():
    print("🎬 動画生成開始...")

    creds = get_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SPREADSHEET_ID)

    # Get channel info from spreadsheet
    channel_number = int(os.environ.get('CHANNEL_NUMBER', 1))
    channel_name = get_channel_name(sh, channel_number)
    if channel_name:
        print(f"📺 チャンネル: {channel_name} (TOKEN_{channel_number})")
    else:
        # Fallback to hardcoded name
        channel_name = CHANNELS.get(channel_number, f"チャンネル{channel_number}")
        print(f"📺 チャンネル: {channel_name} (TOKEN_{channel_number}) [フォールバック]")

    neta = get_pending_neta(sh)
    if not neta:
        print("📭 未作成のネタがありません")
        return

    print(f"📝 ネタ: {neta['title']}")

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
        images = get_images_with_fallback(
            title=neta['title'],
            category=neta['category'],
            count=neta['ranking_num'],
            tmpdir=tmpdir
        )
        print(f"  ✅ 画像取得完了（{len(images)}枚）")

        print("  🎥 動画生成中...")
        video_path = os.path.join(tmpdir, "output.mp4")
        if not create_video_with_moviepy(audio_path, images, neta['title'], video_path):
            update_sheet_status(sh, neta['row_num'], 'エラー')
            return
        print("  ✅ 動画生成完了")

        print("  📺 YouTubeアップロード中...")
        # Create description with channel name
        description = f"{script[:100]}...\n\n"
        if channel_name:
            description += f"【{channel_name}】\n"
        description += "#昭和 #懐かしい #ランキング #思い出 #レトロ"

        video_url = upload_to_youtube(
            file_path=video_path,
            title=neta['title'],
            description=description,
            channel_id=neta['channel_id'],
            privacy='private'  # Test with private
        )
        print(f"  ✅ アップロード完了")

        update_sheet_status(sh, neta['row_num'], '完成', video_url)

    print(f"🎉 動画生成完了！ {video_url}")

if __name__ == "__main__":
    main()
