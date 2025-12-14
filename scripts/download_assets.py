#!/usr/bin/env python3
import os
import requests
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

# Config
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
ASSETS_DIR = BASE_DIR / "assets"
ASSETS_DIR.mkdir(exist_ok=True, parents=True)

# Sources
BGM_URL = "https://peritune.com/music/PerituneMaterial_Shizima4.mp3"
OP_BG_URL = "https://upload.wikimedia.org/wikipedia/commons/thumb/c/ce/Cherry_blossom_and_Canal_in_Okazaki.jpg/1280px-Cherry_blossom_and_Canal_in_Okazaki.jpg" # Cherry Blossom
ED_BG_URL = "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b3/Sunset_at_Lake_Shinji.jpg/1280px-Sunset_at_Lake_Shinji.jpg" # Sunset

# Jacket Placeholders
JACKET_DATA = [
    {"name": "jacket_3_kanashii_sake.jpg", "title": "悲しい酒", "subtitle": "第3位", "color": "#4A90E2"},
    {"name": "jacket_2_yawara.jpg", "title": "柔", "subtitle": "第2位", "color": "#E24A4A"},
    {"name": "jacket_1_kawa.jpg", "title": "川の流れのように", "subtitle": "第1位", "color": "#50E3C2"}
]

def download_file(url, dest_path):
    print(f"Downloading {url}...")
    try:
        res = requests.get(url, stream=True)
        res.raise_for_status()
        with open(dest_path, 'wb') as f:
            for chunk in res.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"Saved to {dest_path}")
        return True
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return False

def create_placeholder(filename, title, subtitle, color):
    # Create a nice placeholder image
    width, height = 800, 800
    img = Image.new('RGB', (width, height), color=color)
    d = ImageDraw.Draw(img)
    
    # Try to load a font, otherwise default
    try:
        # Windows default fonts
        font_title = ImageFont.truetype("meiryo.ttc", 80)
        font_sub = ImageFont.truetype("meiryo.ttc", 60)
    except:
        font_title = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        
    # Draw Text
    # Simple centering logic
    d.text((width/2, height/3), subtitle, font=font_sub, fill="white", anchor="mm")
    d.text((width/2, height/2), title, font=font_title, fill="white", anchor="mm")
    d.text((width/2, height*2/3), "(Jacket Image)", font=font_sub, fill="white", anchor="mm")
    
    path = ASSETS_DIR / filename
    img.save(path)
    print(f"Created placeholder {path}")

def main():
    # 1. Download BGM
    download_file(BGM_URL, ASSETS_DIR / "bgm.mp3")
    
    # 2. Download BGs
    download_file(OP_BG_URL, ASSETS_DIR / "op_bg.jpg")
    download_file(ED_BG_URL, ASSETS_DIR / "ed_bg.jpg")
    
    # 3. Create Jackets
    for item in JACKET_DATA:
        create_placeholder(item["name"], item["title"], item["subtitle"], item["color"])
        
    print("Asset gathering complete.")

if __name__ == "__main__":
    main()
