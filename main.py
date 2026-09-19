import math
import os
import shutil
import traceback
from datetime import datetime
from pathlib import Path
import httpx

from fastapi import FastAPI, Form, Request, UploadFile, File, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from database import init_db, get_connection
from scheduler import schedule_rating_reminder

# Read API Key from Railway environment variables, with local fallback
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
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request):
    user_id = request.cookies.get("user_id")
    if not user_id:
        return None
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user


def haversine_miles(lat1, lon1, lat2, lon2):
    """Calculates distance between two coordinates in miles."""
    if not all([lat1, lon1, lat2, lon2]):
        return 999999.0
    r = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


# --- GOOGLE PLACES API (NEW) ENDPOINTS ---

@app.get("/api/restaurants/nearby")
async def get_nearby_restaurants(lat: float = Query(...), lon: float = Query(...)):
    if not GOOGLE_PLACES_API_KEY or GOOGLE_PLACES_API_KEY == "YOUR_GOOGLE_PLACES_API_KEY":
        return JSONResponse({"error": "Google Places API Key is not set in environment or code"}, status_code=500)

    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.websiteUri,places.location"
    }
    payload = {
        "includedTypes": ["restaurant", "cafe", "bakery", "fast_food_restaurant", "bar"],
        "maxResultCount": 20,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": 3500.0
            }
        }
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            data = resp.json()

            if resp.status_code != 200:
                print(f"[!] Google Places error {resp.status_code}: {data}")
                return JSONResponse({"error": f"Google error: {data}"}, status_code=500)

            results = []
            for place in data.get("places", []):
                name = place.get("displayName", {}).get("text", "")
                if not name:
                    continue
                results.append({
                    "name": name,
                    "address": place.get("formattedAddress", ""),
                    "website": place.get("websiteUri", ""),
                    "lat": place.get("location", {}).get("latitude"),
                    "lon": place.get("location", {}).get("longitude")
                })
            return JSONResponse(results)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/restaurants/search")
async def search_restaurants(query: str = Query(...)):
    if not GOOGLE_PLACES_API_KEY or GOOGLE_PLACES_API_KEY == "YOUR_GOOGLE_PLACES_API_KEY":
        return JSONResponse({"error": "Google Places API Key is not set in environment or code"}, status_code=500)

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.websiteUri,places.location"
    }
    payload = {
        "textQuery": f"restaurants in {query}",
        "maxResultCount": 20
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            data = resp.json()

            if resp.status_code != 200:
                print(f"[!] Google Search error {resp.status_code}: {data}")
                return JSONResponse({"error": f"Google error: {data}"}, status_code=500)

            results = []
            for place in data.get("places", []):
                name = place.get("displayName", {}).get("text", "")
                if not name:
                    continue
                results.append({
                    "name": name,
                    "address": place.get("formattedAddress", ""),
                    "website": place.get("websiteUri", ""),
                    "lat": place.get("location", {}).get("latitude"),
                    "lon": place.get("location", {}).get("longitude")
                })
            return JSONResponse(results)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


# --- MAIN FEED & AREA DISCOVERY ---

@app.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    food_query: str = Query(None),
    location_query: str = Query(None),
    user_lat: str = Query(None),
    user_lon: str = Query(None),
    radius_miles: float = Query(15.0)
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
    all_plates = [dict(row) for row in c.fetchall()]

    for plate in all_plates:
        c.execute("""
            SELECT c.id, c.comment, c.created_at, u.username
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.plate_id = ?
            ORDER BY c.created_at ASC
        """, (plate["id"],))
        plate["comments"] = [dict(r) for r in c.fetchall()]

    conn.close()

    filtered_plates = []
    for plate in all_plates:
        if food_query:
            fq = food_query.lower()
            if fq not in plate["dish_name"].lower() and fq not in plate["restaurant"].lower():
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

    return templates.TemplateResponse(
        "feed.html",
        {
            "request": request,
            "user": user,
            "plates": filtered_plates,
            "food_query": food_query or "",
            "location_query": location_query or "",
            "user_lat": parsed_lat if parsed_lat is not None else "",
            "user_lon": parsed_lon if parsed_lon is not None else ""
        },
    )


# --- FAVORITES PAGE ---

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
        WHERE i.user_id = ? AND i.type = 'save'
    """
    params = [user["id"]]

    if q:
        search_pattern = f"%{q.strip()}%"
        query_str += " AND (p.dish_name LIKE ? OR p.restaurant LIKE ? OR p.restaurant_address LIKE ?)"
        params.extend([search_pattern, search_pattern, search_pattern])

    query_str += " ORDER BY p.created_at DESC"
    c.execute(query_str, tuple(params))
    saved_plates = [dict(r) for r in c.fetchall()]

    for plate in saved_plates:
        c.execute("""
            SELECT c.id, c.comment, c.created_at, u.username
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.plate_id = ?
            ORDER BY c.created_at ASC
        """, (plate["id"],))
        plate["comments"] = [dict(r) for r in c.fetchall()]

    conn.close()

    return templates.TemplateResponse(
        "favorites.html",
        {"request": request, "user": user, "plates": saved_plates, "search_q": q or ""}
    )


# --- USER PROFILE & PENDING RATINGS ---

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
        WHERE p.user_id = ?
        ORDER BY p.created_at DESC
    """, (user["id"],))
    my_plates = c.fetchall()
    conn.close()

    unrated_plates = [p for p in my_plates if p["rating"] is None]
    rated_plates = [p for p in my_plates if p["rating"] is not None]

    return templates.TemplateResponse(
        "my_plates.html",
        {"request": request, "user": user, "unrated": unrated_plates, "rated": rated_plates}
    )


# --- AUTHENTICATION ---

@app.post("/login")
async def login(username: str = Form(...), email: str = Form(...)):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO users (username, email) VALUES (?, ?)",
        (username.strip(), email.strip()),
    )
    conn.commit()
    c.execute("SELECT id FROM users WHERE username = ?", (username.strip(),))
    row = c.fetchone()
    conn.close()

    response = RedirectResponse(url="/", status_code=303)
    if row:
        response.set_cookie(key="user_id", value=str(row["id"]))
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(key="user_id")
    return response


# --- PLATE ACTIONS ---

@app.post("/plates")
async def create_plate(
    request: Request,
    dish_name: str = Form(...),
    restaurant: str = Form(...),
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
            user_id, dish_name, restaurant, restaurant_address, 
            restaurant_website, latitude, longitude, photo_url, rating, reorder
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user["id"], dish_name.strip(), restaurant.strip(),
        restaurant_address.strip(), restaurant_website.strip(),
        lat, lon, photo_url, final_rating, final_reorder
    ))
    plate_id = c.lastrowid
    conn.commit()
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
        "SELECT id FROM interactions WHERE user_id = ? AND plate_id = ? AND type = ?",
        (user["id"], plate_id, action_type),
    )
    existing = c.fetchone()

    if existing:
        c.execute("DELETE FROM interactions WHERE id = ?", (existing["id"],))
    else:
        c.execute(
            "INSERT INTO interactions (user_id, plate_id, type) VALUES (?, ?, ?)",
            (user["id"], plate_id, action_type),
        )
    conn.commit()
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
            "INSERT INTO comments (user_id, plate_id, comment) VALUES (?, ?, ?)",
            (user["id"], plate_id, comment.strip()),
        )
        conn.commit()
        conn.close()

    referer = request.headers.get("referer") or f"/#plate-{plate_id}"
    return RedirectResponse(url=referer, status_code=303)


# --- DELAYED RATING REMINDER LANDING ---

@app.get("/plates/{plate_id}/rate", response_class=HTMLResponse)
async def rate_plate_page(plate_id: int, request: Request):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM plates WHERE id = ?", (plate_id,))
    plate = c.fetchone()
    conn.close()

    if not plate:
        return HTMLResponse("Plate not found", status_code=404)

    return templates.TemplateResponse("rate_reminder.html", {"request": request, "plate": plate})


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
        "UPDATE plates SET rating = ?, reorder = ? WHERE id = ?",
        (rating, reorder, plate_id),
    )
    conn.commit()
    conn.close()
    return RedirectResponse(url=redirect_to, status_code=303)


# Dynamic Port Binding for Railway / Local Execution
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)