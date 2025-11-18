import os
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import requests
from geopy.geocoders import Nominatim
from math import radians, cos, sin, asin, sqrt

# ------------------ App Setup ------------------
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///plate_rating.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

GOOGLE_PLACES_API_KEY = "YOUR_GOOGLE_PLACES_API_KEY"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# ------------------ Models ------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    plates = db.relationship('Plate', backref='user', lazy=True)
    likes = db.relationship('Like', backref='user', lazy=True)
    comments = db.relationship('Comment', backref='user', lazy=True)

class Restaurant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(200))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    plates = db.relationship('Plate', backref='restaurant', lazy=True)

class Plate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50))
    rating = db.Column(db.Integer)
    image_url = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    restaurant_id = db.Column(db.Integer, db.ForeignKey('restaurant.id'))
    likes = db.relationship('Like', backref='plate', lazy=True)
    comments = db.relationship('Comment', backref='plate', lazy=True)

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

# ------------------ Helpers ------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def haversine(lat1, lon1, lat2, lon2):
    R = 3956  # miles
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

# ------------------ Routes ------------------

# Home / Feed
@app.route('/')
def home():
    plates_query = Plate.query.order_by(Plate.created_at.desc())
    plates = plates_query.all()
    return render_template('home.html', plates=plates)

# ------------------ Authentication ------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        if User.query.filter_by(email=email).first():
            flash('Email already registered.')
            return redirect(url_for('register'))
        user = User(username=username, email=email, password_hash=password)
        db.session.add(user)
        db.session.commit()
        session['user_id'] = user.id
        session['username'] = user.username
        flash('Registered successfully!')
        return redirect(url_for('home'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('Logged in successfully!')
            return redirect(url_for('home'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully!')
    return redirect(url_for('home'))

# ------------------ Create Plate ------------------
@app.route('/create_plate', methods=['GET', 'POST'])
def create_plate():
    if request.method == 'POST':
        user_id = session.get('user_id')
        if not user_id:
            flash("You must be logged in.", "error")
            return redirect(url_for('login'))
        name = request.form.get('name')
        description = request.form.get('description')
        category = request.form.get('category')
        rating = request.form.get('rating')
        restaurant_name = request.form.get('restaurant_name')
        restaurant_address = request.form.get('restaurant_address')
        restaurant_lat = request.form.get('restaurant_latitude')
        restaurant_lon = request.form.get('restaurant_longitude')
        if not all([name, restaurant_name, restaurant_lat, restaurant_lon]):
            flash("Fill all fields.", "error")
            return redirect(url_for('create_plate'))
        restaurant = Restaurant.query.filter_by(
            name=restaurant_name, latitude=restaurant_lat, longitude=restaurant_lon
        ).first()
        if not restaurant:
            restaurant = Restaurant(
                name=restaurant_name,
                address=restaurant_address,
                latitude=float(restaurant_lat),
                longitude=float(restaurant_lon)
            )
            db.session.add(restaurant)
            db.session.commit()
        plate = Plate(
            name=name,
            description=description,
            category=category,
            rating=int(rating) if rating else None,
            restaurant_id=restaurant.id,
            user_id=user_id
        )
        file = request.files.get('image')
        if file and allowed_file(file.filename):
            ext = os.path.splitext(file.filename)[1]
            filename = f"{uuid.uuid4().hex}{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename))
            file.save(filepath)
            plate.image_url = f"static/uploads/{filename}"
        db.session.add(plate)
        db.session.commit()
        flash("Plate posted successfully!", "success")
        return redirect(url_for('home'))
    return render_template('create_plate.html')

# ------------------ Like & Comment ------------------
@app.route('/plate/<int:plate_id>/like', methods=['POST'])
def like_plate(plate_id):
    if 'user_id' not in session:
        return jsonify({'error': 'not logged in'}), 403
    user_id = session['user_id']
    existing = Like.query.filter_by(user_id=user_id, plate_id=plate_id).first()
    if existing:
        db.session.delete(existing)
    else:
        db.session.add(Like(user_id=user_id, plate_id=plate_id))
    db.session.commit()
    count = Like.query.filter_by(plate_id=plate_id).count()
    return jsonify({'status': 'ok', 'like_count': count})

@app.route('/plate/<int:plate_id>/comment', methods=['POST'])
def comment_plate(plate_id):
    if 'user_id' not in session:
        return jsonify({'error': 'not logged in'}), 403
    text = request.form.get('text', '').strip()
    if not text:
        return jsonify({'status':'error','message':'Comment cannot be empty'}), 400
    comment = Comment(user_id=session['user_id'], plate_id=plate_id, text=text)
    db.session.add(comment)
    db.session.commit()
    return jsonify({'status':'ok','username':session['username'],'text':text})

# ------------------ Nearby Restaurants ------------------
@app.route('/nearby_restaurants')
def nearby_restaurants():
    radius_meters = float(request.args.get('radius', 16000))  # default 10 mi
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    location = request.args.get('location')  # zip or city,state

    if location and (not lat or not lon):
        location += ", USA"
        geocode_url = f"https://maps.googleapis.com/maps/api/geocode/json?address={location}&key={GOOGLE_PLACES_API_KEY}"
        geo_resp = requests.get(geocode_url).json()
        if geo_resp.get('status') != 'OK' or not geo_resp.get('results'):
            return jsonify({'restaurants': [], 'error': f"Location '{location}' not found."}), 400
        loc = geo_resp['results'][0]['geometry']['location']
        lat = loc['lat']
        lon = loc['lng']

    if not lat or not lon:
        return jsonify({'restaurants': [], 'error': 'Missing coordinates or location'}), 400

    places_url = (
        f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?"
        f"location={lat},{lon}&radius={int(radius_meters)}&type=restaurant&key={GOOGLE_PLACES_API_KEY}"
    )
    resp = requests.get(places_url).json()
    restaurants = []
    if resp.get('status') == 'OK':
        for r in resp.get('results', []):
            restaurants.append({
                "name": r.get('name'),
                "latitude": r['geometry']['location']['lat'],
                "longitude": r['geometry']['location']['lng'],
                "address": r.get('vicinity',''),
            })
    return jsonify({'restaurants': restaurants, 'lat': float(lat), 'lon': float(lon)})

# ------------------ Play: Rate the Plate ------------------
@app.route('/play')
def play():
    return render_template('play.html')

@app.route('/get_plates_nearby')
def get_plates_nearby():
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    if not lat or not lon:
        return jsonify({'error':'Missing lat/lon'}), 400
    lat = float(lat)
    lon = float(lon)
    radius_miles = 20
    plates_query = Plate.query.all()
    nearby = [p for p in plates_query if p.restaurant and haversine(lat, lon, p.restaurant.latitude, p.restaurant.longitude) <= radius_miles]
    plates_list = []
    for p in nearby[:10]:
        plates_list.append({
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'image_url': p.image_url,
            'rating': p.rating,
            'user': p.user.username if p.user else 'Unknown',
            'restaurant_name': p.restaurant.name if p.restaurant else '',
        })
    return jsonify({'plates': plates_list})

@app.route('/plate/<int:plate_id>/play_action', methods=['POST'])
def play_action(plate_id):
    if 'user_id' not in session:
        return jsonify({'error':'not logged in'}),403
    action = request.json.get('action')  # like, dislike, superlike
    if action == 'like' or action == 'superlike':
        existing = Like.query.filter_by(user_id=session['user_id'], plate_id=plate_id).first()
        if not existing:
            db.session.add(Like(user_id=session['user_id'], plate_id=plate_id))
            db.session.commit()
    return jsonify({'status':'ok','action':action})

# ------------------ Run App ------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
