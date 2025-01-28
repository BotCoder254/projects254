from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
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

# Initialize SocketIO
socketio = SocketIO(app)

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
    categories = mongo.db.menu.distinct('category')
    
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
    
    # Get top selling items
    top_items = list(mongo.db.menu.find().sort('orders_count', -1).limit(10))
    
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
        'data': [item.get('orders_count', 0) for item in top_items]
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
        data = request.form.to_dict()
        images = request.files.getlist('images')
        
        # Save images and get their URLs
        image_urls = []
        for image in images:
            if image:
                filename = secure_filename(image.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'menu', filename)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                image.save(filepath)
                image_urls.append(url_for('static', filename=f'uploads/menu/{filename}'))
        
        # Prepare menu item data
        menu_item = {
            'name': data['name'],
            'description': data['description'],
            'price': float(data['price']),
            'category': data['category'],
            'active': data['active'].lower() == 'true',
            'images': image_urls,
            'created_at': datetime.now(),
            'orders_count': 0
        }
        
        # Insert into database
        result = mongo.db.menu.insert_one(menu_item)
        
        # Emit menu update
        emit_menu_update()
        
        return jsonify({'success': True, 'item_id': str(result.inserted_id)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
            'category': data['category'],
            'active': data['active'].lower() == 'true',
            'images': image_urls,
            'updated_at': datetime.now()
        }
        
        mongo.db.menu.update_one(
            {'_id': ObjectId(item_id)},
            {'$set': updates}
        )
        
        # Emit menu update
        emit_menu_update()
        
        return jsonify({'success': True})
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
        emit_menu_update()
        
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
        emit_menu_update()
        
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
            'categories': len(mongo.db.menu.distinct('category')),
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

if __name__ == '__main__':
    socketio.run(app, debug=True) 