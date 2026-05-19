"""Debug child-comments — try different variable combinations."""

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("debug")

from curl_cffi import requests

CSRF = "UFp-tqu8OD7YpTxGNctLGm"
APP_ID = "936619743392459"
LSD = "AdSTqCfBzghvK16smaCDQridjAw"
MEDIA_ID = "3844181034832854577_3233830524"
PARENT = "17920090185142904"
DOC_ID = "34884685271179117"
FRIENDLY = "PolarisPostChildCommentsQuery"


def try_request(label: str, variables: dict, extra_data: dict | None = None):
    data = {
        "av": "0",
        "__d": "www",
        "__user": "0",
        "__a": "1",
        "__req": "1a",
        "__comet_req": "7",
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": FRIENDLY,
        "server_timestamps": "true",
        "variables": json.dumps(variables),
        "doc_id": DOC_ID,
    }
    if LSD:
        data["lsd"] = LSD
    if extra_data:
        data.update(extra_data)

    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9,ur;q=0.8",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://www.instagram.com",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137.0.0.0 Safari/537.36",
        "x-csrftoken": CSRF,
        "x-fb-friendly-name": FRIENDLY,
        "x-ig-app-id": APP_ID,
    }
    if LSD:
        headers["x-fb-lsd"] = LSD

    resp = requests.post(
        "https://www.instagram.com/api/graphql",
        impersonate="chrome142",
        headers=headers,
        data=data,
        timeout=30,
    )
    body = resp.json() if resp.ok else {}
    errors = body.get("errors", [])
    data_block = body.get("data", {})

    edges_count = 0
    if isinstance(data_block, dict):
        for key, val in data_block.items():
            if isinstance(val, dict) and "edges" in val:
                edges_count = len(val["edges"])
            elif isinstance(val, dict):
                for sk, sv in val.items():
                    if isinstance(sv, dict) and "edges" in sv:
                        edges_count = len(sv["edges"])

    error_msg = errors[0].get("message", "")[:80] if errors else ""
    logger.info("  %s -> edges=%d errors=%s %s", label, edges_count, bool(errors), error_msg)
    return edges_count


async def main():
    base_vars = {
        "after": None,
        "before": None,
        "media_id": MEDIA_ID,
        "parent_comment_id": PARENT,
    }

    # Try different combinations
    try_request("base (just 4 vars)", base_vars)
    try_request("+first:50", {**base_vars, "first": 50})
    try_request("+first:50 +last:null", {**base_vars, "first": 50, "last": None})
    try_request("+relay_logged_in", {**base_vars, "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True})
    try_request("+page_size:20", {**base_vars, "page_size": 20})
    try_request("+fetch_comment_count", {**base_vars, "fetch_comment_count": 50})
    try_request("+first:10 +relay", {**base_vars, "first": 10, "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True})
    try_request("+first:50 +relay +sort", {**base_vars, "first": 50, "sort_order": "popular", "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True})
    try_request("+first:20 +relay ONLY", {"media_id": MEDIA_ID, "parent_comment_id": PARENT, "first": 20, "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True})
    try_request("+relay +first:10 +after:null +before:null", {"after": None, "before": None, "first": 10, "media_id": MEDIA_ID, "parent_comment_id": PARENT, "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True})

    # Try with a different doc_id
    logger.info("--- Testing different doc_ids ---")
    for doc_id_label, doc_id in [
        ("34884685271179117 (original)", "34884685271179117"),
        ("26224338453892885 (main pagination)", "26224338453892885"),
        ("26649248411374914 (reel container)", "26649248411374914"),
        ("25516980651312394 (reel comments)", "25516980651312394"),
    ]:
        data = {
            "av": "0",
            "__d": "www",
            "__user": "0",
            "__a": "1",
            "__req": "1a",
            "__comet_req": "7",
            "fb_api_caller_class": "RelayModern",
            "fb_api_req_friendly_name": FRIENDLY,
            "server_timestamps": "true",
            "variables": json.dumps({**base_vars, "first": 20, "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True}),
            "doc_id": doc_id,
        }
        if LSD:
            data["lsd"] = LSD

        resp = requests.post(
            "https://www.instagram.com/api/graphql",
            impersonate="chrome142",
            headers={
                "accept": "*/*",
                "accept-language": "en-US,en;q=0.9,ur;q=0.8",
                "content-type": "application/x-www-form-urlencoded",
                "origin": "https://www.instagram.com",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137.0.0.0 Safari/537.36",
                "x-csrftoken": CSRF,
                "x-fb-friendly-name": FRIENDLY,
                "x-ig-app-id": APP_ID,
                "x-fb-lsd": LSD,
            },
            data=data,
            timeout=30,
        )
        body = resp.json() if resp.ok else {}
        edges_count = 0
        data_block = body.get("data", {})
        if isinstance(data_block, dict):
            for key, val in data_block.items():
                if isinstance(val, dict) and "edges" in val:
                    edges_count = len(val["edges"])
        errors = body.get("errors", [])
        err = errors[0].get("message", "")[:80] if errors else "none"
        logger.info("  doc_id=%s -> edges=%d errors=%s", doc_id, edges_count, err)


if __name__ == "__main__":
    asyncio.run(main())
