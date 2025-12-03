# jinsei-soudan
人生相談チャンネル動画生成システム

YouTube元動画から人生相談を取得し、女性2人キャラで動画化するシステム。

## 機能

- YouTube元動画から字幕を取得し、相談内容を抽出
- Gemini APIで台本（4000〜6000文字）を自動生成
- メタデータ（タイトル・説明文・タグ）を自動生成
- 初コメントを自動生成
- スプレッドシートで進捗管理

## キャラクター設定

- **ミサキ**: 明るく共感力が高い、優しいお姉さんタイプ
- **アヤネ**: 冷静で論理的、的確なアドバイスをするタイプ

## セットアップ

### 必要な環境変数

```bash
# 必須
GEMINI_API_KEY=your_gemini_api_key
GOOGLE_CREDENTIALS_JSON={"type":"service_account",...}
SPREADSHEET_ID=your_spreadsheet_id

# オプション
YOUTUBE_CHANNEL_ID=your_channel_id
SOURCE_VIDEO_URL=https://youtube.com/watch?v=...
```

### 依存関係インストール

```bash
pip install -r requirements.txt
pip install youtube-transcript-api  # 字幕取得用（オプション）
```

## 使い方

### 手動実行

```bash
python jinsei_generator.py [YouTube URL]
```

### 自動実行（GitHub Actions）

```bash
python jinsei_generator_auto.py
```

## スプレッドシート列構成

| 列 | 項目 | 説明 |
|---|---|---|
| A | 作成済 | チェックボックス |
| B | 日時 | 処理日時 |
| C | 情報収集 | 元動画サマリー |
| D | スクリプト作成 | ステータス |
| E | 文字数カウント | 台本の文字数 |
| F | script | 台本本文 |
| G | 生成URL | YouTube動画URL |
| H | 概要欄プロンプト | - |
| I | metadata | タイトル・説明・タグ |
| J | comment | 初コメント |
| K | search | 検索キーワード |

## ファイル構成

```
jinsei-soudan/
├── jinsei_generator.py      # メイン処理
├── jinsei_generator_auto.py # 自動実行用エントリーポイント
├── youtube_source.py        # YouTube元動画取得
├── prompts/
│   ├── prompt_a_script.txt  # 台本生成プロンプト
│   ├── prompt_c_metadata.txt # メタデータ生成
│   └── prompt_d_comment.txt  # 初コメ生成
├── assets/                   # 素材ファイル
├── output/                   # 出力先
├── temp/                     # 一時ファイル
└── requirements.txt
```
