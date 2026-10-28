import os

# Telegram Bot Token (BotFather se milta hai)
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Owner ka Telegram User ID (Numeric ID, jaise 123456789)
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# Render Port (Free tier deployment ke liye)
PORT = int(os.getenv("PORT", 8080))

# Database file ka naam
DB_NAME = "quiz_bot.db"
