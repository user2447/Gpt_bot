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

# Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# Statistika, ban ro‘yxati va xotira
user_total_stats = defaultdict(int)
user_daily_stats = defaultdict(int)
last_stat_date = datetime.now().date()
banned_users = {}
chat_histories = defaultdict(list)
user_last_messages = defaultdict(list)

MAX_PER_MINUTE = 3
DAILY_LIMIT_DEFAULT = 30

# Premium foydalanuvchilar: user_id -> paket nomi
premium_users = {}  # misol: {123456789: "Odiy"}

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

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Salom! Men GPT-4 mini asosidagi Telegram botman 🤖. Savolingizni yozing.")

# /premium
async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    msg = "📦 Premium paketlar:\n\n"
    for name, info in packages.items():
        msg += f"{name} paket: Kunlik {info['daily_limit']} ta savol - Narxi: {info['price']} so‘m\n"
        keyboard.append([InlineKeyboardButton(f"{name} - {info['price']} so‘m", callback_data=f"premium_{name}")])
    msg += "\nSiz paketni tanlash orqali admin bilan bog‘lanishingiz mumkin va to‘lov qilgach, sizga /premium beriladi."
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(msg, reply_markup=reply_markup)

# Callback (paket tanlash)
async def premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    package_name = query.data.replace("premium_", "")
    await query.edit_message_text(f"✅ Siz tanladingiz: {package_name} paketi.\n"
                                  f"Adminga to‘lov qilganingizni bildiring, so‘ng sizga paket beriladi.\n"
                                  f"To‘lov summasi: {packages[package_name]['price']} so‘m")

# /status
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_daily_if_needed()
    user_id = update.effective_user.id
    user_name = update.effective_user.full_name
    daily = user_daily_stats.get(user_id, 0)

    if user_id in premium_users:
        status_text = f"⭐ Status: Premium ({premium_users[user_id]} paketi)"
        extra_info = "✅ Sizning paket limitingiz oshirilgan, javoblar tezroq keladi, chat xotirasi kengaytirilgan va reklamasiz ishlaydi."
        daily_limit = packages[premium_users[user_id]]['daily_limit']
    else:
        status_text = "⭐ Status: Odiy"
        extra_info = ("💡 Siz premium paket xarid qilishingiz mumkin:\n"
                      "   - Kunlik 100 ta savol\n"
                      "   - Javoblar tezroq keladi\n"
                      "   - Chat xotirasi ko‘proq\n"
                      "   - Reklamasiz ishlash")
        daily_limit = DAILY_LIMIT_DEFAULT

    if daily >= daily_limit:
        limit_msg = f"⚠️ Sizning kunlik foydalanish limitingiz tugadi. Agar limitni oshirmoqchi bo‘lsangiz /premium orqali paket sotib oling."
    else:
        limit_msg = f"📅 Bugungi ishlatilgan so‘rov: {daily} ta / Kunlik limit: {daily_limit} ta"

    msg = f"👤 Ism: {user_name}\n" \
          f"🆔 ID: {user_id}\n" \
          f"{status_text}\n" \
          f"{limit_msg}\n\n" \
          f"{extra_info}"

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
        reason = banned_users[user.id]
        await update.message.reply_text(f"⛔ Siz ban olgansiz.\n📌 Sababi: {reason}")
        return

    daily_limit = packages[premium_users[user.id]]['daily_limit'] if user.id in premium_users else DAILY_LIMIT_DEFAULT
    if user_daily_stats[user.id] >= daily_limit:
        await update.message.reply_text(f"⚠️ Kunlik limit ({daily_limit} ta) tugadi. Ertaga davom etishingiz mumkin yoki /premium orqali paket sotib oling.")
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

    try:
        system_message = f"Siz foydali Telegram chatbot bo‘lasiz. Hozirgi yil {datetime.now().year}."
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_message}, *chat_histories[user.id]]
        )
        bot_reply = response.choices[0].message.content
        await update.message.reply_text(bot_reply)

        chat_histories[user.id].append({"role": "assistant", "content": bot_reply})

        # Chat xotirasi uzunligi
        max_history = 50 if user.id in premium_users else 20
        if len(chat_histories[user.id]) > max_history:
            chat_histories[user.id] = chat_histories[user.id][-max_history:]

    except Exception as e:
        if "rate_limit_exceeded" in str(e):
            await update.message.reply_text("❌ Hozir API band, iltimos bir ozdan keyin urinib ko‘ring.")
        else:
            logging.error(f"❌ Xatolik: {e}")
            await update.message.reply_text(f"❌ Kechirasiz, xatolik yuz berdi: {e}")

# /top
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_daily_if_needed()
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Siz admin emassiz.")
        return
    if not user_total_stats:
        await update.message.reply_text("📊 Statistika yo‘q.")
        return
    sorted_users = sorted(user_total_stats.items(), key=lambda x: x[1], reverse=True)[:5]
    msg = "📊 Eng faol 5 foydalanuvchi:\n\n"
    for uid, total in sorted_users:
        today_count = user_daily_stats.get(uid, 0)
        msg += f"👤 User ID: {uid}\n   📅 Bugun: {today_count} ta\n   📈 Umumiy: {total} ta\n\n"
    await update.message.reply_text(msg)

# /ban
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Siz admin emassiz.")
        return
    if not context.args:
        await update.message.reply_text("❌ Foydalanuvchi ID va sabab kiriting. Masalan: `/ban 5553171661 yomon so'zlar ishlatish`")
        return
    try:
        uid = int(context.args[0])
        reason = " ".join(context.args[1:]) if len(context.args) > 1 else "Sabab ko‘rsatilmagan"
        banned_users[uid] = reason
        await update.message.reply_text(f"🚫 Foydalanuvchi {uid} ban qilindi.\n📌 Sababi: {reason}")
        try:
            await context.bot.send_message(uid, f"⛔ Siz ban olgansiz.\n📌 Sababi: {reason}")
        except Exception as e:
            logging.warning(f"❌ Ban xabarini foydalanuvchiga yuborib bo‘lmadi: {e}")
    except Exception as e:
        await update.message.reply_text(f"❌ Xato: {e}")

# /unban
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Siz admin emassiz.")
        return
    if not context.args:
        await update.message.reply_text("❌ Foydalanuvchi ID kiriting. Masalan: `/unban 5553171661`")
        return
    try:
        uid = int(context.args[0])
        if uid in banned_users:
            banned_users.pop(uid)
            await update.message.reply_text(f"✅ Foydalanuvchi {uid} unban qilindi.")
            try:
                await context.bot.send_message(uid, "✅ Siz bandan chiqdingiz. Endi botdan foydalanishingiz mumkin.")
            except Exception as e:
                logging.warning(f"❌ Unban xabarini foydalanuvchiga yuborib bo‘lmadi: {e}")
        else:
            await update.message.reply_text("ℹ️ Bu foydalanuvchi ban qilinmagan.")
    except Exception as e:
        await update.message.reply_text(f"❌ Xato: {e}")

# Botni ishga tushirish
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("premium", premium))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CallbackQueryHandler(premium_callback, pattern="^premium_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Bot ishga tushdi...")
    app.run_polling()

if __name__ == "__main__":
    main()
