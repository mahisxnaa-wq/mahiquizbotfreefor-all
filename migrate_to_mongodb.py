"""
SQLite se MongoDB Atlas me data migrate karne ka script.
Ye script ek baar run karna hai — pehle se existing data ko MongoDB me daal dega.

Usage:
  1. MONGODB_URI environment variable set karo
  2. quiz_bot.db file same folder me hona chahiye
  3. python migrate_to_mongodb.py
"""

import asyncio
import sqlite3
import json
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "")
SQLITE_PATH = "quiz_bot.db"


async def migrate():
    if not MONGODB_URI:
        print("❌ ERROR: MONGODB_URI set nahi hai!")
        print("   .env file me ya environment variable me MONGODB_URI daalo.")
        return

    # SQLite connect
    if not os.path.exists(SQLITE_PATH):
        print(f"❌ ERROR: {SQLITE_PATH} file nahi mili!")
        return

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    cursor = sqlite_conn.cursor()

    # MongoDB connect
    print("🔗 MongoDB Atlas se connect ho rahe hain...")
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client["quiz_bot"]

    # Test connection
    try:
        await client.admin.command("ping")
        print("✅ MongoDB Atlas se successfully connect ho gaye!")
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        return

    # ==================== USERS MIGRATE ====================
    print("\n📋 Users migrate ho rahe hain...")
    cursor.execute("SELECT * FROM users")
    users = [dict(row) for row in cursor.fetchall()]
    
    if users:
        user_count = 0
        for user in users:
            await db.users.update_one(
                {"user_id": user["user_id"]},
                {"$set": user},
                upsert=True
            )
            user_count += 1
        print(f"   ✅ {user_count} users migrate ho gaye!")
    else:
        print("   ⚠️ Koi user nahi mila SQLite me.")

    # ==================== QUIZZES MIGRATE ====================
    print("\n📝 Quizzes migrate ho rahe hain...")
    cursor.execute("SELECT * FROM quizzes")
    quizzes = [dict(row) for row in cursor.fetchall()]
    
    if quizzes:
        quiz_count = 0
        for quiz in quizzes:
            # questions_json string ko Python list me convert karo
            try:
                questions_list = json.loads(quiz.get("questions_json", "[]"))
            except (json.JSONDecodeError, TypeError):
                questions_list = []
            
            mongo_doc = {
                "quiz_id": quiz["quiz_id"],
                "name": quiz.get("name", "Quiz"),
                "timer": quiz.get("timer", 20),
                "questions": questions_list,  # Direct array, no JSON string!
                "created_at": quiz.get("created_at", ""),
                "creator_name": quiz.get("creator_name", ""),
                "user_id": quiz.get("user_id"),
                "sections_enabled": quiz.get("sections_enabled", 0),
                "sections_json": quiz.get("sections_json", "[]"),
            }

            await db.quizzes.update_one(
                {"quiz_id": quiz["quiz_id"]},
                {"$set": mongo_doc},
                upsert=True
            )
            quiz_count += 1
            q_count = len(questions_list)
            print(f"   ✅ Quiz '{quiz.get('name', '?')}' (ID: {quiz['quiz_id']}) - {q_count} questions")
        
        print(f"\n   🎯 Total {quiz_count} quizzes migrate ho gaye!")
    else:
        print("   ⚠️ Koi quiz nahi mila SQLite me.")

    # ==================== USER SCORES MIGRATE ====================
    print("\n🏆 User Scores migrate ho rahe hain...")
    cursor.execute("SELECT * FROM user_scores")
    scores = [dict(row) for row in cursor.fetchall()]
    
    if scores:
        score_count = 0
        for score in scores:
            score.pop("id", None)  # Auto-increment ID hata do
            await db.user_scores.insert_one(score)
            score_count += 1
        print(f"   ✅ {score_count} score records migrate ho gaye!")
    else:
        print("   ⚠️ Koi score record nahi mila SQLite me.")

    # ==================== CREATE INDEXES ====================
    print("\n📊 Indexes bana rahe hain...")
    await db.users.create_index("user_id", unique=True)
    await db.quizzes.create_index("quiz_id", unique=True)
    await db.quizzes.create_index("created_at")
    await db.user_scores.create_index([("quiz_id", 1), ("user_id", 1)])
    print("   ✅ Indexes ban gaye!")

    # ==================== VERIFY ====================
    print("\n🔍 Verification...")
    user_count = await db.users.count_documents({})
    quiz_count = await db.quizzes.count_documents({})
    score_count = await db.user_scores.count_documents({})
    print(f"   Users in MongoDB: {user_count}")
    print(f"   Quizzes in MongoDB: {quiz_count}")
    print(f"   Scores in MongoDB: {score_count}")

    sqlite_conn.close()
    client.close()

    print("\n" + "="*50)
    print("🎉 MIGRATION COMPLETE! Sab data MongoDB me aa gaya!")
    print("="*50)
    print("\nAb aap Render pe MONGODB_URI environment variable")
    print("set karo aur bot redeploy karo. Data safe hai! ✅")


if __name__ == "__main__":
    asyncio.run(migrate())
