import os
import html
import requests


def get_existing_posts(site: dict, limit: int = 100) -> list[dict]:
    """Fetch existing post titles and URLs from LocalWP for internal linking."""
    wp_url = site["url"].rstrip("/")
    auth = (site["username"], site["app_password"])
    try:
        res = requests.get(
            f"{wp_url}/wp-json/wp/v2/posts",
            auth=auth,
            params={"per_page": limit, "status": "publish", "_fields": "title,link"},
            timeout=15,
        )
        res.raise_for_status()
        posts = []
        for item in res.json():
            raw_title = item.get("title", {}).get("rendered", "")
            link = item.get("link", "")
            if raw_title and link:
                posts.append({"title": html.unescape(raw_title), "link": link})
        return posts
    except Exception:
        return []


def upload_image(site: dict, image_path: str, alt_text: str = "") -> dict:
    """Upload a local image to LocalWP Media Library and attach SEO alt-text."""
    wp_url = site["url"].rstrip("/")
    auth = (site["username"], site["app_password"])
    filename = os.path.basename(image_path)

    with open(image_path, "rb") as f:
        media_res = requests.post(
            f"{wp_url}/wp-json/wp/v2/media",
            auth=auth,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": "image/png",
            },
            data=f.read(),
            timeout=45,
        )
    media_res.raise_for_status()
    data = media_res.json()
    media_id = data["id"]
    source_url = data["source_url"]

    if alt_text:
        requests.post(
            f"{wp_url}/wp-json/wp/v2/media/{media_id}",
            auth=auth,
            json={"alt_text": alt_text},
            timeout=15,
        )

    return {"id": media_id, "url": source_url}


def create_post(
    site: dict,
    title: str,
    html_content: str,
    status: str = "draft",
    featured_media_id: int | None = None,
    slug: str | None = None,
    excerpt: str | None = None,
) -> dict:
    """Create a post on LocalWP and return its ID and URL."""
    wp_url = site["url"].rstrip("/")
    auth = (site["username"], site["app_password"])

    payload = {
        "title": title,
        "content": html_content,
        "status": status,
    }
    if featured_media_id:
        payload["featured_media"] = featured_media_id
    if slug:
        payload["slug"] = slug
    if excerpt:
        payload["excerpt"] = excerpt

    res = requests.post(
        f"{wp_url}/wp-json/wp/v2/posts",
        auth=auth,
        json=payload,
        timeout=30,
    )
    res.raise_for_status()
    data = res.json()
    return {"id": data["id"], "link": data.get("link", "")}
