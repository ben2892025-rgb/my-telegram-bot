import os
import sqlite3
import random

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# =========================
# BOT SETTINGS
# =========================

TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

DB = "anime_cards.db"

RARITIES = {
    1: "Common",
    2: "Uncommon",
    3: "Rare",
    4: "Super Rare",
    5: "Epic",
    6: "Legendary",
    7: "Mythic",
    8: "Divine",
    9: "Celestial",
    10: "Eternal",
    11: "Supreme"
}

LEVELS = [
    (0, 1), (5, 2), (10, 3), (15, 4),
    (20, 5), (25, 6), (30, 7), (35, 8),
    (40, 9), (45, 10), (50, 11)
]


# =========================
# DATABASE
# =========================

def connect():
    return sqlite3.connect(DB)


def setup_database():
    db = connect()
    c = db.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        money INTEGER DEFAULT 1000
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS cards (
        card_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        rarity INTEGER,
        price INTEGER,
        image TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS collection (
        instance_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        card_id INTEGER
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS groups_data (
        chat_id INTEGER PRIMARY KEY,
        message_count INTEGER DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS drops (
        chat_id INTEGER PRIMARY KEY,
        card_id INTEGER
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS auctions (
        auction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        seller INTEGER,
        instance_id INTEGER,
        price INTEGER,
        bidder INTEGER DEFAULT 0,
        highest_bid INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1
    )
    """)

    db.commit()
    db.close()


def register_user(user_id):
    db = connect()
    db.execute(
        "INSERT OR IGNORE INTO users(user_id) VALUES(?)",
        (user_id,)
    )
    db.commit()
    db.close()


def balance(user_id):
    register_user(user_id)
    db = connect()
    result = db.execute(
        "SELECT money FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()
    db.close()
    return result[0]


def get_level(user_id):
    db = connect()
    count = db.execute(
        "SELECT COUNT(*) FROM collection WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]
    db.close()

    level = 1
    for required, number in LEVELS:
        if count >= required:
            level = number
    return level, count


def add_money(user_id, amount):
    register_user(user_id)
    db = connect()
    db.execute(
        "UPDATE users SET money=money+? WHERE user_id=?",
        (amount, user_id)
    )
    db.commit()
    db.close()


def add_card(user_id, card_id):
    db = connect()
    db.execute(
        "INSERT INTO collection(user_id,card_id) VALUES(?,?)",
        (user_id, card_id)
    )
    db.commit()
    db.close()


# =========================
# START / PROFILE
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id)

    await update.message.reply_text(
        f"🎴 Welcome to Anime Card World!\n\n"
        f"Hello {user.first_name} ❤️\n\n"
        f"💵 Balance: {balance(user.id)}\n\n"
        "Commands:\n"
        "/profile - Profile\n"
        "/balance - Money\n"
        "/catch - Catch card\n"
        "/collection - My cards\n"
        "/shop - Card shop\n"
        "/buy ID - Buy card\n"
        "/auctions - Auctions\n"
        "/help - Help"
    )


async def help_command(update, context):
    await update.message.reply_text(
        "🎴 ANIME CARD BOT HELP\n\n"
        "/start - Start Bot\n"
        "/profile - My profile\n"
        "/balance - My money\n"
        "/catch - Catch dropped card\n"
        "/collection - My collection\n"
        "/shop - Card shop\n"
        "/buy ID - Buy a card\n"
        "/w ID - Find card name\n"
        ".w ID - Find card name\n"
        "/auctions - Auction list\n"
        "/auction ID PRICE - Sell card by auction\n"
        "/bid ID PRICE - Place a bid\n"
        "/closeauction ID - Close your auction\n\n"
        "💵 Money is the only currency.\n"
        "⭐ Levels depend on collected cards."
    )


async def profile(update, context):
    user = update.effective_user
    register_user(user.id)
    level, count = get_level(user.id)

    await update.message.reply_text(
        f"👤 {user.first_name}\n"
        f"💵 Money: {balance(user.id)}\n"
        f"🎴 Cards: {count}\n"
        f"⭐ Level: {level}/11"
    )


async def show_balance(update, context):
    user = update.effective_user
    await update.message.reply_text(
        f"💵 Your Balance: {balance(user.id)}"
    )


# =========================
# OWNER ADD CARD
# =========================

async def addcard_command(update, context):
    if update.effective_user.id != OWNER_ID:
        return

    if not update.message.reply_to_message:
        await update.message.reply_text(
            "Reply to a photo with:\n"
            "/addcard Name | Rarity | Price"
        )
        return

    replied = update.message.reply_to_message

    if not replied.photo:
        await update.message.reply_text("Photo required!")
        return

    if not context.args:
        await update.message.reply_text(
            "Example: /addcard Naruto | 5 | 500"
        )
        return

    try:
        parts = " ".join(context.args).split("|")
        name = parts[0].strip()
        rarity = int(parts[1].strip())
        price = int(parts[2].strip())

        if not name or rarity not in RARITIES or price < 0:
            raise ValueError()

        image = replied.photo[-1].file_id

        db = connect()
        c = db.cursor()
        c.execute(
            "INSERT INTO cards(name,rarity,price,image) VALUES(?,?,?,?)",
            (name, rarity, price, image)
        )
        card_id = c.lastrowid
        db.commit()
        db.close()

        await update.message.reply_text(
            f"✅ Card Added!\n"
            f"🎴 ID: {card_id}\n"
            f"Name: {name}\n"
            f"⭐ Rarity: {RARITIES[rarity]}\n"
            f"💵 Price: {price}"
        )

    except (ValueError, IndexError):
        await update.message.reply_text(
            "Wrong format!\n"
            "Use: /addcard Naruto | 5 | 500"
        )


# =========================
# GROUP CARD DROP
# =========================

async def group_messages(update, context):
    if not update.message or not update.effective_user:
        return

    if update.effective_user.is_bot:
        return

    chat_id = update.effective_chat.id

    db = connect()
    c = db.cursor()

    c.execute(
        "INSERT OR IGNORE INTO groups_data(chat_id) VALUES(?)",
        (chat_id,)
    )

    c.execute(
        "UPDATE groups_data SET message_count=message_count+1 WHERE chat_id=?",
        (chat_id,)
    )

    count = c.execute(
        "SELECT message_count FROM groups_data WHERE chat_id=?",
        (chat_id,)
    ).fetchone()[0]

    pending = c.execute(
        "SELECT card_id FROM drops WHERE chat_id=?",
        (chat_id,)
    ).fetchone()

    if count >= 100 and not pending:
        card = c.execute(
            "SELECT card_id FROM cards ORDER BY RANDOM() LIMIT 1"
        ).fetchone()

        if card:
            c.execute(
                "INSERT OR REPLACE INTO drops(chat_id,card_id) VALUES(?,?)",
                (chat_id, card[0])
            )
            c.execute(
                "UPDATE groups_data SET message_count=0 WHERE chat_id=?",
                (chat_id,)
            )

            db.commit()
            db.close()

            await update.message.reply_text(
                "🎴 A NEW CARD HAS DROPPED!\n\n"
                "Use /catch to collect it!"
            )
            return

    db.commit()
    db.close()


async def catch_card(update, context):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    db = connect()
    c = db.cursor()

    drop = c.execute(
        "SELECT card_id FROM drops WHERE chat_id=?",
        (chat_id,)
    ).fetchone()

    if not drop:
        db.close()
        await update.message.reply_text("No card available!")
        return

    card_id = drop[0]

    card = c.execute(
        "SELECT name,rarity,image FROM cards WHERE card_id=?",
        (card_id,)
    ).fetchone()

    c.execute(
        "INSERT INTO collection(user_id,card_id) VALUES(?,?)",
        (user_id, card_id)
    )

    c.execute(
        "DELETE FROM drops WHERE chat_id=?",
        (chat_id,)
    )

    db.commit()
    db.close()

    name, rarity, image = card

    await update.message.reply_photo(
        photo=image,
        caption=(
            f"🎉 Card Collected!\n\n"
            f"🎴 ID: {card_id}\n"
            f"Name: {name}\n"
            f"⭐ {RARITIES[rarity]}\n"
            f"👤 Owner: {update.effective_user.first_name}"
        )
    )


async def manual_drop(update, context):
    if update.effective_user.id != OWNER_ID:
        return

    if not context.args:
        await update.message.reply_text("Use /drop CARD_ID")
        return

    try:
        card_id = int(context.args[0])
    except ValueError:
        return

    db = connect()
    card = db.execute(
        "SELECT card_id FROM cards WHERE card_id=?",
        (card_id,)
    ).fetchone()

    if not card:
        db.close()
        await update.message.reply_text("Card not found!")
        return

    db.execute(
        "INSERT OR REPLACE INTO drops(chat_id,card_id) VALUES(?,?)",
        (update.effective_chat.id, card_id)
    )
    db.commit()
    db.close()

    await update.message.reply_text(
        f"🎴 Owner Drop!\nCard ID: {card_id}\nUse /catch"
    )


# =========================
# COLLECTION
# =========================

async def collection(update, context):
    user_id = update.effective_user.id

    db = connect()
    cards = db.execute("""
        SELECT collection.instance_id, cards.card_id,
               cards.name, cards.rarity
        FROM collection
        JOIN cards ON collection.card_id=cards.card_id
        WHERE collection.user_id=?
        ORDER BY collection.instance_id DESC
        LIMIT 30
    """, (user_id,)).fetchall()
    db.close()

    if not cards:
        await update.message.reply_text("Your collection is empty!")
        return

    text = "🎴 YOUR COLLECTION\n\n"

    for instance, card_id, name, rarity in cards:
        text += (
            f"Instance: {instance} | Card ID: {card_id}\n"
            f"{name} - {RARITIES[rarity]}\n\n"
        )

    await update.message.reply_text(text)


# =========================
# CARD NAME SEARCH
# =========================

async def card_search(update, context):
    if not context.args:
        await update.message.reply_text("Use /w CARD_ID")
        return

    try:
        card_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Enter a card ID!")
        return

    db = connect()
    card = db.execute(
        "SELECT name,rarity,price,image FROM cards WHERE card_id=?",
        (card_id,)
    ).fetchone()
    db.close()

    if not card:
        await update.message.reply_text("Card not found!")
        return

    name, rarity, price, image = card

    await update.message.reply_photo(
        photo=image,
        caption=(
            f"🎴 CARD INFORMATION\n\n"
            f"ID: {card_id}\n"
            f"Name: {name}\n"
            f"Rarity: {RARITIES[rarity]}\n"
            f"💵 Price: {price}"
        )
    )


async def dot_search(update, context):
    parts = update.message.text.split()
    context.args = parts[1:] if len(parts) > 1 else []
    await card_search(update, context)


# =========================
# CARD SHOP
# =========================

async def shop(update, context):
    db = connect()
    cards = db.execute(
        "SELECT card_id,name,rarity,price FROM cards ORDER BY card_id"
    ).fetchall()
    db.close()

    if not cards:
        await update.message.reply_text("Shop is empty!")
        return

    text = "🛒 ANIME CARD SHOP\n\n"

    for card_id, name, rarity, price in cards[:30]:
        text += (
            f"🎴 ID: {card_id}\n"
            f"{name} | {RARITIES[rarity]}\n"
            f"💵 Price: {price}\n"
            f"Buy: /buy {card_id}\n\n"
        )

    await update.message.reply_text(text)


async def buy_card(update, context):
    if not context.args:
        await update.message.reply_text("Use /buy CARD_ID")
        return

    try:
        card_id = int(context.args[0])
    except ValueError:
        return

    user_id = update.effective_user.id
    register_user(user_id)

    db = connect()
    c = db.cursor()

    card = c.execute(
        "SELECT name,price FROM cards WHERE card_id=?",
        (card_id,)
    ).fetchone()

    if not card:
        db.close()
        await update.message.reply_text("Card not found!")
        return

    name, price = card
    money = c.execute(
        "SELECT money FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    if money < price:
        db.close()
        await update.message.reply_text("Not enough 💵!")
        return

    c.execute(
        "UPDATE users SET money=money-? WHERE user_id=?",
        (price, user_id)
    )
    c.execute(
        "INSERT INTO collection(user_id,card_id) VALUES(?,?)",
        (user_id, card_id)
    )

    db.commit()
    db.close()

    await update.message.reply_text(
        f"✅ Purchased {name}!\n💵 Paid: {price}"
    )


# =========================
# AUCTION
# =========================

async def auction(update, context):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Use /auction INSTANCE_ID START_PRICE"
        )
        return

    try:
        instance_id = int(context.args[0])
        price = int(context.args[1])
        if price < 1:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("Invalid price or ID!")
        return

    user_id = update.effective_user.id

    db = connect()
    c = db.cursor()

    owned = c.execute(
        "SELECT card_id FROM collection WHERE instance_id=? AND user_id=?",
        (instance_id, user_id)
    ).fetchone()

    if not owned:
        db.close()
        await update.message.reply_text("You don't own this card!")
        return

    active = c.execute(
        "SELECT auction_id FROM auctions WHERE instance_id=? AND active=1",
        (instance_id,)
    ).fetchone()

    if active:
        db.close()
        await update.message.reply_text("This card is already auctioned!")
        return

    c.execute(
        "INSERT INTO auctions(seller,instance_id,price) VALUES(?,?,?)",
        (user_id, instance_id, price)
    )

    auction_id = c.lastrowid
    db.commit()
    db.close()

    await update.message.reply_text(
        f"🔨 Auction Created!\n"
        f"Auction ID: {auction_id}\n"
        f"Starting price: 💵 {price}\n"
        f"Bid: /bid {auction_id} PRICE"
    )


async def auctions(update, context):
    db = connect()
    items = db.execute("""
        SELECT auction_id,instance_id,price,highest_bid
        FROM auctions WHERE active=1
    """).fetchall()
    db.close()

    if not items:
        await update.message.reply_text("No active auctions!")
        return

    text = "🔨 ACTIVE AUCTIONS\n\n"

    for aid, instance, price, highest in items:
        text += (
            f"Auction: {aid}\n"
            f"Card Instance: {instance}\n"
            f"Start: 💵 {price}\n"
            f"Highest bid: 💵 {highest}\n"
            f"Bid: /bid {aid} PRICE\n\n"
        )

    await update.message.reply_text(text)


async def bid(update, context):
    if len(context.args) < 2:
        await update.message.reply_text("Use /bid AUCTION_ID PRICE")
        return

    try:
        auction_id = int(context.args[0])
        amount = int(context.args[1])
        if amount < 1:
            raise ValueError()
    except ValueError:
        return

    user_id = update.effective_user.id
    register_user(user_id)

    db = connect()
    c = db.cursor()

    item = c.execute("""
        SELECT seller,price,bidder,highest_bid
        FROM auctions
        WHERE auction_id=? AND active=1
    """, (auction_id,)).fetchone()

    if not item:
        db.close()
        await update.message.reply_text("Auction not found!")
        return

    seller, start_price, old_bidder, highest = item

    if seller == user_id:
        db.close()
        await update.message.reply_text("You cannot bid on your own card!")
        return

    if amount <= max(start_price, highest):
        db.close()
        await update.message.reply_text("Bid must be higher!")
        return

    money = c.execute(
        "SELECT money FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()[0]

    if money < amount:
        db.close()
        await update.message.reply_text("Not enough 💵!")
        return

    c.execute(
        "UPDATE auctions SET bidder=?,highest_bid=? WHERE auction_id=?",
        (user_id, amount, auction_id)
    )

    db.commit()
    db.close()

    await update.message.reply_text(
        f"🔨 New bid!\n💵 {amount}"
    )


async def close_auction(update, context):
    if not context.args:
        await update.message.reply_text("Use /closeauction AUCTION_ID")
        return

    try:
        auction_id = int(context.args[0])
    except ValueError:
        return

    user_id = update.effective_user.id

    db = connect()
    c = db.cursor()

    item = c.execute("""
        SELECT seller,instance_id,bidder,highest_bid
        FROM auctions
        WHERE auction_id=? AND active=1
    """, (auction_id,)).fetchone()

    if not item:
        db.close()
        await update.message.reply_text("Auction not found!")
        return

    seller, instance, bidder, price = item

    if seller != user_id:
        db.close()
        await update.message.reply_text("Only the seller can close it!")
        return

    if not bidder:
        c.execute(
            "UPDATE auctions SET active=0 WHERE auction_id=?",
            (auction_id,)
        )
        db.commit()
        db.close()
        await update.message.reply_text("Auction closed. No bids.")
        return

    money = c.execute(
        "SELECT money FROM users WHERE user_id=?",
        (bidder,)
    ).fetchone()[0]

    if money < price:
        db.close()
        await update.message.reply_text(
            "Winner no longer has enough money. Auction not completed."
        )
        return

    c.execute(
        "UPDATE users SET money=money-? WHERE user_id=?",
        (price, bidder)
    )
    c.execute(
        "UPDATE users SET money=money+? WHERE user_id=?",
        (price, seller)
    )
    c.execute(
        "UPDATE collection SET user_id=? WHERE instance_id=? AND user_id=?",
        (bidder, instance, seller)
    )
    c.execute(
        "UPDATE auctions SET active=0 WHERE auction_id=?",
        (auction_id,)
    )

    db.commit()
    db.close()

    await update.message.reply_text(
        f"🏆 Auction Completed!\n"
        f"Winner ID: {bidder}\n"
        f"💵 Paid: {price}"
    )


# =========================
# MAIN
# =========================

def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN environment variable is missing!")

    setup_database()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("balance", show_balance))
    app.add_handler(CommandHandler("addcard", addcard_command))
    app.add_handler(CommandHandler("drop", manual_drop))
    app.add_handler(CommandHandler("catch", catch_card))
    app.add_handler(CommandHandler("collection", collection))
    app.add_handler(CommandHandler("w", card_search))
    app.add_handler(CommandHandler("shop", shop))
    app.add_handler(CommandHandler("buy", buy_card))
    app.add_handler(CommandHandler("auction", auction))
    app.add_handler(CommandHandler("auctions", auctions))
    app.add_handler(CommandHandler("bid", bid))
    app.add_handler(CommandHandler("closeauction", close_auction))

    app.add_handler(
        MessageHandler(
            filters.Regex(r"(?i)^\.w(?:\s|$)"),
            dot_search
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            group_messages
        )
    )

    print("ANIME CARD BOT STARTED!")
    app.run_polling()


if __name__ == "__main__":
    main()
        
