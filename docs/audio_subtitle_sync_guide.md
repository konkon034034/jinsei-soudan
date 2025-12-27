# 音声とテキスト（字幕）のズレ修正ガイド

## 問題の原因

- 文字数推定は不正確（話速が一定ではない）
- チャンク境界でズレる（複数チャンク結合時）
- ASS字幕のタイミング計算がズレる

## 解決方法

### 方法1: 実測値を使う（推奨）

```python
from pydub import AudioSegment

# 音声ファイルの実際の長さを取得
audio = AudioSegment.from_file(audio_path)
actual_duration_ms = len(audio)  # ミリ秒単位

# 秒単位に変換
actual_duration_sec = actual_duration_ms / 1000.0
```

音声ファイルを直接読み込み、実際の長さをミリ秒単位で取得する。
推定ではなく実測値なので最も正確。

### 方法2: Whisper/STTで発話タイミング検出

```python
# ElevenLabs STTの例
import requests

response = requests.post(
    "https://api.elevenlabs.io/v1/speech-to-text",
    headers={"xi-api-key": ELEVENLABS_API_KEY},
    files={"audio": open(audio_path, "rb")},
    data={"model": "scribe_v1", "timestamps": "word"}
)

result = response.json()
# result["words"] に各単語のstart/endタイムスタンプが入る
```

音声認識APIを使って発話の開始・終了タイミングを検出する。
各セリフの正確なタイミングが取得できるが、処理時間とAPI料金がかかる。

### 方法3: 画像焼き付け方式（最も確実）

```python
from PIL import Image, ImageDraw, ImageFont

def burn_subtitle(frame, text, speaker):
    """字幕をフレームに直接焼き付け"""
    draw = ImageDraw.Draw(frame)
    font = ImageFont.truetype("NotoSansCJK-Bold.ttc", 48)

    # 画面下部に字幕を描画
    x = frame.width // 2
    y = frame.height - 100
    draw.text((x, y), text, font=font, fill="white", anchor="mm")

    return frame
```

字幕を動画フレームに直接焼き付ける方式。
ASS字幕のタイミング問題を完全に回避できる。
ただし実装の手間がかかる。

## チャンクサイズ

- 15セリフ/チャンクで声質統一OK
- 小さすぎると声質バラバラになる
- 大きすぎるとAPI制限に引っかかる

## nenkin_news.pyの設定

```python
# TTS設定
TTS_MODEL = "gemini-2.5-flash-preview-tts"
VOICE_KATSUMI = "Kore"   # 女性（カツミ）
VOICE_HIROSHI = "Puck"   # 男性（ヒロシ）

# チャンクサイズ
MAX_LINES_PER_CHUNK = 15
```

## コピペ用コード: TTS生成 + 実測タイミング

```python
from google import genai
from google.genai import types
from pydub import AudioSegment

def generate_tts_with_timing(lines, api_key):
    """TTS生成して実測タイミングを返す"""
    combined = AudioSegment.empty()
    timings = []
    current_time = 0.0

    client = genai.Client(api_key=api_key)

    for line in lines:
        speaker = line["speaker"]
        text = line["text"]
        voice = "Puck" if speaker == "ヒロシ" else "Kore"

        # TTS生成
        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
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

        # 音声データ取得
        audio_data = response.candidates[0].content.parts[0].inline_data.data
        audio_segment = AudioSegment(
            data=audio_data,
            sample_width=2,
            frame_rate=24000,
            channels=1
        )

        # 実測値でタイミング記録
        duration = len(audio_segment) / 1000.0
        timings.append({
            "speaker": speaker,
            "text": text,
            "start": current_time,
            "end": current_time + duration
        })

        combined += audio_segment
        current_time += duration

        # 間隔追加
        pause = AudioSegment.silent(duration=300)
        combined += pause
        current_time += 0.3

    return combined, timings
```

## 優先順位

1. まず実測値方式（pydub）を試す
2. ダメならWhisper/STTで発話タイミング検出
3. 完璧を求めるなら画像焼き付け方式
