#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
参考チャンネルから字幕を取得して相談内容を抽出
"""

import os
import sys
import json
import re
import tempfile
import subprocess
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime, timezone, timedelta

import google.generativeai as genai
from google.oauth2 import service_account
import gspread
import requests

# ============================================================
# 設定
# ============================================================
VERSION = "1.0.0"
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
TEST_MODE = os.environ.get("TEST_MODE", "ON").upper() == "ON"

# テストモード: 1分、本番: 設定に従う
TEST_DURATION_MINUTES = 1

def print_info(msg):
    print(f"📝 {msg}")

def print_success(msg):
    print(f"✅ {msg}")

def print_error(msg):
    print(f"❌ {msg}", file=sys.stderr)

def get_jst_now():
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst)

# ============================================================
# Google Sheets 接続
# ============================================================
def get_sheets_client():
    sa_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if sa_key:
        credentials = service_account.Credentials.from_service_account_info(
            json.loads(sa_key),
            scopes=[
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive',
            ]
        )
    else:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_KEY が設定されていません")
    
    return gspread.authorize(credentials)

def get_settings():
    """◎設定シートから設定を取得"""
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    
    try:
        settings_sheet = spreadsheet.worksheet("◎設定")
    except:
        print_error("◎設定シートが見つかりません")
        return []
    
    rows = settings_sheet.get_all_values()
    if len(rows) < 2:
        return []
    
    settings = []
    headers = rows[0]
    
    for row in rows[1:]:
        if len(row) >= 4:
            setting = {
                'channel_name': row[0],
                'account': row[1],
                'duration': row[2],
                'source_url': row[3],
                'test_mode': row[4].upper() == 'ON' if len(row) > 4 else True
            }
            settings.append(setting)
    
    return settings

# ============================================================
# YouTube 動画ダウンロード
# ============================================================
def get_latest_video_url(channel_url: str) -> Optional[str]:
    """チャンネルから最新動画のURLを取得"""
    
    # 既に動画URLの場合はそのまま返す
    if "watch?v=" in channel_url:
        return channel_url
    
    print_info(f"チャンネルから最新動画を検索: {channel_url}")
    
    try:
        # yt-dlp でチャンネルの最新動画を取得
        result = subprocess.run([
            'yt-dlp',
            '--flat-playlist',
            '--playlist-end', '1',
            '--print', 'url',
            channel_url
        ], capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0 and result.stdout.strip():
            video_url = result.stdout.strip()
            print_success(f"最新動画を発見: {video_url}")
            return video_url
        else:
            print_error(f"動画が見つかりません: {result.stderr}")
            return None
            
    except Exception as e:
        print_error(f"動画検索エラー: {e}")
        return None

def download_video(video_url: str, output_dir: str, max_duration: int = 120) -> Optional[str]:
    """動画をダウンロード（テストモードは最初の2分のみ）"""
    
    print_info(f"動画をダウンロード中: {video_url}")
    
    output_path = os.path.join(output_dir, "video.mp4")
    
    try:
        cmd = [
            'yt-dlp',
            '-f', 'best[height<=720]',
            '-o', output_path,
            '--no-playlist',
        ]
        
        # テストモードは2分だけダウンロード
        if TEST_MODE:
            cmd.extend(['--download-sections', f'*0-{max_duration}'])
        
        cmd.append(video_url)
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0 and os.path.exists(output_path):
            print_success(f"ダウンロード完了: {output_path}")
            return output_path
        else:
            print_error(f"ダウンロード失敗: {result.stderr}")
            return None
            
    except Exception as e:
        print_error(f"ダウンロードエラー: {e}")
        return None

# ============================================================
# フレーム抽出 & 字幕認識
# ============================================================
def extract_frames(video_path: str, output_dir: str, interval: int = 3) -> List[str]:
    """動画からフレームを抽出（interval秒ごと）"""
    
    print_info(f"フレームを抽出中（{interval}秒間隔）")
    
    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    
    try:
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-vf', f'fps=1/{interval}',
            '-q:v', '2',
            os.path.join(frames_dir, 'frame_%04d.jpg')
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        frames = sorted([
            os.path.join(frames_dir, f) 
            for f in os.listdir(frames_dir) 
            if f.endswith('.jpg')
        ])
        
        print_success(f"{len(frames)}フレームを抽出")
        return frames
        
    except Exception as e:
        print_error(f"フレーム抽出エラー: {e}")
        return []

def read_subtitles_from_frames(frames: List[str]) -> str:
    """Gemini Vision でフレームから字幕を読み取り"""
    
    print_info("Gemini Vision で字幕を読み取り中...")
    
    genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    all_subtitles = []
    
    for i, frame_path in enumerate(frames):
        try:
            # 画像を読み込み
            with open(frame_path, 'rb') as f:
                image_data = f.read()
            
            import base64
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            
            prompt = """この画像に表示されている字幕テキストを読み取ってください。
字幕がない場合は「なし」と返してください。
字幕テキストのみを返してください。説明は不要です。"""
            
            response = model.generate_content([
                {'mime_type': 'image/jpeg', 'data': image_base64},
                prompt
            ])
            
            subtitle = response.text.strip()
            if subtitle and subtitle != "なし":
                all_subtitles.append(subtitle)
                
            if (i + 1) % 10 == 0:
                print_info(f"  {i + 1}/{len(frames)} フレーム処理完了")
                
        except Exception as e:
            print_error(f"フレーム {i} の処理エラー: {e}")
            continue
    
    # 重複を除去して結合
    unique_subtitles = []
    for sub in all_subtitles:
        if sub not in unique_subtitles:
            unique_subtitles.append(sub)
    
    full_text = "\n".join(unique_subtitles)
    print_success(f"字幕テキスト取得完了（{len(full_text)}文字）")
    
    return full_text

# ============================================================
# 相談内容の要約
# ============================================================
def summarize_consultation(subtitle_text: str, channel_name: str) -> Dict:
    """字幕テキストから相談内容を要約"""
    
    print_info("相談内容を要約中...")
    
    genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    prompt = f"""以下は人生相談動画の字幕テキストです。
この内容から相談内容を要約してください。

【字幕テキスト】
{subtitle_text[:10000]}

【出力形式】
- 相談者の情報（年齢、性別など）
- 相談内容の要約（200〜300文字）
- 主なキーワード（カンマ区切り）

JSON形式で出力してください：
{{
    "consulter_info": "XX歳女性/男性",
    "summary": "相談内容の要約",
    "keywords": "キーワード1,キーワード2,キーワード3"
}}
"""
    
    try:
        response = model.generate_content(prompt)
        result_text = response.text.strip()
        
        # JSON部分を抽出
        json_match = re.search(r'\{[\s\S]*\}', result_text)
        if json_match:
            result = json.loads(json_match.group())
            print_success("要約完了")
            return result
        else:
            return {
                "consulter_info": "不明",
                "summary": subtitle_text[:300],
                "keywords": channel_name
            }
            
    except Exception as e:
        print_error(f"要約エラー: {e}")
        return {
            "consulter_info": "不明",
            "summary": subtitle_text[:300],
            "keywords": channel_name
        }

# ============================================================
# スプレッドシートに追加
# ============================================================
def add_to_spreadsheet(channel_name: str, summary_data: Dict, source_url: str):
    """スプレッドシートに相談内容を追加"""
    
    print_info(f"スプレッドシートに追加: {channel_name}")
    
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    
    try:
        worksheet = spreadsheet.worksheet(channel_name)
    except:
        print_error(f"シート '{channel_name}' が見つかりません")
        return False
    
    # 次の空行を探す
    all_values = worksheet.get_all_values()
    next_row = len(all_values) + 1
    
    # データを追加
    now = get_jst_now().strftime('%Y-%m-%d %H:%M:%S')
    
    worksheet.update_cell(next_row, 2, now)  # B列: 日時
    worksheet.update_cell(next_row, 3, summary_data.get('summary', ''))  # C列: 情報収集
    worksheet.update_cell(next_row, 14, summary_data.get('consulter_info', ''))  # N列: 相談者情報
    worksheet.update_cell(next_row, 15, 'PENDING')  # O列: Status
    worksheet.update_cell(next_row, 16, summary_data.get('keywords', ''))  # P列: トリガーキーワード
    worksheet.update_cell(next_row, 13, source_url)  # M列: 元動画URL
    
    print_success(f"行 {next_row} に追加完了")
    return True

# ============================================================
# Slack通知
# ============================================================
def notify_slack(channel_name: str, summary_data: Dict, source_url: str):
    """Slack に通知"""
    
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if not webhook_url:
        print_info("Slack Webhook URL が設定されていません")
        return
    
    message = {
        "text": f"📺 新しい相談内容を取得しました",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📺 {channel_name} - 新しい相談内容"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*相談者:* {summary_data.get('consulter_info', '不明')}\n\n*内容:*\n{summary_data.get('summary', '')[:500]}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*キーワード:* {summary_data.get('keywords', '')}\n*元動画:* {source_url}"
                }
            }
        ]
    }
    
    try:
        response = requests.post(webhook_url, json=message)
        if response.status_code == 200:
            print_success("Slack通知完了")
        else:
            print_error(f"Slack通知失敗: {response.status_code}")
    except Exception as e:
        print_error(f"Slack通知エラー: {e}")

# ============================================================
# メイン処理
# ============================================================
def process_channel(setting: Dict):
    """1つのチャンネルを処理"""
    
    channel_name = setting['channel_name']
    source_url = setting['source_url']
    
    print(f"\n{'='*60}")
    print(f"🎬 {channel_name} を処理中")
    print(f"{'='*60}")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # 1. 最新動画URLを取得
        video_url = get_latest_video_url(source_url)
        if not video_url:
            return False
        
        # 2. 動画をダウンロード
        video_path = download_video(video_url, temp_dir)
        if not video_path:
            return False
        
        # 3. フレームを抽出
        frames = extract_frames(video_path, temp_dir, interval=3)
        if not frames:
            return False
        
        # 4. 字幕を読み取り
        subtitle_text = read_subtitles_from_frames(frames)
        if not subtitle_text:
            print_error("字幕が取得できませんでした")
            return False
        
        # 5. 相談内容を要約
        summary_data = summarize_consultation(subtitle_text, channel_name)
        
        # 6. スプレッドシートに追加
        add_to_spreadsheet(channel_name, summary_data, video_url)
        
        # 7. Slack通知
        notify_slack(channel_name, summary_data, video_url)
    
    return True

def main():
    print("=" * 60)
    print("📺 参考チャンネル字幕取得システム")
    print(f"📝 バージョン: {VERSION}")
    print(f"📝 テストモード: {'ON' if TEST_MODE else 'OFF'}")
    print("=" * 60)
    
    # 設定を取得
    settings = get_settings()
    if not settings:
        print_error("設定が取得できませんでした")
        sys.exit(1)
    
    print_info(f"{len(settings)} チャンネルの設定を取得")
    
    # 各チャンネルを処理
    for setting in settings:
        try:
            process_channel(setting)
        except Exception as e:
            print_error(f"{setting['channel_name']} の処理エラー: {e}")
            continue
    
    print("\n" + "=" * 60)
    print("✅ 全チャンネルの処理完了")
    print("=" * 60)

if __name__ == "__main__":
    main()
