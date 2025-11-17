import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import requests

# ------------------ App Setup ------------------
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///plate_rating.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
migrate = Migrate(app, db)

GOOGLE_PLACES_API_KEY = "AIzaSyDq7N9Jwponn2TKsDZ4jqjei7xWm_6ctvA"
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
    created_at = db.Column(db.DateTime, server_default=db.func.now())
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
    created_at = db.Column(db.DateTime, server_default=db.func.now())

# ------------------ Helpers ------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ------------------ Routes ------------------
@app.route('/')
def home():
    plates = Plate.query.order_by(Plate.created_at.desc()).all()
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
            flash("You must be logged in to post a plate.", "error")
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
            flash("Please fill out all fields and select a restaurant.", "error")
            return redirect(url_for('create_plate'))

        restaurant = Restaurant.query.filter_by(
            name=restaurant_name,
            latitude=restaurant_lat,
            longitude=restaurant_lon
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

# ------------------ Plate Actions ------------------
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
    if text:
        comment = Comment(user_id=session['user_id'], plate_id=plate_id, text=text)
        db.session.add(comment)
        db.session.commit()
        return jsonify({'status': 'ok', 'username': session['username'], 'text': text})

    return jsonify({'status': 'error', 'message': 'Comment cannot be empty'}), 400

# ------------------ Nearby Restaurants ------------------
@app.route('/nearby_restaurants')
def nearby_restaurants():
    lat = request.args.get('lat')
    lon = request.args.get('lon')
    if not lat or not lon:
        return jsonify({'restaurants': [], 'error': 'Missing coordinates'}), 400

    radius_meters = 16000  # 10 miles
    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius={radius_meters}&type=restaurant&key={GOOGLE_PLACES_API_KEY}"
    response = requests.get(url).json()

    restaurants = []
    if response.get('status') == 'OK':
        for res in response.get('results', []):
            place_id = res.get('place_id')
            website = ''
            if place_id:
                details_url = f"https://maps.googleapis.com/maps/api/place/details/json?place_id={place_id}&fields=website&key={GOOGLE_PLACES_API_KEY}"
                details_resp = requests.get(details_url).json()
                website = details_resp.get('result', {}).get('website', '')

            restaurants.append({
                "name": res.get('name'),
                "latitude": res['geometry']['location']['lat'],
                "longitude": res['geometry']['location']['lng'],
                "address": res.get('vicinity'),
                "website": website
            })

    return jsonify({'restaurants': restaurants})

# ------------------ Run App ------------------
if __name__ == '__main__':
    app.run(debug=True)
