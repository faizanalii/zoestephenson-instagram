"""
Test Comment
"""

from src.comment_scraperv1 import find_comment
from src.models import Post


async def test_find_comment():
    """
    Test the find_comment function with a sample post URL and username.
    """

    post: Post = Post(
        post_url="https://www.instagram.com/p/DWte0fylh5b",
        username="khoun.toy",
        media_id="3867883203923943003",
        hmac_claim="hmac_ttl.1776238048.AR0ehsDmXD7p6Y1tF0zqHAiWFeGoo2-7GA8h-Irp85jISUD6",
        comment_count=1764,
        has_next_comments=True,
        post_exists=True,
        first_comments=[],
    )

    result = await find_comment(post=post, source_queue="instagram:240")

    print(result)


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_find_comment())
