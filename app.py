import os
import uuid
from datetime import datetime
from math import radians, cos, sin, asin, sqrt
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import requests
from dotenv import load_dotenv
from PIL import Image, ExifTags
from flask_login import current_user, login_required
from flask_wtf.csrf import CSRFProtect






load_dotenv()

# ------------------ App Setup ------------------
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
csrf = CSRFProtect(app)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

db = SQLAlchemy(app)
migrate = Migrate(app, db)




GOOGLE_PLACES_API_KEY = os.getenv('GOOGLE_PLACES_API_KEY', '').strip()

# ------------------ Models ------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String, nullable=False, unique=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    plates = db.relationship('Plate', backref='user', lazy=True)
    likes = db.relationship('Like', backref='user', lazy=True)
    user_plates = db.relationship('UserPlate', back_populates='user')  # <-- fixedbackref='user', lazy=True)

class Restaurant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(200))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    plates = db.relationship('Plate', backref='restaurant', lazy=True)
    website = db.Column(db.String(255))  # <--- ADD THIS

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    # Only define relationship once
    plates = db.relationship('Plate', back_populates='category', lazy=True)


class Plate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    description = db.Column(db.Text)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    image_url = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurant.id'))

    comments = db.relationship('Comment', back_populates='plate', lazy=True)
    likes = db.relationship('Like', backref='plate', lazy=True)
    category = db.relationship('Category', back_populates='plates')
    user_plates = db.relationship('UserPlate', back_populates='plate')  # <-- fixed


class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    plate_id = db.Column(db.Integer, db.ForeignKey('plate.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'plate_id', name='unique_like'),)



class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    plate_id = db.Column(db.Integer, db.ForeignKey("plate.id"), nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")  # no backref to avoid conflicts
    plate = db.relationship("Plate", back_populates="comments")


class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    plate_id = db.Column(db.Integer, db.ForeignKey('plate.id'), nullable=False)


class UserPlate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    plate_id = db.Column(db.Integer, db.ForeignKey("plate.id"), nullable=False)
    liked = db.Column(db.Boolean, default=False)
    favorite = db.Column(db.Boolean, default=False)
    rated = db.Column(db.Integer)  # <-- Rating (can be NULL)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'plate_id', name='unique_user_plate'),
    )

    user = db.relationship("User", back_populates="user_plates")
    plate = db.relationship("Plate", back_populates="user_plates")

# ------------------ Helpers ------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def fix_orientation(img):
    try:
        for orientation in ExifTags.TAGS.keys():
            if ExifTags.TAGS[orientation] == 'Orientation':
                break
        exif = img._getexif()
        if exif is not None:
            exif = dict(exif.items())
            if exif.get(orientation) == 3:
                img = img.rotate(180, expand=True)
            elif exif.get(orientation) == 6:
                img = img.rotate(270, expand=True)
            elif exif.get(orientation) == 8:
                img = img.rotate(90, expand=True)
    except:
        pass
    return img

def process_uploaded_image(file, filename):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename))
    file.save(filepath)
    try:
        with Image.open(filepath) as img:
            img = fix_orientation(img)
            img = img.convert("RGB")
            img.thumbnail((1600, 1600), Image.LANCZOS)
            img.save(filepath, optimize=True, quality=85)
    except Exception as e:
        print("Image processing error:", e)
    return f"static/uploads/{filename}"


def haversine(lat1, lon1, lat2, lon2):
    """Calculate distance in miles between two lat/lon points."""
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    miles = 3958.8 * c
    return miles

def find_nearby_restaurants(lat, lon, radius_miles=2):
    if lat is None or lon is None:
        return []

    # Pre-filter using a bounding box (VERY fast)
    lat_mile = 1 / 69.0
    lon_mile = 1 / (69.0 * cos(radians(lat)))

    min_lat = lat - (radius_miles * lat_mile)
    max_lat = lat + (radius_miles * lat_mile)
    min_lon = lon - (radius_miles * lon_mile)
    max_lon = lon + (radius_miles * lon_mile)

    # SQL-only filtering
    candidates = Restaurant.query.filter(
        Restaurant.latitude.between(min_lat, max_lat),
        Restaurant.longitude.between(min_lon, max_lon)
    ).all()

    # Final check (much smaller list)
    return [
        r for r in candidates
        if haversine(lat, lon, r.latitude, r.longitude) <= radius_miles
    ]



def geocode_location(query):
    if not query:
        return None, None
    q = query.strip()
    if q.isdigit() and len(q) == 5:
        q = f"{q}, USA"
    if GOOGLE_PLACES_API_KEY:
        try:
            url = f"https://maps.googleapis.com/maps/api/geocode/json?address={requests.utils.quote(q)}&key={GOOGLE_PLACES_API_KEY}"
            r = requests.get(url, timeout=6).json()
            if r.get('status') == 'OK' and r.get('results'):
                loc = r['results'][0]['geometry']['location']
                return float(loc['lat']), float(loc['lng'])
        except:
            pass
    try:
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={requests.utils.quote(q)}"
        r = requests.get(url, headers={'User-Agent':'plater8te-app/1.0'}, timeout=6).json()
        if r and isinstance(r, list) and len(r) > 0:
            return float(r[0]['lat']), float(r[0]['lon'])
    except:
        pass
    return None, None

def seed_default_categories():
    default_categories = [
        # Mexican
        "Mexican", "Tacos", "Burritos", "Quesadillas", "Enchiladas", "Churros",
        # Italian
        "Italian", "Spaghetti", "Pizza", "Lasagna", "Ravioli", "Risotto",
        # Japanese
        "Japanese", "Sushi", "Ramen", "Tempura", "Udon", "Sashimi",
        # American
        "American", "Burgers", "Hot Dogs", "Fried Chicken", "Steak", "BBQ",
        # Chinese
        "Chinese", "Dumplings", "Sweet and Sour", "Kung Pao Chicken", "Lo Mein",
        # Indian
        "Indian", "Curry", "Tandoori", "Biryani", "Samosa", "Paneer",
        # Mediterranean
        "Mediterranean", "Gyros", "Falafel", "Hummus", "Shawarma", "Tabbouleh",
        # Thai
        "Thai", "Pad Thai", "Green Curry", "Tom Yum", "Spring Rolls",
        # Desserts
        "Dessert", "Ice Cream", "Cake", "Pie", "Brownies", "Macarons",
        # Breakfast / Brunch
        "Breakfast", "Pancakes", "Waffles", "Omelette", "French Toast",
        # Drinks
        "Beverages", "Smoothie", "Coffee", "Tea", "Milkshake", "Cocktail"
    ]

    for name in default_categories:
        if not Category.query.filter_by(name=name).first():
            cat = Category(name=name)
            db.session.add(cat)
    db.session.commit()
    print("Default categories seeded!")

def schedule_email_for_rating(plate_id, user_id):
    pass

def get_place_details(place_id):
    api_key = GOOGLE_PLACES_API_KEY
    if not api_key:
        return {}

    url = (
        "https://maps.googleapis.com/maps/api/place/details/json"
        f"?place_id={place_id}&fields=name,formatted_address,website&key={api_key}"
    )

    response = requests.get(url).json()
    if response.get("status") == "OK":
        result = response.get("result", {})
        return {
            "name": result.get("name"),
            "address": result.get("formatted_address"),
            "website": result.get("website")
        }

    return {}

from sqlalchemy import or_

from sqlalchemy import or_

def get_unrated_plates_for_user(user_id):
    """
    Returns Plate objects that are unrated for the given user.
    Includes:
      - Plates with UserPlate.rated == 0 or NULL
      - Plates with no UserPlate entry yet
    Eager-loads Restaurant and Category.
    Sets avg_rating = None for truly unrated plates.
    """
    plates = (
        db.session.query(Plate)
        .outerjoin(UserPlate, (UserPlate.plate_id == Plate.id) & (UserPlate.user_id == user_id))
        .options(
            db.joinedload(Plate.restaurant),
            db.joinedload(Plate.category),
            db.joinedload(Plate.user_plates)  # Load all user plates to compute avg_rating
        )
        .filter(
            or_(
                UserPlate.rated == 0,
                UserPlate.rated.is_(None),
                UserPlate.id.is_(None)  # No UserPlate record yet
            )
        )
        .all()
    )

    # Compute avg_rating for each plate
    for plate in plates:
        ratings = [up.rated for up in plate.user_plates if up.rated and up.rated > 0]
        plate.avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else None

    return plates







# ------------------ Home / Search ------------------
@app.route('/')
def home():
    category_id = request.args.get('category', type=int)
    location_query = request.args.get('location', '').strip()
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    radius_miles = request.args.get('radius', type=float) or 100
    user_id = session.get('user_id')

    # Base query
    plates_q = Plate.query.options(
        db.joinedload(Plate.restaurant),
        db.joinedload(Plate.category),
        db.joinedload(Plate.user_plates),
        db.joinedload(Plate.comments).joinedload(Comment.user)
    ).order_by(Plate.created_at.desc())

    if category_id:
        plates_q = plates_q.filter(Plate.category_id == category_id)

    plates = plates_q.all()

    for plate in plates:
        # Average rating
        ratings = [up.rated for up in plate.user_plates if up.rated is not None]
        plate.avg_rating = round(sum(ratings)/len(ratings), 1) if ratings else 0

        # Like count
        plate.like_count = sum(1 for up in plate.user_plates if up.liked)

        # User-specific flags
        if user_id:
            user_up = next((up for up in plate.user_plates if up.user_id == user_id), None)
            plate.user_liked = user_up.liked if user_up else False
            plate.user_favorited = user_up.favorite if user_up else False

        # Only keep comments with a valid user
        plate.comments = [c for c in plate.comments if c.user]

    # Location filtering
    if location_query or (lat and lon):
        if not (lat and lon):
            lat, lon = geocode_location(location_query)
        plates = [
            p for p in plates
            if p.restaurant and p.restaurant.latitude and haversine(lat, lon, p.restaurant.latitude, p.restaurant.longitude) <= radius_miles
        ]

    categories = Category.query.order_by(Category.name).all()
    return render_template('home.html', plates=plates, categories=categories)





@app.route('/plates')
@csrf.exempt
def search_plates():
    try:
        user_id = session.get('user_id')

        # --- Query params ---
        location = request.args.get('location', '').strip()
        category_id = request.args.get('category_id', type=int)
        radius_miles = float(request.args.get('radius', 10))  # default 10 miles
        show_unrated_only = request.args.get('unrated', type=int) == 1

        # Fetch all plates with restaurants preloaded
        plates = Plate.query.join(Restaurant).all()

        # Compute avg_rating and check if unrated for current user
        for plate in plates:
            # Ratings from all users
            ratings = [up.rated for up in plate.user_plates if up.rated and up.rated > 0]
            plate.avg_rating = sum(ratings) / len(ratings) if ratings else 0

            # Determine if this plate is unrated by current user
            if user_id:
                up = next((up for up in plate.user_plates if up.user_id == user_id), None)
                plate.is_unrated_for_user = up is None or up.rated is None
            else:
                plate.is_unrated_for_user = False

        filtered_plates = plates

        # --- Filter by category if provided ---
        if category_id:
            filtered_plates = [p for p in filtered_plates if p.category_id == category_id]

        # --- Filter by location if provided ---
        if location:
            lat, lon = geocode_location(location)
            if lat is None or lon is None:
                return render_template(
                    'home.html',
                    plates=[],
                    categories=Category.query.all(),
                    error=f"Could not find location '{location}'"
                )

            filtered_plates = [
                p for p in filtered_plates
                if p.restaurant and p.restaurant.latitude and p.restaurant.longitude and
                   haversine(lat, lon, p.restaurant.latitude, p.restaurant.longitude) <= radius_miles
            ]

        # --- Filter to only unrated plates if requested ---
        if show_unrated_only and user_id:
            filtered_plates = [p for p in filtered_plates if p.is_unrated_for_user]

        categories = Category.query.all()
        return render_template(
            'home.html',
            plates=filtered_plates,
            categories=categories,
            show_unrated_only=show_unrated_only
        )

    except Exception as e:
        print("Error in search_plates:", e)
        return render_template(
            'home.html',
            plates=[],
            categories=Category.query.all(),
            error='Server error'
        )




# ------------------ Auth ------------------
@app.route('/register', methods=['GET','POST'])
@csrf.exempt
def register():
    if request.method=='POST':
        username = request.form.get('username','').strip()
        email = request.form.get('email','').strip().lower()
        password = request.form.get('password','')
        if not (username and email and password):
            flash('Please fill all fields','danger')
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered','warning')
            return redirect(url_for('register'))
        user = User(username=username,email=email,password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        session['user_id']=user.id
        session['username']=user.username
        flash('Registered successfully!','success')
        return redirect(url_for('home'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
@csrf.exempt
def login():
    if request.method=='POST':
        email=request.form.get('email','').strip().lower()
        password=request.form.get('password','')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash,password):
            session['user_id']=user.id
            session['username']=user.username
            flash('Logged in successfully!','success')
            return redirect(url_for('home'))
        flash('Invalid credentials','danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully!','success')
    return redirect(url_for('home'))

# ------------------ Plate Creation ------------------
@app.route('/create_plate', methods=['GET', 'POST'])
@csrf.exempt
def create_plate():
    if 'user_id' not in session:
        flash("Login required", "error")
        return redirect(url_for('login'))

    if request.method == 'POST':
        user_id = session.get('user_id')
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        category_id = request.form.get('category_id', '').strip()
        restaurant_name = request.form.get('restaurant_name', '').strip()
        restaurant_address = request.form.get('restaurant_address', '').strip()
        restaurant_lat = request.form.get('restaurant_latitude', '').strip()
        restaurant_lon = request.form.get('restaurant_longitude', '').strip()

        # Validate required fields
        missing_fields = []
        if not name:
            missing_fields.append("Plate Name")
        if not category_id:
            missing_fields.append("Category")
        if not restaurant_name:
            missing_fields.append("Restaurant Name")
        if not restaurant_lat or not restaurant_lon:
            missing_fields.append("Restaurant Location")

        if missing_fields:
            flash(f"Please fill these fields: {', '.join(missing_fields)}", "error")
            return redirect(url_for('create_plate'))

        # Convert lat/lon to float safely
        try:
            restaurant_lat = float(restaurant_lat)
            restaurant_lon = float(restaurant_lon)
        except ValueError:
            flash("Invalid restaurant location. Use 'Use My Location' or select a valid restaurant.", "error")
            return redirect(url_for('create_plate'))

        # Find or create restaurant
        restaurant = Restaurant.query.filter_by(
            name=restaurant_name,
            latitude=restaurant_lat,
            longitude=restaurant_lon
        ).first()

        if not restaurant:
            restaurant = Restaurant(
                name=restaurant_name,
                address=restaurant_address,
                latitude=restaurant_lat,
                longitude=restaurant_lon
            )
            db.session.add(restaurant)
            db.session.commit()

        # Create plate
        plate = Plate(
            name=name,
            description=description,
            category_id=int(category_id),
            restaurant_id=restaurant.id,
            user_id=user_id
        )

        # Handle image
        file = request.files.get('image')
        if file and allowed_file(file.filename):
            ext = os.path.splitext(file.filename)[1].lower()
            filename = f"{uuid.uuid4().hex}{ext}"
            plate.image_url = process_uploaded_image(file, filename)

        db.session.add(plate)
        db.session.commit()

        # Add to UserPlate (unrated by default)
        user_plate = UserPlate(user_id=user_id, plate_id=plate.id)
        db.session.add(user_plate)
        db.session.commit()

        # Optionally schedule email for rating
        schedule_email_for_rating(plate.id, user_id)

        flash("Plate posted successfully!", "success")
        return redirect(url_for('home'))

    categories = Category.query.all()
    return render_template('create_plate.html', categories=categories)

# ------------------ Nearby Restaurants ------------------
@app.route('/nearby_restaurants')
@csrf.exempt
def nearby_restaurants():
    """
    Return nearby restaurants based on lat/lon or location query.
    Uses Google Places API if GOOGLE_PLACES_API_KEY is set, otherwise local DB with Haversine distance.
    Fast food restaurants are filtered out.
    """
    FAST_FOOD_KEYWORDS = [
        "McDonald's", "Burger King", "Wendy's", "KFC", "Taco Bell",
        "Subway", "Domino's", "Pizza Hut", "Chipotle", "Popeyes",
        "Arby's", "Jack in the Box", "Dairy Queen", "Little Caesars",
        "Dunkin'", "Dunkin", "Starbucks", "Five Guys", "In-N-Out", "Sonic"
    ]

    try:
        radius_meters = float(request.args.get('radius', 4000))  # default ~2.5 miles
        lat = request.args.get('lat', type=float)
        lon = request.args.get('lon', type=float)
        location = request.args.get('location', '').strip()

        # Geocode if location provided but no coordinates
        if location and (lat is None or lon is None):
            lat, lon = geocode_location(location)
            if lat is None or lon is None:
                return jsonify({'restaurants': [], 'error': f"Could not find location '{location}'"}), 400

        # Ensure coordinates are present
        if lat is None or lon is None:
            return jsonify({'restaurants': [], 'error': 'Missing latitude/longitude or location query'}), 400

        restaurants = []

        # --- Google Places API ---
        if GOOGLE_PLACES_API_KEY:
            next_page_token = None
            while True:
                url = (
                    "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
                    f"?location={lat},{lon}&radius={int(radius_meters)}&type=restaurant&key={GOOGLE_PLACES_API_KEY}"
                )
                if next_page_token:
                    url += f"&pagetoken={next_page_token}"
                    import time
                    time.sleep(2)  # short delay required by Google

                resp = requests.get(url, timeout=6).json()
                if resp.get('status') not in ('OK', 'ZERO_RESULTS'):
                    break

                for r in resp.get("results", []):
                    name = r.get("name", "")
                    # Skip fast food
                    if any(keyword.lower() in name.lower() for keyword in FAST_FOOD_KEYWORDS):
                        continue

                    loc = r['geometry']['location']
                    place_id = r.get('place_id')
                    website = None
                    # Fetch website via Place Details
                    if place_id:
                        try:
                            details_url = (
                                f"https://maps.googleapis.com/maps/api/place/details/json"
                                f"?place_id={place_id}&fields=name,formatted_address,website&key={GOOGLE_PLACES_API_KEY}"
                            )
                            details = requests.get(details_url, timeout=6).json()
                            if details.get("status") == "OK":
                                website = details.get("result", {}).get("website")
                        except:
                            pass

                    restaurants.append({
                        "name": name,
                        "latitude": loc.get("lat"),
                        "longitude": loc.get("lng"),
                        "address": r.get("vicinity", ""),
                        "website": website or ""
                    })

                next_page_token = resp.get("next_page_token")
                if not next_page_token:
                    break

        # --- Local DB fallback ---
        else:
            radius_miles = radius_meters / 1609.34
            all_restaurants = Restaurant.query.filter(
                Restaurant.latitude.isnot(None),
                Restaurant.longitude.isnot(None)
            ).all()
            for r in all_restaurants:
                # Skip fast food
                if any(keyword.lower() in r.name.lower() for keyword in FAST_FOOD_KEYWORDS):
                    continue
                dist = haversine(lat, lon, r.latitude, r.longitude)
                if dist <= radius_miles:
                    restaurants.append({
                        "name": r.name,
                        "latitude": r.latitude,
                        "longitude": r.longitude,
                        "address": r.address or "",
                        "website": r.website or ""
                    })

        return jsonify({
            "restaurants": restaurants,
            "lat": lat,
            "lon": lon,
            "count": len(restaurants)
        })

    except Exception as e:
        print("Nearby restaurants error:", e)
        return jsonify({'restaurants': [], 'error': 'Server error', 'detail': str(e)}), 500


@app.route('/add_restaurant', methods=['POST'])
@csrf.exempt
def add_restaurant():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Login required'}), 403

    data = request.get_json()
    name = data.get('name', '').strip()
    address = data.get('address', '').strip()
    city = data.get('city', '').strip()
    state = data.get('state', '').strip()
    website = data.get('website', '').strip()

    if not (name and address and city and state):
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400

    full_address = f"{address}, {city}, {state}"

    # Optionally geocode to store lat/lon
    lat, lon = geocode_location(full_address)

    restaurant = Restaurant(name=name, address=full_address, latitude=lat, longitude=lon, website=website)
    db.session.add(restaurant)
    db.session.commit()

    return jsonify({'success': True, 'restaurant_id': restaurant.id, 'name': restaurant.name})




# ------------------ Play / Swipe ------------------
@app.route('/play')
@csrf.exempt
def play():
    plates = Plate.query.order_by(Plate.created_at.desc()).limit(10).all()
    plates_data = [{"id":p.id,
                    "name":p.name,
                    "description":p.description or '',
                    "rating":0,
                    "image_url":p.image_url or url_for('static',filename='uploads/placeholder.png'),
                    "restaurant":{"name":p.restaurant.name if p.restaurant else ''}} for p in plates]
    return render_template('play.html', plates=plates_data)

@app.route('/get_plates_nearby')
@csrf.exempt
def get_plates_nearby():
    lat=request.args.get('lat')
    lon=request.args.get('lon')
    if not lat or not lon:
        return jsonify({'error':'Missing lat/lon'}),400
    lat,lon=float(lat),float(lon)
    radius_miles=float(request.args.get('radius_miles',20))
    nearby=[p for p in Plate.query.all() if p.restaurant and p.restaurant.latitude and haversine(lat,lon,p.restaurant.latitude,p.restaurant.longitude)<=radius_miles]
    plates_list=[{'id':p.id,'name':p.name,'description':p.description or '', 'image_url':p.image_url or url_for('static', filename='uploads/placeholder.png'), 'rating':0,'user':p.user.username if p.user else 'Unknown','restaurant_name':p.restaurant.name if p.restaurant else ''} for p in nearby[:10]]
    return jsonify({'plates':plates_list})

@app.route('/plate/<int:plate_id>/play_action', methods=['POST'])
@csrf.exempt
def play_action(plate_id):
    if 'user_id' not in session:
        return jsonify({'error':'not logged in'}),403
    payload = request.get_json(force=True, silent=True) or {}
    action = payload.get('action')
    if action in ('like','superlike'):
        if not Like.query.filter_by(user_id=session['user_id'], plate_id=plate_id).first():
            db.session.add(Like(user_id=session['user_id'], plate_id=plate_id))
            db.session.commit()
    return jsonify({'status':'ok','action':action})

@app.route('/plate/<int:plate_id>/swipe', methods=['POST'])
@csrf.exempt
def plate_swipe(plate_id):
    data=request.get_json(force=True, silent=True) or {}
    print(f"Swipe: user={session.get('user_id')} plate={plate_id} dir={data.get('direction')}")
    return jsonify({'status':'ok'})

# ------------------ User Plates ------------------
@app.route('/my_plates')
@csrf.exempt
def my_plates():
    if 'user_id' not in session:
        flash("Login required", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']

    # Get unrated UserPlate entries with eager-loaded Plate + Restaurant + Category
    user_plates = (
        UserPlate.query
        .filter(UserPlate.user_id == user_id)
        .join(UserPlate.plate)
        .options(
            db.joinedload(UserPlate.plate).joinedload(Plate.restaurant),
            db.joinedload(UserPlate.plate).joinedload(Plate.category)
        )
        .all()
    )

    plates = []
    for up in user_plates:
        # Only include unrated or unrated=0
        if up.rated is None or up.rated == 0:
            plate = up.plate
            # Set avg_rating to None for unrated
            plate.avg_rating = None
            # Include like/favorite info
            plate.user_liked = up.liked
            plate.user_favorited = up.favorite
            plates.append(plate)

    return render_template('my_plates.html', plates=plates)

@app.route('/favorites')
@csrf.exempt
def favorites():
    if 'user_id' not in session:
        flash("Login required", "error")
        return redirect(url_for('login'))
    user_id = session['user_id']
    favs = Plate.query.join(UserPlate, (UserPlate.plate_id == Plate.id) & (UserPlate.user_id == user_id)).filter(UserPlate.favorite == True).all()
    return render_template('favorites.html', plates=favs)

@app.route("/unrated_plates")
@csrf.exempt
def unrated_plates():
    if 'user_id' not in session:
        flash("Login required", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']

    # Fetch UserPlate entries that are unrated (None or 0)
    unrated_entries = (
        UserPlate.query
        .filter(UserPlate.user_id == user_id, or_(UserPlate.rated.is_(None), UserPlate.rated == 0))
        .join(UserPlate.plate)
        .options(
            db.joinedload(UserPlate.plate).joinedload(Plate.restaurant),
            db.joinedload(UserPlate.plate).joinedload(Plate.category)
        )
        .all()
    )

    plates = []
    for up in unrated_entries:
        plate = up.plate
        plate.avg_rating = None  # unrated
        plate.user_liked = up.liked
        plate.user_favorited = up.favorite
        plates.append(plate)

    return render_template("unrated_plates.html", plates=plates)

@app.route("/rate_plate/<int:plate_id>", methods=["GET", "POST"])
@csrf.exempt
def rate_plate(plate_id):
    if 'user_id' not in session:
        flash("Login required", "error")
        return redirect(url_for('login'))

    user_id = session['user_id']

    # Load plate + restaurant fully
    plate = (
        Plate.query
            .options(db.joinedload(Plate.restaurant))
            .get_or_404(plate_id)
    )

    # UserPlate entry for this user + plate
    user_plate = UserPlate.query.filter_by(user_id=user_id, plate_id=plate_id).first()

    if request.method == "POST":
        rating = int(request.form["rating"])
        description = request.form.get("description", "").strip()

        user_plate.rated = rating
        user_plate.description = description
        db.session.commit()

        return redirect(url_for("unrated_plates"))

    return render_template("rate_plate.html", plate=plate, user_plate=user_plate)

@app.route('/geocode_reverse')
@csrf.exempt
def geocode_reverse():
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    if lat is None or lon is None:
        return jsonify({'success': False, 'error': 'Missing lat/lon'})

    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&addressdetails=1"
        r = requests.get(url, headers={'User-Agent':'plater8te-app/1.0'}, timeout=6).json()
        addr = r.get('address', {})
        return jsonify({
            'success': True,
            'address': addr.get('road') or '',
            'city': addr.get('city') or addr.get('town') or addr.get('village') or '',
            'state': addr.get('state') or ''
        })
    except:
        return jsonify({'success': False, 'error': 'Could not resolve location'})


# ------------------ Like / Favorite / Comment ------------------
# Toggle Like
@app.route("/plates/<int:plate_id>/like", methods=["POST"])
@csrf.exempt
def toggle_like(plate_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "You must be logged in to like plates."}), 403

    plate = Plate.query.get_or_404(plate_id)

    # Find existing UserPlate for this user and plate
    up = UserPlate.query.filter_by(user_id=user_id, plate_id=plate_id).first()

    if up:
        # Toggle like
        up.liked = not up.liked
    else:
        # Create a new UserPlate with liked=True
        up = UserPlate(user_id=user_id, plate_id=plate_id, liked=True)
        db.session.add(up)

    db.session.commit()

    # Count total likes for this plate
    like_count = UserPlate.query.filter_by(plate_id=plate_id, liked=True).count()

    return jsonify({
        "liked": up.liked,
        "like_count": like_count
    })


# Toggle Favorite
@app.route("/plates/<int:plate_id>/favorite", methods=["POST"])
@csrf.exempt
def toggle_favorite(plate_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "You must be logged in to favorite plates."}), 403

    plate = Plate.query.get_or_404(plate_id)

    # Find existing UserPlate for this user and plate
    up = UserPlate.query.filter_by(user_id=user_id, plate_id=plate_id).first()

    if up:
        # Toggle favorite
        up.favorite = not up.favorite
    else:
        # Create a new UserPlate with favorite=True
        up = UserPlate(user_id=user_id, plate_id=plate_id, favorite=True)
        db.session.add(up)

    db.session.commit()

    return jsonify({
        "favorited": up.favorite
    })


@app.route("/plates/<int:plate_id>/comment", methods=["POST"])
@csrf.exempt
def add_comment(plate_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Login required"}), 403

    data = request.get_json()
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Comment cannot be empty"}), 400

    plate = Plate.query.get_or_404(plate_id)

    comment = Comment(user_id=user_id, plate_id=plate_id, text=text)
    db.session.add(comment)
    db.session.commit()

    return jsonify({
        "id": comment.id,
        "username": session.get("username"),
        "text": comment.text,
        "created_at": comment.created_at.strftime("%Y-%m-%d %H:%M")
    })




# ------------------ App Startup ------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_default_categories()
    app.run(debug=True)