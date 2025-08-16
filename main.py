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
    raise ValueError("❌ TELEGRAM_TOKEN yoki OPENAI_API_KEY .env fayldan topilmadi!")

# OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# logging sozlamalari
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Statistika, ban ro‘yxati va user xotira
user_total_stats = defaultdict(int)
user_daily_stats = defaultdict(int)
last_stat_date = datetime.now().date()
banned_users = {}
chat_histories = defaultdict(list)

# Premium foydalanuvchilar: user_id -> {"package": nomi, "expire": datetime}
premium_users = {}

# Rate limit uchun foydalanuvchi so‘rov vaqtlari
user_last_messages = defaultdict(list)
MAX_PER_MINUTE = 3
DAILY_LIMIT_DEFAULT = 30

# Paketlar narxi va limit
packages = {
    "Odiy": {"daily_limit": 100, "price": 7990},
    "Standart": {"daily_limit": 250, "price": 14990},
}

# Kundalik hisobni tozalash
def reset_daily_if_needed():
    global last_stat_date, user_daily_stats
    today = datetime.now().date()
    if today != last_stat_date:
        user_daily_stats = defaultdict(int)
        last_stat_date = today

# /start komandasi
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Salom! Men GPT-4 mini asosidagi Telegram botman 🤖. Savolingizni yozing.")

# /premium komandasi
async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Odiy paket", callback_data="premium_Odiy")],
        [InlineKeyboardButton("Standart paket", callback_data="premium_Standart")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📦 Premium paketlar:\n\n"
        "Tanlamoqchi bo‘lgan paketni bosing, sizga to‘lov raqami ko‘rsatiladi.\n"
        "To‘lov qilganingizdan so‘ng admin sizga /premium funksiyasini beradi.",
        reply_markup=reply_markup
    )

# Inline button callback
async def premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    package_name = query.data.split("_")[1]
    await query.edit_message_text(
        text=f"✅ Siz {package_name} paketini tanladingiz.\n\n"
             f"💳 To‘lov raqami: 9860190101371507 X.A\n"
             f"💰 To‘lov: 0 so‘m (cheksiz, rasm yuborib adminga tasdiqlatishingiz mumkin)\n\n"
             "To‘lovni amalga oshirganingizdan so‘ng admin sizga /premium funksiyasini beradi."
    )

# /status komandasi
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.full_name
    daily = user_daily_stats.get(user_id, 0)

    if user_id in premium_users:
        package = premium_users[user_id]['package']
        expire = premium_users[user_id]['expire'].strftime("%d-%m-%Y")
        status_text = f"⭐ Status: Premium ({package} paketi)"
        daily_limit = packages[package]['daily_limit']
        extra_info = (
            f"✅ Sizning paket limitingiz: {daily_limit} ta kunlik savol\n"
            f"✅ Paket muddati: {expire}\n"
            "✅ Javoblar tezroq keladi\n"
            "✅ Chat xotirasi kengaytirilgan\n"
            "✅ Maxsus buyruqlar: /summarize, /translate, /askcode\n"
            "✅ Reklamasiz ishlash"
        )
    else:
        status_text = "⭐ Status: Odiy"
        daily_limit = DAILY_LIMIT_DEFAULT
        extra_info = ""
        if user_daily_stats.get(user_id, 0) >= daily_limit:
            extra_info = (
                "⚠️ Sizning kunlik foydalanish limitingiz tugadi. "
                "Agar limitni oshirmoqchi bo‘lsangiz /premium orqali paket sotib oling.\n"
                "📦 Premium paketlar:\n"
                "   - Odiy paket: 100 ta kunlik savol - 7990 so‘m\n"
                "   - Standart paket: 250 ta kunlik savol - 14990 so‘m"
            )

    msg = f"👤 Ism: {user_name}\n" \
          f"🆔 ID: {user_id}\n" \
          f"{status_text}\n" \
          f"📅 Bugungi ishlatilgan so‘rov: {daily} ta\n\n" \
          f"{extra_info}"

    await update.message.reply_text(msg)

# Xabarlarni qayta ishlash
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_daily_if_needed()
    user = update.effective_user
    text = update.message.text

    try:
        # Rate limit (1 minutda 3 ta so‘rov)
        now = datetime.now()
        user_last_messages[user.id] = [t for t in user_last_messages[user.id] if now - t < timedelta(minutes=1)]
        if len(user_last_messages[user.id]) >= MAX_PER_MINUTE:
            await update.message.reply_text("⏳ Siz juda tez so‘rov yubordingiz. Iltimos, 1 daqiqa kuting.")
            return
        user_last_messages[user.id].append(now)

        # Ban tekshirish
        if user.id in banned_users:
            reason = banned_users[user.id]
            await update.message.reply_text(f"⛔ Siz ban olgansiz.\n📌 Sababi: {reason}")
            return

        # Kunlik limit
        if user.id in premium_users:
            package = premium_users[user.id]['package']
            daily_limit = packages[package]['daily_limit']
        else:
            daily_limit = DAILY_LIMIT_DEFAULT

        if user_daily_stats[user.id] >= daily_limit:
            if user.id in premium_users:
                await update.message.reply_text(f"⚠️ Sizning kunlik limitingiz ({daily_limit} ta) tugadi.")
            else:
                await update.message.reply_text(
                    f"⚠️ Sizning kunlik foydalanish limitingiz tugadi. "
                    "Agar limitni oshirmoqchi bo‘lsangiz /premium orqali paket sotib oling."
                )
            return

        logging.info(f"👤 Foydalanuvchi: {user.username} (ID: {user.id}) | ✉️ Xabar: {text}")
        user_total_stats[user.id] += 1
        user_daily_stats[user.id] += 1

        if user.id != ADMIN_ID:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"📩 Yangi xabar:\n\n👤 {user.username or user.full_name}\n🆔 {user.id}\n\n✉️ {text}"
            )

        chat_histories[user.id].append({"role": "user", "content": text})

        current_year = datetime.now().year
        system_message = f"Siz foydali Telegram chatbot bo‘lasiz. Hozirgi yil {current_year}."

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_message}, *chat_histories[user.id]]
        )

        bot_reply = response.choices[0].message.content
        await update.message.reply_text(bot_reply)
        chat_histories[user.id].append({"role": "assistant", "content": bot_reply})

      # Premium foydalanuvchi chat xotirasi kengaytirildi
    max_history = 50 if user.id in premium_users else 20
    if len(chat_histories[user.id]) > max_history:
    chat_histories[user.id] = chat_histories[user.id][-max_history:]

