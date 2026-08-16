import logging
import sqlite3
import json
import requests
import uuid
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters

DB_PATH = os.getenv('DB_PATH', 'mongyni.db')

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789")) # Put your numeric Telegram ID here
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://naady.github.io/mongyni_bot/") # Your GitHub Pages URL
OXAPAY_MERCHANT_KEY = os.getenv("OXAPAY_MERCHANT_KEY", "YOUR_OXAPAY_MERCHANT_KEY") # Replace with your OxaPay API Key

# --- PRODUCTS ---
# To add a new product, just add a new entry here with a unique id (key).
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


    # Example of a new product — copy this block, edit it, and it will show up automatically:
    # "netflix1m": {
    #     "name": "Netflix Premium 1 Month",
    #     "description": "Netflix Premium account, 1 month, Full HD/4K.",
    #     "price": 2.50,
    # },
}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# --- DATABASE SETUP & FUNCTIONS ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS products (id TEXT PRIMARY KEY, stock INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (track_id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, status TEXT)''')
    # Make sure every product defined above has a row in the DB (default stock 0, use /addstock to add stock)
    for product_id in PRODUCTS:
        cursor.execute('INSERT OR IGNORE INTO products (id, stock) VALUES (?, ?)', (product_id, 0))
    conn.commit()
    conn.close()

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
    cursor.execute('SELECT stock FROM products WHERE id = ?', (product_id,))
    result = cursor.fetchone()
    stock = result[0] if result else 0
    conn.close()
    return stock

def reduce_product_stock(product_id, qty=1):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?', (qty, product_id, qty))
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success

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

def build_product_page(product_id, qty):
    info = PRODUCTS[product_id]
    stock = get_product_stock(product_id)
    total = info["price"] * qty
    msg = (f"📦 {info['name']}\n\n"
           f"{info['description']}\n\n"
           f"Price: ${info['price']:.2f} each\n"
           f"In stock: {stock}\n\n"
           f"Quantity: {qty}\n"
           f"Total: ${total:.2f}")
    keyboard = [
        [
            InlineKeyboardButton("➖", callback_data=f"qty_dec_{product_id}"),
            InlineKeyboardButton(f"{qty}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"qty_inc_{product_id}"),
        ],
        [InlineKeyboardButton("✅ Confirm Purchase", callback_data=f"confirm_{product_id}")],
        [InlineKeyboardButton("◀ Back", callback_data="main_menu")],
    ]
    return msg, InlineKeyboardMarkup(keyboard)

# --- HANDLE INLINE BUTTONS ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "main_menu":
        await start(update, context)

    elif data == "noop":
        return

    elif data.startswith("prod_"):
        product_id = data.split("_", 1)[1]
        if product_id not in PRODUCTS:
            await query.answer("❌ Product not found.", show_alert=True)
            return
        context.user_data['cur_product'] = product_id
        context.user_data['cur_qty'] = 1
        msg, markup = build_product_page(product_id, 1)
        await query.edit_message_text(msg, reply_markup=markup)

    elif data.startswith("qty_dec_") or data.startswith("qty_inc_"):
        product_id = data.split("_", 2)[2]
        if context.user_data.get('cur_product') != product_id:
            await query.answer("❌ Session expired, please reopen the product.", show_alert=True)
            return
        qty = context.user_data.get('cur_qty', 1)
        stock = get_product_stock(product_id)
        if data.startswith("qty_dec_"):
            qty = max(1, qty - 1)
        else:
            qty = qty + 1
            if stock > 0 and qty > stock:
                qty = stock
                await query.answer("❌ That's the maximum available stock.", show_alert=False)
        context.user_data['cur_qty'] = qty
        msg, markup = build_product_page(product_id, qty)
        await query.edit_message_text(msg, reply_markup=markup)

    elif data.startswith("confirm_"):
        product_id = data.split("_", 1)[1]
        if context.user_data.get('cur_product') != product_id:
            await query.answer("❌ Session expired, please reopen the product.", show_alert=True)
            return
        qty = context.user_data.get('cur_qty', 1)
        info = PRODUCTS.get(product_id)
        if not info:
            await query.answer("❌ Product not found.", show_alert=True)
            return

        total_price = info["price"] * qty
        balance = get_user_balance(user_id)

        if balance < total_price:
            await query.answer(f"❌ Insufficient funds. You need ${total_price:.2f}.", show_alert=True)
            return

        if reduce_product_stock(product_id, qty):
            update_user_balance(user_id, -total_price)
            new_balance = get_user_balance(user_id)
            await query.edit_message_text(
                f"✅ Purchase successful! {qty}x {info['name']} — ${total_price:.2f} has been deducted.\n\n"
                f"Your remaining balance: ${new_balance:.2f}\n\n"
                f"Here are your {info['name']} details:\n[Product credentials would go here]"
            )
            context.user_data.pop('cur_product', None)
            context.user_data.pop('cur_qty', None)
        else:
            await query.answer("❌ Sorry, not enough stock for that quantity.", show_alert=True)

    elif data == "menu_addfunds":
        context.user_data['awaiting_amount'] = True
        keyboard = [
            [InlineKeyboardButton("◀ Cancel", callback_data="cancel_addfunds")]
        ]
        await query.edit_message_text("Please type and send the amount you want to add (e.g. 5 or 2.50):", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "cancel_addfunds":
        context.user_data['awaiting_amount'] = False
        await start(update, context)

    elif data.startswith("paycoin_"):
        parts = data.split("_", 2)
        pay_currency = parts[1]
        network = parts[2] if len(parts) > 2 else None
        amount = context.user_data.get('deposit_amount')
        
        if pay_currency == "USDT" and (not network or network == "none"):
            keyboard = [
                [InlineKeyboardButton("TRC20 (Tron)", callback_data="paycoin_USDT_trc20")],
                [InlineKeyboardButton("BEP20 (BSC)", callback_data="paycoin_USDT_bep20")],
                [InlineKeyboardButton("ERC20 (Ethereum)", callback_data="paycoin_USDT_erc20")],
                [InlineKeyboardButton("Polygon", callback_data="paycoin_USDT_polygon")],
                [InlineKeyboardButton("◀ Cancel", callback_data="main_menu")]
            ]
            await query.edit_message_text(f"Amount: ${amount:.2f}\nPlease choose the network for USDT:", reply_markup=InlineKeyboardMarkup(keyboard))
            return
            
        if not amount:
            await query.edit_message_text("❌ Session expired. Please try again.")
            return
            
        order_id = str(uuid.uuid4())
        
        # Add 0.04 fixed fee to the invoice amount
        invoice_amount = amount + 0.04
        
        payload = {
            "merchant": OXAPAY_MERCHANT_KEY,
            "amount": invoice_amount,
            "currency": "USD",
            "payCurrency": pay_currency,
            "orderId": order_id,
            "description": f"Add funds for User {user_id}"
        }
        if network and network != "none":
            payload["network"] = network
            
        try:
            response = requests.post("https://api.oxapay.com/merchants/request/whitelabel", json=payload)
            res_data = response.json()
            if res_data.get("result") == 100:
                address = res_data.get("address")
                pay_amount = res_data.get("payAmount")
                track_id = res_data.get("trackId")
                
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute('INSERT INTO transactions (track_id, user_id, amount, status) VALUES (?, ?, ?, ?)', (track_id, user_id, amount, "pending"))
                conn.commit()
                conn.close()
                
                msg = (f"⚠️ Please send EXACTLY this amount:\n<code>{pay_amount}</code> {pay_currency}\n\n"
                       f"📬 To this {network.upper()} address (Tap to copy):\n<code>{address}</code>\n\n"
                       f"Once you have sent the funds, click the button below to check your payment status.")
                       
                keyboard = [
                    [InlineKeyboardButton("Check Payment Status", callback_data=f"checkpay_{track_id}")],
                    [InlineKeyboardButton("◀ Main Menu", callback_data="main_menu")]
                ]
                await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            else:
                await query.edit_message_text(f"❌ Error generating address: {res_data.get('message')}\nDetails: {json.dumps(res_data)}")
        except Exception as e:
            logging.error(f"OxaPay API Error: {e}")
            await query.edit_message_text("❌ Error connecting to payment provider.")

    elif data.startswith("checkpay_"):
        track_id = data.split("_")[1]
        
        payload = {
            "merchant": OXAPAY_MERCHANT_KEY,
            "trackId": int(track_id)
        }
        try:
            response = requests.post("https://api.oxapay.com/merchants/inquiry", json=payload)
            res_data = response.json()
            status = res_data.get("status")
            
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('SELECT status, amount FROM transactions WHERE track_id = ? AND user_id = ?', (track_id, user_id))
            txn = cursor.fetchone()
            
            if txn:
                db_status, amount = txn
                if db_status == "completed":
                    await query.edit_message_text(f"✅ This payment of ${amount} has already been credited to your account.")
                elif status.lower() == "paid":
                    cursor.execute('UPDATE transactions SET status = ? WHERE track_id = ?', ("completed", track_id))
                    conn.commit()
                    update_user_balance(user_id, amount)
                    new_balance = get_user_balance(user_id)
                    await query.edit_message_text(f"✅ Payment successful! ${amount} added. New balance: ${new_balance:.2f}")
                elif status.lower() == "expired":
                    cursor.execute('UPDATE transactions SET status = ? WHERE track_id = ?', ("expired", track_id))
                    conn.commit()
                    await query.edit_message_text("❌ This payment link has expired. Please request a new one.")
                else:
                    keyboard = [
                        [InlineKeyboardButton("Check Payment Status", callback_data=f"checkpay_{track_id}")],
                        [InlineKeyboardButton("◀ Back", callback_data="main_menu")]
                    ]
                    await query.edit_message_text(f"⏳ Payment is still pending (Status: {status}).\nRaw details: {json.dumps(res_data)}", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await query.edit_message_text("❌ Transaction not found.")
            conn.close()
        except Exception as e:
            logging.error(f"OxaPay Check Error: {e}")
            await query.answer("❌ Error checking payment status.", show_alert=True)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        
        try:
            res = requests.post("https://api.oxapay.com/merchants/allowedCoins", json={"merchant": OXAPAY_MERCHANT_KEY})
            data = res.json()
            if data.get("result") == 100:
                coins = data.get("allowed", [])
                keyboard = []
                for coin in coins:
                    if isinstance(coin, dict):
                        currency = coin.get("currency")
                        network = coin.get("network")
                        name = coin.get("name", currency)
                        btn_text = f"{name} ({network})" if network else name
                        cb_data = f"paycoin_{currency}_{network}" if network else f"paycoin_{currency}_none"
                    else:
                        btn_text = str(coin)
                        cb_data = f"paycoin_{coin}_none"
                    keyboard.append([InlineKeyboardButton(btn_text, callback_data=cb_data)])
                
                if not keyboard:
                    await update.message.reply_text("❌ No payment methods configured. Please check your OxaPay merchant settings.")
                    return
                    
                keyboard.append([InlineKeyboardButton("◀ Cancel", callback_data="main_menu")])
                await update.message.reply_text(f"Amount: ${amount:.2f}\nChoose your payment method:", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.message.reply_text(f"❌ Error fetching payment methods: {data.get('message')}")
        except Exception as e:
            logging.error(f"OxaPay API Error: {e}")
            await update.message.reply_text("❌ Error connecting to payment provider.")

async def addstock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id != ADMIN_ID:
        return

    try:
        product_id = context.args[0]
        amount = int(context.args[1])

        if product_id not in PRODUCTS:
            await update.message.reply_text(f"❌ Unknown product id '{product_id}'. Available: {', '.join(PRODUCTS.keys())}")
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('UPDATE products SET stock = stock + ? WHERE id = ?', (amount, product_id))
        conn.commit()
        
        cursor.execute('SELECT stock FROM products WHERE id = ?', (product_id,))
        new_stock = cursor.fetchone()[0]
        conn.close()
        
        await update.message.reply_text(f"✅ Added {amount} items to '{product_id}'. Total stock is now {new_stock}.")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: /addstock <product_id> <number>")

# --- MAIN RUNNER ---
def main() -> None:
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addstock", addstock))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Mongyni Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
