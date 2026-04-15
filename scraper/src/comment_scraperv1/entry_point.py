"""
Entry point for the comment scraper. This file is responsible for starting
the scraper and orchestrating the different components.
"""

import asyncio
import logging
import random
from typing import Any

from curl_cffi import requests

from src.models import AccountCookies, CommentStats, DataRequirements, HeaderRequirements, Post
from src.redis_client import (
    get_next_account_with_cookies,
)

from .ig_query_client import run_graphql_query
from .post_page import get_post_page
from .utils import (
    PostPageParser,
    classify_response,
    extract_rate_limit_error,
    get_comments,
    get_post_id,
    get_random_proxy,
    parse_page_info,
    search_comment,
)

# TODO: Need to update the locations of the
# Complete the flow of the comment extraction


async def find_comment(post: Post, source_queue: str) -> CommentStats | int | None:
    """
    Entry point that returns matching comment model or None for a post URL and username.
    Args:
        post: The Post object containing the URL and username to search comments for
        source_queue: Optional string indicating the source queue for logging and potential
    Returns:
        A CommentStats object if a matching comment is found, or None if not found or an
        error occurs.
    """

    # Check if the username exists in the first comments for the post

    comment: CommentStats | None = await search_comment(
        comments=post.first_comments, username=post.username, post_url=post.post_url
    )

    if comment:
        return comment

    # Get an account used for scraping
    account: AccountCookies | None = await get_next_account_with_cookies()

    # If the account cookies is not available, put the account again into the queue of task
    # and return None to trigger retry with exponential backoff
    if account is None:
        logging.warning(
            f"No account cookies available for scraping. Re-queuing"
            f" task for {post.post_url} and {post.username}."
        )

        # remove the URL from the processing queue to allow for retry in the future
        # await remove_url_from_processing_queue(post_url=post.post_url)

        # Push URL back to the source queue for retry, if source_queue is provided
        # await push_post_to_queue(post_job=post, queue_key=source_queue)

        # Optionally, implement logic to re-queue the task for retry with exponential backoff here
        return None

    logging.info(f"Using account {account.account_id} for scraping {post.post_url}")

    # Pull a random proxy for the request, use that proxy throughout the scraping
    proxy_url: str = await get_random_proxy()

    # Create the session
    session = requests.Session(impersonate="chrome146", proxy=proxy_url)
    # Add cookies to the session
    session.cookies.update(account.cookies)

    # If not found in the first comments, return None to trigger pagination fallback
    # Get the latest post page data for the post URL, which may include updated first comments
    # and pagination info
    post_page_data: str = await get_post_page(
        post_url=post.post_url, proxy=proxy_url, cookies=account.cookies
    )

    post_id: str | None = await get_post_id(post_url=post.post_url)

    # Page Parsing
    page_parser = PostPageParser()

    # Extract the scripts from the HTML Page

    json_scripts: list[dict[str, Any]] = await page_parser.get_scripts_from_profile_page(
        html=post_page_data
    )

    # Headers data for the API call
    header_data: HeaderRequirements = await page_parser.get_header_data(
        json_scripts=json_scripts, html=post_page_data
    )

    if not header_data.lsd_token or not header_data.dtsg_token:
        raise Exception("Missing required header tokens for pagination. Cannot proceed.")

    # Data Payload for the API
    payload_data: DataRequirements = await page_parser.get_data_requirements(
        json_scripts=json_scripts, lsd_token=header_data.lsd_token, fb_dtsg=header_data.dtsg_token
    )

    import pprint

    pprint.pprint(payload_data.cursor)

    index: int = 0

    # Extract all necessary fields for pagination from the page scripts and HTML
    while True:
        print("Doing pagination round:", index)

        try:
            api_response = await run_graphql_query(
                csrf_token=header_data.csrf_token,
                app_id=header_data.app_id,
                media_id=payload_data.media_id,
                post_id=post_id if post_id else payload_data.media_id,
                comment_cursor_bifilter_token=payload_data.cursor,
                cookies=account.cookies,
                session=session,
                proxy=proxy_url,
                lsd_token=payload_data.lsd_token,
                hmac_claim=header_data.hmac_claim,
                fb_dtsg=payload_data.fb_dtsg,
                include_requested_with=True,
            )
        except Exception:
            logging.error(
                f"GraphQL query failed for {post.post_url} with account {account.account_id}. Re-queuing task."
            )
            # TODO: Uncomment the below lines to enable re-queuing on GraphQL query failure, currently left commented for testing purposes
            # remove the URL from the processing queue to allow for retry in the future
            # await remove_url_from_processing_queue(post_url=post.post_url)
            # Push URL back to the source queue for retry, if source_queue is provided
            # await push_post_to_queue(post_job=post, queue_key=source_queue)

            return None

        # Classify the page response to determine if it's a valid JSON response, an HTML page (potentially a block or challenge),
        body_text = api_response.text
        content_type = api_response.headers.get("content-type")

        kind: str = await classify_response(api_response.status_code, content_type, body_text)

        extension: str = "json" if kind == "json" else "html"

        if kind == "json":
            # If it's a JSON response, parse the body and search for the comment
            json_body = api_response.json()
            with open(f"debug_response_{index}.json", "w", encoding="utf-8") as f:
                import json

                json.dump(json_body, f, indent=4)
            index += 1
            next_cursor, has_next_page = await parse_page_info(json_body=json_body)
            rate_limit_error = await extract_rate_limit_error(json_body=json_body)

            print(next_cursor)

            if rate_limit_error:
                print(f"Rate limit error details: {rate_limit_error}")
                logging.warning(
                    f"Rate limit error encountered for {post.post_url} with account {account.account_id}. "
                    f"Error details: {rate_limit_error}. Re-queuing task."
                )
                print(
                    "Sleeping for 30-60 seconds before retrying to avoid immediate rate limit hits..."
                )
                await asyncio.sleep(
                    random.uniform(30, 60)
                )  # Sleep for a random duration before retrying to avoid immediate rate limit hits
                # TODO: Wait for sometime and retry from where it left off, think of a
                # better way to handle this rather than re-queuing from the start
                continue

            else:
                comments = await get_comments(json_body=json_body)

                if not comments:
                    logging.info(f"No comments found in the response for {post.post_url}")
                    return None
                # TODO: If no comments found in the API response think of solution
                # Debug why it happened

                comment = await search_comment(
                    comments=comments, username=post.username, post_url=post.post_url
                )

                if comment:
                    return comment

                if not has_next_page:
                    logging.info(
                        f"No more pages to paginate for {post.post_url}. Ending pagination."
                    )
                    # TODO: If no next pages, mark the DB as record not exist
                    # Exit the loop and remove it from the processing queue
                    # await remove_url_from_processing_queue(post_url=post.post_url)

                    return None

                # Update the payload cursor for the next pagination request
                if next_cursor:
                    payload_data.cursor = next_cursor

                    await asyncio.sleep(
                        random.uniform(1, 3)
                    )  # Sleep for a short duration before the next request
                    # to avoid hitting rate limits

        elif kind == "html":
            logging.warning(
                f"Received HTML response for {post.post_url} with account {account.account_id}. "
                f"Content may indicate a block or challenge. Re-queuing task."
            )
            # TODO: Enable the Redis Processing
            # await remove_url_from_processing_queue(post_url=post.post_url)
            # await push_post_to_queue(post_job=post, queue_key=source_queue)
            with open(f"debug_{account.account_id}_{extension}", "w", encoding="utf-8") as f:
                f.write(body_text)

            return None
