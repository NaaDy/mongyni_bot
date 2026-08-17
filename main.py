import logging
import sqlite3
import json
import requests
import uuid
import os
import time
import hmac
import hashlib
import html as html_lib
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters

load_dotenv()

DB_PATH = os.getenv('DB_PATH', 'mongyni.db')
REQUEST_TIMEOUT = 15  # seconds — so a slow payment API can never freeze the whole bot
OXAPAY_MIN_INVOICE = 0.50  # OxaPay minimum USD invoice limit

OXAPAY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

# --- CONFIGURATION DEFAULT FALLBACKS ---
ADMIN_ID = int(os.getenv("ADMIN_ID", "1477846847"))  # Telegram Admin User ID
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://naady.github.io/mongyni_bot/")

# --- PRODUCTS WITH BULK DISCOUNTS ---
PRODUCTS = {
    "office365": {
        "name": "Office 365 1TB",
        "description": "1TB OneDrive storage + full Office apps, 1 year subscription.",
        "price": 1.30,
        "bulk_discounts": [
            {"min_qty": 5, "price": 1.20},
            {"min_qty": 10, "price": 1.10}
        ]
    },
    "hotmail": {
        "name": "Hotmail Trusted OAuth2 V8 (7-90 Days Aged)",
        "description": """📧 What You Receive

✅ Hotmail Trusted OAuth2 V8 account
✅ Account age: 7–90 Days
✅ Format: mail | password | refreshtoken
✅ Instant delivery
✅ FREE delivery 24/7
✅ Fast & easy access
✅ Details delivered automatically after purchase

🛠️ How to Use
1. Go to: https://aquamarine-pie-24ef2f.netlify.app/
2. Paste the information you received from the bot.
3. Click on the email.
4. Follow the instructions to access the account.

⚡ Why Buy From Us?
🚀 Instant delivery
🕐 Available 24/7
🎁 Free delivery
⚡ Fast service
🔑 OAuth2 V8 format
📅 7–90 Days Aged accounts""",
        "price": 0.018,
        "bulk_discounts": [
            {"min_qty": 50, "price": 0.015},
            {"min_qty": 100, "price": 0.012}
        ]
    },
    "hotmail_graph": {
        "name": "Hotmail Trusted - OAuth2 [Graph] (Live 12-36M)",
        "description": """📧 What You Receive

✅ Hotmail Trusted - OAuth2 [Graph] account
✅ Account age / Validity: Live 12 - 36 Months (100% 7day skip Zin)
✅ Format: mail | password | refreshtoken
✅ Instant delivery 24/7
✅ Details delivered automatically after purchase

📝 Description:
Get trusted, long-term Hotmail accounts with OAuth2 Graph API access, valid for 12-36 months - 100% genuine and ready for automation, bulk emailing, or secure multi-account management. Perfect for marketers and developers needing reliable, aged inboxes with zero risk of lockout.

🛠️ How to Use
1. Go to: https://aquamarine-pie-24ef2f.netlify.app/
2. Paste the information you received from the bot.
3. Click on the email.
4. Follow the instructions to access the account.

⚡ Why Buy From Us?
🚀 Instant delivery 24/7
🔑 OAuth2 Graph API access
📅 Live 12 - 36 Months (100% 7day skip Zin)""",
        "price": 0.019,
        "bulk_discounts": [
            {"min_qty": 50, "price": 0.016},
            {"min_qty": 100, "price": 0.013}
        ]
    },
}

# --- MULTI-LANGUAGE DICTIONARY ---
STRINGS = {
    "ar": {
        "welcome": "مرحباً بك في متجر Mongyni Store!\n\nمعرفك: <code>{user_id}</code>\nرصيدك: <b>${balance:.2f}</b>\n\nيرجى اختيار المنتج المطلوب أدناه:",
        "add_funds": "💳 إضافة رصيد",
        "support": "💬 الدعم الفني",
        "my_orders": "📜 طلباتي",
        "referral": "👥 رابط الإحالة",
        "lang_switch": "🌐 الإنجليزية / English",
        "stock": "المخزون",
        "out_of_stock": "عذراً، هذا المنتج غير متوفر حالياً.",
        "quantity_prompt": "✏️ كم العدد الذي ترغب بشرائه؟ يرجى إرسال رقم.",
        "insufficient_balance": "❌ <b>رصيدك غير كافٍ</b> (${balance:.2f}). المطلوب: <b>${total:.2f}</b>.",
        "purchase_success": "✅ اكتمل الشراء بنجاح! {qty}x {name} — تم خصم ${total:.2f}.\nالرصيد المتبقي: ${balance:.2f}\n\nإليك بيانات الحسابات:\n{delivery}",
        "cancel": "◀ إلغاء",
        "main_menu": "◀ القائمة الرئيسية",
        "apply_coupon": "🎟️ استخدام كود خصم",
        "coupon_prompt": "✏️ يرجى كتابة كود الخصم وإرساله في الشات:",
        "coupon_applied": "✅ تم تطبيق كود الخصم بنجاح!",
        "coupon_invalid": "❌ كود الخصم غير صالح أو انتهت الكمية المتاحة منه.",
        "ref_msg": "👥 <b>نظام الدعوة والإحالة</b>\n\nرابط الدعوة الخاص بك:\n<code>{ref_link}</code>\n\nاحصل على <b>5%</b> رصيد مجاني من كل عملية شراء أو شحن يقوم بها الأشخاص الذين تدعوهم!\n\n• إجمالي المدعوين: <b>{invited_count}</b>\n• أرباحك من الإحالات: <b>${ref_earnings:.2f}</b>",
        "my_orders_title": "📜 <b>سجل طلباتك السابقة:</b>\n\n",
        "no_orders": "ℹ️ ليس لديك أي طلبات سابقة حتى الآن."
    },
    "en": {
        "welcome": "Welcome to Mongyni Store!\n\nYour ID: <code>{user_id}</code>\nYour Balance: <b>${balance:.2f}</b>\n\nPlease select a product below:",
        "add_funds": "💳 Add Funds",
        "support": "💬 Support",
        "my_orders": "📜 My Orders",
        "referral": "👥 Referral Link",
        "lang_switch": "🌐 العربية / Arabic",
        "stock": "Stock",
        "out_of_stock": "Sorry, this product is currently out of stock.",
        "quantity_prompt": "✏️ How many do you want? Please type a number.",
        "insufficient_balance": "❌ <b>Insufficient Balance</b> (${balance:.2f}). Total required: <b>${total:.2f}</b>.",
        "purchase_success": "✅ Purchase successful! {qty}x {name} — ${total:.2f} deducted.\nRemaining balance: ${balance:.2f}\n\nHere are your details:\n{delivery}",
        "cancel": "◀ Cancel",
        "main_menu": "◀ Main Menu",
        "apply_coupon": "🎟️ Apply Promo Code",
        "coupon_prompt": "✏️ Please type and send your promo code in chat:",
        "coupon_applied": "✅ Promo code applied successfully!",
        "coupon_invalid": "❌ Promo code is invalid or usage limit reached.",
        "ref_msg": "👥 <b>Referral & Affiliate System</b>\n\nYour Unique Referral Link:\n<code>{ref_link}</code>\n\nEarn <b>5%</b> free balance rewards on every deposit or purchase made by people you invite!\n\n• Total Invited Users: <b>{invited_count}</b>\n• Referral Earnings: <b>${ref_earnings:.2f}</b>",
        "my_orders_title": "📜 <b>Your Purchase History:</b>\n\n",
        "no_orders": "ℹ️ You have no previous orders yet."
    }
}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# --- OXAPAY SAFE REQUEST HELPER ---
def oxapay_post_request(endpoint, payload):
    url = f"https://api.oxapay.com{endpoint}"
    try:
        res = requests.post(url, headers=OXAPAY_HEADERS, json=payload, timeout=REQUEST_TIMEOUT)
        try:
            return True, res.status_code, res.json()
        except Exception:
            return False, res.status_code, f"Non-JSON response (HTTP {res.status_code}): {res.text[:150]}"
    except Exception as e:
        return False, 0, f"Network error: {str(e)}"

# --- DATABASE SETUP & MIGRATIONS ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance REAL, lang TEXT DEFAULT 'en', referred_by INTEGER DEFAULT 0, ref_earnings REAL DEFAULT 0.0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, product_id TEXT, data TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (track_id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, status TEXT, method TEXT, product_id TEXT, qty INTEGER, extra_credit REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS coupons (code TEXT PRIMARY KEY, discount_type TEXT, discount_value REAL, uses_left INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, product_id TEXT, qty INTEGER, total_price REAL, items_delivered TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    cursor.execute("PRAGMA table_info(transactions)")
    cols = [column[1] for column in cursor.fetchall()]
    if 'method' not in cols:
        cursor.execute('ALTER TABLE transactions ADD COLUMN method TEXT')
    if 'product_id' not in cols:
        cursor.execute('ALTER TABLE transactions ADD COLUMN product_id TEXT')
    if 'qty' not in cols:
        cursor.execute('ALTER TABLE transactions ADD COLUMN qty INTEGER')
    if 'extra_credit' not in cols:
        cursor.execute('ALTER TABLE transactions ADD COLUMN extra_credit REAL')

    cursor.execute("PRAGMA table_info(users)")
    user_cols = [c[1] for c in cursor.fetchall()]
    if 'lang' not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN lang TEXT DEFAULT 'en'")
    if 'referred_by' not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER DEFAULT 0")
    if 'ref_earnings' not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN ref_earnings REAL DEFAULT 0.0")

    conn.commit()
    conn.close()

def get_setting(key, default=""):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    if row and row[0]:
        return row[0]
    val = os.getenv(key, "")
    return val if val else default

def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def get_bot_token():
    return get_setting("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

def get_oxapay_merchant_key():
    return get_setting("OXAPAY_MERCHANT_KEY", "YOUR_OXAPAY_MERCHANT_KEY")

def get_bybit_uid():
    return get_setting("BYBIT_UID", "YOUR_BYBIT_UID_HERE")

def get_bybit_api_key():
    return get_setting("BYBIT_API_KEY", "")

def get_bybit_api_secret():
    return get_setting("BYBIT_API_SECRET", "")

def get_support_username():
    return get_setting("SUPPORT_USERNAME", "mongyni").lstrip("@")

def get_support_url():
    username = get_support_username()
    return f"https://t.me/{username}"

def get_required_channel():
    return get_setting("REQUIRED_CHANNEL", "").strip()

async def check_channel_membership(bot, user_id):
    channel = get_required_channel()
    if not channel or user_id == ADMIN_ID:
        return True
    try:
        chat_member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        if chat_member.status in ("creator", "administrator", "member"):
            return True
    except Exception as e:
        logging.warning(f"Error checking channel membership for user {user_id} in {channel}: {e}")
        return True
    return False

async def prompt_join_channel(update_or_query, channel, lang="en"):
    clean_ch = channel.lstrip("@")
    url = f"https://t.me/{clean_ch}"
    if lang == "ar":
        msg = (f"📢 <b>الانضمام لقناة البث الرسمية مطلوب</b>\n\n"
               f"لاستخدام البوت ومتابعة التحديثات والمخزون الجديد، يرجى الانضمام للقناة أولاً:\n"
               f"<code>{channel}</code>")
        btn_join = "📢 الانضمام للقناة الرسمية"
        btn_check = "✅ تم الانضمام — متابعة"
    else:
        msg = (f"📢 <b>Official Updates Channel Required</b>\n\n"
               f"To use our bot and get restock updates, please join our official channel first:\n"
               f"<code>{channel}</code>")
        btn_join = "📢 Join Official Channel"
        btn_check = "✅ I Have Joined — Continue"

    keyboard = [
        [InlineKeyboardButton(btn_join, url=url)],
        [InlineKeyboardButton(btn_check, callback_data="check_joined")],
    ]
    if hasattr(update_or_query, 'edit_message_text'):
        await update_or_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    else:
        await update_or_query.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

def get_product_unit_price(product_id, qty=1):
    info = PRODUCTS.get(product_id)
    if not info:
        return 0.0
    base_price = info["price"]
    bulk = info.get("bulk_discounts", [])
    for tier in sorted(bulk, key=lambda x: x["min_qty"], reverse=True):
        if qty >= tier["min_qty"]:
            return tier["price"]
    return base_price

def get_user_lang(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT lang FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row and row[0] else 'en'

def set_user_lang(user_id, lang):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET lang = ? WHERE user_id = ?', (lang, user_id))
    conn.commit()
    conn.close()

def get_user_balance(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result is None:
        cursor.execute('INSERT INTO users (user_id, balance, lang) VALUES (?, ?, ?)', (user_id, 0.0, 'en'))
        conn.commit()
        balance = 0.0
    else:
        balance = result[0]
    conn.close()
    return balance

def update_user_balance(user_id, amount_change):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    if cursor.fetchone() is None:
        cursor.execute('INSERT INTO users (user_id, balance, lang) VALUES (?, ?, ?)', (user_id, amount_change, 'en'))
    else:
        cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount_change, user_id))
    conn.commit()
    conn.close()

def set_user_balance_exact(user_id, new_balance):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO users (user_id, balance, lang) VALUES (?, ?, ?)', (user_id, new_balance, 'en'))
    conn.commit()
    conn.close()

def register_user(user_id, language_code=None, referred_by=0):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
    if cursor.fetchone() is None:
        # Default to English unless user's Telegram language starts with 'ar'
        default_lang = 'ar' if language_code and str(language_code).lower().startswith('ar') else 'en'
        cursor.execute('INSERT INTO users (user_id, balance, lang, referred_by) VALUES (?, 0.0, ?, ?)', (user_id, default_lang, referred_by))
        conn.commit()
    conn.close()

def process_referral_reward(user_id, purchase_or_deposit_amount, bot_context=None):
    if purchase_or_deposit_amount <= 0:
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT referred_by FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row and row[0] and row[0] != user_id:
        referrer_id = row[0]
        reward = round(purchase_or_deposit_amount * 0.05, 4)  # 5% referral commission
        if reward > 0:
            cursor.execute('UPDATE users SET balance = balance + ?, ref_earnings = ref_earnings + ? WHERE user_id = ?', (reward, reward, referrer_id))
            conn.commit()
            conn.close()
            if bot_context:
                try:
                    bot_context.bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 <b>Referral Reward!</b>\nYou earned <b>${reward:.2f}</b> from a friend's purchase/deposit!",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
            return
    conn.close()

def get_referral_stats(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users WHERE referred_by = ?', (user_id,))
    invited_count = cursor.fetchone()[0]
    cursor.execute('SELECT ref_earnings FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    ref_earnings = row[0] if row and row[0] else 0.0
    conn.close()
    return invited_count, ref_earnings

def record_completed_order(user_id, product_id, qty, total_price, items_delivered):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    delivery_str = "\n".join(items_delivered) if isinstance(items_delivered, list) else str(items_delivered)
    cursor.execute('INSERT INTO orders (user_id, product_id, qty, total_price, items_delivered) VALUES (?, ?, ?, ?, ?)',
                   (user_id, product_id, qty, total_price, delivery_str))
    conn.commit()
    conn.close()

def get_user_orders(user_id, limit=10):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT product_id, qty, total_price, items_delivered, timestamp FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?', (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return rows

# --- COUPON HELPERS ---
def add_coupon(code, discount_type, discount_value, uses_left):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO coupons (code, discount_type, discount_value, uses_left) VALUES (?, ?, ?, ?)',
                   (code.upper(), discount_type, discount_value, uses_left))
    conn.commit()
    conn.close()

def get_coupon(code):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT discount_type, discount_value, uses_left FROM coupons WHERE code = ?', (code.upper(),))
    row = cursor.fetchone()
    conn.close()
    return row

def use_coupon(code):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE coupons SET uses_left = uses_left - 1 WHERE code = ? AND uses_left > 0', (code.upper(),))
    conn.commit()
    conn.close()

def list_coupons():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT code, discount_type, discount_value, uses_left FROM coupons')
    rows = cursor.fetchall()
    conn.close()
    return rows

def delete_coupon(code):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM coupons WHERE code = ?', (code.upper(),))
    rowcount = cursor.rowcount
    conn.commit()
    conn.close()
    return rowcount

def get_user_info(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    user_row = cursor.fetchone()
    if not user_row:
        conn.close()
        return None

    balance = user_row[0]
    cursor.execute('SELECT COUNT(*), SUM(amount) FROM transactions WHERE user_id = ? AND status = "completed"', (user_id,))
    tx_summary = cursor.fetchone()
    tx_count = tx_summary[0] if tx_summary else 0
    total_spent = tx_summary[1] if tx_summary and tx_summary[1] else 0.0

    cursor.execute('SELECT track_id, amount, method, status FROM transactions WHERE user_id = ? ORDER BY track_id DESC LIMIT 5', (user_id,))
    recent_txs = cursor.fetchall()
    conn.close()

    return {
        "user_id": user_id,
        "balance": balance,
        "tx_count": tx_count,
        "total_spent": total_spent,
        "recent_txs": recent_txs
    }

def get_all_users_list(limit=50):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT ?', (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_product_stock(product_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM inventory WHERE product_id = ?', (product_id,))
    stock = cursor.fetchone()[0]
    conn.close()
    return stock

def add_inventory_items(product_id, items):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executemany('INSERT INTO inventory (product_id, data) VALUES (?, ?)', [(product_id, item) for item in items])
    conn.commit()
    conn.close()

def clear_inventory_items(product_id=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if product_id and product_id != "all":
        cursor.execute('DELETE FROM inventory WHERE product_id = ?', (product_id,))
    else:
        cursor.execute('DELETE FROM inventory')
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted_count

def take_inventory_items(product_id, qty):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, data FROM inventory WHERE product_id = ? ORDER BY id LIMIT ?', (product_id, qty))
    rows = cursor.fetchall()
    if len(rows) < qty:
        conn.close()
        return None
    ids = [row[0] for row in rows]
    cursor.executemany('DELETE FROM inventory WHERE id = ?', [(i,) for i in ids])
    conn.commit()
    conn.close()
    return [row[1] for row in rows]

def check_and_notify_low_stock(product_id, bot_context=None):
    stock = get_product_stock(product_id)
    if stock <= 5 and bot_context:
        info = PRODUCTS.get(product_id, {})
        name = info.get("name", product_id)
        try:
            bot_context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⚠️ <b>LOW STOCK ALERT!</b>\n\nProduct: <b>{name}</b>\nRemaining Stock: <code>{stock}</code> items!\nRun <code>/addstock {product_id}</code> to replenish.",
                parse_mode="HTML"
            )
        except Exception as e:
            logging.warning(f"Could not send low stock alert to admin: {e}")

def create_transaction(track_id, user_id, amount, status, method, product_id=None, qty=0, extra_credit=0.0):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO transactions (track_id, user_id, amount, status, method, product_id, qty, extra_credit) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                   (track_id, user_id, amount, status, method, product_id, qty, extra_credit))
    conn.commit()
    conn.close()

def get_transaction(track_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT status, amount, method, product_id, qty, extra_credit FROM transactions WHERE track_id = ? AND user_id = ?', (track_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return row

def mark_transaction_completed(track_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE transactions SET status = ? WHERE track_id = ?', ("completed", track_id))
    conn.commit()
    conn.close()

# --- BYBIT API HELPERS ---
def bybit_signed_get(endpoint, params=None):
    params = params or {}
    timestamp = str(int(time.time() * 1000))
    recv_window = "5000"
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    api_key = get_bybit_api_key()
    api_secret = get_bybit_api_secret()
    sign_payload = timestamp + api_key + recv_window + query_string
    signature = hmac.new(api_secret.encode(), sign_payload.encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-BAPI-API-KEY": api_key,
        "X-BAPI-SIGN": signature,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-RECV-WINDOW": recv_window,
    }
    url = f"https://api.bybit.com{endpoint}"
    if query_string:
        url += f"?{query_string}"
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    return response.json()

def find_matching_bybit_deposit(expected_amount, tolerance=0.000001):
    try:
        data = bybit_signed_get("/v5/asset/deposit/query-record", {"coin": "USDT", "limit": "50"})
    except Exception as e:
        logging.error(f"Bybit API request error: {e}")
        return False

    if data.get("retCode") != 0:
        logging.error(f"Bybit API error: {data.get('retMsg')}")
        return False

    rows = data.get("result", {}).get("rows", [])
    for row in rows:
        try:
            row_amount = float(row.get("amount", 0))
        except (TypeError, ValueError):
            continue
        status = str(row.get("status"))
        if status in ("3", "success", "successful") and abs(row_amount - expected_amount) <= tolerance:
            return True
    return False

# --- BOT COMMANDS & UI ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_tg_lang = update.effective_user.language_code
    
    # Process Referral Link if present
    referred_by = 0
    if context.args and context.args[0].startswith("ref_"):
        try:
            referred_by = int(context.args[0].split("_")[1])
        except ValueError:
            referred_by = 0

    register_user(user_id, language_code=user_tg_lang, referred_by=referred_by)
    lang = get_user_lang(user_id)

    # Mandatory Channel Check
    req_channel = get_required_channel()
    if req_channel:
        is_member = await check_channel_membership(context.bot, user_id)
        if not is_member:
            await prompt_join_channel(update.callback_query if update.callback_query else update.message, req_channel, lang)
            return

    balance = get_user_balance(user_id)
    s = STRINGS[lang]

    keyboard = []
    for product_id, info in PRODUCTS.items():
        stock = get_product_stock(product_id)
        icon = "🔴" if stock == 0 else ("🔴" if stock < 10 else ("🟠" if stock <= 50 else "🟢"))
        price_str = f"${info['price']:.4f}".rstrip('0').rstrip('.') if info['price'] < 0.1 else f"${info['price']:.2f}"
        btn_text = f"{icon} {info['name']} - {price_str} ({s['stock']}: {stock})"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"prod_{product_id}")])

    support_url = get_support_url()
    keyboard.append([
        InlineKeyboardButton(s["add_funds"], callback_data="menu_addfunds"),
        InlineKeyboardButton(s["my_orders"], callback_data="menu_myorders")
    ])
    keyboard.append([
        InlineKeyboardButton(s["referral"], callback_data="menu_referral"),
        InlineKeyboardButton(s["support"], url=support_url)
    ])
    keyboard.append([
        InlineKeyboardButton(s["lang_switch"], callback_data="toggle_lang")
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = s["welcome"].format(user_id=user_id, balance=balance)
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode="HTML")

def build_product_intro(product_id, lang="en"):
    info = PRODUCTS[product_id]
    stock = get_product_stock(product_id)
    s = STRINGS[lang]

    price_str = f"${info['price']:.3f}"
    bulk = info.get("bulk_discounts", [])
    if bulk:
        price_str += " (Bulk Discounts Available:\n"
        for b in sorted(bulk, key=lambda x: x["min_qty"]):
            price_str += f"  • {b['min_qty']}+ qty = ${b['price']:.3f} each\n"
        price_str += ")"

    msg = (f"📦 {info['name']}\n\n"
           f"{info['description']}\n\n"
           f"Price: {price_str}\n"
           f"{s['stock']}: {stock}\n\n"
           f"{s['quantity_prompt']}")
    keyboard = [
        [InlineKeyboardButton(s["cancel"], callback_data="main_menu")],
    ]
    return msg, InlineKeyboardMarkup(keyboard)

def build_confirm_page(product_id, qty, user_id):
    info = PRODUCTS[product_id]
    lang = get_user_lang(user_id)
    s = STRINGS[lang]

    unit_price = get_product_unit_price(product_id, qty)
    total = unit_price * qty
    balance = get_user_balance(user_id)
    support_url = get_support_url()

    bulk_notice = ""
    if unit_price < info["price"]:
        bulk_notice = f" 🎉 <i>Bulk Discount Applied (${unit_price:.3f} each)!</i>\n"

    msg = (f"📦 <b>{info['name']}</b>\n\n"
           f"Quantity: <b>{qty}</b>\n"
           f"Price per item: <b>${unit_price:.3f}</b>\n"
           f"{bulk_notice}"
           f"Total Price: <b>${total:.2f}</b>\n"
           f"Your Balance: <b>${balance:.2f}</b>\n\n"
           f"Choose how you would like to pay:")

    keyboard = []
    if balance >= total:
        keyboard.append([InlineKeyboardButton(f"✅ Pay with Balance (${balance:.2f})", callback_data=f"confirm_{product_id}_{qty}")])

    keyboard.append([InlineKeyboardButton("💠 Direct Pay via Crypto (OxaPay)", callback_data=f"payprod_oxapay_{product_id}_{qty}")])
    keyboard.append([InlineKeyboardButton("🅱️ Direct Pay via Bybit UID", callback_data=f"payprod_bybit_{product_id}_{qty}")])
    keyboard.append([
        InlineKeyboardButton(s["add_funds"], callback_data="menu_addfunds"),
        InlineKeyboardButton(s["support"], url=support_url)
    ])
    keyboard.append([InlineKeyboardButton(s["cancel"], callback_data="main_menu")])

    return msg, InlineKeyboardMarkup(keyboard)

def build_payment_method_page(amount, lang="en"):
    support_url = get_support_url()
    s = STRINGS[lang]
    msg = f"Amount to Deposit: ${amount:.2f}\n\nHow would you like to pay?"
    keyboard = [
        [InlineKeyboardButton("💠 Pay with Crypto (OxaPay)", callback_data="paymethod_oxapay")],
        [InlineKeyboardButton("🅱️ Pay via Bybit UID", callback_data="paymethod_bybit")],
        [InlineKeyboardButton(s["support"], url=support_url)],
        [InlineKeyboardButton(s["cancel"], callback_data="main_menu")],
    ]
    return msg, InlineKeyboardMarkup(keyboard)

def build_oxapay_coin_menu(prefix, details_header):
    msg = (f"💳 <b>Choose Payment Coin & Network</b>\n\n"
           f"{details_header}\n\n"
           f"Select your preferred cryptocurrency below to generate your direct wallet address:")
    keyboard = [
        [InlineKeyboardButton("💚 USDT (TRC20 - Tron)", callback_data=f"{prefix}_USDT_trc20")],
        [InlineKeyboardButton("💛 USDT (BEP20 - BSC)", callback_data=f"{prefix}_USDT_bep20")],
        [InlineKeyboardButton("💜 USDT (Polygon)", callback_data=f"{prefix}_USDT_polygon")],
        [InlineKeyboardButton("💙 USDT (ERC20 - Ethereum)", callback_data=f"{prefix}_USDT_erc20")],
        [InlineKeyboardButton("⚡ LTC (Litecoin)", callback_data=f"{prefix}_LTC_none")],
        [InlineKeyboardButton("🔴 TRX (Tron)", callback_data=f"{prefix}_TRX_none")],
        [InlineKeyboardButton("🟠 BTC (Bitcoin)", callback_data=f"{prefix}_BTC_none")],
        [InlineKeyboardButton("◀ Cancel", callback_data="main_menu")],
    ]
    return msg, InlineKeyboardMarkup(keyboard)

async def fulfill_transaction(query_or_message, track_id, user_id, amount, product_id, qty, extra_credit=0.0, bot_context=None):
    info = PRODUCTS.get(product_id)
    lang = get_user_lang(user_id)
    s = STRINGS[lang]

    process_referral_reward(user_id, amount, bot_context)

    if product_id and qty > 0 and info:
        items = take_inventory_items(product_id, qty)
        if items is not None:
            record_completed_order(user_id, product_id, qty, amount, items)
            check_and_notify_low_stock(product_id, bot_context)

            delivery_text = "\n".join(items)
            msg = s["purchase_success"].format(qty=qty, name=info["name"], total=amount, balance=get_user_balance(user_id), delivery=delivery_text)
            if extra_credit and extra_credit > 0:
                update_user_balance(user_id, extra_credit)
                new_bal = get_user_balance(user_id)
                msg += f"\n\n💵 <b>${extra_credit:.2f}</b> extra credited to balance (New Balance: ${new_bal:.2f})."
            
            if hasattr(query_or_message, 'edit_message_text'):
                await query_or_message.edit_message_text(msg, parse_mode="HTML")
            else:
                await query_or_message.reply_text(msg, parse_mode="HTML")
            return

        # Out of stock fallback -> credit to balance
        update_user_balance(user_id, amount)
        new_bal = get_user_balance(user_id)
        msg = (f"✅ Payment of ${amount:.2f} received!\n\n"
               f"⚠️ {info['name']} went out of stock. ${amount:.2f} credited to your balance.\n"
               f"New Balance: ${new_bal:.2f}")
        if hasattr(query_or_message, 'edit_message_text'):
            await query_or_message.edit_message_text(msg)
        else:
            await query_or_message.reply_text(msg)
        return

    # Regular Deposit -> update user balance
    update_user_balance(user_id, amount)
    new_bal = get_user_balance(user_id)
    msg = f"✅ Payment successful! ${amount:.2f} added to your account.\nNew balance: ${new_bal:.2f}"
    if hasattr(query_or_message, 'edit_message_text'):
        await query_or_message.edit_message_text(msg)
    else:
        await query_or_message.reply_text(msg)

# --- HANDLE INLINE BUTTONS ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
        await button_handler_inner(update, context, query)
    except Exception as e:
        if "Message is not modified" in str(e):
            logging.info("Ignored 'Message is not modified' error.")
            return
        logging.error(f"Unhandled error in button_handler (data={query.data}): {e}")
        try:
            await query.message.reply_text(f"❌ Error: {str(e)}. Please tap /start and try again.")
        except Exception:
            pass

async def button_handler_inner(update: Update, context: ContextTypes.DEFAULT_TYPE, query) -> None:
    data = query.data
    user_id = query.from_user.id
    lang = get_user_lang(user_id)
    s = STRINGS[lang]

    if data == "check_joined":
        req_channel = get_required_channel()
        if req_channel:
            is_member = await check_channel_membership(context.bot, user_id)
            if not is_member:
                await query.answer("❌ You haven't joined the required channel yet!", show_alert=True)
                return
        await start(update, context)
        return

    if data == "main_menu":
        context.user_data['awaiting_quantity'] = False
        await start(update, context)

    elif data == "toggle_lang":
        new_lang = "en" if lang == "ar" else "ar"
        set_user_lang(user_id, new_lang)
        await start(update, context)

    elif data == "menu_myorders":
        orders = get_user_orders(user_id)
        if not orders:
            await query.edit_message_text(s["no_orders"], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(s["main_menu"], callback_data="main_menu")]]))
            return

        msg = s["my_orders_title"]
        for o_pid, o_qty, o_total, o_del, o_time in orders:
            p_name = PRODUCTS.get(o_pid, {}).get("name", o_pid)
            msg += f"📦 <b>{o_qty}x {p_name}</b> — ${o_total:.2f}\n📅 {o_time}\n<code>{o_del[:100]}...</code>\n───────────────\n"

        keyboard = [[InlineKeyboardButton(s["main_menu"], callback_data="main_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "menu_referral":
        bot_obj = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_obj.username}?start=ref_{user_id}"
        inv_count, ref_earn = get_referral_stats(user_id)
        msg = s["ref_msg"].format(ref_link=ref_link, invited_count=inv_count, ref_earnings=ref_earn)
        keyboard = [[InlineKeyboardButton(s["main_menu"], callback_data="main_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("prod_"):
        product_id = data.split("_", 1)[1]
        if product_id not in PRODUCTS:
            await query.answer("❌ Product not found.", show_alert=True)
            return
        stock = get_product_stock(product_id)
        if stock <= 0:
            await query.answer(s["out_of_stock"], show_alert=True)
            return
        context.user_data['cur_product'] = product_id
        context.user_data['awaiting_quantity'] = True
        msg, markup = build_product_intro(product_id, lang)
        await query.edit_message_text(msg, reply_markup=markup)

    elif data.startswith("confirm_"):
        remainder = data[len("confirm_"):]
        if "_" in remainder:
            product_id, qty_str = remainder.rsplit("_", 1)
            qty = int(qty_str)
        else:
            product_id = remainder
            qty = context.user_data.get('cur_qty', 1)

        info = PRODUCTS.get(product_id)
        if not info:
            await query.answer("❌ Product not found.", show_alert=True)
            return

        unit_price = get_product_unit_price(product_id, qty)
        total_price = unit_price * qty
        balance = get_user_balance(user_id)

        if balance < total_price:
            support_url = get_support_url()
            keyboard = [
                [InlineKeyboardButton("💠 Pay directly via OxaPay", callback_data=f"payprod_oxapay_{product_id}_{qty}")],
                [InlineKeyboardButton("🅱️ Pay directly via Bybit UID", callback_data=f"payprod_bybit_{product_id}_{qty}")],
                [InlineKeyboardButton(s["add_funds"], callback_data="menu_addfunds"), InlineKeyboardButton(s["support"], url=support_url)],
                [InlineKeyboardButton(s["main_menu"], callback_data="main_menu")],
            ]
            await query.edit_message_text(
                s["insufficient_balance"].format(balance=balance, total=total_price),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
            return

        items = take_inventory_items(product_id, qty)
        if items is not None:
            update_user_balance(user_id, -total_price)
            record_completed_order(user_id, product_id, qty, total_price, items)
            process_referral_reward(user_id, total_price, context)
            check_and_notify_low_stock(product_id, context)

            new_balance = get_user_balance(user_id)
            delivery_text = "\n".join(items)
            msg = s["purchase_success"].format(qty=qty, name=info["name"], total=total_price, balance=new_balance, delivery=delivery_text)
            await query.edit_message_text(msg, parse_mode="HTML")
            context.user_data.pop('cur_product', None)
            context.user_data.pop('cur_qty', None)
        else:
            await query.answer(s["out_of_stock"], show_alert=True)

    # --- Direct Product OxaPay Pay ---
    elif data.startswith("payprod_oxapay_"):
        remainder = data[len("payprod_oxapay_"):]
        product_id, qty_str = remainder.rsplit("_", 1)
        qty = int(qty_str)
        info = PRODUCTS.get(product_id)
        if not info:
            await query.answer("❌ Product not found.", show_alert=True)
            return

        merchant_key = get_oxapay_merchant_key()
        if not merchant_key or merchant_key == "YOUR_OXAPAY_MERCHANT_KEY":
            await query.edit_message_text(
                "⚠️ OxaPay payment gateway is not configured yet.\n\n"
                "Admin: Please set your merchant key using `/setoxapay YOUR_KEY`"
            )
            return

        unit_price = get_product_unit_price(product_id, qty)
        total_price = unit_price * qty
        msg, markup = build_oxapay_coin_menu(f"payprodcoin_{product_id}_{qty}", f"Order: <b>{qty}x {info['name']}</b> — Price: <b>${total_price:.2f} USD</b>")
        await query.edit_message_text(msg, reply_markup=markup, parse_mode="HTML")

    # --- Direct Product OxaPay Whitelabel Address Generation ---
    elif data.startswith("payprodcoin_"):
        remainder = data[len("payprodcoin_"):]
        parts = remainder.rsplit("_", 3)
        product_id = parts[0]
        qty = int(parts[1])
        pay_currency = parts[2]
        network = parts[3] if len(parts) > 3 else "none"

        info = PRODUCTS.get(product_id)
        if not info:
            await query.answer("❌ Product not found.", show_alert=True)
            return

        merchant_key = get_oxapay_merchant_key()
        unit_price = get_product_unit_price(product_id, qty)
        total_price = unit_price * qty
        
        # 1.4% percentage fee + unique 6-digit decimal tracking fraction
        track_id = int(uuid.uuid4().int % 10_000_000_000)
        unique_suffix = (track_id % 9999) / 1000000.0
        fee = total_price * 0.014
        raw_invoice_amount = total_price + fee + unique_suffix
        
        if raw_invoice_amount < OXAPAY_MIN_INVOICE:
            invoice_amount = OXAPAY_MIN_INVOICE
            extra_credit = round(OXAPAY_MIN_INVOICE - total_price, 6)
        else:
            invoice_amount = round(raw_invoice_amount, 6)
            extra_credit = 0.0

        order_id = str(uuid.uuid4())
        payload = {
            "merchant": merchant_key,
            "amount": invoice_amount,
            "currency": "USD",
            "payCurrency": pay_currency,
            "orderId": order_id,
            "description": f"Direct order {qty}x {info['name']} for User {user_id}"
        }
        if network and network != "none":
            payload["network"] = network

        ok, status_code, res_data = oxapay_post_request("/merchants/request/whitelabel", payload)

        if ok and isinstance(res_data, dict) and res_data.get("result") == 100:
            address = res_data.get("address")
            pay_amount = res_data.get("payAmount")
            track_id = res_data.get("trackId")

            create_transaction(track_id, user_id, total_price, "pending", "oxapay", product_id=product_id, qty=qty, extra_credit=extra_credit)

            net_display = network.upper() if network != "none" else pay_currency
            msg = (f"💳 <b>Direct Whitelabel Invoice for {qty}x {info['name']}</b>\n\n"
                   f"Amount to Send: <code>{pay_amount}</code> {pay_currency}\n"
                   f"Network: <b>{net_display}</b>\n\n"
                   f"📬 <b>Payment Address (Tap to copy):</b>\n"
                   f"<code>{address}</code>\n\n")

            if extra_credit > 0:
                msg += f"💡 <i>Note: OxaPay minimum payment is $0.50. The extra <b>${extra_credit:.2f}</b> will be credited to your balance automatically!</i>\n\n"

            msg += f"⚠️ Send EXACTLY <code>{pay_amount}</code> {pay_currency} to the address above.\nOnce sent, tap the button below:"
            
            support_url = get_support_url()
            keyboard = [
                [InlineKeyboardButton("Check Payment Status", callback_data=f"checkpay_{track_id}")],
                [InlineKeyboardButton(s["support"], url=support_url)],
                [InlineKeyboardButton(s["main_menu"], callback_data="main_menu")]
            ]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        else:
            err_msg = res_data.get("message") if isinstance(res_data, dict) else str(res_data)
            await query.edit_message_text(f"❌ Whitelabel Invoice Error ({status_code}): {err_msg}")

    # --- Direct Product Bybit Pay ---
    elif data.startswith("payprod_bybit_"):
        remainder = data[len("payprod_bybit_"):]
        product_id, qty_str = remainder.rsplit("_", 1)
        qty = int(qty_str)
        info = PRODUCTS.get(product_id)
        if not info:
            await query.answer("❌ Product not found.", show_alert=True)
            return

        bybit_uid = get_bybit_uid()
        unit_price = get_product_unit_price(product_id, qty)
        total_price = unit_price * qty
        track_id = int(uuid.uuid4().int % 10_000_000_000)
        unique_suffix = (track_id % 9999) / 1000000.0
        unique_amount = round(total_price + unique_suffix, 6)

        create_transaction(track_id, user_id, total_price, "pending", "bybit", product_id=product_id, qty=qty)
        context.user_data['bybit_unique_amount'] = unique_amount

        safe_uid = html_lib.escape(str(bybit_uid))
        support_url = get_support_url()
        msg = (f"📬 Direct Payment for <b>{qty}x {info['name']}</b>:\n\n"
               f"Send EXACTLY this amount via Bybit 'Send to UID':\n"
               f"<code>{unique_amount}</code> USDT\n\n"
               f"To Bybit UID:\n<code>{safe_uid}</code>\n\n"
               f"Once sent, tap the button below to receive your product immediately.")
        keyboard = [
            [InlineKeyboardButton("✅ I've Sent It — Check Now", callback_data=f"checkbybit_{track_id}")],
            [InlineKeyboardButton(s["support"], url=support_url)],
            [InlineKeyboardButton(s["main_menu"], callback_data="main_menu")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "menu_addfunds":
        context.user_data['awaiting_amount'] = True
        keyboard = [
            [InlineKeyboardButton(s["cancel"], callback_data="cancel_addfunds")]
        ]
        await query.edit_message_text("Please type and send the amount you want to add (e.g. 5 or 2.50):", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "cancel_addfunds":
        context.user_data['awaiting_amount'] = False
        await start(update, context)

    # --- OxaPay Add Funds Coin Selection ---
    elif data == "paymethod_oxapay":
        amount = context.user_data.get('deposit_amount')
        if not amount:
            await query.edit_message_text("❌ Session expired. Please try again.")
            return

        merchant_key = get_oxapay_merchant_key()
        if not merchant_key or merchant_key == "YOUR_OXAPAY_MERCHANT_KEY":
            await query.edit_message_text(
                "⚠️ OxaPay payment gateway is not configured yet.\n\n"
                "Admin: Please set your merchant key using `/setoxapay YOUR_KEY`"
            )
            return

        msg, markup = build_oxapay_coin_menu("paycoin", f"Amount to Deposit: <b>${amount:.2f} USD</b>")
        await query.edit_message_text(msg, reply_markup=markup, parse_mode="HTML")

    # --- OxaPay Whitelabel Add Funds Address Generation ---
    elif data.startswith("paycoin_"):
        parts = data.split("_", 2)
        pay_currency = parts[1]
        network = parts[2] if len(parts) > 2 else "none"
        amount = context.user_data.get('deposit_amount')

        if not amount:
            await query.edit_message_text("❌ Session expired. Please try again.")
            return

        merchant_key = get_oxapay_merchant_key()
        
        # 1.4% percentage fee + unique 6-digit decimal tracking fraction
        track_id = int(uuid.uuid4().int % 10_000_000_000)
        unique_suffix = (track_id % 9999) / 1000000.0
        fee = amount * 0.014
        raw_invoice_amount = amount + fee + unique_suffix

        if raw_invoice_amount < OXAPAY_MIN_INVOICE:
            invoice_amount = OXAPAY_MIN_INVOICE
            extra_credit = round(OXAPAY_MIN_INVOICE - amount, 6)
        else:
            invoice_amount = round(raw_invoice_amount, 6)
            extra_credit = 0.0

        order_id = str(uuid.uuid4())

        payload = {
            "merchant": merchant_key,
            "amount": invoice_amount,
            "currency": "USD",
            "payCurrency": pay_currency,
            "orderId": order_id,
            "description": f"Add funds for User {user_id}"
        }
        if network and network != "none":
            payload["network"] = network

        ok, status_code, res_data = oxapay_post_request("/merchants/request/whitelabel", payload)

        if ok and isinstance(res_data, dict) and res_data.get("result") == 100:
            address = res_data.get("address")
            pay_amount = res_data.get("payAmount")
            track_id = res_data.get("trackId")

            create_transaction(track_id, user_id, amount, "pending", "oxapay", extra_credit=extra_credit)

            net_display = network.upper() if network != "none" else pay_currency
            support_url = get_support_url()
            msg = (f"💳 <b>OxaPay Whitelabel Deposit Invoice</b>\n\n"
                   f"Amount to Send: <code>{pay_amount}</code> {pay_currency}\n"
                   f"Network: <b>{net_display}</b>\n\n"
                   f"📬 <b>Deposit Address (Tap to copy):</b>\n"
                   f"<code>{address}</code>\n\n"
                   f"⚠️ Send EXACTLY <code>{pay_amount}</code> {pay_currency} to the address above.\nOnce sent, click the button below to check status.")
            keyboard = [
                [InlineKeyboardButton("Check Payment Status", callback_data=f"checkpay_{track_id}")],
                [InlineKeyboardButton(s["support"], url=support_url)],
                [InlineKeyboardButton(s["main_menu"], callback_data="main_menu")]
            ]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        else:
            err_msg = res_data.get("message") if isinstance(res_data, dict) else str(res_data)
            await query.edit_message_text(f"❌ Whitelabel Invoice Error ({status_code}): {err_msg}")

    elif data.startswith("checkpay_"):
        track_id = data.split("_")[1]

        merchant_key = get_oxapay_merchant_key()
        payload = {
            "merchant": merchant_key,
            "trackId": int(track_id)
        }
        ok, status_code, res_data = oxapay_post_request("/merchants/inquiry", payload)

        if ok and isinstance(res_data, dict):
            status = str(res_data.get("status", "")).lower()
            txn = get_transaction(track_id, user_id)
            if txn:
                db_status, amount, method, product_id, qty, extra_credit = txn
                if db_status == "completed":
                    await query.edit_message_text(f"✅ This payment of ${amount:.2f} has already been completed and processed.")
                elif status in ("paid", "completed", "success", "paid_over", "underpaid"):
                    mark_transaction_completed(track_id)
                    await fulfill_transaction(query, track_id, user_id, amount, product_id, qty, extra_credit=extra_credit, bot_context=context)
                elif status == "expired":
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute('UPDATE transactions SET status = ? WHERE track_id = ?', ("expired", track_id))
                    conn.commit()
                    conn.close()
                    await query.edit_message_text("❌ This payment link has expired. Please request a new one.")
                else:
                    support_url = get_support_url()
                    keyboard = [
                        [InlineKeyboardButton("Check Payment Status", callback_data=f"checkpay_{track_id}")],
                        [InlineKeyboardButton(s["support"], url=support_url)],
                        [InlineKeyboardButton(s["main_menu"], callback_data="main_menu")]
                    ]
                    status_display = res_data.get("status", "Pending")
                    msg_text = f"⏳ Payment is still pending (Status: {status_display}).\n\nIf you have already sent the funds, please wait a few seconds for blockchain confirmation and tap Check again."
                    try:
                        await query.edit_message_text(msg_text, reply_markup=InlineKeyboardMarkup(keyboard))
                    except Exception as e:
                        if "Message is not modified" in str(e):
                            await query.answer(f"⏳ Status: {status_display}. Please wait a few seconds...", show_alert=True)
                        else:
                            raise e
            else:
                await query.edit_message_text("❌ Transaction not found.")
        else:
            err_msg = res_data if isinstance(res_data, str) else str(res_data.get("message", "Unknown error"))
            await query.answer(f"❌ OxaPay Check Error ({status_code}): {err_msg}", show_alert=True)

    # --- Bybit UID flow ---
    elif data == "paymethod_bybit":
        amount = context.user_data.get('deposit_amount')
        if not amount:
            await query.edit_message_text("❌ Session expired. Please try again.")
            return

        bybit_uid = get_bybit_uid()
        track_id = int(uuid.uuid4().int % 10_000_000_000)
        unique_suffix = (track_id % 9999) / 1000000.0
        unique_amount = round(amount + unique_suffix, 6)

        create_transaction(track_id, user_id, amount, "pending", "bybit")
        context.user_data['bybit_unique_amount'] = unique_amount

        safe_uid = html_lib.escape(str(bybit_uid))
        support_url = get_support_url()
        msg = (f"📬 Send EXACTLY this amount via Bybit 'Send to UID':\n\n"
               f"<code>{unique_amount}</code> USDT\n\n"
               f"To this Bybit UID:\n<code>{safe_uid}</code>\n\n"
               f"Once sent, tap the button below.")
        keyboard = [
            [InlineKeyboardButton("✅ I've Sent It — Check Now", callback_data=f"checkbybit_{track_id}")],
            [InlineKeyboardButton(s["support"], url=support_url)],
            [InlineKeyboardButton(s["main_menu"], callback_data="main_menu")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("checkbybit_"):
        track_id = data.split("_", 1)[1]
        txn = get_transaction(track_id, user_id)

        if not txn:
            await query.answer("❌ Transaction not found.", show_alert=True)
            return

        db_status, amount, method, product_id, qty, extra_credit = txn
        if db_status == "completed":
            await query.edit_message_text(f"✅ This payment of ${amount:.2f} has already been completed.")
            return

        unique_amount = context.user_data.get('bybit_unique_amount')
        if not unique_amount:
            await query.answer("❌ Session expired. Please start a new Bybit deposit.", show_alert=True)
            return

        if not get_bybit_api_key() or not get_bybit_api_secret():
            await query.answer("❌ Bybit API verification isn't configured yet by Admin.", show_alert=True)
            return

        found = find_matching_bybit_deposit(unique_amount)
        if found:
            mark_transaction_completed(track_id)
            await fulfill_transaction(query, track_id, user_id, amount, product_id, qty, extra_credit=extra_credit, bot_context=context)
        else:
            support_url = get_support_url()
            keyboard = [
                [InlineKeyboardButton("✅ I've Sent It — Check Now", callback_data=f"checkbybit_{track_id}")],
                [InlineKeyboardButton(s["support"], url=support_url)],
                [InlineKeyboardButton(s["main_menu"], callback_data="main_menu")]
            ]
            await query.edit_message_text(
                f"⏳ We haven't seen that deposit yet. Double check the amount was exact ({unique_amount} USDT) and try again in a minute.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    s = STRINGS[lang]

    if context.user_data.get('awaiting_quantity'):
        product_id = context.user_data.get('cur_product')
        info = PRODUCTS.get(product_id)
        if not info:
            context.user_data['awaiting_quantity'] = False
            await update.message.reply_text("❌ Session expired. Please tap /start and pick the product again.")
            return

        text = update.message.text.strip()
        try:
            qty = int(text)
            if qty <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Please type a valid whole number greater than 0.")
            return

        stock = get_product_stock(product_id)
        if qty > stock:
            await update.message.reply_text(f"❌ Only {stock} left in stock. Please type a smaller number.")
            return

        context.user_data['awaiting_quantity'] = False
        context.user_data['cur_qty'] = qty
        msg, markup = build_confirm_page(product_id, qty, update.effective_user.id)
        await update.message.reply_text(msg, reply_markup=markup, parse_mode="HTML")
        return

    if context.user_data.get('awaiting_amount'):
        text = update.message.text
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Invalid amount. Please enter a valid number greater than 0.")
            return

        context.user_data['awaiting_amount'] = False
        context.user_data['deposit_amount'] = amount

        msg, markup = build_payment_method_page(amount, lang)
        await update.message.reply_text(msg, reply_markup=markup)
        return

# --- ADMIN COMMANDS ---
async def setchannel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: `/setchannel @yourchannel` or `/setchannel off` to disable mandatory channel join.", parse_mode="HTML")
        return

    arg = context.args[0].strip()
    if arg.lower() in ("off", "disable", "none"):
        set_setting("REQUIRED_CHANNEL", "")
        await update.message.reply_text("✅ Mandatory channel join requirement disabled.")
    else:
        channel = arg if arg.startswith("@") else f"@{arg}"
        set_setting("REQUIRED_CHANNEL", channel)
        await update.message.reply_text(f"✅ Mandatory updates channel set to <b>{channel}</b>!", parse_mode="HTML")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return

    text = None
    if update.message.reply_to_message:
        text = update.message.reply_to_message.text or update.message.reply_to_message.caption
    elif context.args:
        text = " ".join(context.args)

    if not text:
        await update.message.reply_text("❌ Usage:\n• `/broadcast <your message>`\n• Or reply `/broadcast` to any message/photo to broadcast it.")
        return

    users = get_all_users_list(limit=10000)
    success = 0
    failed = 0

    await update.message.reply_text(f"🚀 Starting broadcast to {len(users)} users...")

    for u_id, _ in users:
        try:
            if update.message.reply_to_message:
                await update.message.reply_to_message.copy(chat_id=u_id)
            else:
                await context.bot.send_message(chat_id=u_id, text=text, parse_mode="HTML")
            success += 1
            time.sleep(0.04)  # Anti-flood rate limit
        except Exception:
            failed += 1

    await update.message.reply_text(f"✅ Broadcast finished!\n\n• Successfully Sent: <b>{success}</b>\n• Failed: <b>{failed}</b>", parse_mode="HTML")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*), SUM(total_price) FROM orders')
    order_row = cursor.fetchone()
    total_orders = order_row[0] if order_row else 0
    total_revenue = order_row[1] if order_row and order_row[1] else 0.0

    cursor.execute('SELECT COUNT(*), SUM(total_price) FROM orders WHERE DATE(timestamp) = DATE("now")')
    today_row = cursor.fetchone()
    today_orders = today_row[0] if today_row else 0
    today_revenue = today_row[1] if today_row and today_row[1] else 0.0

    conn.close()

    stock_msg = ""
    for pid, pinfo in PRODUCTS.items():
        stk = get_product_stock(pid)
        stock_msg += f"• {pinfo['name']}: <b>{stk}</b> in stock\n"

    msg = (f"📊 <b>Store Analytics & Revenue Stats</b>\n\n"
           f"👥 Total Registered Users: <b>{total_users}</b>\n"
           f"📦 Total Orders Completed: <b>{total_orders}</b>\n"
           f"💰 Total Revenue (All Time): <b>${total_revenue:.2f}</b>\n"
           f"💵 Today's Revenue: <b>${today_revenue:.2f}</b> ({today_orders} orders)\n\n"
           f"<b>Current Stock Levels:</b>\n{stock_msg}")
    await update.message.reply_text(msg, parse_mode="HTML")

async def addcoupon_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if len(context.args) < 3:
        await update.message.reply_text("❌ Usage: `/addcoupon <code> <discount%_or_USD> <uses_count>`\nExample: `/addcoupon SAVE10 10% 50` or `/addcoupon FREE1 1.0USD 20`", parse_mode="HTML")
        return

    code = context.args[0].strip()
    val_str = context.args[1].strip()
    uses = int(context.args[2])

    if val_str.endswith("%"):
        dtype = "percent"
        dval = float(val_str.rstrip("%"))
    else:
        dtype = "usd"
        dval = float(val_str.replace("USD", "").replace("$", ""))

    add_coupon(code, dtype, dval, uses)
    await update.message.reply_text(f"✅ Coupon <code>{code.upper()}</code> created ({dval}{'%' if dtype=='percent' else '$'}, {uses} uses)!", parse_mode="HTML")

async def listcoupons_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    coupons = list_coupons()
    if not coupons:
        await update.message.reply_text("ℹ️ No active coupons found.")
        return

    msg = "🎟️ <b>Active Promo Coupons:</b>\n\n"
    for code, dtype, dval, uses in coupons:
        unit = "%" if dtype == "percent" else "$"
        msg += f"• <code>{code}</code>: <b>{dval}{unit}</b> off ({uses} uses left)\n"

    await update.message.reply_text(msg, parse_mode="HTML")

async def delcoupon_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: `/delcoupon <code>`", parse_mode="HTML")
        return
    code = context.args[0].strip()
    cnt = delete_coupon(code)
    if cnt > 0:
        await update.message.reply_text(f"✅ Coupon <code>{code.upper()}</code> deleted.", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ Coupon <code>{code.upper()}</code> not found.", parse_mode="HTML")

async def addstock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return

    lines = update.message.text.split("\n")
    first_line_parts = lines[0].strip().split()

    if len(first_line_parts) < 2:
        await update.message.reply_text(
            "❌ Usage:\n"
            "/addstock <product_id>\n\n"
            "Then either:\n"
            "• Type the codes as extra lines in the same message, one per line, e.g.:\n"
            "/addstock hotmail\n"
            "mail1@hotmail.com|pass123|token1\n"
            "mail2@hotmail.com|pass456|token2\n\n"
            "• OR send /addstock <product_id> alone, then upload a .txt file as your next message."
        )
        return

    product_id = first_line_parts[1]
    if product_id not in PRODUCTS:
        await update.message.reply_text(f"❌ Unknown product id '{product_id}'. Available: {', '.join(PRODUCTS.keys())}")
        return

    codes = [line.strip() for line in lines[1:] if line.strip()]

    if not codes:
        context.user_data['awaiting_stock_file'] = product_id
        await update.message.reply_text(
            f"📎 Okay, now send me a .txt file for '{product_id}' — one code/account per line."
        )
        return

    add_inventory_items(product_id, codes)
    new_stock = get_product_stock(product_id)
    await update.message.reply_text(f"✅ Added {len(codes)} items to '{product_id}'. Total stock is now {new_stock}.")

async def clearstock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text(
            "❌ Usage:\n"
            "• <code>/clearstock &lt;product_id&gt;</code> (e.g. <code>/clearstock hotmail</code> or <code>/clearstock office365</code>)\n"
            "• <code>/clearstock all</code> (clears ALL products inventory)",
            parse_mode="HTML"
        )
        return

    target = context.args[0].strip().lower()
    if target != "all" and target not in PRODUCTS:
        await update.message.reply_text(f"❌ Unknown product id '{target}'. Available: {', '.join(PRODUCTS.keys())} or 'all'")
        return

    count = clear_inventory_items(target)
    if target == "all":
        await update.message.reply_text(f"🧹 Cleared all stock! Deleted {count} items from inventory.")
    else:
        new_stock = get_product_stock(target)
        await update.message.reply_text(f"🧹 Cleared stock for '{target}'! Deleted {count} items. Stock is now {new_stock}.")

async def user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: <code>/user &lt;user_id&gt;</code> (e.g. <code>/user 1477846847</code>)", parse_mode="HTML")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid Telegram User ID.")
        return

    info = get_user_info(target_id)
    if not info:
        await update.message.reply_text(f"❌ User <code>{target_id}</code> not found in database.", parse_mode="HTML")
        return

    msg = (f"👤 <b>User Profile & Account Info</b>\n\n"
           f"• User ID: <code>{info['user_id']}</code>\n"
           f"• Balance: <b>${info['balance']:.2f}</b>\n"
           f"• Total Orders/Completed TXs: <b>{info['tx_count']}</b>\n"
           f"• Total Spent/Deposited: <b>${info['total_spent']:.2f}</b>\n\n"
           f"<b>Quick Actions:</b>\n"
           f"• Credit Balance: <code>/credituser {info['user_id']} &lt;amount&gt;</code>\n"
           f"• Set Exact Balance: <code>/setbalance {info['user_id']} &lt;new_balance&gt;</code>")
    
    if info['recent_txs']:
        msg += "\n\n<b>Recent Transactions:</b>\n"
        for tx in info['recent_txs']:
            msg += f"• Track #{tx[0]} | ${tx[1]:.2f} | {str(tx[2]).upper()} | {tx[3]}\n"

    await update.message.reply_text(msg, parse_mode="HTML")

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return

    users = get_all_users_list()
    if not users:
        await update.message.reply_text("ℹ️ No registered users found yet.")
        return

    msg = f"👥 <b>Registered Users ({len(users)} shown):</b>\n\n"
    for u_id, bal in users:
        msg += f"• User ID: <code>{u_id}</code> | Balance: <b>${bal:.2f}</b> (<code>/user {u_id}</code>)\n"

    await update.message.reply_text(msg, parse_mode="HTML")

async def setbalance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Usage: <code>/setbalance &lt;user_id&gt; &lt;new_balance&gt;</code>", parse_mode="HTML")
        return
    try:
        target_user = int(context.args[0])
        new_balance = float(context.args[1])
        if new_balance < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Invalid user_id or balance value.")
        return

    set_user_balance_exact(target_user, new_balance)
    await update.message.reply_text(f"✅ Set balance for user <code>{target_user}</code> to <b>${new_balance:.2f}</b>.", parse_mode="HTML")

    try:
        await context.bot.send_message(
            chat_id=target_user,
            text=f"ℹ️ Your account balance has been updated by Admin.\nNew Balance: <b>${new_balance:.2f}</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.warning(f"Could not notify user {target_user}: {e}")

async def setsupport(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: <code>/setsupport &lt;username&gt;</code> (e.g. <code>/setsupport @mongyni</code>)", parse_mode="HTML")
        return
    username = context.args[0].strip().lstrip("@")
    set_setting("SUPPORT_USERNAME", username)
    await update.message.reply_text(f"✅ Support handle updated to <b>@{username}</b> (https://t.me/{username})!", parse_mode="HTML")

async def setoxapay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /setoxapay <your_merchant_key>")
        return
    key = context.args[0].strip()
    set_setting("OXAPAY_MERCHANT_KEY", key)
    await update.message.reply_text(f"✅ OxaPay Merchant Key updated successfully!")

async def setbybit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("❌ Usage: /setbybit <your_bybit_uid>")
        return
    uid = context.args[0].strip()
    set_setting("BYBIT_UID", uid)
    await update.message.reply_text(f"✅ Bybit UID updated to '{uid}' successfully!")

async def setbybitkeys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Usage: /setbybitkeys <api_key> <api_secret>")
        return
    api_key = context.args[0].strip()
    api_secret = context.args[1].strip()
    set_setting("BYBIT_API_KEY", api_key)
    set_setting("BYBIT_API_SECRET", api_secret)
    await update.message.reply_text("✅ Bybit API Keys updated successfully!")

async def credituser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Usage: /credituser <user_id> <amount>")
        return
    try:
        target_user = int(context.args[0])
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid user_id or amount format.")
        return

    update_user_balance(target_user, amount)
    new_bal = get_user_balance(target_user)
    await update.message.reply_text(f"✅ Credited ${amount:.2f} to user {target_user}. New balance: ${new_bal:.2f}")

    try:
        await context.bot.send_message(
            chat_id=target_user,
            text=f"🎉 Admin credited <b>${amount:.2f}</b> to your balance!\nNew Balance: <b>${new_bal:.2f}</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.warning(f"Could not notify user {target_user}: {e}")

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return
    ox_key = get_oxapay_merchant_key()
    by_uid = get_bybit_uid()
    by_key = get_bybit_api_key()
    sup_user = get_support_username()
    req_ch = get_required_channel() or "Disabled"

    ox_status = "✅ Set" if ox_key and ox_key != "YOUR_OXAPAY_MERCHANT_KEY" else "❌ Not Configured"
    by_uid_status = f"✅ Set ({by_uid})" if by_uid and by_uid != "YOUR_BYBIT_UID_HERE" else "❌ Not Configured"
    by_api_status = "✅ Set" if by_key else "❌ Not Configured"

    msg = (f"⚙️ <b>Bot Settings & Control Panel</b>\n\n"
           f"Support Handle: <b>@{sup_user}</b>\n"
           f"Mandatory Channel: <b>{req_ch}</b>\n"
           f"OxaPay Merchant Key: {ox_status}\n"
           f"Bybit UID: {by_uid_status}\n"
           f"Bybit API Key: {by_api_status}\n\n"
           f"<b>📢 Marketing & Channel:</b>\n"
           f"• <code>/setchannel &lt;@channel|off&gt;</code> - Set mandatory channel\n"
           f"• <code>/broadcast &lt;msg&gt;</code> - Send message to all users\n"
           f"• <code>/stats</code> - View sales & revenue stats\n"
           f"• <code>/addcoupon &lt;code&gt; &lt;10%|1$&gt; &lt;uses&gt;</code> - Add coupon\n"
           f"• <code>/coupons</code> - List coupons\n"
           f"• <code>/delcoupon &lt;code&gt;</code> - Delete coupon\n\n"
           f"<b>📦 Inventory Control:</b>\n"
           f"• <code>/clearstock &lt;product_id|all&gt;</code> - Clear stock\n"
           f"• <code>/addstock &lt;product_id&gt;</code> - Add stock\n\n"
           f"<b>👥 User Management:</b>\n"
           f"• <code>/users</code> - List users & balances\n"
           f"• <code>/user &lt;user_id&gt;</code> - View profile & history\n"
           f"• <code>/credituser &lt;user_id&gt; &lt;amount&gt;</code> - Credit balance\n"
           f"• <code>/setbalance &lt;user_id&gt; &lt;amount&gt;</code> - Set exact balance\n\n"
           f"<b>⚙️ Config Commands:</b>\n"
           f"• <code>/setsupport &lt;username&gt;</code>\n"
           f"• <code>/setoxapay &lt;key&gt;</code>\n"
           f"• <code>/setbybit &lt;uid&gt;</code>\n"
           f"• <code>/setbybitkeys &lt;key&gt; &lt;secret&gt;</code>")
    await update.message.reply_text(msg, parse_mode="HTML")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return

    product_id = context.user_data.get('awaiting_stock_file')
    if not product_id:
        await update.message.reply_text("❌ Send /addstock <product_id> first, then upload the file.")
        return

    document = update.message.document
    try:
        file = await document.get_file()
        file_bytes = await file.download_as_bytearray()
        text = file_bytes.decode('utf-8')
    except Exception as e:
        logging.error(f"File download/decode error: {e}")
        await update.message.reply_text("❌ Couldn't read that file. Please make sure it's a plain .txt file and try again.")
        return

    codes = [line.strip() for line in text.split("\n") if line.strip()]
    if not codes:
        await update.message.reply_text("❌ The file looks empty. Please put one code/account per line.")
        return

    add_inventory_items(product_id, codes)
    new_stock = get_product_stock(product_id)
    context.user_data['awaiting_stock_file'] = None
    await update.message.reply_text(f"✅ Added {len(codes)} items to '{product_id}' from the file. Total stock is now {new_stock}.")

async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_message.web_app_data:
        return
    data_str = update.effective_message.web_app_data.data
    try:
        data = json.loads(data_str)
    except Exception as e:
        logging.error(f"Error parsing web app data: {e}")
        return

    action = data.get("action")
    if action == "add_funds":
        context.user_data['awaiting_amount'] = True
        keyboard = [
            [InlineKeyboardButton("◀ Cancel", callback_data="cancel_addfunds")]
        ]
        await update.effective_message.reply_text(
            "Please type and send the amount you want to add (e.g. 5 or 2.50):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif action == "buy_product":
        product_id = data.get("product_id")
        if product_id in PRODUCTS:
            stock = get_product_stock(product_id)
            if stock <= 0:
                await update.effective_message.reply_text("❌ Sorry, this product is currently out of stock.")
                return
            context.user_data['cur_product'] = product_id
            context.user_data['awaiting_quantity'] = True
            msg, markup = build_product_intro(product_id)
            await update.effective_message.reply_text(msg, reply_markup=markup)

async def post_init(application: Application) -> None:
    bot = application.bot
    short_desc = "Welcome to Mongyni Store! Premium Digital Products & Services 24/7."
    full_desc = ("Welcome to Mongyni Store!\n\n"
                 "📦 High Quality Digital Accounts & Products\n"
                 "⚡ 24/7 Instant Automated Delivery\n"
                 "💳 Crypto & Bybit Automated Payments\n\n"
                 "Click START below to browse our live product catalog!")
    try:
        await bot.set_my_short_description(short_desc)
        await bot.set_my_description(full_desc)
        logging.info("Bot welcome banner & short description updated successfully!")
    except Exception as e:
        logging.warning(f"Could not set bot descriptions: {e}")

# --- MAIN RUNNER ---
def main() -> None:
    init_db()
    token = get_bot_token()
    application = Application.builder().token(token).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addstock", addstock))
    application.add_handler(CommandHandler("clearstock", clearstock))
    application.add_handler(CommandHandler("setchannel", setchannel))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("addcoupon", addcoupon_cmd))
    application.add_handler(CommandHandler("coupons", listcoupons_cmd))
    application.add_handler(CommandHandler("delcoupon", delcoupon_cmd))
    application.add_handler(CommandHandler("user", user_command))
    application.add_handler(CommandHandler("users", users_command))
    application.add_handler(CommandHandler("setbalance", setbalance))
    application.add_handler(CommandHandler("setsupport", setsupport))
    application.add_handler(CommandHandler("setoxapay", setoxapay))
    application.add_handler(CommandHandler("setbybit", setbybit))
    application.add_handler(CommandHandler("setbybitkeys", setbybitkeys))
    application.add_handler(CommandHandler("credituser", credituser))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Mongyni Bot is running with auto-language detection, bulk discounts & mandatory channel join...")
    application.run_polling()

if __name__ == "__main__":
    main()
