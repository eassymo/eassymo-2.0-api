import firebase_admin
from firebase_admin import credentials, auth
from dotenv import load_dotenv
import os

load_dotenv()
current_dir = os.path.dirname(os.path.abspath(__file__))
cert_path = os.path.join(current_dir, "eassymo-416717-firebase-adminsdk-nk1q5-9e25e0f01c.json")

cred = credentials.Certificate(cert_path)
firebase_admin.initialize_app(cred)