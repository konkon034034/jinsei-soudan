#!/usr/bin/env python3
"""
年金データ表ショート動画システム v2
- 毎日違う年金ネタの「保存したくなる表」を表示
- カツミとヒロシが60秒トーク
- 最後に「この画像保存しとこっと」で保存を促す
"""

import os
import sys
import json
import re
import time
import tempfile
import requests
import subprocess
import io
import random
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai
from google.genai import types
from pydub import AudioSegment
from PIL import Image, ImageDraw, ImageFont
import qrcode
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from character_settings import apply_reading_dict

# ===== 設定 =====
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
MAX_DURATION = 60

# テストモード
TEST_MODE = os.environ.get("TEST_MODE", "").lower() == "true"
SKIP_API = os.environ.get("SKIP_API", "").lower() == "true"

# TTS設定
TTS_MODEL = "gemini-2.5-flash-preview-tts"
VOICE_KATSUMI = "Kore"   # カツミ（女性）
VOICE_HIROSHI = "Puck"   # ヒロシ（男性）

# ジングル・BGM設定（Google Drive ID）
JINGLE_FILE_ID = "1TdXxBkuGHWBwGcLxyGJCkuggDxomHqfD"
BGM_FILE_ID = "14X_YrRkGvq5rKofXsOL9X42zmYnaXjF1"
BGM_VOLUME_REDUCTION = 18  # dB減（トークの邪魔にならないように）

# 背景画像（Google Drive ID）
BACKGROUND_IMAGE_ID = "1ywnGZHMZWavnus1-fPD1MVI3fWxSrAIp"

# 再生リスト設定
PLAYLIST_TITLE = "🧓 シニア必見！1分年金講座"
PLAYLIST_DESCRIPTION = """年金のこと、ちゃんと知ってますか？

60秒でサクッとわかる年金データを
毎日お届けしています📊

✅ 受給額の損益分岐点
✅ 届出・手続き一覧
✅ 知らないともったいない制度

「あとで見る」より「今すぐ保存」📌
知ってるか知らないかで、全然違います。

🔔 チャンネル登録で最新情報をお届け！
📱 LINE登録はチャンネルページのリンクから！"""

# ===== テーマリスト =====
THEMES = [
    {
        "id": 1,
        "name": "年金受給開始年齢別の損益分岐点",
        "description": "繰り上げ・繰り下げ受給による総受給額の違いと損益分岐点を表にする"
    },
    {
        "id": 2,
        "name": "年金だけで暮らせる都道府県ランキング",
        "description": "生活費と年金受給額を比較した都道府県別ランキング"
    },
    {
        "id": 3,
        "name": "年金世代の節約術ランキング",
        "description": "年金生活者が実践している節約術の人気ランキング"
    },
    {
        "id": 4,
        "name": "知らないと損する年金届出一覧",
        "description": "届け出忘れで損する可能性がある年金関連の届出リスト"
    },
    {
        "id": 5,
        "name": "年金事務所に行く前の準備物リスト",
        "description": "年金事務所での手続きに必要な持ち物チェックリスト"
    },
    {
        "id": 6,
        "name": "繰り下げvs繰り上げ受給総額比較",
        "description": "受給開始年齢別の総受給額シミュレーション表"
    },
    {
        "id": 7,
        "name": "年金から引かれるもの一覧",
        "description": "年金から天引きされる税金・保険料の一覧と金額目安"
    },
    {
        "id": 8,
        "name": "遺族年金の早見表",
        "description": "遺族年金の受給条件と金額の早見表"
    },
    {
        "id": 9,
        "name": "年金世代の副業ランキング",
        "description": "年金受給者に人気の副業・収入源ランキング"
    },
    {
        "id": 10,
        "name": "年金相談先の比較表",
        "description": "年金事務所・社労士・FPなど相談先の特徴比較"
    },
]

# ===== テーマ別ダミーデータ（API失敗時のフォールバック） =====
DUMMY_DATA_BY_THEME = {
    1: {  # 年金受給開始年齢別の損益分岐点
        "table": {
            "youtube_title": "あなたは大丈夫？年金受給額の損益分岐点【年金1分裏情報】",
            "screen_hook": "あなたは大丈夫？",
            "screen_theme": "年金受給の損益分岐点",
            "screen_cta": "保存して損回避！",
            "headers": ["受給開始", "受給率", "損益分岐点"],
            "rows": [
                {"cells": ["60歳", "76.0%", "82歳以上で損"], "highlight": "loss"},
                {"cells": ["62歳", "85.6%", "80歳以上で損"], "highlight": "loss"},
                {"cells": ["64歳", "95.2%", "78歳以上で損"], "highlight": "loss"},
                {"cells": ["65歳", "100%", "基準"], "highlight": "neutral"},
                {"cells": ["66歳", "108.4%", "78歳以上で得"], "highlight": "gain"},
                {"cells": ["68歳", "125.2%", "80歳以上で得"], "highlight": "gain"},
                {"cells": ["70歳", "142.0%", "82歳以上で得"], "highlight": "gain"},
            ],
            "footer": "※2024年度の年金制度に基づく目安"
        },
        "script": [
            {"speaker": "ヒロシ", "text": "60歳から受給すると76%しかもらえないんだ"},
            {"speaker": "カツミ", "text": "そうなのよ。82歳まで生きないと損なの"},
            {"speaker": "ヒロシ", "text": "じゃあ長生きする自信あれば繰り下げた方がいい？"},
            {"speaker": "カツミ", "text": "70歳まで待てば142%よ。でも82歳以上でトントン"},
            {"speaker": "ヒロシ", "text": "うーん、悩むなぁ"},
            {"speaker": "カツミ", "text": "健康状態と相談ね。この画像保存しとこっと"},
        ],
        "first_comment": "カツミです💕 70歳まで待つと142%ってすごいけど、82歳まで生きなきゃ元取れないのよね。健康第一！"
    },
    2: {  # 年金だけで暮らせる都道府県ランキング
        "table": {
            "youtube_title": "衝撃！年金だけで暮らせる県ランキング【年金1分裏情報】",
            "screen_hook": "住む場所で変わる！",
            "screen_theme": "年金で暮らせる県",
            "screen_cta": "移住検討に保存！",
            "headers": ["順位", "都道府県", "生活費差額"],
            "rows": [
                {"cells": ["1位", "秋田県", "+2.1万円"], "highlight": "gain"},
                {"cells": ["2位", "山形県", "+1.8万円"], "highlight": "gain"},
                {"cells": ["3位", "青森県", "+1.5万円"], "highlight": "gain"},
                {"cells": ["4位", "岩手県", "+1.2万円"], "highlight": "gain"},
                {"cells": ["5位", "新潟県", "+0.8万円"], "highlight": "gain"},
                {"cells": ["45位", "神奈川県", "-3.2万円"], "highlight": "loss"},
                {"cells": ["46位", "大阪府", "-3.5万円"], "highlight": "loss"},
                {"cells": ["47位", "東京都", "-5.8万円"], "highlight": "loss"},
            ],
            "footer": "※平均年金月額15万円との差額"
        },
        "script": [
            {"speaker": "ヒロシ", "text": "秋田県だと年金だけで2万円も余るの？"},
            {"speaker": "カツミ", "text": "東北は物価が安いのよね。家賃も全然違う"},
            {"speaker": "ヒロシ", "text": "東京だと5万8千円も足りないって..."},
            {"speaker": "カツミ", "text": "だから地方移住が増えてるのよ"},
            {"speaker": "ヒロシ", "text": "老後の住む場所、考えないとな"},
            {"speaker": "カツミ", "text": "この表保存して検討してね"},
        ],
        "first_comment": "カツミです💕 東京と秋田で月8万円も差があるなんて！移住も選択肢よね〜"
    },
    3: {  # 年金世代の節約術ランキング
        "table": {
            "youtube_title": "年金生活者が実践！節約術TOP10【年金1分裏情報】",
            "screen_hook": "みんなやってる！",
            "screen_theme": "年金世代の節約術",
            "screen_cta": "今日から実践！",
            "headers": ["順位", "節約術", "月の節約額"],
            "rows": [
                {"cells": ["1位", "格安スマホ", "約5,000円"], "highlight": "gain"},
                {"cells": ["2位", "シニア割引活用", "約3,000円"], "highlight": "gain"},
                {"cells": ["3位", "まとめ買い", "約2,500円"], "highlight": "gain"},
                {"cells": ["4位", "図書館利用", "約2,000円"], "highlight": "gain"},
                {"cells": ["5位", "早朝スーパー", "約1,500円"], "highlight": "gain"},
                {"cells": ["6位", "ポイ活", "約1,200円"], "highlight": "gain"},
                {"cells": ["7位", "自炊徹底", "約3,500円"], "highlight": "gain"},
                {"cells": ["8位", "保険見直し", "約4,000円"], "highlight": "gain"},
            ],
            "footer": "※実践者の平均節約額"
        },
        "script": [
            {"speaker": "ヒロシ", "text": "格安スマホで月5千円も節約できるの？"},
            {"speaker": "カツミ", "text": "大手キャリアは高いのよ。私も変えたわ"},
            {"speaker": "ヒロシ", "text": "シニア割引ってそんなにあるんだ"},
            {"speaker": "カツミ", "text": "映画館も電車も飲食店も、聞いてみるのよ"},
            {"speaker": "ヒロシ", "text": "全部やったら月2万円くらい浮くな"},
            {"speaker": "カツミ", "text": "この表見て今日から実践よ！保存してね"},
        ],
        "first_comment": "カツミです💕 格安スマホは本当におすすめ！全然変わらないのに5千円も安くなったの〜"
    },
    4: {  # 知らないと損する年金届出一覧
        "table": {
            "youtube_title": "届出忘れで損！年金届出一覧【年金1分裏情報】",
            "screen_hook": "届出忘れてない？",
            "screen_theme": "年金届出チェック",
            "screen_cta": "確認して保存！",
            "headers": ["届出名", "対象者", "影響"],
            "rows": [
                {"cells": ["繰下げ届", "66歳以上", "届出ないと増額なし"], "highlight": "loss"},
                {"cells": ["加給年金届", "配偶者あり", "年39万円損"], "highlight": "loss"},
                {"cells": ["振替加算届", "妻65歳時", "年6万円損"], "highlight": "loss"},
                {"cells": ["住所変更届", "引越し時", "届かなくなる"], "highlight": "loss"},
                {"cells": ["口座変更届", "変更時", "振込されない"], "highlight": "loss"},
                {"cells": ["死亡届", "死亡時", "不正受給に"], "highlight": "loss"},
                {"cells": ["未届出確認", "年1回", "年金事務所へ"], "highlight": "neutral"},
            ],
            "footer": "※届出は年金事務所で無料"
        },
        "script": [
            {"speaker": "ヒロシ", "text": "加給年金の届出忘れると年39万円損？"},
            {"speaker": "カツミ", "text": "配偶者がいる人は絶対確認して"},
            {"speaker": "ヒロシ", "text": "振替加算って何？"},
            {"speaker": "カツミ", "text": "妻が65歳になった時の届出よ。忘れがち"},
            {"speaker": "ヒロシ", "text": "これ全部自分で届けないとダメなのか"},
            {"speaker": "カツミ", "text": "そう！この一覧保存して確認してね"},
        ],
        "first_comment": "カツミです💕 届出忘れで何十万円も損してる人多いのよ！年金事務所で確認してね〜"
    },
    5: {  # 年金事務所に行く前の準備物リスト
        "table": {
            "youtube_title": "二度手間防止！年金事務所の持ち物【年金1分裏情報】",
            "screen_hook": "忘れ物注意！",
            "screen_theme": "年金事務所の持ち物",
            "screen_cta": "行く前に確認！",
            "headers": ["持ち物", "用途", "必須度"],
            "rows": [
                {"cells": ["年金手帳", "番号確認", "必須"], "highlight": "loss"},
                {"cells": ["マイナンバー", "本人確認", "必須"], "highlight": "loss"},
                {"cells": ["身分証明書", "本人確認", "必須"], "highlight": "loss"},
                {"cells": ["通帳", "口座確認", "必須"], "highlight": "loss"},
                {"cells": ["印鑑", "届出書用", "必須"], "highlight": "loss"},
                {"cells": ["委任状", "代理の場合", "該当者"], "highlight": "neutral"},
                {"cells": ["戸籍謄本", "加給年金等", "該当者"], "highlight": "neutral"},
                {"cells": ["診断書", "障害年金", "該当者"], "highlight": "neutral"},
            ],
            "footer": "※事前予約で待ち時間短縮"
        },
        "script": [
            {"speaker": "ヒロシ", "text": "年金事務所、何持っていけばいいの？"},
            {"speaker": "カツミ", "text": "年金手帳とマイナンバーは絶対よ"},
            {"speaker": "ヒロシ", "text": "通帳も必要なんだ"},
            {"speaker": "カツミ", "text": "振込口座の確認に使うの。印鑑もね"},
            {"speaker": "ヒロシ", "text": "忘れたら二度手間だもんな"},
            {"speaker": "カツミ", "text": "この表保存して行く前にチェックしてね"},
        ],
        "first_comment": "カツミです💕 年金事務所は予約していくと待ち時間なしよ！電話で予約できるわ〜"
    },
    6: {  # 繰り下げvs繰り上げ受給総額比較
        "table": {
            "youtube_title": "繰り下げvs繰り上げ！総額比較【年金1分裏情報】",
            "screen_hook": "どっちが得？",
            "screen_theme": "繰下げvs繰上げ",
            "screen_cta": "シミュレーションに！",
            "headers": ["開始年齢", "85歳時総額", "90歳時総額"],
            "rows": [
                {"cells": ["60歳", "4,560万円", "5,472万円"], "highlight": "loss"},
                {"cells": ["62歳", "4,711万円", "5,748万円"], "highlight": "loss"},
                {"cells": ["65歳", "4,800万円", "6,000万円"], "highlight": "neutral"},
                {"cells": ["67歳", "4,723万円", "6,139万円"], "highlight": "gain"},
                {"cells": ["70歳", "4,260万円", "5,964万円"], "highlight": "gain"},
            ],
            "footer": "※月額20万円で試算"
        },
        "script": [
            {"speaker": "ヒロシ", "text": "85歳までなら60歳開始が一番多いの？"},
            {"speaker": "カツミ", "text": "そうなの。でも90歳まで生きると逆転"},
            {"speaker": "ヒロシ", "text": "70歳開始だと85歳時点で600万円少ない"},
            {"speaker": "カツミ", "text": "でも90歳まで生きれば取り戻せるわ"},
            {"speaker": "ヒロシ", "text": "自分の寿命次第か...難しいな"},
            {"speaker": "カツミ", "text": "家系の寿命も参考にしてね。保存しとこ"},
        ],
        "first_comment": "カツミです💕 私は70歳まで繰り下げるつもり。142%になるから！長生きする気満々よ〜"
    },
    7: {  # 年金から引かれるもの一覧
        "table": {
            "youtube_title": "手取りは？年金から引かれるもの【年金1分裏情報】",
            "screen_hook": "思ったより少ない！",
            "screen_theme": "年金の天引き一覧",
            "screen_cta": "手取り計算に！",
            "headers": ["項目", "月額目安", "対象"],
            "rows": [
                {"cells": ["所得税", "約3,000円", "年金211万超"], "highlight": "loss"},
                {"cells": ["住民税", "約8,000円", "年金155万超"], "highlight": "loss"},
                {"cells": ["国民健康保険", "約12,000円", "全員"], "highlight": "loss"},
                {"cells": ["介護保険", "約6,000円", "65歳以上"], "highlight": "loss"},
                {"cells": ["後期高齢者医療", "約5,000円", "75歳以上"], "highlight": "loss"},
                {"cells": ["合計", "約3.4万円", "平均的な例"], "highlight": "neutral"},
            ],
            "footer": "※収入や自治体により異なる"
        },
        "script": [
            {"speaker": "ヒロシ", "text": "年金から3万4千円も引かれるの？"},
            {"speaker": "カツミ", "text": "そうなのよ。手取りは思ったより少ない"},
            {"speaker": "ヒロシ", "text": "健康保険と介護保険だけで1万8千円か"},
            {"speaker": "カツミ", "text": "75歳からは後期高齢者医療に変わるの"},
            {"speaker": "ヒロシ", "text": "手取り計算しておかないとな"},
            {"speaker": "カツミ", "text": "この表で計算してみてね。保存必須よ"},
        ],
        "first_comment": "カツミです💕 額面と手取りは全然違うから要注意！私も最初びっくりしたわ〜"
    },
    8: {  # 遺族年金の早見表
        "table": {
            "youtube_title": "もしもの時に！遺族年金早見表【年金1分裏情報】",
            "screen_hook": "もしもの備え！",
            "screen_theme": "遺族年金の早見表",
            "screen_cta": "家族で確認！",
            "headers": ["種類", "対象者", "年額目安"],
            "rows": [
                {"cells": ["遺族基礎年金", "18歳未満の子あり", "約100万円"], "highlight": "gain"},
                {"cells": ["子の加算", "第1子・第2子", "各23万円"], "highlight": "gain"},
                {"cells": ["子の加算", "第3子以降", "各7.5万円"], "highlight": "gain"},
                {"cells": ["遺族厚生年金", "配偶者等", "報酬比例の3/4"], "highlight": "gain"},
                {"cells": ["中高齢寡婦加算", "40-65歳の妻", "約60万円"], "highlight": "gain"},
                {"cells": ["経過的寡婦加算", "65歳以上の妻", "生年により変動"], "highlight": "neutral"},
            ],
            "footer": "※2024年度の金額"
        },
        "script": [
            {"speaker": "ヒロシ", "text": "遺族年金って結構もらえるんだな"},
            {"speaker": "カツミ", "text": "子供がいると遺族基礎年金100万円よ"},
            {"speaker": "ヒロシ", "text": "遺族厚生年金は報酬の3/4か"},
            {"speaker": "カツミ", "text": "夫の年金が多いほど多くなるわ"},
            {"speaker": "ヒロシ", "text": "もしもの時のために知っておくべきだな"},
            {"speaker": "カツミ", "text": "家族で共有しといてね。この表保存して"},
        ],
        "first_comment": "カツミです💕 遺族年金は意外と知らない人多いの。いざという時のために家族で確認してね〜"
    },
    9: {  # 年金世代の副業ランキング
        "table": {
            "youtube_title": "年金+αで安心！副業ランキング【年金1分裏情報】",
            "screen_hook": "年金だけじゃ不安？",
            "screen_theme": "年金世代の副業",
            "screen_cta": "収入UPの参考に！",
            "headers": ["順位", "副業", "月収目安"],
            "rows": [
                {"cells": ["1位", "シルバー人材", "3-8万円"], "highlight": "gain"},
                {"cells": ["2位", "マンション管理", "5-10万円"], "highlight": "gain"},
                {"cells": ["3位", "駐車場管理", "3-5万円"], "highlight": "gain"},
                {"cells": ["4位", "家事代行", "3-6万円"], "highlight": "gain"},
                {"cells": ["5位", "試験監督", "1-3万円"], "highlight": "gain"},
                {"cells": ["6位", "ハンドメイド販売", "1-5万円"], "highlight": "gain"},
                {"cells": ["7位", "治験モニター", "2-10万円"], "highlight": "neutral"},
            ],
            "footer": "※働く時間・頻度により変動"
        },
        "script": [
            {"speaker": "ヒロシ", "text": "シルバー人材センターってそんなに稼げる？"},
            {"speaker": "カツミ", "text": "週3くらいで月5万円くらいよ。体も動かせる"},
            {"speaker": "ヒロシ", "text": "マンション管理人は住み込み？"},
            {"speaker": "カツミ", "text": "住み込みじゃない巡回型もあるのよ"},
            {"speaker": "ヒロシ", "text": "年金だけじゃ不安だから考えようかな"},
            {"speaker": "カツミ", "text": "無理せず自分に合うの探してね。保存しとこ"},
        ],
        "first_comment": "カツミです💕 シルバー人材センターは登録無料よ！仲間もできて一石二鳥〜"
    },
    10: {  # 年金相談先の比較表
        "table": {
            "youtube_title": "どこに相談？年金相談先比較【年金1分裏情報】",
            "screen_hook": "相談先で違う！",
            "screen_theme": "年金相談先の比較",
            "screen_cta": "相談前に確認！",
            "headers": ["相談先", "費用", "特徴"],
            "rows": [
                {"cells": ["年金事務所", "無料", "公式・正確"], "highlight": "gain"},
                {"cells": ["街角年金相談", "無料", "予約しやすい"], "highlight": "gain"},
                {"cells": ["市区町村窓口", "無料", "身近・気軽"], "highlight": "gain"},
                {"cells": ["社会保険労務士", "有料", "専門的アドバイス"], "highlight": "neutral"},
                {"cells": ["FP", "有料", "総合的な設計"], "highlight": "neutral"},
                {"cells": ["銀行・証券", "無料", "商品勧誘あり"], "highlight": "loss"},
            ],
            "footer": "※まずは無料窓口がおすすめ"
        },
        "script": [
            {"speaker": "ヒロシ", "text": "年金の相談ってどこにすればいいの？"},
            {"speaker": "カツミ", "text": "まずは年金事務所よ。正確な情報がもらえる"},
            {"speaker": "ヒロシ", "text": "街角年金相談センターってなに？"},
            {"speaker": "カツミ", "text": "年金事務所と同じサービスで予約しやすいの"},
            {"speaker": "ヒロシ", "text": "銀行は商品勧誘があるのか..."},
            {"speaker": "カツミ", "text": "無料のところからがおすすめよ。保存してね"},
        ],
        "first_comment": "カツミです💕 年金事務所は電話予約すると待ち時間なしよ！ねんきんダイヤルも便利〜"
    },
}

# 後方互換性のため（SKIP_API時のデフォルト）
DUMMY_TABLE_DATA = DUMMY_DATA_BY_THEME[1]["table"]
DUMMY_SCRIPT = {
    "script": DUMMY_DATA_BY_THEME[1]["script"],
    "first_comment": DUMMY_DATA_BY_THEME[1]["first_comment"]
}


class GeminiKeyManager:
    """Gemini APIキー管理"""
    def __init__(self):
        self.keys = []
        self.key_names = []

        base_key = os.environ.get("GEMINI_API_KEY")
        if base_key:
            self.keys.append(base_key)
            self.key_names.append("GEMINI_API_KEY")

        for i in range(1, 43):
            key = os.environ.get(f"GEMINI_API_KEY_{i}")
            if key:
                self.keys.append(key)
                self.key_names.append(f"GEMINI_API_KEY_{i}")

        self.current_index = 0
        print(f"  利用可能なAPIキー: {len(self.keys)}個")

    def get_key(self):
        if not self.keys:
            raise ValueError("APIキーがありません")
        return self.keys[self.current_index]

    def get_key_name(self):
        return self.key_names[self.current_index]

    def next_key(self):
        self.current_index = (self.current_index + 1) % len(self.keys)
        return self.get_key()

    def get_key_for_index(self, index):
        """指定インデックス用のキーを取得（ラウンドロビン）"""
        idx = index % len(self.keys)
        return self.keys[idx], self.key_names[idx]


def download_from_drive(file_id: str, output_path: str) -> bool:
    """Google Driveからファイルをダウンロード（gdown使用）"""
    try:
        import gdown
        url = f"https://drive.google.com/uc?id={file_id}"
        gdown.download(url, output_path, quiet=False)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
            print(f"    ダウンロード成功: {os.path.getsize(output_path)} bytes")
            return True
        else:
            print(f"    ⚠ ダウンロード失敗: ファイルが小さすぎる")
    except Exception as e:
        print(f"    ⚠ ダウンロードエラー: {e}")
    return False


def download_background_image(file_id: str, output_path: str) -> bool:
    """背景画像をダウンロードして1080x1920にリサイズ"""
    try:
        import gdown
        from PIL import Image

        # 一時ファイルにダウンロード
        temp_path = output_path + ".tmp"
        url = f"https://drive.google.com/uc?id={file_id}"
        gdown.download(url, temp_path, quiet=False)

        if os.path.exists(temp_path) and os.path.getsize(temp_path) > 1000:
            # 1080x1920にリサイズ
            img = Image.open(temp_path)
            img = img.resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.Resampling.LANCZOS)
            img.save(output_path)
            os.remove(temp_path)
            print(f"    背景画像ダウンロード・リサイズ成功: {VIDEO_WIDTH}x{VIDEO_HEIGHT}")
            return True
        else:
            print(f"    ⚠ 背景画像ダウンロード失敗")
    except Exception as e:
        print(f"    ⚠ 背景画像エラー: {e}")
    return False


def select_theme() -> dict:
    """今日のテーマを選択"""
    # 日付ベースでローテーション（毎日違うテーマ）
    day_of_year = datetime.now().timetuple().tm_yday
    theme_index = day_of_year % len(THEMES)
    return THEMES[theme_index]


def get_dummy_data_for_theme(theme: dict) -> dict:
    """テーマに対応するダミーデータを取得"""
    theme_id = theme.get("id", 1)
    if theme_id in DUMMY_DATA_BY_THEME:
        return DUMMY_DATA_BY_THEME[theme_id]
    # 見つからない場合はデフォルト
    return DUMMY_DATA_BY_THEME[1]


def generate_table_data(theme: dict, key_manager: GeminiKeyManager) -> dict:
    """Gemini APIで表データを生成"""
    print(f"\n[1/6] 表データを生成中... テーマ: {theme['name']}")

    # テーマ別ダミーデータを取得
    dummy_data = get_dummy_data_for_theme(theme)

    if SKIP_API:
        print(f"  [SKIP_API] テーマ別ダミーデータを使用 (ID:{theme.get('id', 1)})")
        return dummy_data["table"]

    prompt = f"""あなたは年金の専門家です。
テーマ「{theme['name']}」について、ショート動画用のデータ表を作成してください。

{theme['description']}

以下のJSON形式で出力してください（JSONのみ、説明不要）：
{{
  "youtube_title": "マイルド煽り + テーマ名 + 【年金1分裏情報】",
  "screen_hook": "マイルド煽り（10文字以内）",
  "screen_theme": "テーマ名（15文字以内）",
  "screen_cta": "短いCTA（12文字以内）",
  "headers": ["列名1（6文字以内）", "列名2（6文字以内）", "列名3（6文字以内）"],
  "rows": [
    {{"cells": ["データ1", "データ2", "データ3"], "highlight": "loss"}},
    {{"cells": ["データ4", "データ5", "データ6"], "highlight": "neutral"}},
    {{"cells": ["データ7", "データ8", "データ9"], "highlight": "gain"}}
  ],
  "footer": "※注釈"
}}

ルール：
- 行数は8〜12行程度（多すぎると見づらい）
- 列数は2〜4列、各列名は6文字以内（長いと表示が崩れる）
- highlight: "loss"=損する情報（赤）, "gain"=得する情報（緑）, "neutral"=中立（黒）
- 数字は最新の2024年度データを使用
- youtube_title: YouTubeに投稿するタイトル「マイルド煽り + テーマ名 + 【年金1分裏情報】」
- screen_hook: 画面上部1行目（10文字以内）例：「あなたは大丈夫？」「知らないと損！」「確認した？」「意外と知らない！」
- screen_theme: 画面上部2行目（15文字以内）テーマ名のみ
- screen_cta: 画面下部CTA（12文字以内）例：「保存して損回避！」「今すぐ保存！」「保存必須！」「これ保存！」
- 具体的な数字や金額を入れる"""

    max_retries = 5  # 3→5に増加
    failed_keys = set()  # 失敗したキーを記録

    for attempt in range(max_retries):
        try:
            # 失敗したキーを避けて次のキーを選択
            for _ in range(len(key_manager.keys)):
                current_key = key_manager.get_key()
                if current_key not in failed_keys:
                    break
                key_manager.next_key()

            client = genai.Client(api_key=key_manager.get_key())

            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    response_mime_type="application/json"
                )
            )

            result_text = response.text.strip()
            # JSON抽出
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0]
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0]

            table_data = json.loads(result_text)
            print(f"  ✓ 表データ生成完了: {table_data.get('youtube_title', '')}")
            print(f"    行数: {len(table_data['rows'])}, 列数: {len(table_data['headers'])}")
            return table_data

        except Exception as e:
            error_str = str(e)
            failed_keys.add(key_manager.get_key())  # 失敗したキーを記録
            print(f"  ⚠ 試行{attempt + 1}/{max_retries} 失敗: {error_str[:50]}...")

            # 429エラーの場合は長めに待機
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                wait_time = 60  # 429エラーは60秒待機
            else:
                wait_time = 30  # その他のエラーは30秒待機

            key_manager.next_key()

            if attempt < max_retries - 1:
                print(f"    {wait_time}秒待機後にリトライ...")
                time.sleep(wait_time)

    print(f"  ❌ 表データ生成失敗、テーマ別ダミーデータを使用 (ID:{theme.get('id', 1)})")
    return dummy_data["table"]


def generate_table_image(table_data: dict, output_path: str):
    """表画像を生成（PIL）- スクロール用に縦長

    画像サイズ: 1080 x 2420
    - 最初は下半分だけ表示 (y=500からスタート)
    - 50秒かけてy=0までスクロール
    - 最後10秒はy=0で固定
    """
    print("\n[2/6] 表画像を生成中...")

    width = VIDEO_WIDTH
    # スクロール用に縦長画像 (1920 + 500 = 2420)
    height = VIDEO_HEIGHT + 500

    # 背景（透明 - 背景画像が見えるように）
    img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # フォント設定
    try:
        font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
        if not os.path.exists(font_path):
            font_path = "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"
        if not os.path.exists(font_path):
            font_path = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"

        title_font = ImageFont.truetype(font_path, 70)
        subtitle_font = ImageFont.truetype(font_path, 50)
        header_font = ImageFont.truetype(font_path, 36)
        cell_font = ImageFont.truetype(font_path, 32)
        footer_font = ImageFont.truetype(font_path, 24)
    except:
        title_font = ImageFont.load_default()
        subtitle_font = title_font
        header_font = title_font
        cell_font = title_font
        footer_font = title_font

    # 1行目: screen_hook（上部、黄色、太い黒縁取り+白影）
    screen_hook = table_data.get("screen_hook", "知らないと損！")
    hook_y = 60

    # 太い縁取り（黒、5px）
    outline_color = '#000000'
    outline_width = 5
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx != 0 or dy != 0:
                draw.text((width//2 + dx, hook_y + dy), screen_hook, fill=outline_color, font=title_font, anchor="mm")
    # 影（白、右下）
    draw.text((width//2 + 4, hook_y + 4), screen_hook, fill='#FFFFFF', font=title_font, anchor="mm")
    # 本体（黄色）
    draw.text((width//2, hook_y), screen_hook, fill='#FFD700', font=title_font, anchor="mm")

    # 2行目: screen_theme + 【年金1分裏情報】（太い黒縁取り+白影）
    screen_theme = table_data.get("screen_theme", "")
    theme_text = f"{screen_theme}【年金1分裏情報】" if screen_theme else "【年金1分裏情報】"
    theme_y = 130
    # 太い縁取り（黒、4px）
    for dx in range(-4, 5):
        for dy in range(-4, 5):
            if dx != 0 or dy != 0:
                draw.text((width//2 + dx, theme_y + dy), theme_text, fill='#000000', font=subtitle_font, anchor="mm")
    # 影（白）
    draw.text((width//2 + 3, theme_y + 3), theme_text, fill='#FFFFFF', font=subtitle_font, anchor="mm")
    # 本体（黄色）
    draw.text((width//2, theme_y), theme_text, fill='#FFFF00', font=subtitle_font, anchor="mm")

    # 表の描画
    headers = table_data.get("headers", [])
    rows = table_data.get("rows", [])

    if not headers or not rows:
        print("  ⚠ 表データが不正です")
        img.save(output_path, "PNG")
        return

    num_cols = len(headers)
    num_rows = len(rows)

    # 表のサイズと位置
    table_width = width - 80
    cell_height = 60
    header_height = 70
    table_height = header_height + cell_height * num_rows

    table_x = 40
    table_y = 220

    cell_width = table_width // num_cols

    # 表の背景（白、角丸）
    table_rect = [table_x, table_y, table_x + table_width, table_y + table_height]
    draw.rounded_rectangle(table_rect, radius=15, fill='#FFFFFF', outline='#333333', width=3)

    # ヘッダー行（黄色背景）
    header_rect = [table_x, table_y, table_x + table_width, table_y + header_height]
    draw.rounded_rectangle(header_rect, radius=15, fill='#FFD700', outline='#333333', width=2)
    # 下の角を四角にするために上書き
    draw.rectangle([table_x, table_y + header_height - 15, table_x + table_width, table_y + header_height], fill='#FFD700')

    # ヘッダーテキスト
    for i, header in enumerate(headers):
        x = table_x + cell_width * i + cell_width // 2
        y = table_y + header_height // 2
        draw.text((x, y), header, fill='#000000', font=header_font, anchor="mm")

    # データ行
    for row_idx, row in enumerate(rows):
        cells = row.get("cells", [])
        highlight = row.get("highlight", "neutral")

        row_y = table_y + header_height + cell_height * row_idx

        # 行の区切り線
        if row_idx > 0:
            draw.line([(table_x + 10, row_y), (table_x + table_width - 10, row_y)], fill='#CCCCCC', width=1)

        # 色設定
        if highlight == "loss":
            text_color = '#E53935'  # 赤
        elif highlight == "gain":
            text_color = '#43A047'  # 緑
        else:
            text_color = '#333333'  # 黒

        # セルテキスト
        for col_idx, cell in enumerate(cells):
            x = table_x + cell_width * col_idx + cell_width // 2
            y = row_y + cell_height // 2

            # テキストが長い場合は縮小
            display_text = cell[:20] + "..." if len(cell) > 20 else cell
            draw.text((x, y), display_text, fill=text_color, font=cell_font, anchor="mm")

    # 列の区切り線
    for i in range(1, num_cols):
        x = table_x + cell_width * i
        draw.line([(x, table_y + header_height), (x, table_y + table_height - 10)], fill='#CCCCCC', width=1)

    # フッター
    footer = table_data.get("footer", "")
    if footer:
        footer_y = table_y + table_height + 30
        draw.text((width//2, footer_y), footer, fill='#666666', font=footer_font, anchor="mm")

    # 下部CTAはASS字幕で固定表示するため、表画像内には描画しない

    img.save(output_path, "PNG")
    print(f"  ✓ 表画像生成完了: {output_path}")


def generate_script(table_data: dict, key_manager: GeminiKeyManager, theme: dict = None) -> dict:
    """台本を生成（first_comment含む）

    Args:
        table_data: 表データ
        key_manager: APIキー管理
        theme: テーマ情報（ダミーデータ選択用）

    Returns:
        dict: {"script": [...], "first_comment": "..."}
    """
    print("\n[3/6] 台本を生成中...")

    # テーマ別ダミーデータを取得
    if theme:
        dummy_data = get_dummy_data_for_theme(theme)
        dummy_script = {
            "script": dummy_data["script"],
            "first_comment": dummy_data["first_comment"]
        }
    else:
        dummy_script = DUMMY_SCRIPT

    if SKIP_API:
        theme_id = theme.get("id", 1) if theme else 1
        print(f"  [SKIP_API] テーマ別ダミー台本を使用 (ID:{theme_id})")
        return dummy_script

    # 表の内容を要約
    rows_summary = ""
    for row in table_data.get("rows", [])[:5]:  # 最初の5行
        cells = row.get("cells", [])
        rows_summary += "・" + " / ".join(cells) + "\n"

    prompt = f"""あなたは年金のことをコソコソ話すカツミとヒロシです。
以下の表について60秒で内緒話・ぶっちゃけトークしてください。

【表のタイトル】{table_data.get('screen_theme', '')}
【表の内容（一部）】
{rows_summary}

【登場人物】※コソコソ話・ぶっちゃけキャラスタイル

■カツミ（63歳・女性）
- 元スーパーのパート勤務、今は専業主婦
- 夫（ヒロシ）と二人暮らし、娘は結婚して独立
- 趣味：韓国ドラマ、スーパーの特売チェック、健康番組
- 悩み：老後のお金が不安、夫が話を聞いてくれない
- 話し方：「ぶっちゃけさ〜」「正直な話〜」「ここだけの話なんだけど」
- 視聴者を仲間に引き込む：「誰にも言わないでね」感
- ※関西弁は使わない

■ヒロシ（65歳・男性）
- 元サラリーマン（中小企業の経理）、最近定年退職
- 趣味：野球観戦（巨人ファン）、散歩、将棋
- 悩み：退職して暇、年金だけで生活できるか心配
- 話し方：「え、内緒の話？」「僕も知らなかったかも…」
- 視聴者と同じ目線で驚く役

■二人の関係性
- 結婚38年目の熟年夫婦
- カツミが内緒話を持ちかける→ヒロシが食いつく

【会話スタイル】※コソコソ話風
- カツミ「ねえ、ちょっとここだけの話なんだけど…」
- ヒロシ「え、なに？内緒の話？」
- カツミ「ぶっちゃけさ、これ知らない人めっちゃ損してるのよ」
- ヒロシ「えっ、そうなの？僕も知らなかったかも…」
- カツミ「でしょ？私も最近知ってびっくりしたの。損したくないじゃない？」
- ヒロシ「確かに…これは保存しとかないと」

ルール：
- 60秒以内（6〜8往復、合計250〜350文字程度）
- 1つのセリフは30文字以内（字幕が見やすくなる）
- 「ぶっちゃけ」「正直な話」「ここだけの話」を使う
- 「これ知らないと損するよ」感を出す
- ヒソヒソ声のイメージ、視聴者を仲間に引き込む
- 表のポイントを2〜3個解説
- 具体的な数字を引用する
- 【最重要】会話の最後の方で保存を促す：
  「これは保存しとかないとマズいわよ」
  「損したくないから動画保存しとく」
  「これスクショして親にも送っとくわ」

出力形式（JSONのみ、説明不要）：
{{
  "script": [
    {{"speaker": "ヒロシ", "text": "セリフ"}},
    {{"speaker": "カツミ", "text": "セリフ"}},
    ...
  ],
  "first_comment": "カツミの初コメント（150〜200文字）"
}}

【初コメント生成ルール】
カツミ（中高年女性）の人格で、視聴者に寄り添う初コメントを作成してください。
堅い年金の話だけじゃなく、日常のぼやきや本音を混ぜて、井戸端会議のような雰囲気に。

【必ず含める3要素】
1. 日常の話題（以下からランダムに1つ選んで書き出しに使う）
   - お昼ごはんの話（「今日はスーパーの半額弁当にしようかな」）
   - スーパーの物価（「卵がまた値上がりしてて…」）
   - 天気の話（「今日は寒いですね〜」「洗濯物乾かなくて困る〜」）
   - 芸能人の話題（「〇〇さんの結婚、びっくりしましたね」）
   - スポーツの話題（「昨日の野球見ました？」）
   - 健康の話（「最近腰が痛くて…」「健康診断の結果が気になる〜」）

2. 動画内容への軽いコメント
   - 「今日の話、私も知らなかったんですよ」
   - 「こういうの、もっと早く知りたかった〜」
   - 「皆さん知ってました？私びっくりしちゃって」

3. 視聴者への寄り添い
   - 「皆さんも気をつけてくださいね」
   - 「一緒に勉強していきましょうね」
   - 「分からないことあったらコメントしてね」

4. 最後にさりげなくLINEプレゼント告知（自然な形で）
   - 「そうそう、LINEで友だち登録すると新NISAガイドがもらえますよ〜📖」
   - 「あ、LINE登録で新NISAの資料もらえるから、興味ある人はぜひ〜」
   - 「LINEで友だち追加すると、私たちが作った新NISAガイドがもらえるんですよ〜」
   ※ 毎回少しずつ表現を変えて、宣伝っぽくならないように自然に

【カツミの性格・トーン】
- 親しみやすい中高年女性、日常のぼやきや本音をよく言う
- 視聴者を「皆さん」と呼んで寄り添う
- 「〜ですよね」「〜かしら」など柔らかい語尾
- 絵文字は控えめに（😊🙏📖程度で1〜2個）
- 200文字以内

【NG】
- 堅い敬語、宣伝っぽい文章
- 毎回同じような内容（日常話題は必ず変える）
- LINEのURLを直接書く（URLは後から自動追加されるため不要）"""

    max_retries = 5  # 3→5に増加
    failed_keys = set()  # 失敗したキーを記録

    for attempt in range(max_retries):
        try:
            # 失敗したキーを避けて次のキーを選択
            for _ in range(len(key_manager.keys)):
                current_key = key_manager.get_key()
                if current_key not in failed_keys:
                    break
                key_manager.next_key()

            client = genai.Client(api_key=key_manager.get_key())

            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.8,
                    response_mime_type="application/json"
                )
            )

            result_text = response.text.strip()
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0]
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0]

            result = json.loads(result_text)

            # 新フォーマット（dict）と旧フォーマット（list）の両方に対応
            if isinstance(result, list):
                # 旧フォーマット: listの場合はdictに変換
                script_data = {"script": result, "first_comment": ""}
            else:
                script_data = result

            script_lines = script_data.get("script", [])
            first_comment = script_data.get("first_comment", "")
            print(f"  ✓ 台本生成完了: {len(script_lines)}セリフ")
            if first_comment:
                print(f"  ✓ 初コメント生成完了: {first_comment[:30]}...")
            return script_data

        except Exception as e:
            error_str = str(e)
            failed_keys.add(key_manager.get_key())  # 失敗したキーを記録
            print(f"  ⚠ 試行{attempt + 1}/{max_retries} 失敗: {error_str[:50]}...")

            # 429エラーの場合は長めに待機
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                wait_time = 60
            else:
                wait_time = 30

            key_manager.next_key()

            if attempt < max_retries - 1:
                print(f"    {wait_time}秒待機後にリトライ...")
                time.sleep(wait_time)

    theme_id = theme.get("id", 1) if theme else 1
    print(f"  ❌ 台本生成失敗、テーマ別ダミー台本を使用 (ID:{theme_id})")
    return dummy_script


def _generate_single_tts(args: tuple) -> dict:
    """単一セリフのTTS生成"""
    index, line, api_key, key_name = args
    speaker = line["speaker"]
    text = apply_reading_dict(line["text"])  # 読み方辞書を適用
    voice = VOICE_HIROSHI if speaker == "ヒロシ" else VOICE_KATSUMI

    max_retries = 3
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=TTS_MODEL,
                contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice
                            )
                        )
                    )
                )
            )
            audio_data = response.candidates[0].content.parts[0].inline_data.data
            return {"index": index, "success": True, "audio_data": audio_data, "speaker": speaker, "key_name": key_name}
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(5)
    return {"index": index, "success": False, "audio_data": None, "speaker": speaker, "key_name": key_name}


def generate_tts_audio(script: list, output_path: str, key_manager: GeminiKeyManager) -> tuple:
    """TTS並列生成"""
    print("\n[4/6] 音声を並列生成中...")

    if SKIP_API:
        # 無音音声を生成
        duration = len(script) * 4.0
        silent = AudioSegment.silent(duration=int(duration * 1000))
        silent.export(output_path, format="wav")
        timings = []
        current = 0.0
        for i in range(len(script)):
            timings.append({"start": current, "end": current + 3.5})
            current += 4.0
        return duration, timings

    all_keys = key_manager.keys
    all_key_names = key_manager.key_names
    num_keys = len(all_keys)

    # タスク準備
    tasks = []
    for i, line in enumerate(script):
        key_idx = i % num_keys
        tasks.append((i, line, all_keys[key_idx], all_key_names[key_idx]))

    max_workers = min(len(script), num_keys, 10)
    print(f"  並列数: {max_workers}")

    results = [None] * len(script)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_generate_single_tts, task): task[0] for task in tasks}
        for future in as_completed(futures):
            result = future.result()
            results[result["index"]] = result
            status = "✓" if result["success"] else "✗"
            print(f"  {status} [{result['index']+1}/{len(script)}] {result['speaker']}")

    # 失敗リトライ
    for idx, r in enumerate(results):
        if not r["success"]:
            for key_idx in range(num_keys):
                retry_result = _generate_single_tts((idx, script[idx], all_keys[key_idx], all_key_names[key_idx]))
                if retry_result["success"]:
                    results[idx] = retry_result
                    break

    # 結合
    combined = AudioSegment.empty()
    timings = []
    current_time = 0.0
    gap_duration = 200

    for result in results:
        if not result["success"]:
            raise RuntimeError(f"TTS生成失敗: {script[result['index']]}")

        audio_segment = AudioSegment.from_raw(
            io.BytesIO(result["audio_data"]),
            sample_width=2, frame_rate=24000, channels=1
        )
        segment_duration = len(audio_segment) / 1000.0
        timings.append({"start": current_time, "end": current_time + segment_duration})
        current_time += segment_duration
        combined += audio_segment
        combined += AudioSegment.silent(duration=gap_duration)
        current_time += gap_duration / 1000.0

    combined.export(output_path, format="wav")
    duration = len(combined) / 1000.0
    print(f"  ✓ 音声生成完了: {duration:.1f}秒")
    return duration, timings


def wrap_subtitle_text(text: str, max_chars: int = 8) -> str:
    """字幕テキストを折り返し（最大8文字/行、読みやすく）"""
    if len(text) <= max_chars:
        return text

    lines = []
    current = ""
    for char in text:
        current += char
        if len(current) >= max_chars:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)

    return "\\N".join(lines)


def generate_subtitles(script: list, audio_duration: float, output_path: str, timings: list = None, jingle_duration: float = 0, video_title: str = ""):
    """ASS字幕を生成（表の下、60-70%位置に配置、大きめフォント）"""
    print("  字幕を生成中...")

    # 字幕位置: 画面の78.5%位置（下から21.5%）
    # 1920px * 0.215 = 413px
    margin_v = 413  # 下から413px = 上から約78.5%

    # フォントサイズ: 120px
    font_size = 120

    # CTA用設定: 画面の86.5%位置（YouTube UIに被ってもOK）
    # 1920px * 0.135 = 259px
    title_font_size = 105  # CTA 1.5倍サイズ
    title_margin_v = 259   # 下から259px = 上から約86.5%位置

    # BorderStyle=1 で縁取り+影、高齢者に見やすい配色
    # カツミ: 濃い紫(#800080)、白縁取り4px、黒影2px
    # ヒロシ: 濃い緑(#008000)、白縁取り4px、黒影2px
    # タイトル: 赤(#FF0000)、黄縁取り4px、黒影2px
    header = f"""[Script Info]
Title: Nenkin Table Short
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Katsumi,Noto Sans CJK JP,{font_size},&H00800080,&H000000FF,&H00FFFFFF,&H00000000,1,0,0,0,100,100,0,0,1,4,2,2,30,30,{margin_v},1
Style: Hiroshi,Noto Sans CJK JP,{font_size},&H00008000,&H000000FF,&H00FFFFFF,&H00000000,1,0,0,0,100,100,0,0,1,4,2,2,30,30,{margin_v},1
Style: VideoTitle,Noto Sans CJK JP,{title_font_size},&H000000FF,&H000000FF,&H0000FFFF,&H00000000,1,0,0,0,100,100,0,0,1,4,2,2,30,30,{title_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]

    # 動画タイトルを最初から最後まで固定表示
    if video_title:
        end_time_str = f"0:{int(audio_duration // 60):02d}:{audio_duration % 60:05.2f}"
        lines.append(f"Dialogue: 1,0:00:00.00,{end_time_str},VideoTitle,,0,0,0,,{video_title}")

    for i, line in enumerate(script):
        if timings and i < len(timings):
            # ジングル分のオフセットを追加
            start_time = timings[i]["start"] + jingle_duration
            end_time = timings[i]["end"] + jingle_duration
        else:
            time_per_line = audio_duration / len(script)
            start_time = i * time_per_line + jingle_duration
            end_time = (i + 1) * time_per_line + jingle_duration

        start_str = f"0:{int(start_time // 60):02d}:{start_time % 60:05.2f}"
        end_str = f"0:{int(end_time // 60):02d}:{end_time % 60:05.2f}"

        style = "Hiroshi" if line["speaker"] == "ヒロシ" else "Katsumi"

        # 8文字で折り返し（読みやすく）
        wrapped_text = wrap_subtitle_text(line["text"], max_chars=8)

        # ポップアップアニメーション
        popup = "{\\fscx80\\fscy80\\t(0,100,\\fscx100\\fscy100)}"
        lines.append(f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{popup}{wrapped_text}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def process_audio_with_jingle_bgm(talk_audio_path: str, output_path: str, temp_dir: Path) -> float:
    """ジングルとBGMを追加して最終音声を生成

    Returns:
        float: ジングルの長さ（秒）
    """
    print("\n[4.5/6] ジングル・BGM処理中...")

    # トーク音声を読み込み
    talk = AudioSegment.from_file(talk_audio_path)
    talk_duration = len(talk)

    jingle_duration = 0.0
    final_audio = talk

    # ジングルをダウンロード
    jingle_path = str(temp_dir / "jingle.mp3")
    print("  ジングルをダウンロード中...")
    if download_from_drive(JINGLE_FILE_ID, jingle_path):
        try:
            jingle = AudioSegment.from_file(jingle_path)
            jingle_duration = len(jingle) / 1000.0
            print(f"    ✓ ジングル: {jingle_duration:.1f}秒")

            # BGMをダウンロード
            bgm_path = str(temp_dir / "bgm.mp3")
            print("  BGMをダウンロード中...")
            if download_from_drive(BGM_FILE_ID, bgm_path):
                try:
                    bgm = AudioSegment.from_file(bgm_path)
                    print(f"    ✓ BGM: {len(bgm) / 1000:.1f}秒")

                    # BGMをトークの長さに調整（ループまたはカット）
                    if len(bgm) < talk_duration:
                        # ループして延長
                        loops_needed = (talk_duration // len(bgm)) + 1
                        bgm = bgm * loops_needed
                    bgm = bgm[:talk_duration]

                    # BGM音量を下げる
                    bgm = bgm - BGM_VOLUME_REDUCTION
                    print(f"    BGM音量: -{BGM_VOLUME_REDUCTION}dB")

                    # トークとBGMをミックス
                    talk_with_bgm = talk.overlay(bgm)
                    print("    ✓ トーク+BGMミックス完了")

                    # ジングル + (トーク+BGM)
                    final_audio = jingle + talk_with_bgm
                    print(f"    ✓ 最終音声: {len(final_audio) / 1000:.1f}秒")

                except Exception as e:
                    print(f"    ⚠ BGM処理エラー: {e}")
                    # BGMなしでジングル + トーク
                    final_audio = jingle + talk
            else:
                print("    ⚠ BGMダウンロード失敗、BGMなしで続行")
                final_audio = jingle + talk

        except Exception as e:
            print(f"    ⚠ ジングル処理エラー: {e}")
            # ジングルなしでトークのみ
            final_audio = talk
            jingle_duration = 0.0
    else:
        print("    ⚠ ジングルダウンロード失敗、スキップ")
        jingle_duration = 0.0

    # 最終音声を出力
    final_audio.export(output_path, format="wav")
    print(f"  ✓ 最終音声出力: {len(final_audio) / 1000:.1f}秒")

    return jingle_duration


def generate_line_qr_overlay(output_path: str) -> str:
    """LINE QRコード付きオーバーレイ画像を生成

    Returns:
        str: 生成した画像のパス
    """
    LINE_URL = "https://lin.ee/SrziaPE"

    # QRコード生成
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(LINE_URL)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_img = qr_img.resize((200, 200), Image.Resampling.LANCZOS)

    # オーバーレイ画像を作成（透明背景）
    overlay = Image.new('RGBA', (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # 白い背景の矩形（QR + テキスト用）
    box_width = 320
    box_height = 300
    box_x = VIDEO_WIDTH - box_width - 40  # 右から40px
    box_y = VIDEO_HEIGHT - box_height - 200  # 下から200px

    # 角丸白背景
    draw.rounded_rectangle(
        [(box_x, box_y), (box_x + box_width, box_y + box_height)],
        radius=20,
        fill=(255, 255, 255, 240)
    )

    # QRコードを貼り付け
    qr_x = box_x + (box_width - 200) // 2
    qr_y = box_y + 20
    overlay.paste(qr_img, (qr_x, qr_y))

    # テキスト追加
    try:
        font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
        if not os.path.exists(font_path):
            font_path = "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"
        font = ImageFont.truetype(font_path, 28)
    except:
        font = ImageFont.load_default()

    # 「LINEで毎日届く！」
    text1 = "📱 LINEで毎日届く！"
    bbox = draw.textbbox((0, 0), text1, font=font)
    text_width = bbox[2] - bbox[0]
    text_x = box_x + (box_width - text_width) // 2
    draw.text((text_x, qr_y + 210), text1, fill=(0, 0, 0), font=font)

    # 「カメラでスキャン→」
    text2 = "カメラでスキャン→"
    bbox2 = draw.textbbox((0, 0), text2, font=font)
    text_width2 = bbox2[2] - bbox2[0]
    text_x2 = box_x + (box_width - text_width2) // 2
    draw.text((text_x2, qr_y + 245), text2, fill=(100, 100, 100), font=font)

    # 保存
    overlay.save(output_path, 'PNG')
    print(f"  ✓ QRオーバーレイ生成: {output_path}")
    return output_path


def generate_video(table_image_path: str, bg_image_path: str, audio_path: str, subtitle_path: str, output_path: str, duration: float = 60):
    """動画を生成（背景固定 + 表スクロールアニメーション + 最後3秒QRコード）

    レイヤー構成（下から上）:
    - 背景画像（固定）
    - 表画像（上から下にスクロール）
    - 字幕、動画タイトル
    - QRコード（最後3秒のみ）

    スクロールタイミング（上から降りてくる）:
    - 動画の半分の時点でスクロール完了
    - 例: 60秒動画 → 30秒でスクロール完了、残り30秒は固定
    """
    print("\n[5/6] 動画を生成中（背景固定 + 表スクロール + QRコード）...")

    # スクロールタイミング計算
    # 動画の半分の時点でスクロール完了
    scroll_distance = 500  # 表の移動距離（ピクセル）
    scroll_end_time = duration / 2  # 動画の半分でスクロール完了
    scroll_speed = scroll_distance / scroll_end_time  # ピクセル/秒

    # QRコードオーバーレイ生成
    qr_overlay_path = "qr_overlay.png"
    generate_line_qr_overlay(qr_overlay_path)

    # QR表示タイミング（最後3秒）
    qr_start_time = duration - 3

    # filter_complex:
    # [0] 背景画像を1080x1920にスケール
    # [1] 表画像をそのまま使用（1080x2420）
    # [3] QRオーバーレイ（最後3秒のみ表示）
    # overlay: 表を背景の上に重ねる、y座標をアニメーション
    # 式: if(lt(t,scroll_end_time), -500+speed*t, 0)
    filter_complex = (
        f"[0:v]scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},setsar=1[bg];"
        f"[bg][1:v]overlay=0:'if(lt(t,{scroll_end_time}),-{scroll_distance}+{scroll_speed}*t,0)'[video];"
        f"[video]ass={subtitle_path}[subtitled];"
        f"[subtitled][3:v]overlay=0:0:enable='gte(t,{qr_start_time})'[out]"
    )

    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', bg_image_path,   # 背景画像 [0]
        '-loop', '1', '-i', table_image_path, # 表画像 [1]
        '-i', audio_path,                     # 音声 [2]
        '-loop', '1', '-i', qr_overlay_path,  # QRオーバーレイ [3]
        '-filter_complex', filter_complex,
        '-map', '[out]',
        '-map', '2:a',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '192k',
        '-shortest', '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        output_path
    ]

    print(f"  レイヤー: 背景(固定) + 表(上から下) + 字幕 + QR(最後3秒)")
    print(f"  スクロール: y=-{scroll_distance}→0 ({scroll_end_time:.1f}秒), 固定 ({duration - scroll_end_time:.1f}秒)")
    print(f"  QRコード: {qr_start_time:.1f}秒〜{duration:.1f}秒")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if os.path.exists(output_path):
        print(f"  ✓ 動画生成完了: {output_path}")
    else:
        print(f"  ❌ 動画生成失敗: {result.stderr[:500]}")
        raise RuntimeError("動画生成に失敗しました")


def get_playlist_id() -> str:
    """ショート動画用再生リストIDを取得（固定ID）

    Returns:
        str: 再生リストID
    """
    # ショート用再生リストID（固定）
    PLAYLIST_ID = "PLSMHaaaPDI0h8PPTA0vySJJN_ijtI2HEQ"
    print(f"  ✓ 再生リストID: {PLAYLIST_ID}")
    return PLAYLIST_ID


def add_video_to_playlist(youtube, playlist_id: str, video_id: str):
    """動画を再生リストに追加

    Args:
        youtube: YouTube APIクライアント
        playlist_id: 再生リストID
        video_id: 動画ID
    """
    if not playlist_id:
        print("  ⚠ 再生リストIDがないためスキップ")
        return

    print("  再生リストに追加中...")
    try:
        request = youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id
                    }
                }
            }
        )
        request.execute()
        print(f"  ✓ 再生リストに追加完了")
    except Exception as e:
        print(f"  ⚠ 再生リスト追加失敗: {e}")


def upload_to_youtube(video_path: str, title: str, description: str, first_comment: str = "") -> str:
    """YouTubeにアップロード

    Args:
        video_path: 動画ファイルパス
        title: 動画タイトル
        description: 動画説明文
        first_comment: 初コメント（台本生成時に作成）
    """
    print("\n[6/6] YouTubeにアップロード中...")

    try:
        from google.oauth2.credentials import Credentials

        client_id = os.environ.get("YOUTUBE_CLIENT_ID")
        client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
        refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN_23")

        if not all([client_id, client_secret, refresh_token]):
            print("  ⚠ YouTube認証情報が不足しています")
            return ""

        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret
        )

        youtube = build("youtube", "v3", credentials=creds)

        # 再生リストを取得または作成
        playlist_id = get_playlist_id()

        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": ["年金", "年金制度", "老後", "お金", "Shorts"],
                "categoryId": "22"
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }

        media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = request.execute()

        video_id = response["id"]
        video_url = f"https://youtube.com/shorts/{video_id}"
        print(f"  ✓ アップロード完了: {video_url}")

        # 再生リストに追加
        add_video_to_playlist(youtube, playlist_id, video_id)

        # 初コメントを自動投稿
        post_first_comment(youtube, video_id, first_comment)

        return video_url

    except Exception as e:
        print(f"  ❌ アップロード失敗: {e}")
        return ""


def post_first_comment(youtube, video_id: str, first_comment: str = ""):
    """動画に初コメントを自動投稿（LINE誘導）

    Args:
        youtube: YouTube APIクライアント
        video_id: 動画ID
        first_comment: 台本生成時に作成されたコメント（空の場合はフォールバック使用）
    """
    print("  初コメントを投稿中...")

    LINE_URL = "https://lin.ee/SrziaPE"

    if first_comment:
        # 動的生成されたコメントにLINE URLを追加
        comment_text = f"{first_comment}\n\n↓ LINE登録はこちら ↓\n{LINE_URL}"
    else:
        # フォールバック: 固定コメント
        comment_text = f"""カツミです💕

ねぇ、これ保存した？
まだの人、絶対しといて！！

あとね、ここだけの話…
LINEだともっと詳しい情報
毎朝届けてるの👀✨

↓今すぐ友だち追加↓
{LINE_URL}

届いた人から関係なくなってるよ〜📱💨"""

    try:
        comment_body = {
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {
                        "textOriginal": comment_text
                    }
                }
            }
        }

        youtube.commentThreads().insert(
            part="snippet",
            body=comment_body
        ).execute()

        print("  ✓ 初コメント投稿完了")

    except Exception as e:
        print(f"  ⚠ 初コメント投稿失敗（スキップ）: {e}")


def send_discord_notification(message: str):
    """Discord通知"""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook_url:
        try:
            requests.post(webhook_url, json={"content": message}, timeout=10)
        except:
            pass


def generate_community_post_short(theme_name: str, key_manager: GeminiKeyManager) -> dict:
    """ショート動画用コミュニティ投稿案を生成"""
    print("\n[コミュニティ投稿案] 生成中...")

    if SKIP_API:
        print("  [SKIP_API] スキップ")
        return None

    api_key = key_manager.get_key()
    if not api_key:
        print("  ⚠ APIキーがないためスキップ")
        return None

    prompt = f"""あなたは年金ニュースチャンネルの運営者です。
今日のショート動画のテーマに関連した、視聴者参加型のアンケート投稿を作ってください。

【今日のテーマ】
{theme_name}

【ルール】
- 損得・賛否・経験を聞く形式
- 高齢者が答えやすいシンプルな質問
- 選択肢は2〜4個
- 「正直に聞きます」「皆さんに質問です」など親しみやすい書き出し
- 絵文字は控えめ（1〜2個）

【出力形式】必ずこの形式で出力してください：
質問文:
〇〇〇〇？

選択肢:
1. △△△
2. □□□
3. ▲▲▲"""

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.7)
        )
        text = response.text.strip()

        # パース
        question = ""
        options = []
        lines = text.split("\n")
        in_options = False
        for line in lines:
            line = line.strip()
            if line.startswith("質問文:"):
                continue
            elif line.startswith("選択肢:"):
                in_options = True
                continue
            elif not in_options and line and not question:
                question = line
            elif in_options and line:
                # "1. xxx" or "・xxx" などを処理
                import re
                match = re.match(r'^[\d\.・\-\*]+\s*(.+)$', line)
                if match:
                    options.append(match.group(1))
                elif line:
                    options.append(line)

        if question and len(options) >= 2:
            print(f"  ✓ 投稿案生成完了: {question[:30]}...")
            return {"question": question, "options": options[:4]}

    except Exception as e:
        print(f"  ⚠ 生成エラー: {e}")

    print("  ⚠ コミュニティ投稿案の生成に失敗")
    return None


def create_community_image(question: str, output_path: str) -> str:
    """コミュニティ投稿用画像を生成

    Args:
        question: 質問文
        output_path: 出力パス

    Returns:
        str: 生成した画像のパス
    """
    # 画像サイズ（YouTubeコミュニティ投稿用 1200x675推奨）
    width = 1200
    height = 675

    # ベース画像を作成（温かみのあるベージュ系）
    img = Image.new('RGB', (width, height), '#FFF8E7')
    draw = ImageDraw.Draw(img)

    # 上部に赤いバー
    draw.rectangle([0, 0, width, 80], fill='#CC0000')

    # フォント設定
    try:
        font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
        if not os.path.exists(font_path):
            font_path = "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"
        title_font = ImageFont.truetype(font_path, 42)
        main_font = ImageFont.truetype(font_path, 56)
        sub_font = ImageFont.truetype(font_path, 32)
    except:
        title_font = ImageFont.load_default()
        main_font = ImageFont.load_default()
        sub_font = ImageFont.load_default()

    # 上部バーのテキスト
    title_text = "📊 みんなに聞いてみた！"
    bbox = draw.textbbox((0, 0), title_text, font=title_font)
    text_width = bbox[2] - bbox[0]
    draw.text((width // 2 - text_width // 2, 20), title_text, fill='white', font=title_font)

    # 質問文を改行処理（30文字で折り返し）
    import textwrap
    wrapped_lines = []
    for line in question.split('\n'):
        wrapped_lines.extend(textwrap.wrap(line, width=20))

    # メイン質問テキスト（中央配置）
    y_pos = 200
    line_height = 80
    for line in wrapped_lines[:4]:  # 最大4行
        bbox = draw.textbbox((0, 0), line, font=main_font)
        text_width = bbox[2] - bbox[0]
        draw.text((width // 2 - text_width // 2, y_pos), line, fill='#333333', font=main_font)
        y_pos += line_height

    # 下部にチャンネル名
    channel_text = "毎日届く！得する年金ニュース速報"
    bbox = draw.textbbox((0, 0), channel_text, font=sub_font)
    text_width = bbox[2] - bbox[0]
    draw.text((width // 2 - text_width // 2, height - 60), channel_text, fill='#888888', font=sub_font)

    # 装飾（角に年金マーク風）
    draw.text((40, 110), "💰", font=main_font)
    draw.text((width - 100, 110), "💰", font=main_font)

    # 保存
    img.save(output_path, 'PNG')
    print(f"  ✓ コミュニティ画像生成: {output_path}")
    return output_path


def send_community_post_to_slack_short(post_data: dict):
    """ショート動画用コミュニティ投稿案をSlackに送信"""
    if not post_data:
        return

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("  ⚠ SLACK_WEBHOOK_URL未設定のためスキップ")
        return

    question = post_data.get("question", "")
    options = post_data.get("options", [])
    options_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])

    # コミュニティ投稿用画像を生成（ローカル保存）
    today = datetime.now().strftime("%Y%m%d")
    image_path = f"community_post_short_{today}.png"
    create_community_image(question, image_path)
    print(f"  ✓ コミュニティ画像生成: {image_path}")

    message = f"""📱 *ショート動画のコミュニティ投稿案*

【質問文】コピペ用👇
{question}

【選択肢】
{options_text}

▶️ 投稿はこちら
https://studio.youtube.com/channel/UCcjf76-saCvRAkETlieeokw/community"""

    try:
        payload = {"text": message}
        response = requests.post(webhook_url, json=payload, timeout=30)

        if response.status_code == 200:
            print("  ✓ コミュニティ投稿案をSlackに送信完了")
        else:
            print(f"  ⚠ Slack送信失敗: {response.status_code}")
    except Exception as e:
        print(f"  ⚠ Slack送信エラー: {e}")


def main():
    """メイン処理"""
    start_time = time.time()

    print("=" * 50)
    print("年金データ表ショート動画システム v2")
    print("=" * 50)
    if TEST_MODE:
        print("🟡 テストモード（YouTubeアップロードをスキップ）")
    else:
        print("🔴 本番モード（YouTubeにアップロード）")
    if SKIP_API:
        print("⚙️  APIスキップ: 有効（ダミーデータでテスト）")
    print("=" * 50)

    key_manager = GeminiKeyManager()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # STEP1: テーマ選択
        theme = select_theme()
        print(f"\n📊 今日のテーマ: {theme['name']}")

        # STEP2: 表データ生成
        table_data = generate_table_data(theme, key_manager)

        # STEP3: 表画像生成
        image_path = str(temp_path / "table.png")
        generate_table_image(table_data, image_path)

        # STEP4: 台本生成
        script_data = generate_script(table_data, key_manager, theme)
        script = script_data.get("script", [])
        first_comment = script_data.get("first_comment", "")

        # STEP5: TTS生成
        tts_audio_path = str(temp_path / "tts_audio.wav")
        tts_duration, timings = generate_tts_audio(script, tts_audio_path, key_manager)

        # STEP5.5: ジングル・BGM追加
        final_audio_path = str(temp_path / "audio.wav")
        jingle_duration = process_audio_with_jingle_bgm(tts_audio_path, final_audio_path, temp_path)

        # 最終音声の長さを取得
        final_audio = AudioSegment.from_file(final_audio_path)
        duration = len(final_audio) / 1000.0
        print(f"  最終音声長: {duration:.1f}秒 (ジングル: {jingle_duration:.1f}秒)")

        # 画面下部CTA（ASS字幕で固定表示、12文字以内に切り詰め）
        screen_cta = table_data.get('screen_cta', '')
        video_title = screen_cta[:12] if len(screen_cta) > 12 else screen_cta

        # 字幕生成（ジングル分だけタイミングをオフセット、タイトル固定表示）
        subtitle_path = str(temp_path / "subtitles.ass")
        generate_subtitles(script, duration, subtitle_path, timings, jingle_duration, video_title)

        # STEP5.8: 背景画像をダウンロード（gdown + 1080x1920リサイズ）
        bg_image_path = str(temp_path / "background.png")
        print(f"\n  背景画像をダウンロード中...")
        if download_background_image(BACKGROUND_IMAGE_ID, bg_image_path):
            print(f"  ✓ 背景画像準備完了")
        else:
            # フォールバック：黒背景を生成
            print(f"  ⚠ 背景画像ダウンロード失敗、黒背景を使用")
            from PIL import Image
            bg = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), '#000000')
            bg.save(bg_image_path)

        # STEP6: 動画生成（背景固定 + 表スクロール）
        video_path = str(temp_path / "short.mp4")
        generate_video(image_path, bg_image_path, final_audio_path, subtitle_path, video_path, duration)

        # タイトルと説明文
        title = f"{table_data.get('youtube_title', '')} #Shorts"
        description = f"""📊 {table_data.get('youtube_title', '')}

年金の気になる情報を分かりやすい表でお届け！
保存して活用してくださいね。

━━━━━━━━━━━━━━━━━━━━
🎁 LINE登録で無料プレゼント！
━━━━━━━━━━━━━━━━━━━━

「年金だけじゃ足りない…」そんな不安ありませんか？

カツミとヒロシが作った
『新NISA超入門ガイド』をプレゼント中🎁

▼ 友だち追加で今すぐ受け取る
https://lin.ee/SrziaPE

━━━━━━━━━━━━━━━━━━━━
📺 ご視聴ありがとうございます！

「自分の年金、ちゃんともらえるか不安…」
そんな方のために、かんたん診断を作りました🎁

▼ あなたの年金、損してない？
https://konkon034034.github.io/nenkin-shindan/

#年金 #年金制度 #老後資金 #お金 #Shorts
━━━━━━━━━━━━━━━━━━━━"""

        # STEP7: アップロード
        import shutil
        # 動画ファイルを保存（TikTokアップロード用にも使用）
        output_video = "output_video.mp4"
        shutil.copy(video_path, output_video)
        print(f"  動画を保存: {output_video}")

        if TEST_MODE:
            print("\n[テストモード] YouTubeアップロードをスキップ")
            video_url = f"file://{output_video}"
        else:
            video_url = upload_to_youtube(video_path, title, description, first_comment)

        # 完了
        elapsed = time.time() - start_time
        print("\n" + "=" * 50)
        print(f"✅ 完了！ 処理時間: {elapsed:.1f}秒")
        print(f"📊 テーマ: {theme['name']}")
        print(f"🎬 動画URL: {video_url}")
        print("=" * 50)

        # 動画URL・タイトルをファイルに保存（ワークフロー通知用）
        youtube_title = table_data.get('youtube_title', '')
        with open("video_url.txt", "w") as f:
            f.write(video_url)
        with open("video_title.txt", "w") as f:
            f.write(youtube_title)

        # Discord通知（本番成功時のみ）
        if video_url and not TEST_MODE:
            send_discord_notification(f"📊 年金データ表ショート動画を投稿しました！\n\n{video_url}")

        # コミュニティ投稿案（本番のみ）
        if not TEST_MODE:
            theme_name = table_data.get('screen_theme', theme.get('name', ''))
            community_post = generate_community_post_short(theme_name, key_manager)
            if community_post:
                send_community_post_to_slack_short(community_post)


if __name__ == "__main__":
    main()
