import os
import asyncio
from datetime import datetime
from aiohttp import web
from telegram import (
    Update,
    ChatMember,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PollAnswerHandler,
    ChatMemberHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
import config
from db import (
    init_db,
    create_new_quiz,
    add_question_to_quiz,
    set_quiz_timer,
    get_quiz_by_id,
    get_user_quizzes,
    save_group,
    remove_group,
    get_all_groups,
    update_score,
    get_leaderboard,
    add_general_question,
    get_random_general_question,
    get_system_stats,
)
from parser import parse_and_save_quiz_text
from question_image import generate_quiz_image

# Conversation States for /newquiz
TITLE, ADD_QUESTIONS, CHOOSE_TIMER = range(3)

# Global trackers
RUNNING_SESSIONS = {}  # chat_id: session_state
ACTIVE_POLLS = {}      # poll_id: poll_info

# --- 1. /newquiz Workflow (Interactive Quiz Creator) ---
async def newquiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        bot_user = (await context.bot.get_me()).username
        await update.message.reply_text(f"⚠️ Naya quiz create karne ke liye mujhe **Personal Chat** me message karein: @{bot_user}")
        return ConversationHandler.END

    await update.message.reply_text(
        "📝 **Naya Quiz Banayein!**\n\n"
        "Apne Quiz ka **Title / Naam** bhejein (Jaise: *Lucent GK Test 1* ya *SSC Math Speed Quiz*):"
    )
    return TITLE

async def newquiz_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    creator_id = update.effective_user.id
    
    quiz_id = create_new_quiz(title, creator_id)
    context.user_data["current_quiz_id"] = quiz_id
    context.user_data["q_count"] = 0

    await update.message.reply_text(
        f"✅ Quiz Name: **{title}**\n\n"
        "📌 **Ab Questions Bhejein:**\n"
        "Attachment 📎 icon par click karke **Poll** chunein, **Quiz Mode ON** karein aur question options ke saath bhejte jayein.\n\n"
        "💡 *Jab sabhi sawaal add ho jayein, toh `/done` type karein.*",
        parse_mode="Markdown"
    )
    return ADD_QUESTIONS

async def newquiz_question_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    quiz_id = context.user_data.get("current_quiz_id")

    if msg.poll:
        poll = msg.poll
        if poll.type != "quiz":
            await msg.reply_text("⚠️ Kripya **Quiz Mode** wala poll bhejein (jisme correct option par tick hota hai)!")
            return ADD_QUESTIONS

        q_text = poll.question
        options = [opt.text for opt in poll.options]
        correct_id = poll.correct_option_id
        exp = poll.explanation or "Sahi jawab!"

        add_question_to_quiz(quiz_id, q_text, options, correct_id, exp)
        context.user_data["q_count"] += 1
        count = context.user_data["q_count"]

        await msg.reply_text(f"✅ Sawaal #{count} save ho gaya! Agla bhejein ya `/done` likhein.")
        return ADD_QUESTIONS
    else:
        await msg.reply_text("Kripya Poll/Quiz ke roop me sawaal bhejein, ya khatam karne ke liye `/done` likhein.")
        return ADD_QUESTIONS

async def newquiz_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = context.user_data.get("q_count", 0)
    if count == 0:
        await update.message.reply_text("⚠️ Kam se kam 1 question add karein!")
        return ADD_QUESTIONS

    keyboard = [
        [
            InlineKeyboardButton("10 Sec", callback_data="time_10"),
            InlineKeyboardButton("15 Sec", callback_data="time_15"),
            InlineKeyboardButton("30 Sec", callback_data="time_30"),
        ],
        [
            InlineKeyboardButton("45 Sec", callback_data="time_45"),
            InlineKeyboardButton("60 Sec", callback_data="time_60"),
        ]
    ]
    await update.message.reply_text(
        f"🎉 Kul **{count} Sawaal** jud gaye!\n\n⏱ Har sawaal ke liye kitna time dena hai?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CHOOSE_TIMER

async def newquiz_timer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    time_sec = int(query.data.split("_")[1])
    quiz_id = context.user_data.get("current_quiz_id")
    set_quiz_timer(quiz_id, time_sec)
    
    bot_username = (await context.bot.get_me()).username
    share_url = f"https://t.me/{bot_username}?startgroup=quiz_{quiz_id}"

    keyboard = [[InlineKeyboardButton("➕ Add & Start In Group", url=share_url)]]

    await query.edit_message_text(
        f"🎯 **Aapka Quiz Ban Kar Tayar Hai!**\n\n"
        f"🆔 **Quiz ID:** `{quiz_id}`\n"
        f"⏱ **Time Limit:** `{time_sec} Seconds per question`\n\n"
        f"👉 Niche diye button se is quiz ko kisi bhi Study Group me chalu karein!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Quiz creation cancel kar diya gaya.")
    return ConversationHandler.END

# --- 2. Group Quiz Runner (Live Timer & Auto-Next) ---
async def startquiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type == "private":
        await update.message.reply_text("Group me jaakar `/startquiz <quiz_id>` likhein!")
        return

    if not context.args:
        await update.message.reply_text("Kripya Quiz ID daalein! Jaise: `/startquiz 1`")
        return

    try:
        quiz_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Galat ID! Number daalein.")
        return

    if chat_id in RUNNING_SESSIONS:
        await update.message.reply_text("⚠️ Is group me pehle se ek quiz chal raha hai! Pehle `/stopquiz` karein.")
        return

    asyncio.create_task(run_quiz_session(chat_id, quiz_id, context))

async def run_quiz_session(chat_id: int, quiz_id: int, context: ContextTypes.DEFAULT_TYPE):
    quiz_meta, questions = get_quiz_by_id(quiz_id)
    if not quiz_meta or not questions:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Ye Quiz ID exist nahi karta!")
        return

    time_limit = quiz_meta["time"]
    RUNNING_SESSIONS[chat_id] = {"active": True, "scores": {}}

    # 3.. 2.. 1.. Countdown
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🏁 **Quiz Shuru Hone Wala Hai!**\n\n📖 **Title:** {quiz_meta['title']}\n🔢 **Questions:** {len(questions)}\n⏱ **Time per Q:** {time_limit}s\n\n*Get Ready in 3... 2... 1...*",
        parse_mode="Markdown"
    )
    await asyncio.sleep(4)

    for idx, q in enumerate(questions, 1):
        if not RUNNING_SESSIONS.get(chat_id, {}).get("active"):
            break

        poll_msg = await context.bot.send_poll(
            chat_id=chat_id,
            question=f"[{idx}/{len(questions)}] {q['question']}",
            options=q["options"],
            type="quiz",
            correct_option_id=q["correct_id"],
            explanation=q["explanation"],
            open_period=time_limit,
            is_anonymous=False
        )

        ACTIVE_POLLS[poll_msg.poll.id] = {
            "correct_id": q["correct_id"],
            "chat_id": chat_id
        }

        # Auto wait for the timer to expire
        await asyncio.sleep(time_limit + 2)

    # Winner Declaration
    session = RUNNING_SESSIONS.pop(chat_id, None)
    if session and session["scores"]:
        sorted_scores = sorted(session["scores"].items(), key=lambda x: x[1], reverse=True)
        board = f"🏆 **QUIZ FINISHED - LEADERBOARD** 🏆\n\n📖 **{quiz_meta['title']}**\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (uname, scr) in enumerate(sorted_scores[:10], 1):
            badge = medals[i-1] if i <= 3 else f"{i}."
            board += f"{badge} **{uname}** : {scr} Points\n"
        await context.bot.send_message(chat_id=chat_id, text=board, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=chat_id, text=f"🏁 **Quiz '{quiz_meta['title']}' Samapt Hua!**")

async def stopquiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in RUNNING_SESSIONS:
        RUNNING_SESSIONS[chat_id]["active"] = False
        await update.message.reply_text("🛑 Ongoing Quiz ko stop kar diya gaya hai.")
    else:
        await update.message.reply_text("Abhi koi quiz nahi chal raha hai.")

# --- 3. Photo Card Quiz Command (/quizimg) ---
async def quiz_img_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q_data = get_random_general_question()
    if not q_data:
        await update.message.reply_text("General question bank khali hai.")
        return

    q_text, a, b, c, d, correct_id, exp = q_data
    options = [a, b, c, d]

    img_stream = generate_quiz_image(q_text, options, "Live Quiz")
    await context.bot.send_photo(chat_id=chat_id, photo=img_stream, caption="🎯 Answer dene ke liye niche option chunein:")

    poll_msg = await context.bot.send_poll(
        chat_id=chat_id,
        question="Sahi uttar chunein:",
        options=["Option A", "Option B", "Option C", "Option D"],
        type="quiz",
        correct_option_id=correct_id,
        explanation=exp,
        open_period=20,
        is_anonymous=False
    )
    ACTIVE_POLLS[poll_msg.poll.id] = {"correct_id": correct_id, "chat_id": chat_id}

# --- 4. Answer Handling & Leaderboard ---
async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    poll_id = ans.poll_id
    user = ans.user

    if poll_id in ACTIVE_POLLS and ans.option_ids:
        info = ACTIVE_POLLS[poll_id]
        if ans.option_ids[0] == info["correct_id"]:
            chat_id = info["chat_id"]
            uname = user.first_name or user.username or f"User_{user.id}"
            
            # Live session score
            if chat_id in RUNNING_SESSIONS:
                curr = RUNNING_SESSIONS[chat_id]["scores"].get(uname, 0)
                RUNNING_SESSIONS[chat_id]["scores"][uname] = curr + 1

            # Global score
            update_score(chat_id, user.id, uname, 1)

async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    top = get_leaderboard(chat_id, 10)
    if not top:
        await update.message.reply_text("🏆 Abhi koi points nahi hain! Quiz shuru karein.")
        return

    text = "🏆 **Group Study Leaderboard** 🏆\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, (uname, score) in enumerate(top, 1):
        badge = medals[i-1] if i <= 3 else f"{i}."
        text += f"{badge} **{uname}** : {score} pts\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# --- 5. Owner Alerts (Jab koi bot group me add kare) ---
async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result:
        return
    chat = result.chat
    actor = result.from_user
    was_m = result.old_chat_member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR]
    is_m = result.new_chat_member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR]

    if not was_m and is_m:
        actor_name = actor.first_name + (f" (@{actor.username})" if actor.username else "")
        save_group(chat.id, chat.title, actor_name, actor.id)
        if config.OWNER_ID:
            try:
                await context.bot.send_message(
                    chat_id=config.OWNER_ID,
                    text=(
                        "🎉 **Bot Naye Group Me Add Hua!**\n\n"
                        f"🏷 **Group:** `{chat.title}`\n"
                        f"🆔 **ID:** `{chat.id}`\n"
                        f"👤 **Added By:** {actor_name} (ID: `{actor.id}`)\n"
                        f"📅 `{datetime.now().strftime('%d-%m-%Y %H:%M')}`"
                    ),
                    parse_mode="Markdown"
                )
            except:
                pass
    elif was_m and not is_m:
        remove_group(chat.id)

# --- 6. Owner Commands (/stats, /groups) ---
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.OWNER_ID:
        return
    g, u, q = get_system_stats()
    text = (
        f"📊 **Master Control Panel Stats**\n\n"
        f"👥 Active Groups: **{g}**\n"
        f"🎮 Total Quiz Players: **{u}**\n"
        f"📚 Total Quizzes Created: **{q}**"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def groups_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.OWNER_ID:
        return
    groups = get_all_groups()
    if not groups:
        await update.message.reply_text("Koi group nahi mila.")
        return
    text = "📋 **Connected Groups List:**\n\n"
    for i, (title, cid, by_user, at) in enumerate(groups, 1):
        text += f"{i}. **{title}**\n   🆔 `{cid}`\n   👤 By: {by_user}\n   📅 `{at}`\n\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    # Deep-link se group me start hona
    if args and args[0].startswith("quiz_"):
        quiz_id = int(args[0].split("_")[1])
        if update.effective_chat.type in ["group", "supergroup"]:
            asyncio.create_task(run_quiz_session(update.effective_chat.id, quiz_id, context))
            return

    text = (
        "👋 **Namaste! Main Advanced Quiz Bot hoon!**\n\n"
        "✨ **Commands:**\n"
        "• `/newquiz` - Naya quiz create karein (DM me)\n"
        "• `/startquiz <id>` - Group me quiz start karein\n"
        "• `/quizimg` - Photo Quiz card bhejein\n"
        "• `/leaderboard` - Group rank check karein\n"
        "• `/stopquiz` - Ongoing quiz stop karein\n\n"
        "👥 *Mujhe kisi bhi group me add karein aur quiz khele!*"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# Render Web Keep-Alive Server
async def web_server():
    async def ping(r):
        return web.Response(text="Bot is running!")
    app = web.Application()
    app.router.add_get("/", ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()

async def main():
    init_db()
    
    # Preload sample questions agar database khali ho
    if not get_random_general_question():
        add_general_question("Bharat ka rashtriya phool (National Flower) konsa hai?", "Kamal (Lotus)", "Gulab", "Surajmukhi", "Genda", 0, "Lotus is National Flower of India")
        add_general_question("Computer me RAM ka pura naam kya hai?", "Random Access Memory", "Read Access Memory", "Run Auto Memory", "Real Action Memory", 0, "Random Access Memory is volatile")

    app = Application.builder().token(config.BOT_TOKEN).build()

    # /newquiz wizard
    conv = ConversationHandler(
        entry_points=[CommandHandler("newquiz", newquiz_start)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, newquiz_title)],
            ADD_QUESTIONS: [
                MessageHandler(filters.POLL, newquiz_question_received),
                CommandHandler("done", newquiz_done)
            ],
            CHOOSE_TIMER: [CallbackQueryHandler(newquiz_timer_callback, pattern="^time_")]
        },
        fallbacks=[CommandHandler("cancel", cancel_quiz)]
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("startquiz", startquiz_cmd))
    app.add_handler(CommandHandler("stopquiz", stopquiz_cmd))
    app.add_handler(CommandHandler("quizimg", quiz_img_cmd))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("groups", groups_cmd))
    app.add_handler(PollAnswerHandler(handle_poll_answer))
    app.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))

    # Keep alive port for Render
    await web_server()
    print("Bot is fully active and listening...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
