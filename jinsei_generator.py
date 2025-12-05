#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人生相談チャンネル動画生成システム（自動修正版）
"""

from dotenv import load_dotenv
load_dotenv()

import os
import sys
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional, List

import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
import gspread

from slack_notifier import notify_script_complete

# ============================================================
# 定数設定
# ============================================================
SCRIPT_NAME = "人生相談チャンネル動画生成システム"
VERSION = "4.0.0"
PROMPTS_DIR = Path("prompts")

CHARACTER_CONSULTER = os.environ.get("CONSULTER_NAME", "由美子")
CHARACTER_ADVISOR = os.environ.get("ADVISOR_NAME", "P")
SHEET_NAME = os.environ.get("SHEET_NAME", "人生相談")

class Status:
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    APPROVAL_PENDING_SCRIPT = "APPROVAL_PENDING_SCRIPT"
    APPROVED_SCRIPT = "APPROVED_SCRIPT"
    REVISE_SCRIPT = "REVISE_SCRIPT"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"

class Col:
    COMPLETED = 0
    DATETIME = 1
    SOURCE_SUMMARY = 2
    PROMPT_MEMO = 3
    CHAR_COUNT = 4
    SCRIPT = 5
    VIDEO_URL = 6
    DESC_PROMPT = 7
    METADATA = 8
    COMMENT = 9
    SEARCH = 10
    SOURCE_VIDEO_ID = 11
    SOURCE_VIDEO_URL = 12
    CONSULTER_INFO = 13
    STATUS = 14
    TRIGGER_KEYWORD = 15
    FUNC_TAG = 16


# ============================================================
# ヘルパー関数
# ============================================================
def print_header(message: str, level: int = 1):
    if level == 1:
        print("=" * 60)
        print(f"🎬 {message}")
        print("=" * 60)
    elif level == 2:
        print("-" * 60)
        print(f"🚀 {message}")
        print("-" * 60)
    elif level == 3:
        print(f"📌 {message}")
    else:
        print(f"  {message}")


def print_error(message: str):
    print(f"❌ {message}", file=sys.stderr)


def print_success(message: str):
    print(f"✅ {message}")


def print_info(message: str):
    print(f"📝 {message}")


def get_jst_now() -> datetime:
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst)


def load_prompt(prompt_name: str) -> str:
    prompt_path = PROMPTS_DIR / f"{prompt_name}.txt"
    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')
    print(f"⚠️ プロンプトファイルが見つかりません: {prompt_path}")
    return ""


def find_working_model():
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        raise Exception("GEMINI_API_KEY環境変数が設定されていません")

    print(f"  APIキー: {api_key[:20]}...")

    try:
        available_models = [m.name for m in genai.list_models()]
    except Exception as e:
        print(f"  ⚠️ モデル一覧の取得失敗: {e}")
        available_models = []

    priority_candidates = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]

    for candidate in priority_candidates:
        for name in [candidate, f"models/{candidate}"]:
            if name in available_models:
                try:
                    print(f"  試行中: {name}...")
                    model = genai.GenerativeModel(name)
                    response = model.generate_content("テスト")
                    if response:
                        print(f"  ✅ {name} が利用可能")
                        return model, name
                except Exception as e:
                    print(f"  ❌ {name} エラー: {str(e)[:50]}")
                    continue

    raise Exception("利用可能なGeminiモデルが見つかりませんでした")


def is_script_valid(script: str) -> bool:
    """台本が現在のキャラクター設定と一致するか確認"""
    if not script or len(script) < 100:
        return False
    
    # 現在のキャラクター名が台本に含まれているか確認
    has_consulter = f"{CHARACTER_CONSULTER}：" in script or f"{CHARACTER_CONSULTER}:" in script
    has_advisor = f"{CHARACTER_ADVISOR}：" in script or f"{CHARACTER_ADVISOR}:" in script
    
    if has_consulter and has_advisor:
        print_info(f"台本に「{CHARACTER_CONSULTER}」と「{CHARACTER_ADVISOR}」が見つかりました")
        return True
    
    # 古いキャラクター名（由美子、P）が含まれているか確認
    old_chars = ["由美子：", "由美子:", "P：", "P:"]
    has_old = any(old in script for old in old_chars)
    
    if has_old and (CHARACTER_CONSULTER != "由美子" or CHARACTER_ADVISOR != "P"):
        print_info(f"⚠️ 古いキャラクター名が検出されました。台本を再生成します。")
        return False
    
    return True


# ============================================================
# YouTube アップロード
# ============================================================
def upload_to_youtube(video_path: str, title: str, description: str) -> Optional[str]:
    """YouTubeに動画をアップロード"""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    import requests

    print_info("YouTube認証開始...")

    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        print_error("YouTube認証情報が不足しています")
        return None

    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }

    try:
        response = requests.post(token_url, data=token_data)
        response.raise_for_status()
        access_token = response.json()["access_token"]
        print_success("アクセストークン取得成功")
    except Exception as e:
        print_error(f"アクセストークン取得失敗: {e}")
        return None

    credentials = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=token_url,
        client_id=client_id,
        client_secret=client_secret
    )

    youtube = build("youtube", "v3", credentials=credentials)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": ["人生相談", "お悩み相談", "昭和"],
            "categoryId": "22"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }

    print_info(f"アップロード中: {video_path}")
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)

    try:
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print_info(f"  進捗: {int(status.progress() * 100)}%")

        video_id = response["id"]
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        print_success(f"アップロード完了: {video_url}")
        return video_url

    except Exception as e:
        print_error(f"アップロードエラー: {e}")
        import traceback
        traceback.print_exc()
        return None


# ============================================================
# メインクラス
# ============================================================
class JinseiSoudanGenerator:

    def __init__(self):
        print_header(SCRIPT_NAME, 1)
        print_info(f"バージョン: {VERSION}")
        print_info(f"タイムスタンプ: {get_jst_now().strftime('%Y-%m-%d %H:%M:%S')}")
        print_info(f"シート: {SHEET_NAME}")
        print_info(f"相談者: {CHARACTER_CONSULTER}")
        print_info(f"回答者: {CHARACTER_ADVISOR}")

        self.spreadsheet_id = os.getenv('SPREADSHEET_ID')
        if not self.spreadsheet_id:
            raise ValueError("SPREADSHEET_ID が設定されていません")

        self._setup_google_apis()
        self._setup_gemini()

    def _setup_google_apis(self):
        print_info("Google API認証開始...")

        sa_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
        if sa_key:
            print("  🔐 環境変数から認証情報を読み込み...")
            credentials = service_account.Credentials.from_service_account_info(
                json.loads(sa_key),
                scopes=[
                    'https://www.googleapis.com/auth/spreadsheets',
                    'https://www.googleapis.com/auth/drive',
                ]
            )
        else:
            credentials_path = Path("credentials.json")
            if credentials_path.exists():
                print("  📄 credentials.json から認証情報を読み込み...")
                credentials = service_account.Credentials.from_service_account_file(
                    str(credentials_path),
                    scopes=[
                        'https://www.googleapis.com/auth/spreadsheets',
                        'https://www.googleapis.com/auth/drive',
                    ]
                )
            else:
                creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
                if not creds_json:
                    raise ValueError("Google認証情報が見つかりません")
                print("  🔐 環境変数から認証情報を読み込み...")
                credentials = service_account.Credentials.from_service_account_info(
                    json.loads(creds_json),
                    scopes=[
                        'https://www.googleapis.com/auth/spreadsheets',
                        'https://www.googleapis.com/auth/drive',
                    ]
                )

        self.gspread_client = gspread.authorize(credentials)
        self.spreadsheet = self.gspread_client.open_by_key(self.spreadsheet_id)
        self.worksheet = self.spreadsheet.worksheet(SHEET_NAME)
        print_success(f"Google API認証成功（シート: {self.worksheet.title}）")

    def _setup_gemini(self):
        print_info("Gemini API設定開始...")
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        self.model, self.model_name = find_working_model()
        self.generation_config = {
            "temperature": 0.9,
            "top_p": 0.95,
            "max_output_tokens": 8192,
        }
        print_success(f"Gemini API設定成功（{self.model_name}）")

    def find_pending_rows(self) -> List[int]:
        print_info("未処理行を検索中...")
        all_values = self.worksheet.get_all_values()
        pending_rows = []

        for i, row in enumerate(all_values[1:], start=2):
            if len(row) > Col.STATUS:
                status = row[Col.STATUS].strip().upper()
                has_summary = len(row) > Col.SOURCE_SUMMARY and row[Col.SOURCE_SUMMARY].strip()

                if not has_summary:
                    continue

                if status == Status.PENDING or status == "":
                    pending_rows.append(i)
                elif status == Status.APPROVAL_PENDING_SCRIPT:
                    video_url = row[Col.VIDEO_URL].strip() if len(row) > Col.VIDEO_URL else ""
                    if not video_url:
                        print_info(f"  → 行 {i}: 動画未生成のため再処理対象に追加")
                        pending_rows.append(i)

        print_info(f"未処理行: {len(pending_rows)}件")
        return pending_rows

    def get_row_data(self, row_num: int) -> Dict:
        row = self.worksheet.row_values(row_num)
        while len(row) < 17:
            row.append("")

        return {
            'row_num': row_num,
            'completed': row[Col.COMPLETED],
            'datetime': row[Col.DATETIME],
            'source_summary': row[Col.SOURCE_SUMMARY],
            'prompt_memo': row[Col.PROMPT_MEMO],
            'char_count': row[Col.CHAR_COUNT],
            'script': row[Col.SCRIPT],
            'video_url': row[Col.VIDEO_URL],
            'desc_prompt': row[Col.DESC_PROMPT],
            'metadata': row[Col.METADATA],
            'comment': row[Col.COMMENT],
            'search': row[Col.SEARCH],
            'source_video_id': row[Col.SOURCE_VIDEO_ID],
            'source_video_url': row[Col.SOURCE_VIDEO_URL],
            'consulter_info': row[Col.CONSULTER_INFO],
            'status': row[Col.STATUS],
            'trigger_keyword': row[Col.TRIGGER_KEYWORD],
            'func_tag': row[Col.FUNC_TAG],
        }

    def update_cell(self, row_num: int, col: int, value: str):
        if len(str(value)) > 50000:
            value = str(value)[:49990] + "...(truncated)"
        self.worksheet.update_cell(row_num, col + 1, value)

    def update_status(self, row_num: int, status: str):
        self.update_cell(row_num, Col.STATUS, status)
        print_info(f"ステータス更新: {status}")

    def clear_row_for_retry(self, row_num: int):
        """エラー時にセルをクリアして再処理可能にする"""
        print_info("セルをクリアして再処理準備中...")
        self.update_cell(row_num, Col.SCRIPT, "")  # F列
        self.update_cell(row_num, Col.VIDEO_URL, "")  # G列
        self.update_cell(row_num, Col.CHAR_COUNT, "")  # E列
        self.update_status(row_num, Status.PENDING)  # O列
        print_success("セルをクリアしました。次回実行時に再処理されます。")

    def generate_script(self, source_summary: str) -> str:
        print_info("台本生成中...")
        prompt_template = load_prompt("prompt_a_script")

        if not prompt_template:
            prompt_template = """
あなたは台本作家です。
以下の人生相談をもとに、2人のトーク動画の台本を作成してください。

【キャラクター設定】
- {consulter}: 相談者。中高年。不安げに悩みを打ち明ける。
- {advisor}: 回答者。冷静に寄り添いながらアドバイスする。

【相談内容】
{summary}

【出力形式】
- 約10〜15分（4000〜6000文字程度）の対話形式
- 相談者が悩みを話し、回答者が共感しながらアドバイス
- 具体的かつ実践的なアドバイスを含める
- 最後は前向きなメッセージで締める

【フォーマット】
{consulter}：（セリフ）
{advisor}：（セリフ）
...

台本のみを出力してください。
"""

        prompt = prompt_template.format(
            consulter=CHARACTER_CONSULTER,
            advisor=CHARACTER_ADVISOR,
            summary=source_summary,
            char1_name=CHARACTER_CONSULTER,
            char2_name=CHARACTER_ADVISOR,
            char1_personality="相談者。中高年。不安げに悩みを打ち明ける。",
            char2_personality="回答者。冷静に寄り添いながらアドバイスする。",
            consultation=source_summary,
            title="",
        )

        try:
            response = self.model.generate_content(
                prompt,
                generation_config=self.generation_config
            )
            script = response.text
            char_count = len(script)
            print_success(f"台本生成完了（{char_count:,}文字）")

            preview_lines = script.split('\n')[:6]
            print("  📄 プレビュー:")
            for line in preview_lines:
                print(f"    {line[:60]}{'...' if len(line) > 60 else ''}")

            return script

        except Exception as e:
            print_error(f"台本生成失敗: {str(e)}")
            raise

    def process_row(self, row_num: int) -> bool:
        print_header(f"行 {row_num} を処理中", 2)

        try:
            row_data = self.get_row_data(row_num)
            source_summary = row_data['source_summary']

            if not source_summary:
                print_error("C列（情報収集）が空です")
                return False

            print_info(f"サマリー: {source_summary[:100]}...")

            self.update_status(row_num, Status.PROCESSING)
            self.update_cell(row_num, Col.DATETIME, get_jst_now().strftime('%Y-%m-%d %H:%M:%S'))

            # 既存の台本をチェック（キャラクター名が一致するか確認）
            existing_script = row_data['script']
            if existing_script and is_script_valid(existing_script):
                print_info("既存の台本を使用します")
                script = existing_script
            else:
                if existing_script:
                    print_info("⚠️ 既存の台本は無効です。新しく生成します。")
                    self.update_cell(row_num, Col.SCRIPT, "")  # 古い台本をクリア
                
                print_header("ステップ 1: 台本生成", 3)
                script = self.generate_script(source_summary)

                print_header("ステップ 2: スプレッドシート更新", 3)
                self.update_cell(row_num, Col.SCRIPT, script)

                char_count = len(script)
                self.update_cell(row_num, Col.CHAR_COUNT, str(char_count))

                print_header("ステップ 3: Slack通知", 3)
                try:
                    source_info = {
                        'title': '',
                        'summary': source_summary,
                        'consultation': source_summary,
                    }
                    metadata = {
                        'title': source_summary[:50] + '...' if len(source_summary) > 50 else source_summary,
                    }
                    notify_script_complete(
                        source_info=source_info,
                        script=script,
                        metadata=metadata,
                        row_num=row_num,
                        spreadsheet_id=self.spreadsheet_id
                    )
                except Exception as e:
                    print_error(f"Slack通知失敗（処理は続行）: {str(e)}")

            video_path = generate_audio_and_video(script, row_num)
            if video_path:
                title = f"人生相談 #{row_num} - {source_summary[:30]}"
                description = f"{source_summary}\n\n#人生相談 #お悩み相談"
                
                youtube_url = upload_to_youtube(str(video_path), title, description)
                
                if youtube_url:
                    self.update_cell(row_num, Col.VIDEO_URL, youtube_url)
                    self.update_status(row_num, Status.COMPLETED)
                    print_success(f"行 {row_num} の処理が完了しました")
                    print_info(f"YouTube URL: {youtube_url}")
                else:
                    self.update_cell(row_num, Col.VIDEO_URL, str(video_path))
                    self.update_status(row_num, Status.APPROVAL_PENDING_SCRIPT)
                    print_error("YouTubeアップロードに失敗しました")
            else:
                # 動画生成失敗 → セルをクリアして次回再処理
                print_error("動画生成に失敗しました。セルをクリアします。")
                self.clear_row_for_retry(row_num)

            return True

        except Exception as e:
            print_error(f"処理エラー: {str(e)}")
            import traceback
            traceback.print_exc()

            try:
                self.clear_row_for_retry(row_num)
            except:
                pass

            return False

    def run(self, row_num: Optional[int] = None) -> bool:
        print_header("メイン処理開始", 2)

        try:
            if row_num:
                return self.process_row(row_num)
            else:
                pending_rows = self.find_pending_rows()

                if not pending_rows:
                    print_info("処理待ちの行がありません")
                    return True

                return self.process_row(pending_rows[0])

        except Exception as e:
            print_error(f"メイン処理エラー: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


# ============================================================
# 音声・動画生成
# ============================================================
def generate_audio_and_video(script: str, row_num: int) -> Optional[str]:
    from tts_generator import TTSGenerator
    from video_generator_v2 import VideoGeneratorV2 as VideoGenerator

    try:
        print_header("ステップ 4: 音声生成", 3)
        tts = TTSGenerator()
        audio_path = tts.generate_from_script(script)

        if not audio_path:
            print_error("音声生成に失敗しました")
            return None

        print_success(f"音声生成完了: {audio_path}")

        print_header("ステップ 5: 動画生成", 3)
        video_gen = VideoGenerator()
        video_path = video_gen.generate_from_audio_and_script(audio_path, script)

        if not video_path:
            print_error("動画生成に失敗しました")
            return None

        print_success(f"動画生成完了: {video_path}")
        return video_path

    except Exception as e:
        print_error(f"音声・動画生成エラー: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


# ============================================================
# メイン実行
# ============================================================
def main():
    generator = JinseiSoudanGenerator()

    row_num = None
    if len(sys.argv) > 1:
        try:
            row_num = int(sys.argv[1])
            print_info(f"指定行: {row_num}")
        except ValueError:
            print_error(f"無効な行番号: {sys.argv[1]}")
            sys.exit(1)

    success = generator.run(row_num)

    if not success:
        print_error("処理が失敗しました")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠️ ユーザーによって中断されました")
        sys.exit(130)
    except Exception as e:
        print(f"💥 致命的エラー: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
