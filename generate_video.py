import os
import time
from gtts import gTTS
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips, CompositeAudioClip

# Define the content (same as presentation)
slides_content = [
    {
        "title": "第5位：きなこ棒",
        "image": r"C:\Users\rentsu-windows\.gemini\antigravity\brain\4ddab301-7bf4-4a03-b3e3-4c23851f5878\kinako_bo_retro_1765688680720.png",
        "description": "第5位、きなこ棒。きな粉と水飴を練り合わせて作られた素朴な駄菓子です。独特の甘さとねっとりとした食感が特徴で、当たり（爪楊枝が赤い）が出るともう一本もらえるワクワク感も人気の秘密でした。"
    },
    {
        "title": "第4位：ココアシガレット",
        "image": r"C:\Users\rentsu-windows\.gemini\antigravity\brain\4ddab301-7bf4-4a03-b3e3-4c23851f5878\cocoa_cigarette_retro_1765688663132.png",
        "description": "第4位、ココアシガレット。タバコのような形状をしたココア味の菓子です。子供たちが大人の真似をしてプカプカとふかす真似をして楽しむ姿は、昭和の路地裏の定番風景でした。"
    },
    {
        "title": "第3位：よっちゃんイカ",
        "image": r"C:\Users\rentsu-windows\.gemini\antigravity\brain\4ddab301-7bf4-4a03-b3e3-4c23851f5878\yocchan_ika_retro_1765688644345.png",
        "description": "第3位、よっちゃんイカ。イカを加工した酢漬けの駄菓子です。その強烈な酸味と独特の食感は一度食べると病みつきに。当たりくじ付きのパッケージも子供心をくすぐりました。"
    },
    {
        "title": "第2位：キャベツ太郎",
        "image": r"C:\Users\rentsu-windows\.gemini\antigravity\brain\4ddab301-7bf4-4a03-b3e3-4c23851f5878\cabbage_taro_retro_1765688627380.png",
        "description": "第2位、キャベツ太郎。丸い形とサクサクとした食感が特徴のスナック菓子です。キャベツが入っているわけではありませんが、その丸い形が愛らしく、ソース味が後を引く美味しさです。"
    },
    {
        "title": "第1位：うまい棒",
        "image": r"C:\Users\rentsu-windows\.gemini\antigravity\brain\4ddab301-7bf4-4a03-b3e3-4c23851f5878\umai_bo_retro_1765688610757.png",
        "description": "第1位、うまい棒。1979年発売の王道駄菓子です。1本10円という安さと、コーンポタージュ、めんたい、チーズなど豊富なフレーバーで、不動の人気ナンバーワンを誇ります。"
    }
]

def generate_voice_and_video():
    clips = []
    
    # 1. Generate Audio and Create Clips
    for i, item in enumerate(slides_content):
        print(f"Processing {item['title']}...")
        
        # Generate Audio
        audio_filename = f"audio_{i}.mp3"
        if not os.path.exists(audio_filename):
            tts = gTTS(text=item['description'], lang='ja')
            tts.save(audio_filename)
            time.sleep(1) # Wait to ensure file is saved
        
        # Create Audio Clip
        voice_clip = AudioFileClip(audio_filename)
        duration = voice_clip.duration + 1.0 # Add 1 second buffer
        if duration < 10:
             duration = 10 # Minimum 10 seconds per slide

        # Create Image Clip
        if os.path.exists(item["image"]):
            video_clip = ImageClip(item["image"]).with_duration(duration)
        else:
            print(f"Warning: Image not found: {item['image']}")
            continue
            
        video_clip = video_clip.with_audio(voice_clip)
        clips.append(video_clip)

    if not clips:
        print("No clips generated.")
        return

    # 2. Concatenate Clips
    final_clip = concatenate_videoclips(clips)

    # 3. Add BGM if exists
    bgm_file = "bgm.mp3"
    if os.path.exists(bgm_file):
        bgm_clip = AudioFileClip(bgm_file)
        
        # Fit BGM to video duration
        # If BGM is longer, crop it using subclipped (v2)
        if bgm_clip.duration > final_clip.duration:
             bgm_clip = bgm_clip.subclipped(0, final_clip.duration)
        else:
             # If BGM is shorter, we verify if we can loop it or just leave it.
             # For MoviePy v2, if looping is complex, we just stick to original length for now
             # to avoid errors, or find a loop method. 
             # Assuming standard BGM is long enough.
             pass
        
        # Reduce volume: v2 uses `with_volume_scaled`
        bgm_clip = bgm_clip.with_volume_scaled(0.3)

        # Combine Voice and BGM
        # Note: CompositeAudioClip combines audios, starting at 0 by default.
        final_audio = CompositeAudioClip([final_clip.audio, bgm_clip])
        final_clip = final_clip.with_audio(final_audio)
    else:
        print("Warning: bgm.mp3 not found. Video will have no background music.")

    # 4. Write Output
    output_filename = "showa_dagashi_top5.mp4"
    print(f"Writing video to {output_filename}...")
    final_clip.write_videofile(output_filename, fps=24)
    
    # Cleanup temporary audio files
    print("Cleaning up...")
    for i in range(len(slides_content)):
        try:
            if os.path.exists(f"audio_{i}.mp3"):
                os.remove(f"audio_{i}.mp3")
        except:
            pass
    print("Done!")

if __name__ == "__main__":
    generate_voice_and_video()
