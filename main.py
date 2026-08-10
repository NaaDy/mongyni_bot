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
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
ADMIN_ID = 123456789 # Put your numeric Telegram ID here
MINI_APP_URL = "https://naady.github.io/mongyni_bot/" # Your GitHub Pages URL
OXAPAY_MERCHANT_KEY = "YOUR_OXAPAY_MERCHANT_KEY" # Replace with your OxaPay API Key
PRODUCT_PRICE = 1.30

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# --- DATABASE SETUP & FUNCTIONS ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS products (id TEXT PRIMARY KEY, stock INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (track_id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL, status TEXT)''')
    # Insert default product if not exists
    cursor.execute('INSERT OR IGNORE INTO products (id, stock) VALUES (?, ?)', ('office365', 100))
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

def get_product_stock(product_id='office365'):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT stock FROM products WHERE id = ?', (product_id,))
    result = cursor.fetchone()
    stock = result[0] if result else 0
    conn.close()
    return stock

def reduce_product_stock(product_id='office365'):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE products SET stock = stock - 1 WHERE id = ? AND stock > 0', (product_id,))
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success

# --- BOT COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    balance = get_user_balance(user_id)
    stock = get_product_stock()

    web_app_url_with_data = f"{MINI_APP_URL}?stock={stock}&balance={balance}&userid={user_id}"

    keyboard = [
        [InlineKeyboardButton("Open Store 🛒", web_app=WebAppInfo(url=web_app_url_with_data))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Welcome to Mongyni Store!\n\nYour ID: {user_id}\nYour Balance: ${balance:.2f}",
        reply_markup=reply_markup
    )

# --- HANDLE WEB APP CLICKS ---
async def web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = json.loads(update.message.web_app_data.data)
    action = data.get("action")
    user_id = update.message.from_user.id

    if action == "buy_product":
        balance = get_user_balance(user_id)
        if balance >= PRODUCT_PRICE:
            if reduce_product_stock():
                update_user_balance(user_id, -PRODUCT_PRICE)
                new_balance = get_user_balance(user_id)
                await update.message.reply_text(f"✅ Purchase successful! $1.30 has been deducted.\n\nYour remaining balance: ${new_balance:.2f}\n\nHere are your Office 365 1TB details:\n[Product credentials would go here]")
            else:
                await update.message.reply_text("❌ Sorry, this product is currently out of stock.")
        else:
            await update.message.reply_text(f"❌ Insufficient funds. You need ${PRODUCT_PRICE:.2f} but your balance is ${balance:.2f}. Please add funds.")
            
    elif action == "add_funds":
        keyboard = [
            [InlineKeyboardButton("$2", callback_data="addfunds_2"), InlineKeyboardButton("$5", callback_data="addfunds_5")],
            [InlineKeyboardButton("$10", callback_data="addfunds_10"), InlineKeyboardButton("$20", callback_data="addfunds_20")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Select the amount you want to add to your balance:", reply_markup=reply_markup)

# --- HANDLE INLINE BUTTONS (OXAPAY) ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data.startswith("addfunds_"):
        amount = float(data.split("_")[1])
        order_id = str(uuid.uuid4())
        
        # Request OxaPay payment link
        payload = {
            "merchant": OXAPAY_MERCHANT_KEY,
            "amount": amount,
            "currency": "USD",
            "orderId": order_id,
            "description": f"Add funds for User {user_id}"
        }
        
        try:
            response = requests.post("https://api.oxapay.com/merchants/request", json=payload)
            res_data = response.json()
            if res_data.get("result") == 100:
                pay_link = res_data.get("payLink")
                track_id = res_data.get("trackId")
                
                # Save transaction
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute('INSERT INTO transactions (track_id, user_id, amount, status) VALUES (?, ?, ?, ?)', (track_id, user_id, amount, "pending"))
                conn.commit()
                conn.close()
                
                keyboard = [
                    [InlineKeyboardButton("Pay via OxaPay", url=pay_link)],
                    [InlineKeyboardButton("Check Payment Status", callback_data=f"checkpay_{track_id}")]
                ]
                await query.edit_message_text(f"Click the button below to pay ${amount}. Once completed, click 'Check Payment Status'.", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await query.edit_message_text(f"❌ Error generating payment link: {res_data.get('message')}")
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
            
            conn = sqlite3.connect('mongyni.db')
            cursor = conn.cursor()
            cursor.execute('SELECT status, amount FROM transactions WHERE track_id = ? AND user_id = ?', (track_id, user_id))
            txn = cursor.fetchone()
            
            if txn:
                db_status, amount = txn
                if db_status == "completed":
                    await query.edit_message_text(f"✅ This payment of ${amount} has already been credited to your account.")
                elif status == "Paid":
                    cursor.execute('UPDATE transactions SET status = ? WHERE track_id = ?', ("completed", track_id))
                    conn.commit()
                    update_user_balance(user_id, amount)
                    new_balance = get_user_balance(user_id)
                    await query.edit_message_text(f"✅ Payment successful! ${amount} added. New balance: ${new_balance:.2f}")
                elif status == "Expired":
                    cursor.execute('UPDATE transactions SET status = ? WHERE track_id = ?', ("expired", track_id))
                    conn.commit()
                    await query.edit_message_text("❌ This payment link has expired. Please request a new one.")
                else:
                    # Still pending
                    keyboard = [
                        [InlineKeyboardButton("Check Payment Status", callback_data=f"checkpay_{track_id}")]
                    ]
                    await query.edit_message_text(f"⏳ Payment is still pending (Status: {status}). Try again in a moment.", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await query.edit_message_text("❌ Transaction not found.")
            conn.close()
        except Exception as e:
            logging.error(f"OxaPay Check Error: {e}")
            await query.answer("❌ Error checking payment status.", show_alert=True)

# --- MAIN RUNNER ---
def main() -> None:
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data))
    application.add_handler(CallbackQueryHandler(button_handler))

    print("Mongyni Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
