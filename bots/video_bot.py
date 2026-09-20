import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logger = logging.getLogger(__name__)

def get_db():
    from app import DB_PATH
    return sqlite3.connect(DB_PATH)

def get_videos(bot_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, title, description, link FROM items WHERE bot_id=?", (bot_id,))
    videos = c.fetchall()
    conn.close()
    return videos

def save_user(bot_id, user):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE bot_id=? AND user_id=?", (bot_id, user.id))
    if not c.fetchone():
        c.execute('INSERT INTO users (bot_id, user_id, username, first_name) VALUES (?,?,?,?)',
                  (bot_id, str(user.id), user.username or '', user.first_name or ''))
        conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    bot_id = context.bot_data['bot_id']
    save_user(bot_id, user)
    
    keyboard = [
        [InlineKeyboardButton("🎬 الفيديوهات", callback_data="list")],
        [InlineKeyboardButton("🔍 بحث", callback_data="search")],
    ]
    await update.message.reply_text(
        f"👋 أهلاً {user.first_name}!\n\n🎬 بوت الفيديوهات\nاختر:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    bot_id = context.bot_data['bot_id']
    data = query.data
    
    if data == "list":
        videos = get_videos(bot_id)
        if not videos:
            await query.edit_message_text("😢 لا توجد فيديوهات حالياً")
            return
        
        keyboard = []
        for v in videos:
            keyboard.append([InlineKeyboardButton(f"🎬 {v[1]}", callback_data=f"play_{v[0]}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
        
        await query.edit_message_text("🎬 *قائمة الفيديوهات:*",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    elif data.startswith("play_"):
        vid = int(data.split("_")[1])
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT title, description, link FROM items WHERE id=?", (vid,))
        v = c.fetchone()
        conn.close()
        if v:
            text = f"🎬 *{v[0]}*\n\n📝 {v[1] or ''}\n\n"
            if v[2]:
                text += f"🔗 [مشاهدة الفيديو]({v[2]})"
            await query.edit_message_text(text, parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="list")]]))
    
    elif data == "back":
        await query.edit_message_text("🎬 اختر:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 الفيديوهات", callback_data="list")],
            [InlineKeyboardButton("🔍 بحث", callback_data="search")],
        ]))
    
    elif data == "search":
        await query.edit_message_text("🔍 اكتب اسم الفيديو:")

def run_bot(token, admin_id, bot_id, db_path):
    logger.info(f"🎬 Video bot {bot_id} starting...")
    app = Application.builder().token(token).build()
    app.bot_data['bot_id'] = bot_id
    app.bot_data['admin_id'] = admin_id
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling(drop_pending_updates=True)