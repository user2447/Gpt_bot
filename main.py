import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from openai import OpenAI
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # Python 3.9+

# .env faylni yuklash
load_dotenv()

# Environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    raise ValueError("❌ TELEGRAM_TOKEN yoki OPENAI_API_KEY topilmadi!")

client = OpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Statistika va xotira
user_total_stats = defaultdict(int)
user_daily_stats = defaultdict(int)
last_stat_date = datetime.now().date()
banned_users = {}
chat_histories = defaultdict(list)
user_last_messages = defaultdict(list)
premium_users = {}
pending_payments = {}
photo_pending = {}

MAX_PER_MINUTE = 5
DAILY_LIMIT_DEFAULT = 30

packages = {
    "Odiy": {
        "daily_limit": 100,
        "price": 7990,
        "features": [
            "⏱ Javob tezligi: odiy",
            "💬 Chat xotirasi: 20 ta oxirgi xabar",
            "📢 Reklamasiz ishlash: ❌"
        ]
    },
    "Standart": {
        "daily_limit": 250,
        "price": 14990,
        "features": [
            "⏱ Javob tezligi: tezroq",
            "💬 Chat xotirasi: 50 ta oxirgi xabar",
            "📢 Reklamasiz ishlash: ✅"
        ]
    },
}

CARD_NUMBER = "9860190101371507 Xilola Akamuratova"

# Kunlik statistika reset
def reset_daily_if_needed():
    global last_stat_date, user_daily_stats
    try:
        today = datetime.now(ZoneInfo("Asia/Tashkent")).date()
    except Exception:
        today = datetime.utcnow().date()
    if today != last_stat_date:
        user_daily_stats = defaultdict(int)
        last_stat_date = today

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Salom! Men GPT-4 mini asosidagi Telegram botman 🤖")

# 🔹 Ban funksiyalari
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Siz admin emassiz.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Foydalanish: /ban <user_id> <sababi>")
        return
    user_id = int(context.args[0])
    reason = " ".join(context.args[1:])
    banned_users[user_id] = reason
    await update.message.reply_text(f"✅ {user_id} foydalanuvchi ban qilindi.\n📌 Sababi: {reason}")

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Siz admin emassiz.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("❌ Foydalanish: /unban <user_id>")
        return
    user_id = int(context.args[0])
    if user_id in banned_users:
        del banned_users[user_id]
        await update.message.reply_text(f"✅ {user_id} foydalanuvchi unban qilindi.")
    else:
        await update.message.reply_text("⚠️ Bu foydalanuvchi ban qilingan emas.")

# /premium
async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(f"Odiy paket: {packages['Odiy']['price']} so'm", callback_data="premium_Odiy")],
        [InlineKeyboardButton(f"Standart paket: {packages['Standart']['price']} so'm", callback_data="premium_Standart")]
    ]
    await update.message.reply_text(
        "📦 Premium paketlar:\n\nOdiy va Standart paketlardan birini tanlang:", 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Callback
async def premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data.startswith("premium_"):
        package_name = query.data.replace("premium_", "")
        pending_payments[user_id] = package_name
        photo_pending[user_id] = True
        package = packages[package_name]
        features_text = "\n".join(package["features"])
        await query.edit_message_text(
            f"✅ Siz tanladingiz: {package_name} paketi\n"
            f"💳 To‘lov summasi: {package['price']} so'm\n"
            f"💳 To‘lash uchun karta: {CARD_NUMBER}\n\n"
            f"📋 Paket ichidagi imkoniyatlar:\n{features_text}\n"
            f"⚡ Kunlik savollar limiti: {package['daily_limit']} ta\n\n"
            "To‘lov qilganingizni tasdiqlash uchun tugmani bosing:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("To‘landi ✅", callback_data="payment_done")]])
        )
    elif query.data == "payment_done":
        if user_id not in pending_payments:
            await query.edit_message_text("⚠️ Hech qanday paket tanlanmagan.")
            return
        await query.edit_message_text(
            "✅ To‘lov tugmasi bosildi.\nIltimos, chek rasmini yuboring. Admin tasdiqlagach paket beriladi."
        )

# /givepremium
async def give_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Siz admin emassiz.")
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("❌ Foydalanish: /givepremium <user_id> <Odiy/Standart>")
        return
    user_id, package_name = args
    if package_name not in packages:
        await update.message.reply_text("❌ Paket noto‘g‘ri.")
        return
    user_id = int(user_id)
    premium_users[user_id] = package_name
    if user_id in pending_payments:
        del pending_payments[user_id]
    await update.message.reply_text(f"✅ Foydalanuvchiga {package_name} paketi berildi.")

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
        extra_info = "💡 Siz premium paket xarid qilishingiz mumkin."
        daily_limit = DAILY_LIMIT_DEFAULT
    limit_msg = (f"⚠️ Sizning kunlik foydalanish limitingiz tugadi. /premium orqali paket sotib oling."
                 if daily >= daily_limit else f"📅 Bugungi ishlatilgan so‘rov: {daily} ta / Kunlik limit: {daily_limit} ta")
    msg = f"👤 Ism: {user_name}\n🆔 ID: {user_id}\n{status_text}\n{limit_msg}\n\n{extra_info}"
    await update.message.reply_text(msg)

# Xabarlar
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_daily_if_needed()
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    text = update.message.text.strip()

    # Ban check
    if user.id in banned_users:
        await update.message.reply_text(f"⛔ Siz ban olgansiz.\n📌 Sababi: {banned_users[user.id]}")
        return

    # Kunlik limit check
    daily_limit = packages[premium_users[user.id]]['daily_limit'] if user.id in premium_users else DAILY_LIMIT_DEFAULT
    if user_daily_stats[user.id] >= daily_limit:
        await update.message.reply_text(f"⚠️ Kunlik limit ({daily_limit} ta) tugadi. /premium orqali paket sotib oling.")
        return

    # 1 daqiqada 5 ta limit
    now = datetime.now(ZoneInfo("Asia/Tashkent"))
    user_last_messages[user.id] = [t for t in user_last_messages[user.id] if now - t < timedelta(minutes=1)]
    if len(user_last_messages[user.id]) >= MAX_PER_MINUTE:
        await update.message.reply_text("⏳ Siz juda tez so‘rov yubordingiz. Iltimos, 1 daqiqa kuting.")
        return
    user_last_messages[user.id].append(now)

    # Statistika
    user_total_stats[user.id] += 1
    user_daily_stats[user.id] += 1

    # Admin log
    if user.id != ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            f"📩 Yangi xabar:\n\n👤 {user.username or user.full_name}\n🆔 {user.id}\n\n✉️ {text}"
        )

    # GPT javobi (sana majburlash yo‘q)
    chat_histories[user.id].append({"role": "user", "content": text})
    system_message = "Siz foydali Telegram chatbot bo‘lasiz. Siz GPT-4 mini modelisiz."
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_message}, *chat_histories[user.id]]
        )
        bot_reply = response.choices[0].message.content
        await update.message.reply_text(bot_reply)
        chat_histories[user.id].append({"role": "assistant", "content": bot_reply})

        max_history = 50 if user.id in premium_users else 20
        if len(chat_histories[user.id]) > max_history:
            chat_histories[user.id] = chat_histories[user.id][-max_history:]

    except Exception as e:
        await update.message.reply_text(f"❌ GPT javob berolmayapti: {e}")

# Rasm handler
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in photo_pending and photo_pending[user_id]:
        photo_file = await update.message.photo[-1].get_file()
        file_path = f"{user_id}_check.jpg"
        await photo_file.download_to_drive(file_path)
        await context.bot.send_photo(ADMIN_ID, photo=open(file_path, "rb"),
                                     caption=f"📸 Foydalanuvchi {update.effective_user.full_name} ({user_id}) chek yubordi.")
        await update.message.reply_text("✅ Rasm qabul qilindi. Admin tasdiqlagach paket beriladi.")
        photo_pending[user_id] = False
    else:
        await update.message.reply_text("⚠️ Siz hali paket tanlamagansiz yoki chek yuborish shart emas.")

# Bot ishga tushirish
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("premium", premium))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("givepremium", give_premium))
    app.add_handler(CommandHandler("ban", ban_user))
    app.add_handler(CommandHandler("unban", unban_user))
    app.add_handler(CallbackQueryHandler(premium_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    logging.info("🤖 Bot ishga tushdi! Polling ishlamoqda...")
    app.run_polling()

if __name__ == "__main__":
    main()
