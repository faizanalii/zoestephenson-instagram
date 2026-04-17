from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, cast

from src.redis_client import get_redis_client
from src.settings import KEY_COOKIES_AVAILABLE


async def test_push_cookies_to_redis() -> None:
    """
    Push sample cookie payloads into Redis and verify they are present.
    """

    client = await get_redis_client()

    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    payloads = [
        {
            "account_id": f"test_account_{run_id}_1",
            "cookies": {
                "datr": "5OMeaePRlpjQPSm_vk7T9ceW",
                "ig_did": "05AFC37A-6314-46BC-BC40-6166AD73A2EE",
                "ig_nrcb": "1",
                "mid": "aSGKewAEAAFb-XKY1pWHmNFj5AW4",
                "ds_user_id": "59442049758",
                "ps_l": "1",
                "ps_n": "1",
                "csrftoken": "KrRiZBaA1BYYmu6mqTONbrXEHVtJTDlY",
                "wd": "1012x795",
                "rur": '"RVA\\05459442049758\\0541807950285:01fea810a69f67d771e29f792c603f88e85ce1d8cb6fdf39e3d93f28d4b97970623a4038"',
                "sessionid": "59442049758%3A7cu5PyTFKC61UO%3A25%3AAYjDLbLCaLXIq9piskPT0nk8PJeLVmTROhqfkUbasuA",
            },
        }
    ]

    for payload in payloads:
        client.rpush(KEY_COOKIES_AVAILABLE, json.dumps(payload))

    queue_items_result = client.lrange(KEY_COOKIES_AVAILABLE, 0, -1)
    if asyncio.iscoroutine(queue_items_result):
        queue_items = cast(list[Any], await queue_items_result)
    else:
        queue_items = cast(list[Any], queue_items_result)

    queue_items_text = [str(item) for item in queue_items]

    for payload in payloads:
        if json.dumps(payload) not in queue_items_text:
            raise AssertionError(
                f"Payload not found in Redis list: {payload['account_id']}"
            )

    print(
        f"Pushed {len(payloads)} cookie payloads to '{KEY_COOKIES_AVAILABLE}' and verified them."
    )


if __name__ == "__main__":
    asyncio.run(test_push_cookies_to_redis())
