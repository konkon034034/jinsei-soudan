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
import tempfile
import subprocess
import base64
from datetime import datetime
from pathlib import Path

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
BACKGROUND_IMAGE_ID = "1mP9u9WhUurmn2vBXB_BzzUnzPyo8ybVO"

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
    "title": "年金事務所が絶対に言わない届出ランキング",
    "description": "窓口では積極的に教えてくれない届出TOP10",
    "rankings": [
        {"rank": 10, "title": "国民年金の任意加入", "points": ["60歳以降も加入可能", "年金額アップのチャンス"]},
        {"rank": 9, "title": "年金の繰り下げ受給", "points": ["最大84%増額", "75歳まで繰り下げ可能"]},
        {"rank": 8, "title": "配偶者加算の届出", "points": ["年間約39万円の加算", "届出が必要"]},
        {"rank": 7, "title": "障害年金の請求", "points": ["初診日が重要", "遡及請求も可能"]},
        {"rank": 6, "title": "遺族年金の請求", "points": ["5年の時効", "未届けが多い"]},
        {"rank": 5, "title": "年金の免除申請", "points": ["全額免除から1/4免除まで", "追納で満額に"]},
        {"rank": 4, "title": "年金分割の請求", "points": ["離婚時に必須", "2年の期限"]},
        {"rank": 3, "title": "特別支給の老齢厚生年金", "points": ["65歳前にもらえる", "請求しないともらえない"]},
        {"rank": 2, "title": "加給年金の届出", "points": ["年間約40万円", "配偶者がいる場合"]},
        {"rank": 1, "title": "振替加算の届出", "points": ["見落とし多数", "年間数万円の差"]},
    ],
    "dialogue": [
        {"speaker": "カツミ", "text": "さあ、今日は年金事務所が絶対に言わない届出ランキングをお届けします"},
        {"speaker": "ヒロシ", "text": "え、年金事務所って教えてくれないことあるの？"},
        {"speaker": "カツミ", "text": "そうなのよ。聞かないと教えてくれないことって意外と多いの"},
    ],
    "first_comment": "カツミです！今日のランキング、けっこう重要だからね。年金事務所は聞かないと教えてくれないから、この動画で予習しておいてね。LINEだともっと詳しく届くよ👀"
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

    prompt = f"""あなたは年金ニュース番組の台本作家です。
以下のテーマでランキング動画の台本を作成してください。

【テーマ】
{theme['title']}
{theme['description']}

【登場人物】
カツミ（60代前半女性）
- 年金の専門家、解説役
- 落ち着いていて優しく丁寧
- 視聴者に寄り添う雰囲気

ヒロシ（40代前半男性）
- 視聴者代弁、素朴な疑問を聞く
- 親世代のために勉強中という立場
- ちょっとお馬鹿でのんびり、リアクション大きめ

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
この動画の内容に合わせて、カツミが投稿する初コメントも作成してください。

- カツミの本音キャラで、その日の動画内容に触れる
- 視聴者への感謝や共感を入れる
- 最後にさりげなくLINE登録へ誘導
- 毎回違う内容になるように（固定文NG）
- 150〜200文字程度
- 絵文字は2〜3個まで

【LINE誘導の例】
「LINEだともっと詳しく届くよ👀」
「毎朝届くLINE、届いてる？」
「LINEの方が早く届くからね〜」
※URLは後から追加するので不要
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


def generate_tts_audio(dialogue: list, output_path: str, key_manager: GeminiKeyManager) -> tuple:
    """TTS音声を生成"""
    print("\n[3/7] TTS音声を生成中...")

    if SKIP_API:
        print("  [SKIP_API] ダミー音声を生成")
        # 無音の音声を生成
        silence = AudioSegment.silent(duration=5000)
        silence.export(output_path, format="wav")
        return 5.0, []

    all_keys = key_manager.get_all_keys()
    if not all_keys:
        raise RuntimeError("APIキーがありません")

    audio_segments = []
    timings = []
    current_time = 0.0

    total_lines = len(dialogue)
    print(f"  合計 {total_lines} セリフを生成します")

    for i, line in enumerate(dialogue):
        speaker = line["speaker"]
        text = line["text"]
        voice = VOICE_HIROSHI if speaker == "ヒロシ" else VOICE_KATSUMI

        # APIキーをラウンドロビンで選択
        api_key, key_name = all_keys[i % len(all_keys)]

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

                # タイミング記録
                duration = len(audio_segment) / 1000.0
                timings.append({
                    "speaker": speaker,
                    "text": text,
                    "start": current_time,
                    "end": current_time + duration
                })
                current_time += duration

                audio_segments.append(audio_segment)

                if (i + 1) % 10 == 0 or i == total_lines - 1:
                    print(f"  [{i + 1}/{total_lines}] TTS生成中...")

                break

            except Exception as e:
                print(f"  ⚠ TTS失敗 ({speaker}): {str(e)[:30]}...")
                if attempt < max_retries - 1:
                    # 別のAPIキーを試す
                    api_key, key_name = all_keys[(i + attempt + 1) % len(all_keys)]
                    time.sleep(2)
                else:
                    # 無音で代替
                    silence = AudioSegment.silent(duration=1000)
                    audio_segments.append(silence)
                    current_time += 1.0

        # 間隔を追加
        pause = AudioSegment.silent(duration=300)
        audio_segments.append(pause)
        current_time += 0.3

    # 音声を結合
    combined = AudioSegment.empty()
    for segment in audio_segments:
        combined += segment

    combined.export(output_path, format="wav")
    duration = len(combined) / 1000.0
    print(f"  ✓ TTS生成完了: {duration:.1f}秒")

    return duration, timings


def generate_subtitles(dialogue: list, duration: float, output_path: str, timings: list):
    """ASS字幕を生成"""
    print("\n[4/7] 字幕を生成中...")

    # ASS字幕設定
    font_size = 48
    margin_v = 50

    ass_header = f"""[Script Info]
Title: Ranking Video Subtitles
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Katsumi,Noto Sans CJK JP,{font_size},&H00FF00FF,&H000000FF,&H00FFFFFF,&H00000000,1,0,0,0,100,100,0,0,1,3,2,2,30,30,{margin_v},1
Style: Hiroshi,Noto Sans CJK JP,{font_size},&H0000FF00,&H000000FF,&H00FFFFFF,&H00000000,1,0,0,0,100,100,0,0,1,3,2,2,30,30,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def format_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    events = []
    for timing in timings:
        speaker = timing["speaker"]
        text = timing["text"]
        start = timing["start"]
        end = timing["end"]

        style = "Katsumi" if speaker == "カツミ" else "Hiroshi"
        start_str = format_time(start)
        end_str = format_time(end)

        events.append(f"Dialogue: 0,{start_str},{end_str},{style},,0,0,0,,{text}")

    ass_content = ass_header + "\n".join(events)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    print(f"  ✓ 字幕生成完了: {len(events)}イベント")


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


def generate_video(audio_path: str, subtitle_path: str, bg_path: str, output_path: str, duration: float):
    """動画を生成"""
    print("\n[5/7] 動画を生成中...")

    # ffmpegコマンド
    vf_filter = f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},ass={subtitle_path}:fontsdir=/usr/share/fonts"

    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', bg_path,
        '-i', audio_path,
        '-vf', vf_filter,
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '192k',
        '-shortest',
        '-pix_fmt', 'yuv420p',
        '-movflags', '+faststart',
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ❌ 動画生成失敗: {result.stderr[:500]}")
        raise RuntimeError("動画生成に失敗しました")

    print(f"  ✓ 動画生成完了: {duration:.1f}秒")


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

        # 初コメントを自動投稿
        post_first_comment(youtube, video_id, first_comment)

        return video_url

    except Exception as e:
        print(f"  ❌ アップロード失敗: {e}")
        return ""


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

            # STEP4: 字幕生成
            subtitle_path = str(temp_path / "subtitles.ass")
            generate_subtitles(dialogue, duration, subtitle_path, timings)

            # STEP5: 背景画像ダウンロード
            bg_path = str(temp_path / "background.png")
            print("\n  背景画像をダウンロード中...")
            if not download_background_image(BACKGROUND_IMAGE_ID, bg_path):
                # フォールバック：黒背景
                from PIL import Image
                bg = Image.new('RGB', (VIDEO_WIDTH, VIDEO_HEIGHT), '#1a1a2e')
                bg.save(bg_path)
                print("  ⚠ 背景画像ダウンロード失敗、デフォルト背景を使用")

            # STEP6: 動画生成
            video_path = str(temp_path / "ranking.mp4")
            generate_video(audio_path, subtitle_path, bg_path, video_path, duration)

            # タイトルと説明文
            title = f"{script.get('title', theme['title'])}（{script.get('hook', '1位は意外にも...')}）【年金口コミぶっちゃけランキング】"
            description = f"""{script.get('description', theme['description'])}

📺 年金ニュースチャンネル
毎日19時にランキング動画を投稿中！

🔔 チャンネル登録お願いします
📱 LINEで毎日11時に最新情報をお届け: https://lin.ee/SrziaPE

#年金 #ランキング #老後 #お金 #年金制度
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

    except Exception as e:
        print(f"\n❌ エラー: {e}")
        import traceback
        traceback.print_exc()

        # エラー通知
        send_discord_notification(f"❌ **ランキング動画生成に失敗しました**\n\nエラー: {str(e)[:200]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
