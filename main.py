import logging
import sqlite3
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# --- CONFIGURATION ---
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
ADMIN_ID = 123456789 # Put your numeric Telegram ID here
MINI_APP_URL = "https://naady.github.io/mongyni_bot/" # Your GitHub Pages URL

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# --- DATABASE FUNCTIONS ---
def get_user_balance(user_id):
    conn = sqlite3.connect('mongyni.db')
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

def get_product_stock(product_id='office365'):
    conn = sqlite3.connect('mongyni.db')
    cursor = conn.cursor()
    cursor.execute('SELECT stock FROM products WHERE id = ?', (product_id,))
    stock = cursor.fetchone()[0]
    conn.close()
    return stock

# --- BOT COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    balance = get_user_balance(user_id)
    stock = get_product_stock()

    # Pass dynamic data to the Web App
    web_app_url_with_data = f"{MINI_APP_URL}?stock={stock}&balance={balance}&userid={user_id}"

    keyboard = [
        [InlineKeyboardButton("Open Store 🛒", web_app=WebAppInfo(url=web_app_url_with_data))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Welcome to Mongyni Store!\n\nYour ID: {user_id}\nYour Balance: ${balance}",
        reply_markup=reply_markup
    )

# --- HANDLE WEB APP CLICKS ---
async def web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """This function receives data when a button is clicked inside the Mini App"""
    data = json.loads(update.message.web_app_data.data)
    action = data.get("action")
    user_id = update.message.from_user.id

    if action == "buy_product":
        await update.message.reply_text("Checking your balance and processing order...")
        # We will write the purchase logic (deducting balance & giving product) in the next step!
        
    elif action == "add_funds":
        await update.message.reply_text("Please wait, generating OxaPay deposit link...")
        # We will write the OxaPay API connection in the next step!

# --- MAIN RUNNER ---
def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    
    # Listen for data coming from the Web App
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data))

    print("Mongyni Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
