import os
import json
import sqlite3
import threading
import logging
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

# ===== تحميل المتغيرات =====
load_dotenv()

# ===== إعداد السيرفر =====
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# ===== إعداد اللوج =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===== قاعدة البيانات =====
DB_PATH = 'database/bots.db'
os.makedirs('database', exist_ok=True)

def init_db():
    """إنشاء الجداول لو مش موجودة"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # جدول البوتات
    c.execute('''
        CREATE TABLE IF NOT EXISTS bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            admin_id TEXT NOT NULL,
            bot_type TEXT NOT NULL,
            bot_username TEXT,
            bot_name TEXT,
            status TEXT DEFAULT 'running',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # جدول العناصر (منتجات/فيديوهات/كورسات...)
    c.execute('''
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            price TEXT,
            link TEXT,
            extra TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (bot_id) REFERENCES bots (id)
        )
    ''')

    # جدول المستخدمين
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT,
            first_name TEXT,
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (bot_id) REFERENCES bots (id)
        )
    ''')

    # جدول الطلبات
    c.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            item_id INTEGER,
            details TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (bot_id) REFERENCES bots (id)
        )
    ''')

    conn.commit()
    conn.close()
    logger.info("✅ Database initialized")

init_db()

# ===== تخزين البوتات الشغالة في الذاكرة =====
running_bots = {}  # {bot_id: thread_object}

# ===== استيراد البوتات =====
# ملاحظة: بيتم استيراد البوتين الموجودين بس حالياً
# لما ترفع باقي البوتات، شيل الكومنت عنهم
try:
    from bots import store_bot, video_bot
    BOT_MODULES = {
        'store': store_bot,
        'video': video_bot,
    }
    logger.info(f"✅ Loaded {len(BOT_MODULES)} bot modules")
except Exception as e:
    logger.error(f"❌ Failed to import bots: {e}")
    BOT_MODULES = {}

# ===== المسار الرئيسي =====
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# ===== API: إنشاء بوت =====
@app.route('/api/create_bot', methods=['POST'])
def create_bot():
    try:
        data = request.json
        token = data.get('token', '').strip()
        admin_id = data.get('admin_id', '').strip()
        bot_type = data.get('bot_type', '').strip()

        # التحقق من البيانات
        if not all([token, admin_id, bot_type]):
            return jsonify({'success': False, 'error': 'جميع الحقول مطلوبة'}), 400

        if ':' not in token:
            return jsonify({'success': False, 'error': 'التوكن غير صحيح'}), 400

        if bot_type not in BOT_MODULES:
            return jsonify({
                'success': False,
                'error': f'نوع البوت غير مدعوم: {bot_type}. المتاح: {list(BOT_MODULES.keys())}'
            }), 400

        # التحقق من التوكن عبر Telegram API
        import requests as req
        try:
            resp = req.get(f'https://api.telegram.org/bot{token}/getMe', timeout=10)
            if resp.status_code != 200:
                return jsonify({'success': False, 'error': 'التوكن غير صالح أو منتهي'}), 400
            bot_info = resp.json()['result']
        except Exception as e:
            return jsonify({'success': False, 'error': f'فشل الاتصال بتليجرام: {str(e)}'}), 400

        bot_username = bot_info.get('username', '')
        bot_name = bot_info.get('first_name', '')

        # حفظ في قاعدة البيانات
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute('''
                INSERT INTO bots (token, admin_id, bot_type, bot_username, bot_name, status)
                VALUES (?, ?, ?, ?, ?, 'running')
            ''', (token, admin_id, bot_type, bot_username, bot_name))
            bot_id = c.lastrowid
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({'success': False, 'error': 'البوت مسجل بالفعل'}), 400
        conn.close()

        # تشغيل البوت
        start_bot(bot_id, token, admin_id, bot_type)

        logger.info(f"✅ Bot created: @{bot_username} (type: {bot_type})")

        return jsonify({
            'success': True,
            'bot_id': bot_id,
            'bot_username': bot_username,
            'bot_name': bot_name,
            'bot_type': bot_type,
            'message': f'تم إنشاء البوت @{bot_username} بنجاح'
        })

    except Exception as e:
        logger.error(f"❌ Error creating bot: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ===== دالة تشغيل بوت =====
def start_bot(bot_id, token, admin_id, bot_type):
    """تشغيل البوت في Thread منفصل"""
    if bot_id in running_bots:
        logger.warning(f"Bot {bot_id} already running")
        return

    module = BOT_MODULES.get(bot_type)
    if not module:
        logger.error(f"Unknown bot type: {bot_type}")
        return

    def run():
        try:
            module.run_bot(token, admin_id, bot_id, DB_PATH)
        except Exception as e:
            logger.error(f"Bot {bot_id} crashed: {e}")
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE bots SET status='stopped' WHERE id=?", (bot_id,))
            conn.commit()
            conn.close()
            running_bots.pop(bot_id, None)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    running_bots[bot_id] = thread
    logger.info(f"🚀 Bot {bot_id} started in thread")

# ===== API: إيقاف بوت =====
@app.route('/api/stop_bot', methods=['POST'])
def stop_bot():
    try:
        data = request.json
        bot_id = data.get('bot_id')

        if not bot_id:
            return jsonify({'success': False, 'error': 'bot_id مطلوب'}), 400

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE bots SET status='stopped' WHERE id=?", (bot_id,))
        conn.commit()
        conn.close()

        running_bots.pop(bot_id, None)

        return jsonify({'success': True, 'message': 'تم إيقاف البوت'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ===== API: إضافة عنصر =====
@app.route('/api/add_item', methods=['POST'])
def add_item():
    try:
        data = request.json
        bot_id = data.get('bot_id')
        title = data.get('title', '').strip()
        description = data.get('description', '').strip()
        price = data.get('price', '').strip()
        link = data.get('link', '').strip()

        if not bot_id or not title:
            return jsonify({'success': False, 'error': 'العنوان مطلوب'}), 400

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO items (bot_id, title, description, price, link)
            VALUES (?, ?, ?, ?, ?)
        ''', (bot_id, title, description, price, link))
        item_id = c.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"✅ Item added to bot {bot_id}: {title}")

        return jsonify({
            'success': True,
            'item_id': item_id,
            'message': 'تم إضافة العنصر بنجاح'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ===== API: عرض العناصر =====
@app.route('/api/items/<int:bot_id>', methods=['GET'])
def get_items(bot_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            SELECT id, title, description, price, link, created_at
            FROM items WHERE bot_id=? ORDER BY id DESC
        ''', (bot_id,))
        rows = c.fetchall()
        conn.close()

        items = [{
            'id': r[0], 'title': r[1], 'description': r[2],
            'price': r[3], 'link': r[4], 'created_at': r[5]
        } for r in rows]

        return jsonify({'success': True, 'items': items})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ===== API: حذف عنصر =====
@app.route('/api/delete_item', methods=['POST'])
def delete_item():
    try:
        data = request.json
        item_id = data.get('item_id')

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM items WHERE id=?", (item_id,))
        conn.commit()
        conn.close()

        return jsonify({'success': True, 'message': 'تم الحذف'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ===== API: إحصائيات البوت =====
@app.route('/api/stats/<int:bot_id>', methods=['GET'])
def get_stats(bot_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM items WHERE bot_id=?", (bot_id,))
        items_count = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM users WHERE bot_id=?", (bot_id,))
        users_count = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM orders WHERE bot_id=?", (bot_id,))
        orders_count = c.fetchone()[0]

        conn.close()

        return jsonify({
            'success': True,
            'stats': {
                'items': items_count,
                'users': users_count,
                'orders': orders_count
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ===== API: عرض المستخدمين =====
@app.route('/api/users/<int:bot_id>', methods=['GET'])
def get_users(bot_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            SELECT user_id, username, first_name, joined_at
            FROM users WHERE bot_id=? ORDER BY id DESC LIMIT 100
        ''', (bot_id,))
        rows = c.fetchall()
        conn.close()

        users = [{
            'user_id': r[0], 'username': r[1],
            'first_name': r[2], 'joined_at': r[3]
        } for r in rows]

        return jsonify({'success': True, 'users': users})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ===== API: حالة السيرفر =====
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'running_bots': len(running_bots),
        'available_types': list(BOT_MODULES.keys())
    })

# ===== إعادة تشغيل البوتات عند بدء السيرفر =====
def restore_bots():
    """عند بدء السيرفر، شغّل كل البوتات اللي كانت شغالة"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, token, admin_id, bot_type FROM bots WHERE status='running'")
        bots = c.fetchall()
        conn.close()

        for bot in bots:
            bot_id, token, admin_id, bot_type = bot
            logger.info(f"🔄 Restoring bot {bot_id} ({bot_type})")
            start_bot(bot_id, token, admin_id, bot_type)
    except Exception as e:
        logger.error(f"Restore error: {e}")

# ===== تشغيل السيرفر =====
if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    logger.info(f"🚀 Starting server on port {port}")
    restore_bots()
    app.run(host='0.0.0.0', port=port, debug=False)
else:
    # عند التشغيل من gunicorn
    restore_bots()