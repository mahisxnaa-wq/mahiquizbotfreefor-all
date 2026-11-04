import os
from dotenv import load_dotenv

# .env file load karein
load_dotenv()

# Telegram Bot Configuration
# Yahan apna @BotFather se mila hua BOT TOKEN daalein
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Admin IDs (apna Telegram user id yahan dalein, e.g. [123456789])
ADMIN_IDS = [int(i.strip()) for i in os.getenv("ADMIN_IDS", "0").split(",") if i.strip().isdigit()]

# MongoDB Atlas Connection URI
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb+srv://username:password@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority")

# Default Quiz Settings
DEFAULT_QUESTION_TIMER = int(os.getenv("DEFAULT_QUESTION_TIMER", "20"))  # in seconds
MAX_OPTIONS = 10
MIN_OPTIONS = 2
