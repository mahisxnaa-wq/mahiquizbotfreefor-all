import sqlite3
import json
from datetime import datetime
from config import DB_NAME

def get_connection():
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = get_connection()
    c = conn.cursor()

    # 1. Groups Table (Kon kahan bot add kar raha hai)
    c.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            added_by_name TEXT,
            added_by_id INTEGER,
            joined_at TEXT
        )
    ''')

    # 2. Quizzes Table (User ke banaye hue custom quizzes)
    c.execute('''
        CREATE TABLE IF NOT EXISTS custom_quizzes (
            quiz_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            creator_id INTEGER,
            time_per_q INTEGER DEFAULT 15,
            created_at TEXT
        )
    ''')

    # 3. Questions Table (Har quiz ke andar ke questions)
    c.execute('''
        CREATE TABLE IF NOT EXISTS quiz_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER,
            question TEXT,
            options_json TEXT,
            correct_id INTEGER,
            explanation TEXT,
            FOREIGN KEY (quiz_id) REFERENCES custom_quizzes(quiz_id)
        )
    ''')

    # 4. Global & Group Leaderboard Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS scores (
            chat_id INTEGER,
            user_id INTEGER,
            username TEXT,
            score INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        )
    ''')

    # 5. Default General Question Bank
    c.execute('''
        CREATE TABLE IF NOT EXISTS general_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT,
            opt_a TEXT,
            opt_b TEXT,
            opt_c TEXT,
            opt_d TEXT,
            correct_opt INTEGER,
            explanation TEXT,
            category TEXT DEFAULT 'general'
        )
    ''')

    conn.commit()
    conn.close()

# --- Quiz Creation Methods ---
def create_new_quiz(title: str, creator_id: int, time_per_q: int = 15) -> int:
    conn = get_connection()
    c = conn.cursor()
    created_at = datetime.now().strftime("%d-%m-%Y %H:%M")
    c.execute('''
        INSERT INTO custom_quizzes (title, creator_id, time_per_q, created_at)
        VALUES (?, ?, ?, ?)
    ''', (title, creator_id, time_per_q, created_at))
    quiz_id = c.lastrowid
    conn.commit()
    conn.close()
    return quiz_id

def add_question_to_quiz(quiz_id: int, question: str, options: list, correct_id: int, explanation: str = ""):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO quiz_questions (quiz_id, question, options_json, correct_id, explanation)
        VALUES (?, ?, ?, ?, ?)
    ''', (quiz_id, question, json.dumps(options), correct_id, explanation))
    conn.commit()
    conn.close()

def set_quiz_timer(quiz_id: int, time_per_q: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute('UPDATE custom_quizzes SET time_per_q = ? WHERE quiz_id = ?', (time_per_q, quiz_id))
    conn.commit()
    conn.close()

def get_quiz_by_id(quiz_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT title, time_per_q FROM custom_quizzes WHERE quiz_id = ?', (quiz_id,))
    quiz = c.fetchone()
    if not quiz:
        conn.close()
        return None, []
    
    c.execute('SELECT question, options_json, correct_id, explanation FROM quiz_questions WHERE quiz_id = ?', (quiz_id,))
    rows = c.fetchall()
    questions = []
    for r in rows:
        questions.append({
            "question": r[0],
            "options": json.loads(r[1]),
            "correct_id": r[2],
            "explanation": r[3]
        })
    conn.close()
    return {"id": quiz_id, "title": quiz[0], "time": quiz[1]}, questions

def get_user_quizzes(user_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT quiz_id, title FROM custom_quizzes WHERE creator_id = ? ORDER BY quiz_id DESC', (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

# --- Group Tracking Methods ---
def save_group(chat_id: int, title: str, added_by_name: str, added_by_id: int):
    conn = get_connection()
    c = conn.cursor()
    joined_at = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    c.execute('''
        INSERT INTO groups (chat_id, title, added_by_name, added_by_id, joined_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            title = ?, added_by_name = ?, joined_at = ?
    ''', (chat_id, title, added_by_name, added_by_id, joined_at, title, added_by_name, joined_at))
    conn.commit()
    conn.close()

def remove_group(chat_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM groups WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

def get_all_groups():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT title, chat_id, added_by_name, joined_at FROM groups")
    rows = c.fetchall()
    conn.close()
    return rows

# --- Leaderboard Methods ---
def update_score(chat_id: int, user_id: int, username: str, points: int = 1):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO scores (chat_id, user_id, username, score)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
            score = score + ?, username = ?
    ''', (chat_id, user_id, username, points, points, username))
    conn.commit()
    conn.close()

def get_leaderboard(chat_id: int, limit: int = 10):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        SELECT username, score FROM scores
        WHERE chat_id = ?
        ORDER BY score DESC LIMIT ?
    ''', (chat_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows

# --- General Bank Methods ---
def add_general_question(q, a, b, c_opt, d, correct_id, explanation, cat="general"):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO general_questions (question, opt_a, opt_b, opt_c, opt_d, correct_opt, explanation, category)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (q, a, b, c_opt, d, correct_id, explanation, cat))
    conn.commit()
    conn.close()

def get_random_general_question():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT question, opt_a, opt_b, opt_c, opt_d, correct_opt, explanation FROM general_questions ORDER BY RANDOM() LIMIT 1")
    row = c.fetchone()
    conn.close()
    return row

def get_system_stats():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM groups")
    g_count = c.fetchone()[0]
    c.execute("SELECT COUNT(DISTINCT user_id) FROM scores")
    u_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM custom_quizzes")
    q_count = c.fetchone()[0]
    conn.close()
    return g_count, u_count, q_count
