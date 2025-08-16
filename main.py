import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from collections import defaultdict
from datetime import datetime

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

# Xabarlarni qayta ishlash
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_daily_if_needed()
    user = update.effective_user
    text = update.message.text

    if user.id in banned_users:
        reason = banned_users[user.id]
        await update.message.reply_text(f"⛔ Siz ban olgansiz.\n📌 Sababi: {reason}")
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
        current_year = datetime.now().year
        system_message = f"Siz foydali Telegram chatbot bo‘lasiz. Hozirgi yil {current_year}."

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_message}, *chat_histories[user.id]]
        )

        bot_reply = response.choices[0].message.content
        await update.message.reply_text(bot_reply)
        chat_histories[user.id].append({"role": "assistant", "content": bot_reply})

        if len(chat_histories[user.id]) > 20:
            chat_histories[user.id] = chat_histories[user.id][-20:]

    except Exception as e:
        logging.error(f"❌ Xatolik: {e}")
        await update.message.reply_text(f"❌ Kechirasiz, xatolik yuz berdi: {e}")

# /top komandasi
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

# /ban komandasi
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

# /unban komandasi
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
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 Bot ishga tushdi...")
    app.run_polling()

if __name__ == "__main__":
    main()
