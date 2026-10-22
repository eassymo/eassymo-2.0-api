import os
import sys
from pathlib import Path

import pymongo
from dotenv import load_dotenv

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

MONGO_URI = os.getenv("MONGO_URI", "").strip()
mongo_db = None

if not MONGO_URI:
    print("Missing required environment variable: MONGO_URI")
    sys.exit(1)

try:
    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    mongo_db = client.EASSYMOSTAGING
    print("MongoDB connected successfully")
except pymongo.errors.ConfigurationError as e:
    print(f"MongoDB configuration error: {e}")
    sys.exit(1)
except pymongo.errors.ServerSelectionTimeoutError as e:
    print(f"MongoDB connection failed: {e}")
    sys.exit(1)
except Exception as e:
    print(f"MongoDB connection failed: {e}")
    sys.exit(1)

MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
MYSQL_USERNAME = os.getenv("MYSQL_USERNAME")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_SSL_CA = os.getenv("MYSQL_SSL_CA")

required_vars = [MYSQL_HOST, MYSQL_DATABASE, MYSQL_USERNAME, MYSQL_PASSWORD]

mysql_engine = None
MySQLSessionLocal = None

if not all(required_vars):
    print("Missing required MySQL environment variables:")
    for name, value in [
        ("MYSQL_HOST", MYSQL_HOST),
        ("MYSQL_DATABASE", MYSQL_DATABASE),
        ("MYSQL_USERNAME", MYSQL_USERNAME),
        ("MYSQL_PASSWORD", MYSQL_PASSWORD),
    ]:
        if not value:
            print(f"  - {name}")
    sys.exit(1)

try:
    DATABASE_URL = f"mysql+pymysql://{MYSQL_USERNAME}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
    connect_args = {}
    if MYSQL_SSL_CA:
        connect_args["ssl"] = {"ca": MYSQL_SSL_CA}
    mysql_engine = create_engine(DATABASE_URL, echo=False, connect_args=connect_args)
    MySQLSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=mysql_engine)
    print("MySQL RDS connected successfully")

except Exception as e:
    print(f"Error while connecting to MySQL: {e}")
    mysql_engine=None
    MySQLSessionLocal=None

def get_mongo_db():
    return mongo_db

def get_mysql_db():
    if MySQLSessionLocal is None:
        raise Exception("theres not a mysql connection")
    db = MySQLSessionLocal()

    try:
        yield db
    finally:
        db.close()

db = mongo_db