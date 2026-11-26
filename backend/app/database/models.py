"""Every table the app uses. SQLite keeps each record as JSON text next to the keys it is looked up by."""

# trips (checkpoints), mock bookings, cached AI replies, daily call counters, and the toolkit's records
PLANNER_TABLES = """
CREATE TABLE IF NOT EXISTS checkpoints(thread_id TEXT PRIMARY KEY, state TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bookings(idempotency_key TEXT PRIMARY KEY, thread_id TEXT, booking TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS llm_cache(key TEXT PRIMARY KEY, value TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS counters(name TEXT, day TEXT, n INTEGER NOT NULL, PRIMARY KEY(name, day));
CREATE TABLE IF NOT EXISTS trip_items(thread_id TEXT NOT NULL, kind TEXT NOT NULL, item_id TEXT NOT NULL,
    data TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY(thread_id, kind, item_id));
"""

# optional local accounts
ACCOUNT_TABLES = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, salt TEXT NOT NULL,
    pw TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS user_memory(user_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS user_trips(thread_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
    summary TEXT NOT NULL, updated TEXT NOT NULL);
"""
