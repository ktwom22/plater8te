"""
seed.py - Seeds national plates with accurate dish imagery and verified spots.
Run: python seed.py
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from argon2 import PasswordHasher
from database import init_db, get_connection

ph = PasswordHasher()

SAMPLE_USERS = [
    {"username": "chef_marcus", "email": "marcus@platerate.com", "password": "password123"},
    {"username": "sarah_eats", "email": "sarah@platerate.com", "password": "password123"},
    {"username": "local_critic", "email": "critic@platerate.com", "password": "password123"},
    {"username": "austin_pitmaster", "email": "austin@platerate.com", "password": "password123"},
    {"username": "nyc_foodie", "email": "nyc@platerate.com", "password": "password123"}
]

SAMPLE_RESTAURANTS = [
    # NH / ME Local
    {
        "name": "Bad Brgr",
        "address": "17 N Main St, Rochester, NH 03867",
        "website": "https://www.badbrgr.com",
        "latitude": 43.3045, "longitude": -70.9756
    },
    {
        "name": "Lexie's Joint",
        "address": "212 Islington St, Portsmouth, NH 03801",
        "website": "https://www.peaceloveburgers.com",
        "latitude": 43.0729, "longitude": -70.7656
    },
    {
        "name": "La Festa Brick & Brew",
        "address": "300 Central Ave, Dover, NH 03820",
        "website": "https://www.lafestabrickandbrew.com",
        "latitude": 43.1979, "longitude": -70.8737
    },
    # Portland, ME
    {
        "name": "Eventide Oyster Co.",
        "address": "86 Middle St, Portland, ME 04101",
        "website": "https://www.eventideoysterco.com",
        "latitude": 43.6593, "longitude": -70.2520
    },
    {
        "name": "Duckfat",
        "address": "43 Middle St, Portland, ME 04101",
        "website": "https://duckfat.com",
        "latitude": 43.6586, "longitude": -70.2505
    },
    # Boston, MA
    {
        "name": "Regina Pizzeria",
        "address": "11 1/2 Thacher St, Boston, MA 02113",
        "website": "https://reginapizzeria.com",
        "latitude": 42.3655, "longitude": -71.0573
    },
    # New York City, NY
    {
        "name": "Joe's Pizza",
        "address": "7 Carmine St, New York, NY 10014",
        "website": "https://www.joespizzanyc.com",
        "latitude": 40.7306, "longitude": -74.0021
    },
    {
        "name": "7th Street Burger",
        "address": "91 E 7th St, New York, NY 10009",
        "website": "https://7thstreetburger.com",
        "latitude": 40.7268, "longitude": -73.9845
    },
    # Austin, TX
    {
        "name": "Franklin Barbecue",
        "address": "900 E 11th St, Austin, TX 78702",
        "website": "https://franklinbbq.com",
        "latitude": 30.2701, "longitude": -97.7313
    },
    {
        "name": "Torchy's Tacos",
        "address": "1822 S Congress Ave, Austin, TX 78704",
        "website": "https://torchystacos.com",
        "latitude": 30.2471, "longitude": -97.7508
    },
    # Chicago, IL
    {
        "name": "Pequod's Pizza",
        "address": "2207 N Clybourn Ave, Chicago, IL 60614",
        "website": "https://pequodspizza.com",
        "latitude": 41.9219, "longitude": -86.6644
    }
]

SAMPLE_PLATES = [
    # 1. Double Smash Burger
    {
        "author_index": 0, "rest_index": 0, "dish_name": "Truffle Double Smash Burger",
        "category": "Burgers", "rating": 10, "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1586190848861-99aa4a171e90?auto=format&fit=crop&w=1000&q=80",
        "comments": ["Lacy crust edges with melted sharp cheddar. Best burger in NH."]
    },
    # 2. Crispy Hot Chicken
    {
        "author_index": 1, "rest_index": 1, "dish_name": "Crispy Nashville Hot Chicken",
        "category": "Burgers", "rating": 9, "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1625813506062-0aeb1d7a094b?auto=format&fit=crop&w=1000&q=80",
        "comments": ["Huge crunch, sweet hot glaze, dill pickles cut right through."]
    },
    # 3. Hot Honey Pepperoni
    {
        "author_index": 2, "rest_index": 2, "dish_name": "Hot Honey Cupped Pepperoni Pizza",
        "category": "Pizza", "rating": 9, "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1513104890138-7c749659a591?auto=format&fit=crop&w=1000&q=80",
        "comments": ["Crispy char blisters and genuine spicy honey drizzle."]
    },
    # 4. Brown Butter Lobster Roll
    {
        "author_index": 0, "rest_index": 3, "dish_name": "Brown Butter Steamed Lobster Roll",
        "category": "Seafood", "rating": 10, "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1599488615731-7e5c2823ff28?auto=format&fit=crop&w=1000&q=80",
        "comments": ["Served warm on a pillowy steamed bun. Absolute perfection."]
    },
    # 5. Duck Fat Fries & Poutine
    {
        "author_index": 1, "rest_index": 4, "dish_name": "Hand-Cut Duckfat Poutine",
        "category": "Other", "rating": 9, "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1586816001966-79b736744398?auto=format&fit=crop&w=1000&q=80",
        "comments": ["Fried twice in duck fat with local squeaky curd."]
    },
    # 6. North End Artisan Pie
    {
        "author_index": 2, "rest_index": 5, "dish_name": "Boston North End Brick-Oven Pie",
        "category": "Pizza", "rating": 9, "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1534308983496-4fabb1a015ee?auto=format&fit=crop&w=1000&q=80",
        "comments": ["Thin, charred, tangy crushed tomato base."]
    },
    # 7. NYC Street Slice
    {
        "author_index": 4, "rest_index": 6, "dish_name": "Classic NY Cheese Slice",
        "category": "Pizza", "rating": 10, "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1574071318508-1cdbab80d002?auto=format&fit=crop&w=1000&q=80",
        "comments": ["The quintessential New York fold. Zero grease flop."]
    },
    # 8. Classic Smash
    {
        "author_index": 4, "rest_index": 7, "dish_name": "East Village Double Cheeseburger",
        "category": "Burgers", "rating": 10, "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?auto=format&fit=crop&w=1000&q=80",
        "comments": ["Paper thin patties, toasted potato roll, melted American."]
    },
    # 9. Texas Smoked Brisket
    {
        "author_index": 3, "rest_index": 8, "dish_name": "Prime Smoked Texas Brisket",
        "category": "BBQ & Meat", "rating": 10, "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1529193591184-b1d58069ecdd?auto=format&fit=crop&w=1000&q=80",
        "comments": ["Peppery black bark and buttery rendering. World class."]
    },
    # 10. Loaded Street Tacos
    {
        "author_index": 3, "rest_index": 9, "dish_name": "Crispy Green Chile Queso Tacos",
        "category": "Tacos & Mexican", "rating": 9, "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1565299585323-38d6b0865b47?auto=format&fit=crop&w=1000&q=80",
        "comments": ["Fresh handmade tortilla, poblano queso drizzle."]
    },
    # 11. Chicago Deep Dish
    {
        "author_index": 1, "rest_index": 10, "dish_name": "Caramelized Crust Deep Dish",
        "category": "Pizza", "rating": 9, "reorder": "Hell yes",
        "photo_url": "https://images.unsplash.com/photo-1590947132387-155cc02f3212?auto=format&fit=crop&w=1000&q=80",
        "comments": ["That blackened cheese rim crust is iconic."]
    }
]


def run_seed():
    init_db()
    conn = get_connection()
    c = conn.cursor()

    print("[*] Refreshing users...")
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

    print("[*] Refreshing restaurants...")
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

    print("[*] Seeding updated plates with matching photos...")
    plate_ids = []
    for p in SAMPLE_PLATES:
        author_id = user_ids[p["author_index"]]
        rest = SAMPLE_RESTAURANTS[p["rest_index"]]
        rest_id = rest_ids[p["rest_index"]]

        c.execute("SELECT id FROM plates WHERE dish_name = %s AND restaurant = %s", (p["dish_name"], rest["name"]))
        existing = c.fetchone()

        if existing:
            c.execute("""
                UPDATE plates SET photo_url = %s, rating = %s, reorder = %s, category = %s
                WHERE id = %s RETURNING id
            """, (p["photo_url"], p["rating"], p["reorder"], p["category"], existing["id"]))
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

    print("[*] Seeding Plate Duel...")
    if len(plate_ids) >= 2:
        c.execute("SELECT id FROM duels WHERE is_active = TRUE")
        if not c.fetchone():
            c.execute("""
                INSERT INTO duels (title, plate_a_id, plate_b_id, votes_a, votes_b, is_active)
                VALUES (%s, %s, %s, 42, 38, TRUE)
            """, ("The Clash: Bad Brgr Smash vs. Nashville Hot Chicken", plate_ids[0], plate_ids[1]))

    conn.commit()
    c.close()
    conn.close()
    print("[✓] All sample plates updated with authentic food photography.")


if __name__ == "__main__":
    run_seed()