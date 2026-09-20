import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)

logger = logging.getLogger(__name__)

def get_db():
    """اتصال بقاعدة البيانات"""
    from app import DB_PATH
    return sqlite3.connect(DB_PATH)

def get_items(bot_id):
    """جلب منتجات البوت"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, title, description, price FROM items WHERE bot_id=?", (bot_id,))
    items = c.fetchall()
    conn.close()
    return items

def save_user(bot_id, user):
    """حفظ المستخدم"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE bot_id=? AND user_id=?", (bot_id, user.id))
    if not c.fetchone():
        c.execute('''
            INSERT INTO users (bot_id, user_id, username, first_name)
            VALUES (?, ?, ?, ?)
        ''', (bot_id, str(user.id), user.username or '', user.first_name or ''))
        conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /start"""
    user = update.effective_user
    bot_id = context.bot_data['bot_id']
    admin_id = context.bot_data['admin_id']
    
    save_user(bot_id, user)
    
    keyboard = [
        [InlineKeyboardButton("🛒 تصفح المنتجات", callback_data="browse")],
        [InlineKeyboardButton("ℹ️ عن المتجر", callback_data="about")],
    ]
    if str(user.id) == str(admin_id):
        keyboard.append([InlineKeyboardButton("👑 لوحة الأدمن", callback_data="admin")])
    
    await update.message.reply_text(
        f"👋 أهلاً {user.first_name}!\n\n"
        f"🛒 مرحباً بك في متجرنا الإلكتروني\n"
        f"اختر من القائمة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع الأزرار"""
    query = update.callback_query
    await query.answer()
    
    bot_id = context.bot_data['bot_id']
    admin_id = context.bot_data['admin_id']
    data = query.data
    
    if data == "browse":
        items = get_items(bot_id)
        if not items:
            await query.edit_message_text(
                "😢 لا توجد منتجات حالياً\n\n"
                "تواصل مع الأدمن لإضافة منتجات.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 رجوع", callback_data="back")
                ]])
            )
            return
        
        keyboard = []
        for item in items:
            keyboard.append([InlineKeyboardButton(
                f"📦 {item[1]} — {item[3] or 'مجاناً'}",
                callback_data=f"item_{item[0]}"
            )])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
        
        await query.edit_message_text(
            "🛒 *المنتجات المتاحة:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif data.startswith("item_"):
        item_id = int(data.split("_")[1])
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT title, description, price, link FROM items WHERE id=?", (item_id,))
        item = c.fetchone()
        conn.close()
        
        if item:
            text = f"📦 *{item[0]}*\n\n"
            text += f"📝 {item[1] or 'لا يوجد وصف'}\n\n"
            text += f"💰 السعر: {item[2] or 'مجاناً'}\n"
            if item[3]:
                text += f"🔗 الرابط: {item[3]}"
            
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🛍️ شراء", callback_data=f"buy_{item_id}"),
                    InlineKeyboardButton("🔙 رجوع", callback_data="browse")
                ]]),
                parse_mode='Markdown'
            )
    
    elif data.startswith("buy_"):
        await query.edit_message_text(
            "✅ تم إرسال طلبك للأدمن\n\n"
            "سيتم التواصل معك قريباً.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 القائمة", callback_data="back")
            ]])
        )
        # إشعار الأدمن
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"🔔 *طلب جديد!*\n\n"
                     f"👤 من: {query.from_user.first_name}\n"
                     f"🆔 `{query.from_user.id}`",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to notify admin: {e}")
    
    elif data == "about":
        await query.edit_message_text(
            "ℹ️ *عن المتجر*\n\n"
            "متجر إلكتروني موثوق\n"
            "✅ منتجات أصلية\n"
            "⚡ توصيل سريع\n"
            "💬 دعم فني 24/7",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="back")
            ]]),
            parse_mode='Markdown'
        )
    
    elif data == "admin":
        if str(query.from_user.id) != str(admin_id):
            await query.answer("⛔ أنت لست الأدمن", show_alert=True)
            return
        
        await query.edit_message_text(
            "👑 *لوحة الأدمن*\n\n"
            "استخدم الموقع للتحكم الكامل في البوت:\n"
            "• إضافة منتجات\n"
            "• إدارة الطلبات\n"
            "• الإحصائيات",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 رجوع", callback_data="back")
            ]]),
            parse_mode='Markdown'
        )
    
    elif data == "back":
        await start_from_callback(query, context, admin_id)

async def start_from_callback(query, context, admin_id):
    """إعادة عرض القائمة الرئيسية"""
    keyboard = [
        [InlineKeyboardButton("🛒 تصفح المنتجات", callback_data="browse")],
        [InlineKeyboardButton("ℹ️ عن المتجر", callback_data="about")],
    ]
    if str(query.from_user.id) == str(admin_id):
        keyboard.append([InlineKeyboardButton("👑 لوحة الأدمن", callback_data="admin")])
    
    await query.edit_message_text(
        f"👋 أهلاً {query.from_user.first_name}!\n\n"
        f"🛒 اختر من القائمة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def run_bot(token, admin_id, bot_id, db_path):
    """تشغيل البوت"""
    logger.info(f"🛒 Store bot {bot_id} starting...")
    
    app = Application.builder().token(token).build()
    
    # حفظ البيانات
    app.bot_data['bot_id'] = bot_id
    app.bot_data['admin_id'] = admin_id
    
    # الأوامر
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info(f"✅ Store bot {bot_id} is running")
    app.run_polling(drop_pending_updates=True)