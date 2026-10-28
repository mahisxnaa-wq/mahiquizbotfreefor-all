from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import textwrap

def generate_quiz_image(question_text: str, options: list, title: str = "QUIZ CHALLENGE") -> BytesIO:
    width, height = 900, 600
    
    # Modern Dark Gradient Background
    image = Image.new("RGB", (width, height), color=(15, 23, 42))
    draw = ImageDraw.Draw(image)
    
    # Header Banner
    draw.rectangle([(0, 0), (width, 80)], fill=(30, 58, 138))
    
    # Load Fonts
    try:
        font_header = ImageFont.truetype("NotoSans-Regular.ttf", 32)
        font_q = ImageFont.truetype("NotoSans-Regular.ttf", 26)
        font_opt = ImageFont.truetype("NotoSans-Regular.ttf", 22)
    except Exception:
        font_header = ImageFont.load_default()
        font_q = ImageFont.load_default()
        font_opt = ImageFont.load_default()
        
    # Header Text
    draw.text((40, 24), f"🎯 {title.upper()}", fill=(255, 255, 255), font=font_header)
    
    # Question Card Box
    draw.rectangle([(40, 110), (width - 40, 250)], fill=(30, 41, 59), outline=(59, 130, 246), width=2)
    wrapped_q = textwrap.fill(question_text, width=54)
    draw.text((60, 130), wrapped_q, fill=(248, 250, 252), font=font_q)
    
    # Options A, B, C, D
    opt_letters = ["A", "B", "C", "D"]
    colors = [(239, 68, 68), (34, 197, 94), (234, 179, 8), (168, 85, 247)]
    y_pos = 280
    
    for i in range(len(options)):
        # Box background
        draw.rectangle([(40, y_pos), (width - 40, y_pos + 55)], fill=(30, 41, 59))
        # Badge circle
        draw.rectangle([(50, y_pos + 10), (90, y_pos + 45)], fill=colors[i % 4])
        draw.text((63, y_pos + 15), opt_letters[i], fill=(255, 255, 255), font=font_opt)
        # Option text
        draw.text((110, y_pos + 15), str(options[i])[:55], fill=(226, 232, 240), font=font_opt)
        y_pos += 65
        
    # Footer Watermark
    draw.text((width - 240, height - 35), "⚡ Study Quiz Master", fill=(148, 163, 184), font=font_opt)
    
    bio = BytesIO()
    bio.name = "quiz_card.png"
    image.save(bio, "PNG")
    bio.seek(0)
    return bio
