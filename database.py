import sqlite3

db = sqlite3.connect("anime_cards.db")
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    money INTEGER DEFAULT 0,
    cards INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS card_collection (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    card_id INTEGER,
    card_name TEXT,
    rarity INTEGER
)
""")

db.commit()
db.close()

print("DATABASE READY!")
