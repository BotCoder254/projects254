from pymongo import MongoClient
from werkzeug.security import generate_password_hash
from datetime import datetime
import os
from dotenv import load_dotenv
from passlib.hash import sha256_crypt

# Load environment variables
load_dotenv()

# MongoDB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/food_ordering")
client = MongoClient(MONGO_URI)
db = client.get_database()

# Admin credentials
admin_user = {
    'email': 'admin@foodiehub.com',
    'password': sha256_crypt.hash('admin123'),  # Using SHA256 instead
    'name': 'Admin User',
    'role': 'admin',
    'created_at': datetime.now(),
    'is_active': True,
    'last_login': datetime.now()
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
    print("Password: admin123")  # Change this to match the password above

# Initialize required collections if they don't exist
collections = ['menu', 'orders', 'categories']
for collection in collections:
    if collection not in db.list_collection_names():
        db.create_collection(collection)
        print(f"Created {collection} collection")

# Add some sample categories if none exist
if db.categories.count_documents({}) == 0:
    categories = [
        {'name': 'Pizza', 'icon': 'fa-pizza-slice'},
        {'name': 'Burgers', 'icon': 'fa-hamburger'},
        {'name': 'Salads', 'icon': 'fa-leaf'},
        {'name': 'Desserts', 'icon': 'fa-ice-cream'},
        {'name': 'Drinks', 'icon': 'fa-glass-martini'}
    ]
    db.categories.insert_many(categories)
    print("Added sample categories")

print("\nInitialization complete!")
print("You can now log in to the admin panel with:")
print("Email: admin@foodiehub.com")
print("Password: admin123") 