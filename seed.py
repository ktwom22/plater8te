"""
seed.py - Seeds users, restaurants, plates, duels, and trails.
Run: python seed.py
"""
import os
import psycopg2
from argon2 import PasswordHasher
from database import get_connection

ph = PasswordHasher()

SAMPLE_USERS = [
    {"username": "chef_marcus", "email": "marcus@platerate.com", "password": "password123"},
    {"username": "sarah_eats", "email": "sarah@platerate.com", "password": "password123"},
    {"username": "local_critic", "email": "critic@platerate.com", "password": "password123"},
]

SAMPLE_RESTAURANTS = [
    {
        "name": "Bad Brgr",
        "address": "17 N Main St, Rochester, NH 03867",
        "website": "https://www.badbrgr.com",
        "latitude": 43.3045,
        "longitude": -70.9756
    },
    {
        "name": "La Festa Brick & Brew",
        "address": "300 Central Ave, Dover, NH 03820",
        "website": "https://www.lafestabrickandbrew.com",
        "latitude": 43.1979,
        "longitude": -70.8737
    },
    {
        "name": "Smokey's Greater BBQ",
        "address": "215 Portland St, Rochester, NH 03867",
        "website": "https://www.smokeysgreaterbbq.com",
        "latitude": 43.3089,
        "longitude": -70.9621
    },
    {
        "name": "Tulsi Indian Restaurant",
        "address": "20 Main St, Kittery, ME 03904",
        "website": "https://www.tulsirestaurant.com",
        "latitude": 43.0886,
        "longitude": -70.7388
    },
    {
        "name": "Lexie's Joint",
        "address": "212 Islington St, Portsmouth, NH 03801",
        "website": "https://www.peaceloveburgers.com",
        "latitude": 43.0729,
        "longitude": -70.7656
    }
]

SAMPLE_PLATES = [
    {
        "author_index": 0,
        "rest_index": 0,
        "dish_name": "Truffle Smash Burger",
        "category": "Burgers",
        "rating": 10,
        "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?auto=format&fit=crop&w=800&q=80",
        "comments": ["Crust on the beef patties was immaculate.", "Best smash burger on the Seacoast hands down."]
    },
    {
        "author_index": 1,
        "rest_index": 4,
        "dish_name": "Crispy Bistro Fried Chicken Sandwich",
        "category": "Burgers",
        "rating": 9,
        "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1625813506062-0aeb1d7a094b?auto=format&fit=crop&w=800&q=80",
        "comments": ["Spicy mayo has a nice kick, incredibly crispy."]
    },
    {
        "author_index": 1,
        "rest_index": 1,
        "dish_name": "Hot Honey Pepperoni Brick-Oven Slice",
        "category": "Pizza",
        "rating": 9,
        "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1513104890138-7c749659a591?auto=format&fit=crop&w=800&q=80",
        "comments": ["Crispy undercarriage and real hot honey drizzle."]
    },
    {
        "author_index": 2,
        "rest_index": 2,
        "dish_name": "Dry-Rubbed Smoked Brisket Plate",
        "category": "BBQ & Meat",
        "rating": 9,
        "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1529193591184-b1d58069ecdd?auto=format&fit=crop&w=800&q=80",
        "comments": ["Bark was unreal, nice smoke ring."]
    },
    {
        "author_index": 0,
        "rest_index": 3,
        "dish_name": "Chicken Tikka Masala & Garlic Naan",
        "category": "Asian & Noodles",
        "rating": 9,
        "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1588166524941-3bf61a9c41db?auto=format&fit=crop&w=800&q=80",
        "comments": ["Rich sauce, perfectly pillowy naan."]
    }
]


def run_seed():
    conn = get_connection()
    c = conn.cursor()

    print("[*] Seeding users...")
    user_ids = []
    for u in SAMPLE_USERS:
        pwd_hash = ph.hash(u["password"])
        c.execute("""
            INSERT INTO users (username, email, password_hash)
            VALUES (%s, %s, %s)
            ON CONFLICT (username) DO UPDATE SET email = EXCLUDED.email
            RETURNING id
        """, (u["username"], u["email"], pwd_hash))
        user_ids.append(c.fetchone()["id"])

    print("[*] Seeding restaurants...")
    rest_ids = []
    for r in SAMPLE_RESTAURANTS:
        c.execute("""
            INSERT INTO restaurants (name, address, website, latitude, longitude, created_by_user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (name, address) DO UPDATE 
            SET website = EXCLUDED.website, latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude
            RETURNING id
        """, (r["name"], r["address"], r["website"], r["latitude"], r["longitude"], user_ids[0]))
        rest_ids.append(c.fetchone()["id"])

    print("[*] Seeding plates...")
    plate_ids = []
    for p in SAMPLE_PLATES:
        author_id = user_ids[p["author_index"]] if p["author_index"] is not None else None
        rest = SAMPLE_RESTAURANTS[p["rest_index"]]
        rest_id = rest_ids[p["rest_index"]]

        c.execute("SELECT id FROM plates WHERE dish_name = %s AND restaurant = %s", (p["dish_name"], rest["name"]))
        existing = c.fetchone()

        if existing:
            plate_ids.append(existing["id"])
        else:
            c.execute("""
                INSERT INTO plates (
                    user_id, restaurant_id, dish_name, restaurant, category, 
                    restaurant_address, restaurant_website, latitude, longitude, 
                    photo_url, rating, reorder
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                author_id, rest_id, p["dish_name"], rest["name"], p["category"],
                rest["address"], rest["website"], rest["latitude"], rest["longitude"],
                p["photo_url"], p["rating"], p["reorder"]
            ))
            pid = c.fetchone()["id"]
            plate_ids.append(pid)

            for comment_text in p["comments"]:
                c.execute("INSERT INTO comments (user_id, plate_id, comment) VALUES (%s, %s, %s)", (author_id, pid, comment_text))

    print("[*] Seeding Plate Duel of the Week...")
    if len(plate_ids) >= 2:
        c.execute("SELECT id FROM duels WHERE is_active = TRUE")
        if not c.fetchone():
            c.execute("""
                INSERT INTO duels (title, plate_a_id, plate_b_id, votes_a, votes_b, is_active)
                VALUES (%s, %s, %s, 14, 11, TRUE)
            """, ("Smash Burger Clash: Bad Brgr vs. Lexie's Joint", plate_ids[0], plate_ids[1]))

    print("[*] Seeding Foodie Trails...")
    c.execute("SELECT id FROM trails WHERE slug = 'seacoast-burger-trail'")
    if not c.fetchone():
        c.execute("""
            INSERT INTO trails (title, slug, description, badge_reward)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (
            "The Seacoast Smash Tour",
            "seacoast-burger-trail",
            "Conquer the 3 most iconic independent smash burgers across Rochester and Portsmouth.",
            "Burger Baron 🍔"
        ))
        trail_id = c.fetchone()["id"]
        c.execute("INSERT INTO trail_items (trail_id, plate_id, order_index) VALUES (%s, %s, 1)", (trail_id, plate_ids[0]))
        c.execute("INSERT INTO trail_items (trail_id, plate_id, order_index) VALUES (%s, %s, 2)", (trail_id, plate_ids[1]))

    conn.commit()
    c.close()
    conn.close()
    print("[✓] All 5 growth engines seeded successfully.")


if __name__ == "__main__":
    run_seed()