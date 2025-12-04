#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
人生相談チャンネル動画生成システム

処理フロー:
1. スプレッドシートから未処理行を取得（Status = PENDING）
2. 元動画からサマリー取得（C列）
3. プロンプトA + サマリーで台本生成（Gemini API使用）
4. 生成した台本をF列に保存
5. 文字数をE列に保存
6. slack_notifier.py で通知
7. Status = APPROVAL_PENDING_SCRIPT に更新
8. 承認待ち
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

# Google関連
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
import gspread

# Slack通知
from slack_notifier import notify_script_complete

# ============================================================
# 定数設定
# ============================================================
SCRIPT_NAME = "人生相談チャンネル動画生成システム"
VERSION = "1.0.0"
PROMPTS_DIR = Path("prompts")

# キャラクター設定
CHARACTER_CONSULTER = "由美子"  # 相談者: 中高年女性、不安げ
CHARACTER_ADVISOR = "P"          # 回答者: 中高年女性、冷静に寄り添う

# ステータス定義
class Status:
    PENDING = "PENDING"                           # 未処理
    PROCESSING = "PROCESSING"                     # 処理中
    APPROVAL_PENDING_SCRIPT = "APPROVAL_PENDING_SCRIPT"  # 台本承認待ち
    APPROVED_SCRIPT = "APPROVED_SCRIPT"           # 台本承認済み
    REVISE_SCRIPT = "REVISE_SCRIPT"               # 台本修正待ち
    REJECTED = "REJECTED"                         # ボツ
    COMPLETED = "COMPLETED"                       # 完了
    ERROR = "ERROR"                               # エラー

# スプレッドシート列インデックス（0始まり）
class Col:
    # 基本列（A-K）
    COMPLETED = 0       # A: 作成済（チェックボックス）
    DATETIME = 1        # B: 日時
    SOURCE_SUMMARY = 2  # C: 情報収集（元動画サマリー）
    PROMPT_MEMO = 3     # D: スクリプト作成（プロンプト指示メモ）
    CHAR_COUNT = 4      # E: 文字数カウント
    SCRIPT = 5          # F: script（台本本文）
    VIDEO_URL = 6       # G: 生成URL（音声/動画のDrive URL）
    DESC_PROMPT = 7     # H: 概要欄プロンプト
    METADATA = 8        # I: metadata（タイトル・説明文）
    COMMENT = 9         # J: comment（初コメ）
    SEARCH = 10         # K: search（SEOキーワード）

    # 人生相談チャンネル用追加列（L-Q）
    SOURCE_VIDEO_ID = 11   # L: 元動画ID（重複防止）
    SOURCE_VIDEO_URL = 12  # M: 元動画URL
    CONSULTER_INFO = 13    # N: 相談者情報（例：68歳女性/夫と二人暮らし）
    STATUS = 14            # O: Status（PENDING/PROCESSING/APPROVAL_PENDING_SCRIPT/COMPLETED）
    TRIGGER_KEYWORD = 15   # P: 高齢女性トリガー（刺さりそうなキーワード）
    FUNC_TAG = 16          # Q: 機能タグ（厳しめ回/優しめ回など）


# ============================================================
# ヘルパー関数
# ============================================================
def print_header(message: str, level: int = 1):
    """見出しを出力"""
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
    """現在の日本時間を取得"""
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst)


def load_prompt(prompt_name: str) -> str:
    """プロンプトファイルを読み込む"""
    prompt_path = PROMPTS_DIR / f"{prompt_name}.txt"
    if prompt_path.exists():
        return prompt_path.read_text(encoding='utf-8')
    print(f"⚠️ プロンプトファイルが見つかりません: {prompt_path}")
    return ""


def find_working_model():
    """利用可能なGeminiモデルを探す"""
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


# ============================================================
# メインクラス
# ============================================================
class JinseiSoudanGenerator:
    """人生相談動画生成クラス"""

    def __init__(self):
        """初期化"""
        print_header(SCRIPT_NAME, 1)
        print_info(f"バージョン: {VERSION}")
        print_info(f"タイムスタンプ: {get_jst_now().strftime('%Y-%m-%d %H:%M:%S')}")

        self.spreadsheet_id = os.getenv('SPREADSHEET_ID')
        if not self.spreadsheet_id:
            raise ValueError("SPREADSHEET_ID が設定されていません")

        self._setup_google_apis()
        self._setup_gemini()

    def _setup_google_apis(self):
        """Google APIの認証設定"""
        print_info("Google API認証開始...")

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

        # スプレッドシート接続
        self.gspread_client = gspread.authorize(credentials)
        self.spreadsheet = self.gspread_client.open_by_key(self.spreadsheet_id)
        # 「人生相談」シートを使用
        self.worksheet = self.spreadsheet.worksheet('人生相談')
        print_success(f"Google API認証成功（シート: {self.worksheet.title}）")

    def _setup_gemini(self):
        """Gemini APIの設定"""
        print_info("Gemini API設定開始...")

        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        self.model, self.model_name = find_working_model()

        self.generation_config = {
            "temperature": 0.9,
            "top_p": 0.95,
            "max_output_tokens": 8192,  # 長い台本用に増加
        }

        print_success(f"Gemini API設定成功（{self.model_name}）")

    def find_pending_rows(self) -> List[int]:
        """
        未処理行を取得
        - Status = PENDING または 空欄
        - または Status = APPROVAL_PENDING_SCRIPT で VIDEO_URL が空（再処理対象）

        Returns:
            行番号のリスト（1始まり）
        """
        print_info("未処理行を検索中...")

        all_values = self.worksheet.get_all_values()
        pending_rows = []

        for i, row in enumerate(all_values[1:], start=2):  # ヘッダースキップ
            if len(row) > Col.STATUS:
                status = row[Col.STATUS].strip().upper()

                # C列（サマリー）が入力されているか確認
                has_summary = len(row) > Col.SOURCE_SUMMARY and row[Col.SOURCE_SUMMARY].strip()

                if not has_summary:
                    continue

                # 条件1: Status が PENDING または 空欄
                if status == Status.PENDING or status == "":
                    pending_rows.append(i)
                # 条件2: Status が APPROVAL_PENDING_SCRIPT で VIDEO_URL が空（動画生成失敗→再処理）
                elif status == Status.APPROVAL_PENDING_SCRIPT:
                    video_url = row[Col.VIDEO_URL].strip() if len(row) > Col.VIDEO_URL else ""
                    if not video_url:
                        print_info(f"  → 行 {i}: 動画未生成のため再処理対象に追加")
                        pending_rows.append(i)

        print_info(f"未処理行: {len(pending_rows)}件")
        return pending_rows

    def get_row_data(self, row_num: int) -> Dict:
        """
        指定行のデータを取得

        Args:
            row_num: 行番号（1始まり）

        Returns:
            行データの辞書
        """
        row = self.worksheet.row_values(row_num)

        # 列数を補完（A-Q = 17列）
        while len(row) < 17:
            row.append("")

        return {
            'row_num': row_num,
            # 基本列（A-K）
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
            # 人生相談チャンネル用追加列（L-Q）
            'source_video_id': row[Col.SOURCE_VIDEO_ID],
            'source_video_url': row[Col.SOURCE_VIDEO_URL],
            'consulter_info': row[Col.CONSULTER_INFO],
            'status': row[Col.STATUS],
            'trigger_keyword': row[Col.TRIGGER_KEYWORD],
            'func_tag': row[Col.FUNC_TAG],
        }

    def update_cell(self, row_num: int, col: int, value: str):
        """セルを更新"""
        # 文字数制限（スプレッドシートのセル制限は50000文字）
        if len(str(value)) > 50000:
            value = str(value)[:49990] + "...(truncated)"
        self.worksheet.update_cell(row_num, col + 1, value)  # gspreadは1始まり

    def update_status(self, row_num: int, status: str):
        """ステータスを更新"""
        self.update_cell(row_num, Col.STATUS, status)
        print_info(f"ステータス更新: {status}")

    def generate_script(self, source_summary: str) -> str:
        """
        台本を生成

        Args:
            source_summary: 元動画のサマリー（C列）

        Returns:
            生成された台本
        """
        print_info("台本生成中...")

        # プロンプトA を読み込む
        prompt_template = load_prompt("prompt_a_script")

        if not prompt_template:
            # デフォルトプロンプト
            prompt_template = """
あなたは台本作家です。
以下の人生相談をもとに、女性2人のトーク動画の台本を作成してください。

【キャラクター設定】
- {consulter}: 相談者。中高年女性。不安げに悩みを打ち明ける。
- {advisor}: 回答者。中高年女性。冷静に寄り添いながらアドバイスする。

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
            char1_personality="相談者。中高年女性。不安げに悩みを打ち明ける。",
            char2_personality="回答者。中高年女性。冷静に寄り添いながらアドバイスする。",
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

            # プレビュー表示
            preview_lines = script.split('\n')[:6]
            print("  📄 プレビュー:")
            for line in preview_lines:
                print(f"    {line[:60]}{'...' if len(line) > 60 else ''}")

            return script

        except Exception as e:
            print_error(f"台本生成失敗: {str(e)}")
            raise

    def process_row(self, row_num: int) -> bool:
        """
        1行を処理

        Args:
            row_num: 行番号（1始まり）

        Returns:
            成功/失敗
        """
        print_header(f"行 {row_num} を処理中", 2)

        try:
            # 1. 行データを取得
            row_data = self.get_row_data(row_num)
            source_summary = row_data['source_summary']

            if not source_summary:
                print_error("C列（情報収集）が空です")
                return False

            print_info(f"サマリー: {source_summary[:100]}...")

            # 2. ステータスを PROCESSING に更新
            self.update_status(row_num, Status.PROCESSING)
            self.update_cell(row_num, Col.DATETIME, get_jst_now().strftime('%Y-%m-%d %H:%M:%S'))

            # 3. 台本生成（既存の台本があればスキップ）
            existing_script = row_data['script']
            if existing_script and len(existing_script) > 100:
                print_info("既存の台本を使用します")
                script = existing_script
            else:
                print_header("ステップ 1: 台本生成", 3)
                script = self.generate_script(source_summary)

                # 4. F列に台本を保存
                print_header("ステップ 2: スプレッドシート更新", 3)
                self.update_cell(row_num, Col.SCRIPT, script)

                # 5. E列に文字数を保存
                char_count = len(script)
                self.update_cell(row_num, Col.CHAR_COUNT, str(char_count))

                # 6. Slack通知
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

            # 7. 音声・動画生成
            video_path = generate_audio_and_video(script, row_num)
            if video_path:
                self.update_cell(row_num, Col.VIDEO_URL, str(video_path))
                self.update_status(row_num, Status.COMPLETED)
                print_header("処理完了", 2)
                print_success(f"行 {row_num} の動画生成が完了しました")
                print_info(f"動画: {video_path}")
            else:
                self.update_status(row_num, Status.APPROVAL_PENDING_SCRIPT)
                print_header("処理完了", 2)
                print_success(f"行 {row_num} の台本生成が完了しました")
                print_info("動画生成に失敗。Slackで承認後、再試行してください")

            return True

        except Exception as e:
            print_error(f"処理エラー: {str(e)}")
            import traceback
            traceback.print_exc()

            # エラーステータスに更新
            try:
                self.update_status(row_num, f"{Status.ERROR}: {str(e)[:50]}")
            except:
                pass

            return False

    def run(self, row_num: Optional[int] = None) -> bool:
        """
        メイン処理を実行

        Args:
            row_num: 処理する行番号（指定しない場合は未処理行を自動検索）

        Returns:
            成功/失敗
        """
        print_header("メイン処理開始", 2)

        try:
            if row_num:
                # 特定の行を処理
                return self.process_row(row_num)
            else:
                # 未処理行を検索して処理
                pending_rows = self.find_pending_rows()

                if not pending_rows:
                    print_info("処理待ちの行がありません")
                    return True

                # 最初の1行だけ処理（バッチ処理の場合はループに変更）
                return self.process_row(pending_rows[0])

        except Exception as e:
            print_error(f"メイン処理エラー: {str(e)}")
            import traceback
            traceback.print_exc()
            return False


# ============================================================
# メイン実行
# ============================================================
if __name__ == "__main__":
    try:
        generator = JinseiSoudanGenerator()

        # コマンドライン引数から行番号を取得（オプション）
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

    except KeyboardInterrupt:
        print("\n⚠️ ユーザーによって中断されました")
        sys.exit(130)

    except Exception as e:
        print(f"💥 致命的エラー: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


# ============================================================
# 音声・動画生成（追加機能）
# ============================================================

def generate_audio_and_video(script: str, row_num: int) -> Optional[str]:
    """台本から音声・動画を生成"""
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
```

---

### ③ 「Commit changes」をクリック

---

## 変更点まとめ
```
1. find_pending_rows(): 
   APPROVAL_PENDING_SCRIPT で動画URLが空なら再処理対象に

2. process_row():
   既存の台本があればスキップ（再生成しない）
