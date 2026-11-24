
import sqlite3
from pathlib import Path
from datetime import datetime, timezone


# Database location
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "user_memory.db"


# Connect to database
def get_memory_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


# Create memory table
def initialize_memory_database():

    connection = get_memory_db()

    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS user_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                memory_key TEXT NOT NULL,
                memory_value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                UNIQUE(user_id, memory_key)
            )
        """)

        connection.commit()

        print("User memory database initialized successfully.")

    finally:
        connection.close()


# Save or update a user's memory
def save_user_memory(user_id, memory_key, memory_value):

    connection = get_memory_db()

    now = datetime.now(timezone.utc).isoformat()

    try:
        connection.execute("""
            INSERT INTO user_memories (
                user_id,
                memory_key,
                memory_value,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)

            ON CONFLICT(user_id, memory_key)
            DO UPDATE SET
                memory_value = excluded.memory_value,
                updated_at = excluded.updated_at
        """, (
            user_id,
            memory_key,
            memory_value,
            now,
            now
        ))

        connection.commit()

        return True

    finally:
        connection.close()


# Retrieve all memories of a user
def get_user_memories(user_id):

    connection = get_memory_db()

    try:
        memories = connection.execute("""
            SELECT memory_key, memory_value
            FROM user_memories
            WHERE user_id = ?
            ORDER BY memory_key
        """, (user_id,)).fetchall()

        return [dict(memory) for memory in memories]

    finally:
        connection.close()


# Retrieve one specific memory
def get_user_memory(user_id, memory_key):

    connection = get_memory_db()

    try:
        memory = connection.execute("""
            SELECT memory_value
            FROM user_memories
            WHERE user_id = ? AND memory_key = ?
        """, (user_id, memory_key)).fetchone()

        return memory["memory_value"] if memory else None

    finally:
        connection.close()


# Delete one memory
def delete_user_memory(user_id, memory_key):

    connection = get_memory_db()

    try:
        cursor = connection.execute("""
            DELETE FROM user_memories
            WHERE user_id = ? AND memory_key = ?
        """, (user_id, memory_key))

        connection.commit()

        return cursor.rowcount > 0

    finally:
        connection.close()


# Delete all memories of a user
def delete_all_user_memories(user_id):

    connection = get_memory_db()

    try:
        cursor = connection.execute("""
            DELETE FROM user_memories
            WHERE user_id = ?
        """, (user_id,))

        connection.commit()

        return cursor.rowcount

    finally:
        connection.close()


# Initialize database when this module is imported
initialize_memory_database()
