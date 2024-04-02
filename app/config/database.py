import os
import sys
import pymongo
from dotenv import load_dotenv

load_dotenv()

try:
    client = pymongo.MongoClient(os.getenv("MONGO_URI"))
    print("Connected to mongodb")
except pymongo.errors.ConfigurationError:
    print("Error while connecting to mongodb")
    sys.exit(1)
  
db = client.EASSYMOSTAGING