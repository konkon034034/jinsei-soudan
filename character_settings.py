#!/usr/bin/env python3
"""
キャラクター設定ファイル
全チャンネル共通のMCキャラクター設定

使用方法:
    from character_settings import CHARACTERS, get_voice_for_speaker, CHARACTER_PROMPT
"""

import os

# ===== Fish Audio ボイスID =====
# カツミ（女性）: 女性アナウンサー（ベテラン）- 信頼感ある落ち着いた進行役
FISH_VOICE_KATSUMI = "f1d92c18f84e47c6b5bc0cebb80ddaf5"

# ヒロシ（男性）: おじさん（極道風）- 毒舌ツッコミ役
FISH_VOICE_HIROSHI = "dd25aabce1894d94b5c3d1230efaeb68"


# ===== メインキャラクター設定 =====
CHARACTERS = {
    "カツミ": {
        "voice": FISH_VOICE_KATSUMI,
        "voice_name": "女性アナウンサー（ベテラン）",
        "color": "#FFE4B5",  # モカシン（オレンジ系）
        "color_rgb": (255, 228, 181),
        "role": "メインMC",
        "personality": "論理的、知的、落ち着いた",
        "speaking_style": [
            "丁寧語で話す",
            "「皆さんご存知の通り」「〇〇ですよね」などの表現",
            "ランキングの紹介・説明を担当",
            "視聴者に語りかけるような話し方",
        ],
        "emotion_patterns": {
            "共感": "(empathetic)",
            "説明": "",  # デフォルト
            "強調": "(confident)",
        }
    },
    "ヒロシ": {
        "voice": FISH_VOICE_HIROSHI,
        "voice_name": "おじさん（極道風）",
        "color": "#6495ED",  # コーンフラワーブルー
        "color_rgb": (100, 149, 237),
        "role": "サブMC・ツッコミ担当",
        "personality": "素直、リアクション上手、毒舌",
        "speaking_style": [
            "「へぇ〜」「なるほど」「それは知らなかった」などリアクション",
            "視聴者目線で質問したり感想を言う",
            "時々毒舌で本音を言う",
            "カツミの説明に対してツッコミを入れる",
        ],
        "emotion_patterns": {
            "毒舌": "(sarcastic)",
            "驚き": "(surprised)",
            "断言": "(confident)",
            "共感": "",  # デフォルト
            "フラストレーション": "(frustrated)",
        }
    }
}


# ===== チャンネル別ボイス設定 =====
# channel: (カツミのボイス, ヒロシのボイス)
CHANNEL_VOICE_CONFIG = {
    "27": (FISH_VOICE_KATSUMI, FISH_VOICE_HIROSHI),  # シニア口コミランキング
    "23": (FISH_VOICE_KATSUMI, FISH_VOICE_HIROSHI),  # 年金ニュース
    "24": (FISH_VOICE_KATSUMI, FISH_VOICE_HIROSHI),  # テスト用
}


# ===== Fish Audio ボイス名マッピング =====
FISH_VOICE_NAMES = {
    FISH_VOICE_KATSUMI: "女性アナウンサー（ベテラン）",
    FISH_VOICE_HIROSHI: "おじさん（極道風）",
}


# ===== 台本生成用プロンプト =====
CHARACTER_PROMPT = """
【キャラクター設定】

🎙️ カツミ（メインMC）
- 役割: メインMC、進行役
- 性格: 論理的で知的、落ち着いたトーン
- 話し方:
  - ランキングの紹介・説明を担当
  - 「皆さんご存知の通り」「〇〇ですよね」など丁寧語
  - 視聴者に語りかけるような話し方

🎙️ ヒロシ（サブMC）
- 役割: サブMC、ツッコミ担当
- 性格: 素直な感想・リアクションを担当、時々毒舌
- 話し方:
  - 「へぇ〜」「なるほど」「それは知らなかった」などリアクション
  - 視聴者目線で質問したり感想を言う
  - カツミの説明に対してツッコミを入れる

【掛け合いの基本パターン】
1. カツミ：「第〇位は『〇〇』です」（発表）
2. ヒロシ：「おお、これはよく聞きますね」（リアクション）
3. カツミ：「この事例では〇〇が原因でした」（説明）
4. ヒロシ：「確かに、気をつけないといけませんね」（共感）
5. カツミ：「そうなんです、〇〇な点が重要です」（補足）
6. 交互に続く...
"""


def get_voice_for_speaker(speaker: str, channel: str = "27") -> str:
    """
    スピーカー名からボイスIDを取得

    Args:
        speaker: "カツミ" または "ヒロシ"
        channel: チャンネル番号

    Returns:
        ボイスID
    """
    if channel in CHANNEL_VOICE_CONFIG:
        katsumi_voice, hiroshi_voice = CHANNEL_VOICE_CONFIG[channel]
        if speaker == "カツミ":
            return katsumi_voice
        elif speaker == "ヒロシ":
            return hiroshi_voice

    # デフォルト
    return CHARACTERS.get(speaker, {}).get("voice", FISH_VOICE_KATSUMI)


def get_voice_name(voice_id: str) -> str:
    """ボイスIDから説明を取得"""
    return FISH_VOICE_NAMES.get(voice_id, voice_id[:8] + "...")


def get_character_color(speaker: str) -> str:
    """スピーカー名から色コードを取得"""
    return CHARACTERS.get(speaker, {}).get("color", "#FFFFFF")


def get_character_color_rgb(speaker: str) -> tuple:
    """スピーカー名からRGB色を取得"""
    return CHARACTERS.get(speaker, {}).get("color_rgb", (255, 255, 255))


def setup_channel_voices(channel: str):
    """
    チャンネルに応じてキャラクターのボイスを設定

    Args:
        channel: チャンネル番号

    Note:
        この関数はCHARACTERSをin-placeで更新する
    """
    if channel in CHANNEL_VOICE_CONFIG:
        katsumi_voice, hiroshi_voice = CHANNEL_VOICE_CONFIG[channel]
        CHARACTERS["カツミ"]["voice"] = katsumi_voice
        CHARACTERS["ヒロシ"]["voice"] = hiroshi_voice
        print(f"  ボイス設定: カツミ={get_voice_name(katsumi_voice)}, "
              f"ヒロシ={get_voice_name(hiroshi_voice)}")


def detect_emotion_tag(speaker: str, text: str) -> str:
    """
    セリフの内容から感情タグを判定

    感情タグルール:
    - カツミ（普通）: タグなし
    - カツミ（共感）: (empathetic)
    - ヒロシ（毒舌）: (frustrated) または (sarcastic)
    - ヒロシ（ツッコミ）: (surprised)
    - ヒロシ（断言）: (confident)
    """
    # 毒舌・皮肉パターン
    toxic_patterns = ["まあ", "正直", "ぶっちゃけ", "ひどい", "残念", "ダメ", "最悪", "無理", "やばい", "やめて"]
    # ツッコミパターン
    tsukkomi_patterns = ["えっ", "え？", "何それ", "マジで", "うそ", "本当", "信じられない", "！？", "!?"]
    # 断言パターン
    confident_patterns = ["間違いない", "絶対", "確実", "これは", "断言", "やっぱり", "当然", "もちろん"]
    # 共感パターン
    empathetic_patterns = ["わかる", "そうだね", "確かに", "なるほど", "いいね", "素敵", "すごい", "感動"]

    if speaker == "ヒロシ":
        # 毒舌チェック
        for pattern in toxic_patterns:
            if pattern in text:
                import random
                return "(sarcastic) " if random.random() > 0.5 else "(frustrated) "
        # ツッコミチェック
        for pattern in tsukkomi_patterns:
            if pattern in text:
                return "(surprised) "
        # 断言チェック
        for pattern in confident_patterns:
            if pattern in text:
                return "(confident) "

    elif speaker == "カツミ":
        # 共感チェック
        for pattern in empathetic_patterns:
            if pattern in text:
                return "(empathetic) "

    return ""  # タグなし


# ===== 字幕スタイル設定 =====
SUBTITLE_STYLES = {
    "カツミ": {
        "ass_style_name": "Katsumi",
        "font_name": "Noto Sans CJK JP",
        "font_size": 64,
        "primary_color": "&H00FFE4B5",  # モカシン（BGR形式）
        "outline_color": "&H00000000",
        "back_color": "&H80000000",
        "margin_v_percent": 0.35,  # 画面下から35%
        "alignment": 2,  # 下中央
    },
    "ヒロシ": {
        "ass_style_name": "Hiroshi",
        "font_name": "Noto Sans CJK JP",
        "font_size": 64,
        "primary_color": "&H006495ED",  # コーンフラワーブルー（BGR形式）
        "outline_color": "&H00000000",
        "back_color": "&H80000000",
        "margin_v_percent": 0.20,  # 画面下から20%
        "alignment": 2,  # 下中央
    },
}


if __name__ == "__main__":
    # テスト出力
    print("=" * 50)
    print("キャラクター設定")
    print("=" * 50)

    for name, char in CHARACTERS.items():
        print(f"\n{name}:")
        print(f"  役割: {char['role']}")
        print(f"  性格: {char['personality']}")
        print(f"  ボイス: {char['voice_name']}")
        print(f"  色: {char['color']}")

    print("\n" + "=" * 50)
    print("チャンネル別ボイス設定")
    print("=" * 50)
    for ch, (k, h) in CHANNEL_VOICE_CONFIG.items():
        print(f"  チャンネル{ch}: カツミ={get_voice_name(k)}, ヒロシ={get_voice_name(h)}")
