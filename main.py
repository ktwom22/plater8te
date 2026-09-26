import math
import os
import shutil
import traceback
import secrets
from datetime import datetime
from pathlib import Path
import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from fastapi import FastAPI, Form, Request, UploadFile, File, Query, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from database import init_db, get_connection
from scheduler import schedule_rating_reminder

ph = PasswordHasher()

GOOGLE_PLACES_API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "YOUR_GOOGLE_PLACES_API_KEY")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)

TEMPLATES_DIR = BASE_DIR / "templates"
UPLOADS_DIR = DATA_DIR / "uploads"

TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

init_db()

app = FastAPI()
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])

app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

CATEGORIES = [
    {"name": "Burgers", "icon": "🍔"},
    {"name": "Pizza", "icon": "🍕"},
    {"name": "Pasta & Italian", "icon": "🍝"},
    {"name": "Tacos & Mexican", "icon": "🌮"},
    {"name": "Asian & Noodles", "icon": "🍜"},
    {"name": "Seafood", "icon": "🦞"},
    {"name": "BBQ & Meat", "icon": "🥩"},
    {"name": "Brunch & Cafe", "icon": "🥞"},
    {"name": "Desserts", "icon": "🍰"},
    {"name": "Drinks & Cocktails", "icon": "🍸"},
    {"name": "Other", "icon": "🍽️"}
]

NON_RESTAURANT_BLOCKLIST = {
    "mcdonald's", "mcdonalds", "burger king", "wendy's", "wendys", "taco bell",
    "subway", "kfc", "kentucky fried chicken", "pizza hut", "domino's", "dominos",
    "papa john's", "papa johns", "little caesars", "popeyes", "chick-fil-a", "chick fil a",
    "dunkin", "dunkin'", "dunkin' donuts", "starbucks", "sonic drive-in", "sonic",
    "jack in the box", "arby's", "arbys", "panda express", "dairy queen", "dq",
    "hardee's", "hardees", "carl's jr.", "carls jr", "five guys", "jimmy john's",
    "jimmy johns", "jersey mike's", "jersey mikes", "chipotle", "chipotle mexican grill",
    "wingstop", "raising cane's", "raising canes", "culver's", "culvers", "white castle",
    "whataburger", "checkers", "rally's", "del taco", "church's chicken",
    "panera bread", "tim hortons", "baskin-robbins", "firehouse subs",
    "nouria", "cumberland farms", "cumby's", "circle k", "7-eleven", "7 eleven",
    "irving", "mobil", "exxon", "shell", "citgo", "bp", "sunoco", "speedway",
    "wawa", "sheetz", "casey's", "gulf", "gas station", "convenience", "mini mart", "mart",
    "smoke", "vape", "tobacco", "cbd", "dispensary", "beverage", "liquor", "package store",
    "spiritual", "retreat", "renewal", "church", "center for", "ecological"
}

EXCLUDED_TYPES = {
    "gas_station", "convenience_store", "liquor_store", "tobacco_shop",
    "place_of_worship", "grocery_store", "supermarket", "fast_food_restaurant"
}


def is_invalid_spot(name: str, types: list = None) -> bool:
    name_lower = name.lower()
    for bad in NON_RESTAURANT_BLOCKLIST:
        if bad in name_lower:
            return True
    if types:
        for t in types:
            if t.lower() in EXCLUDED_TYPES or "fast_food" in t.lower():
                return True
    return False


def get_current_user(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return None
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT id, username, email FROM users WHERE id = %s", (int(user_id),))
        user = c.fetchone()
        c.close()
        conn.close()
        return user
    except Exception:
        return None


def haversine_miles(lat1, lon1, lat2, lon2):
    if not all([lat1, lon1, lat2, lon2]):
        return 999999.0
    r = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def compute_user_badges(user_id: int, conn) -> list:
    if not user_id:
        return []
    c = conn.cursor()
    badges = []

    if user_id <= 25:
        badges.append({"label": "Pioneer", "icon": "🚀", "color": "bg-indigo-50 text-indigo-700 border-indigo-200"})

    c.execute("""
        SELECT COUNT(*) AS total,
               AVG(rating) AS avg_rating,
               COUNT(CASE WHEN rating = 10 THEN 1 END) AS tens_count,
               COUNT(CASE WHEN photo_url IS NOT NULL THEN 1 END) AS photo_count
        FROM plates WHERE user_id = %s
    """, (user_id,))
    stats = c.fetchone()
    total_plates = stats["total"] or 0
    avg_rating = stats["avg_rating"] or 0
    tens_count = stats["tens_count"] or 0
    photo_count = stats["photo_count"] or 0

    if total_plates >= 30:
        badges.append({"label": "Plate Legend", "icon": "👑", "color": "bg-amber-100 text-amber-900 border-amber-300"})
    elif total_plates >= 15:
        badges.append({"label": "Top Critic", "icon": "🥇", "color": "bg-amber-50 text-amber-800 border-amber-200"})
    elif total_plates >= 5:
        badges.append({"label": "Foodie", "icon": "🍽️", "color": "bg-slate-100 text-slate-700 border-slate-200"})
    elif total_plates >= 1:
        badges.append({"label": "Apprentice", "icon": "🥉", "color": "bg-stone-50 text-stone-700 border-stone-200"})

    if total_plates >= 5:
        if avg_rating >= 8.5:
            badges.append({"label": "Taste Maker", "icon": "🌟", "color": "bg-rose-50 text-rose-700 border-rose-200"})
        elif avg_rating <= 6.5:
            badges.append({"label": "Tough Room", "icon": "🎯", "color": "bg-red-50 text-red-700 border-red-200"})

    if tens_count >= 2:
        badges.append(
            {"label": "Perfectionist", "icon": "💯", "color": "bg-emerald-50 text-emerald-700 border-emerald-200"})

    if total_plates >= 5 and photo_count == total_plates:
        badges.append(
            {"label": "Visual Storyteller", "icon": "📸", "color": "bg-cyan-50 text-cyan-700 border-cyan-200"})

    c.execute("""
        SELECT category, COUNT(*) as cat_count
        FROM plates
        WHERE user_id = %s AND category IS NOT NULL
        GROUP BY category
    """, (user_id,))
    cuisine_counts = {row["category"]: row["cat_count"] for row in c.fetchall()}

    cuisine_badges = {
        "Pizza": ("Pizza Connoisseur", "🍕"),
        "Burgers": ("Burger Boss", "🍔"),
        "Tacos & Mexican": ("Taco Baron", "🌮"),
        "Pasta & Italian": ("Pasta Maestro", "🍝"),
        "Asian & Noodles": ("Noodle Whisperer", "🍜"),
        "Seafood": ("Catch of the Day", "🦞"),
        "Desserts": ("Sweet Tooth", "🍰"),
        "Drinks & Cocktails": ("Mixologist", "🍸")
    }

    for cat_name, (badge_label, badge_icon) in cuisine_badges.items():
        if cuisine_counts.get(cat_name, 0) >= 3:
            badges.append({
                "label": badge_label,
                "icon": badge_icon,
                "color": "bg-orange-50 text-orange-800 border-orange-200"
            })

    c.close()
    return badges


def compute_plate_badges(plate: dict) -> list:
    badges = []
    rating = plate.get("rating")
    likes = plate.get("likes") or 0
    comments = plate.get("comment_count") or 0
    reorder = plate.get("reorder") or ""

    if rating == 10 and reorder == "Hell yes":
        badges.append({"label": "God Tier", "icon": "👑",
                       "color": "bg-amber-400 text-slate-950 border-amber-300 font-black shadow-sm"})
    elif rating and rating >= 9.0:
        badges.append({"label": "Diamond Pick", "icon": "💎", "color": "bg-blue-50 text-blue-800 border-blue-200"})

    if likes >= 15:
        badges.append(
            {"label": "Viral Plate", "icon": "💥", "color": "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200"})
    elif likes >= 5:
        badges.append({"label": "Crowd Favorite", "icon": "🔥", "color": "bg-rose-50 text-rose-700 border-rose-200"})

    if comments >= 6:
        badges.append(
            {"label": "Town Square", "icon": "🗣️", "color": "bg-indigo-50 text-indigo-700 border-indigo-200"})
    elif comments >= 2:
        badges.append({"label": "Buzzing", "icon": "💬", "color": "bg-sky-50 text-sky-700 border-sky-200"})

    saves = plate.get("saves") or 0
    if saves >= 5:
        badges.append({"label": "Must-Try", "icon": "🔖", "color": "bg-purple-50 text-purple-700 border-purple-200"})

    if rating and rating >= 8.5 and likes < 2:
        badges.append(
            {"label": "Hidden Gem", "icon": "⚡", "color": "bg-emerald-50 text-emerald-800 border-emerald-200"})

    if reorder == "Hell yes" and not any(b["label"] == "God Tier" for b in badges):
        badges.append({"label": "Hell Yes", "icon": "🔥", "color": "bg-emerald-50 text-emerald-700 border-emerald-200"})
    elif reorder == "Pass":
        badges.append({"label": "Pass", "icon": "🚫", "color": "bg-slate-100 text-slate-600 border-slate-200"})

    return badges


def get_community_restaurants(conn, lat=None, lon=None, query=None, radius_miles=8.0):
    c = conn.cursor()
    c.execute("""
        SELECT r.*, 
               COUNT(p.id) as plate_count,
               AVG(p.rating) as avg_rating
        FROM restaurants r
        LEFT JOIN plates p ON r.id = p.restaurant_id
        GROUP BY r.id
        ORDER BY r.created_at DESC
    """)
    rows = c.fetchall()
    c.close()

    results = []
    for r in rows:
        name = r["name"]
        address = r["address"] or ""
        website = r["website"] or ""
        r_lat = r["latitude"]
        r_lon = r["longitude"]

        if query:
            q = query.lower()
            if q not in name.lower() and q not in address.lower():
                continue

        dist = None
        if lat is not None and lon is not None and r_lat and r_lon:
            dist = haversine_miles(lat, lon, r_lat, r_lon)
            if dist > radius_miles:
                continue

        results.append({
            "id": r["id"],
            "name": name,
            "address": address,
            "website": website,
            "rating": round(float(r["avg_rating"]), 1) if r["avg_rating"] else None,
            "user_ratings_total": r["plate_count"],
            "lat": r_lat,
            "lon": r_lon,
            "distance_miles": round(dist, 1) if dist is not None else None,
            "is_community_added": True
        })
    return results


async def fetch_area_restaurants_gps(lat: float, lon: float):
    if not GOOGLE_PLACES_API_KEY or GOOGLE_PLACES_API_KEY == "YOUR_GOOGLE_PLACES_API_KEY":
        return []

    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.websiteUri,places.location,places.types,places.rating,places.userRatingCount"
    }
    payload = {
        "includedTypes": ["restaurant", "cafe", "bakery", "bar"],
        "excludedTypes": ["fast_food_restaurant"],
        "maxResultCount": 20,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": 8000.0
            }
        }
    }

    try:
        async with httpx.AsyncClient(timeout=9.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                return []
            data = resp.json()
            spots = []
            for place in data.get("places", []):
                name = place.get("displayName", {}).get("text", "")
                types = place.get("types", [])
                if not name or is_invalid_spot(name, types):
                    continue
                p_lat = place.get("location", {}).get("latitude")
                p_lon = place.get("location", {}).get("longitude")
                dist = haversine_miles(lat, lon, p_lat, p_lon) if p_lat and p_lon else None
                spots.append({
                    "name": name,
                    "address": place.get("formattedAddress", ""),
                    "website": place.get("websiteUri", ""),
                    "rating": place.get("rating"),
                    "user_ratings_total": place.get("userRatingCount"),
                    "lat": p_lat,
                    "lon": p_lon,
                    "distance_miles": round(dist, 1) if dist is not None else None,
                    "is_community_added": False
                })
            spots.sort(key=lambda x: x["distance_miles"] if x["distance_miles"] is not None else 9999)
            return spots
    except Exception:
        return []


async def fetch_area_restaurants_query(query_text: str):
    if not GOOGLE_PLACES_API_KEY or GOOGLE_PLACES_API_KEY == "YOUR_GOOGLE_PLACES_API_KEY":
        return []

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.websiteUri,places.location,places.types,places.rating,places.userRatingCount"
    }
    payload = {
        "textQuery": f"best local restaurants and food in {query_text}",
        "maxResultCount": 20
    }

    try:
        async with httpx.AsyncClient(timeout=9.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                return []
            data = resp.json()
            spots = []
            for place in data.get("places", []):
                name = place.get("displayName", {}).get("text", "")
                types = place.get("types", [])
                if not name or is_invalid_spot(name, types):
                    continue
                spots.append({
                    "name": name,
                    "address": place.get("formattedAddress", ""),
                    "website": place.get("websiteUri", ""),
                    "rating": place.get("rating"),
                    "user_ratings_total": place.get("userRatingCount"),
                    "lat": place.get("location", {}).get("latitude"),
                    "lon": place.get("location", {}).get("longitude"),
                    "distance_miles": None,
                    "is_community_added": False
                })
            return spots
    except Exception:
        return []


# --- SEO & AI DIRECTIVE ENDPOINTS ---

@app.get("/robots.txt", response_class=PlainTextResponse)
def get_robots_txt():
    content = """User-agent: Googlebot
Allow: /

User-agent: Bingbot
Allow: /

User-agent: OAI-SearchBot
Allow: /

User-agent: ChatGPT-User
Allow: /

User-agent: GPTBot
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Perplexity-User
Allow: /

User-agent: Claude-SearchBot
Allow: /

User-agent: Claude-User
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: Applebot-Extended
Allow: /

User-agent: *
Allow: /
Disallow: /logout
Disallow: /api/

Sitemap: https://r8theplate.com/sitemap.xml
"""
    return content.strip()


@app.get("/sitemap.xml")
def get_sitemap():
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT id, created_at FROM plates ORDER BY created_at DESC LIMIT 500")
        plates = c.fetchall() or []
        c.close()
        conn.close()
    except Exception:
        plates = []

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += "  <url><loc>https://r8theplate.com/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>\n"

    categories = ["Burgers", "Pizza", "Pasta%20%26%20Italian", "Tacos%20%26%20Mexican", "Asian%20%26%20Noodles",
                  "Seafood"]
    for cat in categories:
        xml += f"  <url><loc>https://r8theplate.com/?category={cat}</loc><changefreq>daily</changefreq><priority>0.8</priority></url>\n"

    for p in plates:
        date_str = p["created_at"].strftime("%Y-%m-%d") if p.get("created_at") else "2026-09-25"
        xml += f"  <url><loc>https://r8theplate.com/#plate-{p['id']}</loc><lastmod>{date_str}</lastmod><changefreq>weekly</changefreq><priority>0.6</priority></url>\n"

    xml += "</urlset>"
    return Response(content=xml, media_type="application/xml")


# --- AJAX RESTAURANT ENDPOINTS ---

@app.get("/api/restaurants/nearby")
async def get_nearby_restaurants(lat: float = Query(...), lon: float = Query(...)):
    results = await fetch_area_restaurants_gps(lat, lon)
    return JSONResponse(results)


@app.get("/api/restaurants/search")
async def search_restaurants(query: str = Query(...)):
    results = await fetch_area_restaurants_query(query)
    return JSONResponse(results)


# --- PLATE DUEL VOTING API ---

@app.post("/api/duels/vote")
async def vote_duel(request: Request, duel_id: int = Form(...), choice: str = Form(...)):
    # Persistent voter token cookie to prevent spam
    voter_token = request.cookies.get("voter_token")
    new_token = False
    if not voter_token:
        voter_token = secrets.token_hex(16)
        new_token = True

    choice_clean = choice.upper()
    if choice_clean not in ["A", "B"]:
        return JSONResponse({"error": "Invalid choice"}, status_code=400)

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT voter_token FROM duel_votes WHERE duel_id = %s AND voter_token = %s", (duel_id, voter_token))
    already_voted = c.fetchone()

    if already_voted:
        c.close()
        conn.close()
        return JSONResponse({"status": "already_voted", "message": "You've already cast your vote for this duel!"})

    c.execute("INSERT INTO duel_votes (duel_id, voter_token, choice) VALUES (%s, %s, %s)",
              (duel_id, voter_token, choice_clean))
    if choice_clean == "A":
        c.execute("UPDATE duels SET votes_a = votes_a + 1 WHERE id = %s RETURNING votes_a, votes_b", (duel_id,))
    else:
        c.execute("UPDATE duels SET votes_b = votes_b + 1 WHERE id = %s RETURNING votes_a, votes_b", (duel_id,))

    updated = c.fetchone()
    conn.commit()
    c.close()
    conn.close()

    total = (updated["votes_a"] or 0) + (updated["votes_b"] or 0)
    pct_a = round(((updated["votes_a"] or 0) / total) * 100) if total > 0 else 50
    pct_b = 100 - pct_a

    response = JSONResponse(
        {"status": "success", "votes_a": updated["votes_a"], "votes_b": updated["votes_b"], "pct_a": pct_a,
         "pct_b": pct_b})
    if new_token:
        response.set_cookie(key="voter_token", value=voter_token, max_age=31536000, httponly=True)
    return response


# --- AUTHENTICATION ROUTES ---

@app.post("/signup")
async def signup(
        request: Request,
        username: str = Form(...),
        email: str = Form(...),
        password: str = Form(...)
):
    clean_user = username.strip().lower()
    clean_email = email.strip().lower()
    clean_pass = password.strip()

    if len(clean_user) < 3:
        return RedirectResponse(url="/?auth_error=Username must be at least 3 characters.#auth", status_code=303)
    if len(clean_pass) < 6:
        return RedirectResponse(url="/?auth_error=Password must be at least 6 characters.#auth", status_code=303)

    pwd_hash = ph.hash(clean_pass)

    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT username, email FROM users WHERE username = %s OR email = %s", (clean_user, clean_email))
        conflict = c.fetchone()
        if conflict:
            err_msg = "Username is already taken." if conflict[
                                                          "username"] == clean_user else "Email is already registered."
            return RedirectResponse(url=f"/?auth_error={err_msg}#auth", status_code=303)

        c.execute("""
            INSERT INTO users (username, email, password_hash)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (clean_user, clean_email, pwd_hash))
        new_id = c.fetchone()["id"]
        conn.commit()
    except Exception:
        conn.rollback()
        return RedirectResponse(url="/?auth_error=An error occurred creating your account.#auth", status_code=303)
    finally:
        c.close()
        conn.close()

    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="user_id",
        value=str(new_id),
        httponly=True,
        samesite="lax",
        secure=is_https,
        max_age=2592000,
        path="/"
    )
    return response


@app.post("/login")
async def login(
        request: Request,
        identifier: str = Form(...),
        password: str = Form(...)
):
    clean_id = identifier.strip().lower()
    clean_pass = password.strip()

    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username = %s OR email = %s", (clean_id, clean_id))
    user = c.fetchone()
    c.close()
    conn.close()

    if not user:
        return RedirectResponse(url="/?auth_error=No account found with that username or email.#auth", status_code=303)

    if user.get("password_hash"):
        try:
            ph.verify(user["password_hash"], clean_pass)
        except VerifyMismatchError:
            return RedirectResponse(url="/?auth_error=Incorrect password.#auth", status_code=303)

    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="user_id",
        value=str(user["id"]),
        httponly=True,
        samesite="lax",
        secure=is_https,
        max_age=2592000,
        path="/"
    )
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key="user_id", path="/")
    return response


# --- RESTAURANT QR LANDING PAGE (GROWTH ENGINE 5) ---

@app.get("/r/{restaurant_id}", response_class=HTMLResponse)
async def restaurant_qr_page(restaurant_id: int, request: Request):
    user = get_current_user(request)
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT * FROM restaurants WHERE id = %s", (restaurant_id,))
    spot = c.fetchone()

    if not spot:
        c.close()
        conn.close()
        return RedirectResponse(url="/", status_code=303)

    c.execute("""
        SELECT p.*, COALESCE(u.username, 'anonymous') as username,
               (SELECT COUNT(*) FROM interactions WHERE plate_id = p.id AND type = 'like') AS likes,
               (SELECT COUNT(*) FROM comments WHERE plate_id = p.id) AS comment_count
        FROM plates p
        LEFT JOIN users u ON p.user_id = u.id
        WHERE p.restaurant_id = %s
        ORDER BY p.rating DESC NULLS LAST, p.created_at DESC
    """, (restaurant_id,))
    dishes = c.fetchall() or []

    for d in dishes:
        d["plate_badges"] = compute_plate_badges(d)

    c.close()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="feed.html",
        context={
            "user": user,
            "user_badges": [],
            "plates": dishes,
            "discovered_restaurants": [spot],
            "area_label": f"Dishes at {spot['name']}",
            "categories": CATEGORIES,
            "selected_category": "",
            "food_query": "",
            "location_query": "",
            "user_lat": spot.get("latitude") or "",
            "user_lon": spot.get("longitude") or "",
            "scope": "all",
            "is_fallback": False,
            "auth_error": None,
            "active_duel": None,
            "top_critics": [],
            "pioneers_left": 25,
            "active_trails": [],
            "qr_spot": spot
        }
    )


# --- MAIN FEED ROUTE (INTEGRATES ALL 5 ENGINES) ---

@app.get("/", response_class=HTMLResponse)
async def home(
        request: Request,
        food_query: str = Query(None),
        location_query: str = Query(None),
        category: str = Query(None),
        user_lat: str = Query(None),
        user_lon: str = Query(None),
        radius_miles: float = Query(15.0),
        scope: str = Query("nearby"),
        auth_error: str = Query(None)
):
    try:
        parsed_lat = None
        parsed_lon = None

        if user_lat and user_lat.strip():
            try:
                parsed_lat = float(user_lat.strip())
            except (ValueError, TypeError):
                parsed_lat = None

        if user_lon and user_lon.strip():
            try:
                parsed_lon = float(user_lon.strip())
            except (ValueError, TypeError):
                parsed_lon = None

        user = get_current_user(request)
        conn = get_connection()
        c = conn.cursor()

        # Engine 1: Plate Duel of the Week
        c.execute("""
            SELECT d.*, 
                   pa.dish_name as plate_a_dish, pa.restaurant as plate_a_restaurant, pa.photo_url as plate_a_photo, pa.rating as plate_a_rating,
                   pb.dish_name as plate_b_dish, pb.restaurant as plate_b_restaurant, pb.photo_url as plate_b_photo, pb.rating as plate_b_rating
            FROM duels d
            JOIN plates pa ON d.plate_a_id = pa.id
            JOIN plates pb ON d.plate_b_id = pb.id
            WHERE d.is_active = TRUE
            ORDER BY d.created_at DESC
            LIMIT 1
        """)
        active_duel_row = c.fetchone()
        active_duel = None
        if active_duel_row:
            total_votes = (active_duel_row["votes_a"] or 0) + (active_duel_row["votes_b"] or 0)
            pct_a = round(((active_duel_row["votes_a"] or 0) / total_votes) * 100) if total_votes > 0 else 50
            pct_b = 100 - pct_a
            active_duel = dict(active_duel_row)
            active_duel["pct_a"] = pct_a
            active_duel["pct_b"] = pct_b

        # Engine 3: Pioneer & Critics Leaderboard
        c.execute("SELECT COUNT(*) AS total_critics FROM users")
        critics_count = c.fetchone()["total_critics"] or 0
        pioneers_left = max(0, 25 - critics_count)

        c.execute("""
            SELECT u.id, u.username, COUNT(p.id) as plate_count, AVG(p.rating) as avg_rating
            FROM users u
            JOIN plates p ON u.id = p.user_id
            GROUP BY u.id
            ORDER BY plate_count DESC, avg_rating DESC
            LIMIT 5
        """)
        top_critics = c.fetchall() or []

        # Engine 4: Active Food Trails
        c.execute("SELECT * FROM trails ORDER BY id ASC")
        active_trails = c.fetchall() or []

        # Plates Query
        c.execute("""
            SELECT p.*, 
                   COALESCE(u.username, 'anonymous') AS username,
                   (SELECT COUNT(*) FROM interactions WHERE plate_id = p.id AND type = 'like') AS likes,
                   (SELECT COUNT(*) FROM interactions WHERE plate_id = p.id AND type = 'save') AS saves,
                   (SELECT COUNT(*) FROM comments WHERE plate_id = p.id) AS comment_count
            FROM plates p
            LEFT JOIN users u ON p.user_id = u.id
            ORDER BY p.is_sponsored DESC, p.created_at DESC
        """)
        all_plates = c.fetchall() or []

        for plate in all_plates:
            c.execute("""
                SELECT c.id, c.comment, TO_CHAR(c.created_at, 'YYYY-MM-DD HH24:MI') as formatted_date, 
                       COALESCE(u.username, 'anonymous') as username
                FROM comments c
                LEFT JOIN users u ON c.user_id = u.id
                WHERE c.plate_id = %s
                ORDER BY c.created_at ASC
            """, (plate["id"],))
            plate["comments"] = c.fetchall() or []

            plate["plate_badges"] = compute_plate_badges(plate)
            plate["author_badges"] = compute_user_badges(plate["user_id"], conn) if plate.get("user_id") else []

            if parsed_lat is not None and parsed_lon is not None and plate.get("latitude") and plate.get("longitude"):
                dist = haversine_miles(parsed_lat, parsed_lon, plate["latitude"], plate["longitude"])
                plate["distance_miles"] = round(dist, 1)
            else:
                plate["distance_miles"] = None

        user_badges = []
        if user:
            user_badges = compute_user_badges(user["id"], conn)

        # Baseline category and text filtering
        base_filtered = []
        for plate in all_plates:
            if category and category.strip():
                if (plate.get("category") or "").lower() != category.strip().lower():
                    continue

            if food_query:
                fq = food_query.lower()
                dish_match = fq in plate["dish_name"].lower()
                rest_match = fq in plate["restaurant"].lower()
                cat_match = fq in (plate.get("category") or "").lower()
                if not (dish_match or rest_match or cat_match):
                    continue

            if location_query:
                lq = location_query.lower()
                addr = (plate.get("restaurant_address") or "").lower()
                rest = (plate.get("restaurant") or "").lower()
                if lq not in addr and lq not in rest:
                    continue

            base_filtered.append(plate)

        # Proximity Logic: Nearby-first with graceful fallback
        is_fallback = False
        final_plates = []

        if parsed_lat is not None and parsed_lon is not None and scope != "all":
            nearby_plates = [
                p for p in base_filtered
                if p["distance_miles"] is not None and p["distance_miles"] <= radius_miles
            ]
            nearby_plates.sort(key=lambda x: x["distance_miles"])

            if len(nearby_plates) > 0:
                final_plates = nearby_plates
            else:
                is_fallback = True
                final_plates = base_filtered
                final_plates.sort(key=lambda x: x["distance_miles"] if x["distance_miles"] is not None else 999999)
        else:
            final_plates = base_filtered
            if parsed_lat is not None and parsed_lon is not None:
                final_plates.sort(key=lambda x: x["distance_miles"] if x["distance_miles"] is not None else 999999)

        community_spots = get_community_restaurants(
            conn, lat=parsed_lat, lon=parsed_lon, query=location_query
        ) or []

        c.close()
        conn.close()

        google_spots = []
        area_label = ""

        if parsed_lat is not None and parsed_lon is not None:
            area_label = "Spots Near You"
            google_spots = await fetch_area_restaurants_gps(parsed_lat, parsed_lon)
        elif location_query and location_query.strip():
            area_label = f"Spots in {location_query.strip().title()}"
            google_spots = await fetch_area_restaurants_query(location_query.strip())
        else:
            area_label = "Local Independent Eateries"
            google_spots = await fetch_area_restaurants_query("Lebanon ME Rochester NH")

        existing_names = set()
        discovered_restaurants = []

        for spot in community_spots:
            existing_names.add(spot["name"].strip().lower())
            discovered_restaurants.append(spot)

        for spot in (google_spots or []):
            if spot.get("name") and spot["name"].strip().lower() not in existing_names:
                existing_names.add(spot["name"].strip().lower())
                discovered_restaurants.append(spot)

        return templates.TemplateResponse(
            request=request,
            name="feed.html",
            context={
                "user": user,
                "user_badges": user_badges,
                "plates": final_plates,
                "discovered_restaurants": discovered_restaurants,
                "area_label": area_label,
                "categories": CATEGORIES,
                "selected_category": category or "",
                "food_query": food_query or "",
                "location_query": location_query or "",
                "user_lat": parsed_lat if parsed_lat is not None else "",
                "user_lon": parsed_lon if parsed_lon is not None else "",
                "scope": scope,
                "is_fallback": is_fallback,
                "auth_error": auth_error,
                "active_duel": active_duel,
                "top_critics": top_critics,
                "pioneers_left": pioneers_left,
                "active_trails": active_trails,
                "qr_spot": None
            },
        )
    except Exception as e:
        print(f"[!] Root Route Exception: {traceback.format_exc()}")
        return HTMLResponse(
            "<!DOCTYPE html><html><body><h1>PlateRate Updating</h1><p>Please refresh in a moment.</p></body></html>",
            status_code=200
        )


# --- FAVORITES ---

@app.get("/favorites", response_class=HTMLResponse)
async def favorites_page(request: Request, q: str = Query(None)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    conn = get_connection()
    c = conn.cursor()

    query_str = """
        SELECT p.*, COALESCE(u.username, 'anonymous') as username,
               (SELECT COUNT(*) FROM interactions WHERE plate_id = p.id AND type = 'like') AS likes,
               (SELECT COUNT(*) FROM interactions WHERE plate_id = p.id AND type = 'save') AS saves,
               (SELECT COUNT(*) FROM comments WHERE plate_id = p.id) AS comment_count
        FROM interactions i
        JOIN plates p ON i.plate_id = p.id
        LEFT JOIN users u ON p.user_id = u.id
        WHERE i.user_id = %s AND i.type = 'save'
    """
    params = [user["id"]]

    if q:
        search_pattern = f"%{q.strip()}%"
        query_str += " AND (p.dish_name ILIKE %s OR p.restaurant ILIKE %s OR p.restaurant_address ILIKE %s OR p.category ILIKE %s)"
        params.extend([search_pattern, search_pattern, search_pattern, search_pattern])

    query_str += " ORDER BY p.created_at DESC"
    c.execute(query_str, tuple(params))
    saved_plates = c.fetchall()

    for plate in saved_plates:
        c.execute("""
            SELECT c.id, c.comment, TO_CHAR(c.created_at, 'YYYY-MM-DD HH24:MI') as formatted_date, 
                   COALESCE(u.username, 'anonymous') as username
            FROM comments c
            LEFT JOIN users u ON c.user_id = u.id
            WHERE c.plate_id = %s
            ORDER BY c.created_at ASC
        """, (plate["id"],))
        plate["comments"] = c.fetchall()

    c.close()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="favorites.html",
        context={"user": user, "plates": saved_plates, "search_q": q or ""}
    )


# --- MY PLATES ---

@app.get("/my-plates", response_class=HTMLResponse)
async def my_plates_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM interactions WHERE plate_id = p.id AND type = 'like') AS likes,
               (SELECT COUNT(*) FROM interactions WHERE plate_id = p.id AND type = 'save') AS saves,
               (SELECT COUNT(*) FROM comments WHERE plate_id = p.id) AS comment_count
        FROM plates p
        WHERE p.user_id = %s
        ORDER BY p.created_at DESC
    """, (user["id"],))
    my_plates = c.fetchall()
    c.close()
    conn.close()

    unrated_plates = [p for p in my_plates if p["rating"] is None]
    rated_plates = [p for p in my_plates if p["rating"] is not None]

    return templates.TemplateResponse(
        request=request,
        name="my_plates.html",
        context={"user": user, "unrated": unrated_plates, "rated": rated_plates}
    )


# --- CREATE PLATE (PERSISTS TO REGISTRY) ---

@app.post("/plates")
async def create_plate(
        request: Request,
        dish_name: str = Form(...),
        restaurant: str = Form(...),
        category: str = Form("Other"),
        restaurant_address: str = Form(""),
        restaurant_website: str = Form(""),
        latitude: str = Form(None),
        longitude: str = Form(None),
        skip_rating: str = Form(None),
        rating: int = Form(None),
        reorder: str = Form(None),
        photo: UploadFile = File(None),
        guest_email: str = Form(None)
):
    user = get_current_user(request)
    author_id = user["id"] if user else None

    is_skipped = skip_rating == "true"
    photo_url = None

    if photo and photo.filename:
        safe_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{photo.filename}"
        target_path = UPLOADS_DIR / safe_filename
        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
        photo_url = f"/uploads/{safe_filename}"

    final_rating = None if is_skipped else rating
    final_reorder = None if is_skipped else reorder
    lat = float(latitude) if latitude and latitude.strip() else None
    lon = float(longitude) if longitude and longitude.strip() else None

    clean_rest = restaurant.strip()
    clean_addr = restaurant_address.strip()
    clean_web = restaurant_website.strip()

    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT id FROM restaurants WHERE LOWER(name) = LOWER(%s)", (clean_rest,))
    rest_row = c.fetchone()

    if rest_row:
        restaurant_id = rest_row["id"]
        if (lat and lon) or clean_web or clean_addr:
            c.execute("""
                UPDATE restaurants 
                SET address = COALESCE(NULLIF(address, ''), %s),
                    website = COALESCE(NULLIF(website, ''), %s),
                    latitude = COALESCE(latitude, %s),
                    longitude = COALESCE(longitude, %s)
                WHERE id = %s
            """, (clean_addr, clean_web, lat, lon, restaurant_id))
    else:
        c.execute("""
            INSERT INTO restaurants (name, address, website, latitude, longitude, created_by_user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (clean_rest, clean_addr, clean_web, lat, lon, author_id))
        restaurant_id = c.fetchone()["id"]

    c.execute("""
        INSERT INTO plates (
            user_id, restaurant_id, dish_name, restaurant, category, restaurant_address, 
            restaurant_website, latitude, longitude, photo_url, rating, reorder
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        author_id, restaurant_id, dish_name.strip(), clean_rest,
        (category or "Other").strip(), clean_addr, clean_web,
        lat, lon, photo_url, final_rating, final_reorder
    ))
    plate_id = c.fetchone()["id"]
    conn.commit()
    c.close()
    conn.close()

    reminder_target = user["email"] if user else (guest_email.strip() if guest_email else None)
    if is_skipped and reminder_target:
        schedule_rating_reminder(plate_id, reminder_target)

    return RedirectResponse(url="/", status_code=303)


# --- SOCIAL INTERACTIONS ---

@app.post("/plates/{plate_id}/interact")
async def interact_plate(plate_id: int, action_type: str = Form(...), request: Request = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/#auth", status_code=303)

    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT id FROM interactions WHERE user_id = %s AND plate_id = %s AND type = %s",
        (user["id"], plate_id, action_type),
    )
    existing = c.fetchone()

    if existing:
        c.execute("DELETE FROM interactions WHERE id = %s", (existing["id"],))
    else:
        c.execute(
            "INSERT INTO interactions (user_id, plate_id, type) VALUES (%s, %s, %s)",
            (user["id"], plate_id, action_type),
        )
    conn.commit()
    c.close()
    conn.close()

    referer = request.headers.get("referer") or "/"
    return RedirectResponse(url=referer, status_code=303)


@app.post("/plates/{plate_id}/comments")
async def add_comment(plate_id: int, comment: str = Form(...), request: Request = None):
    user = get_current_user(request)
    author_id = user["id"] if user else None

    if comment.strip():
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO comments (user_id, plate_id, comment) VALUES (%s, %s, %s)",
            (author_id, plate_id, comment.strip()),
        )
        conn.commit()
        c.close()
        conn.close()

    referer = request.headers.get("referer") or f"/#plate-{plate_id}"
    return RedirectResponse(url=referer, status_code=303)


# --- DELAYED RATING ---

@app.get("/plates/{plate_id}/rate", response_class=HTMLResponse)
async def rate_plate_page(plate_id: int, request: Request):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM plates WHERE id = %s", (plate_id,))
    plate = c.fetchone()
    c.close()
    conn.close()

    if not plate:
        return HTMLResponse("Plate not found", status_code=404)

    return templates.TemplateResponse(
        request=request,
        name="rate_reminder.html",
        context={"plate": plate}
    )


@app.post("/plates/{plate_id}/rate")
async def submit_delayed_rating(
        plate_id: int,
        rating: int = Form(...),
        reorder: str = Form(...),
        redirect_to: str = Form("/my-plates")
):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE plates SET rating = %s, reorder = %s WHERE id = %s",
        (rating, reorder, plate_id),
    )
    conn.commit()
    c.close()
    conn.close()
    return RedirectResponse(url=redirect_to, status_code=303)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)