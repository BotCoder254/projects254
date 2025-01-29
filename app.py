from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort, make_response, session
from flask_pymongo import PyMongo
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv
from bson.objectid import ObjectId
from datetime import datetime, timedelta
from functools import wraps
from passlib.hash import sha256_crypt
from werkzeug.utils import secure_filename
import random
from pdf import PDF
import requests
import base64
import logging
import time

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "your-secret-key")
app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://localhost:27017/food_ordering")

# Configure upload folder with absolute path
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'menu'), exist_ok=True)

# Initialize MongoDB
mongo = PyMongo(app)

# Update existing menu items with default dietary_info
def init_menu_items():
    try:
        # Update all menu items that don't have dietary_info
        mongo.db.menu.update_many(
            {'dietary_info': {'$exists': False}},
            {'$set': {
                'dietary_info': {
                    'vegetarian': False,
                    'vegan': False,
                    'gluten_free': False
                }
            }}
        )
    except Exception as e:
        app.logger.error(f"Error updating menu items with dietary info: {str(e)}")

# Call initialization function
init_menu_items()

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize SocketIO
socketio = SocketIO(app)

# Configure logging
logging.basicConfig(level=logging.INFO)

class User(UserMixin):
    def __init__(self, user_data):
        self.user_data = user_data
        
    def get_id(self):
        return str(self.user_data['_id'])
    
    @property
    def role(self):
        return self.user_data.get('role', 'customer')
    
    def has_role(self, role):
        return self.role == role

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.has_role('admin'):
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

@login_manager.user_loader
def load_user(user_id):
    user_data = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    return User(user_data) if user_data else None

# Routes
@app.route('/')
def index():
    # Redirect admin users to admin dashboard
    if current_user.is_authenticated and current_user.has_role('admin'):
        return redirect(url_for('admin_dashboard'))
    
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
        
        if user and sha256_crypt.verify(password, user['password']):
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
            
            # Redirect admin users to admin dashboard
            if user.get('role') == 'admin':
                return redirect(url_for('admin_dashboard'))
                    
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
            hashed_password = sha256_crypt.hash(password)
            # Set default role as customer
            mongo.db.users.insert_one({
                'email': email,
                'password': hashed_password,
                'name': name,
                'role': 'customer',
                'created_at': datetime.now()
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

    # Get menu items and add default dietary_info if missing
    menu_items = list(mongo.db.menu.find(query).sort(sort_field, sort_direction))
    for item in menu_items:
        if 'dietary_info' not in item:
            item['dietary_info'] = {
                'vegetarian': False,
                'vegan': False,
                'gluten_free': False
            }

    return render_template('menu.html', 
                         menu_items=menu_items,
                         categories=categories,
                         dietary_preferences=dietary_preferences,
                         current_category=category,
                         current_dietary=dietary,
                         current_sort=sort)

# Cart Routes
@app.route('/cart')
def cart():
    try:
        # Get cart from session or initialize empty
        cart = session.get('cart', [])
        
        # Calculate total
        total = sum(float(item.get('price', 0)) * int(item.get('quantity', 0)) for item in cart)
        
        return render_template('cart.html', cart_items=cart, total=total)
    except Exception as e:
        app.logger.error(f"Error loading cart: {str(e)}")
        flash('Error loading cart', 'error')
        return redirect(url_for('menu'))

@app.route('/api/cart', methods=['GET'])
def get_cart():
    try:
        cart = session.get('cart', [])
        return jsonify(cart)
    except Exception as e:
        app.logger.error(f"Error getting cart: {str(e)}")
        return jsonify([])

@app.route('/api/cart/add', methods=['POST'])
def add_to_cart():
    try:
        item_data = request.json
        if not item_data:
            return jsonify({'status': 'error', 'message': 'No data provided'}), 400

        # Get existing cart or initialize empty
        cart = session.get('cart', [])
        
        # Check if item already exists
        existing_item = next((item for item in cart if item.get('id') == item_data.get('id')), None)
        
        if existing_item:
            # Update quantity if item exists
            existing_item['quantity'] = int(existing_item.get('quantity', 0)) + int(item_data.get('quantity', 1))
        else:
            # Add new item to cart
            cart.append({
                'id': item_data.get('id'),
                'name': item_data.get('name'),
                'price': float(item_data.get('price', 0)),
                'quantity': int(item_data.get('quantity', 1)),
                'image_url': item_data.get('image_url')
            })
        
        # Update session
        session['cart'] = cart
        
        # Emit cart update event
        socketio.emit('cart_update', {'cart': cart})
        
        return jsonify({'status': 'success', 'cart': cart})
    except Exception as e:
        app.logger.error(f"Error adding to cart: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/cart/sync', methods=['POST'])
def sync_cart():
    try:
        cart_data = request.json
        if cart_data is not None:
            session['cart'] = cart_data
            socketio.emit('cart_update', {'cart': cart_data})
            return jsonify({'status': 'success'})
        return jsonify({'status': 'error', 'message': 'Invalid cart data'}), 400
    except Exception as e:
        app.logger.error(f"Error syncing cart: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/cart/remove', methods=['POST'])
def remove_from_cart():
    try:
        item_id = request.json.get('item_id')
        if not item_id:
            return jsonify({'status': 'error', 'message': 'No item ID provided'}), 400
        
        # Get cart from session
        cart = session.get('cart', [])
        
        # Remove item from cart
        cart = [item for item in cart if item.get('id') != item_id]
        
        # Update session
        session['cart'] = cart
        
        # Emit cart update event
        socketio.emit('cart_update', {'cart': cart})
        
        return jsonify({'status': 'success', 'cart': cart})
    except Exception as e:
        app.logger.error(f"Error removing from cart: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

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

# Order Tracking Routes
@app.route('/order/<order_id>')
@login_required
def track_order(order_id):
    order = mongo.db.orders.find_one({'order_id': order_id})
    if not order:
        flash('Order not found')
        return redirect(url_for('index'))
    
    # Calculate progress based on status
    status_progress = {
        'confirmed': 25,
        'preparing': 50,
        'out_for_delivery': 75,
        'delivered': 100
    }
    progress = status_progress.get(order['status'], 0)
    
    # Calculate estimated delivery time
    base_time = order['created_at']
    if order['status'] == 'confirmed':
        estimated_time = "45-60 minutes"
        estimated_delivery_time = base_time + timedelta(minutes=60)
    elif order['status'] == 'preparing':
        estimated_time = "30-45 minutes"
        estimated_delivery_time = base_time + timedelta(minutes=45)
    elif order['status'] == 'out_for_delivery':
        estimated_time = "15-20 minutes"
        estimated_delivery_time = base_time + timedelta(minutes=20)
    else:
        estimated_time = "Delivered"
        estimated_delivery_time = base_time + timedelta(minutes=0)

    return render_template('order_tracking.html',
                         order=order,
                         progress=progress,
                         estimated_time=estimated_time,
                         estimated_delivery_time=estimated_delivery_time.isoformat())

# WebSocket event handlers
@socketio.on('connect')
def handle_connect():
    """Handle Socket.IO connection"""
    if current_user.is_authenticated and current_user.has_role('admin'):
        join_room('admin_analytics')
        # Send initial analytics data
        with app.app_context():
            data = get_realtime_user_data(
                datetime.now() - timedelta(days=1),
                datetime.now()
            )
            emit('user_activity', data, room='admin_analytics')

def emit_user_update():
    """Emit user activity updates to admin analytics"""
    with app.app_context():
        user_data = get_realtime_user_data(
            datetime.now() - timedelta(days=1),
            datetime.now()
        )
        socketio.emit('user_activity', user_data, room='admin_analytics')

@app.before_request
def track_user_activity():
    """Track user activity for analytics"""
    if current_user.is_authenticated:
        # Update user's last activity
        mongo.db.users.update_one(
            {'_id': ObjectId(current_user.get_id())},
            {'$set': {'last_activity': datetime.now()}}
        )
        
        # Record user action
        if request.endpoint:
            action_type = request.endpoint
            mongo.db.user_actions.insert_one({
                'user': current_user.get_id(),
                'action_type': action_type,
                'timestamp': datetime.now(),
                'details': {
                    'method': request.method,
                    'path': request.path,
                    'endpoint': request.endpoint
                }
            })
            
            # Emit update to admin analytics
            if action_type not in ['static', 'socket.io']:
                emit_user_update()

def get_dashboard_stats():
    """Get real-time dashboard statistics"""
    total_orders = mongo.db.orders.count_documents({})
    total_revenue = sum(order.get('total', 0) for order in mongo.db.orders.find())
    active_users = mongo.db.users.count_documents({'active': True})
    menu_items = mongo.db.menu.count_documents({})
    
    return {
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'active_users': active_users,
        'menu_items': menu_items
    }

def broadcast_order_update(order_id, status):
    """Broadcast order status updates to admin clients"""
    order = mongo.db.orders.find_one({'_id': ObjectId(order_id)})
    if order:
        socketio.emit('order_status_update', {
            'order_id': str(order['_id']),
            'status': status
        })
        # Update dashboard stats for all admin clients
        socketio.emit('stats_update', get_dashboard_stats())

@app.route('/api/admin/update-order-status', methods=['POST'])
@admin_required
def update_order_status():
    data = request.get_json()
    order_id = data.get('order_id')
    new_status = data.get('status')
    
    if not order_id or not new_status:
        return jsonify({'error': 'Missing required fields'}), 400
    
    try:
        mongo.db.orders.update_one(
            {'_id': ObjectId(order_id)},
            {'$set': {'status': new_status}}
        )
        broadcast_order_update(order_id, new_status)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/menu', methods=['GET'])
@admin_required
def get_menu_items():
    """Get all menu items for admin panel"""
    menu_items = list(mongo.db.menu.find())
    for item in menu_items:
        item['_id'] = str(item['_id'])
    return jsonify(menu_items)

def notify_new_order(order):
    """Notify admin clients of new orders"""
    socketio.emit('new_order', {
        'order_id': str(order['_id']),
        'total': order['total'],
        'status': order['status'],
        'created_at': order['created_at'].isoformat()
    })
    # Update dashboard stats for all admin clients
    socketio.emit('stats_update', get_dashboard_stats())

# Update the create_order function to notify admins
def create_order(order_data):
    """Create a new order and notify admin clients"""
    order = {
        'user_id': current_user.id,
        'items': order_data['items'],
        'total': order_data['total'],
        'status': 'confirmed',
        'created_at': datetime.utcnow()
    }
    result = mongo.db.orders.insert_one(order)
    order['_id'] = result.inserted_id
    notify_new_order(order)
    return str(result.inserted_id)

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

@app.errorhandler(403)
def forbidden(e):
    return render_template('errors/403.html'), 403

# Protect admin routes with the admin_required decorator
@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    # Calculate stats
    stats = {
        'total_orders': mongo.db.orders.count_documents({}),
        'total_revenue': sum(order.get('total', 0) for order in mongo.db.orders.find()),
        'active_users': mongo.db.users.count_documents({'last_login': {'$gte': datetime.now() - timedelta(days=30)}}),
        'menu_items': mongo.db.menu.count_documents({}),
        'active_items': mongo.db.menu.count_documents({'active': True}),
        'orders_growth': 15,  # Calculate from previous month
        'revenue_growth': 20,  # Calculate from previous month
        'users_growth': 10  # Calculate from previous month
    }
    
    # Get recent orders
    recent_orders = mongo.db.orders.find().sort('created_at', -1).limit(5)
    
    # Get popular items
    popular_items = mongo.db.menu.find().sort('orders_count', -1).limit(5)
    
    # Prepare chart data
    chart_data = {
        'labels': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        'sales': [150, 230, 180, 290, 200, 300, 250]
    }
    
    return render_template('admin/dashboard.html',
                         stats=stats,
                         recent_orders=recent_orders,
                         popular_items=popular_items,
                         chart_data=chart_data)

@app.route('/admin/menu')
@login_required
@admin_required
def admin_menu():
    menu_items = mongo.db.menu.find()
    categories = [category['name'] for category in mongo.db.categories.find()]
    
    # Calculate menu statistics
    stats = {
        'total_items': mongo.db.menu.count_documents({}),
        'active_items': mongo.db.menu.count_documents({'active': True}),
        'categories': len(categories),
    }
    
    # Get top seller safely
    try:
        top_seller = mongo.db.orders.aggregate([
            {'$unwind': '$items'},
            {'$group': {
                '_id': '$items.id',
                'name': {'$first': '$items.name'},
                'count': {'$sum': '$items.quantity'}
            }},
            {'$sort': {'count': -1}},
            {'$limit': 1}
        ]).next()
        stats['top_seller_orders'] = top_seller['count']
        stats['top_seller_name'] = top_seller['name']
    except StopIteration:
        stats['top_seller_orders'] = 0
        stats['top_seller_name'] = 'No orders yet'
    
    return render_template('admin/menu.html',
                         menu_items=menu_items,
                         categories=categories,
                         stats=stats)

@app.route('/admin/orders')
@login_required
@admin_required
def admin_orders():
    orders = mongo.db.orders.find().sort('created_at', -1)
    return render_template('admin/orders.html', orders=orders)

@app.route('/api/admin/analytics/range/<time_range>')
@login_required
@admin_required
def get_analytics_range(time_range):
    end_date = datetime.now()
    
    if time_range == 'today':
        start_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
    elif time_range == 'week':
        start_date = end_date - timedelta(days=7)
    elif time_range == 'month':
        start_date = end_date - timedelta(days=30)
    elif time_range == 'year':
        start_date = end_date - timedelta(days=365)
    else:
        return jsonify({'error': 'Invalid time range'}), 400
    
    # Get analytics data for the time range
    analytics_data = get_analytics_data(start_date, end_date)
    
    # Get real-time user data
    user_data = get_realtime_user_data(start_date, end_date)
    analytics_data.update(user_data)
    
    return jsonify(analytics_data)

def get_realtime_user_data(start_date, end_date):
    """Get real-time user activity data"""
    # Get active users in the current period
    active_users = mongo.db.users.count_documents({
        'last_activity': {'$gte': start_date, '$lte': end_date}
    })
    
    # Get active users in the previous period
    previous_start = start_date - (end_date - start_date)
    previous_active = mongo.db.users.count_documents({
        'last_activity': {'$gte': previous_start, '$lt': start_date}
    })
    
    # Calculate user growth
    users_growth = ((active_users - previous_active) / previous_active * 100) if previous_active > 0 else 0
    
    # Get user actions (last 24 hours)
    recent_actions = list(mongo.db.user_actions.find({
        'timestamp': {'$gte': datetime.now() - timedelta(hours=24)}
    }).sort('timestamp', -1).limit(50))
    
    # Get new vs returning users
    new_users = mongo.db.users.count_documents({
        'created_at': {'$gte': start_date, '$lte': end_date}
    })
    returning_users = active_users - new_users
    
    # Get user engagement metrics
    engagement_metrics = mongo.db.user_actions.aggregate([
        {'$match': {'timestamp': {'$gte': start_date, '$lte': end_date}}},
        {'$group': {
            '_id': '$action_type',
            'count': {'$sum': 1}
        }}
    ])
    
    return {
        'active_users': active_users,
        'users_growth': users_growth,
        'recent_actions': [{
            'user': action['user'],
            'action': action['action_type'],
            'timestamp': action['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
            'details': action.get('details', {})
        } for action in recent_actions],
        'user_metrics': {
            'new_users': new_users,
            'returning_users': returning_users,
            'engagement': list(engagement_metrics)
        }
    }

@app.route('/api/admin/analytics/filter', methods=['POST'])
@login_required
@admin_required
def filter_analytics():
    data = request.json
    start_date = datetime.strptime(data['start_date'], '%Y-%m-%d')
    end_date = datetime.strptime(data['end_date'], '%Y-%m-%d')
    
    # Get analytics data for the date range
    analytics_data = get_analytics_data(start_date, end_date)
    return jsonify(analytics_data)

def get_analytics_data(start_date, end_date):
    # Calculate analytics data
    orders = list(mongo.db.orders.find({
        'created_at': {'$gte': start_date, '$lte': end_date}
    }))
    
    total_orders = len(orders)
    total_revenue = sum(order.get('total', 0) for order in orders)
    avg_order_value = total_revenue / total_orders if total_orders > 0 else 0
    
    # Calculate growth percentages
    previous_period = end_date - (end_date - start_date)
    previous_orders = mongo.db.orders.count_documents({
        'created_at': {'$gte': previous_period, '$lt': start_date}
    })
    previous_revenue = sum(order.get('total', 0) for order in mongo.db.orders.find({
        'created_at': {'$gte': previous_period, '$lt': start_date}
    }))
    previous_avg_order = previous_revenue / previous_orders if previous_orders > 0 else 0
    
    revenue_growth = ((total_revenue - previous_revenue) / previous_revenue * 100) if previous_revenue > 0 else 0
    orders_growth = ((total_orders - previous_orders) / previous_orders * 100) if previous_orders > 0 else 0
    avg_order_growth = ((avg_order_value - previous_avg_order) / previous_avg_order * 100) if previous_avg_order > 0 else 0
    
    # Get active users and growth
    active_users = mongo.db.users.count_documents({
        'last_login': {'$gte': start_date}
    })
    previous_active_users = mongo.db.users.count_documents({
        'last_login': {'$gte': previous_period, '$lt': start_date}
    })
    users_growth = ((active_users - previous_active_users) / previous_active_users * 100) if previous_active_users > 0 else 0
    
    # Get revenue trend data
    days = (end_date - start_date).days + 1
    revenue_trend = {
        'labels': [(end_date - timedelta(days=x)).strftime('%b %d') for x in range(days-1, -1, -1)],
        'data': [0] * days
    }
    
    # Populate revenue trend data
    for order in orders:
        day_index = (order['created_at'].date() - start_date.date()).days
        if 0 <= day_index < days:
            revenue_trend['data'][day_index] += order.get('total', 0)
    
    # Get popular dishes
    pipeline = [
        {'$match': {'created_at': {'$gte': start_date, '$lte': end_date}}},
        {'$unwind': '$items'},
        {'$group': {
            '_id': '$items.id',
            'name': {'$first': '$items.name'},
            'units_sold': {'$sum': '$items.quantity'},
            'revenue': {'$sum': {'$multiply': ['$items.price', '$items.quantity']}}
        }},
        {'$sort': {'units_sold': -1}},
        {'$limit': 10}
    ]
    popular_items = list(mongo.db.orders.aggregate(pipeline))
    
    popular_dishes = {
        'labels': [item['name'] for item in popular_items],
        'data': [item['units_sold'] for item in popular_items]
    }
    
    # Get order activity by hour
    order_activity = {
        'labels': [f"{h:02d}:00" for h in range(24)],
        'data': [0] * 24
    }
    
    for order in orders:
        hour = order['created_at'].hour
        order_activity['data'][hour] += 1
    
    # Get user activity
    user_activity = {
        'labels': [(end_date - timedelta(days=x)).strftime('%b %d') for x in range(7, -1, -1)],
        'new_users': [0] * 8,
        'repeat_users': [0] * 8
    }
    
    # Populate user activity data
    for i in range(8):
        day = end_date - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        new_users = mongo.db.users.count_documents({
            'created_at': {'$gte': day_start, '$lte': day_end}
        })
        repeat_users = mongo.db.users.count_documents({
            'last_login': {'$gte': day_start, '$lte': day_end},
            'created_at': {'$lt': day_start}
        })
        
        user_activity['new_users'][7-i] = new_users
        user_activity['repeat_users'][7-i] = repeat_users
    
    return {
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'avg_order_value': avg_order_value,
        'revenue_growth': revenue_growth,
        'orders_growth': orders_growth,
        'avg_order_growth': avg_order_growth,
        'active_users': active_users,
        'users_growth': users_growth,
        'revenue_trend': revenue_trend,
        'popular_dishes': popular_dishes,
        'order_activity': order_activity,
        'user_activity': user_activity,
        'top_items': popular_items
    }

@app.route('/admin/analytics')
@login_required
@admin_required
def admin_analytics():
    # Calculate analytics data
    total_orders = mongo.db.orders.count_documents({})
    total_revenue = sum(order.get('total', 0) for order in mongo.db.orders.find())
    avg_order_value = total_revenue / total_orders if total_orders > 0 else 0
    
    # Calculate growth percentages (comparing to previous period)
    previous_orders = mongo.db.orders.count_documents({'created_at': {'$lt': datetime.now() - timedelta(days=30)}})
    previous_revenue = sum(order.get('total', 0) for order in mongo.db.orders.find({'created_at': {'$lt': datetime.now() - timedelta(days=30)}}))
    previous_avg_order = previous_revenue / previous_orders if previous_orders > 0 else 0
    
    revenue_growth = ((total_revenue - previous_revenue) / previous_revenue * 100) if previous_revenue > 0 else 0
    orders_growth = ((total_orders - previous_orders) / previous_orders * 100) if previous_orders > 0 else 0
    avg_order_growth = ((avg_order_value - previous_avg_order) / previous_avg_order * 100) if previous_avg_order > 0 else 0
    
    # Get active users count and growth
    active_users = mongo.db.users.count_documents({'last_login': {'$gte': datetime.now() - timedelta(days=30)}})
    previous_active_users = mongo.db.users.count_documents({'last_login': {'$lt': datetime.now() - timedelta(days=30), '$gte': datetime.now() - timedelta(days=60)}})
    users_growth = ((active_users - previous_active_users) / previous_active_users * 100) if previous_active_users > 0 else 0
    
    # Get top selling items with revenue
    pipeline = [
        {'$unwind': '$items'},
        {'$group': {
            '_id': '$items.id',
            'name': {'$first': '$items.name'},
            'orders_count': {'$sum': 1},
            'revenue': {'$sum': {'$multiply': ['$items.price', '$items.quantity']}}
        }},
        {'$sort': {'orders_count': -1}},
        {'$limit': 10}
    ]
    top_items = list(mongo.db.orders.aggregate(pipeline))
    
    # Get sales by category
    category_sales = list(mongo.db.orders.aggregate([
        {'$unwind': '$items'},
        {'$group': {
            '_id': '$items.category',
            'total': {'$sum': {'$multiply': ['$items.price', '$items.quantity']}}
        }}
    ]))
    
    # Prepare chart data
    revenue_trend = {
        'labels': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        'data': [150, 230, 180, 290, 200, 300, 250]
    }
    
    popular_dishes = {
        'labels': [item['name'] for item in top_items],
        'data': [item['orders_count'] for item in top_items]
    }
    
    order_activity = {
        'labels': ['0-12', '12-24', '24-36', '36-48', '48-60', '60-72', '72-84'],
        'data': [0, 0, 0, 0, 0, 0, 0]
    }
    
    user_activity = {
        'labels': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        'new_users': [0, 0, 0, 0, 0, 0, 0],
        'repeat_users': [0, 0, 0, 0, 0, 0, 0]
    }
    
    return render_template('admin/analytics.html',
                         total_orders=total_orders,
                         total_revenue=total_revenue,
                         avg_order_value=avg_order_value,
                         revenue_growth=revenue_growth,
                         orders_growth=orders_growth,
                         avg_order_growth=avg_order_growth,
                         active_users=active_users,
                         users_growth=users_growth,
                         top_items=top_items,
                         category_sales=category_sales,
                         revenue_trend=revenue_trend,
                         popular_dishes=popular_dishes,
                         order_activity=order_activity,
                         user_activity=user_activity)

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    # Get all users with pagination
    page = request.args.get('page', 1, type=int)
    per_page = 10
    skip = (page - 1) * per_page
    
    # Get users with their last activity and order count
    pipeline = [
        {
            '$lookup': {
                'from': 'orders',
                'localField': '_id',
                'foreignField': 'user_id',
                'as': 'orders'
            }
        },
        {
            '$addFields': {
                'total_orders': {'$size': '$orders'},
                'total_spent': {'$sum': '$orders.total'},
                'last_order_date': {'$max': '$orders.created_at'}
            }
        },
        {
            '$project': {
                'name': 1,
                'email': 1,
                'role': 1,
                'created_at': 1,
                'last_activity': 1,
                'total_orders': 1,
                'total_spent': 1,
                'last_order_date': 1,
                'status': {
                    '$cond': [
                        {'$gte': ['$last_activity', datetime.now() - timedelta(days=30)]},
                        'active',
                        'inactive'
                    ]
                }
            }
        },
        {'$skip': skip},
        {'$limit': per_page}
    ]
    
    users = list(mongo.db.users.aggregate(pipeline))
    total_users = mongo.db.users.count_documents({})
    
    # Get user statistics
    total_active = mongo.db.users.count_documents({
        'last_activity': {'$gte': datetime.now() - timedelta(days=30)}
    })
    new_users_today = mongo.db.users.count_documents({
        'created_at': {'$gte': datetime.now().replace(hour=0, minute=0, second=0)}
    })
    
    stats = {
        'total_users': total_users,
        'active_users': total_active,
        'new_users_today': new_users_today,
        'active_percentage': (total_active / total_users * 100) if total_users > 0 else 0
    }
    
    return render_template('admin/users.html',
                         users=users,
                         stats=stats,
                         page=page,
                         pages=(total_users + per_page - 1) // per_page)

@app.route('/api/admin/users/search')
@login_required
@admin_required
def search_users():
    query = request.args.get('q', '').strip()
    filter_by = request.args.get('filter', 'all')
    
    # Base query
    base_query = {}
    
    # Add search query if provided
    if query:
        base_query['$or'] = [
            {'name': {'$regex': query, '$options': 'i'}},
            {'email': {'$regex': query, '$options': 'i'}}
        ]
    
    # Add filter
    if filter_by == 'active':
        base_query['last_activity'] = {'$gte': datetime.now() - timedelta(days=30)}
    elif filter_by == 'inactive':
        base_query['last_activity'] = {'$lt': datetime.now() - timedelta(days=30)}
    elif filter_by == 'admin':
        base_query['role'] = 'admin'
    
    # Get users with their order data
    pipeline = [
        {'$match': base_query},
        {
            '$lookup': {
                'from': 'orders',
                'localField': '_id',
                'foreignField': 'user_id',
                'as': 'orders'
            }
        },
        {
            '$addFields': {
                'total_orders': {'$size': '$orders'},
                'total_spent': {'$sum': '$orders.total'},
                'last_order_date': {'$max': '$orders.created_at'}
            }
        },
        {
            '$project': {
                'name': 1,
                'email': 1,
                'role': 1,
                'created_at': 1,
                'last_activity': 1,
                'total_orders': 1,
                'total_spent': 1,
                'last_order_date': 1,
                'status': {
                    '$cond': [
                        {'$gte': ['$last_activity', datetime.now() - timedelta(days=30)]},
                        'active',
                        'inactive'
                    ]
                }
            }
        }
    ]
    
    users = list(mongo.db.users.aggregate(pipeline))
    return jsonify(users)

@app.route('/api/admin/users/<user_id>', methods=['PUT'])
@login_required
@admin_required
def update_user(user_id):
    data = request.json
    
    # Validate user exists
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Update allowed fields
    allowed_updates = {
        'name': data.get('name'),
        'email': data.get('email'),
        'role': data.get('role'),
        'status': data.get('status')
    }
    
    # Remove None values
    updates = {k: v for k, v in allowed_updates.items() if v is not None}
    
    if updates:
        mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': updates}
        )
        
        # Emit user update event
        emit_user_update()
        
        return jsonify({'message': 'User updated successfully'})
    
    return jsonify({'message': 'No updates provided'})

@app.route('/api/admin/users/<user_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_user(user_id):
    # Validate user exists
    user = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Delete user
    mongo.db.users.delete_one({'_id': ObjectId(user_id)})
    
    # Delete user's orders
    mongo.db.orders.delete_many({'user_id': ObjectId(user_id)})
    
    # Emit user update event
    emit_user_update()
    
    return jsonify({'message': 'User deleted successfully'})

@app.route('/api/admin/users/bulk-action', methods=['POST'])
@login_required
@admin_required
def bulk_user_action():
    try:
        data = request.json
        user_ids = data.get('user_ids', [])
        action = data.get('action')
        
        if not user_ids or not action:
            return jsonify({'error': 'Missing required parameters'}), 400
        
        # Convert string IDs to ObjectId
        object_ids = [ObjectId(uid) for uid in user_ids]
        
        if action == 'delete':
            # Delete users
            mongo.db.users.delete_many({'_id': {'$in': object_ids}})
            # Delete their orders
            mongo.db.orders.delete_many({'user_id': {'$in': object_ids}})
        elif action == 'activate':
            mongo.db.users.update_many(
                {'_id': {'$in': object_ids}},
                {'$set': {'status': 'active'}}
            )
        elif action == 'deactivate':
            mongo.db.users.update_many(
                {'_id': {'$in': object_ids}},
                {'$set': {'status': 'inactive'}}
            )
        
        # Emit user update event
        emit_user_update()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/users/stats', methods=['GET'])
@login_required
@admin_required
def get_user_stats():
    try:
        total_users = mongo.db.users.count_documents({})
        active_users = mongo.db.users.count_documents({
            'last_activity': {'$gte': datetime.now() - timedelta(days=30)}
        })
        new_users_today = mongo.db.users.count_documents({
            'created_at': {'$gte': datetime.now().replace(hour=0, minute=0, second=0)}
        })
        online_users = mongo.db.users.count_documents({
            'last_activity': {'$gte': datetime.now() - timedelta(minutes=5)}
        })
        
        stats = {
            'total_users': total_users,
            'active_users': active_users,
            'new_users_today': new_users_today,
            'online_users': online_users
        }
        
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/users/<user_id>/activity', methods=['GET'])
@login_required
@admin_required
def get_user_activity(user_id):
    try:
        # Get user's recent activity
        recent_actions = list(mongo.db.user_actions.find(
            {'user': user_id},
            {'_id': 0}
        ).sort('timestamp', -1).limit(10))
        
        # Format timestamps
        for action in recent_actions:
            action['timestamp'] = action['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify(recent_actions)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/users/<user_id>/orders', methods=['GET'])
@login_required
@admin_required
def get_user_orders(user_id):
    try:
        # Get user's orders
        orders = list(mongo.db.orders.find(
            {'user_id': ObjectId(user_id)},
            {'_id': 0}
        ).sort('created_at', -1).limit(10))
        
        # Format timestamps and ObjectIds
        for order in orders:
            order['created_at'] = order['created_at'].strftime('%Y-%m-%d %H:%M:%S')
            if 'items' in order:
                for item in order['items']:
                    item['id'] = str(item['id'])
        
        return jsonify(orders)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@socketio.on('user_connect')
def handle_user_connect():
    """Handle user connection for real-time updates"""
    if current_user.is_authenticated and current_user.has_role('admin'):
        join_room('admin_analytics')
        # Send initial user stats
        with app.app_context():
            stats = get_realtime_user_stats()
            emit('user_stats_update', stats, room='admin_analytics')

def get_realtime_user_stats():
    """Get real-time user statistics"""
    total_users = mongo.db.users.count_documents({})
    active_users = mongo.db.users.count_documents({
        'last_activity': {'$gte': datetime.now() - timedelta(days=30)}
    })
    new_users_today = mongo.db.users.count_documents({
        'created_at': {'$gte': datetime.now().replace(hour=0, minute=0, second=0)}
    })
    online_users = mongo.db.users.count_documents({
        'last_activity': {'$gte': datetime.now() - timedelta(minutes=5)}
    })
    
    return {
        'total_users': total_users,
        'active_users': active_users,
        'new_users_today': new_users_today,
        'online_users': online_users
    }

def emit_user_update():
    """Emit user update to admin clients"""
    with app.app_context():
        stats = get_realtime_user_stats()
        socketio.emit('user_stats_update', stats, room='admin_analytics')

# Menu API Routes
@app.route('/api/admin/menu', methods=['POST'])
@login_required
@admin_required
def add_menu_item():
    try:
        if 'images' not in request.files:
            return jsonify({'error': 'No images provided'}), 400

        data = request.form.to_dict()
        images = request.files.getlist('images')
        
        # Validate category
        category = data.get('category')
        if not category or not mongo.db.categories.find_one({'name': category}):
            return jsonify({'error': 'Invalid category selected'}), 400
        
        # Save images and get their URLs
        image_urls = []
        upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'menu')
        
        for image in images:
            if image and image.filename:
                try:
                    filename = secure_filename(image.filename)
                    if not filename:
                        continue
                    
                    filepath = os.path.join(upload_dir, filename)
                    image.save(filepath)
                    image_urls.append(url_for('static', filename=f'uploads/menu/{filename}'))
                except Exception as e:
                    app.logger.error(f"Error saving image {filename}: {str(e)}")
                    continue
        
        current_time = datetime.now()
        
        # Prepare menu item data
        menu_item = {
            'name': data.get('name', ''),
            'description': data.get('description', ''),
            'price': float(data.get('price', 0)),
            'category': category,
            'active': data.get('active', 'true').lower() == 'true',
            'images': image_urls,
            'created_at': current_time,
            'orders_count': 0,
            'dietary_info': {
                'vegetarian': data.get('vegetarian', 'false').lower() == 'true',
                'vegan': data.get('vegan', 'false').lower() == 'true',
                'gluten_free': data.get('gluten_free', 'false').lower() == 'true'
            }
        }
        
        # Insert into database
        result = mongo.db.menu.insert_one(menu_item)
        
        # Prepare response data
        response_item = menu_item.copy()
        response_item['_id'] = str(result.inserted_id)
        response_item['created_at'] = current_time.isoformat()
        
        # Emit menu update
        socketio.emit('menu_update', {'action': 'add', 'item': response_item})
        
        return jsonify({'success': True, 'item': response_item})
    except Exception as e:
        app.logger.error(f"Error adding menu item: {str(e)}")
        return jsonify({'error': 'An error occurred while saving the menu item', 'details': str(e)}), 500

@app.route('/api/admin/menu/<item_id>', methods=['GET'])
@login_required
@admin_required
def get_menu_item(item_id):
    try:
        item = mongo.db.menu.find_one({'_id': ObjectId(item_id)})
        if item:
            item['_id'] = str(item['_id'])
            return jsonify(item)
        return jsonify({'error': 'Item not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/menu/<item_id>', methods=['PUT'])
@login_required
@admin_required
def update_menu_item(item_id):
    try:
        data = request.form.to_dict()
        images = request.files.getlist('images')
        
        # Get existing item
        item = mongo.db.menu.find_one({'_id': ObjectId(item_id)})
        if not item:
            return jsonify({'error': 'Item not found'}), 404
        
        # Validate category
        category = data.get('category')
        if not category or not mongo.db.categories.find_one({'name': category}):
            return jsonify({'error': 'Invalid category selected'}), 400
        
        # Handle new images
        image_urls = item.get('images', [])
        for image in images:
            if image:
                filename = secure_filename(image.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'menu', filename)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                image.save(filepath)
                image_urls.append(url_for('static', filename=f'uploads/menu/{filename}'))
        
        # Update menu item
        updates = {
            'name': data['name'],
            'description': data['description'],
            'price': float(data['price']),
            'category': category,
            'active': data['active'].lower() == 'true',
            'images': image_urls,
            'updated_at': datetime.now(),
            'dietary_info': {
                'vegetarian': data.get('vegetarian', 'false').lower() == 'true',
                'vegan': data.get('vegan', 'false').lower() == 'true',
                'gluten_free': data.get('gluten_free', 'false').lower() == 'true'
            }
        }
        
        mongo.db.menu.update_one(
            {'_id': ObjectId(item_id)},
            {'$set': updates}
        )
        
        # Get updated item for response
        updated_item = mongo.db.menu.find_one({'_id': ObjectId(item_id)})
        updated_item['_id'] = str(updated_item['_id'])
        
        # Emit menu update
        socketio.emit('menu_update', {'action': 'update', 'item': updated_item})
        
        return jsonify({'success': True, 'item': updated_item})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/menu/<item_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_menu_item(item_id):
    try:
        # Check if item exists
        item = mongo.db.menu.find_one({'_id': ObjectId(item_id)})
        if not item:
            return jsonify({'error': 'Item not found'}), 404
        
        # Delete item
        mongo.db.menu.delete_one({'_id': ObjectId(item_id)})
        
        # Emit menu update
        socketio.emit('menu_update', {'action': 'delete', 'item_id': item_id})
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/menu/<item_id>/check-orders', methods=['GET'])
@login_required
@admin_required
def check_menu_item_orders(item_id):
    try:
        active_orders = mongo.db.orders.count_documents({
            'items.id': ObjectId(item_id),
            'status': {'$nin': ['delivered', 'cancelled']}
        })
        return jsonify({'active_orders': active_orders})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/menu/bulk-action', methods=['POST'])
@login_required
@admin_required
def bulk_menu_action():
    try:
        data = request.json
        item_ids = data.get('item_ids', [])
        action = data.get('action')
        
        if not item_ids or not action:
            return jsonify({'error': 'Missing required parameters'}), 400
        
        # Convert string IDs to ObjectId
        object_ids = [ObjectId(iid) for iid in item_ids]
        
        if action == 'delete':
            mongo.db.menu.delete_many({'_id': {'$in': object_ids}})
        elif action == 'activate':
            mongo.db.menu.update_many(
                {'_id': {'$in': object_ids}},
                {'$set': {'active': True}}
            )
        elif action == 'deactivate':
            mongo.db.menu.update_many(
                {'_id': {'$in': object_ids}},
                {'$set': {'active': False}}
            )
        
        # Emit menu update
        socketio.emit('menu_update', {'action': 'bulk', 'item_ids': item_ids, 'action': action})
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/menu/search', methods=['GET'])
@login_required
@admin_required
def search_menu_items():
    try:
        query = request.args.get('q', '').strip()
        category = request.args.get('category', 'all')
        
        # Build search query
        search_query = {}
        if query:
            search_query['$or'] = [
                {'name': {'$regex': query, '$options': 'i'}},
                {'description': {'$regex': query, '$options': 'i'}}
            ]
        if category != 'all':
            # Verify category exists
            if mongo.db.categories.find_one({'name': category}):
                search_query['category'] = category
        
        # Get matching items
        items = list(mongo.db.menu.find(search_query))
        
        # Convert ObjectId to string
        for item in items:
            item['_id'] = str(item['_id'])
        
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def emit_menu_update():
    """Emit menu update to all admin clients"""
    with app.app_context():
        menu_stats = {
            'total_items': mongo.db.menu.count_documents({}),
            'active_items': mongo.db.menu.count_documents({'active': True}),
            'categories': mongo.db.categories.count_documents({}),
        }
        
        # Get top seller
        try:
            top_seller = mongo.db.orders.aggregate([
                {'$unwind': '$items'},
                {'$group': {
                    '_id': '$items.id',
                    'name': {'$first': '$items.name'},
                    'count': {'$sum': '$items.quantity'}
                }},
                {'$sort': {'count': -1}},
                {'$limit': 1}
            ]).next()
            menu_stats['top_seller_orders'] = top_seller['count']
            menu_stats['top_seller_name'] = top_seller['name']
        except StopIteration:
            menu_stats['top_seller_orders'] = 0
            menu_stats['top_seller_name'] = 'No orders yet'
        
        socketio.emit('menu_update', {'stats': menu_stats}, room='admin_analytics')

# Configure upload folder
app.config['UPLOAD_FOLDER'] = os.path.join(app.static_folder, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create upload folders if they don't exist
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'menu'), exist_ok=True)

@app.route('/payment', methods=['GET'])
def payment():
    cart = session.get('cart', [])
    if not cart:
        flash('Your cart is empty', 'error')
        return redirect(url_for('menu'))
    
    total = sum(item['price'] * item['quantity'] for item in cart)
    return render_template('payment.html', cart=cart, total=total)

def get_access_token():
    """Generate OAuth access token."""
    consumer_key = "frmypHgIJYc7mQuUu5NBvnYc0kF1StP3"  # Updated consumer key
    consumer_secret = "UAeJAJLNUkV5MLpL"
    url = "https://api.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    
    try:
        # Create auth string and encode to base64
        auth_string = f"{consumer_key}:{consumer_secret}"
        auth_bytes = auth_string.encode('ascii')
        auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
        
        headers = {
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        logging.info("Requesting access token with headers: %s", headers)
        response = requests.get(url, headers=headers, verify=True)
        
        if response.status_code != 200:
            logging.error("Access token request failed. Status: %d, Response: %s", 
                        response.status_code, response.text)
            raise Exception(f"Failed to get access token: {response.text}")
            
        token_data = response.json()
        if 'access_token' not in token_data:
            logging.error("Access token not found in response: %s", token_data)
            raise Exception("Access token not found in response")
            
        logging.info("Successfully obtained access token")
        return token_data['access_token']
        
    except requests.exceptions.RequestException as e:
        logging.error("Network error getting access token: %s", str(e))
        raise Exception(f"Network error: {str(e)}")
    except Exception as e:
        logging.error("Unexpected error getting access token: %s", str(e))
        raise

@app.route('/process-payment', methods=['POST'])
def process_payment():
    """Process payment using M-Pesa STK Push."""
    try:
        logging.info("Received payment request: %s", request.json)
        data = request.get_json()
        if not data or 'phone' not in data or 'amount' not in data:
            return jsonify({
                'success': False,
                'message': 'Missing required fields'
            }), 400

        phone_number = str(data['phone']).strip()
        amount = data['amount']

        # Format phone number
        phone_number = phone_number.replace('+', '').replace(' ', '')
        phone_number = ''.join(filter(str.isdigit, phone_number))
        if not phone_number.startswith('254'):
            phone_number = '254' + phone_number.lstrip('0')

        # Get access token
        access_token = get_access_token()
        url = "https://api.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        
        password_str = f"4121151{'68cb945afece7b529b4a0901b2d8b1bb3bd9daa19bfdb48c69bec8dde962a932'}{timestamp}"
        password = base64.b64encode(password_str.encode()).decode('utf-8')

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        payload = {
            "BusinessShortCode": "4121151",
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": phone_number,
            "PartyB": "4121151",
            "PhoneNumber": phone_number,
            "CallBackURL": "https://github.com/BotCoder254",
            "AccountReference": "KIOTA",
            "TransactionDesc": "Food Order Payment"
        }

        logging.info("Sending STK push request with payload: %s", payload)
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        logging.info("STK push response: %s", result)

        if result.get('ResponseCode') == "0":
            # Store checkout request ID for later verification
            session['checkout_request_id'] = result.get('CheckoutRequestID')
            return jsonify({
                'success': True,
                'message': 'Payment initiated successfully',
                'checkoutRequestId': result.get('CheckoutRequestID')
            })
        else:
            return jsonify({
                'success': False,
                'status': 'FAILED',
                'message': 'Failed to initiate payment: ' + result.get('ResponseDescription', 'Unknown error')
            }), 400

    except requests.exceptions.RequestException as e:
        logging.error(f"Payment error: {str(e)}")
        return jsonify({
            'success': False,
            'message': f"Payment request failed: {str(e)}"
        }), 500
    except Exception as e:
        logging.error(f"Unexpected error in payment processing: {str(e)}")
        return jsonify({
            'success': False,
            'message': f"An unexpected error occurred: {str(e)}"
        }), 500

@app.route('/check-payment-status', methods=['POST'])
def check_payment_status():
    """Check payment status using M-Pesa query."""
    try:
        logging.info("Received query request: %s", request.json)
        data = request.get_json()
        checkout_request_id = data.get('checkoutRequestId')
        
        if not checkout_request_id:
            logging.error('Missing checkoutRequestId parameter')
            return jsonify({
                'ResponseCode': '1',
                'ResultCode': '1',
                'ResultDesc': 'Missing checkoutRequestId parameter',
                'errorMessage': 'Missing checkoutRequestId parameter'
            }), 200

        # Get access token
        access_token = get_access_token()
        url = "https://api.safaricom.co.ke/mpesa/stkpushquery/v1/query"
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        
        password_str = f"4121151{'68cb945afece7b529b4a0901b2d8b1bb3bd9daa19bfdb48c69bec8dde962a932'}{timestamp}"
        password = base64.b64encode(password_str.encode()).decode('utf-8')

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        payload = {
            "BusinessShortCode": "4121151",
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id
        }

        logging.info("Making query request: url=%s, payload=%s", url, payload)
        response = requests.post(url, json=payload, headers=headers)
        
        # Handle response
        if response.status_code == 200:
            result = response.json()
            logging.info("Query response: %s", result)
            
            # Check for cancellation
            if result.get('ResultCode') == '1032':
                return jsonify({
                    'ResponseCode': '3',
                    'ResultCode': '1032',
                    'ResultDesc': 'Transaction canceled by user',
                    'errorMessage': 'Transaction was canceled',
                    'isCanceled': True
                }), 200
            
            # Check for successful payment
            if result.get('ResultCode') == '0':
                # Create order
                cart = session.get('cart', [])
                # Convert any ObjectId in cart items to string
                for item in cart:
                    if 'id' in item and isinstance(item['id'], ObjectId):
                        item['id'] = str(item['id'])
                
                total = sum(float(item['price']) * int(item['quantity']) for item in cart)
                current_time = datetime.now()
                
                order = {
                    'number': 'ORD' + str(random.randint(10000, 99999)),
                    'user_id': str(current_user.get_id()) if not current_user.is_anonymous else None,
                    'items': cart,
                    'total': total,
                    'payment': {
                        'method': 'mpesa',
                        'transaction_id': result.get('MpesaReceiptNumber'),
                        'phone': result.get('PhoneNumber'),
                        'amount': total,
                        'status': 'completed',
                        'checkout_request_id': checkout_request_id
                    },
                    'status': 'pending',
                    'created_at': current_time.strftime('%Y-%m-%d %H:%M:%S')
                }
                
                # Save order and update session
                order_result = mongo.db.orders.insert_one(order)
                order_id = str(order_result.inserted_id)
                
                session['last_order'] = {
                    'number': order['number'],
                    'total': total,
                    '_id': order_id
                }
                session.pop('cart', None)
                
                # Prepare socket order data
                socket_order = {
                    **order,
                    '_id': order_id,
                    'created_at': current_time.strftime('%Y-%m-%d %H:%M:%S')
                }
                
                # Notify admin
                socketio.emit('new_order', {'order': socket_order}, room='admin')
                
                return jsonify({
                    **result,
                    'ResponseCode': result.get('ResponseCode', '0'),
                    'success': True,
                    'status': 'COMPLETED',
                    'message': 'Payment completed successfully',
                    'order': {
                        'id': order_id,
                        'number': order['number']
                    },
                    'redirect_url': url_for('order_confirmation')
                }), 200
            
            # Check for processing status
            error_code = result.get('errorCode')
            if error_code == '500.001.1001':
                return jsonify({
                    'ResponseCode': '2',
                    'ResultCode': '2',
                    'ResultDesc': 'The transaction is being processed',
                    'errorMessage': result.get('errorMessage', 'Payment is processing'),
                    'isProcessing': True
                }), 200
            
            # Return the original response for other cases
            return jsonify({
                **result,
                'ResponseCode': result.get('ResponseCode', '1')
            }), 200
            
        else:
            logging.error("M-Pesa API error response: %s", response.text)
            return jsonify({
                'ResponseCode': '1',
                'ResultCode': '1',
                'ResultDesc': 'Failed to check payment status',
                'errorMessage': response.text
            }), 200

    except Exception as e:
        logging.error("Query error: %s", str(e))
        return jsonify({
            'ResponseCode': '1',
            'ResultCode': '1',
            'ResultDesc': str(e) or 'Failed to check payment status',
            'errorMessage': str(e) or 'Payment query failed'
        }), 200

@app.route('/order-confirmation')
def order_confirmation():
    try:
        last_order = session.get('last_order')
        if not last_order or not last_order.get('_id'):
            flash('No order found', 'error')
            return redirect(url_for('menu'))
        
        # Get full order details from database
        order = mongo.db.orders.find_one({'_id': ObjectId(last_order['_id'])})
        if not order:
            flash('Order not found', 'error')
            return redirect(url_for('menu'))
        
        # Convert ObjectId to string
        order['_id'] = str(order['_id'])
        
        # Ensure items is a list
        if 'items' not in order or not order['items']:
            order['items'] = []
        elif isinstance(order['items'], dict):
            order['items'] = [order['items']]
        
        # Convert any ObjectId in items to string
        for item in order['items']:
            if 'id' in item and isinstance(item['id'], ObjectId):
                item['id'] = str(item['id'])
        
        # Format dates
        if 'created_at' in order:
            if isinstance(order['created_at'], str):
                try:
                    order['created_at'] = datetime.strptime(order['created_at'], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    order['created_at'] = datetime.now()
            elif not isinstance(order['created_at'], datetime):
                order['created_at'] = datetime.now()
        
        # Ensure total exists
        if 'total' not in order:
            order['total'] = sum(float(item.get('price', 0)) * int(item.get('quantity', 0)) for item in order['items'])
        
        # Ensure payment info exists
        if 'payment' not in order:
            order['payment'] = {
                'method': 'mpesa',
                'status': 'completed'
            }
        
        return render_template('order-confirmation.html', order=order)
        
    except Exception as e:
        logging.error(f"Error in order confirmation: {str(e)}")
        flash('Error loading order confirmation', 'error')
        return redirect(url_for('menu'))

@app.route('/download-receipt/<order_id>')
def download_receipt(order_id):
    try:
        # Get order details
        order = mongo.db.orders.find_one({'_id': ObjectId(order_id)})
        if not order:
            abort(404)
            
        # Generate PDF receipt
        pdf = PDF()
        pdf.add_page()
        
        # Header
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(0, 10, 'Order Receipt', 0, 1, 'C')
        pdf.ln(10)
        
        # Order details
        pdf.set_font('Arial', '', 12)
        pdf.cell(0, 10, f"Order Number: {order['number']}", 0, 1)
        pdf.cell(0, 10, f"Date: {order['created_at'].strftime('%Y-%m-%d %H:%M')}", 0, 1)
        pdf.ln(10)
        
        # Items
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(90, 10, 'Item', 1)
        pdf.cell(30, 10, 'Quantity', 1)
        pdf.cell(30, 10, 'Price', 1)
        pdf.cell(40, 10, 'Total', 1)
        pdf.ln()
        
        pdf.set_font('Arial', '', 12)
        for item in order['items']:
            pdf.cell(90, 10, item['name'], 1)
            pdf.cell(30, 10, str(item['quantity']), 1)
            pdf.cell(30, 10, f"${item['price']:.2f}", 1)
            pdf.cell(40, 10, f"${item['price'] * item['quantity']:.2f}", 1)
            pdf.ln()
        
        # Total
        pdf.ln(10)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(150, 10, 'Total:', 0)
        pdf.cell(40, 10, f"${order['total']:.2f}", 0)
        
        # Payment details
        pdf.ln(20)
        pdf.set_font('Arial', 'B', 12)
        pdf.cell(0, 10, 'Payment Information', 0, 1)
        pdf.set_font('Arial', '', 12)
        pdf.cell(0, 10, f"Method: M-Pesa", 0, 1)
        pdf.cell(0, 10, f"Transaction ID: {order['payment']['transaction_id']}", 0, 1)
        
        # Generate the PDF
        response = make_response(pdf.output(dest='S').encode('latin1'))
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=receipt_{order["number"]}.pdf'
        
        return response
        
    except Exception as e:
        app.logger.error(f"Error generating receipt: {str(e)}")
        abort(500)

if __name__ == '__main__':
    socketio.run(app, debug=True) 