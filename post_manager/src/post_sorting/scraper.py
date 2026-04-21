"""
Scraper for fetching Instagram post data.
"""

from rnet import Client, Impersonate, Proxy, Version
from tenacity import retry
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_exponential


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=60))
async def get_post_page(
    post_url: str,
    proxy: str | None = None,
    cookies: dict[str, str] | None = None,
) -> str:
    """
    Get the Instagram Post page HTML content.
    Args:
        post_url: The URL of the Instagram post.
        proxy: Optional proxy URL to use for the request.
        cookies: Optional Instagram cookie jar for authenticated requests.
    Returns:
        The HTML content of the profile page.
    """

    client = Client(
        impersonate=Impersonate.Chrome137,
        tls_info=True,
        proxies=[Proxy.all(url=proxy)] if proxy else None,
    )

    response_obj = await client.get(
        post_url.split("?")[0],
        version=Version.HTTP_2,
        allow_redirects=True,
        cookies=cookies,
    )

    if response_obj.status_code.as_int() != 200:
        raise RuntimeError(
            f"Failed to fetch post page for {post_url}. Status code: {response_obj.status_code}"
        )

    response: str = await response_obj.text()

    return response
