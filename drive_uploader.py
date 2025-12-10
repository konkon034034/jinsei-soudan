"""Google Drive アップロード機能"""
import os
import json
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

def upload_to_drive(file_path: str, folder_id: str = None) -> str:
    """
    ファイルをGoogle Driveにアップロード
    
    Returns:
        共有リンクURL
    """
    # 認証
    creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/drive.file']
        )
    else:
        creds = service_account.Credentials.from_service_account_file(
            'credentials.json',
            scopes=['https://www.googleapis.com/auth/drive.file']
        )
    
    service = build('drive', 'v3', credentials=creds)
    
    # フォルダID
    if not folder_id:
        folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID', '1oqjzUgpNexap4mgioXO43UUO3XI5XEzl')
    
    # ファイル名
    file_name = Path(file_path).name
    
    # アップロード
    file_metadata = {
        'name': file_name,
        'parents': [folder_id]
    }
    
    media = MediaFileUpload(file_path, resumable=True)
    
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id, webViewLink'
    ).execute()
    
    # 共有設定（リンクを知っている人は誰でも閲覧可能）
    service.permissions().create(
        fileId=file['id'],
        body={'type': 'anyone', 'role': 'reader'}
    ).execute()
    
    print(f"✅ Google Driveにアップロード完了: {file['webViewLink']}")
    return file['webViewLink']

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        url = upload_to_drive(sys.argv[1])
        print(url)
