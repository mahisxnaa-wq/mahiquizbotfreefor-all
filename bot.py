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
        self.wfile.write(b"Quiz Bot is alive and running on Render!")

    def log_message(self, format, *args):
        # Console me logs flood na hon
        return

def run_health_server():
    """Render Web Service ke liye background port listener"""
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    logger.info(f"Health check web server started on port {port}")
    server.serve_forever()


# ---------------------- COMMAND HANDLERS ----------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
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
        "• Koi bhi user yahan naya quiz bana sakta hai (`/newquiz`)\n"
        "• Text ya `.txt` file bhejkar ek click me quiz import kar sakte hain\n"
        "• Telegram Groups me quiz contest chala sakte hain\n"
        "• Real-time leaderboard aur rankings dekh sakte hain\n\n"
        "Neeche diye gaye buttons se shuru karein 👇"
    )

    await update.message.reply_text(
        welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command handler"""
    help_text = (
        "📖 **Bot Commands Guide:**\n\n"
        "• `/start` - Bot ko shuru karein aur main menu dekhein\n"
        "• `/quizzes` - Available quizzes ki list dekhein\n"
        "• `/newquiz` - Naya quiz banayein (Sabke liye open hai)\n"
        "• `/leaderboard` - Top rankers ki list dekhein\n"
        "• `/cancel` - Chalu process cancel karein\n\n"
        "📝 **Bulk Questions Add Karne Ka Tarika:**\n"
        "Aap direct is format me text ya `.txt` file bhej sakte hain:\n"
        "```\n"
        "Q1. Bharat ki rajdhani kya hai?\n"
        "A) Mumbai\n"
        "B) Kolkata\n"
        "C) New Delhi\n"
        "D) Chennai\n"
        "Ans: C\n"
        "Exp: 1911 me New Delhi rajdhani ghoshit hui thi.\n"
        "```"
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


# ---------------------- STEP-BY-STEP QUIZ CREATOR ----------------------

async def newquiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Interactive quiz creation shuru karna"""
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
        "Ab apna **Question 1** bhejiye:\n\n"
        "*(Jab sabhi questions add ho jayein, toh `/done` dabayein)*",
        parse_mode=ParseMode.MARKDOWN
    )
    return QUESTION_PROMPT


async def newquiz_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == "/done":
        return await newquiz_finish(update, context)

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


async def newquiz_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_lines = [line.strip() for line in update.message.text.split("\n") if line.strip()]
    if len(raw_lines) < 2:
        await update.message.reply_text("❌ Kam se kam 2 options hone chahiye. Dobara options bhejiye:")
        return OPTIONS_PROMPT

    context.user_data["current_options"] = raw_lines[:10]

    opts_display = "\n".join([f"{i+1}) {opt}" for i, opt in enumerate(context.user_data["current_options"])])
    await update.message.reply_text(
        f"Options note ho gaye:\n{opts_display}\n\n"
        "Inme se **Sahi Answer kaunsa number hai?** (1, 2, 3, ya 4 likhein):"
    )
    return CORRECT_PROMPT


async def newquiz_correct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ Kripya sahi number dalein (e.g. 1, 2, 3):")
        return CORRECT_PROMPT

    correct_idx = int(text) - 1
    total_opts = len(context.user_data["current_options"])
    if not (0 <= correct_idx < total_opts):
        await update.message.reply_text(f"❌ 1 se {total_opts} ke beech number chunein:")
        return CORRECT_PROMPT

    context.user_data["current_correct"] = correct_idx

    await update.message.reply_text(
        "💡 Is question ka koi **Explanation (Vyakhya)** dena chahte hain?\n"
        "Agar nahi, toh `/skip` likhein."
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
        "Agla question bhejiye, ya agar quiz complete ho gaya toh `/done` dabayein.",
        parse_mode=ParseMode.MARKDOWN
    )
    return QUESTION_PROMPT


async def newquiz_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    questions = context.user_data.get("questions", [])
    if not questions:
        await update.message.reply_text("❌ Aapne koi question add nahi kiya. Quiz cancel ho gaya.")
        return ConversationHandler.END

    title = context.user_data.get("title", "Untitled Quiz")
    timer = context.user_data.get("timer", config.DEFAULT_QUESTION_TIMER)
    user_id = update.effective_user.id

    quiz_id = await db.create_quiz(creator_id=user_id, title=title, timer=timer)
    for q in questions:
        await db.add_question(
            quiz_id=quiz_id,
            question_text=q["question"],
            options=q["options"],
            correct_idx=q["correct_option_index"],
            explanation=q.get("explanation", ""),
        )

    await update.message.reply_text(
        f"🎉 **Badhai ho! Aapka Quiz create ho gaya hai!**\n\n"
        f"📌 **Title:** {title}\n"
        f"🔢 **Total Questions:** {len(questions)}\n"
        f"⏱️ **Timer per Question:** {timer}s\n"
        f"🆔 **Quiz ID:** `{quiz_id}`\n\n"
        f"Khelne ke liye click karein:\n"
        f"👉 `/play_{quiz_id}`",
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("🚫 Process cancel kar di gayi hai.")
    return ConversationHandler.END


# ---------------------- BULK TEXT / FILE PARSER ----------------------

async def handle_text_or_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User ke text ya .txt document ko scan karke quiz banana"""
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

    # Parser chala kar dekhein
    questions = parse_questions_from_text(raw_text)
    if not questions:
        return

    user_id = update.effective_user.id
    # Quiz Title banayein (First question se ya general)
    first_q_preview = questions[0]["question"].split("?")[0][:30].strip()
    title = f"{first_q_preview}..." if len(questions) > 1 else questions[0]["question"][:35]

    quiz_id = await db.create_quiz(creator_id=user_id, title=title, timer=config.DEFAULT_QUESTION_TIMER)

    for q in questions:
        await db.add_question(
            quiz_id=quiz_id,
            question_text=q["question"],
            options=q["options"],
            correct_idx=q["correct_option_index"],
            explanation=q.get("explanation", "")
        )

    await update.message.reply_text(
        f"⚡ **Quiz Successfully Create Ho Gaya!**\n\n"
        f"📖 **Title:** {title}\n"
        f"🔢 **Total Questions:** {len(questions)}\n"
        f"⏱️ **Timer:** {config.DEFAULT_QUESTION_TIMER}s\n"
        f"🆔 **Quiz ID:** `{quiz_id}`\n\n"
        f"Khelne ke liye click karein:\n"
        f"👉 `/play_{quiz_id}`",
        parse_mode=ParseMode.MARKDOWN
    )


# ---------------------- PLAY QUIZ / LIVE ENGINE ----------------------

async def list_quizzes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quizzes = await db.get_all_quizzes(limit=10)
    if not quizzes:
        msg = "Abhi koi quiz available nahi hai. Aap `/newquiz` se pehla quiz banayein!"
        if update.callback_query:
            await update.callback_query.message.reply_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    buttons = []
    for q in quizzes:
        buttons.append([
            InlineKeyboardButton(
                f"🎯 {q['title']} ({q['total_questions']} Qs)",
                callback_data=f"startquiz_{q['quiz_id']}"
            )
        ])

    reply_markup = InlineKeyboardMarkup(buttons)
    text = "📚 **Neeche diye gaye Quizzes me se chunein:**"

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
            "➕ Naya quiz banane ke liye `/newquiz` command bhejiye, ya directly text paste karein!"
        )
    elif data == "show_leaderboard":
        await leaderboard_command(update, context)
    elif data == "show_help":
        await help_command(update, context)
    elif data.startswith("startquiz_"):
        quiz_id = int(data.split("_")[1])
        await start_quiz_session(quiz_id, update.effective_chat.id, context)


async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    parts = text.split("_")
    if len(parts) > 1 and parts[1].isdigit():
        quiz_id = int(parts[1])
        await start_quiz_session(quiz_id, update.effective_chat.id, context)
    else:
        await list_quizzes_command(update, context)


async def start_quiz_session(quiz_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    quiz = await db.get_quiz(quiz_id)
    questions = await db.get_quiz_questions(quiz_id)

    if not quiz or not questions:
        await context.bot.send_message(chat_id=chat_id, text="❌ Yeh quiz khali hai ya nahi mila.")
        return

    active_sessions[chat_id] = {
        "quiz_id": quiz_id,
        "title": quiz["title"],
        "timer": quiz["timer_seconds"],
        "questions": questions,
        "current_index": 0,
        "scores": {},
        "active_poll_id": None,
    }

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🚀 **Quiz Shuru Ho Raha Hai!**\n\n"
            f"📖 **Title:** {quiz['title']}\n"
            f"🔢 **Total Questions:** {len(questions)}\n"
            f"⏱️ **Timer:** {quiz['timer_seconds']}s per question\n\n"
            f"Tayyar ho jaiye! Question 1 aa raha hai..."
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

    # Image Card Generation (with fallback)
    try:
        img_bio = create_question_image(
            question_text=f"Q{idx+1}. {q['question_text']}",
            options=q["options"],
            quiz_title=session["title"]
        )
        await context.bot.send_photo(chat_id=chat_id, photo=img_bio)
    except Exception as e:
        logger.warning(f"Image generation failed: {e}")

    # Native Telegram Quiz Poll
    poll_msg = await context.bot.send_poll(
        chat_id=chat_id,
        question=f"Q{idx+1}: {q['question_text'][:250]}",
        options=q["options"][:10],
        type=Poll.QUIZ,
        correct_option_id=q["correct_option_index"],
        open_period=timer,
        is_anonymous=False,
        explanation=q.get("explanation", "")[:200] if q.get("explanation") else None,
    )

    session["active_poll_id"] = poll_msg.poll.id
    session["current_index"] += 1

    # Schedule next question
    context.job_queue.run_once(
        quiz_timer_callback,
        when=timer + 2,
        chat_id=chat_id,
        name=f"quiz_timer_{chat_id}_{idx}"
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
                correct_idx = session["questions"][curr_idx]["correct_option_index"]
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

    result_text = f"🏁 **Quiz Samapt (Completed)!**\n\n📖 **{session['title']}**\n\n🏆 **Leaderboard:**\n"
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
        msg = "🏆 Abhi tak koi score record nahi hua hai."
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
        await update.message.reply_text("Upyog: `/broadcast Aapka Message Yahan`")
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

    await update.message.reply_text(f"✅ Broadcast {count} users ko bhej diya gaya hai!")


# ---------------------- STARTUP HOOK & MAIN ----------------------

async def post_init(application: Application):
    """Event Loop ke andar database initialize karna (Render fix)"""
    await db.init_db()
    logger.info("Database initialized successfully.")


def main():
    if config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or not config.BOT_TOKEN:
        print("❌ ERROR: BOT_TOKEN configure nahi hai! Render ke Environment Variables me daalein.")
        return

    # 1. Render Health Check server background thread me start karein
    threading.Thread(target=run_health_server, daemon=True).start()

    # 2. Telegram Application Builder with post_init
    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()

    # Conversation Handler for /newquiz
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("newquiz", newquiz_start)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, newquiz_title)],
            TIMER: [MessageHandler(filters.TEXT & ~filters.COMMAND, newquiz_timer)],
            QUESTION_PROMPT: [
                CommandHandler("done", newquiz_finish),
                MessageHandler(filters.TEXT & ~filters.COMMAND, newquiz_question)
            ],
            OPTIONS_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, newquiz_options)],
            CORRECT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, newquiz_correct)],
            EXPLANATION_PROMPT: [
                CommandHandler("skip", newquiz_explanation),
                MessageHandler(filters.TEXT & ~filters.COMMAND, newquiz_explanation)
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

    app.add_handler(MessageHandler(filters.Regex(r"^/play(_\d+)?$"), play_command))
    app.add_handler(MessageHandler(filters.Document.ALL | (filters.TEXT & ~filters.COMMAND), handle_text_or_document))

    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(PollAnswerHandler(handle_poll_answer))

    print("🤖 Telegram Quiz Bot successfully started on Render!")
    app.run_polling()


if __name__ == "__main__":
    main()
