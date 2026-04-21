"""
Models for the Instagram Post Manager application. This includes data models for tokens,
cookies, and any other relevant entities used in the application.
"""

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
        description="Number of cookie-backed retries used while enriching this post",
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


class AccountCookies(BaseModel):
    """Binds a Redis cookie payload to the account it came from."""

    account_id: str
    cookies: dict[str, str]
