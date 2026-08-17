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

# --- PRODUCTS ---
PRODUCTS = {
    "office365": {
        "name": "Office 365 1TB",
        "description": "1TB OneDrive storage + full Office apps, 1 year subscription.",
        "price": 1.30,
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
    },
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

# --- DATABASE SETUP & DYNAMIC SETTINGS ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, product_id TEXT, data TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (track_id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, status TEXT, method TEXT, product_id TEXT, qty INTEGER, extra_credit REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')

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

def get_user_balance(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result is None:
        cursor.execute('INSERT INTO users (user_id, balance) VALUES (?, ?)', (user_id, 0.0))
        conn.commit()
        balance = 0.0
    else:
        balance = result[0]
    conn.close()
    return balance

def update_user_balance(user_id, amount_change):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount_change, user_id))
    conn.commit()
    conn.close()

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

# --- BOT COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    balance = get_user_balance(user_id)

    keyboard = []
    for product_id, info in PRODUCTS.items():
        stock = get_product_stock(product_id)
        icon = "🔴" if stock == 0 else ("🔴" if stock < 10 else ("🟠" if stock <= 50 else "🟢"))
        btn_text = f"{icon} {info['name']} - ${info['price']:.2f} (Stock: {stock})"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"prod_{product_id}")])

    keyboard.append([InlineKeyboardButton("💳 Add Funds", callback_data="menu_addfunds")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    msg = f"Welcome to Mongyni Store!\n\nYour ID: {user_id}\nYour Balance: ${balance:.2f}\n\nPlease select a product below:"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup)
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup)

def build_product_intro(product_id):
    info = PRODUCTS[product_id]
    stock = get_product_stock(product_id)
    msg = (f"📦 {info['name']}\n\n"
           f"{info['description']}\n\n"
           f"Price: ${info['price']:.2f} each\n"
           f"In stock: {stock}\n\n"
           f"✏️ How many do you want? Please type a number.")
    keyboard = [
        [InlineKeyboardButton("◀ Cancel", callback_data="main_menu")],
    ]
    return msg, InlineKeyboardMarkup(keyboard)

def build_confirm_page(product_id, qty, user_id):
    info = PRODUCTS[product_id]
    total = info["price"] * qty
    balance = get_user_balance(user_id)

    msg = (f"📦 <b>{info['name']}</b>\n\n"
           f"Quantity: <b>{qty}</b>\n"
           f"Price: <b>${info['price']:.2f}</b> each\n"
           f"Total Price: <b>${total:.2f}</b>\n"
           f"Your Balance: <b>${balance:.2f}</b>\n\n"
           f"Choose how you would like to pay:")

    keyboard = []
    if balance >= total:
        keyboard.append([InlineKeyboardButton(f"✅ Pay with Balance (${balance:.2f})", callback_data=f"confirm_{product_id}_{qty}")])

    keyboard.append([InlineKeyboardButton("💠 Direct Pay via Crypto (OxaPay)", callback_data=f"payprod_oxapay_{product_id}_{qty}")])
    keyboard.append([InlineKeyboardButton("🅱️ Direct Pay via Bybit UID", callback_data=f"payprod_bybit_{product_id}_{qty}")])
    keyboard.append([InlineKeyboardButton("💳 Add Funds to Balance", callback_data="menu_addfunds")])
    keyboard.append([InlineKeyboardButton("◀ Cancel", callback_data="main_menu")])

    return msg, InlineKeyboardMarkup(keyboard)

def build_payment_method_page(amount):
    msg = f"Amount to Deposit: ${amount:.2f}\n\nHow would you like to pay?"
    keyboard = [
        [InlineKeyboardButton("💠 Pay with Crypto (OxaPay)", callback_data="paymethod_oxapay")],
        [InlineKeyboardButton("🅱️ Pay via Bybit UID", callback_data="paymethod_bybit")],
        [InlineKeyboardButton("◀ Cancel", callback_data="main_menu")],
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

async def fulfill_transaction(query_or_message, track_id, user_id, amount, product_id, qty, extra_credit=0.0):
    info = PRODUCTS.get(product_id)
    if product_id and qty > 0 and info:
        items = take_inventory_items(product_id, qty)
        if items is not None:
            delivery_text = "\n".join(items)
            msg = (f"✅ Payment successful & order delivered!\n\n"
                   f"Product: <b>{qty}x {info['name']}</b>\n"
                   f"Amount Paid: <b>${amount:.2f}</b>\n\n")
            if extra_credit and extra_credit > 0:
                update_user_balance(user_id, extra_credit)
                new_bal = get_user_balance(user_id)
                msg += f"💵 <b>${extra_credit:.2f}</b> extra has been credited to your balance (New Balance: ${new_bal:.2f}).\n\n"
            
            msg += f"Here are your account details:\n{delivery_text}"
            if hasattr(query_or_message, 'edit_message_text'):
                await query_or_message.edit_message_text(msg, parse_mode="HTML")
            else:
                await query_or_message.reply_text(msg, parse_mode="HTML")
            return

        # Out of stock fallback -> credit to balance
        update_user_balance(user_id, amount)
        new_bal = get_user_balance(user_id)
        msg = (f"✅ Payment of ${amount:.2f} received!\n\n"
               f"⚠️ Unfortunately, {info['name']} went out of stock. ${amount:.2f} has been credited to your balance.\n"
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

    if data == "main_menu":
        context.user_data['awaiting_quantity'] = False
        await start(update, context)

    elif data == "noop":
        return

    elif data.startswith("prod_"):
        product_id = data.split("_", 1)[1]
        if product_id not in PRODUCTS:
            await query.answer("❌ Product not found.", show_alert=True)
            return
        stock = get_product_stock(product_id)
        if stock <= 0:
            await query.answer("❌ Sorry, this product is currently out of stock.", show_alert=True)
            return
        context.user_data['cur_product'] = product_id
        context.user_data['awaiting_quantity'] = True
        msg, markup = build_product_intro(product_id)
        await query.edit_message_text(msg, reply_markup=markup)

    elif data.startswith("confirm_"):
        parts = data.split("_")
        product_id = parts[1]
        qty = int(parts[2]) if len(parts) > 2 else context.user_data.get('cur_qty', 1)

        info = PRODUCTS.get(product_id)
        if not info:
            await query.answer("❌ Product not found.", show_alert=True)
            return

        total_price = info["price"] * qty
        balance = get_user_balance(user_id)

        if balance < total_price:
            keyboard = [
                [InlineKeyboardButton("💠 Pay directly via OxaPay", callback_data=f"payprod_oxapay_{product_id}_{qty}")],
                [InlineKeyboardButton("🅱️ Pay directly via Bybit UID", callback_data=f"payprod_bybit_{product_id}_{qty}")],
                [InlineKeyboardButton("💳 Add Funds to Account", callback_data="menu_addfunds")],
                [InlineKeyboardButton("◀ Main Menu", callback_data="main_menu")],
            ]
            await query.edit_message_text(
                f"❌ <b>Insufficient Balance</b> (${balance:.2f}). Total required: <b>${total_price:.2f}</b>.\n\n"
                f"Choose a payment option below to complete your order:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
            return

        items = take_inventory_items(product_id, qty)
        if items is not None:
            update_user_balance(user_id, -total_price)
            new_balance = get_user_balance(user_id)
            delivery_text = "\n".join(items)
            await query.edit_message_text(
                f"✅ Purchase successful! {qty}x {info['name']} — ${total_price:.2f} deducted.\n"
                f"Remaining balance: ${new_balance:.2f}\n\n"
                f"Here are your details:\n{delivery_text}"
            )
            context.user_data.pop('cur_product', None)
            context.user_data.pop('cur_qty', None)
        else:
            await query.answer("❌ Sorry, not enough stock for that quantity.", show_alert=True)

    # --- Direct Product OxaPay Pay (Coin Selection) ---
    elif data.startswith("payprod_oxapay_"):
        parts = data.split("_")
        product_id = parts[2]
        qty = int(parts[3])
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

        total_price = info["price"] * qty
        msg, markup = build_oxapay_coin_menu(f"payprodcoin_{product_id}_{qty}", f"Order: <b>{qty}x {info['name']}</b> — Price: <b>${total_price:.2f} USD</b>")
        await query.edit_message_text(msg, reply_markup=markup, parse_mode="HTML")

    # --- Direct Product OxaPay Whitelabel Address Generation ---
    elif data.startswith("payprodcoin_"):
        parts = data.split("_")
        product_id = parts[1]
        qty = int(parts[2])
        pay_currency = parts[3]
        network = parts[4] if len(parts) > 4 else "none"

        info = PRODUCTS.get(product_id)
        if not info:
            await query.answer("❌ Product not found.", show_alert=True)
            return

        merchant_key = get_oxapay_merchant_key()
        total_price = info["price"] * qty
        
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
            
            keyboard = [
                [InlineKeyboardButton("Check Payment Status", callback_data=f"checkpay_{track_id}")],
                [InlineKeyboardButton("◀ Main Menu", callback_data="main_menu")]
            ]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        else:
            err_msg = res_data.get("message") if isinstance(res_data, dict) else str(res_data)
            await query.edit_message_text(f"❌ Whitelabel Invoice Error ({status_code}): {err_msg}")

    # --- Direct Product Bybit Pay ---
    elif data.startswith("payprod_bybit_"):
        parts = data.split("_")
        product_id = parts[2]
        qty = int(parts[3])
        info = PRODUCTS.get(product_id)
        if not info:
            await query.answer("❌ Product not found.", show_alert=True)
            return

        bybit_uid = get_bybit_uid()
        total_price = info["price"] * qty
        track_id = int(uuid.uuid4().int % 10_000_000_000)
        unique_suffix = (track_id % 9999) / 1000000.0
        unique_amount = round(total_price + unique_suffix, 6)

        create_transaction(track_id, user_id, total_price, "pending", "bybit", product_id=product_id, qty=qty)
        context.user_data['bybit_unique_amount'] = unique_amount

        safe_uid = html_lib.escape(str(bybit_uid))
        msg = (f"📬 Direct Payment for <b>{qty}x {info['name']}</b>:\n\n"
               f"Send EXACTLY this amount via Bybit 'Send to UID':\n"
               f"<code>{unique_amount}</code> USDT\n\n"
               f"To Bybit UID:\n<code>{safe_uid}</code>\n\n"
               f"Once sent, tap the button below to receive your product immediately.")
        keyboard = [
            [InlineKeyboardButton("✅ I've Sent It — Check Now", callback_data=f"checkbybit_{track_id}")],
            [InlineKeyboardButton("◀ Main Menu", callback_data="main_menu")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "menu_addfunds":
        context.user_data['awaiting_amount'] = True
        keyboard = [
            [InlineKeyboardButton("◀ Cancel", callback_data="cancel_addfunds")]
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
            msg = (f"💳 <b>OxaPay Whitelabel Deposit Invoice</b>\n\n"
                   f"Amount to Send: <code>{pay_amount}</code> {pay_currency}\n"
                   f"Network: <b>{net_display}</b>\n\n"
                   f"📬 <b>Deposit Address (Tap to copy):</b>\n"
                   f"<code>{address}</code>\n\n"
                   f"⚠️ Send EXACTLY <code>{pay_amount}</code> {pay_currency} to the address above.\nOnce sent, click the button below to check status.")
            keyboard = [
                [InlineKeyboardButton("Check Payment Status", callback_data=f"checkpay_{track_id}")],
                [InlineKeyboardButton("◀ Main Menu", callback_data="main_menu")]
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
                    await fulfill_transaction(query, track_id, user_id, amount, product_id, qty, extra_credit=extra_credit)
                elif status == "expired":
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute('UPDATE transactions SET status = ? WHERE track_id = ?', ("expired", track_id))
                    conn.commit()
                    conn.close()
                    await query.edit_message_text("❌ This payment link has expired. Please request a new one.")
                else:
                    keyboard = [
                        [InlineKeyboardButton("Check Payment Status", callback_data=f"checkpay_{track_id}")],
                        [InlineKeyboardButton("◀ Back", callback_data="main_menu")]
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
        msg = (f"📬 Send EXACTLY this amount via Bybit 'Send to UID':\n\n"
               f"<code>{unique_amount}</code> USDT\n\n"
               f"To this Bybit UID:\n<code>{safe_uid}</code>\n\n"
               f"Once sent, tap the button below.")
        keyboard = [
            [InlineKeyboardButton("✅ I've Sent It — Check Now", callback_data=f"checkbybit_{track_id}")],
            [InlineKeyboardButton("◀ Main Menu", callback_data="main_menu")]
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
            await fulfill_transaction(query, track_id, user_id, amount, product_id, qty, extra_credit=extra_credit)
        else:
            keyboard = [
                [InlineKeyboardButton("✅ I've Sent It — Check Now", callback_data=f"checkbybit_{track_id}")],
                [InlineKeyboardButton("◀ Main Menu", callback_data="main_menu")]
            ]
            await query.edit_message_text(
                f"⏳ We haven't seen that deposit yet. Double check the amount was exact ({unique_amount} USDT) and try again in a minute.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

        msg, markup = build_payment_method_page(amount)
        await update.message.reply_text(msg, reply_markup=markup)
        return

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

    ox_status = "✅ Set" if ox_key and ox_key != "YOUR_OXAPAY_MERCHANT_KEY" else "❌ Not Configured"
    by_uid_status = f"✅ Set ({by_uid})" if by_uid and by_uid != "YOUR_BYBIT_UID_HERE" else "❌ Not Configured"
    by_api_status = "✅ Set" if by_key else "❌ Not Configured"

    msg = (f"⚙️ <b>Bot Settings</b>\n\n"
           f"OxaPay Merchant Key: {ox_status}\n"
           f"Bybit UID: {by_uid_status}\n"
           f"Bybit API Key: {by_api_status}\n\n"
           f"<b>Admin Commands:</b>\n"
           f"• <code>/setoxapay &lt;key&gt;</code>\n"
           f"• <code>/setbybit &lt;uid&gt;</code>\n"
           f"• <code>/setbybitkeys &lt;api_key&gt; &lt;api_secret&gt;</code>\n"
           f"• <code>/credituser &lt;user_id&gt; &lt;amount&gt;</code>\n"
           f"• <code>/addstock &lt;product_id&gt;</code>")
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

# --- MAIN RUNNER ---
def main() -> None:
    init_db()
    token = get_bot_token()
    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addstock", addstock))
    application.add_handler(CommandHandler("setoxapay", setoxapay))
    application.add_handler(CommandHandler("setbybit", setbybit))
    application.add_handler(CommandHandler("setbybitkeys", setbybitkeys))
    application.add_handler(CommandHandler("credituser", credituser))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Mongyni Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
