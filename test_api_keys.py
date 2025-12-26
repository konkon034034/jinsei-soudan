#!/usr/bin/env python3
"""
Gemini APIキーのテストスクリプト
各キーを個別にテストして、どれが動作するか確認
"""

import os
import sys
import google.generativeai as genai


def test_api_key(key_name: str, api_key: str) -> dict:
    """APIキーをテスト"""
    result = {
        "name": key_name,
        "key_preview": api_key[:8] + "..." + api_key[-4:] if api_key else "None",
        "status": "unknown",
        "error": None
    }

    if not api_key:
        result["status"] = "未設定"
        return result

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        # 簡単なテストリクエスト
        response = model.generate_content("Say 'Hello' in Japanese. Just one word.")

        if response and response.text:
            result["status"] = "✅ 成功"
            result["response"] = response.text[:50]
        else:
            result["status"] = "⚠️ 空のレスポンス"

    except Exception as e:
        error_str = str(e)
        if "429" in error_str:
            result["status"] = "❌ クォータ切れ (429)"
        elif "503" in error_str:
            result["status"] = "❌ サーバーエラー (503)"
        elif "401" in error_str or "403" in error_str:
            result["status"] = "❌ 認証エラー"
        elif "Invalid" in error_str:
            result["status"] = "❌ 無効なキー"
        else:
            result["status"] = f"❌ エラー"
        result["error"] = error_str[:200]

    return result


def main():
    print("=" * 60)
    print("Gemini APIキー テスト")
    print("=" * 60)

    # テスト対象のキー
    keys_to_test = [
        ("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY")),
        ("GEMINI_API_KEY_1", os.environ.get("GEMINI_API_KEY_1")),
        ("GEMINI_API_KEY_2", os.environ.get("GEMINI_API_KEY_2")),
        ("GEMINI_API_KEY_3", os.environ.get("GEMINI_API_KEY_3")),
    ]

    # 設定状況を表示
    print("\n【環境変数の設定状況】")
    for name, key in keys_to_test:
        if key:
            print(f"  {name}: {key[:8]}...{key[-4:]} (長さ: {len(key)})")
        else:
            print(f"  {name}: 未設定")

    # 各キーをテスト
    print("\n【APIキーテスト結果】")
    print("-" * 60)

    results = []
    for name, key in keys_to_test:
        print(f"\n{name} をテスト中...")
        result = test_api_key(name, key)
        results.append(result)

        print(f"  キー: {result['key_preview']}")
        print(f"  結果: {result['status']}")
        if result.get("response"):
            print(f"  応答: {result['response']}")
        if result.get("error"):
            print(f"  エラー詳細: {result['error'][:100]}")

    # サマリー
    print("\n" + "=" * 60)
    print("【サマリー】")
    print("=" * 60)

    success_count = sum(1 for r in results if "成功" in r["status"])
    quota_count = sum(1 for r in results if "クォータ" in r["status"])
    error_count = sum(1 for r in results if "❌" in r["status"] and "クォータ" not in r["status"])

    print(f"  成功: {success_count}個")
    print(f"  クォータ切れ: {quota_count}個")
    print(f"  その他エラー: {error_count}個")

    if success_count > 0:
        print("\n✅ 動作するAPIキーがあります！")
        return 0
    elif quota_count == len([r for r in results if r["key_preview"] != "None"]):
        print("\n⚠️ 全キーがクォータ切れです。明日まで待つか、新しいキーを追加してください。")
        return 1
    else:
        print("\n❌ APIキーに問題があります。キーを確認してください。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
