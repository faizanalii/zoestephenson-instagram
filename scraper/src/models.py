"""
Models for the Instagram Post Manager application. This includes data models for tokens,
cookies, and any other relevant entities used in the application.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Post(BaseModel):
    """
    Model for creating or upserting a post.

    Used when inserting new posts or updating existing ones.
    Only post_url and username are required.

    Example:
        >>> post = PostCreate(
        ...     post_url="https://www.instagram.com/reel/DW9kcaxD4kJ/",
        ...     username="arladairyuk",
        ...     media_id="7566027081650277650",
        ...     hmac_claim="7597536448384746518"
        ... )
    """

    post_url: str = Field(
        ...,
        description="Instagram post URL (short or long form)",
        examples=[
            "https://www.instagram.com/reel/DW9kcaxD4kJ/",
            "https://www.instagram.com/p/Cj1X9a2Lh8e/",
        ],
    )

    username: str = Field(
        ...,
        description="Instagram username who posted the post (without @)",
        examples=["arladairyuk"],
    )

    media_id: str | None = Field(
        default=None,
        description="Extracted Instagram media ID (immutable once set)",
        examples=["7566027081650277650"],
    )

    hmac_claim: str | None = Field(
        default=None,
        description="Extracted Instagram HMAC claim (immutable once set)",
        examples=["7597536448384746518"],
    )

    comment_count: int | None = Field(
        default=None, ge=0, description="Number of comments on the post"
    )

    has_next_comments: bool = Field(
        default=True,
        description="Indicates if there are more comments to fetch beyond the first batch",
    )

    first_comments: list[dict] = Field(
        default_factory=list,
        description="List of the first few comments extracted from the post",
    )

    post_exists: bool = Field(default=True, description="Indicates if the post exists on Instagram")

    retry_count: int = Field(
        default=0,
        ge=0,
        description="Number of times this post has been re-queued for retry",
    )

    @field_validator("post_url")
    @classmethod
    def validate_instagram_url(cls, v: str) -> str:
        """Ensure the URL is an Instagram URL."""
        if not any(domain in v.lower() for domain in ["instagram.com"]):
            raise ValueError("URL must be an Instagram URL")
        return v

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """Strip whitespace and validate username."""
        v = v.strip()
        if not v:
            raise ValueError("Username cannot be empty")
        return v


class CommentStats(BaseModel):
    """
    Model for comment statistics of a post.

    Example:
        >>> stats = CommentStats(
        ...     post_url="https://www.instagram.com/reel/DW9kcaxD4kJ/",
        ...     username="arladairyuk",
        ...     text="Great post!",
        ...     likes=5,
        ...     reply_count=2,
        ...     date_of_comment="2023-10-01",
        ...     date="2023-10-01"
        ... )
    """

    post_url: str = Field(..., description="Instagram post URL")
    username: str = Field(..., description="Instagram username who posted the post")
    text: str = Field(..., description="The text of the comment")
    likes: int = Field(default=0, ge=0, description="Number of likes on the comment")
    reply_count: int = Field(
        default=0,
        ge=0,
        description="Number of replies to the comment",
    )
    date_of_comment: str = Field(
        ..., description="Date of the comment"
    )  # Convert the timestamp (1748573540) to a string in the format "YYYY-MM-DD" when creating an instance of CommentStats.
    date: str = Field(default=datetime.now().strftime("%Y-%m-%d"))


class ScrapeStatus(str, Enum):
    """
    Enum representing the possible statuses of a scraping task.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    FOUND = "found"
    NOT_FOUND = "not_found"
    RETRY = "retry"
    ERROR = "error"


class TaskState(BaseModel):
    """Represents the processing state for a single post/username search task."""

    post_url: str
    username: str
    account_id: str | None = None
    source_queue: str | None = None
    requeued: bool = False
    retry_at: datetime | None = None
    variables: dict[str, Any] | None = None
    retry_count: int = 0
    proxy: str | None = None
    last_cursor_at: datetime | None = None
    last_error: str | None = None


class AccountCookies(BaseModel):
    """Binds an account identifier to the cookie jar used for GraphQL calls."""

    account_id: str
    cookies: dict[str, str]


class HeaderRequirements(BaseModel):
    """Holds extracted header data from the post page required for pagination and rate limit checks."""

    app_id: str
    csrf_token: str
    hmac_claim: str | None = None
    lsd_token: str | None = None
    dtsg_token: str | None = None
    claim_token: str | None = None


class DataRequirements(BaseModel):
    """
    Holds all extracted fields required to call Instagram comments pagination APIs.
    """

    media_id: str
    cursor: dict[str, Any] | str | None = None
    fb_dtsg: str
    lsd_token: str


class PageRequirements(BaseModel):
    """Holds all extracted fields required to call Instagram comments pagination APIs."""

    post_id: str
    csrf_token: str
    app_id: str
    media_id: str
    cursor: dict[str, Any] | str
    lsd_token: str | None = None
    dtsg_token: str | None = None
    claim_token: str | None = None


class CommentNotFound(BaseModel):
    """Model for marking no comments found."""

    post_url: str
    comment_exists: bool = False


class UpdateCommentCheckDay(BaseModel):
    """Model for updating last comment check day."""

    post_url: str
    last_comment_update: str = Field(default_factory=lambda: datetime.now(UTC).date().isoformat())


class ScrapeResult(BaseModel):
    """Standardized result returned from scraper functions like `find_comment()`.

    Use `status` to determine how the caller should react (requeue, persist, etc.).
    """

    status: ScrapeStatus
    post_url: str | None = None
    username: str | None = None
    comment: CommentStats | None = None
    retry_count: int = 0
    retry_after_seconds: int | None = None
    error: str | None = None
