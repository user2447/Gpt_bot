import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from openai import OpenAI
from collections import defaultdict
from datetime import datetime, timedelta

# .env o'qish
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

# Menu tugmasi faqat chap tomonda, xabar yozish oynasida ishlaydi
def menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📋 Menu", callback_data="open_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Menu ichidagi tugmalar
def menu_options_keyboard():
    keyboard = [
        [InlineKeyboardButton("📦 Premium Paketlar", callback_data="menu_premium")],
        [InlineKeyboardButton("📊 Status", callback_data="menu_status")],
        [InlineKeyboardButton("❌ Yopish", callback_data="menu_close")]
    ]
    return InlineKeyboardMarkup(keyboard)

# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Salom! Men GPT-4 mini asosidagi Telegram botman 🤖\n"
        "Chap tomondagi Menu tugmasini bosing.",
        reply_markup=menu_keyboard()
    )

# Callback menu
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "open_menu":
        await query.edit_message_text(
            "📋 Menu:",
            reply_markup=menu_options_keyboard()
        )
    elif query.data == "menu_premium":
        await query.edit_message_text("📦 Premium paketlar:\n\n" + "\n".join(
            [f"{name} paket: Kunlik {info['daily_limit']} ta savol - Narxi: {info['price']} so‘m"
             for name, info in packages.items()]) +
            "\n\n💳 To‘lov uchun karta yuboriladi.", reply_markup=menu_options_keyboard()
        )
    elif query.data == "menu_status":
        reset_daily_if_needed()
        daily = user_daily_stats.get(user_id, 0)
        user_name = query.from_user.full_name
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
        await query.edit_message_text(msg, reply_markup=menu_options_keyboard())
    elif query.data == "menu_close":
        await query.edit_message_text("📌 Menu yopildi.", reply_markup=menu_keyboard())

# Xabarlar handler
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_daily_if_needed()
    user = update.effective_user
    if update.message.text:
        text = update.message.text
        now = datetime.now()
        user_last_messages[user.id] = [t for t in user_last_messages[user.id] if now - t < timedelta(minutes=1)]
        if len(user_last_messages[user.id]) >= MAX_PER_MINUTE:
            await update.message.reply_text("⏳ Siz juda tez so‘rov yubordingiz. Iltimos, 1 daqiqa kuting.",
                                            reply_markup=menu_keyboard())
            return
        user_last_messages[user.id].append(now)
        if user.id in banned_users:
            await update.message.reply_text(f"⛔ Siz ban olgansiz.\n📌 Sababi: {banned_users[user.id]}",
                                            reply_markup=menu_keyboard())
            return
        daily_limit = packages[premium_users[user.id]]['daily_limit'] if user.id in premium_users else DAILY_LIMIT_DEFAULT
        if user_daily_stats[user.id] >= daily_limit:
            await update.message.reply_text(f"⚠️ Kunlik limit ({daily_limit} ta) tugadi. /premium orqali paket sotib oling.",
                                            reply_markup=menu_keyboard())
            return
        logging.info(f"👤 {user.username} ({user.id}) | ✉️ {text}")
        user_total_stats[user.id] += 1
        user_daily_stats[user.id] += 1
        if user.id != ADMIN_ID:
            await context.bot.send_message(
                ADMIN_ID,
                f"📩 Yangi xabar:\n\n👤 {user.username or user.full_name}\n🆔 {user.id}\n\n✉️ {text}"
            )

        chat_histories[user.id].append({"role": "user", "content": text})
        try:
            system_message = f"Siz foydali Telegram chatbot bo‘lasiz. Hozirgi yil {datetime.now().year}."
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": system_message}, *chat_histories[user.id]]
            )
            bot_reply = response.choices[0].message.content
            await update.message.reply_text(bot_reply, reply_markup=menu_keyboard())
            chat_histories[user.id].append({"role": "assistant", "content": bot_reply})
            max_history = 50 if user.id in premium_users else 20
            if len(chat_histories[user.id]) > max_history:
                chat_histories[user.id] = chat_histories[user.id][-max_history:]
        except Exception as e:
            if "rate_limit_exceeded" in str(e):
                await update.message.reply_text("❌ Hozir API band, iltimos bir ozdan keyin urinib ko‘ring.",
                                                reply_markup=menu_keyboard())
            else:
                logging.error(f"❌ Xatolik: {e}")
                await update.message.reply_text(f"❌ Kechirasiz, xatolik yuz berdi: {e}", reply_markup=menu_keyboard())

# Bot ishga tushirish
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logging.info("🤖 Bot ishga tushdi!")
    app.run_polling()

if __name__ == "__main__":
    main()
