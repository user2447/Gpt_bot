import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from openai import OpenAI
from collections import defaultdict
from datetime import datetime, timedelta

# .env fayldan o'qish
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    raise ValueError("❌ TELEGRAM_TOKEN yoki OPENAI_API_KEY topilmadi!")

client = OpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# Statistika va xotira
user_total_stats = defaultdict(int)
user_daily_stats = defaultdict(int)
last_stat_date = datetime.now().date()
banned_users = {}
chat_histories = defaultdict(list)
user_last_messages = defaultdict(list)
premium_users = {}      # user_id -> paket nomi
pending_payments = {}   # user_id -> paket tanlangan
photo_pending = {}      # user_id -> True/False rasm kutish

MAX_PER_MINUTE = 3
DAILY_LIMIT_DEFAULT = 30

packages = {
    "Odiy": {"daily_limit": 100, "price": 7990},
    "Standart": {"daily_limit": 250, "price": 14990},
}

def reset_daily_if_needed():
    global last_stat_date, user_daily_stats
    today = datetime.now().date()
    if today != last_stat_date:
        user_daily_stats = defaultdict(int)
        last_stat_date = today

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("/premium", callback_data="menu_premium")],
        [InlineKeyboardButton("/status", callback_data="menu_status")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Salom! Men GPT-4 mini asosidagi Telegram botman 🤖.\n"
        "Quyidagi tugmalar yordamida paketlar yoki statusni ko‘rishingiz mumkin.", 
        reply_markup=reply_markup
    )

# /premium
async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    msg = "📦 Premium paketlar:\n\n"
    for name, info in packages.items():
        msg += f"{name} paket: Kunlik {info['daily_limit']} ta savol - Narxi: {info['price']} so‘m\n"
        keyboard.append([InlineKeyboardButton(f"{name} - {info['price']} so‘m", callback_data=f"premium_{name}")])
    msg += "\nSiz paketni tanlab, to‘lov qilganingizni adminga bildiring. Keyin sizga premium beriladi.\n"
    msg += "💳 To‘lov uchun karta: 9860190101371507 Xilola Akamuratova\n⚠️ Chek yuborilishi shart, aks holda premium berilmaydi."
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(msg, reply_markup=reply_markup)

# Callback paket tanlash
async def premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    package_name = query.data.replace("premium_", "")
    pending_payments[query.from_user.id] = package_name
    photo_pending[query.from_user.id] = False
    await query.edit_message_text(
        f"✅ Siz tanladingiz: {package_name} paketi.\n"
        f"To‘lov summasi: {packages[package_name]['price']} so‘m\n"
        f"To‘lov qilganingizni tasdiqlash uchun tugmani bosing:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("To‘lov qilindi ✅", callback_data="payment_done")]
        ])
    )

# To‘lov tugmasi bosilganda
async def payment_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id not in pending_payments:
        await query.edit_message_text("⚠️ Hech qanday paket tanlanmagan yoki to‘lov summasi mavjud emas.")
        return
    package_name = pending_payments[user_id]
    photo_pending[user_id] = True  # rasm kutish
    await context.bot.send_message(
        ADMIN_ID,
        f"💳 Foydalanuvchi {query.from_user.full_name} ({user_id}) "
        f"{package_name} paketini to‘lov qilganligini tasdiqlash uchun chek kutyapti."
    )
    await query.edit_message_text(
        f"✅ Siz to‘lov tugmasini bosdingiz. Iltimos, chek rasmini yuboring. "
        f"Admin tasdiqlagach, sizga paket beriladi."
    )

# /givepremium komandasi (admin orqali premium berish)
async def give_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = int(context.args[0])
    package_name = context.args[1]
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Siz admin emassiz!")
        return
    premium_users[user_id] = package_name
    if user_id in pending_payments: del pending_payments[user_id]
    if user_id in photo_pending: del photo_pending[user_id]
    await context.bot.send_message(user_id, f"✅ Sizga {package_name} paketi berildi! Premium aktivlashtirildi.")
    await update.message.reply_text(f"✅ {user_id} foydalanuvchiga {package_name} paketi berildi.")

# Rasm handler
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in photo_pending and photo_pending[user_id]:
        photo_file = await update.message.photo[-1].get_file()
        await photo_file.download_to_drive(f"{user_id}_check.jpg")
        await context.bot.send_message(ADMIN_ID, f"📸 Foydalanuvchi {update.effective_user.full_name} ({user_id}) chek yubordi.")
        await update.message.reply_text("⏳ Iltimos kuting, admin tasdiqlagach paket beriladi.")
        photo_pending[user_id] = False
    else:
        await update.message.reply_text("⚠️ Siz hali paket tanlamagansiz yoki chek yuborish shart emas.")

# /status
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_daily_if_needed()
    user_id = update.effective_user.id
    user_name = update.effective_user.full_name
    daily = user_daily_stats.get(user_id, 0)
    if user_id in premium_users:
        status_text = f"⭐ Status: Premium ({premium_users[user_id]} paketi)"
        extra_info = "✅ Paket limitingiz oshirilgan, javoblar tezroq keladi, chat xotirasi kengaytirilgan va reklamasiz ishlaydi."
        daily_limit = packages[premium_users[user_id]]['daily_limit']
    else:
        status_text = "⭐ Status: Odiy"
        extra_info = ("💡 Siz premium paket xarid qilishingiz mumkin:\n"
                      "   - Kunlik 100 ta savol\n"
                      "   - Javoblar tezroq keladi\n"
                      "   - Chat xotirasi ko‘proq\n"
                      "   - Reklamasiz ishlash")
        daily_limit = DAILY_LIMIT_DEFAULT
    limit_msg = (f"⚠️ Sizning kunlik foydalanish limitingiz tugadi. /premium orqali paket sotib oling."
                 if daily >= daily_limit else f"📅 Bugungi ishlatilgan so‘rov: {daily} ta / Kunlik limit: {daily_limit} ta")
    msg = f"👤 Ism: {user_name}\n🆔 ID: {user_id}\n{status_text}\n{limit_msg}\n\n{extra_info}"
    await update.message.reply_text(msg)

# Xabarlarni qayta ishlash
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_daily_if_needed()
    user = update.effective_user
    text = update.message.text
    now = datetime.now()
    user_last_messages[user.id] = [t for t in user_last_messages[user.id] if now - t < timedelta(minutes=1)]
    if len(user_last_messages[user.id]) >= MAX_PER_MINUTE:
        await update.message.reply_text("⏳ Siz juda tez so‘rov yubordingiz. Iltimos, 1 daqiqa kuting.")
        return
    user_last_messages[user.id].append(now)
    if user.id in banned_users:
        await update.message.reply_text(f"⛔ Siz ban olgansiz.\n📌 Sababi: {banned_users[user.id]}")
        return
    daily_limit = packages[premium_users[user.id]]['daily_limit'] if user.id in premium_users else DAILY_LIMIT_DEFAULT
    if user_daily_stats[user.id] >= daily_limit:
        await update.message.reply_text(f"⚠️ Kunlik limit ({daily_limit} ta) tugadi.
