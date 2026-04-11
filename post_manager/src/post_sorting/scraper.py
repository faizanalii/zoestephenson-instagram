"""
Scraper for fetching Instagram post data.
"""

from rnet import Client, Impersonate, Proxy, Version
from tenacity import retry
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_exponential

from src.post_sorting.utils import get_random_proxy


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=60))
async def get_post_page(post_url: str) -> str:
    """
    Get the Instagram Post page HTML content.
    Args:
        post_url (str): The URL of the Instagram post.
    Returns:
        str: The HTML content of the profile page.
    """

    proxy: str = await get_random_proxy()

    client = Client(
        impersonate=Impersonate.Chrome137,
        tls_info=True,
        proxies=[Proxy.all(url=proxy)] if proxy else None,
    )

    response_obj = await client.get(post_url, version=Version.HTTP_2, allow_redirects=True)

    response: str = await response_obj.text()

    return response
