"""Collect ALL comments for a reel via cookie-free pagination."""
import asyncio
import json
import random
import sys
import time

from src.comment_scraper.post_page import get_post_page
from src.comment_scraper.utils import (
    PostPageParser,
    extract_general_errors,
    extract_rate_limit_error,
    get_comments,
    get_post_id,
    get_random_proxy,
    parse_page_info,
)
from src.comment_scraper.ig_query_client import run_graphql_query, PAGINATION_FRIENDLY_NAME

URL = "https://www.instagram.com/reel/DYiC0dKKlvU/?igsh=MW10cmI5dDhldHluag=="
USERNAMES = ["arladairyuk", "arlaprotein"]
OUT_FILE = "comments_dump_dyic0dkklvu.json"
MAX_PAGES = 600


def to_date(ts):
    if ts is None:
        return ""
    try:
        import datetime
        return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).date().isoformat()
    except Exception:
        return ""


async def main():
    proxy = await get_random_proxy()
    html = await get_post_page(post_url=URL, proxy=proxy)
    parser = PostPageParser()
    scripts = await parser.get_scripts_from_profile_page(html=html)
    header = await parser.get_header_data(json_scripts=scripts, html=html)
    payload = await parser.get_data_requirements(
        json_scripts=scripts, lsd_token=header.lsd_token, fb_dtsg=header.dtsg_token
    )
    post_id = await get_post_id(post_url=URL)
    doc_id = await parser.get_doc_id(
        friendly_name=PAGINATION_FRIENDLY_NAME, json_scripts=scripts, html=html
    )
    print(f"media_id={payload.media_id} doc_id={doc_id}", flush=True)

    all_comments = []
    seen_pks = set()
    cursor = payload.cursor
    hits = {}
    t0 = time.time()

    for page in range(1, MAX_PAGES + 1):
        try:
            resp = await run_graphql_query(
                csrf_token=header.csrf_token,
                app_id=header.app_id,
                media_id=payload.media_id,
                post_id=post_id or payload.media_id,
                cursor=cursor,
                proxy=await get_random_proxy(),
                lsd_token=payload.lsd_token,
                hmac_claim=header.hmac_claim,
                fb_dtsg=payload.fb_dtsg,
                doc_id=doc_id,
            )
        except Exception as exc:
            print(f"page {page}: QUERY EXCEPTION {type(exc).__name__}: {exc}", flush=True)
            await asyncio.sleep(random.uniform(3, 6))
            continue

        body = resp.json()

        if await extract_rate_limit_error(json_body=body):
            print(f"page {page}: RATE LIMIT — sleeping 45s", flush=True)
            await asyncio.sleep(45)
            continue

        errs = await extract_general_errors(json_body=body)
        if errs:
            print(f"page {page}: ERRORS {json.dumps(errs)[:300]}", flush=True)
            break

        comments = await get_comments(json_body=body)
        nxt, has_next = await parse_page_info(json_body=body)

        if not comments:
            print(f"page {page}: no comments (has_next={has_next})", flush=True)
            if not has_next:
                break
            cursor = nxt
            continue

        for c in comments:
            node = c.get("node", {})
            pk = node.get("pk")
            uname = node.get("user", {}).get("username", "")
            if pk and pk in seen_pks:
                continue
            seen_pks.add(pk)
            all_comments.append(
                {
                    "username": uname,
                    "text": node.get("text"),
                    "likes": node.get("comment_like_count", 0),
                    "reply_count": node.get("child_comment_count", 0),
                    "comment_id": str(pk) if pk else None,
                    "date": to_date(node.get("created_at")),
                }
            )
            if uname:
                hits[uname] = hits.get(uname, 0) + 1

        if page % 25 == 0 or not has_next:
            with open(OUT_FILE, "w") as f:
                json.dump(all_comments, f, ensure_ascii=False, indent=2)
            print(
                f"progress: page={page} collected={len(all_comments)} "
                f"elapsed={time.time()-t0:.0f}s has_next={has_next}",
                flush=True,
            )

        if not has_next or not nxt:
            print(f"page {page}: no next page — stopping", flush=True)
            break

        cursor = nxt
        await asyncio.sleep(random.uniform(0.3, 0.8))

    with open(OUT_FILE, "w") as f:
        json.dump(all_comments, f, ensure_ascii=False, indent=2)

    print("=" * 60, flush=True)
    print(f"TOTAL comments collected: {len(all_comments)}", flush=True)
    print(f"pages: {page}, elapsed: {time.time()-t0:.0f}s", flush=True)
    for u in USERNAMES:
        if u in hits:
            print(f"FOUND @{u}: {hits[u]} comment(s)", flush=True)
            for c in all_comments:
                if c["username"] == u:
                    print(f"   -> {c}", flush=True)
        else:
            print(f"@{u}: NOT FOUND", flush=True)
    print(f"saved to {OUT_FILE}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
