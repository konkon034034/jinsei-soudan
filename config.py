#!/usr/bin/env python3
"""3チャンネル用の設定"""

import random

# 相談者の名前リスト（ランダムで選ばれる）
CONSULTER_NAMES_MALE = [
    "正夫", "和夫", "勝", "博", "清", "茂", "弘", "隆", "誠", "浩",
    "健一", "修", "豊", "進", "実", "明", "義男", "武", "正", "昭"
]

CONSULTER_NAMES_FEMALE = [
    "幸子", "和子", "節子", "洋子", "恵子", "京子", "美智子", "昭子",
    "久子", "文子", "敏子", "悦子", "弘子", "良子", "信子", "千代子"
]

def get_random_consulter_name():
    """ランダムな相談者名を取得"""
    all_names = CONSULTER_NAMES_MALE + CONSULTER_NAMES_FEMALE
    return random.choice(all_names)


# 3チャンネルの設定
CHANNEL_CONFIGS = {
    "jinsei": {
        "name": "人生相談",
        "sheet_name": "人生相談",
        "advisor_name": "マダム・ミレーヌ",
        "advisor_voice": "ja-JP-Wavenet-A",  # 女性・落ち着いた
        "advisor_pitch": -2.0,
        "advisor_rate": 0.9,
        "consulter_voice": "ja-JP-Neural2-B",  # 相談者
        "consulter_pitch": 2.0,
        "consulter_rate": 1.1,
        "reference_channel": "https://www.youtube.com/@wdemetrius62",
        "youtube_token_secret": "YOUTUBE_REFRESH_TOKEN_1",
        "upload_channel": "ザ昭和シリーズ",
    },
    "denwa": {
        "name": "電話相談",
        "sheet_name": "電話相談",
        "advisor_name": "ヴェルヴェーヌ",
        "advisor_voice": "ja-JP-Wavenet-A",  # 女性・優しい
        "advisor_pitch": 0.0,
        "advisor_rate": 0.95,
        "consulter_voice": "ja-JP-Neural2-B",
        "consulter_pitch": 2.0,
        "consulter_rate": 1.1,
        "reference_channel": "https://www.youtube.com/@skaterkid0324",
        "youtube_token_secret": "YOUTUBE_REFRESH_TOKEN_2",
        "upload_channel": "たかし☕️朝ドラ喫茶🎩マスター",
    },
    "ningen": {
        "name": "人間関係相談",
        "sheet_name": "人間関係相談",
        "advisor_name": "加東先生",
        "advisor_voice": "ja-JP-Wavenet-C",  # 男性・渋い
        "advisor_pitch": -4.0,
        "advisor_rate": 0.85,
        "consulter_voice": "ja-JP-Neural2-B",
        "consulter_pitch": 2.0,
        "consulter_rate": 1.1,
        "reference_channel": "https://www.youtube.com/@marzell_jones",
        "youtube_token_secret": "YOUTUBE_REFRESH_TOKEN_3",
        "upload_channel": "元お水店長のゲーム部屋Ⅱ",
    },
}


def get_config(channel_key: str) -> dict:
    """チャンネル設定を取得"""
    if channel_key not in CHANNEL_CONFIGS:
        raise ValueError(f"Unknown channel: {channel_key}")
    
    config = CHANNEL_CONFIGS[channel_key].copy()
    config["consulter_name"] = get_random_consulter_name()
    return config
