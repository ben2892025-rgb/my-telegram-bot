import os
import re
import sqlite3
import random
import asyncio
from datetime import datetime, timedelta, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "anime_cards.db")
DROP_EVERY = 100
CURRENCY = "💵"

RARITIES = [
    ("Common", "⚪", 1), ("Uncommon", "🟢", 2), ("Rare", "🔵", 3),
    ("Super Rare", "🟣", 4), ("Epic", "🟠", 5), ("Elite", "💎", 6),
    ("Legendary", "🌟", 7), ("Mythic", "🔮", 8), ("Astral", "🌌", 9),
    ("Eternal", "✨", 10), ("Secret", "👑", 11)
]
PLAYER_LEVELS = [
    (0, "🌱 Beginner"), (5, "⚔️ Fighter"), (10, "🔥 Warrior"),
    (15, "🌌 Elite"), (20, "💎 Master"), (25, "👑 Champion"),
    (30, "🌠 Legend"), (35, "🔮 Mythic"), (40, "🐉 Dragon Lord"),
    (45, "🌟 Celestial"), (50, "♛ Supreme God")
]

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            balance INTEGER NOT NULL DEFAULT 0, last_daily TEXT
        );
        CREATE TABLE IF NOT EXISTS cards(
            card_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            rarity TEXT NOT NULL, price INTEGER NOT NULL DEFAULT 100,
            file_id TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS inventory(
            user_id INTEGER NOT NULL, card_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY(user_id, card_id)
        );
        CREATE TABLE IF NOT EXISTS groups_data(
            chat_id INTEGER PRIMARY KEY, message_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS drops(
            chat_id INTEGER PRIMARY KEY, card_id INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auctions(
            auction_id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER NOT NULL,
            card_id INTEGER NOT NULL, current_bid INTEGER NOT NULL,
            highest_bidder INTEGER, ends_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS bids(
            auction_id INTEGER NOT NULL, bidder_id INTEGER NOT NULL, amount INTEGER NOT NULL,
            PRIMARY KEY(auction_id, bidder_id)
        );
        CREATE TABLE IF NOT EXISTS processed_daily(
            user_id INTEGER PRIMARY KEY, day TEXT NOT NULL
        );
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_auction_status ON auctions(status, ends_at)")

def ensure_user(user):
    with db() as c:
        c.execute(
            "INSERT INTO users(user_id, username, first_name) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name",
            (user.id, user.username or "", user.first_name or "Player")
        )

def user_data(user_id):
    with db() as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def card_data(card_id):
    with db() as c:
        return c.execute("SELECT * FROM cards WHERE card_id=? AND active=1", (card_id,)).fetchone()

def collection_count(user_id):
    with db() as c:
        row = c.execute("SELECT COALESCE(SUM(quantity),0) n FROM inventory WHERE user_id=?", (user_id,)).fetchone()
        return int(row["n"])

def player_level(count):
    level = PLAYER_LEVELS[0][1]
    next_count = None
    for i, (needed, name) in enumerate(PLAYER_LEVELS):
        if count >= needed:
            level = name
            if i + 1 < len(PLAYER_LEVELS):
                next_count = PLAYER_LEVELS[i + 1][0]
    return level, next_count

def menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎴 Gacha / Catch", callback_data="catch"),
         InlineKeyboardButton("👤 Profile", callback_data="profile")],
        [InlineKeyboardButton("📚 Collection", callback_data="collection"),
         InlineKeyboardButton("🛒 Card Shop", callback_data="shop")],
        [InlineKeyboardButton("🎮 Mini Game", callback_data="game"),
         InlineKeyboardButton("🏆 Ranking", callback_data="rank")],
        [InlineKeyboardButton("🎁 Daily Reward", callback_data="daily"),
         InlineKeyboardButton("⚔️ Auction Hall", callback_data="auctions")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ])

async def send_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)
    text = (
        "🌌 <b>ANIME CARD WORLD</b>\n"
        "COLLECT • TRADE • PLAY\n\n"
        f"Welcome, <b>{user.first_name}</b>!\n"
        "Choose a destination below."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=menu_keyboard())
    else:
        await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=menu_keyboard())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_menu(update, context)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 <b>COMMANDS</b>\n"
        "/start - Main menu\n/profile - Profile\n/balance - Balance\n"
        "/catch - Catch dropped card\n/collection - Your cards\n"
        "/w CARD_ID - Card details\n/shop - Card shop\n/buy CARD_ID - Buy card\n"
        "/daily - Daily reward\n/rank - Ranking\n/games - Mini games\n"
        "/auction CARD_ID PRICE HOURS - List a card\n/auctions - Open auctions\n"
        "/bid AUCTION_ID AMOUNT - Place a bid\n"
        "/myauctions - Your auctions\n\n"
        "Group drops happen after every 100 regular messages."
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ensure_user(u)
    data = user_data(u.id)
    count = collection_count(u.id)
    level, nxt = player_level(count)
    progress = f"{count}/{nxt}" if nxt else f"{count}/MAX"
    await update.effective_message.reply_text(
        f"👤 <b>{u.first_name}</b>\n"
        f"🏅 Level: <b>{level}</b>\n🎴 Cards: <b>{count}</b>\n"
        f"📈 Next level: <b>{progress}</b>\n{CURRENCY} Balance: <b>{data['balance']:,}</b>",
        parse_mode="HTML"
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_user(update.effective_user)
    d = user_data(update.effective_user.id)
    await update.effective_message.reply_text(f"{CURRENCY} Balance: <b>{d['balance']:,}</b>", parse_mode="HTML")

async def show_collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(update.effective_user)
    with db() as c:
        rows = c.execute(
            "SELECT cards.card_id,cards.name,cards.rarity,inventory.quantity "
            "FROM inventory JOIN cards USING(card_id) WHERE inventory.user_id=? ORDER BY cards.card_id DESC LIMIT 30",
            (uid,)
        ).fetchall()
    if not rows:
        await update.effective_message.reply_text("📚 Your collection is empty. Catch a card in a group!")
        return
    lines = ["📚 <b>MY COLLECTION</b>"]
    for r in rows:
        lines.append(f"#{r['card_id']} • {r['name']} — {r['rarity']} ×{r['quantity']}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")

async def card_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args and update.effective_message and update.effective_message.text:
        raw = update.effective_message.text.strip()
        raw = re.sub(r"^(?:/w(?:@\\w+)?|\\.w)\\s*", "", raw, flags=re.IGNORECASE)
        args = raw.split() if raw else []
    if not args:
        await update.effective_message.reply_text("အသုံးပြုပုံ: /w CARD_ID (သို့) /w Card Name")
        return
    query = " ".join(args).strip()
    with db() as c:
        if query.isdigit():
            row = c.execute("SELECT * FROM cards WHERE card_id=? AND active=1", (int(query),)).fetchone()
        else:
            row = c.execute("SELECT * FROM cards WHERE active=1 AND lower(name) LIKE ? LIMIT 1", (f"%{query.lower()}%",)).fetchone()
    if not row:
        await update.effective_message.reply_text("ဒီကဒ်ကို မတွေ့ပါဘူး။")
        return
    await update.effective_message.reply_photo(
        row["file_id"],
        caption=f"🎴 <b>{row['name']}</b>\n🆔 ID: <code>{row['card_id']}</code>\n"
                f"✨ Rarity: {row['rarity']}\n{CURRENCY} Price: {row['price']:,}",
        parse_mode="HTML"
    )

async def catch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    uid = update.effective_user.id
    ensure_user(update.effective_user)
    if chat.type == "private":
        await update.effective_message.reply_text("ကဒ်ဖမ်းဖို့ Card Drop ဖြစ်နေတဲ့ GP ထဲမှာ /catch ကိုနှိပ်ပါ။")
        return
    with db() as c:
        drop = c.execute("SELECT card_id FROM drops WHERE chat_id=?", (chat.id,)).fetchone()
        if not drop:
            await update.effective_message.reply_text("လက်ရှိ ကဒ်မကျသေးပါဘူး။ GP မှာ စာတွေပြောပြီး Drop ကိုစောင့်ပါ။")
            return
        card = c.execute("SELECT * FROM cards WHERE card_id=? AND active=1", (drop["card_id"],)).fetchone()
        if not card:
            c.execute("DELETE FROM drops WHERE chat_id=?", (chat.id,))
            await update.effective_message.reply_text("ဒီ Drop ကဒ် မရှိတော့ပါဘူး။")
            return
        c.execute(
            "INSERT INTO inventory(user_id,card_id,quantity) VALUES(?,?,1) "
            "ON CONFLICT(user_id,card_id) DO UPDATE SET quantity=quantity+1",
            (uid, card["card_id"])
        )
        c.execute("DELETE FROM drops WHERE chat_id=?", (chat.id,))
    await update.effective_message.reply_text(
        f"🎉 <b>{update.effective_user.first_name}</b> caught a card!\n"
        f"🎴 {card['name']} • {card['rarity']} • ID #{card['card_id']}",
        parse_mode="HTML"
    )

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as c:
        rows = c.execute("SELECT * FROM cards WHERE active=1 ORDER BY price,card_id DESC LIMIT 20").fetchall()
    if not rows:
        await update.effective_message.reply_text("🛒 Shop မှာ ကဒ်မရှိသေးပါဘူး။")
        return
    lines = ["🛒 <b>CARD SHOP</b>"]
    for r in rows:
        lines.append(f"#{r['card_id']} {r['name']} • {r['rarity']} • {CURRENCY}{r['price']:,}  (/buy {r['card_id']})")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("အသုံးပြုပုံ: /buy CARD_ID")
        return
    uid = update.effective_user.id
    cid = int(context.args[0])
    with db() as c:
        card = c.execute("SELECT * FROM cards WHERE card_id=? AND active=1", (cid,)).fetchone()
        user = c.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
        if not card or not user:
            await update.effective_message.reply_text("ကဒ် သို့မဟုတ် User မတွေ့ပါဘူး။")
            return
        if user["balance"] < card["price"]:
            await update.effective_message.reply_text("💵 ငွေမလုံလောက်ပါဘူး။")
            return
        c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (card["price"], uid))
        c.execute("INSERT INTO inventory(user_id,card_id,quantity) VALUES(?,?,1) ON CONFLICT(user_id,card_id) DO UPDATE SET quantity=quantity+1", (uid,cid))
    await update.effective_message.reply_text(f"✅ {card['name']} ကို ဝယ်ယူပြီးပါပြီ။")

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ensure_user(update.effective_user)
    today = datetime.now(timezone.utc).date().isoformat()
    reward = 500
    with db() as c:
        row = c.execute("SELECT last_daily FROM users WHERE user_id=?", (uid,)).fetchone()
        if row["last_daily"] == today:
            await update.effective_message.reply_text("🎁 ဒီနေ့ Daily Reward ယူပြီးပါပြီ။")
            return
        c.execute("UPDATE users SET balance=balance+?, last_daily=? WHERE user_id=?", (reward,today,uid))
    await update.effective_message.reply_text(f"🎁 Daily Reward ရပါပြီ။ +{CURRENCY}{reward:,}")

async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as c:
        rows = c.execute(
            "SELECT users.user_id,users.first_name,COALESCE(SUM(inventory.quantity),0) total "
            "FROM users LEFT JOIN inventory USING(user_id) GROUP BY users.user_id "
            "ORDER BY total DESC LIMIT 10"
        ).fetchall()
    lines = ["🏆 <b>TOP COLLECTORS</b>"]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. {r['first_name']} — 🎴 {r['total']}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")

async def game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = random.randint(1, 5)
    context.user_data["guess_number"] = n
    await update.effective_message.reply_text("🎮 Number Guess!\n1 ကနေ 5 အတွင်း နံပါတ်တစ်ခု ရွေးပါ။ /guess NUMBER")

async def guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("အသုံးပြုပုံ: /guess 1-5")
        return
    target = context.user_data.get("guess_number")
    if target is None:
        await update.effective_message.reply_text("/games နဲ့ အရင်စပါ။")
        return
    if int(context.args[0]) == target:
        with db() as c:
            c.execute("UPDATE users SET balance=balance+200 WHERE user_id=?", (update.effective_user.id,))
        await update.effective_message.reply_text(f"🎉 မှန်ပါတယ်။ +{CURRENCY}200")
    else:
        await update.effective_message.reply_text("မမှန်သေးဘူး။ နောက်တစ်ခါ စမ်းပါ။")
    context.user_data.pop("guess_number", None)

async def addcard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    msg = update.effective_message
    if not msg.photo:
        await msg.reply_text("ကဒ်ပုံကို caption နဲ့အတူ ပို့ပါ:\n/addcard Name | Rarity | Price")
        return
    caption = msg.caption or ""
    raw = caption.replace("/addcard", "", 1).strip()
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 3 or not parts[2].isdigit():
        await msg.reply_text("Format: /addcard Name | Rarity | Price")
        return
    name, rarity, price = parts[0], parts[1], int(parts[2])
    if rarity.lower() not in [r[0].lower() for r in RARITIES]:
        await msg.reply_text("Rarity မမှန်ပါ။ Common မှ Secret အထိ 11 ဆင့်ထဲက ရွေးပါ။")
        return
    file_id = msg.photo[-1].file_id
    with db() as c:
        cur = c.execute("INSERT INTO cards(name,rarity,price,file_id) VALUES(?,?,?,?)", (name,rarity,price,file_id))
        cid = cur.lastrowid
    await msg.reply_text(f"✅ Card Added!\nID: {cid}\nName: {name}\nRarity: {rarity}")

async def drop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("အသုံးပြုပုံ: /drop CARD_ID")
        return
    cid = int(context.args[0])
    card = card_data(cid)
    if not card:
        await update.effective_message.reply_text("Card ID မတွေ့ပါဘူး။")
        return
    with db() as c:
        c.execute("INSERT INTO drops(chat_id,card_id,created_at) VALUES(?,?,?) ON CONFLICT(chat_id) DO UPDATE SET card_id=excluded.card_id,created_at=excluded.created_at",
                  (update.effective_chat.id,cid,datetime.now(timezone.utc).isoformat()))
        c.execute("UPDATE groups_data SET message_count=0 WHERE chat_id=?", (update.effective_chat.id,))
    await update.effective_message.reply_photo(card["file_id"], caption=f"🎴 CARD DROP!\n{card['name']} • {card['rarity']}\n/catch to collect!")

async def group_message_counter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or chat.type not in ("group", "supergroup") or not msg.text:
        return
    if msg.text.startswith("/"):
        return
    with db() as c:
        c.execute("INSERT INTO groups_data(chat_id,message_count) VALUES(?,1) ON CONFLICT(chat_id) DO UPDATE SET message_count=message_count+1", (chat.id,))
        row = c.execute("SELECT message_count FROM groups_data WHERE chat_id=?", (chat.id,)).fetchone()
        count = int(row["message_count"])
        pending = c.execute("SELECT 1 FROM drops WHERE chat_id=?", (chat.id,)).fetchone()
        if count >= DROP_EVERY and not pending:
            cards = c.execute("SELECT * FROM cards WHERE active=1").fetchall()
            if cards:
                chosen = random.choice(cards)
                c.execute("INSERT INTO drops(chat_id,card_id,created_at) VALUES(?,?,?)", (chat.id,chosen["card_id"],datetime.now(timezone.utc).isoformat()))
                c.execute("UPDATE groups_data SET message_count=0 WHERE chat_id=?", (chat.id,))
                await msg.reply_photo(chosen["file_id"], caption=f"✨ A NEW CARD HAS APPEARED!\n🎴 {chosen['name']} • {chosen['rarity']}\nUse /catch to collect it!")

async def auctions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as c:
        rows = c.execute("SELECT * FROM auctions WHERE status='open' ORDER BY ends_at LIMIT 10").fetchall()
    if not rows:
        await update.effective_message.reply_text("⚔️ လက်ရှိ Auction မရှိသေးပါဘူး။")
        return
    lines = ["⚔️ <b>AUCTION HALL</b>"]
    for a in rows:
        card = card_data(a["card_id"])
        if card:
            lines.append(f"#{a['auction_id']} • {card['name']} • Bid {CURRENCY}{a['current_bid']:,} • /bid {a['auction_id']} AMOUNT")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")

async def auction_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 3 or not all(x.isdigit() for x in context.args):
        await update.effective_message.reply_text("အသုံးပြုပုံ: /auction CARD_ID START_PRICE HOURS")
        return
    uid = update.effective_user.id
    cid, price, hours = map(int, context.args)
    if price < 1 or hours not in (1, 6, 12, 24):
        await update.effective_message.reply_text("ဈေးနှုန်းမှန်ရမယ်။ နာရီကို 1/6/12/24 ထဲက ရွေးပါ။")
        return
    ends = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    with db() as c:
        owned = c.execute("SELECT quantity FROM inventory WHERE user_id=? AND card_id=?", (uid,cid)).fetchone()
        if not owned or owned["quantity"] < 1:
            await update.effective_message.reply_text("ဒီကဒ်ကို မပိုင်ဆိုင်ပါဘူး။")
            return
        c.execute("UPDATE inventory SET quantity=quantity-1 WHERE user_id=? AND card_id=?", (uid,cid))
        c.execute("DELETE FROM inventory WHERE user_id=? AND card_id=? AND quantity<=0", (uid,cid))
        cur = c.execute("INSERT INTO auctions(seller_id,card_id,current_bid,ends_at) VALUES(?,?,?,?)", (uid,cid,price,ends))
        aid = cur.lastrowid
    await update.effective_message.reply_text(f"⚔️ Auction #{aid} စတင်ပါပြီ။ /auctions")

async def bid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2 or not all(x.isdigit() for x in context.args):
        await update.effective_message.reply_text("အသုံးပြုပုံ: /bid AUCTION_ID AMOUNT")
        return
    aid, amount = map(int, context.args)
    uid = update.effective_user.id
    with db() as c:
        a = c.execute("SELECT * FROM auctions WHERE auction_id=? AND status='open'", (aid,)).fetchone()
        u = c.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
        if not a or datetime.fromisoformat(a["ends_at"]) <= datetime.now(timezone.utc):
            await update.effective_message.reply_text("Auction ပိတ်သွားပါပြီ။")
            return
        if uid == a["seller_id"] or amount <= a["current_bid"] or not u or u["balance"] < amount:
            await update.effective_message.reply_text("လေလံဈေး၊ ကိုယ့်ကဒ်ကိုယ်လေလံဆွဲခြင်း၊ သို့မဟုတ် Balance ကို စစ်ပါ။")
            return
        if a["highest_bidder"]:
            c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (a["current_bid"],a["highest_bidder"]))
        c.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount,uid))
        c.execute("UPDATE auctions SET current_bid=?,highest_bidder=? WHERE auction_id=?", (amount,uid,aid))
        c.execute("INSERT INTO bids(auction_id,bidder_id,amount) VALUES(?,?,?) ON CONFLICT(auction_id,bidder_id) DO UPDATE SET amount=excluded.amount", (aid,uid,amount))
    await update.effective_message.reply_text(f"✅ Auction #{aid} မှာ {CURRENCY}{amount:,} လေလံတင်ပြီးပါပြီ။")

async def settle_auctions(app: Application):
    while True:
        now = datetime.now(timezone.utc)
        with db() as c:
            rows = c.execute("SELECT * FROM auctions WHERE status='open' AND ends_at<=?", (now.isoformat(),)).fetchall()
            for a in rows:
                if a["highest_bidder"]:
                    c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (a["current_bid"],a["seller_id"]))
                    c.execute("INSERT INTO inventory(user_id,card_id,quantity) VALUES(?,?,1) ON CONFLICT(user_id,card_id) DO UPDATE SET quantity=quantity+1", (a["highest_bidder"],a["card_id"]))
                else:
                    c.execute("INSERT INTO inventory(user_id,card_id,quantity) VALUES(?,?,1) ON CONFLICT(user_id,card_id) DO UPDATE SET quantity=quantity+1", (a["seller_id"],a["card_id"]))
                c.execute("UPDATE auctions SET status='closed' WHERE auction_id=?", (a["auction_id"],))
        await asyncio.sleep(30)

async def set_commands(app: Application):
    commands = [
        BotCommand("start","Main Menu"), BotCommand("profile","My Profile"),
        BotCommand("balance","My Balance"), BotCommand("catch","Catch Card"),
        BotCommand("collection","My Collection"), BotCommand("w","Card Info"),
        BotCommand("shop","Card Shop"), BotCommand("buy","Buy Card"),
        BotCommand("daily","Daily Reward"), BotCommand("rank","Ranking"),
        BotCommand("games","Mini Games"), BotCommand("guess","Guess Game"),
        BotCommand("auction","Create Auction"), BotCommand("auctions","Auction Hall"),
        BotCommand("bid","Place Bid"), BotCommand("help","Help")
    ]
    await app.bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
    await app.bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    action = q.data
    if action == "profile":
        await profile(update, context)
    elif action == "collection":
        await show_collection(update, context)
    elif action == "shop":
        await shop(update, context)
    elif action == "catch":
        await q.message.reply_text("🎴 ကဒ်ဖမ်းဖို့ Drop ဖြစ်နေတဲ့ GP ထဲမှာ /catch ကိုနှိပ်ပါ။")
    elif action == "daily":
        await daily(update, context)
    elif action == "rank":
        await rank(update, context)
    elif action == "game":
        await game(update, context)
    elif action == "auctions":
        await auctions(update, context)
    elif action == "help":
        await q.message.reply_text("အသုံးပြုပုံကြည့်ရန် /help ကိုနှိပ်ပါ။")

async def post_init(app: Application):
    await set_commands(app)
    app.create_task(settle_auctions(app))

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN (or TELEGRAM_BOT_TOKEN) secret is missing.")
    init_db()
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("collection", show_collection))
    app.add_handler(CommandHandler("w", card_info))
    app.add_handler(MessageHandler(filters.Regex(r"^\.w(?:\s|$)"), card_info))
    app.add_handler(CommandHandler("catch", catch))
    app.add_handler(CommandHandler("shop", shop))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(CommandHandler("games", game))
    app.add_handler(CommandHandler("guess", guess))
    app.add_handler(CommandHandler("addcard", addcard))
    app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(r"^/addcard"), addcard))
    app.add_handler(CommandHandler("drop", drop_cmd))
    app.add_handler(CommandHandler("auction", auction_cmd))
    app.add_handler(CommandHandler("auctions", auctions))
    app.add_handler(CommandHandler("bid", bid))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT, group_message_counter), group=10)
    print("ANIME CARD WORLD BOT STARTED")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
      
