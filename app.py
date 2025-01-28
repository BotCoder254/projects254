from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_pymongo import PyMongo
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv
from bson.objectid import ObjectId
from datetime import datetime, timedelta
from functools import wraps
from passlib.hash import sha256_crypt

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
    if current_user.is_authenticated and current_user.has_role('admin'):
        # Send initial stats to admin
        emit('stats_update', get_dashboard_stats())

@socketio.on('disconnect')
def handle_disconnect():
    pass

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
    return render_template('admin/menu.html',
                         menu_items=menu_items,
                         categories=categories)

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
    return jsonify(analytics_data)

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
    users = mongo.db.users.find()
    return render_template('admin/users.html', users=users)

# Add route to manage user roles (admin only)
@app.route('/api/admin/users/<user_id>/role', methods=['PUT'])
@login_required
@admin_required
def update_user_role(user_id):
    try:
        data = request.json
        new_role = data.get('role')
        
        if new_role not in ['admin', 'customer', 'staff']:
            return jsonify({'status': 'error', 'message': 'Invalid role'}), 400
            
        mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {'role': new_role}}
        )
        
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

if __name__ == '__main__':
    socketio.run(app, debug=True) 