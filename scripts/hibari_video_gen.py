import os
import sys
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# MoviePy 2.x Imports
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip, TextClip, CompositeAudioClip, afx

from dotenv import load_dotenv
from google.cloud import texttospeech
from google.oauth2 import service_account

# Load Env
load_dotenv()
BASE_DIR = Path(__file__).resolve().parent.parent

# Config
OUTPUT_DIR = BASE_DIR / "output"
ASSETS_DIR = BASE_DIR / "assets"
OUTPUT_DIR.mkdir(exist_ok=True)
ASSETS_DIR.mkdir(exist_ok=True)

# TTS Config (Copied/simplified from tts_generator.py)
CHARACTER_ADVISOR = "P"
VOICE_SETTINGS = {
    CHARACTER_ADVISOR: {
        "voice_name": "ja-JP-Wavenet-A", # Woman
        "pitch": -2.0,
        "speaking_rate": 0.9,
    },
}

def get_tts_client():
    sa_key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY")
    if sa_key:
        credentials_info = json.loads(sa_key)
        credentials = service_account.Credentials.from_service_account_info(credentials_info)
        return texttospeech.TextToSpeechClient(credentials=credentials)
    
    credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if credentials_json:
        try:
            credentials_info = json.loads(credentials_json)
            credentials = service_account.Credentials.from_service_account_info(credentials_info)
            return texttospeech.TextToSpeechClient(credentials=credentials)
        except json.JSONDecodeError:
            pass # Might be a path?
    
    # Fallback to local files
    for filename in ["service_account.txt", "service_account.json", "credentials.json"]:
        p = BASE_DIR / filename
        if p.exists():
            print(f"Loading credentials from {filename}")
            # If it is .txt or .json, assuming json content
            credentials = service_account.Credentials.from_service_account_file(str(p))
            return texttospeech.TextToSpeechClient(credentials=credentials)
            
    return texttospeech.TextToSpeechClient()

def text_to_speech(text, character, client, output_path):
    settings = VOICE_SETTINGS.get(character, VOICE_SETTINGS[CHARACTER_ADVISOR])
    
    try:
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code="ja-JP",
            name=settings["voice_name"],
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            pitch=settings["pitch"],
            speaking_rate=settings["speaking_rate"],
        )
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        with open(output_path, "wb") as out:
            out.write(response.audio_content)
        return True
    except Exception as e:
        print(f"TTS Error: {e}")
        return False

# Script Data
SCRIPT = [
    {
        "type": "title",
        "text": "美空ひばり\n売上ベスト３",
        "narration": "みなさん、こんにちは。今日は、永遠の歌姫、美空ひばりさんの、売上ランキングベスト３をご紹介します。",
        "bg_color": "#FFD700", # Gold/Yellow
        "duration_buffer": 0.5
    },
    {
        "type": "rank",
        "rank": 3,
        "title": "悲しい酒",
        "image": "jacket_3_kanashii_sake.jpg",
        "narration": "第3位は、「悲しい酒」。145万枚におよぶ大ヒット。ひばりさんの涙ながらの歌唱が、心を揺さぶります。",
        "duration_buffer": 0.5
    },
    {
        "type": "rank",
        "rank": 2,
        "title": "柔",
        "image": "jacket_2_yawara.jpg",
        "narration": "第2位は、「柔」。180万枚を超える大記録。力強くも優しい歌声が、日本中を勇気づけました。",
        "duration_buffer": 0.5
    },
    {
        "type": "rank",
        "rank": 1,
        "title": "川の流れのように",
        "image": "jacket_1_kawa.jpg",
        "narration": "そして、第1位は、「川の流れのように」。205万枚の売上を記録。人生を川の流れに例えた、心に沁みる名曲です。",
        "duration_buffer": 1.0
    },
    {
        "type": "end",
        "text": "あなたの好きな曲は？",
        "narration": "あなたの思い出の曲はありましたか？これからも、ひばりさんの歌声は、私たちの心の中で生き続けます。",
        "bg_color": "#FFC0CB", # Pink
        "duration_buffer": 1.0
    }
]

def create_bg_image(filename, color, width=1920, height=1080):
    path = ASSETS_DIR / filename
    img = Image.new('RGB', (width, height), color=color)
    img.save(path)
    return path

def generate_tts_audio(text, index):
    output_path = ASSETS_DIR / f"audio_{index}.mp3"
    if output_path.exists():
        return output_path
        
    client = get_tts_client()
    success = text_to_speech(text, CHARACTER_ADVISOR, client, output_path)
    if success:
        return output_path
    
    print(f"Failed to generate audio for {index}")
    return None

def create_text_clip_pil(text, duration, fontsize=70, color='white'):
    w, h = 1920, 1080
    img = Image.new('RGBA', (w, h), (0,0,0,0))
    d = ImageDraw.Draw(img)
    
    try:
        font = ImageFont.truetype("meiryo.ttc", fontsize)
    except:
        font = ImageFont.load_default()
        
    d.text((w/2, h*0.8), text, font=font, fill=color, anchor="mm", align="center", stroke_width=2, stroke_fill="black")
    
    # Use hash for filename to avoid collisions
    h_val = abs(hash(text))
    path = ASSETS_DIR / f"subtitle_{h_val}.png"
    img.save(path)
    
    clip = ImageClip(str(path))
    if hasattr(clip, 'with_duration'):
        clip = clip.with_duration(duration)
    else:
        clip = clip.set_duration(duration)
        
    return clip

def main():
    print("Starting Video Generation...")
    
    clips = []
    
    for i, item in enumerate(SCRIPT):
        print(f"Processing Scene {i}: {item.get('title') or item.get('text')}")
        
        # Audio
        audio_path = generate_tts_audio(item['narration'], i)
        if not audio_path:
            continue
            
        audio_clip = AudioFileClip(str(audio_path))
        duration = audio_clip.duration + item['duration_buffer']
        
        # Visual
        if item['type'] in ['title', 'end']:
            bg_path = ASSETS_DIR / f"bg_{i}.jpg"
            
            # Check for existing generated assets
            if item['type'] == 'title' and (ASSETS_DIR / "op_bg.jpg").exists():
                 bg_path = ASSETS_DIR / "op_bg.jpg"
            elif item['type'] == 'end' and (ASSETS_DIR / "ed_bg.jpg").exists():
                 bg_path = ASSETS_DIR / "ed_bg.jpg"
            else:
                 create_bg_image(bg_path.name, item['bg_color'])

            # Render Text onto BG copy
            scene_bg_path = ASSETS_DIR / f"scene_bg_{i}.jpg"
            try:
                img = Image.open(bg_path).convert("RGB")
                img = img.resize((1920, 1080))
                d = ImageDraw.Draw(img)
                try:
                    font = ImageFont.truetype("meiryo.ttc", 100)
                except:
                    font = ImageFont.load_default()
                
                d.text((1920/2, 1080/2), item['text'], font=font, fill="black", anchor="mm", align="center", stroke_width=2, stroke_fill="white")
                img.save(scene_bg_path)
                
                img_clip = ImageClip(str(scene_bg_path))
                if hasattr(img_clip, 'with_duration'):
                    img_clip = img_clip.with_duration(duration)
                else:
                    img_clip = img_clip.set_duration(duration)
            except Exception as e:
                print(f"Text render error: {e}")
                # Fallback to just BG
                img_clip = ImageClip(str(bg_path))
                if hasattr(img_clip, 'with_duration'):
                    img_clip = img_clip.with_duration(duration)
                else:
                    img_clip = img_clip.set_duration(duration)

        else:
            # Rank Slide
            jacket_path = ASSETS_DIR / item['image']
            if not jacket_path.exists():
                print(f"Missing jacket {jacket_path}, using placeholder")
                create_bg_image(item['image'], "#CCCCCC")
            
            bg_clip = ImageClip(str(create_bg_image(f"bg_{i}.jpg", "#F0F0F0")))
            if hasattr(bg_clip, 'with_duration'):
                bg_clip = bg_clip.with_duration(duration)
            else:
                bg_clip = bg_clip.set_duration(duration)
            
            jacket_clip = ImageClip(str(jacket_path))
            if hasattr(jacket_clip, 'with_duration'):
                jacket_clip = jacket_clip.with_duration(duration)
            else:
                jacket_clip = jacket_clip.set_duration(duration)
            
            try:
                jacket_clip = jacket_clip.resized(height=800)
            except AttributeError:
                if hasattr(jacket_clip, 'resize'):
                    jacket_clip = jacket_clip.resize(height=800)
            
            try:
                jacket_clip = jacket_clip.with_position("center")
            except:
                jacket_clip = jacket_clip.set_position("center")
            
            img_clip = CompositeVideoClip([bg_clip, jacket_clip])
            if hasattr(img_clip, 'with_duration'):
                img_clip = img_clip.with_duration(duration)
            else:
                img_clip = img_clip.set_duration(duration)
        
        # Subtitle
        sub_text = item.get('title') or item.get('text').replace("\n", " ")
        sub_clip = create_text_clip_pil(sub_text, duration)
        
        final_scene = CompositeVideoClip([img_clip, sub_clip])
        if hasattr(final_scene, 'with_duration'):
            final_scene = final_scene.with_duration(duration)
        else:
            final_scene = final_scene.set_duration(duration)
            
        # Audio
        if hasattr(final_scene, 'with_audio'):
            final_scene = final_scene.with_audio(audio_clip)
        else:
            final_scene = final_scene.set_audio(audio_clip)
            
        clips.append(final_scene)
    
    # Concatenate
    final_video = concatenate_videoclips(clips)
    
    # BGM
    bgm_path = ASSETS_DIR / "bgm.mp3"
    if bgm_path.exists():
        bgm_clip = AudioFileClip(str(bgm_path))
        bgm_clip = afx.audio_loop(bgm_clip, duration=final_video.duration)
        
        if hasattr(bgm_clip, 'with_volume_multiplier'):
             bgm_clip = bgm_clip.with_volume_multiplier(0.1)
        elif hasattr(bgm_clip, 'volumex'):
             bgm_clip = bgm_clip.volumex(0.1)
             
        new_audio = CompositeAudioClip([final_video.audio, bgm_clip])
        if hasattr(final_video, 'with_audio'):
            final_video = final_video.with_audio(new_audio)
        else:
            final_video = final_video.set_audio(new_audio)
            
    output_path = OUTPUT_DIR / "hibari_top3_video.mp4"
    final_video.write_videofile(str(output_path), fps=24, codec='libx264', audio_codec='aac')
    print(f"Video created: {output_path}")

if __name__ == "__main__":
    main()
