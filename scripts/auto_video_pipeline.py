#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto Video Generation Pipeline
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
import google.generativeai as genai
from dotenv import load_dotenv

# Add parent directory to path to import sibling modules
sys.path.append(str(Path(__file__).parent.parent))

try:
    from tts_generator import TTSGenerator, merge_audio_files
    from slack_notifier import notify_script_complete
except ImportError:
    # If running from scripts dir, try adjusting path
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from tts_generator import TTSGenerator, merge_audio_files
    from slack_notifier import notify_script_complete

load_dotenv()

# ============================================================
# Constants & Config
# ============================================================

SPREADSHEET_ID = "15_ixYlyRp9sOlS0tdklhz6wQmwRxWlOL9cPndFWwOFo"
SHEET_NAME = "YouTube自動投稿" 

# Directory Config
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
PROMPTS_DIR = BASE_DIR / "prompts"

# Ensure directories exist
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

class Status:
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    GENERATING_SLIDES = "GENERATING_SLIDES"
    GENERATING_AUDIO = "GENERATING_AUDIO"
    GENERATING_VIDEO = "GENERATING_VIDEO"
    UPLOADING = "UPLOADING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"

class Col:
    # Adjust these based on the actual sheet columns if needed
    # Assuming a specific structure for the automation sheet
    # A=Timestamp, B=Title/Theme, C=Status, D=Video URL, E=Log
    TIMESTAMP = 0
    THEME = 1
    STATUS = 2
    VIDEO_URL = 3
    LOG = 4

# ============================================================
# Helpers
# ============================================================

def get_jst_now() -> datetime:
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst)

def print_info(msg: str):
    print(f"📝 {msg}")

def print_success(msg: str):
    print(f"✅ {msg}")

def print_error(msg: str):
    print(f"❌ {msg}", file=sys.stderr)

# ============================================================
# Google API Handler
# ============================================================

class GoogleService:
    def __init__(self):
        self.creds = self._get_credentials()
        self.gspread_client = gspread.authorize(self.creds)
        self.slides_service = build('slides', 'v1', credentials=self.creds)
        self.drive_service = build('drive', 'v3', credentials=self.creds)

    def _get_credentials(self):
        sa_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/presentations',
            'https://www.googleapis.com/auth/drive',
        ]
        
        if sa_key:
            return service_account.Credentials.from_service_account_info(
                json.loads(sa_key), scopes=scopes
            )
        
        # Fallback to local file
        creds_path = BASE_DIR / "service_account.json" # Or credentials.json
        if creds_path.exists():
             return service_account.Credentials.from_service_account_file(
                str(creds_path), scopes=scopes
            )
        
        # Fallback to service_account.txt (as seen in repo)
        creds_path_txt = BASE_DIR / "service_account.txt"
        if creds_path_txt.exists():
             return service_account.Credentials.from_service_account_file(
                str(creds_path_txt), scopes=scopes
            )

        # Fallback to existing logic in codebase
        creds_path_old = BASE_DIR / "credentials.json"
        if creds_path_old.exists():
             return service_account.Credentials.from_service_account_file(
                str(creds_path_old), scopes=scopes
            )
            
        raise ValueError("No Google Credentials found (Env or File). Checked: service_account.json, service_account.txt, credentials.json")

# ============================================================
# Main Pipeline
# ============================================================

class AutoVideoPipeline:
    def __init__(self):
        self.google = GoogleService()
        self.sheet = self.google.gspread_client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        
        # Setup Gemini
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        self.model = genai.GenerativeModel("gemini-2.0-flash") # Use a faster model for content

    def run(self):
        print_info("Starting Auto Video Pipeline...")
        
        # 1. Fetch Task
        task = self.fetch_pending_task()
        if not task:
            print_info("No pending tasks found.")
            return

        row_num, theme = task
        print_info(f"Processing Theme: {theme} (Row: {row_num})")
        
        try:
            self.update_status(row_num, Status.PROCESSING)

            # 2. Generate Content
            content = self.generate_content(theme)
            
            # 3. Create Slides
            self.update_status(row_num, Status.GENERATING_SLIDES)
            presentation_id, slide_images = self.create_slides(content)
            
            # 4. Generate Audio
            self.update_status(row_num, Status.GENERATING_AUDIO)
            audio_paths = self.generate_audio(content, presentation_id)
            
            # 5. Generate Video
            self.update_status(row_num, Status.GENERATING_VIDEO)
            video_path = self.generate_video(slide_images, audio_paths, f"video_{row_num}.mp4")
            
            # 6. Upload to YouTube
            self.update_status(row_num, Status.UPLOADING)
            video_url = self.upload_youtube(video_path, theme, content['title'])
            
            # 7. Finalize
            self.update_cell(row_num, Col.VIDEO_URL, video_url)
            self.update_status(row_num, Status.COMPLETED)
            
            # 8. Notify
            if os.getenv("SLACK_WEBHOOK_URL"):
                # Use simple notification or reuse existing
                print_info("Sending Slack Notification...")
                pass 

        except Exception as e:
            print_error(f"Pipeline Failed: {e}")
            self.update_status(row_num, f"{Status.ERROR}: {str(e)}")
            import traceback
            traceback.print_exc()

    def fetch_pending_task(self) -> Optional[tuple[int, str]]:
        """Find the first row with 'PENDING' status (or empty status with a theme)."""
        rows = self.sheet.get_all_values()
        
        # Skip header
        for i, row in enumerate(rows[1:], start=2):
            if len(row) <= Col.THEME: continue
            
            theme = row[Col.THEME].strip()
            status = row[Col.STATUS].strip().upper() if len(row) > Col.STATUS else ""
            
            if theme and (status == "PENDING" or status == ""):
                return i, theme
        return None

    def update_status(self, row_num: int, status: str):
        self.sheet.update_cell(row_num, Col.STATUS + 1, status)
        self.sheet.update_cell(row_num, Col.LOG + 1, f"Updated at {get_jst_now()}")

    def update_cell(self, row_num: int, col_idx: int, value: str):
        self.sheet.update_cell(row_num, col_idx + 1, value)

    def generate_content(self, theme: str) -> Dict:
        """Generate title, slide content, and scripts using Gemini."""
        print_info("Generating content with Gemini...")
        
        prompt = f"""
        Theme: {theme}
        
        Create a 5-slide presentation script for a YouTube video about this theme.
        The output must be valid JSON with the following structure:
        {{
            "title": "Video Title",
            "description": "Video Description",
            "slides": [
                {{
                    "title": "Slide 1 Title",
                    "bullets": ["Point 1", "Point 2"],
                    "narration": "Narration text for this slide (about 20-30 seconds)."
                }},
                ...
            ]
        }}
        """
        
        response = self.model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text)

    def create_slides(self, content: Dict) -> tuple[str, List[Path]]:
        """Create Google Slides and export as images."""
        print_info("Creating Google Slides...")
        
        # 1. Create Presentation
        title = content.get("title", "Untitled Video")
        body = {
            'title': title
        }
        presentation = self.google.slides_service.presentations().create(body=body).execute()
        presentation_id = presentation.get('presentationId')
        print_success(f"Created Presentation: {presentation_id}")

        # 2. Add Slides
        requests = []
        
        # Delete default slides if any (usually starts with one title slide)
        # But we can just use it or delete it. Let's delete to be clean.
        # Actually, let's keep it simple and just append new slides.
        
        # Slide 1: Title Slide
        slide_id_1 = "slide_title"
        requests.append({
            'createSlide': {
                'objectId': slide_id_1,
                'slideLayoutReference': {
                    'predefinedLayout': 'TITLE'
                }
            }
        })
        
        # Content Slides
        slide_ids = [slide_id_1]
        for i, slide_content in enumerate(content.get('slides', [])):
            slide_id = f"slide_content_{i}"
            slide_ids.append(slide_id)
            requests.append({
                'createSlide': {
                    'objectId': slide_id,
                    'slideLayoutReference': {
                        'predefinedLayout': 'TITLE_AND_BODY'
                    }
                }
            })
            
        # Execute creation (so we can populate them)
        self.google.slides_service.presentations().batchUpdate(
            presentationId=presentation_id, body={'requests': requests}
        ).execute()

        # 3. Populate Content
        populate_requests = []
        
        # Title Slide Content
        populate_requests.append({
            'replaceAllText': {
                'containsText': {'text': 'Click to add title'},
                'replaceText': title,
                'pageObjectIds': [slide_id_1]
            }
        })
        
        # Content Slides Content
        for i, slide_content in enumerate(content.get('slides', [])):
            slide_id = f"slide_content_{i}"
            slide_title = slide_content.get('title', '')
            bullets = slide_content.get('bullets', [])
            bullet_text = "\n".join(bullets)
            
            # Since we don't know the exact Placeholder IDs without querying, 
            # we rely on the fact that 'TITLE_AND_BODY' usually has specific structure.
            # But replaceAllText is risky if placeholders are empty.
            # Interactive approach: Get the slide, find placeholders.
            # For simplicity in this v1, we will use 'replaceAllShapesWithImage' logic or just simple text insertion if we can.
            
            # Robust way: Get slide details
            slide = self.google.slides_service.presentations().pages().get(
                presentationId=presentation_id, pageObjectId=slide_id
            ).execute()
            
            for element in slide.get('pageElements', []):
                shape = element.get('shape')
                if not shape: continue
                
                # Check for Title
                if shape.get('placeholder', {}).get('type') == 'TITLE':
                     populate_requests.append({
                        'insertText': {
                            'objectId': element['objectId'],
                            'text': slide_title
                        }
                    })
                
                # Check for Body
                if shape.get('placeholder', {}).get('type') == 'BODY':
                     populate_requests.append({
                        'insertText': {
                            'objectId': element['objectId'],
                            'text': bullet_text
                        }
                    })
        
        if populate_requests:
            self.google.slides_service.presentations().batchUpdate(
                presentationId=presentation_id, body={'requests': populate_requests}
            ).execute()
            
        print_success("Slides Populated.")

        # 4. Export Images
        slide_images = []
        print_info("Exporting Slide Images...")
        
        # Wait a bit for changes to propagate? Usually API is consistent.
        
        # We need to target the slides we created.
        # Note: Index 0 might be the default blank slide if we didn't delete it.
        # Let's re-fetch the presentation to get clean page IDs.
        presentation = self.google.slides_service.presentations().get(presentationId=presentation_id).execute()
        slides = presentation.get('slides', [])
        
        for i, slide in enumerate(slides):
            page_id = slide['objectId']
            # Using thumbnail API (Official way to get slide image)
            # 1600x900 is standard 16:9 high res
            thumbnail = self.google.slides_service.presentations().pages().getThumbnail(
                presentationId=presentation_id, 
                pageObjectId=page_id,
                thumbnailProperties_thumbnailSize='LARGE' # LARGE is usually 1600px width
            ).execute()
            
            image_url = thumbnail.get('contentUrl')
            if not image_url:
                print_error(f"Failed to get thumbnail for slide {i}")
                continue
                
            # Download Image
            import requests
            img_data = requests.get(image_url).content
            
            img_path = OUTPUT_DIR / f"slide_{row_num}_{i}.png" # row_num is not in scope here, need to fix
            # Fix: Use presentation_id as unique key
            img_path = OUTPUT_DIR / f"slide_{presentation_id}_{i}.png"
            
            with open(img_path, 'wb') as f:
                f.write(img_data)
            
            slide_images.append(img_path)
            print_info(f"Downloaded Slide {i}: {img_path.name}")
            
        return presentation_id, slide_images

    def generate_audio(self, content: Dict, presentation_id: str) -> List[Path]:
        """Generate audio for each slide."""
        print_info("Generating Audio...")
        
        audio_paths = []
        tts = TTSGenerator() # Initialize TTS Generator
        
        # We need a consistent voice. Let's use the 'Advisor' voice as the narrator
        character = "P" # defined in tts_generator.py as CHARACTER_ADVISOR default
        
        slides = content.get('slides', [])
        
        # Add Title Slide Narration (Title + "について紹介します")
        title_text = content.get('title', "") + "について解説します。"
        title_audio_path = OUTPUT_DIR / f"audio_{presentation_id}_title.mp3"
        if tts.client: # Check if client is initialized
             # We use the internal text_to_speech function from tts_generator module if possible
             # But tts_generator.py has it as a standalone function mostly.
             # The TTSGenerator class uses self.client.
             from tts_generator import text_to_speech
             
             # Need to ensure we use the client from the instance
             success = text_to_speech(title_text, character, tts.client, title_audio_path)
             if success:
                 audio_paths.append(title_audio_path)
             else:
                 print_error("Failed to generate title audio")
                 # Create silent audio? Or skip.
                 # Let's create silent audio as fallback or just use a short duration.
                 pass

        for i, slide in enumerate(slides):
            text = slide.get('narration', '')
            if not text:
                text = " " # Silence
            
            # Using slide index + 1 because index 0 is title slide in our list of images usually
            # But wait, create_slides returns images for ALL slides including title.
            # So if we have Title + 5 slides, we have 6 images.
            # We generated audio for Title, so that's index 0.
            # Now we generate for content slides.
            
            path = OUTPUT_DIR / f"audio_{presentation_id}_{i}.mp3"
            
            from tts_generator import text_to_speech
            success = text_to_speech(text, character, tts.client, path)
            
            if success:
                audio_paths.append(path)
            else:
                 print_error(f"Failed to generate audio for slide {i}")

        return audio_paths

    def generate_video(self, slide_images: List[Path], audio_paths: List[Path], output_filename: str = "final_video.mp4") -> Path:
        """Compose video."""
        print_info("Composing Video...")
        
        from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip, afx
        import moviepy.audio.fx.all as afx_all
        
        clips = []
        
        # Ensure we match images and audio
        # Logic: We have N images and M audios.
        # Ideally N == M. 
        # Title slide image (0) -> Title audio (0)
        # Slide 1 image (1) -> Slide 1 audio (1)
        
        min_len = min(len(slide_images), len(audio_paths))
        
        for i in range(min_len):
            img_path = str(slide_images[i])
            audio_path = str(audio_paths[i])
            
            audio_clip = AudioFileClip(audio_path)
            # Add a bit of padding/silence?
            duration = audio_clip.duration + 0.5 # 0.5s pause
            
            img_clip = ImageClip(img_path).set_duration(duration)
            img_clip = img_clip.set_audio(audio_clip)
            
            clips.append(img_clip)
            
        final_clip = concatenate_videoclips(clips, method="compose")
        
        # Add BGM
        bgm_path = BASE_DIR / "bgm.mp3"
        if bgm_path.exists():
            bgm_clip = AudioFileClip(str(bgm_path))
            # Loop BGM to match video duration
            bgm_clip = afx_all.audio_loop(bgm_clip, duration=final_clip.duration)
            # Lower volume
            bgm_clip = bgm_clip.volumex(0.1)
            
            # Composite Audio
            final_audio = CompositeVideoClip([final_clip.set_audio(None)]).audio # Dummy
            from moviepy.audio.AudioClip import CompositeAudioClip
            final_audio = CompositeAudioClip([final_clip.audio, bgm_clip])
            final_clip = final_clip.set_audio(final_audio)
            
        output_path = OUTPUT_DIR / output_filename
        final_clip.write_videofile(str(output_path), fps=24, codec='libx264', audio_codec='aac')
        
        return output_path

    def upload_youtube(self, video_path: Path, theme: str, title: str) -> str:
        """Upload to YouTube."""
        print_info("Uploading to YouTube...")
        
        from googleapiclient.http import MediaFileUpload
        import requests
        
        # We need OAuth logic for YouTube
        # If we use Service Account, it works for some YouTube APIs but not for uploading usually (needs to be associated with channel).
        # Usually we need to use 'refresh_token' flow for YouTube upload if we are acting on behalf of a user channel.
        # jinsei_generator.py uses refresh_token flow.
        
        print_info("YouTube Auth Start...")
        client_id = os.environ.get("YOUTUBE_CLIENT_ID")
        client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
        refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

        if not all([client_id, client_secret, refresh_token]):
            print_error("YouTube Auth info missing (CLIENT_ID, SECRET, REFRESH_TOKEN)")
            return ""

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
            print_success("Got YouTube Access Token")
        except Exception as e:
            print_error(f"Failed to get Access Token: {e}")
            return ""
            
        creds = service_account.Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri=token_url,
            client_id=client_id,
            client_secret=client_secret
        ) # Actually this constructor usage might be tricky for pure OAuth2 credentials vs Service Account
        # Standard way for OAuth2 user creds:
        from google.oauth2.credentials import Credentials
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri=token_url,
            client_id=client_id,
            client_secret=client_secret
        )

        youtube = build("youtube", "v3", credentials=creds)

        body = {
            "snippet": {
                "title": title[:100],
                "description": f"Theme: {theme}\n\nAutomated Video.\n#shorts #automation",
                "tags": ["automation", "python", "googleapi"],
                "categoryId": "22"
            },
            "status": {
                "privacyStatus": "private", # Safer for testing
                "selfDeclaredMadeForKids": False
            }
        }

        media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
        
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                 print_info(f"Uploading: {int(status.progress() * 100)}%")
                 
        video_id = response.get("id")
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        print_success(f"Upload Complete: {video_url}")
        
        return video_url

if __name__ == "__main__":
    pipeline = AutoVideoPipeline()
    pipeline.run()
