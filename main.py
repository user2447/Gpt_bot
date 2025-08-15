import psycopg2
import openai
from telegram import Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext

# ======================
# API kalitlari va tokenlar
# ======================

TELEGRAM_TOKEN = "8216703007:AAEx1RS-hIYgArmTSCY4SB-rT676WmGEScA"
DATABASE_URL = "postgresql://${PGUSER}:${POSTGRES_PASSWORD}@${RAILWAY_PRIVATE_DOMAIN}:5432/${PGDATABASE}"

# ======================
# Bazaga ulanish
# ======================
conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# Jadvalni yaratish (agar mavjud bo'lmasa)
cursor.execute("""
CREATE TABLE IF NOT EXISTS qa_table (
    id SERIAL PRIMARY KEY,
    question TEXT,
    answer TEXT
)
""")
conn.commit()

# ======================
# Savol-javob funksiyasi
# ======================
def save_question_answer(question):
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": question}]
    )
    answer = response['choices'][0]['message']['content']

    cursor.execute(
        "INSERT INTO qa_table (question, answer) VALUES (%s, %s)",
        (question, answer)
    )
    conn.commit()
    return answer

# ======================
# Telegram handler funksiyasi
# ======================
def handle_message(update: Update, context: CallbackContext):
    user_question = update.message.text
    bot_reply = save_question_answer(user_question)
    update.message.reply_text(bot_reply)

# ======================
# Bot ishga tushirish
# ======================
updater = Updater(token=TELEGRAM_TOKEN)
dispatcher = updater.dispatcher
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

print("Bot ishga tushdi...")
updater.start_polling()
updater.idle()

# ======================
# Bog‘lanishni yopish
# ======================
cursor.close()
conn.close()
