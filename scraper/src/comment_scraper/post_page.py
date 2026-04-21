"""
Scraper for fetching Instagram post data.
"""

from rnet import Client, Impersonate, Proxy, Version
from tenacity import retry
from tenacity.stop import stop_after_attempt
from tenacity.wait import wait_exponential


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=60))
async def get_post_page(post_url: str, proxy: str, cookies: dict[str, str]) -> str:
    """
    Get the Instagram Post page HTML content.
    Args:
        post_url (str): The URL of the Instagram post.
        proxy (str): The proxy URL to use for the request.
    Returns:
        str: The HTML content of the profile page.
    """

    client = Client(
        impersonate=Impersonate.Chrome137,
        tls_info=True,
        proxies=[Proxy.all(url=proxy)] if proxy else None,
    )

    # Remove the query parameters from the post URL to avoid issues with fetching the page
    post_url = post_url.split("?")[0]

    response_obj = await client.get(
        post_url, version=Version.HTTP_2, allow_redirects=True, cookies=cookies
    )

    if response_obj.status_code.as_int() != 200:
        raise Exception(
            f"Failed to fetch post page for {post_url}. Status code: {response_obj.status_code}"
        )

    response: str = await response_obj.text()

    return response
