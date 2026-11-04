import io
import textwrap
from PIL import Image, ImageDraw, ImageFont
from typing import List, Optional

def create_question_image(
    question_text: str,
    options: List[str],
    quiz_title: str = "Quiz Challenge",
    brand_name: str = "@MyQuizBot"
) -> io.BytesIO:
    """
    Question and options ke sath ek attractive exam/quiz card image generate karta hai.
    """
    width, height = 1200, 675
    # Elegant dark background (Navy / Slate)
    bg_color = (24, 32, 54)
    card_bg = (35, 45, 75)
    accent_color = (78, 161, 255)  # Telegram Blue accent
    text_color = (255, 255, 255)
    opt_bg = (48, 60, 95)
    opt_text_color = (230, 235, 245)

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Rounded card in the center
    margin = 40
    draw.rounded_rectangle([margin, margin, width - margin, height - margin], radius=24, fill=card_bg)

    # Fonts fallback handling
    try:
        title_font = ImageFont.truetype("arial.ttf", 32)
        q_font = ImageFont.truetype("arial.ttf", 36)
        opt_font = ImageFont.truetype("arial.ttf", 28)
        brand_font = ImageFont.truetype("arial.ttf", 24)
    except Exception:
        # Default font if arial is not found
        title_font = ImageFont.load_default()
        q_font = ImageFont.load_default()
        opt_font = ImageFont.load_default()
        brand_font = ImageFont.load_default()

    # Draw Header (Quiz Title)
    draw.text((margin + 30, margin + 25), quiz_title.upper(), fill=accent_color, font=title_font)
    draw.line([(margin + 30, margin + 70), (width - margin - 30, margin + 70)], fill=(60, 75, 115), width=2)

    # Word wrap Question text
    wrapped_q = textwrap.fill(question_text, width=55)
    draw.text((margin + 30, margin + 95), wrapped_q, fill=text_color, font=q_font)

    # Draw Options (2x2 grid or stacked list)
    y_start = margin + 250
    option_labels = ["A", "B", "C", "D", "E", "F"]

    for i, opt in enumerate(options[:4]):
        col = i % 2
        row = i // 2
        x = margin + 30 + col * 550
        y = y_start + row * 130

        # Option button box
        draw.rounded_rectangle([x, y, x + 520, y + 95], radius=16, fill=opt_bg)
        
        # Circle badge for A, B, C, D
        badge_x, badge_y = x + 15, y + 18
        draw.ellipse([badge_x, badge_y, badge_x + 55, badge_y + 55], fill=accent_color)
        draw.text((badge_x + 18, badge_y + 12), option_labels[i], fill=(255, 255, 255), font=opt_font)

        # Option Text
        wrapped_opt = textwrap.fill(opt, width=28)
        draw.text((badge_x + 75, y + 25), wrapped_opt, fill=opt_text_color, font=opt_font)

    # Branding Footer
    draw.text((width - margin - 220, height - margin - 45), brand_name, fill=(130, 145, 175), font=brand_font)

    # Save to BytesIO
    bio = io.BytesIO()
    bio.name = "quiz_card.jpg"
    img.save(bio, "JPEG", quality=90)
    bio.seek(0)
    return bio
