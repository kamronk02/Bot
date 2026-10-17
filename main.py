import os
import sqlite3
import logging
from contextlib import contextmanager

import telebot
from telebot import types

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "kino.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set.")

ADMIN_IDS = {int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()}
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
user_states = {}
user_drafts = {}
pending_broadcasts = {}

@contextmanager
def db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                year INTEGER,
                genre TEXT,
                description TEXT,
                file_id TEXT NOT NULL,
                file_type TEXT NOT NULL,
                added_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS required_channels (
                channel TEXT PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

def is_admin(user_id):
    return user_id in ADMIN_IDS

def remember_user(user_id):
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))

def get_required_channels():
    with db() as conn:
        return conn.execute("SELECT channel FROM required_channels ORDER BY channel").fetchall()

def subscribed_to_all(user_id):
    for row in get_required_channels():
        channel = row["channel"]
        try:
            member = bot.get_chat_member(channel, user_id)
            if member.status not in ("member", "administrator", "creator"):
                return False
        except Exception:
            logging.exception("Could not check membership for %s", channel)
            return False
    return True

def subscription_prompt(chat_id):
    channels = get_required_channels()
    markup = types.InlineKeyboardMarkup()
    for row in channels:
        channel = row["channel"]
        username = channel.lstrip("@")
        markup.add(types.InlineKeyboardButton(f"📢 {channel} kanaliga obuna bo‘lish", url=f"https://t.me/{username}"))
    markup.add(types.InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_subs"))
    bot.send_message(
        chat_id,
        "🔒 <b>Botdan foydalanish uchun quyidagi kanal(lar)ga obuna bo‘ling.</b>\n"
        "Obuna bo‘lgach, «Obunani tekshirish» tugmasini bosing.",
        reply_markup=markup
    )

def allowed_to_use(message):
    if is_admin(message.from_user.id):
        return True
    if not subscribed_to_all(message.from_user.id):
        subscription_prompt(message.chat.id)
        return False
    return True

def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🔎 Kino qidirish", "🎭 Janr bo‘yicha")
    markup.row("📅 Yil bo‘yicha", "📚 Barcha kinolar")
    if is_admin(user_id):
        markup.row("👑 Admin panel")
    return markup

def escape_html(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def movie_caption(movie):
    return (
        f"🎬 <b>{escape_html(movie['title'])}</b>\n"
        f"📅 Yil: {movie['year'] or 'Noma’lum'}\n"
        f"🎭 Janr: {escape_html(movie['genre'] or 'Noma’lum')}\n\n"
        f"{escape_html(movie['description'] or 'Tavsif kiritilmagan.')}"
    )

def send_movie(chat_id, movie):
    caption = movie_caption(movie)
    if movie["file_type"] == "video":
        bot.send_video(chat_id, movie["file_id"], caption=caption)
    elif movie["file_type"] == "document":
        bot.send_document(chat_id, movie["file_id"], caption=caption)
    elif movie["file_type"] == "animation":
        bot.send_animation(chat_id, movie["file_id"], caption=caption)
    else:
        bot.send_message(chat_id, caption)

def show_movies(chat_id, movies, empty_text="😕 Hech narsa topilmadi."):
    if not movies:
        bot.send_message(chat_id, empty_text)
        return
    for movie in movies[:15]:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("▶️ Kinoni olish", callback_data=f"movie:{movie['id']}"))
        text = (
            f"🎬 <b>{escape_html(movie['title'])}</b>\n"
            f"📅 {movie['year'] or 'Noma’lum'}  |  🎭 {escape_html(movie['genre'] or 'Noma’lum')}"
        )
        bot.send_message(chat_id, text, reply_markup=markup)

def admin_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("➕ Kino qo‘shish", "🗑 Kino o‘chirish")
    markup.row("🔒 Obuna kanallari", "📢 Ommaviy xabar")
    markup.row("📊 Statistika", "⬅️ Asosiy menyu")
    return markup

@bot.message_handler(commands=["start", "help"])
def start(message):
    remember_user(message.from_user.id)
    if not allowed_to_use(message):
        return
    bot.send_message(
        message.chat.id,
        "🎬 <b>Kino olamiga xush kelibsiz!</b>\n\n"
        "Kinolarni nomi, janri yoki yili bo‘yicha qidiring.",
        reply_markup=main_menu(message.from_user.id)
    )

@bot.message_handler(commands=["id"])
def show_id(message):
    bot.reply_to(message, f"Sizning Telegram ID raqamingiz: <code>{message.from_user.id}</code>")

@bot.callback_query_handler(func=lambda c: c.data == "check_subs")
def check_subscriptions(call):
    if subscribed_to_all(call.from_user.id):
        bot.answer_callback_query(call.id, "Obuna tasdiqlandi!")
        bot.send_message(call.message.chat.id, "✅ Rahmat! Endi botdan foydalanishingiz mumkin.", reply_markup=main_menu(call.from_user.id))
    else:
        bot.answer_callback_query(call.id, "Hali barcha kanallarga obuna bo‘lmagansiz.", show_alert=True)
        subscription_prompt(call.message.chat.id)

@bot.message_handler(func=lambda m: m.text == "🔎 Kino qidirish")
def ask_search(message):
    if not allowed_to_use(message): return
    user_states[message.from_user.id] = "search"
    bot.send_message(message.chat.id, "Kino nomini yozing:")

@bot.message_handler(func=lambda m: m.text == "🎭 Janr bo‘yicha")
def ask_genre(message):
    if not allowed_to_use(message): return
    user_states[message.from_user.id] = "genre"
    bot.send_message(message.chat.id, "Janr nomini yozing (masalan: Komediya):")

@bot.message_handler(func=lambda m: m.text == "📅 Yil bo‘yicha")
def ask_year(message):
    if not allowed_to_use(message): return
    user_states[message.from_user.id] = "year"
    bot.send_message(message.chat.id, "Kino yilini yozing (masalan: 2024):")

@bot.message_handler(func=lambda m: m.text == "📚 Barcha kinolar")
def all_movies(message):
    if not allowed_to_use(message): return
    with db() as conn:
        rows = conn.execute("SELECT * FROM movies ORDER BY id DESC LIMIT 15").fetchall()
    show_movies(message.chat.id, rows, "Hozircha bazada kino yo‘q.")

@bot.message_handler(func=lambda m: m.text == "👑 Admin panel")
def admin_panel(message):
    if not is_admin(message.from_user.id): return
    bot.send_message(message.chat.id, "👑 <b>Admin panel</b>", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text == "⬅️ Asosiy menyu")
def back_menu(message):
    bot.send_message(message.chat.id, "Asosiy menyu:", reply_markup=main_menu(message.from_user.id))

@bot.message_handler(func=lambda m: m.text == "➕ Kino qo‘shish")
def add_movie_start(message):
    if not is_admin(message.from_user.id): return
    user_states[message.from_user.id] = "add_video"
    user_drafts.pop(message.from_user.id, None)
    bot.send_message(message.chat.id, "Kino videosini yuboring. Video yoki Telegram hujjati sifatida yuborishingiz mumkin.")

@bot.message_handler(func=lambda m: m.text == "🗑 Kino o‘chirish")
def delete_movie_start(message):
    if not is_admin(message.from_user.id): return
    user_states[message.from_user.id] = "delete"
    bot.send_message(message.chat.id, "O‘chirish uchun kino ID raqamini yuboring. Ro‘yxat uchun /movies buyrug‘i.")

@bot.message_handler(func=lambda m: m.text == "🔒 Obuna kanallari")
def channels_menu(message):
    if not is_admin(message.from_user.id): return
    user_states[message.from_user.id] = None
    rows = get_required_channels()
    current = "\n".join(f"• {escape_html(r['channel'])}" for r in rows) or "Hozircha majburiy obuna kanali yo‘q."
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("➕ Kanal qo‘shish", "➖ Kanalni o‘chirish")
    markup.row("👑 Admin panel")
    bot.send_message(
        message.chat.id,
        f"🔒 <b>Majburiy obuna kanallari</b>\n{current}\n\n"
        "Kanal qo‘shishda ochiq kanal username'ini yuboring, masalan: @meningkanalim.\n"
        "Bot ushbu kanalda administrator bo‘lishi kerak.",
        reply_markup=markup
    )

@bot.message_handler(func=lambda m: m.text == "➕ Kanal qo‘shish")
def add_channel_start(message):
    if not is_admin(message.from_user.id): return
    user_states[message.from_user.id] = "add_channel"
    bot.send_message(message.chat.id, "Kanal username'ini yuboring, masalan: @meningkanalim")

@bot.message_handler(func=lambda m: m.text == "➖ Kanalni o‘chirish")
def remove_channel_start(message):
    if not is_admin(message.from_user.id): return
    user_states[message.from_user.id] = "remove_channel"
    bot.send_message(message.chat.id, "O‘chirmoqchi bo‘lgan kanal username'ini yuboring, masalan: @meningkanalim")

@bot.message_handler(func=lambda m: m.text == "📢 Ommaviy xabar")
def broadcast_start(message):
    if not is_admin(message.from_user.id): return
    user_states[message.from_user.id] = "broadcast_wait"
    bot.send_message(message.chat.id, "Barcha bot foydalanuvchilariga yuboriladigan xabarni yuboring. Matn, rasm, video yoki hujjat yuborishingiz mumkin.\nBekor qilish: /cancel")

@bot.message_handler(commands=["cancel"])
def cancel_action(message):
    user_states.pop(message.from_user.id, None)
    user_drafts.pop(message.from_user.id, None)
    pending_broadcasts.pop(message.from_user.id, None)
    bot.send_message(message.chat.id, "Amal bekor qilindi.", reply_markup=main_menu(message.from_user.id))

@bot.message_handler(commands=["movies"])
def list_admin_movies(message):
    if not is_admin(message.from_user.id): return
    with db() as conn:
        rows = conn.execute("SELECT id, title, year FROM movies ORDER BY id DESC LIMIT 50").fetchall()
    if not rows:
        bot.send_message(message.chat.id, "Bazaga hali kino qo‘shilmagan.")
        return
    bot.send_message(message.chat.id, "\n".join(f"ID {r['id']} — {escape_html(r['title'])} ({r['year'] or 'yil yo‘q'})" for r in rows))

@bot.message_handler(func=lambda m: m.text == "📊 Statistika")
def stats(message):
    if not is_admin(message.from_user.id): return
    with db() as conn:
        movies = conn.execute("SELECT COUNT(*) AS n FROM movies").fetchone()["n"]
        users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    bot.send_message(message.chat.id, f"🎬 Kinolar: {movies}\n👥 Foydalanuvchilar: {users}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("movie:"))
def movie_callback(call):
    if not is_admin(call.from_user.id) and not subscribed_to_all(call.from_user.id):
        bot.answer_callback_query(call.id, "Avval majburiy kanallarga obuna bo‘ling.", show_alert=True)
        subscription_prompt(call.message.chat.id)
        return
    try:
        movie_id = int(call.data.split(":", 1)[1])
    except ValueError:
        bot.answer_callback_query(call.id, "Noto‘g‘ri kino ID.")
        return
    with db() as conn:
        movie = conn.execute("SELECT * FROM movies WHERE id = ?", (movie_id,)).fetchone()
    if not movie:
        bot.answer_callback_query(call.id, "Bu kino bazada topilmadi.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    send_movie(call.message.chat.id, movie)

@bot.message_handler(content_types=["video", "document", "animation", "photo"])
def receive_media(message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        if not allowed_to_use(message): return
        return
    state = user_states.get(user_id)
    if state == "broadcast_wait":
        pending_broadcasts[user_id] = message.message_id
        user_states[user_id] = "broadcast_confirm"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.row("✅ Yuborish", "❌ Bekor qilish")
        bot.send_message(message.chat.id, "Xabar tayyor. Uni barcha foydalanuvchilarga yuboraymi?", reply_markup=markup)
        return
    if state != "add_video":
        return
    file_id = None
    file_type = None
    if message.content_type == "video":
        file_id, file_type = message.video.file_id, "video"
    elif message.content_type == "animation":
        file_id, file_type = message.animation.file_id, "animation"
    elif message.content_type == "document":
        file_id, file_type = message.document.file_id, "document"
    elif message.content_type == "photo":
        file_id, file_type = message.photo[-1].file_id, "photo"
    if not file_id:
        bot.reply_to(message, "Faylni o‘qib bo‘lmadi. Qaytadan yuboring.")
        return
    user_drafts[user_id] = {"file_id": file_id, "file_type": file_type}
    user_states[user_id] = "add_title"
    bot.send_message(message.chat.id, "Kino nomini yozing:")

@bot.message_handler(func=lambda m: True, content_types=["text"])
def text_router(message):
    user_id = message.from_user.id
    text = (message.text or "").strip()
    state = user_states.get(user_id)

    if is_admin(user_id) and state == "broadcast_confirm":
        if text == "❌ Bekor qilish":
            pending_broadcasts.pop(user_id, None)
            user_states.pop(user_id, None)
            bot.send_message(message.chat.id, "Ommaviy xabar bekor qilindi.", reply_markup=admin_menu())
            return
        if text == "✅ Yuborish":
            source_message_id = pending_broadcasts.pop(user_id, None)
            user_states.pop(user_id, None)
            with db() as conn:
                recipients = [r["user_id"] for r in conn.execute("SELECT user_id FROM users").fetchall()]
            sent = failed = 0
            for recipient in recipients:
                try:
                    bot.copy_message(recipient, message.chat.id, source_message_id)
                    sent += 1
                except Exception:
                    failed += 1
            bot.send_message(message.chat.id, f"📢 Yuborish yakunlandi.\n✅ Yetkazildi: {sent}\n⚠️ Yetkazilmadi: {failed}", reply_markup=admin_menu())
            return
        bot.send_message(message.chat.id, "Yuborish uchun «✅ Yuborish» yoki bekor qilish uchun «❌ Bekor qilish»ni bosing.")
        return

    if is_admin(user_id) and state == "add_channel":
        channel = text if text.startswith("@") else "@" + text
        if not channel[1:].replace("_", "").isalnum():
            bot.send_message(message.chat.id, "Username noto‘g‘ri ko‘rinadi. Masalan: @meningkanalim")
            return
        try:
            chat = bot.get_chat(channel)
            bot.get_chat_member(channel, bot.get_me().id)
        except Exception:
            bot.send_message(message.chat.id, "Kanal topilmadi yoki bot kanalni tekshira olmadi. Botni kanalga administrator qilib, yana urinib ko‘ring.")
            return
        with db() as conn:
            conn.execute("INSERT OR IGNORE INTO required_channels(channel) VALUES (?)", (channel,))
        user_states.pop(user_id, None)
        bot.send_message(message.chat.id, f"✅ Majburiy obuna kanali qo‘shildi: {escape_html(channel)}", reply_markup=admin_menu())
        return

    if is_admin(user_id) and state == "remove_channel":
        channel = text if text.startswith("@") else "@" + text
        with db() as conn:
            cursor = conn.execute("DELETE FROM required_channels WHERE channel = ?", (channel,))
        user_states.pop(user_id, None)
        bot.send_message(message.chat.id, "✅ Kanal o‘chirildi." if cursor.rowcount else "Bu kanal ro‘yxatda topilmadi.", reply_markup=admin_menu())
        return

    if state in ("search", "genre", "year") and not allowed_to_use(message):
        user_states.pop(user_id, None)
        return

    if state == "search":
        with db() as conn:
            rows = conn.execute("SELECT * FROM movies WHERE title LIKE ? ORDER BY title LIMIT 15", (f"%{text}%",)).fetchall()
        user_states.pop(user_id, None)
        show_movies(message.chat.id, rows)
        return
    if state == "genre":
        with db() as conn:
            rows = conn.execute("SELECT * FROM movies WHERE genre LIKE ? ORDER BY title LIMIT 15", (f"%{text}%",)).fetchall()
        user_states.pop(user_id, None)
        show_movies(message.chat.id, rows)
        return
    if state == "year":
        if not text.isdigit() or len(text) != 4:
            bot.send_message(message.chat.id, "Yilni 4 ta raqam bilan yozing, masalan: 2024.")
            return
        with db() as conn:
            rows = conn.execute("SELECT * FROM movies WHERE year = ? ORDER BY title LIMIT 15", (int(text),)).fetchall()
        user_states.pop(user_id, None)
        show_movies(message.chat.id, rows)
        return

    if is_admin(user_id) and state == "add_title":
        user_drafts[user_id]["title"] = text
        user_states[user_id] = "add_year"
        bot.send_message(message.chat.id, "Chiqarilgan yilini yozing (masalan 2024) yoki bilmasangiz 0 yuboring:")
        return
    if is_admin(user_id) and state == "add_year":
        if not text.isdigit() or (int(text) != 0 and not 1888 <= int(text) <= 2100):
            bot.send_message(message.chat.id, "Yilni to‘g‘ri kiriting (1888–2100) yoki 0 yuboring.")
            return
        user_drafts[user_id]["year"] = int(text) or None
        user_states[user_id] = "add_genre"
        bot.send_message(message.chat.id, "Janrini yozing (masalan: Fantastika, Sarguzasht):")
        return
    if is_admin(user_id) and state == "add_genre":
        user_drafts[user_id]["genre"] = text
        user_states[user_id] = "add_description"
        bot.send_message(message.chat.id, "Qisqacha tavsif yozing yoki o‘tkazib yuborish uchun - yuboring:")
        return
    if is_admin(user_id) and state == "add_description":
        draft = user_drafts.pop(user_id, {})
        with db() as conn:
            cursor = conn.execute(
                """INSERT INTO movies(title, year, genre, description, file_id, file_type, added_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (draft.get("title"), draft.get("year"), draft.get("genre"), "" if text == "-" else text,
                 draft.get("file_id"), draft.get("file_type"), user_id)
            )
            movie_id = cursor.lastrowid
        user_states.pop(user_id, None)
        bot.send_message(message.chat.id, f"✅ Kino bazaga qo‘shildi!\nID: <code>{movie_id}</code>\nNomi: {escape_html(draft.get('title'))}", reply_markup=admin_menu())
        return
    if is_admin(user_id) and state == "delete":
        if not text.isdigit():
            bot.send_message(message.chat.id, "Kino ID raqamini yuboring, masalan: 12.")
            return
        with db() as conn:
            cursor = conn.execute("DELETE FROM movies WHERE id = ?", (int(text),))
        user_states.pop(user_id, None)
        bot.send_message(message.chat.id, "✅ Kino o‘chirildi." if cursor.rowcount else "Bunday ID topilmadi.", reply_markup=admin_menu())
        return

    if text and not text.startswith("/"):
        if not allowed_to_use(message): return
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM movies WHERE title LIKE ? OR genre LIKE ? OR CAST(year AS TEXT) = ? ORDER BY title LIMIT 15",
                (f"%{text}%", f"%{text}%", text)
            ).fetchall()
        show_movies(message.chat.id, rows, "😕 Bunday kino topilmadi. Menyudan nom, janr yoki yil bo‘yicha qidirib ko‘ring.")

init_db()
logging.info("Kino bot ishga tushmoqda.")
bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
