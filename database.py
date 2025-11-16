# -*- coding: utf-8 -*-
"""
database.py
(فایل ۲ از ۴)
(ارتقا یافته برای آزمون پیشرفته)
"""

import sqlite3
from datetime import datetime
from typing import Optional, List, Dict

# (مهم) منابع مشترک از config وارد می‌شوند
from config import DB, CUR, logger, SUPER_ADMIN_ID, AI_PERSONALITIES
# (جدید) وارد کردن سوالات اولیه
try:
    from quiz_data import QUESTIONS_DATA
except ImportError:
    logger.warning("quiz_data.py یافت نشد. سوالات اولیه بارگذاری نمی‌شوند.")
    QUESTIONS_DATA = []


def setup_database():
    """جداول دیتابیس را در صورت عدم وجود ایجاد می‌کند."""
    try:
        CUR.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            joined_at TEXT,
            ai_personality TEXT DEFAULT 'default',
            quiz_score INTEGER DEFAULT 0 /* (جدید) امتیاز آزمون کاربر */
        );
        CREATE TABLE IF NOT EXISTS history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            subject TEXT,
            content TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT,
            admin_reply TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS reminders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            remind_at TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS coin_rates(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            rate INTEGER,
            fetched_at TEXT
        );
        CREATE TABLE IF NOT EXISTS admins(
            user_id INTEGER PRIMARY KEY,
            added_by INTEGER,
            added_at TEXT
        );
        CREATE TABLE IF NOT EXISTS channels(
            channel_id TEXT PRIMARY KEY, /* یوزرنیم کانال بدون @ */
            added_by INTEGER,
            added_at TEXT
        );
        CREATE TABLE IF NOT EXISTS my_cases(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT,
            case_number TEXT,
            branch TEXT,
            notes TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS quiz_questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_text TEXT,
            option_a TEXT,
            option_b TEXT,
            option_c TEXT,
            option_d TEXT,
            correct_option TEXT, /* 'a', 'b', 'c', or 'd' */
            rationale_text TEXT, /* (جدید) پاسخنامه تشریحی */
            created_by INTEGER,
            created_at TEXT,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS quiz_user_answers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            question_id INTEGER,
            answer TEXT, /* 'a', 'b', 'c', 'd' */
            is_correct INTEGER,
            answered_at TEXT,
            UNIQUE(user_id, question_id)
        );
        CREATE TABLE IF NOT EXISTS legal_tips(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tip_text TEXT,
            added_by INTEGER,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS managed_groups(
            chat_id INTEGER PRIMARY KEY, /* آیدی عددی گروه یا کانال */
            added_at TEXT,
            daily_tip_enabled INTEGER DEFAULT 1
        );
        """)
        DB.commit()
        logger.info("Database tables checked/created successfully.")
    except Exception as e:
        logger.error(f"Failed to setup database: {e}")
        raise

# (جدید) تابع افزودن سوالات اولیه
def populate_initial_questions():
    """سوالات اولیه را از quiz_data.py به دیتابیس اضافه می‌کند (اگر خالی باشد)"""
    try:
        CUR.execute("SELECT COUNT(*) as c FROM quiz_questions")
        count = CUR.fetchone()["c"]
        if count > 0:
            logger.info("Quiz questions table already populated.")
            return

        if not QUESTIONS_DATA:
            logger.warning("No initial quiz data found to populate.")
            return

        logger.info(f"Populating database with {len(QUESTIONS_DATA)} initial quiz questions...")
        
        admin_id = SUPER_ADMIN_ID or 0
        created_at = datetime.utcnow().isoformat()
        
        insert_data = []
        for q in QUESTIONS_DATA:
            insert_data.append((
                q["question"], q["a"], q["b"], q["c"], q["d"], 
                q["correct"], q["rationale"], admin_id, created_at, 1
            ))

        CUR.executemany(
            "INSERT INTO quiz_questions(question_text, option_a, option_b, option_c, option_d, correct_option, rationale_text, created_by, created_at, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            insert_data
        )
        DB.commit()
        logger.info("Successfully populated quiz questions.")

    except Exception as e:
        logger.error(f"Failed to populate initial quiz questions: {e}")

# ---------- utilities (توابع کمکی دیتابیس) ----------

def is_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID:
        return True
    try:
        CUR.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        return CUR.fetchone() is not None
    except Exception:
        return False

def save_user(user) -> None:
    try:
        CUR.execute(
            "INSERT OR IGNORE INTO users(user_id, username, first_name, last_name, joined_at, ai_personality) VALUES (?, ?, ?, ?, ?, ?)",
            (user.id, user.username or "", user.first_name or "", user.last_name or "", datetime.utcnow().isoformat(), "default")
        )
        DB.commit()
    except Exception as e:
        logger.error(f"Failed to save user {user_id}: {e}")

# (جدید) تابع دریافت امتیاز کاربر
def get_user_score(user_id: int) -> int:
    try:
        CUR.execute("SELECT quiz_score FROM users WHERE user_id = ?", (user_id,))
        row = CUR.fetchone()
        return row["quiz_score"] if row else 0
    except Exception:
        return 0

# (جدید) تابع افزایش امتیاز کاربر
def increment_user_score(user_id: int, points: int = 1) -> None:
    try:
        CUR.execute(
            "UPDATE users SET quiz_score = quiz_score + ? WHERE user_id = ?",
            (points, user_id)
        )
        DB.commit()
    except Exception as e:
        logger.error(f"Failed to increment score for user {user_id}: {e}")

def get_user_settings(user_id: int) -> dict:
    try:
        CUR.execute("SELECT ai_personality FROM users WHERE user_id = ?", (user_id,))
        row = CUR.fetchone()
        if row:
            return {"ai_personality": row["ai_personality"]}
        return {"ai_personality": "default"}
    except Exception:
        return {"ai_personality": "default"}

def set_user_personality(user_id: int, personality: str) -> None:
    if personality not in AI_PERSONALITIES:
        personality = "default"
    try:
        CUR.execute("UPDATE users SET ai_personality = ? WHERE user_id = ?", (personality, user_id))
        DB.commit()
    except Exception as e:
        logger.error(f"Failed to set personality for {user_id}: {e}")

def save_history(user_id: int, role: str, subject: str, content: str) -> None:
    try:
        CUR.execute(
            "INSERT INTO history(user_id, role, subject, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, role, subject, content, datetime.utcnow().isoformat())
        )
        DB.commit()
    except Exception as e:
        logger.error(f"Failed to save history for {user_id}: {e}")

def get_chat_history(user_id: int, subject_tag: str = "حقوقی", limit: int = 5) -> List[Dict[str, str]]:
    """
    تاریخچه چت کاربر را برای یک موضوع خاص (مانند 'حقوقی' یا 'simulator') برمی‌گرداند.
    """
    try:
        history = []
        rows = []
        
        if subject_tag == "all":
            CUR.execute(
                "SELECT role, content FROM history WHERE user_id = ? AND role IN ('user', 'bot') ORDER BY id DESC LIMIT ?",
                (user_id, limit)
            )
            rows = CUR.fetchall()
        else:
            query_subject = "پرسش حقوقی"
            response_subject = "پاسخ حقوقی"
            
            if subject_tag == "simulator":
                query_subject = "پرونده شبیه‌ساز"
                response_subject = "پاسخ شبیه‌ساز"
            elif subject_tag == "checklist":
                query_subject = "چک‌لیست"
                response_subject = "پاسخ چک‌لیست"
            elif subject_tag == "smart_contract":
                query_subject = "قرارداد هوشمند"
                response_subject = "پاسخ قرارداد هوشمند"
            # ... (می‌توان موضوعات دیگر را در آینده اضافه کرد)

            CUR.execute(
                "SELECT role, content FROM history WHERE user_id = ? AND subject IN (?, ?) ORDER BY id DESC LIMIT ?",
                (user_id, query_subject, response_subject, limit)
            )
            rows = CUR.fetchall()

        for r in reversed(rows):
            role = r["role"]
            if role == "bot":
                role = "assistant"
            history.append({"role": role, "content": r["content"]})
        return history
        
    except Exception as e:
        logger.error(f"Failed to get chat history for {user_id} (subject: {subject_tag}): {e}")
        return []

def create_report(user_id: int, content: str) -> int:
    CUR.execute(
        "INSERT INTO reports(user_id, content, admin_reply, created_at) VALUES (?, ?, ?, ?)",
        (user_id, content, None, datetime.utcnow().isoformat())
    )
    DB.commit()
    return CUR.lastrowid

def add_reminder(user_id: int, title: str, remind_at: str) -> int:
    CUR.execute(
        "INSERT INTO reminders(user_id, title, remind_at, created_at) VALUES (?, ?, ?, ?)",
        (user_id, title, remind_at, datetime.utcnow().isoformat())
    )
    DB.commit()
    return CUR.lastrowid

def save_coin_rate(source: str, rate: int) -> None:
    CUR.execute(
        "INSERT INTO coin_rates(source, rate, fetched_at) VALUES (?, ?, ?)",
        (source, rate, datetime.utcnow().isoformat())
    )
    DB.commit()

def get_last_rate(source: str = "tgju_sekee") -> Optional[int]:
    CUR.execute("SELECT rate FROM coin_rates WHERE source IN ('tgju_sekee', 'tgju_sekeb') ORDER BY id DESC LIMIT 1")
    r = CUR.fetchone()
    return int(r["rate"]) if r else None

def get_mandatory_channels() -> List[str]:
    try:
        CUR.execute("SELECT channel_id FROM channels")
        rows = CUR.fetchall()
        return [r["channel_id"] for r in rows]
    except Exception as e:
        logger.error(f"Failed to get mandatory channels: {e}")
        return []

# (تغییر یافته) نام و منطق تابع تغییر کرد
def get_next_quiz_question(user_id: int) -> Optional[sqlite3.Row]:
    """
    اولین سوال فعالی که کاربر هنوز به آن پاسخ نداده است را برمی‌گرداند.
    """
    try:
        CUR.execute("""
            SELECT * FROM quiz_questions 
            WHERE is_active = 1 
            AND id NOT IN (
                SELECT question_id FROM quiz_user_answers WHERE user_id = ?
            )
            ORDER BY id ASC 
            LIMIT 1
        """, (user_id,))
        return CUR.fetchone()
    except Exception as e:
        logger.error(f"Error getting next quiz question for user {user_id}: {e}")
        return None
