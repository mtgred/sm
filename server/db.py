import os
import pymongo

client = pymongo.MongoClient(os.environ.get("MONGODB_URL", "mongodb://localhost:27017"))
db = client["soulmasters"]
