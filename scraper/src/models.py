"""
Models for the Instagram Post Manager application. This includes data models for tokens,
cookies, and any other relevant entities used in the application.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    )  # Convert the timestamp (1748573540) to a string in the format "YYYY-MM-DD"
    date: str = Field(default=datetime.now().strftime("%Y-%m-%d"))


@dataclass(slots=True)
class TaskState:
    """Represents the processing state for a single post/username search task."""

    post_url: str
    username: str
    account_id: str | None = None
    requeued: bool = False
    retry_at: datetime | None = None
    variables: dict[str, Any] | None = None


@dataclass(slots=True)
class AccountCookies:
    """Binds an account identifier to the cookie jar used for GraphQL calls."""

    account_id: str
    cookies: dict[str, str]


@dataclass(slots=True)
class PageRequirements:
    """Holds all extracted fields required to call Instagram comments pagination APIs."""

    post_id: str
    csrf_token: str
    app_id: str
    media_id: str
    cursor: dict[str, Any]
    lsd_token: str | None
    dtsg_token: str | None
    claim_token: str | None


@dataclass
class CommentNotFound:
    """Model for marking no comments found."""

    video_id: str
    comment_exists: bool = False


@dataclass
class UpdateCommentCheckDay:
    """Model for updating last comment check day."""

    video_id: str
    last_comment_update: str = field(default_factory=lambda: datetime.now(UTC).date().isoformat())
