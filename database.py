import logging
import uuid
import datetime
from typing import List, Dict, Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient
import config

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, mongodb_uri: str = None):
        self.uri = mongodb_uri or config.MONGODB_URI
        self.client = None
        self.db = None

    async def init_db(self):
        """MongoDB se connect karna aur collections setup karna"""
        try:
            self.client = AsyncIOMotorClient(self.uri)
            self.db = self.client["quiz_bot"]

            # Indexes create karna for fast lookups
            await self.db.users.create_index("user_id", unique=True)
            await self.db.quizzes.create_index("quiz_id", unique=True)
            await self.db.quizzes.create_index("created_at")
            await self.db.user_scores.create_index([("quiz_id", 1), ("user_id", 1)])

            # Connection test
            await self.client.admin.command("ping")
            logger.info("✅ MongoDB Atlas se successfully connect ho gaya!")
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            raise

    async def register_user(self, user_id: int, username: Optional[str], first_name: str):
        """User ko register ya update karna"""
        await self.db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
            },
             "$setOnInsert": {
                "joined_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }},
            upsert=True
        )

    async def get_all_users(self) -> List[int]:
        """Broadcast ke liye sabhi user IDs retrieve karna"""
        cursor = self.db.users.find({}, {"user_id": 1, "_id": 0})
        users = await cursor.to_list(length=None)
        return [u["user_id"] for u in users]

    async def create_quiz(
        self,
        creator_id: int,
        title: str,
        questions: List[Dict[str, Any]],
        timer: int = 20,
        creator_name: str = ""
    ) -> str:
        """Naya quiz create karna"""
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

        await self.db.quizzes.insert_one({
            "quiz_id": quiz_id,
            "name": title,
            "timer": timer,
            "questions": formatted_questions,
            "user_id": creator_id,
            "creator_name": creator_name,
            "created_at": now_str,
            "sections_enabled": 0,
            "sections_json": "[]"
        })

        return quiz_id

    async def get_quiz(self, quiz_id: str) -> Optional[Dict[str, Any]]:
        """Quiz details aur uske questions get karna"""
        doc = await self.db.quizzes.find_one({"quiz_id": quiz_id})
        if not doc:
            return None
        doc.pop("_id", None)
        doc["title"] = doc.get("name") or "Quiz"
        doc["timer_seconds"] = doc.get("timer") or 20
        # questions directly array me hain, JSON parse nahi karna
        if "questions" not in doc:
            doc["questions"] = []
        return doc

    async def get_all_quizzes(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Available quizzes ki list return karna"""
        cursor = self.db.quizzes.find(
            {},
            {"quiz_id": 1, "name": 1, "timer": 1, "questions": 1, "created_at": 1, "creator_name": 1, "_id": 0}
        ).sort("created_at", -1).limit(limit)

        result = []
        async for doc in cursor:
            doc["title"] = doc.get("name") or "Quiz"
            doc["total_questions"] = len(doc.get("questions", []))
            result.append(doc)
        return result

    async def record_score(self, quiz_id: str, chat_id: int, user_id: int, score: int, total: int):
        """User ka score save karna"""
        await self.db.user_scores.insert_one({
            "quiz_id": quiz_id,
            "chat_id": chat_id,
            "user_id": user_id,
            "score": score,
            "total_questions": total,
            "submitted_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    async def update_quiz_title(self, quiz_id: str, new_title: str):
        """Quiz ka title/naam update karna"""
        await self.db.quizzes.update_one(
            {"quiz_id": quiz_id},
            {"$set": {"name": new_title}}
        )

    async def update_quiz_timer(self, quiz_id: str, new_timer: int):
        """Quiz ka timer update karna"""
        await self.db.quizzes.update_one(
            {"quiz_id": quiz_id},
            {"$set": {"timer": new_timer}}
        )

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
        await self.db.quizzes.update_one(
            {"quiz_id": quiz_id},
            {"$set": {"questions": formatted_questions}}
        )

    async def get_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Global Leaderboard calculate karna"""
        pipeline = [
            {"$group": {
                "_id": "$user_id",
                "score": {"$sum": "$score"},
                "total_questions": {"$sum": "$total_questions"}
            }},
            {"$sort": {"score": -1}},
            {"$limit": limit},
            {"$lookup": {
                "from": "users",
                "localField": "_id",
                "foreignField": "user_id",
                "as": "user_info"
            }},
            {"$unwind": {"path": "$user_info", "preserveNullAndEmptyArrays": True}},
            {"$project": {
                "_id": 0,
                "first_name": {"$ifNull": ["$user_info.first_name", "Unknown"]},
                "username": {"$ifNull": ["$user_info.username", None]},
                "score": 1,
                "total_questions": 1
            }}
        ]
        cursor = self.db.user_scores.aggregate(pipeline)
        return await cursor.to_list(length=None)
