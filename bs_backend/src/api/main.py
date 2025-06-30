from fastapi import FastAPI, Depends, HTTPException, Request, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import json

# Import our modules
from ..database import get_db, create_tables
from ..models import (
    User, Book, SwapOffer, Notification,
    BookCondition, SwapOfferStatus
)
from ..auth import (
    get_current_user,
    get_optional_current_user,
    verify_webhook_signature,
    ClerkAuthError
)


# Pydantic models for request validation
class BookCreateRequest(BaseModel):
    title: str = Field(..., description="Book title")
    author: str = Field(..., description="Book author")
    isbn: Optional[str] = Field(None, description="ISBN number")
    genre: Optional[str] = Field(None, description="Book genre")
    description: Optional[str] = Field(None, description="Book description")
    condition: str = Field(..., description="Book condition")
    publication_year: Optional[int] = Field(None, description="Publication year")
    publisher: Optional[str] = Field(None, description="Publisher name")
    language: str = Field("English", description="Book language")
    page_count: Optional[int] = Field(None, description="Number of pages")
    is_giveaway: bool = Field(False, description="Whether this is a giveaway")
    location: Optional[str] = Field(None, description="Pickup location")
    tags: Optional[str] = Field(None, description="JSON string of tags")


class BookUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, description="Book title")
    author: Optional[str] = Field(None, description="Book author")
    isbn: Optional[str] = Field(None, description="ISBN number")
    genre: Optional[str] = Field(None, description="Book genre")
    description: Optional[str] = Field(None, description="Book description")
    condition: Optional[str] = Field(None, description="Book condition")
    publication_year: Optional[int] = Field(None, description="Publication year")
    publisher: Optional[str] = Field(None, description="Publisher name")
    language: Optional[str] = Field(None, description="Book language")
    page_count: Optional[int] = Field(None, description="Number of pages")
    is_giveaway: Optional[bool] = Field(None, description="Whether giveaway")
    is_available: Optional[bool] = Field(None, description="Whether available")
    location: Optional[str] = Field(None, description="Pickup location")
    tags: Optional[str] = Field(None, description="JSON string of tags")


class SwapOfferCreateRequest(BaseModel):
    requested_book_id: int = Field(..., description="ID of requested book")
    offered_book_ids: Optional[List[int]] = Field(None, description="Offered books")
    message: Optional[str] = Field(None, description="Message to book owner")


class SwapOfferUpdateRequest(BaseModel):
    status: str = Field(..., description="New status")
    response_message: Optional[str] = Field(None, description="Response message")


class NotificationCreateRequest(BaseModel):
    title: str = Field(..., description="Notification title")
    message: str = Field(..., description="Notification message")
    notification_type: str = Field(..., description="Type of notification")
    related_entity_id: Optional[int] = Field(None, description="Related entity ID")
    related_entity_type: Optional[str] = Field(None, description="Entity type")
    priority: str = Field("normal", description="Priority level")


class UserProfileUpdateRequest(BaseModel):
    bio: Optional[str] = Field(None, description="User biography")
    location: Optional[str] = Field(None, description="User location")
    interests: Optional[str] = Field(None, description="User interests JSON")
    email_notifications: Optional[bool] = Field(None, description="Email prefs")


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
    profile_data: UserProfileUpdateRequest,
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
    # Update fields that are provided
    update_data = profile_data.dict(exclude_unset=True)

    for field, value in update_data.items():
        setattr(current_user, field, value)

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
    book_data: BookCreateRequest,
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
    # Create book
    book = Book(
        title=book_data.title,
        author=book_data.author,
        isbn=book_data.isbn,
        genre=book_data.genre,
        description=book_data.description,
        condition=BookCondition(book_data.condition),
        publication_year=book_data.publication_year,
        publisher=book_data.publisher,
        language=book_data.language,
        page_count=book_data.page_count,
        is_giveaway=book_data.is_giveaway,
        location=book_data.location,
        tags=book_data.tags,
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


@app.get("/books/{book_id}", tags=["books"])
def get_book(
    book_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    Get detailed information about a specific book.

    Args:
        book_id: ID of the book to retrieve
        db: Database session
        current_user: Current user if authenticated

    Returns:
        dict: Detailed book information

    Raises:
        HTTPException: If book not found
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "isbn": book.isbn,
        "genre": book.genre,
        "description": book.description,
        "condition": book.condition.value,
        "cover_image_url": book.cover_image_url,
        "publication_year": book.publication_year,
        "publisher": book.publisher,
        "language": book.language,
        "page_count": book.page_count,
        "is_available": book.is_available,
        "is_giveaway": book.is_giveaway,
        "location": book.location,
        "tags": book.tags,
        "owner": {
            "id": book.owner.id,
            "username": book.owner.username,
            "first_name": book.owner.first_name,
            "last_name": book.owner.last_name
        },
        "created_at": book.created_at,
        "updated_at": book.updated_at
    }


@app.put("/books/{book_id}", tags=["books"])
def update_book(
    book_id: int,
    book_data: BookUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update a book listing.

    Only the book owner can update their book listing.

    Args:
        book_id: ID of the book to update
        book_data: Updated book information
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: Updated book information

    Raises:
        HTTPException: If book not found or user not authorized
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if book.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this book")

    # Update fields that are provided
    update_data = book_data.dict(exclude_unset=True)

    for field, value in update_data.items():
        if field == "condition" and value:
            setattr(book, field, BookCondition(value))
        else:
            setattr(book, field, value)

    db.commit()
    db.refresh(book)

    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "condition": book.condition.value,
        "is_available": book.is_available,
        "is_giveaway": book.is_giveaway,
        "updated_at": book.updated_at
    }


@app.delete("/books/{book_id}", tags=["books"])
def delete_book(
    book_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a book listing.

    Only the book owner can delete their book listing.

    Args:
        book_id: ID of the book to delete
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: Success confirmation

    Raises:
        HTTPException: If book not found or user not authorized
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if book.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this book")

    db.delete(book)
    db.commit()

    return {"message": "Book deleted successfully"}


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


# Swap offer endpoints
@app.post("/swap-offers", tags=["swaps"])
def create_swap_offer(
    offer_data: SwapOfferCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new swap offer.

    Authenticated users can create swap offers for books they want.
    The offer can include books they're willing to trade or be a giveaway request.

    Args:
        offer_data: Swap offer information
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: Created swap offer information

    Raises:
        HTTPException: If requested book not found or not available
    """
    # Verify requested book exists and is available
    requested_book = db.query(Book).filter(
        Book.id == offer_data.requested_book_id,
        Book.is_available.is_(True)
    ).first()

    if not requested_book:
        raise HTTPException(
            status_code=404,
            detail="Requested book not found or not available"
        )

    if requested_book.owner_id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="Cannot create swap offer for your own book"
        )

    # Verify offered books exist and belong to current user (if any)
    offered_book_ids_json = None
    if offer_data.offered_book_ids:
        for book_id in offer_data.offered_book_ids:
            offered_book = db.query(Book).filter(
                Book.id == book_id,
                Book.owner_id == current_user.id,
                Book.is_available.is_(True)
            ).first()
            if not offered_book:
                raise HTTPException(
                    status_code=400,
                    detail=f"Offered book {book_id} not found or not available"
                )
        offered_book_ids_json = json.dumps(offer_data.offered_book_ids)

    # Create swap offer
    swap_offer = SwapOffer(
        requester_id=current_user.id,
        recipient_id=requested_book.owner_id,
        requested_book_id=offer_data.requested_book_id,
        offered_book_ids=offered_book_ids_json,
        message=offer_data.message,
        expires_at=datetime.utcnow() + timedelta(days=7)  # Expire in 7 days
    )

    db.add(swap_offer)
    db.commit()
    db.refresh(swap_offer)

    return {
        "id": swap_offer.id,
        "requester_id": swap_offer.requester_id,
        "recipient_id": swap_offer.recipient_id,
        "requested_book_id": swap_offer.requested_book_id,
        "offered_book_ids": swap_offer.offered_book_ids,
        "message": swap_offer.message,
        "status": swap_offer.status.value,
        "expires_at": swap_offer.expires_at,
        "created_at": swap_offer.created_at
    }


@app.get("/swap-offers", tags=["swaps"])
def list_swap_offers(
    type: str = Query("received", description="Type: 'sent' or 'received'"),
    skip: int = Query(0, description="Number of records to skip"),
    limit: int = Query(20, description="Maximum number of records to return"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List swap offers for the current user.

    Returns either sent offers (offers made by current user) or received offers
    (offers made to current user) based on the type parameter.

    Args:
        type: Type of offers to list ('sent' or 'received')
        skip: Number of records to skip (pagination)
        limit: Maximum number of records to return
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: List of swap offers with metadata
    """
    if type == "sent":
        query = db.query(SwapOffer).filter(SwapOffer.requester_id == current_user.id)
    elif type == "received":
        query = db.query(SwapOffer).filter(SwapOffer.recipient_id == current_user.id)
    else:
        raise HTTPException(
            status_code=400,
            detail="Invalid type parameter. Use 'sent' or 'received'"
        )

    total = query.count()
    offers = query.offset(skip).limit(limit).all()

    return {
        "offers": [
            {
                "id": offer.id,
                "requester": {
                    "id": offer.requester.id,
                    "username": offer.requester.username,
                    "first_name": offer.requester.first_name,
                    "last_name": offer.requester.last_name
                },
                "recipient": {
                    "id": offer.recipient.id,
                    "username": offer.recipient.username,
                    "first_name": offer.recipient.first_name,
                    "last_name": offer.recipient.last_name
                },
                "requested_book": {
                    "id": offer.requested_book.id,
                    "title": offer.requested_book.title,
                    "author": offer.requested_book.author
                },
                "offered_book_ids": offer.offered_book_ids,
                "message": offer.message,
                "status": offer.status.value,
                "response_message": offer.response_message,
                "expires_at": offer.expires_at,
                "created_at": offer.created_at,
                "updated_at": offer.updated_at
            }
            for offer in offers
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
        "type": type
    }


@app.get("/swap-offers/{offer_id}", tags=["swaps"])
def get_swap_offer(
    offer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific swap offer.

    Only the requester or recipient can view the offer details.

    Args:
        offer_id: ID of the swap offer to retrieve
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: Detailed swap offer information

    Raises:
        HTTPException: If offer not found or user not authorized
    """
    offer = db.query(SwapOffer).filter(SwapOffer.id == offer_id).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Swap offer not found")

    if (offer.requester_id != current_user.id and
            offer.recipient_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized to view this offer")

    # Get offered books details if any
    offered_books = []
    if offer.offered_book_ids:
        offered_book_ids = json.loads(offer.offered_book_ids)
        offered_books = db.query(Book).filter(Book.id.in_(offered_book_ids)).all()

    return {
        "id": offer.id,
        "requester": {
            "id": offer.requester.id,
            "username": offer.requester.username,
            "first_name": offer.requester.first_name,
            "last_name": offer.requester.last_name,
            "location": offer.requester.location
        },
        "recipient": {
            "id": offer.recipient.id,
            "username": offer.recipient.username,
            "first_name": offer.recipient.first_name,
            "last_name": offer.recipient.last_name,
            "location": offer.recipient.location
        },
        "requested_book": {
            "id": offer.requested_book.id,
            "title": offer.requested_book.title,
            "author": offer.requested_book.author,
            "condition": offer.requested_book.condition.value,
            "is_giveaway": offer.requested_book.is_giveaway
        },
        "offered_books": [
            {
                "id": book.id,
                "title": book.title,
                "author": book.author,
                "condition": book.condition.value
            }
            for book in offered_books
        ],
        "message": offer.message,
        "status": offer.status.value,
        "response_message": offer.response_message,
        "match_score": offer.match_score,
        "expires_at": offer.expires_at,
        "created_at": offer.created_at,
        "updated_at": offer.updated_at,
        "completed_at": offer.completed_at
    }


@app.put("/swap-offers/{offer_id}", tags=["swaps"])
def update_swap_offer(
    offer_id: int,
    update_data: SwapOfferUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update a swap offer status.

    Only the recipient can accept/reject offers. Both parties can cancel.

    Args:
        offer_id: ID of the swap offer to update
        update_data: Update information including status
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: Updated swap offer information

    Raises:
        HTTPException: If offer not found or user not authorized
    """
    offer = db.query(SwapOffer).filter(SwapOffer.id == offer_id).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Swap offer not found")

    # Validate authorization based on status change
    new_status = SwapOfferStatus(update_data.status)

    if new_status in [SwapOfferStatus.ACCEPTED, SwapOfferStatus.REJECTED]:
        if offer.recipient_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Only the recipient can accept or reject offers"
            )
    elif new_status == SwapOfferStatus.CANCELLED:
        if (offer.requester_id != current_user.id and
                offer.recipient_id != current_user.id):
            raise HTTPException(
                status_code=403,
                detail="Only requester or recipient can cancel offers"
            )
    elif new_status == SwapOfferStatus.COMPLETED:
        if offer.recipient_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Only the recipient can mark offers as completed"
            )

    # Update offer
    offer.status = new_status
    if update_data.response_message:
        offer.response_message = update_data.response_message

    if new_status == SwapOfferStatus.COMPLETED:
        offer.completed_at = datetime.utcnow()
        # Mark requested book as unavailable
        offer.requested_book.is_available = False
        # Mark offered books as unavailable if any
        if offer.offered_book_ids:
            offered_book_ids = json.loads(offer.offered_book_ids)
            db.query(Book).filter(Book.id.in_(offered_book_ids)).update(
                {"is_available": False}, synchronize_session=False
            )

    db.commit()
    db.refresh(offer)

    return {
        "id": offer.id,
        "status": offer.status.value,
        "response_message": offer.response_message,
        "updated_at": offer.updated_at,
        "completed_at": offer.completed_at
    }


# Notification endpoints
@app.get("/notifications", tags=["notifications"])
def list_notifications(
    skip: int = Query(0, description="Number of records to skip"),
    limit: int = Query(20, description="Maximum number of records to return"),
    unread_only: bool = Query(False, description="Return only unread notifications"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List notifications for the current user.

    Returns paginated list of notifications for the authenticated user.

    Args:
        skip: Number of records to skip (pagination)
        limit: Maximum number of records to return
        unread_only: Whether to return only unread notifications
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: List of notifications with metadata
    """
    query = db.query(Notification).filter(Notification.user_id == current_user.id)

    if unread_only:
        query = query.filter(Notification.is_read.is_(False))

    query = query.order_by(Notification.created_at.desc())

    total = query.count()
    notifications = query.offset(skip).limit(limit).all()

    return {
        "notifications": [
            {
                "id": notification.id,
                "title": notification.title,
                "message": notification.message,
                "notification_type": notification.notification_type.value,
                "related_entity_id": notification.related_entity_id,
                "related_entity_type": notification.related_entity_type,
                "is_read": notification.is_read,
                "priority": notification.priority,
                "metadata": notification.metadata,
                "created_at": notification.created_at,
                "read_at": notification.read_at
            }
            for notification in notifications
        ],
        "total": total,
        "unread_count": db.query(Notification).filter(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False)
        ).count(),
        "skip": skip,
        "limit": limit
    }


@app.put("/notifications/{notification_id}/read", tags=["notifications"])
def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Mark a notification as read.

    Args:
        notification_id: ID of the notification to mark as read
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: Success confirmation

    Raises:
        HTTPException: If notification not found or user not authorized
    """
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id
    ).first()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    notification.is_read = True
    notification.read_at = datetime.utcnow()

    db.commit()

    return {"message": "Notification marked as read"}


@app.put("/notifications/read-all", tags=["notifications"])
def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Mark all notifications as read for the current user.

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: Success confirmation with count of notifications marked
    """
    updated_count = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read.is_(False)
    ).update(
        {"is_read": True, "read_at": datetime.utcnow()},
        synchronize_session=False
    )

    db.commit()

    return {
        "message": f"Marked {updated_count} notifications as read",
        "count": updated_count
    }


@app.delete("/notifications/{notification_id}", tags=["notifications"])
def delete_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a notification.

    Args:
        notification_id: ID of the notification to delete
        current_user: Current authenticated user
        db: Database session

    Returns:
        dict: Success confirmation

    Raises:
        HTTPException: If notification not found or user not authorized
    """
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user.id
    ).first()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    db.delete(notification)
    db.commit()

    return {"message": "Notification deleted successfully"}


# Custom exception handler for authentication errors
@app.exception_handler(ClerkAuthError)
async def clerk_auth_exception_handler(request: Request, exc: ClerkAuthError):
    """Handle Clerk authentication errors with proper JSON response."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "type": "authentication_error"}
    )
