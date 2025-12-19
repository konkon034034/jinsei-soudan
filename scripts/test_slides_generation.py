#!/usr/bin/env python3
"""
Gemini API + Google Slides API テスト
昭和の駄菓子屋TOP5 スライド自動生成（画像付き）
"""

import os
import sys
import json

# .env ファイル読み込み
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key, value)

load_env()

import requests
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# === 設定 ===
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
GOOGLE_CSE_API_KEY = os.environ.get('GOOGLE_CSE_API_KEY')
GOOGLE_CSE_ID = os.environ.get('GOOGLE_CSE_ID')
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), '..', 'credentials.json')

if not GEMINI_API_KEY:
    print("エラー: GEMINI_API_KEY が設定されていません")
    sys.exit(1)

if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_ID:
    print("エラー: Google Custom Search APIの設定が必要です")
    print("以下を .env に追加してください:")
    print('  GOOGLE_CSE_API_KEY=your_api_key')
    print('  GOOGLE_CSE_ID=your_search_engine_id')
    sys.exit(1)


# === Google Custom Search で画像取得 ===
def search_image(query):
    """Google Custom Search APIで画像URLを取得"""
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': GOOGLE_CSE_API_KEY,
        'cx': GOOGLE_CSE_ID,
        'q': f"{query} 駄菓子",
        'searchType': 'image',
        'num': 1,
        'safe': 'active'
    }

    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            if 'items' in data and len(data['items']) > 0:
                return data['items'][0]['link']
    except Exception as e:
        print(f"    画像検索エラー ({query}): {e}")

    return None


# === Gemini でスライド内容生成 ===
def generate_slide_content():
    """Gemini APIでスライド内容を生成"""

    prompt = """
昭和の駄菓子屋で売られていた人気商品TOP5のスライド内容をJSON形式で生成してください。

以下の形式で出力してください（JSONのみ、説明不要）:
{
  "title": "タイトル",
  "subtitle": "サブタイトル",
  "slides": [
    {
      "rank": 5,
      "name": "商品名",
      "description": "説明（50文字程度）",
      "price": "当時の価格",
      "memory": "思い出エピソード（30文字程度）"
    },
    ...（5位から1位まで）
  ],
  "summary": "まとめの一言"
}

懐かしさを感じる内容にしてください。
"""

    models = ['gemini-2.0-flash', 'gemini-2.5-flash', 'gemini-2.0-flash-lite']
    response = None

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={GEMINI_API_KEY}"
        response = requests.post(url, json={
            "contents": [{"parts": [{"text": prompt}]}]
        })
        if response.status_code == 200:
            print(f"  モデル: {model}")
            break
        print(f"  {model} -> {response.status_code}")

    if response.status_code != 200:
        raise Exception(f"Gemini API error: {response.status_code}")

    result = response.json()
    text = result['candidates'][0]['content']['parts'][0]['text'].strip()

    if '```json' in text:
        text = text.split('```json')[1].split('```')[0]
    elif '```' in text:
        text = text.split('```')[1].split('```')[0]

    return json.loads(text.strip())


# === Google Slides API ===
def create_slides(content, images):
    """Google Slides APIでスライド作成（画像付き）"""

    token_json = os.environ.get('TOKEN_SLIDES') or os.environ.get('TOKEN_1')
    if token_json:
        token_data = json.loads(token_json)
        credentials = Credentials(
            token=token_data.get('access_token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri='https://oauth2.googleapis.com/token',
            client_id=token_data.get('client_id'),
            client_secret=token_data.get('client_secret')
        )
    else:
        credentials = service_account.Credentials.from_service_account_file(
            CREDENTIALS_FILE,
            scopes=['https://www.googleapis.com/auth/presentations',
                    'https://www.googleapis.com/auth/drive']
        )

    slides_service = build('slides', 'v1', credentials=credentials)
    drive_service = build('drive', 'v3', credentials=credentials)

    # プレゼンテーション作成
    presentation = slides_service.presentations().create(
        body={'title': content['title']}
    ).execute()

    presentation_id = presentation['presentationId']
    print(f"プレゼンテーション作成: {presentation_id}")

    # スライド追加リクエスト
    reqs = []

    # タイトルスライド
    first_slide_id = presentation['slides'][0]['objectId']
    reqs.extend(create_title_slide_requests(first_slide_id, content))

    # ランキングスライド（画像付き）
    for slide_data in content['slides']:
        slide_id = f"slide_rank_{slide_data['rank']}"
        reqs.append({
            'createSlide': {
                'objectId': slide_id,
                'slideLayoutReference': {'predefinedLayout': 'BLANK'}
            }
        })
        img_url = images.get(slide_data['name'])
        reqs.extend(create_rank_slide_requests(slide_id, slide_data, img_url))

    # まとめスライド
    summary_slide_id = 'slide_summary'
    reqs.append({
        'createSlide': {
            'objectId': summary_slide_id,
            'slideLayoutReference': {'predefinedLayout': 'BLANK'}
        }
    })
    reqs.extend(create_summary_slide_requests(summary_slide_id, content))

    # バッチ更新
    slides_service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={'requests': reqs}
    ).execute()

    # 公開設定
    drive_service.permissions().create(
        fileId=presentation_id,
        body={'type': 'anyone', 'role': 'reader'}
    ).execute()

    return f"https://docs.google.com/presentation/d/{presentation_id}/edit"


def create_title_slide_requests(slide_id, content):
    """タイトルスライド"""
    reqs = []

    # タイトル
    title_box_id = f"{slide_id}_title"
    reqs.append({
        'createShape': {
            'objectId': title_box_id,
            'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': 600, 'unit': 'PT'},
                        'height': {'magnitude': 80, 'unit': 'PT'}},
                'transform': {'scaleX': 1, 'scaleY': 1,
                             'translateX': 60, 'translateY': 150, 'unit': 'PT'}
            }
        }
    })
    reqs.append({'insertText': {'objectId': title_box_id, 'text': content['title']}})
    reqs.append({
        'updateTextStyle': {
            'objectId': title_box_id,
            'style': {'fontSize': {'magnitude': 44, 'unit': 'PT'}, 'bold': True},
            'fields': 'fontSize,bold'
        }
    })

    # サブタイトル
    subtitle_box_id = f"{slide_id}_subtitle"
    reqs.append({
        'createShape': {
            'objectId': subtitle_box_id,
            'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': 500, 'unit': 'PT'},
                        'height': {'magnitude': 40, 'unit': 'PT'}},
                'transform': {'scaleX': 1, 'scaleY': 1,
                             'translateX': 110, 'translateY': 250, 'unit': 'PT'}
            }
        }
    })
    reqs.append({'insertText': {'objectId': subtitle_box_id, 'text': content['subtitle']}})
    reqs.append({
        'updateTextStyle': {
            'objectId': subtitle_box_id,
            'style': {'fontSize': {'magnitude': 24, 'unit': 'PT'}},
            'fields': 'fontSize'
        }
    })

    return reqs


def create_rank_slide_requests(slide_id, data, img_url=None):
    """ランキングスライド（左:テキスト、右:画像）"""
    reqs = []

    # 左側のテキストエリア幅
    text_width = 350 if img_url else 600

    # 順位（左上）
    rank_box_id = f"{slide_id}_rank"
    reqs.append({
        'createShape': {
            'objectId': rank_box_id,
            'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': 120, 'unit': 'PT'},
                        'height': {'magnitude': 80, 'unit': 'PT'}},
                'transform': {'scaleX': 1, 'scaleY': 1,
                             'translateX': 30, 'translateY': 30, 'unit': 'PT'}
            }
        }
    })
    reqs.append({'insertText': {'objectId': rank_box_id, 'text': f"第{data['rank']}位"}})
    reqs.append({
        'updateTextStyle': {
            'objectId': rank_box_id,
            'style': {
                'fontSize': {'magnitude': 40, 'unit': 'PT'},
                'bold': True,
                'foregroundColor': {'opaqueColor': {'rgbColor': {'red': 0.8, 'green': 0.2, 'blue': 0.2}}}
            },
            'fields': 'fontSize,bold,foregroundColor'
        }
    })

    # 商品名
    name_box_id = f"{slide_id}_name"
    reqs.append({
        'createShape': {
            'objectId': name_box_id,
            'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': text_width, 'unit': 'PT'},
                        'height': {'magnitude': 50, 'unit': 'PT'}},
                'transform': {'scaleX': 1, 'scaleY': 1,
                             'translateX': 30, 'translateY': 100, 'unit': 'PT'}
            }
        }
    })
    reqs.append({'insertText': {'objectId': name_box_id, 'text': data['name']}})
    reqs.append({
        'updateTextStyle': {
            'objectId': name_box_id,
            'style': {'fontSize': {'magnitude': 32, 'unit': 'PT'}, 'bold': True},
            'fields': 'fontSize,bold'
        }
    })

    # 価格
    price_box_id = f"{slide_id}_price"
    reqs.append({
        'createShape': {
            'objectId': price_box_id,
            'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': text_width, 'unit': 'PT'},
                        'height': {'magnitude': 25, 'unit': 'PT'}},
                'transform': {'scaleX': 1, 'scaleY': 1,
                             'translateX': 30, 'translateY': 150, 'unit': 'PT'}
            }
        }
    })
    reqs.append({'insertText': {'objectId': price_box_id, 'text': f"当時の価格: {data['price']}"}})
    reqs.append({
        'updateTextStyle': {
            'objectId': price_box_id,
            'style': {'fontSize': {'magnitude': 16, 'unit': 'PT'}},
            'fields': 'fontSize'
        }
    })

    # 説明
    desc_box_id = f"{slide_id}_desc"
    reqs.append({
        'createShape': {
            'objectId': desc_box_id,
            'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': text_width, 'unit': 'PT'},
                        'height': {'magnitude': 80, 'unit': 'PT'}},
                'transform': {'scaleX': 1, 'scaleY': 1,
                             'translateX': 30, 'translateY': 185, 'unit': 'PT'}
            }
        }
    })
    reqs.append({'insertText': {'objectId': desc_box_id, 'text': data['description']}})
    reqs.append({
        'updateTextStyle': {
            'objectId': desc_box_id,
            'style': {'fontSize': {'magnitude': 18, 'unit': 'PT'}},
            'fields': 'fontSize'
        }
    })

    # 思い出
    memory_box_id = f"{slide_id}_memory"
    reqs.append({
        'createShape': {
            'objectId': memory_box_id,
            'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': text_width, 'unit': 'PT'},
                        'height': {'magnitude': 50, 'unit': 'PT'}},
                'transform': {'scaleX': 1, 'scaleY': 1,
                             'translateX': 30, 'translateY': 280, 'unit': 'PT'}
            }
        }
    })
    reqs.append({'insertText': {'objectId': memory_box_id, 'text': f"💭 {data['memory']}"}})
    reqs.append({
        'updateTextStyle': {
            'objectId': memory_box_id,
            'style': {
                'fontSize': {'magnitude': 14, 'unit': 'PT'},
                'italic': True,
                'foregroundColor': {'opaqueColor': {'rgbColor': {'red': 0.4, 'green': 0.4, 'blue': 0.4}}}
            },
            'fields': 'fontSize,italic,foregroundColor'
        }
    })

    # 画像（右側）
    if img_url:
        img_id = f"{slide_id}_img"
        reqs.append({
            'createImage': {
                'objectId': img_id,
                'url': img_url,
                'elementProperties': {
                    'pageObjectId': slide_id,
                    'size': {'width': {'magnitude': 280, 'unit': 'PT'},
                            'height': {'magnitude': 280, 'unit': 'PT'}},
                    'transform': {'scaleX': 1, 'scaleY': 1,
                                 'translateX': 400, 'translateY': 50, 'unit': 'PT'}
                }
            }
        })

    return reqs


def create_summary_slide_requests(slide_id, content):
    """まとめスライド"""
    reqs = []

    # タイトル
    title_box_id = f"{slide_id}_title"
    reqs.append({
        'createShape': {
            'objectId': title_box_id,
            'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': 400, 'unit': 'PT'},
                        'height': {'magnitude': 60, 'unit': 'PT'}},
                'transform': {'scaleX': 1, 'scaleY': 1,
                             'translateX': 160, 'translateY': 60, 'unit': 'PT'}
            }
        }
    })
    reqs.append({'insertText': {'objectId': title_box_id, 'text': 'まとめ'}})
    reqs.append({
        'updateTextStyle': {
            'objectId': title_box_id,
            'style': {'fontSize': {'magnitude': 40, 'unit': 'PT'}, 'bold': True},
            'fields': 'fontSize,bold'
        }
    })

    # まとめ文
    summary_box_id = f"{slide_id}_summary"
    reqs.append({
        'createShape': {
            'objectId': summary_box_id,
            'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': 550, 'unit': 'PT'},
                        'height': {'magnitude': 80, 'unit': 'PT'}},
                'transform': {'scaleX': 1, 'scaleY': 1,
                             'translateX': 85, 'translateY': 140, 'unit': 'PT'}
            }
        }
    })
    reqs.append({'insertText': {'objectId': summary_box_id, 'text': content['summary']}})
    reqs.append({
        'updateTextStyle': {
            'objectId': summary_box_id,
            'style': {'fontSize': {'magnitude': 22, 'unit': 'PT'}},
            'fields': 'fontSize'
        }
    })

    # TOP5リスト
    list_text = "\n".join([f"{s['rank']}位: {s['name']}" for s in content['slides']])
    list_box_id = f"{slide_id}_list"
    reqs.append({
        'createShape': {
            'objectId': list_box_id,
            'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': 300, 'unit': 'PT'},
                        'height': {'magnitude': 150, 'unit': 'PT'}},
                'transform': {'scaleX': 1, 'scaleY': 1,
                             'translateX': 210, 'translateY': 230, 'unit': 'PT'}
            }
        }
    })
    reqs.append({'insertText': {'objectId': list_box_id, 'text': list_text}})
    reqs.append({
        'updateTextStyle': {
            'objectId': list_box_id,
            'style': {'fontSize': {'magnitude': 18, 'unit': 'PT'}},
            'fields': 'fontSize'
        }
    })

    return reqs


# === メイン ===
def main():
    print("=" * 50)
    print("昭和の駄菓子屋TOP5 スライド自動生成（画像付き）")
    print("=" * 50)

    # 1. Gemini でコンテンツ生成
    print("\n[1/4] Gemini APIでスライド内容を生成中...")
    content = generate_slide_content()
    print(f"  タイトル: {content['title']}")
    print(f"  スライド数: {len(content['slides']) + 2}枚")

    for slide in content['slides']:
        print(f"    {slide['rank']}位: {slide['name']}")

    # 2. 画像検索
    print("\n[2/4] Google Custom Searchで画像を取得中...")
    images = {}
    for slide in content['slides']:
        name = slide['name']
        print(f"  検索中: {name}...", end=" ")
        img_url = search_image(name)
        if img_url:
            images[name] = img_url
            print("✓")
        else:
            print("✗ (画像なし)")

    print(f"  取得: {len(images)}/{len(content['slides'])}枚")

    # 3. Google Slides で作成
    print("\n[3/4] Google Slides APIでスライド作成中...")
    url = create_slides(content, images)

    # 4. 結果表示
    print("\n[4/4] 完了!")
    print("=" * 50)
    print(f"\n📊 スライドURL:\n{url}\n")
    print("=" * 50)


if __name__ == '__main__':
    main()
