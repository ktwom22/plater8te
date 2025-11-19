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

load_dotenv()

# ------------------ App Setup ------------------
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

GOOGLE_PLACES_API_KEY = os.getenv('GOOGLE_PLACES_API_KEY', '').strip()
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# ------------------ Models ------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    plates = db.relationship('Plate', backref='user', lazy=True)
    likes = db.relationship('Like', backref='user', lazy=True)
    comments = db.relationship('Comment', backref='user', lazy=True)
    user_plates = db.relationship('UserPlate', backref='user', lazy=True)

class Restaurant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(200))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    plates = db.relationship('Plate', backref='restaurant', lazy=True)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    plates = db.relationship('Plate', backref='category_obj', lazy=True)

class Plate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    image_url = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurant.id'))
    comments = db.relationship('Comment', backref='plate', lazy=True)
    likes = db.relationship('Like', backref='plate', lazy=True)
    user_plates = db.relationship('UserPlate', backref='plate', lazy=True)

class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    plate_id = db.Column(db.Integer, db.ForeignKey('plate.id'))

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    plate_id = db.Column(db.Integer, db.ForeignKey('plate.id'))
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UserPlate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    plate_id = db.Column(db.Integer, db.ForeignKey("plate.id"))
    favorite = db.Column(db.Boolean, default=False)
    description = db.Column(db.Text, nullable=True)
    rated = db.Column(db.Integer, default=0)  # 0 = unrated
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ------------------ Helpers ------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def haversine(lat1, lon1, lat2, lon2):
    R = 3956  # miles
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2*asin(sqrt(a))*R

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
        if r and isinstance(r, list) and len(r)>0:
            return float(r[0]['lat']), float(r[0]['lon'])
    except:
        pass
    return None, None

def seed_default_categories():
    defaults = ["American", "BBQ", "Burgers", "Breakfast", "Brunch",
                "Chinese", "Thai", "Indian", "Italian", "Mexican",
                "Pizza", "Seafood", "Sushi", "Steakhouse",
                "Vegetarian", "Vegan", "Dessert"]
    for name in defaults:
        if not Category.query.filter_by(name=name).first():
            db.session.add(Category(name=name))
    db.session.commit()

def schedule_email_for_rating(plate_id, user_id):
    pass  # placeholder

# ------------------ Routes ------------------
@app.route('/')
def home():
    category_id = request.args.get('category', type=int)
    location_query = request.args.get('location','').strip()
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    radius_miles = request.args.get('radius_miles', type=float)

    plates_q = Plate.query.order_by(Plate.created_at.desc())
    if category_id:
        plates_q = plates_q.filter(Plate.category_id==category_id)
    plates = plates_q.all()

    if (lat and lon) or location_query:
        if not (lat and lon):
            geolat, geolon = geocode_location(location_query)
            if geolat is None:
                return render_template('home.html', plates=plates, categories=Category.query.order_by(Category.name).all())
            lat, lon = geolat, geolon
        else:
            lat, lon = float(lat), float(lon)
        radius_miles = radius_miles or 100
        plates = [p for p in plates if p.restaurant and p.restaurant.latitude and p.restaurant.longitude and haversine(lat, lon, p.restaurant.latitude, p.restaurant.longitude)<=radius_miles]

    return render_template('home.html', plates=plates, categories=Category.query.order_by(Category.name).all())

# ------------------ Auth ------------------
@app.route('/register', methods=['GET','POST'])
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

# ------------------ Create Plate ------------------
@app.route('/create_plate', methods=['GET','POST'])
def create_plate():
    if 'user_id' not in session:
        flash("Login required","error")
        return redirect(url_for('login'))

    if request.method=='POST':
        user_id = session.get('user_id')
        name = request.form.get('name')
        description = request.form.get('description')
        category_id = request.form.get('category_id')
        restaurant_name = request.form.get('restaurant_name')
        restaurant_address = request.form.get('restaurant_address')
        restaurant_lat = request.form.get('restaurant_latitude')
        restaurant_lon = request.form.get('restaurant_longitude')
        if not all([name, restaurant_name, restaurant_lat, restaurant_lon, category_id]):
            flash("Fill all fields","error")
            return redirect(url_for('create_plate'))

        restaurant = Restaurant.query.filter_by(name=restaurant_name, latitude=restaurant_lat, longitude=restaurant_lon).first()
        if not restaurant:
            restaurant = Restaurant(name=restaurant_name, address=restaurant_address, latitude=float(restaurant_lat), longitude=float(restaurant_lon))
            db.session.add(restaurant)
            db.session.commit()

        plate = Plate(name=name, description=description, category_id=int(category_id), restaurant_id=restaurant.id, user_id=user_id)

        file = request.files.get('image')
        if file and allowed_file(file.filename):
            ext = os.path.splitext(file.filename)[1]
            filename = f"{uuid.uuid4().hex}{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename))
            file.save(filepath)
            plate.image_url=f"static/uploads/{filename}"

        db.session.add(plate)
        db.session.commit()

        # Track creator
        user_plate = UserPlate(user_id=user_id, plate_id=plate.id)
        db.session.add(user_plate)
        db.session.commit()

        schedule_email_for_rating(plate.id, user_id)
        flash("Plate posted successfully!","success")
        return redirect(url_for('home'))

    categories = Category.query.all()
    return render_template('create_plate.html', categories=categories)

@app.route('/nearby_restaurants')
def nearby_restaurants():
    """
    Return nearby restaurants based on lat/lon or location query.
    If GOOGLE_PLACES_API_KEY is set, use Google Places API.
    Otherwise, use local database with Haversine distance.
    """
    try:
        # Get query params
        radius_meters = float(request.args.get('radius', 16000))  # default 10 miles
        lat = request.args.get('lat', type=float)
        lon = request.args.get('lon', type=float)
        location = request.args.get('location', '').strip()

        # Geocode if location provided but no coordinates
        if location and (lat is None or lon is None):
            lat, lon = geocode_location(location)
            if lat is None or lon is None:
                return jsonify({
                    'restaurants': [],
                    'error': f"Could not find location '{location}'"
                }), 400

        # Ensure coordinates are present
        if lat is None or lon is None:
            return jsonify({
                'restaurants': [],
                'error': 'Missing latitude/longitude or location query'
            }), 400

        restaurants = []

        # Use Google Places API if available
        if GOOGLE_PLACES_API_KEY:
            url = (
                f"https://maps.googleapis.com/maps/api/place/nearbysearch/json"
                f"?location={lat},{lon}&radius={int(radius_meters)}&type=restaurant&key={GOOGLE_PLACES_API_KEY}"
            )
            resp = requests.get(url, timeout=6).json()
            if resp.get('status') == 'OK':
                for r in resp.get('results', []):
                    loc = r['geometry']['location']
                    restaurants.append({
                        "name": r.get('name'),
                        "latitude": loc.get('lat'),
                        "longitude": loc.get('lng'),
                        "address": r.get('vicinity', '')
                    })
        else:
            # Fallback: use local DB
            radius_miles = radius_meters / 1609.34  # convert meters to miles
            all_restaurants = Restaurant.query.filter(Restaurant.latitude.isnot(None), Restaurant.longitude.isnot(None)).all()
            for r in all_restaurants:
                dist = haversine(lat, lon, r.latitude, r.longitude)
                if dist <= radius_miles:
                    restaurants.append({
                        "name": r.name,
                        "latitude": r.latitude,
                        "longitude": r.longitude,
                        "address": r.address or ''
                    })

        return jsonify({
            "restaurants": restaurants,
            "lat": lat,
            "lon": lon,
            "count": len(restaurants)
        })

    except Exception as e:
        return jsonify({'restaurants': [], 'error': 'Server error', 'detail': str(e)}), 500

# ------------------ Play / Swipe ------------------
@app.route('/play')
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
def plate_swipe(plate_id):
    data=request.get_json(force=True, silent=True) or {}
    print(f"Swipe: user={session.get('user_id')} plate={plate_id} dir={data.get('direction')}")
    return jsonify({'status':'ok'})

# ------------------ User Plates ------------------
@app.route('/my_plates')
def my_plates():
    if 'user_id' not in session:
        flash("Login required","error")
        return redirect(url_for('login'))
    user_id=session['user_id']
    unrated=db.session.query(Plate).join(UserPlate, (UserPlate.plate_id==Plate.id)&(UserPlate.user_id==user_id), isouter=True).filter((UserPlate.rated==False)|(UserPlate.rated==None)).all()
    return render_template('my_plates.html', plates=unrated)

@app.route('/favorites')
def favorites():
    if 'user_id' not in session:
        flash("Login required", "error")
        return redirect(url_for('login'))
    user_id = session['user_id']
    favs = Plate.query.join(UserPlate, (UserPlate.plate_id == Plate.id) & (UserPlate.user_id == user_id)).filter(UserPlate.favorite == True).all()
    return render_template('favorites.html', plates=favs)

@app.route("/unrated_plates")
def unrated_plates():
    if 'user_id' not in session:
        flash("Login required","error")
        return redirect(url_for('login'))
    user_id = session['user_id']
    unrated = UserPlate.query.filter_by(user_id=user_id, rated=0).all()
    return render_template("unrated_plates.html", plates=unrated)

@app.route("/rate_plate/<int:plate_id>", methods=["GET", "POST"])
def rate_plate(plate_id):
    if 'user_id' not in session:
        flash("Login required","error")
        return redirect(url_for('login'))
    user_id = session['user_id']
    plate = Plate.query.get_or_404(plate_id)
    user_plate = UserPlate.query.filter_by(user_id=user_id, plate_id=plate_id).first()
    if request.method == "POST":
        rating = int(request.form["rating"])
        description = request.form.get("description", "").strip()
        user_plate.rated = rating
        user_plate.description = description
        db.session.commit()
        return redirect(url_for("unrated_plates"))
    return render_template("rate_plate.html", plate=plate, user_plate=user_plate)

# ------------------ App Startup ------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_default_categories()
    app.run(debug=True)
