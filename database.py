import aiosqlite
import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = "quiz_bot.db"):
        self.db_path = db_path

    async def init_db(self):
        """Database tables create karna"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS quizzes (
                    quiz_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    creator_id INTEGER,
                    title TEXT NOT NULL,
                    description TEXT,
                    timer_seconds INTEGER DEFAULT 20,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    question_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    quiz_id INTEGER,
                    question_text TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    correct_option_index INTEGER NOT NULL,
                    explanation TEXT,
                    FOREIGN KEY (quiz_id) REFERENCES quizzes(quiz_id) ON DELETE CASCADE
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    quiz_id INTEGER,
                    chat_id INTEGER,
                    user_id INTEGER,
                    score INTEGER DEFAULT 0,
                    total_questions INTEGER DEFAULT 0,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (quiz_id) REFERENCES quizzes(quiz_id)
                )
            """)
            await db.commit()
            logger.info("Database initialized successfully.")

    async def register_user(self, user_id: int, username: Optional[str], first_name: str):
        """User ko register ya update karna"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO users (user_id, username, first_name)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name
            """, (user_id, username, first_name))
            await db.commit()

    async def get_all_users(self) -> List[int]:
        """Broadcast ke liye sabhi user IDs retrieve karna"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT user_id FROM users") as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

    async def create_quiz(self, creator_id: int, title: str, description: str = "", timer: int = 20) -> int:
        """Naya quiz create karna aur quiz_id return karna"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO quizzes (creator_id, title, description, timer_seconds)
                VALUES (?, ?, ?, ?)
            """, (creator_id, title, description, timer))
            await db.commit()
            return cursor.lastrowid

    async def add_question(self, quiz_id: int, question_text: str, options: List[str], correct_idx: int, explanation: str = ""):
        """Quiz me question add karna"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO questions (quiz_id, question_text, options_json, correct_option_index, explanation)
                VALUES (?, ?, ?, ?, ?)
            """, (quiz_id, question_text, json.dumps(options, ensure_ascii=False), correct_idx, explanation))
            await db.commit()

    async def get_quiz(self, quiz_id: int) -> Optional[Dict[str, Any]]:
        """Quiz details get karna"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM quizzes WHERE quiz_id = ?", (quiz_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_quiz_questions(self, quiz_id: int) -> List[Dict[str, Any]]:
        """Quiz ke sabhi questions get karna"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM questions WHERE quiz_id = ?", (quiz_id,)) as cursor:
                rows = await cursor.fetchall()
                result = []
                for r in rows:
                    q = dict(r)
                    q['options'] = json.loads(q['options_json'])
                    result.append(q)
                return result

    async def get_all_quizzes(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Available quizzes ki list return karna"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT q.*, COUNT(ques.question_id) as total_questions
                FROM quizzes q
                LEFT JOIN questions ques ON q.quiz_id = ques.quiz_id
                GROUP BY q.quiz_id
                ORDER BY q.created_at DESC
                LIMIT ?
            """, (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def record_score(self, quiz_id: int, chat_id: int, user_id: int, score: int, total: int):
        """User ka score save karna"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO user_scores (quiz_id, chat_id, user_id, score, total_questions)
                VALUES (?, ?, ?, ?, ?)
            """, (quiz_id, chat_id, user_id, score, total))
            await db.commit()

    async def get_leaderboard(self, quiz_id: Optional[int] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Leaderboard calculate karna"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if quiz_id:
                query = """
                    SELECT u.first_name, u.username, s.score, s.total_questions
                    FROM user_scores s
                    JOIN users u ON s.user_id = u.user_id
                    WHERE s.quiz_id = ?
                    ORDER BY s.score DESC, s.submitted_at ASC
                    LIMIT ?
                """
                params = (quiz_id, limit)
            else:
                query = """
                    SELECT u.first_name, u.username, SUM(s.score) as score, SUM(s.total_questions) as total_questions
                    FROM user_scores s
                    JOIN users u ON s.user_id = u.user_id
                    GROUP BY s.user_id
                    ORDER BY score DESC
                    LIMIT ?
                """
                params = (limit,)

            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
