# -*- coding: utf-8 -*-
"""
main.py
(فایل ۴ از ۴)
(ارتقا یافته برای آزمون پیشرفته)
"""

import asyncio
from datetime import datetime, timedelta

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# (مهم) وارد کردن منابع و تنظیمات
from config import (
    logger, GROQ_client, TELEGRAM_TOKEN, CUR,
    DAILY_TIP_HOUR, DAILY_GROUP_TIP_HOUR
)
# (مهم) وارد کردن تابع راه‌اندازی دیتابیس
from database import setup_database, populate_initial_questions # (جدید)

# (مهم) وارد کردن تمام هندلرها از فایل جداگانه
import handlers

# ---------- background daily tip ----------
async def daily_tip_loop(application):
    """نکته روزانه برای کاربران در چت خصوصی"""
    while True:
        try:
            now = datetime.utcnow()
            target_hour_utc = (DAILY_TIP_HOUR - 3) % 24 # ساعت ایران به UTC
            target_minute_utc = 30 # (اصلاح) برای 3:30
            if target_hour_utc < 0: target_hour_utc += 24
            
            target = now.replace(hour=target_hour_utc, minute=target_minute_utc, second=0, microsecond=0)
            if target <= now:
                target = target + timedelta(days=1)
            wait = (target - now).total_seconds()
            
            logger.info("Daily USER tip scheduled in %s seconds", int(wait))
            await asyncio.sleep(wait)
            
            CUR.execute("SELECT tip_text FROM legal_tips ORDER BY RANDOM() LIMIT 1")
            row = CUR.fetchone()
            if not row:
                logger.warning("No legal tips in DB to send to users.")
                continue
            
            tip = row['tip_text']
            CUR.execute("SELECT user_id FROM users")
            rows = CUR.fetchall()
            logger.info(f"Sending daily tip to {len(rows)} users...")
            
            for r in rows:
                uid = r["user_id"]
                try:
                    await application.bot.send_message(chat_id=uid, text=f"🔔 نکته حقوقی روز:\n\n{tip}")
                except Exception:
                    logger.warning("Failed to send daily tip to %s", uid)
                await asyncio.sleep(0.05)
                
        except Exception:
            logger.exception("daily USER tip loop crashed")
            await asyncio.sleep(300)

async def daily_group_tip_loop(application):
    """نکته روزانه برای گروه‌ها و کانال‌ها"""
    while True:
        try:
            now = datetime.utcnow()
            target_hour_utc = (DAILY_GROUP_TIP_HOUR - 3) % 24
            target_minute_utc = 30
            if target_hour_utc < 0: target_hour_utc += 24
            
            target = now.replace(hour=target_hour_utc, minute=target_minute_utc, second=0, microsecond=0)
            if target <= now:
                target = target + timedelta(days=1)
            wait = (target - now).total_seconds()
            
            logger.info("Daily GROUP tip scheduled in %s seconds", int(wait))
            await asyncio.sleep(wait)
            
            CUR.execute("SELECT tip_text FROM legal_tips ORDER BY RANDOM() LIMIT 1")
            row = CUR.fetchone()
            if not row:
                logger.warning("No legal tips in DB to send to groups.")
                continue
            
            tip = row['tip_text']
            CUR.execute("SELECT chat_id FROM managed_groups WHERE daily_tip_enabled = 1")
            rows = CUR.fetchall()
            logger.info(f"Sending daily tip to {len(rows)} groups...")
            
            for r in rows:
                chat_id = r["chat_id"]
                try:
                    await application.bot.send_message(chat_id=chat_id, text=f"🔔 نکته حقوقی روز:\n\n{tip}")
                except Exception as e:
                    logger.warning(f"Failed to send daily tip to group {chat_id}: {e}")
                await asyncio.sleep(0.1) 
                
        except Exception:
            logger.exception("daily GROUP tip loop crashed")
            await asyncio.sleep(300)

# ---------- application bootstrap ----------
async def on_startup(app):
    try:
        app.create_task(daily_tip_loop(app))
        logger.info("Daily USER tip loop scheduled.")
        app.create_task(daily_group_tip_loop(app)) 
        logger.info("Daily GROUP tip loop scheduled.")
    except Exception as e:
        logger.exception("Failed to schedule daily tip loop: %s", e)

def build_application():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(on_startup).build()
    
    # ثبت هندلرهای ادمین
    app.add_handler(CommandHandler("admin", handlers.admin_panel_handler))

    # ثبت هندلرهای اصلی کاربر
    app.add_handler(CommandHandler("start", handlers.start_handler))
    app.add_handler(CallbackQueryHandler(handlers.callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handlers.text_handler))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.ChatType.PRIVATE, handlers.document_handler))
    app.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, handlers.voice_handler))

    # ثبت هندلرهای گروه
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handlers.new_chat_member_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP), handlers.group_message_handler))

    # ثبت هندلر خطا
    app.add_error_handler(handlers.error_handler)
    
    return app

def main():
    if not GROQ_client:
        logger.error("کلاینت Groq راه‌اندازی نشد. لطفاً GROQ_API_KEY را بررسی کنید.")
        logger.error("ربات متوقف شد.")
        return

    # (مهم) اطمینان از ساخته شدن جداول قبل از اجرای ربات
    logger.info("Setting up database...")
    setup_database()
    
    # (جدید) افزودن سوالات اولیه به دیتابیس (فقط اگر خالی باشد)
    logger.info("Populating initial quiz data if needed...")
    populate_initial_questions()

    app = build_application()
    logger.info("🤖 Bot (Ultimate Version - 4 File Structure) is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
