import sqlite3, os

DB_PATH = os.getenv("DB_PATH", "parking.db")

# Vom Admin änderbar (PUT /api/admin/settings)
DEFAULTS = {
    "free_minutes": "60",             # kostenlose / maximale Parkdauer
    "rate_cents_per_hour": "200",     # Gebühr pro angefangener Stunde nach free_minutes
    "fine_mode": "on_overstay",       # off | on_overstay (sofort) | on_exit (erst bei Ausfahrt)
    "fine_cents": "3000",
    "currency": "EUR",
    "operator_name": "Parkplatz Betreiber",
    "operator_address": "Musterstrasse 1, 53111 Bonn",
}

def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS whitelist(plate TEXT PRIMARY KEY, note TEXT);
        CREATE TABLE IF NOT EXISTS sessions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plate TEXT, entry_ts INTEGER, exit_ts INTEGER,
            status TEXT DEFAULT 'open',          -- open | closed
            paid_hours INTEGER DEFAULT 0,
            fine_waived INTEGER DEFAULT 0,
            entry_image TEXT);
        CREATE TABLE IF NOT EXISTS fines(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER, plate TEXT, amount_cents INTEGER,
            created_ts INTEGER, paid_ts INTEGER, voided INTEGER DEFAULT 0,
            pdf_path TEXT);
        CREATE TABLE IF NOT EXISTS payments(
            ref TEXT PRIMARY KEY, plate TEXT, session_id INTEGER,
            hours INTEGER, fine_ids TEXT, amount_cents INTEGER,
            method TEXT, status TEXT DEFAULT 'pending', provider_id TEXT);
        """)
        for k, v in DEFAULTS.items():
            c.execute("INSERT OR IGNORE INTO settings VALUES(?,?)", (k, v))

def settings():
    with conn() as c:
        return {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}
