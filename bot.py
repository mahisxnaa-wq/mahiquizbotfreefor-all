import logging
import asyncio
import io
import os
import time
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
from telegram.request import HTTPXRequest

import config
from database import Database
from parser import parse_questions_from_text
from image_generator import create_question_image

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

db = Database()

# States for /newquiz Conversation
TITLE, QUESTION_PROMPT, OPTIONS_PROMPT, CORRECT_PROMPT, EXPLANATION_PROMPT, TIMER = range(6)

# States for /edit Conversation
EDIT_MENU, EDIT_NAME_INPUT, EDIT_TIMER_INPUT, EDIT_ADD_Q_INPUT, EDIT_REMOVE_Q_INPUT = range(10, 15)

# In-memory tracking of active quiz sessions: chat_id -> SessionData
active_sessions: Dict[int, Dict[str, Any]] = {}

EXPLANATION_PREFIXES = ["ex:-", "ex:", "ex-", "ex.-", "exp:-", "exp:", "exp-", "exp.-", "explanation:", "explanation-", "vyakhya:", "व्याख्या:", "व्याख्या:-", "व्याख्या-"]

def is_exp_line(line: str) -> bool:
    l = line.lower().strip()
    l_clean = re.sub(r'^(?:[a-z0-9][\.\)]|\([a-z0-9]\))\s*', '', l).strip()
    return any(l.startswith(p) or l_clean.startswith(p) for p in EXPLANATION_PREFIXES)

def extract_exp_text(line: str) -> str:
    cleaned = re.sub(r'^(?:[a-z0-9][\.\)]|\([a-z0-9]\))\s*', '', line.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r'^(?:ex(?:p(?:lanation)?)?|vyakhya|व्याख्या)\s*[:=\.\-]+\s*', '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


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
    chat = update.effective_chat
    chat_id = chat.id
    await db.register_user(user.id, user.username, user.first_name)

    # Deep link check: /start play_QUIZID (jab Group button se aaye)
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith("play_"):
            quiz_id = arg[5:]
            if quiz_id:
                await start_quiz_session(quiz_id, chat_id, context)
                return ConversationHandler.END

    # Agar group me /start bheja hai bina quiz ID ke
    if chat.type != "private":
        bot_username = (await context.bot.get_me()).username
        keyboard = [
            [InlineKeyboardButton("🍼 Naya Quiz Banayein (Private Me) 🎀", url=f"https://t.me/{bot_username}?start=newquiz")]
        ]
        await update.message.reply_text(
            "Arey re! 🥺 Quiz creation group me nahi hota ji!\n\n"
            "Group me hum sirf **masti se quiz khelte hain!** 🎯\n"
            "Naya quiz banane ke liye mujhe **Private (DM) me message karo na**! 🧸💖",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END

    # Private chat me seedha quiz creation shuru karo
    context.user_data.clear()
    context.user_data["questions"] = []

    await update.message.reply_text(
        "📝 **Mela Naya Pyala Quiz Banayein!** 🧸🎀\n\n"
        "Apne pyale-pyale **Quiz ka Naam/Title** batao na:\n"
        "(Jaise: *Mahi Ki Cutie Quiz* ya *Masti Time GK*) 🥰✨\n\n"
        "Nahi banana toh `/cancel` bol dena, katti ho jaungi 🥺",
        parse_mode=ParseMode.MARKDOWN
    )
    return TITLE


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **Meli Pyali Help Guide Suno Na:** 🧸🎀\n\n"
        "• `/start` ya `/newquiz` - Pyala sa naya quiz banao 🍼\n"
        "• `/quizzes` - Saare quizzes ki list dekho 📋\n"
        "• `/leaderboard` - Sabse aage kaun hai dekho 🏆\n"
        "• `/edit QUIZ_ID` - Apne quiz me kuch bhi badlo ✏️\n"
        "• `/cancel` - Chalu kaam band karna ho toh bolo 🥺\n\n"
        "📝 **Ek Saath Saare Questions Kaise Bhejein:**\n"
        "Seedha text paste kar do ya `.txt` file bhej do na:\n"
        "```\n"
        "Sawal yahan likho?\n"
        "Option 1\n"
        "Option 2\n"
        "Option 3 ✅\n"
        "Option 4\n"
        "Ex:- Pyala sa explanation\n"
        "```"
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


# ---------------------- STEP-BY-STEP QUIZ CREATOR ----------------------

async def newquiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type != "private":
        bot_username = (await context.bot.get_me()).username
        keyboard = [
            [InlineKeyboardButton("🍼 Naya Quiz Banayein (Private Me) 🎀", url=f"https://t.me/{bot_username}?start=newquiz")]
        ]
        await update.message.reply_text(
            "Arey re! 🥺 Quiz creation group me nahi hota ji!\n\n"
            "Naya quiz banane ke liye mujhe **Private (DM) me message karo na**! 🧸💖",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["questions"] = []

    await update.message.reply_text(
        "📝 **Mela Naya Pyala Quiz Banayein!** 🧸🎀\n\n"
        "Sabse pehle apne pyale se **Quiz ka Naam/Title** batao na:\n"
        "(Jaise: *Mahi Ki Cutie Quiz* ya *Class 10 Science*) 🥰✨\n\n"
        "Nahi banana toh `/cancel` bol dena, katti ho jaungi 🥺",
        parse_mode=ParseMode.MARKDOWN
    )
    return TITLE


async def newquiz_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    context.user_data["title"] = title

    await update.message.reply_text(
        f"Awwww! Kitna pyala naam hai: **{title}** 🎀💖\n\n"
        "Ab jaldi-jaldi apne **Questions** bhejo na:\n\n"
        "🍼 **Tarika 1:** Ek-ek sawal bhejo (main help kalungi)\n"
        "📄 **Tarika 2:** Saare sawal ek sath paste kal do (✅ tick format me)\n"
        "📂 **Tarika 3:** `.txt` file bhej do\n\n"
        "*(Jab saare sawal daal do toh **`/done`** bol dena ji!)* 🐣✨",
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
            f"Waaaah! **{count} Questions** add ho gaye! 🧸🎉 (Total: {total})\n\n"
            "Aur bhejna hai toh bhejte laho, ya phir **`/done`** bol do na! 🐥",
            parse_mode=ParseMode.MARKDOWN
        )
        return QUESTION_PROMPT

    context.user_data["current_question"] = text
    await update.message.reply_text(
        "Ab is sawal ke **Options** batao na (har option nayi line me):\n\n"
        "Jaise aese:\n"
        "Option 1\n"
        "Option 2\n"
        "Option 3\n"
        "Option 4 🌸"
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
                f"Yayyy! File se **{count} Questions** add ho gaye! 📄🎉 (Total: {total})\n\n"
                "Aur bhejo ya phir **`/done`** bol do na! 🐥",
                parse_mode=ParseMode.MARKDOWN
            )
            return QUESTION_PROMPT
        else:
            await update.message.reply_text("Arey re! File me sawal samajh nahi aaye mujhe 🥺 Ek baar format check karo na.")
            return QUESTION_PROMPT
    else:
        await update.message.reply_text("Gandi baat! 🥺 Sirf `.txt` file bhejo ya text paste karo na.")
        return QUESTION_PROMPT


async def newquiz_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_lines = [line.strip() for line in update.message.text.split("\n") if line.strip()]
    if len(raw_lines) < 2:
        await update.message.reply_text("Arey re! Kam se kam 2 options toh do na 🥺 Dobara bhejo:")
        return OPTIONS_PROMPT

    context.user_data["current_options"] = raw_lines[:10]

    opts_display = "\n".join([f"{i+1}) {opt}" for i, opt in enumerate(context.user_data["current_options"])])
    await update.message.reply_text(
        f"Options note kar liye maine! 🎀\n\n{opts_display}\n\n"
        "Inme se **Sahi wala Answer kaunsa number hai?** jaldi batao na (1, 2, 3, ya 4): 🥺👉👈"
    )
    return CORRECT_PROMPT


async def newquiz_correct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Hawww! Sirf number likho na (jaise: 1, 2, 3) 🥺:")
        return CORRECT_PROMPT

    correct_idx = int(text) - 1
    total_opts = len(context.user_data["current_options"])
    if not (0 <= correct_idx < total_opts):
        await update.message.reply_text(f"Gandi baat! 1 se {total_opts} ke beech ka number chuno na 🥺:")
        return CORRECT_PROMPT

    context.user_data["current_correct"] = correct_idx

    await update.message.reply_text(
        "💡 Is sawal ka koi **Pyala sa Explanation** dena hai kya?\n"
        "Agar nahi dena toh `/skip` bol do na! 🍼"
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
        f"Yayyy! **Question #{q_count}** add ho gaya! 🧸💖\n\n"
        "Agla sawal bhejo na, ya phir **`/done`** bol do! 🐣",
        parse_mode=ParseMode.MARKDOWN
    )
    return QUESTION_PROMPT


async def newquiz_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    questions = context.user_data.get("questions", [])
    if not questions:
        await update.message.reply_text("Hawww! Koi question hi nahi diya? Quiz cancel ho gaya 🥺💔")
        return ConversationHandler.END

    # Timer pucho last me
    await update.message.reply_text(
        f"Yayyy! **{len(questions)} Questions** ready ho gaye! 🥳🎉\n\n"
        "Bas aakhli cheez bata do — har sawal ke liye kitna **Timer (Seconds)** lagau? ⏰🍼\n"
        "(Jaise: 10, 15, 20, ya 30 seconds likh kar bhejo na)",
        parse_mode=ParseMode.MARKDOWN
    )
    return TIMER


async def newquiz_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Timer set karke quiz save karna (last step)"""
    text = update.message.text.strip()
    timer = int(text) if text.isdigit() and 5 <= int(text) <= 300 else config.DEFAULT_QUESTION_TIMER
    context.user_data["timer"] = timer

    questions = context.user_data.get("questions", [])
    title = context.user_data.get("title", "Untitled Quiz")
    user = update.effective_user
    creator_name = user.first_name or user.username or "User"

    quiz_id = await db.create_quiz(
        creator_id=user.id,
        title=title,
        questions=questions,
        timer=timer,
        creator_name=creator_name
    )

    await send_quiz_card(update.effective_chat.id, quiz_id, title, questions, timer, creator_name, context)
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Hawww! Cancel kar diya? Main katti ho gayi abhi 🥺💔")
    return ConversationHandler.END


# ---------------------- BULK TEXT / FILE PARSER ----------------------

async def handle_text_or_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User ke text ya .txt file se directly quiz banana (sirf Private chat me!)"""
    # Group me galti se text/file aane par quiz nahi banega
    if update.effective_chat.type != "private":
        return

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

    await send_quiz_card(update.effective_chat.id, quiz_id, title, questions, config.DEFAULT_QUESTION_TIMER, user.first_name or user.username or "User", context)


# ---------------------- QUIZ INFO CARD ----------------------

async def send_quiz_card(chat_id, quiz_id, title, questions, timer, creator_name, context):
    """Sundar Quiz Info Card with Start, Group, Share buttons"""
    bot_username = (await context.bot.get_me()).username
    total_q = len(questions) if isinstance(questions, list) else 0

    card_text = (
        f"📋 **Mela Pyala Quiz Card** 🎀🧸\n\n"
        f"📚  Naam: **{title}**\n"
        f"🔢  Total Sawal: **{total_q}**\n"
        f"⏱️  Timer: **{timer}s** har sawal ke liye\n"
        f"🆔  Quiz ID: `{quiz_id}`\n"
        f"💰  Type: **Free Sabke Liye** 💖\n"
        f"👤  Banane Wale: **{creator_name}** 🍼✨\n\n"
        f"Khelna hai toh neeche button dabao na! 👇🥰"
    )

    keyboard = [
        [InlineKeyboardButton("🎯 Khelna Shuru Karo ▶️", callback_data=f"sq_{quiz_id}")],
        [InlineKeyboardButton("🚀 Group Me Khelo ▶️", url=f"https://t.me/{bot_username}?startgroup=play_{quiz_id}")],
        [InlineKeyboardButton("🔗 Friends Ko Bhejo", switch_inline_query=f"play_{quiz_id}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.send_message(
        chat_id=chat_id,
        text=card_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )


# ---------------------- QUIZ EDIT SYSTEM ----------------------

async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/edit QUIZID - Quiz edit menu open karna (sirf Private chat me)"""
    if update.effective_chat.type != "private":
        bot_username = (await context.bot.get_me()).username
        quiz_id = context.args[0].strip() if context.args else ""
        link = f"https://t.me/{bot_username}?start=edit_{quiz_id}" if quiz_id else f"https://t.me/{bot_username}"
        keyboard = [[InlineKeyboardButton("✏️ Private Me Edit Karein 🎀", url=link)]]
        await update.message.reply_text(
            "Arey re! 🥺 Quiz edit group me nahi karte ji! Mujhe **Private (DM) me /edit bhejo na**! 🧸💖",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END

    if not context.args or not context.args[0].strip():
        await update.message.reply_text("Usage: `/edit QUIZ_ID`", parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END

    quiz_id = context.args[0].strip()
    quiz = await db.get_quiz(quiz_id)

    if not quiz:
        await update.message.reply_text("❌ Quiz ID nahi mili.")
        return ConversationHandler.END

    context.user_data["edit_quiz_id"] = quiz_id
    msg = await send_edit_menu_msg(update.effective_chat.id, quiz, context)
    context.user_data["edit_menu_msg_id"] = msg.message_id
    return EDIT_MENU


def build_edit_menu_text(quiz, status_line=""):
    """Edit menu ka text build karna"""
    quiz_id = quiz.get("quiz_id", "?")
    title = quiz.get("title", "Quiz")
    timer = quiz.get("timer_seconds", 20)
    questions = quiz.get("questions", [])

    text = f"✏️ **Mela Quiz Edit Menu** 🎀🧸\n\n"
    if status_line:
        text += f"{status_line}\n\n"
    text += (
        f"📌 **Naam:** {title}\n"
        f"🔢 **Total Sawal:** {len(questions)}\n"
        f"⏱️ **Timer:** {timer}s\n"
        f"🆔 **ID:** `{quiz_id}`\n\n"
        f"Batao aapke liye kya badlu? 🥺👉👈"
    )
    return text


def build_edit_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Naam Badlo", callback_data="edit_name"),
         InlineKeyboardButton("⏱️ Time Badlo", callback_data="edit_timer")],
        [InlineKeyboardButton("➕ Sawal Jodo", callback_data="edit_add_q"),
         InlineKeyboardButton("🗑️ Sawal Hatao", callback_data="edit_remove_q")],
        [InlineKeyboardButton("📄 .txt File Lo", callback_data="edit_export_txt")],
        [InlineKeyboardButton("✅ Done (Masti Save Karo)", callback_data="edit_done")],
    ])


async def send_edit_menu_msg(chat_id, quiz, context, status_line=""):
    """Naya edit menu message bhejna"""
    return await context.bot.send_message(
        chat_id=chat_id,
        text=build_edit_menu_text(quiz, status_line),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=build_edit_keyboard()
    )


async def update_edit_menu(chat_id, msg_id, quiz, context, status_line=""):
    """Existing edit menu message ko update karna (naya message nahi)"""
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=build_edit_menu_text(quiz, status_line),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_edit_keyboard()
        )
    except Exception:
        pass


async def edit_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit menu ke buttons"""
    query = update.callback_query
    await query.answer()
    data = query.data
    quiz_id = context.user_data.get("edit_quiz_id")

    if not quiz_id:
        await query.message.edit_text("❌ Session expire. `/edit QUIZ_ID` dobara chalayein.")
        return ConversationHandler.END

    if data == "edit_name":
        await query.message.edit_text(
            "📝 **Naya Quiz Name bhejiye:**",
            parse_mode=ParseMode.MARKDOWN
        )
        return EDIT_NAME_INPUT

    elif data == "edit_timer":
        await query.message.edit_text(
            "⏱️ **Naya Timer (seconds) bhejiye:**\n(5 se 300 ke beech)",
            parse_mode=ParseMode.MARKDOWN
        )
        return EDIT_TIMER_INPUT

    elif data == "edit_add_q":
        await query.message.edit_text(
            "➕ **Questions bhejiye** (text paste ya .txt file)\n\nJab ho jaye `/done` dabayein.",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data["edit_new_questions"] = []
        return EDIT_ADD_Q_INPUT

    elif data == "edit_remove_q":
        quiz = await db.get_quiz(quiz_id)
        questions = quiz.get("questions", [])
        if not questions:
            await update_edit_menu(query.message.chat_id, query.message.message_id, quiz, context, "⚠️ Koi question nahi hai")
            return EDIT_MENU

        q_list = ""
        for i, q in enumerate(questions[:30], 1):
            q_text = (q.get("question_text") or q.get("question", ""))[:50]
            q_list += f"`{i}.` {q_text}...\n"

        await query.message.edit_text(
            f"🗑️ **Kaunsa hatana hai?**\n\n{q_list}\n"
            f"Number bhejiye: `3` ya `1,3,5` ya `2-5`",
            parse_mode=ParseMode.MARKDOWN
        )
        return EDIT_REMOVE_Q_INPUT

    elif data == "edit_export_txt":
        quiz = await db.get_quiz(quiz_id)
        questions = quiz.get("questions", [])
        if not questions:
            await update_edit_menu(query.message.chat_id, query.message.message_id, quiz, context, "⚠️ Quiz khali hai")
            return EDIT_MENU

        txt = ""
        for q in questions:
            q_text = q.get("question_text") or q.get("question", "")
            options = q.get("options", [])
            correct_idx = q.get("correct_option_id", q.get("correct_option_index", 0))
            explanation = q.get("explanation", "")
            txt += f"{q_text}\n"
            for j, opt in enumerate(options):
                txt += f"{opt}{' ✅' if j == correct_idx else ''}\n"
            if explanation:
                txt += f"Ex:- {explanation}\n"
            txt += "\n"

        bio = io.BytesIO(txt.encode("utf-8"))
        bio.name = f"quiz_{quiz_id}.txt"
        await context.bot.send_document(chat_id=query.message.chat_id, document=bio,
            caption=f"📄 {quiz.get('title', 'Quiz')} ({len(questions)} Qs)")

        await update_edit_menu(query.message.chat_id, query.message.message_id, quiz, context, "✅ File export ho gayi")
        return EDIT_MENU

    elif data == "edit_done":
        quiz = await db.get_quiz(quiz_id)
        title = quiz.get("title", "Quiz")
        timer = quiz.get("timer_seconds", 20)
        questions = quiz.get("questions", [])

        await query.message.edit_text(
            f"Awwww! Saare changes save ho gaye ji! 💖🧸\n\n"
            f"📌 **Naam:** {title}\n"
            f"🔢 **Questions:** {len(questions)}\n"
            f"⏱️ **Timer:** {timer}s\n"
            f"🆔 **ID:** `{quiz_id}`\n\n"
            f"👉 Masti shuru karo: `/play_{quiz_id}` 🥳🎉",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data.clear()
        return ConversationHandler.END


async def edit_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text.strip()
    quiz_id = context.user_data.get("edit_quiz_id")
    chat_id = update.effective_chat.id

    await db.update_quiz_title(quiz_id, new_name)

    # User ka message delete karo (clean rakhne ke liye)
    try:
        await update.message.delete()
    except Exception:
        pass

    quiz = await db.get_quiz(quiz_id)
    context.user_data["edit_quiz"] = quiz
    msg = await send_edit_menu_msg(chat_id, quiz, context, f"✅ Name changed: {new_name}")
    context.user_data["edit_menu_msg_id"] = msg.message_id
    return EDIT_MENU


async def edit_timer_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    quiz_id = context.user_data.get("edit_quiz_id")
    chat_id = update.effective_chat.id

    if not text.isdigit() or not (5 <= int(text) <= 300):
        await update.message.reply_text("❌ 5 se 300 ke beech number dalein:")
        return EDIT_TIMER_INPUT

    new_timer = int(text)
    await db.update_quiz_timer(quiz_id, new_timer)

    try:
        await update.message.delete()
    except Exception:
        pass

    quiz = await db.get_quiz(quiz_id)
    msg = await send_edit_menu_msg(chat_id, quiz, context, f"✅ Timer changed: {new_timer}s")
    context.user_data["edit_menu_msg_id"] = msg.message_id
    return EDIT_MENU


async def edit_add_q_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and update.message.text.strip() == "/done":
        return await edit_add_q_done(update, context)

    raw_text = update.message.text or ""
    parsed = parse_questions_from_text(raw_text) if raw_text else []

    if parsed:
        context.user_data.setdefault("edit_new_questions", []).extend(parsed)
        total = len(context.user_data["edit_new_questions"])
        await update.message.reply_text(f"✅ {len(parsed)} Qs added (Total new: {total}). Aur bhejiye ya `/done`")
    return EDIT_ADD_Q_INPUT


async def edit_add_q_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if doc.file_name and doc.file_name.lower().endswith((".txt", ".text")):
        file = await doc.get_file()
        byte_content = await file.download_as_bytearray()
        raw_text = byte_content.decode("utf-8", errors="ignore")
        parsed = parse_questions_from_text(raw_text)
        if parsed:
            context.user_data.setdefault("edit_new_questions", []).extend(parsed)
            total = len(context.user_data["edit_new_questions"])
            await update.message.reply_text(f"✅ File se {len(parsed)} Qs added (Total: {total}). `/done`")
    return EDIT_ADD_Q_INPUT


async def edit_add_q_done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await edit_add_q_done(update, context)


async def edit_add_q_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    quiz_id = context.user_data.get("edit_quiz_id")
    new_qs = context.user_data.get("edit_new_questions", [])
    chat_id = update.effective_chat.id

    status = "⚠️ Koi naya question nahi mila"
    if new_qs:
        quiz = await db.get_quiz(quiz_id)
        existing = quiz.get("questions", [])
        all_q = existing + new_qs
        await db.update_quiz_questions(quiz_id, all_q)
        status = f"✅ {len(new_qs)} questions add huye (Total: {len(all_q)})"

    context.user_data.pop("edit_new_questions", None)
    quiz = await db.get_quiz(quiz_id)
    msg = await send_edit_menu_msg(chat_id, quiz, context, status)
    context.user_data["edit_menu_msg_id"] = msg.message_id
    return EDIT_MENU


async def edit_remove_q_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    quiz_id = context.user_data.get("edit_quiz_id")
    chat_id = update.effective_chat.id

    quiz = await db.get_quiz(quiz_id)
    questions = quiz.get("questions", [])
    total = len(questions)

    to_remove = set()
    for part in text.replace(" ", "").split(","):
        if "-" in part:
            try:
                s, e = part.split("-", 1)
                for n in range(int(s), int(e) + 1):
                    if 1 <= n <= total:
                        to_remove.add(n - 1)
            except ValueError:
                pass
        elif part.isdigit():
            n = int(part)
            if 1 <= n <= total:
                to_remove.add(n - 1)

    if not to_remove:
        await update.message.reply_text("❌ Valid number dalein ya `/cancel`")
        return EDIT_REMOVE_Q_INPUT

    new_questions = [q for i, q in enumerate(questions) if i not in to_remove]
    await db.update_quiz_questions(quiz_id, new_questions)

    try:
        await update.message.delete()
    except Exception:
        pass

    quiz = await db.get_quiz(quiz_id)
    msg = await send_edit_menu_msg(chat_id, quiz, context, f"✅ {len(to_remove)} question(s) removed")
    context.user_data["edit_menu_msg_id"] = msg.message_id
    return EDIT_MENU


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
        "scores": {},           # user_id -> correct count
        "wrong": {},            # user_id -> wrong count
        "user_names": {},       # user_id -> first_name
        "start_time": {},       # user_id -> first answer timestamp
        "last_answer_time": {}, # user_id -> last answer timestamp
        "active_poll_id": None,
    }

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"Yayyy! Mela Quiz Shuru Ho Raha Hai! 🎯🥳🍼\n\n"
            f"📖 **{quiz['title']}**\n"
            f"🔢 **Questions:** {len(questions)}\n"
            f"⏱️ **Timer:** {timer}s har sawal ke liye\n\n"
            f"Jaldi jaldi tayyar ho jao sab... 3... 2... 1... Go! 🏃‍♀️💨✨"
        ),
        parse_mode=ParseMode.MARKDOWN
    )
    await asyncio.sleep(2)
    await send_next_question(chat_id, context)


async def send_next_question(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        session = active_sessions.get(chat_id)
        if not session:
            return

        idx = session["current_index"]
        questions = session["questions"]

        if idx >= len(questions):
            await finish_quiz_session(chat_id, context)
            return

        q = questions[idx]
        if isinstance(q, str):
            try:
                import json
                q = json.loads(q)
            except Exception:
                q = {"question_text": q, "options": ["A", "B"], "correct_option_id": 0}

        timer = session.get("timer", 20)

        # Get question text and options
        q_text = str(q.get("question_text") or q.get("question") or "Question")
        raw_options = q.get("options", [])
        if isinstance(raw_options, str):
            try:
                import json
                raw_options = json.loads(raw_options)
            except Exception:
                raw_options = [raw_options]

        options = [str(opt) for opt in raw_options]

        # Safe correct index parsing
        raw_correct = q.get("correct_option_id")
        if raw_correct is None:
            raw_correct = q.get("correct_option_index", 0)
        try:
            correct_idx = int(raw_correct)
        except (ValueError, TypeError):
            correct_idx = 0

        explanation = str(q.get("explanation") or "")

        # Clean explanation if accidentally saved inside options in older quizzes
        filtered_options = []
        for opt in options:
            if is_exp_line(opt):
                if not explanation:
                    explanation = extract_exp_text(opt)
            else:
                filtered_options.append(opt)
        options = filtered_options

        # Ensure correct_idx is within bounds
        if not (0 <= correct_idx < len(options)):
            correct_idx = 0

        # Native Telegram Quiz Poll only (no image card)
        total_q = len(questions)
        poll_question = f"[{idx+1}/{total_q}] {q_text[:240]}"
        
        # A), B), C), D) prefix add karna
        option_labels = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
        poll_options = []
        for i, opt in enumerate(options[:10]):
            clean_opt = re.sub(r'^(?:[A-Za-z0-9][\.\)]|\([A-Za-z0-9]\))\s*', '', opt).strip()
            label = option_labels[i] if i < len(option_labels) else str(i+1)
            poll_options.append(f"{label}) {clean_opt}"[:100])

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
    except Exception as e:
        import traceback
        err_detail = traceback.format_exc()
        logger.error(f"Error in send_next_question: {err_detail}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Arey re! Sawal bhejne me dikkat aa gayi 🥺:\n`{e}`\n\n*(Agar group me ho toh check karo ki bot ko **Send Polls** ki permission hai na!)*",
            parse_mode=ParseMode.MARKDOWN
        )
        active_sessions.pop(chat_id, None)


async def quiz_timer_callback(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    await send_next_question(chat_id, context)


async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    user = answer.user
    selected_option = answer.option_ids[0] if answer.option_ids else None
    now = time.time()

    for chat_id, session in active_sessions.items():
        if session.get("active_poll_id") == answer.poll_id:
            curr_idx = session["current_index"] - 1
            if 0 <= curr_idx < len(session["questions"]):
                q = session["questions"][curr_idx]
                correct_idx = q.get("correct_option_id") if "correct_option_id" in q else q.get("correct_option_index", 0)
                
                # User name save karo
                session["user_names"][user.id] = user.first_name or user.username or "User"
                
                # First answer time track karo
                if user.id not in session["start_time"]:
                    session["start_time"][user.id] = now
                session["last_answer_time"][user.id] = now
                
                if selected_option == correct_idx:
                    session["scores"][user.id] = session["scores"].get(user.id, 0) + 1
                else:
                    session["wrong"][user.id] = session["wrong"].get(user.id, 0) + 1
                
                await db.register_user(user.id, user.username, user.first_name)
            break


async def finish_quiz_session(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    session = active_sessions.pop(chat_id, None)
    if not session:
        return

    scores = session["scores"]
    wrong = session["wrong"]
    user_names = session["user_names"]
    start_times = session["start_time"]
    last_times = session["last_answer_time"]
    quiz_id = session["quiz_id"]
    total_q = len(session["questions"])
    title = session["title"]

    # Save scores to DB
    for uid, sc in scores.items():
        await db.record_score(quiz_id, chat_id, uid, sc, total_q)

    # All users who participated
    all_users = set(list(scores.keys()) + list(wrong.keys()))

    if not all_users:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🏁 **Quiz Completed!**\n\n📖 {title}\n\nKisi ne bhi answer nahi diya.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Build detailed stats per user
    user_stats = []
    for uid in all_users:
        correct = scores.get(uid, 0)
        wr = wrong.get(uid, 0)
        attempted = correct + wr
        skipped = total_q - attempted
        score_val = float(correct)  # Can add negative marking here
        name = user_names.get(uid, "User")
        
        # Time calculation
        if uid in start_times and uid in last_times:
            elapsed = last_times[uid] - start_times[uid]
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            time_str = f"{mins}m {secs}s"
        else:
            time_str = "N/A"
            elapsed = 99999
        
        accuracy = (correct / total_q * 100) if total_q > 0 else 0

        user_stats.append({
            "uid": uid,
            "name": name,
            "correct": correct,
            "wrong": wr,
            "skipped": skipped,
            "score": score_val,
            "time_str": time_str,
            "elapsed": elapsed,
            "accuracy": accuracy,
        })

    # Sort by score (desc), then by time (asc)
    user_stats.sort(key=lambda x: (-x["score"], x["elapsed"]))

    # Build result card
    medals = ["🥇", "🥈", "🥉"]
    result_text = (
        f"🏆 **Yayyy! Mela Quiz Khatam Ho Gaya!** 🥳🎉\n\n"
        f"📖  **{title}**\n\n"
        f"✨ **Dekho Kisne Kitna Kamaal Kiya:** 🍼\n"
        f"{'─' * 30}\n"
    )

    for rank, s in enumerate(user_stats[:15], start=1):
        medal = medals[rank - 1] if rank <= len(medals) else f"{rank}."
        
        # Accuracy bar
        acc = s['accuracy']
        if acc >= 80:
            acc_emoji = "🌟"
        elif acc >= 50:
            acc_emoji = "✨"
        else:
            acc_emoji = "🐥"

        result_text += (
            f"{medal} **{s['name']}** | "
            f"✅ {s['correct']} | "
            f"❌ {s['wrong']} | "
            f"⏭ {s['skipped']} | "
            f"🎯 {s['score']:.0f} | "
            f"⏱ {s['time_str']} | "
            f"{acc_emoji} {s['accuracy']:.1f}%\n"
            f"{'─' * 30}\n"
        )

    await context.bot.send_message(
        chat_id=chat_id,
        text=result_text,
        parse_mode=ParseMode.MARKDOWN
    )


# ---------------------- LEADERBOARD & ADMIN ----------------------

async def is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check karo ki user group ka admin/owner hai ya nahi"""
    chat = update.effective_chat
    user_id = update.effective_user.id

    # Private chat me sab allowed
    if chat.type == "private":
        return True

    # Bot admin list me hai
    if user_id in config.ADMIN_IDS:
        return True

    # Group admin/owner check
    try:
        member = await context.bot.get_chat_member(chat.id, user_id)
        return member.status in ["creator", "administrator"]
    except Exception:
        return False


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stop - Chalu quiz ko turant band karna (sirf admin)"""
    if not await is_group_admin(update, context):
        await update.message.reply_text("Hawww! Sirf group ke admin bhaiya/didi hi /stop bol sakte hain 🥺")
        return

    chat_id = update.effective_chat.id
    session = active_sessions.get(chat_id)

    if not session:
        await update.message.reply_text("Arey re! Is group me koi quiz chal hi nahi raha hai 🥺")
        return

    # Cancel all scheduled timer jobs for this quiz
    current_jobs = context.job_queue.get_jobs_by_name(f"qt_{chat_id}")
    for job in context.job_queue.jobs():
        if job.name and job.name.startswith(f"qt_{chat_id}_"):
            job.schedule_removal()

    await update.message.reply_text("🛑 **Arey re! Quiz rok diya gaya! Abhi sabse katti!** 🥺", parse_mode=ParseMode.MARKDOWN)
    await finish_quiz_session(chat_id, context)


async def fast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/fast 10 - Timer kam karna (sirf admin)"""
    if not await is_group_admin(update, context):
        await update.message.reply_text("Hawww! Sirf admin hi timer fast kar sakte hain 🥺")
        return

    chat_id = update.effective_chat.id
    session = active_sessions.get(chat_id)

    if not session:
        await update.message.reply_text("Arey re! Koi quiz chal hi nahi raha hai 🥺")
        return

    # Parse seconds from command
    new_timer = config.DEFAULT_QUESTION_TIMER
    if context.args and context.args[0].isdigit():
        new_timer = max(5, int(context.args[0]))  # Minimum 5 seconds
    else:
        new_timer = max(5, session["timer"] - 5)  # Default: 5 sec kam

    session["timer"] = new_timer
    await update.message.reply_text(
        f"⚡ **Hehe! Timer fast-fast kar diya!** 🏎️💨\nAb har sawal ka timer: **{new_timer}s**",
        parse_mode=ParseMode.MARKDOWN
    )


async def slow_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/slow 30 - Timer badhaana (sirf admin)"""
    if not await is_group_admin(update, context):
        await update.message.reply_text("Hawww! Sirf admin hi timer slow kar sakte hain 🥺")
        return

    chat_id = update.effective_chat.id
    session = active_sessions.get(chat_id)

    if not session:
        await update.message.reply_text("Arey re! Koi quiz chal hi nahi raha hai 🥺")
        return

    new_timer = config.DEFAULT_QUESTION_TIMER
    if context.args and context.args[0].isdigit():
        new_timer = min(300, int(context.args[0]))  # Maximum 5 minutes
    else:
        new_timer = min(300, session["timer"] + 5)  # Default: 5 sec zyada

    session["timer"] = new_timer
    await update.message.reply_text(
        f"🐢 **Aaram-aaram se khelo ab!** 🍼\nTimer slow kar diya: **{new_timer}s**",
        parse_mode=ParseMode.MARKDOWN
    )


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

    # Build Application with increased timeouts for Render free tier
    request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=40.0,
        write_timeout=40.0,
        pool_timeout=20.0,
    )
    app = Application.builder().token(config.BOT_TOKEN).request(request).post_init(post_init).build()

    # /newquiz Conversation Handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("newquiz", newquiz_start),
            CommandHandler("start", start_command),
        ],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, newquiz_title)],
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
            TIMER: [MessageHandler(filters.TEXT & ~filters.COMMAND, newquiz_timer)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )

    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("quizzes", list_quizzes_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("stop", stop_command))
    app.add_handler(CommandHandler("fast", fast_command))
    app.add_handler(CommandHandler("slow", slow_command))
    app.add_handler(conv_handler)

    # /edit Conversation Handler
    edit_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("edit", edit_command)],
        states={
            EDIT_MENU: [
                CallbackQueryHandler(edit_menu_callback, pattern="^edit_"),
            ],
            EDIT_NAME_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name_input),
            ],
            EDIT_TIMER_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_timer_input),
            ],
            EDIT_ADD_Q_INPUT: [
                CommandHandler("done", edit_add_q_done_cmd),
                MessageHandler(filters.Document.ALL, edit_add_q_file),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_add_q_text),
            ],
            EDIT_REMOVE_Q_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_remove_q_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    app.add_handler(edit_conv_handler)

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
