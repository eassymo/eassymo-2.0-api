import firebase_admin
from firebase_admin import credentials, auth, db
from dotenv import load_dotenv
import os
import json

load_dotenv()

def initialize_firebase():
    """
    Initialize Firebase Admin SDK with proper service account credentials
    """
    if firebase_admin._apps:
        return
    
    try:
        # Try multiple credential sources in order of preference
        
        # Option 1: Service account file path
        service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
        if service_account_path and os.path.exists(service_account_path):
            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred, {
                'databaseURL': os.getenv("FIREBASE_RTDB_URL")
            })
            print("✅ Firebase initialized with service account file")
            return
        
        # Option 2: Environment variables (fix the private key formatting)
        if all([
            os.getenv("FIREBASE_PROJECT_ID"),
            os.getenv("FIREBASE_PRIVATE_KEY"),
            os.getenv("FIREBASE_CLIENT_EMAIL")
        ]):
            # Properly format the private key
            private_key = os.getenv("FIREBASE_PRIVATE_KEY")
            
            # Handle different newline formats and ensure proper structure
            if "\\n" in private_key:
                private_key = private_key.replace("\\n", "\n")
            
            # Ensure the key has proper header and footer
            if not private_key.startswith("-----BEGIN"):
                raise ValueError("Private key must start with -----BEGIN")
            
            cred_dict = {
                "type": "service_account",
                "project_id": os.getenv("FIREBASE_PROJECT_ID"),
                "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
                "private_key": private_key,
                "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
                "client_id": os.getenv("FIREBASE_CLIENT_ID"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{os.getenv('FIREBASE_CLIENT_EMAIL')}"
            }
            
            # Validate the credentials before using them
            validate_service_account_creds(cred_dict)
            
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred, {
                'databaseURL': os.getenv("FIREBASE_RTDB_URL")
            })
            print("✅ Firebase initialized with environment variables")
            return
        
        # Option 3: Try to create service account from JSON string
        firebase_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
        if firebase_json:
            try:
                cred_dict = json.loads(firebase_json)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred, {
                    'databaseURL': os.getenv("FIREBASE_RTDB_URL")
                })
                print("✅ Firebase initialized with JSON credentials")
                return
            except json.JSONDecodeError as e:
                print(f"❌ Invalid JSON in FIREBASE_SERVICE_ACCOUNT_JSON: {e}")
        
        # If we get here, we need proper credentials
        raise ValueError(
            "❌ Firebase service account credentials not found or invalid. "
            "Please set either:\n"
            "1. FIREBASE_SERVICE_ACCOUNT_PATH (path to service account file)\n"
            "2. FIREBASE_SERVICE_ACCOUNT_JSON (JSON string of service account)\n"
            "3. Individual environment variables (FIREBASE_PROJECT_ID, FIREBASE_PRIVATE_KEY, etc.)"
        )
        
    except Exception as e:
        print(f"❌ Error initializing Firebase: {e}")
        print("🔧 Troubleshooting tips:")
        print("   - Check your private key formatting (ensure \\n is properly escaped)")
        print("   - Verify your service account has Realtime Database permissions")
        print("   - Ensure all required environment variables are set")
        raise


def validate_service_account_creds(cred_dict):
    """
    Validate service account credentials before using them
    """
    required_fields = ["type", "project_id", "private_key", "client_email"]
    missing_fields = [field for field in required_fields if not cred_dict.get(field)]
    
    if missing_fields:
        raise ValueError(f"Missing required credential fields: {missing_fields}")
    
    if cred_dict["type"] != "service_account":
        raise ValueError("Credential type must be 'service_account'")
    
    private_key = cred_dict["private_key"]
    if not private_key.startswith("-----BEGIN PRIVATE KEY-----"):
        raise ValueError("Private key format is invalid")


# Initialize Firebase when module is imported
initialize_firebase()


def verify_firebase_token(id_token: str):
    """
    Verify Firebase ID token from Authorization header
    """
    try:
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token
    except Exception as e:
        print(f"❌ Error verifying Firebase token: {e}")
        raise ValueError("Invalid Firebase token")


def get_user_from_token(id_token: str):
    """
    Get user information from Firebase token
    """
    try:
        decoded_token = verify_firebase_token(id_token)
        return {
            "uid": decoded_token["uid"],
            "email": decoded_token.get("email"),
            "name": decoded_token.get("name"),
            "email_verified": decoded_token.get("email_verified", False)
        }
    except Exception as e:
        print(f"❌ Error getting user from token: {e}")
        raise


def get_database_reference(path: str):
    """
    Get Firebase Realtime Database reference
    """
    try:
        return db.reference(path)
    except Exception as e:
        print(f"❌ Error getting database reference: {e}")
        print("💡 Make sure Firebase is properly initialized with service account credentials")
        raise