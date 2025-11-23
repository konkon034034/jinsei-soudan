def create_text_clip(text, fontsize=40, color='white', bg_color='black', 
                     duration=1.0, size=(1920, 1080), position='bottom'):
    """PILでテキスト画像を作成してImageClipに変換"""
    
    # 画像作成
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # フォント設定
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", fontsize)
    except Exception as e:
        print(f"⚠ フォント読み込み失敗: {e}")
        font = ImageFont.load_default()
    
    # 背景の矩形を描画
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    # テキストの配置計算
    padding = 20
    box_width = text_width + padding * 2
    box_height = text_height + padding * 2
    
    # 位置によって配置を変える
    if position == 'bottom':
        x = (size[0] - box_width) // 2
        y = size[1] - box_height - 50
    else:  # center
        x = (size[0] - box_width) // 2
        y = (size[1] - box_height) // 2
    
    # 背景矩形（半透明の黒）
    draw.rectangle(
        [x, y, x + box_width, y + box_height],
        fill=(0, 0, 0, 180)
    )
    
    # テキスト描画
    text_x = x + padding
    text_y = y + padding
    draw.text((text_x, text_y), text, font=font, fill=color)
    
    # 一時ファイルとして保存
    temp_path = WORK_DIR / f"text_temp_{hash(text)}.png"
    img.save(temp_path)
    
    # ImageClipとして返す
    return ImageClip(str(temp_path)).set_duration(duration).set_position(('center', 'bottom'))
