#!/usr/bin/env python3
"""昭和ネタ朝の準備スクリプト - Gemini台本生成 + 画像検索 + Slack送信"""

import os
import json
import requests
from datetime import datetime
import random

# チャンネル設定
CHANNELS = [
    {
        'gmail': 'jyb475rt@gmail.com',
        'name': '昭和の銀幕スター',
        'token_num': 27,
        'topics': [
            '高倉健の名作映画TOP10',
            '美空ひばりの伝説的名曲ランキング',
            '石原裕次郎の魅力を振り返る',
            '吉永小百合の代表作ベスト10',
            '三船敏郎の侍映画傑作選',
            '昭和の二枚目俳優ランキング',
            '黒澤明監督作品の名シーン',
            '昭和の大女優たちの競演',
            '男はつらいよシリーズの魅力',
            '昭和スターの意外なエピソード',
        ]
    },
    {
        'gmail': 'kij876tge@gmail.com',
        'name': '昭和アイドル伝説',
        'token_num': 24,
        'topics': [
            '山口百恵の伝説TOP10',
            'キャンディーズ名曲ランキング',
            'ピンク・レディー旋風を振り返る',
            '松田聖子vs中森明菜 80年代対決',
            '昭和アイドルの衝撃引退劇',
            'たのきんトリオの青春時代',
            '昭和アイドルの意外な現在',
            'ザ・ベストテン名場面集',
            '昭和アイドル水泳大会の思い出',
            'おニャン子クラブ全盛期',
        ]
    },
    {
        'gmail': 'ftt357g@gmail.com',
        'name': '朝ドラ&大河ヒロイン',
        'token_num': 23,
        'topics': [
            '歴代朝ドラヒロインランキング',
            'おしんが国民的ドラマになった理由',
            '大河ドラマ名シーンTOP10',
            '朝ドラ主題歌ベスト20',
            'NHK朝ドラの泣ける名場面',
            '大河ドラマ歴代視聴率ランキング',
            '朝ドラから生まれたスターたち',
            '昭和の大河ドラマ傑作選',
            '朝ドラロケ地巡りの旅',
            'あまちゃんブームを振り返る',
        ]
    }
]


def generate_script_with_gemini(channel_name, topic):
    """Gemini APIで台本生成"""
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        print("⚠️ GEMINI_API_KEY not set, using sample script")
        return generate_sample_script(channel_name, topic)

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        model = genai.GenerativeModel('gemini-1.5-flash')

        prompt = f"""あなたはYouTubeチャンネル「{channel_name}」の台本ライターです。
視聴者は60代以上の女性が中心で、昭和の思い出に浸りたい方々です。

以下のテーマで動画用ナレーション台本を作成してください：
「{topic}」

【台本の形式】
1. キャッチーなタイトル（サムネイル用）
2. オープニング（視聴者への挨拶、テーマ紹介）
3. ランキング本編（TOP3形式、各項目に詳しい解説とエピソード）
4. エンディング（まとめ、チャンネル登録のお願い）

【注意事項】
- 懐かしさと共感を大切に
- 「あの頃は〜でしたね」など視聴者の記憶を呼び起こす表現
- 具体的な年代やエピソードを入れる
- 800文字程度で書く（テスト用に短縮）
- 親しみやすい語り口調（「皆さん」「〜ですよね」）
- 各段落は1〜2文で区切る（Slack表示用）
"""

        response = model.generate_content(prompt)
        return response.text

    except Exception as e:
        print(f"Gemini API error: {e}")
        return generate_sample_script(channel_name, topic)


def generate_sample_script(channel_name, topic):
    """サンプル台本（API失敗時用）"""
    return f"""【タイトル】
{topic}｜60代が涙する懐かしの名場面

【オープニング】
皆さん、こんにちは！「{channel_name}」へようこそ。
今日は「{topic}」をお届けします。

昭和の時代、私たちはテレビの前でワクワクしながら見ていましたよね。
あの頃の思い出が蘇ってきませんか？

【ランキング本編】
それでは早速、ランキングを見ていきましょう！

第10位から第1位まで、懐かしい名場面をお届けします...

（ここに詳しいランキング内容が入ります）

【エンディング】
いかがでしたでしょうか？
皆さんの青春時代の思い出が蘇ってきたでしょうか。

チャンネル登録と高評価をお願いします！
コメント欄であなたの思い出もぜひ教えてくださいね。

次回もお楽しみに！
"""


def search_images(query, num_images=10):
    """Google Custom Search APIで画像検索（テスト用に10枚）"""
    api_key = os.environ.get('GOOGLE_SEARCH_API_KEY')
    search_engine_id = os.environ.get('GOOGLE_SEARCH_ENGINE_ID')

    if not api_key or not search_engine_id:
        print("⚠️ Google Search API not configured")
        return []

    images = []
    # テスト用: 10枚だけ取得
    for start in [1]:
        try:
            url = 'https://www.googleapis.com/customsearch/v1'
            params = {
                'key': api_key,
                'cx': search_engine_id,
                'q': f'{query} 昭和',
                'searchType': 'image',
                'num': 10,
                'start': start,
                'safe': 'active',
                'imgSize': 'large'
            }

            response = requests.get(url, params=params, timeout=30)
            data = response.json()

            if 'items' in data:
                for item in data['items']:
                    images.append({
                        'url': item.get('link'),
                        'title': item.get('title'),
                        'thumbnail': item.get('image', {}).get('thumbnailLink')
                    })

        except Exception as e:
            print(f"Image search error (start={start}): {e}")

    print(f"  取得画像数: {len(images)}枚")
    return images


def send_to_slack(channel_info, topic, script, images):
    """Slackに台本と画像を送信（モバイル対応・シンプル版）"""
    bot_token = os.environ.get('SLACK_BOT_TOKEN')
    slack_channel = os.environ.get('SLACK_CHANNEL', '#all-こんこん')

    if not bot_token:
        print("⚠️ SLACK_BOT_TOKEN not set")
        return False

    headers = {
        'Authorization': f'Bearer {bot_token}',
        'Content-Type': 'application/json'
    }

    def post_message(blocks, text):
        payload = {"channel": slack_channel, "blocks": blocks, "text": text}
        try:
            resp = requests.post('https://slack.com/api/chat.postMessage',
                               headers=headers, json=payload, timeout=30)
            result = resp.json()
            return result.get('ok'), result.get('error')
        except Exception as e:
            return False, str(e)

    ch_num = channel_info['token_num']

    # === メッセージ1: ヘッダー ===
    script_lines = [line.strip() for line in script.split('\n') if line.strip()]
    total_lines = len(script_lines)

    blocks_header = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🎬 {channel_info['name']}"}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*テーマ:* {topic}\n*台本:* {total_lines}行 | *画像:* 10枚"}
        }
    ]

    ok, err = post_message(blocks_header, f"{channel_info['name']} - {topic}")
    if not ok:
        print(f"  ❌ ヘッダー送信失敗: {err}")
        return False

    # === 台本を1行ずつ送信（✅/❌ボタン付き） ===
    print(f"  台本行数: {total_lines}行")

    for line_num, line in enumerate(script_lines, 1):
        display_line = line[:60] + "..." if len(line) > 60 else line

        blocks_line = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*台本 {line_num}/{total_lines}*\n{display_line}"}
            },
            {
                "type": "actions",
                "block_id": f"line_{ch_num}_{line_num}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ 使う"},
                        "style": "primary",
                        "action_id": f"use_line_{ch_num}_{line_num}"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ 削除"},
                        "action_id": f"skip_line_{ch_num}_{line_num}"
                    }
                ]
            }
        ]

        ok, err = post_message(blocks_line, f"台本{line_num}")
        if not ok:
            print(f"  ⚠️ 台本{line_num}送信失敗: {err}")

    # === 画像を1枚ずつ送信（モバイル対応） ===
    display_images = images[:10]
    total_images = len(display_images)
    print(f"  画像数: {total_images}枚")

    for img_num, img in enumerate(display_images, 1):
        img_url = img.get('url', '')
        thumb_url = img.get('thumbnail') or img_url
        img_title = img.get('title', f'画像{img_num}')[:30]

        if not thumb_url:
            continue

        # 1枚につき: section + image + actions = 3ブロック
        # valueにJSON形式で画像情報を含める（GASで復元用）
        import json as json_module
        img_value = json_module.dumps({"url": thumb_url, "title": img_title[:20]}, ensure_ascii=False)

        blocks_img = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*画像 {img_num}/{total_images}*"}
            },
            {
                "type": "image",
                "image_url": thumb_url,
                "alt_text": img_title,
                "title": {"type": "plain_text", "text": img_title[:20]}
            },
            {
                "type": "actions",
                "block_id": f"img_{ch_num}_{img_num}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ 使う"},
                        "style": "primary",
                        "action_id": f"use_img_{ch_num}_{img_num}",
                        "value": img_value
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ 削除"},
                        "action_id": f"skip_img_{ch_num}_{img_num}",
                        "value": img_value
                    }
                ]
            }
        ]

        ok, err = post_message(blocks_img, f"画像{img_num}")
        if not ok:
            print(f"  ⚠️ 画像{img_num}送信失敗: {err}")

    # === 最終メッセージ: アクションボタン ===
    blocks_actions = [
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*📊 ch{ch_num}*\n画像: {total_images}枚 | 台本: {total_lines}行"}
        },
        {
            "type": "actions",
            "block_id": f"action_{ch_num}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🎬 生成"},
                    "style": "primary",
                    "action_id": f"generate_{ch_num}"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔄 再生成"},
                    "action_id": f"regenerate_{ch_num}"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "⏭️"},
                    "action_id": f"skip_{ch_num}"
                }
            ]
        }
    ]

    ok, err = post_message(blocks_actions, "アクション")
    if ok:
        print(f"  ✅ Slack送信成功")
        return True
    else:
        print(f"  ❌ アクション送信失敗: {err}")
        return False


def process_channel(channel_info):
    """1チャンネルの処理"""
    print(f"\n{'='*60}")
    print(f"📺 {channel_info['name']} (TOKEN_{channel_info['token_num']})")
    print('='*60)

    # ランダムにトピック選択
    topic = random.choice(channel_info['topics'])
    print(f"📋 テーマ: {topic}")

    # 1. 台本生成
    print("\n1. 台本生成中...")
    script = generate_script_with_gemini(channel_info['name'], topic)
    print(f"  台本生成完了 ({len(script)}文字)")

    # 2. 画像検索
    print("\n2. 画像検索中...")
    search_query = topic.replace('TOP10', '').replace('ランキング', '').strip()
    images = search_images(search_query)

    # 3. Slack送信
    print("\n3. Slack送信中...")
    send_to_slack(channel_info, topic, script, images)


def main():
    print("=" * 60)
    print("🌅 昭和ネタ朝の準備")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    channel_index = int(os.environ.get('CHANNEL_INDEX', '0'))

    if channel_index == 0:
        # 全チャンネル処理
        for channel in CHANNELS:
            process_channel(channel)
    else:
        # 指定チャンネルのみ
        if 1 <= channel_index <= len(CHANNELS):
            process_channel(CHANNELS[channel_index - 1])
        else:
            print(f"❌ Invalid channel index: {channel_index}")

    print("\n" + "=" * 60)
    print("✅ 朝の準備完了！Slackをチェックしてください。")
    print("=" * 60)


if __name__ == '__main__':
    main()
