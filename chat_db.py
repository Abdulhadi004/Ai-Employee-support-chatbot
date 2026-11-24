
import sqlite3

from pathlib import Path
from datetime import datetime, timezone


# ========================================
# DATABASE CONFIGURATION
# ========================================

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / "chat_history.db"


# ========================================
# DATABASE CONNECTION
# ========================================

def get_chat_db():

    connection = sqlite3.connect(DB_PATH)

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON")

    return connection


# ========================================
# INITIALIZE DATABASE
# ========================================

def initialize_chat_database():

    connection = get_chat_db()

    try:

        # Conversations table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS conversations (

                id TEXT PRIMARY KEY,

                user_id INTEGER NOT NULL,

                title TEXT NOT NULL,

                created_at TEXT NOT NULL,

                updated_at TEXT NOT NULL

            )
        """)

        # Messages table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS messages (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                conversation_id TEXT NOT NULL,

                role TEXT NOT NULL
                    CHECK(role IN ('user', 'assistant')),

                content TEXT NOT NULL,

                category TEXT,

                created_at TEXT NOT NULL,

                FOREIGN KEY (conversation_id)
                    REFERENCES conversations(id)
                    ON DELETE CASCADE

            )
        """)

        # Improve conversation lookup performance
        connection.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_conversations_user
            ON conversations(user_id)
        """)

        # Improve message lookup performance
        connection.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_messages_conversation
            ON messages(conversation_id)
        """)

        connection.commit()

        print("Chat history database initialized successfully.")

    finally:

        connection.close()


# ========================================
# CREATE CONVERSATION
# ========================================

def create_conversation(user_id, conversation_id, title):

    connection = get_chat_db()

    now = datetime.now(timezone.utc).isoformat()

    try:

        connection.execute("""
            INSERT INTO conversations (
                id,
                user_id,
                title,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            conversation_id,
            user_id,
            title[:100],
            now,
            now
        ))

        connection.commit()

    finally:

        connection.close()


# ========================================
# VERIFY CONVERSATION OWNERSHIP
# ========================================

def get_user_conversation(user_id, conversation_id):

    connection = get_chat_db()

    try:

        conversation = connection.execute("""
            SELECT *
            FROM conversations
            WHERE id = ? AND user_id = ?
        """, (
            conversation_id,
            user_id
        )).fetchone()

        return dict(conversation) if conversation else None

    finally:

        connection.close()


# ========================================
# SAVE MESSAGE
# ========================================

def save_message(
    conversation_id,
    role,
    content,
    category=None
):

    connection = get_chat_db()

    now = datetime.now(timezone.utc).isoformat()

    try:

        connection.execute("""
            INSERT INTO messages (
                conversation_id,
                role,
                content,
                category,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, (
            conversation_id,
            role,
            content,
            category,
            now
        ))

        connection.execute("""
            UPDATE conversations
            SET updated_at = ?
            WHERE id = ?
        """, (
            now,
            conversation_id
        ))

        connection.commit()

    finally:

        connection.close()


# ========================================
# GET ALL USER CONVERSATIONS
# ========================================

def get_user_conversations(user_id):

    connection = get_chat_db()

    try:

        conversations = connection.execute("""
            SELECT *
            FROM conversations
            WHERE user_id = ?
            ORDER BY updated_at DESC
        """, (user_id,)).fetchall()

        return [dict(row) for row in conversations]

    finally:

        connection.close()


# ========================================
# GET CONVERSATION MESSAGES
# ========================================

def get_conversation_messages(user_id, conversation_id):

    connection = get_chat_db()

    try:

        # Verify ownership first
        conversation = connection.execute("""
            SELECT id
            FROM conversations
            WHERE id = ? AND user_id = ?
        """, (
            conversation_id,
            user_id
        )).fetchone()

        if not conversation:
            return None

        messages = connection.execute("""
            SELECT *
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
        """, (conversation_id,)).fetchall()

        return [dict(row) for row in messages]

    finally:

        connection.close()


# ========================================
# DELETE CONVERSATION
# ========================================

def delete_conversation(user_id, conversation_id):

    connection = get_chat_db()

    try:

        cursor = connection.execute("""
            DELETE FROM conversations
            WHERE id = ? AND user_id = ?
        """, (
            conversation_id,
            user_id
        ))

        connection.commit()

        return cursor.rowcount > 0

    finally:

        connection.close()


# ========================================
# INITIALIZE DATABASE ON IMPORT
# ========================================

initialize_chat_database()
