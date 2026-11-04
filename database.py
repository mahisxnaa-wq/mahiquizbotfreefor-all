import aiosqlite
import json
import logging
import uuid
import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = "quiz_bot.db"):
        self.db_path = db_path

    async def init_db(self):
        """Database tables check aur create karna"""
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
                    quiz_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    timer INTEGER DEFAULT 20,
                    questions_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    creator_name TEXT,
                    sections_enabled INTEGER DEFAULT 0,
                    sections_json TEXT DEFAULT '[]',
                    user_id INTEGER
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    quiz_id TEXT,
                    chat_id INTEGER,
                    user_id INTEGER,
                    score INTEGER DEFAULT 0,
                    total_questions INTEGER DEFAULT 0,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

    async def create_quiz(
        self,
        creator_id: int,
        title: str,
        questions: List[Dict[str, Any]],
        timer: int = 20,
        creator_name: str = ""
    ) -> str:
        """Naya quiz create karna (existing database format ke mutabiq)"""
        quiz_id = uuid.uuid4().hex[:8].upper()

        # Standardize question format
        formatted_questions = []
        for q in questions:
            q_text = q.get("question") or q.get("question_text", "")
            options = q.get("options", [])
            correct_idx = q.get("correct_option_index") if "correct_option_index" in q else q.get("correct_option_id", 0)
            explanation = q.get("explanation", "")

            formatted_questions.append({
                "question_text": q_text,
                "options": options,
                "correct_option_id": correct_idx,
                "explanation": explanation
            })

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO quizzes (quiz_id, name, timer, questions_json, user_id, creator_name, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                quiz_id,
                title,
                timer,
                json.dumps(formatted_questions, ensure_ascii=False),
                creator_id,
                creator_name,
                now_str
            ))
            await db.commit()
            return quiz_id

    async def get_quiz(self, quiz_id: str) -> Optional[Dict[str, Any]]:
        """Quiz details aur uske questions get karna"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM quizzes WHERE quiz_id = ?", (quiz_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                d = dict(row)
                d["title"] = d.get("name") or "Quiz"
                d["timer_seconds"] = d.get("timer") or 20
                try:
                    d["questions"] = json.loads(d.get("questions_json", "[]"))
                except Exception:
                    d["questions"] = []
                return d

    async def get_all_quizzes(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Available quizzes ki list return karna"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT quiz_id, name, timer, questions_json, created_at, creator_name
                FROM quizzes
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,)) as cursor:
                rows = await cursor.fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    d["title"] = d.get("name") or "Quiz"
                    try:
                        qs = json.loads(d.get("questions_json", "[]"))
                        d["total_questions"] = len(qs)
                    except Exception:
                        d["total_questions"] = 0
                    result.append(d)
                return result

    async def record_score(self, quiz_id: str, chat_id: int, user_id: int, score: int, total: int):
        """User ka score save karna"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO user_scores (quiz_id, chat_id, user_id, score, total_questions)
                VALUES (?, ?, ?, ?, ?)
            """, (quiz_id, chat_id, user_id, score, total))
            await db.commit()

    async def update_quiz_title(self, quiz_id: str, new_title: str):
        """Quiz ka title/naam update karna"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE quizzes SET name = ? WHERE quiz_id = ?", (new_title, quiz_id))
            await db.commit()

    async def update_quiz_timer(self, quiz_id: str, new_timer: int):
        """Quiz ka timer update karna"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE quizzes SET timer = ? WHERE quiz_id = ?", (new_timer, quiz_id))
            await db.commit()

    async def update_quiz_questions(self, quiz_id: str, questions: List[Dict[str, Any]]):
        """Quiz ke questions update karna"""
        formatted_questions = []
        for q in questions:
            formatted_questions.append({
                "question_text": q.get("question") or q.get("question_text", ""),
                "options": q.get("options", []),
                "correct_option_id": q.get("correct_option_index") if "correct_option_index" in q else q.get("correct_option_id", 0),
                "explanation": q.get("explanation", "")
            })
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE quizzes SET questions_json = ? WHERE quiz_id = ?",
                (json.dumps(formatted_questions, ensure_ascii=False), quiz_id)
            )
            await db.commit()

    async def get_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Global Leaderboard calculate karna"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query = """
                SELECT u.first_name, u.username, SUM(s.score) as score, SUM(s.total_questions) as total_questions
                FROM user_scores s
                JOIN users u ON s.user_id = u.user_id
                GROUP BY s.user_id
                ORDER BY score DESC
                LIMIT ?
            """
            async with db.execute(query, (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
