#!/usr/bin/env python3
"""
年金ランキング動画自動生成システム

- 毎日19:00 JSTに自動投稿
- 30分〜1時間のランキング動画（10位〜1位）
- カツミ＆ヒロシがトーク形式で解説
- Gemini APIで台本生成、Gemini TTSで音声生成
"""

import os
import sys
import json
import time
import random
import re
import tempfile
import subprocess
import base64
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from google import genai
from google.genai import types
from pydub import AudioSegment

# ===== 設定 =====
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"
SKIP_API = os.environ.get("SKIP_API", "false").lower() == "true"

# 動画サイズ（横動画）
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080

# TTS設定
TTS_MODEL = "gemini-2.5-flash-preview-tts"
VOICE_KATSUMI = "Kore"  # 女性
VOICE_HIROSHI = "Puck"  # 男性

# Google Drive背景画像ID
BACKGROUND_IMAGE_ID = "1DyjuCeNZRVPgZiiqfw7ik3TZ-2loq-ah"

# Google Drive BGM ID
BGM_FILE_ID = "1816kmpYDIoX0rBlrKLLkpjnMjlg_9hQs"
BGM_VOLUME = 0.12  # BGM音量（0.10〜0.15推奨、トークの邪魔にならない程度）

# ===== ランキングテーマ（30種類） =====
RANKING_THEMES = [
    {
        "id": 1,
        "title": "年金事務所が絶対に言わない届出ランキング",
        "description": "窓口では積極的に教えてくれない、でも知らないと損する届出を紹介"
    },
    {
        "id": 2,
        "title": "実は申請しないともらえない年金ランキング",
        "description": "自動では支給されない、申請必須の年金給付を解説"
    },
    {
        "id": 3,
        "title": "届出1枚で年間○○万円変わる手続きランキング",
        "description": "たった1枚の届出で大きく変わる年金額の実例"
    },
    {
        "id": 4,
        "title": "60歳になって初めて知った年金の現実ランキング",
        "description": "60歳を迎えて「こんなはずじゃなかった」と驚く年金の真実"
    },
    {
        "id": 5,
        "title": "平均○○万円もらい忘れてる給付金ランキング",
        "description": "多くの人が請求し忘れている給付金・還付金を紹介"
    },
    {
        "id": 6,
        "title": "役所の窓口で教えてもらえなかった制度ランキング",
        "description": "聞かないと教えてくれない、お得な制度を大公開"
    },
    {
        "id": 7,
        "title": "ねんきん定期便に載ってない重要情報ランキング",
        "description": "定期便だけでは分からない、確認すべき情報とは"
    },
    {
        "id": 8,
        "title": "実は5年で時効になる届出ランキング",
        "description": "急いで申請しないと権利が消滅する届出を解説"
    },
    {
        "id": 9,
        "title": "実は働くと減る年金のケースランキング",
        "description": "在職老齢年金など、働くことで年金が減るケースを紹介"
    },
    {
        "id": 10,
        "title": "年金から毎月引かれてるお金ランキング",
        "description": "年金から天引きされている税金・保険料を詳しく解説"
    },
    {
        "id": 11,
        "title": "年金だけで暮らせる都道府県ランキング",
        "description": "生活費と年金額を比較して、暮らしやすい地域を紹介"
    },
    {
        "id": 12,
        "title": "年金世代の節約術ランキング",
        "description": "シニア世代に人気の節約テクニックを紹介"
    },
    {
        "id": 13,
        "title": "繰り下げvs繰り上げ受給 どっちが得かランキング",
        "description": "受給開始年齢による損益分岐点を徹底比較"
    },
    {
        "id": 14,
        "title": "遺族年金の意外と知らないルールランキング",
        "description": "遺族年金の受給条件や注意点を解説"
    },
    {
        "id": 15,
        "title": "年金世代におすすめの副業ランキング",
        "description": "シニアでも始めやすい副業と年金への影響を紹介"
    },
    {
        "id": 16,
        "title": "年金相談先の比較ランキング",
        "description": "年金事務所、社労士、FPなど相談先の特徴を比較"
    },
    {
        "id": 17,
        "title": "年金事務所に行く前に準備すべきものランキング",
        "description": "スムーズに相談するために必要な書類・情報を解説"
    },
    {
        "id": 18,
        "title": "知らないと申請できない年金の届出ランキング",
        "description": "存在自体を知らないと申請できない届出を紹介"
    },
    {
        "id": 19,
        "title": "年金の加算で見落としがちなものランキング",
        "description": "配偶者加算、子の加算など見落としやすい加算を解説"
    },
    {
        "id": 20,
        "title": "定年後にやっておくべき届出ランキング",
        "description": "退職後すぐにやるべき届出を優先度順に紹介"
    },
    {
        "id": 21,
        "title": "配偶者がいると変わる年金ランキング",
        "description": "婚姻状況で変わる年金の仕組みを解説"
    },
    {
        "id": 22,
        "title": "離婚で変わる年金ランキング",
        "description": "年金分割制度など、離婚時の年金について解説"
    },
    {
        "id": 23,
        "title": "病気・ケガでもらえる年金ランキング",
        "description": "障害年金など、傷病時にもらえる年金を紹介"
    },
    {
        "id": 24,
        "title": "退職後に届く書類で重要なものランキング",
        "description": "見落としがちだけど重要な書類を解説"
    },
    {
        "id": 25,
        "title": "年金受給者がうっかり払いすぎてる税金ランキング",
        "description": "確定申告で取り戻せる税金を紹介"
    },
    {
        "id": 26,
        "title": "国民年金と厚生年金の違いランキング",
        "description": "2つの年金制度の違いを分かりやすく解説"
    },
    {
        "id": 27,
        "title": "60歳からの働き方で変わる年金額ランキング",
        "description": "働き方による年金への影響を具体的に解説"
    },
    {
        "id": 28,
        "title": "年金生活で見直すべき固定費ランキング",
        "description": "年金生活を楽にする固定費削減ポイントを紹介"
    },
    {
        "id": 29,
        "title": "年金受給者向けお得な割引制度ランキング",
        "description": "シニア割引など、知らないと損する制度を紹介"
    },
    {
        "id": 30,
        "title": "年金に関するよくある勘違いランキング",
        "description": "多くの人が誤解している年金の常識を解説"
    },
]

# ===== ダミーデータ（テスト用） =====
DUMMY_SCRIPT = {
    "title": "年金で損しないためにやるべきことランキング",
    "description": "字幕とレイアウトの確認用ダミー台本",
    "opening": [
        {"speaker": "カツミ", "text": "さあ、今日は年金で損しないためにやるべきことランキングをお届けします"},
        {"speaker": "ヒロシ", "text": "年金って難しそうだけど、大事なことなんですよね"},
    ],
    "rankings": [
        {
            "rank": 3,
            "title": "繰り下げ受給を検討する",
            "subtitle": "受給開始を遅らせるだけで年金額が最大84%アップ！",
            "points": [
                {"text": "65歳から受給開始が基本", "important": False},
                {"text": "知り合いは届出忘れて3ヶ月分損した", "important": False, "type": "体験談"},
                {"text": "最大84%も増額される！", "important": True},
                {"text": "ただし寿命との兼ね合いが大事", "important": False},
            ],
            "dialogue": [
                {"speaker": "カツミ", "text": "これはね、実は知らない人がすごく多いんですけど、年金って繰り下げ受給すると1ヶ月ごとに0.7%ずつ増えていくんですよ"},
                {"speaker": "ヒロシ", "text": "えぇ〜！84%も増えるんですか！？それってめちゃくちゃお得じゃないですか！"},
                {"speaker": "カツミ", "text": "私の知り合いでね、届出忘れて3ヶ月分損した人がいるのよ。もったいないよね"},
                {"speaker": "ヒロシ", "text": "恥ずかしい話、僕まだ親の年金のこと全然把握してないんですよ..."},
                {"speaker": "カツミ", "text": "正直ね、この制度ほんまにわかりにくいと思うわ。役所ももっと親切に説明してほしいよね"},
            ]
        },
        {
            "rank": 2,
            "title": "ねんきん定期便を必ず確認",
            "subtitle": "記録漏れがあると将来の年金が減ってしまう！",
            "points": [
                {"text": "毎年届くハガキをチェック", "important": False},
                {"text": "加入記録に漏れがないか確認", "important": False},
                {"text": "記録漏れは年金減額の原因に！", "important": True},
                {"text": "ねんきんネットで詳細確認可能", "important": False},
            ],
            "dialogue": [
                {"speaker": "カツミ", "text": "ねんきん定期便って届いても見ずに捨てちゃう人が多いんですけど、実はこれ、ちゃんと確認しないと大変なことになるんです"},
                {"speaker": "ヒロシ", "text": "そうなんですか！？僕も正直あんまりちゃんと見てなかったかも...これからはしっかり確認するようにします！"},
            ]
        },
        {
            "rank": 1,
            "title": "付加年金に加入する",
            "subtitle": "月額400円で将来の年金が年間〇〇万円増える！",
            "points": [
                {"text": "月額たったの400円", "important": False},
                {"text": "国民年金の上乗せ制度", "important": False},
                {"text": "2年で元が取れる！", "important": True},
                {"text": "手続きは市区町村役場で", "important": False},
            ],
            "dialogue": [
                {"speaker": "カツミ", "text": "これが1位です！付加年金は月額たったの400円で、将来もらえる年金が増えるんです。2年で元が取れるから、とってもお得なんですよ"},
                {"speaker": "ヒロシ", "text": "月400円で将来の年金が増えるなんて！これは絶対にやらなきゃ損ですね！今すぐ手続きしたいくらいです！"},
            ]
        },
    ],
    "ending": [
        {"speaker": "カツミ", "text": "以上、年金で損しないためにやるべきことランキングでした。知ってるか知らないかで全然違いますからね"},
        {"speaker": "ヒロシ", "text": "勉強になりました！チャンネル登録よろしくお願いします！"},
    ],
    "first_comment": "テスト用コメントです"
}


class GeminiKeyManager:
    """Gemini APIキー管理"""
    def __init__(self):
        self.keys = []
        self.key_names = []
        self.current_index = 0
        self._load_keys()

    def _load_keys(self):
        """環境変数からAPIキーを読み込み"""
        # メインキー
        main_key = os.environ.get("GEMINI_API_KEY")
        if main_key:
            self.keys.append(main_key)
            self.key_names.append("MAIN")

        # 番号付きキー（1-42）
        for i in range(1, 43):
            key = os.environ.get(f"GEMINI_API_KEY_{i}")
            if key:
                self.keys.append(key)
                self.key_names.append(f"KEY_{i}")

        if not self.keys:
            print("  ⚠ Gemini APIキーが見つかりません")

        print(f"  [APIキー] {len(self.keys)}個のキーを読み込みました")

    def get_key(self) -> str:
        """現在のAPIキーを取得"""
        if not self.keys:
            return ""
        return self.keys[self.current_index]

    def next_key(self):
        """次のAPIキーに切り替え"""
        if len(self.keys) > 1:
            self.current_index = (self.current_index + 1) % len(self.keys)
            print(f"  [APIキー] {self.key_names[self.current_index]}に切り替え")

    def get_all_keys(self) -> list:
        """全APIキーを取得（TTS並列処理用）"""
        return list(zip(self.keys, self.key_names))


def select_random_theme() -> dict:
    """ランダムにテーマを選択"""
    theme = random.choice(RANKING_THEMES)
    print(f"  [テーマ] #{theme['id']}: {theme['title']}")
    return theme


def generate_script(theme: dict, key_manager: GeminiKeyManager) -> dict:
    """ランキング台本を生成"""
    print("\n[2/7] 台本を生成中...")

    if SKIP_API:
        print("  [SKIP_API] ダミー台本を使用")
        return DUMMY_SCRIPT

    # テストモードの場合は短縮版
    if TEST_MODE:
        rank_count = 3  # TOP3のみ
        dialogue_per_rank = 3
    else:
        rank_count = 10  # TOP10
        dialogue_per_rank = 6

    prompt = f"""あなたは年金ランキング動画の台本作家です。
以下のテーマでランキング動画の台本を作成してください。

【テーマ】
{theme['title']}
{theme['description']}

【登場人物】※はっちゃけキャラ・人格全開スタイル

■カツミ（63歳・女性）
- 元スーパーのパート勤務、今は専業主婦
- 夫（ヒロシ）と二人暮らし、娘は結婚して独立
- 趣味：韓国ドラマ、スーパーの特売チェック、健康番組
- 悩み：老後のお金が不安、夫が話を聞いてくれない
- リアクション大きめ：「えーっ！」「ウソでしょ！？」「マジで！？」
- 日常ネタをガンガン入れる：韓国ドラマ、スーパーの特売の話
- 話し方：感情豊かで楽しい口調「ねえねえ！」「見てよこれ！」「びっくりしない？」
- ※関西弁は使わない（「〜やん」「〜やで」「〜やねん」などは禁止）

■ヒロシ（65歳・男性）
- 元サラリーマン（中小企業の経理）、最近定年退職
- 趣味：野球観戦（巨人ファン）、散歩、将棋
- 悩み：退職して暇、年金だけで生活できるか心配
- リアクション大きめ：「え、なになに？」「うわ、マジか」「それヤバくない？」
- 野球ネタを時々入れる：巨人戦の話など
- 話し方：妻にはツッコまれる役「いや関係ないでしょ」「話ズレてるって」

■二人の関係性
- 結婚38年目の熟年夫婦
- カツミがよく喋り、ヒロシは聞き役でツッコミ担当
- 夫婦漫才のような掛け合い
- カツミが話を脱線→ヒロシが「話戻そう」とツッコむ

【トーンと姿勢】※はっちゃけスタイル
- 楽しくワイワイ、本音全開
- 視聴者と一緒に驚く「えー！知らなかった！」
- 日常ネタをガンガン入れて親しみやすく
- 夫婦の掛け合いで笑いを取る

【会話の特徴】
- カツミ「ねえねえヒロシ、これ見てよ！びっくりしない？」
- ヒロシ「え、なになに？…うわ、マジか」
- カツミ「でしょ？私これ見た時、韓国ドラマ止めて二度見したわよ」
- ヒロシ「いや韓国ドラマ関係ないでしょ」
- カツミ「あ、そういえば昨日スーパーで卵また値上がりしてたのよ…って話ズレた！」
- 日常のあるあるネタをどんどん混ぜる
- リアクション大きめで盛り上げる

【隠れたブランドエッセンス】※さりげなく、自然に織り込む

以下の3つの要素を「香り」のように漂わせてください。

1. 【知らないと損】（興味を引く香り）
   - 時々「知っておくと安心」「意外と知られていない」程度の表現
   - 押し付けがましくなく、軽く触れる程度

2. 【心の安心トーク】（温かさの香り）
   - 「大丈夫ですよ」「焦らなくていいんです」
   - 情報を伝えた後のさりげないフォロー
   - 視聴者に寄り添う一言

3. 【昭和の思い出×人生の知恵】（懐かしさの香り）
   - 時々「昔はこうでしたね」「お母さんがよく言ってた」的な一言
   - 「昭和の頃を思い出しますね」程度のさりげない懐古

【必須要素】各順位の話題に必ず以下を含めること：

1. 体験談・口コミ
- 「実際に〇〇した人の声」「うちの近所の〇〇さんが...」のような具体的なエピソード
- 視聴者が「へぇ〜そうなんだ」と思えるリアルな話
- 例：「私の知り合いで、届出忘れて3ヶ月分損した人がいるのよ」

2. カツミ or ヒロシの本音・弱音（話題ごとに1回）
- 「正直、私もこれできてなくて…」
- 「僕もこれ知らなかったんですよね…」
- 視聴者が「わかる〜」と共感できる弱さ

3. 具体的にやれること（1つだけ、簡単なもの）
- 「まずは年金事務所に電話してみましょう」
- 「ねんきん定期便、引き出しの奥にありませんか？まず見てみて」
- 「スマホで"ねんきんネット"って検索するだけでも第一歩ですよ」

4. 寄り添いの言葉
- 「焦らなくていいんです、一緒にやっていきましょうね」

【トークの流れ例】
カツミ「ねえねえ、これ見てよ。年金の繰り下げ受給の話」
ヒロシ「ああ、70歳まで待つと増えるってやつ？」
カツミ「そうそう。でもね、私たちの場合どうなのかなって」
ヒロシ「うーん、僕もよくわかってないんだよね正直」
カツミ「でしょ？だから調べてみたの」
〜解説〜
カツミ「ね、私たちもねんきん定期便ちゃんと見てなかったじゃない」
ヒロシ「確かに…引き出しの奥にあるかも」
カツミ「今日帰ったら一緒に探してみましょうよ。皆さんも、まずはそこからですよ」

【台本の方針】
- タイトルには「損」という言葉を入れない
- でも根底には「損得」の感情を流す
- 「もったいない」「知らないと怖い」「もらえるものはもらわないと」
- 「知ってるか知らないかで全然違う」という価値観

【構成】
- オープニング（カツミとヒロシの掛け合い、テーマ紹介）
- {rank_count}位から1位まで順番に紹介
- 各順位で{dialogue_per_rank}往復程度の会話
- エンディング（「知ってるか知らないかで全然違うからね」で締め）

【ルール】
- 各セリフは60文字以内
- 具体的な数字（○万円、○%、○年など）を必ず入れる
- 専門用語は必ず噛み砕いて説明
- ヒロシは「え、マジで？」「それヤバくない？」的なリアクション多め
- 1位は特に詳しく解説（最重要トピック）

【出力形式】
以下のJSON形式で出力してください:
```json
{{
  "title": "テーマ名（〇〇ランキングの形式）",
  "hook": "煽り文（例：1位は〇〇！△位が意外... or 意外なものが△位に！）",
  "description": "動画の説明文（100文字程度）",
  "rankings": [
    {{
      "rank": 10,
      "title": "ランキング項目のタイトル",
      "points": ["ポイント1", "ポイント2"],
      "dialogue": [
        {{"speaker": "カツミ", "text": "セリフ"}},
        {{"speaker": "ヒロシ", "text": "セリフ"}}
      ]
    }}
  ],
  "opening": [
    {{"speaker": "カツミ", "text": "オープニングセリフ"}},
    {{"speaker": "ヒロシ", "text": "オープニングセリフ"}}
  ],
  "ending": [
    {{"speaker": "カツミ", "text": "エンディングセリフ"}},
    {{"speaker": "ヒロシ", "text": "エンディングセリフ"}}
  ],
  "first_comment": "カツミの初コメント（150〜200文字）"
}}
```

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

【カツミの性格・トーン】
- 親しみやすい中高年女性、日常のぼやきや本音をよく言う
- 視聴者を「皆さん」と呼んで寄り添う
- 「〜ですよね」「〜かしら」など柔らかい語尾
- 絵文字は控えめに（😊🙏程度で1〜2個）
- 200文字以内

【NG】
- 堅い敬語、宣伝っぽい文章、LINE誘導（URLは後から自動追加）
- 毎回同じような内容（日常話題は必ず変える）
"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
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

            script = json.loads(result_text)
            rank_count = len(script.get("rankings", []))
            print(f"  ✓ 台本生成完了: {rank_count}ランキング")

            if script.get("first_comment"):
                print(f"  ✓ 初コメント生成完了: {script['first_comment'][:30]}...")

            return script

        except Exception as e:
            print(f"  ⚠ 試行{attempt + 1}/{max_retries} 失敗: {str(e)[:50]}...")
            key_manager.next_key()
            time.sleep(3)

    print("  ❌ 台本生成失敗、ダミー台本を使用")
    return DUMMY_SCRIPT


def extract_all_dialogue(script: dict) -> list:
    """台本から全てのセリフを抽出"""
    dialogue = []

    # オープニング
    for line in script.get("opening", []):
        dialogue.append(line)

    # 各ランキングのダイアログ
    rankings = script.get("rankings", [])
    # 10位から1位の順に（降順でソート）
    sorted_rankings = sorted(rankings, key=lambda x: x.get("rank", 0), reverse=True)

    for ranking in sorted_rankings:
        # ランキング発表
        dialogue.append({
            "speaker": "カツミ",
            "text": f"第{ranking['rank']}位は、{ranking['title']}です"
        })
        # 各ランキングの会話
        for line in ranking.get("dialogue", []):
            dialogue.append(line)

    # エンディング
    for line in script.get("ending", []):
        dialogue.append(line)

    return dialogue


def _process_tts_line_parallel(args: tuple) -> dict:
    """並列TTS処理用の1セリフ処理関数（ThreadPoolExecutor用）"""
    line, api_key, key_name, line_index, temp_dir, total_lines = args

    speaker = line["speaker"]
    text = line["text"]
    voice = VOICE_HIROSHI if speaker == "ヒロシ" else VOICE_KATSUMI

    # スタッガード遅延（API負荷軽減）- インデックスに応じて遅延
    # 初期遅延: 各ワーカーが少しずつずれて開始
    initial_delay = (line_index % 8) * 1.0  # 8ワーカーで1秒ずつずらす
    # 追加遅延: バッチごとにさらに遅延
    batch_delay = (line_index // 29) * 2.0  # 29キーごとに2秒追加
    total_delay = initial_delay + batch_delay
    if total_delay > 0:
        time.sleep(min(total_delay, 30.0))  # 最大30秒

    audio_path = str(temp_dir / f"line_{line_index:04d}.wav")
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

            # 音声データを取得
            audio_data = response.candidates[0].content.parts[0].inline_data.data
            audio_segment = AudioSegment(
                data=audio_data,
                sample_width=2,
                frame_rate=24000,
                channels=1
            )

            # ファイルに保存
            audio_segment.export(audio_path, format="wav")
            duration = len(audio_segment) / 1000.0

            return {
                "index": line_index,
                "success": True,
                "path": audio_path,
                "duration": duration,
                "speaker": speaker,
                "text": text
            }

        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 5 * (attempt + 1)  # より長い指数バックオフ（5秒、10秒）
                time.sleep(wait_time)
            else:
                # 無音で代替
                silence = AudioSegment.silent(duration=1000)
                silence.export(audio_path, format="wav")
                return {
                    "index": line_index,
                    "success": False,
                    "path": audio_path,
                    "duration": 1.0,
                    "speaker": speaker,
                    "text": text,
                    "error": str(e)[:50]
                }

    return {"index": line_index, "success": False, "path": None, "duration": 0}


def generate_tts_audio(dialogue: list, output_path: str, key_manager: GeminiKeyManager) -> tuple:
    """TTS音声を並列生成（29キー対応）"""
    print("\n[3/7] TTS音声を生成中...")

    if SKIP_API:
        print("  [SKIP_API] ダミー音声・タイミングを生成")
        # 20秒の無音音声を生成
        duration = 20.0
        silence = AudioSegment.silent(duration=int(duration * 1000))
        silence.export(output_path, format="wav")

        # ダミータイミングを生成（各セリフを均等に配置）
        timings = []
        if dialogue:
            interval = duration / len(dialogue)
            for i, line in enumerate(dialogue):
                start = i * interval
                end = start + interval - 0.1  # 少し隙間を空ける
                timings.append({
                    "speaker": line["speaker"],
                    "text": line["text"],
                    "start": start,
                    "end": end
                })
        print(f"  ✓ ダミー音声 {duration}秒、{len(timings)}件のタイミング生成")
        return duration, timings

    all_keys = key_manager.get_all_keys()
    if not all_keys:
        raise RuntimeError("APIキーがありません")

    total_lines = len(dialogue)
    print(f"  合計 {total_lines} セリフを{len(all_keys)}個のAPIキーで並列生成")

    # 一時ディレクトリを作成
    temp_dir = Path(tempfile.mkdtemp(prefix="tts_parallel_"))

    # 並列処理のワーカー数（APIキー数とセリフ数の小さい方、最大8）
    # 429エラー対策で同時リクエスト数を制限
    max_workers = min(len(all_keys), total_lines, 8)
    print(f"  [並列処理] max_workers={max_workers}, {len(all_keys)}キー使用")

    # タスクを準備（各セリフに異なるAPIキーを割り当て）
    tasks = []
    for i, line in enumerate(dialogue):
        api_key, key_name = all_keys[i % len(all_keys)]
        tasks.append((line, api_key, key_name, i, temp_dir, total_lines))

    # ThreadPoolExecutorで並列処理
    results = [None] * total_lines
    success_count = 0
    fail_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_tts_line_parallel, task): task[3] for task in tasks}

        for future in as_completed(futures):
            line_index = futures[future]
            try:
                result = future.result()
                results[result["index"]] = result
                if result["success"]:
                    success_count += 1
                else:
                    fail_count += 1
                    if "error" in result:
                        print(f"  ⚠ TTS失敗 [{result['index']+1}] ({result['speaker']}): {result['error']}")

                # 進捗表示（20セリフごと）
                completed = success_count + fail_count
                if completed % 20 == 0 or completed == total_lines:
                    print(f"  [{completed}/{total_lines}] 完了 (成功:{success_count}, 失敗:{fail_count})")

            except Exception as e:
                fail_count += 1
                print(f"  ✗ 例外 [{line_index+1}]: {str(e)[:50]}")

    print(f"  [並列処理完了] {success_count}/{total_lines} 成功")

    # 音声を順番に結合してタイミングを計算
    combined = AudioSegment.empty()
    timings = []
    current_time = 0.0

    for i, result in enumerate(results):
        if result and result["path"] and os.path.exists(result["path"]):
            try:
                audio_segment = AudioSegment.from_file(result["path"])
                duration = len(audio_segment) / 1000.0

                timings.append({
                    "speaker": result["speaker"],
                    "text": result["text"],
                    "start": current_time,
                    "end": current_time + duration
                })

                combined += audio_segment
                current_time += duration

                # 間隔を追加（0.3秒）
                pause = AudioSegment.silent(duration=300)
                combined += pause
                current_time += 0.3

            except Exception as e:
                print(f"  ⚠ 音声結合エラー [{i+1}]: {e}")
        else:
            # 失敗したセリフは無音1秒で代替
            silence = AudioSegment.silent(duration=1000)
            combined += silence
            if i < len(dialogue):
                timings.append({
                    "speaker": dialogue[i]["speaker"],
                    "text": dialogue[i]["text"],
                    "start": current_time,
                    "end": current_time + 1.0
                })
            current_time += 1.0

    # 出力
    combined.export(output_path, format="wav")
    total_duration = len(combined) / 1000.0
    print(f"  ✓ TTS生成完了: {total_duration:.1f}秒")

    # 一時ファイルを削除
    import shutil
    try:
        shutil.rmtree(temp_dir)
    except:
        pass

    return total_duration, timings


def wrap_text(text: str, max_chars: int = 18, max_lines: int = 2) -> str:
    """テキストを指定文字数で改行（ASS用に\\Nを使用）

    Args:
        text: 元のテキスト
        max_chars: 1行あたりの最大文字数（デフォルト18）
        max_lines: 最大行数（デフォルト2）
    """
    if len(text) <= max_chars:
        return text

    lines = []
    current_line = ""

    for char in text:
        current_line += char
        if len(current_line) >= max_chars:
            # 区切りの良い位置を探す
            break_points = ["、", "。", "！", "？", "…", "」", "）", "で", "が", "を", "に", "は", "と", "も"]
            found_break = False
            for i in range(len(current_line) - 1, max(0, len(current_line) - 8), -1):
                if current_line[i] in break_points:
                    lines.append(current_line[:i+1])
                    current_line = current_line[i+1:]
                    found_break = True
                    break
            if not found_break:
                lines.append(current_line)
                current_line = ""

            # 最大行数に達したら終了
            if len(lines) >= max_lines:
                break

    if current_line and len(lines) < max_lines:
        lines.append(current_line)

    # 最大行数を超えた場合は切り詰め
    lines = lines[:max_lines]

    return r"\N".join(lines)


def generate_subtitles(dialogue: list, duration: float, output_path: str, timings: list, script: dict = None):
    """ASS字幕を生成（新レイアウト：上部タイトル、中央トピック+ポイント、下部セリフ）"""
    print("\n[4/7] 字幕を生成中...")

    # ===== ASS字幕設定 =====
    # 画面上部タイトル（★付き、強調部分は赤）
    title_font_size = 90
    title_margin_v = 30

    # 画面上部：順位タイトル（タイトルのすぐ下、Alignment=8で上基準）
    topic_font_size = 105  # 70 → 105（1.5倍）
    topic_margin_v = 150  # タイトル下端(30+90=120) + 間隔30px = 150

    # ポイント（箇条書き）: 大きめフォント、左揃え
    point_font_size = 80  # 40 → 80（2倍）
    point_important_font_size = 85  # 45 → 85
    point_base_y = 280  # ポイント開始Y位置（トピックの下）+30px下げ
    point_line_height = 95  # 各ポイントの行間（大きくなったので調整）
    point_left_margin = 160  # 左端からのマージン（60→160、中央寄りに）

    # 画面下部セリフ（名前なし、背景付き）
    dialogue_font_size = 102  # 68 × 1.5 = 102（1.5倍に拡大）
    dialogue_margin_v = 140  # 下マージン調整

    # ASS色フォーマット: &HAABBGGRR (Alpha, Blue, Green, Red)
    title_color = "&H00FFFFFF"
    title_outline = "&H00000000"

    topic_color = "&H0000FFFF"  # 黄色
    topic_outline = "&H00000000"

    # ポイント（通常）: 白
    point_color = "&H00FFFFFF"
    point_outline = "&H00000000"

    # ポイント（重要）: 赤 (#FF3333 → BGR: 3333FF)
    point_important_color = "&H003333FF"
    point_important_outline = "&H0000FFFF"  # 黄色縁取り

    # ポイント（体験談）: オレンジ (#FF9933 → BGR: 3399FF)
    point_testimonial_color = "&H003399FF"
    point_testimonial_outline = "&H00000000"

    # カツミ: 薄い紫
    katsumi_color = "&H00DDA0DD"
    katsumi_outline = "&H00800080"

    # ヒロシ: 薄い緑
    hiroshi_color = "&H0090EE90"
    hiroshi_outline = "&H00228B22"

    ass_header = f"""[Script Info]
Title: Ranking Video Subtitles
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,Noto Sans CJK JP,{title_font_size},{title_color},&H000000FF,{title_outline},&H80000000,1,0,0,0,100,100,0,0,1,4,2,8,30,30,{title_margin_v},1
Style: Topic,Noto Sans CJK JP,{topic_font_size},{topic_color},&H000000FF,{topic_outline},&H80808080,1,0,0,0,100,100,0,0,3,15,0,8,30,30,{topic_margin_v},1
Style: Point,Noto Sans CJK JP,{point_font_size},{point_color},&H000000FF,{point_outline},&H00000000,0,0,0,0,100,100,0,0,1,2,1,7,100,100,0,1
Style: PointImportant,Noto Sans CJK JP,{point_important_font_size},{point_important_color},&H000000FF,{point_important_outline},&H00000000,1,0,0,0,100,100,0,0,1,3,2,7,100,100,0,1
Style: PointTestimonial,Noto Sans CJK JP,{point_font_size},{point_testimonial_color},&H000000FF,{point_testimonial_outline},&H00000000,1,0,0,0,100,100,0,0,1,2,1,7,100,100,0,1
Style: Katsumi,Noto Sans CJK JP,{dialogue_font_size},{katsumi_color},&H000000FF,{katsumi_outline},&H80808080,1,0,0,0,100,100,0,0,3,8,0,2,50,50,{dialogue_margin_v},1
Style: Hiroshi,Noto Sans CJK JP,{dialogue_font_size},{hiroshi_color},&H000000FF,{hiroshi_outline},&H80808080,1,0,0,0,100,100,0,0,3,8,0,2,50,50,{dialogue_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def format_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    events = []

    # ===== 1. タイトル（★付き、強調部分は赤、常時表示） =====
    video_title = script.get("title", "年金ランキング") if script else "年金ランキング"
    # タイトルが長い場合は2行に折り返し（25文字で改行）
    if len(video_title) > 25:
        # 区切りの良い位置を探す
        break_pos = 25
        for i in range(min(25, len(video_title)) - 1, 10, -1):
            if video_title[i] in ["、", "。", "！", "？", "…", "」", "）", "の", "を", "が", "に", "は", "と"]:
                break_pos = i + 1
                break
        video_title = video_title[:break_pos] + r"\N" + video_title[break_pos:]

    # タイトル内の重要キーワードを赤色で強調
    # ASS色タグ: {\c&HBBGGRR&} 赤=#FF3333 → BGR=3333FF
    highlight_color = r"{\c&H3333FF&}"
    reset_color = r"{\c&HFFFFFF&}"

    # 強調パターン（複数対応）
    highlight_words = ["損しない", "やるべきこと", "知らない", "損する", "得する"]
    decorated_title = video_title
    for word in highlight_words:
        if word in decorated_title:
            decorated_title = decorated_title.replace(word, f"{highlight_color}【{word}】{reset_color}")
            break  # 最初に見つかった1つだけ強調

    decorated_title = f"★ {decorated_title} ★"
    events.append(f"Dialogue: 0,0:00:00.00,{format_time(duration)},Title,,0,0,0,,{decorated_title}")

    # ===== 2. 話題/順位とポイントの表示 =====
    rankings = script.get("rankings", []) if script else []
    sorted_rankings = sorted(rankings, key=lambda x: x.get("rank", 0), reverse=True)
    rank_data = {r["rank"]: r for r in sorted_rankings}

    # timingsから各ランキングの開始・終了時間を取得
    topic_events = []
    current_rank = None
    topic_start = 0.0

    for i, timing in enumerate(timings):
        text = timing["text"]
        start = timing["start"]

        match = re.search(r"第(\d+)位は", text)
        if match:
            rank = int(match.group(1))
            if current_rank is not None:
                topic_events.append({
                    "rank": current_rank,
                    "start": topic_start,
                    "end": start
                })
            current_rank = rank
            topic_start = start

    if current_rank is not None:
        topic_events.append({
            "rank": current_rank,
            "start": topic_start,
            "end": duration
        })

    # 各トピックのイベントを生成
    for topic in topic_events:
        rank = topic["rank"]
        start = topic["start"]
        end = topic["end"]
        start_str = format_time(start)
        end_str = format_time(end)

        ranking_data = rank_data.get(rank, {})
        rank_title = ranking_data.get("title", "")
        points = ranking_data.get("points", [])

        # トピックタイトル（ズームアニメーション）
        topic_text = f"【第{rank}位】{rank_title}"
        zoom_effect = r"{\fscx50\fscy50\t(0,500,\fscx100\fscy100)}"
        events.append(f"Dialogue: 1,{start_str},{end_str},Topic,,0,0,0,,{zoom_effect}{topic_text}")

        # ポイント（箇条書き）を順次表示
        topic_duration = end - start
        if points:
            point_interval = min(topic_duration / (len(points) + 1), 2.0)  # 最大2秒間隔
            for idx, point in enumerate(points):
                point_start = start + (idx + 1) * point_interval * 0.5  # 0.5秒後から開始
                point_start_str = format_time(point_start)

                # pointが文字列の場合と辞書の場合に対応
                if isinstance(point, str):
                    point_text = point
                    is_important = False
                    point_type = ""
                else:
                    point_text = point.get("text", "") if isinstance(point, dict) else str(point)
                    is_important = point.get("important", False) if isinstance(point, dict) else False
                    point_type = point.get("type", "") if isinstance(point, dict) else ""

                # 位置を計算（moveタグで右から左へスライドイン）
                y_pos = point_base_y + idx * point_line_height
                # スライドイン: 右端(2000)から左揃え位置へ、各項目200ms遅延
                slide_delay = idx * 200  # 0ms, 200ms, 400ms...
                slide_start = slide_delay
                slide_end = slide_delay + 400  # 400msでスライド完了
                move_tag = r"{\an7\move(2000," + str(y_pos) + "," + str(point_left_margin) + "," + str(y_pos) + "," + str(slide_start) + "," + str(slide_end) + r")}"

                if is_important:
                    # 重要ポイント: 赤、少し大きめ
                    bullet_text = f"【重要】{point_text}"
                    events.append(f"Dialogue: 2,{point_start_str},{end_str},PointImportant,,0,0,0,,{move_tag}{bullet_text}")
                elif point_type == "体験談":
                    # 体験談ポイント: オレンジ
                    bullet_text = f"【体験談】{point_text}"
                    events.append(f"Dialogue: 2,{point_start_str},{end_str},PointTestimonial,,0,0,0,,{move_tag}{bullet_text}")
                else:
                    # 通常ポイント: 白
                    bullet_text = f"・{point_text}"
                    events.append(f"Dialogue: 2,{point_start_str},{end_str},Point,,0,0,0,,{move_tag}{bullet_text}")

    # ===== 3. セリフ（下部、名前なし、複数行対応） =====
    for timing in timings:
        speaker = timing["speaker"]
        text = timing["text"]
        start = timing["start"]
        end = timing["end"]

        style = "Katsumi" if speaker == "カツミ" else "Hiroshi"
        start_str = format_time(start)
        end_str = format_time(end)

        # テキストを複数行に分割（大きいフォントなので短めに）
        wrapped_text = wrap_text(text, 18)
        # 名前は表示しない（声で判断できる）
        events.append(f"Dialogue: 3,{start_str},{end_str},{style},,0,0,0,,{wrapped_text}")

    ass_content = ass_header + "\n".join(events)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    print(f"  ✓ 字幕生成完了: {len(events)}イベント（タイトル1、話題{len(topic_events)}、セリフ{len(timings)}）")


def download_background_image(file_id: str, output_path: str) -> bool:
    """Google Driveから背景画像をダウンロード"""
    try:
        import gdown
        url = f"https://drive.google.com/uc?id={file_id}"
        gdown.download(url, output_path, quiet=True)

        if os.path.exists(output_path):
            # リサイズ
            from PIL import Image
            img = Image.open(output_path)
            img = img.resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.Resampling.LANCZOS)
            img.save(output_path)
            return True
    except Exception as e:
        print(f"  ⚠ 背景画像ダウンロード失敗: {e}")
    return False


def download_bgm(file_id: str, output_path: str) -> bool:
    """Google DriveからBGMをダウンロード"""
    try:
        import gdown
        url = f"https://drive.google.com/uc?id={file_id}"
        gdown.download(url, output_path, quiet=True)
        return os.path.exists(output_path)
    except Exception as e:
        print(f"  ⚠ BGMダウンロード失敗: {e}")
    return False


def generate_video(audio_path: str, subtitle_path: str, bg_path: str, output_path: str, duration: float, bgm_path: str = None):
    """動画を生成（下部セリフ帯のみ、タイトルは字幕で表示、BGMミックス対応）"""
    print("\n[5/7] 動画を生成中...")

    # ===== レイアウト設定 =====
    # 上部タイトル帯: 削除（字幕で白文字+黒縁取りのみ）
    # 下部セリフ帯: 透過背景なし（字幕のみ、縁取りで読みやすく）

    # ffmpegフィルタチェーン:
    # 1. 背景画像をスケール
    # 2. ASS字幕を重ねる（透かし背景なし）
    vf_filter = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
        f"ass={subtitle_path}:fontsdir=/usr/share/fonts"
    )

    # BGMがある場合はミックス、ない場合は通常のコマンド
    if bgm_path and os.path.exists(bgm_path):
        # BGMをループ再生しながらトーク音声とミックス
        # [2:a] = BGM, [1:a] = トーク音声
        af_filter = f"[2:a]volume={BGM_VOLUME},aloop=loop=-1:size=2e+09[bgm];[1:a][bgm]amix=inputs=2:duration=first[aout]"
        cmd = [
            'ffmpeg', '-y',
            '-loop', '1', '-i', bg_path,
            '-i', audio_path,
            '-i', bgm_path,
            '-vf', vf_filter,
            '-filter_complex', af_filter,
            '-map', '0:v', '-map', '[aout]',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '192k',
            '-shortest',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            output_path
        ]
    else:
        # BGMなしの場合（明示的にオーディオをマッピング）
        cmd = [
            'ffmpeg', '-y',
            '-loop', '1', '-i', bg_path,
            '-i', audio_path,
            '-vf', vf_filter,
            '-map', '0:v', '-map', '1:a',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '192k',
            '-shortest',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            output_path
        ]

    # デバッグ: 音声ファイルの確認
    if os.path.exists(audio_path):
        audio_size = os.path.getsize(audio_path)
        print(f"  [デバッグ] 音声ファイル: {audio_path} ({audio_size} bytes)")
    else:
        print(f"  ⚠ 音声ファイルが見つかりません: {audio_path}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ❌ 動画生成失敗: {result.stderr[:500]}")
        raise RuntimeError("動画生成に失敗しました")

    bgm_status = "BGMあり" if (bgm_path and os.path.exists(bgm_path)) else "BGMなし"
    print(f"  ✓ 動画生成完了: {duration:.1f}秒（{bgm_status}）")


def upload_to_youtube(video_path: str, title: str, description: str, first_comment: str = "") -> str:
    """YouTubeにアップロード"""
    print("\n[6/7] YouTubeにアップロード中...")

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

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

        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": ["年金", "ランキング", "老後", "お金", "年金制度"],
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
        video_url = f"https://youtube.com/watch?v={video_id}"
        print(f"  ✓ アップロード完了: {video_url}")

        # 再生リストに追加
        add_to_playlist(youtube, video_id)

        # 初コメントを自動投稿
        post_first_comment(youtube, video_id, first_comment)

        return video_url

    except Exception as e:
        print(f"  ❌ アップロード失敗: {e}")
        return ""


def add_to_playlist(youtube, video_id: str):
    """動画を再生リストに追加"""
    # ランキング用再生リストID（固定）
    PLAYLIST_ID = "PLSMHaaaPDI0hZg5xqpAiJoyk3q6CdI20Z"

    print("  再生リストに追加中...")
    try:
        request = youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": PLAYLIST_ID,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id
                    }
                }
            }
        )
        request.execute()
        print(f"  ✓ 再生リストに追加: {PLAYLIST_ID}")
    except Exception as e:
        print(f"  ⚠ 再生リスト追加エラー: {e}")


def post_first_comment(youtube, video_id: str, first_comment: str = ""):
    """動画に初コメントを自動投稿"""
    print("  初コメントを投稿中...")

    LINE_URL = "https://lin.ee/SrziaPE"

    if first_comment:
        comment_text = f"{first_comment}\n\n↓ LINE登録はこちら ↓\n{LINE_URL}"
    else:
        comment_text = f"""カツミです💕

今日のランキング、役に立った？
知ってるか知らないかで全然違うからね！

LINEだともっと詳しく届くよ👀

↓ LINE登録はこちら ↓
{LINE_URL}"""

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
        except Exception as e:
            print(f"  ⚠ Discord通知失敗: {e}")


def generate_community_post_ranking(title: str, key_manager: GeminiKeyManager) -> dict:
    """ランキング動画用コミュニティ投稿案を生成"""
    print("\n[コミュニティ投稿案] 生成中...")

    if SKIP_API:
        print("  [SKIP_API] スキップ")
        return None

    api_key = key_manager.get_key()
    if not api_key:
        print("  ⚠ APIキーがないためスキップ")
        return None

    prompt = f"""あなたは年金ニュースチャンネルの運営者です。
今日のランキング動画のテーマに関連した、視聴者参加型のアンケート投稿を作ってください。

【今日のランキングテーマ】
{title}

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
    from PIL import Image, ImageDraw, ImageFont
    import textwrap

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

    # 質問文を改行処理（20文字で折り返し）
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


def send_community_post_to_slack_ranking(post_data: dict):
    """ランキング動画用コミュニティ投稿案をSlackに送信"""
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
    image_path = f"community_post_ranking_{today}.png"
    create_community_image(question, image_path)
    print(f"  ✓ コミュニティ画像生成: {image_path}")

    message = f"""📊 *ランキング動画のコミュニティ投稿案*

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
    print("=" * 50)
    print("年金ランキング動画生成システム")
    print("=" * 50)

    if TEST_MODE:
        print("🧪 テストモード（短縮版）")
    else:
        print("🔴 本番モード（フル版）")

    start_time = time.time()

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # STEP1: テーマ選択
            print("\n[1/7] テーマを選択中...")
            theme = select_random_theme()

            # STEP2: 台本生成
            key_manager = GeminiKeyManager()
            script = generate_script(theme, key_manager)
            first_comment = script.get("first_comment", "")

            # STEP3: セリフ抽出 & TTS生成
            dialogue = extract_all_dialogue(script)
            audio_path = str(temp_path / "audio.wav")
            duration, timings = generate_tts_audio(dialogue, audio_path, key_manager)

            # STEP4: 字幕生成（新レイアウト対応）
            subtitle_path = str(temp_path / "subtitles.ass")
            generate_subtitles(dialogue, duration, subtitle_path, timings, script)

            # STEP5: 背景画像ダウンロード
            bg_path = str(temp_path / "background.png")
            print("\n  背景画像をダウンロード中...")
            if not download_background_image(BACKGROUND_IMAGE_ID, bg_path):
                # フォールバック：黒背景
                from PIL import Image
                bg = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), '#1a1a2e')
                bg.save(bg_path)
                print("  ⚠ 背景画像ダウンロード失敗、デフォルト背景を使用")

            # STEP5.5: BGMダウンロード
            bgm_path = str(temp_path / "bgm.mp3")
            print("  BGMをダウンロード中...")
            if download_bgm(BGM_FILE_ID, bgm_path):
                print(f"  ✓ BGMダウンロード完了（音量: {BGM_VOLUME}）")
            else:
                bgm_path = None
                print("  ⚠ BGMダウンロード失敗、BGMなしで続行")

            # STEP6: 動画生成
            video_path = str(temp_path / "ranking.mp4")
            generate_video(audio_path, subtitle_path, bg_path, video_path, duration, bgm_path)

            # タイトルと説明文
            title = f"{script.get('title', theme['title'])}（{script.get('hook', '1位は意外にも...')}）【年金口コミぶっちゃけランキング】"
            description = f"""{script.get('description', theme['description'])}

📺 年金ニュースチャンネル
毎日19時にランキング動画を投稿中！

🔔 チャンネル登録お願いします

#年金 #ランキング #老後 #お金 #年金制度

━━━━━━━━━━━━━━━━━━━━
📺 ご視聴ありがとうございます！

「自分の年金、ちゃんともらえるか不安…」
そんな方のために、かんたん診断を作りました🎁

▼ あなたの年金、損してない？
https://konkon034034.github.io/nenkin-shindan/

LINE登録で毎日の年金ニュースも届きます📱
👉 https://lin.ee/SrziaPE
━━━━━━━━━━━━━━━━━━━━
"""

            # STEP7: YouTube投稿
            if TEST_MODE:
                # テストモード: ファイル保存のみ
                output_video = f"ranking_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
                import shutil
                shutil.copy(video_path, output_video)
                print(f"\n  動画を保存: {output_video}")
                video_url = f"file://{output_video}"
            else:
                video_url = upload_to_youtube(video_path, title, description, first_comment)

            # 完了
            elapsed = time.time() - start_time
            print("\n" + "=" * 50)
            print(f"✅ 完了！ 処理時間: {elapsed:.1f}秒")
            print(f"🎬 動画URL: {video_url}")
            print("=" * 50)

            # Discord通知
            if video_url and not TEST_MODE:
                send_discord_notification(
                    f"📊 **ランキング動画投稿完了！**\n\n"
                    f"📺 タイトル: {title}\n"
                    f"🔗 URL: {video_url}\n"
                    f"⏱️ 処理時間: {elapsed:.1f}秒"
                )

            # video_url.txt, video_title.txt に保存（ワークフロー通知用）
            with open("video_url.txt", "w") as f:
                f.write(video_url)
            with open("video_title.txt", "w") as f:
                f.write(title)

            # コミュニティ投稿案（本番のみ）
            if not TEST_MODE:
                community_post = generate_community_post_ranking(title, key_manager)
                if community_post:
                    send_community_post_to_slack_ranking(community_post)

    except Exception as e:
        print(f"\n❌ エラー: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
