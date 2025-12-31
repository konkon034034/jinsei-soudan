#!/usr/bin/env python3
"""
口コミランキングチャンネル - 台本生成システム
字幕をカツミ＆ヒロシの掛け合い形式に変換
"""

import os
import sys
import json
from pathlib import Path

# 親ディレクトリをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

import google.generativeai as genai

# キャラクター設定をインポート
try:
    from character_settings import CHARACTER_PROMPT, CHARACTERS
except ImportError:
    CHARACTER_PROMPT = ""
    CHARACTERS = {}


class ScriptGenerator:
    """台本生成クラス"""

    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY が設定されていません")

        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel("gemini-2.5-flash")

    def generate_script(self, transcript_text: str, topic: str = "口コミランキング",
                        max_lines: int = 30) -> dict:
        """
        字幕テキストから掛け合い台本を生成

        Args:
            transcript_text: 元の字幕テキスト
            topic: 動画のトピック
            max_lines: 最大セリフ数

        Returns:
            {
                "title": str,
                "description": str,
                "dialogue": [
                    {"speaker": "カツミ", "text": "..."},
                    {"speaker": "ヒロシ", "text": "..."},
                    ...
                ]
            }
        """
        print("📝 台本を生成中...")

        prompt = f"""以下の口コミ動画の内容を、カツミとヒロシの掛け合い形式の台本にリライトしてください。

{CHARACTER_PROMPT}

【元の動画内容】
{transcript_text[:4000]}

【リライトの方針】
1. 元の情報の要点を正確に伝える
2. カツミがメインで説明、ヒロシがリアクション・質問
3. 自然な会話形式にする
4. 1セリフは20〜50文字程度
5. 合計{max_lines}セリフ以内
6. 各セリフは最低15文字以上（TTS用）

【口調の例】
カツミ: 「あら、これ知ってる？すごくお得なのよ」「正直に言うと、これはイマイチだわ」
ヒロシ: 「確かに、それは気になりますね」「なるほど、そういう見方もありますか」

【出力形式】
以下のJSON形式で出力してください:
{{
    "title": "動画タイトル（30文字以内）",
    "description": "動画の説明（100文字程度）",
    "dialogue": [
        {{"speaker": "カツミ", "text": "セリフ内容"}},
        {{"speaker": "ヒロシ", "text": "セリフ内容"}},
        ...
    ]
}}

JSONのみを出力してください。
"""

        try:
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json"
                )
            )

            # レスポンスをパース
            result_text = response.text.strip()

            # JSONブロックを抽出
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            script = json.loads(result_text)

            # 検証
            if "dialogue" not in script:
                raise ValueError("dialogue フィールドがありません")

            print(f"✅ 台本生成完了: {len(script['dialogue'])}セリフ")
            print(f"   タイトル: {script.get('title', '未設定')}")

            return script

        except json.JSONDecodeError as e:
            print(f"❌ JSONパースエラー: {e}")
            raise
        except Exception as e:
            print(f"❌ 台本生成エラー: {e}")
            raise

    def validate_script(self, script: dict) -> list:
        """
        台本を検証し、問題点をリスト化

        Returns:
            問題点のリスト（空なら問題なし）
        """
        issues = []

        if not script.get("title"):
            issues.append("タイトルがありません")

        dialogue = script.get("dialogue", [])
        if len(dialogue) < 5:
            issues.append(f"セリフ数が少なすぎます: {len(dialogue)}件")

        for i, line in enumerate(dialogue):
            if not line.get("speaker"):
                issues.append(f"セリフ{i+1}: speakerがありません")
            if not line.get("text"):
                issues.append(f"セリフ{i+1}: textがありません")
            elif len(line["text"]) < 10:
                issues.append(f"セリフ{i+1}: テキストが短すぎます ({len(line['text'])}文字)")

        return issues


def generate_from_transcript(transcript_text: str, topic: str = "口コミ") -> dict:
    """
    字幕テキストから台本を生成（簡易インターフェース）
    """
    generator = ScriptGenerator()
    script = generator.generate_script(transcript_text, topic)

    # 検証
    issues = generator.validate_script(script)
    if issues:
        print("⚠️ 検証結果:")
        for issue in issues:
            print(f"   - {issue}")

    return script


if __name__ == "__main__":
    # テスト
    test_transcript = """
    今回は2024年に話題になった商品をランキング形式で紹介します。
    第3位は100均で買える便利グッズです。これがすごく便利なんです。
    第2位はAmazonで人気の家電製品。コスパ最高と評判です。
    第1位は主婦の間で大人気のキッチングッズ。これは本当におすすめ。
    """

    try:
        script = generate_from_transcript(test_transcript, "話題の商品ランキング")
        print("\n=== 生成された台本 ===")
        print(json.dumps(script, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"❌ エラー: {e}")
