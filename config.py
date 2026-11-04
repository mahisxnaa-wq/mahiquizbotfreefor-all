import os
from dotenv import load_dotenv

# .env file load karein
load_dotenv()

# Telegram Bot Configuration
# Yahan apna @BotFather se mila hua BOT TOKEN daalein
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Admin / Owner IDs
OWNER_ID = int(os.getenv("OWNER_ID", "6416451659"))
ADMIN_IDS = [int(i.strip()) for i in os.getenv("ADMIN_IDS", "6416451659").split(",") if i.strip().isdigit()]
if OWNER_ID not in ADMIN_IDS:
    ADMIN_IDS.append(OWNER_ID)

# MongoDB Atlas Connection URI
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb+srv://username:password@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority")

# Default Quiz Settings
DEFAULT_QUESTION_TIMER = int(os.getenv("DEFAULT_QUESTION_TIMER", "20"))  # in seconds
MAX_OPTIONS = 10
MIN_OPTIONS = 2
