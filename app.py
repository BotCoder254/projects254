from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_pymongo import PyMongo
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv
from bson.objectid import ObjectId
from datetime import datetime

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "your-secret-key")
app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://localhost:27017/food_ordering")

# Initialize MongoDB
mongo = PyMongo(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, user_data):
        self.user_data = user_data
        
    def get_id(self):
        return str(self.user_data['_id'])

@login_manager.user_loader
def load_user(user_id):
    user_data = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    return User(user_data) if user_data else None

# Routes
@app.route('/')
def index():
    featured_items = mongo.db.menu.find({'featured': True}).limit(4)
    categories = mongo.db.categories.find()
    return render_template('index.html', featured_items=featured_items, categories=categories)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = True if request.form.get('remember-me') else False
        
        if not email or not password:
            flash('Please fill in all fields')
            return redirect(url_for('login'))
        
        user = mongo.db.users.find_one({'email': email})
        
        if user and check_password_hash(user['password'], password):
            user_obj = User(user)
            login_user(user_obj, remember=remember)
            
            # Sync cart from localStorage if exists
            if 'cart' in request.form:
                try:
                    cart_data = request.form.get('cart')
                    mongo.db.users.update_one(
                        {'_id': user['_id']},
                        {'$set': {'cart': cart_data}}
                    )
                except:
                    pass
                    
            return redirect(url_for('index'))
        
        flash('Invalid email or password. Please check your credentials.')
        return redirect(url_for('login'))
    
    return render_template('auth/login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        name = request.form.get('name')
        
        # Validate required fields
        if not email or not password or not name:
            flash('All fields are required')
            return redirect(url_for('register'))
        
        # Check if email already exists
        if mongo.db.users.find_one({'email': email}):
            flash('Email already registered')
            return redirect(url_for('register'))
        
        # Validate password length
        if len(password) < 8:
            flash('Password must be at least 8 characters long')
            return redirect(url_for('register'))
        
        # Hash password and create user
        try:
            hashed_password = generate_password_hash(password)
            mongo.db.users.insert_one({
                'email': email,
                'password': hashed_password,
                'name': name
            })
            
            flash('Registration successful! Please login.')
            return redirect(url_for('login'))
        except Exception as e:
            flash('An error occurred during registration. Please try again.')
            return redirect(url_for('register'))
    
    return render_template('auth/register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/search')
def search():
    query = request.args.get('q', '')
    results = mongo.db.menu.find({
        '$or': [
            {'name': {'$regex': query, '$options': 'i'}},
            {'description': {'$regex': query, '$options': 'i'}},
            {'category': {'$regex': query, '$options': 'i'}}
        ]
    })
    return render_template('search_results.html', results=results, query=query)

@app.route('/menu')
def menu():
    # Get filter parameters
    category = request.args.get('category', '')
    dietary = request.args.get('dietary', '')
    sort = request.args.get('sort', 'name')
    search = request.args.get('search', '')

    # Build query
    query = {}
    if category:
        query['category'] = category
    if dietary:
        query['dietary_info.' + dietary] = True
    if search:
        query['$or'] = [
            {'name': {'$regex': search, '$options': 'i'}},
            {'description': {'$regex': search, '$options': 'i'}}
        ]

    # Get all categories and dietary preferences for filters
    categories = mongo.db.menu.distinct('category')
    dietary_preferences = ['vegetarian', 'vegan', 'gluten_free']

    # Sort options
    sort_field = 'price' if sort in ['price_asc', 'price_desc'] else 'name'
    sort_direction = -1 if sort == 'price_desc' else 1

    # Get menu items
    menu_items = mongo.db.menu.find(query).sort(sort_field, sort_direction)

    return render_template('menu.html', 
                         menu_items=menu_items,
                         categories=categories,
                         dietary_preferences=dietary_preferences,
                         current_category=category,
                         current_dietary=dietary,
                         current_sort=sort)

# Cart Routes
@app.route('/cart')
@login_required
def cart():
    return render_template('cart.html')

@app.route('/api/cart', methods=['GET'])
@login_required
def get_cart():
    user = mongo.db.users.find_one({'_id': ObjectId(current_user.get_id())})
    return jsonify(user.get('cart', []))

@app.route('/api/cart/sync', methods=['POST'])
@login_required
def sync_cart():
    try:
        cart_data = request.json
        mongo.db.users.update_one(
            {'_id': ObjectId(current_user.get_id())},
            {'$set': {'cart': cart_data}}
        )
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/cart/add', methods=['POST'])
@login_required
def add_to_cart():
    try:
        item_data = request.json
        user_id = ObjectId(current_user.get_id())
        
        # Update user's cart in MongoDB
        mongo.db.users.update_one(
            {'_id': user_id},
            {'$push': {'cart': item_data}}
        )
        
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/cart/remove', methods=['POST'])
@login_required
def remove_from_cart():
    try:
        item_id = request.json.get('item_id')
        user_id = ObjectId(current_user.get_id())
        
        # Remove item from user's cart in MongoDB
        mongo.db.users.update_one(
            {'_id': user_id},
            {'$pull': {'cart': {'id': item_id}}}
        )
        
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/cart/update-quantity', methods=['POST'])
@login_required
def update_cart_quantity():
    try:
        data = request.json
        item_id = data.get('item_id')
        quantity = data.get('quantity')
        user_id = ObjectId(current_user.get_id())
        
        # Update item quantity in user's cart
        mongo.db.users.update_one(
            {'_id': user_id, 'cart.id': item_id},
            {'$set': {'cart.$.quantity': quantity}}
        )
        
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

# Context processors
@app.context_processor
def utility_processor():
    return {
        'now': datetime.now()
    }

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('errors/500.html'), 500

if __name__ == '__main__':
    app.run(debug=True) 