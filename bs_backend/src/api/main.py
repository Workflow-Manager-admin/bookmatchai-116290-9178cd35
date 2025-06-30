from fastapi import FastAPI, Depends, HTTPException, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
import json

# Import our modules
from ..database import get_db, create_tables
from ..models import User, Book
from ..auth import (
    get_current_user,
    get_optional_current_user,
    verify_webhook_signature,
    ClerkAuthError
)

# Create FastAPI app with OpenAPI documentation
app = FastAPI(
    title="BookSwap+ API",
    description="Community platform for book swapping with AI-powered matching",
    version="1.0.0",
    openapi_tags=[
        {
            "name": "auth",
            "description": "Authentication and user management"
        },
        {
            "name": "users",
            "description": "User profile operations"
        },
        {
            "name": "books",
            "description": "Book listing and management"
        },
        {
            "name": "swaps",
            "description": "Swap offer operations"
        },
        {
            "name": "notifications",
            "description": "User notifications"
        }
    ]
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Create database tables on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database tables on application startup."""
    create_tables()


# Health check endpoint
@app.get("/", tags=["health"])
def health_check():
    """
    Health check endpoint to verify the API is running.

    Returns:
        dict: Status message indicating the API is healthy
    """
    return {"message": "BookSwap+ API is healthy", "version": "1.0.0"}


# Authentication endpoints
@app.post("/auth/webhook", tags=["auth"])
async def clerk_webhook(
    request: Request,
    payload: bytes = Body(...),
    db: Session = Depends(get_db)
):
    """
    Handle Clerk webhooks for user lifecycle events.

    This endpoint processes user creation, updates, and deletion events.
    It ensures our local user database stays synchronized with Clerk's data.

    Args:
        request: FastAPI request object containing headers
        payload: Raw webhook payload from Clerk
        db: Database session

    Returns:
        dict: Success confirmation

    Raises:
        HTTPException: If webhook signature verification fails
    """
    # Verify webhook signature
    if not verify_webhook_signature(request, payload):
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature"
        )

    try:
        # Parse webhook payload
        data = json.loads(payload.decode())
        event_type = data.get("type", "")
        user_data = data.get("data", {})

        if event_type == "user.created":
            # Create user in our database
            clerk_user_id = user_data.get("id")
            email_addresses = user_data.get("email_addresses", [])
            primary_email = None

            for email_obj in email_addresses:
                primary_id = user_data.get("primary_email_address_id")
                if email_obj.get("id") == primary_id:
                    primary_email = email_obj.get("email_address")
                    break

            if not primary_email and email_addresses:
                primary_email = email_addresses[0].get("email_address")

            username = user_data.get("username")
            if not username:
                if primary_email:
                    username = primary_email.split("@")[0]
                else:
                    username = f"user_{clerk_user_id[:8]}"

            user = User(
                clerk_user_id=clerk_user_id,
                email=primary_email or "",
                username=username,
                first_name=user_data.get("first_name", ""),
                last_name=user_data.get("last_name", "")
            )

            db.add(user)
            db.commit()

        elif event_type == "user.updated":
            # Update existing user
            clerk_user_id = user_data.get("id")
            user = db.query(User).filter(
                User.clerk_user_id == clerk_user_id
            ).first()

            if user:
                email_addresses = user_data.get("email_addresses", [])
                primary_email = None

                for email_obj in email_addresses:
                    primary_id = user_data.get("primary_email_address_id")
                    if email_obj.get("id") == primary_id:
                        primary_email = email_obj.get("email_address")
                        break

                if primary_email:
                    user.email = primary_email
                user.first_name = user_data.get("first_name", user.first_name)
                user.last_name = user_data.get("last_name", user.last_name)
                user.username = user_data.get("username", user.username)

                db.commit()

        elif event_type == "user.deleted":
            # Handle user deletion (soft delete or anonymize)
            clerk_user_id = user_data.get("id")
            user = db.query(User).filter(
                User.clerk_user_id == clerk_user_id
            ).first()

            if user:
                # For now, we'll keep the user but mark as inactive
                # You might want to implement proper data deletion policies
                from ..models import UserStatus
                user.status = UserStatus.INACTIVE
                db.commit()

        return {"success": True, "processed": event_type}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process webhook: {str(e)}"
        )


@app.get("/auth/me", tags=["auth"])
def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    Get current authenticated user information.

    Returns the profile information of the currently authenticated user.

    Args:
        current_user: Current authenticated user (injected by dependency)

    Returns:
        dict: User profile information
    """
    return {
        "id": current_user.id,
        "clerk_user_id": current_user.clerk_user_id,
        "email": current_user.email,
        "username": current_user.username,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "bio": current_user.bio,
        "location": current_user.location,
        "interests": current_user.interests,
        "status": current_user.status.value,
        "email_notifications": current_user.email_notifications,
        "created_at": current_user.created_at,
        "updated_at": current_user.updated_at
    }


# User profile endpoints
@app.get("/users/{user_id}", tags=["users"])
def get_user_profile(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Get user profile by ID.

    Returns public profile information for any user. Some fields may be
    restricted based on privacy settings.

    Args:
        user_id: ID of the user to retrieve
        db: Database session
        current_user: Current authenticated user (optional)

    Returns:
        dict: Public user profile information

    Raises:
        HTTPException: If user not found
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Return public profile (you might want to add privacy controls)
    return {
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "bio": user.bio,
        "location": user.location,
        "created_at": user.created_at
    }


@app.put("/users/me", tags=["users"])
def update_user_profile(
    profile_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update current user's profile.

    Allows authenticated users to update their profile information
    including bio, location, and notification preferences.

    Args:
        profile_data: Profile update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: Updated user profile information
    """
    # Update allowed fields
    updatable_fields = ["bio", "location", "interests", "email_notifications"]

    for field in updatable_fields:
        if field in profile_data:
            setattr(current_user, field, profile_data[field])

    db.commit()
    db.refresh(current_user)

    return {
        "id": current_user.id,
        "username": current_user.username,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "bio": current_user.bio,
        "location": current_user.location,
        "interests": current_user.interests,
        "email_notifications": current_user.email_notifications,
        "updated_at": current_user.updated_at
    }


# Protected route examples for books and swaps
@app.get("/books", tags=["books"])
def list_books(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    List available books for swapping.

    Returns a paginated list of books available for swap or giveaway.
    Authentication is optional - some features may require login.

    Args:
        skip: Number of records to skip (pagination)
        limit: Maximum number of records to return
        db: Database session
        current_user: Current user if authenticated

    Returns:
        dict: List of books with metadata
    """
    query = db.query(Book).filter(Book.is_available.is_(True))

    total = query.count()
    books = query.offset(skip).limit(limit).all()

    return {
        "books": [
            {
                "id": book.id,
                "title": book.title,
                "author": book.author,
                "genre": book.genre,
                "condition": book.condition.value,
                "is_giveaway": book.is_giveaway,
                "location": book.location,
                "owner": {
                    "id": book.owner.id,
                    "username": book.owner.username
                }
            }
            for book in books
        ],
        "total": total,
        "skip": skip,
        "limit": limit
    }


@app.post("/books", tags=["books"])
def create_book_listing(
    book_data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new book listing for swap or giveaway.

    Authenticated users can create listings for books they want to
    swap or give away to other community members.

    Args:
        book_data: Book information including title, author, condition, etc.
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: Created book listing information
    """
    from ..models import BookCondition

    # Validate required fields
    required_fields = ["title", "author", "condition"]
    for field in required_fields:
        if field not in book_data:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required field: {field}"
            )

    # Create book
    book = Book(
        title=book_data["title"],
        author=book_data["author"],
        isbn=book_data.get("isbn"),
        genre=book_data.get("genre"),
        description=book_data.get("description"),
        condition=BookCondition(book_data["condition"]),
        publication_year=book_data.get("publication_year"),
        publisher=book_data.get("publisher"),
        language=book_data.get("language", "English"),
        page_count=book_data.get("page_count"),
        is_giveaway=book_data.get("is_giveaway", False),
        location=book_data.get("location"),
        tags=book_data.get("tags"),
        owner_id=current_user.id
    )

    db.add(book)
    db.commit()
    db.refresh(book)

    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "condition": book.condition.value,
        "is_available": book.is_available,
        "is_giveaway": book.is_giveaway,
        "created_at": book.created_at
    }


@app.get("/books/my", tags=["books"])
def get_user_books(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get current user's book listings.

    Returns all books listed by the currently authenticated user,
    including both available and unavailable listings.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: List of user's book listings
    """
    books = db.query(Book).filter(Book.owner_id == current_user.id).all()

    return {
        "books": [
            {
                "id": book.id,
                "title": book.title,
                "author": book.author,
                "genre": book.genre,
                "condition": book.condition.value,
                "is_available": book.is_available,
                "is_giveaway": book.is_giveaway,
                "location": book.location,
                "created_at": book.created_at
            }
            for book in books
        ]
    }


# Custom exception handler for authentication errors
@app.exception_handler(ClerkAuthError)
async def clerk_auth_exception_handler(request: Request, exc: ClerkAuthError):
    """Handle Clerk authentication errors with proper JSON response."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "type": "authentication_error"}
    )
