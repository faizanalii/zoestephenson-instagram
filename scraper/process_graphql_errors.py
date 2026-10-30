"""Process graphql_errors posts using logged-in cookies (full comet body from HAR)."""
import asyncio
import json
import os
import sys
import time
import urllib.parse

from curl_cffi import requests as cffi
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")
from supabase import create_client

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

HAR_PATH = "../Debugging/server_error/www.instagram.com.har"
COOKIES_FILE = "../Debugging/cookies.json"
OUT_FILE = "graphql_errors_found_comments.json"


def shortcode_to_media_id(code):
    mid = 0
    for ch in code:
        mid = mid * 64 + ALPHABET.index(ch)
    return str(mid)


def extract_shortcode(url):
    path = url.split("?")[0].rstrip("/")
    return path.split("/")[-1]


def load_cookies(path):
    data = json.load(open(path))
    if isinstance(data, list):
        return {c["name"]: c["value"] for c in data}
    return data


def load_har_template():
    """Extract the full comet body + headers from the logged-in comments query."""
    har = json.load(open(HAR_PATH))
    target = None
    for e in har["log"]["entries"]:
        pd = e["request"].get("postData", {})
        text = pd.get("text", "") if isinstance(pd, dict) else ""
        if "PolarisPostCommentsPaginationQuery" in urllib.parse.unquote(text):
            target = e
            break
    if target is None:
        raise RuntimeError("No comments pagination query found in HAR")

    headers = {}
    for h in target["request"]["headers"]:
        n = h["name"]
        if n.startswith(":") or n in ("content-length", "cookie", "accept-encoding"):
            continue
        headers[n] = h["value"]

    body = target["request"]["postData"].get("text", "")
    params = dict(urllib.parse.parse_qsl(body, keep_blank_values=True))
    url = target["request"]["url"]
    return headers, params, url


def to_date(ts):
    if ts is None:
        return ""
    try:
        import datetime
        return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).date().isoformat()
    except Exception:
        return ""


def fetch_posts(limit=None):
    c = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    rows = []
    off = 0
    batch = 1000
    while True:
        r = (
            c.table("instagram_error_videos")
            .select("post_url", "error")
            .like("error", "graphql_errors%")
            .range(off, off + batch - 1)
            .execute()
        )
        if not r.data:
            break
        rows += r.data
        if len(r.data) < batch:
            break
        off += batch
    urls = sorted({r["post_url"] for r in rows})
    if limit:
        urls = urls[:limit]
    usernames = {}
    for i in range(0, len(urls), 100):
        rr = c.table("instagram").select("post_url", "username").in_("post_url", urls[i:i + 100]).execute()
        for row in rr.data:
            usernames[row["post_url"]] = row.get("username")
    return [{"post_url": u, "username": usernames.get(u)} for u in urls]


def query_page(session, headers, params_template, url, media_id, after):
    params = dict(params_template)
    params["variables"] = json.dumps(
        {
            "after": after,
            "before": None,
            "first": 50,
            "last": None,
            "media_id": media_id,
            "sort_order": "popular",
            "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True,
        }
    )
    params["doc_id"] = "28428885330094742"
    r = session.post(url, headers=headers, data=urllib.parse.urlencode(params), timeout=30)
    return r


def scrape_post(session, headers, params_template, url, post):
    post_url = post["post_url"]
    username = post["username"]
    code = extract_shortcode(post_url)
    try:
        media_id = shortcode_to_media_id(code)
    except Exception as exc:
        return {"status": "shortcode_error", "err": str(exc)[:100]}

    after = None
    for page in range(1, 300):
        try:
            r = query_page(session, headers, params_template, url, media_id, after)
        except Exception as exc:
            return {"status": "graphql_exception", "err": str(exc)[:150], "page": page}
        if r.status_code != 200:
            return {"status": "graphql_status", "status_code": r.status_code, "page": page}
        try:
            body = r.json()
        except Exception:
            return {"status": "invalid_json", "page": page}

        errs = body.get("errors")
        if errs:
            msgs = "; ".join(str(e.get("message", ""))[:90] for e in errs)
            return {"status": "graphql_errors", "err": msgs[:300], "page": page}

        conn = body.get("data", {}).get("xdt_api__v1__media__media_id__comments__connection", {})
        edges = conn.get("edges", [])
        page_info = conn.get("page_info", {})

        for ed in edges:
            node = ed.get("node", {})
            u = (node.get("user") or {}).get("username", "")
            if u and u.lower() == (username or "").lower():
                return {
                    "status": "found",
                    "username": u,
                    "text": node.get("text"),
                    "likes": node.get("comment_like_count", 0),
                    "reply_count": node.get("child_comment_count"),
                    "comment_id": str(node.get("pk")) if node.get("pk") else None,
                    "date": to_date(node.get("created_at")),
                }

        after_raw = page_info.get("end_cursor")
        has_next = page_info.get("has_next_page")
        if not has_next or not after_raw:
            return {"status": "not_found", "pages": page}
        after = after_raw
        time.sleep(0.2)

    return {"status": "depth_exhausted", "pages": 300}


async def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    cookies = load_cookies(COOKIES_FILE)
    headers, params_template, url = load_har_template()
    print("endpoint:", url)
    print("cookies:", sorted(cookies.keys()))

    posts = fetch_posts(limit=limit)
    print(f"posts to process: {len(posts)}")

    session = cffi.Session()
    for k, v in cookies.items():
        session.cookies.set(k, v)

    results = []
    t0 = time.time()
    for i, post in enumerate(posts, 1):
        try:
            res = scrape_post(session, headers, params_template, url, post)
        except Exception as exc:
            res = {"status": "exception", "err": str(exc)[:150]}
        res["post_url"] = post["post_url"]
        res["target_username"] = post["username"]
        results.append(res)
        flag = "FOUND" if res.get("status") == "found" else res.get("status", "?")
        print(f"[{i}/{len(posts)}] {flag:20} {post['username']}  {post['post_url'][:60]}")
        if res.get("status") == "found":
            print(f"           -> {res.get('text','')[:90]}")
        with open(OUT_FILE, "w") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        time.sleep(0.3)

    found = [r for r in results if r.get("status") == "found"]
    print("=" * 60)
    print(f"DONE in {time.time()-t0:.0f}s: {len(found)} found / {len(results)} total")
    print(f"saved to {OUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
