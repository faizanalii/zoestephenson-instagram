"""
Scraper for fetching Instagram post data.
Uses rnet for HTTP/2 requests with Chrome TLS impersonation.
No cookies required — works against Instagram's public pages.
"""

from rnet import Client, Impersonate, Proxy, Version
from tenacity import retry, stop_after_attempt, wait_exponential


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=60))
async def get_post_page(post_url: str, proxy: str, cookies: dict[str, str] | None = None) -> str:
    """
    Get the Instagram post page HTML content.

    Args:
        post_url: The URL of the Instagram post/reel.
        proxy: The proxy URL to use for the request.
        cookies: Optional cookies dict. Defaults to None (no cookies needed).
    Returns:
        The HTML content of the page.
    """
    client = Client(
        impersonate=Impersonate.Chrome137,
        tls_info=True,
        proxies=[Proxy.all(url=proxy)] if proxy else None,
    )

    post_url = post_url.split("?")[0]

    if "/reel/" in post_url and "/reels/" not in post_url:
        post_url = post_url.replace("/reel/", "/reels/")

    response_obj = await client.get(
        post_url, version=Version.HTTP_2, allow_redirects=True, cookies=cookies or {}
    )

    if response_obj.status_code.as_int() != 200:
        raise Exception(
            f"Failed to fetch post page for {post_url}. Status code: {response_obj.status_code}"
        )

    response: str = await response_obj.text()

    return response


def _is_reel_url(post_url: str) -> bool:
    """
    Check if the given post URL is a reel URL.
    Args:
        post_url: The URL of the Instagram post to check.
    Returns:
        True if the URL is identified as a reel, False otherwise.
    """
    normalized = post_url.lower()
    return "/reel/" in normalized or "/reels/" in normalized
