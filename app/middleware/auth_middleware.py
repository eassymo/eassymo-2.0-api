from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.utils.firebase_admin import verify_firebase_token, get_user_from_token
import logging

logger = logging.getLogger(__name__)


# Backward compatibility function
async def verify_token(request: Request):
    """
    Backward compatibility function for the old verify_token pattern
    """
    try:
        authorization = request.headers.get("Authorization")
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header missing or invalid"
            )
        
        token = authorization.replace("Bearer ", "")
        decoded_token = verify_firebase_token(token)
        
        # Add user info to request state (old pattern)
        request.state.user = decoded_token
        request.state.groupSelected = request.headers.get('groupselected')
        
        return decoded_token
        
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase token"
        )
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed"
        )


class FirebaseAuthMiddleware:
    def __init__(self):
        self.security = HTTPBearer()

    async def __call__(self, request: Request):
        """
        Middleware to verify Firebase tokens from Authorization header
        """
        try:
            # Extract token from Authorization header
            authorization = request.headers.get("Authorization")
            if not authorization:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authorization header missing"
                )
            
            # Remove 'Bearer ' prefix
            if not authorization.startswith("Bearer "):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid authorization format"
                )
            
            token = authorization.replace("Bearer ", "")
            
            # Verify Firebase token
            decoded_token = verify_firebase_token(token)
            
            # Add user info to request state
            request.state.user = {
                "uid": decoded_token["uid"],
                "email": decoded_token.get("email"),
                "name": decoded_token.get("name"),
                "email_verified": decoded_token.get("email_verified", False)
            }
            
            return request
            
        except ValueError as e:
            logger.error(f"Firebase token verification failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Firebase token"
            )
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication failed"
            )


# Helper function to get current user from request
def get_current_user(request: Request):
    """
    Get current user from request state
    """
    if not hasattr(request.state, 'user'):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not authenticated"
        )
    return request.state.user


# Dependency for FastAPI routes
async def firebase_auth_required(request: Request):
    """
    FastAPI dependency to require Firebase authentication
    """
    try:
        authorization = request.headers.get("Authorization")
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header missing or invalid"
            )
        
        token = authorization.replace("Bearer ", "")
        user_info = get_user_from_token(token)
        
        return user_info
        
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase token"
        )
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed"
        )