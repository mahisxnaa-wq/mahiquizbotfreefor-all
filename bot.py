import logging
import asyncio
import io
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Poll,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    PollAnswerHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

import config
from database import Database
from parser import parse_questions_from_text
from image_generator import create_question_image

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

db = Database(config.DB_NAME)

# States for /newquiz Conversation
TITLE, TIMER, QUESTION_PROMPT, OPTIONS_PROMPT, CORRECT_PROMPT, EXPLANATION_PROMPT = range(6)

# In-memory tracking of active quiz sessions: chat_id -> SessionData
active_sessions: Dict[int, Dict[str, Any]] = {}


# ---------------------- RENDER HEALTH-CHECK SERVER ----------------------

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Quiz Bot is alive and running!")

    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info(f"Health check web server started on port {port}")
    server.serve_forever()


# ---------------------- COMMAND HANDLERS ----------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.register_user(user.id, user.username, user.first_name)

    keyboard = [
        [
            InlineKeyboardButton("🎯 Play Quiz", callback_data="list_quizzes"),
            InlineKeyboardButton("➕ Create Quiz", callback_data="create_quiz_info"),
        ],
        [
            InlineKeyboardButton("🏆 Leaderboard", callback_data="show_leaderboard"),
            InlineKeyboardButton("ℹ️ Help", callback_data="show_help"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = (
        f"👋 **Namaste {user.first_name}!**\n\n"
        "Main aapka **Telegram Quiz Bot** hoon! 🧠\n\n"
        "✨ **Aap yahan kya-kya kar sakte hain:**\n"
        "• Koi bhi user naya quiz bana sakta hai (`/newquiz`)\n"
        "• Text ya `.txt` file bhejkar ek click me quiz import kar sakte hain\n"
        "• Groups me quiz contest chala sakte hain\n"
        "• Real-time leaderboard dekh sakte hain\n\n"
        "Neeche diye gaye buttons se shuru karein 👇"
    )

    await update.message.reply_text(
        welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **Bot Commands Guide:**\n\n"
        "• `/start` - Main menu dekhein\n"
        "• `/quizzes` - Available quizzes ki list\n"
        "• `/newquiz` - Naya quiz banayein (Sabke liye open)\n"
        "• `/leaderboard` - Top rankers\n"
        "• `/cancel` - Chalu process cancel karein\n\n"
        "📝 **Bulk Questions Add Karne Ka Tarika:**\n"
        "Direct text paste karein ya `.txt` file bhejiye:\n"
        "```\n"
        "Q1. Bharat ki rajdhani kya hai?\n"
        "A) Mumbai\n"
        "B) Kolkata\n"
        "C) New Delhi\n"
        "D) Chennai\n"
        "Ans: C\n"
        "```\n\n"
        "Ya ✅ tick format bhi chalega:\n"
        "```\n"
        "Bharat ki rajdhani?\n"
        "Mumbai\n"
        "Kolkata\n"
        "New Delhi ✅\n"
        "Chennai\n"
        "```"
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


# ---------------------- STEP-BY-STEP QUIZ CREATOR ----------------------

async def newquiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["questions"] = []

    await update.message.reply_text(
        "📝 **Naya Quiz Banayein!**\n\n"
        "Sabse pehle apne **Quiz ka Title/Naam** bhejiye:\n"
        "(Jaise: *General Knowledge Test* ya *Class 10 Science*)\n\n"
        "Cancel karne ke liye `/cancel` likhein.",
        parse_mode=ParseMode.MARKDOWN
    )
    return TITLE


async def newquiz_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    context.user_data["title"] = title

    await update.message.reply_text(
        f"✅ Title: **{title}**\n\n"
        "Har question ke liye kitna **Timer (Seconds)** rakhna chahte hain?\n"
        "(Recommended: 15, 20, 30, ya 45)",
        parse_mode=ParseMode.MARKDOWN
    )
    return TIMER


async def newquiz_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    timer = int(text) if text.isdigit() and 10 <= int(text) <= 300 else config.DEFAULT_QUESTION_TIMER
    context.user_data["timer"] = timer

    await update.message.reply_text(
        f"⏱️ Timer set ho gaya: **{timer} seconds**\n\n"
        "Ab aap questions bhej sakte hain:\n\n"
        "**Option 1:** Ek-ek question bhejiye (bot aapko guide karega)\n"
        "**Option 2:** Saare questions ek sath text me paste kar dijiye (✅ tick ya Ans: C format)\n"
        "**Option 3:** `.txt` file bhej dijiye\n\n"
        "*(Jab complete ho jaye toh `/done` dabayein)*",
        parse_mode=ParseMode.MARKDOWN
    )
    return QUESTION_PROMPT


async def newquiz_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == "/done":
        return await newquiz_finish(update, context)

    # Check agar user ne pura question + options ya multiple questions paste kar diye
    parsed = parse_questions_from_text(text)
    if parsed:
        context.user_data["questions"].extend(parsed)
        count = len(parsed)
        total = len(context.user_data["questions"])
        await update.message.reply_text(
            f"✅ **{count} Questions detect aur add ho gaye!** (Total: {total})\n\n"
            "Aur questions bhejiye ya `/done` dabayein.",
            parse_mode=ParseMode.MARKDOWN
        )
        return QUESTION_PROMPT

    context.user_data["current_question"] = text
    await update.message.reply_text(
        "Ab is question ke **Options** bhejiye (har option nayi line me):\n\n"
        "Example:\n"
        "Mumbai\n"
        "Kolkata\n"
        "New Delhi\n"
        "Chennai"
    )
    return OPTIONS_PROMPT


async def newquiz_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Agar user /newquiz ke dauran seedha .txt file bhej de"""
    doc = update.message.document
    if doc.file_name and doc.file_name.lower().endswith((".txt", ".text")):
        file = await doc.get_file()
        byte_content = await file.download_as_bytearray()
        raw_text = byte_content.decode("utf-8", errors="ignore")
        parsed = parse_questions_from_text(raw_text)
        if parsed:
            context.user_data["questions"].extend(parsed)
            count = len(parsed)
            total = len(context.user_data["questions"])
            await update.message.reply_text(
                f"✅ **File se {count} Questions import ho gaye!** (Total: {total})\n\n"
                "Aur bhejiye ya `/done` dabayein.",
                parse_mode=ParseMode.MARKDOWN
            )
            return QUESTION_PROMPT
        else:
            await update.message.reply_text("❌ File me koi valid question detect nahi hua. Format check karein.")
            return QUESTION_PROMPT
    else:
        await update.message.reply_text("❌ Sirf `.txt` file bhejiye ya text paste karein.")
        return QUESTION_PROMPT


async def newquiz_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_lines = [line.strip() for line in update.message.text.split("\n") if line.strip()]
    if len(raw_lines) < 2:
        await update.message.reply_text("❌ Kam se kam 2 options chahiye. Dobara bhejiye:")
        return OPTIONS_PROMPT

    context.user_data["current_options"] = raw_lines[:10]

    opts_display = "\n".join([f"{i+1}) {opt}" for i, opt in enumerate(context.user_data["current_options"])])
    await update.message.reply_text(
        f"Options note ho gaye:\n{opts_display}\n\n"
        "Inme se **Sahi Answer kaunsa number hai?** (1, 2, 3, ya 4):"
    )
    return CORRECT_PROMPT


async def newquiz_correct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ Sirf number dalein (e.g. 1, 2, 3):")
        return CORRECT_PROMPT

    correct_idx = int(text) - 1
    total_opts = len(context.user_data["current_options"])
    if not (0 <= correct_idx < total_opts):
        await update.message.reply_text(f"❌ 1 se {total_opts} ke beech number chunein:")
        return CORRECT_PROMPT

    context.user_data["current_correct"] = correct_idx

    await update.message.reply_text(
        "💡 Is question ka **Explanation** dena chahte hain?\n"
        "Agar nahi toh `/skip` likhein."
    )
    return EXPLANATION_PROMPT


async def newquiz_explanation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    explanation = "" if text.lower() == "/skip" else text

    q_data = {
        "question": context.user_data["current_question"],
        "options": context.user_data["current_options"],
        "correct_option_index": context.user_data["current_correct"],
        "explanation": explanation,
    }
    context.user_data["questions"].append(q_data)

    q_count = len(context.user_data["questions"])
    await update.message.reply_text(
        f"✅ **Question #{q_count} add ho gaya!**\n\n"
        "Agla question bhejiye, ya `/done` dabayein.",
        parse_mode=ParseMode.MARKDOWN
    )
    return QUESTION_PROMPT


async def newquiz_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    questions = context.user_data.get("questions", [])
    if not questions:
        await update.message.reply_text("❌ Koi question nahi mila. Quiz cancel ho gaya.")
        return ConversationHandler.END

    title = context.user_data.get("title", "Untitled Quiz")
    timer = context.user_data.get("timer", config.DEFAULT_QUESTION_TIMER)
    user = update.effective_user

    quiz_id = await db.create_quiz(
        creator_id=user.id,
        title=title,
        questions=questions,
        timer=timer,
        creator_name=user.first_name or user.username or ""
    )

    await update.message.reply_text(
        f"🎉 **Quiz Create Ho Gaya!**\n\n"
        f"📌 **Title:** {title}\n"
        f"🔢 **Total Questions:** {len(questions)}\n"
        f"⏱️ **Timer:** {timer}s per question\n"
        f"🆔 **Quiz ID:** `{quiz_id}`\n\n"
        f"Khelne ke liye:\n"
        f"👉 `/play_{quiz_id}`",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🚫 Process cancel ho gayi.")
    return ConversationHandler.END


# ---------------------- BULK TEXT / FILE PARSER ----------------------

async def handle_text_or_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User ke text ya .txt file se directly quiz banana (bina /newquiz ke)"""
    raw_text = ""

    if update.message.document:
        doc = update.message.document
        if doc.file_name and doc.file_name.lower().endswith((".txt", ".text")):
            file = await doc.get_file()
            byte_content = await file.download_as_bytearray()
            raw_text = byte_content.decode("utf-8", errors="ignore")
        else:
            return
    elif update.message.text:
        raw_text = update.message.text

    if not raw_text or len(raw_text.strip()) < 10:
        return

    questions = parse_questions_from_text(raw_text)
    if not questions:
        return

    user = update.effective_user
    await db.register_user(user.id, user.username, user.first_name)

    first_q_preview = questions[0]["question"][:30].strip()
    title = f"{first_q_preview}..." if len(questions) > 1 else questions[0]["question"][:40]

    quiz_id = await db.create_quiz(
        creator_id=user.id,
        title=title,
        questions=questions,
        timer=config.DEFAULT_QUESTION_TIMER,
        creator_name=user.first_name or user.username or ""
    )

    await update.message.reply_text(
        f"⚡ **Quiz Create Ho Gaya!**\n\n"
        f"📖 **Title:** {title}\n"
        f"🔢 **Total Questions:** {len(questions)}\n"
        f"⏱️ **Timer:** {config.DEFAULT_QUESTION_TIMER}s\n"
        f"🆔 **Quiz ID:** `{quiz_id}`\n\n"
        f"👉 `/play_{quiz_id}`",
        parse_mode=ParseMode.MARKDOWN
    )


# ---------------------- PLAY QUIZ / LIVE ENGINE ----------------------

async def list_quizzes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quizzes = await db.get_all_quizzes(limit=10)
    if not quizzes:
        msg = "Abhi koi quiz available nahi hai. `/newquiz` se pehla quiz banayein!"
        if update.callback_query:
            await update.callback_query.message.reply_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    buttons = []
    for q in quizzes:
        buttons.append([
            InlineKeyboardButton(
                f"🎯 {q['title'][:30]} ({q['total_questions']} Qs)",
                callback_data=f"sq_{q['quiz_id']}"
            )
        ])

    reply_markup = InlineKeyboardMarkup(buttons)
    text = "📚 **Neeche se Quiz chunein:**"

    if update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "list_quizzes":
        await list_quizzes_command(update, context)
    elif data == "create_quiz_info":
        await query.message.reply_text(
            "➕ `/newquiz` command bhejiye ya directly questions paste / `.txt` file bhej dijiye!"
        )
    elif data == "show_leaderboard":
        await leaderboard_command(update, context)
    elif data == "show_help":
        await help_command(update, context)
    elif data.startswith("sq_"):
        quiz_id = data[3:]
        await start_quiz_session(quiz_id, update.effective_chat.id, context)


async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    parts = text.split("_", 1)
    if len(parts) > 1 and parts[1].strip():
        quiz_id = parts[1].strip()
        await start_quiz_session(quiz_id, update.effective_chat.id, context)
    else:
        await list_quizzes_command(update, context)


async def start_quiz_session(quiz_id: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    quiz = await db.get_quiz(quiz_id)

    if not quiz or not quiz.get("questions"):
        await context.bot.send_message(chat_id=chat_id, text="❌ Quiz nahi mila ya khali hai.")
        return

    questions = quiz["questions"]
    timer = quiz.get("timer_seconds", 20)

    active_sessions[chat_id] = {
        "quiz_id": quiz_id,
        "title": quiz["title"],
        "timer": timer,
        "questions": questions,
        "current_index": 0,
        "scores": {},
        "active_poll_id": None,
    }

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🚀 **Quiz Shuru Ho Raha Hai!**\n\n"
            f"📖 **{quiz['title']}**\n"
            f"🔢 **Questions:** {len(questions)}\n"
            f"⏱️ **Timer:** {timer}s per question\n\n"
            f"Tayyar ho jaiye..."
        ),
        parse_mode=ParseMode.MARKDOWN
    )
    await asyncio.sleep(2)
    await send_next_question(chat_id, context)


async def send_next_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    session = active_sessions.get(chat_id)
    if not session:
        return

    idx = session["current_index"]
    questions = session["questions"]

    if idx >= len(questions):
        await finish_quiz_session(chat_id, context)
        return

    q = questions[idx]
    timer = session["timer"]

    # Get question text and options (support both field names)
    q_text = q.get("question_text") or q.get("question", "")
    options = q.get("options", [])
    correct_idx = q.get("correct_option_id") if "correct_option_id" in q else q.get("correct_option_index", 0)
    explanation = q.get("explanation", "")

    # Image Card (with fallback)
    try:
        img_bio = create_question_image(
            question_text=f"Q{idx+1}. {q_text}",
            options=options,
            quiz_title=session["title"]
        )
        await context.bot.send_photo(chat_id=chat_id, photo=img_bio)
    except Exception as e:
        logger.warning(f"Image generation failed: {e}")

    # Telegram Quiz Poll
    poll_question = f"Q{idx+1}: {q_text[:250]}"
    poll_options = options[:10]

    # Ensure at least 2 options
    if len(poll_options) < 2:
        poll_options = poll_options + ["(no option)"] * (2 - len(poll_options))

    poll_msg = await context.bot.send_poll(
        chat_id=chat_id,
        question=poll_question,
        options=poll_options,
        type=Poll.QUIZ,
        correct_option_id=correct_idx,
        open_period=timer,
        is_anonymous=False,
        explanation=explanation[:200] if explanation else None,
    )

    session["active_poll_id"] = poll_msg.poll.id
    session["current_index"] += 1

    context.job_queue.run_once(
        quiz_timer_callback,
        when=timer + 2,
        chat_id=chat_id,
        name=f"qt_{chat_id}_{idx}"
    )


async def quiz_timer_callback(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    await send_next_question(chat_id, context)


async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    user = answer.user
    selected_option = answer.option_ids[0] if answer.option_ids else None

    for chat_id, session in active_sessions.items():
        if session.get("active_poll_id") == answer.poll_id:
            curr_idx = session["current_index"] - 1
            if 0 <= curr_idx < len(session["questions"]):
                q = session["questions"][curr_idx]
                correct_idx = q.get("correct_option_id") if "correct_option_id" in q else q.get("correct_option_index", 0)
                if selected_option == correct_idx:
                    session["scores"][user.id] = session["scores"].get(user.id, 0) + 1
                    await db.register_user(user.id, user.username, user.first_name)
            break


async def finish_quiz_session(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    session = active_sessions.pop(chat_id, None)
    if not session:
        return

    scores = session["scores"]
    quiz_id = session["quiz_id"]
    total_q = len(session["questions"])

    for uid, sc in scores.items():
        await db.record_score(quiz_id, chat_id, uid, sc, total_q)

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    result_text = f"🏁 **Quiz Complete!**\n\n📖 **{session['title']}**\n\n🏆 **Results:**\n"
    if not sorted_scores:
        result_text += "Kisi ne bhi answer nahi diya."
    else:
        medals = ["🥇", "🥈", "🥉", "🎖️", "🎖️"]
        for rank, (uid, sc) in enumerate(sorted_scores[:10], start=1):
            medal = medals[rank - 1] if rank <= len(medals) else "🔹"
            result_text += f"{medal} **Rank {rank}:** `{sc}/{total_q}` Sahi\n"

    await context.bot.send_message(chat_id=chat_id, text=result_text, parse_mode=ParseMode.MARKDOWN)


# ---------------------- LEADERBOARD & ADMIN ----------------------

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leaders = await db.get_leaderboard(limit=10)
    if not leaders:
        msg = "🏆 Abhi tak koi score record nahi hua."
    else:
        msg = "🏆 **Global Top Rankers:**\n\n"
        medals = ["🥇", "🥈", "🥉", "🎖️", "🎖️"]
        for i, user in enumerate(leaders, start=1):
            medal = medals[i - 1] if i <= len(medals) else "🔹"
            name = user["first_name"] or user["username"] or "Learner"
            msg += f"{medal} **{name}**: `{user['score']}` Points\n"

    if update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in config.ADMIN_IDS and config.ADMIN_IDS != [0]:
        await update.message.reply_text("❌ Aap admin nahi hain.")
        return

    msg_to_send = " ".join(context.args)
    if not msg_to_send:
        await update.message.reply_text("Usage: `/broadcast Aapka Message`")
        return

    users = await db.get_all_users()
    count = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=msg_to_send, parse_mode=ParseMode.MARKDOWN)
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    await update.message.reply_text(f"✅ Broadcast {count} users ko bhej diya!")


# ---------------------- STARTUP & MAIN ----------------------

async def post_init(application: Application):
    """Database init on startup (Render compatible)"""
    await db.init_db()
    logger.info("Database initialized successfully.")


def main():
    if config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or not config.BOT_TOKEN:
        print("ERROR: BOT_TOKEN set nahi hai!")
        return

    # Render Health Check
    threading.Thread(target=run_health_server, daemon=True).start()

    # Build Application
    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    # /newquiz Conversation Handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("newquiz", newquiz_start)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, newquiz_title)],
            TIMER: [MessageHandler(filters.TEXT & ~filters.COMMAND, newquiz_timer)],
            QUESTION_PROMPT: [
                CommandHandler("done", newquiz_finish),
                MessageHandler(filters.Document.ALL, newquiz_document),
                MessageHandler(filters.TEXT & ~filters.COMMAND, newquiz_question),
            ],
            OPTIONS_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, newquiz_options)],
            CORRECT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, newquiz_correct)],
            EXPLANATION_PROMPT: [
                CommandHandler("skip", newquiz_explanation),
                MessageHandler(filters.TEXT & ~filters.COMMAND, newquiz_explanation),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("quizzes", list_quizzes_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(conv_handler)

    # /play_QUIZID
    app.add_handler(MessageHandler(filters.Regex(r"^/play_"), play_command))

    # Direct text/file -> quiz
    app.add_handler(MessageHandler(filters.Document.ALL | (filters.TEXT & ~filters.COMMAND), handle_text_or_document))

    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(PollAnswerHandler(handle_poll_answer))

    print("🤖 Quiz Bot started successfully!")
    app.run_polling()


if __name__ == "__main__":
    main()
