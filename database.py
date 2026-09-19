import os
import psycopg2
from psycopg2.extras import RealDictCursor

# Reads the injected Railway DATABASE_URL, with a fallback for local testing
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/platerate"
)


def get_connection():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    # Users
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        email VARCHAR(255) UNIQUE NOT NULL
    );
    """)

    # Plates
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

    # Likes & Saves
    c.execute("""
    CREATE TABLE IF NOT EXISTS interactions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        plate_id INTEGER NOT NULL REFERENCES plates(id) ON DELETE CASCADE,
        type VARCHAR(20) NOT NULL,
        UNIQUE(user_id, plate_id, type)
    );
    """)

    # Comments
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
    print("[Postgres] Database tables checked/initialized successfully.")


if __name__ == "__main__":
    init_db()