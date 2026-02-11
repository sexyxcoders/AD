from pymongo import MongoClient
from telethon.sessions import StringSession
import config

# Connect to MongoDB
client = MongoClient(config.MONGO_URI)  # Mongo URI from config.py
db = client['telegram_bot_db']  # Create or use the database
accounts_collection = db['accounts']  # Collection for storing account sessions

# Function to save account session data
def save_account(phone_number, session_data):
    """Save the account session data in MongoDB."""
    accounts_collection.update_one(
        {'phone_number': phone_number},
        {'$set': {'session_data': session_data}},
        upsert=True  # Create a new document if it doesn't exist
    )

# Function to get session by phone number
def get_session_by_phone(phone_number):
    """Retrieve the session data for the given phone number."""
    account = accounts_collection.find_one({'phone_number': phone_number})
    return account['session_data'] if account else None

# Function to get all accounts
def get_all_accounts():
    """Get a list of all phone numbers stored in the accounts collection."""
    accounts = accounts_collection.find({}, {'_id': 0, 'phone_number': 1})
    return [account['phone_number'] for account in accounts]
