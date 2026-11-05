import logging
import uuid
import datetime
from typing import List, Dict, Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient
import certifi
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
            ca = certifi.where()
            self.client = AsyncIOMotorClient(
                self.uri,
                tlsCAFile=ca,
                serverSelectionTimeoutMS=15000
            )
            self.db = self.client["quiz_bot"]

            # Connection test
            await self.client.admin.command("ping")
            logger.info("✅ MongoDB Atlas se successfully connect ho gaya!")

            # Indexes create karna for fast lookups
            await self.db.users.create_index("user_id", unique=True)
            await self.db.quizzes.create_index("quiz_id", unique=True)
            await self.db.quizzes.create_index("created_at")
            await self.db.user_scores.create_index([("quiz_id", 1), ("user_id", 1)])
            await self.db.quiz_plays.create_index("quiz_id")
            await self.db.quiz_plays.create_index("played_at")
        except Exception as e:
            logger.error(f"❌ MongoDB connection error: {e}")
            logger.info("MongoDB retry mode me chal raha hai, bot crash nahi hoga.")

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
        
        # Support both questions array and questions_json string
        if "questions" in doc and isinstance(doc["questions"], list):
            pass
        elif "questions_json" in doc:
            try:
                doc["questions"] = json.loads(doc["questions_json"])
            except Exception:
                doc["questions"] = []
        elif "questions" in doc and isinstance(doc["questions"], str):
            try:
                doc["questions"] = json.loads(doc["questions"])
            except Exception:
                doc["questions"] = []
        else:
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

    async def save_group(self, chat_id: int, title: str, username: Optional[str], members_count: int, added_by_id: int, added_by_name: str):
        """Jab bot kisi group me add ho toh group details MongoDB me save karna"""
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await self.db.groups.update_one(
            {"chat_id": chat_id},
            {"$set": {
                "chat_id": chat_id,
                "title": title,
                "username": username,
                "members_count": members_count,
                "added_by_id": added_by_id,
                "added_by_name": added_by_name,
                "updated_at": now_str,
            },
            "$setOnInsert": {
                "added_at": now_str
            }},
            upsert=True
        )

    async def get_all_groups(self) -> List[Dict[str, Any]]:
        """Saare groups ki list retrieve karna"""
        cursor = self.db.groups.find({}, {"_id": 0})
        return await cursor.to_list(length=None)

    async def get_all_group_ids(self) -> List[int]:
        """Saare unique group IDs nikalna (groups collection + user_scores dono se)"""
        group_ids = set()
        try:
            cursor = self.db.groups.find({}, {"chat_id": 1, "_id": 0})
            async for doc in cursor:
                cid = doc.get("chat_id")
                if cid:
                    group_ids.add(int(cid))
        except Exception:
            pass

        try:
            scores_groups = await self.db.user_scores.distinct("chat_id", {"chat_id": {"$lt": 0}})
            for cid in scores_groups:
                if cid:
                    group_ids.add(int(cid))
        except Exception:
            pass

        return list(group_ids)

    async def get_user_quiz_count(self, user_id: int) -> int:
        """User ne ab tak kitne quizzes banaye hain count karna"""
        try:
            return await self.db.quizzes.count_documents({"user_id": user_id})
        except Exception as e:
            logger.error(f"Error getting user quiz count: {e}")
            return 0

    async def get_total_quizzes_count(self) -> int:
        """Bot me total kitne quizzes bane hain"""
        try:
            return await self.db.quizzes.count_documents({})
        except Exception:
            return 0

    async def get_top_creators(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Top quiz creators ki ranking aur stats"""
        try:
            pipeline = [
                {
                    "$group": {
                        "_id": "$user_id",
                        "quiz_count": {"$sum": 1},
                        "creator_name": {"$last": "$creator_name"},
                        "latest_quiz_date": {"$max": "$created_at"},
                    }
                },
                {"$sort": {"quiz_count": -1}},
                {"$limit": limit}
            ]
            creators = await self.db.quizzes.aggregate(pipeline).to_list(length=limit)
            for c in creators:
                user_doc = await self.db.users.find_one({"user_id": c["_id"]})
                if user_doc:
                    c["username"] = user_doc.get("username")
                    if not c.get("creator_name"):
                        c["creator_name"] = user_doc.get("first_name", "Unknown")
            return creators
        except Exception as e:
            logger.error(f"Error getting top creators: {e}")
            return []

    async def record_quiz_play(
        self,
        quiz_id: str,
        quiz_title: str,
        chat_id: int,
        chat_title: str,
        chat_type: str,
        starter_id: int,
        starter_name: str,
        starter_username: Optional[str] = None
    ):
        """Jab bhi koi quiz start/play kiya jaye toh MongoDB me log karna"""
        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            play_doc = {
                "quiz_id": quiz_id,
                "quiz_title": quiz_title,
                "chat_id": chat_id,
                "chat_title": chat_title,
                "chat_type": chat_type,
                "starter_id": starter_id,
                "starter_name": starter_name,
                "starter_username": starter_username,
                "played_at": now_str
            }
            await self.db.quiz_plays.insert_one(play_doc)
            await self.db.quizzes.update_one(
                {"quiz_id": quiz_id},
                {"$inc": {"plays_count": 1}, "$set": {"last_played_at": now_str}}
            )
        except Exception as e:
            logger.error(f"Error recording quiz play: {e}")

    async def get_quiz_play_count(self, quiz_id: str) -> int:
        """Ek quiz total kitni baar khela gaya hai"""
        try:
            return await self.db.quiz_plays.count_documents({"quiz_id": quiz_id})
        except Exception:
            return 0

    async def get_total_plays_count(self) -> int:
        """Poore bot me total kitni baar quizzes khele gaye"""
        try:
            return await self.db.quiz_plays.count_documents({})
        except Exception:
            return 0

    async def get_recent_quiz_plays(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Recent groups/chats jahan quiz khele/share kiye gaye"""
        try:
            cursor = self.db.quiz_plays.find({}, {"_id": 0}).sort("played_at", -1).limit(limit)
            return await cursor.to_list(length=limit)
        except Exception as e:
            logger.error(f"Error getting recent plays: {e}")
            return []

