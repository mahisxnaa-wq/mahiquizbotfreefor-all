# Telegram Quiz Bot 🧠

Ek powerful aur modern Telegram Quiz Bot jisme interactive quiz creation, bulk import, image cards, native quiz polls aur live leaderboard features shamil hain.

---

## 📁 Project Structure

* `bot.py` - Main bot application logic aur command handlers
* `config.py` - Bot tokens, Admin IDs aur settings
* `database.py` - SQLite database queries (Users, Quizzes, Questions, Scores)
* `parser.py` - Text aur .txt files se questions extract karne ke liye
* `image_generator.py` - Pillow ke sath attractive question image cards generate karne ke liye
* `sample_quiz.txt` - Testing ke liye sample questions file
* `requirements.txt` - Python dependencies

---

## 🚀 Setup & Run Kaise Karein

### 1. Telegram Bot Token Prapt Karein:
1. Telegram open karein aur search karein: `@BotFather`
2. Command bhejiye: `/newbot`
3. Bot ka naam aur username set karein (e.g. `MyQuizMasterBot`).
4. `@BotFather` aapko ek **API Token** dega.

### 2. Dependencies Install Karein:
Terminal ya Command Prompt me yeh command chalayein:
```bash
cd C:\Users\HP\.gemini\antigravity\scratch\telegram_quiz_bot
pip install -r requirements.txt
```

### 3. Config Setup:
`config.py` file open karein aur apna token paste karein:
```python
BOT_TOKEN = "Aapka_Telegram_Token_Yahan"
```
*(Ya fir ek `.env` file banakar usme `BOT_TOKEN=...` save kar sakte hain)*

### 4. Bot Ko Run Karein:
```bash
python bot.py
```

---

## 🎮 Features aur Commands

* `/start` - Main menu aur welcome message
* `/newquiz` - Step-by-step naya quiz create karein
* `/quizzes` - Available quizzes list dekhein aur play karein
* `/leaderboard` - Global Top rankers dekhein
* `/broadcast <message>` - Sabhi registered users ko alert bhejein (Admin only)

### Bulk Questions Upload:
Aap direct bot ko chat me aisa text ya `.txt` file bhej sakte hain:
```text
Q1. Bharat ki rajdhani kya hai?
A) Mumbai
B) Kolkata
C) New Delhi
D) Chennai
Ans: C
Exp: New Delhi 1911 me bani thi.
```
Bot automatically ise detect karke naya quiz create kar dega!
