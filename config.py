# -*- coding: utf-8 -*-
"""
config.py
(فایل ۱ از ۴)
شامل تمام تنظیمات، کلیدها، ثابت‌ها و منابع مشترک مانند دیتابیس و کلاینت Groq.
"""

import os
import logging
import sqlite3
from typing import Optional, List, Dict

# (تغییر) وارد کردن کتابخانه Groq
try:
    from groq import Groq
except ImportError:
    print("کتابخانه groq یافت نشد. لطفاً آن را نصب کنید: pip install groq")
    Groq = None # type: ignore

from telegram import ReplyKeyboardMarkup

# ------------------ CONFIG (مقادیر شما اینجا) ------------------
# (مهم) مقادیر حساس از Replit Secrets (متغیرهای محیطی) خوانده می‌شوند
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_FALLBACK_TELEGRAM_TOKEN_HERE")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "YOUR_FALLBACK_GROQ_API_KEY_HERE")
SUPER_ADMIN_ID_STR = os.environ.get("SUPER_ADMIN_ID", "YOUR_FALLBACK_ADMIN_ID_HERE")

try:
    SUPER_ADMIN_ID = int(SUPER_ADMIN_ID_STR)
except ValueError:
    print(f"SUPER_ADMIN_ID ('{SUPER_ADMIN_ID_STR}') معتبر نیست. باید یک عدد باشد.")
    SUPER_ADMIN_ID = 0 # مقدار پیش‌فرض نامعتبر

DB_FILE = "legal_bot_ultimate.db"
DAILY_TIP_HOUR = 12
DAILY_GROUP_TIP_HOUR = 10
RATE_LIMIT_PER_MIN = 8
TGJU_SEKE_URL = "https://www.tgju.org/profile/sekeb" 
DEFAULT_TAX_RATE = 0.10
CHAT_HISTORY_LIMIT = 5

LEGAL_DISCLAIMER = "\n\n⚖️ **تذکر:** اطلاعات این ربات بر اساس داده‌های عمومی است و هرگز جایگزین مشاوره تخصصی با وکیل دادگستری نمی‌باشد."
# ---------------------------------------------------------------

# ---------- راه‌اندازی کلاینت Groq (اصلاح شد) ----------
if not TELEGRAM_TOKEN or "FALLBACK" in TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN یافت نشد. آن را در Replit Secrets تنظیم کنید.")

GROQ_client = None
if GROQ_API_KEY and "FALLBACK" not in GROQ_API_KEY and Groq is not None:
    try:
        GROQ_client = Groq(
            api_key=GROQ_API_KEY,
        )
        print("کلاینت Groq با موفقیت راه‌اندازی شد.")
    except Exception as e:
        print(f"Failed to initialize Groq client: {e}")
elif not Groq:
     print("کتابخانه Groq نصب نیست. قابلیت‌های AI غیرفعال خواهند بود.")
else:
    print("GROQ_API_KEY یافت نشد یا معتبر نیست. آن را در Replit Secrets تنظیم کنید.")

# ---------- logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- DB (پایگاه داده) ----------
# این اتصال در تمام فایل‌های دیگر import خواهد شد
DB = sqlite3.connect(DB_FILE, check_same_thread=False)
DB.row_factory = sqlite3.Row
CUR = DB.cursor()

# ---------- UI (منوی اصلی جدید) ----------
MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["🧾 پرسش حقوقی (با حافظه)", "📄 تحلیل سند (PDF/DOCX)"],
        ["🧮 محاسبه‌گر", "📝 پیش‌نویس", "📄 دستیار هوشمند قرارداد"],
        ["🔔 آخرین اخبار", "🗂️ پرونده‌های من", "⚖️ آزمون حقوقی"],
        ["🎙️ تحلیلگر صوتی", "📋 چک‌لیست پرونده", "👨‍⚖️ شبیه‌ساز دادگاه"],
        ["💡 نکات حقوقی", "📚 واژه‌نامه", "⏰ یادآوری‌ها"], 
        ["⚙️ تنظیمات", "📨 ارسال گزارش", "👤 پروفایل من"]
    ],
    resize_keyboard=True
)

# دیکشنری شخصیت‌های AI
AI_PERSONALITIES = {
    "default": "شما وکیل مشاور حقوقی متخصص در قوانین ایران هستید. پاسخ‌ها باید دقیق، مستند و کاربردی باشند. در صورت امکان به مواد قانونی مرتبط ارجاع دهید.",
    "simple": "شما یک دوست آگاه به حقوق هستید. همه چیز را به زبان کاملاً ساده و عامیانه توضیح می‌دهید، انگار برای یک فرد 15 ساله توضیح می‌دهید. پاسخ شما باید *از نظر حقوقی صحیح* باشد، اما بیان آن ساده باشد.",
    "technical": "شما یک قاضی یا وکیل ارشد هستید. پاسخ‌های شما باید بسیار فنی، دقیق، مستند و مملو از ارجاع به مواد قانونی و رویه‌های قضایی باشد. دقت اولویت اول شماست."
}

# کلمات کلیدی برای تشخیص سوال حقوقی در گروه
LEGAL_KEYWORDS = [
    "حقوق", "قانون", "وکیل", "قضایی", "دادگاه", "ارث", "طلاق", "مهریه", "دیه", 
    "سفته", "چک", "قرارداد", "مجازات", "کیفری", "شکایت", "دادسرا", "اجاره"
]
