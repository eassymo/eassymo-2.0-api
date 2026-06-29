from uuid import uuid4
from typing import Dict, Any, Optional
from app.schemas.Notification import Notification
import requests
import os
from dotenv import load_dotenv

load_dotenv()


def send_notification(notification: Notification, user_token: str) -> None:
    """
    Send a notification to Firebase Realtime Database using REST API with user token
    
    Args:
        notification: Notification model instance
        user_token: Firebase user ID token for authentication
    """
    uid = str(uuid4())
    
    try:
        # Debug: Log token info (first/last 10 chars for security)
        token_preview = f"{user_token[:10]}...{user_token[-10:]}" if len(user_token) > 20 else user_token
        print(f"🔑 Using token: {token_preview}")
        
        # Get Firebase database URL from environment
        firebase_url = os.getenv("FIREBASE_RTDB_URL")
        if not firebase_url:
            raise ValueError("FIREBASE_RTDB_URL not found in environment variables")
        
        # Remove trailing slash if present
        if firebase_url.endswith("/"):
            firebase_url = firebase_url[:-1]
        
        # Build the REST API URL for the notification path with auth parameter
        notification_path = f"notifications/{notification.ownerGroup}/{notification.owner}"
        url = f"{firebase_url}/{notification_path}.json?auth={user_token}"
        
        # Debug: Log the URL structure (without the full token)
        url_debug = f"{firebase_url}/{notification_path}.json?auth=***TOKEN***"
        print(f"🌐 Firebase URL: {url_debug}")
        
        # Convert notification to dict and add uid
        notification_dict = notification.model_dump()
        notification_dict["uid"] = uid
        
        # Convert enum to string value if needed
        if hasattr(notification_dict["type"], "value"):
            notification_dict["type"] = notification_dict["type"].value
        
        # Prepare the notification data with server timestamp
        notification_data = {
            **notification_dict,
            "timestamp": {".sv": "timestamp"}
        }
        
        # Debug: Log notification data (without sensitive info)
        print(f"📧 Notification data: {{'type': '{notification_dict['type']}', 'owner': '{notification.owner}', 'ownerGroup': '{notification.ownerGroup}'}}")
        
        # Send POST request to Firebase REST API with user token as query parameter
        headers = {
            "Content-Type": "application/json"
        }
        
        response = requests.post(url, json=notification_data, headers=headers)
        
        # Debug: Log response details
        print(f"📡 Response status: {response.status_code}")
        print(f"📡 Response headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            print(f"✅ Notification sent successfully to {notification.owner}")
        else:
            print(f"❌ Failed to send notification: {response.status_code}")
            print(f"❌ Response text: {response.text}")
            
            # Additional debugging for 401 errors
            if response.status_code == 401:
                print("🔍 401 Unauthorized - Possible issues:")
                print("   - Token might be expired or invalid")
                print("   - Firebase Security Rules might deny the write")
                print("   - Token might not have the required permissions")
                print("   - Check if token is a valid Firebase ID token")
                
                # Try to decode the token to check if it's malformed
                try:
                    import base64
                    import json
                    # Split the JWT token to get the payload
                    token_parts = user_token.split('.')
                    if len(token_parts) == 3:
                        # Decode the payload (second part)
                        payload_encoded = token_parts[1]
                        # Add padding if needed
                        padding = len(payload_encoded) % 4
                        if padding:
                            payload_encoded += '=' * (4 - padding)
                        
                        try:
                            payload_decoded = base64.urlsafe_b64decode(payload_encoded)
                            payload_json = json.loads(payload_decoded)
                            print(f"🔍 Token payload preview: iss={payload_json.get('iss')}, exp={payload_json.get('exp')}")
                        except Exception as decode_error:
                            print(f"🔍 Could not decode token payload: {decode_error}")
                    else:
                        print("🔍 Token does not appear to be a valid JWT format")
                except Exception as token_debug_error:
                    print(f"🔍 Token debug failed: {token_debug_error}")
            
            raise Exception(f"Firebase REST API error: {response.status_code} - {response.text}")
        
    except Exception as error:
        print(f"❌ Error creating notification: {error}")
        # Re-raise the exception so the calling code knows the notification failed
        raise


def send_notification_dict(notification: Dict[str, Any], user_token: str) -> None:
    """
    Send a notification dictionary to Firebase Realtime Database using REST API
    For backward compatibility with existing code
    
    Args:
        notification: Dictionary containing notification data
        user_token: Firebase user ID token for authentication
    """
    uid = str(uuid4())
    
    try:
        # Get Firebase database URL from environment
        firebase_url = os.getenv("FIREBASE_RTDB_URL")
        if not firebase_url:
            raise ValueError("FIREBASE_RTDB_URL not found in environment variables")
        
        # Remove trailing slash if present
        if firebase_url.endswith("/"):
            firebase_url = firebase_url[:-1]
        
        # Build the REST API URL for the notification path with auth parameter
        notification_path = f"notifications/{notification['ownerGroup']}/{notification['owner']}"
        url = f"{firebase_url}/{notification_path}.json?auth={user_token}"
        
        # Prepare the notification data with server timestamp
        notification_data = {
            **notification,
            "uid": uid,
            "timestamp": {".sv": "timestamp"}
        }
        
        # Send POST request to Firebase REST API with user token as query parameter
        headers = {
            "Content-Type": "application/json"
        }
        
        response = requests.post(url, json=notification_data, headers=headers)
        
        if response.status_code == 200:
            print(f"✅ Notification sent successfully to {notification['owner']}")
        else:
            print(f"❌ Failed to send notification: {response.status_code} - {response.text}")
            raise Exception(f"Firebase REST API error: {response.status_code}")
        
    except Exception as error:
        print(f"❌ Error creating notification: {error}")
        # Re-raise the exception so the calling code knows the notification failed
        raise


# Legacy function for backward compatibility (deprecated)
def send_notification_legacy(notification: Notification) -> None:
    """
    Legacy function - deprecated, use send_notification with user_token instead
    """
    print("⚠️ Warning: send_notification_legacy is deprecated. Use send_notification with user_token parameter.")
    from app.utils.firebase_admin import get_database_reference
    
    uid = str(uuid4())
    
    try:
        notifications_ref = get_database_reference(f"notifications/{notification.ownerGroup}/{notification.owner}")
        
        # Convert notification to dict and add uid
        notification_dict = notification.model_dump()
        notification_dict["uid"] = uid
        
        # Convert enum to string value if needed
        if hasattr(notification_dict["type"], "value"):
            notification_dict["type"] = notification_dict["type"].value
        
        # Push notification with server timestamp
        notifications_ref.push({
            **notification_dict,
            "timestamp": {"sv": "timestamp"}
        })
        
        print(f"✅ Notification sent successfully to {notification.owner}")
        
    except Exception as error:
        print(f"❌ Error creating notification: {error}")
        # Re-raise the exception so the calling code knows the notification failed
        raise