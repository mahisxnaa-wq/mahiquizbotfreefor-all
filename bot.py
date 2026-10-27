import os
import random
import sqlite3
import asyncio
from aiohttp import web
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    PollAnswerHandler,
    ContextTypes,
)
from questions import QUIZ_DATA

# Environment variables se token lena
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 8080))

# Database Setup (Leaderboard & Points)
DB_FILE = "quiz_bot.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS scores (
            chat_id INTEGER,
            user_id INTEGER,
            username TEXT,
            score INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        )
    ''')
    conn.commit()
    conn.close()

def update_score(chat_id: int, user_id: int, username: str, points: int = 1):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO scores (chat_id, user_id, username, score)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
            score = score + ?,
            username = ?
    ''', (chat_id, user_id, username, points, points, username))
    conn.commit()
    conn.close()

def get_top_scores(chat_id: int, limit: int = 10):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        SELECT username, score FROM scores
        WHERE chat_id = ?
        ORDER BY score DESC
        LIMIT ?
    ''', (chat_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows

# Track active polls: {poll_id: {"correct_id": int, "chat_id": int}}
ACTIVE_POLLS = {}

# Commands
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 **Namaste! Main Study Group Quiz Bot hoon!**\n\n"
        "Aap mujhe apne group me add kar sakte hain aur quiz chalu kar sakte hain.\n\n"
        "📌 **Available Commands:**\n"
        "• `/quiz` - Ek random quiz question start karein\n"
        "• `/quiz <category>` - Specific topic ka quiz (e.g., `/quiz science`, `/quiz computer`, `/quiz gk`)\n"
        "• `/leaderboard` - Group ke top scorers ki list dekhein\n"
        "• `/help` - Help aur jankari\n\n"
        "👥 *Group me mujhe Admin banayein taaki main smoothly Polls bhej sakun!*"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **Bot Commands Guide:**\n\n"
        "1. `/quiz` : Instant sawaal aayega jisme 4 options honge.\n"
        "2. Categories: `/quiz science`, `/quiz gk`, `/quiz computer`, `/quiz history`\n"
        "3. Har sahi jawab par **+1 Point** milta hai!\n"
        "4. `/leaderboard` type karke group ranking check karein."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    args = context.args

    # Category filter
    filtered_questions = QUIZ_DATA
    if args:
        requested_category = args[0].lower()
        cat_matches = [q for q in QUIZ_DATA if q.get("category", "").lower() == requested_category]
        if cat_matches:
            filtered_questions = cat_matches
        else:
            await update.message.reply_text(
                f"⚠️ Category '{requested_category}' nahi mili. Available: `science`, `computer`, `gk`, `history`.\nRandom sawaal bheja ja raha hai!",
                parse_mode="Markdown"
            )

    selected_q = random.choice(filtered_questions)

    # Send Native Quiz Poll
    # is_anonymous=False is REQUIRED to track scores!
    message = await context.bot.send_poll(
        chat_id=chat_id,
        question=f"📚 {selected_q['question']}",
        options=selected_q["options"],
        type="quiz",
        correct_option_id=selected_q["correct_id"],
        explanation=selected_q.get("explanation", "Great job!"),
        is_anonymous=False
    )

    # Store poll context to verify answer
    ACTIVE_POLLS[message.poll.id] = {
        "correct_id": selected_q["correct_id"],
        "chat_id": chat_id
    }

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    poll_id = answer.poll_id
    user = answer.user
    selected_options = answer.option_ids

    if poll_id in ACTIVE_POLLS and selected_options:
        poll_info = ACTIVE_POLLS[poll_id]
        if selected_options[0] == poll_info["correct_id"]:
            chat_id = poll_info["chat_id"]
            username = user.first_name or user.username or f"User_{user.id}"
            update_score(chat_id, user.id, username, points=1)

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    top_users = get_top_scores(chat_id, limit=10)

    if not top_users:
        await update.message.reply_text("🏆 Abhi tak kisi ne koi points score nahi kiye! `/quiz` start karein.")
        return

    text = "🏆 **Group Quiz Leaderboard** 🏆\n\n"
    medals = ["🥇", "🥈", "🥉"]

    for idx, (username, score) in enumerate(top_users, start=1):
        badge = medals[idx - 1] if idx <= 3 else f"{idx}."
        text += f"{badge} **{username}** : {score} pts\n"

    await update.message.reply_text(text, parse_mode="Markdown")

# Render ke free web service ke liye lightweight HTTP ping server
async def web_server():
    async def handle_ping(request):
        return web.Response(text="Bot is running active and fine!")

    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web server started on port {PORT}")

async def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN environment variable set nahi hai!")
        return

    init_db()

    # Telegram bot application setup
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("quiz", quiz_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(PollAnswerHandler(handle_poll_answer))

    # Start dummy web server for Render
    await web_server()

    # Start polling
    print("Bot is polling...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    # Keep running forever
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
