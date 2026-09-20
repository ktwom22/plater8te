import os
import time
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/platerate"
)


def get_connection(retries=5, delay=2):
    for attempt in range(retries):
        try:
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            return conn
        except psycopg2.OperationalError as e:
            if attempt < retries - 1:
                print(f"[!] Database retry {attempt + 1}/{retries}...")
                time.sleep(delay)
            else:
                raise e


def init_db():
    conn = get_connection()
    c = conn.cursor()

    # Users
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        email VARCHAR(255) UNIQUE NOT NULL,
        password_hash VARCHAR(255)
    );
    """)

    # Shared Restaurants Registry (Custom and Cached Spots)
    c.execute("""
    CREATE TABLE IF NOT EXISTS restaurants (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        address TEXT,
        website TEXT,
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(name, address)
    );
    """)

    # Plates
    c.execute("""
    CREATE TABLE IF NOT EXISTS plates (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        restaurant_id INTEGER REFERENCES restaurants(id) ON DELETE SET NULL,
        dish_name VARCHAR(255) NOT NULL,
        restaurant VARCHAR(255) NOT NULL,
        restaurant_address TEXT,
        restaurant_website TEXT,
        category VARCHAR(100),
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        photo_url TEXT,
        rating INTEGER DEFAULT NULL,
        reorder VARCHAR(50) DEFAULT NULL,
        is_sponsored INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Safe Migrations
    c.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='plates' AND column_name='category'
            ) THEN
                ALTER TABLE plates ADD COLUMN category VARCHAR(100);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='plates' AND column_name='restaurant_id'
            ) THEN
                ALTER TABLE plates ADD COLUMN restaurant_id INTEGER REFERENCES restaurants(id) ON DELETE SET NULL;
            END IF;
        END $$;
    """)

    # Interactions
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
    print("[Postgres] Database initialized with shared restaurants registry.")


if __name__ == "__main__":
    init_db()