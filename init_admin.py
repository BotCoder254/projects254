from pymongo import MongoClient
from pymongo.server_api import ServerApi
from werkzeug.security import generate_password_hash
from datetime import datetime
import os
from dotenv import load_dotenv
from passlib.hash import sha256_crypt
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

# Load environment variables
load_dotenv()

# MongoDB connection
uri = "mongodb+srv://teumteum776:soulmind254@cluster0.wxgbm.mongodb.net/food_ordering?retryWrites=true&w=majority&appName=Cluster0"

try:
    # Initialize MongoDB client
    client = MongoClient(uri, server_api=ServerApi('1'))
    
    # Test connection
    client.admin.command('ping')
    print("Successfully connected to MongoDB!")
    
    # Get database
    db = client.get_database("food_ordering")
    
    # Admin credentials
    admin_user = {
        'email': 'admin@foodiehub.com',
        'password': sha256_crypt.hash('admin123'),
        'name': 'Admin User',
        'role': 'admin',
        'created_at': datetime.now(),
        'is_active': True,
        'last_login': datetime.now(),
        'last_activity': datetime.now()
    }

    # Check if admin already exists
    existing_admin = db.users.find_one({'email': admin_user['email']})

    if existing_admin:
        print("Admin user already exists!")
    else:
        # Create admin user
        db.users.insert_one(admin_user)
        print("Admin user created successfully!")
        print("Email:", admin_user['email'])
        print("Password: admin123")

    # Initialize required collections if they don't exist
    required_collections = ['users', 'menu', 'orders', 'categories', 'user_actions', 'downloads']
    existing_collections = db.list_collection_names()

    for collection in required_collections:
        if collection not in existing_collections:
            db.create_collection(collection)
            print(f"Created {collection} collection")

    # Add sample categories if none exist
    if db.categories.count_documents({}) == 0:
        categories = [
            {'name': 'Pizza', 'icon': 'fa-pizza-slice', 'created_at': datetime.now()},
            {'name': 'Burgers', 'icon': 'fa-hamburger', 'created_at': datetime.now()},
            {'name': 'Salads', 'icon': 'fa-leaf', 'created_at': datetime.now()},
            {'name': 'Desserts', 'icon': 'fa-ice-cream', 'created_at': datetime.now()},
            {'name': 'Drinks', 'icon': 'fa-glass-martini', 'created_at': datetime.now()}
        ]
        db.categories.insert_many(categories)
        print("Added sample categories")

    # Initialize menu items with dietary info if needed
    menu_update_result = db.menu.update_many(
        {'dietary_info': {'$exists': False}},
        {'$set': {
            'dietary_info': {
                'vegetarian': False,
                'vegan': False,
                'gluten_free': False
            }
        }}
    )
    if menu_update_result.modified_count > 0:
        print(f"Updated {menu_update_result.modified_count} menu items with dietary info")

    print("\nInitialization complete!")
    print("You can now log in to the admin panel with:")
    print("Email: admin@foodiehub.com")
    print("Password: admin123")

except Exception as e:
    print(f"Error during initialization: {str(e)}")
    raise 