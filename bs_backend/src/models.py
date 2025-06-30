from sqlalchemy import (Column, Integer, String, Text, DateTime, Boolean,
                        ForeignKey, Enum, Float)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import enum


class UserStatus(enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"


class BookCondition(enum.Enum):
    NEW = "new"
    LIKE_NEW = "like_new"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"


class SwapOfferStatus(enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class NotificationType(enum.Enum):
    MATCH_SUGGESTION = "match_suggestion"
    SWAP_REQUEST = "swap_request"
    SWAP_ACCEPTED = "swap_accepted"
    SWAP_REJECTED = "swap_rejected"
    SWAP_COMPLETED = "swap_completed"
    GENERAL = "general"


class User(Base):
    """
    User model representing registered users in the BookSwap+ platform.
    Integrates with Clerk.dev for authentication.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    clerk_user_id = Column(String(255), unique=True, index=True,
                           nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    bio = Column(Text, nullable=True)
    location = Column(String(255), nullable=True)
    interests = Column(Text, nullable=True)  # JSON string of user interests
    status = Column(Enum(UserStatus), default=UserStatus.ACTIVE)
    email_notifications = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    books = relationship("Book", back_populates="owner")
    sent_offers = relationship("SwapOffer",
                               foreign_keys="SwapOffer.requester_id",
                               back_populates="requester")
    received_offers = relationship("SwapOffer",
                                   foreign_keys="SwapOffer.recipient_id",
                                   back_populates="recipient")
    notifications = relationship("Notification", back_populates="user")


class Book(Base):
    """
    Book model representing books available for swap or giveaway.
    Contains detailed book information and metadata.
    """
    __tablename__ = "books"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False, index=True)
    author = Column(String(255), nullable=False)
    isbn = Column(String(20), nullable=True, index=True)
    genre = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    condition = Column(Enum(BookCondition), nullable=False)
    cover_image_url = Column(String(500), nullable=True)
    publication_year = Column(Integer, nullable=True)
    publisher = Column(String(255), nullable=True)
    language = Column(String(50), default="English")
    page_count = Column(Integer, nullable=True)
    is_available = Column(Boolean, default=True)
    is_giveaway = Column(Boolean, default=False)  # True if giving away
    location = Column(String(255), nullable=True)  # Pickup location
    tags = Column(Text, nullable=True)  # JSON string of tags
    semantic_embedding = Column(Text, nullable=True)  # For semantic matching
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    owner = relationship("User", back_populates="books")
    swap_offers = relationship("SwapOffer", back_populates="requested_book")


class SwapOffer(Base):
    """
    SwapOffer model representing swap requests between users.
    Tracks the status and details of book exchange offers.
    """
    __tablename__ = "swap_offers"

    id = Column(Integer, primary_key=True, index=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    requested_book_id = Column(Integer, ForeignKey("books.id"),
                               nullable=False)
    offered_book_ids = Column(Text, nullable=True)  # JSON array of book IDs
    message = Column(Text, nullable=True)
    status = Column(Enum(SwapOfferStatus), default=SwapOfferStatus.PENDING)
    response_message = Column(Text, nullable=True)
    match_score = Column(Float, nullable=True)  # Semantic matching score
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    requester = relationship("User", foreign_keys=[requester_id],
                             back_populates="sent_offers")
    recipient = relationship("User", foreign_keys=[recipient_id],
                             back_populates="received_offers")
    requested_book = relationship("Book", back_populates="swap_offers")


class Notification(Base):
    """
    Notification model for user notifications about matches, swaps, and
    system messages. Supports different notification types and delivery
    preferences.
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    notification_type = Column(Enum(NotificationType), nullable=False)
    related_entity_id = Column(Integer, nullable=True)  # ID of related entity
    related_entity_type = Column(String(50), nullable=True)  # Entity type
    is_read = Column(Boolean, default=False)
    is_email_sent = Column(Boolean, default=False)
    priority = Column(String(20), default="normal")  # low, normal, high
    metadata = Column(Text, nullable=True)  # JSON string for additional data
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    read_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="notifications")
