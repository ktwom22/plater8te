import math
import os
import shutil
import traceback
from datetime import datetime
from pathlib import Path
import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from fastapi import FastAPI, Form, Request, UploadFile, File, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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

# Curated categories with icon emojis
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

# Comprehensive blocklist: fast food, gas stations, smoke/vape shops, retreats, and non-dining spots
NON_RESTAURANT_BLOCKLIST = {
    # Fast Food & National Chains
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

    # Gas Stations, Convenience & Fuel Stops
    "nouria", "cumberland farms", "cumby's", "circle k", "7-eleven", "7 eleven",
    "irving", "mobil", "exxon", "shell", "citgo", "bp", "sunoco", "speedway",
    "wawa", "sheetz", "casey's", "gulf", "gas station", "convenience", "mini mart", "mart",

    # Smoke, Vape & Retail
    "smoke", "vape", "tobacco", "cbd", "dispensary", "beverage", "liquor", "package store",

    # Spiritual / Retreats / Non-dining
    "spiritual", "retreat", "renewal", "church", "center for", "ecological"
}

# Explicit Google Places type exclusions
EXCLUDED_GOOGLE_TYPES = {
    "gas_station", "convenience_store", "liquor_store", "tobacco_shop",
    "place_of_worship", "grocery_store", "supermarket", "fast_food_restaurant"
}


def is_invalid_spot(name: str, types: list = None) -> bool:
    """Returns True if the place matches fast-food chains, gas stations, vape shops, or non-eateries."""
    name_lower = name.lower()
    for bad_term in NON_RESTAURANT_BLOCKLIST:
        if bad_term in name_lower:
            return True

    if types:
        for t in types:
            if t.lower() in EXCLUDED_GOOGLE_TYPES or "fast_food" in t.lower():
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
    except Exception as e:
        print(f"[!] Error fetching current user: {e}")
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


# --- GOOGLE PLACES API HELPERS ---

async def fetch_area_restaurants_gps(lat: float, lon: float):
    """Fetches local independent dining venues via GPS coordinates."""
    if not GOOGLE_PLACES_API_KEY or GOOGLE_PLACES_API_KEY == "YOUR_GOOGLE_PLACES_API_KEY":
        return []

    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.websiteUri,places.location,places.types,places.rating,places.userRatingCount"
    }
    payload = {
        "includedTypes": [
            "restaurant", "bar_and_grill", "hamburger_restaurant",
            "pizza_restaurant", "mexican_restaurant", "italian_restaurant",
            "seafood_restaurant", "bar", "cafe", "bakery"
        ],
        "excludedTypes": list(EXCLUDED_GOOGLE_TYPES),
        "maxResultCount": 20,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": 8000.0  # ~5.0 miles
            }
        }
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
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
                    "distance_miles": round(dist, 1) if dist is not None else None
                })
            spots.sort(key=lambda x: x["distance_miles"] if x["distance_miles"] is not None else 9999)
            return spots
    except Exception as e:
        print(f"[!] Places Nearby error: {e}")
        return []


async def fetch_area_restaurants_query(query_text: str):
    """Fetches local restaurants in a searched city or zip code."""
    if not GOOGLE_PLACES_API_KEY or GOOGLE_PLACES_API_KEY == "YOUR_GOOGLE_PLACES_API_KEY":
        return []

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.websiteUri,places.location,places.types,places.rating,places.userRatingCount"
    }
    payload = {
        "textQuery": f"restaurants dining burgers pizza in {query_text}",
        "includedType": "restaurant",
        "maxResultCount": 20
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
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
                    "distance_miles": None
                })
            return spots
    except Exception as e:
        print(f"[!] Places TextSearch error: {e}")
        return []


# --- GOOGLE PLACES API AJAX ENDPOINTS ---

@app.get("/api/restaurants/nearby")
async def get_nearby_restaurants(lat: float = Query(...), lon: float = Query(...)):
    results = await fetch_area_restaurants_gps(lat, lon)
    return JSONResponse(results)


@app.get("/api/restaurants/search")
async def search_restaurants(query: str = Query(...)):
    results = await fetch_area_restaurants_query(query)
    return JSONResponse(results)


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
            err_msg = "Username is already taken." if conflict["username"] == clean_user else "Email is already registered."
            return RedirectResponse(url=f"/?auth_error={err_msg}#auth", status_code=303)

        c.execute("""
            INSERT INTO users (username, email, password_hash)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (clean_user, clean_email, pwd_hash))
        new_id = c.fetchone()["id"]
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"[!] Signup error: {e}")
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


# --- MAIN FEED ROUTE ---

@app.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    food_query: str = Query(None),
    location_query: str = Query(None),
    category: str = Query(None),
    user_lat: str = Query(None),
    user_lon: str = Query(None),
    radius_miles: float = Query(15.0),
    auth_error: str = Query(None)
):
    parsed_lat = None
    parsed_lon = None

    if user_lat and user_lat.strip():
        try:
            parsed_lat = float(user_lat.strip())
        except ValueError:
            parsed_lat = None

    if user_lon and user_lon.strip():
        try:
            parsed_lon = float(user_lon.strip())
        except ValueError:
            parsed_lon = None

    user = get_current_user(request)
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        SELECT p.*, u.username,
               (SELECT COUNT(*) FROM interactions WHERE plate_id = p.id AND type = 'like') AS likes,
               (SELECT COUNT(*) FROM interactions WHERE plate_id = p.id AND type = 'save') AS saves,
               (SELECT COUNT(*) FROM comments WHERE plate_id = p.id) AS comment_count
        FROM plates p
        JOIN users u ON p.user_id = u.id
        ORDER BY p.is_sponsored DESC, p.created_at DESC
    """)
    all_plates = c.fetchall()

    for plate in all_plates:
        c.execute("""
            SELECT c.id, c.comment, TO_CHAR(c.created_at, 'YYYY-MM-DD HH24:MI') as formatted_date, u.username
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.plate_id = %s
            ORDER BY c.created_at ASC
        """, (plate["id"],))
        plate["comments"] = c.fetchall()

    c.close()
    conn.close()

    filtered_plates = []
    for plate in all_plates:
        if category and category.strip():
            plate_cat = plate.get("category") or ""
            if plate_cat.lower() != category.strip().lower():
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
            addr = (plate["restaurant_address"] or "").lower()
            rest = plate["restaurant"].lower()
            if lq not in addr and lq not in rest:
                continue

        if parsed_lat is not None and parsed_lon is not None:
            dist = haversine_miles(parsed_lat, parsed_lon, plate["latitude"], plate["longitude"])
            if dist > radius_miles:
                continue
            plate["distance_miles"] = round(dist, 1)
        else:
            plate["distance_miles"] = None

        filtered_plates.append(plate)

    if parsed_lat is not None and parsed_lon is not None:
        filtered_plates.sort(key=lambda x: x["distance_miles"] if x["distance_miles"] is not None else 999999)

    # Fetch Google Places for Discovery
    discovered_restaurants = []
    area_label = ""

    if parsed_lat is not None and parsed_lon is not None:
        area_label = "Spots Near You"
        discovered_restaurants = await fetch_area_restaurants_gps(parsed_lat, parsed_lon)
    elif location_query and location_query.strip():
        area_label = f"Spots in {location_query.strip().title()}"
        discovered_restaurants = await fetch_area_restaurants_query(location_query.strip())
    elif len(filtered_plates) == 0:
        area_label = "Top Independent Spots"
        discovered_restaurants = await fetch_area_restaurants_query("local dining")

    return templates.TemplateResponse(
        request=request,
        name="feed.html",
        context={
            "user": user,
            "plates": filtered_plates,
            "discovered_restaurants": discovered_restaurants,
            "area_label": area_label,
            "categories": CATEGORIES,
            "selected_category": category or "",
            "food_query": food_query or "",
            "location_query": location_query or "",
            "user_lat": parsed_lat if parsed_lat is not None else "",
            "user_lon": parsed_lon if parsed_lon is not None else "",
            "auth_error": auth_error
        },
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
        SELECT p.*, u.username,
               (SELECT COUNT(*) FROM interactions WHERE plate_id = p.id AND type = 'like') AS likes,
               (SELECT COUNT(*) FROM interactions WHERE plate_id = p.id AND type = 'save') AS saves,
               (SELECT COUNT(*) FROM comments WHERE plate_id = p.id) AS comment_count
        FROM interactions i
        JOIN plates p ON i.plate_id = p.id
        JOIN users u ON p.user_id = u.id
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
            SELECT c.id, c.comment, TO_CHAR(c.created_at, 'YYYY-MM-DD HH24:MI') as formatted_date, u.username
            FROM comments c
            JOIN users u ON c.user_id = u.id
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


# --- CREATE PLATE ---

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
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

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
    lat = float(latitude) if latitude else None
    lon = float(longitude) if longitude else None

    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO plates (
            user_id, dish_name, restaurant, category, restaurant_address, 
            restaurant_website, latitude, longitude, photo_url, rating, reorder
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        user["id"], dish_name.strip(), restaurant.strip(),
        (category or "Other").strip(),
        restaurant_address.strip(), restaurant_website.strip(),
        lat, lon, photo_url, final_rating, final_reorder
    ))
    plate_id = c.fetchone()["id"]
    conn.commit()
    c.close()
    conn.close()

    if is_skipped:
        schedule_rating_reminder(plate_id, user["email"])

    return RedirectResponse(url="/", status_code=303)


# --- SOCIAL INTERACTIONS ---

@app.post("/plates/{plate_id}/interact")
async def interact_plate(plate_id: int, action_type: str = Form(...), request: Request = None):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)

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
    if not user:
        return RedirectResponse(url="/", status_code=303)

    if comment.strip():
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO comments (user_id, plate_id, comment) VALUES (%s, %s, %s)",
            (user["id"], plate_id, comment.strip()),
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