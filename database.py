import sqlite3

def init_db():
    with sqlite3.connect('bot.db') as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS mail_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER,
            account_id TEXT,
            address TEXT,
            password TEXT
        )''')

def add_account(tg_id, acc_id, address, password):
    with sqlite3.connect('bot.db') as conn:
        conn.execute("INSERT INTO mail_accounts (tg_id, account_id, address, password) VALUES (?, ?, ?, ?)",
                     (tg_id, acc_id, address, password))

def get_user_accounts(tg_id):
    with sqlite3.connect('bot.db') as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM mail_accounts WHERE tg_id = ?", (tg_id,)).fetchall()

def delete_account_from_db(account_id):
    with sqlite3.connect('bot.db') as conn:
        conn.execute("DELETE FROM mail_accounts WHERE account_id = ?", (account_id,))

def get_account_by_id(account_id):
    with sqlite3.connect('bot.db') as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM mail_accounts WHERE account_id = ?", (account_id,)).fetchone()