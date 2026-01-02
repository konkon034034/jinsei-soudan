# 横スクロール動画リメイクシステム

YouTube登録チャンネルからランダムにランキング動画を選択し、横スクロール動画を自動生成するシステム。

## フォルダ構成

```
ranking_remake/
├── data/
│   └── channels.json      # 登録チャンネル一覧
├── screenshots/           # スクリーンショット保存先
├── output/                # 動画出力先
├── select_random_video.py # ランダム動画選択スクリプト
├── .env.example           # 環境変数サンプル
└── README.md
```

## 必要な環境変数

`.env.example` をコピーして `.env` を作成し、以下を設定:

| 変数名 | 説明 |
|--------|------|
| `YOUTUBE_API_KEY` | YouTube Data API v3 のAPIキー |
| `DISCORD_WEBHOOK` | Discord Webhook URL（通知用） |

## セットアップ

```bash
# 依存パッケージのインストール
pip install google-api-python-client python-dotenv requests

# 環境変数の設定
cp .env.example .env
# .env を編集してAPIキーを設定
```

## 使い方

### 1. ランダム動画選択

```bash
python select_random_video.py
```

**動作:**
1. `data/channels.json` から登録チャンネルを読み込み
2. ランダムに1チャンネルを選択
3. YouTube Data API v3 でそのチャンネルの最新動画10本を取得
4. タイトルに以下のキーワードが含まれる動画をフィルタリング:
   - `ランキング`
   - `TOP`
   - `位`
   - `選`
5. ランキング動画が見つかった場合、Discord Webhookで通知

## channels.json のフォーマット

```json
[
  {
    "channel_id": "UCxxxxxxxxxx",
    "channel_name": "チャンネル名"
  }
]
```
