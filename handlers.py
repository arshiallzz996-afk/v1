# -*- coding: utf-8 -*-
"""
handlers.py
(فایل ۳ از ۴)
(ارتقا یافته برای آزمون پیشرفته)
"""

import os
# ... (سایر import ها) ...
import asyncio
import tempfile
# ... (سایر import ها) ...
from config import (
    logger, DB, CUR, GROQ_client, SUPER_ADMIN_ID,
    MAIN_MENU, AI_PERSONALITIES, LEGAL_DISCLAIMER, TGJU_SEKE_URL,
    DEFAULT_TAX_RATE, CHAT_HISTORY_LIMIT, RATE_LIMIT_PER_MIN,
    LEGAL_KEYWORDS
)
from database import (
    is_admin, save_user, get_user_settings, set_user_personality,
    save_history, get_chat_history, create_report, add_reminder,
    save_coin_rate, get_last_rate, get_mandatory_channels,
    get_next_quiz_question, increment_user_score, get_user_score # (جدید)
)

# ---------- توابع استخراج متن فایل ----------
def extract_pdf_text(path: str) -> str:
    try:
        doc = fitz.open(path)
        text = "\n".join([page.get_text("text") for page in doc])
        return text
    except Exception as e:
        logger.error(f"PDF Error: {e}")
        return f"خطا در خواندن PDF: {e}"

def extract_docx_text(path: str) -> str:
    try:
        doc = docx.Document(path)
        text = "\n".join([para.text for para in doc.paragraphs])
        return text
    except Exception as e:
        logger.error(f"DOCX Error: {e}")
        return f"خطا در خواندن DOCX: {e}"

# ---------- rate limiting ----------
_recent_requests: dict[int, list[float]] = {}
def rate_limited(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        uid = update.effective_user.id if update.effective_user else None
        if not uid or is_admin(uid):
            return await func(update, context, *args, **kwargs)
        now = time.time()
        lst = _recent_requests.get(uid, [])
        lst = [t for t in lst if t > now - 60]
        if len(lst) >= RATE_LIMIT_PER_MIN:
            try:
                await update.message.reply_text("⚠️ شما در حال ارسال پیام با سرعت زیاد هستید. لطفاً چند لحظه صبر کنید.")
            except Exception: pass
            return
        lst.append(now)
        _recent_requests[uid] = lst
        return await func(update, context, *args, **kwargs)
    return wrapper

# ---------- membership ----------
async def check_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    channels = get_mandatory_channels()
    if not channels:
        return True

    try:
        for channel_username in channels:
            username = channel_username if channel_username.startswith("@") else f"@{channel_username}"
            member = await context.bot.get_chat_member(username, user_id)
            if member.status not in ("member", "creator", "administrator"):
                logger.info(f"User {user_id} is NOT a member of {username}")
                return False
        return True
    except Exception as e:
        logger.warning("Membership check error for user %s: %s", user_id, e)
        return True 

async def send_join_request_for_user(update: Update):
    channels = get_mandatory_channels()
    kb_buttons = []
    if not channels:
        await update.message.reply_text("⚖️ برای استفاده از ربات، عضویت در کانال الزامی است. (خطا: کانالی تنظیم نشده)")
        return
        
    for channel_username in channels:
        url = f"https://t.me/{channel_username.strip('@')}"
        kb_buttons.append([InlineKeyboardButton(f"📢 عضویت در کانال @{channel_username}", url=url)])
    
    kb_buttons.append([InlineKeyboardButton("✅ تایید عضویت", callback_data="verify_membership")])
    kb = InlineKeyboardMarkup(kb_buttons)
    reply_func = update.message.reply_text if update.message else update.effective_message.reply_text
    await reply_func("⚖️ برای استفاده از ربات، ابتدا باید در **تمام** کانال‌های زیر عضو شوید:", reply_markup=kb, parse_mode="Markdown")

# ---------- AI helper ----------
async def ask_ai(user_id: int, prompt: str, chat_history: Optional[List[Dict[str, str]]] = None, system: Optional[str] = None) -> str:
    if not GROQ_client:
        logger.error("کلاینت Groq راه‌اندازی نشده است.")
        return "⚠️ سرویس هوش مصنوعی در حال حاضر در دسترس نیست. (کلاینت راه‌اندازی نشد)"

    user_settings = get_user_settings(user_id)
    personality_prompt = AI_PERSONALITIES.get(user_settings["ai_personality"], AI_PERSONALITIES["default"])
    final_system_prompt = system or personality_prompt
    messages = [{"role": "system", "content": final_system_prompt}]
    
    if chat_history:
        messages.extend(chat_history)
    messages.append({"role": "user", "content": prompt})

    def _call():
        try:
            completion = GROQ_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages, # type: ignore
                temperature=0.2,
                max_tokens=1024,
                top_p=1,
                stream=False
            )
            if completion.choices and completion.choices[0].message:
                return completion.choices[0].message.content.strip()
            else:
                logger.warning("Groq response format unknown: %s", completion)
                return "⚠️ فرمت پاسخ از سرویس AI ناشناخته است."
        except Exception as e:
            logger.exception("Groq API error")
            return f"⚠️ خطا در ارتباط با سرویس Groq: {e}"

    return await asyncio.to_thread(_call)

# ---------- TGJU fetch ----------
async def fetch_tgju_sekee_rate() -> Optional[int]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
            r = await client.get(TGJU_SEKE_URL, headers=headers) 
            r.raise_for_status()
            html = r.text
    except Exception as e:
        logger.warning(f"Failed to fetch TGJU ({TGJU_SEKE_URL}): {e}", e)
        return None
    
    try:
        soup = BeautifulSoup(html, "html.parser")
        price_span = soup.find("span", {"data-col": "info.last_trade.price"}) 
        
        if price_span:
            cleaned = price_span.text.replace(",", "").strip()
            candidate = int(cleaned)
            save_coin_rate("tgju_sekeb", candidate) 
            return candidate
        else:
            logger.warning(f"Could not find price span in TGJU HTML ({TGJU_SEKE_URL}).")
            return None
    except Exception:
        logger.exception("Error parsing TGJU HTML")
        return None

# ---------- Handlers (هندلرهای اصلی) ----------

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    
    if not await check_membership(user.id, context):
        await send_join_request_for_user(update)
        return
    
    msg = f"👋 سلام {user.first_name or ''}!\nاز منو یک گزینه انتخاب کنید:"
    if is_admin(user.id):
        msg += "\n\n(شما ادمین هستید. برای پنل مدیریت /admin را ارسال کنید.)"

    await update.message.reply_text(msg, reply_markup=MAIN_MENU)

@rate_limited
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    text = (update.message.text or "").strip()
    state = context.user_data.get("state")
    current_menu = MAIN_MENU

    if not await check_membership(uid, context):
        await send_join_request_for_user(update)
        return

    if text in ("🔙 بازگشت به منو", "❌ پایان شبیه‌سازی"):
        context.user_data.clear()
        await update.message.reply_text("منوی اصلی:", reply_markup=MAIN_MENU)
        return

    # --- (جدید) منطق حالت‌های ادمین ---
    if is_admin(uid):
        if text == "🔙 بازگشت به منو":
             context.user_data.clear()
             await update.message.reply_text("منوی اصلی:", reply_markup=MAIN_MENU)
             return
        
        # --- حالت پاسخ به گزارش ---
        if state == "awaiting_admin_reply":
            try:
                report_data = context.user_data.pop("reply_to_report", None)
                if not report_data:
                    await update.message.reply_text("❌ خطای داخلی: اطلاعات گزارش یافت نشد.", reply_markup=current_menu)
                    context.user_data.pop("state", None)
                    return

                reply_text = update.message.text
                target_user_id = report_data["user_id"]
                report_id = report_data["report_id"]

                CUR.execute("UPDATE reports SET admin_reply = ? WHERE id = ?", (reply_text, report_id))
                DB.commit()

                try:
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=f"📨 **پاسخ ادمین به گزارش شما (ID: {report_id})**:\n\n{reply_text}"
                    )
                    await update.message.reply_text(f"✅ پاسخ شما برای گزارش #{report_id} ارسال شد.")
                except Exception as e:
                    logger.warning(f"Failed to send admin reply to user {target_user_id}: {e}")
                    await update.message.reply_text(f"⚠️ پاسخ در دیتابیس ثبت شد، اما ارسال به کاربر با خطا مواجه شد: {e}")
                
                context.user_data.pop("state", None)
                await show_admin_reports(update, context, query_message=update.message)

            except Exception as e:
                logger.error(f"Admin reply error: {e}")
                await update.message.reply_text(f"❌ خطا در ارسال پاسخ: {e}")
            return
        
        # --- حالت افزودن سوال آزمون ---
        if state == "awaiting_quiz_question":
            try:
                # (تغییر) اکنون 7 بخش نیاز است (با پاسخ تشریحی)
                parts = [p.strip() for p in text.split("|")]
                if len(parts) != 7:
                    raise ValueError(f"فرمت اشتباه، 7 بخش مورد نیاز است (دریافتی: {len(parts)})")
                
                question, o_a, o_b, o_c, o_d, correct, rationale = parts
                correct = correct.strip().lower()
                if correct not in ['a', 'b', 'c', 'd', 'الف', 'ب', 'ج', 'د']:
                     raise ValueError("پاسخ صحیح باید a, b, c, d یا الف, ب, ج, د باشد")
                
                if correct in ['الف', 'ب', 'ج', 'د']:
                    correct = {'الف': 'a', 'ب': 'b', 'ج': 'c', 'د': 'd'}[correct]
                
                if len(rationale) < 10:
                    raise ValueError("پاسخ تشریحی (بخش هفتم) بسیار کوتاه است")

                # (تغییر) غیرفعال کردن سوالات قبلی دیگر منطقی نیست، چون آزمون داریم
                # CUR.execute("UPDATE quiz_questions SET is_active = 0") 
                
                CUR.execute(
                    "INSERT INTO quiz_questions(question_text, option_a, option_b, option_c, option_d, correct_option, rationale_text, created_by, created_at, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    (question, o_a, o_b, o_c, o_d, correct, rationale, uid, datetime.utcnow().isoformat())
                )
                DB.commit()
                await update.message.reply_text("✅ سوال آزمون (با پاسخ تشریحی) با موفقیت ثبت و فعال شد.")
                context.user_data.pop("state", None)
                await admin_quiz_panel_handler(update, context, query_message=update.message)

            except Exception as e:
                logger.error(f"Admin quiz add error: {e}")
                await update.message.reply_text(f"❌ خطا: {e}\n\n"
                                                "لطفاً در فرمت دقیق 7 بخشی (جدا شده با |) ارسال کنید:\n"
                                                "سوال؟ | الف | ب | ج | د | پاسخ (a/b) | پاسخ تشریحی کامل")
            return

        # --- حالت افزودن نکته حقوقی ---
        if state == "awaiting_new_legal_tip":
            try:
                if len(text) < 10: raise ValueError("نکته 너무 کوتاه است")
                CUR.execute("INSERT INTO legal_tips(tip_text, added_by, created_at) VALUES (?, ?, ?)",
                            (text, uid, datetime.utcnow().isoformat()))
                DB.commit()
                await update.message.reply_text("✅ نکته حقوقی با موفقیت ثبت شد.")
                context.user_data.pop("state", None)
                await admin_manage_tips_handler(update, context, query_message=update.message)
            except Exception as e:
                logger.error(f"Admin add tip error: {e}")
                await update.message.reply_text(f"❌ خطا در ثبت نکته: {e}")
            return
        
        # --- حالت پیام همگانی ---
        if state == "awaiting_broadcast":
            context.user_data.pop("state", None)
            CUR.execute("SELECT user_id FROM users")
            rows = CUR.fetchall()
            await update.message.reply_text(f"⏳ شروع ارسال پیام به {len(rows)} کاربر...")
            count = 0
            for r in rows:
                try:
                    await context.bot.send_message(chat_id=r["user_id"], text=text)
                    count += 1
                except Exception:
                    logger.warning("Failed to send broadcast to %s", r["user_id"])
                await asyncio.sleep(0.05)
            await update.message.reply_text(f"✅ پیام همگانی با موفقیت به {count} نفر از {len(rows)} کاربر ارسال شد.")
            await admin_panel_handler(update, context)
            return

        # --- حالت جستجوی کاربر ---
        if state == "awaiting_user_search":
            context.user_data.pop("state", None)
            try:
                target_uid = int(text)
                CUR.execute("SELECT * FROM users WHERE user_id = ?", (target_uid,))
                user_row = CUR.fetchone()
                if not user_row:
                    await update.message.reply_text(f"❌ کاربری با آیدی {target_uid} یافت نشد.")
                    return
                
                msg = (
                    f"👤 **اطلاعات کاربر {target_uid}**\n"
                    f"نام: {user_row['first_name']}\n"
                    f"یوزرنیم: @{user_row['username'] or '---'}\n"
                    f"عضویت: {user_row['joined_at'].split('T')[0]}\n"
                    f"شخصیت AI: {user_row['ai_personality']}\n"
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"📜 مشاهده تاریخچه {target_uid}", callback_data=f"admin_view_user_history_{target_uid}")],
                    [InlineKeyboardButton("🔙 بازگشت به پنل اصلی", callback_data="admin_main")]
                ])
                await update.message.reply_text(msg, reply_markup=kb)
                
            except ValueError:
                await update.message.reply_text("❌ لطفاً فقط آیدی عددی کاربر را وارد کنید.")
            except Exception as e:
                await update.message.reply_text(f"❌ خطای جستجو: {e}")
            return

        # --- حالت افزودن ادمین ---
        if state == "awaiting_new_admin_id":
            context.user_data.pop("state", None)
            try:
                target_uid = int(text)
                if target_uid == SUPER_ADMIN_ID: raise ValueError("ادمین کل قابل افزودن نیست")
                CUR.execute("INSERT INTO admins(user_id, added_by, added_at) VALUES (?, ?, ?)",
                            (target_uid, uid, datetime.utcnow().isoformat()))
                DB.commit()
                await update.message.reply_text(f"✅ کاربر {target_uid} با موفقیت به لیست ادمین‌ها اضافه شد.")
                await admin_manage_admins_handler(update, context, query_message=update.message)
            except sqlite3.IntegrityError:
                await update.message.reply_text(f"❌ کاربر {target_uid} از قبل ادمین بوده است.")
            except Exception as e:
                await update.message.reply_text(f"❌ خطای افزودن ادمین: {e}")
            return

        # --- حالت حذف ادمین ---
        if state == "awaiting_remove_admin_id":
            context.user_data.pop("state", None)
            try:
                target_uid = int(text)
                if target_uid == SUPER_ADMIN_ID: raise ValueError("ادمین کل قابل حذف نیست")
                CUR.execute("DELETE FROM admins WHERE user_id = ?", (target_uid,))
                DB.commit()
                if CUR.rowcount > 0:
                    await update.message.reply_text(f"✅ کاربر {target_uid} با موفقیت از لیست ادمین‌ها حذف شد.")
                else:
                    await update.message.reply_text(f"❌ کاربر {target_uid} در لیست ادمین‌ها نبود.")
                await admin_manage_admins_handler(update, context, query_message=update.message)
            except Exception as e:
                await update.message.reply_text(f"❌ خطای حذف ادمین: {e}")
            return
            
        # --- حالت افزودن کانال ---
        if state == "awaiting_new_channel_username":
            context.user_data.pop("state", None)
            try:
                channel_username = text.strip().replace("@", "")
                if not channel_username: raise ValueError("یوزرنیم خالی است")
                CUR.execute("INSERT INTO channels(channel_id, added_by, added_at) VALUES (?, ?, ?)",
                            (channel_username, uid, datetime.utcnow().isoformat()))
                DB.commit()
                await update.message.reply_text(f"✅ کانال @{channel_username} با موفقیت به لیست عضویت اجباری اضافه شد.")
                await admin_manage_channels_handler(update, context, query_message=update.message)
            except sqlite3.IntegrityError:
                await update.message.reply_text(f"❌ کانال @{channel_username} از قبل موجود است.")
            except Exception as e:
                await update.message.reply_text(f"❌ خطای افزودن کانال: {e}")
            return

        # --- حالت حذف کانال ---
        if state == "awaiting_remove_channel_username":
            context.user_data.pop("state", None)
            try:
                channel_username = text.strip().replace("@", "")
                if not channel_username: raise ValueError("یوزرنیم خالی است")
                CUR.execute("DELETE FROM channels WHERE channel_id = ?", (channel_username,))
                DB.commit()
                if CUR.rowcount > 0:
                    await update.message.reply_text(f"✅ کانال @{channel_username} با موفقیت از لیست حذف شد.")
                else:
                    await update.message.reply_text(f"❌ کانال @{channel_username} در لیست وجود نداشت.")
                await admin_manage_channels_handler(update, context, query_message=update.message)
            except Exception as e:
                await update.message.reply_text(f"❌ خطای حذف کانال: {e}")
            return

    # --- منطق کاربر: حالت پیش‌نویس قرارداد ---
    if state == "awaiting_draft_request":
        await update.message.reply_text("⏳ در حال تنظیم پیش‌نویس...")
        answer = await ask_ai(
            user_id=uid,
            prompt=f"یک پیش‌نویس قرارداد کامل و دقیق برای موضوع زیر بنویس: '{text}'. تمام مواد لازم، تعهدات طرفین و شرایط فسخ را ذکر کن.",
            system="شما یک وکیل متخصص در تنظیم قرارداد هستید. باید پیش‌نویس‌های کامل و حرفه‌ای ارائه دهید."
        )
        save_history(uid, "user", "پیش‌نویس", text)
        save_history(uid, "bot", "پاسخ پیش‌نویس", answer)
        await update.message.reply_text(answer + LEGAL_DISCLAIMER, reply_markup=current_menu)
        context.user_data.pop("state", None)
        return

    # --- منطق کاربر: حالت واژه‌نامه حقوقی ---
    if state == "awaiting_term":
        await update.message.reply_text("⏳ در حال جستجوی اصطلاح...")
        answer = await ask_ai(
            user_id=uid,
            prompt=f"اصطلاح حقوقی '{text}' را به زبان ساده فارسی برای یک فرد غیرحقوقی توضیح بده.",
            system="شما یک فرهنگ‌نامه حقوقی هستید که اصطلاحات را به زبان ساده توضیح می‌دهید."
        )
        save_history(uid, "user", "واژه‌نامه", text)
        save_history(uid, "bot", "پاسخ واژه‌نامه", answer)
        await update.message.reply_text(answer + LEGAL_DISCLAIMER, reply_markup=current_menu)
        context.user_data.pop("state", None)
        return
    
    # --- منطق محاسبه‌گرها ---
    if state == "awaiting_enforcement_calc":
        try:
            amount = float(text.replace(",", "").strip())
            cost = amount * 0.05
            msg = (
                f"🧮 محاسبه هزینه اجرای احکام:\n\n"
                f"مبلغ محکوم به: {int(amount):,} ریال\n"
                f"هزینه اجرا (نیم عشر): {int(cost):,} ریال"
            )
            await update.message.reply_text(msg, reply_markup=current_menu)
        except Exception:
            await update.message.reply_text("❌ فرمت اشتباه. لطفاً فقط مبلغ را به ریال وارد کنید.", reply_markup=current_menu)
        context.user_data.pop("state", None)
        return

    if state == "awaiting_late_payment_calc":
        await update.message.reply_text("⏳ در حال محاسبه خسارت بر اساس شاخص بانک مرکزی...")
        answer = await ask_ai(
            user_id=uid,
            prompt=f"خسارت تاخیر تادیه را برای این مورد محاسبه کن: '{text}'. فرمول و شاخص مورد استفاده را ذکر کن.",
            system="شما یک متخصص امور مالی و حقوقی هستید که با استفاده از شاخص‌های بانک مرکزی ایران، خسارت تاخیر تادیه را محاسبه می‌کنید. حتماً ذکر کنید که این محاسبه تخمینی است."
        )
        await update.message.reply_text(answer + LEGAL_DISCLAIMER, reply_markup=current_menu)
        context.user_data.pop("state", None)
        return

    if state == "awaiting_diyah_calc":
        await update.message.reply_text("⏳ در حال محاسبه دیه بر اساس نرخ روز...")
        answer = await ask_ai(
            user_id=uid,
            prompt=f"دیه را برای مورد زیر محاسبه کن: '{text}'. لطفاً نرخ دیه کامل سال جاری (۱۴۰۴) و اینکه آیا ماه حرام (در صورت ذکر) تاثیر داشته است را ذکر کن.",
            system="شما یک کارشناس رسمی دادگستری مسلط به قوانین دیه (مجازات اسلامی) هستید. شما مبلغ دیه کامل مرد در سال 1404 در ماه عادی را 1 میلیارد و 400 میلیون تومان و در ماه حرام 1 میلیارد و 800 میلیون تومان در نظر می‌گیرید."
        )
        await update.message.reply_text(answer + LEGAL_DISCLAIMER, reply_markup=current_menu)
        context.user_data.pop("state", None)
        return

    if state == "awaiting_inheritance_calc":
        await update.message.reply_text("⏳ در حال تحلیل طبقات و درجات و محاسبه سهم‌الارث...")
        answer = await ask_ai(
            user_id=uid,
            prompt=f"سهم‌الارث را برای بازماندگان زیر محاسبه کن: '{text}'. لطفاً طبقه و سهم هر فرد را به تفکیک مشخص کن.",
            system="شما یک متخصص ارشد حقوقی مسلط به قانون مدنی ایران در باب ارث هستید. محاسبات را دقیق و بر اساس طبقات و درجات انجام دهید."
        )
        await update.message.reply_text(answer + LEGAL_DISCLAIMER, reply_markup=current_menu)
        context.user_data.pop("state", None)
        return

    if state == "awaiting_dadrasi_calc":
        try:
            amount = float(text.replace(",", "").strip())
            threshold = 200_000_000
            rate1 = 0.035
            rate2 = 0.025 

            if amount <= threshold:
                cost_badavi = amount * rate1
            else:
                cost_badavi = (threshold * rate1) + ((amount - threshold) * rate2)
            
            cost_tajdid = cost_badavi * 1.5
            
            msg = (
                f"🧾 **محاسبه هزینه دادرسی (تخمینی)**\n\n"
                f"مبلغ خواسته: {int(amount):,} ریال\n\n"
                f"هزینه مرحله بدوی (اولیه): {int(cost_badavi):,} ریال\n"
                f"هزینه مرحله تجدیدنظر (تقریبی): {int(cost_tajdid):,} ریال\n\n"
                f"توجه: این محاسبه بر اساس فرمول ارائه شده (۳.۵٪ تا ۲۰م ت و ۲.۵٪ مازاد) است."
            )
            await update.message.reply_text(msg, reply_markup=current_menu)

        except Exception as e:
            await update.message.reply_text(f"❌ فرمت اشتباه. لطفاً فقط مبلغ خواسته را به ریال وارد کنید. {e}", reply_markup=current_menu)
        context.user_data.pop("state", None)
        return

    if state == "awaiting_my_case_details":
        try:
            parts = {k.strip(): v.strip() for k, v in (p.split(":", 1) for p in text.split("|"))}
            title = parts.get("عنوان", "بدون عنوان")
            case_num = parts.get("شماره", "---")
            branch = parts.get("شعبه", "---")
            notes = parts.get("یادداشت", "---")

            CUR.execute(
                "INSERT INTO my_cases(user_id, title, case_number, branch, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (uid, title, case_num, branch, notes, datetime.utcnow().isoformat())
            )
            DB.commit()
            await update.message.reply_text(f"✅ پرونده '{title}' با موفقیت در دفترچه شما ذخیره شد.", reply_markup=current_menu)

        except Exception as e:
            logger.error(f"MyCase add error: {e}")
            await update.message.reply_text("❌ خطا در فرمت ورودی. لطفاً از فرمت پیشنهادی استفاده کنید.",
                                            reply_markup=current_menu)
        context.user_data.pop("state", None)
        return

    if state == "awaiting_mehrieh_calc":
        try:
            count = int(text.split()[0])
            if count <= 0: raise ValueError
        except Exception:
            await update.message.reply_text("❌ فرمت اشتباه. یک عدد مثبت (مانند 110) وارد کنید.", reply_markup=current_menu)
            context.user_data.pop("state", None)
            return
        
        await update.message.reply_text("⏳ در حال دریافت آخرین نرخ سکه...")
        rate = await fetch_tgju_sekee_rate()
        if rate is None: 
            rate = get_last_rate()
        
        if rate is None:
            await update.message.reply_text("❌ موفق به دریافت نرخ لحظه‌ای سکه نشدم. لطفاً چند دقیقه دیگر تلاش کنید.", reply_markup=current_menu)
            context.user_data.pop("state", None)
            return
            
        total_riyals = int(count * rate)
        total_toman = total_riyals // 10
        msg = (
            f"💰 محاسبه مهریه (به نرخ روز)\n\n"
            f"تعداد سکه: {count} عدد\n"
            f"نرخ هر سکه: {rate:,} ریال\n"
            f"مبلغ کل: {total_riyals:,} ریال\n"
            f"مبلغ به تومان: {total_toman:,} تومان"
        )
        await update.message.reply_text(msg, reply_markup=current_menu)
        context.user_data.pop("state", None)
        return

    if state == "awaiting_categorized_question":
        await update.message.reply_text("⏳ در حال تحلیل سوال شما...")
        
        category = context.user_data.pop("question_category", "عمومی")
        full_prompt = f"در موضوع: {category}. سوال: {text}"
        
        chat_history = get_chat_history(uid, subject_tag="حقوقی", limit=CHAT_HISTORY_LIMIT)
        answer = await ask_ai(uid, full_prompt, chat_history=chat_history)
        
        save_history(uid, "user", "پرسش حقوقی", full_prompt)
        save_history(uid, "bot", "پاسخ حقوقی", answer)
        
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("👍", callback_data="like"), InlineKeyboardButton("👎", callback_data="dislike")]])
        await update.message.reply_text(answer + LEGAL_DISCLAIMER, reply_markup=kb)
        context.user_data.pop("state", None)
        return

    if state == "awaiting_checklist_request":
        await update.message.reply_text("⏳ در حال تولید چک‌لیست...")
        answer = await ask_ai(
            user_id=uid,
            prompt=f"لطفاً یک چک‌لیست کامل از تمام مدارک لازم و مراحل اجرایی برای مورد زیر تهیه کن: '{text}'",
            system="شما یک دستیار حقوقی فوق‌العاده دقیق هستید که چک‌لیست‌های (Checklist) مرحله به مرحله و کامل تهیه می‌کنید."
        )
        save_history(uid, "user", "چک‌لیست", text)
        save_history(uid, "bot", "پاسخ چک‌لیست", answer)
        await update.message.reply_text(answer + LEGAL_DISCLAIMER, reply_markup=current_menu)
        context.user_data.pop("state", None)
        return

    if state == "awaiting_simulator_case":
        await update.message.reply_text("⏳ در حال ورود به شبیه‌ساز... لطفاً صبر کنید...")
        save_history(uid, "user", "پرونده شبیه‌ساز", text)
        
        answer = await ask_ai(
            user_id=uid,
            prompt=f"شما قاضی هستید. من پرونده‌ام را اینطور مطرح می‌کنم: '{text}'. لطفاً جلسه دادگاه را شروع کنید.",
            system="شما قاضی یک دادگاه هستید. قاطع، رسمی و دقیق صحبت کنید. کاربر پرونده خود را مطرح کرده است. شما باید جلسه را مدیریت کنید.",
            chat_history=[]
        )
        
        save_history(uid, "bot", "پاسخ شبیه‌ساز", answer)
        await update.message.reply_text(f"⚖️ **شبیه‌ساز دادگاه (نقش شما: قاضی)**\n\n{answer}\n\n(جلسه شروع شد. پاسخ خود را بنویسید.)", 
                                        reply_markup=ReplyKeyboardMarkup([["❌ پایان شبیه‌سازی"]], resize_keyboard=True, one_time_keyboard=True))
        context.user_data["state"] = "in_simulator_session"
        return

    if state == "in_simulator_session":
        await update.message.reply_text("⏳ (قاضی در حال بررسی...)")
        
        chat_history = get_chat_history(uid, subject_tag="simulator", limit=CHAT_HISTORY_LIMIT)
        save_history(uid, "user", "پرونده شبیه‌ساز", text)

        answer = await ask_ai(
            user_id=uid,
            prompt=text,
            system="شما قاضی یک دادگاه هستید. قاطع، رسمی و دقیق صحبت کنید. به صحبت‌های کاربر پاسخ دهید و جلسه را ادامه دهید.",
            chat_history=chat_history
        )
        
        save_history(uid, "bot", "پاسخ شبیه‌ساز", answer)
        await update.message.reply_text(answer, 
                                        reply_markup=ReplyKeyboardMarkup([["❌ پایان شبیه‌سازی"]], resize_keyboard=True, one_time_keyboard=True))
        return
        
    if state == "awaiting_smart_template_subject":
        subject = update.message.text
        context.user_data["smart_template_subject"] = subject
        await update.message.reply_text(f"موضوع: **{subject}**\n\nعالی. حالا لطفاً اطلاعات کلیدی و طرفین قرارداد را وارد کنید:", 
                                        reply_markup=ReplyKeyboardMarkup([["🔙 بازگشت به منو"]], resize_keyboard=True, one_time_keyboard=True))
        context.user_data["state"] = "awaiting_smart_template_details"
        return

    if state == "awaiting_smart_template_details":
        subject = context.user_data.pop("smart_template_subject", "نامشخص")
        details = update.message.text
        await update.message.reply_text("⏳ در حال تنظیم پیش‌نویس قرارداد هوشمند... (این ممکن است کمی طول بکشد)")
        
        full_prompt = f"یک پیش‌نویس قرارداد کامل و دقیق برای موضوع '{subject}' با جزئیات زیر تنظیم کن: '{details}'. تمام مواد قانونی لازم را ذکر کن."
        
        answer = await ask_ai(uid, 
                              prompt=full_prompt, 
                              system="شما یک وکیل ارشد متخصص در تنظیم قراردادهای حقوقی در ایران هستید.")
        
        save_history(uid, "user", "قرارداد هوشمند", full_prompt)
        save_history(uid, "bot", "پاسخ قرارداد هوشمند", answer)
        
        await update.message.reply_text(answer + LEGAL_DISCLAIMER, reply_markup=current_menu)
        context.user_data.pop("state", None)
        return

    if state == "awaiting_report":
        report_id = create_report(uid, text)
        if SUPER_ADMIN_ID:
            try:
                await context.bot.send_message(
                    chat_id=SUPER_ADMIN_ID, 
                    text=f"📩 گزارش جدید (ID: {report_id}) از {user.first_name} (@{user.username or 'ندارد'})\n🆔 {uid}\n\n{text}",
                )
                await context.bot.send_message(chat_id=SUPER_ADMIN_ID, text="(برای پاسخگویی به پنل /admin بخش 'مدیریت گزارش‌ها' مراجعه کنید.)")
            except Exception: logger.exception("failed to notify admin")
        await update.message.reply_text("✅ گزارش شما ثبت شد.", reply_markup=current_menu)
        context.user_data.pop("state", None)
        return

    if state == "adding_reminder":
        try:
            if ":" not in text: raise ValueError("format")
            title, datepart = text.split(":", 1)
            add_reminder(uid, title.strip(), datepart.strip())
            await update.message.reply_text(f"✅ یادآوری '{title.strip()}' ثبت شد.", reply_markup=current_menu)
        except Exception:
            await update.message.reply_text("❌ فرمت اشتباه. مثال: قرار: 2025-12-20 14:30", reply_markup=current_menu)
        context.user_data.pop("state", None)
        return
    
    # ... (سایر حالت‌های محاسبه‌گر ساده حذف شده از فایل اصلی شما در اینجا قرار می‌گرفتند) ...

    # --- دکمه‌های منوی اصلی ---
    
    if text == "🧾 پرسش حقوقی (با حافظه)":
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚖️ خانواده (طلاق، مهریه، ارث)", callback_data="category_خانواده و ارث"),
                InlineKeyboardButton("🏛️ ملکی (اجاره، خرید و فروش)", callback_data="category_ملکی و قراردادها")
            ],
            [
                InlineKeyboardButton("👮 کیفری (کلاهبرداری، سرقت)", callback_data="category_کیفری"),
                InlineKeyboardButton("💰 مالی (چک، سفته، دیه)", callback_data="category_مالی و تجاری")
            ],
            [
                InlineKeyboardButton("🚗 تصادفات و بیمه", callback_data="category_تصادفات و بیمه"),
                InlineKeyboardButton("✍️ سایر موضوعات (متنی)", callback_data="category_عمومی")
            ]
        ])
        await update.message.reply_text("📚 لطفاً ابتدا موضوع سوال حقوقی خود را انتخاب کنید:", reply_markup=kb)
        return

    if text == "📨 ارسال گزارش":
        await update.message.reply_text("📝 لطفاً متن گزارش را بنویس:", reply_markup=ReplyKeyboardMarkup([["🔙 بازگشت به منو"]], resize_keyboard=True, one_time_keyboard=True))
        context.user_data["state"] = "awaiting_report"
        return

    if text == "📄 تحلیل سند (PDF/DOCX)":
        await update.message.reply_text("✍️ لطفاً فایل PDF یا DOCX خود را برای تحلیل ارسال کنید:", reply_markup=ReplyKeyboardMarkup([["🔙 بازگشت به منو"]], resize_keyboard=True, one_time_keyboard=True))
        context.user_data["state"] = "awaiting_document"
        return

    if text == "📝 پیش‌نویس": 
        await update.message.reply_text("✍️ موضوع قرارداد مورد نیاز خود را بنویسید (مثال: اجاره‌نامه خودرو):", reply_markup=ReplyKeyboardMarkup([["🔙 بازگشت به منو"]], resize_keyboard=True, one_time_keyboard=True))
        context.user_data["state"] = "awaiting_draft_request"
        return

    if text == "📚 واژه‌نامه": 
        await update.message.reply_text("✍️ لطفاً اصطلاح حقوقی مورد نظر خود را بنویسید (مانند: سرقفلی):", reply_markup=ReplyKeyboardMarkup([["🔙 بازگشت به منو"]], resize_keyboard=True, one_time_keyboard=True))
        context.user_data["state"] = "awaiting_term"
        return

    if text == "📄 دستیار هوشمند قرارداد":
        await update.message.reply_text("⚖️ **دستیار هوشمند قرارداد**\n\nموضوع قرارداد را بنویسید:", 
                                        reply_markup=ReplyKeyboardMarkup([["🔙 بازگشت به منو"]], resize_keyboard=True, one_time_keyboard=True))
        context.user_data["state"] = "awaiting_smart_template_subject"
        return

    if text == "🔔 آخرین اخبار":
        await update.message.reply_text("⏳ در حال جستجوی آخرین اخبار و مصوبات حقوقی...")
        answer = await ask_ai(
            user_id=uid,
            prompt="آخرین مصوبات مجلس، آرای وحدت رویه جدید، و اخبار مهم حقوقی روز ایران را در 3 مورد بسیار کوتاه و خلاصه (هر کدام یک خط) برای من لیست کن.",
            system="شما یک دستیار حقوقی هستید که به اخبار روز مسلط است."
        )
        await update.message.reply_text(f"🔔 **آخرین اخبار حقوقی (به روایت AI)**\n\n{answer}\n\n" + LEGAL_DISCLAIMER, reply_markup=current_menu)
        return

    if text == "🗂️ پرونده‌های من":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗒️ مشاهده همه‌ی پرونده‌ها", callback_data="list_my_cases")],
            [InlineKeyboardButton("➕ افزودن پرونده جدید", callback_data="add_my_case")]
        ])
        await update.message.reply_text("🗂️ **دفترچه یادداشت پرونده‌های من**", reply_markup=kb)
        return
        
    if text == "⚖️ آزمون حقوقی":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⁉️ شروع/ادامه آزمون", callback_data="quiz_start")],
            [InlineKeyboardButton("🏆 جدول امتیازات", callback_data="quiz_leaderboard")]
        ])
        await update.message.reply_text("⚖️ **آزمون حقوقی**", reply_markup=kb)
        return
    
    if text == "💡 نکات حقوقی":
        await send_legal_tip(update, context, tip_id=1)
        context.user_data['current_tip_id'] = 1
        return

    if text == "🎙️ تحلیلگر صوتی":
        await update.message.reply_text("🎙️ لطفاً پیام صوتی (Voice Message) خود را ضبط و ارسال کنید:", 
                                        reply_markup=ReplyKeyboardMarkup([["🔙 بازگشت به منو"]], resize_keyboard=True, one_time_keyboard=True))
        context.user_data["state"] = "awaiting_voice_query"
        return
        
    if text == "📋 چک‌لیست پرونده":
        await update.message.reply_text("✍️ لطفاً موضوعی که برای آن نیاز به چک‌لیست دارید را بنویسید (مثال: طلاق توافقی):", 
                                        reply_markup=ReplyKeyboardMarkup([["🔙 بازگشت به منو"]], resize_keyboard=True, one_time_keyboard=True))
        context.user_data["state"] = "awaiting_checklist_request"
        return
        
    if text == "👨‍⚖️ شبیه‌ساز دادگاه":
        await update.message.reply_text("✍️ به شبیه‌ساز دادگاه خوش آمدید. موضوع پرونده و نقش خود را شرح دهید:", 
                                        reply_markup=ReplyKeyboardMarkup([["🔙 بازگشت به منو"]], resize_keyboard=True, one_time_keyboard=True))
        context.user_data["state"] = "awaiting_simulator_case"
        return

    if text == "⏰ یادآوری‌ها":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 افزودن یادآوری جدید", callback_data="add_reminder")],
            [InlineKeyboardButton("🗒️ مشاهده یادآوری‌ها", callback_data="list_reminders")]
        ])
        await update.message.reply_text("🔔 مدیریت یادآوری‌ها:", reply_markup=kb)
        return

    if text == "🧮 محاسبه‌گر": 
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🪙 محاسبه مهریه (به نرخ روز)", callback_data="calc_mehrieh")],
            [InlineKeyboardButton("⚖️ محاسبه دیه (هوشمند)", callback_data="calc_diyah")],
            [InlineKeyboardButton("📈 خسارت تاخیر تادیه (هوشمند)", callback_data="calc_late_payment")],
            [InlineKeyboardButton("🏛️ هزینه اجرای احکام (ساده)", callback_data="calc_enforcement")],
            [InlineKeyboardButton("🧾 محاسبه هزینه دادرسی (جدید)", callback_data="calc_dadrasi")],
            [InlineKeyboardButton("👨‍👩‍👧‍👦 محاسبه سهم‌الارث (هوشمند)", callback_data="calc_inheritance")],
        ])
        await update.message.reply_text("🧮 کدام مورد را محاسبه کنم؟", reply_markup=kb)
        return

    if text == "⚙️ تنظیمات":
        settings = get_user_settings(uid)
        p = settings["ai_personality"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{'✅' if p == 'simple' else ''} ساده (عامیانه)", callback_data="set_p_simple")],
            [InlineKeyboardButton(f"{'✅' if p == 'default' else ''} متوسط (پیش‌فرض)", callback_data="set_p_default")],
            [InlineKeyboardButton(f"{'✅' if p == 'technical' else ''} فنی (مستند)", callback_data="set_p_technical")]
        ])
        await update.message.reply_text("⚙️ شخصیت ربات را برای پاسخگویی انتخاب کنید:", reply_markup=kb)
        return

    if text == "👤 پروفایل من":
        CUR.execute("SELECT joined_at FROM users WHERE user_id=?", (uid,))
        row = CUR.fetchone()
        joined = row["joined_at"].split("T")[0] if row else "نامشخص"
        
        CUR.execute("SELECT COUNT(*) as c FROM reminders WHERE user_id=?", (uid,))
        rem_count = CUR.fetchone()["c"]
        CUR.execute("SELECT COUNT(*) as c FROM reports WHERE user_id=?", (uid,))
        rep_count = CUR.fetchone()["c"]
        
        # (جدید) دریافت امتیاز آزمون
        quiz_score = get_user_score(uid)
        
        await update.message.reply_text(
            f"👤 نام: {user.first_name or ''}\n"
            f"یوزرنیم: @{user.username or 'ندارد'}\n"
            f"آیدی: {uid}\n"
            f"زمان عضویت: {joined}\n"
            f"🏆 امتیاز آزمون: {quiz_score}\n" # (جدید)
            f"یادآوری‌ها: {rem_count}\n"
            f"گزارش‌ها: {rep_count}",
            reply_markup=current_menu
        )
        return
        
    if is_admin(uid) and not state:
        await update.message.reply_text("دستور شما در منوی اصلی موجود نیست. \nبرای پنل مدیریت /admin را ارسال کنید.", reply_markup=current_menu)
        return
        
    await update.message.reply_text("لطفاً یکی از گزینه‌های منو را انتخاب کنید 👇", reply_markup=current_menu)

# ---------- Document Handler ----------
@rate_limited
async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    doc = update.message.document
    state = context.user_data.get("state")
    current_menu = MAIN_MENU

    if state == "awaiting_document":
        if update.message.text and update.message.text == "🔙 بازگشت به منو":
            context.user_data.clear()
            await update.message.reply_text("منوی اصلی:", reply_markup=MAIN_MENU)
            return

    if state != "awaiting_document":
        logger.info(f"User {uid} sent a document without being in 'awaiting_document' state.")
        return

    file_name = doc.file_name.lower()
    if not (file_name.endswith('.pdf') or file_name.endswith('.docx')):
        await update.message.reply_text("❌ فقط فایل‌های PDF و DOCX پشتیبانی می‌شوند.", reply_markup=current_menu)
        return

    await update.message.reply_text(f"⏳ فایل '{doc.file_name}' دریافت شد. در حال دانلود و استخراج متن...")
    
    file = await doc.get_file()
    text_content = ""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, doc.file_name)
        await file.download_to_drive(path)
        
        if file_name.endswith('.pdf'):
            text_content = extract_pdf_text(path)
        elif file_name.endswith('.docx'):
            text_content = extract_docx_text(path)
    
    if not text_content or len(text_content.strip()) < 20:
        await update.message.reply_text("❌ متنی از فایل استخراج نشد.", reply_markup=current_menu)
        context.user_data.pop("state", None)
        return

    await update.message.reply_text(f"✅ متن با موفقیت استخراج شد. در حال ارسال به هوش مصنوعی...")
    
    max_len = 8000
    if len(text_content) > max_len:
        text_content = text_content[:max_len] + "\n\n... (متن به دلیل طولانی بودن کوتاه شد)"

    answer = await ask_ai(
        user_id=uid,
        prompt=f"متن سند زیر را به دقت تحلیل حقوقی کن، نکات کلیدی، تعهدات طرفین و ریسک‌های احتمالی آن را مشخص کن:\n\n{text_content}",
        system="شما یک وکیل ارشد هستید که در تحلیل و خلاصه‌سازی اسناد حقوقی و قراردادها تخصص دارید."
    )
    
    save_history(uid, "user", "تحلیل سند", file_name)
    save_history(uid, "bot", "پاسخ تحلیل سند", answer)
    
    await update.message.reply_text(answer + LEGAL_DISCLAIMER, reply_markup=current_menu)
    context.user_data.pop("state", None)

# ---------- Voice Handler ----------
@rate_limited
async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    voice = update.message.voice
    state = context.user_data.get("state")
    current_menu = MAIN_MENU

    if state == "awaiting_voice_query":
        if update.message.text and update.message.text == "🔙 بازگشت به منو":
            context.user_data.clear()
            await update.message.reply_text("منوی اصلی:", reply_markup=MAIN_MENU)
            return
            
    if state != "awaiting_voice_query":
        logger.info(f"User {uid} sent a voice message without being in 'awaiting_voice_query' state.")
        if state is None:
            await update.message.reply_text("برای تحلیل پیام صوتی، لطفاً ابتدا دکمه '🎙️ تحلیلگر صوتی' را انتخاب کنید.", reply_markup=current_menu)
        return

    if not await check_membership(uid, context):
        await send_join_request_for_user(update)
        return

    await update.message.reply_text("⏳ پیام صوتی دریافت شد. در حال دانلود و ارسال برای تبدیل به متن...")

    try:
        file = await voice.get_file()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, f"voice_{uid}.ogg")
            await file.download_to_drive(path)
            await update.message.reply_text("✅ دانلود کامل شد. در حال پردازش صوت (Whisper)...")
            
            with open(path, "rb") as audio_file:
                transcription = await asyncio.to_thread(
                    GROQ_client.audio.transcriptions.create,
                    model="whisper-large-v3",
                    file=audio_file,
                )
            
            transcribed_text = transcription.text
            if not transcribed_text or len(transcribed_text.strip()) < 2:
                await update.message.reply_text("❌ متنی از صوت استخراج نشد.", reply_markup=current_menu)
                context.user_data.pop("state", None)
                return

    except Exception as e:
        logger.error(f"Voice transcription error: {e}")
        await update.message.reply_text(f"❌ خطا در پردازش فایل صوتی: {e}", reply_markup=current_menu)
        context.user_data.pop("state", None)
        return
        
    await update.message.reply_text(f"**متن استخراج شده:**\n'{transcribed_text}'\n\n⏳ در حال ارسال متن به هوش مصنوعی...")
    
    category = "عمومی (صوتی)"
    full_prompt = f"در موضوع: {category}. سوال: {transcribed_text}"
    chat_history = get_chat_history(uid, subject_tag="حقوقی", limit=CHAT_HISTORY_LIMIT)
    answer = await ask_ai(uid, full_prompt, chat_history=chat_history)
    
    save_history(uid, "user", "پرسش حقوقی", full_prompt)
    save_history(uid, "bot", "پاسخ حقوقی", answer)
    
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("👍", callback_data="like"), InlineKeyboardButton("👎", callback_data="dislike")]])
    await update.message.reply_text(answer + LEGAL_DISCLAIMER, reply_markup=current_menu)
    context.user_data.pop("state", None)

# ---------- Admin Panel Handlers ----------

def build_admin_menu(menu_type: str = "main", user_id: int = 0) -> InlineKeyboardMarkup:
    kb = []
    if menu_type == "main":
        kb = [
            [InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats")],
            [InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast")],
            [InlineKeyboardButton("📨 مدیریت گزارش‌ها", callback_data="admin_reports")],
            [InlineKeyboardButton("👤 مدیریت کاربران", callback_data="admin_users")],
            [InlineKeyboardButton("⚙️ تنظیمات ربات", callback_data="admin_settings")], 
            [InlineKeyboardButton("❌ بستن پنل", callback_data="admin_close")]
        ]
    elif menu_type == "settings": 
        kb.append([InlineKeyboardButton("📢 مدیریت کانال‌ها", callback_data="admin_manage_channels")])
        if user_id == SUPER_ADMIN_ID:
             kb.append([InlineKeyboardButton("🛂 مدیریت ادمین‌ها", callback_data="admin_manage_admins")])
        kb.append([InlineKeyboardButton("⁉️ مدیریت آزمون", callback_data="admin_manage_quiz")]) 
        kb.append([InlineKeyboardButton("💡 مدیریت نکات حقوقی", callback_data="admin_manage_tips")]) 
        kb.append([InlineKeyboardButton("🔙 بازگشت به پنل اصلی", callback_data="admin_main")])
        
    elif menu_type == "manage_admins": 
        kb = [
            [InlineKeyboardButton("➕ افزودن ادمین", callback_data="admin_add_admin")],
            [InlineKeyboardButton("➖ حذف ادمین", callback_data="admin_remove_admin")],
            [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="admin_settings")]
        ]
    
    elif menu_type == "manage_channels": 
        kb = [
            [InlineKeyboardButton("➕ افزودن کانال", callback_data="admin_add_channel")],
            [InlineKeyboardButton("➖ حذف کانال", callback_data="admin_remove_channel")],
            [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="admin_settings")]
        ]
        
    elif menu_type == "manage_quiz": 
        kb = [
            [InlineKeyboardButton("➕ افزودن سوال جدید", callback_data="admin_add_quiz")],
            [InlineKeyboardButton("❌ غیرفعال کردن همه‌ی سوالات", callback_data="admin_clear_quiz")],
            [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="admin_settings")]
        ]
        
    elif menu_type == "manage_tips": 
        kb = [
            [InlineKeyboardButton("➕ افزودن نکته جدید", callback_data="admin_add_tip")],
            [InlineKeyboardButton("🔙 بازگشت به تنظیمات", callback_data="admin_settings")]
        ]
        
    elif menu_type in ["stats", "broadcast", "reports", "users"]:
        kb = [[InlineKeyboardButton("🔙 بازگشت به پنل اصلی", callback_data="admin_main")]]
        
    return InlineKeyboardMarkup(kb)

async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("شما ادمین نیستید.", reply_markup=MAIN_MENU)
        return
        
    context.user_data.clear()
    await update.message.reply_text(
        "🔐 **پنل مدیریت ربات**",
        reply_markup=build_admin_menu("main", user.id)
    )

async def show_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE, query: object):
    CUR.execute("SELECT COUNT(*) as c FROM users")
    total_users = CUR.fetchone()["c"]
    today_str = date.today().isoformat()
    CUR.execute("SELECT COUNT(*) as c FROM users WHERE joined_at >= ?", (today_str,))
    today_users = CUR.fetchone()["c"]
    CUR.execute("SELECT COUNT(*) as c FROM history")
    total_history = CUR.fetchone()["c"]
    CUR.execute("SELECT COUNT(*) as c FROM reports WHERE admin_reply IS NULL")
    pending_reports = CUR.fetchone()["c"]
    CUR.execute("SELECT COUNT(*) as c FROM reports")
    total_reports = CUR.fetchone()["c"]

    msg = (
        f"📊 **آمار ربات**\n\n"
        f"👤 **کاربران:** {total_users} (امروز: {today_users})\n"
        f"📨 **گزارش‌ها:** {total_reports} (در انتظار: {pending_reports})\n"
        f"💬 **تاریخچه:** {total_history} پیام"
    )
    await query.edit_message_text(msg, reply_markup=build_admin_menu("stats", query.from_user.id))

async def show_admin_reports(update: Update, context: ContextTypes.DEFAULT_TYPE, query: object = None, query_message: object = None):
    CUR.execute("SELECT R.id, R.content, R.created_at, U.first_name, U.user_id FROM reports R LEFT JOIN users U ON R.user_id = U.user_id WHERE R.admin_reply IS NULL ORDER BY R.id DESC LIMIT 5")
    rows = CUR.fetchall()
    
    msg_part = "📨 **گزارش‌های در انتظار پاسخ** (۵ مورد آخر)\n\n"
    kb_buttons = []
    
    if not rows:
        msg_part += "هیچ گزارش در انتظار پاسخی یافت نشد."
    else:
        for r in rows:
            msg_part += (
                f"--- (ID: {r['id']}) ---\n"
                f"از: {r['first_name']} (ID: {r['user_id']})\n"
                f"متن: {r['content'][:150]}...\n\n"
            )
            kb_buttons.append([
                InlineKeyboardButton(
                    f"✉️ پاسخ به گزارش #{r['id']}", 
                    callback_data=f"admin_reply_to_{r['id']}_{r['user_id']}"
                )
            ])
            
    kb_buttons.append([InlineKeyboardButton("🔙 بازگشت به پنل اصلی", callback_data="admin_main")])
    reply_markup = InlineKeyboardMarkup(kb_buttons)
    
    if query:
        await query.edit_message_text(msg_part, reply_markup=reply_markup)
    elif query_message:
        await query_message.reply_text(msg_part, reply_markup=reply_markup)

async def admin_settings_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, query: object):
    user_id = query.from_user.id
    await query.edit_message_text(
        "⚙️ **تنظیمات ربات**",
        reply_markup=build_admin_menu("settings", user_id)
    )

async def admin_manage_admins_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, query: object = None, query_message: object = None):
    user_id = query.from_user.id if query else query_message.from_user.id
    if user_id != SUPER_ADMIN_ID:
        if query: await query.answer("⛔ فقط ادمین کل به این بخش دسترسی دارد.", show_alert=True)
        return

    CUR.execute("SELECT user_id, added_at FROM admins")
    rows = CUR.fetchall()
    msg = f"🛂 **مدیریت ادمین‌ها**\n\n👑 **ادمین کل:** `{SUPER_ADMIN_ID}`\n\n👥 **ادمین‌های ثانویه:**\n"
    
    if not rows:
        msg += "(هیچ ادمین ثانویه‌ای اضافه نشده است.)"
    else:
        for r in rows:
            msg += f"  - `{r['user_id']}` (افزوده: {r['added_at'].split('T')[0]})\n"
            
    kb = build_admin_menu("manage_admins", user_id)
    if query:
        await query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    elif query_message:
        await query_message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

async def admin_manage_channels_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, query: object = None, query_message: object = None):
    user_id = query.from_user.id if query else query_message.from_user.id
    channels = get_mandatory_channels()
    msg = "📢 **مدیریت کانال‌های عضویت اجباری**\n\n"
    if not channels:
        msg += "(هیچ کانالی تنظیم نشده است.)"
    else:
        for ch_id in channels:
            msg += f"  - `@{ch_id}`\n"
            
    kb = build_admin_menu("manage_channels", user_id)
    if query:
        await query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    elif query_message:
        await query_message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

async def admin_quiz_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, query: object = None, query_message: object = None):
    """نمایش پنل مدیریت آزمون"""
    user_id = query.from_user.id if query else query_message.from_user.id
    
    CUR.execute("SELECT id, question_text FROM quiz_questions WHERE is_active = 1 ORDER BY id DESC")
    active_qs = CUR.fetchall()
    
    CUR.execute("SELECT COUNT(*) as c FROM quiz_questions")
    total_qs = CUR.fetchone()["c"]
    
    msg = "⁉️ **مدیریت آزمون**\n\n"
    msg += f"تعداد کل سوالات: {total_qs}\n"
    msg += f"تعداد سوالات فعال: {len(active_qs)}\n\n"

    if active_qs:
        msg += f"**آخرین سوال فعال اضافه شده:**\n(ID: {active_qs[0]['id']}) - {active_qs[0]['question_text'][:100]}...\n\n"
    else:
        msg += "(در حال حاضر هیچ سوال فعالی وجود ندارد. کاربران با خطای 'آزمون موجود نیست' مواجه می‌شوند.)\n\n"
            
    kb = build_admin_menu("manage_quiz", user_id)
    if query:
        await query.edit_message_text(msg, reply_markup=kb)
    elif query_message:
        await query_message.reply_text(msg, reply_markup=kb)

async def admin_manage_tips_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, query: object = None, query_message: object = None):
    user_id = query.from_user.id if query else query_message.from_user.id
    CUR.execute("SELECT COUNT(*) as c FROM legal_tips")
    count = CUR.fetchone()["c"]
    CUR.execute("SELECT tip_text FROM legal_tips ORDER BY id DESC LIMIT 1")
    last_tip = CUR.fetchone()
    
    msg = f"💡 **مدیریت نکات حقوقی**\n\nتعداد کل نکات: {count}\n\n"
    if last_tip:
        msg += f"**آخرین نکته:**\n{last_tip['tip_text'][:100]}...\n\n"
    else:
        msg += "(هنوز هیچ نکته‌ای ثبت نشده است.)\n\n"
            
    kb = build_admin_menu("manage_tips", user_id)
    if query:
        await query.edit_message_text(msg, reply_markup=kb)
    elif query_message:
        await query_message.reply_text(msg, reply_markup=kb)

# ---------- Quiz & Tip Senders ----------

# (تغییر یافته) این تابع اکنون سوال بعدی که کاربر ندیده را ارسال می‌کند
async def send_next_quiz_question(message: object, context: ContextTypes.DEFAULT_TYPE, user_id: int): 
    """سوال بعدی آزمون را برای کاربر ارسال می‌کند (یا پیام اتمام)"""
    
    q = await asyncio.to_thread(get_next_quiz_question, user_id)
    
    # (جدید) اگر سوالی باقی نمانده
    if not q:
        user_score = get_user_score(user_id)
        msg = (
            f"🎉 **تبریک!**\n"
            f"شما به تمام سوالات موجود در آزمون پاسخ دادید.\n\n"
            f"🏆 **امتیاز نهایی شما: {user_score}**\n\n"
            "منتظر سوالات جدید باشید. می‌توانید امتیاز خود را در جدول امتیازات یا پروفایل من ببینید."
        )
        # اگر از کال‌بک آمده، پیام را ویرایش کن
        if hasattr(message, 'edit_message_text'):
            await message.edit_message_text(msg, reply_markup=None)
        # اگر از /start آمده، پیام جدید بفرست
        else:
            await message.reply_text(msg, reply_markup=MAIN_MENU)
        return

    # (جدید) شمارش سوالات باقی‌مانده
    CUR.execute("SELECT COUNT(*) as c FROM quiz_questions WHERE is_active = 1 AND id NOT IN (SELECT question_id FROM quiz_user_answers WHERE user_id = ?)", (user_id,))
    remaining = CUR.fetchone()['c']

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"الف) {q['option_a']}", callback_data=f"quiz_answer_{q['id']}_a")],
        [InlineKeyboardButton(f"ب) {q['option_b']}", callback_data=f"quiz_answer_{q['id']}_b")],
        [InlineKeyboardButton(f"ج) {q['option_c']}", callback_data=f"quiz_answer_{q['id']}_c")],
        [InlineKeyboardButton(f"د) {q['option_d']}", callback_data=f"quiz_answer_{q['id']}_d")],
    ])
    
    msg_text = f"⚖️ **آزمون حقوقی** (سوال {q['id']} - {remaining} سوال باقی‌مانده)\n\n**سوال:**\n{q['question_text']}"
    
    # (جدید) منطق ویرایش یا ارسال پیام
    try:
        if hasattr(message, 'edit_message_text'):
            await message.edit_message_text(msg_text, reply_markup=kb)
        else:
            await message.reply_text(msg_text, reply_markup=kb)
    except Exception as e:
        logger.warning(f"Failed to send next quiz question: {e}")
        # اگر ویرایش پیام مشابه قبلی باشد، تلگرام خطا می‌دهد. در این حالت کافیست نادیده بگیریم.


async def send_legal_tip(update: Update, context: ContextTypes.DEFAULT_TYPE, tip_id: int, is_edit: bool = False):
    query = update.callback_query
    message = update.message
    
    try:
        CUR.execute("SELECT tip_text FROM legal_tips WHERE id = ?", (tip_id,))
        row = CUR.fetchone()
        CUR.execute("SELECT COUNT(*) as c FROM legal_tips")
        total_tips = CUR.fetchone()["c"]
        
        if not row:
            if tip_id > 1: 
                if query: await query.answer("شما به پایان نکات رسیدید.", show_alert=True)
                new_id = 1 
                context.user_data['current_tip_id'] = new_id
                CUR.execute("SELECT tip_text FROM legal_tips WHERE id = ?", (new_id,))
                row = CUR.fetchone()
                if not row: 
                    await query.edit_message_text("❌ هنوز هیچ نکته‌ای ثبت نشده است.", reply_markup=None)
                    return
            else: 
                msg = "❌ هنوز هیچ نکته‌ای توسط ادمین ثبت نشده است."
                if is_edit: await query.edit_message_text(msg, reply_markup=None)
                else: await message.reply_text(msg, reply_markup=MAIN_MENU)
                return
        
        msg = f"💡 **نکته حقوقی** ({tip_id} / {total_tips})\n\n{row['tip_text']}"
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➡️ بعدی", callback_data="legal_tip_next"),
                InlineKeyboardButton("⬅️ قبلی", callback_data="legal_tip_prev")
            ]
        ])
        
        if is_edit:
            await query.edit_message_text(msg, reply_markup=kb)
        else:
            await message.reply_text(msg, reply_markup=kb)
            
    except Exception as e:
        logger.error(f"Error sending legal tip: {e}")
        if is_edit: await query.edit_message_text(f"❌ خطایی رخ داد: {e}")
        else: await message.reply_text(f"❌ خطایی رخ داد: {e}")

# ---------- Callback router ----------
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data or ""

    # --- منطق پنل ادمین ---
    if data.startswith("admin_"):
        if not is_admin(uid):
            await query.edit_message_text("⛔ این بخش فقط مختص ادمین است.")
            return

        context.user_data.pop("state", None)

        if data == "admin_main":
            await query.edit_message_text("🔐 **پنل مدیریت ربات**", reply_markup=build_admin_menu("main", uid))
        elif data == "admin_stats":
            await show_admin_stats(update, context, query)
        elif data == "admin_broadcast":
            await query.edit_message_text("✍️ لطفاً پیام مورد نظر خود را برای ارسال همگانی بنویسید:", reply_markup=build_admin_menu("broadcast", uid))
            context.user_data["state"] = "awaiting_broadcast"
        elif data == "admin_reports":
            await show_admin_reports(update, context, query)
        elif data.startswith("admin_reply_to_"):
            parts = data.split("_")
            report_id = int(parts[3])
            target_uid = int(parts[4])
            context.user_data["reply_to_report"] = {"report_id": report_id, "user_id": target_uid}
            context.user_data["state"] = "awaiting_admin_reply"
            await query.edit_message_text(f"✍️ لطفاً متن پاسخ برای گزارش #{report_id} را ارسال کنید:")
        elif data == "admin_users":
            await query.edit_message_text("👤 **مدیریت کاربران**\n\nلطفاً آیدی عددی کاربر را ارسال کنید:", reply_markup=build_admin_menu("users", uid))
            context.user_data["state"] = "awaiting_user_search"
        elif data.startswith("admin_view_user_history_"):
            target_uid = int(data.replace("admin_view_user_history_", ""))
            history = get_chat_history(target_uid, subject_tag="all", limit=5) 
            msg = f"📜 **تاریخچه {target_uid}** (۵ پیام آخر)\n\n"
            if not history:
                msg += "(تاریخچه چت یافت نشد.)"
            else:
                for h in history:
                    role_fa = "کاربر" if h['role'] == 'user' else "ربات"
                    msg += f"**{role_fa}:**\n{h['content'][:100]}...\n---\n"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")]])
            await query.edit_message_text(msg, reply_markup=kb)
        elif data == "admin_settings":
            await admin_settings_handler(update, context, query)
        elif data == "admin_manage_admins":
            await admin_manage_admins_handler(update, context, query)
        elif data == "admin_add_admin":
            if uid != SUPER_ADMIN_ID: return
            await query.edit_message_text("✍️ آیدی عددی ادمین جدید:", reply_markup=build_admin_menu("manage_admins", uid))
            context.user_data["state"] = "awaiting_new_admin_id"
        elif data == "admin_remove_admin":
            if uid != SUPER_ADMIN_ID: return
            await query.edit_message_text("✍️ آیدی عددی ادمین جهت حذف:", reply_markup=build_admin_menu("manage_admins", uid))
            context.user_data["state"] = "awaiting_remove_admin_id"
        elif data == "admin_manage_channels":
            await admin_manage_channels_handler(update, context, query)
        elif data == "admin_add_channel":
            await query.edit_message_text("✍️ یوزرنیم کانال (بدون @):", reply_markup=build_admin_menu("manage_channels", uid))
    if data == "admin_manage_quiz":
        await admin_quiz_panel_handler(update, context, query)
    
    elif data == "admin_add_quiz":
        await query.edit_message_text("✍️ لطفاً اطلاعات سوال را در *یک* پیام و با فرمت 7 بخشی زیر ارسال کنید (با | جدا کنید):\n\n"
                                      "`متن سوال؟ | متن الف | متن ب | متن ج | متن د | پاسخ (a/b/c/d) | پاسخ تشریحی کامل`\n\n"
                                      "مثال: `پایتخت ایران؟ | ... | ... | ... | ... | ب | تهران پایتخت است...`",
                                      parse_mode="Markdown")
        context.user_data["state"] = "awaiting_quiz_question"

    elif data == "admin_clear_quiz":
            CUR.execute("UPDATE quiz_questions SET is_active = 0")
            DB.commit()
            await query.answer("✅ تمام سوالات فعال، غیرفعال شدند.", show_alert=True)
            await admin_quiz_panel_handler(update, context, query)
        elif data == "admin_manage_tips":
            await admin_manage_tips_handler(update, context, query)
        elif data == "admin_add_tip":
            await query.edit_message_text("✍️ لطفاً متن کامل نکته حقوقی جدید را ارسال کنید:")
            context.user_data["state"] = "awaiting_new_legal_tip"
        elif data == "admin_close":
            await query.edit_message_text("✅ پنل مدیریت بسته شد.")
        return

    # --- منطق کال‌بک‌های کاربران ---
    if data == "verify_membership":
        if await check_membership(uid, context):
            await query.edit_message_text("✅ عضویت شما تایید شد.")
            await query.message.reply_text("منوی اصلی فعال شد:", reply_markup=MAIN_MENU)
        else:
            await query.edit_message_text("❌ شما هنوز عضو تمام کانال‌ها نشده‌اید.")
        return

    if data in ("like", "dislike"):
        val = 1 if data == "like" else -1
        save_coin_rate("rating", val)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ نظر شما ثبت شد. متشکریم!")
        return

    if data == "add_reminder":
        await query.edit_message_text("✍️ عنوان و تاریخ را وارد کنید (مثال: قرار: 2025-12-20 14:30)")
        context.user_data["state"] = "adding_reminder"
        return

    if data == "list_reminders":
        CUR.execute("SELECT id, title, remind_at FROM reminders WHERE user_id=? ORDER BY id DESC", (uid,))
        rows = CUR.fetchall()
        if not rows:
            await query.edit_message_text("❌ هنوز یادآوری ثبت نشده است.")
        else:
            lines = [f"#{r['id']} — {r['title']} ➜ {r['remind_at']}" for r in rows]
            await query.edit_message_text("📌 یادآوری‌ها:\n\n" + "\n".join(lines))
        return
    
    if data.startswith("category_"):
        category_name = data.split("_", 1)[1]
        context.user_data["state"] = "awaiting_categorized_question"
        context.user_data["question_category"] = category_name
        await query.edit_message_text(f"موضوع: ⚖️ **{category_name}**\n\n✍️ لطفاً سوال دقیق خود را بنویسید:",
                                      reply_markup=None)
        return

    if data == "list_my_cases":
        CUR.execute("SELECT id, title, case_number, branch FROM my_cases WHERE user_id = ? ORDER BY id DESC", (uid,))
        rows = CUR.fetchall()
        if not rows:
            await query.edit_message_text("❌ شما هنوز هیچ پرونده‌ای ذخیره نکرده‌اید.", 
                                          reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ افزودن", callback_data="add_my_case")]]))
            return
        msg = "🗂️ **پرونده‌های شما:**\n\n"
        for r in rows:
            msg += f"--- (ID: {r['id']}) ---\n**{r['title']}**\nشماره: {r['case_number']} | شعبه: {r['branch']}\n\n"
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ افزودن", callback_data="add_my_case")]]))
        return

    if data == "add_my_case":
        await query.edit_message_text("✍️ فرمت: `عنوان: ... | شماره: ... | شعبه: ... | یادداشت: ...`", parse_mode="Markdown")
        context.user_data["state"] = "awaiting_my_case_details"
        return

    if data.startswith("legal_tip_"):
        action = data.split("_")[2]
        current_id = context.user_data.get('current_tip_id', 1)
        
        if action == "next": new_id = current_id + 1
        elif action == "prev": new_id = max(1, current_id - 1)
        else: return

        context.user_data['current_tip_id'] = new_id
        await send_legal_tip(update, context, tip_id=new_id, is_edit=True)
        return

    if data.startswith("quiz_answer_"):
        try:
            parts = data.split("_")
            q_id = int(parts[2])
            answer = parts[3].strip().lower()
            
            CUR.execute("SELECT 1 FROM quiz_user_answers WHERE user_id = ? AND question_id = ?", (uid, q_id))
            if CUR.fetchone():
                await query.answer("شما قبلاً به این سوال پاسخ داده‌اید.", show_alert=True)
                return

            CUR.execute("SELECT * FROM quiz_questions WHERE id = ?", (q_id,))
            q = CUR.fetchone()
            if not q:
                await query.edit_message_text("❌ این سوال دیگر فعال نیست.")
                return

            is_correct = (answer == q["correct_option"])
            
            # (جدید) ثبت امتیاز اگر پاسخ صحیح بود
            if is_correct:
                increment_user_score(uid, 1) # افزودن 1 امتیاز
            
            CUR.execute(
                "INSERT INTO quiz_user_answers(user_id, question_id, answer, is_correct, answered_at) VALUES (?, ?, ?, ?, ?, ?)",
                (uid, q_id, answer, 1 if is_correct else 0, datetime.utcnow().isoformat())
            )
            DB.commit()
            
            # (تغییر یافته) نمایش پاسخ تشریحی
            msg = f"**سوال:**\n{q['question_text']}\n\n"
            if is_correct:
                msg += f"✅ **پاسخ شما ({answer}) صحیح بود!** (+1 امتیاز)\n\n"
            else:
                correct_text = q[f"option_{q['correct_option']}"]
                msg += f"❌ **پاسخ شما ({answer}) اشتباه بود.**\n\nپاسخ صحیح: ({q['correct_option']}) {correct_text}\n\n"
            
            # (جدید) افزودن پاسخ تشریحی
            msg += f"**📖 پاسخ تشریحی:**\n{q['rationale_text']}\n\n"
            msg += "⏳ ... (در حال بارگذاری سوال بعدی)"
            
            await query.edit_message_text(msg, reply_markup=None)

            # (جدید) ارسال خودکار سوال بعدی پس از 3 ثانیه
            await asyncio.sleep(3) # تاخیر تا کاربر پاسخ را بخواند
            await send_next_quiz_question(query.message, context, uid)

        except sqlite3.IntegrityError:
             await query.answer("شما قبلاً به این سوال پاسخ داده‌اید.", show_alert=True)
        except Exception as e:
            logger.error(f"Quiz answer error: {e}")
            await query.edit_message_text("❌ خطایی در ثبت پاسخ رخ داد.")
        return

    if data == "quiz_start":
        await query.answer()
        # (تغییر یافته) اکنون اولین سوالی که کاربر ندیده ارسال می‌شود
        await send_next_quiz_question(query.message, context, uid) 
        return

    if data == "quiz_leaderboard":
        try:
            # (تغییر یافته) اکنون مستقیماً از ستون امتیاز می‌خواند
            CUR.execute("""
                SELECT first_name, quiz_score
                FROM users
                WHERE quiz_score > 0
                ORDER BY quiz_score DESC
                LIMIT 5
            """)
            rows = CUR.fetchall()
            
            # (جدید) دریافت امتیاز خود کاربر
            user_score = get_user_score(uid)
            
            msg = f"🏆 **جدول امتیازات آزمون** 🏆\n\n"
            msg += f"⭐️ **امتیاز شما: {user_score}**\n\n"
            
            if not rows:
                msg += "(هنوز هیچ‌کس در آزمون‌ها امتیازی کسب نکرده است.)"
    if data == "quiz_back_to_menu":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⁉️ شروع/ادامه آزمون", callback_data="quiz_start")],
            [InlineKeyboardButton("🏆 جدول امتیازات", callback_data="quiz_leaderboard")]
        ])
        await query.edit_message_text("⚖️ **آزمون حقوقی**", reply_markup=kb)
        return

    # --- کال‌بک‌های محاسبه‌گر ---
    if data == "calc_mehrieh":
        await query.edit_message_text("✍️ تعداد سکه مهریه را وارد کنید (مثال: 110):")
        context.user_data["state"] = "awaiting_mehrieh_calc"
        return
    if data == "calc_diyah":
        await query.edit_message_text("✍️ لطفاً نوع و درصد آسیب را بنویسید (مثال: 10 درصد شکستگی دست راست):")
        context.user_data["state"] = "awaiting_diyah_calc"
        return
    if data == "calc_late_payment":
        await query.edit_message_text("✍️ مثال: 10000000 ریال، از 1398/05/10 تا 1403/02/20")
        context.user_data["state"] = "awaiting_late_payment_calc"
        return
    if data == "calc_enforcement":
        await query.edit_message_text("✍️ لطفاً مبلغ محکومٌ به را به ریال وارد کنید:")
        context.user_data["state"] = "awaiting_enforcement_calc"
        return
    if data == "calc_dadrasi": 
        await query.edit_message_text("✍️ لطفاً «مبلغ خواسته» را به ریال وارد کنید:")
        context.user_data["state"] = "awaiting_dadrasi_calc"
        return
    if data == "calc_inheritance":
        await query.edit_message_text("✍️ لطفاً لیست کامل ورثه و اموال را بنویسید:")
        context.user_data["state"] = "awaiting_inheritance_calc"
        return
        
    # --- کال‌بک‌های تنظیمات ---
    if data.startswith("set_p_"):
        personality = data.replace("set_p_", "")
        set_user_personality(uid, personality)
        await query.edit_message_text(f"✅ شخصیت ربات به '{personality}' تغییر یافت.")
        return

# ---------- Group Handlers ----------
async def new_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return
        
    bot_id = context.bot.id
    if bot_id in [m.id for m in update.message.new_chat_members]:
        chat = update.effective_chat
        chat_id = chat.id
        try:
            CUR.execute("INSERT OR IGNORE INTO managed_groups(chat_id, added_at) VALUES (?, ?)",
                        (chat_id, datetime.utcnow().isoformat()))
            DB.commit()
            await context.bot.send_message(
                chat_id=chat_id,
                text="🤖 سلام! این ربات حقوقی فعال شد.\n"
                     "من هر روز یک نکته حقوقی ارسال می‌کنم.\n"
                     "اگر سوال حقوقی بپرسید و با '?' تمام کنید، سعی می‌کنم پاسخ دهم."
            )
            logger.info(f"Bot added to new group: {chat.title} ({chat_id})")
        except Exception as e:
            logger.error(f"Failed to save new group {chat_id}: {e}")

@rate_limited 
async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
        
    text = update.message.text
    uid = update.effective_user.id
    
    if not text.endswith("?"): return
    if len(text) < 15: return
    if not any(keyword in text for keyword in LEGAL_KEYWORDS): return
        
    logger.info(f"Detected legal question in group {update.effective_chat.id} from user {uid}")
    
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
        answer = await ask_ai(uid, prompt=text, chat_history=None) # بدون حافظه در گروه
        await update.message.reply_text(
            answer + LEGAL_DISCLAIMER,
            reply_to_message_id=update.message.message_id
        )
    except Exception as e:
        logger.error(f"Failed to auto-reply in group: {e}")

# ---------- Error handler ----------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled error: %s", context.error)
    try:
        if getattr(update, "effective_message", None):
            await update.effective_message.reply_text("⚠️ خطایی رخ داد. تیم فنی مطلع شد.")
    except Exception: pass
