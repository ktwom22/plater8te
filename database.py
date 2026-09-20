import os
import time
import psycopg2
from psycopg2.extras import RealDictCursor

# Reads the injected Railway DATABASE_PUBLIC_URL or DATABASE_URL
DATABASE_URL = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/platerate"
)


def get_connection(retries=5, delay=2):
    """Establishes a connection with automatic retry for startup delays."""
    for attempt in range(retries):
        try:
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            return conn
        except psycopg2.OperationalError as e:
            if attempt < retries - 1:
                print(f"[!] Database connection failed (attempt {attempt + 1}/{retries}). Retrying in {delay}s...")
                time.sleep(delay)
            else:
                raise e


def init_db():
    conn = get_connection()
    c = conn.cursor()

    # Users Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        email VARCHAR(255) UNIQUE NOT NULL,
        password_hash VARCHAR(255)
    );
    """)

    # Safe migration: Add password_hash column if the table already existed without it
    c.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='users' AND column_name='password_hash'
            ) THEN
                ALTER TABLE users ADD COLUMN password_hash VARCHAR(255);
            END IF;
        END $$;
    """)

    # Plates Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS plates (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        dish_name VARCHAR(255) NOT NULL,
        restaurant VARCHAR(255) NOT NULL,
        restaurant_address TEXT,
        restaurant_website TEXT,
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        photo_url TEXT,
        rating INTEGER DEFAULT NULL,
        reorder VARCHAR(50) DEFAULT NULL,
        is_sponsored INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Interactions Table (Likes & Saves)
    c.execute("""
    CREATE TABLE IF NOT EXISTS interactions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        plate_id INTEGER NOT NULL REFERENCES plates(id) ON DELETE CASCADE,
        type VARCHAR(20) NOT NULL,
        UNIQUE(user_id, plate_id, type)
    );
    """)

    # Comments Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS comments (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        plate_id INTEGER NOT NULL REFERENCES plates(id) ON DELETE CASCADE,
        comment TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    c.close()
    conn.close()
    print("[Postgres] Database initialized with password support.")


if __name__ == "__main__":
    init_db()