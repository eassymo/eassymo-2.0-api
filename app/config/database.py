import os
import sys
import pymongo
from dotenv import load_dotenv

load_dotenv()

try:
    client = pymongo.MongoClient(os.getenv("MONGO_URI"))
except pymongo.errors.ConfigurationError:
    sys.exit(1)
  
db = client.EASSYMOSTAGING