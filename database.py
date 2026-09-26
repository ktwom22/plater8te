import os
import time
import psycopg2
from psycopg2.extras import RealDictCursor

# Fallback directly to your public Railway database URL
DATABASE_URL = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:mipHSVDCfYqNNFtvJGcNknSQFHHSuFtP@maglev.proxy.rlwy.net:17278/railway"
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

    # Users Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(100) UNIQUE NOT NULL,
        email VARCHAR(255) UNIQUE NOT NULL,
        password_hash VARCHAR(255)
    );
    """)

    # Shared Restaurants Registry
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

    # Plates Table
    c.execute("""
    CREATE TABLE IF NOT EXISTS plates (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
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

    # Interactions Table
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
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        plate_id INTEGER NOT NULL REFERENCES plates(id) ON DELETE CASCADE,
        comment TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Plate Duels
    c.execute("""
    CREATE TABLE IF NOT EXISTS duels (
        id SERIAL PRIMARY KEY,
        title VARCHAR(255) NOT NULL,
        plate_a_id INTEGER REFERENCES plates(id) ON DELETE CASCADE,
        plate_b_id INTEGER REFERENCES plates(id) ON DELETE CASCADE,
        votes_a INTEGER DEFAULT 0,
        votes_b INTEGER DEFAULT 0,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Duel Votes
    c.execute("""
    CREATE TABLE IF NOT EXISTS duel_votes (
        id SERIAL PRIMARY KEY,
        duel_id INTEGER REFERENCES duels(id) ON DELETE CASCADE,
        voter_token VARCHAR(255) NOT NULL,
        choice VARCHAR(1) NOT NULL,
        UNIQUE(duel_id, voter_token)
    );
    """)

    # Plate Trails / Hit Lists
    c.execute("""
    CREATE TABLE IF NOT EXISTS trails (
        id SERIAL PRIMARY KEY,
        title VARCHAR(255) NOT NULL,
        slug VARCHAR(100) UNIQUE NOT NULL,
        description TEXT,
        badge_reward VARCHAR(100) DEFAULT 'Trailblazer 🥾',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS trail_items (
        id SERIAL PRIMARY KEY,
        trail_id INTEGER REFERENCES trails(id) ON DELETE CASCADE,
        plate_id INTEGER REFERENCES plates(id) ON DELETE CASCADE,
        order_index INTEGER DEFAULT 0,
        UNIQUE(trail_id, plate_id)
    );
    """)

    # Safe Migrations
    c.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='plates' AND column_name='user_id' AND is_nullable='NO'
            ) THEN
                ALTER TABLE plates ALTER COLUMN user_id DROP NOT NULL;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name='comments' AND column_name='user_id' AND is_nullable='NO'
            ) THEN
                ALTER TABLE comments ALTER COLUMN user_id DROP NOT NULL;
            END IF;
        END $$;
    """)

    conn.commit()
    c.close()
    conn.close()
    print("[Postgres] Database initialized with growth engines (Duels, Trails, Anonymous, Registry).")


if __name__ == "__main__":
    init_db()