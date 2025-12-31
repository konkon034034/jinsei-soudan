#!/usr/bin/env python3
"""
YouTube動画をGemini APIで分析するツール

使い方:
  python3 youtube_analyzer.py "https://www.youtube.com/watch?v=..."
  python3 youtube_analyzer.py "https://www.youtube.com/watch?v=..." -o output.json

エイリアス:
  yt-analyze "URL"
"""
import os
import sys
import json
import argparse
from pathlib import Path
from dotenv import load_dotenv

# .env読み込み
load_dotenv(Path(__file__).parent / ".env")

from google import genai
from google.genai import types


def analyze_youtube_video(url: str, api_key: str = None) -> dict:
    """YouTube動画を分析してランキングデータを抽出"""

    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEY が設定されていません")

    client = genai.Client(api_key=api_key)

    prompt = """
この動画を分析して、以下の情報をJSON形式で出力してください：

{
  "title": "動画タイトル",
  "type": "ランキング/解説/その他",
  "theme": "テーマ（例：昭和のお菓子、俳優など）",
  "total_items": 順位の総数,
  "items": [
    {
      "rank": 1,
      "name": "名前",
      "data": {
        "追加情報のキー": "値"
      },
      "description": "解説文"
    }
  ],
  "summary": "動画全体の要約（100文字程度）"
}

【重要】
- ランキング動画の場合は、全ての順位のアイテムを items に含めてください
- ランキング動画でない場合は、items を空配列にして summary に内容をまとめてください
- data には動画内で表示されている追加情報（発売年、メーカー、価格など）を含めてください
- 必ず有効なJSONのみを出力してください（説明文は不要）
"""

    print("   Gemini APIで動画を分析中...")

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=prompt),
                    types.Part.from_uri(file_uri=url, mime_type="video/*"),
                ]
            )
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )

    # JSONを抽出
    text = response.text.strip()

    # ```json ... ``` を除去
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(text)
        # リストの場合は最初の要素を取得、またはitemsとして扱う
        if isinstance(data, list):
            if len(data) > 0 and isinstance(data[0], dict) and "rank" in data[0]:
                # ランキングアイテムのリストの場合
                return {
                    "title": "分析結果",
                    "type": "ランキング",
                    "theme": "不明",
                    "total_items": len(data),
                    "items": data,
                    "summary": ""
                }
            elif len(data) == 1:
                return data[0]
        return data
    except json.JSONDecodeError as e:
        print(f"   ⚠️ JSONパースエラー: {e}")
        print(f"   生のレスポンス:\n{text[:500]}")
        return {"error": str(e), "raw_response": text}


def main():
    parser = argparse.ArgumentParser(
        description="YouTube動画をGemini APIで分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  %(prog)s "https://www.youtube.com/watch?v=LtOKNUyvfvA"
  %(prog)s "https://www.youtube.com/watch?v=LtOKNUyvfvA" -o ranking.json
        """
    )
    parser.add_argument("url", help="YouTube URL")
    parser.add_argument("--output", "-o", help="出力JSONファイルパス")
    parser.add_argument("--api-key", help="Gemini API Key（省略時は環境変数から取得）")
    args = parser.parse_args()

    print(f"\n🎬 YouTube動画分析")
    print("=" * 50)
    print(f"URL: {args.url}")

    try:
        result = analyze_youtube_video(args.url, args.api_key)

        if isinstance(result, dict) and "error" not in result:
            print(f"\n✅ 分析完了!")
            print(f"   タイプ: {result.get('type', '不明')}")
            print(f"   テーマ: {result.get('theme', '不明')}")
            items = result.get('items', [])
            print(f"   アイテム数: {result.get('total_items', len(items))}")

        if args.output:
            output_path = Path(args.output)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"\n📁 保存: {output_path}")
        else:
            print("\n" + "=" * 50)
            print(json.dumps(result, ensure_ascii=False, indent=2))

        return 0

    except Exception as e:
        print(f"\n❌ エラー: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
