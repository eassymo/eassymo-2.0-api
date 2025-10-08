import os
import sys
import pymongo
from dotenv import load_dotenv

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

load_dotenv()

try:
    client = pymongo.MongoClient(os.getenv("MONGO_URI"))
    mongo_db = client.EASSYMOSTAGING
    print("MongoDB connected successfully")
except pymongo.errors.ConfigurationError:
    sys.exit(1)
    mongo_db = None

MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")
MYSQL_USERNAME = os.getenv("MYSQL_USERNAME")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")

required_vars = [MYSQL_HOST, MYSQL_DATABASE, MYSQL_USERNAME, MYSQL_PASSWORD]

mysql_engine = None
MySQLSessionLocal = None

if not all(required_vars):
    print("Missing required MySQL environment variables")
    sys.exit(1)

try:
    DATABASE_URL = f"mysql+pymysql://{MYSQL_USERNAME}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
    mysql_engine = create_engine(DATABASE_URL, echo=False)
    MySQLSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=mysql_engine)
    print("MySQL RDS connected successfully")

except Exception as e:
    print("Error while connecting to Mysql")
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