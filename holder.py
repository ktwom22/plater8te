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
