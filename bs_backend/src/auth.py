import os
import jwt
import requests
from typing import Optional, Dict, Any
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import get_db
from models import User
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Clerk configuration
CLERK_PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY", "")
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
CLERK_WEBHOOK_SECRET = os.getenv("CLERK_WEBHOOK_SECRET", "")

# JWT Bearer token handler
security = HTTPBearer()


class ClerkAuthError(HTTPException):
    """Custom exception for Clerk authentication errors."""

    def __init__(self, detail: str):
        super().__init__(status_code=401, detail=detail)


# PUBLIC_INTERFACE
def get_clerk_public_keys() -> Dict[str, Any]:
    """
    Fetch Clerk's public keys for JWT verification.

    Returns:
        Dict containing the public keys from Clerk's JWKS endpoint
    """
    try:
        # Extract the domain from the publishable key
        if not CLERK_PUBLISHABLE_KEY.startswith("pk_"):
            raise ClerkAuthError("Invalid Clerk publishable key format")

        # For Clerk, we need to get the JWKS from their endpoint
        # The domain is derived from the publishable key
        key_parts = CLERK_PUBLISHABLE_KEY.split("_")
        domain_part = key_parts[1] if len(key_parts) > 1 else "live"
        jwks_url = f"https://clerk.{domain_part}.lcl.dev/.well-known/jwks.json"

        # Try the standard clerk.dev domain if the above fails
        try:
            response = requests.get(jwks_url, timeout=10)
        except requests.RequestException:
            # Fallback to standard Clerk domain
            jwks_url = "https://clerk.clerk.app/.well-known/jwks.json"
            response = requests.get(jwks_url, timeout=10)

        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        raise ClerkAuthError(f"Failed to fetch Clerk public keys: {str(e)}")


# PUBLIC_INTERFACE
def verify_clerk_jwt(token: str) -> Dict[str, Any]:
    """
    Verify a Clerk JWT token.

    Args:
        token: The JWT token to verify

    Returns:
        Dict containing the decoded token payload

    Raises:
        ClerkAuthError: If token verification fails
    """
    try:
        # Get the header without verification to extract the kid
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        if not kid:
            raise ClerkAuthError("Token missing key ID")

        # Get public keys from Clerk
        jwks = get_clerk_public_keys()

        # Find the matching key
        public_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                break

        if not public_key:
            raise ClerkAuthError("Public key not found for token")

        # Verify and decode the token
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={"verify_aud": False}
        )

        return payload

    except jwt.ExpiredSignatureError:
        raise ClerkAuthError("Token has expired")
    except jwt.InvalidTokenError as e:
        raise ClerkAuthError(f"Invalid token: {str(e)}")


# PUBLIC_INTERFACE
def get_or_create_user(clerk_user_data: Dict[str, Any], db: Session) -> User:
    """
    Get or create a user in the local database based on Clerk user data.

    Args:
        clerk_user_data: User data from Clerk JWT payload
        db: Database session

    Returns:
        User object from local database
    """
    clerk_user_id = clerk_user_data.get("sub")
    if not clerk_user_id:
        raise ValueError("No user ID found in Clerk data")

    # Check if user already exists
    user = db.query(User).filter(User.clerk_user_id == clerk_user_id).first()

    if user:
        return user

    # Create new user
    email = clerk_user_data.get("email", "")
    username = clerk_user_data.get("username")
    if not username:
        if email:
            username = email.split("@")[0]
        else:
            username = f"user_{clerk_user_id[:8]}"

    first_name = clerk_user_data.get("given_name", "")
    last_name = clerk_user_data.get("family_name", "")

    user = User(
        clerk_user_id=clerk_user_id,
        email=email,
        username=username,
        first_name=first_name,
        last_name=last_name
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


# PUBLIC_INTERFACE
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    FastAPI dependency to get the current authenticated user.

    Args:
        credentials: HTTP authorization credentials containing the JWT token
        db: Database session

    Returns:
        User object from local database

    Raises:
        ClerkAuthError: If authentication fails
    """
    try:
        # Verify the JWT token
        token_payload = verify_clerk_jwt(credentials.credentials)

        # Get or create user in local database
        user = get_or_create_user(token_payload, db)

        return user

    except Exception as e:
        if isinstance(e, ClerkAuthError):
            raise e
        raise ClerkAuthError(f"Authentication failed: {str(e)}")


# PUBLIC_INTERFACE
def get_optional_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    FastAPI dependency to get the current user if authenticated, None otherwise.
    Useful for endpoints that work for both authenticated and anonymous users.

    Args:
        request: FastAPI request object
        db: Database session

    Returns:
        User object if authenticated, None otherwise
    """
    try:
        # Check for Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        token = auth_header.split(" ")[1]
        token_payload = verify_clerk_jwt(token)
        user = get_or_create_user(token_payload, db)

        return user

    except Exception:
        # Return None for any authentication errors in optional context
        return None


# PUBLIC_INTERFACE
def verify_webhook_signature(request: Request, payload: bytes) -> bool:
    """
    Verify Clerk webhook signature to ensure the request is from Clerk.

    Args:
        request: FastAPI request object
        payload: Raw request payload bytes

    Returns:
        True if signature is valid, False otherwise
    """
    if not CLERK_WEBHOOK_SECRET:
        return False

    try:
        import hmac
        import hashlib

        signature = request.headers.get("clerk-signature", "")
        if not signature:
            return False

        # Clerk sends signature in format: v1=<signature>
        if not signature.startswith("v1="):
            return False

        expected_signature = signature[3:]  # Remove "v1=" prefix

        # Calculate HMAC
        calculated_signature = hmac.new(
            CLERK_WEBHOOK_SECRET.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected_signature, calculated_signature)

    except Exception:
        return False
